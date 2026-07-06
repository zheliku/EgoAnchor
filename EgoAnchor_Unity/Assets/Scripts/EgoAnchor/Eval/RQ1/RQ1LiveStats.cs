using System.Text;
using EgoAnchor.Alignment;
using EgoAnchor.Runtime;
using TMPro;
using UnityEngine;

namespace EgoAnchor.Eval.RQ1
{
    /// <summary>
    /// RQ1 实时性遥测面板。
    /// <para>
    /// 与 <see cref="RQ1StatusUI"/>（录制/标注状态）解耦，本组件只关心「数据实时性好坏」：
    /// 每渲染帧显示端到端时延、pose 更新率、锚定误差、抖动、可靠性分数与锚定状态。
    /// </para>
    /// <para>
    /// 唯一引用是 <see cref="EvalRecorder"/>：主变体 runtime、显示用 anchor Transform、
    /// frame 缓存和 GT pose 都从 recorder 取，保证实时数字与录进 JSONL 的数据完全同源
    /// （同一主变体、同一 GT keep-alive 逻辑、同一时延时钟）。本组件不改状态、不写文件。
    /// </para>
    /// <para>
    /// 所有指标都直接显示每帧采样的瞬时值，不做平滑，保证屏幕上的数字与同一时刻录进
    /// JSONL 的数据一致；渲染按 <see cref="updateRate"/> 节流，避免刷字太快看不清。
    /// </para>
    /// <para>
    /// 时延语义与离线指标一致：<c>now - 该 frame_id 采集时刻的 SenderMonoMs</c>，两端都是
    /// Unity 单调时钟（<see cref="Time.realtimeSinceStartupAsDouble"/>），无跨机时钟偏差。
    /// 锚定误差公式与 Python 离线 pose_error 一致（平移欧氏距离 + 四元数夹角）。
    /// </para>
    /// </summary>
    public sealed class RQ1LiveStats : MonoBehaviour
    {
        // ── References ──

        [Header("References")]
        [Tooltip("评估记录器；主变体 runtime / anchor Transform / frame 缓存 / GT pose 都从它取，与录制同源。")]
        [SerializeField] private EvalRecorder recorder;

        [Tooltip("实时性遥测文本。")]
        [SerializeField] private TextMeshProUGUI statsText;

        // ── Settings ──

        [Header("Settings")]
        [Tooltip("UI 刷新频率（Hz）。数值仍是每帧采样的瞬时值，此项只控制文本重绘节流。")]
        [Min(1f)]
        [SerializeField] private float updateRate = 10f;

        [Header("Latency Thresholds (ms)")]
        [Tooltip("时延低于此值显示绿色（良好）。")]
        [SerializeField] private float latencyGoodMs = 120f;

        [Tooltip("时延高于此值显示红色（差）；介于两者之间显示黄色。")]
        [SerializeField] private float latencyBadMs = 200f;

        [Header("Error Thresholds (vs GT)")]
        [Tooltip("平移误差低于此值显示绿色（良好），单位毫米。")]
        [SerializeField] private float transErrGoodMm = 10f;

        [Tooltip("平移误差高于此值显示红色（差），单位毫米；介于两者之间显示黄色。")]
        [SerializeField] private float transErrBadMm = 20f;

        [Tooltip("旋转误差低于此值显示绿色（良好），单位度。")]
        [SerializeField] private float rotErrGoodDeg = 5f;

        [Tooltip("旋转误差高于此值显示红色（差），单位度；介于两者之间显示黄色。")]
        [SerializeField] private float rotErrBadDeg = 20f;

        // ── State ──

        private float _updateTimer;

        /// <summary>上次观测到 LatestAlignedFrameId 变化的时刻（毫秒），用于估 pose 更新率。</summary>
        private long _lastSeenFrameId = long.MinValue;
        private double _lastFrameChangeMonoMs = -1.0;

        /// <summary>最新一帧的端到端时延（毫秒）；无有效数据时为 NaN。</summary>
        private double _latestLatencyMs = double.NaN;

        /// <summary>最新观测的 pose 更新率（Hz）；无有效数据时为 NaN。</summary>
        private double _latestPoseHz = double.NaN;

