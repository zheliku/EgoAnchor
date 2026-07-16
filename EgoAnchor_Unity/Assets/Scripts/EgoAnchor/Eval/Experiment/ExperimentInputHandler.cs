using System;
using UnityEngine;
using UnityEngine.InputSystem;

namespace EgoAnchor.Eval.Experiment
{
    /// <summary>把 Inspector 内联 InputAction 路由到九任务采集状态机。</summary>
    public sealed class ExperimentInputHandler : MonoBehaviour
    {
        /// <summary>接收选择、开始、标记、结束和作废动作的任务选择器。</summary>
        [Header("References")]
        [Tooltip("九任务采集选择器；所有 InputAction 最终只调用该状态机。")]
        [SerializeField] private ExperimentTrialSelector selector;

        /// <summary>右手摇杆二维选场动作。</summary>
        [Header("Inline Input Actions")]
        [Tooltip("九宫格选场动作，期望 Vector2；正式场景默认绑定右手摇杆。")]
        [SerializeField] private InputAction navigateAction =
            new InputAction("NavigateTask", InputActionType.Value, expectedControlType: "Vector2");

        /// <summary>开始当前选中任务的动作。</summary>
        [Tooltip("开始任务；正式场景默认绑定右手 A。")]
        [SerializeField] private InputAction startAction =
            new InputAction("StartTask", InputActionType.Button);

        /// <summary>记录主事件或目标重新可见的动作。</summary>
        [Tooltip("写入事件 marker；正式场景默认绑定右手扳机。")]
        [SerializeField] private InputAction markAction =
            new InputAction("MarkEvent", InputActionType.Button);

        /// <summary>结束当前任务或最终结束 session 的动作。</summary>
        [Tooltip("结束任务；空闲且至少完成一项时再次执行会结束本次 session。默认绑定右手 B 和 Enter。")]
        [SerializeField] private InputAction stopAction =
            new InputAction("StopOrFinish", InputActionType.Button);

        /// <summary>作废活动或选中完成 trial 的动作。</summary>
        [Tooltip("作废当前 trial 或选中任务最后一次完成 trial。默认绑定摇杆按下和 Backspace。")]
        [SerializeField] private InputAction rejectAction =
            new InputAction("RejectTrial", InputActionType.Button);

        /// <summary>键盘 1--9 对应的九项任务动作。</summary>
        [Tooltip("九个内联 Button Action，顺序对应任务 1--9；首次按下开始任务，后续按下写事件 marker。")]
        [SerializeField] private InputAction[] taskActions = CreateTaskActions();

        /// <summary>摇杆触发一次选择所需的最小幅度。</summary>
        [Header("Navigation")]
        [Range(0.1f, 1.0f)]
        [Tooltip("摇杆幅度达到该阈值后移动一格；必须回中后才能再次移动。")]
        [SerializeField] private float navigationThreshold = 0.7f;

        /// <summary>摇杆是否已经触发，防止长按连续跨越多格。</summary>
        private bool _navigationLatched;

        /// <summary>键盘任务动作的稳定回调数组。</summary>
        private Action<InputAction.CallbackContext>[] _taskCallbacks;

        /// <summary>当前是否已完成动作订阅。</summary>
        private bool _subscribed;

        /// <summary>启用组件时订阅并启用全部内联动作。</summary>
        private void OnEnable()
        {
            SubscribeActions();
            SetActionsEnabled(true);
        }

        /// <summary>禁用组件时先停用动作再解除订阅；序列化动作不得 Dispose。</summary>
        private void OnDisable()
        {
            SetActionsEnabled(false);
            UnsubscribeActions();
            _navigationLatched = false;
        }

        /// <summary>订阅手柄和九个键盘任务动作。</summary>
        private void SubscribeActions()
        {
            if (_subscribed) return;
            navigateAction.performed += OnNavigatePerformed;
            navigateAction.canceled += OnNavigateCanceled;
            startAction.performed += OnStartPerformed;
            markAction.performed += OnMarkPerformed;
            stopAction.performed += OnStopPerformed;
            rejectAction.performed += OnRejectPerformed;

            int count = taskActions?.Length ?? 0;
            _taskCallbacks = new Action<InputAction.CallbackContext>[count];
            for (int index = 0; index < count; index++)
            {
                int taskIndex = index;
                _taskCallbacks[index] = _ => HandleTask(taskIndex);
                if (taskActions[index] != null)
                    taskActions[index].performed += _taskCallbacks[index];
            }

            _subscribed = true;
        }

