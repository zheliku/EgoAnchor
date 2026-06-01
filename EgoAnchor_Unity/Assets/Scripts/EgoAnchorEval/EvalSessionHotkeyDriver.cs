using UnityEngine;
using UnityEngine.InputSystem;

namespace EgoAnchorEval
{
    /// <summary>
    /// U3/U4 手动验收热键组件：用 Unity 新 Input System 驱动 session、条件段和事件 marker。
    /// </summary>
    public sealed class EvalSessionHotkeyDriver : MonoBehaviour
    {
        /// <summary>被热键控制的 session controller。</summary>
        [Header("References")]
        [Tooltip("被热键控制的 EvalSessionController。")]
        [SerializeField] private EvalSessionController controller;

        /// <summary>开始录制热键。</summary>
        [Header("Session Keys")]
        [Tooltip("开始录制热键。默认 F7。")]
        [SerializeField] private Key startSessionKey = Key.F7;

        /// <summary>停止录制热键。</summary>
        [Tooltip("停止录制热键。默认 F8。")]
        [SerializeField] private Key stopSessionKey = Key.F8;

        /// <summary>结束当前条件段热键。</summary>
        [Tooltip("结束当前条件段热键。默认 Digit0。")]
        [SerializeField] private Key endConditionKey = Key.Digit0;

        /// <summary>static 条件段热键。</summary>
        [Header("Condition Keys")]
        [Tooltip("static 条件段热键。默认 Digit1。")]
        [SerializeField] private Key staticKey = Key.Digit1;

        /// <summary>slow_head 条件段热键。</summary>
        [Tooltip("slow_head 条件段热键。默认 Digit2。")]
        [SerializeField] private Key slowHeadKey = Key.Digit2;

        /// <summary>fast_head 条件段热键。</summary>
        [Tooltip("fast_head 条件段热键。默认 Digit3。")]
        [SerializeField] private Key fastHeadKey = Key.Digit3;

        /// <summary>object_motion 条件段热键。</summary>
        [Tooltip("object_motion 条件段热键。默认 Digit4。")]
        [SerializeField] private Key objectMotionKey = Key.Digit4;

        /// <summary>occlusion 条件段热键。</summary>
        [Tooltip("occlusion 条件段热键。默认 Digit5。")]
        [SerializeField] private Key occlusionKey = Key.Digit5;

        /// <summary>out_of_view 条件段热键。</summary>
        [Tooltip("out_of_view 条件段热键。默认 Digit6。")]
        [SerializeField] private Key outOfViewKey = Key.Digit6;

        /// <summary>lighting 条件段热键。</summary>
        [Tooltip("lighting 条件段热键。默认 Digit7。")]
        [SerializeField] private Key lightingKey = Key.Digit7;

        /// <summary>occlusion 事件 marker 热键。</summary>
        [Header("Marker Keys")]
        [Tooltip("occlusion 事件 marker 热键。默认 O。")]
        [SerializeField] private Key markOcclusionKey = Key.O;

        /// <summary>out_of_view 事件 marker 热键。</summary>
        [Tooltip("out_of_view 事件 marker 热键。默认 V。")]
        [SerializeField] private Key markOutOfViewKey = Key.V;

        /// <summary>recovery 事件 marker 热键。</summary>
        [Tooltip("recovery 事件 marker 热键。默认 R。")]
        [SerializeField] private Key markRecoveryKey = Key.R;

