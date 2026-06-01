using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;

namespace EgoAnchorEval
{
    /// <summary>
    /// 评估 session 控制器：负责启动/停止录制、切换条件区间、记录事件标记并写 session_manifest.json。
    /// </summary>
    public sealed class EvalSessionController : MonoBehaviour
    {
        /// <summary>写 capture/output JSONL 的 recorder。</summary>
        [Header("References")]
        [Tooltip("写 capture/output JSONL 的 AnchorEvalRecorder。")]
        [SerializeField] private AnchorEvalRecorder recorder;

        /// <summary>手柄 GT provider，用于写 manifest 中的 gt_source 和连续性策略。</summary>
        [Tooltip("手柄 GT provider，用于写 manifest 中的 gt_source、controller 和 hold-last 策略。")]
        [SerializeField] private ControllerGroundTruthProvider gt;

        /// <summary>评估数据根目录；为空时自动指向 EgoAnchor_Python/data/eval。</summary>
        [Header("Session Metadata")]
        [Tooltip("评估数据根目录；推荐填写绝对路径 EgoAnchor_Python/data/eval。为空时自动从 Unity 工程推导。")]
        [SerializeField] private string outputRoot = string.Empty;

        /// <summary>本 session 追踪对象 ID，必须与 Python --object 和 GT 手柄一致。</summary>
        [Tooltip("本 session 追踪对象 ID，例如 controller_right 或 controller_left。必须与 Python --object 和 GT provider 的 controller 一致。")]
        [SerializeField] private string objectId = "controller_right";

        /// <summary>Unity 运行模式，默认 Editor + Quest Link。</summary>
        [Tooltip("Unity 运行模式，默认 editor_link。真机 build 或其它模式时手动改写。")]
        [SerializeField] private string unityRunMode = "editor_link";

        /// <summary>Python runtime log 文件名；未知时留空，后续 P1 loader 可显式传入。</summary>
        [Tooltip("Python runtime log 文件名；未知时留空，后续分析 CLI 可显式传入 --python-log。")]
        [SerializeField] private string pythonLogFilename = string.Empty;

        /// <summary>本轮实验备注。</summary>
        [Tooltip("本轮实验备注，例如 lighting、mesh、Python 配置或异常情况。")]
        [TextArea]
        [SerializeField] private string notes = string.Empty;

        /// <summary>当前 session id。</summary>
        private string sessionId = string.Empty;

        /// <summary>当前 session 目录。</summary>
        private string sessionDir = string.Empty;

        /// <summary>Unity 单调时钟到 Unix 毫秒的近似偏移。</summary>
        private double monoToUnixOffsetMs;

        /// <summary>session 启动时 Unity 单调毫秒。</summary>
        private double sessionStartMonoMs;

        /// <summary>session 停止时 Unity 单调毫秒。</summary>
        private double sessionStopMonoMs;

        /// <summary>已关闭的条件区间列表。</summary>
        private readonly List<EvalConditionSpan> spans = new List<EvalConditionSpan>();

        /// <summary>瞬时事件标记列表。</summary>
        private readonly List<EvalEventMarker> markers = new List<EvalEventMarker>();

        /// <summary>manifest 写入时复用的变体标签列表。</summary>
        private readonly List<string> variantLabels = new List<string>();

        /// <summary>是否存在打开中的条件区间。</summary>
        private bool hasOpenSpan;

        /// <summary>打开中条件区间的标签。</summary>
        private string openSpanLabel = string.Empty;

        /// <summary>打开中条件区间的开始时间。</summary>
        private double openSpanStartMonoMs;

        /// <summary>当前是否正在录制。</summary>
        private bool recording;

        /// <summary>当前 session id。</summary>
        public string SessionId => sessionId;

        /// <summary>当前 session 输出目录。</summary>
        public string SessionDir => sessionDir;

        /// <summary>当前是否正在录制。</summary>
        public bool IsRecording => recording;

        /// <summary>
        /// 启动一个新的评估 session，并开始写 capture/output JSONL。
        /// </summary>
        public void StartSession()
        {
            if (recorder == null)
            {
                Debug.LogWarning("[EgoAnchorEval][U3] Missing AnchorEvalRecorder; session not started.");
                return;
            }

            if (recording)
            {
                StopSession();
            }

            string outputRootPath = ResolveOutputRoot();
            string baseSessionId = BuildReadableSessionId(DateTimeOffset.Now, objectId);
            sessionId = ResolveUniqueSessionId(outputRootPath, baseSessionId);
            sessionDir = Path.Combine(outputRootPath, sessionId);
            Directory.CreateDirectory(sessionDir);
            spans.Clear();
            markers.Clear();
            variantLabels.Clear();
            hasOpenSpan = false;
            openSpanLabel = string.Empty;
            openSpanStartMonoMs = 0.0;

            sessionStartMonoMs = NowMonoMs();
            sessionStopMonoMs = sessionStartMonoMs;
            monoToUnixOffsetMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - sessionStartMonoMs;

            string capturePath = Path.Combine(sessionDir, $"{sessionId}_unity_capture.jsonl");
            string outputPath = Path.Combine(sessionDir, $"{sessionId}_unity_output.jsonl");
            recorder.BeginRecording(capturePath, outputPath);
            recording = true;

            LogSessionConsistency();
            Debug.Log($"[EgoAnchorEval][U3] Session started: {sessionDir}");
        }

