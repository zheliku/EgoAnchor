using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace EgoAnchor.Eval.RQ1
{
    /// <summary>
    /// RQ1 状态 UI 面板。
    /// <para>
    /// 显示当前录制状态、指标标记、建议时长等信息。
    /// </para>
    /// </summary>
    public sealed class RQ1StatusUI : MonoBehaviour
    {
        // ── References ──

        [Header("References")]
        [Tooltip("RQ1 指标记录器。")]
        [SerializeField] private RQ1MetricRecorder recorder;

        [Tooltip("评估 session 控制器。")]
        [SerializeField] private EvalSession evalSession;

        [Header("UI Elements")]
        [Tooltip("录制状态文本（例如：● 录制中）。")]
        [SerializeField] private TextMeshProUGUI recordingStatusText;

        [Tooltip("Session ID 文本。")]
        [SerializeField] private TextMeshProUGUI sessionIdText;

        [Tooltip("录制时长文本。")]
        [SerializeField] private TextMeshProUGUI durationText;

        [Tooltip("当前指标文本（例如：快速挥动 (按键 3)）。")]
        [SerializeField] private TextMeshProUGUI currentMetricText;

        [Tooltip("建议时长文本（例如：建议时长: 20秒）。")]
        [SerializeField] private TextMeshProUGUI suggestedDurationText;

        [Tooltip("已标记时长文本（例如：已标记: 00:08）。")]
        [SerializeField] private TextMeshProUGUI markedDurationText;

        [Tooltip("按键对照表文本（列出所有指标和对应按键）。")]
        [SerializeField] private TextMeshProUGUI keyBindingsText;

        [Header("Settings")]
        [Tooltip("UI 更新频率（Hz）。")]
        [SerializeField] private float updateRate = 10f;

        // ── State ──

        private double _sessionStartMonoMs;
        private float _updateTimer;

        // ── Unity 生命周期 ──

        private void Start()
        {
            if (evalSession != null)
            {
                // 可以订阅 session 开始/停止事件（如果 EvalSession 有提供）
            }

            UpdateUI();
        }

        private void Update()
        {
            _updateTimer += Time.deltaTime;
            if (_updateTimer >= 1f / updateRate)
            {
                _updateTimer = 0f;
                UpdateUI();
            }
        }

        // ── UI 更新 ──

        private void UpdateUI()
        {
            // 录制状态
            if (recordingStatusText != null)
            {
                bool isRecording = evalSession != null && evalSession.IsRecording;
                recordingStatusText.text = isRecording ? "● Recording" : "○ Not Recording";
                recordingStatusText.color = isRecording ? Color.red : Color.gray;
            }

            // Session ID
            if (sessionIdText != null)
            {
                string sessionId = evalSession != null ? evalSession.SessionId : "";
                sessionIdText.text = string.IsNullOrEmpty(sessionId) ? "Session: Not Started" : $"Session: {sessionId}";
            }

            // 录制时长
            if (durationText != null)
            {
                if (evalSession != null && evalSession.IsRecording)
                {
                    double nowMs = Time.realtimeSinceStartupAsDouble * 1000.0;
                    if (_sessionStartMonoMs == 0.0) _sessionStartMonoMs = nowMs;
                    double elapsedS = (nowMs - _sessionStartMonoMs) / 1000.0;
                    int minutes = (int)(elapsedS / 60);
                    int seconds = (int)(elapsedS % 60);
                    durationText.text = $"Duration: {minutes:00}:{seconds:00}";
                }
                else
                {
                    _sessionStartMonoMs = 0.0;
                    durationText.text = "Duration: 00:00";
                }
            }

            // 当前指标
            if (currentMetricText != null && recorder != null)
            {
                RQ1MetricType metric = recorder.CurrentMetric;
                if (metric == RQ1MetricType.None)
                {
                    currentMetricText.text = "Current Metric: None";
                }
                else
                {
                    int keyNumber = (int)metric;
                    string displayName = metric.GetDisplayName();
                    currentMetricText.text = $"Current Metric: {displayName} (Key {keyNumber})";
                }
            }

            // 建议时长
            if (suggestedDurationText != null && recorder != null)
            {
                RQ1MetricType metric = recorder.CurrentMetric;
                int suggestedDuration = metric.GetSuggestedDuration();
                if (suggestedDuration > 0)
                {
                    suggestedDurationText.text = $"Suggested: {suggestedDuration}s";
                }
                else if (metric == RQ1MetricType.OcclusionRecovery)
                {
                    suggestedDurationText.text = "Suggested: Single event";
                }
                else
                {
                    suggestedDurationText.text = "Suggested: -";
                }
            }

            // 已标记时长
            if (markedDurationText != null && recorder != null)
            {
                if (recorder.CurrentMetric != RQ1MetricType.None)
                {
                    double markedDuration = recorder.CurrentMetricDuration;
                    int minutes = (int)(markedDuration / 60);
                    int seconds = (int)(markedDuration % 60);
                    markedDurationText.text = $"Marked: {minutes:00}:{seconds:00}";
                }
                else
                {
                    markedDurationText.text = "Marked: 00:00";
                }
            }

            // 按键对照表
            UpdateKeyBindings();
        }

        private void UpdateKeyBindings()
        {
            if (keyBindingsText == null) return;

            RQ1MetricType active = recorder != null ? recorder.CurrentMetric : RQ1MetricType.None;

            // 每行格式：[键] 名称  时长提示  ← 当前
            var sb = new System.Text.StringBuilder();

            AppendMetricRow(sb, "[1]", RQ1MetricType.StaticObservation, "60s",   active);
            AppendMetricRow(sb, "[2]", RQ1MetricType.SlowTranslation,   "20s",   active);
            AppendMetricRow(sb, "[3]", RQ1MetricType.FastMotion,        "20s",   active);
            AppendMetricRow(sb, "[4]", RQ1MetricType.Rotation,          "20s",   active);
            AppendMetricRow(sb, "[5]", RQ1MetricType.OcclusionRecovery, "Single",  active);
            sb.AppendLine();
            sb.AppendLine("[0]  Clear Marking");
            sb.Append("[F7] Start Recording   [F8] Stop Recording");

            keyBindingsText.text = sb.ToString();
        }

        private static void AppendMetricRow(
            System.Text.StringBuilder sb,
            string key,
            RQ1MetricType type,
            string duration,
            RQ1MetricType active)
        {
            bool isActive = type == active;
            string name = type.GetDisplayName();

            if (isActive)
                sb.AppendLine($"<color=#FFD700><b>{key}  {name,-8}  {duration}  ◀</b></color>");
            else
                sb.AppendLine($"{key}  {name,-8}  {duration}");
        }
    }
}
