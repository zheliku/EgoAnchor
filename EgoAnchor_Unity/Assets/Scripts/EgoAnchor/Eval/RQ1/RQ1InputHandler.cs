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
    [RequireComponent(typeof(RQ1MetricRecorder))]
    public sealed class RQ1InputHandler : MonoBehaviour
    {
        // ── References ──

        [Header("References")]
        [Tooltip("RQ1 metric recorder.")]
        [SerializeField] private RQ1MetricRecorder recorder;

        [Tooltip("Eval session controller (for F7/F8 control).")]
        [SerializeField] private EvalSession evalSession;

        // ── Input Actions ──

        [Header("Metric Input Actions")]
        [Tooltip("Set metric: Static Observation")]
        [SerializeField] private InputAction metric1Action = new InputAction(type: InputActionType.Button);

        [Tooltip("Set metric: Slow Translation")]
        [SerializeField] private InputAction metric2Action = new InputAction(type: InputActionType.Button);

        [Tooltip("Set metric: Fast Motion")]
        [SerializeField] private InputAction metric3Action = new InputAction(type: InputActionType.Button);

        [Tooltip("Set metric: Rotation")]
        [SerializeField] private InputAction metric4Action = new InputAction(type: InputActionType.Button);

        [Tooltip("Set metric: Occlusion Recovery")]
        [SerializeField] private InputAction metric5Action = new InputAction(type: InputActionType.Button);

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
            if (recorder == null) recorder = GetComponent<RQ1MetricRecorder>();
        }

        private void OnEnable()
        {
            // Register callbacks
            metric1Action.performed += _ => recorder?.SetMetric(RQ1MetricType.StaticObservation);
            metric2Action.performed += _ => recorder?.SetMetric(RQ1MetricType.SlowTranslation);
            metric3Action.performed += _ => recorder?.SetMetric(RQ1MetricType.FastMotion);
            metric4Action.performed += _ => recorder?.SetMetric(RQ1MetricType.Rotation);
            metric5Action.performed += _ => recorder?.SetMetric(RQ1MetricType.OcclusionRecovery);
            clearMetricAction.performed += _ => recorder?.ClearMetric();
            startRecordingAction.performed += _ =>
            {
                evalSession?.StartSession();
                recorder?.StartRecording();
            };
            stopRecordingAction.performed += _ =>
            {
                evalSession?.StopSession();
                recorder?.StopRecording();
            };

            // Enable all actions
            metric1Action.Enable();
            metric2Action.Enable();
            metric3Action.Enable();
            metric4Action.Enable();
            metric5Action.Enable();
            clearMetricAction.Enable();
            startRecordingAction.Enable();
            stopRecordingAction.Enable();
        }

        private void OnDisable()
        {
            // Disable all actions
            metric1Action.Disable();
            metric2Action.Disable();
            metric3Action.Disable();
            metric4Action.Disable();
            metric5Action.Disable();
            clearMetricAction.Disable();
            startRecordingAction.Disable();
            stopRecordingAction.Disable();
        }
    }
}
