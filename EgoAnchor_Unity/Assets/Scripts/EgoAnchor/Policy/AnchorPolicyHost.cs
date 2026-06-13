using EgoAnchor.Diagnostics;
using EgoAnchor.Runtime;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Unity 侧 anchor policy 宿主。
    /// 该组件直接组合 Gate、Estimator 和 Output 三类模块；Python 侧叫 pipeline，
    /// Unity 前端负责 policy 决策，所以这里保留 AnchorPolicyHost 名称。
    /// </summary>
    public sealed class AnchorPolicyHost : MonoBehaviour
    {
        private const int DefaultsVersion = 1;
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<AnchorPolicyHost>();

        /// <summary>门控模块组件。</summary>
        [Header("Policy Modules")]
        [Tooltip("门控模块组件。只能引用继承 AnchorGateModule 的脚本，不使用 enum 选择策略。")]
        [SerializeField] private AnchorGateModule gateModule;

        /// <summary>估计器模块组件。</summary>
        [Tooltip("估计器模块组件。负责滤波、升采样和 PredictAt(renderTime)。")]
        [SerializeField] private AnchorEstimatorModule estimatorModule;

        /// <summary>输出整形模块组件。</summary>
        [Tooltip("输出整形模块组件。负责静止锁、限速或直接透传，不修改 estimator 状态。")]
        [SerializeField] private AnchorOutputStageModule outputModule;

        /// <summary>策略 label；为空时使用 estimator module 名称。</summary>
        [Tooltip("策略 label，写入 eval；为空时使用 estimator module 名称。")]
        [SerializeField] private string strategyLabel = "";

        /// <summary>短时无可靠测量的 coasting 时长，单位秒。</summary>
        [Header("Lifecycle")]
        [Tooltip("短时无可靠测量的 coasting 时长，单位秒。")]
        [SerializeField] private float coastTimeoutSeconds = 0.45f;

        /// <summary>长时间无可靠测量后进入 Lost 的时长，单位秒。</summary>
        [Tooltip("长时间无可靠测量后进入 Lost 的时长，单位秒。")]
        [SerializeField] private float lostTimeoutSeconds = 2.0f;

        /// <summary>判定静止的线速度阈值，单位 m/s。</summary>
        [Tooltip("判定静止的线速度阈值，单位 m/s；用于 output stage 静止锁上下文。")]
        [SerializeField] private float staticSpeedThresholdMps = 0.015f;

        /// <summary>判定静止的角速度阈值，单位 deg/s。</summary>
        [Tooltip("判定静止的角速度阈值，单位 deg/s；用于 output stage 静止锁上下文。")]
        [SerializeField] private float staticAngularSpeedThresholdDps = 1.5f;

        private int defaultsInitializedVersion = DefaultsVersion;
        private AnchorStateMachine stateMachine;
        private PoseToAnchorRuntime boundOwner;
        private double lastAcceptedTimeSeconds = -1.0;
        private float latestAcceptedScore = 1.0f;
        private AnchorMotionState motionState = AnchorMotionState.Unknown;
        private GateDecision latestGateDecision = GateDecision.Hold("initialized");
        private float predictAheadSeconds;

        /// <summary>eval 使用的策略 label。</summary>
        public string StrategyLabel => string.IsNullOrEmpty(strategyLabel) ? EstimatorModuleName : strategyLabel;

        /// <summary>当前 gate module 名称。</summary>
        public string GateModuleName => gateModule != null ? gateModule.ModuleName : "";

        /// <summary>当前 gate module 组件引用，只用于 eval 配置摘要。</summary>
        public AnchorGateModule GateModule => gateModule;

        /// <summary>当前 estimator module 名称。</summary>
        public string EstimatorModuleName => estimatorModule != null ? estimatorModule.ModuleName : "";

        /// <summary>当前 estimator module 组件引用，只用于 eval 配置摘要。</summary>
        public AnchorEstimatorModule EstimatorModule => estimatorModule;

        /// <summary>当前 output module 名称。</summary>
        public string OutputModuleName => outputModule != null ? outputModule.ModuleName : "";

        /// <summary>当前 output module 组件引用，只用于 eval 配置摘要。</summary>
        public AnchorOutputStageModule OutputModule => outputModule;

        /// <summary>当前 anchor 生命周期状态。</summary>
        public AnchorState State
        {
            get
            {
                EnsureDefaults();
                return stateMachine.State;
            }
        }

        /// <summary>当前运动状态。</summary>
        public AnchorMotionState MotionState => motionState;

        /// <summary>当前估计线速度模长，单位 m/s。</summary>
        public float SpeedMps => estimatorModule != null ? estimatorModule.LinearVelocity.magnitude : 0.0f;

        /// <summary>当前估计角速度模长，单位 deg/s。</summary>
        public float AngularSpeedDps => estimatorModule != null ? estimatorModule.AngularVelocityRad.magnitude * Mathf.Rad2Deg : 0.0f;

        /// <summary>最近一次 Advance 使用的前推时长，单位秒。</summary>
        public float PredictAheadSeconds => predictAheadSeconds;

        /// <summary>最近一次被接受测量的可靠性分数。</summary>
        public float LatestAcceptedScore => latestAcceptedScore;

        /// <summary>最近一次 gate/policy 动作。</summary>
        public AnchorPolicyAction LatestAction => latestGateDecision.ToPolicyAction();

        /// <summary>最近一次 gate/policy 原因。</summary>
        public string LatestReason => latestGateDecision.Reason;

        /// <summary>最近一次 output stage 平移残差，单位米。</summary>
        public float LatestResidualMeters => outputModule != null ? outputModule.LastResidualMeters : float.NaN;

        /// <summary>最近一次 output stage 旋转残差，单位度。</summary>
        public float LatestResidualDegrees => outputModule != null ? outputModule.LastResidualDegrees : float.NaN;

        /// <summary>最近一次输出是否被静止锁定。</summary>
        public bool LatestStaticLocked => outputModule != null && outputModule.IsStaticLocked;

        /// <summary>累计接受测量数。</summary>
        public long AcceptedCount { get; private set; }

        /// <summary>累计拒绝测量数。</summary>
        public long RejectedCount { get; private set; }

        /// <summary>Unity Awake：初始化模块状态。</summary>
        private void Awake()
        {
            EnsureDefaults();
            ResetModules();
        }

        /// <summary>Inspector 修改时修正生命周期参数。</summary>
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

        /// <summary>
        /// 绑定唯一 runtime。policy 内含 estimator 状态，不能被多个 runtime 共享。
        /// </summary>
        public void Bind(PoseToAnchorRuntime owner)
        {
            EnsureDefaults();
            if (owner == null)
            {
                return;
            }

            if (boundOwner != null && boundOwner != owner)
            {
                Log.Error($"AnchorPolicyHost 已绑定 {boundOwner.name}，拒绝再绑定 {owner.name}；每个 runtime 需要独立 policy host。", this);
                return;
            }

            boundOwner = owner;
        }

        /// <summary>
        /// 输入一帧测量并返回分类决策。该方法不输出 stable pose。
        /// </summary>
        public AnchorPolicyDecision AcceptPose(in AnchorObservation observation)
        {
            EnsureReady();
            double now = ObservationTime(observation);
            AnchorEstimate predicted = estimatorModule.HasEstimate
                ? estimatorModule.PredictAt(now)
                : AnchorEstimate.Stationary(Pose.identity, now);
            latestGateDecision = gateModule.Evaluate(observation, predicted, estimatorModule.HasEstimate);

            switch (latestGateDecision.Action)
            {
                case GateAction.Snap:
                    if (observation.HasAlignedPose)
                    {
                        estimatorModule.Snap(observation);
                        OnAcceptedObservation(observation, now);
                    }
                    else
                    {
                        OnMissingObservation(now, observation.FailureReason);
                    }
                    break;
                case GateAction.Accept:
                    if (observation.HasAlignedPose)
                    {
                        estimatorModule.UpdateEstimate(observation);
                        OnAcceptedObservation(observation, now);
                    }
                    else
                    {
                        OnMissingObservation(now, observation.FailureReason);
                    }
                    break;
                case GateAction.Reject:
                    RejectedCount++;
                    stateMachine.OnUncertainPose(now, latestGateDecision.Reason);
                    break;
                default:
                    if (observation.HasAlignedPose)
                    {
                        stateMachine.OnUncertainPose(now, latestGateDecision.Reason);
                    }
                    else
                    {
                        OnMissingObservation(now, latestGateDecision.Reason);
                    }
                    break;
            }

            return new AnchorPolicyDecision(latestGateDecision.ToPolicyAction(), stateMachine.State, latestGateDecision.Reason);
        }

        /// <summary>
        /// 每渲染帧输出当前 stable pose。
        /// </summary>
        public AnchorPolicyOutput Advance(double nowSeconds)
        {
            EnsureReady();
            if (!estimatorModule.HasEstimate)
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

            AnchorEstimate estimate = estimatorModule.PredictAt(nowSeconds);
            UpdateMotionState();
            predictAheadSeconds = lastAcceptedTimeSeconds >= 0.0
                ? Mathf.Max((float)(nowSeconds - lastAcceptedTimeSeconds), 0.0f)
                : 0.0f;
            OutputContext context = new OutputContext(
                lastAcceptedTimeSeconds,
                gap,
                latestAcceptedScore,
                stateMachine.State,
                motionState
            );
            Pose pose = outputModule.Condition(estimate, nowSeconds, context);
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
            stateMachine.OnMissingPose(sampleTimeSeconds, stateMachine.LostTimeoutSeconds, estimatorModule != null && estimatorModule.HasEstimate, reason ?? "lost");
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

        private void OnAcceptedObservation(in AnchorObservation observation, double nowSeconds)
        {
            AcceptedCount++;
            lastAcceptedTimeSeconds = nowSeconds;
            latestAcceptedScore = observation.ReliabilityScore;
            stateMachine.OnReliablePose(nowSeconds, latestGateDecision.Reason);
            UpdateMotionState();
        }

        private void OnMissingObservation(double nowSeconds, string reason)
        {
            double gap = lastAcceptedTimeSeconds >= 0.0 ? nowSeconds - lastAcceptedTimeSeconds : double.PositiveInfinity;
            stateMachine.OnMissingPose(nowSeconds, gap, estimatorModule.HasEstimate, string.IsNullOrEmpty(reason) ? "missing_pose" : reason);
        }

        private void UpdateMotionState()
        {
            if (SpeedMps <= staticSpeedThresholdMps && AngularSpeedDps <= staticAngularSpeedThresholdDps)
            {
                motionState = estimatorModule != null && estimatorModule.HasEstimate ? AnchorMotionState.Static : AnchorMotionState.Unknown;
                return;
            }

            motionState = AnchorMotionState.Moving;
        }

        private void ResetModules()
        {
            gateModule?.ResetModule();
            estimatorModule?.ResetModule();
            outputModule?.ResetModule();
            lastAcceptedTimeSeconds = -1.0;
            latestAcceptedScore = 1.0f;
            motionState = AnchorMotionState.Unknown;
            predictAheadSeconds = 0.0f;
            AcceptedCount = 0;
            RejectedCount = 0;
        }

        private void EnsureReady()
        {
            EnsureDefaults();
            if (gateModule == null || estimatorModule == null || outputModule == null)
            {
                throw new System.InvalidOperationException("AnchorPolicyHost 需要显式绑定 gateModule、estimatorModule 和 outputModule。");
            }
        }

        private void EnsureDefaults()
        {
            if (defaultsInitializedVersion != DefaultsVersion)
            {
                coastTimeoutSeconds = 0.45f;
                lostTimeoutSeconds = 2.0f;
                staticSpeedThresholdMps = 0.015f;
                staticAngularSpeedThresholdDps = 1.5f;
                strategyLabel = string.Empty;
                defaultsInitializedVersion = DefaultsVersion;
            }

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
