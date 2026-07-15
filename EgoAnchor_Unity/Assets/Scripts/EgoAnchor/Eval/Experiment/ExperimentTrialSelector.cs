using System;
using UnityEngine;

namespace EgoAnchor.Eval.Experiment
{
    /// <summary>实验采集上下文的不可变快照，供 UI、日志和离线配对共享。</summary>
    public readonly struct ExperimentContext
    {
        /// <summary>实验稳定标识。</summary>
        public readonly string ExperimentId;

        /// <summary>场景稳定标识。</summary>
        public readonly string ScenarioId;

        /// <summary>当前 trial 稳定标识。</summary>
        public readonly string TrialId;

        /// <summary>当前人工事件稳定标识。</summary>
        public readonly string EventId;

        /// <summary>当前条件稳定标识。</summary>
        public readonly string ConditionId;

        /// <summary>当前人工事件的协议角色。</summary>
        public readonly string EventRole;

        /// <summary>构造实验上下文快照。</summary>
        public ExperimentContext(
            string experimentId,
            string scenarioId,
            string trialId,
            string eventId,
            string conditionId,
            string eventRole)
        {
            ExperimentId = experimentId ?? string.Empty;
            ScenarioId = scenarioId ?? string.Empty;
            TrialId = trialId ?? string.Empty;
            EventId = eventId ?? string.Empty;
            ConditionId = conditionId ?? string.Empty;
            EventRole = eventRole ?? ExperimentEventRole.None;
        }

        /// <summary>当前是否已选择实验和场景。</summary>
        public bool IsSelected => !string.IsNullOrEmpty(ExperimentId) && !string.IsNullOrEmpty(ScenarioId);
    }

    /// <summary>按固定九场景计划维护 trial 和人工事件；操作者只需执行单一推进动作。</summary>
    public sealed class ExperimentTrialSelector : MonoBehaviour
    {
        /// <summary>绑定 session 生命周期；未录制时推进动作被忽略。</summary>
        [Tooltip("绑定 EvalSession；录制开始时自动选择固定计划的第一个场景。")]
        [SerializeField] private EvalSession session;

        /// <summary>当前实验标识。</summary>
        private string _experimentId = ExperimentId.None;

        /// <summary>当前场景标识。</summary>
        private string _scenarioId = string.Empty;

        /// <summary>当前 trial 标识。</summary>
        private string _trialId = string.Empty;

        /// <summary>当前事件标识。</summary>
        private string _eventId = string.Empty;

        /// <summary>当前事件的实验协议角色。</summary>
        private string _eventRole = ExperimentEventRole.None;

        /// <summary>当前是否已有尚未写入 target_visible 的遮挡事件。</summary>
        private bool _hasOpenOcclusion;

        /// <summary>固定采集计划的零基索引。</summary>
        private int _planIndex = -1;

        /// <summary>九个场景是否已经全部完成。</summary>
        private bool _planComplete;

        /// <summary>当前 trial 序号。</summary>
        private int _trialSequence;

        /// <summary>当前事件序号。</summary>
        private int _eventSequence;

        /// <summary>当前实验标识。</summary>
        public string CurrentExperimentId => _experimentId;

        /// <summary>当前场景标识。</summary>
        public string CurrentScenarioId => _scenarioId;

        /// <summary>当前 trial 标识；空值表示尚未开始 trial。</summary>
        public string CurrentTrialId => _trialId;

        /// <summary>当前事件标识；空值表示当前 trial 尚无事件标记。</summary>
        public string CurrentEventId => _eventId;

        /// <summary>当前人工事件角色；空值表示当前 trial 尚无事件标记。</summary>
        public string CurrentEventRole => _eventRole;

        /// <summary>当前是否正在等待遮挡目标重新可见标记。</summary>
        public bool HasOpenOcclusion => _hasOpenOcclusion;