        /// <summary>
        /// 每帧读取新 Input System 键盘状态。
        /// </summary>
        private void Update()
        {
            if (controller == null || Keyboard.current == null)
            {
                return;
            }

            if (WasPressedThisFrame(startSessionKey))
            {
                controller.StartSession();
            }

            if (WasPressedThisFrame(stopSessionKey))
            {
                controller.StopSession();
            }

            if (WasPressedThisFrame(endConditionKey))
            {
                controller.EndCondition();
            }

            if (WasPressedThisFrame(staticKey))
            {
                BeginStaticCondition();
            }

            if (WasPressedThisFrame(slowHeadKey))
            {
                BeginSlowHeadCondition();
            }

            if (WasPressedThisFrame(fastHeadKey))
            {
                BeginFastHeadCondition();
            }

            if (WasPressedThisFrame(objectMotionKey))
            {
                BeginObjectMotionCondition();
            }

            if (WasPressedThisFrame(occlusionKey))
            {
                BeginOcclusionCondition();
            }

            if (WasPressedThisFrame(outOfViewKey))
            {
                BeginOutOfViewCondition();
            }

            if (WasPressedThisFrame(lightingKey))
            {
                BeginLightingCondition();
            }

            if (WasPressedThisFrame(markOcclusionKey))
            {
                MarkOcclusion();
            }

            if (WasPressedThisFrame(markOutOfViewKey))
            {
                MarkOutOfView();
            }

            if (WasPressedThisFrame(markRecoveryKey))
            {
                MarkRecovery();
            }
        }

        /// <summary>Inspector/按钮入口：开始 session。</summary>
        [ContextMenu("EgoAnchor Eval/Start Session")]
        public void StartSession() => controller?.StartSession();

        /// <summary>Inspector/按钮入口：停止 session。</summary>
        [ContextMenu("EgoAnchor Eval/Stop Session")]
        public void StopSession() => controller?.StopSession();

        /// <summary>Inspector/按钮入口：开始 static 条件段。</summary>
        [ContextMenu("EgoAnchor Eval/Condition Static")]
        public void BeginStaticCondition() => controller?.BeginStaticCondition();

        /// <summary>Inspector/按钮入口：开始 slow_head 条件段。</summary>
        [ContextMenu("EgoAnchor Eval/Condition Slow Head")]
        public void BeginSlowHeadCondition() => controller?.BeginSlowHeadCondition();

        /// <summary>Inspector/按钮入口：开始 fast_head 条件段。</summary>
        [ContextMenu("EgoAnchor Eval/Condition Fast Head")]
        public void BeginFastHeadCondition() => controller?.BeginFastHeadCondition();

        /// <summary>Inspector/按钮入口：开始 object_motion 条件段。</summary>
        [ContextMenu("EgoAnchor Eval/Condition Object Motion")]
        public void BeginObjectMotionCondition() => controller?.BeginObjectMotionCondition();

        /// <summary>Inspector/按钮入口：开始 occlusion 条件段。</summary>
        [ContextMenu("EgoAnchor Eval/Condition Occlusion")]
        public void BeginOcclusionCondition() => controller?.BeginOcclusionCondition();

        /// <summary>Inspector/按钮入口：开始 out_of_view 条件段。</summary>
        [ContextMenu("EgoAnchor Eval/Condition Out Of View")]
        public void BeginOutOfViewCondition() => controller?.BeginOutOfViewCondition();

        /// <summary>Inspector/按钮入口：开始 lighting 条件段。</summary>
        [ContextMenu("EgoAnchor Eval/Condition Lighting")]
        public void BeginLightingCondition() => controller?.BeginLightingCondition();

        /// <summary>Inspector/按钮入口：记录 occlusion marker。</summary>
        [ContextMenu("EgoAnchor Eval/Mark Occlusion")]
        public void MarkOcclusion() => controller?.MarkOcclusion();

        /// <summary>Inspector/按钮入口：记录 out_of_view marker。</summary>
        [ContextMenu("EgoAnchor Eval/Mark Out Of View")]
        public void MarkOutOfView() => controller?.MarkOutOfView();

        /// <summary>Inspector/按钮入口：记录 recovery marker。</summary>
        [ContextMenu("EgoAnchor Eval/Mark Recovery")]
        public void MarkRecovery() => controller?.MarkRecovery();

        /// <summary>
        /// 使用 Unity 新 Input System 检查单帧按键。
        /// </summary>
        private static bool WasPressedThisFrame(Key key)
        {
            return key != Key.None
                && Keyboard.current != null
                && Keyboard.current[key].wasPressedThisFrame;
        }
    }
}
