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
    /// 不再靠 estimator 内部限幅 predict-ahead，因此低频 pose 也能逐帧连续输出。
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
        private PoseToAnchorRuntime boundOwner;
        private double lastAcceptedTimeSeconds = -1.0;
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

        /// <summary>运动模型名 (eval 沿用 EstimatorModuleName 字段名以兼容旧分析管线)。</summary>
        public string EstimatorModuleName => motionModel != null ? motionModel.ModelName : "";

        /// <summary>平滑策略名 (eval 沿用 OutputModuleName 字段名)。</summary>
        public string OutputModuleName => smoothingStrategy != null ? smoothingStrategy.StrategyName : "";

        /// <summary>门控名 (eval 沿用 GateModuleName 字段名)。</summary>
        public string GateModuleName => enableScoreGate ? "score_jump_gate" : "null_gate";

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

        /// <summary>是否静止锁定 (本轮未实现 static-lock，固定 false)。</summary>
        public bool LatestStaticLocked => false;

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
            double now = ObservationTime(observation);

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
            lastAcceptedTimeSeconds = -1.0;
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

        private static double ObservationTime(in AnchorObservation observation)
        {
            return observation.HasCaptureTime ? observation.CaptureTimeSeconds : observation.SampleTimeSeconds;
        }
    }
}