        /// <summary>最新一帧的锚定平移误差（米）；无 GT 或无输出时为 NaN。</summary>
        private double _latestTransErrM = double.NaN;

        /// <summary>最新一帧的锚定旋转误差（度）；无 GT 或无输出时为 NaN。</summary>
        private double _latestRotErrDeg = double.NaN;

        /// <summary>上一帧 anchor pose，用于估计位置/旋转抖动。</summary>
        private Vector3 _lastAnchorPos;
        private Quaternion _lastAnchorRot;
        private bool _hasLastAnchorPos;

        /// <summary>最新一帧的位置抖动（米，帧间位移幅度）；无数据时为 NaN。</summary>
        private double _latestJitterM = double.NaN;

        /// <summary>最新一帧的旋转抖动（度，帧间旋转幅度）；无数据时为 NaN。</summary>
        private double _latestJitterDeg = double.NaN;

        // ── Public API（供其它诊断/测试读取，不写文件） ──

        /// <summary>最新一帧的端到端时延（毫秒）；无数据为 NaN。</summary>
        public double LatestLatencyMs => _latestLatencyMs;

        /// <summary>最新观测的 pose 更新率（Hz）；无数据为 NaN。</summary>
        public double LatestPoseHz => _latestPoseHz;

        /// <summary>最新一帧的平移误差（米）；无数据为 NaN。</summary>
        public double LatestTranslationErrorM => _latestTransErrM;

        /// <summary>最新一帧的旋转误差（度）；无数据为 NaN。</summary>
        public double LatestRotationErrorDeg => _latestRotErrDeg;

        /// <summary>最新一帧的位置抖动（米）；无数据为 NaN。</summary>
        public double LatestJitterM => _latestJitterM;

        /// <summary>最新一帧的旋转抖动（度）；无数据为 NaN。</summary>
        public double LatestJitterDeg => _latestJitterDeg;

        // ── Unity 生命周期 ──

        private void Update()
        {
            SampleLiveSignals();

            _updateTimer += Time.deltaTime;
            if (_updateTimer >= 1f / Mathf.Max(1f, updateRate))
            {
                _updateTimer = 0f;
                RenderText();
            }
        }

        // ── 采样与估计 ──

        /// <summary>
        /// 每帧采样：pose 更新率、端到端时延、锚定误差、位置抖动，全部从 recorder 同源取瞬时值。
        /// </summary>
        private void SampleLiveSignals()
        {
            if (recorder == null)
            {
                return;
            }

            PoseToAnchorRuntime runtime = recorder.PrimaryRuntime;
            if (runtime == null)
            {
                return;
            }

            double nowMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            long frameId = runtime.LatestAlignedFrameId;

            // pose 更新率：LatestAlignedFrameId 发生变化即视为收到一条新的有效 pose
            if (frameId >= 0 && frameId != _lastSeenFrameId)
            {
                if (_lastFrameChangeMonoMs >= 0.0)
                {
                    double intervalMs = nowMs - _lastFrameChangeMonoMs;
                    if (intervalMs > 1e-3)
                    {
                        _latestPoseHz = 1000.0 / intervalMs;
                    }
                }
                _lastFrameChangeMonoMs = nowMs;
                _lastSeenFrameId = frameId;
            }

            // 端到端时延：now - 该 frame_id 采集时刻 SenderMonoMs（同一 Unity 单调时钟）
            FramePoseHistory history = recorder.FrameHistory;
            if (frameId >= 0 && history != null
                && history.TryGet(frameId, out FramePoseRecord record))
            {
                double latencyMs = nowMs - record.SenderMonoMs;
                if (latencyMs >= 0.0)
                {
                    _latestLatencyMs = latencyMs;
                }
            }

            // 锚定误差与抖动都基于主变体显示用 anchor Transform（与录制 output_pos 同源）。
            Transform anchor = recorder.PrimaryAnchorTransform;
            if (anchor == null)
            {
                return;
            }

            // 锚定误差 vs GT：面板用 live GT（直读 Transform，不受 OVR tracked 门控），
            // 只要手柄在动就更新；公式与 Python pose_error 一致（平移欧氏距离 + 四元数夹角）。
            if (recorder.TryGetLiveGtPose(out Pose gtPose))
            {
                _latestTransErrM = (anchor.position - gtPose.position).magnitude;
                _latestRotErrDeg = Quaternion.Angle(anchor.rotation, gtPose.rotation);
            }

            // 位置/旋转抖动：相邻帧 anchor 位移与旋转幅度（不依赖 GT，反映输出平滑度）。
            if (_hasLastAnchorPos)
            {
                _latestJitterM = (anchor.position - _lastAnchorPos).magnitude;
                _latestJitterDeg = Quaternion.Angle(anchor.rotation, _lastAnchorRot);
            }
            _lastAnchorPos = anchor.position;
            _lastAnchorRot = anchor.rotation;
            _hasLastAnchorPos = true;
        }

