using System;
using System.Linq;
using EgoAnchor.Policy;
using EgoAnchor.Protocol.Generated;
using UnityEngine;

namespace EgoAnchor.Runtime
{
    /// <summary>
    /// PoseResult 到 Unity anchor policy 输入的字段映射器。
    ///
    /// 本类集中处理 Python 协议字段读取、默认值和 policy observation 构造；
    /// PoseToAnchorRuntime 只负责 frame alignment、喂 policy host 和状态应用。
    /// </summary>
    internal static class PoseResultPolicyMapper
    {
        /// <summary>
        /// 从成功对齐的 PoseResult 构造 policy observation。
        /// </summary>
        /// <param name="frameId">已对齐 pose 对应的 Quest stereo frame_id。</param>
        /// <param name="worldPose">frame-aligned Unity world pose。</param>
        /// <param name="sampleTime">观测到达 Unity 的单调时间，单位秒。</param>
        /// <param name="captureTimeSeconds">该 frame_id 的 Unity 采集单调时间，单位秒；小于 0 表示未知。</param>
        /// <param name="result">源 PoseResult；测试直接注入时可为空。</param>
        /// <param name="fallbackPhase">源 PoseResult 缺失时使用的 phase 诊断文本。</param>
        /// <returns>可交给 AnchorPolicyHost 的观测。</returns>
        public static AnchorObservation FromAlignedPose(
            long frameId,
            Pose worldPose,
            double sampleTime,
            double captureTimeSeconds,
            PoseResult result,
            string fallbackPhase)
        {
            return AnchorObservation.FromAlignedPose(
                frameId,
                worldPose,
                sampleTime,
                ReadReliabilityScore(result),
                ReadReliabilityFlags(result),
                result?.Phase ?? fallbackPhase ?? string.Empty,
                result?.PoseSource ?? string.Empty,
                captureTimeSeconds
            );
        }

        /// <summary>
        /// 从 PoseResult 读取 reliability score；非空结果中的 0 分保持为 0 分。
        /// </summary>
        /// <param name="result">Python 发布的 PoseResult。</param>
        /// <returns>限制到 0..1 的可靠性分。</returns>
        public static float ReadReliabilityScore(PoseResult result)
        {
            if (result == null)
            {
                return 1.0f;
            }

            return Mathf.Clamp01(result.ReliabilityScore);
        }

        /// <summary>
        /// 从 PoseResult 读取 reliability flags。
        /// </summary>
        /// <param name="result">Python 发布的 PoseResult。</param>
        /// <returns>可靠性诊断 flags；缺失时为空数组。</returns>
        public static string[] ReadReliabilityFlags(PoseResult result)
        {
            if (result == null || result.ReliabilityFlags == null || result.ReliabilityFlags.Count == 0)
            {
                return Array.Empty<string>();
            }

            return result.ReliabilityFlags.ToArray();
        }
    }
}
