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
    ///   4. 绝对漂移租绳: 观测共识 (obsConsensus, denoised EMA) 相对锁定时刻共识 (anchorOrigin) 的总漂移
    ///      超租绳 → 解锁 (堵慢速持续平移这种死区内/速度阈下、CUSUM 又跟不上的长尾; 量去噪共识而非
    ///      creep 后的 lockedPose, 否则慢移时 creep 停摆会把 driftPos 钉死在 0 → 慢移永不解锁);
    ///   5. 漏锁 creep: 锁定时极小增益朝高分小位移 creep (精修锁点 + 跟极慢漂移);
    ///   6. 反 chatter: 解锁后若干观测内禁止再锁 (否则锁定 churn, 接缝污染抵消收益);
    ///   7. 接缝过渡: 解锁瞬间记录 lockedPose ⊖ candidate 的残差, 之后逐帧融合收敛到 candidate, 防 pop。
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

        // 头停沉降冻结 (问题3 续): 头动时 slip 累进 obsConsensus / 抬高观测速度; 头一停, headToleranceFactor
        // 由头速驱动会几乎瞬间塌回 1 (阈值收紧), 但 obsConsensus 携带的 slip 要按 evidenceHalfLifeSeconds 才褪去
        // → 出现"阈值已收紧、slip 未褪净"的窗口 → 漂移租绳/CUSUM/速度逃逸误触发 (用户报告: 头一停物体就脱离 static)。
        // 解法: 头动期间 + 头停后 headSettleSeconds 内, 冻结所有"判物体在动→解锁"的证据 (漂移租绳/CUSUM/速度逃逸),
        // 给 obsConsensus 时间把 slip 褪干净再恢复监测。settleSeconds 取 ~2~3× evidenceHalfLifeSeconds。
        // 0=关闭沉降冻结。低分释放不冻结 (它是独立可靠性信号, 与 head-slip 无关)。
        private float headSettleSeconds = 0.6f;            // 头停后冻结解锁判定的时长 (秒, 帧率无关; 0=关闭)
        private const float HeadMovingRatioEps = 0.06f;    // headMotionRatio 超此值视为"头在动" (重置沉降计时)

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
        private Pose anchorOrigin;                     // 锁定时刻的*观测共识* (denoised, 不动), 绝对漂移租绳参考。
                                                       // 注意: 不是 candidate/lockedPose —— 见 obsConsensus 说明与 UpdateLockedEvidence 租绳计算。
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

        // 观测共识 (denoised, 死区无关): 对被接受观测做低增益 EMA, 平滑掉单帧噪声/head-slip 尖峰,
        // 但*如实跟随*真实持续位移 (与 creep 不同, 不受死区门控)。绝对漂移租绳用它相对 anchorOrigin
        // (= 锁定时刻的共识) 度量真实漂移, 修复"慢移时观测超死区→creep 停摆→lockedPose 钉死→租绳恒为 0
        // →慢移永不解锁"的结构性失效。EMA 平滑 + headToleranceFactor 放大保留对头转抖动 (问题3) 的免疫。
        private bool hasObsConsensus;
        private Vector3 obsConsensusPos;
        private Quaternion obsConsensusRot;

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
        private float headMotionRatio;             // 头动强度 0..1 (0=头静止, 1=头速达满容忍阈值)。门控 creep: 头动时减弱/冻结 creep, 防 head-slip 偏置被 creep 单向累积成锁点漂移。
        private float headSettleLeftSeconds;       // 头停沉降冻结剩余时间 (秒)。头在动时重置满, 头静止时递减; >0 期间冻结解锁判定 (漂移租绳/CUSUM/速度逃逸)。
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
            float headSettleSeconds,
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
            this.headSettleSeconds = Mathf.Max(headSettleSeconds, 0.0f);
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
            hasObsConsensus = false;
            obsConsensusPos = Vector3.zero;
            obsConsensusRot = Quaternion.identity;
            seamActive = false;
            seamPos = Vector3.zero;
            seamRot = Vector3.zero;
            hasLastHead = false;
            lastHeadPos = Vector3.zero;
            lastHeadRot = Quaternion.identity;
            headLinSpeedEma = 0.0f;
            headAngSpeedEma = 0.0f;
            headToleranceFactor = 1.0f;
            headMotionRatio = 0.0f;
            headSettleLeftSeconds = 0.0f;
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

            // 头停沉降计时: 头在动 (ratio>eps) → 重置满; 头静止 → 按真实 dt 递减。>0 期间冻结解锁判定,
            // 给 obsConsensus 把 head-slip 褪干净的时间, 避免"头一停阈值收紧快于 slip 褪去"的误解锁。
            if (headMotionRatio > HeadMovingRatioEps)
            {
                headSettleLeftSeconds = headSettleSeconds;
            }
            else
            {
                headSettleLeftSeconds = Mathf.Max(0.0f, headSettleLeftSeconds - obsDt);
            }

            // 距离自适应位置容忍 (问题2): 物体越远立体深度噪声越大, 位置容忍按距离放大 (旋转不放大)。
            posDistanceFactor = ComputePosDistanceFactor(hasHeadPose, headPose, pos);

            // 观测共识 (denoised, 死区无关): 低增益 EMA 跟踪真实观测。绝对漂移租绳用它 (而非 creep 后的
            // lockedPose) 度量真实漂移, 故必须在 UpdateLockedEvidence 之前更新。增益按真实 dt 的半衰期换算,
            // 与帧率无关; 复用 evidenceHalfLifeSeconds 作时间常数 (同一"什么算真实运动 vs 噪声"的尺度)。
            UpdateObsConsensus(pos, rot, obsDt);

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
        /// 更新观测共识 (denoised, 死区无关): 对被接受观测做半衰期 EMA。
        /// 与 creep 的关键区别: creep 只在死区内动 (物体一动就停), 共识则*始终*跟随真实观测,
        /// 只是被 EMA 平滑掉单帧噪声/head-slip 尖峰。绝对漂移租绳用它 (相对 anchorOrigin) 度量真实漂移,
        /// 使"慢速持续平移"能如实累积、顶破租绳解锁, 同时单帧噪声被平滑而不误触发。增益帧率无关。
        /// </summary>
        private void UpdateObsConsensus(Vector3 pos, Quaternion rot, float obsDt)
        {
            if (!hasObsConsensus)
            {
                obsConsensusPos = pos;
                obsConsensusRot = AnchorMath.Normalize(rot);
                hasObsConsensus = true;
                return;
            }

            // g = 1 - 0.5^(dt/halfLife): 每过一个半衰期, 共识朝观测靠拢一半。dt=0 (首帧/同刻) → g=0 不动。
            float g = 1.0f - Mathf.Pow(0.5f, obsDt / evidenceHalfLifeSeconds);
            obsConsensusPos += (pos - obsConsensusPos) * g;
            obsConsensusRot = AnchorMath.Normalize(Quaternion.Slerp(obsConsensusRot, rot, g));
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
                headMotionRatio = 0.0f;     // 头动门控关闭 → creep 不被头动抑制 (原行为)
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
            headMotionRatio = ratio;        // 供 creep 门控用: 头动越快 → creep 增益越小 (见 UpdateLockedEvidence)
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
            // 绝对漂移租绳参考 = 锁定时刻的*观测共识* (denoised), 不是 candidate。
            // candidate 含 smoothing/predict-ahead 的偏置 (录制中 predict_ahead ~260ms), 与 obs 不同源;
            // 用 obs 共识做 origin 才能让"漂移 = 真实观测相对锁定位的位移", 使 unlockDriftMeters 量纲正确。
            // 共识尚未建立 (理论上不会, OnObservation 必先于 EnterLock) 时退化用 candidate。
            anchorOrigin = hasObsConsensus
                ? new Pose(obsConsensusPos, obsConsensusRot)
                : candidatePose;
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

            // 头停沉降冻结 (问题3 续, 用户报告"头扫静止物体后头一停 static 就脱开"): 头动期间 + 头停后
            // headSettleSeconds 内, 冻结所有"判物体在动→解锁"的证据 (速度逃逸/漂移租绳/CUSUM)。原因: 头动时
            // head-slip 累进 obsConsensus、抬高观测速度; 头一停 headToleranceFactor 由头速驱动几乎瞬间塌回 1
            // (阈值收紧), 但 obsConsensus 携带的 slip 要按 evidenceHalfLifeSeconds 才褪去 → 出现"阈值已收紧、
            // slip 未褪净"的窗口 → 这三路误触发解锁。冻结期清零三路证据 (头停后从零重判), 给 obsConsensus 时间
            // 褪 slip 再恢复监测。低分释放不冻结 (上面, 独立可靠性信号); creep 也不冻结 (它已被 (1-headMotionRatio)
            // 门控, 头动时≈0, 且 creep 只精修不解锁)。settleSeconds 取 ~2~3× evidenceHalfLifeSeconds 保证 slip 充分衰减。
            bool settleFrozen = headSettleLeftSeconds > 0.0f;

            // 速度逃逸: 速度明确超阈连续一段 *时间* → 解锁 (速度比位移更早的运动信号, 堵 false-lock 长尾)。
            // 头动时阈值放大: 头转带来的 slip 速度不该触发逃逸。冻结期 movingNow 强制 false → movingRunSeconds 清零。
            bool movingNow = !settleFrozen
                             && (obsSpeedEma > staticEnterSpeedMps * unlockSpeedFactor * f
                                 || obsAngSpeedEma > staticEnterAngSpeedDps * unlockSpeedFactor * f);
            movingRunSeconds = movingNow ? movingRunSeconds + obsDt : 0.0f;
            if (movingRunSeconds >= unlockMovingSeconds)
            {
                wantUnlock = true;
                return; // 解锁在 Stabilize 提交 (此刻才有 candidate 做接缝)
            }

            // 绝对漂移租绳: 相对锁定时刻的*观测共识* anchorOrigin 的总漂移超租绳 → 解锁。
            // 关键: 漂移用 *观测共识 obsConsensus* (denoised, 死区无关) 度量, 既不用单帧原始观测、也不用 creep 后的 lockedPose:
            //   - 不用原始观测: 噪声大 (本数据集静止物体旋转 p90~13°、平移 p90~30mm, 远超 5°/15mm 租绳),
            //     头静止 (f=1) 时单帧尖峰就频繁误触发解锁 → 锚点"漂一小段又被拉回"的抖动 (问题3, 见 obsConsensus 注释)。
            //   - 不用 lockedPose: 它靠 creep 移动, 而 creep 只在死区内触发; 慢移时观测超死区→creep 停摆→lockedPose
            //     被钉死在 anchorOrigin 上→driftPos 恒≈0→慢移*永不解锁* (即使 unlockDriftMeters=0 也无效, 实测租绳被钉在亚毫米)。
            //   obsConsensus 是死区无关的低增益 EMA: 平滑掉单帧噪声/head-slip (保留问题3 免疫), 又如实跟随真实持续位移,
            //   因此慢移会被如实累积、顶破租绳正常解锁。这恢复了 unlockDriftMeters 作为"慢移逃逸灵敏度"旋钮的作用。
            // 头动时租绳放大: 头转造成的 world-pose slip 漂移不该触发解锁; 头静止时回原租绳, 真实慢移正常逃逸。
            // 位置租绳再乘 posDistanceFactor (问题2): 远处深度噪声大, 位置租绳同比放宽; 旋转租绳不随距离变 (旋转噪声与距离无关)。
            float driftPos = Vector3.Distance(obsConsensusPos, anchorOrigin.position);
            float driftRot = AnchorMath.AngleDegrees(anchorOrigin.rotation, obsConsensusRot);
            if (!settleFrozen && (driftPos > unlockDriftMeters * f * posDistanceFactor || driftRot > unlockDriftDegrees * f))
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
            if (!settleFrozen)
            {
                float decay = Mathf.Pow(0.5f, obsDt / evidenceHalfLifeSeconds);
                float accScale = obsDt / refObsIntervalSeconds;
                evidencePos = decay * evidencePos + accScale * score * Mathf.Max(0.0f, dPos - dbMeters);
                evidenceRot = decay * evidenceRot + accScale * score * Mathf.Max(0.0f, dRot - dbDegrees);

                if (evidencePos > unlockEvidenceMeters || evidenceRot > unlockEvidenceDegrees)
                {
                    wantUnlock = true;
                    return; // 解锁在 Stabilize 提交
                }
            }
            else
            {
                // 沉降冻结期: CUSUM 证据清零, 头停后从干净状态重新累积 (slip 期间攒的假证据不该带过窗口)。
                evidencePos = 0.0f;
                evidenceRot = 0.0f;
            }

            // 漏锁 creep: 仅死区内 (纯噪声/极慢漂移) 才朝观测缓慢靠拢, 精修锁点 + 跟极慢漂移而不抖。
            // creep 增益按真实 dt 的半衰期换算, 与帧率无关。
            // 头动门控: 增益乘 (1 - headMotionRatio)。头动时 head-motion slip 让"静止物体"的观测 world pose 出现
            // *系统性偏置* (非零均值噪声), 且死区被 headToleranceFactor 放大 → 偏置观测更易落进死区触发 creep →
            // creep 单向朝偏置靠拢, 多帧累积成净漂移, 头停后还要按 creepHalfLife 慢慢爬回 (用户报告: 头动观察后
            // 锚点偏移且不立即复位)。漂移租绳用 obsConsensus (EMA 可回中) 不受此影响, 但 creep 改的是输出本身,
            // 漂移会实打实留下。故头动越快 creep 越弱、头动达满容忍 (ratio=1) 时完全冻结锁点; 头静止 (ratio=0)
            // 时满增益照常精修。平滑过渡, 无硬阈值突变。
            if (dPos < dbMeters && dRot < dbDegrees)
            {
                float g = (1.0f - Mathf.Pow(0.5f, obsDt / creepHalfLifeSeconds)) * score * (1.0f - headMotionRatio);
                Vector3 newPos = lockedPose.position + (pos - lockedPose.position) * g;
                Quaternion newRot = Quaternion.Slerp(lockedPose.rotation, rot, g);
                lockedPose = new Pose(newPos, AnchorMath.Normalize(newRot));
            }
        }
    }
}
