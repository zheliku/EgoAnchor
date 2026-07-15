using System.Text;
using TMPro;
using UnityEngine;

namespace EgoAnchor.Eval.Experiment
{
    /// <summary>头显内实验状态面板，只显示当前进度和下一次单键动作。</summary>
    public sealed class ExperimentStatusUI : MonoBehaviour
    {
        /// <summary>提供固定计划与 trial 状态的 selector。</summary>
        [Tooltip("固定采集计划选择器。")]
        [SerializeField] private ExperimentTrialSelector selector;

        /// <summary>提供录制状态和 session id 的 session 控制器。</summary>
        [Tooltip("评估 session 控制器。")]
        [SerializeField] private EvalSession session;

        /// <summary>显示实时状态的 TextMesh Pro 文本。</summary>
        [Tooltip("显示下一步、计划进度、场景和事件状态的 TMP 文本。")]
        [SerializeField] private TextMeshProUGUI statusText;

        /// <summary>UI 重绘频率。</summary>
        [Min(1f)]
        [SerializeField] private float updateRate = 10f;

        /// <summary>文本重绘计时器。</summary>
        private float _updateTimer;

        /// <summary>启用时立即显示一次状态。</summary>
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

        /// <summary>构建当前状态文本。</summary>
        public string BuildStatusText()
        {
            var builder = new StringBuilder(320);
            bool recording = session != null && session.IsRecording;
            if (selector == null)
            {
                builder.AppendLine("NEXT: NOT CONFIGURED");
                builder.AppendLine(EvalStatusText.Recording(recording));
                return builder.ToString();
            }

            builder.AppendLine($"NEXT: {selector.NextActionText}");
            builder.AppendLine($"Progress: {selector.CurrentPlanStep} / {selector.PlanStepCount}");
            builder.AppendLine(EvalStatusText.Recording(recording));
            builder.AppendLine(EvalStatusText.Session(session != null ? session.SessionId : string.Empty));
            builder.AppendLine($"Experiment: {selector.CurrentExperimentDisplayName}");
            builder.AppendLine($"Scenario: {selector.CurrentScenarioDisplayName}");
            builder.AppendLine($"Trial: {(selector.HasActiveTrial ? selector.CurrentTrialId : "Idle")}");
            builder.AppendLine($"Role: {(string.IsNullOrEmpty(selector.CurrentEventRole) ? "None" : selector.CurrentEventRole)}");
            return builder.ToString();
        }

        /// <summary>将文本写入 TMP 组件。</summary>
        private void RenderText()
        {
            if (statusText != null)
                statusText.text = BuildStatusText();
        }
    }
}
