using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// EgoAnchor 静态锚定稳定器 (纯 C# 控制器, 无 MonoBehaviour)。
    ///
    /// 这是 EgoAnchor 方法的核心 —— 不是又一个滤波器, 而是建立在 baseline (MotionModel ×
    /// SmoothingStrategy) 之上的 **score-gated 分区静止锁定控制层**。被锚定的真实物体绝大多数
    /// 时间是静止的 (动的是头显, 噪的是观测: 帧对齐残差 + 深度噪声 + head-motion slip)。
    /// baseline 都是 motion-agnostic 滤波器, 静止时残留抖动; 本控制器显式锁定静止 pose, 把
    /// 小幅抖动当噪声吸收 → 抖动 ≈ 0 ("看上去一动不动"), 运动时交回 smoothing 输出。
    ///
    /// 设计已在离线仿真 (EgoAnchor_Tools3 EgoAnchorStabilizerPredictor) 验证: 静止段
    /// P50 位置步长 0.115mm→0.000mm, 冻结帧 9%→63%; 运动跟踪不退化 (lag 不变), 代价是
    /// 运动起始响应 +~110ms 中位延迟。关键机制:
    ///   1. 死区 (deadband): 锁定时位移在死区内 → 忽略 (噪声地板, 杀静止抖动的核心);
    ///   2. score 加权 CUSUM: E += score·max(0,|Δ|−deadband), 每观测衰减。高分持续位移 → 解锁;
    ///      低分远跳 → 权重小被压住 (软 score 门, 不是硬阈值);
    ///   3. 速度逃逸: 观测速度明确超阈连续若干帧 → 立即解锁 (堵 CUSUM 跟不上的 false-lock 长尾);
    ///   4. 漏锁 creep: 锁定时极小增益朝高分小位移 creep (精修锁点 + 跟极慢漂移);
    ///   5. 反 chatter: 解锁后若干观测内禁止再锁 (否则锁定 churn, 接缝污染抵消收益);
    ///   6. 接缝过渡: 解锁瞬间记录 lockedPose ⊖ candidate 的残差, 之后逐帧融合收敛到 candidate, 防 pop。
    ///
    /// 位置/旋转独立证据通道 (静止物体的角度摇摆视觉上最刺眼)。所有阈值由 host 注入, 速度阈值
    /// 是物理量、与帧率无关 (符合项目"不硬编码帧率"惯例)。
    ///
    /// 用法 (host 每帧):
    ///   - 收到观测: <see cref="OnObservation"/> (传入 world pose + score, 内部更新静/动证据);
    ///   - 每渲染帧: <see cref="Stabilize"/> (传入 smoothing 输出的 candidate pose + dt, 返回这一帧
    ///     应输出的锚定 pose —— 锁定时为 lockedPose, 解锁过渡时为 candidate⊕衰减残差, 否则为 candidate)。
    /// </summary>
    public sealed class StaticLockController
    {
        // === 参数 (host 注入) ===
        // 时间量纲均为帧率无关 (秒 / 半衰期秒)。速度阈值是物理量, 与帧率无关。
        private float staticEnterSpeedMps = 0.05f;
        private float staticEnterAngSpeedDps = 35.0f;
        private float staticDwellSeconds = 0.35f;
        private float staticEnterMinScore = 0.25f;
        private float deadbandMeters = 0.008f;
        private float deadbandDegrees = 3.0f;
        private float unlockEvidenceMeters = 0.08f;
        private float unlockEvidenceDegrees = 20.0f;
        private float unlockDriftMeters = 0.015f;     // 绝对漂移租绳: 相对锁定原点平移超此 → 解锁 (修慢速平移不脱离)
        private float unlockDriftDegrees = 5.0f;
        private float evidenceHalfLifeSeconds = 0.27f;
        private float creepHalfLifeSeconds = 2.7f;
        private float relockSuppressSeconds = 1.0f;
        private float unlockSpeedFactor = 2.5f;
        private float unlockMovingSeconds = 0.4f;
        private float seamDecayPerFrame = 0.85f;
        private float refObsIntervalSeconds = 0.2f; // CUSUM 累积时间归一基准

        // 头动感知 (问题3): 头转/平移时 head-motion-induced slip 抬高观测物体表观运动,
        // 静止物体被误判 moving → 误解锁 → anchor 跟头抖。头动越大→临时按比例放大 static 容忍度
        // (死区/漂移租绳/速度逃逸阈值), 吸收 slip; 头静止时回到原阈值 (物体真动才解锁)。
        private float headRotForFullToleranceDps = 60.0f; // 头角速度达此值 → 容忍因子吃满
        private float headLinForFullToleranceMps = 0.3f;  // 头线速度达此值 → 容忍因子吃满
        private float headMaxToleranceFactor = 4.0f;      // 容忍度上限 (1=关闭头动感知)

        // 距离自适应位置容忍 (问题2): 物体越远, 立体深度估计噪声越大 (~z², 离线证实 corr(距离, 位置抖动)=+0.23;
        // 旋转抖动与距离无关 corr≈-0.02, 故只缩放位置通道, 旋转阈值不变)。同样真实静止, 远处观测位置抖得更大 →
        // 固定米死区/租绳在远处频繁被噪声顶破 → 误解锁。解法: 位置死区与位置租绳乘
        // posDistanceFactor = clamp(1 + slope·(dist−ref), 1, max), dist=物体到头部距离。ref 以内不放大 (近处不动)。
        private float posToleranceRefDistanceMeters = 0.4f;   // 此距离以内位置容忍不放大 (factor=1)
        private float posToleranceDistanceSlope = 1.0f;       // 每超出 ref 1m, 位置容忍增加比例 (1/m)
        private float posToleranceMaxFactor = 3.0f;           // 位置容忍放大上限 (1=关闭距离自适应)

        // 低分释放 (问题1): 锁定时若 score 持续低于阈值, 锁点已不可信 (物体可能被移走/遮挡/跟丢),
        // 强制解锁, 不让 anchor 冻在错误 pose 上 (否则用户得手动移出视野再回来)。解锁后交回 coasting,
        // 配合 PoseToAnchorRuntime 的低分自动 reacquire。0=关闭该机制。
        private float lowScoreReleaseScore = 0.3f;        // 低于此分视为不可信
        private float lowScoreReleaseSeconds = 0.6f;      // 持续低分多久后强制解锁

        // === 运行时状态 ===
        private bool locked;
        private Pose lockedPose;
        private Pose anchorOrigin;                     // 锁定时固定锚点 (creep 不动), 绝对漂移租绳参考
        private float evidencePos;
        private float evidenceRot;
        private float staticRunSeconds;
        private float relockSuppressLeftSeconds;
        private float movingRunSeconds;
        private bool wantUnlock;                        // UpdateLockedEvidence 累积判定, Stabilize 提交 (拿 candidate 做接缝)

        // obs-to-obs 速度跟踪
        private bool hasLastObs;
        private Vector3 lastObsPos;
        private Quaternion lastObsRot;
        private double lastObsTime;
        private bool hasSpeedEma;
        private float obsSpeedEma;
        private float obsAngSpeedEma;

        // 解锁接缝残差
        private bool seamActive;
        private Vector3 seamPos;
        private Vector3 seamRot; // 切空间向量 (rad)

        // 头动跟踪 (从 host 注入的 HMD/CenterEye world pose 差分)
        private bool hasLastHead;
        private Vector3 lastHeadPos;
        private Quaternion lastHeadRot;
        private float headLinSpeedEma;   // m/s
        private float headAngSpeedEma;   // deg/s
        private float headToleranceFactor = 1.0f; // 当前头动放大系数 (1=头静止)
        private float posDistanceFactor = 1.0f;    // 当前距离自适应位置容忍系数 (问题2; 1=近处/关闭)
        private float lowScoreRunSeconds;          // 锁定时连续低分累计时间 (低分释放用)

        /// <summary>当前是否锁定 (供 host 写 eval 的 latest_static_locked)。</summary>
        public bool IsLocked => locked;

        /// <summary>累计锁定进入次数 (诊断)。</summary>
        public int LockEnters { get; private set; }

        /// <summary>累计解锁次数 (诊断)。</summary>
        public int Unlocks { get; private set; }

        /// <summary>用 host 的参数配置控制器 (Inspector 可能改, 每次激活时调用)。时间量纲均帧率无关。</summary>
        public void Configure(
            float staticEnterSpeedMps,
            float staticEnterAngSpeedDps,
            float staticDwellSeconds,
            float staticEnterMinScore,
            float deadbandMeters,
            float deadbandDegrees,
            float unlockEvidenceMeters,
            float unlockEvidenceDegrees,
            float unlockDriftMeters,
            float unlockDriftDegrees,
            float evidenceHalfLifeSeconds,
            float creepHalfLifeSeconds,
            float relockSuppressSeconds,
            float unlockSpeedFactor,
            float unlockMovingSeconds,
            float seamDecayPerFrame,
            float refObsIntervalSeconds,
            float headRotForFullToleranceDps,
            float headLinForFullToleranceMps,
            float headMaxToleranceFactor,
            float posToleranceRefDistanceMeters,
            float posToleranceDistanceSlope,
            float posToleranceMaxFactor,
            float lowScoreReleaseScore,
            float lowScoreReleaseSeconds)
        {
            this.staticEnterSpeedMps = Mathf.Max(staticEnterSpeedMps, 0.0f);
            this.staticEnterAngSpeedDps = Mathf.Max(staticEnterAngSpeedDps, 0.0f);
            this.staticDwellSeconds = Mathf.Max(staticDwellSeconds, 0.0f);
            this.staticEnterMinScore = Mathf.Clamp01(staticEnterMinScore);
            this.deadbandMeters = Mathf.Max(deadbandMeters, 0.0f);
            this.deadbandDegrees = Mathf.Max(deadbandDegrees, 0.0f);
            this.unlockEvidenceMeters = Mathf.Max(unlockEvidenceMeters, 0.0f);
            this.unlockEvidenceDegrees = Mathf.Max(unlockEvidenceDegrees, 0.0f);
            this.unlockDriftMeters = Mathf.Max(unlockDriftMeters, 0.0f);
            this.unlockDriftDegrees = Mathf.Max(unlockDriftDegrees, 0.0f);
            this.evidenceHalfLifeSeconds = Mathf.Max(evidenceHalfLifeSeconds, 1e-3f);
            this.creepHalfLifeSeconds = Mathf.Max(creepHalfLifeSeconds, 1e-3f);
            this.relockSuppressSeconds = Mathf.Max(relockSuppressSeconds, 0.0f);
            this.unlockSpeedFactor = Mathf.Max(unlockSpeedFactor, 1.0f);
            this.unlockMovingSeconds = Mathf.Max(unlockMovingSeconds, 0.0f);
            this.seamDecayPerFrame = Mathf.Clamp(seamDecayPerFrame, 0.5f, 0.99f);
            this.refObsIntervalSeconds = Mathf.Max(refObsIntervalSeconds, 1e-3f);
            this.headRotForFullToleranceDps = Mathf.Max(headRotForFullToleranceDps, 1e-3f);
            this.headLinForFullToleranceMps = Mathf.Max(headLinForFullToleranceMps, 1e-3f);
            this.headMaxToleranceFactor = Mathf.Max(headMaxToleranceFactor, 1.0f);
            this.posToleranceRefDistanceMeters = Mathf.Max(posToleranceRefDistanceMeters, 0.0f);
            this.posToleranceDistanceSlope = Mathf.Max(posToleranceDistanceSlope, 0.0f);
            this.posToleranceMaxFactor = Mathf.Max(posToleranceMaxFactor, 1.0f);
            this.lowScoreReleaseScore = Mathf.Clamp01(lowScoreReleaseScore);
            this.lowScoreReleaseSeconds = Mathf.Max(lowScoreReleaseSeconds, 0.0f);
        }

        /// <summary>清空所有状态。</summary>
        public void Reset()
        {
            locked = false;
            lockedPose = Pose.identity;
            anchorOrigin = Pose.identity;
            evidencePos = 0.0f;
            evidenceRot = 0.0f;
            staticRunSeconds = 0.0f;
            relockSuppressLeftSeconds = 0.0f;
            movingRunSeconds = 0.0f;
            wantUnlock = false;
            hasLastObs = false;
            lastObsPos = Vector3.zero;
            lastObsRot = Quaternion.identity;
            lastObsTime = 0.0;
            hasSpeedEma = false;
            obsSpeedEma = 0.0f;
            obsAngSpeedEma = 0.0f;
            seamActive = false;
            seamPos = Vector3.zero;
            seamRot = Vector3.zero;
            hasLastHead = false;
            lastHeadPos = Vector3.zero;
            lastHeadRot = Quaternion.identity;
            headLinSpeedEma = 0.0f;
            headAngSpeedEma = 0.0f;
            headToleranceFactor = 1.0f;
            posDistanceFactor = 1.0f;
            lowScoreRunSeconds = 0.0f;
            LockEnters = 0;
            Unlocks = 0;
        }

        /// <summary>
        /// 收到一帧被接受的观测时调用 (host 在 motionModel 更新后)。
        /// 更新 obs-to-obs 速度、头动容忍系数、静/动 dwell 计数; 锁定中则累积解锁证据。
        /// </summary>
        /// <param name="worldPose">frame-aligned world pose (= 进 motion model 的同一 pose)。</param>
        /// <param name="score">该观测可靠性分数 0..1。</param>
        /// <param name="measurementTimeSeconds">观测测量时间 (capture 时间)。</param>
        /// <param name="hasHeadPose">是否提供了头部 (HMD/CenterEye) world pose。</param>
        /// <param name="headPose">头部 world pose; 用于头动感知放宽 static 约束 (问题3)。</param>
        public void OnObservation(in Pose worldPose, float score, double measurementTimeSeconds, bool hasHeadPose = false, Pose headPose = default)
        {
            Vector3 pos = worldPose.position;
            Quaternion rot = worldPose.rotation;

            // 本次观测相对上一观测的真实时间间隔 (秒); 首帧为 0。dwell/suppress 累积按它走, 帧率无关。
            float obsDt = hasLastObs ? Mathf.Max((float)(measurementTimeSeconds - lastObsTime), 0.0f) : 0.0f;

            if (hasLastObs)
            {
                float dt = Mathf.Max(obsDt, 1e-3f);
                float speed = Vector3.Distance(pos, lastObsPos) / dt;
                float angSpeed = AnchorMath.AngleDegrees(lastObsRot, rot) / dt;
                if (hasSpeedEma)
                {
                    obsSpeedEma += 0.5f * (speed - obsSpeedEma);
                    obsAngSpeedEma += 0.5f * (angSpeed - obsAngSpeedEma);
                }
                else
                {
                    obsSpeedEma = speed;
                    obsAngSpeedEma = angSpeed;
                    hasSpeedEma = true;
                }
            }

            // 头动感知 (问题3): 从 head pose 差分头速, 更新容忍放大系数。头动越大→放宽 static 约束吸收 slip。
            UpdateHeadMotion(hasHeadPose, headPose, obsDt);

            // 距离自适应位置容忍 (问题2): 物体越远立体深度噪声越大, 位置容忍按距离放大 (旋转不放大)。
            posDistanceFactor = ComputePosDistanceFactor(hasHeadPose, headPose, pos);

            float f = headToleranceFactor;
            bool isStatic = obsSpeedEma <= staticEnterSpeedMps * f
                            && obsAngSpeedEma <= staticEnterAngSpeedDps * f
                            && score >= staticEnterMinScore;

            if (locked)
            {
                UpdateLockedEvidence(pos, rot, score, obsDt);
            }
            else if (relockSuppressLeftSeconds > 0.0f)
            {
                relockSuppressLeftSeconds -= obsDt;
                staticRunSeconds = 0.0f;
            }
            else
            {
                staticRunSeconds = isStatic ? staticRunSeconds + obsDt : 0.0f;
            }

            hasLastObs = true;
            lastObsPos = pos;
            lastObsRot = rot;
            lastObsTime = measurementTimeSeconds;
        }

        /// <summary>
        /// 距离自适应位置容忍系数 (问题2): factor = clamp(1 + slope·(dist − ref), 1, max),
        /// dist = 观测物体到头部的距离。ref 以内 (近处) factor=1 不放大; 越远越大, max 封顶。
        /// 无头部 pose 或功能关闭 (max≤1) → 返回 1。只缩放位置通道, 旋转不受影响。
        /// </summary>
        private float ComputePosDistanceFactor(bool hasHeadPose, in Pose headPose, Vector3 objectPos)
        {
            if (!hasHeadPose || posToleranceMaxFactor <= 1.0f)
            {
                return 1.0f;
            }

            float dist = Vector3.Distance(objectPos, headPose.position);
            float factor = 1.0f + posToleranceDistanceSlope * (dist - posToleranceRefDistanceMeters);
            return Mathf.Clamp(factor, 1.0f, posToleranceMaxFactor);
        }

        /// <summary>从 head pose obs-to-obs 差分头部角/线速度, 更新头动容忍放大系数 headToleranceFactor。</summary>
        private void UpdateHeadMotion(bool hasHeadPose, in Pose headPose, float obsDt)
        {
            if (!hasHeadPose || headMaxToleranceFactor <= 1.0f)
            {
                headToleranceFactor = 1.0f; // 无头部数据或功能关闭 → 不放大
                return;
            }

            if (hasLastHead && obsDt > 1e-4f)
            {
                float linSpeed = Vector3.Distance(headPose.position, lastHeadPos) / obsDt;
                float angSpeed = AnchorMath.AngleDegrees(lastHeadRot, headPose.rotation) / obsDt;
                headLinSpeedEma += 0.5f * (linSpeed - headLinSpeedEma);
                headAngSpeedEma += 0.5f * (angSpeed - headAngSpeedEma);
            }
            hasLastHead = true;
            lastHeadPos = headPose.position;
            lastHeadRot = headPose.rotation;

            float ratio = Mathf.Max(headAngSpeedEma / headRotForFullToleranceDps, headLinSpeedEma / headLinForFullToleranceMps);
            ratio = Mathf.Clamp01(ratio);
            headToleranceFactor = 1.0f + ratio * (headMaxToleranceFactor - 1.0f);
        }

        /// <summary>
        /// 每渲染帧调用。传入 smoothing 策略输出的 candidate pose, 返回这一帧应输出的锚定 pose:
        ///   - 锁定: lockedPose (完全冻结);
        ///   - 解锁过渡: candidate ⊕ 衰减残差 (从 lockedPose 平滑收敛到 candidate, 防 pop);
        ///   - 自由: candidate。
        /// </summary>
        /// <param name="candidatePose">smoothing 策略本帧输出。</param>
        /// <param name="dtSeconds">距上一渲染帧的时间 (秒), 用于接缝残差按 60fps 基准衰减。</param>
        public Pose Stabilize(in Pose candidatePose, float dtSeconds)
        {
            if (locked)
            {
                if (ShouldUnlock())
                {
                    Unlock(candidatePose);
                }
                else
                {
                    return lockedPose;
                }
            }
            else if (staticRunSeconds >= staticDwellSeconds)
            {
                EnterLock(candidatePose);
                return lockedPose;
            }

            if (seamActive)
            {
                return ApplySeam(candidatePose, dtSeconds);
            }

            return candidatePose;
        }

        private bool ShouldUnlock()
        {
            return wantUnlock;
        }

        private void EnterLock(in Pose candidatePose)
        {
            locked = true;
            LockEnters++;
            lockedPose = candidatePose; // 锚到当前 candidate, C⁰ 连续无 pop
            anchorOrigin = candidatePose; // 固定锚点 (creep 不动), 绝对漂移租绳参考
            evidencePos = 0.0f;
            evidenceRot = 0.0f;
            movingRunSeconds = 0.0f;
            wantUnlock = false;
            seamActive = false;
            seamPos = Vector3.zero;
            seamRot = Vector3.zero;
        }

        private void Unlock(in Pose candidatePose)
        {
            locked = false;
            Unlocks++;
            wantUnlock = false;
            staticRunSeconds = 0.0f;
            relockSuppressLeftSeconds = relockSuppressSeconds;
            movingRunSeconds = 0.0f;
            // 接缝残差 = lockedPose ⊖ candidate, 让输出从 lockedPose 起、逐帧收敛到 candidate。
            seamPos = lockedPose.position - candidatePose.position;
            seamRot = AnchorMath.RelativeRotationLog(candidatePose.rotation, lockedPose.rotation);
            seamActive = seamPos.magnitude > 1e-5f || seamRot.magnitude > 1e-5f;
        }

        private Pose ApplySeam(in Pose candidatePose, float dtSeconds)
        {
            Vector3 pos = candidatePose.position + seamPos;
            Quaternion rot = AnchorMath.Multiply(candidatePose.rotation, AnchorMath.Exp(seamRot));

            float frames = Mathf.Max(dtSeconds, 0.0f) * 60.0f;
            float decay = Mathf.Pow(seamDecayPerFrame, frames);
            seamPos *= decay;
            seamRot *= decay;
            if (seamPos.magnitude < 1e-5f && seamRot.magnitude < 1e-5f)
            {
                seamActive = false;
            }

            return new Pose(pos, rot);
        }

        /// <summary>锁定时: 速度逃逸 + 死区吸收 + score 加权 CUSUM + 漏锁 creep。全部按真实 dt, 帧率无关。</summary>
        private void UpdateLockedEvidence(Vector3 pos, Quaternion rot, float score, float obsDt)
        {
            // 头动放大系数 (头静止=1)。头动时所有"判物体在动→解锁"的阈值同比放大, 把 head-slip 当噪声吸收 (问题3)。
            float f = headToleranceFactor;

            // 低分释放 (问题1): 锁定时持续低分 → 锁点不可信 (物体被移走/遮挡/跟丢), 强制解锁,
            // 不让 anchor 冻在错 pose 上。解锁后交回 coasting + 由 PoseToAnchorRuntime 低分 reacquire。
            if (lowScoreReleaseSeconds > 0.0f && score < lowScoreReleaseScore)
            {
                lowScoreRunSeconds += obsDt;
                if (lowScoreRunSeconds >= lowScoreReleaseSeconds)
                {
                    wantUnlock = true;
                    return; // 解锁在 Stabilize 提交
                }
            }
            else
            {
                lowScoreRunSeconds = 0.0f;
            }

            // 速度逃逸: 速度明确超阈连续一段 *时间* → 解锁 (速度比位移更早的运动信号, 堵 false-lock 长尾)。
            // 头动时阈值放大: 头转带来的 slip 速度不该触发逃逸。
            bool movingNow = obsSpeedEma > staticEnterSpeedMps * unlockSpeedFactor * f
                             || obsAngSpeedEma > staticEnterAngSpeedDps * unlockSpeedFactor * f;
            movingRunSeconds = movingNow ? movingRunSeconds + obsDt : 0.0f;
            if (movingRunSeconds >= unlockMovingSeconds)
            {
                wantUnlock = true;
                return; // 解锁在 Stabilize 提交 (此刻才有 candidate 做接缝)
            }

            // 绝对漂移租绳: 相对锁定时固定的 anchorOrigin (creep 不动) 的总漂移超租绳 → 解锁。
            // 关键: 漂移用 *creep 后的 lockedPose* (去噪共识) 度量, 不用单帧原始观测 pos/rot。
            //   原始观测噪声大 (本数据集静止物体旋转噪声 p90~13°、平移 p90~30mm, 远超 5°/15mm 租绳),
            //   若直接拿原始观测度量, 头静止 (f=1) 时单帧噪声尖峰就频繁误触发解锁 → 锚点"漂一小段又被拉回"的抖动
            //   (用户报告的现象: 物体不动头转时轻微抖动)。lockedPose 只在死区内经 creep 缓慢移动, 对单帧噪声免疫;
            //   而真实持续漂移会被 creep 如实跟随、累计够远仍顶破租绳, 因此"极慢平移逃逸"能力保持不变。
            // 头动时租绳放大: 头转造成的 world-pose slip 漂移不该触发解锁; 头静止时回原租绳, 真实慢移正常逃逸。
            // 位置租绳再乘 posDistanceFactor (问题2): 远处深度噪声大, 位置租绳同比放宽; 旋转租绳不随距离变 (旋转噪声与距离无关)。
            float driftPos = Vector3.Distance(lockedPose.position, anchorOrigin.position);
            float driftRot = AnchorMath.AngleDegrees(anchorOrigin.rotation, lockedPose.rotation);
            if (driftPos > unlockDriftMeters * f * posDistanceFactor || driftRot > unlockDriftDegrees * f)
            {
                wantUnlock = true;
                return; // 解锁在 Stabilize 提交
            }

            float dPos = Vector3.Distance(pos, lockedPose.position);
            float dRot = AnchorMath.AngleDegrees(lockedPose.rotation, rot);

            // CUSUM (帧率无关): 每观测先按真实 dt 做半衰期衰减 (漏积分), 再累积"超死区"部分,
            // 累积量乘 (obsDt / refObsIntervalSeconds), 使同样的持续运动在任何帧率下单位时间攒到的证据相同。
            // 死区随头动放大: 头转时观测抖动大, 死区放宽吸收 slip; 头静止时回到原死区。
            // 位置死区再乘 posDistanceFactor (问题2): 远处位置噪声大, 位置死区同比放宽; 旋转死区不随距离变。
            float dbMeters = deadbandMeters * f * posDistanceFactor;
            float dbDegrees = deadbandDegrees * f;
            float decay = Mathf.Pow(0.5f, obsDt / evidenceHalfLifeSeconds);
            float accScale = obsDt / refObsIntervalSeconds;
            evidencePos = decay * evidencePos + accScale * score * Mathf.Max(0.0f, dPos - dbMeters);
            evidenceRot = decay * evidenceRot + accScale * score * Mathf.Max(0.0f, dRot - dbDegrees);

            if (evidencePos > unlockEvidenceMeters || evidenceRot > unlockEvidenceDegrees)
            {
                wantUnlock = true;
                return; // 解锁在 Stabilize 提交
            }

            // 漏锁 creep: 仅死区内 (纯噪声/极慢漂移) 才朝观测缓慢靠拢, 精修锁点 + 跟极慢漂移而不抖。
            // creep 增益按真实 dt 的半衰期换算, 与帧率无关。
            if (dPos < dbMeters && dRot < dbDegrees)
            {
                float g = (1.0f - Mathf.Pow(0.5f, obsDt / creepHalfLifeSeconds)) * score;
                Vector3 newPos = lockedPose.position + (pos - lockedPose.position) * g;
                Quaternion newRot = Quaternion.Slerp(lockedPose.rotation, rot, g);
                lockedPose = new Pose(newPos, AnchorMath.Normalize(newRot));
            }
        }
    }
}