        /// <summary>解除所有动作回调，避免 Play Mode 重入后重复触发。</summary>
        private void UnsubscribeActions()
        {
            if (!_subscribed) return;
            navigateAction.performed -= OnNavigatePerformed;
            navigateAction.canceled -= OnNavigateCanceled;
            startAction.performed -= OnStartPerformed;
            markAction.performed -= OnMarkPerformed;
            stopAction.performed -= OnStopPerformed;
            rejectAction.performed -= OnRejectPerformed;

            int count = Math.Min(taskActions?.Length ?? 0, _taskCallbacks?.Length ?? 0);
            for (int index = 0; index < count; index++)
            {
                if (taskActions[index] != null)
                    taskActions[index].performed -= _taskCallbacks[index];
            }

            _taskCallbacks = null;
            _subscribed = false;
        }

        /// <summary>统一启用或停用所有内联动作。</summary>
        private void SetActionsEnabled(bool enabled)
        {
            SetActionEnabled(navigateAction, enabled);
            SetActionEnabled(startAction, enabled);
            SetActionEnabled(markAction, enabled);
            SetActionEnabled(stopAction, enabled);
            SetActionEnabled(rejectAction, enabled);
            if (taskActions == null) return;
            foreach (InputAction action in taskActions)
                SetActionEnabled(action, enabled);
        }

        /// <summary>启用或停用一个非空动作。</summary>
        private static void SetActionEnabled(InputAction action, bool enabled)
        {
            if (action == null) return;
            if (enabled) action.Enable();
            else action.Disable();
        }

        /// <summary>读取摇杆并在回中前只执行一次九宫格移动。</summary>
        private void OnNavigatePerformed(InputAction.CallbackContext context)
        {
            Vector2 value = context.ReadValue<Vector2>();
            if (_navigationLatched || value.magnitude < navigationThreshold) return;
            _navigationLatched = true;
            HandleNavigate(value);
        }

        /// <summary>摇杆回中后解除选择锁。</summary>
        private void OnNavigateCanceled(InputAction.CallbackContext context)
        {
            _navigationLatched = false;
        }

        /// <summary>处理开始动作回调。</summary>
        private void OnStartPerformed(InputAction.CallbackContext context) => HandleStart();

        /// <summary>处理事件 marker 动作回调。</summary>
        private void OnMarkPerformed(InputAction.CallbackContext context) => HandleMark();

        /// <summary>处理结束动作回调。</summary>
        private void OnStopPerformed(InputAction.CallbackContext context) => HandleStop();

        /// <summary>处理作废动作回调。</summary>
        private void OnRejectPerformed(InputAction.CallbackContext context) => HandleReject();

        /// <summary>移动九宫格选中项。</summary>
        public bool HandleNavigate(Vector2 direction)
        {
            return selector != null && selector.MoveSelection(direction);
        }

        /// <summary>开始当前选中任务。</summary>
        public bool HandleStart()
        {
            return selector != null && selector.StartTrial();
        }

        /// <summary>记录主事件或目标重新可见。</summary>
        public bool HandleMark()
        {
            return selector != null && selector.MarkEvent();
        }

        /// <summary>结束当前任务，或在至少完成一项后确认结束模块化 session。</summary>
        public bool HandleStop()
        {
            return selector != null && selector.StopOrFinish();
        }

        /// <summary>作废当前或选中任务的 trial。</summary>
        public bool HandleReject()
        {
            return selector != null && selector.RejectCurrentOrSelected();
        }

        /// <summary>键盘任务键：空闲时选择并开始；已完成任务直接重录；活动任务中再次按下写 marker。</summary>
        public bool HandleTask(int taskIndex)
        {
            if (selector == null || taskIndex < 0 || taskIndex >= ExperimentScenario.PlanCount)
                return false;
            if (selector.HasActiveTrial)
            {
                return selector.ActiveTaskIndex == taskIndex && selector.MarkEvent();
            }

            if (!selector.SelectTask(taskIndex)) return false;
            return selector.StartTrial();
        }

        /// <summary>创建九个没有硬编码 binding 的内联键盘任务动作。</summary>
        private static InputAction[] CreateTaskActions()
        {
            var actions = new InputAction[ExperimentScenario.PlanCount];
            for (int index = 0; index < actions.Length; index++)
                actions[index] = new InputAction($"Task{index + 1}", InputActionType.Button);
            return actions;
        }

    }
}
