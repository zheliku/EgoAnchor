using EgoAnchor.Policy;
using EgoAnchor.Runtime;
using TMPro;
using UnityEngine;

namespace AnchorViz
{
    /// <summary>
    /// 在 anchor 上方显示其当前状态（Tracking / Lost 等）的状态标签。
    ///
    /// 与 EgoAnchor 库解耦：只通过 PoseToAnchorRuntime 的公开只读接口读状态，不改 anchor 逻辑。
    /// 用法：把本组件挂到 anchor 下的一个带 TextMeshPro 的子物体上，Inspector 里指定
    /// runtime、label、（可选）facingCamera。字号/字型/对齐等字体参数全在 TextMeshPro
    /// 组件里配置，本脚本只更新文字内容、颜色，并让文字朝向相机。
    /// </summary>
    public sealed class AnchorStatusLabel : MonoBehaviour
    {
        /// <summary>简化后的对用户友好的状态分类。</summary>
        private enum DisplayStatus
        {
            Tracking,
            Static,
            Uncertain,
            Lost,
            Searching,
            Paused,
            Error,
        }

        /// <summary>状态来源。为空时自动向父级查找 PoseToAnchorRuntime。</summary>
        [Header("References")]
        [Tooltip("状态来源 PoseToAnchorRuntime。留空时自动向父级查找。")]
        [SerializeField] private PoseToAnchorRuntime runtime;

        /// <summary>显示文字的 TMP 组件。为空时自动取本物体上的。字体参数请在该组件里配置。</summary>
        [Tooltip("显示文字的 TextMeshPro 组件。留空时取本物体上的。字号/字型/对齐在此组件配置。")]
        [SerializeField] private TMP_Text label;

        /// <summary>文字朝向的相机。为空时自动取 Camera.main。</summary>
        [Tooltip("文字朝向的相机。留空时自动取 Camera.main。")]
        [SerializeField] private Camera facingCamera;

        /// <summary>是否让文字朝向相机位置（LookAt）。</summary>
        [Header("Facing")]
        [Tooltip("开启后每帧让文字朝向相机位置。这是 LookAt 行为：纯转头（相机原地旋转）时文字不动，只有相机移动到不同位置才转向相机。")]
        [SerializeField] private bool faceCamera = true;

        /// <summary>文字方向反了时翻转，绕 Y 轴 180°。</summary>
        [Tooltip("文字显示成镜像/背面时勾选，绕 Y 轴翻转 180°。")]
        [SerializeField] private bool flip = false;

        /// <summary>是否简化状态显示。</summary>
        [Header("Display")]
        [Tooltip("简化显示：显示 Tracking / Static / Uncertain / Lost / Searching / Paused / Error，并隐藏 Coasting、Relocalizing 等内部状态。关闭则显示原始状态，便于调试。")]
        [SerializeField] private bool simplified = true;

        /// <summary>简化模式下，Uncertain 候选状态需持续多久才显示，单位秒。</summary>
        [Tooltip("简化模式下，Static/Tracking 切到 Uncertain 前的显示防抖时间。用于吸收低帧率 GPU 或偶发低分帧导致的短暂 FrozenUncertain；不改变实际 anchor policy。0=关闭防抖。")]
        [SerializeField] private float uncertainDelaySeconds = 0.75f;

        /// <summary>状态颜色（简化模式与详细模式共用）。</summary>
        [Header("Colors")]
        [SerializeField] private Color trackingColor = new Color(0.30f, 0.85f, 0.35f);
        [SerializeField] private Color staticColor = new Color(0.20f, 0.70f, 0.90f);
        [SerializeField] private Color uncertainColor = new Color(1.00f, 0.60f, 0.10f);
        [SerializeField] private Color lostColor = new Color(0.95f, 0.25f, 0.25f);
        [SerializeField] private Color searchingColor = new Color(0.30f, 0.75f, 0.95f);
        [SerializeField] private Color pausedColor = new Color(0.70f, 0.70f, 0.70f);
        [SerializeField] private Color errorColor = new Color(1.00f, 0.15f, 0.45f);

