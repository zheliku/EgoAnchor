using System.Collections.Generic;
using System.Text;
using EgoAnchor.Anchor;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace EgoAnchor.Diagnostics
{
    /// <summary>
    /// Anchor 状态与拒绝原因的轻量事件面板。
    ///
    /// 该组件只读取 PoseToAnchorRuntime 的公开诊断属性，把状态变化、policy action 和失败原因
    /// 写入可选 UI Text/TMP_Text。它不订阅网络、不修改 Transform、不驱动状态机。
    /// </summary>
    public sealed class EventLogPanel : MonoBehaviour
    {
        /// <summary>要观察的 anchor runtime 列表。</summary>
        [Header("Inputs")]
        [Tooltip("要观察的 PoseToAnchorRuntime 列表。建议显式绑定 raw、smoothed 或 reliability-aware runtime。")]
        [SerializeField] private List<PoseToAnchorRuntime> runtimes = new List<PoseToAnchorRuntime>();

        /// <summary>可选 Unity UI Text 输出。</summary>
        [Header("Output")]
        [Tooltip("可选 Unity UI Text 输出。为空时只保留内存事件，不更新 UI。")]
        [SerializeField] private Text legacyText;

        /// <summary>可选 TextMeshPro 输出。</summary>
        [Tooltip("可选 TextMeshPro 输出。若同时设置 TMP_Text 和 Text，优先写 TMP_Text。")]
        [SerializeField] private TMP_Text tmpText;

        /// <summary>最多保留事件数量。</summary>
        [Tooltip("最多保留的状态/拒绝原因事件数量。超过后淘汰最旧事件。")]
        [Min(1)]
        [SerializeField] private int maxEvents = 32;

        /// <summary>是否在 Console 中同步输出事件。</summary>
        [Header("Debug")]
        [Tooltip("是否在 Unity Console 中同步输出状态变化和 policy 事件。")]
        [SerializeField] private bool logToConsole;

        /// <summary>最近一次观察到的每个 runtime 状态。</summary>
        private readonly Dictionary<PoseToAnchorRuntime, AnchorState> lastStates = new Dictionary<PoseToAnchorRuntime, AnchorState>();

        /// <summary>最近一次观察到的每个 runtime policy action。</summary>
        private readonly Dictionary<PoseToAnchorRuntime, string> lastActions = new Dictionary<PoseToAnchorRuntime, string>();

        /// <summary>事件环形列表。</summary>
        private readonly Queue<string> events = new Queue<string>();

        /// <summary>UI 文本构造器，避免每帧产生大量临时字符串。</summary>
        private readonly StringBuilder builder = new StringBuilder(1024);

        /// <summary>当前保留的事件数量。</summary>
        public int EventCount => events.Count;

        /// <summary>
        /// Inspector 修改时确保列表非空。
        /// </summary>
        private void OnValidate()
        {
            if (runtimes == null)
            {
                runtimes = new List<PoseToAnchorRuntime>();
            }
        }

        /// <summary>
        /// Unity Update：轮询 runtime 诊断并记录变化。
        /// </summary>
        private void Update()
        {
            if (runtimes == null)
            {
                return;
            }

            foreach (PoseToAnchorRuntime runtime in runtimes)
            {
                if (runtime == null)
                {
                    continue;
                }

                AnchorState state = runtime.CurrentAnchorState;
                string action = runtime.LatestPolicyAction ?? string.Empty;
                bool stateChanged = !lastStates.TryGetValue(runtime, out AnchorState previousState) || previousState != state;
                bool actionChanged = !lastActions.TryGetValue(runtime, out string previousAction) || previousAction != action;
                if (!stateChanged && !actionChanged)
                {
                    continue;
                }

                lastStates[runtime] = state;
                lastActions[runtime] = action;
                AddEvent(FormatEvent(runtime, state, action));
            }
        }

        /// <summary>
        /// 清空事件列表和 UI。
        /// </summary>
        public void ClearEvents()
        {
            events.Clear();
            UpdateText();
        }

        /// <summary>
        /// 记录一条事件并刷新 UI。
        /// </summary>
        /// <param name="message">事件文本。</param>
        private void AddEvent(string message)
        {
            events.Enqueue(message);
            while (events.Count > Mathf.Max(1, maxEvents))
            {
                events.Dequeue();
            }

            if (logToConsole)
            {
                Debug.Log($"[EgoAnchorEventLog] {message}", this);
            }

            UpdateText();
        }

        /// <summary>
        /// 格式化单个 runtime 的状态事件。
        /// </summary>
        /// <param name="runtime">被观察的 runtime。</param>
        /// <param name="state">当前 anchor 状态。</param>
        /// <param name="action">最近 policy action。</param>
        /// <returns>事件文本。</returns>
        private static string FormatEvent(PoseToAnchorRuntime runtime, AnchorState state, string action)
        {
            string reason = runtime.LatestPolicyReason;
            if (string.IsNullOrEmpty(reason))
            {
                reason = runtime.LatestFailure;
            }

            return $"{Time.realtimeSinceStartupAsDouble:F2}s {runtime.name}: state={state} action={action} reason={reason} frame={runtime.LatestAlignedFrameId} score={runtime.LatestReliabilityScore:F2}";
        }

        /// <summary>
        /// 把事件列表写入 UI 文本。
        /// </summary>
        private void UpdateText()
        {
            if (tmpText == null && legacyText == null)
            {
                return;
            }

            builder.Clear();
            foreach (string entry in events)
            {
                builder.AppendLine(entry);
            }

            string text = builder.ToString();
            if (tmpText != null)
            {
                tmpText.text = text;
            }
            else if (legacyText != null)
            {
                legacyText.text = text;
            }
        }
    }
}