        // ── 渲染 ──

        private void RenderText()
        {
            if (statsText == null)
            {
                return;
            }

            PoseToAnchorRuntime runtime = recorder != null ? recorder.PrimaryRuntime : null;
            if (runtime == null)
            {
                statsText.text = "Live Stats: no runtime";
                return;
            }

            var sb = new StringBuilder();

            // 时延（带颜色阈值，一眼看好坏）
            sb.AppendLine(double.IsNaN(_latestLatencyMs)
                ? "Latency: --"
                : $"Latency: <color={LatencyColor(_latestLatencyMs)}>{_latestLatencyMs:0} ms</color>");

            // pose 更新率
            sb.AppendLine(double.IsNaN(_latestPoseHz)
                ? "Pose rate: --"
                : $"Pose rate: {_latestPoseHz:0.0} Hz");

            // 锚定误差 vs GT（平移带颜色阈值）
            sb.AppendLine(double.IsNaN(_latestTransErrM)
                ? "Trans err: --"
                : $"Trans err: <color={TransErrColor(_latestTransErrM * 1000.0)}>{_latestTransErrM * 1000.0:0} mm</color>");
            sb.AppendLine(double.IsNaN(_latestRotErrDeg)
                ? "Rot err: --"
                : $"Rot err: <color={RotErrColor(_latestRotErrDeg)}>{_latestRotErrDeg:0.0}°</color>");

            // 抖动（帧间位移/旋转，越小越稳）
            string jitterPos = double.IsNaN(_latestJitterM) ? "--" : $"{_latestJitterM * 1000.0:0.0} mm";
            string jitterRot = double.IsNaN(_latestJitterDeg) ? "--" : $"{_latestJitterDeg:0.00}°";
            sb.AppendLine($"Jitter: {jitterPos} / {jitterRot}");

            // 可靠性分数（policy 接受分优先，回退到原始可靠性分）
            float accepted = runtime.LatestAcceptedScore;
            float score = float.IsNaN(accepted) ? runtime.LatestReliabilityScore : accepted;
            sb.AppendLine($"Score: {score:0.00}");

            // 锚定状态 + 静止锁定
            sb.Append($"State: {runtime.CurrentAnchorState}");
            if (runtime.LatestStaticLocked)
            {
                sb.Append("  <color=#7FDBFF>[LOCKED]</color>");
            }

            statsText.text = sb.ToString();
        }

        /// <summary>按阈值把时延映射到 绿/黄/红。</summary>
        private string LatencyColor(double latencyMs)
            => ThresholdColor(latencyMs, latencyGoodMs, latencyBadMs);

        /// <summary>按阈值把平移误差（毫米）映射到 绿/黄/红。</summary>
        private string TransErrColor(double errMm)
            => ThresholdColor(errMm, transErrGoodMm, transErrBadMm);

        /// <summary>按阈值把旋转误差（度）映射到 绿/黄/红。</summary>
        private string RotErrColor(double errDeg)
            => ThresholdColor(errDeg, rotErrGoodDeg, rotErrBadDeg);

        /// <summary>低于 good 绿、高于 bad 红、之间黄。</summary>
        private static string ThresholdColor(double value, double good, double bad)
        {
            if (value <= good) return "#3AD16B";  // 绿：良好
            if (value >= bad) return "#E74C3C";    // 红：差
            return "#F1C40F";                       // 黄：一般
        }
    }
}
