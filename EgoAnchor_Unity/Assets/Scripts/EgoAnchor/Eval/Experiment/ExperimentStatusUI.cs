using System.Text;
using TMPro;
using UnityEngine;

namespace EgoAnchor.Eval.Experiment
{
    /// <summary>显示九项任务完成表、当前阶段、计时和实际输入绑定。</summary>
    public sealed class ExperimentStatusUI : MonoBehaviour
    {
        /// <summary>提供任务选择、完成状态和实时阶段。</summary>
        [Header("References")]
        [Tooltip("九任务采集选择器。")]
        [SerializeField] private ExperimentTrialSelector selector;

        /// <summary>提供录制状态和 session id。</summary>
        [Tooltip("评估 session 控制器。")]
        [SerializeField] private EvalSession session;

        /// <summary>显示实时状态的 TextMesh Pro 文本。</summary>
        [Tooltip("显示任务九宫格、当前阶段、时间和下一项操作的 TMP 文本。")]
        [SerializeField] private TextMeshProUGUI statusText;

        /// <summary>计时文本的重绘频率。</summary>
        [Min(1f)]
        [Tooltip("每秒刷新次数；任务状态变化会立即刷新。")]
        [SerializeField] private float updateRate = 10f;

        /// <summary>九宫格当前选中任务的颜色。</summary>
        [Header("Task Colors")]
        [Tooltip("当前选中任务的高亮颜色；状态板使用 TMP 富文本显示。")]
        [SerializeField] private Color selectedTaskColor = new Color32(255, 208, 84, 255);

        /// <summary>正在运行任务的颜色。</summary>
        [Tooltip("正在录制的任务颜色。")]
        [SerializeField] private Color runningTaskColor = new Color32(77, 214, 166, 255);

        /// <summary>已完成任务的颜色。</summary>
        [Tooltip("本 session 已完成任务的颜色。")]
        [SerializeField] private Color completedTaskColor = new Color32(91, 169, 255, 255);

        /// <summary>未完成任务的颜色。</summary>
        [Tooltip("尚未开始任务的颜色。")]
        [SerializeField] private Color pendingTaskColor = new Color32(177, 188, 204, 255);

        /// <summary>session 阻断或等待状态的颜色。</summary>
        [Tooltip("Python session 未配对或启动被阻断时的提示颜色。")]
        [SerializeField] private Color blockedStatusColor = new Color32(255, 125, 106, 255);

        /// <summary>下一步操作提示的颜色。</summary>
        [Header("Live Status Colors")]
        [Tooltip("NEXT 下一步操作提示颜色。")]
        [SerializeField] private Color nextActionColor = new Color32(255, 208, 84, 255);

        /// <summary>当前阶段提示的颜色。</summary>
        [Tooltip("Phase 当前采集阶段提示颜色。")]
        [SerializeField] private Color phaseStatusColor = new Color32(109, 211, 255, 255);

        /// <summary>marker 操作说明的颜色。</summary>
        [Tooltip("Marker 操作说明颜色。")]
        [SerializeField] private Color markerStatusColor = new Color32(255, 169, 92, 255);

        /// <summary>处于建议结束窗口时的计时颜色。</summary>
        [Tooltip("Trial 达到建议 90--120 秒窗口时的计时颜色。")]
        [SerializeField] private Color readyTimerColor = new Color32(77, 214, 166, 255);

        /// <summary>文本重绘计时器。</summary>
        private float _updateTimer;

        /// <summary>启用时订阅任务状态变化。</summary>
        private void OnEnable()
        {
            if (selector != null)
                selector.ContextEvent += OnContextEvent;
        }

        /// <summary>禁用时解除任务状态订阅。</summary>
        private void OnDisable()
        {
            if (selector != null)
                selector.ContextEvent -= OnContextEvent;
        }

        /// <summary>启动时立即显示一次状态。</summary>
        private void Start()
        {
            RefreshNow();
        }

        /// <summary>按频率刷新 trial 和阶段计时。</summary>
        private void Update()
        {
            _updateTimer += Time.unscaledDeltaTime;
            if (_updateTimer < 1f / Mathf.Max(1f, updateRate)) return;
            _updateTimer = 0f;
            RenderText();
        }

        /// <summary>收到任务状态事件后立即刷新。</summary>
        private void OnContextEvent(ExperimentContext context, string eventType)
        {
            RenderText();
        }

        /// <summary>公开刷新入口，供测试和场景初始化调用。</summary>
        public void RefreshNow()
        {
            RenderText();
        }