        /// <summary>仅详细模式（simplified=false）使用的额外状态颜色。</summary>
        [Header("Colors (detailed mode only)")]
        [SerializeField] private Color coastingColor = new Color(0.70f, 0.85f, 0.30f);
        [SerializeField] private Color relocalizingColor = new Color(0.45f, 0.55f, 1.00f);
        [SerializeField] private Color uninitializedColor = new Color(0.55f, 0.55f, 0.55f);

        private AnchorState lastState = (AnchorState)(-1);
        private bool lastStaticLocked;
        private bool lastSimplified;
        private bool hasDisplayedStatus;
        private DisplayStatus displayedStatus;
        private DisplayStatus pendingStatus;
        private double pendingSinceSeconds;

        private void Awake()
        {
            if (label == null)
            {
                label = GetComponent<TMP_Text>();
            }

            if (runtime == null)
            {
                runtime = GetComponentInParent<PoseToAnchorRuntime>();
            }
        }

        // 编辑器里改开关/颜色后强制下一帧刷新。
        private void OnValidate()
        {
            lastState = (AnchorState)(-1);
            hasDisplayedStatus = false;
        }

        // LateUpdate：在 anchor pose 应用（DynamicObjectAnchor 也在 LateUpdate）与相机移动之后再对齐朝向。
        private void LateUpdate()
        {
            if (runtime == null || label == null)
            {
                return;
            }

            RefreshStatus(Time.realtimeSinceStartupAsDouble);

            if (faceCamera)
            {
                FaceCamera();
            }
        }

        /// <summary>读取 runtime 状态并刷新标签文本与颜色。</summary>
        private void RefreshStatus(double nowSeconds)
        {
            AnchorState state = runtime.CurrentAnchorState;
            bool staticLocked = runtime.LatestStaticLocked;

            if (simplified)
            {
                DisplayStatus rawStatus = Simplify(state, staticLocked);
                DisplayStatus status = StabilizeSimplifiedStatus(rawStatus, nowSeconds);
                if (hasDisplayedStatus && status == displayedStatus && state == lastState && staticLocked == lastStaticLocked && simplified == lastSimplified)
                {
                    return;
                }

                displayedStatus = status;
                hasDisplayedStatus = true;
                lastState = state;
                lastStaticLocked = staticLocked;
                lastSimplified = simplified;
                label.text = SimplifiedText(status);
                label.color = SimplifiedColor(status);
            }
            else
            {
                hasDisplayedStatus = false;
                if (state == lastState && staticLocked == lastStaticLocked && simplified == lastSimplified)
                {
                    return;
                }

                lastState = state;
                lastStaticLocked = staticLocked;
                lastSimplified = simplified;
                label.text = DetailedText(state, staticLocked);
                label.color = DetailedColor(state);
            }
        }

        /// <summary>对简化显示状态做轻量滞回，避免短暂 Uncertain 抖动画面标签。</summary>
        private DisplayStatus StabilizeSimplifiedStatus(DisplayStatus rawStatus, double nowSeconds)
        {
            if (!hasDisplayedStatus)
            {
                pendingStatus = rawStatus;
                pendingSinceSeconds = nowSeconds;
                return rawStatus;
            }

            if (rawStatus == displayedStatus)
            {
                pendingStatus = rawStatus;
                pendingSinceSeconds = nowSeconds;
                return rawStatus;
            }

            float delaySeconds = DisplayTransitionDelay(displayedStatus, rawStatus);
            if (delaySeconds <= 0.0f)
            {
                pendingStatus = rawStatus;
                pendingSinceSeconds = nowSeconds;
                return rawStatus;
            }

            if (pendingStatus != rawStatus)
            {
                pendingStatus = rawStatus;
                pendingSinceSeconds = nowSeconds;
                return displayedStatus;
            }

            return nowSeconds - pendingSinceSeconds >= delaySeconds ? rawStatus : displayedStatus;
        }

        /// <summary>返回指定显示状态转移需要等待的时间，单位秒。</summary>
        private float DisplayTransitionDelay(DisplayStatus from, DisplayStatus to)
        {
            if (to == DisplayStatus.Uncertain && (from == DisplayStatus.Static || from == DisplayStatus.Tracking))
            {
                return Mathf.Max(0.0f, uncertainDelaySeconds);
            }

            return 0.0f;
        }

