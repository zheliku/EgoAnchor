using UnityEngine;

namespace EgoAnchor.Anchor
{
    /// <summary>
    /// dynamic object anchor Transform 应用组件。
    ///
    /// 该组件是场景中真正移动虚拟物体的薄封装：
    /// - 从 PoseToAnchorRuntime 读取 raw 或 stable world pose。
    /// - 把 pose 应用到当前 Transform 或指定目标 Transform。
    /// - 不订阅网络，不解码 Protobuf，不做平滑或状态机。
    ///
    /// 论文/实验对照：同一 PoseToAnchorRuntime 可以驱动两个 DynamicObjectAnchor，
    /// 一个选择 Raw（不处理 baseline），另一个选择 Smoothed（processor chain 输出）。
    /// </summary>
    public sealed class DynamicObjectAnchor : MonoBehaviour
    {
        /// <summary>Transform 应用哪一种 runtime 输出。</summary>
        public enum PoseOutputMode
        {
            /// <summary>不做平滑，直接应用 frame-aligned raw world pose。</summary>
            Raw,

            /// <summary>应用 PoseToAnchorRuntime 的 stable/processor-chain 输出。</summary>
            Smoothed,
        }

        /// <summary>Pose-to-Anchor runtime。</summary>
        [Header("Runtime")]
        [Tooltip("Pose-to-Anchor runtime。该组件只读 runtime 输出，不订阅网络。")]
        [SerializeField] private PoseToAnchorRuntime runtime;

        /// <summary>要应用 pose 的目标 Transform。</summary>
        [Tooltip("要应用 pose 的目标 Transform。为空时应用到当前 GameObject。")]
        [SerializeField] private Transform targetTransform;

        /// <summary>输出模式。</summary>
        [Tooltip("输出模式：Raw 用于不处理 baseline；Smoothed 读取 PoseToAnchorRuntime 的 stable/processor-chain 输出。")]
        [SerializeField] private PoseOutputMode outputMode = PoseOutputMode.Smoothed;

        /// <summary>是否应用 position。</summary>
        [Header("Apply")]
        [Tooltip("是否应用 position。关闭后只更新 rotation。")]
        [SerializeField] private bool applyPosition = true;

        /// <summary>是否应用 rotation。</summary>
        [Tooltip("是否应用 rotation。关闭后只更新 position。")]
        [SerializeField] private bool applyRotation = true;

        /// <summary>没有有效 pose 时是否保持上一帧 Transform。</summary>
        [Tooltip("没有有效 pose 时是否保持上一帧 Transform。建议保持开启，避免 has_pose=false 时物体跳回原点。")]
        [SerializeField] private bool holdLastPoseWhenMissing = true;

        /// <summary>是否记录 Inspector 诊断。</summary>
        [Header("Debug")]
        [Tooltip("是否在 Inspector 中记录最后一次成功应用的 frame_id。")]
        [SerializeField] private bool keepDiagnostics = true;

        /// <summary>最近一次成功应用的 frame_id。</summary>
        [Tooltip("最近一次成功应用的 frame_id。只用于 Inspector/日志诊断。")]
        [SerializeField] private long lastAppliedFrameId = -1;

        /// <summary>
        /// Unity Reset：默认应用到自身 Transform。
        /// </summary>
        private void Reset()
        {
            targetTransform = transform;
            runtime = GetComponent<PoseToAnchorRuntime>();
        }

        /// <summary>
        /// Unity Awake：补齐目标 Transform。
        /// </summary>
        private void Awake()
        {
            if (targetTransform == null)
            {
                targetTransform = transform;
            }

            if (runtime == null)
            {
                runtime = GetComponent<PoseToAnchorRuntime>();
            }
        }

        /// <summary>
        /// LateUpdate 中读取 runtime 最新输出并应用到 Transform。
        /// </summary>
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
                if (!holdLastPoseWhenMissing && keepDiagnostics)
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


