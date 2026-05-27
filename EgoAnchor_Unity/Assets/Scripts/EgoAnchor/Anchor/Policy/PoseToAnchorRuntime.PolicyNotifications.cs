using UnityEngine;

namespace EgoAnchor.Anchor
{
    /// <summary>
    /// PoseToAnchorRuntime 对外 policy/lifecycle 通知入口。
    ///
    /// 这些方法由 command/status/heartbeat receiver 调用，只更新本地 anchor lifecycle
    /// 与诊断字段，不直接修改 Transform，也不接触网络。
    /// </summary>
    public sealed partial class PoseToAnchorRuntime
    {
        /// <summary>
        /// 本地收到 reset accepted 或状态事件时通知 anchor policy。
        /// </summary>
        /// <param name="clearProcessors">是否同时清理 processor 状态。</param>
        /// <param name="clearAnchorPose">是否清空 raw/stable pose。</param>
        /// <param name="reason">reset 原因。</param>
        public void NotifyResetAccepted(bool clearProcessors, bool clearAnchorPose, string reason)
        {
            if (clearProcessors)
            {
                ResetProcessors();
            }

            if (clearAnchorPose)
            {
                hasRawPose = false;
                hasStablePose = false;
                diagnostics.latestAlignedFrameId = -1;
            }

            if (policyHost != null)
            {
                policyHost.NotifyReset(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyDiagnostics();
            }
            else
            {
                diagnostics.currentAnchorState = AnchorState.Searching;
            }
            diagnostics.latestFailure = reason ?? "reset";
            diagnostics.latestPolicyAction = "reset";
            diagnostics.latestPolicyReason = reason ?? "reset";
        }

        /// <summary>
        /// 本地收到 reacquire accepted 或状态事件时通知 anchor policy。
        /// </summary>
        /// <param name="clearPose">是否清空当前 raw/stable pose。</param>
        /// <param name="reason">reacquire 原因。</param>
        public void NotifyReacquireAccepted(bool clearPose, string reason)
        {
            ResetProcessors();
            if (clearPose)
            {
                hasRawPose = false;
                hasStablePose = false;
                diagnostics.latestAlignedFrameId = -1;
            }

            if (policyHost != null)
            {
                policyHost.NotifyReacquire(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyDiagnostics();
            }
            else
            {
                diagnostics.currentAnchorState = AnchorState.Relocalizing;
            }
            diagnostics.latestFailure = reason ?? "reacquire";
            diagnostics.latestPolicyAction = "reacquire";
            diagnostics.latestPolicyReason = reason ?? "reacquire";
        }

        /// <summary>
        /// 通知本地 anchor policy 暂停更新。
        /// </summary>
        /// <param name="reason">暂停原因。</param>
        public void NotifyPauseAccepted(string reason)
        {
            if (policyHost != null)
            {
                policyHost.NotifyPause(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyDiagnostics();
            }
            else
            {
                diagnostics.currentAnchorState = AnchorState.Paused;
            }
            diagnostics.latestPolicyAction = "pause";
            diagnostics.latestPolicyReason = reason ?? "pause";
        }

        /// <summary>
        /// 通知本地 anchor policy 恢复更新。
        /// </summary>
        /// <param name="reason">恢复原因。</param>
        public void NotifyResumeAccepted(string reason)
        {
            if (policyHost != null)
            {
                policyHost.NotifyResume(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyDiagnostics();
            }
            else
            {
                diagnostics.currentAnchorState = hasStablePose || hasRawPose ? AnchorState.Tracking : AnchorState.Searching;
            }
            diagnostics.latestPolicyAction = "resume";
            diagnostics.latestPolicyReason = reason ?? "resume";
        }

        /// <summary>
        /// 清空当前 raw/stable anchor pose 状态。
        /// </summary>
        /// <param name="clearProcessors">是否同时重置处理器内部状态。</param>
        public void ClearPoseState(bool clearProcessors = true)
        {
            hasRawPose = false;
            hasStablePose = false;
            diagnostics.latestAlignedFrameId = -1;
            diagnostics.latestPhase = string.Empty;
            diagnostics.latestFailure = "cleared_by_status";
            diagnostics.latestPolicyAction = "clear";
            diagnostics.latestPolicyReason = "cleared_by_status";

            if (clearProcessors)
            {
                ResetProcessors();
            }

            if (policyHost != null)
            {
                policyHost.Clear(Time.realtimeSinceStartupAsDouble, "cleared_by_status");
                SyncPolicyDiagnostics();
            }
        }
    }
}
