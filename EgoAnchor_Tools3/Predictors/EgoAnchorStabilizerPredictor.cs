using System;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Sim;

namespace EgoAnchor.Tools3.Predictors
{
    /// <summary>
    /// EgoAnchor 锚定稳定器 (装饰器)。这是论文方法层, 不是又一个滤波器。
    ///
    /// 思想: 被锚定的真实物体 **绝大多数时间是不动的** —— 动的是头显, 噪的是观测
    /// (帧对齐残差 + 深度噪声 + head-motion-induced slip)。所有 baseline (CV/Kalman/1€)
    /// 都是 motion-agnostic 滤波器, 假设信号在持续运动, 只做去噪, 因此静止物体永远残留抖动。
    /// 本类显式建模"物体是个锚、默认静止"这一先验, 做成一个 **分区切换稳定器**:
    ///
    ///   - STATIC 区: 输出一个锁定 pose (lockedPose), 平移+旋转都冻结, 观测的小抖动一律
    ///       吸收 (它们就是噪声), 抖动 ≈ 0, 看上去一动不动;
    ///   - MOVING 区: 交回被装饰的 inner 预测器 (你已满意的 interp/blend) 跟踪;
    ///   - 两区切换由 **pose score 加权的运动证据 (CUSUM)** 仲裁。
    ///
    /// 关键机制 (规避静态锁的经典毛病 —— 慢速真实运动被锁住 → 滞后 → 猛跳):
    ///   1. **死区 (deadband)**: 锁定时, 观测相对 lockedPose 的位移在死区内 → 完全忽略
    ///      (这是噪声地板, 杀掉静止抖动的核心);
    ///   2. **score 加权 CUSUM**: E += score·max(0, |Δ| − deadband), 每帧/每观测衰减。
    ///      高分 + 持续同向位移 → E 越阈 → 解锁 (慢速真实运动也能最终触发, 抗 false-lock);
    ///      低分远跳 → score 权重小 → 贡献被压低 → 不解锁 (这就是 score 拒坏 pose 的地方,
    ///      但是软的、积分式的, 不是硬阈值);
    ///   3. **漏锁 (leaky creep)**: 锁定时用极小增益把 lockedPose 朝高分小位移观测缓慢 creep,
    ///      既精修锁点 (score 加权质心比单帧准), 又跟住极慢真实漂移而不抖;
    ///   4. **接缝过渡 (seam)**: 解锁瞬间 inner 可能已离 lockedPose 较远 (尤其 false-lock 迟到解锁),
    ///      用残差融合在若干帧内从 lockedPose 平滑收敛到 inner, 防解锁 pop。
    ///
    /// 位置和旋转用 **独立证据通道** (静态物体的角度摇摆视觉上最刺眼, 必须单独锁/单独解)。
    /// 这是 Unity 侧 host 内联 static-lock 的离线对照实现 (装饰器, 不改 inner)。
    /// </summary>
    public sealed class EgoAnchorStabilizerPredictor : IPredictor
    {
        private readonly IPredictor inner;

        // --- 硬 score 门控 (拒坏 pose) ---
        private readonly double scoreGateMinScore;   // 低于此分: 硬拒, 不喂 inner (Hold, 继续外推)

        // --- 进入锁: 静止判定 ---
        private readonly double staticEnterSpeed;     // m/s, 观测速度低于此 → 静止候选
        private readonly double staticEnterAngSpeed;  // deg/s
        private readonly double staticDwellSeconds;   // 连续静止 *时间* 才锁 (帧率无关; 防静止判定抖动)
        private readonly double staticEnterMinScore;  // 需此分以上才信任"静止"判断

        // --- 死区 (锁定时的噪声地板) ---
        private readonly double deadbandPos;          // m, 位移小于此 → 视为抖动, 忽略
        private readonly double deadbandRot;          // deg

        // --- 解锁: score 加权 CUSUM ---
        private readonly double unlockEvidencePos;    // 位置证据阈值 (m·s, 加权累计的超死区位移 × 时间)
        private readonly double unlockEvidenceRot;    // 旋转证据阈值 (deg·s)
        private readonly double evidenceHalfLifeSeconds; // 证据半衰期 (秒, 帧率无关漏积分; 旧 evidenceDecay 的时间化)

