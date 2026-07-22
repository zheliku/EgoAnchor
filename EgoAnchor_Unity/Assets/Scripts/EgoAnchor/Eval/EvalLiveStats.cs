using System.Text;
using EgoAnchor.Alignment;
using EgoAnchor.Runtime;
using TMPro;
using UnityEngine;

namespace EgoAnchor.Eval
{
    /// <summary>
    /// 正式评估场景的只读实时诊断面板。
    /// <para>
    /// 面板读取完整 EgoAnchor 变体、平台控制器参考和 frame history，显示当前输出差异、
    /// 图像观测年龄、pose 更新率、可靠性、残差、帧间变化与锚点状态。
    /// </para>
    /// <para>
    /// 位置和旋转差异使用平台控制器参考，不是外部光学真值；观测年龄使用 Unity 同一
    /// 单调时钟计算，不是纯网络时延。面板只用于采集前检查和现场排障，论文指标仍以
    /// schema-v2 离线配对分析为准。
    /// </para>
    /// </summary>
    public sealed class EvalLiveStats : MonoBehaviour
    {
        /// <summary>提供完整 EgoAnchor runtime、显示 Transform、参考位姿和 frame history。</summary>
        [Header("References")]
        [Tooltip("评估记录器；实时诊断与正式日志使用同一主变体、平台参考和 frame history。")]
        [SerializeField] private EvalRecorder recorder;

        /// <summary>实时诊断文本。</summary>
        [Tooltip("独立实时诊断面板的 TextMeshProUGUI。")]
        [SerializeField] private TextMeshProUGUI statsText;

        /// <summary>文本刷新频率；信号仍在每个 Unity frame 采样。</summary>
        [Header("Refresh")]
        [Min(1f)]
        [Tooltip("文本每秒刷新次数。指标仍按 Unity frame 采样，此值只限制文本重绘。")]
        [SerializeField] private float updateRate = 10f;

        /// <summary>超过该时间没有新 frame_id 时，pose rate 显示为 0。</summary>
        [Min(0.1f)]
        [Tooltip("连续多少秒没有新 frame_id 后把 pose rate 置为 0，避免保留过期更新率。")]
        [SerializeField] private float poseRateTimeoutSeconds = 2f;

        /// <summary>观测年龄绿色上限，单位毫秒。</summary>
        [Header("Observation Age Thresholds (ms)")]
        [Tooltip("观测年龄不高于此值时显示绿色。它不是纯网络时延。")]
        [SerializeField] private float observationAgeGoodMs = 120f;

        /// <summary>观测年龄红色下限，单位毫秒。</summary>
        [Tooltip("观测年龄不低于此值时显示红色；中间区间显示黄色。")]
        [SerializeField] private float observationAgeBadMs = 200f;

        /// <summary>平台参考位置差异绿色上限，单位毫米。</summary>
        [Header("Platform Reference Delta Thresholds")]
        [Tooltip("显示 pose 相对平台控制器参考的位置差异绿色上限，单位毫米。")]
        [SerializeField] private float positionDeltaGoodMm = 10f;

        /// <summary>平台参考位置差异红色下限，单位毫米。</summary>
        [Tooltip("显示 pose 相对平台控制器参考的位置差异红色下限，单位毫米。")]
        [SerializeField] private float positionDeltaBadMm = 20f;

        /// <summary>平台参考旋转差异绿色上限，单位度。</summary>
        [Tooltip("显示 pose 相对平台控制器参考的旋转差异绿色上限，单位度。")]
        [SerializeField] private float rotationDeltaGoodDeg = 5f;

        /// <summary>平台参考旋转差异红色下限，单位度。</summary>
        [Tooltip("显示 pose 相对平台控制器参考的旋转差异红色下限，单位度。")]
        [SerializeField] private float rotationDeltaBadDeg = 20f;

        /// <summary>当前文本刷新周期内累计时间。</summary>
        private float _updateTimer;

        /// <summary>最近一次看到的主变体 frame_id。</summary>
        private long _lastSeenFrameId = long.MinValue;

        /// <summary>最近一次 frame_id 变化的 Unity 单调时钟毫秒。</summary>
        private double _lastFrameChangeMonoMs = double.NaN;

        /// <summary>最新图像观测年龄，单位毫秒。</summary>
        private double _latestObservationAgeMs = double.NaN;

