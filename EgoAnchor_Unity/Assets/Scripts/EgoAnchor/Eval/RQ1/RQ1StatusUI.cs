using System.Text;
using TMPro;
using UnityEngine;

namespace EgoAnchor.Eval.RQ1
{
    /// <summary>
    /// RQ1 状态面板，显示录制 session、当前指标及其操作快捷键。
    /// </summary>
    public sealed class RQ1StatusUI : MonoBehaviour
    {
        /// <summary>当前 RQ1 指标标记来源。</summary>
        [Header("References")]
        [Tooltip("当前 RQ1 指标标记来源。")]
        [SerializeField] private RQ1MetricSelector selector;

        /// <summary>评估 session 录制状态来源。</summary>
        [Tooltip("评估 session 录制状态来源。")]
        [SerializeField] private EvalSession evalSession;

        /// <summary>录制状态文本。</summary>
        [Header("UI Elements")]
        [Tooltip("显示 Recording 或 Not Recording。")]
        [SerializeField] private TextMeshProUGUI recordingStatusText;

        /// <summary>session id 文本。</summary>
        [Tooltip("显示当前 session id。")]
        [SerializeField] private TextMeshProUGUI sessionIdText;

        /// <summary>session 录制时长文本。</summary>
        [Tooltip("显示本次 session 的录制时长。")]
        [SerializeField] private TextMeshProUGUI durationText;

        /// <summary>当前指标与对应数字键文本。</summary>
        [Tooltip("显示当前 RQ1 指标及对应数字键。")]
        [SerializeField] private TextMeshProUGUI currentMetricText;

        /// <summary>当前指标建议时长文本。</summary>
        [Tooltip("显示当前指标的建议时长或单次事件提示。")]
        [SerializeField] private TextMeshProUGUI suggestedDurationText;

        /// <summary>当前指标已标记时长文本。</summary>
        [Tooltip("显示当前指标已连续标记的时长。")]
        [SerializeField] private TextMeshProUGUI markedDurationText;

        /// <summary>RQ1 操作快捷键文本。</summary>
        [Tooltip("显示指标标记和 session 控制快捷键。")]
        [SerializeField] private TextMeshProUGUI keyBindingsText;

        /// <summary>状态面板每秒刷新次数。</summary>
        [Header("Settings")]
        [Tooltip("状态面板每秒刷新次数。")]
        [Min(1f)]
        [SerializeField] private float updateRate = 10f;

        /// <summary>当前面板刷新周期内累计的时间。</summary>
        private float _updateTimer;

        /// <summary>面板首次观察到当前 session 正在录制的单调时刻。</summary>
        private double _sessionStartMonoMs;

        /// <summary>初始化时立即绘制完整状态面板。</summary>
        private void Start()
        {
            UpdateUI();
        }

        /// <summary>按配置频率刷新状态，避免每帧重建文本。</summary>
        private void Update()
        {
            _updateTimer += Time.deltaTime;
            float interval = 1f / Mathf.Max(1f, updateRate);
            if (_updateTimer < interval) return;

            _updateTimer = 0f;
            UpdateUI();
        }

        /// <summary>根据 EvalSession 与 selector 的当前状态更新所有文本。</summary>
        private void UpdateUI()
        {
            bool recording = evalSession != null && evalSession.IsRecording;
            if (recordingStatusText != null)
            {
                recordingStatusText.text = EvalStatusText.Recording(recording);
                recordingStatusText.color = recording ? Color.red : Color.gray;
            }

            if (sessionIdText != null)
            {
                string sessionId = evalSession != null ? evalSession.SessionId : string.Empty;
                sessionIdText.text = EvalStatusText.Session(sessionId);
            }

            UpdateSessionDuration(recording);

            RQ1MetricType metric = selector != null
                ? selector.CurrentMetric
                : RQ1MetricType.None;
            if (currentMetricText != null)
            {
                currentMetricText.text = metric == RQ1MetricType.None
                    ? "Current Metric: None"
                    : $"Current Metric: {metric.GetDisplayName()} (Key {(int)metric})";
            }

            if (suggestedDurationText != null)
            {
                int suggestedDuration = metric.GetSuggestedDuration();
                suggestedDurationText.text = suggestedDuration > 0
                    ? $"Suggested: {suggestedDuration}s"
                    : metric == RQ1MetricType.OcclusionRecovery
                        ? "Suggested: Single event"
                        : "Suggested: -";
            }

            if (markedDurationText != null)
            {
                double markedDuration = selector != null
                    ? selector.CurrentMetricDuration
                    : 0.0;
                markedDurationText.text = $"Marked: {EvalStatusText.Duration(markedDuration)}";
            }

            if (keyBindingsText != null)
            {
                keyBindingsText.text = BuildKeyBindingsText(metric);
            }
        }

        /// <summary>更新 session 计时；停止录制后重置本地起点。</summary>
        private void UpdateSessionDuration(bool recording)
        {
            if (durationText == null) return;

            if (!recording)
            {
                _sessionStartMonoMs = 0.0;
                durationText.text = "Duration: 00:00";
                return;
            }

            double nowMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            if (_sessionStartMonoMs <= 0.0)
            {
                _sessionStartMonoMs = nowMs;
            }

            double elapsedSeconds = (nowMs - _sessionStartMonoMs) / 1000.0;
            durationText.text = $"Duration: {EvalStatusText.Duration(elapsedSeconds)}";
        }

        /// <summary>生成完整 RQ1 快捷键表，活动指标只高亮一行。</summary>
        private static string BuildKeyBindingsText(RQ1MetricType active)
        {
            var builder = new StringBuilder(256);
            AppendMetricRow(
                builder, "[1]", RQ1MetricType.StaticObservation, "80s", active);
            AppendMetricRow(
                builder, "[2]", RQ1MetricType.OcclusionRecovery, "Single", active);
            builder.AppendLine();
            builder.AppendLine("[0]  Clear Marking");
            builder.Append("[F7] Start Recording   [F8] Stop Recording");
            return builder.ToString();
        }

        /// <summary>追加一行 RQ1 指标快捷键，并应用公共活动行样式。</summary>
        private static void AppendMetricRow(
            StringBuilder builder,
            string key,
            RQ1MetricType type,
            string duration,
            RQ1MetricType active)
        {
            string content = $"{key}  {type.GetDisplayName()}  {duration}";
            EvalStatusText.AppendSelectionRow(builder, content, type == active);
        }
    }
}
