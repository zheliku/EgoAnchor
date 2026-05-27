using System;
using System.Linq;
using EgoAnchor.Protocol.Generated;
using UnityEngine;

namespace EgoAnchor.Anchor
{
    /// <summary>
    /// PoseToAnchorRuntime 的 pose 失败事件与 policy 决策应用逻辑。
    /// </summary>
    public sealed partial class PoseToAnchorRuntime
    {
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