        /// <summary>图像时间代理到 Unity 完成 pose 处理的同帧到达延迟，单位毫秒。</summary>
        private double _latestE2eArrivalMs = double.NaN;

        /// <summary>最新 pose 更新率，单位 Hz。</summary>
        private double _latestPoseHz = double.NaN;

        /// <summary>显示 pose 相对平台参考的位置差异，单位米。</summary>
        private double _latestPositionDeltaM = double.NaN;

        /// <summary>显示 pose 相对平台参考的旋转差异，单位度。</summary>
        private double _latestRotationDeltaDeg = double.NaN;

        /// <summary>相邻 Unity frame 的显示位置变化，单位米。</summary>
        private double _latestFrameStepM = double.NaN;

        /// <summary>相邻 Unity frame 的显示旋转变化，单位度。</summary>
        private double _latestFrameStepDeg = double.NaN;

        /// <summary>上一帧显示 pose，用于计算帧间变化。</summary>
        private Pose _lastDisplayPose;

        /// <summary>是否已有上一帧显示 pose。</summary>
        private bool _hasLastDisplayPose;

        /// <summary>主 runtime 当前是否提供有效 output pose。</summary>
        private bool _hasOutput;

        /// <summary>主变体当前是否实际显示 pose，包括 hold-last。</summary>
        private bool _hasDisplay;

        /// <summary>平台参考 Transform 是否已绑定。</summary>
        private bool _hasReference;

        /// <summary>平台参考 Transform 当前是否激活；false 时 pose 保持最后一次激活值。</summary>
        private bool _referenceActive;

        /// <summary>当前是否处于可读取 OpenXR 状态的 Play Mode。</summary>
        private bool _xrRuntimeActive;

        /// <summary>OpenXR 当前是否检测到头显设备。</summary>
        private bool _hmdPresent;

        /// <summary>Meta runtime 当前是否判断用户佩戴着头显。</summary>
        private bool _userPresent;

        /// <summary>Unity 应用当前是否持有 VR focus。</summary>
        private bool _vrFocus;

        /// <summary>Unity 应用当前是否持有 XR 输入 focus。</summary>
        private bool _inputFocus;

        /// <summary>最新图像观测年龄，单位毫秒；无有效 frame 时为 NaN。</summary>
        public double LatestObservationAgeMs => _latestObservationAgeMs;

        /// <summary>图像时间代理到 Unity 完成 pose 处理的同帧到达延迟，单位毫秒。</summary>
        public double LatestE2eArrivalMs => _latestE2eArrivalMs;

        /// <summary>最新 pose 更新率，单位 Hz；尚未得到两个 frame_id 时为 NaN。</summary>
        public double LatestPoseHz => _latestPoseHz;

        /// <summary>显示 pose 相对平台参考的位置差异，单位米。</summary>
        public double LatestPositionDeltaM => _latestPositionDeltaM;

        /// <summary>显示 pose 相对平台参考的旋转差异，单位度。</summary>
        public double LatestRotationDeltaDeg => _latestRotationDeltaDeg;

        /// <summary>相邻 Unity frame 的显示位置变化，单位米。</summary>
        public double LatestFrameStepM => _latestFrameStepM;

        /// <summary>相邻 Unity frame 的显示旋转变化，单位度。</summary>
        public double LatestFrameStepDeg => _latestFrameStepDeg;

        /// <summary>主 runtime 当前是否有有效 output pose。</summary>
        public bool HasOutput => _hasOutput;

        /// <summary>主变体当前是否实际显示 pose，包括 hold-last。</summary>
        public bool HasDisplay => _hasDisplay;

        /// <summary>平台参考 Transform 是否已绑定。</summary>
        public bool HasReference => _hasReference;

        /// <summary>平台参考 Transform 当前是否激活。</summary>
        public bool ReferenceActive => _referenceActive;

        /// <summary>每帧采样实时信号，并按配置频率重绘文本。</summary>
        private void Update()
        {
            SampleLiveSignals();
            _updateTimer += Time.deltaTime;
            if (_updateTimer < 1f / Mathf.Max(1f, updateRate)) return;

            _updateTimer = 0f;
            RenderText();
        }

