using UnityEngine;
using UnityEngine.InputSystem;

namespace EgoAnchor.Eval.RQ1
{
    /// <summary>
    /// RQ1 evaluation input handler.
    /// <para>
    /// Configure input bindings directly in Inspector.<br/>
    /// Default key bindings:<br/>
    /// - Keys 1-5: Set corresponding RQ1 metric<br/>
    /// - Key 0: Clear current metric<br/>
    /// - F7: Start recording<br/>
    /// - F8: Stop recording
    /// </para>
    /// </summary>
    [RequireComponent(typeof(RQ1MetricSelector))]
    public sealed class RQ1InputHandler : MonoBehaviour
    {
        // ── References ──

        [Header("References")]
        [Tooltip("RQ1 metric selector (holds the currently marked metric).")]
        [SerializeField] private RQ1MetricSelector selector;

        [Tooltip("Eval session controller (for F7/F8 control).")]
        [SerializeField] private EvalSession evalSession;

        // ── Input Actions ──

        [Header("Metric Input Actions")]
        [Tooltip("Set metric: Static Observation")]
        [SerializeField] private InputAction metric1Action = new InputAction(type: InputActionType.Button);

        [Tooltip("Set metric: Occlusion Recovery")]
        [SerializeField] private InputAction metric2Action = new InputAction(type: InputActionType.Button);

        [Tooltip("Clear current metric")]
        [SerializeField] private InputAction clearMetricAction = new InputAction(type: InputActionType.Button);

        [Header("Recording Control")]
        [Tooltip("Start recording session")]
        [SerializeField] private InputAction startRecordingAction = new InputAction(type: InputActionType.Button);

        [Tooltip("Stop recording session")]
        [SerializeField] private InputAction stopRecordingAction = new InputAction(type: InputActionType.Button);

        // ── Unity Lifecycle ──

        private void Awake()
        {
            if (selector == null) selector = GetComponent<RQ1MetricSelector>();
        }

        private void OnEnable()
        {
            // Register callbacks
            metric1Action.performed += _ => selector?.SetMetric(RQ1MetricType.StaticObservation);
            metric2Action.performed += _ => selector?.SetMetric(RQ1MetricType.OcclusionRecovery);
            clearMetricAction.performed += _ => selector?.ClearMetric();
            startRecordingAction.performed += _ => evalSession?.StartSession();
            stopRecordingAction.performed += _ => evalSession?.StopSession();

            // Enable all actions
            metric1Action.Enable();
            metric2Action.Enable();
            clearMetricAction.Enable();
            startRecordingAction.Enable();
            stopRecordingAction.Enable();
        }

        private void OnDisable()
        {
            // Disable all actions
            metric1Action.Disable();
            metric2Action.Disable();
            clearMetricAction.Disable();
            startRecordingAction.Disable();
            stopRecordingAction.Disable();
        }
    }
}