        // --- 漏锁 creep ---
        private readonly double creepHalfLifeSeconds; // 漏锁 creep 半衰期 (秒, 帧率无关; 旧 creepGain 的时间化)

        // --- 解锁接缝 ---
        private readonly double seamDecayPerFrame;    // 解锁后残差融合衰减 (60fps 基准, 已帧率无关)
        private readonly double relockSuppressSeconds; // 解锁后多少 *时间* 内禁止再锁 (反 chatter)
        private readonly double unlockSpeedFactor;     // 锁定时观测速度 > staticEnterSpeed × 此倍数 → 速度逃逸
        private readonly double unlockMovingSeconds;   // 连续多少 *时间* 明确运动才速度逃逸 (防单帧噪声)

        // CUSUM 时间归一基准: 增量乘 (dt / refObsIntervalSeconds), 使"持续运动多久能解锁"与帧率无关。
        private readonly double refObsIntervalSeconds;

        // --- 绝对漂移租绳 (leash): 防 creep 把慢速持续运动"吃掉"导致永不解锁 ---
        // CUSUM 用的 dPos 是相对(会被 creep 跟随的) lockedPose 的, 慢速平移时 creep 让 dPos 始终在死区内,
        // 证据永不累积 → 永不解锁 (用户报告的"极慢平移不脱离 static")。
        // 解法: 额外跟踪相对一个 *锁定时固定、creep 不动* 的 anchorOrigin 的绝对漂移; 超过租绳直接解锁。
        private readonly double unlockDriftMeters;    // 相对锁定原点的绝对平移超过此值 → 解锁 (creep 无关)
        private readonly double unlockDriftDegrees;   // 相对锁定原点的绝对旋转超过此值 → 解锁

        // === 运行时状态 ===
        private bool locked;
        private Pose lockedPose;
        private Pose anchorOrigin;                     // 锁定时的固定锚点 (creep 不动它), 用于绝对漂移租绳
        private double evidencePos;
        private double evidenceRot;
        private double staticRunSeconds;              // 当前连续静止 *时间* (秒)
        private double relockSuppressLeftSeconds;     // 解锁后剩余的禁锁 *时间* (秒)
        private double movingRunSeconds;              // 锁定时连续"明确运动" *时间* (秒, 速度逃逸用)

        // 观测速度跟踪 (obs-to-obs)
        private bool hasLastObs;
        private Vec3 lastObsPos;
        private Quat lastObsRot;
        private double lastObsTime;
        private bool hasSpeedEma;
        private double obsSpeedEma;                   // m/s
        private double obsAngSpeedEma;                // deg/s

        // 跨 OnObservation→PredictAt 的意图标志 (决策在 OnObservation 累积, 在 PredictAt 提交以拿到 now+inner)
        private bool wantUnlock;

        // 解锁接缝残差
        private bool seamActive;
        private Vec3 seamPos;                         // lockedPose − inner 的位置残差
        private Vec3 seamRot;                         // 切空间残差
        private bool hasRendered;
        private double lastRenderTime;

        // === 诊断计数 (PoC 调参用, 不影响算法) ===
        public int LockEnters { get; private set; }
        public int Unlocks { get; private set; }
        public long FramesLocked { get; private set; }
        public long FramesSeam { get; private set; }
        public long FramesFree { get; private set; }
        public long FramesGated { get; private set; }