        /// <summary>从主变体和平台参考读取一次不改变运行状态的实时快照。</summary>
        private void SampleLiveSignals()
        {
            SampleXrStatus();
            PoseToAnchorRuntime runtime = recorder != null ? recorder.PrimaryRuntime : null;
            if (runtime == null)
            {
                ClearAllSignals();
                return;
            }

            double nowMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            long frameId = runtime.LatestAlignedFrameId;
            UpdatePoseRate(frameId, nowMs);
            UpdateTiming(frameId, nowMs, runtime.LatestUnityPoseHandleMonoMs);

            _hasOutput = runtime.TryGetOutputPose(out _);
            _hasReference = recorder.TryGetLiveReferencePose(out Pose referencePose, out _referenceActive);

            _hasDisplay = recorder.TryGetPrimaryDisplayPose(out Pose displayPose);
            if (!_hasDisplay)
            {
                ClearDisplaySignals();
                return;
            }
            UpdateFrameStep(displayPose);

            _latestPositionDeltaM = double.NaN;
            _latestRotationDeltaDeg = double.NaN;
            if (_hasReference)
            {
                _latestPositionDeltaM = (displayPose.position - referencePose.position).magnitude;
                _latestRotationDeltaDeg = Quaternion.Angle(displayPose.rotation, referencePose.rotation);
            }
        }

        /// <summary>读取 Meta OpenXR 的设备、佩戴和 focus 状态；EditMode 不调用原生 XR API。</summary>
        private void SampleXrStatus()
        {
            _xrRuntimeActive = Application.isPlaying;
            if (!_xrRuntimeActive)
            {
                _hmdPresent = false;
                _userPresent = false;
                _vrFocus = false;
                _inputFocus = false;
                return;
            }

            _hmdPresent = OVRManager.isHmdPresent;
            _userPresent = OVRManager.instance != null && OVRManager.instance.isUserPresent;
            _vrFocus = OVRManager.hasVrFocus;
            _inputFocus = OVRManager.hasInputFocus;
        }

        /// <summary>按新 frame_id 的到达间隔更新 pose rate，并在数据停滞时归零。</summary>
        private void UpdatePoseRate(long frameId, double nowMs)
        {
            if (frameId >= 0 && frameId != _lastSeenFrameId)
            {
                if (!double.IsNaN(_lastFrameChangeMonoMs))
                {
                    double intervalMs = nowMs - _lastFrameChangeMonoMs;
                    if (intervalMs > 1e-3) _latestPoseHz = 1000.0 / intervalMs;
                }

                _lastSeenFrameId = frameId;
                _lastFrameChangeMonoMs = nowMs;
                return;
            }

            double timeoutMs = Mathf.Max(0.1f, poseRateTimeoutSeconds) * 1000.0;
            if (!double.IsNaN(_lastFrameChangeMonoMs) && nowMs - _lastFrameChangeMonoMs >= timeoutMs)
                _latestPoseHz = 0.0;
        }

        /// <summary>
        /// 使用 Unity 同一单调时钟计算观测年龄和同帧 E2E arrival。
        /// E2E arrival 只在 handle 时间仍与当前 aligned frame_id 原子对应时有效。
        /// </summary>
        private void UpdateTiming(long frameId, double nowMs, double handleMonoMs)
        {
            _latestObservationAgeMs = double.NaN;
            _latestE2eArrivalMs = double.NaN;
            FramePoseHistory history = recorder.FrameHistory;
            if (frameId < 0 || history == null || !history.TryGet(frameId, out FramePoseRecord record))
                return;

            double ageMs = nowMs - record.ImageMonoMs;
            if (ageMs >= 0.0) _latestObservationAgeMs = ageMs;

            double arrivalMs = handleMonoMs - record.ImageMonoMs;
            if (!double.IsNaN(handleMonoMs) && arrivalMs >= 0.0)
                _latestE2eArrivalMs = arrivalMs;
        }

        /// <summary>计算连续显示 pose 的帧间位置和旋转变化。</summary>
        private void UpdateFrameStep(Pose displayPose)
        {
            if (_hasLastDisplayPose)
            {
                _latestFrameStepM = (displayPose.position - _lastDisplayPose.position).magnitude;
                _latestFrameStepDeg = Quaternion.Angle(displayPose.rotation, _lastDisplayPose.rotation);
            }

            _lastDisplayPose = displayPose;
            _hasLastDisplayPose = true;
        }

