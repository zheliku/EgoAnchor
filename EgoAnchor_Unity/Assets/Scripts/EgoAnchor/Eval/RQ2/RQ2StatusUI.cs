using System.Text;
using TMPro;
using UnityEngine;

namespace EgoAnchor.Eval.RQ2
{
    /// <summary>
    /// RQ2 采集状态面板，集中显示 session、试次和目标速度。
    /// </summary>
    public sealed class RQ2StatusUI : MonoBehaviour
    {
        /// <summary>当前 RQ2 试次上下文来源。</summary>
        [Header("References")]
        [Tooltip("当前 RQ2 试次上下文来源。")]
        [SerializeField] private RQ2TrialSelector selector;

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

        /// <summary>当前试次编号与场景文本。</summary>
        [Tooltip("显示当前试次编号与运动场景。")]
        [SerializeField] private TextMeshProUGUI trialText;

        /// <summary>目标线速度或角速度文本。</summary>
        [Tooltip("显示当前试次预设目标速度。")]
        [SerializeField] private TextMeshProUGUI targetSpeedText;

        /// <summary>试次总时长文本。</summary>
        [Tooltip("显示当前试次从数字键按下后的总时长。")]
        [SerializeField] private TextMeshProUGUI trialDurationText;

        /// <summary>实验操作按键对照文本。</summary>
        [Tooltip("显示试次与 session 操作按键。")]
        [SerializeField] private TextMeshProUGUI keyBindingsText;

        /// <summary>状态面板每秒刷新次数。</summary>
        [Header("Settings")]
        [Tooltip("状态面板每秒刷新次数。")]
        [Min(1f)]
        [SerializeField] private float updateRate = 10f;

        /// <summary>距离下一次面板刷新剩余的累计时间。</summary>
        private float _updateTimer;

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

            RQ2Condition condition = selector != null
                ? selector.CurrentCondition
                : RQ2Condition.None;
            int trialId = selector != null ? selector.CurrentTrialId : -1;

            if (trialText != null)
            {
                trialText.text = BuildTrialText(trialId, condition);
            }

            if (trialDurationText != null)
            {
                double trialDuration = selector != null ? selector.CurrentTrialDurationSeconds : 0.0;
                trialDurationText.text = $"Trial Envelope: {EvalStatusText.Duration(trialDuration)}";
            }

            if (targetSpeedText != null)
                targetSpeedText.text = BuildTargetSpeedText(condition);

            UpdateKeyBindings(condition);
        }

        /// <summary>按当前场景生成唯一适用的目标速度文本。</summary>
        private string BuildTargetSpeedText(RQ2Condition condition)
        {
            if (selector == null) return "Nominal target: -";
            if (condition == RQ2Condition.Rotation)
            {
                float angular = selector.TargetAngularSpeedDegS;
                return float.IsNaN(angular) ? "Nominal Target: -" : $"Target: {angular:F1} deg/s";
            }
            if (condition == RQ2Condition.SlowTranslation || condition == RQ2Condition.FastMotion)
            {
                float linear = selector.TargetLinearSpeedMs;
                return float.IsNaN(linear) ? "Nominal Target: -" : $"Target: {linear:F2} m/s";
            }
            return "Nominal Target: -";
        }

        /// <summary>按当前试次场景绘制操作按键表，并高亮对应的场景快捷键。</summary>
        private void UpdateKeyBindings(RQ2Condition active)
        {
            if (keyBindingsText == null) return;

            keyBindingsText.text = BuildKeyBindingsText(active);
        }

        /// <summary>生成当前试次文本；活动试次同时显示对应数字键。</summary>
        private static string BuildTrialText(int trialId, RQ2Condition condition)
        {
            return trialId > 0
                ? $"Trial {trialId}: {condition.GetDisplayName()} (Key {(int)condition})"
                : "Trial: Idle";
        }

        /// <summary>生成完整快捷键表；活动场景使用与 RQ1 相同的金色粗体和指示符。</summary>
        private static string BuildKeyBindingsText(RQ2Condition active)
        {
            var sb = new StringBuilder(256);
            AppendConditionRow(sb, "[1]", RQ2Condition.SlowTranslation, active);
            AppendConditionRow(sb, "[2]", RQ2Condition.FastMotion, active);
            AppendConditionRow(sb, "[3]", RQ2Condition.Rotation, active);
            sb.AppendLine();
            sb.AppendLine("[0] End Trial");
            sb.Append("[F7] Start Recording   [F8] Stop Recording");
            return sb.ToString();
        }

        /// <summary>追加一行场景快捷键；当前场景沿用 RQ1 的高亮标记。</summary>
        private static void AppendConditionRow(
            StringBuilder sb,
            string key,
            RQ2Condition condition,
            RQ2Condition active)
        {
            string content = $"{key}  {condition.GetDisplayName()}";
            EvalStatusText.AppendSelectionRow(sb, content, condition == active);
        }
    }
}
