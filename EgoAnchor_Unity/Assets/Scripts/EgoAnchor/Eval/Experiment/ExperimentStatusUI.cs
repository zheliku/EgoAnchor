using System.Text;
using TMPro;
using UnityEngine;

namespace EgoAnchor.Eval.Experiment
{
    /// <summary>实验采集实时状态面板，显示 session、场景、trial 和人工事件上下文。</summary>
    public sealed class ExperimentStatusUI : MonoBehaviour
    {
        /// <summary>提供实验上下文的 selector。</summary>
        [Header("References")]
        [Tooltip("实验上下文选择器。")]
        [SerializeField] private ExperimentTrialSelector selector;

        /// <summary>提供录制状态和 session id 的 session 控制器。</summary>
        [Tooltip("评估 session 控制器。")]
        [SerializeField] private EvalSession session;

        /// <summary>显示实时状态的 TextMesh Pro 文本。</summary>
        [Tooltip("用于显示实验场景、trial 和事件状态的 TMP 文本。")]
        [SerializeField] private TextMeshProUGUI statusText;

        /// <summary>UI 重绘频率。</summary>
        [Min(1f)]
        [SerializeField] private float updateRate = 10f;

        /// <summary>文本重绘计时器。</summary>
        private float _updateTimer;

        /// <summary>启用时立即显示一次状态，避免等待首个刷新周期。</summary>
        private void Start()
        {
            RefreshNow();
        }

        /// <summary>按频率刷新实时采集状态。</summary>
        private void Update()
        {
            _updateTimer += Time.unscaledDeltaTime;
            if (_updateTimer < 1f / Mathf.Max(1f, updateRate)) return;
            _updateTimer = 0f;
            RenderText();
        }

        /// <summary>公开刷新入口，供测试和场景初始化调用。</summary>
        public void RefreshNow()
        {
            RenderText();
        }

        /// <summary>构建当前状态文本，供 EditMode 测试验证无旧 RQ 文案。</summary>
        public string BuildStatusText()
        {
            var sb = new StringBuilder(512);
            bool recording = session != null && session.IsRecording;
            sb.AppendLine(EvalStatusText.Recording(recording));
            sb.AppendLine(EvalStatusText.Session(session != null ? session.SessionId : string.Empty));

            if (selector == null)
            {
                sb.AppendLine("Experiment: NOT CONFIGURED");
                return sb.ToString();
            }

            sb.AppendLine($"Experiment: {selector.CurrentExperimentDisplayName}");
            sb.AppendLine($"Scenario: {selector.CurrentScenarioDisplayName}");
            sb.AppendLine($"Trial: {(selector.HasActiveTrial ? selector.CurrentTrialId : "Idle")}");
            sb.AppendLine($"Event: {(string.IsNullOrEmpty(selector.CurrentEventId) ? "None" : selector.CurrentEventId)}");
            sb.AppendLine($"Role: {(string.IsNullOrEmpty(selector.CurrentEventRole) ? "None" : selector.CurrentEventRole)}");
            if (selector.HasOpenOcclusion)
                sb.AppendLine("Occlusion: Waiting for target visible");
            sb.AppendLine();
            AppendScenarioRows(sb, selector.CurrentExperimentId == ExperimentId.DesignAttribution);
            return sb.ToString();
        }

        /// <summary>将文本写入 TMP 组件。</summary>
        private void RenderText()
        {
            if (statusText != null)
                statusText.text = BuildStatusText();
        }

        /// <summary>显示当前实验对应的数字键场景列表。</summary>
        private void AppendScenarioRows(StringBuilder builder, bool attribution)
        {
            string[] scenarios = attribution
                ? ExperimentScenario.AttributionScenarios
                : ExperimentScenario.SystemScenarios;
            for (int i = 0; i < scenarios.Length; i++)
            {
                string row = $"[{i + 1}]  {ExperimentScenario.ToDisplayName(scenarios[i])}";
                EvalStatusText.AppendSelectionRow(builder, row, scenarios[i] == selector.CurrentScenarioId);
            }
        }
    }
}
