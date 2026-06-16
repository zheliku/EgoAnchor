using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using EgoAnchor.Runtime;
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

        /// <summary>提供 Python 端 session_id 的 anchor runtime 分发中心。</summary>
        [Tooltip("提供 Python 端 session_id 的 AnchorRuntimeHub。应与 PoseResultReceiver 使用同一个实例；Python 会把共享 eval 目录名写进每条 PoseResult 头部。")]
        [SerializeField] private AnchorRuntimeHub runtimeHub;

        /// <summary>评估数据根目录；为空时自动指向 EgoAnchor_Python/data/eval。</summary>
        [Header("Session Metadata")]
        [Tooltip("评估数据根目录；推荐填写绝对路径 EgoAnchor_Python/data/eval。为空时自动从 Unity 工程推导。")]
        [SerializeField] private string outputRoot = string.Empty;

        /// <summary>本 session 追踪对象 ID，必须与 Python --object 一致。</summary>
        [Tooltip("本 session 追踪对象 ID，例如 controller_right 或 controller_left。必须与 Python --object 一致。")]
        [SerializeField] private string objectId = "controller_right";

        /// <summary>Unity 运行模式，默认 Editor + Quest Link。</summary>
        [Tooltip("Unity 运行模式，默认 editor_link。真机 build 或其它模式时手动改写。")]
        [SerializeField] private string unityRunMode = "editor_link";

        /// <summary>开始录制时是否复用 Python 经 NATS 广播的 session_id 命名目录。</summary>
        [Tooltip("开始录制时是否用 Python 经 NATS 广播的 session_id 命名本地目录，实现跨机器配对。通常先启动 Python、等 pose 流起来再按 F7/Start 录制 Unity。")]
        [SerializeField] private bool reusePythonSessionId = true;

        /// <summary>本轮实验备注。</summary>
        [Tooltip("本轮实验备注，例如 lighting、mesh、Python 配置或异常情况。")]
        [InspectorName("实验备注")]
        [TextArea]
        [SerializeField] private string sessionNotes = string.Empty;

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

        /// <summary>manifest 写入时复用的变体配置列表。</summary>
        private readonly List<EvalVariantConfig> variantConfigs = new List<EvalVariantConfig>();

        /// <summary>是否存在打开中的条件区间。</summary>
        private bool hasOpenSpan;

        /// <summary>打开中条件区间的标签。</summary>
        private string openSpanLabel = string.Empty;

        /// <summary>打开中条件区间的开始时间。</summary>
        private double openSpanStartMonoMs;

        /// <summary>当前是否正在录制。</summary>
        private bool recording;

        /// <summary>本次录制实际写入 manifest 的 Python runtime log 文件名。</summary>
        private string activePythonLogFilename = string.Empty;

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
            activePythonLogFilename = string.Empty;
            string pythonSessionId = reusePythonSessionId && runtimeHub != null
                ? runtimeHub.LatestPythonSessionId
                : string.Empty;
            if (!string.IsNullOrEmpty(pythonSessionId))
            {
                sessionId = pythonSessionId;
                sessionDir = Path.Combine(outputRootPath, sessionId);
                Directory.CreateDirectory(sessionDir);
                // Python eval session 默认把 runtime JSONL 写为 <session_id>_python_runtime.jsonl，
                // 事后从服务器 scp 到本地同名目录即与 Unity 日志自动合并。
                activePythonLogFilename = $"{sessionId}_python_runtime.jsonl";
                Debug.Log($"[EgoAnchorEval][U3] Pairing with Python session via NATS: {sessionDir}");
            }
            else
            {
                if (reusePythonSessionId)
                {
                    Debug.LogWarning("[EgoAnchorEval][U3] No Python session_id received over NATS yet; falling back to local clock. 先启动 Python 并等 pose 流起来再开始录制，否则两端目录无法配对。");
                }

                string baseSessionId = BuildReadableSessionId(DateTimeOffset.UtcNow, objectId);
                sessionId = ResolveUniqueSessionId(outputRootPath, baseSessionId);
                sessionDir = Path.Combine(outputRootPath, sessionId);
                Directory.CreateDirectory(sessionDir);
            }
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

        /// <summary>项目统一可读时区：北京时间 (UTC+8)，与运行机器系统时区无关。</summary>
        private static readonly TimeSpan BeijingOffset = TimeSpan.FromHours(8);

        /// <summary>
        /// 构造人类可读的 session id，格式为 yyyyMMdd_HHmmss_objectId，时间为北京时间 (UTC+8)。
        /// </summary>
        public static string BuildReadableSessionId(DateTimeOffset time, string sessionObjectId)
        {
            string safeObjectId = SanitizePathToken(string.IsNullOrWhiteSpace(sessionObjectId) ? "object" : sessionObjectId);
            return $"{time.ToOffset(BeijingOffset).ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture)}_{safeObjectId}";
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
            variantConfigs.Clear();
            recorder?.CollectVariantConfigs(variantConfigs);
            string manifest = EvalSessionManifestJson.BuildManifest(
                sessionId,
                objectId,
                unityRunMode,
                ResolveGtSource(),
                recorder != null ? recorder.ManifestGtTransform : string.Empty,
                monoToUnixOffsetMs,
                sessionStartMonoMs,
                sessionStopMonoMs,
                spans,
                markers,
                variantLabels,
                variantConfigs,
                activePythonLogFilename,
                sessionNotes);
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
            if (recorder != null)
            {
                return recorder.ManifestGtSource;
            }

            return "transform_missing";
        }

        /// <summary>
        /// 启动时打印 objectId / gt_source / GT Transform，便于人工核对 Python --object 和场景绑定。
        /// </summary>
        private void LogSessionConsistency()
        {
            string gtSource = ResolveGtSource();
            string gtTransformName = recorder != null && !string.IsNullOrEmpty(recorder.ManifestGtTransform)
                ? recorder.ManifestGtTransform
                : "MissingTransform";
            Debug.Log($"[EgoAnchorEval][U3] object_id={objectId} gt_source={gtSource} gt_transform={gtTransformName} python_object_should_match={objectId}");

            if (recorder == null || string.IsNullOrEmpty(recorder.ManifestGtTransform))
            {
                Debug.LogWarning("[EgoAnchorEval][U3] Missing GT Transform; bind AnchorEvalRecorder.groundTruthTransform to OVRControllerPrefab before recording.");
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