        public EgoAnchorStabilizerPredictor(
            IPredictor inner,
            double scoreGateMinScore = 0.15,
            double staticEnterSpeed = 0.05,
            double staticEnterAngSpeed = 35.0,
            double staticDwellSeconds = 0.35,
            double staticEnterMinScore = 0.25,
            double deadbandPos = 0.008,
            double deadbandRot = 3.0,
            double unlockEvidencePos = 0.08,
            double unlockEvidenceRot = 20.0,
            double unlockDriftPos = 0.015,
            double unlockDriftRot = 5.0,
            double evidenceHalfLifeSeconds = 0.27,
            double creepHalfLifeSeconds = 2.7,
            double seamDecayPerFrame = 0.85,
            double relockSuppressSeconds = 1.0,
            double unlockSpeedFactor = 2.5,
            double unlockMovingSeconds = 0.4,
            double refObsIntervalSeconds = 0.2)
        {
            this.inner = inner;
            this.scoreGateMinScore = scoreGateMinScore;
            this.staticEnterSpeed = staticEnterSpeed;
            this.staticEnterAngSpeed = staticEnterAngSpeed;
            this.staticDwellSeconds = Math.Max(staticDwellSeconds, 0.0);
            this.staticEnterMinScore = staticEnterMinScore;
            this.deadbandPos = deadbandPos;
            this.deadbandRot = deadbandRot;
            this.unlockEvidencePos = unlockEvidencePos;
            this.unlockEvidenceRot = unlockEvidenceRot;
            this.unlockDriftMeters = Math.Max(unlockDriftPos, 0.0);
            this.unlockDriftDegrees = Math.Max(unlockDriftRot, 0.0);
            this.evidenceHalfLifeSeconds = Math.Max(evidenceHalfLifeSeconds, 1e-3);
            this.creepHalfLifeSeconds = Math.Max(creepHalfLifeSeconds, 1e-3);
            this.seamDecayPerFrame = seamDecayPerFrame;
            this.relockSuppressSeconds = Math.Max(relockSuppressSeconds, 0.0);
            this.unlockSpeedFactor = Math.Max(unlockSpeedFactor, 1.0);
            this.unlockMovingSeconds = Math.Max(unlockMovingSeconds, 0.0);
            this.refObsIntervalSeconds = Math.Max(refObsIntervalSeconds, 1e-3);
        }

        public string Label => $"ego_{inner.Label}";

        public bool HasEstimate => inner.HasEstimate;

        public void Reset()
        {
            inner.Reset();
            locked = false;
            lockedPose = Pose.Identity;
            anchorOrigin = Pose.Identity;
            evidencePos = 0.0;
            evidenceRot = 0.0;
            staticRunSeconds = 0.0;
            relockSuppressLeftSeconds = 0.0;
            movingRunSeconds = 0.0;
            hasLastObs = false;
            lastObsPos = Vec3.Zero;
            lastObsRot = Quat.Identity;
            lastObsTime = 0.0;
            hasSpeedEma = false;
            obsSpeedEma = 0.0;
            obsAngSpeedEma = 0.0;
            wantUnlock = false;
            seamActive = false;
            seamPos = Vec3.Zero;
            seamRot = Vec3.Zero;
            hasRendered = false;
            lastRenderTime = 0.0;
        }

        public void OnObservation(in Observation observation)
        {
            // 硬 score 门控: 太低分 = 坏 pose, 不喂 inner (Hold 语义: inner 用旧状态继续外推),
            // 也不更新运动证据 (坏帧不该影响静/动判定)。
            if (observation.Score < scoreGateMinScore)
            {
                FramesGated++;
                return;
            }

            inner.OnObservation(observation);

            Vec3 pos = observation.Pose.Position;
            Quat rot = observation.Pose.Rotation;
            double t = observation.TimeSeconds;

            // 本次观测相对上一观测的真实时间间隔 (秒); 首帧为 0。所有 dwell/suppress 累积都按它走, 与帧率无关。
            double obsDt = hasLastObs ? Math.Max(t - lastObsTime, 0.0) : 0.0;

            // --- 更新 obs-to-obs 速度 (静止判定用) ---
            if (hasLastObs)
            {
                double dt = Math.Max(obsDt, 1e-3);
                double speed = Vec3.Distance(pos, lastObsPos) / dt;
                double angSpeed = Quat.AngleDegrees(rot, lastObsRot) / dt;
                // EMA 平滑 (单帧噪声不该立刻翻转静/动判定)
                if (hasSpeedEma)
                {
                    obsSpeedEma += 0.5 * (speed - obsSpeedEma);
                    obsAngSpeedEma += 0.5 * (angSpeed - obsAngSpeedEma);
                }
                else
                {
                    obsSpeedEma = speed;
                    obsAngSpeedEma = angSpeed;
                    hasSpeedEma = true;
                }
            }

            bool isStatic = obsSpeedEma <= staticEnterSpeed
                            && obsAngSpeedEma <= staticEnterAngSpeed
                            && observation.Score >= staticEnterMinScore;

            if (locked)
            {
                UpdateLockedEvidence(pos, rot, observation.Score, obsSpeedEma, obsAngSpeedEma, obsDt);
            }
            else
            {
                // 反 chatter: 解锁后一段 *时间* 内不许再锁, 给真实运动一个"逃逸窗口"。
                if (relockSuppressLeftSeconds > 0.0)
                {
                    relockSuppressLeftSeconds -= obsDt;
                    staticRunSeconds = 0.0;
                }
                else
                {
                    // 未锁定: 累积静止 *时间*。够了就请求在下一帧 PredictAt 锁定 (拿当前 inner 输出当锚, 保证 C⁰)。
                    staticRunSeconds = isStatic ? staticRunSeconds + obsDt : 0.0;
                }
            }

            hasLastObs = true;
            lastObsPos = pos;
            lastObsRot = rot;
            lastObsTime = t;
        }

