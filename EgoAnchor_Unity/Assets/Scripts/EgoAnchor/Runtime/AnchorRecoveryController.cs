using System;
using System.Threading.Tasks;
using EgoAnchor.Client;
using EgoAnchor.Diagnostics;
using EgoAnchor.Policy;
using EgoAnchor.Protocol.Generated;
using UnityEngine;

namespace EgoAnchor.Runtime
{
    /// <summary>
    /// Anchor 自动 recovery 的正交控制层。
    /// 它只观察 PoseToAnchorRuntime 诊断并发送 reacquire command，不干涉 policy host 的模块组合或生命周期，也不把 CommandAck 解释为恢复完成。
    /// </summary>
    public sealed class AnchorRecoveryController : MonoBehaviour
    {
        /// <summary>自动低分重获取原因。</summary>
        public const string ReasonLowScore = "auto_reacquire_low_score";

        /// <summary>自动 lost 重获取原因。</summary>
        public const string ReasonLost = "auto_reacquire_lost";

        /// <summary>自动 no-pose 重获取原因。</summary>
        public const string ReasonNoPose = "auto_reacquire_no_pose";

        /// <summary>输入未就绪等待原因。</summary>
        public const string ReasonInputNotReady = "input_not_ready_wait";

        /// <summary>组件日志通道。</summary>
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<AnchorRecoveryController>();

        /// <summary>被观察的 anchor runtime。</summary>
        [Header("Targets")]
        [Tooltip("被观察的 PoseToAnchorRuntime。recovery 只读取诊断状态，不直接修改 Transform 或滤波器。")]
        [SerializeField] private PoseToAnchorRuntime runtime;

        /// <summary>用于发送 NATS command 的客户端。</summary>
        [Tooltip("用于发送 reacquire command 的 AnchorCommandClient。ack 只表示 Python 接受命令，不表示 recovery 已完成。")]
        [SerializeField] private AnchorCommandClient commandClient;

        /// <summary>总开关。</summary>
        [Header("Triggers")]
        [Tooltip("自动 reacquire 总开关。关闭时本组件只保持诊断，不发送命令。")]
        [SerializeField] private bool enableAutoReacquire;

        /// <summary>是否允许低分持续触发。</summary>
        [Tooltip("是否允许 reliability score 持续低于阈值后触发 reacquire。RQ2 baseline 对比时应关闭。")]
        [SerializeField] private bool enableLowScoreReacquire;

        /// <summary>是否允许 Lost 状态持续触发。</summary>
        [Tooltip("是否允许 runtime 进入 Lost 状态并持续一段时间后触发 reacquire。")]
        [SerializeField] private bool enableLostReacquire = true;

        /// <summary>是否允许 no-pose 持续触发。</summary>
        [Tooltip("是否允许连续 no_pose 失败持续一段时间后触发 reacquire。")]
        [SerializeField] private bool enableNoPoseReacquire = true;

        /// <summary>低分阈值。</summary>
        [Tooltip("低分 reacquire 阈值。只有 LatestReliabilityScore 持续低于该值才触发。")]
        [Range(0.0f, 1.0f)]
        [SerializeField] private float lowScoreThreshold = 0.25f;

        /// <summary>低分持续时间。</summary>
        [Tooltip("低分需要持续的时间，单位秒。")]
        [Min(0.0f)]
        [SerializeField] private float lowScoreSeconds = 0.8f;

        /// <summary>Lost 持续时间。</summary>
        [Tooltip("Lost 状态需要持续的时间，单位秒。")]
        [Min(0.0f)]
        [SerializeField] private float lostSeconds = 0.3f;

        /// <summary>no-pose 持续时间。</summary>
        [Tooltip("no_pose 失败需要持续的时间，单位秒。")]
        [Min(0.0f)]
        [SerializeField] private float noPoseSeconds = 1.0f;

        /// <summary>命令冷却时间。</summary>
        [Tooltip("两次自动 reacquire 命令之间的最短间隔，单位秒，防止命令风暴。")]
        [Min(0.0f)]
        [SerializeField] private float cooldownSeconds = 3.0f;

        /// <summary>reacquire 前是否清空 Python 旧 tracking 状态。</summary>
        [Tooltip("发送 ReacquireAnchorRequest 时是否要求 Python 先清空旧 tracking 状态。")]
        [SerializeField] private bool clearTrackingFirst = true;

