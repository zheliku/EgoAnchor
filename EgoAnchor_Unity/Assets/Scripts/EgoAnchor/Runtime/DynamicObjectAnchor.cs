using System;
using System.Collections.Generic;
using EgoAnchor.Diagnostics;
using EgoAnchor.Policy;
using UnityEngine;

namespace EgoAnchor.Runtime
{
    /// <summary>
    /// dynamic object anchor Transform 应用组件。
    ///
    /// 该组件是场景中真正移动虚拟物体的薄封装：
    /// - 从 PoseToAnchorRuntime 读取 anchor policy 每帧输出的 world pose。
    /// - 把 pose 应用到当前 Transform 或指定目标 Transform。
    /// - 按 anchor 状态控制视觉对象可见度（可选，见 hideWhenAnchorNotTracking）。
    /// - 不订阅网络，不解码 Protobuf，不做平滑或状态机。
    ///
    /// 论文/实验对照由多个 PoseToAnchorRuntime + AnchorPolicyHost module 组合表达；
    /// HoldStrategy（ZOH 零阶保持）也是 policy 输出的一种，不在 Transform 应用层选择双路模式。
    /// </summary>
    [DefaultExecutionOrder(0)]
    public sealed class DynamicObjectAnchor : MonoBehaviour
    {
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<DynamicObjectAnchor>();

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

        /// <summary>可选的外部视觉对象根节点列表；为空时使用 targetTransform 下的 Renderer。</summary>
        [Tooltip("可选的外部视觉 Transform 列表（例如 Mesh、Axis）。配置后，隐藏/显示时切换这些对象及其子物体的 GameObject.activeSelf；全部留空则切换 targetTransform 下所有 Renderer。不要指定锚点运行时所在对象或其父物体。")]
        [SerializeField] private List<Transform> visualTransforms;

        /// <summary>没有有效 pose 时是否保持上一帧 Transform。</summary>
        [Tooltip("没有有效 pose 时是否保持上一帧 Transform。开启时物体停在最后一帧位置；关闭时隐藏物体渲染，避免停留在已失效的旧 pose。")]
        [SerializeField] private bool holdLastPoseWhenMissing = true;

        /// <summary>锚点失去可信追踪时是否隐藏视觉对象。</summary>
        [Tooltip("是否按 anchor 状态控制可见度。开启后只在 Tracking 显示；Uncertain/Lost/Searching（含遮挡与重新获取）隐藏，回到 Tracking 后自动恢复。Paused 保持暂停前的可见度。关闭时保持原有 hold-last 可见度行为。")]
        [SerializeField] private bool hideWhenAnchorNotTracking;

        /// <summary>隐藏前需要持续处于不可信状态的时间，单位秒。</summary>
        [Tooltip("隐藏防抖时间，单位秒。只对“显示→隐藏”生效，用于吸收单帧低分或偶发 GPU 卡顿导致的瞬时 Uncertain；恢复显示始终立即生效。0=不防抖。")]
        [SerializeField] private float hideDelaySeconds = 0.35f;

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

        /// <summary>当前是否因缺失 pose 或不可追踪状态而隐藏了视觉对象。</summary>
        private bool renderersHidden;

        /// <summary>校验通过、可以安全直接启停的外部视觉对象。</summary>
        private Transform[] toggleableVisuals;

        /// <summary>当前候选可见度持续成立的起始时间，单位秒；用于隐藏防抖。</summary>
        private double pendingVisibleSinceSeconds;

        /// <summary>当前候选可见度取值。</summary>
        private bool pendingVisible;

        /// <summary>是否已经产生过一次可见度判定。</summary>
        private bool hasVisibilityDecision;

        /// <summary>防抖后本帧生效的可见度。</summary>
        private bool visibleNow;

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
            toggleableVisuals = ResolveToggleableVisuals();

            // 视觉对象路径下 renderersHidden 必须反映场景里已经写好的 active 状态，
            // 否则首次 SetVisualHidden(false) 会被"状态未变"判定吞掉。
            // 多条目混合时按"任一隐藏即视为隐藏"取值，避免 HasDisplayPose 谎报完整可见。
            foreach (Transform item in toggleableVisuals)
            {
                if (!item.gameObject.activeSelf)
                {
                    renderersHidden = true;
                    break;
                }
            }
        }

