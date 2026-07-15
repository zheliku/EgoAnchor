using System;
using EgoAnchor.Eval;
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

    /// <summary>维护实验选择、trial 生命周期和人工事件标记，不直接写文件。</summary>
    public sealed class ExperimentTrialSelector : MonoBehaviour
    {
        /// <summary>绑定 session 生命周期；未录制时所有操作均被忽略。</summary>
        [Header("Session")]
        [Tooltip("绑定 EvalSession；只有录制期间才允许创建 trial 和 event。")]
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

        /// <summary>当前条件标识。</summary>
        public string CurrentConditionId => string.IsNullOrEmpty(_experimentId) || string.IsNullOrEmpty(_scenarioId)
            ? string.Empty
            : $"{_experimentId}/{_scenarioId}";

        /// <summary>当前是否处于活动 trial。</summary>
        public bool HasActiveTrial => !string.IsNullOrEmpty(_trialId);

        /// <summary>当前是否允许修改采集上下文。</summary>
        public bool IsRecording => session != null && session.IsRecording;

        /// <summary>当前上下文快照。</summary>
        public ExperimentContext CurrentContext => new ExperimentContext(
            _experimentId, _scenarioId, _trialId, _eventId, CurrentConditionId, _eventRole);

        /// <summary>上下文变化事件，供可视化面板刷新。</summary>
        public event Action<ExperimentContext, string> ContextEvent;

        /// <summary>绑定或替换 session，并同步监听开始/停止事件。</summary>
        public void BindSession(EvalSession target)
        {
            UnbindSession();
            session = target;
            if (session == null) return;
            session.SessionStarted.AddListener(ResetForSession);
            session.SessionStopped.AddListener(ResetForSession);
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

        /// <summary>选择实验一场景；活动 trial 中不允许切换。</summary>
        public bool SelectSystemScenario(int key)
        {
            return SelectScenario(ExperimentId.SystemCharacterization, ExperimentScenario.GetSystemScenario(key));
        }

        /// <summary>选择实验二归因场景；活动 trial 中不允许切换。</summary>
        public bool SelectAttributionScenario(int key)
        {
            return SelectScenario(ExperimentId.DesignAttribution, ExperimentScenario.GetAttributionScenario(key));
        }

        /// <summary>开始当前场景的一个 trial。</summary>
        public bool BeginTrial()
        {
            if (!IsRecording || string.IsNullOrEmpty(_scenarioId) || HasActiveTrial) return false;
            _trialId = $"trial_{++_trialSequence:000}";
            _eventId = string.Empty;
            _eventRole = ExperimentEventRole.None;
            _hasOpenOcclusion = false;
            Emit("trial_started");
            return true;
        }

        /// <summary>结束当前 trial，并保留实验和场景选择。</summary>
        public bool EndTrial()
        {
            if (!IsRecording || !HasActiveTrial || _hasOpenOcclusion) return false;
            Emit("trial_ended");
            _trialId = string.Empty;
            _eventId = string.Empty;
            _eventRole = ExperimentEventRole.None;
            return true;
        }

        /// <summary>按当前场景协议标记主事件；遮挡未闭合时拒绝重复开始。</summary>
        public bool MarkPrimaryEvent()
        {
            if (!IsRecording || !HasActiveTrial) return false;
            string role = ExperimentEventRole.ResolvePrimary(_scenarioId);
            if (role == ExperimentEventRole.OcclusionStarted && _hasOpenOcclusion) return false;

            _eventId = $"event_{++_eventSequence:000}";
            _eventRole = role;
            _hasOpenOcclusion = role == ExperimentEventRole.OcclusionStarted;
            Emit("event_marker");
            return true;
        }

        /// <summary>标记遮挡目标重新可见；没有开放遮挡或场景不支持时拒绝。</summary>
        public bool MarkTargetVisible()
        {
            if (!IsRecording || !HasActiveTrial || !_hasOpenOcclusion) return false;
            if (!ExperimentEventRole.SupportsTargetVisible(_scenarioId)) return false;

            _eventId = $"event_{++_eventSequence:000}";
            _eventRole = ExperimentEventRole.TargetVisible;
            _hasOpenOcclusion = false;
            Emit("event_marker");
            return true;
        }

        /// <summary>清空 session 内的实验、trial 和事件上下文。</summary>
        public void ResetForSession()
        {
            _experimentId = ExperimentId.None;
            _scenarioId = string.Empty;
            _trialId = string.Empty;
            _eventId = string.Empty;
            _eventRole = ExperimentEventRole.None;
            _hasOpenOcclusion = false;
            _trialSequence = 0;
            _eventSequence = 0;
        }

        /// <summary>返回当前场景显示名称。</summary>
        public string CurrentScenarioDisplayName => ExperimentScenario.ToDisplayName(_scenarioId);

        /// <summary>返回当前实验显示名称。</summary>
        public string CurrentExperimentDisplayName => ExperimentId.ToDisplayName(_experimentId);

        /// <summary>执行场景切换并通知订阅者。</summary>
        private bool SelectScenario(string experimentId, string scenarioId)
        {
            if (!IsRecording || HasActiveTrial || string.IsNullOrEmpty(scenarioId)) return false;
            _experimentId = experimentId;
            _scenarioId = scenarioId;
            _eventId = string.Empty;
            _eventRole = ExperimentEventRole.None;
            _hasOpenOcclusion = false;
            Emit("scenario_selected");
            return true;
        }

        /// <summary>发送当前上下文事件；订阅者异常不得阻断输入状态机。</summary>
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

        /// <summary>解除 session 开始/停止监听。</summary>
        private void UnbindSession()
        {
            if (session == null) return;
            session.SessionStarted.RemoveListener(ResetForSession);
            session.SessionStopped.RemoveListener(ResetForSession);
        }
    }
}