        /// <summary>当前是否处于活动 trial。</summary>
        public bool HasActiveTrial => !string.IsNullOrEmpty(_trialId);

        /// <summary>当前是否允许推进采集。</summary>
        public bool IsRecording => session != null && session.IsRecording;

        /// <summary>当前是否已完成固定采集计划。</summary>
        public bool IsPlanComplete => _planComplete;

        /// <summary>当前场景在九场景计划中的一基序号。</summary>
        public int CurrentPlanStep => _planIndex >= 0 ? _planIndex + 1 : 0;

        /// <summary>固定采集计划的场景总数。</summary>
        public int PlanStepCount => ExperimentScenario.PlanCount;

        /// <summary>当前条件标识。</summary>
        public string CurrentConditionId => string.IsNullOrEmpty(_experimentId) || string.IsNullOrEmpty(_scenarioId)
            ? string.Empty
            : $"{_experimentId}/{_scenarioId}";

        /// <summary>当前上下文快照。</summary>
        public ExperimentContext CurrentContext => new ExperimentContext(
            _experimentId, _scenarioId, _trialId, _eventId, CurrentConditionId, _eventRole);

        /// <summary>返回头显面板应显示的下一步动作。</summary>
        public string NextActionText
        {
            get
            {
                if (_planComplete) return "COLLECTION COMPLETE";
                if (!IsRecording) return "WAITING FOR PYTHON";
                if (!CurrentContext.IsSelected) return "PREPARING COLLECTION";
                if (!HasActiveTrial) return "PRESS RIGHT A TO START TRIAL";
                if (_hasOpenOcclusion) return "PRESS RIGHT A WHEN TARGET IS VISIBLE";
                if (!string.IsNullOrEmpty(_eventId)) return "PRESS RIGHT A TO FINISH TRIAL";

                string role = ExperimentEventRole.ResolvePrimary(_scenarioId);
                if (role == ExperimentEventRole.OcclusionStarted)
                    return "PRESS RIGHT A WHEN OCCLUSION STARTS";
                if (role == ExperimentEventRole.TransitionStarted)
                    return "PRESS RIGHT A WHEN MOTION STARTS";
                return "PRESS RIGHT A BEFORE THE ACTION";
            }
        }

        /// <summary>上下文变化事件，供录制器和可视化面板共享。</summary>
        public event Action<ExperimentContext, string> ContextEvent;

        /// <summary>绑定或替换 session，并监听录制开始事件。</summary>
        public void BindSession(EvalSession target)
        {
            UnbindSession();
            session = target;
            if (session == null) return;
            session.SessionStarted.AddListener(PreparePlan);
            if (session.IsRecording) PreparePlan();
        }

        /// <summary>Unity 启用时绑定 Inspector 中配置的 session。</summary>
        private void OnEnable()
        {
            if (session != null) BindSession(session);
        }

        /// <summary>Unity 禁用时解除 session 事件监听。</summary>
        private void OnDisable()
        {
            UnbindSession();
        }

        /// <summary>
        /// 执行唯一的采集推进动作：开始 trial、标记主事件、标记目标可见或结束并切换场景。
        /// </summary>
        public bool Advance()
        {
            if (!IsRecording || _planComplete || !CurrentContext.IsSelected) return false;
            if (!HasActiveTrial) return BeginTrial();
            if (string.IsNullOrEmpty(_eventId)) return MarkPrimaryEvent();
            if (_hasOpenOcclusion) return MarkTargetVisible();
            return FinishTrialAndAdvance();
        }

        /// <summary>录制开始时重置计数并自动选择固定计划的第一个场景。</summary>
        public void PreparePlan()
        {
            ResetState();
            if (IsRecording) SelectPlanItem(0);
        }

        /// <summary>返回当前场景显示名称。</summary>
        public string CurrentScenarioDisplayName => ExperimentScenario.ToDisplayName(_scenarioId);