        /// <summary>
        /// 停止当前评估 session，关闭打开中的条件区间并写 session_manifest.json。
        /// </summary>
        public void StopSession()
        {
            if (!recording)
            {
                Debug.LogWarning("[EgoAnchorEval][U3] StopSession ignored because no session is recording.");
                return;
            }

            EndCondition();
            sessionStopMonoMs = NowMonoMs();
            recorder?.StopRecording();
            recording = false;
            WriteManifest();
            Debug.Log($"[EgoAnchorEval][U3] Session stopped: {sessionDir}");
        }

        /// <summary>
        /// 打开一个新的条件区间；若已有区间，会先自动关闭旧区间。
        /// </summary>
        /// <param name="label">条件标签，例如 static、slow_head 或 occlusion。</param>
        public void BeginCondition(string label)
        {
            if (!recording)
            {
                Debug.LogWarning($"[EgoAnchorEval][U3] BeginCondition({label}) ignored because no session is recording.");
                return;
            }

            EndCondition();
            openSpanLabel = string.IsNullOrWhiteSpace(label) ? "unnamed" : label.Trim();
            openSpanStartMonoMs = NowMonoMs();
            hasOpenSpan = true;
            Debug.Log($"[EgoAnchorEval][U3] Condition started: {openSpanLabel}");
        }

        /// <summary>
        /// 关闭当前条件区间。
        /// </summary>
        public void EndCondition()
        {
            if (!hasOpenSpan)
            {
                return;
            }

            double endMonoMs = NowMonoMs();
            spans.Add(new EvalConditionSpan(openSpanLabel, openSpanStartMonoMs, endMonoMs));
            Debug.Log($"[EgoAnchorEval][U3] Condition ended: {openSpanLabel}");
            hasOpenSpan = false;
            openSpanLabel = string.Empty;
            openSpanStartMonoMs = 0.0;
        }

        /// <summary>
        /// 记录一个瞬时事件 marker。
        /// </summary>
        /// <param name="type">事件类型，例如 occlusion、out_of_view 或 recovery。</param>
        public void Mark(string type)
        {
            if (!recording)
            {
                Debug.LogWarning($"[EgoAnchorEval][U3] Mark({type}) ignored because no session is recording.");
                return;
            }

            string markerType = string.IsNullOrWhiteSpace(type) ? "unnamed" : type.Trim();
            markers.Add(new EvalEventMarker(markerType, NowMonoMs()));
            Debug.Log($"[EgoAnchorEval][U3] Event marked: {markerType}");
        }

        /// <summary>开始 static 条件段。</summary>
        public void BeginStaticCondition() => BeginCondition("static");

        /// <summary>开始 slow_head 条件段。</summary>
        public void BeginSlowHeadCondition() => BeginCondition("slow_head");

        /// <summary>开始 fast_head 条件段。</summary>
        public void BeginFastHeadCondition() => BeginCondition("fast_head");

        /// <summary>开始 object_motion 条件段。</summary>
        public void BeginObjectMotionCondition() => BeginCondition("object_motion");

        /// <summary>开始 occlusion 条件段。</summary>
        public void BeginOcclusionCondition() => BeginCondition("occlusion");

        /// <summary>开始 out_of_view 条件段。</summary>
        public void BeginOutOfViewCondition() => BeginCondition("out_of_view");

        /// <summary>开始 lighting 条件段。</summary>
        public void BeginLightingCondition() => BeginCondition("lighting");

        /// <summary>记录 occlusion 事件。</summary>
        public void MarkOcclusion() => Mark("occlusion");

        /// <summary>记录 out_of_view 事件。</summary>
        public void MarkOutOfView() => Mark("out_of_view");

        /// <summary>记录 recovery 事件。</summary>
        public void MarkRecovery() => Mark("recovery");

        /// <summary>
        /// 构造人类可读的 session id，格式为 yyyyMMdd_HHmmss_objectId。
        /// </summary>
        public static string BuildReadableSessionId(DateTimeOffset localTime, string sessionObjectId)
        {
            string safeObjectId = SanitizePathToken(string.IsNullOrWhiteSpace(sessionObjectId) ? "object" : sessionObjectId);
            return $"{localTime.ToLocalTime().ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture)}_{safeObjectId}";
        }

