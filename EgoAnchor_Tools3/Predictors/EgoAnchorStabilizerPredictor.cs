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
    /// 关键机制 (规避静止锚定的经典毛病 —— 慢速真实运动被锁住 → 滞后 → 猛跳):
    ///   1. **死区 (deadband)**: 锁定时, 观测相对 lockedPose 的位移在死区内 → 完全忽略
    ///      (这是噪声地板, 杀掉静止抖动的核心);
    ///   2. **score 加权 CUSUM**: E += score·max(0, |Δ| − deadband), 每帧/每观测衰减。
    ///      高分 + 持续同向位移 → E 越阈 → 解锁 (慢速真实运动也能最终触发, 抗 false-lock);
    ///      低分远跳 → score 权重小 → 贡献被压低 → 不解锁 (这就是 score 拒坏 pose 的地方,
    ///      但是软的、积分式的, 不是硬阈值);
    ///   3. **漏锁 (leaky creep)**: 锁定时用极小增益把 lockedPose 朝高分小位移观测缓慢 creep,
    ///      既精修锁点 (score 加权质心比单帧准), 又跟住极慢真实漂移而不抖; **头动时按 (1−headMotionRatio)
    ///      门控**, 头转越快 creep 越弱, 防 head-slip 系统性偏置被 creep 单向累积成锁点净漂移;
    ///   4. **接缝过渡 (seam)**: 解锁瞬间 inner 可能已离 lockedPose 较远 (尤其 false-lock 迟到解锁),
    ///      用残差融合在若干帧内从 lockedPose 平滑收敛到 inner, 防解锁 pop;
    ///   5. **绝对漂移租绳 (leash)**: 量死区无关的去噪观测共识 obsConsensus (EMA) 相对锁定原点的漂移,
    ///      超租绳即解锁。修"慢移时观测超死区→creep 停摆→lockedPose 钉死→量 lockedPose 的旧租绳恒≈0→
    ///      慢移永不解锁"的结构性失效 (旧实现量 creep 后的 lockedPose, 是 bug);
    ///   6. **头停沉降冻结 (settle-freeze)**: 头动期间 + 头停后 headSettleSeconds 内冻结上述 2/5 与速度逃逸
    ///      三路解锁判定 (冻结期清零 CUSUM)。修"头扫静止物体后头一停 static 就脱开": 头停时容忍系数瞬间收紧,
    ///      但 head-slip 还残留在 obsConsensus/速度里, 不冻结就会误解锁。给 obsConsensus 时间褪 slip 再恢复监测。
    ///
    /// 位置和旋转用 **独立证据通道** (静态物体的角度摇摆视觉上最刺眼, 必须单独锁/单独解)。
    /// 这是 Unity 侧静止锚定的离线对照实现 (装饰器, 不改 inner)。
    /// </summary>
    public sealed class EgoAnchorStabilizerPredictor : IPredictor
    {
        private readonly IPredictor inner;

        // --- 可选质量评估门控 (拒坏 pose) ---
        private readonly double qualityGateMinScore; // 低于此分: 硬拒, 不喂 inner (Hold, 继续外推)

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

        // --- 头动感知 (问题3): 头转/平移时, head-motion-induced slip 抬高观测物体的"表观运动",
        // 静止物体会被误判 moving → 误解锁 → anchor 抖。解法: 头动越大, 临时按比例放大 static 容忍度
        // (deadband + drift-leash + unlock-evidence 阈值), 把 slip 当噪声吸收; 头静止时回到原阈值。
        // 头速 = 相邻观测的 HeadPose 差分。容忍因子 = 1 + min(headRatio, max-1), headRatio 取角速度/线速度归一后的较大者。
        private readonly double headRotForFullTolerance;  // 头角速度 (deg/s) 达此值 → 容忍因子吃满
        private readonly double headLinForFullTolerance;  // 头线速度 (m/s) 达此值 → 容忍因子吃满
        private readonly double headMaxToleranceFactor;   // 容忍度最大放大倍数 (1=关闭头动感知)

        // --- 头停沉降冻结 (问题3 续: 头扫静止物体后头一停 static 就脱开) ---
        // 头动期间 head-slip 累进 obsConsensus / 抬高观测速度; 头一停, headToleranceFactor 由头速驱动几乎瞬间
        // 塌回 1 (阈值收紧), 但 obsConsensus 携带的 slip 要按 evidenceHalfLifeSeconds 才褪去 → "阈值已收紧、
        // slip 未褪净"的窗口 → 漂移租绳/CUSUM/速度逃逸误触发解锁。解法: 头动期间 + 头停后 headSettleSeconds 内
        // 冻结这三路解锁判定 (冻结期清零 CUSUM 证据), 给 obsConsensus 时间褪 slip 再恢复监测。settleSeconds 取
        // ~2~3× evidenceHalfLifeSeconds。低分释放不冻结 (独立可靠性信号); creep 也不冻 (已被 (1-headMotionRatio) 门控)。
        private readonly double headSettleSeconds;         // 头停后冻结解锁判定的时长 (秒, 帧率无关; 0=关闭)
        private const double HeadMovingRatioEps = 0.06;    // headMotionRatio 超此值视为"头在动" (重置沉降计时)

        // --- 绝对漂移租绳 (leash): 防 creep 把慢速持续运动"吃掉"导致永不解锁 ---
        // CUSUM 用的 dPos 是相对(会被 creep 跟随的) lockedPose 的, 慢速平移时 creep 让 dPos 始终在死区内,
        // 证据永不累积 → 永不解锁 (用户报告的"极慢平移不脱离 static")。
        // 解法: 额外跟踪相对一个 *锁定时固定、creep 不动* 的 anchorOrigin 的绝对漂移; 超过租绳直接解锁。
        private readonly double unlockDriftMeters;    // 相对锁定原点的绝对平移超过此值 → 解锁 (creep 无关)
        private readonly double unlockDriftDegrees;   // 相对锁定原点的绝对旋转超过此值 → 解锁

        // --- 距离自适应位置容忍 (问题2): 物体越远, 立体深度估计噪声越大 (~z², 离线证实
        // corr(距离, 位置抖动)=+0.23; 而旋转抖动与距离无关 corr≈-0.02, 故只缩放位置通道, 旋转不动)。
        // 同样的真实静止, 远处观测位置抖得更大 → 固定米死区/租绳在远处频繁被噪声顶破 → 误解锁抖动。
        // 解法: 位置死区与位置租绳乘 posDistanceFactor = clamp(1 + slope·(dist−ref), 1, max),
        // dist = 观测物体到头部的距离。ref 以内不放大 (近处不动), 越远越宽松。max 封顶防失控。
        private readonly double posToleranceRefDistance;   // 此距离 (m) 以内位置容忍不放大 (factor=1)
        private readonly double posToleranceDistanceSlope; // 每超出 ref 1m, 位置容忍增加的比例 (1/m)
        private readonly double posToleranceMaxFactor;     // 位置容忍放大上限 (1=关闭距离自适应)

        // --- 低分释放 (问题1): 锁定时持续低分 → 锁点不可信, 强制解锁 (不让 anchor 冻在错 pose) ---
        private readonly double lowScoreReleaseScore;   // 低于此分视为不可信
        private readonly double lowScoreReleaseSeconds; // 持续低分多久后强制解锁 (0=关闭)

        // === 运行时状态 ===
        private bool locked;
        private Pose lockedPose;
        private Pose anchorOrigin;                     // 锁定时的固定锚点 (creep 不动它), 用于绝对漂移租绳
        private double evidencePos;
        private double evidenceRot;
        private double staticRunSeconds;              // 当前连续静止 *时间* (秒)
        private double relockSuppressLeftSeconds;     // 解锁后剩余的禁锁 *时间* (秒)
        private double movingRunSeconds;              // 锁定时连续"明确运动" *时间* (秒, 速度逃逸用)
        private double lowScoreRunSeconds;            // 锁定时连续低分累计时间 (低分释放用)

        // 观测速度跟踪 (obs-to-obs)
        private bool hasLastObs;
        private Vec3 lastObsPos;
        private Quat lastObsRot;
        private double lastObsTime;
        private bool hasSpeedEma;
        private double obsSpeedEma;                   // m/s
        private double obsAngSpeedEma;                // deg/s

        // 观测共识 (denoised, 死区无关): 对被接受观测做低增益 EMA, 平滑掉单帧噪声/head-slip 尖峰,
        // 但 *如实跟随* 真实持续位移 (与 creep 不同, 不受死区门控)。绝对漂移租绳用它相对 anchorOrigin
        // (= 锁定时刻的共识) 度量真实漂移, 修复"慢移时观测超死区→creep 停摆→lockedPose 钉死→租绳恒≈0
        // →慢移永不解锁 (unlockDriftMeters 调到 0 都无效)"的结构性失效。EMA 平滑 + headToleranceFactor 放大保留头转抖动免疫。
        private bool hasObsConsensus;
        private Vec3 obsConsensusPos;
        private Quat obsConsensusRot;

        // 跨 OnObservation→PredictAt 的意图标志 (决策在 OnObservation 累积, 在 PredictAt 提交以拿到 now+inner)
        private bool wantUnlock;

        // 解锁接缝残差
        private bool seamActive;
        private Vec3 seamPos;                         // lockedPose − inner 的位置残差
        private Vec3 seamRot;                         // 切空间残差
        private bool hasRendered;
        private double lastRenderTime;

        // 头动跟踪 (obs-to-obs, 从 Observation.HeadPose 差分)
        private bool hasLastHead;
        private Pose lastHeadPose;
        private double headAngSpeedEma;               // deg/s
        private double headLinSpeedEma;               // m/s
        private double headToleranceFactor = 1.0;     // 当前头动放大系数 (1=头静止)
        private double headMotionRatio;               // 头动强度 0..1 (0=头静止, 1=头速达满容忍阈值)。门控 creep: 头动时减弱/冻结 creep, 防 head-slip 偏置被 creep 单向累积成锁点漂移。
        private double headSettleLeftSeconds;         // 头停沉降冻结剩余时间 (秒)。头在动时重置满, 头静止时递减; >0 期间冻结解锁判定 (漂移租绳/CUSUM/速度逃逸)。
        private double posDistanceFactor = 1.0;       // 当前距离自适应位置容忍系数 (问题2; 1=近处/关闭)

        // === 诊断计数 (PoC 调参用, 不影响算法) ===
        public int LockEnters { get; private set; }
        public int Unlocks { get; private set; }
        public long FramesLocked { get; private set; }
        public long FramesSeam { get; private set; }
        public long FramesFree { get; private set; }
        public long FramesQualityRejected { get; private set; }

        public EgoAnchorStabilizerPredictor(
            IPredictor inner,
            double qualityGateMinScore = 0.15,
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
            double refObsIntervalSeconds = 0.2,
            // 头动感知 (问题3): 头动时 head-motion-induced slip 抬高观测物体表观速度,
            // 把静止物体误判成 moving → 误解锁 → anchor 跟头抖。头动越大, 临时放大静止容忍度
            // (死区/漂移租绳/解锁证据阈值), 把 slip 当噪声吸收。头静止时回到原阈值 (真动才解锁)。
            double headRotForFullTolerance = 60.0,   // 头角速度达此值 (deg/s) → 容忍度放大到上限
            double headLinForFullTolerance = 0.3,    // 头线速度达此值 (m/s) → 容忍度放大到上限
            double headMaxToleranceFactor = 4.0,     // 容忍度最大放大倍数 (1=不放大)
            double headSettleSeconds = 0.6,          // 头停沉降冻结时长 (秒): 头动期间+头停后此时长内冻结解锁判定 (0=关闭)
            double posToleranceRefDistance = 0.4,    // 距离自适应 (问题2): 此距离 (m) 以内位置容忍不放大
            double posToleranceDistanceSlope = 1.0,  // 每超出 ref 1m, 位置死区/租绳增加的比例 (1/m)
            double posToleranceMaxFactor = 3.0,      // 位置容忍放大上限 (1=关闭距离自适应)
            double lowScoreReleaseScore = 0.3,       // 低分释放 (问题1): 锁定时低于此分
            double lowScoreReleaseSeconds = 0.6)     // 持续低分此时长 → 强制解锁 (0=关闭)
        {
            this.inner = inner;
            this.qualityGateMinScore = qualityGateMinScore;
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
            this.headRotForFullTolerance = Math.Max(headRotForFullTolerance, 1e-3);
            this.headLinForFullTolerance = Math.Max(headLinForFullTolerance, 1e-3);
            this.headMaxToleranceFactor = Math.Max(headMaxToleranceFactor, 1.0);
            this.headSettleSeconds = Math.Max(headSettleSeconds, 0.0);
            this.posToleranceRefDistance = Math.Max(posToleranceRefDistance, 0.0);
            this.posToleranceDistanceSlope = Math.Max(posToleranceDistanceSlope, 0.0);
            this.posToleranceMaxFactor = Math.Max(posToleranceMaxFactor, 1.0);
            this.lowScoreReleaseScore = Math.Min(Math.Max(lowScoreReleaseScore, 0.0), 1.0);
            this.lowScoreReleaseSeconds = Math.Max(lowScoreReleaseSeconds, 0.0);
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
            lowScoreRunSeconds = 0.0;
            hasLastObs = false;
            lastObsPos = Vec3.Zero;
            lastObsRot = Quat.Identity;
            lastObsTime = 0.0;
            hasSpeedEma = false;
            obsSpeedEma = 0.0;
            obsAngSpeedEma = 0.0;
            hasObsConsensus = false;
            obsConsensusPos = Vec3.Zero;
            obsConsensusRot = Quat.Identity;
            wantUnlock = false;
            seamActive = false;
            seamPos = Vec3.Zero;
            seamRot = Vec3.Zero;
            hasRendered = false;
            lastRenderTime = 0.0;
            hasLastHead = false;
            lastHeadPose = Pose.Identity;
            headAngSpeedEma = 0.0;
            headLinSpeedEma = 0.0;
            headToleranceFactor = 1.0;
            headMotionRatio = 0.0;
            headSettleLeftSeconds = 0.0;
            posDistanceFactor = 1.0;
        }

        public void OnObservation(in Observation observation)
        {
            // 可选质量评估门控: 太低分 = 坏 pose, 不喂 inner (Hold 语义: inner 用旧状态继续外推),
            // 也不更新运动证据 (坏帧不该影响静/动判定)。
            if (observation.Score < qualityGateMinScore)
            {
                FramesQualityRejected++;
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

            // --- 头动跟踪 (问题3): 从 HeadPose 差分头部角/线速度, 算容忍度放大系数 ---
            // 头动越大 → head-motion-induced slip 越强 → 观测物体表观运动里"假运动"成分越多,
            // 所以临时放大静止判定/解锁的容忍度, 把 slip 当噪声吸收, 而不是误判成物体真动。
            UpdateHeadMotion(observation, obsDt);

            // --- 头停沉降计时: 头在动 (ratio>eps) → 重置满; 头静止 → 按真实 dt 递减。>0 期间冻结解锁判定 ---
            // 给 obsConsensus 把 head-slip 褪干净的时间, 避免"头一停阈值收紧快于 slip 褪去"的误解锁 (见 UpdateLockedEvidence)。
            if (headMotionRatio > HeadMovingRatioEps)
            {
                headSettleLeftSeconds = headSettleSeconds;
            }
            else
            {
                headSettleLeftSeconds = Math.Max(0.0, headSettleLeftSeconds - obsDt);
            }

            // --- 距离自适应位置容忍 (问题2): 物体越远立体深度噪声越大, 位置容忍按距离放大 (旋转不放大) ---
            posDistanceFactor = ComputePosDistanceFactor(observation, pos);

            // --- 观测共识 (denoised, 死区无关): 低增益 EMA 跟踪真实观测。绝对漂移租绳用它 (而非 creep 后的
            // lockedPose) 度量真实漂移, 故必须在 UpdateLockedEvidence 之前更新。增益按真实 dt 的半衰期换算,
            // 与帧率无关; 复用 evidenceHalfLifeSeconds 作时间常数 (同一"什么算真实运动 vs 噪声"的尺度)。
            UpdateObsConsensus(pos, rot, obsDt);

            // 头动放大后的有效阈值 (头静止时 factor=1, 等于原阈值)。
            double f = headToleranceFactor;
            bool isStatic = obsSpeedEma <= staticEnterSpeed * f
                            && obsAngSpeedEma <= staticEnterAngSpeed * f
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

        /// <summary>
        /// 更新观测共识 (denoised, 死区无关): 对被接受观测做半衰期 EMA。
        /// 与 creep 的关键区别: creep 只在死区内动 (物体一动就停), 共识则*始终*跟随真实观测,
        /// 只是被 EMA 平滑掉单帧噪声/head-slip 尖峰。绝对漂移租绳用它 (相对 anchorOrigin) 度量真实漂移,
        /// 使"慢速持续平移"能如实累积、顶破租绳解锁, 同时单帧噪声被平滑而不误触发。增益帧率无关。
        /// </summary>
        private void UpdateObsConsensus(Vec3 pos, Quat rot, double obsDt)
        {
            if (!hasObsConsensus)
            {
                obsConsensusPos = pos;
                obsConsensusRot = rot.Normalized();
                hasObsConsensus = true;
                return;
            }

            // g = 1 - 0.5^(dt/halfLife): 每过一个半衰期, 共识朝观测靠拢一半。dt=0 (首帧/同刻) → g=0 不动。
            double g = 1.0 - Math.Pow(0.5, obsDt / evidenceHalfLifeSeconds);
            obsConsensusPos += (pos - obsConsensusPos) * g;
            obsConsensusRot = Quat.Slerp(obsConsensusRot, rot, g).Normalized();
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
            // 头动放大系数 (头静止=1)。头动时所有"判物体在动→解锁"的阈值同比放大, 把 head-slip 当噪声吸收。
            double f = headToleranceFactor;

            // 低分释放 (问题1): 锁定时持续低分 → 锁点不可信 (物体被移走/遮挡/跟丢), 强制解锁,
            // 不让 anchor 冻在错 pose 上。解锁后交回 inner + (真机) 由 recovery 低分 reacquire。
            if (lowScoreReleaseSeconds > 0.0 && score < lowScoreReleaseScore)
            {
                lowScoreRunSeconds += obsDt;
                if (lowScoreRunSeconds >= lowScoreReleaseSeconds)
                {
                    wantUnlock = true;
                    return;
                }
            }
            else
            {
                lowScoreRunSeconds = 0.0;
            }

            // 头停沉降冻结 (问题3 续, 真机报告"头扫静止物体后头一停 static 就脱开"): 仅在头*已停下*但沉降计时
            // 未走完的窗口内, 冻结"判物体在动→解锁"的证据 (速度逃逸/漂移租绳/CUSUM)。原因: 头停瞬间 headToleranceFactor
            // 由头速驱动几乎瞬间塌回 1 (阈值收紧), 但 head-slip 还残留在 obsConsensus / 观测速度里 (要按
            // evidenceHalfLifeSeconds 才褪去) → "阈值已收紧、slip 未褪净"的窗口 → 三路误解锁。冻结期清零三路证据,
            // 给 obsConsensus 时间褪 slip 再恢复监测。
            // 关键: *只冻头停窗口, 不冻头动期间*。头动期间物体可能大幅真动 (要它能解锁), 此时靠 headToleranceFactor
            // 抬高阈值吸收 slip 即可——slip 小幅 (~阈值量级)、真动大幅, 抬高的阈值能区分。若头动期间也冻结, 物体大幅真动
            // 会被锁死 (彻底不响应), 与"只增大释放阈值"的设计意图相悖。故 headMotionRatio>eps (头在动) 时不冻。
            // 低分释放不冻结 (独立可靠性信号); creep 也不冻结 (已被 (1-headMotionRatio) 门控)。
            bool headStill = headMotionRatio <= HeadMovingRatioEps;
            bool settleFrozen = headStill && headSettleLeftSeconds > 0.0;

            // 速度逃逸: 观测速度明确超过静止阈值 × 倍数, 连续一段 *时间* → 立即解锁。
            // 这堵住了"慢速真实运动被 creep 跟住、CUSUM 永不越阈"的 false-lock 长尾
            // (PoC 里 onset-lag P90=1500ms 的卡死 case)。速度是比位移更早的运动信号。
            // 头动时阈值放大: 头转带来的 slip 速度不该触发逃逸。冻结期 movingNow 强制 false → movingRunSeconds 清零。
            bool movingNow = !settleFrozen
                             && (obsSpeed > staticEnterSpeed * unlockSpeedFactor * f
                                 || obsAngSpeed > staticEnterAngSpeed * unlockSpeedFactor * f);
            movingRunSeconds = movingNow ? movingRunSeconds + obsDt : 0.0;
            if (movingRunSeconds >= unlockMovingSeconds)
            {
                wantUnlock = true;
                return;
            }

            // 绝对漂移租绳: 相对锁定时刻的*观测共识* anchorOrigin 的总漂移超过租绳 → 解锁。
            // 关键: 漂移用 *观测共识 obsConsensus* (denoised, 死区无关) 度量, 既不用单帧原始观测、也不用 creep 后的 lockedPose:
            //   - 不用原始观测: 噪声大 (静止物体旋转 p90~13°、平移 p90~30mm, 远超 5°/15mm 租绳), 头静止 (f=1) 时单帧
            //     尖峰就频繁误触发解锁 → 锚点"漂一小段又被拉回"的抖动 (问题3, 见 obsConsensus 注释)。
            //   - 不用 lockedPose: 它靠 creep 移动, 而 creep 只在死区内触发; 慢移时观测超死区→creep 停摆→lockedPose
            //     被钉死在 anchorOrigin 上→driftPos 恒≈0→慢移*永不解锁* (即使 unlockDriftMeters=0 也无效, 实测租绳被钉在亚毫米;
            //     真机 dataset 20260619_041332 复现: 10s 锁定段 lockedPose 只动 0.58mm 而观测漂 42mm)。
            //   obsConsensus 是死区无关的低增益 EMA: 平滑掉单帧噪声/head-slip (保留问题3 免疫), 又如实跟随真实持续位移,
            //   因此慢移会被如实累积、顶破租绳正常解锁。这恢复了 unlockDriftMeters 作为"慢移逃逸灵敏度"旋钮的作用。
            // 头动时租绳放大: 头转造成的 world-pose slip 漂移不该触发解锁; 头静止时回到原租绳, 真实慢移正常逃逸。
            // 位置租绳再乘 posDistanceFactor (问题2): 远处深度噪声大, 位置租绳同比放宽; 旋转租绳不随距离变 (旋转噪声与距离无关)。
            double driftPos = Vec3.Distance(obsConsensusPos, anchorOrigin.Position);
            double driftRot = Quat.AngleDegrees(obsConsensusRot, anchorOrigin.Rotation);
            if (!settleFrozen && (driftPos > unlockDriftMeters * f * posDistanceFactor || driftRot > unlockDriftDegrees * f))
            {
                wantUnlock = true;
                return;
            }

            double dPos = Vec3.Distance(pos, lockedPose.Position);
            double dRot = Quat.AngleDegrees(rot, lockedPose.Rotation);

            // CUSUM (帧率无关): 每观测先按真实 dt 做半衰期衰减 (漏积分), 再累积"超出死区"的部分。
            // 累积量乘 (obsDt / refObsIntervalSeconds): 同样的持续运动, 不论 5fps 还是 12fps, 单位时间攒到的证据相同。
            // 死区随头动放大: 头转时观测抖动大, 死区放宽吸收 slip; 头静止时回到原死区。
            // 位置死区再乘 posDistanceFactor (问题2): 远处位置噪声大, 位置死区同比放宽; 旋转死区不随距离变。
            double dbPos = deadbandPos * f * posDistanceFactor;
            double dbRot = deadbandRot * f;
            if (!settleFrozen)
            {
                double decay = Math.Pow(0.5, obsDt / evidenceHalfLifeSeconds);
                double accScale = obsDt / refObsIntervalSeconds;
                evidencePos = decay * evidencePos + accScale * score * Math.Max(0.0, dPos - dbPos);
                evidenceRot = decay * evidenceRot + accScale * score * Math.Max(0.0, dRot - dbRot);

                if (evidencePos > unlockEvidencePos || evidenceRot > unlockEvidenceRot)
                {
                    wantUnlock = true; // 在下一帧 PredictAt 提交 (拿 inner(now) 做接缝)
                    return;
                }
            }
            else
            {
                // 沉降冻结期: CUSUM 证据清零, 头停后从干净状态重新累积 (slip 期间攒的假证据不该带过窗口)。
                evidencePos = 0.0;
                evidenceRot = 0.0;
            }

            // 漏锁 creep: 仅当位移在死区内 (纯噪声/极慢漂移) 才朝观测缓慢靠拢,
            // 精修锁点为 score 加权质心 + 跟住极慢真实漂移而不抖。死区外不 creep (那是在攒解锁证据)。
            // creep 增益按真实 dt 的半衰期换算成"每观测比例", 与帧率无关。
            // 头动门控: 增益乘 (1 - headMotionRatio)。头动时 head-motion slip 让"静止物体"的观测 pose 出现
            // *系统性偏置* (非零均值噪声), 且死区被 headToleranceFactor 放大 → 偏置观测更易落进死区触发 creep →
            // creep 单向朝偏置靠拢, 多帧累积成 lockedPose 净漂移, 头停后还要按 creepHalfLife 慢慢爬回 (真机报告:
            // 头动观察静止物体后锚点偏移且不立即复位)。漂移租绳用 obsConsensus (EMA 可回中) 不受此影响, 但 creep
            // 改的是输出本身, 漂移会实打实留下。故头动越快 creep 越弱、ratio=1 时完全冻结锁点; 头静止满增益照常精修。
            if (dPos < dbPos && dRot < dbRot)
            {
                double g = (1.0 - Math.Pow(0.5, obsDt / creepHalfLifeSeconds)) * score * (1.0 - headMotionRatio);
                Vec3 newPos = lockedPose.Position + (pos - lockedPose.Position) * g;
                Quat newRot = Quat.Slerp(lockedPose.Rotation, rot, g);
                lockedPose = new Pose(newPos, newRot.Normalized());
            }
        }

        /// <summary>
        /// 距离自适应位置容忍系数 (问题2): factor = clamp(1 + slope·(dist − ref), 1, max),
        /// dist = 观测物体到头部的距离。ref 以内 (近处) factor=1 不放大; 越远越大, max 封顶。
        /// 无头部 pose 或功能关闭 (max≤1) → 返回 1。只缩放位置通道, 旋转不受影响。
        /// </summary>
        private double ComputePosDistanceFactor(in Observation observation, Vec3 objectPos)
        {
            if (!observation.HasHeadPose || posToleranceMaxFactor <= 1.0)
            {
                return 1.0;
            }

            double dist = Vec3.Distance(objectPos, observation.HeadPose.Position);
            double factor = 1.0 + posToleranceDistanceSlope * (dist - posToleranceRefDistance);
            return Math.Min(Math.Max(factor, 1.0), posToleranceMaxFactor);
        }

        /// <summary>从 HeadPose obs-to-obs 差分头部角/线速度, 更新头动容忍放大系数 headToleranceFactor。</summary>
        private void UpdateHeadMotion(in Observation observation, double obsDt)
        {
            if (!observation.HasHeadPose || headMaxToleranceFactor <= 1.0)
            {
                headToleranceFactor = 1.0; // 无头部数据或功能关闭 → 不放大
                headMotionRatio = 0.0;     // 头动门控关闭 → creep 不被头动抑制 (原行为)
                return;
            }

            Pose head = observation.HeadPose;
            if (hasLastHead && obsDt > 1e-4)
            {
                double linSpeed = Vec3.Distance(head.Position, lastHeadPose.Position) / obsDt;
                double angSpeed = Quat.AngleDegrees(head.Rotation, lastHeadPose.Rotation) / obsDt;
                // EMA 平滑 (单帧头部噪声不该瞬间翻转容忍度)
                headLinSpeedEma += 0.5 * (linSpeed - headLinSpeedEma);
                headAngSpeedEma += 0.5 * (angSpeed - headAngSpeedEma);
            }
            hasLastHead = true;
            lastHeadPose = head;

            // 头速归一: 角速度/线速度各除以"吃满"基准, 取较大者; factor = 1 + ratio*(max-1), 上限 max。
            double ratio = Math.Max(headAngSpeedEma / headRotForFullTolerance, headLinSpeedEma / headLinForFullTolerance);
            ratio = Math.Min(Math.Max(ratio, 0.0), 1.0);
            headMotionRatio = ratio;        // 供 creep 头动门控用 (头动越快 creep 越弱, 见 UpdateLockedEvidence)
            headToleranceFactor = 1.0 + ratio * (headMaxToleranceFactor - 1.0);
        }

        private void EnterLock(Pose innerPose)
        {
            locked = true;
            LockEnters++;
            lockedPose = innerPose;
            // 绝对漂移租绳参考 = 锁定时刻的*观测共识* (denoised), 不是 inner 输出。
            // inner 含 smoothing/预测的偏置, 与 obs 不同源; 用 obs 共识做 origin 才能让
            // "漂移 = 真实观测相对锁定位的位移", 使 unlockDriftMeters 量纲正确。
            // 共识尚未建立 (理论上不会, OnObservation 必先于 EnterLock) 时退化用 inner 输出。
            anchorOrigin = hasObsConsensus
                ? new Pose(obsConsensusPos, obsConsensusRot)
                : innerPose;
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
