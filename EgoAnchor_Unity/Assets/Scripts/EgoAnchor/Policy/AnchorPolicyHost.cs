using EgoAnchor.Diagnostics;
using EgoAnchor.Runtime;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// PoseToAnchorRuntime 旁路挂载的自适应 anchor policy 宿主。
    ///
    /// 本组件只负责持有 Inspector 参数包和 PolicyController 生命周期。是否启用 policy
    /// 由 PoseToAnchorRuntime 是否引用该组件决定；网络接收、frame alignment、Transform
    /// 应用仍分别保留在各自层里。Inspector 修改参数时热更生效，不清空滤波历史。
    /// 一个 host 只服务一个 runtime（内部含独占滤波状态），Bind 守卫防止误共享。
    /// </summary>
    public sealed class AnchorPolicyHost : MonoBehaviour
    {
        /// <summary>组件日志通道。</summary>
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<AnchorPolicyHost>();

        /// <summary>自适应 anchor 控制器参数包。</summary>
        [Tooltip("自适应 anchor 控制器参数包：评分门控、跳变门控、位置/旋转滤波噪声、运动分类与时序续航。运行中修改即时生效，不清空滤波历史。")]
        [SerializeField] private AnchorPolicyConfig config = new AnchorPolicyConfig();

        /// <summary>当前 policy controller。</summary>
        private PolicyController controller;

        /// <summary>当前绑定的 runtime；host 内含独占滤波状态，只允许一个。</summary>
        private PoseToAnchorRuntime boundOwner;

        /// <summary>当前 policy 状态。</summary>
        public AnchorState State => Controller.State;

        /// <summary>当前运动状态。</summary>
        public AnchorMotionState MotionState => Controller.MotionState;

        /// <summary>当前估计线速度模长，单位米/秒。</summary>
        public float SpeedMps => Controller.SpeedMps;

        /// <summary>当前估计角速度模长，单位度/秒。</summary>
        public float AngularSpeedDps => Controller.AngularSpeedDps;

        /// <summary>最近一次门控的位置 innovation 马氏距离平方。</summary>
        public float LastInnovationPosD2 => Controller.LastInnovationPosD2;

        /// <summary>最近一次门控的位置有效测量噪声，单位 m^2。</summary>
        public float LastREffPos => Controller.LastREffPos;

        /// <summary>最近一次 Advance 实际使用的前推时长，单位秒。</summary>
        public float PredictAheadSeconds => Controller.PredictAheadSeconds;

        /// <summary>累计接受的测量数（含贴合接受）。</summary>
        public long AcceptedCount => Controller.AcceptedCount;

        /// <summary>累计拒绝的测量数。</summary>
        public long RejectedCount => Controller.RejectedCount;

        /// <summary>
        /// Unity Awake：构造 policy controller。
        /// </summary>
        private void Awake()
        {
            EnsureController();
        }

        /// <summary>
        /// Inspector 修改参数时热更 controller，不重建、不清空滤波历史。
        /// </summary>
        private void OnValidate()
        {
            config ??= new AnchorPolicyConfig();
            config.Validate();
            controller?.ApplyConfig(config);
        }

        /// <summary>
        /// 绑定唯一的宿主 runtime。host 内含独占滤波状态，被第二个 runtime 复用会互相污染。
        /// </summary>
        /// <param name="owner">请求绑定的 runtime。</param>
        public void Bind(PoseToAnchorRuntime owner)
        {
            if (owner == null)
            {
                return;
            }

            if (boundOwner != null && boundOwner != owner)
            {
                Log.Error($"AnchorPolicyHost 已绑定 {boundOwner.name}，拒绝再绑定 {owner.name}；每个 policy runtime 需要独立的 host 实例。", this);
                return;
            }

            boundOwner = owner;
        }

        /// <summary>
        /// 输入一帧观测并返回输入分类决策。渲染输出请使用 Advance。
        /// </summary>
        /// <param name="observation">Unity anchor policy 观测。</param>
        /// <returns>本帧 policy 决策。</returns>
        public AnchorPolicyDecision AcceptPose(AnchorObservation observation)
        {
            return Controller.AcceptPose(observation);
        }

        /// <summary>
        /// 每渲染帧推进计时并输出当前 anchor pose。
        /// </summary>
        /// <param name="nowSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <returns>本帧 anchor 输出。</returns>
        public AnchorPolicyOutput Advance(double nowSeconds)
        {
            return Controller.Advance(nowSeconds);
        }

        /// <summary>
        /// reset command 或 status event 到达时通知 policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">reset 原因。</param>
        public void NotifyReset(double sampleTimeSeconds, string reason)
        {
            Controller.NotifyReset(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// reacquire command 或 status event 到达时通知 policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">reacquire 原因。</param>
        public void NotifyReacquire(double sampleTimeSeconds, string reason)
        {
            Controller.NotifyReacquire(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// 暂停本地 anchor policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">暂停原因。</param>
        public void NotifyPause(double sampleTimeSeconds, string reason)
        {
            Controller.NotifyPause(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// 恢复本地 anchor policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">恢复原因。</param>
        public void NotifyResume(double sampleTimeSeconds, string reason)
        {
            Controller.NotifyResume(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// Python status/heartbeat 报告错误时通知 policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">错误原因。</param>
        public void NotifyError(double sampleTimeSeconds, string reason)
        {
            Controller.NotifyError(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// Python status 报告目标丢失时通知 policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">丢失原因。</param>
        public void NotifyLost(double sampleTimeSeconds, string reason)
        {
            Controller.NotifyLost(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// 清空 policy 内部滤波状态和状态机。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">清空原因。</param>
        public void Clear(double sampleTimeSeconds, string reason)
        {
            Controller.Clear(sampleTimeSeconds, reason);
        }

        /// <summary>确保 controller 存在并返回。</summary>
        private PolicyController Controller
        {
            get
            {
                EnsureController();
                return controller;
            }
        }

        /// <summary>按当前参数包构造 controller（仅在尚不存在时）。</summary>
        private void EnsureController()
        {
            if (controller == null)
            {
                config ??= new AnchorPolicyConfig();
                controller = new PolicyController(config);
            }
        }
    }
}
