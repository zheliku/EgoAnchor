using System.Text;
using TMPro;
using UnityEngine;

namespace EgoAnchor.Eval.Experiment
{
    /// <summary>以固定层级显示九项任务、当前操作、计时和两套输入说明。</summary>
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
        [Tooltip("显示任务九宫格、当前状态、单一计时、下一步操作和固定输入图例的 TMP 文本。")]
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

        /// <summary>构建头显中的紧凑状态板；只显示操作者当前需要的信息。</summary>
        public string BuildStatusText()
        {
            var builder = new StringBuilder(768);
            bool sessionActive = session != null && session.IsRecording;
            if (selector == null)
            {
                builder.AppendLine("<size=34><b>EGOANCHOR COLLECTION</b></size>");
                builder.AppendLine(Colorize("[BLOCKED] NOT CONFIGURED", blockedStatusColor));
                return builder.ToString();
            }

            builder.AppendLine("<size=34><b>EGOANCHOR COLLECTION</b></size>");
            string sessionText = sessionActive ? "[READY] SESSION ACTIVE" : "[WAIT] NO SESSION";
            builder.AppendLine(
                $"{Colorize(sessionText, sessionActive ? runningTaskColor : blockedStatusColor)} | " +
                EvalStatusText.Session(session != null ? session.SessionId : string.Empty));
            if (session != null && !string.IsNullOrWhiteSpace(session.SessionStatusMessage))
            {
                string serverStatus = sessionActive ? "SERVER  CONNECTED" : $"SERVER  {session.SessionStatusMessage}";
                builder.AppendLine(
                    $"<size=22>{(sessionActive ? serverStatus : Colorize(serverStatus, blockedStatusColor))}</size>");
            }

            builder.AppendLine($"NEXT  <size=25><b>{Colorize(selector.NextActionText, nextActionColor)}</b></size>");
            builder.AppendLine($"TASKS  {Colorize($"{selector.CompletedTaskCount}/{selector.PlanStepCount} COMPLETE", completedTaskColor)}");
            AppendTaskGrid(builder);
            if (selector.SelectedTaskIndex >= 0)
            {
                builder.AppendLine($"CURRENT  <b>{selector.SelectedTaskIndex + 1}. {selector.CurrentScenarioDisplayName}</b>");
            }
            else
            {
                builder.AppendLine("CURRENT  WAITING FOR SESSION");
            }
            string timer = selector.HasActiveTrial
                ? EvalStatusText.Duration(selector.TrialElapsedSeconds)
                : "--:--";
            builder.AppendLine(
                $"STATE  {Colorize(selector.CurrentPhaseText, phaseStatusColor)} | " +
                $"TIME  {Colorize(timer, TimerColor())}");
            if (selector.HasMarkerFeedback)
            {
                Color feedbackColor = selector.MarkerFeedbackSucceeded ? runningTaskColor : blockedStatusColor;
                builder.AppendLine(
                    $"MARKER  <size=26><b>{Colorize(selector.MarkerFeedbackText, feedbackColor)}</b></size>");
            }
            else
            {
                builder.AppendLine($"MARKER  <size=24>{Colorize(selector.MarkerInstructionText, markerStatusColor)}</size>");
            }
            builder.AppendLine("<size=22>KEYPAD  1-9 Select | Enter Start | + Marker | 0 End");
            builder.AppendLine("ALT     Arrows Select | Enter Start | M Marker | E End");
            builder.AppendLine("VR      Stick Select | A Start | Trigger Marker | Tap B End");
            builder.AppendLine("OTHER   Space Reject | F Stop Session | Hold B Stop</size>");
            return builder.ToString();
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
                    bool selected = selector.SelectedTaskIndex == index;
                    string coloredCell = Colorize(cell.PadRight(17), TaskColor(index));
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

        /// <summary>活动 trial 使用运行色，空闲时使用待执行色。</summary>
        private Color TimerColor()
        {
            return selector.HasActiveTrial ? runningTaskColor : pendingTaskColor;
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
