using UnityEngine;
using UnityEngine.InputSystem;

namespace EgoAnchor.Eval.RQ1
{
    /// <summary>
    /// RQ1 指标与评估 session 的输入映射。
    /// <para>
    /// 数字键 1/2 选择指标，0 清除指标，F7/F8 控制录制。该组件只转发输入，
    /// 指标和录制状态分别由 <see cref="RQ1MetricSelector"/> 与 <see cref="EvalSession"/> 维护。
    /// </para>
    /// </summary>
    [RequireComponent(typeof(RQ1MetricSelector))]
    public sealed class RQ1InputHandler : MonoBehaviour
    {
        /// <summary>保存当前 RQ1 指标标记的选择器。</summary>
        [Header("References")]
        [Tooltip("保存当前 RQ1 指标标记的选择器。")]
        [SerializeField] private RQ1MetricSelector selector;

        /// <summary>唯一的评估 session 录制控制器。</summary>
        [Tooltip("唯一的 EvalSession 录制控制器，仅用于 F7/F8。")]
        [SerializeField] private EvalSession evalSession;

        /// <summary>开始长时静止观察标记的输入动作，默认键为 1。</summary>
        [Header("Metric Input Actions")]
        [Tooltip("开始长时静止观察标记，默认键为 1。")]
        [SerializeField] private InputAction metric1Action =
            new InputAction("Metric 1", InputActionType.Button, "<Keyboard>/1");

        /// <summary>开始一次遮挡恢复标记的输入动作，默认键为 2。</summary>
        [Tooltip("开始一次遮挡恢复标记，默认键为 2。")]
        [SerializeField] private InputAction metric2Action =
            new InputAction("Metric 2", InputActionType.Button, "<Keyboard>/2");

        /// <summary>清除当前指标标记的输入动作，默认键为 0。</summary>
        [Tooltip("清除当前指标标记，默认键为 0。")]
        [SerializeField] private InputAction clearMetricAction =
            new InputAction("Clear Metric", InputActionType.Button, "<Keyboard>/0");

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
            if (selector == null) selector = GetComponent<RQ1MetricSelector>();
        }

        /// <summary>注册输入回调并启用全部动作。</summary>
        private void OnEnable()
        {
            metric1Action.performed += OnSelectStaticObservation;
            metric2Action.performed += OnSelectOcclusionRecovery;
            clearMetricAction.performed += OnClearMetric;
            startRecordingAction.performed += OnStartRecording;
            stopRecordingAction.performed += OnStopRecording;

            metric1Action.Enable();
            metric2Action.Enable();
            clearMetricAction.Enable();
            startRecordingAction.Enable();
            stopRecordingAction.Enable();
        }

        /// <summary>禁用全部动作并注销回调，避免组件反复启用后重复触发。</summary>
        private void OnDisable()
        {
            metric1Action.Disable();
            metric2Action.Disable();
            clearMetricAction.Disable();
            startRecordingAction.Disable();
            stopRecordingAction.Disable();

            metric1Action.performed -= OnSelectStaticObservation;
            metric2Action.performed -= OnSelectOcclusionRecovery;
            clearMetricAction.performed -= OnClearMetric;
            startRecordingAction.performed -= OnStartRecording;
            stopRecordingAction.performed -= OnStopRecording;
        }

        /// <summary>选择长时静止观察指标。</summary>
        private void OnSelectStaticObservation(InputAction.CallbackContext context)
        {
            selector?.SetMetric(RQ1MetricType.StaticObservation);
        }

        /// <summary>选择一次遮挡恢复指标。</summary>
        private void OnSelectOcclusionRecovery(InputAction.CallbackContext context)
        {
            selector?.SetMetric(RQ1MetricType.OcclusionRecovery);
        }

        /// <summary>清除当前 RQ1 指标。</summary>
        private void OnClearMetric(InputAction.CallbackContext context)
        {
            selector?.ClearMetric();
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