        private void FaceCamera()
        {
            Camera cam = ResolveCamera();
            if (cam == null)
            {
                return;
            }

            // 用"相机→文字"的位置差做朝向（而非相机的 forward），这样纯转头时朝向不变。
            // TMP 文字正面朝局部 -Z，故让 +Z 背离相机即可正面朝向相机；世界 up 让文字保持竖直。
            Vector3 dir = transform.position - cam.transform.position;
            if (dir.sqrMagnitude < 1e-8f)
            {
                return;
            }

            Quaternion look = Quaternion.LookRotation(dir.normalized, Vector3.up);
            if (flip)
            {
                look *= Quaternion.Euler(0f, 180f, 0f);
            }

            transform.rotation = look;
        }

        private Camera ResolveCamera()
        {
            if (facingCamera == null)
            {
                facingCamera = Camera.main;
            }

            return facingCamera;
        }

        /// <summary>把 9 个内部状态归并为对用户友好的分类。staticLocked=true 且正在跟踪时显示 Static。</summary>
        private static DisplayStatus Simplify(AnchorState state, bool staticLocked)
        {
            switch (state)
            {
                case AnchorState.Tracking:
                case AnchorState.Coasting: // 帧间正常空档（<coastTimeout），物体仍在预测位置
                    // 静止锁定中 = 物体已静止并被锚定冻结，单列 Static 让用户看到"已稳定锁定"而非普通跟踪。
                    return staticLocked ? DisplayStatus.Static : DisplayStatus.Tracking;
                case AnchorState.FrozenUncertain: // pose 不可靠、已冻结降级，不能当作正常跟踪
                    return DisplayStatus.Uncertain;
                case AnchorState.Lost:
                    return DisplayStatus.Lost;
                case AnchorState.Paused:
                    return DisplayStatus.Paused;
                case AnchorState.Error:
                    return DisplayStatus.Error;
                default: // Uninitialized / Searching / Relocalizing
                    return DisplayStatus.Searching;
            }
        }

        private static string SimplifiedText(DisplayStatus status)
        {
            switch (status)
            {
                case DisplayStatus.Tracking: return "Tracking";
                case DisplayStatus.Static: return "Static";
                case DisplayStatus.Uncertain: return "Uncertain";
                case DisplayStatus.Lost: return "Lost";
                case DisplayStatus.Searching: return "Searching";
                case DisplayStatus.Paused: return "Paused";
                default: return "Error";
            }
        }

        private Color SimplifiedColor(DisplayStatus status)
        {
            switch (status)
            {
                case DisplayStatus.Tracking: return trackingColor;
                case DisplayStatus.Static: return staticColor;
                case DisplayStatus.Uncertain: return uncertainColor;
                case DisplayStatus.Lost: return lostColor;
                case DisplayStatus.Searching: return searchingColor;
                case DisplayStatus.Paused: return pausedColor;
                default: return errorColor;
            }
        }

        /// <summary>详细模式：每个原始状态的简短文字。</summary>
        private static string DetailedText(AnchorState state, bool staticLocked)
        {
            switch (state)
            {
                case AnchorState.Tracking: return staticLocked ? "Locked" : "Tracking";
                case AnchorState.Coasting: return "Coasting";
                case AnchorState.FrozenUncertain: return "Uncertain";
                case AnchorState.Searching: return "Searching";
                case AnchorState.Relocalizing: return "Relocating";
                case AnchorState.Lost: return "Lost";
                case AnchorState.Paused: return "Paused";
                case AnchorState.Error: return "Error";
                default: return "Init";
            }
        }

        private Color DetailedColor(AnchorState state)
        {
            switch (state)
            {
                case AnchorState.Tracking: return trackingColor;
                case AnchorState.Coasting: return coastingColor;
                case AnchorState.FrozenUncertain: return uncertainColor;
                case AnchorState.Searching: return searchingColor;
                case AnchorState.Relocalizing: return relocalizingColor;
                case AnchorState.Lost: return lostColor;
                case AnchorState.Paused: return pausedColor;
                case AnchorState.Error: return errorColor;
                default: return uninitializedColor;
            }
        }
    }
}
