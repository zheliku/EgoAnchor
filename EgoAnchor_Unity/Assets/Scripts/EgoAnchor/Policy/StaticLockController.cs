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
        private float staticEnterSpeedMps = 0.03f;
        private float staticEnterAngSpeedDps = 12.0f;
        private int staticDwellObs = 3;
        private float staticEnterMinScore = 0.4f;
        private float deadbandMeters = 0.008f;
        private float deadbandDegrees = 3.0f;
        private float unlockEvidenceMeters = 0.05f;
        private float unlockEvidenceDegrees = 12.0f;
        private float evidenceDecay = 0.6f;
        private float creepGain = 0.05f;
        private int relockSuppressObs = 4;
        private float unlockSpeedFactor = 2.0f;
        private int unlockMovingObs = 2;
        private float seamDecayPerFrame = 0.75f;

        // === 运行时状态 ===
        private bool locked;
        private Pose lockedPose;
        private float evidencePos;
        private float evidenceRot;
        private int staticRun;
        private int relockSuppressLeft;
        private int movingRun;

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

        /// <summary>当前是否锁定 (供 host 写 eval 的 latest_static_locked)。</summary>
        public bool IsLocked => locked;

        /// <summary>累计锁定进入次数 (诊断)。</summary>
        public int LockEnters { get; private set; }

        /// <summary>累计解锁次数 (诊断)。</summary>
        public int Unlocks { get; private set; }

        /// <summary>用 host 的参数配置控制器 (Inspector 可能改, 每次激活时调用)。</summary>
        public void Configure(
            float staticEnterSpeedMps,
            float staticEnterAngSpeedDps,
            int staticDwellObs,
            float staticEnterMinScore,
            float deadbandMeters,
            float deadbandDegrees,
            float unlockEvidenceMeters,
            float unlockEvidenceDegrees,
            float evidenceDecay,
            float creepGain,
            int relockSuppressObs,
            float unlockSpeedFactor,
            int unlockMovingObs,
            float seamDecayPerFrame)
        {
            this.staticEnterSpeedMps = Mathf.Max(staticEnterSpeedMps, 0.0f);
            this.staticEnterAngSpeedDps = Mathf.Max(staticEnterAngSpeedDps, 0.0f);
            this.staticDwellObs = Mathf.Max(staticDwellObs, 1);
            this.staticEnterMinScore = Mathf.Clamp01(staticEnterMinScore);
            this.deadbandMeters = Mathf.Max(deadbandMeters, 0.0f);
            this.deadbandDegrees = Mathf.Max(deadbandDegrees, 0.0f);
            this.unlockEvidenceMeters = Mathf.Max(unlockEvidenceMeters, 0.0f);
            this.unlockEvidenceDegrees = Mathf.Max(unlockEvidenceDegrees, 0.0f);
            this.evidenceDecay = Mathf.Clamp01(evidenceDecay);
            this.creepGain = Mathf.Clamp01(creepGain);
            this.relockSuppressObs = Mathf.Max(relockSuppressObs, 0);
            this.unlockSpeedFactor = Mathf.Max(unlockSpeedFactor, 1.0f);
            this.unlockMovingObs = Mathf.Max(unlockMovingObs, 1);
            this.seamDecayPerFrame = Mathf.Clamp(seamDecayPerFrame, 0.5f, 0.99f);
        }

        /// <summary>清空所有状态。</summary>
        public void Reset()
        {
            locked = false;
            lockedPose = Pose.identity;
            evidencePos = 0.0f;
            evidenceRot = 0.0f;
            staticRun = 0;
            relockSuppressLeft = 0;
            movingRun = 0;
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
            LockEnters = 0;
            Unlocks = 0;
        }

        /// <summary>
        /// 收到一帧被接受的观测时调用 (host 在 motionModel 更新后)。
        /// 更新 obs-to-obs 速度、静/动 dwell 计数; 锁定中则累积解锁证据。
        /// </summary>
        /// <param name="worldPose">frame-aligned world pose (= 进 motion model 的同一 pose)。</param>
        /// <param name="score">该观测可靠性分数 0..1。</param>
        /// <param name="measurementTimeSeconds">观测测量时间 (capture 时间)。</param>
        public void OnObservation(in Pose worldPose, float score, double measurementTimeSeconds)
        {
            Vector3 pos = worldPose.position;
            Quaternion rot = worldPose.rotation;

            if (hasLastObs)
            {
                float dt = Mathf.Max((float)(measurementTimeSeconds - lastObsTime), 1e-3f);
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

            bool isStatic = obsSpeedEma <= staticEnterSpeedMps
                            && obsAngSpeedEma <= staticEnterAngSpeedDps
                            && score >= staticEnterMinScore;

            if (locked)
            {
                UpdateLockedEvidence(pos, rot, score);
            }
            else if (relockSuppressLeft > 0)
            {
                relockSuppressLeft--;
                staticRun = 0;
            }
            else
            {
                staticRun = isStatic ? staticRun + 1 : 0;
            }

            hasLastObs = true;
            lastObsPos = pos;
            lastObsRot = rot;
            lastObsTime = measurementTimeSeconds;
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
            else if (staticRun >= staticDwellObs)
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
            return evidencePos > unlockEvidenceMeters
                   || evidenceRot > unlockEvidenceDegrees
                   || movingRun >= unlockMovingObs;
        }

        private void EnterLock(in Pose candidatePose)
        {
            locked = true;
            LockEnters++;
            lockedPose = candidatePose; // 锚到当前 candidate, C⁰ 连续无 pop
            evidencePos = 0.0f;
            evidenceRot = 0.0f;
            movingRun = 0;
            seamActive = false;
            seamPos = Vector3.zero;
            seamRot = Vector3.zero;
        }

        private void Unlock(in Pose candidatePose)
        {
            locked = false;
            Unlocks++;
            staticRun = 0;
            relockSuppressLeft = relockSuppressObs;
            movingRun = 0;
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

        /// <summary>锁定时: 速度逃逸 + 死区吸收 + score 加权 CUSUM + 漏锁 creep。</summary>
        private void UpdateLockedEvidence(Vector3 pos, Quaternion rot, float score)
        {
            // 速度逃逸: 速度明确超阈连续若干帧 → 解锁 (速度比位移更早的运动信号, 堵 false-lock 长尾)。
            bool movingNow = obsSpeedEma > staticEnterSpeedMps * unlockSpeedFactor
                             || obsAngSpeedEma > staticEnterAngSpeedDps * unlockSpeedFactor;
            movingRun = movingNow ? movingRun + 1 : 0;
            if (movingRun >= unlockMovingObs)
            {
                return; // 解锁在 Stabilize 提交 (此刻才有 candidate 做接缝)
            }

            float dPos = Vector3.Distance(pos, lockedPose.position);
            float dRot = AnchorMath.AngleDegrees(lockedPose.rotation, rot);

            evidencePos = evidenceDecay * evidencePos + score * Mathf.Max(0.0f, dPos - deadbandMeters);
            evidenceRot = evidenceDecay * evidenceRot + score * Mathf.Max(0.0f, dRot - deadbandDegrees);

            if (evidencePos > unlockEvidenceMeters || evidenceRot > unlockEvidenceDegrees)
            {
                return; // 解锁在 Stabilize 提交
            }

            // 漏锁 creep: 仅死区内 (纯噪声/极慢漂移) 才朝观测缓慢靠拢, 精修锁点 + 跟极慢漂移而不抖。
            if (dPos < deadbandMeters && dRot < deadbandDegrees)
            {
                float g = creepGain * score;
                Vector3 newPos = lockedPose.position + (pos - lockedPose.position) * g;
                Quaternion newRot = Quaternion.Slerp(lockedPose.rotation, rot, g);
                lockedPose = new Pose(newPos, AnchorMath.Normalize(newRot));
            }
        }
    }
}