        /// <summary>
        /// 挑出可以安全直接启停的视觉对象。
        ///
        /// 关键约束：被停用的节点下不能含有推进 anchor 状态的组件。若某个 visualTransform 是
        /// 本组件或 runtime 的祖先，停用后 runtime.LateUpdate 不再执行，anchor 状态永远无法
        /// 回到 Tracking，视觉对象将永久隐藏（死锁）。这类条目被剔除并告警。
        /// </summary>
        /// <returns>校验通过的视觉对象数组；无可用条目时为空数组。</returns>
        private Transform[] ResolveToggleableVisuals()
        {
            if (visualTransforms == null || visualTransforms.Count == 0)
            {
                return Array.Empty<Transform>();
            }

            List<Transform> accepted = new List<Transform>(visualTransforms.Count);
            foreach (Transform item in visualTransforms)
            {
                if (item == null || accepted.Contains(item))
                {
                    continue;
                }

                if (item == transform || transform.IsChildOf(item))
                {
                    Log.Warning($"visualTransforms 中的 \"{item.name}\" 是本组件所在对象或其父物体，停用后本组件不再更新；已忽略该条目。", this);
                    continue;
                }

                if (runtime != null && runtime.transform.IsChildOf(item))
                {
                    Log.Warning($"visualTransforms 中的 \"{item.name}\" 是 PoseToAnchorRuntime 所在对象或其父物体，停用后 anchor 状态无法推进且永久隐藏；已忽略该条目。", this);
                    continue;
                }

                accepted.Add(item);
            }

            return accepted.ToArray();
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
            double now = Time.realtimeSinceStartupAsDouble;

            if (!hasPose)
            {
                if (hideWhenAnchorNotTracking)
                {
                    // 无输出 pose 一定不可显示，直接进防抖判定，不受 hold-last 开关影响。
                    SetVisualHidden(!StabilizeVisibility(false, now));
                    return;
                }

                if (!holdLastPoseWhenMissing)
                {
                    lastAppliedFrameId = -1;
                    SetVisualHidden(true);
                }
                return;
            }

            if (hideWhenAnchorNotTracking)
            {
                AnchorState state = runtime.CurrentAnchorState;

                // Paused 是用户主动暂停更新，不是失去追踪：冻结当前可见度，不参与防抖判定。
                if (state != AnchorState.Paused)
                {
                    SetVisualHidden(!StabilizeVisibility(state == AnchorState.Tracking, now));
                }
            }
            else
            {
                SetVisualHidden(false);
            }

            if (applyPosition)
            {
                targetTransform.position = pose.position;
            }

            if (applyRotation)
            {
                targetTransform.rotation = pose.rotation;
            }

            // 隐藏期间仍写入实际来源帧：LastAppliedFrameId 已由 HasDisplayPose 门控返回 -1，
            // 这里保留真值以便 Inspector/日志看到最后一次应用的帧，并在恢复显示时立即可用。
            lastAppliedFrameId = runtime.LatestAcceptedFrameId;
        }

        /// <summary>
        /// 对可见度判定做单向防抖：恢复显示立即生效，隐藏需要不可信状态持续 hideDelaySeconds。
        ///
        /// 质量评估门控拒绝单帧即会把状态打到 Uncertain，无防抖会让物体逐帧闪灭。
        /// 该防抖只影响本组件的显示，不改变 anchor policy 状态与输出 pose。
        /// </summary>
        /// <param name="displayable">本帧 anchor 状态是否属于可显示状态。</param>
        /// <param name="nowSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <returns>本帧最终是否显示视觉对象。</returns>
        private bool StabilizeVisibility(bool displayable, double nowSeconds)
        {
            if (!hasVisibilityDecision)
            {
                // 首次判定不防抖：冷启动尚未追踪上时必须立刻隐藏，不能让物体先停在初始位置。
                hasVisibilityDecision = true;
                pendingVisible = displayable;
                pendingVisibleSinceSeconds = nowSeconds;
                visibleNow = displayable;
                return visibleNow;
            }

            if (pendingVisible != displayable)
            {
                pendingVisible = displayable;
                pendingVisibleSinceSeconds = nowSeconds;
            }

            if (displayable)
            {
                visibleNow = true;
            }
            else if (visibleNow && (hideDelaySeconds <= 0f || nowSeconds - pendingVisibleSinceSeconds >= hideDelaySeconds))
            {
                visibleNow = false;
            }

            return visibleNow;
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
        /// 切换视觉对象可见性；优先启停外部视觉对象，否则切换目标渲染器。
        /// </summary>
        /// <param name="hidden">是否隐藏视觉对象。</param>
        private void SetVisualHidden(bool hidden)
        {
            // 可见度未变化时不重写 GameObject.activeSelf，保留 Inspector 或外部脚本的手动开关。
            if (hidden == renderersHidden)
            {
                return;
            }

            if (toggleableVisuals != null && toggleableVisuals.Length > 0)
            {
                renderersHidden = hidden;
                foreach (Transform item in toggleableVisuals)
                {
                    if (item != null)
                    {
                        item.gameObject.SetActive(!hidden);
                    }
                }

                return;
            }

            if (targetRenderers == null)
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