        /// <summary>返回当前实验显示名称。</summary>
        public string CurrentExperimentDisplayName => ExperimentId.ToDisplayName(_experimentId);

        /// <summary>开始当前场景的 trial。</summary>
        private bool BeginTrial()
        {
            if (!IsRecording || string.IsNullOrEmpty(_scenarioId) || HasActiveTrial) return false;
            _trialId = $"trial_{++_trialSequence:000}";
            _eventId = string.Empty;
            _eventRole = ExperimentEventRole.None;
            _hasOpenOcclusion = false;
            Emit("trial_started");
            return true;
        }

        /// <summary>按当前场景协议标记主事件。</summary>
        private bool MarkPrimaryEvent()
        {
            if (!IsRecording || !HasActiveTrial || !string.IsNullOrEmpty(_eventId)) return false;
            _eventId = $"event_{++_eventSequence:000}";
            _eventRole = ExperimentEventRole.ResolvePrimary(_scenarioId);
            _hasOpenOcclusion = _eventRole == ExperimentEventRole.OcclusionStarted;
            Emit("event_marker");
            return true;
        }

        /// <summary>在遮挡场景中标记目标重新可见。</summary>
        private bool MarkTargetVisible()
        {
            if (!IsRecording || !HasActiveTrial || !_hasOpenOcclusion) return false;
            if (!ExperimentEventRole.SupportsTargetVisible(_scenarioId)) return false;
            _eventId = $"event_{++_eventSequence:000}";
            _eventRole = ExperimentEventRole.TargetVisible;
            _hasOpenOcclusion = false;
            Emit("event_marker");
            return true;
        }

        /// <summary>结束当前 trial；最后一个场景完成后自动停止 session。</summary>
        private bool FinishTrialAndAdvance()
        {
            if (!EndTrial()) return false;
            if (SelectPlanItem(_planIndex + 1)) return true;

            _planComplete = true;
            Emit("collection_completed");
            session.StopSession();
            return true;
        }

        /// <summary>结束当前 trial，并在事件发出后清空 trial 上下文。</summary>
        private bool EndTrial()
        {
            if (!IsRecording || !HasActiveTrial || _hasOpenOcclusion || string.IsNullOrEmpty(_eventId)) return false;
            Emit("trial_ended");
            _trialId = string.Empty;
            _eventId = string.Empty;
            _eventRole = ExperimentEventRole.None;
            return true;
        }

        /// <summary>选择固定计划中的一项；越过末尾时返回 false。</summary>
        private bool SelectPlanItem(int index)
        {
            if (!ExperimentScenario.TryGetPlanItem(index, out string experimentId, out string scenarioId))
                return false;
            _planIndex = index;
            _experimentId = experimentId;
            _scenarioId = scenarioId;
            _trialId = string.Empty;
            _eventId = string.Empty;
            _eventRole = ExperimentEventRole.None;
            _hasOpenOcclusion = false;
            Emit("scenario_selected");
            return true;
        }

        /// <summary>清空上一 session 的计划、trial 和事件状态。</summary>
        private void ResetState()
        {
            _experimentId = ExperimentId.None;
            _scenarioId = string.Empty;
            _trialId = string.Empty;
            _eventId = string.Empty;
            _eventRole = ExperimentEventRole.None;
            _hasOpenOcclusion = false;
            _planIndex = -1;
            _planComplete = false;
            _trialSequence = 0;
            _eventSequence = 0;
        }

        /// <summary>发送当前上下文事件；订阅者异常不得阻断采集状态机。</summary>
        private void Emit(string eventType)
        {
            try
            {
                ContextEvent?.Invoke(CurrentContext, eventType);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"实验上下文事件回调失败：{ex.Message}", this);
            }
        }

        /// <summary>解除 session 开始监听。</summary>
        private void UnbindSession()
        {
            if (session == null) return;
            session.SessionStarted.RemoveListener(PreparePlan);
        }
    }
}
