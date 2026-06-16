using EgoAnchor.Diagnostics;
using EgoAnchor.Runtime;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Unity 侧 anchor policy 宿主 (重构后)。
    ///
    /// 职责收敛为三件事：
    ///   1. 持有两个可自由组合的模块：MotionModel (运动模型) + SmoothingStrategy (平滑策略)；
    ///   2. 维护 anchor 生命周期状态机 (Tracking / Coasting / Lost / Reacquire ...)；
    ///   3. 把观测喂给模块，并每渲染帧产出平滑 pose。
    ///
    /// 旧的 Gate / Estimator / Output 三模块拆分已移除。score-gating (拒绝低分/跳变坏观测)
    /// 作为本 host 的可选内联功能 (默认关闭)，只有 EgoAnchor 方法需要时才在 Inspector 打开，
    /// 不再是独立模块。每帧平滑由 SmoothingStrategy 负责 (外推+残差融合 或 延迟插值)，
    /// 不再靠运动模型内部限幅 predict-ahead，因此低频 pose 也能逐帧连续输出。
    /// </summary>
    public sealed class AnchorPolicyHost : MonoBehaviour
    {
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<AnchorPolicyHost>();

        /// <summary>运动模型模块 (CV / Kalman / OneEuro)。</summary>
        [Header("Modules (free 3x2 combination)")]
        [Tooltip("运动模型模块：只能挂 MotionModel 子类 (ConstantVelocityModel / KalmanModel / OneEuroModel)。负责去噪 + 估计速度 + 外推。")]
        [SerializeField] private MotionModel motionModel;

        /// <summary>平滑策略模块 (Blend / DelayedInterp)。</summary>
        [Tooltip("平滑策略模块：只能挂 SmoothingStrategy 子类 (BlendStrategy=零延迟外推+残差融合 / DelayedInterpStrategy=延迟一周期+插值)。负责把低频 pose 变高频平滑。")]
        [SerializeField] private SmoothingStrategy smoothingStrategy;

        /// <summary>策略 label；为空时用 "model+strategy" 自动拼。</summary>
        [Tooltip("策略 label，写入 eval；为空时自动用 \"<model>_<strategy>\"。")]
        [SerializeField] private string strategyLabel = "";

        /// <summary>是否启用 score/jump 门控 (拒绝坏观测)。只建议 EgoAnchor 方法开启。</summary>
        [Header("Score Gate (EgoAnchor only, optional)")]
        [Tooltip("是否启用 score/jump 门控：拒绝低可靠分或大跳变的坏观测。baseline 应关闭 (照单全收)；EgoAnchor 方法开启以证明鲁棒性。默认关闭。")]
        [SerializeField] private bool enableScoreGate = false;

        /// <summary>接受观测所需的最低可靠性分数。</summary>
        [Tooltip("接受观测所需的最低可靠性分数 (0..1)。低于此值的观测被拒绝、不更新模型。仅在启用门控时生效。默认 0.2。")]
        [Range(0f, 1f)]
        [SerializeField] private float minScore = 0.2f;

        /// <summary>判定坏跳变的平移阈值，单位米。</summary>
        [Tooltip("判定坏跳变的平移阈值 (米)：新观测相对当前预测的平移超过此值则拒绝。仅在启用门控时生效。默认 0.8。")]
        [SerializeField] private float maxJumpMeters = 0.8f;

        /// <summary>判定坏跳变的旋转阈值，单位度。</summary>
        [Tooltip("判定坏跳变的旋转阈值 (度)：新观测相对当前预测的旋转超过此值则拒绝。仅在启用门控时生效。默认 120。")]
        [SerializeField] private float maxJumpDegrees = 120f;

        /// <summary>是否启用静止锁定 (EgoAnchor 核心方法层)。</summary>
        [Header("Static Lock (EgoAnchor 核心方法, optional)")]
        [Tooltip("是否启用静止锚定稳定器：物体静止且高分时冻结输出 pose，把小抖动当噪声吸收 → 看上去一动不动；运动时交回 smoothing。baseline 关、EgoAnchor 开。默认关闭。")]
        [SerializeField] private bool enableStaticLock = false;

        /// <summary>进入静止判定的线速度阈值，单位 m/s。</summary>
        [Tooltip("进入静止判定的观测线速度阈值 (m/s)。必须设在观测噪声地板之上 (5090@12fps 平移噪声地板 ~14mm/s)。默认 0.05。")]
        [SerializeField] private float staticLockEnterSpeedMps = 0.05f;

        /// <summary>进入静止判定的角速度阈值，单位 deg/s。</summary>
        [Tooltip("进入静止判定的观测角速度阈值 (deg/s)。设太低 (低于旋转噪声地板) 会导致永不锁定 (5090@12fps 旋转噪声地板 ~15°/s)。默认 35。")]
        [SerializeField] private float staticLockEnterAngSpeedDps = 35.0f;

        /// <summary>进入锁定需连续保持静止的时间，单位秒 (帧率无关)。</summary>
        [Tooltip("进入锁定需连续保持静止 (+高分) 的时间 (秒)。防静止判定抖动。帧率无关。默认 0.35。")]
        [SerializeField] private float staticLockDwellSeconds = 0.35f;

        /// <summary>进入锁定所需的最低可靠性分数。</summary>
        [Tooltip("进入/维持锁定所需的最低可靠性分数 (0..1)。设太高 (高于物体常见分) 会永不锁定。默认 0.25。")]
        [Range(0f, 1f)]
        [SerializeField] private float staticLockMinScore = 0.25f;

        /// <summary>锁定时位置死区，单位米。</summary>
        [Tooltip("锁定时位置死区 (米)：观测相对锁点位移小于此值视为噪声、忽略。杀静止抖动的核心。默认 0.008。")]
        [SerializeField] private float staticLockDeadbandMeters = 0.008f;

        /// <summary>锁定时旋转死区，单位度。</summary>
        [Tooltip("锁定时旋转死区 (度)：旋转小于此值视为噪声、忽略。默认 3。")]
        [SerializeField] private float staticLockDeadbandDegrees = 3.0f;

        /// <summary>解锁位置证据阈值 (score 加权 CUSUM)，单位米。</summary>
        [Tooltip("解锁位置证据阈值 (score 加权累计的超死区位移, 米)。越大越粘 (难解锁), 越小越灵敏。默认 0.08。")]
        [SerializeField] private float staticLockUnlockEvidenceMeters = 0.08f;

        /// <summary>解锁旋转证据阈值 (score 加权 CUSUM)，单位度。</summary>
        [Tooltip("解锁旋转证据阈值 (score 加权累计的超死区旋转, 度)。越大越粘。默认 20。")]
        [SerializeField] private float staticLockUnlockEvidenceDegrees = 20.0f;

        /// <summary>绝对漂移解锁租绳 (平移)，单位米。</summary>
        [Tooltip("绝对漂移租绳 (米)：相对锁定原点的总平移超此值直接解锁。修复'极慢平移被 creep 吃掉、永不脱离 static'。越小越早跟随慢移。默认 0.015。")]
        [SerializeField] private float staticLockUnlockDriftMeters = 0.015f;

        /// <summary>绝对漂移解锁租绳 (旋转)，单位度。</summary>
        [Tooltip("绝对漂移租绳 (度)：相对锁定原点的总旋转超此值直接解锁。修复极慢旋转永不脱离。默认 5。")]
        [SerializeField] private float staticLockUnlockDriftDegrees = 5.0f;

        /// <summary>解锁证据半衰期，单位秒 (帧率无关)。</summary>
        [Tooltip("解锁证据半衰期 (秒, 帧率无关漏积分)：偶发噪声会漏掉, 只有持续运动才累积越阈。越大越粘。默认 0.27。")]
        [SerializeField] private float staticLockEvidenceHalfLifeSeconds = 0.27f;

        /// <summary>漏锁 creep 半衰期，单位秒 (帧率无关)。</summary>
        [Tooltip("漏锁 creep 半衰期 (秒, 帧率无关)：锁定时朝高分小位移观测缓慢靠拢, 精修锁点 + 跟极慢漂移。越小靠拢越快。默认 2.7。")]
        [SerializeField] private float staticLockCreepHalfLifeSeconds = 2.7f;

        /// <summary>解锁后禁止再锁的时间，单位秒 (反 chatter, 帧率无关)。</summary>
        [Tooltip("解锁后禁止再锁的时间 (秒, 反 chatter)：给真实运动一个逃逸窗口, 防锁定频繁翻转。帧率无关。默认 1.0。")]
        [SerializeField] private float staticLockRelockSuppressSeconds = 1.0f;

        /// <summary>速度逃逸倍数。</summary>
        [Tooltip("速度逃逸倍数：锁定时观测速度 > 静止阈值 × 此倍数 连续一段时间 → 立即解锁 (堵 CUSUM 跟不上的慢运动 false-lock 长尾)。越大越粘。默认 2.5。")]
        [SerializeField] private float staticLockUnlockSpeedFactor = 2.5f;

        /// <summary>速度逃逸需连续运动的时间，单位秒 (帧率无关)。</summary>
        [Tooltip("速度逃逸需连续检测到明确运动的时间 (秒)。防单帧噪声误解锁。帧率无关。默认 0.4。")]
        [SerializeField] private float staticLockUnlockMovingSeconds = 0.4f;

        /// <summary>解锁接缝残差衰减 (60fps 基准, 已帧率无关)。</summary>
        [Tooltip("解锁接缝残差每帧衰减比例 (60fps 基准, 已按 dt 归一)：解锁瞬间从锁点平滑收敛到 smoothing 输出, 防 pop。越大释放越柔、越不卡。默认 0.85。")]
        [Range(0.5f, 0.99f)]
        [SerializeField] private float staticLockSeamDecayPerFrame = 0.85f;

        /// <summary>CUSUM 累积时间归一基准，单位秒。</summary>
        [Tooltip("CUSUM 证据累积的时间归一基准 (秒)：通常设为标定时的观测周期 (5fps=0.2)。改它等比缩放所有解锁灵敏度。默认 0.2。")]
        [SerializeField] private float staticLockRefObsIntervalSeconds = 0.2f;

        /// <summary>短时无可靠测量的 coasting 时长，单位秒。</summary>
        [Header("Lifecycle")]
        [Tooltip("短时无可靠测量时保持 Coasting (继续外推/插值) 的时长，单位秒。超过则进入更不确定状态。默认 0.45。")]
        [SerializeField] private float coastTimeoutSeconds = 0.45f;

        /// <summary>长时间无可靠测量后进入 Lost 的时长，单位秒。</summary>
        [Tooltip("长时间无可靠测量后进入 Lost (停止输出) 的时长，单位秒。必须大于 coast。默认 2.0。")]
        [SerializeField] private float lostTimeoutSeconds = 2.0f;

        /// <summary>判定静止的线速度阈值，单位 m/s。</summary>
        [Tooltip("判定运动/静止的线速度阈值，单位 m/s；仅用于 motionState 诊断。默认 0.015。")]
        [SerializeField] private float staticSpeedThresholdMps = 0.015f;

        /// <summary>判定静止的角速度阈值，单位 deg/s。</summary>
        [Tooltip("判定运动/静止的角速度阈值，单位 deg/s；仅用于 motionState 诊断。默认 1.5。")]
        [SerializeField] private float staticAngularSpeedThresholdDps = 1.5f;

        private AnchorStateMachine stateMachine;
        private readonly StaticLockController staticLock = new StaticLockController();
        private PoseToAnchorRuntime boundOwner;
        private double lastAcceptedTimeSeconds = -1.0;
        private double lastAdvanceTimeSeconds = -1.0;
        private float latestAcceptedScore = 1.0f;
        private AnchorMotionState motionState = AnchorMotionState.Unknown;
        private GateDecision latestGateDecision = GateDecision.Hold("initialized");
        private float predictAheadSeconds;

        /// <summary>eval 使用的策略 label。</summary>
        public string StrategyLabel
        {
            get
            {
                if (!string.IsNullOrEmpty(strategyLabel))
                {
                    return strategyLabel;
                }

                return $"{ModelName}_{StrategyName}";
            }
        }

        /// <summary>运动模型名 (CV / Kalman / OneEuro)。写入 eval 的 motion_model 字段。</summary>
        public string MotionModelName => motionModel != null ? motionModel.ModelName : "";

        /// <summary>平滑策略名 (Blend / DelayedInterp / RawPassthrough)。写入 eval 的 smoothing_strategy 字段。</summary>
        public string SmoothingStrategyName => smoothingStrategy != null ? smoothingStrategy.StrategyName : "";

        /// <summary>门控名 (启用时 score_jump_gate，否则 null_gate)。写入 eval 的 gate 字段。</summary>
        public string GateName => enableScoreGate ? "score_jump_gate" : "null_gate";

        /// <summary>运动模型组件引用，仅用于 eval 配置摘要。</summary>
        public MotionModel MotionModel => motionModel;

        /// <summary>平滑策略组件引用，仅用于 eval 配置摘要。</summary>
        public SmoothingStrategy SmoothingStrategy => smoothingStrategy;

        private string ModelName => motionModel != null ? motionModel.ModelName : "none";
        private string StrategyName => smoothingStrategy != null ? smoothingStrategy.StrategyName : "none";

        /// <summary>当前 anchor 生命周期状态。</summary>
        public AnchorState State
        {
            get
            {
                EnsureStateMachine();
                return stateMachine.State;
            }
        }

        /// <summary>当前运动状态。</summary>
        public AnchorMotionState MotionState => motionState;

        /// <summary>当前估计线速度模长，单位 m/s。</summary>
        public float SpeedMps => motionModel != null ? motionModel.LinearVelocity.magnitude : 0.0f;

        /// <summary>当前估计角速度模长，单位 deg/s。</summary>
        public float AngularSpeedDps => motionModel != null ? motionModel.AngularVelocityRad.magnitude * Mathf.Rad2Deg : 0.0f;

        /// <summary>最近一次 Advance 使用的前推时长，单位秒。</summary>
        public float PredictAheadSeconds => predictAheadSeconds;

        /// <summary>最近一次被接受测量的可靠性分数。</summary>
        public float LatestAcceptedScore => latestAcceptedScore;

        /// <summary>最近一次 gate/policy 动作。</summary>
        public AnchorPolicyAction LatestAction => latestGateDecision.ToPolicyAction();

        /// <summary>最近一次 gate/policy 原因。</summary>
        public string LatestReason => latestGateDecision.Reason;

        /// <summary>output stage 平移残差 (新架构不单独整形，返回 NaN 兼容 eval)。</summary>
        public float LatestResidualMeters => float.NaN;

        /// <summary>output stage 旋转残差 (新架构不单独整形，返回 NaN 兼容 eval)。</summary>
        public float LatestResidualDegrees => float.NaN;

        /// <summary>是否静止锁定 (EgoAnchor 静态锚定稳定器当前是否冻结输出)。</summary>
        public bool LatestStaticLocked => enableStaticLock && staticLock.IsLocked;

        /// <summary>累计接受测量数。</summary>
        public long AcceptedCount { get; private set; }

        /// <summary>累计拒绝测量数。</summary>
        public long RejectedCount { get; private set; }

        private void Awake()
        {
            EnsureStateMachine();
            ResetModules();
            if (motionModel == null || smoothingStrategy == null)
            {
                Log.Warning("AnchorPolicyHost 未绑定 MotionModel 或 SmoothingStrategy；该 host 不会输出 pose。", this);
            }
        }

        private void OnValidate()
        {
            if (coastTimeoutSeconds <= 0.0f)
            {
                coastTimeoutSeconds = 0.45f;
            }

            if (lostTimeoutSeconds <= coastTimeoutSeconds)
            {
                lostTimeoutSeconds = coastTimeoutSeconds * 3.0f;
            }
        }

        /// <summary>绑定唯一 runtime。模块内含状态，不能被多个 runtime 共享。</summary>
        public void Bind(PoseToAnchorRuntime owner)
        {
            EnsureStateMachine();
            if (owner == null)
            {
                return;
            }

            if (boundOwner != null && boundOwner != owner)
            {
                Log.Error($"AnchorPolicyHost 已绑定 {boundOwner.name}，拒绝再绑定 {owner.name}；每个 runtime 需要独立 host。", this);
                return;
            }

            boundOwner = owner;
        }

        /// <summary>输入一帧测量并返回分类决策。不输出 stable pose。</summary>
        public AnchorPolicyDecision AcceptPose(in AnchorObservation observation)
        {
            EnsureReady();
            double now = observation.MeasurementTimeSeconds;

            if (!observation.HasAlignedPose)
            {
                OnMissingObservation(now, observation.FailureReason);
                latestGateDecision = GateDecision.Hold(string.IsNullOrEmpty(observation.FailureReason) ? "missing_pose" : observation.FailureReason);
                return new AnchorPolicyDecision(latestGateDecision.ToPolicyAction(), stateMachine.State, latestGateDecision.Reason);
            }

            // 可选 score/jump 门控 (仅 EgoAnchor 方法开启)
            if (ShouldRejectObservation(observation, now, out string rejectReason))
            {
                RejectedCount++;
                latestGateDecision = GateDecision.Reject(rejectReason);
                stateMachine.OnUncertainPose(now, rejectReason);
                return new AnchorPolicyDecision(AnchorPolicyAction.Reject, stateMachine.State, rejectReason);
            }

            // 首帧或重定位后 Snap，否则正常更新
            bool snap = !motionModel.HasState;
            if (snap)
            {
                motionModel.Snap(observation);
                latestGateDecision = GateDecision.Snap("snap");
            }
            else
            {
                motionModel.UpdateState(observation);
                latestGateDecision = GateDecision.Accept("accept");
            }

            smoothingStrategy.OnObservation(motionModel, observation);

            // EgoAnchor 静态锚定稳定器: 喂同一 world pose + score, 更新静/动证据 (仅启用时)。
            if (enableStaticLock)
            {
                ConfigureStaticLock();
                staticLock.OnObservation(observation.WorldPose, observation.ReliabilityScore, observation.MeasurementTimeSeconds);
            }

            AcceptedCount++;
            lastAcceptedTimeSeconds = now;
            latestAcceptedScore = observation.ReliabilityScore;
            stateMachine.OnReliablePose(now, latestGateDecision.Reason);
            UpdateMotionState();

            return new AnchorPolicyDecision(latestGateDecision.ToPolicyAction(), stateMachine.State, latestGateDecision.Reason);
        }

        /// <summary>每渲染帧输出当前 stable pose。</summary>
        public AnchorPolicyOutput Advance(double nowSeconds)
        {
            EnsureReady();
            if (!motionModel.HasState)
            {
                stateMachine.OnMissingPose(nowSeconds, double.PositiveInfinity, false, "no_estimate");
                return AnchorPolicyOutput.None(stateMachine.State, "no_estimate");
            }

            double gap = lastAcceptedTimeSeconds >= 0.0 ? Mathf.Max((float)(nowSeconds - lastAcceptedTimeSeconds), 0.0f) : 0.0;
            if (lastAcceptedTimeSeconds < 0.0)
            {
                stateMachine.OnMissingPose(nowSeconds, double.PositiveInfinity, false, "no_reliable_pose");
            }
            else if (gap > 0.0 && stateMachine.State != AnchorState.Paused)
            {
                stateMachine.OnMissingPose(nowSeconds, gap, true, "stale_measurement");
            }

            if (stateMachine.State == AnchorState.Lost || stateMachine.State == AnchorState.Error || stateMachine.State == AnchorState.Searching)
            {
                return AnchorPolicyOutput.None(stateMachine.State, stateMachine.LastEvent.Reason);
            }

            Pose pose = smoothingStrategy.Output(motionModel, nowSeconds);

            // EgoAnchor 静态锚定稳定器: 锁定时冻结输出, 解锁过渡平滑收敛, 否则透传 (仅启用时)。
            if (enableStaticLock)
            {
                ConfigureStaticLock();
                float advanceDt = lastAdvanceTimeSeconds >= 0.0 ? (float)(nowSeconds - lastAdvanceTimeSeconds) : 0.0f;
                pose = staticLock.Stabilize(pose, advanceDt);
            }

            lastAdvanceTimeSeconds = nowSeconds;
            predictAheadSeconds = (float)gap;
            UpdateMotionState();
            return new AnchorPolicyOutput(true, pose, stateMachine.State, motionState, predictAheadSeconds, stateMachine.LastEvent.Reason);
        }

        /// <summary>reset command/status 到达时清空 policy。</summary>
        public void NotifyReset(double sampleTimeSeconds, string reason)
        {
            ResetModules();
            stateMachine.OnReset(sampleTimeSeconds, reason ?? "reset");
            latestGateDecision = GateDecision.Hold(reason ?? "reset");
        }

        /// <summary>reacquire command/status 到达时进入 Relocalizing 并清空估计。</summary>
        public void NotifyReacquire(double sampleTimeSeconds, string reason)
        {
            ResetModules();
            stateMachine.OnReacquire(sampleTimeSeconds, reason ?? "reacquire");
            latestGateDecision = GateDecision.Hold(reason ?? "reacquire");
        }

        /// <summary>暂停本地 policy。</summary>
        public void NotifyPause(double sampleTimeSeconds, string reason)
        {
            stateMachine.OnPause(sampleTimeSeconds, reason ?? "pause");
            latestGateDecision = GateDecision.Hold(reason ?? "pause");
        }

        /// <summary>恢复本地 policy。</summary>
        public void NotifyResume(double sampleTimeSeconds, string reason)
        {
            stateMachine.OnResume(sampleTimeSeconds, reason ?? "resume");
            latestGateDecision = GateDecision.Hold(reason ?? "resume");
        }

        /// <summary>通知本地目标丢失。</summary>
        public void NotifyLost(double sampleTimeSeconds, string reason)
        {
            stateMachine.OnMissingPose(sampleTimeSeconds, stateMachine.LostTimeoutSeconds, motionModel != null && motionModel.HasState, reason ?? "lost");
            latestGateDecision = GateDecision.Hold(reason ?? "lost");
        }

        /// <summary>通知本地错误。</summary>
        public void NotifyError(double sampleTimeSeconds, string reason)
        {
            stateMachine.OnError(sampleTimeSeconds, reason ?? "error");
            latestGateDecision = GateDecision.Reject(reason ?? "error");
        }

        /// <summary>清空状态机和所有模块。</summary>
        public void Clear(double sampleTimeSeconds, string reason)
        {
            ResetModules();
            stateMachine.Clear(sampleTimeSeconds, reason ?? "clear");
            latestGateDecision = GateDecision.Hold(reason ?? "clear");
        }

        private bool ShouldRejectObservation(in AnchorObservation observation, double now, out string reason)
        {
            reason = string.Empty;
            if (!enableScoreGate)
            {
                return false;
            }

            if (observation.ReliabilityScore < minScore)
            {
                reason = "low_score";
                return true;
            }

            // 跳变检测：与当前预测比较 (需已有状态，且不是重定位帧)
            if (motionModel.HasState && !observation.IsRelocalization)
            {
                Pose predicted = motionModel.PredictAt(now);
                float dPos = Vector3.Distance(predicted.position, observation.WorldPose.position);
                float dDeg = AnchorMath.AngleDegrees(predicted.rotation, observation.WorldPose.rotation);
                if (dPos > maxJumpMeters || dDeg > maxJumpDegrees)
                {
                    reason = "jump";
                    return true;
                }
            }

            return false;
        }

        private void OnMissingObservation(double nowSeconds, string reason)
        {
            double gap = lastAcceptedTimeSeconds >= 0.0 ? nowSeconds - lastAcceptedTimeSeconds : double.PositiveInfinity;
            stateMachine.OnMissingPose(nowSeconds, gap, motionModel != null && motionModel.HasState, string.IsNullOrEmpty(reason) ? "missing_pose" : reason);
        }

        private void UpdateMotionState()
        {
            if (motionModel == null || !motionModel.HasState)
            {
                motionState = AnchorMotionState.Unknown;
                return;
            }

            motionState = SpeedMps <= staticSpeedThresholdMps && AngularSpeedDps <= staticAngularSpeedThresholdDps
                ? AnchorMotionState.Static
                : AnchorMotionState.Moving;
        }

        private void ResetModules()
        {
            motionModel?.ResetModel();
            smoothingStrategy?.ResetStrategy();
            staticLock.Reset();
            lastAcceptedTimeSeconds = -1.0;
            lastAdvanceTimeSeconds = -1.0;
            latestAcceptedScore = 1.0f;
            motionState = AnchorMotionState.Unknown;
            predictAheadSeconds = 0.0f;
            AcceptedCount = 0;
            RejectedCount = 0;
        }

        private void EnsureReady()
        {
            EnsureStateMachine();
            if (motionModel == null || smoothingStrategy == null)
            {
                throw new System.InvalidOperationException("AnchorPolicyHost 需要绑定 MotionModel 和 SmoothingStrategy。");
            }
        }

        /// <summary>把 Inspector 上的静止锁参数推给控制器 (Inspector 可能运行时改, 每次喂/输出前同步)。</summary>
        private void ConfigureStaticLock()
        {
            staticLock.Configure(
                staticLockEnterSpeedMps,
                staticLockEnterAngSpeedDps,
                staticLockDwellSeconds,
                staticLockMinScore,
                staticLockDeadbandMeters,
                staticLockDeadbandDegrees,
                staticLockUnlockEvidenceMeters,
                staticLockUnlockEvidenceDegrees,
                staticLockUnlockDriftMeters,
                staticLockUnlockDriftDegrees,
                staticLockEvidenceHalfLifeSeconds,
                staticLockCreepHalfLifeSeconds,
                staticLockRelockSuppressSeconds,
                staticLockUnlockSpeedFactor,
                staticLockUnlockMovingSeconds,
                staticLockSeamDecayPerFrame,
                staticLockRefObsIntervalSeconds);
        }

        private void EnsureStateMachine()
        {
            if (stateMachine == null)
            {
                if (lostTimeoutSeconds <= coastTimeoutSeconds)
                {
                    lostTimeoutSeconds = coastTimeoutSeconds * 3.0f;
                }

                stateMachine = new AnchorStateMachine(coastTimeoutSeconds, lostTimeoutSeconds);
            }
        }
    }
}
