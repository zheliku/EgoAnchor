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

        /// <summary>Python runtime log 文件名；未知时留空，后续 P1 loader 可显式传入。</summary>
        [Tooltip("手动覆盖 Python runtime log 文件名。默认留空；启用自动复用 Python session 时会从 python_session.json 自动填入 manifest。")]
        [SerializeField] private string pythonLogFilename = string.Empty;

        /// <summary>开始录制时是否优先复用 Python 已创建的共享 eval session 目录。</summary>
        [Tooltip("开始录制时是否优先复用 Python 已创建的共享 eval session 目录。通常先运行 Python，再按 F7/Start 录制 Unity。")]
        [SerializeField] private bool reuseLatestPythonSession = true;

        /// <summary>自动复用 Python session 的最大年龄，单位分钟；小于等于 0 表示不限制。</summary>
        [Tooltip("自动复用 Python session 的最大年龄，单位分钟；小于等于 0 表示不限制。")]
        [SerializeField] private double maxPythonSessionAgeMinutes = 180.0;

        /// <summary>Python 写入的 session 元数据文件名。</summary>
        [Tooltip("Python 写入的 session 元数据文件名。Unity 通过它读取 object_id 和 python_log_filename。")]
        [SerializeField] private string pythonSessionMetadataFilename = "python_session.json";

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
            if (reuseLatestPythonSession && TryFindReusablePythonSession(
                outputRootPath,
                objectId,
                maxPythonSessionAgeMinutes,
                pythonSessionMetadataFilename,
                out string reusedSessionId,
                out string reusedSessionDir,
                out string reusedPythonLogFilename))
            {
                sessionId = reusedSessionId;
                sessionDir = reusedSessionDir;
                activePythonLogFilename = reusedPythonLogFilename;
                Directory.CreateDirectory(sessionDir);
                Debug.Log($"[EgoAnchorEval][U3] Reusing Python eval session: {sessionDir}");
            }
            else
            {
                string baseSessionId = BuildReadableSessionId(DateTimeOffset.Now, objectId);
                sessionId = ResolveUniqueSessionId(outputRootPath, baseSessionId);
                sessionDir = Path.Combine(outputRootPath, sessionId);
                Directory.CreateDirectory(sessionDir);
                activePythonLogFilename = pythonLogFilename;
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
                ResolvePythonLogFilenameForManifest(),
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
        /// 查找最新且尚未写入 Unity 日志的 Python eval session 目录。
        /// </summary>
        /// <param name="outputRootPath">共享 eval 根目录。</param>
        /// <param name="expectedObjectId">Unity 当前 objectId；必须与 Python metadata object_id 一致。</param>
        /// <param name="maxAgeMinutes">最大允许年龄，单位分钟；小于等于 0 表示不限制。</param>
        /// <param name="metadataFilename">Python 写入的 metadata 文件名。</param>
        /// <param name="resolvedSessionId">找到的 session id。</param>
        /// <param name="resolvedSessionDir">找到的 session 目录。</param>
        /// <param name="resolvedPythonLogFilename">metadata 中记录的 Python runtime log 文件名。</param>
        /// <returns>找到可复用目录时返回 true。</returns>
        public static bool TryFindReusablePythonSession(
            string outputRootPath,
            string expectedObjectId,
            double maxAgeMinutes,
            string metadataFilename,
            out string resolvedSessionId,
            out string resolvedSessionDir,
            out string resolvedPythonLogFilename)
        {
            resolvedSessionId = string.Empty;
            resolvedSessionDir = string.Empty;
            resolvedPythonLogFilename = string.Empty;

            if (string.IsNullOrWhiteSpace(outputRootPath) || !Directory.Exists(outputRootPath))
            {
                return false;
            }

            string safeMetadataFilename = string.IsNullOrWhiteSpace(metadataFilename)
                ? "python_session.json"
                : Path.GetFileName(metadataFilename);
            string expected = SanitizePathToken(string.IsNullOrWhiteSpace(expectedObjectId) ? "object" : expectedObjectId);
            DateTime nowUtc = DateTime.UtcNow;
            DateTime bestWriteUtc = DateTime.MinValue;

            foreach (string candidateDir in Directory.GetDirectories(outputRootPath))
            {
                string metadataPath = Path.Combine(candidateDir, safeMetadataFilename);
                if (!File.Exists(metadataPath) || HasUnityEvalLogs(candidateDir))
                {
                    continue;
                }

                DateTime writeUtc = File.GetLastWriteTimeUtc(metadataPath);
                if (maxAgeMinutes > 0.0 && nowUtc - writeUtc > TimeSpan.FromMinutes(maxAgeMinutes))
                {
                    continue;
                }

                string json = File.ReadAllText(metadataPath);
                string objectId = ReadJsonStringProperty(json, "object_id");
                string pythonLog = ReadJsonStringProperty(json, "python_log_filename");
                if (string.IsNullOrWhiteSpace(objectId) || string.IsNullOrWhiteSpace(pythonLog))
                {
                    continue;
                }

                string safeObjectId = SanitizePathToken(objectId);
                if (!string.Equals(safeObjectId, expected, StringComparison.Ordinal))
                {
                    continue;
                }

                if (writeUtc <= bestWriteUtc)
                {
                    continue;
                }

                bestWriteUtc = writeUtc;
                resolvedSessionId = Path.GetFileName(candidateDir);
                resolvedSessionDir = candidateDir;
                resolvedPythonLogFilename = Path.GetFileName(pythonLog);
            }

            return !string.IsNullOrEmpty(resolvedSessionDir);
        }

        /// <summary>
        /// 判断 session 目录中是否已经存在 Unity capture/output，存在则不可自动复用。
        /// </summary>
        private static bool HasUnityEvalLogs(string sessionDirectory)
        {
            return Directory.GetFiles(sessionDirectory, "*_unity_capture.jsonl").Length > 0
                || Directory.GetFiles(sessionDirectory, "*_unity_output.jsonl").Length > 0;
        }

        /// <summary>
        /// 从简单 JSON object 中读取字符串属性；用于解析 Python session metadata。
        /// </summary>
        private static string ReadJsonStringProperty(string json, string propertyName)
        {
            if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(propertyName))
            {
                return string.Empty;
            }

            string needle = $"\"{propertyName}\"";
            int nameIndex = json.IndexOf(needle, StringComparison.Ordinal);
            if (nameIndex < 0)
            {
                return string.Empty;
            }

            int colonIndex = json.IndexOf(':', nameIndex + needle.Length);
            if (colonIndex < 0)
            {
                return string.Empty;
            }

            int quoteIndex = json.IndexOf('"', colonIndex + 1);
            if (quoteIndex < 0)
            {
                return string.Empty;
            }

            var builder = new StringBuilder();
            bool escaping = false;
            for (int i = quoteIndex + 1; i < json.Length; i++)
            {
                char c = json[i];
                if (escaping)
                {
                    builder.Append(c);
                    escaping = false;
                    continue;
                }

                if (c == '\\')
                {
                    escaping = true;
                    continue;
                }

                if (c == '"')
                {
                    return builder.ToString();
                }

                builder.Append(c);
            }

            return string.Empty;
        }

        /// <summary>
        /// 返回本次 manifest 应写入的 Python runtime log 文件名。
        /// </summary>
        private string ResolvePythonLogFilenameForManifest()
        {
            return !string.IsNullOrWhiteSpace(activePythonLogFilename)
                ? activePythonLogFilename
                : pythonLogFilename;
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
