using UnityEngine;
using UnityEngine.InputSystem;

namespace EgoAnchor.Eval.RQ2
{
    /// <summary>
    /// RQ2 试次与评估 session 的输入映射。
    /// <para>
    /// 该组件只把输入转发给 <see cref="RQ2TrialSelector"/> 与 <see cref="EvalSession"/>；
    /// 试次上下文与录制状态仍分别由这两个组件独立维护。
    /// </para>
    /// </summary>
    [RequireComponent(typeof(RQ2TrialSelector))]
    public sealed class RQ2InputHandler : MonoBehaviour
    {
        /// <summary>保存当前 RQ2 试次上下文的选择器。</summary>
        [Header("References")]
        [Tooltip("保存当前 RQ2 试次上下文的选择器。")]
        [SerializeField] private RQ2TrialSelector selector;

        /// <summary>唯一的评估 session 录制控制器。</summary>
        [Tooltip("唯一的 EvalSession 录制控制器，仅用于 F7/F8。")]
        [SerializeField] private EvalSession evalSession;

        /// <summary>慢速平移试次的预设目标线速度，单位 m/s。</summary>
        [Header("Target Speeds")]
        [Tooltip("慢速平移试次的预设目标线速度，单位 m/s；实际速度仍以 GT 轨迹为准。")]
        [Min(0f)]
        [SerializeField] private float slowTranslationSpeedMs = 0.10f;

        /// <summary>快速挥动试次的预设目标线速度，单位 m/s。</summary>
        [Tooltip("快速挥动试次的预设目标线速度，单位 m/s；实际速度仍以 GT 轨迹为准。")]
        [Min(0f)]
        [SerializeField] private float fastMotionSpeedMs = 0.80f;

        /// <summary>旋转试次的预设目标角速度，单位 deg/s。</summary>
        [Tooltip("旋转试次的预设目标角速度，单位 deg/s；实际速度仍以 GT 轨迹为准。")]
        [Min(0f)]
        [SerializeField] private float rotationSpeedDegS = 90f;

        /// <summary>开始慢速平移试次的输入动作，默认键为 1。</summary>
        [Header("Trial Input Actions")]
        [Tooltip("开始慢速平移试次，默认键为 1。")]
        [SerializeField] private InputAction startSlowTranslationAction =
            new InputAction("Start Slow Translation", InputActionType.Button, "<Keyboard>/1");

        /// <summary>开始快速挥动试次的输入动作，默认键为 2。</summary>
        [Tooltip("开始快速挥动试次，默认键为 2。")]
        [SerializeField] private InputAction startFastMotionAction =
            new InputAction("Start Fast Motion", InputActionType.Button, "<Keyboard>/2");

        /// <summary>开始旋转试次的输入动作，默认键为 3。</summary>
        [Tooltip("开始旋转试次，默认键为 3。")]
        [SerializeField] private InputAction startRotationAction =
            new InputAction("Start Rotation", InputActionType.Button, "<Keyboard>/3");

        /// <summary>结束当前试次的输入动作，默认键为 0。</summary>
        [Tooltip("结束当前 RQ2 试次，默认键为 0。")]
        [SerializeField] private InputAction endTrialAction =
            new InputAction("End Trial", InputActionType.Button, "<Keyboard>/0");

        /// <summary>开始评估 session 的输入动作，默认键为 F7。</summary>
        [Header("Session Input Actions")]
        [Tooltip("开始评估 session，默认键为 F7。")]
        [SerializeField] private InputAction startRecordingAction =
            new InputAction("Start Recording", InputActionType.Button, "<Keyboard>/f7");

        /// <summary>停止评估 session 的输入动作，默认键为 F8。</summary>
        [Tooltip("停止评估 session，默认键为 F8。")]
        [SerializeField] private InputAction stopRecordingAction =
            new InputAction("Stop Recording", InputActionType.Button, "<Keyboard>/f8");

        /// <summary>补齐同一 GameObject 上的 selector 引用。</summary>
        private void Awake()
        {
            if (selector == null) selector = GetComponent<RQ2TrialSelector>();
            if (selector != null && evalSession != null) selector.BindSession(evalSession);
        }

        /// <summary>注册输入回调并启用全部动作。</summary>
        private void OnEnable()
        {
            startSlowTranslationAction.performed += OnStartSlowTranslation;
            startFastMotionAction.performed += OnStartFastMotion;
            startRotationAction.performed += OnStartRotation;
            endTrialAction.performed += OnEndTrial;
            startRecordingAction.performed += OnStartRecording;
            stopRecordingAction.performed += OnStopRecording;

            startSlowTranslationAction.Enable();
            startFastMotionAction.Enable();
            startRotationAction.Enable();
            endTrialAction.Enable();
            startRecordingAction.Enable();
            stopRecordingAction.Enable();
        }

        /// <summary>禁用全部动作并注销输入回调，避免组件反复启用后重复触发。</summary>
        private void OnDisable()
        {
            startSlowTranslationAction.Disable();
            startFastMotionAction.Disable();
            startRotationAction.Disable();
            endTrialAction.Disable();
            startRecordingAction.Disable();
            stopRecordingAction.Disable();

            startSlowTranslationAction.performed -= OnStartSlowTranslation;
            startFastMotionAction.performed -= OnStartFastMotion;
            startRotationAction.performed -= OnStartRotation;
            endTrialAction.performed -= OnEndTrial;
            startRecordingAction.performed -= OnStartRecording;
            stopRecordingAction.performed -= OnStopRecording;
        }

        /// <summary>开始慢速平移试次。</summary>
        private void OnStartSlowTranslation(InputAction.CallbackContext context)
        {
            selector?.StartTrial(RQ2Condition.SlowTranslation, slowTranslationSpeedMs, float.NaN);
        }

        /// <summary>开始快速挥动试次。</summary>
        private void OnStartFastMotion(InputAction.CallbackContext context)
        {
            selector?.StartTrial(RQ2Condition.FastMotion, fastMotionSpeedMs, float.NaN);
        }

        /// <summary>开始旋转试次。</summary>
        private void OnStartRotation(InputAction.CallbackContext context)
        {
            selector?.StartTrial(RQ2Condition.Rotation, float.NaN, rotationSpeedDegS);
        }

        /// <summary>结束当前试次。</summary>
        private void OnEndTrial(InputAction.CallbackContext context)
        {
            selector?.EndTrial();
        }

        /// <summary>请求 EvalSession 开始录制。</summary>
        private void OnStartRecording(InputAction.CallbackContext context)
        {
            evalSession?.StartSession();
        }

        /// <summary>请求 EvalSession 停止录制。</summary>
        private void OnStopRecording(InputAction.CallbackContext context)
        {
            evalSession?.StopSession();
        }
    }
}
