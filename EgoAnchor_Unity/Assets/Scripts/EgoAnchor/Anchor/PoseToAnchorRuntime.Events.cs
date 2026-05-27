using System;
using System.Linq;
using EgoAnchor.Protocol.Generated;
using UnityEngine;

namespace EgoAnchor.Anchor
{
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
        /// 接收 Python AnchorStatusEvent，并映射到 Unity anchor lifecycle。
        ///
        /// 本方法只更新 anchor runtime 的本地状态/processor，不接触网络，也不直接修改 Transform。
        /// reset/reacquire 完成与否仍由后续 PoseResult 负责驱动 Tracking 恢复。
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
                bool clearPose = eventName.Contains("STARTED");
                NotifyReacquireAccepted(clearPose, reason);
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

        /// <summary>
        /// 清空当前 raw/stable anchor pose 状态。
        ///
        /// 该方法用于 Unity 收到 Python reset command accepted 后，按需清理本地可视化状态。
        /// Python reset 只会重置外部 pose 估计 pipeline；Unity 侧上一帧 raw/stable pose 和滤波器需要由本方法显式清理。
        /// </summary>
        /// <param name="clearProcessors">是否同时重置处理器内部状态。</param>
        public void ClearPoseState(bool clearProcessors = true)
        {
            hasRawPose = false;
            hasStablePose = false;
            diagnostics.latestAlignedFrameId = -1;
            diagnostics.latestPhase = string.Empty;
            diagnostics.latestFailure = "cleared_by_command";
            diagnostics.latestPolicyAction = "clear";
            diagnostics.latestPolicyReason = "cleared_by_command";

            if (clearProcessors)
            {
                ResetProcessors();
            }

            if (policyHost != null)
            {
                policyHost.Clear(Time.realtimeSinceStartupAsDouble, "cleared_by_command");
                SyncPolicyDiagnostics();
            }
        }

        /// <summary>
        /// 处理 no-pose 观测，让状态机看到缺失事件。
        /// </summary>
        private void NotifyMissingPose(long frameId, double sampleTime, string reason, string phase)
        {
            if (policyHost == null)
            {
                diagnostics.latestPolicyAction = "no_pose";
                diagnostics.latestPolicyReason = reason;
                if (!hasStablePose && !hasRawPose)
                {
                    diagnostics.currentAnchorState = AnchorState.Searching;
                }
                return;
            }

            AnchorPolicyDecision decision = policyHost.AcceptPose(AnchorObservation.MissingPose(frameId, sampleTime, reason, phase));
            ApplyPolicyDecision(decision, frameId);
        }

        /// <summary>
        /// 处理 frame alignment 或协议解析失败，让状态机看到失败事件。
        /// </summary>
        private void NotifyAlignFailure(long frameId, double sampleTime, string reason, string phase)
        {
            if (policyHost == null)
            {
                diagnostics.latestPolicyAction = "align_failed";
                diagnostics.latestPolicyReason = reason;
                return;
            }

            AnchorPolicyDecision decision = policyHost.AcceptPose(AnchorObservation.AlignFailed(frameId, sampleTime, reason, phase));
            ApplyPolicyDecision(decision, frameId);
        }

        /// <summary>
        /// 应用 anchor policy 决策到 stable pose 和 Inspector 诊断。
        /// </summary>
        private void ApplyPolicyDecision(AnchorPolicyDecision decision, long frameId)
        {
            diagnostics.latestPolicyAction = decision.Action.ToString();
            diagnostics.latestPolicyReason = decision.Reason;
            diagnostics.currentAnchorState = decision.State;
            if (decision.HasOutputPose)
            {
                stablePose = RunProcessors(decision.OutputPose, frameId, Time.realtimeSinceStartupAsDouble);
                hasStablePose = true;
            }
            else
            {
                hasStablePose = false;
            }
        }

        /// <summary>
        /// 从 PoseResult 读取 reliability score；旧协议/缺省字段按 1.0 向后兼容。
        /// </summary>
        private static float ReadReliabilityScore(PoseResult result)
        {
            if (result == null)
            {
                return 1.0f;
            }

            if (result.ReliabilityScore > 0.0f)
            {
                return Mathf.Clamp01(result.ReliabilityScore);
            }

            bool hasNewDiagnostics = (result.ReliabilityFlags != null && result.ReliabilityFlags.Count > 0)
                || result.DepthValidInMask > 0.0f
                || result.MaskAreaRatio > 0.0f
                || !string.IsNullOrEmpty(result.PoseSource);
            return hasNewDiagnostics ? 0.0f : 1.0f;
        }

        /// <summary>
        /// 从 PoseResult 读取 reliability flags。
        /// </summary>
        private static string[] ReadReliabilityFlags(PoseResult result)
        {
            if (result == null || result.ReliabilityFlags == null || result.ReliabilityFlags.Count == 0)
            {
                return Array.Empty<string>();
            }

            return result.ReliabilityFlags.ToArray();
        }

        /// <summary>
        /// 从 policy controller 同步 Inspector 诊断。
        /// </summary>
        private void SyncPolicyDiagnostics()
        {
            if (policyHost != null)
            {
                diagnostics.currentAnchorState = policyHost.State;
            }
        }

    }
}
