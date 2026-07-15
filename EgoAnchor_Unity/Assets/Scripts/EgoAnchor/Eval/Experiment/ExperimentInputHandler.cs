using UnityEngine;
using UnityEngine.InputSystem;

namespace EgoAnchor.Eval.Experiment
{
    /// <summary>实验采集键盘输入：数字键选场景，Enter/Space/Shift+Space/0 管理 trial 和事件。</summary>
    public sealed class ExperimentInputHandler : MonoBehaviour
    {
        /// <summary>接收输入的实验上下文选择器。</summary>
        [Header("References")]
        [Tooltip("实验 trial selector；输入只调用 selector，不直接写日志。")]
        [SerializeField] private ExperimentTrialSelector selector;

        /// <summary>是否允许 F7/F8 控制 EvalSession。</summary>
        [Tooltip("启用后 F7 开始 session，F8 停止 session。")]
        [SerializeField] private bool controlSessionShortcuts = true;

        /// <summary>可选的 session 快捷键目标。</summary>
        [SerializeField] private EvalSession session;

        /// <summary>轮询 Unity Input System 键盘状态。</summary>
        private void Update()
        {
            Keyboard keyboard = Keyboard.current;
            if (keyboard == null) return;

            bool shift = keyboard.leftShiftKey.isPressed || keyboard.rightShiftKey.isPressed;
            if (keyboard.digit1Key.wasPressedThisFrame) HandleNumber(1, shift);
            if (keyboard.digit2Key.wasPressedThisFrame) HandleNumber(2, shift);
            if (keyboard.digit3Key.wasPressedThisFrame) HandleNumber(3, shift);
            if (keyboard.digit4Key.wasPressedThisFrame) HandleNumber(4, shift);
            if (keyboard.digit5Key.wasPressedThisFrame) HandleNumber(5, shift);
            if (keyboard.enterKey.wasPressedThisFrame) HandleEnter();
            if (keyboard.spaceKey.wasPressedThisFrame) HandleSpace(shift);
            if (keyboard.digit0Key.wasPressedThisFrame) HandleZero();

            if (controlSessionShortcuts && keyboard.f7Key.wasPressedThisFrame)
                session?.StartSession();
            if (controlSessionShortcuts && keyboard.f8Key.wasPressedThisFrame)
                session?.StopSession();
        }

        /// <summary>处理数字键场景选择；按住 Shift 时进入实验二归因。</summary>
        public void HandleNumber(int key, bool shift)
        {
            if (selector == null) return;
            if (shift) selector.SelectAttributionScenario(key);
            else if (key <= 5) selector.SelectSystemScenario(key);
        }

        /// <summary>处理 Enter：开始当前场景 trial。</summary>
        public void HandleEnter()
        {
            selector?.BeginTrial();
        }

        /// <summary>处理 Space：普通按键标记主事件，按住 Shift 标记目标重新可见。</summary>
        public void HandleSpace(bool shift)
        {
            if (selector == null) return;
            if (shift) selector.MarkTargetVisible();
            else selector.MarkPrimaryEvent();
        }

        /// <summary>处理 0：结束当前 trial。</summary>
        public void HandleZero()
        {
            selector?.EndTrial();
        }
    }
}