        /// <summary>构建当前完整状态文本。</summary>
        public string BuildStatusText()
        {
            var builder = new StringBuilder(768);
            bool recording = session != null && session.IsRecording;
            if (selector == null)
            {
                builder.AppendLine("NEXT: NOT CONFIGURED");
                builder.AppendLine(EvalStatusText.Recording(recording));
                return builder.ToString();
            }

            builder.AppendLine($"NEXT: {Colorize(selector.NextActionText, nextActionColor)}");
            builder.AppendLine($"Completed: {Colorize($"{selector.CompletedTaskCount} / {selector.PlanStepCount}", completedTaskColor)}");
            AppendCompletedTaskNumbers(builder);
            builder.AppendLine($"{EvalStatusText.Recording(recording)} | {EvalStatusText.Session(session != null ? session.SessionId : string.Empty)}");
            if (session != null && !string.IsNullOrWhiteSpace(session.SessionStatusMessage))
            {
                string status = $"Session status: {session.SessionStatusMessage}";
                builder.AppendLine(recording ? status : Colorize(status, blockedStatusColor));
            }
            builder.AppendLine("Tasks (3 x 3):");
            AppendTaskGrid(builder);
            if (selector.SelectedTaskIndex >= 0)
            {
                builder.AppendLine($"Selected: {selector.SelectedTaskIndex + 1}. {selector.CurrentScenarioDisplayName}");
                builder.AppendLine($"Experiment: {selector.CurrentExperimentDisplayName}");
            }
            else
            {
                builder.AppendLine("Selected: Waiting for session");
            }
            string trialState = selector.HasActiveTrial ? selector.CurrentTrialId : "Idle";
            builder.AppendLine($"Trial: {Colorize(trialState, selector.HasActiveTrial ? runningTaskColor : pendingTaskColor)}");
            string timer = $"Trial {selector.TrialElapsedSeconds:0.0} s | Phase {selector.PhaseElapsedSeconds:0.0} s";
            builder.AppendLine($"Phase: {Colorize(selector.CurrentPhaseText, phaseStatusColor)} | {Colorize(timer, TimerColor())}");
            builder.AppendLine(selector.SelectedTaskIndex >= 0
                ? $"Recommended: {selector.CurrentTask.MinimumSeconds}-{selector.CurrentTask.MaximumSeconds} s"
                : "Recommended: 90-120 s per task");
            builder.AppendLine($"Marker: {Colorize(selector.MarkerInstructionText, markerStatusColor)}");
            builder.AppendLine($"Role: {(string.IsNullOrEmpty(selector.CurrentEventRole) ? "None" : selector.CurrentEventRole)}");
            return builder.ToString();
        }

        /// <summary>显示当前 session 已完成的任务编号，便于停止前核对模块化采集范围。</summary>
        private void AppendCompletedTaskNumbers(StringBuilder builder)
        {
            builder.Append("This session: ");
            bool hasCompleted = false;
            for (int index = 0; index < selector.PlanStepCount; index++)
            {
                if (!selector.IsTaskCompleted(index)) continue;
                if (hasCompleted) builder.Append(", ");
                builder.Append(index + 1);
                hasCompleted = true;
            }
            builder.AppendLine(hasCompleted ? string.Empty : "None");
        }

        /// <summary>按三乘三布局写入九项任务状态。</summary>
        private void AppendTaskGrid(StringBuilder builder)
        {
            for (int row = 0; row < 3; row++)
            {
                for (int column = 0; column < 3; column++)
                {
                    int index = row * 3 + column;
                    string pointer = selector.SelectedTaskIndex == index ? ">" : " ";
                    string state = TaskState(index);
                    ExperimentScenario.TryGetTask(index, out ExperimentTask task);
                    string cell = $"{pointer}{state}{index + 1} {task.ShortName}";
                    string paddedCell = cell.PadRight(17);
                    bool selected = selector.SelectedTaskIndex == index;
                    string coloredCell = Colorize(paddedCell, TaskColor(index));
                    builder.Append(selected ? $"<b>{coloredCell}</b>" : coloredCell);
                }

                builder.AppendLine();
            }
        }

        /// <summary>返回一个任务在九宫格中的稳定状态标签。</summary>
        private string TaskState(int index)
        {
            if (selector.ActiveTaskIndex == index) return "[RUN]";
            if (selector.IsTaskCompleted(index)) return "[OK]";
            return "[ ]";
        }

        /// <summary>按运行、完成、选中、待执行优先级返回任务颜色；选中通过箭头和粗体提示。</summary>
        private Color TaskColor(int index)
        {
            if (selector.ActiveTaskIndex == index) return runningTaskColor;
            if (selector.IsTaskCompleted(index)) return completedTaskColor;
            if (selector.SelectedTaskIndex == index) return selectedTaskColor;
            return pendingTaskColor;
        }

        /// <summary>按未达最短时长、建议窗口和超时三种状态返回实时计时颜色。</summary>
        private Color TimerColor()
        {
            if (!selector.HasActiveTrial) return pendingTaskColor;
            if (selector.IsOverRecommendedDuration) return blockedStatusColor;
            if (selector.IsWithinRecommendedDuration) return readyTimerColor;
            return selectedTaskColor;
        }

        /// <summary>把一段任务状态文本包装为 TextMesh Pro 富文本颜色标签。</summary>
        private static string Colorize(string text, Color color)
        {
            return $"<color=#{ColorUtility.ToHtmlStringRGB(color)}>{text}</color>";
        }

        /// <summary>将文本写入 TMP 组件。</summary>
        private void RenderText()
        {
            if (statusText != null)
                statusText.text = BuildStatusText();
        }
    }
}
