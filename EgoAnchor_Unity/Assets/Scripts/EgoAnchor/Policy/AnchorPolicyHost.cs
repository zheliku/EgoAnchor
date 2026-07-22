using System;
using EgoAnchor.Diagnostics;
using EgoAnchor.Runtime;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Unity 侧 anchor policy 宿主。
    ///
    /// 职责收敛为三件事：
    ///   1. 持有两个可自由组合的模块：MotionModel (运动模型) + SmoothingStrategy (平滑策略)；
    ///   2. 维护 anchor 生命周期状态机 (Tracking / Coasting / Lost / Reacquire ...)；
    ///   3. 把观测喂给模块，并每渲染帧产出平滑 pose。
    ///
    /// VCD 观测接纳门控作为本 host 的可选内联功能 (默认关闭)，
    /// 完整 EgoAnchor 配置需要时在 Inspector 打开。每帧平滑由 SmoothingStrategy 负责 (外推+残差融合 或 延迟插值)，
    /// 不再靠运动模型内部限幅 predict-ahead，因此低频 pose 也能逐帧连续输出。
    /// </summary>
    public sealed class AnchorPolicyHost : MonoBehaviour
    {
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<AnchorPolicyHost>();

        /// <summary>运动模型模块 (CV / Kalman / OneEuro)。</summary>
        [Header("Modules")]
        [Tooltip("运动模型模块：只能挂 MotionModel 子类 (ConstantVelocityModel / KalmanModel / OneEuroModel)。负责去噪 + 估计速度 + 外推。")]
        [SerializeField] private MotionModel motionModel;

        /// <summary>逐帧输出策略模块。</summary>
        [Tooltip("输出策略模块：只能挂 SmoothingStrategy 子类；正式链路使用 Hold、PredictToNow、LinearSlerp 或 CausalPrediction。")]
        [SerializeField] private SmoothingStrategy smoothingStrategy;

        /// <summary>策略 label；为空时用 "model+strategy" 自动拼。</summary>
        [Tooltip("策略 label，写入 eval；为空时自动用 \"<model>_<strategy>\"。")]
        [SerializeField] private string strategyLabel = "";

        /// <summary>是否启用 VCD 观测接纳门控。</summary>
        [Header("Quality Gate (optional)")]
        [Tooltip("是否启用 VCD 观测接纳门控：拒绝低可靠分的观测。Arrival-Hold 与 Capture-Hold 关闭；One-Euro Anchor、完整 EgoAnchor 和策略候选开启；组件消融按实验定义配置。默认关闭。")]
        [SerializeField] private bool enableQualityGate = false;

        /// <summary>接受观测所需的最低可靠性分数。</summary>
        [Tooltip("接受观测所需的最低可靠性分数 (0..1)。低于此值的观测被拒绝、不更新模型。仅在启用门控时生效。默认 0.2。")]
        [Range(0f, 1f)]
        [SerializeField] private float minQualityScore = 0.2f;

        /// <summary>EgoAnchor 静止锚定方法模块 (可选)。剥离自本 host, 持有静止锁参数和控制器。</summary>
        [Header("Static Anchoring (EgoAnchor 方法, optional)")]
        [Tooltip("EgoAnchor 静止锚定方法模块 (EgoAnchorStaticLockModule)。拖入并 enabled = EgoAnchor 方法 (静止冻结/头动感知/低分释放); 留空或不启用 = 纯 baseline (motion × smoothing)。挂在同一 GameObject 上。")]
        [SerializeField] private EgoAnchorStaticLockModule staticLockModule;

        /// <summary>短时无可靠测量的 coasting 时长，单位秒。</summary>
        [Header("Lifecycle")]
        [Tooltip("短时无可靠测量时保持 Coasting (继续外推/插值) 的时长，单位秒。超过则进入更不确定状态。默认 0.45。")]
        [SerializeField] private float coastTimeoutSeconds = 0.45f;

        /// <summary>判定 pose 是否"可靠"的总分下限：决定 Tracking vs 低分降级，并决定是否刷新可靠时间戳。0 = 关闭。</summary>
        [Tooltip("判定 pose 可靠的 reliability 总分下限 (0..1)。0 = 关闭分数参与状态判定 (baseline 原语义: 收到 pose 即 Tracking, 照单全收, 永不因低分降级/Lost)，多变体对照应保持 0 以免 Lost 停输出污染轨迹。>0 启用: ≥ 它 = 可靠 → Tracking 并刷新可靠时间戳; < 它 = 不可靠 → 不刷新时间戳, gap 持续累积, 由 Advance 按 coast/lost 超时推进 Coasting→Uncertain→Lost, 使状态如实反映 pose 质量 (遮挡/持续低分会变 Lost)。EgoAnchor 可设 0.5 作为用户可见低质提示；server reacquire 阈值默认 0.45，更低且需要持续时间确认。")]
        [Range(0f, 1f)]
        [SerializeField] private float trackingScoreFloor = 0.0f;

        /// <summary>长时间无可靠测量后进入 Lost 的时长，单位秒。</summary>
        [Tooltip("长时间无可靠测量后进入 Lost (停止输出) 的时长，单位秒。必须大于 coast。默认 1.0。")]
        [SerializeField] private float lostTimeoutSeconds = 1.0f;

        /// <summary>判定静止的线速度阈值，单位 m/s。</summary>
        [Tooltip("判定运动/静止的线速度阈值，单位 m/s；仅用于 motionState 诊断。默认 0.015。")]
        [SerializeField] private float staticSpeedThresholdMps = 0.015f;

        /// <summary>判定静止的角速度阈值，单位 deg/s。</summary>
        [Tooltip("判定运动/静止的角速度阈值，单位 deg/s；仅用于 motionState 诊断。默认 1.5。")]
        [SerializeField] private float staticAngularSpeedThresholdDps = 1.5f;

        /// <summary>是否在进入 Lost 状态时产生服务器重获取事件。</summary>
        [Header("Lost Reacquire")]
        [Tooltip("进入 Lost 状态时是否产生服务器重获取事件；最终是否上报由 emitServerReacquire 控制。")]
        [SerializeField] private bool enableLostReacquire = true;

        /// <summary>是否启用低分重定位。</summary>
        [Header("Low-Score Reacquire")]
        [Tooltip("是否启用低分重定位：reliability 总分持续过低时，本地重置 policy 并进入 Relocalizing。是否同时请求 Python 重新 register 由 emitServerReacquire 控制。")]
        [SerializeField] private bool enableLowScoreReacquire = true;

        /// <summary>本地重获取发生时，是否向 AnchorRuntimeHub 发出服务器重获取请求。</summary>
        [Tooltip("是否把 Lost/低分重获取上报给 AnchorRuntimeHub，再由共享 client 请求 Python 重新 register。被动 shadow baseline 应关闭，本地生命周期与低分重置仍照常执行。")]
        [SerializeField] private bool emitServerReacquire = true;

        /// <summary>触发低分重定位的分数阈值。</summary>
        [Tooltip("score 持续低于此值才触发低分重定位。默认 0.45；低于状态提示阈值 0.5，避免轻微遮挡刚降级显示就反复 register。")]
        [Range(0f, 1f)]
        [SerializeField] private float lowScoreReacquireThreshold = 0.45f;

        /// <summary>低分需持续的时间，单位秒。</summary>
        [Tooltip("score 连续低于阈值需持续的时间 (秒) 才触发, 防瞬时低分误触发。默认 0.6。")]
        [SerializeField] private float lowScoreReacquireSeconds = 0.6f;

        /// <summary>两次低分重定位的最短间隔，单位秒。</summary>
        [Tooltip("两次低分重定位之间的最短间隔 (秒), 防抖。默认 3。")]
        [SerializeField] private float lowScoreReacquireCooldownSeconds = 3.0f;

        /// <summary>几何子分阈值：几何加权平均分低于它视为 track 丢失。</summary>
        [Tooltip("几何加权平均分低于此值时，低分重获取原因标记为 track_lost；几何仍好时标记为 low_score。该值只影响诊断原因。")]
        [Range(0f, 1f)]
        [SerializeField] private float reacquireGeometryFloor = 0.5f;

        /// <summary>几何核里 reprojection 子分的权重 (对齐 Python reproj_weight)。</summary>
        [Tooltip("几何加权平均里 reprojection 子分的权重。默认 0.2，与 Python defaults.toml [reliability.pose_score].reproj_weight 对齐：颜色重投影对低纹理目标 (如手柄) 不可靠，只作辅助证据。")]
        [Range(0f, 1f)]
        [SerializeField] private float reacquireReprojWeight = 0.2f;

        /// <summary>几何核里 depth 子分的权重 (对齐 Python depth_weight)。</summary>
        [Tooltip("几何加权平均里 depth 子分的权重。默认 0.8，与 Python defaults.toml [reliability.pose_score].depth_weight 对齐：手柄等低纹理目标优先相信深度对齐。")]
        [Range(0f, 1f)]
        [SerializeField] private float reacquireDepthWeight = 0.8f;

        private AnchorStateMachine stateMachine;
        private PoseToAnchorRuntime boundOwner;
        private double lastReliableLifecycleTimeSeconds = -1.0;
        private double lastAdvanceTimeSeconds = -1.0;
        private float latestAcceptedScore = 1.0f;
        private AnchorMotionState motionState = AnchorMotionState.Unknown;
        private QualityGateDecision latestQualityGateDecision = QualityGateDecision.Hold("initialized");
        private float predictAheadSeconds;
        private double lowScoreStartSeconds = -1.0;
        private double lastLowScoreReacquireSeconds = double.NegativeInfinity;
        private bool wantsServerReacquire;

        /// <summary>最近一次 Advance 时当前渲染时刻距最近图像观测语义时刻的年龄，单位秒。</summary>
        private double observationAgeSeconds = double.NaN;

        /// <summary>最近一次 policy 输出 pose 对应的 Unity 单调时钟语义时刻，单位秒。</summary>
        private double outputTargetTimeSeconds = double.NaN;

        /// <summary>最近一次 policy 输出相对当前渲染时刻的实际平滑延迟，单位秒。</summary>
        private double smoothingDelaySeconds = double.NaN;

        /// <summary>
        /// 是否有待上游处理的“通知 Python 重新 register”请求。
        /// runtime 每帧 consume 一次, 转给 AnchorRuntimeHub 统一发 NATS reacquire。host 自身不持 client。
        /// </summary>
        public bool ConsumeServerReacquireRequest()
        {
            if (!wantsServerReacquire)
            {
                return false;
            }

            wantsServerReacquire = false;
            return true;
        }

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

        /// <summary>运动模型参数指纹，参与 variant 配置哈希。</summary>
        public string MotionModelConfiguration => motionModel != null ? motionModel.ConfigurationFingerprint : "";

        /// <summary>平滑策略参数指纹，参与 variant 配置哈希。</summary>
        public string SmoothingStrategyConfiguration =>
            smoothingStrategy != null ? smoothingStrategy.ConfigurationFingerprint : "";

        /// <summary>host、生命周期、接纳、重获取和 StaticLock 的完整配置指纹。</summary>
        public string ConfigurationFingerprint => FormattableString.Invariant($"quality:{enableQualityGate},{minQualityScore:R}|lifecycle:{coastTimeoutSeconds:R},{trackingScoreFloor:R},{lostTimeoutSeconds:R}|motion-state:{staticSpeedThresholdMps:R},{staticAngularSpeedThresholdDps:R}|reacquire:{enableLostReacquire},{enableLowScoreReacquire},{emitServerReacquire},{lowScoreReacquireThreshold:R},{lowScoreReacquireSeconds:R},{lowScoreReacquireCooldownSeconds:R},{reacquireGeometryFloor:R},{reacquireReprojWeight:R},{reacquireDepthWeight:R}|static:{(staticLockModule != null ? staticLockModule.ConfigurationFingerprint : "none")}");

        /// <summary>输出策略名，写入 eval 的 smoothing_strategy 字段。</summary>
        public string SmoothingStrategyName => smoothingStrategy != null ? smoothingStrategy.StrategyName : "";

        /// <summary>质量评估门控模式，写入 eval 的 quality_gate 字段。</summary>
        public string QualityGateMode => enableQualityGate ? "enabled" : "disabled";

        /// <summary>是否启用 VCD 观测接纳。</summary>
        public bool UsesVcdAdmission => enableQualityGate;

        /// <summary>是否启用跨渲染帧时序合成，包括历史缓冲或因果校正残差融合。</summary>
        public bool UsesTemporalSynthesis =>
            smoothingStrategy is LinearSlerpStrategy
            || smoothingStrategy is CausalPredictionStrategy;

        /// <summary>是否启用显式静止锚定模块。</summary>
        public bool UsesStaticLock => staticLockModule != null && staticLockModule.Enabled;

        /// <summary>是否启用低分触发的本地重获取。</summary>
        public bool UsesLowScoreReacquire => enableLowScoreReacquire;

        /// <summary>是否允许向共享 AnchorRuntimeHub 发出服务器重获取请求。</summary>
        public bool UsesServerReacquire => emitServerReacquire && (enableLostReacquire || enableLowScoreReacquire);

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

        /// <summary>最近一次 Advance 时当前渲染时刻距最近观测语义时刻的年龄，单位秒。</summary>
        public double ObservationAgeSeconds => observationAgeSeconds;

        /// <summary>最近一次 policy 输出 pose 对应的 Unity 单调时钟语义时刻，单位秒。</summary>
        public double OutputTargetTimeSeconds => outputTargetTimeSeconds;

        /// <summary>最近一次 policy 输出相对当前渲染时刻的实际平滑延迟，单位秒。</summary>
        public double SmoothingDelaySeconds => smoothingDelaySeconds;

        /// <summary>最近一次被接受测量的可靠性分数。</summary>
        public float LatestAcceptedScore => latestAcceptedScore;

        /// <summary>最近一次质量评估门控或 policy 动作。</summary>
        public AnchorPolicyAction LatestAction => latestQualityGateDecision.ToPolicyAction();

        /// <summary>最近一次质量评估门控或 policy 原因。</summary>
        public string LatestReason => latestQualityGateDecision.Reason;

        /// <summary>是否静止锁定 (EgoAnchor 静止锚定稳定器当前是否冻结输出)。</summary>
        public bool LatestStaticLocked => staticLockModule != null && staticLockModule.IsLocked;

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
            double lifecycleTime = observation.LifecycleTimeSeconds;

            if (!observation.HasAlignedPose)
            {
                OnMissingObservation(lifecycleTime, observation.FailureReason);
                latestQualityGateDecision = QualityGateDecision.Hold(string.IsNullOrEmpty(observation.FailureReason) ? "missing_pose" : observation.FailureReason);
                return new AnchorPolicyDecision(latestQualityGateDecision.ToPolicyAction(), stateMachine.State, latestQualityGateDecision.Reason);
            }

            // 运动模型和历史合成都要求严格递增的测量时间。这里统一拒绝，避免旧观测
            // 回拨模型时钟，或向 Linear/SLERP、Causal Prediction 与 StaticLock 注入乱序控制点。
            if (ShouldRejectMeasurementTime(observation, out string timeRejectReason))
            {
                RejectedCount++;
                latestQualityGateDecision = QualityGateDecision.Reject(timeRejectReason);
                return new AnchorPolicyDecision(AnchorPolicyAction.Reject, stateMachine.State, timeRejectReason);
            }

            // 低分重定位：已有锚定后若总分持续过低，本地重置进入 Relocalizing；
            // emitServerReacquire 决定是否同时请求上游通知 Python 重 register。
            // host 不持 client; 在 raw observation 上判定, 不受下面质量评估门控是否拒绝影响。
            if (TryLowScoreReacquire(observation, lifecycleTime))
            {
                latestQualityGateDecision = QualityGateDecision.Hold("low_score_reacquire");
                return new AnchorPolicyDecision(AnchorPolicyAction.Reacquire, stateMachine.State, "low_score_reacquire");
            }

            // 可选 VCD 观测接纳门控；系统基线关闭，完整系统按实验定义开启。
            if (ShouldRejectObservation(observation, out string rejectReason))
            {
                RejectedCount++;
                latestQualityGateDecision = QualityGateDecision.Reject(rejectReason);
                stateMachine.OnUncertainPose(lifecycleTime, rejectReason);
                return new AnchorPolicyDecision(AnchorPolicyAction.Reject, stateMachine.State, rejectReason);
            }

            // 首帧或重定位后 Snap，否则正常更新
            bool snap = !motionModel.HasState;
            if (snap)
            {
                motionModel.Snap(observation);
                latestQualityGateDecision = QualityGateDecision.Snap("snap");
            }
            else
            {
                motionModel.UpdateState(observation);
                latestQualityGateDecision = QualityGateDecision.Accept("accept");
            }

            smoothingStrategy.OnObservation(motionModel, observation);

            // EgoAnchor 静止锚定稳定器: 喂同一 world pose + score, 更新静/动证据 (仅启用时)。
            // 头部 pose 来自 observation (= FramePoseHistory 按 frame_id 记录的采集时刻 center camera pose,
            // 与帧对齐复用同一份缓存, 不重复绑定 CenterEyeAnchor)。头动时放宽 static 约束吸收 slip。
            // EgoAnchor 方法层 (静止锚定) 已剥离为可选的 EgoAnchorStaticLockModule, 未挂则纯 baseline。
            if (staticLockModule != null)
            {
                staticLockModule.OnObservation(observation.WorldPose, observation.ReliabilityScore, observation.MeasurementTimeSeconds, observation.HasHeadPose, observation.HeadPose);
            }

            AcceptedCount++;
            latestAcceptedScore = observation.ReliabilityScore;
            UpdateMotionState();

            // 分数参与状态判定: 模型已更新 (低分 pose 也喂模型以维持平滑连续性), 但只有"可靠" pose
            // (总分 >= trackingScoreFloor) 才刷新可靠时间戳并进 Tracking。低分 pose 不刷新时间戳、
            // 也不在此直接改状态——把"无新鲜可靠 pose"的状态推进 (Coasting→Uncertain→Lost) 统一交给
            // 每帧 Advance 的 gap 机制 (单一数据源, 避免与 Advance 在同帧内打架)。这样遮挡/持续低分时
            // FoundationPose 仍发漂移 pose, 但 gap 持续累积会按 coast/lost 超时如实推进到 Lost。
            if (observation.ReliabilityScore >= trackingScoreFloor)
            {
                lastReliableLifecycleTimeSeconds = lifecycleTime;
                stateMachine.OnReliablePose(lifecycleTime, latestQualityGateDecision.Reason);
            }

            return new AnchorPolicyDecision(latestQualityGateDecision.ToPolicyAction(), stateMachine.State, latestQualityGateDecision.Reason);
        }

        /// <summary>每渲染帧输出当前 stable pose。</summary>
        public AnchorPolicyOutput Advance(double nowSeconds)
        {
            EnsureReady();
            if (!motionModel.HasState)
            {
                observationAgeSeconds = double.NaN;
                outputTargetTimeSeconds = double.NaN;
                smoothingDelaySeconds = double.NaN;
                stateMachine.OnMissingPose(nowSeconds, double.PositiveInfinity, false, "no_estimate");
                return AnchorPolicyOutput.None(
                    stateMachine.State,
                    "no_estimate",
                    double.NaN,
                    smoothingStrategy.Diagnostics);
            }

            observationAgeSeconds = nowSeconds > motionModel.LastObservationTimeSeconds
                ? nowSeconds - motionModel.LastObservationTimeSeconds
                : 0.0;

            double lifecycleGap = lastReliableLifecycleTimeSeconds >= 0.0 ? Mathf.Max((float)(nowSeconds - lastReliableLifecycleTimeSeconds), 0.0f) : 0.0;
            AnchorState stateBeforeAdvance = stateMachine.State;
            if (lastReliableLifecycleTimeSeconds < 0.0)
            {
                stateMachine.OnMissingPose(nowSeconds, double.PositiveInfinity, false, "no_reliable_pose");
            }
            else if (lifecycleGap > 0.0 && stateMachine.State != AnchorState.Paused)
            {
                stateMachine.OnMissingPose(nowSeconds, lifecycleGap, true, "stale_measurement");
            }

            if (stateMachine.State == AnchorState.Lost || stateMachine.State == AnchorState.Error || stateMachine.State == AnchorState.Searching)
            {
                if (enableLostReacquire && emitServerReacquire &&
                    stateMachine.State == AnchorState.Lost && stateBeforeAdvance != AnchorState.Lost)
                {
                    wantsServerReacquire = true;
                }
                outputTargetTimeSeconds = double.NaN;
                smoothingDelaySeconds = double.NaN;
                return AnchorPolicyOutput.None(
                    stateMachine.State,
                    stateMachine.LastEvent.Reason,
                    observationAgeSeconds,
                    smoothingStrategy.Diagnostics);
            }

            Pose pose = smoothingStrategy.Output(motionModel, nowSeconds);
            outputTargetTimeSeconds = smoothingStrategy.OutputTargetTimeSeconds;
            smoothingDelaySeconds = double.IsNaN(outputTargetTimeSeconds)
                ? double.NaN
                : (nowSeconds > outputTargetTimeSeconds ? nowSeconds - outputTargetTimeSeconds : 0.0);

            // EgoAnchor 静止锚定稳定器: 锁定时冻结输出, 解锁过渡平滑收敛, 否则透传 (未挂模块则纯 baseline)。
            if (staticLockModule != null)
            {
                bool overrodeSmoothingPose = staticLockModule.OverridesSmoothingPose;
                float advanceDt = lastAdvanceTimeSeconds >= 0.0 ? (float)(nowSeconds - lastAdvanceTimeSeconds) : 0.0f;
                pose = staticLockModule.Stabilize(pose, advanceDt);
                overrodeSmoothingPose |= staticLockModule.OverridesSmoothingPose;
                if (overrodeSmoothingPose)
                {
                    outputTargetTimeSeconds = double.NaN;
                    smoothingDelaySeconds = double.NaN;
                }
            }

            lastAdvanceTimeSeconds = nowSeconds;
            predictAheadSeconds = motionModel.HasState
                ? Mathf.Max((float)(nowSeconds - motionModel.LastObservationTimeSeconds), 0.0f)
                : 0.0f;
            UpdateMotionState();
            return new AnchorPolicyOutput(
                true,
                pose,
                stateMachine.State,
                motionState,
                predictAheadSeconds,
                observationAgeSeconds,
                outputTargetTimeSeconds,
                smoothingDelaySeconds,
                smoothingStrategy.Diagnostics,
                stateMachine.LastEvent.Reason);
        }

        /// <summary>reset command/status 到达时清空 policy。</summary>
        public void NotifyReset(double sampleTimeSeconds, string reason)
        {
            ResetModules();
            stateMachine.OnReset(sampleTimeSeconds, reason ?? "reset");
            latestQualityGateDecision = QualityGateDecision.Hold(reason ?? "reset");
        }

        /// <summary>reacquire command/status 到达时进入 Relocalizing 并清空估计。</summary>
        public void NotifyReacquire(double sampleTimeSeconds, string reason)
        {
            ResetModules();
            stateMachine.OnReacquire(sampleTimeSeconds, reason ?? "reacquire");
            latestQualityGateDecision = QualityGateDecision.Hold(reason ?? "reacquire");
        }

        /// <summary>暂停本地 policy。</summary>
        public void NotifyPause(double sampleTimeSeconds, string reason)
        {
            stateMachine.OnPause(sampleTimeSeconds, reason ?? "pause");
            latestQualityGateDecision = QualityGateDecision.Hold(reason ?? "pause");
        }

        /// <summary>恢复本地 policy。</summary>
        public void NotifyResume(double sampleTimeSeconds, string reason)
        {
            stateMachine.OnResume(sampleTimeSeconds, reason ?? "resume");
            latestQualityGateDecision = QualityGateDecision.Hold(reason ?? "resume");
        }

        /// <summary>通知本地目标丢失。</summary>
        public void NotifyLost(double sampleTimeSeconds, string reason)
        {
            stateMachine.OnMissingPose(sampleTimeSeconds, stateMachine.LostTimeoutSeconds, motionModel != null && motionModel.HasState, reason ?? "lost");
            latestQualityGateDecision = QualityGateDecision.Hold(reason ?? "lost");
        }

        /// <summary>通知本地错误。</summary>
        public void NotifyError(double sampleTimeSeconds, string reason)
        {
            stateMachine.OnError(sampleTimeSeconds, reason ?? "error");
            latestQualityGateDecision = QualityGateDecision.Reject(reason ?? "error");
        }

        /// <summary>清空状态机和所有模块。</summary>
        public void Clear(double sampleTimeSeconds, string reason)
        {
            ResetModules();
            stateMachine.Clear(sampleTimeSeconds, reason ?? "clear");
            latestQualityGateDecision = QualityGateDecision.Hold(reason ?? "clear");
        }

        /// <summary>
        /// 低分重定位: 已有锚定后 reliability 总分连续低于阈值持续一段时间 → 本地重置
        /// (清空运动模型/平滑/静止锁的内部状态并进入 Relocalizing, 不再信任旧低分锚点, 下一帧 pose 重新建立锚定)。
        /// emitServerReacquire 开启时，由上游 (runtime → hub) 发 NATS reacquire 让 Python 重新 register。
        /// 几何子分只决定诊断 reason：几何差/缺失记为 track_lost/no_geometry，几何仍好记为 low_score。
        /// 触发时返回 true (调用方应提前返回)。
        /// </summary>
        private bool TryLowScoreReacquire(in AnchorObservation observation, double now)
        {
            if (!enableLowScoreReacquire || !motionModel.HasState)
            {
                lowScoreStartSeconds = -1.0;
                return false;
            }

            if (observation.ReliabilityScore > lowScoreReacquireThreshold)
            {
                lowScoreStartSeconds = -1.0;
                return false;
            }

            if (lowScoreStartSeconds < 0.0)
            {
                lowScoreStartSeconds = now;
            }

            if (now - lowScoreStartSeconds < lowScoreReacquireSeconds
                || now - lastLowScoreReacquireSeconds < lowScoreReacquireCooldownSeconds)
            {
                return false;
            }

            lastLowScoreReacquireSeconds = now;
            lowScoreStartSeconds = -1.0;

            // 几何仲裁只决定诊断原因；本地重置始终执行，服务器请求由 emitServerReacquire 决定。
            // 标志在 NotifyReacquire（会 ResetModules）之后设置，避免被重置清除。
            float geometryScore = observation.GeometryScore(reacquireReprojWeight, reacquireDepthWeight, out bool hasGeometryEvidence);
            string reason = !hasGeometryEvidence
                ? "low_score_no_geometry"
                : (geometryScore < reacquireGeometryFloor ? "low_score_track_lost" : "low_score");
            NotifyReacquire(now, reason);
            wantsServerReacquire = emitServerReacquire;

            return true;
        }

        /// <summary>
        /// 检查运动估计时间戳。乱序输入只记为拒绝，不立即改变生命周期状态；
        /// 生命周期仍由最近可靠观测与当前到达时钟统一推进。
        /// </summary>
        private bool ShouldRejectMeasurementTime(in AnchorObservation observation, out string reason)
        {
            double measurementTime = observation.MeasurementTimeSeconds;
            if (double.IsNaN(measurementTime) || double.IsInfinity(measurementTime))
            {
                reason = "invalid_measurement_time";
                return true;
            }

            if (motionModel != null
                && motionModel.HasState
                && measurementTime <= motionModel.LastObservationTimeSeconds)
            {
                reason = "non_monotonic_measurement_time";
                return true;
            }

            reason = string.Empty;
            return false;
        }

        /// <summary>按当前 VCD admission 配置判断观测是否应被拒绝。</summary>
        private bool ShouldRejectObservation(in AnchorObservation observation, out string reason)
        {
            reason = string.Empty;
            if (!enableQualityGate)
            {
                return false;
            }

            if (observation.ReliabilityScore < minQualityScore)
            {
                reason = "low_score";
                return true;
            }

            return false;
        }

        private void OnMissingObservation(double nowSeconds, string reason)
        {
            double gap = lastReliableLifecycleTimeSeconds >= 0.0 ? nowSeconds - lastReliableLifecycleTimeSeconds : double.PositiveInfinity;
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
            if (staticLockModule != null)
            {
                staticLockModule.ResetModule();
            }
            lastReliableLifecycleTimeSeconds = -1.0;
            lastAdvanceTimeSeconds = -1.0;
            latestAcceptedScore = 1.0f;
            lowScoreStartSeconds = -1.0;
            motionState = AnchorMotionState.Unknown;
            predictAheadSeconds = 0.0f;
            observationAgeSeconds = double.NaN;
            outputTargetTimeSeconds = double.NaN;
            smoothingDelaySeconds = double.NaN;
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