        public Pose PredictAt(double renderTimeSeconds)
        {
            if (!inner.HasEstimate)
            {
                return Pose.Identity;
            }

            Pose innerPose = inner.PredictAt(renderTimeSeconds);
            double dt = hasRendered ? renderTimeSeconds - lastRenderTime : 0.0;

            // === 锁定状态机 (在此提交, 因为这里才有 now + inner 输出, 保证切换 C⁰ 连续) ===
            if (locked)
            {
                if (wantUnlock)
                {
                    // 解锁: 记录接缝残差 = 当前 lockedPose ⊖ inner(now), 之后逐帧融合收敛到 inner。
                    Unlock(innerPose);
                }
            }
            else if (staticRunSeconds >= staticDwellSeconds)
            {
                // 进入锁定: 锚定到当前 inner 输出 (C⁰ 无 pop), 清证据。
                EnterLock(innerPose);
            }

            Pose output;
            if (locked)
            {
                output = lockedPose;
                FramesLocked++;
            }
            else if (seamActive)
            {
                // 解锁过渡: inner ⊕ 残差, 残差逐帧衰减 → 平滑收敛到 inner, 防解锁跳变。
                output = ApplySeam(innerPose, dt);
                FramesSeam++;
            }
            else
            {
                output = innerPose;
                FramesFree++;
            }

            hasRendered = true;
            lastRenderTime = renderTimeSeconds;
            return output;
        }

