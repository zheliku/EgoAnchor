using UnityEngine;

namespace EgoAnchor.Runtime
{
    /// <summary>
    /// dynamic object anchor Transform 应用组件。
    ///
    /// 该组件是场景中真正移动虚拟物体的薄封装：
    /// - 从 PoseToAnchorRuntime 读取 anchor policy 每帧输出的 world pose。
    /// - 把 pose 应用到当前 Transform 或指定目标 Transform。
    /// - 不订阅网络，不解码 Protobuf，不做平滑或状态机。
    ///
    /// 论文/实验对照由多个 PoseToAnchorRuntime + AnchorPolicyHost module 组合表达；
    /// HoldStrategy（ZOH 零阶保持）也是 policy 输出的一种，不在 Transform 应用层选择双路模式。
    /// </summary>
    [DefaultExecutionOrder(0)]
    public sealed class DynamicObjectAnchor : MonoBehaviour
    {
        /// <summary>Pose-to-Anchor runtime。</summary>
        [Header("Runtime")]
        [Tooltip("Pose-to-Anchor runtime。该组件只读 runtime 输出，不订阅网络。")]
        [SerializeField] private PoseToAnchorRuntime runtime;

        /// <summary>要应用 pose 的目标 Transform。</summary>
        [Tooltip("要应用 pose 的目标 Transform。为空时应用到当前 GameObject。")]
        [SerializeField] private Transform targetTransform;

        /// <summary>是否应用 position。</summary>
        [Header("Apply")]
        [Tooltip("是否应用 position。关闭后只更新 rotation。")]
        [SerializeField] private bool applyPosition = true;

        /// <summary>是否应用 rotation。</summary>
        [Tooltip("是否应用 rotation。关闭后只更新 position。")]
        [SerializeField] private bool applyRotation = true;

        /// <summary>没有有效 pose 时是否保持上一帧 Transform。</summary>
        [Tooltip("没有有效 pose 时是否保持上一帧 Transform。开启时物体停在最后一帧位置；关闭时隐藏物体渲染，避免停留在已失效的旧 pose。")]
        [SerializeField] private bool holdLastPoseWhenMissing = true;

        /// <summary>目标 Transform 当前是否实际显示一个已经应用或保留的 anchor pose。</summary>
        public bool HasDisplayPose => lastAppliedFrameId >= 0 && !renderersHidden;

        /// <summary>最近一次实际应用且仍在显示的来源 frame_id；从未应用或已隐藏时为 -1。</summary>
        public long LastAppliedFrameId => HasDisplayPose ? lastAppliedFrameId : -1;

        [Header("Debug")]
        /// <summary>最近一次成功应用的 frame_id。</summary>
        [Tooltip("最近一次成功应用的 frame_id。只用于 Inspector/日志诊断。")]
        [SerializeField] private long lastAppliedFrameId = -1;

        /// <summary>目标下的渲染器缓存，用于 missing 时隐藏/恢复显示。</summary>
        private Renderer[] targetRenderers;

        /// <summary>当前是否因缺失 pose 而隐藏了渲染器。</summary>
        private bool renderersHidden;

        /// <summary>
        /// Unity Reset：默认应用到自身 Transform。
        /// </summary>
        private void Reset()
        {
            targetTransform = transform;
            runtime = GetComponent<PoseToAnchorRuntime>();
        }

        /// <summary>
        /// Unity Awake：补齐目标 Transform 并缓存渲染器。
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

            targetRenderers = targetTransform.GetComponentsInChildren<Renderer>(true);
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

            bool hasPose = runtime.TryGetOutputPose(out Pose pose);

            if (!hasPose)
            {
                if (!holdLastPoseWhenMissing)
                {
                    lastAppliedFrameId = -1;
                    SetRenderersHidden(true);
                }
                return;
            }

            SetRenderersHidden(false);

            if (applyPosition)
            {
                targetTransform.position = pose.position;
            }

            if (applyRotation)
            {
                targetTransform.rotation = pose.rotation;
            }

            lastAppliedFrameId = runtime.LatestAlignedFrameId;
        }

        /// <summary>读取当前实际显示的 world pose；隐藏或从未应用过 pose 时返回 false。</summary>
        /// <param name="pose">当前目标 Transform 的 world pose。</param>
        /// <returns>用户当前是否能看到一个已应用或 hold-last 的 anchor pose。</returns>
        public bool TryGetDisplayPose(out Pose pose)
        {
            pose = targetTransform != null
                ? new Pose(targetTransform.position, targetTransform.rotation)
                : Pose.identity;
            return targetTransform != null && HasDisplayPose;
        }

        /// <summary>
        /// 切换目标渲染器可见性；只在状态变化时写入，避免每帧刷新。
        /// </summary>
        /// <param name="hidden">是否隐藏渲染器。</param>
        private void SetRenderersHidden(bool hidden)
        {
            if (hidden == renderersHidden || targetRenderers == null)
            {
                return;
            }

            renderersHidden = hidden;
            foreach (Renderer item in targetRenderers)
            {
                if (item != null)
                {
                    item.enabled = !hidden;
                }
            }
        }
    }
}
