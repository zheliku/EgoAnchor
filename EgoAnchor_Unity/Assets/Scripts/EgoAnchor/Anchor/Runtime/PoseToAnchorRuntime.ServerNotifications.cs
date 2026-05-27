using EgoAnchor.Protocol.Generated;
using UnityEngine;

namespace EgoAnchor.Anchor
{
    /// <summary>
    /// PoseToAnchorRuntime 接收 Python status/heartbeat 后的本地 lifecycle 映射。
    /// </summary>
    public sealed partial class PoseToAnchorRuntime
    {
        /// <summary>
        /// 接收 Python AnchorStatusEvent，并映射到 Unity anchor lifecycle。
        /// </summary>
        /// <param name="status">Python 发布的 AnchorStatusEvent。</param>
        public void NotifyStatusEvent(AnchorStatusEvent status)
        {
            if (status == null)
            {
                return;
            }

            diagnostics.latestServerState = status.State ?? string.Empty;
            diagnostics.latestServerEvent = status.Event ?? string.Empty;
            string reason = string.IsNullOrEmpty(status.Message) ? diagnostics.latestServerEvent : status.Message;
            string eventName = (diagnostics.latestServerEvent ?? string.Empty).ToUpperInvariant();
            string serverState = (diagnostics.latestServerState ?? string.Empty).ToUpperInvariant();

            if (eventName.Contains("RESET"))
            {
                NotifyResetAccepted(clearProcessors: true, clearAnchorPose: false, reason);
                return;
            }

            if (eventName.Contains("REACQUIRE"))
            {
                NotifyReacquireAccepted(eventName.Contains("STARTED"), reason);
                return;
            }

            if (eventName.Contains("PAUSE") || serverState == "PAUSED")
            {
                NotifyPauseAccepted(reason);
                return;
            }

            if (eventName.Contains("RESUME"))
            {
                NotifyResumeAccepted(reason);
                return;
            }

            if (serverState == "LOST")
            {
                diagnostics.currentAnchorState = AnchorState.Lost;
                diagnostics.latestPolicyAction = "server_status";
                diagnostics.latestPolicyReason = reason;
                return;
            }

            if (serverState == "ERROR" || status.Error != null && !string.IsNullOrEmpty(status.Error.Code))
            {
                diagnostics.currentAnchorState = AnchorState.Error;
                diagnostics.latestPolicyAction = "server_error";
                diagnostics.latestPolicyReason = string.IsNullOrEmpty(status.Error?.Code) ? reason : status.Error.Code;
                return;
            }

            diagnostics.latestPolicyAction = "server_status";
            diagnostics.latestPolicyReason = reason;
        }

        /// <summary>
        /// 接收 Python ServerHeartbeat，并在输入未就绪或服务错误时更新本地 anchor 状态。
        /// </summary>
        /// <param name="heartbeat">Python 发布的 ServerHeartbeat。</param>
        public void NotifyHeartbeat(ServerHeartbeat heartbeat)
        {
            if (heartbeat == null)
            {
                return;
            }

            diagnostics.latestHeartbeatInputReady = heartbeat.InputReady;
            diagnostics.latestHeartbeatReceiveTime = Time.realtimeSinceStartupAsDouble;
            diagnostics.latestServerState = heartbeat.State ?? diagnostics.latestServerState;
            if (!heartbeat.InputReady && diagnostics.currentAnchorState != AnchorState.Paused)
            {
                diagnostics.currentAnchorState = hasStablePose || hasRawPose ? AnchorState.FrozenUncertain : AnchorState.Searching;
                diagnostics.latestPolicyAction = "heartbeat";
                diagnostics.latestPolicyReason = "input_not_ready";
            }

            if (heartbeat.LastError != null && !string.IsNullOrEmpty(heartbeat.LastError.Code))
            {
                diagnostics.currentAnchorState = AnchorState.Error;
                diagnostics.latestPolicyAction = "heartbeat_error";
                diagnostics.latestPolicyReason = heartbeat.LastError.Code;
            }
        }
    }
}