        /// <summary>测试替换命令发送器；生产路径为空并使用 commandClient。</summary>
        private IAnchorCommandSender commandSenderOverride;

        /// <summary>低分开始时间；负数表示当前未处于低分窗口。</summary>
        private double lowScoreStartSeconds = -1.0;

        /// <summary>Lost 开始时间；负数表示当前未处于 Lost 窗口。</summary>
        private double lostStartSeconds = -1.0;

        /// <summary>no-pose 开始时间；负数表示当前未处于 no-pose 窗口。</summary>
        private double noPoseStartSeconds = -1.0;

        /// <summary>最近一次命令发送时间。</summary>
        private double lastCommandSeconds = double.NegativeInfinity;

        /// <summary>是否已有命令正在等待 ack。</summary>
        private bool inFlight;

        /// <summary>最近一次触发或等待原因。</summary>
        [Header("Diagnostics")]
        [Tooltip("最近一次触发、等待或抑制原因。")]
        [SerializeField] private string latestReason = "";

        /// <summary>累计自动发送命令数。</summary>
        [Tooltip("累计自动发送 reacquire 命令数。")]
        [SerializeField] private int sentReacquireCount;

        /// <summary>累计 accepted ack 数。</summary>
        [Tooltip("累计 accepted CommandAck 数。accepted 不代表恢复完成。")]
        [SerializeField] private int acceptedAckCount;

        /// <summary>累计 rejected/null ack 数。</summary>
        [Tooltip("累计 rejected 或 null CommandAck 数。")]
        [SerializeField] private int rejectedAckCount;

        /// <summary>最近一次触发或等待原因。</summary>
        public string LatestReason => latestReason;

        /// <summary>累计自动发送命令数。</summary>
        public int SentReacquireCount => sentReacquireCount;

        /// <summary>累计 accepted ack 数。</summary>
        public int AcceptedAckCount => acceptedAckCount;

        /// <summary>累计 rejected/null ack 数。</summary>
        public int RejectedAckCount => rejectedAckCount;

        /// <summary>是否已有 command request 正在等待 ack。</summary>
        public bool InFlight => inFlight;

        /// <summary>
        /// smoke 测试注入命令发送器，避免测试连接真实 NATS。
        /// 生产场景应保持为空并使用 Inspector 绑定的 AnchorCommandClient。
        /// </summary>
        /// <param name="sender">测试命令发送器；传 null 可恢复生产路径。</param>
        internal void SetCommandSenderForTesting(IAnchorCommandSender sender)
        {
            commandSenderOverride = sender;
        }

        /// <summary>Unity Update：按显式时间驱动 recovery 判定。</summary>
        private void Update()
        {
            Tick(Time.realtimeSinceStartupAsDouble);
        }

        /// <summary>Inspector 修改时修正阈值范围。</summary>
        private void OnValidate()
        {
            lowScoreThreshold = Mathf.Clamp01(lowScoreThreshold);
            lowScoreSeconds = Mathf.Max(0.0f, lowScoreSeconds);
            lostSeconds = Mathf.Max(0.0f, lostSeconds);
            noPoseSeconds = Mathf.Max(0.0f, noPoseSeconds);
            cooldownSeconds = Mathf.Max(0.0f, cooldownSeconds);
        }

        /// <summary>
        /// 显式推进 recovery 判定，便于 smoke 用固定时间轴验证。
        /// </summary>
        /// <param name="nowSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <returns>本 tick 是否新发出一条 reacquire command。</returns>
        public bool Tick(double nowSeconds)
        {
            if (!enableAutoReacquire || runtime == null)
            {
                latestReason = enableAutoReacquire ? "missing_runtime" : "auto_reacquire_disabled";
                ResetTriggerWindows();
                return false;
            }

            if (!runtime.LatestHeartbeatInputReady)
            {
                latestReason = ReasonInputNotReady;
                ResetTriggerWindows();
                return false;
            }

            if (inFlight)
            {
                latestReason = "reacquire_in_flight";
                return false;
            }

            if (nowSeconds - lastCommandSeconds < cooldownSeconds)
            {
                latestReason = "reacquire_cooldown";
                return false;
            }

            if (runtime.CurrentAnchorState == AnchorState.Paused
                || runtime.CurrentAnchorState == AnchorState.Relocalizing
                || runtime.CurrentAnchorState == AnchorState.Error)
            {
                latestReason = "runtime_not_recoverable";
                ResetTriggerWindows();
                return false;
            }

            string triggerReason = EvaluateTriggers(nowSeconds);
            if (string.IsNullOrEmpty(triggerReason))
            {
                return false;
            }

            IAnchorCommandSender sender = commandSenderOverride ?? commandClient;
            if (sender == null)
            {
                latestReason = "missing_command_client";
                return false;
            }

            _ = SendReacquireAsync(sender, triggerReason, nowSeconds);
            latestReason = triggerReason;
            return true;
        }