        /// <summary>清空依赖有效显示输出的差异和帧间变化。</summary>
        private void ClearDisplaySignals()
        {
            _latestPositionDeltaM = double.NaN;
            _latestRotationDeltaDeg = double.NaN;
            _latestFrameStepM = double.NaN;
            _latestFrameStepDeg = double.NaN;
            _hasLastDisplayPose = false;
        }

        /// <summary>主 runtime 不存在时清空全部实时状态。</summary>
        private void ClearAllSignals()
        {
            _latestObservationAgeMs = double.NaN;
            _latestE2eArrivalMs = double.NaN;
            _latestPoseHz = double.NaN;
            _lastSeenFrameId = long.MinValue;
            _lastFrameChangeMonoMs = double.NaN;
            _hasOutput = false;
            _hasDisplay = false;
            _hasReference = false;
            _referenceActive = false;
            ClearDisplaySignals();
        }

        /// <summary>按最新采样状态构建实时诊断文本，供运行时和测试复用。</summary>
        public string BuildStatsText()
        {
            PoseToAnchorRuntime runtime = recorder != null ? recorder.PrimaryRuntime : null;
            if (runtime == null)
                return "<size=30><b>LIVE SYSTEM DIAGNOSTICS</b></size>\nRuntime not configured";

            var builder = new StringBuilder();
            string outputStatus = Status(_hasOutput, "VALID", "WAITING");
            string displayStatus = Status(_hasDisplay, "VISIBLE", "HIDDEN");
            string e2eArrival = Number(_latestE2eArrivalMs, "0", " ms");
            string serverProcessing = Number(runtime.LatestServerProcessingMs, "0", " ms");
            string smoothingDelay = Number(runtime.LatestSmoothingDelayMs, "0", " ms");
            string poseRate = Number(_latestPoseHz, "0.0", " Hz");
            string residualPosition = Number(runtime.LatestCorrectionPositionResidualMeters * 1000.0, "0.0", " mm");
            string residualRotation = Number(runtime.LatestCorrectionRotationResidualDegrees, "0.00", " deg");
            string frameStepPosition = Number(_latestFrameStepM * 1000.0, "0.0", " mm");
            string frameStepRotation = Number(_latestFrameStepDeg, "0.00", " deg");
            string staticLock = runtime.LatestStaticLocked ? "ON" : "OFF";

            builder.AppendLine("<size=30><b>LIVE SYSTEM DIAGNOSTICS</b></size>");
            builder.AppendLine($"<size=19>PRIMARY  {Escape(recorder.PrimaryVariantLabel)}</size>");
            builder.AppendLine(XrDeviceStatusText());
            builder.AppendLine(XrFocusStatusText());
            builder.AppendLine($"SIGNALS  OUTPUT {outputStatus} | DISPLAY {displayStatus} | REF {ReferenceStatus()}");
            builder.AppendLine("<size=18>DISPLAY VS PLATFORM CONTROLLER</size>");
            builder.AppendLine($"POSITION DELTA  {PositionDeltaText()}");
            builder.AppendLine($"ROTATION DELTA  {RotationDeltaText()}");
            builder.AppendLine($"OBS AGE  {ObservationAgeText()} | E2E ARRIVAL  {e2eArrival}");
            builder.AppendLine($"SERVER  {serverProcessing} | SMOOTH  {smoothingDelay} | POSE RATE  {poseRate}");

            string latestScore = runtime.LatestAlignedFrameId < 0
                ? "--"
                : runtime.LatestReliabilityScore.ToString("0.00");
            string acceptedScore = float.IsNaN(runtime.LatestAcceptedScore)
                ? "--"
                : runtime.LatestAcceptedScore.ToString("0.00");
            builder.AppendLine($"VCD  LATEST {latestScore} | ACCEPTED {acceptedScore}");
            builder.AppendLine($"CORRECTION  {residualPosition} / {residualRotation}");
            builder.AppendLine($"FRAME STEP  {frameStepPosition} / {frameStepRotation}");
            builder.AppendLine($"ANCHOR  {runtime.CurrentAnchorState} | MOTION  {Escape(runtime.CurrentMotionStateName)}");
            builder.AppendLine($"STATIC LOCK  {staticLock} | FRAME  {FrameText(runtime.LatestAlignedFrameId)}");
            builder.Append("<size=17><color=#B1BCCC>Live diagnostic only; offline paired metrics are authoritative.</color></size>");
            return builder.ToString();
        }

