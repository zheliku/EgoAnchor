using System;
using System.Collections.Generic;
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

    /// <summary>维护可任意选择、可作废重做的九项实验采集任务。</summary>
    public sealed class ExperimentTrialSelector : MonoBehaviour
    {
        /// <summary>绑定 session 生命周期；未录制时所有采集动作都被拒绝。</summary>
        [Tooltip("绑定 EvalSession；录制开始时重置九项任务状态并选中任务 1。")]
        [SerializeField] private EvalSession session;

        /// <summary>九宫格当前选中的任务索引。</summary>
        private int _selectedTaskIndex = -1;

        /// <summary>正在录制的任务索引；空闲时为 -1。</summary>
        private int _activeTaskIndex = -1;

        /// <summary>九项任务各自是否已有一个未作废的完成 trial。</summary>
        private readonly bool[] _completed = new bool[ExperimentScenario.PlanCount];

        /// <summary>每项任务最后一次完成 trial 的完整上下文，供事后作废。</summary>
        private readonly ExperimentContext[] _completedContexts =
            new ExperimentContext[ExperimentScenario.PlanCount];

        /// <summary>当前 trial 标识。</summary>
        private string _trialId = string.Empty;

        /// <summary>当前事件标识。</summary>
        private string _eventId = string.Empty;

        /// <summary>当前事件协议角色。</summary>
        private string _eventRole = ExperimentEventRole.None;

        /// <summary>当前遮挡是否尚未写入 target_visible。</summary>
        private bool _hasOpenOcclusion;

        /// <summary>当前 trial 已记录的 marker 数量。</summary>
        private int _trialEventCount;

        /// <summary>最近一次 marker 操作的头显反馈文本。</summary>
        private string _markerFeedbackText = string.Empty;

        /// <summary>最近一次 marker 操作是否成功。</summary>
        private bool _markerFeedbackSucceeded;

        /// <summary>最近一次 marker 反馈停止显示的 Unity 非缩放时刻。</summary>
        private double _markerFeedbackUntil;

        /// <summary>marker 操作反馈在头显状态板中的显示时长。</summary>
        [Min(0.5f)]
        [Tooltip("marker 成功或被拒绝后，确认信息在头显状态板中保留的秒数。")]
        [SerializeField] private float markerFeedbackSeconds = 2.0f;

        /// <summary>当前 trial 开始的 Unity 单调时刻。</summary>
        private double _trialStartedAt;

        /// <summary>session 内 trial 序号。</summary>
        private int _trialSequence;

        /// <summary>session 内事件序号。</summary>
        private int _eventSequence;

        /// <summary>当前选中的任务索引。</summary>
        public int SelectedTaskIndex => _selectedTaskIndex;

        /// <summary>当前正在录制的任务索引。</summary>
        public int ActiveTaskIndex => _activeTaskIndex;

        /// <summary>当前实验标识。</summary>
        public string CurrentExperimentId => CurrentTask.ExperimentId ?? ExperimentId.None;

        /// <summary>当前场景标识。</summary>
        public string CurrentScenarioId => CurrentTask.ScenarioId ?? string.Empty;

        /// <summary>当前 trial 标识；空值表示尚未开始。</summary>
        public string CurrentTrialId => _trialId;

        /// <summary>当前事件标识；空值表示当前 trial 尚无 marker。</summary>
        public string CurrentEventId => _eventId;

        /// <summary>当前人工事件角色。</summary>
        public string CurrentEventRole => _eventRole;

        /// <summary>最近一次 marker 操作仍在显示期内时返回确认文本。</summary>
        public string MarkerFeedbackText => HasMarkerFeedback ? _markerFeedbackText : string.Empty;

        /// <summary>最近一次 marker 操作是否成功；只在 <see cref="HasMarkerFeedback"/> 为真时使用。</summary>
        public bool MarkerFeedbackSucceeded => _markerFeedbackSucceeded;

        /// <summary>最近一次 marker 操作是否仍应显示即时反馈。</summary>
        public bool HasMarkerFeedback => !string.IsNullOrEmpty(_markerFeedbackText)
            && Time.unscaledTimeAsDouble <= _markerFeedbackUntil;

        /// <summary>当前是否正在等待目标重新可见 marker。</summary>
        public bool HasOpenOcclusion => _hasOpenOcclusion;

        /// <summary>当前是否有活动 trial。</summary>
        public bool HasActiveTrial => _activeTaskIndex >= 0;

        /// <summary>当前是否处于 session 录制状态。</summary>
        public bool IsRecording => session != null && session.IsRecording;

        /// <summary>只要正在录制就可以显式结束 session，活动 trial 会先作废。</summary>
        public bool CanFinishSession => IsRecording;

        /// <summary>已经完成的任务数量。</summary>
        public int CompletedTaskCount
        {
            get
            {
                int count = 0;
                for (int index = 0; index < _completed.Length; index++)
                {
                    if (_completed[index]) count++;
                }

                return count;
            }
        }

        /// <summary>固定任务总数。</summary>
        public int PlanStepCount => ExperimentScenario.PlanCount;

        /// <summary>当前选中任务定义。</summary>
        public ExperimentTask CurrentTask
        {
            get
            {
                ExperimentScenario.TryGetTask(_selectedTaskIndex, out ExperimentTask task);
                return task;
            }
        }

        /// <summary>当前条件标识。</summary>
        public string CurrentConditionId => string.IsNullOrEmpty(CurrentExperimentId) || string.IsNullOrEmpty(CurrentScenarioId)
            ? string.Empty
            : $"{CurrentExperimentId}/{CurrentScenarioId}";

        /// <summary>当前上下文快照。</summary>
        public ExperimentContext CurrentContext => new ExperimentContext(
            CurrentExperimentId,
            CurrentScenarioId,
            _trialId,
            _eventId,
            CurrentConditionId,
            _eventRole);

        /// <summary>当前 trial 已经过的秒数。</summary>
        public double TrialElapsedSeconds => HasActiveTrial
            ? Math.Max(0.0, Time.realtimeSinceStartupAsDouble - _trialStartedAt)
            : 0.0;

        /// <summary>当前头显 UI 使用的直白采集状态；不暴露分析术语。</summary>
        public string CurrentPhaseText
        {
            get
            {
                if (!IsRecording) return "WAITING FOR SESSION";
                if (!HasActiveTrial) return "TASK SELECTED - NOT RUNNING";
                if (_trialEventCount == 0) return "RECORDING BASELINE";
                if (_hasOpenOcclusion) return "TARGET OCCLUDED";
                if (ExperimentEventRole.SupportsTargetVisible(CurrentScenarioId)) return "TARGET VISIBLE";
                if (_eventRole == ExperimentEventRole.TransitionStarted) return "MOTION IN PROGRESS";
                return "ACTION IN PROGRESS";
            }
        }

        /// <summary>返回当前状态下下一项合法操作。</summary>
        public string NextActionText
        {
            get
            {
                if (!IsRecording)
                {
                    return session != null && !string.IsNullOrWhiteSpace(session.SessionStatusMessage)
                        ? session.SessionStatusMessage
                        : "WAIT FOR PYTHON SESSION";
                }
                if (!CurrentContext.IsSelected) return "SELECT A TASK";
                if (!HasActiveTrial && IsTaskCompleted(_selectedTaskIndex))
                    return "RERECORD: NUMPAD ENTER | REJECT: SPACE";
                if (!HasActiveTrial) return "START: NUMPAD ENTER | STOP SESSION: F";
                if (_trialEventCount == 0)
                    return "MARK NOW: NUMPAD +";
                if (_hasOpenOcclusion)
                    return "TARGET VISIBLE: NUMPAD +";
                return "END: NUMPAD 0 | NEXT MARKER: NUMPAD +";
            }
        }

        /// <summary>把当前 marker 的协议角色翻译为头显操作者可直接执行的提示。</summary>
        public string MarkerInstructionText
        {
            get
            {
                if (!HasActiveTrial)
                    return "Marker is available only while a task is recording.";
                if (_trialEventCount == 0)
                    return "Numpad + / M / Trigger at action or occlusion start.";
                if (_hasOpenOcclusion)
                    return "Numpad + / M / Trigger when the target becomes visible.";
                if (_eventRole == ExperimentEventRole.TargetVisible)
                    return "Pair saved. Mark again at the next occlusion.";
                if (_eventRole == ExperimentEventRole.TransitionStarted)
                    return "Motion saved. Mark again at the next motion.";
                return "Event saved. Mark again at the next event.";
            }
        }

        /// <summary>当前场景显示名称。</summary>
        public string CurrentScenarioDisplayName => CurrentTask.DisplayName ?? "NO SCENARIO";

        /// <summary>上下文变化事件，供录制器和状态 UI 共享。</summary>
        public event Action<ExperimentContext, string> ContextEvent;

        /// <summary>绑定或替换 session，并监听录制开始事件。</summary>
        public void BindSession(EvalSession target)
        {
            UnbindSession();
            session = target;
            if (session == null) return;
            session.SessionStarted.AddListener(PrepareCollection);
            if (session.IsRecording) PrepareCollection();
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

        /// <summary>录制开始时清空上一 session 状态并选中任务 1。</summary>
        public void PrepareCollection()
        {
            ResetState();
            if (IsRecording) SelectTask(0);
        }

        /// <summary>选择一项任务；活动 trial 期间禁止切换。</summary>
        public bool SelectTask(int index)
        {
            if (!IsRecording || HasActiveTrial || !ExperimentScenario.TryGetTask(index, out _))
                return false;
            if (_selectedTaskIndex == index) return true;

            _selectedTaskIndex = index;
            Emit(CurrentContext, "task_selected");
            return true;
        }

        /// <summary>按三乘三九宫格移动选择，斜向输入只取绝对值更大的轴。</summary>
        public bool MoveSelection(Vector2 direction)
        {
            if (!IsRecording || HasActiveTrial || _selectedTaskIndex < 0) return false;
            int column = _selectedTaskIndex % 3;
            int row = _selectedTaskIndex / 3;
            if (Mathf.Abs(direction.x) >= Mathf.Abs(direction.y))
            {
                if (direction.x > 0.0f) column++;
                else if (direction.x < 0.0f) column--;
                else return false;
            }
            else
            {
                if (direction.y > 0.0f) row--;
                else if (direction.y < 0.0f) row++;
                else return false;
            }

            if (column < 0 || column >= 3 || row < 0 || row >= 3) return false;
            return SelectTask(row * 3 + column);
        }

        /// <summary>开始当前选中任务；已完成任务会先自动写入 trial_rejected，再开始新 trial。</summary>
        public bool StartTrial()
        {
            if (!IsRecording || HasActiveTrial || _selectedTaskIndex < 0) return false;
            if (IsTaskCompleted(_selectedTaskIndex))
            {
                Emit(_completedContexts[_selectedTaskIndex], "trial_rejected");
                _completed[_selectedTaskIndex] = false;
                _completedContexts[_selectedTaskIndex] = default;
            }

            _activeTaskIndex = _selectedTaskIndex;
            _trialId = $"trial_{++_trialSequence:000}";
            _eventId = string.Empty;
            _eventRole = ExperimentEventRole.None;
            _trialEventCount = 0;
            _hasOpenOcclusion = false;
            _trialStartedAt = Time.realtimeSinceStartupAsDouble;
            Emit(CurrentContext, "trial_started");
            return true;
        }

        /// <summary>写入主事件；遮挡任务在遮挡开始与目标可见之间交替。</summary>
        public bool MarkEvent()
        {
            if (!IsRecording || !HasActiveTrial)
            {
                SetMarkerFeedback("MARKER IGNORED: START A TASK FIRST", false);
                return false;
            }

            string role;
            if (ExperimentEventRole.SupportsTargetVisible(CurrentScenarioId))
            {
                role = _hasOpenOcclusion
                    ? ExperimentEventRole.TargetVisible
                    : ExperimentEventRole.OcclusionStarted;
                _hasOpenOcclusion = role == ExperimentEventRole.OcclusionStarted;
            }
            else
            {
                role = ExperimentEventRole.ResolvePrimary(CurrentScenarioId);
            }

            _eventId = $"event_{++_eventSequence:000}";
            _eventRole = role;
            _trialEventCount++;
            SetMarkerFeedback($"MARKER SAVED #{_trialEventCount}: {MarkerRoleText(role)}", true);
            Emit(CurrentContext, "event_marker");
            return true;
        }

        /// <summary>结束当前活动任务；事件不完整时拒绝结束。</summary>
        public bool EndTrial()
        {
            return IsRecording && HasActiveTrial && FinishTrial();
        }

        /// <summary>立即停止 session；活动 trial 先标记 rejected，已完成任务保持不变。</summary>
        public bool FinishSessionNow()
        {
            if (!IsRecording) return false;
            if (HasActiveTrial)
            {
                Emit(CurrentContext, "trial_rejected");
                ClearActiveTrial();
            }
            Emit(CurrentContext, "collection_finalized");
            session.StopSession();
            return true;
        }

        /// <summary>按任务编号升序复制当前 session 最终保留的完成任务。</summary>
        public void CollectCompletedTasks(List<CompletedExperimentTask> output)
        {
            if (output == null) throw new ArgumentNullException(nameof(output));
            output.Clear();
            for (int index = 0; index < _completed.Length; index++)
            {
                if (!_completed[index]) continue;
                ExperimentContext context = _completedContexts[index];
                output.Add(new CompletedExperimentTask(
                    index + 1,
                    context.ExperimentId,
                    context.ScenarioId,
                    context.TrialId));
            }
        }

        /// <summary>作废活动 trial，或作废选中任务最后一次完成 trial 以便单项重做。</summary>
        public bool RejectCurrentOrSelected()
        {
            if (!IsRecording || _selectedTaskIndex < 0) return false;
            if (HasActiveTrial)
            {
                Emit(CurrentContext, "trial_rejected");
                ClearActiveTrial();
                return true;
            }

            if (!IsTaskCompleted(_selectedTaskIndex)) return false;
            Emit(_completedContexts[_selectedTaskIndex], "trial_rejected");
            _completed[_selectedTaskIndex] = false;
            _completedContexts[_selectedTaskIndex] = default;
            return true;
        }

        /// <summary>返回指定任务是否已有未作废的完成 trial。</summary>
        public bool IsTaskCompleted(int index)
        {
            return index >= 0 && index < _completed.Length && _completed[index];
        }

        /// <summary>结束活动 trial，并保留最后上下文用于事后作废。</summary>
        private bool FinishTrial()
        {
            if (_trialEventCount == 0 || _hasOpenOcclusion) return false;
            ExperimentContext completedContext = CurrentContext;
            Emit(completedContext, "trial_ended");
            _completed[_activeTaskIndex] = true;
            _completedContexts[_activeTaskIndex] = completedContext;
            ClearActiveTrial();
            return true;
        }

        /// <summary>清空当前 trial，不改变任务选择与其他任务完成状态。</summary>
        private void ClearActiveTrial()
        {
            _activeTaskIndex = -1;
            _trialId = string.Empty;
            _eventId = string.Empty;
            _eventRole = ExperimentEventRole.None;
            _trialEventCount = 0;
            _hasOpenOcclusion = false;
            _trialStartedAt = 0.0;
        }

        /// <summary>清空上一 session 的选择、完成表、trial 与事件计数。</summary>
        private void ResetState()
        {
            _selectedTaskIndex = -1;
            ClearActiveTrial();
            Array.Clear(_completed, 0, _completed.Length);
            Array.Clear(_completedContexts, 0, _completedContexts.Length);
            _trialSequence = 0;
            _eventSequence = 0;
            _markerFeedbackText = string.Empty;
            _markerFeedbackSucceeded = false;
            _markerFeedbackUntil = 0.0;
        }

        /// <summary>保存短时 marker 操作反馈；它只影响 UI，不写入实验事件流。</summary>
        private void SetMarkerFeedback(string text, bool succeeded)
        {
            _markerFeedbackText = text ?? string.Empty;
            _markerFeedbackSucceeded = succeeded;
            _markerFeedbackUntil = Time.unscaledTimeAsDouble + Math.Max(0.5f, markerFeedbackSeconds);
        }

        /// <summary>把 marker 协议角色转换为操作者可直接识别的 ASCII 文本。</summary>
        private static string MarkerRoleText(string role)
        {
            if (role == ExperimentEventRole.OcclusionStarted) return "OCCLUSION START";
            if (role == ExperimentEventRole.TargetVisible) return "TARGET VISIBLE";
            if (role == ExperimentEventRole.TransitionStarted) return "MOTION START";
            return "EVENT";
        }

        /// <summary>发送指定上下文事件；订阅者异常不得阻断采集状态机。</summary>
        private void Emit(ExperimentContext context, string eventType)
        {
            try
            {
                ContextEvent?.Invoke(context, eventType);
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
            session.SessionStarted.RemoveListener(PrepareCollection);
        }
    }
}