        /// <summary>
        /// 评估三类触发条件，返回固定 reason；无触发时返回空字符串。
        /// </summary>
        private string EvaluateTriggers(double nowSeconds)
        {
            if (enableLostReacquire && IsLost())
            {
                if (StartOrElapsed(ref lostStartSeconds, nowSeconds) >= lostSeconds)
                {
                    return ReasonLost;
                }
            }
            else
            {
                lostStartSeconds = -1.0;
            }

            if (enableNoPoseReacquire && IsNoPose())
            {
                if (StartOrElapsed(ref noPoseStartSeconds, nowSeconds) >= noPoseSeconds)
                {
                    return ReasonNoPose;
                }
            }
            else
            {
                noPoseStartSeconds = -1.0;
            }

            if (enableLowScoreReacquire && IsLowScore())
            {
                if (StartOrElapsed(ref lowScoreStartSeconds, nowSeconds) >= lowScoreSeconds)
                {
                    return ReasonLowScore;
                }
            }
            else
            {
                lowScoreStartSeconds = -1.0;
            }

            latestReason = "watching";
            return string.Empty;
        }

        /// <summary>
        /// 发送 reacquire command 并更新 in-flight/ack 诊断。
        /// </summary>
        private async Task SendReacquireAsync(IAnchorCommandSender sender, string reason, double nowSeconds)
        {
            inFlight = true;
            lastCommandSeconds = nowSeconds;
            sentReacquireCount++;
            try
            {
                CommandAck ack = await sender.ReacquireAsync(
                    ReacquireAnchorRequest.Types.ReacquireMode.NextValidFrame,
                    clearTrackingFirst,
                    string.Empty,
                    0.0,
                    reason);
                if (ack != null && ack.Accepted)
                {
                    acceptedAckCount++;
                }
                else
                {
                    rejectedAckCount++;
                }
            }
            catch (Exception ex)
            {
                rejectedAckCount++;
                Log.Warning($"auto reacquire failed reason={reason}, error={ex.Message}", this);
            }
            finally
            {
                inFlight = false;
                ResetTriggerWindows();
            }
        }

        /// <summary>
        /// 判断当前是否处于 Lost 触发窗口。
        /// </summary>
        private bool IsLost()
        {
            return runtime.CurrentAnchorState == AnchorState.Lost
                || string.Equals(runtime.LatestServerState, "LOST", StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// 判断当前是否处于 no-pose 触发窗口。
        /// </summary>
        private bool IsNoPose()
        {
            return string.Equals(runtime.LatestFailure, "no_pose", StringComparison.OrdinalIgnoreCase)
                || string.Equals(runtime.LatestPolicyAction, "no_pose", StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// 判断当前是否处于低分触发窗口。
        /// </summary>
        private bool IsLowScore()
        {
            return runtime.LatestAlignedFrameId >= 0
                && runtime.LatestReliabilityScore <= lowScoreThreshold
                && runtime.CurrentAnchorState != AnchorState.Searching
                && runtime.CurrentAnchorState != AnchorState.Uninitialized;
        }

        /// <summary>
        /// 启动窗口计时或返回已持续时间。
        /// </summary>
        private static double StartOrElapsed(ref double startSeconds, double nowSeconds)
        {
            if (startSeconds < 0.0)
            {
                startSeconds = nowSeconds;
                return 0.0;
            }

            return nowSeconds - startSeconds;
        }

        /// <summary>
        /// 清空所有触发窗口计时。
        /// </summary>
        private void ResetTriggerWindows()
        {
            lowScoreStartSeconds = -1.0;
            lostStartSeconds = -1.0;
            noPoseStartSeconds = -1.0;
        }
    }
}