        /// <summary>把最新诊断文本写入 TextMesh Pro。</summary>
        private void RenderText()
        {
            if (statsText != null) statsText.text = BuildStatsText();
        }

        /// <summary>生成平台参考 Transform 的激活/保持状态文本。</summary>
        private string ReferenceStatus()
        {
            if (!_hasReference) return $"<color=#FF7D6A>MISSING</color>";
            string activeState = _referenceActive
                ? "<color=#4DD6A6>ACTIVE</color>"
                : "<color=#FFD054>HELD</color>";
            string preflight = recorder != null && recorder.PlatformReferencePreflightPassed
                ? "<color=#4DD6A6>VERIFIED</color>"
                : "<color=#FF7D6A>MOVE TO VERIFY</color>";
            return $"{activeState} | CHECK {preflight}";
        }

        /// <summary>生成头显连接和佩戴状态文本。</summary>
        private string XrDeviceStatusText()
        {
            if (!_xrRuntimeActive) return "XR DEVICE  NOT RUNNING";
            return $"XR DEVICE  HMD {Status(_hmdPresent, "PRESENT", "MISSING")} | " +
                $"WORN {Status(_userPresent, "YES", "NO")}";
        }

        /// <summary>生成 VR 和输入 focus 状态文本；黑屏排查优先查看本行。</summary>
        private string XrFocusStatusText()
        {
            if (!_xrRuntimeActive) return "XR FOCUS   NOT RUNNING";
            return $"XR FOCUS   VR {Status(_vrFocus, "ACTIVE", "LOST")} | " +
                $"INPUT {Status(_inputFocus, "ACTIVE", "LOST")}";
        }

        /// <summary>生成带阈值颜色的位置差异文本。</summary>
        private string PositionDeltaText()
        {
            if (double.IsNaN(_latestPositionDeltaM)) return "--";
            double millimeters = _latestPositionDeltaM * 1000.0;
            return $"<color={ThresholdColor(millimeters, positionDeltaGoodMm, positionDeltaBadMm)}>{millimeters:0.0} mm</color>";
        }

        /// <summary>生成带阈值颜色的旋转差异文本。</summary>
        private string RotationDeltaText()
        {
            if (double.IsNaN(_latestRotationDeltaDeg)) return "--";
            return $"<color={ThresholdColor(_latestRotationDeltaDeg, rotationDeltaGoodDeg, rotationDeltaBadDeg)}>{_latestRotationDeltaDeg:0.00} deg</color>";
        }

        /// <summary>生成带阈值颜色的观测年龄文本。</summary>
        private string ObservationAgeText()
        {
            if (double.IsNaN(_latestObservationAgeMs)) return "--";
            return $"<color={ThresholdColor(_latestObservationAgeMs, observationAgeGoodMs, observationAgeBadMs)}>{_latestObservationAgeMs:0} ms</color>";
        }

        /// <summary>生成真假状态文本。</summary>
        private static string Status(bool value, string trueText, string falseText)
            => value
                ? $"<color=#4DD6A6>{trueText}</color>"
                : $"<color=#FF7D6A>{falseText}</color>";

        /// <summary>格式化可选数值；NaN 和 Infinity 显示为占位符。</summary>
        private static string Number(double value, string format, string suffix)
            => double.IsNaN(value) || double.IsInfinity(value)
                ? "--"
                : value.ToString(format) + suffix;

        /// <summary>格式化 frame_id。</summary>
        private static string FrameText(long frameId) => frameId >= 0 ? frameId.ToString() : "--";

        /// <summary>转义可能来自 Inspector 的富文本控制字符。</summary>
        private static string Escape(string value)
            => string.IsNullOrWhiteSpace(value)
                ? "UNNAMED"
                : value.Replace("<", "&lt;").Replace(">", "&gt;");

        /// <summary>低于 good 显示绿，高于 bad 显示红，中间显示黄。</summary>
        private static string ThresholdColor(double value, double good, double bad)
        {
            if (value <= good) return "#4DD6A6";
            if (value >= bad) return "#FF7D6A";
            return "#FFD054";
        }
    }
}