        /// <summary>
        /// 组件销毁时尽量完整收尾，避免 Play Mode 停止时丢 manifest。
        /// </summary>
        private void OnDestroy()
        {
            if (recording)
            {
                StopSession();
            }
        }

        /// <summary>
        /// 写 session_manifest.json。
        /// </summary>
        private void WriteManifest()
        {
            if (string.IsNullOrEmpty(sessionDir) || string.IsNullOrEmpty(sessionId))
            {
                return;
            }

            variantLabels.Clear();
            recorder?.CollectVariantLabels(variantLabels);
            string manifest = EvalSessionManifestJson.BuildManifest(
                sessionId,
                objectId,
                unityRunMode,
                ResolveGtSource(),
                gt != null ? gt.Controller.ToString() : string.Empty,
                monoToUnixOffsetMs,
                sessionStartMonoMs,
                sessionStopMonoMs,
                spans,
                markers,
                variantLabels,
                pythonLogFilename,
                notes,
                gt != null ? gt.HoldPolicyName : "missing_gt_provider",
                gt != null && gt.HoldLastPoseWhenUntracked,
                gt != null ? gt.MaxHoldAgeMs : 0.0);
            string manifestPath = Path.Combine(sessionDir, "session_manifest.json");
            File.WriteAllText(manifestPath, manifest, new UTF8Encoding(false));
            Debug.Log($"[EgoAnchorEval][U3] Manifest written: {manifestPath}");
        }

        /// <summary>
        /// 解析输出根目录。
        /// </summary>
        private string ResolveOutputRoot()
        {
            if (!string.IsNullOrWhiteSpace(outputRoot))
            {
                return Path.IsPathRooted(outputRoot)
                    ? outputRoot
                    : Path.GetFullPath(Path.Combine(Application.dataPath, "..", outputRoot));
            }

            return Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "EgoAnchor_Python", "data", "eval"));
        }

        /// <summary>
        /// 若同秒已存在同名 session，则追加 _02/_03 等后缀。
        /// </summary>
        private static string ResolveUniqueSessionId(string outputRootPath, string baseSessionId)
        {
            string candidate = baseSessionId;
            int suffix = 2;
            while (Directory.Exists(Path.Combine(outputRootPath, candidate)))
            {
                candidate = $"{baseSessionId}_{suffix.ToString("00", CultureInfo.InvariantCulture)}";
                suffix++;
            }

            return candidate;
        }

        /// <summary>
        /// 把 objectId 变成可用于目录名的短 token。
        /// </summary>
        private static string SanitizePathToken(string value)
        {
            var builder = new StringBuilder(value.Length);
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                if (char.IsLetterOrDigit(c) || c == '_' || c == '-')
                {
                    builder.Append(c);
                }
                else
                {
                    builder.Append('_');
                }
            }

            string token = builder.ToString().Trim('_', '-');
            return string.IsNullOrEmpty(token) ? "object" : token;
        }

        /// <summary>
        /// 解析 manifest 中的 gt_source。
        /// </summary>
        private string ResolveGtSource()
        {
            if (gt != null)
            {
                return gt.ManifestGtSource;
            }

            string lowerObject = objectId == null ? string.Empty : objectId.ToLowerInvariant();
            if (lowerObject.Contains("left"))
            {
                return "ovr_ltouch";
            }

            if (lowerObject.Contains("right"))
            {
                return "ovr_rtouch";
            }

            return string.Empty;
        }

        /// <summary>
        /// 启动时打印 objectId / gt_source / controller，便于人工核对 Python --object。
        /// </summary>
        private void LogSessionConsistency()
        {
            string gtSource = ResolveGtSource();
            string controllerName = gt != null ? gt.Controller.ToString() : "MissingProvider";
            Debug.Log($"[EgoAnchorEval][U3] object_id={objectId} gt_source={gtSource} controller={controllerName} python_object_should_match={objectId}");

            string lowerObject = objectId == null ? string.Empty : objectId.ToLowerInvariant();
            bool objectIsLeft = lowerObject.Contains("left");
            bool objectIsRight = lowerObject.Contains("right");
            bool gtIsLeft = string.Equals(gtSource, "ovr_ltouch", StringComparison.OrdinalIgnoreCase);
            bool gtIsRight = string.Equals(gtSource, "ovr_rtouch", StringComparison.OrdinalIgnoreCase);
            if ((objectIsLeft && !gtIsLeft) || (objectIsRight && !gtIsRight))
            {
                Debug.LogWarning("[EgoAnchorEval][U3] objectId and GT controller look inconsistent; check Python --object, provider.controller, and manifest gt_source.");
            }
        }

        /// <summary>
        /// 当前 Unity 单调时间，单位毫秒。
        /// </summary>
        private static double NowMonoMs()
        {
            return Time.realtimeSinceStartupAsDouble * 1000.0;
        }
    }
}
