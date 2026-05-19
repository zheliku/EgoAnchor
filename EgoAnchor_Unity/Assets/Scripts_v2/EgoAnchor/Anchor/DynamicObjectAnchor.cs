using UnityEngine;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// v2 dynamic object anchor Transform 应用组件。
    ///
    /// 该组件将是场景中真正移动/稳定虚拟物体的 MonoBehaviour。职责应保持非常薄：
    /// - 从 PoseToAnchorRuntime 读取稳定 world pose。
    /// - 把 pose 应用到当前 Transform 或指定目标 Transform。
    /// - 暴露交互系统需要的挂载点。
    ///
    /// 当前不订阅网络、不解码 Protobuf；后续也不应把 NATS/ZMQ 逻辑写进这里。
    ///
    /// 论文/实验对照：同一 PoseToAnchorRuntime 可以驱动两个 DynamicObjectAnchor，
    /// 一个选择 Raw（不处理 baseline），另一个选择 Smoothed（processor chain 输出），从而并排观察抖动与延迟。
    /// </summary>
    public sealed class DynamicObjectAnchor : MonoBehaviour
    {
        /// <summary>Transform 应用哪一种 runtime 输出。</summary>
        public enum PoseOutputMode
        {
            /// <summary>不做平滑，直接应用 frame-aligned raw world pose。</summary>
            Raw,

            /// <summary>应用 PoseToAnchorRuntime 的 stable 输出。名称保留为 Smoothed 以兼容已有场景序列化。</summary>
            Smoothed,
        }

        [Header("Runtime")]
        [Tooltip("Pose-to-Anchor runtime。该组件只读 runtime 输出，不订阅网络。")]
        [SerializeField] private PoseToAnchorRuntime runtime;

        [Tooltip("要应用 pose 的目标 Transform。为空时应用到当前 GameObject。")]
        [SerializeField] private Transform targetTransform;

        [Tooltip("输出模式：Raw 用于不处理 baseline；Smoothed 读取 PoseToAnchorRuntime 的 stable/processor-chain 输出。")]
        [SerializeField] private PoseOutputMode outputMode = PoseOutputMode.Smoothed;

        [Header("Apply")]
        [Tooltip("是否应用 position。关闭后只更新 rotation。")]
        [SerializeField] private bool applyPosition = true;

        [Tooltip("是否应用 rotation。关闭后只更新 position。")]
        [SerializeField] private bool applyRotation = true;

        [Tooltip("没有有效 pose 时是否保持上一帧 Transform。建议保持开启，避免 has_pose=false 时物体跳回原点。")]
        [SerializeField] private bool holdLastPoseWhenMissing = true;

        [Header("Debug")]
        [Tooltip("是否在 Inspector 中记录最后一次成功应用的 frame_id。")]
        [SerializeField] private bool keepDiagnostics = true;

        [Tooltip("最近一次成功应用的 frame_id。只用于 Inspector/日志诊断。")]
        [SerializeField] private long lastAppliedFrameId = -1;

        private void Reset()
        {
            targetTransform = transform;
        }

        private void Awake()
        {
            if (targetTransform == null)
            {
                targetTransform = transform;
            }
        }

        private void LateUpdate()
        {
            if (runtime == null || targetTransform == null)
            {
                return;
            }

            bool hasPose = outputMode == PoseOutputMode.Raw
                ? runtime.TryGetRawPose(out Pose pose)
                : runtime.TryGetStablePose(out pose);

            if (!hasPose)
            {
                if (!holdLastPoseWhenMissing)
                {
                    lastAppliedFrameId = -1;
                }
                return;
            }

            if (applyPosition)
            {
                targetTransform.position = pose.position;
            }

            if (applyRotation)
            {
                targetTransform.rotation = pose.rotation;
            }

            if (keepDiagnostics)
            {
                lastAppliedFrameId = runtime.LatestAlignedFrameId;
            }
        }
    }
}
