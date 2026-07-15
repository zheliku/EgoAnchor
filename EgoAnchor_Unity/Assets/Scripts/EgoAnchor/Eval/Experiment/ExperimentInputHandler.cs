using UnityEngine;
using UnityEngine.InputSystem;

namespace EgoAnchor.Eval.Experiment
{
    /// <summary>把右手控制器 A 或桌面 Space 映射为唯一的采集推进动作。</summary>
    public sealed class ExperimentInputHandler : MonoBehaviour
    {
        /// <summary>接收推进动作的实验上下文选择器。</summary>
        [Header("References")]
        [Tooltip("固定采集计划选择器；右手 A 和键盘 Space 只调用其 Advance。")]
        [SerializeField] private ExperimentTrialSelector selector;

        /// <summary>Quest 右手 A 键的 Input System binding path，可在 Inspector 中改绑。</summary>
        [Header("Input System Bindings")]
        [Tooltip("手柄推进输入。默认是 Quest 右手 A；可填写其他 Input System binding path。")]
        [SerializeField] private string controllerBinding = "<XRController>{RightHand}/primaryButton";

        /// <summary>桌面键盘后备的 Input System binding path，可在 Inspector 中改绑。</summary>
        [Tooltip("键盘推进输入。默认是 Space；与手柄输入执行完全相同的采集动作。")]
        [SerializeField] private string keyboardBinding = "<Keyboard>/space";

        /// <summary>运行时创建的单一输入动作，避免在场景中维护多组快捷键。</summary>
        private InputAction _advanceAction;

        /// <summary>启用组件时创建并打开控制器/键盘绑定。</summary>
        private void OnEnable()
        {
            _advanceAction = new InputAction("AdvanceCollection", InputActionType.Button);
            AddBinding(controllerBinding);
            AddBinding(keyboardBinding);
            _advanceAction.performed += OnAdvancePerformed;
            _advanceAction.Enable();
        }

        /// <summary>向统一动作添加一条非空 binding path。</summary>
        private void AddBinding(string bindingPath)
        {
            if (!string.IsNullOrWhiteSpace(bindingPath))
                _advanceAction.AddBinding(bindingPath.Trim());
        }

        /// <summary>禁用组件时释放 Input System 资源，避免 Play Mode 重入后重复回调。</summary>
        private void OnDisable()
        {
            if (_advanceAction == null) return;
            _advanceAction.performed -= OnAdvancePerformed;
            _advanceAction.Disable();
            _advanceAction.Dispose();
            _advanceAction = null;
        }

        /// <summary>处理 Input System performed 回调。</summary>
        private void OnAdvancePerformed(InputAction.CallbackContext context)
        {
            HandleAdvance();
        }

        /// <summary>推进固定采集状态机；供输入回调和 EditMode 测试共用。</summary>
        public bool HandleAdvance()
        {
            return selector != null && selector.Advance();
        }
    }
}