        /// <summary>锁定时: 速度逃逸 + 死区吸收 + score 加权 CUSUM 累积运动证据 + 漏锁 creep。全部按真实 dt, 帧率无关。</summary>
        private void UpdateLockedEvidence(Vec3 pos, Quat rot, double score, double obsSpeed, double obsAngSpeed, double obsDt)
        {
            // 速度逃逸: 观测速度明确超过静止阈值 × 倍数, 连续一段 *时间* → 立即解锁。
            // 这堵住了"慢速真实运动被 creep 跟住、CUSUM 永不越阈"的 false-lock 长尾
            // (PoC 里 onset-lag P90=1500ms 的卡死 case)。速度是比位移更早的运动信号。
            bool movingNow = obsSpeed > staticEnterSpeed * unlockSpeedFactor
                             || obsAngSpeed > staticEnterAngSpeed * unlockSpeedFactor;
            movingRunSeconds = movingNow ? movingRunSeconds + obsDt : 0.0;
            if (movingRunSeconds >= unlockMovingSeconds)
            {
                wantUnlock = true;
                return;
            }

            // 绝对漂移租绳: 相对锁定时固定的 anchorOrigin (creep 不动它) 的总漂移超过租绳 → 解锁。
            // 这是慢速持续平移的逃生口: creep 会让 lockedPose 跟着慢移、使下面的相对 CUSUM 失效,
            // 但 anchorOrigin 不动, 慢移累计够远必然触发, 修复"极慢平移永不脱离 static"。
            double driftPos = Vec3.Distance(pos, anchorOrigin.Position);
            double driftRot = Quat.AngleDegrees(rot, anchorOrigin.Rotation);
            if (driftPos > unlockDriftMeters || driftRot > unlockDriftDegrees)
            {
                wantUnlock = true;
                return;
            }

            double dPos = Vec3.Distance(pos, lockedPose.Position);
            double dRot = Quat.AngleDegrees(rot, lockedPose.Rotation);

            // CUSUM (帧率无关): 每观测先按真实 dt 做半衰期衰减 (漏积分), 再累积"超出死区"的部分。
            // 累积量乘 (obsDt / refObsIntervalSeconds): 同样的持续运动, 不论 5fps 还是 12fps, 单位时间攒到的证据相同。
            double decay = Math.Pow(0.5, obsDt / evidenceHalfLifeSeconds);
            double accScale = obsDt / refObsIntervalSeconds;
            evidencePos = decay * evidencePos + accScale * score * Math.Max(0.0, dPos - deadbandPos);
            evidenceRot = decay * evidenceRot + accScale * score * Math.Max(0.0, dRot - deadbandRot);

            if (evidencePos > unlockEvidencePos || evidenceRot > unlockEvidenceRot)
            {
                wantUnlock = true; // 在下一帧 PredictAt 提交 (拿 inner(now) 做接缝)
                return;
            }

            // 漏锁 creep: 仅当位移在死区内 (纯噪声/极慢漂移) 才朝观测缓慢靠拢,
            // 精修锁点为 score 加权质心 + 跟住极慢真实漂移而不抖。死区外不 creep (那是在攒解锁证据)。
            // creep 增益按真实 dt 的半衰期换算成"每观测比例", 与帧率无关。
            if (dPos < deadbandPos && dRot < deadbandRot)
            {
                double g = (1.0 - Math.Pow(0.5, obsDt / creepHalfLifeSeconds)) * score;
                Vec3 newPos = lockedPose.Position + (pos - lockedPose.Position) * g;
                Quat newRot = Quat.Slerp(lockedPose.Rotation, rot, g);
                lockedPose = new Pose(newPos, newRot.Normalized());
            }
        }

        private void EnterLock(Pose innerPose)
        {
            locked = true;
            LockEnters++;
            lockedPose = innerPose;
            anchorOrigin = innerPose; // 固定锚点, creep 不动它; 绝对漂移租绳的参考
            evidencePos = 0.0;
            evidenceRot = 0.0;
            movingRunSeconds = 0.0;
            wantUnlock = false;
            seamActive = false;
            seamPos = Vec3.Zero;
            seamRot = Vec3.Zero;
        }

        private void Unlock(Pose innerPose)
        {
            locked = false;
            Unlocks++;
            wantUnlock = false;
            staticRunSeconds = 0.0;
            relockSuppressLeftSeconds = relockSuppressSeconds;
            // 接缝残差: lockedPose 相对 inner(now) 的偏移, 让输出从 lockedPose 起、平滑收敛到 inner。
            seamPos = lockedPose.Position - innerPose.Position;
            Quat aligned = Quat.AlignHemisphere(innerPose.Rotation, lockedPose.Rotation);
            seamRot = Quat.Log(innerPose.Rotation.Inverse() * aligned);
            seamActive = seamPos.Magnitude > 1e-5 || seamRot.Magnitude > 1e-5;
        }

        private Pose ApplySeam(Pose innerPose, double dt)
        {
            Vec3 pos = innerPose.Position + seamPos;
            Quat rot = (innerPose.Rotation * Quat.Exp(seamRot)).Normalized();

            double frames = Math.Max(dt, 0.0) * 60.0;
            double decay = Math.Pow(seamDecayPerFrame, frames);
            seamPos *= decay;
            seamRot *= decay;
            if (seamPos.Magnitude < 1e-5 && seamRot.Magnitude < 1e-5)
            {
                seamActive = false;
            }

            return new Pose(pos, rot);
        }
    }
}
