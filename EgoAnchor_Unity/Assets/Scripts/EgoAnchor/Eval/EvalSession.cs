using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using EgoAnchor.Diagnostics;
using EgoAnchor.Runtime;
using UnityEngine;

namespace EgoAnchor.Eval
{
    /// <summary>
    /// 评估 session 控制器：管理录制开始/停止，自动从 Python session_id 命名目录，写 session_manifest.json。
    /// <para>
    /// 推荐工作流：先启动 Python 服务，<see cref="autoStart"/> 为 true 时 Unity 收到第一个 PoseResult
    /// 即自动开始录制，无需手动按键；停止时调用 <see cref="StopSession"/> 或 F8。
    /// </para>
    /// </summary>
    public sealed class EvalSession : MonoBehaviour
    {
        // ── References ──

        /// <summary>负责写 JSONL 的记录器。</summary>
        [Header("References")]
        [Tooltip("负责写 JSONL 的 EvalRecorder。")]
        [SerializeField] private EvalRecorder recorder;

        /// <summary>提供 Python session_id 的 runtime 分发中心。</summary>
        [Tooltip("提供 Python session_id 的 AnchorRuntimeHub；Python 会把共享目录名通过 NATS 广播。")]
        [SerializeField] private AnchorRuntimeHub runtimeHub;

        // ── Session Metadata ──

        /// <summary>评估数据根目录；为空时自动推导至 EgoAnchor_Python/data/eval。</summary>
        [Header("Session Metadata")]
        [Tooltip("评估数据根目录，建议填写绝对路径。为空时自动推导。")]
        [SerializeField] private string outputRoot = string.Empty;

        /// <summary>追踪对象 ID，必须与 Python --object 一致，例如 controller_right。</summary>
        [Tooltip("追踪对象 ID，例如 controller_right。必须与 Python --object 参数一致。")]
        [SerializeField] private string objectId = "controller_right";

        /// <summary>Unity 运行模式，写入 manifest，例如 editor_link 或 build_standalone。</summary>
        [Tooltip("Unity 运行模式，写入 manifest，例如 editor_link。真机 build 时手动改写。")]
        [SerializeField] private string runMode = "editor_link";

        /// <summary>收到第一个 PoseResult 时是否自动开始录制。</summary>
        [Tooltip("收到第一个 PoseResult 时自动开始录制；无需手动按 F7。")]
        [SerializeField] private bool autoStart = true;

        /// <summary>实验备注，写入 manifest。</summary>
        [Tooltip("实验备注，例如光照条件、mesh 版本等。")]
        [TextArea]
        [SerializeField] private string notes = string.Empty;

        // ── State ──

        private string _sessionId;
        private string _sessionDir;
        private bool _recording;
        private bool _autoStarted;
        private string _pythonLogFilename;

        private readonly List<string> _variantLabels = new List<string>();
        private readonly List<EvalVariantConfig> _variantConfigs = new List<EvalVariantConfig>();

        // ── Public API ──

        /// <summary>当前 session id。</summary>
        public string SessionId => _sessionId;

        /// <summary>当前 session 输出目录。</summary>
        public string SessionDir => _sessionDir;

        /// <summary>当前是否正在录制。</summary>
        public bool IsRecording => _recording;

        /// <summary>
        /// 启动一个新的评估 session。
        /// 若 Python session_id 已通过 NATS 到达，则复用其命名；否则回退到本地时钟命名。
        /// </summary>
        public void StartSession()
        {
            if (recorder == null)
            {
                EgoAnchorLog.For<EvalSession>().Warning("EvalRecorder 未绑定，session 未启动。");
                return;
            }

            if (_recording) StopSession();

            string root = ResolveOutputRoot();
            _pythonLogFilename = string.Empty;

            string pythonId = runtimeHub != null ? runtimeHub.LatestPythonSessionId : string.Empty;
            if (!string.IsNullOrEmpty(pythonId))
            {
                _sessionId  = pythonId;
                _sessionDir = Path.Combine(root, _sessionId);
                Directory.CreateDirectory(_sessionDir);
                _pythonLogFilename = $"{_sessionId}_python_runtime.jsonl";
                EgoAnchorLog.For<EvalSession>().Info($"复用 Python session_id：{_sessionId}");
            }
            else
            {
                if (autoStart)
                    EgoAnchorLog.For<EvalSession>().Warning("尚未收到 Python session_id，回退到本地时钟。先启动 Python 再录制可自动配对。");
                string baseId = BuildSessionId(DateTimeOffset.UtcNow, objectId);
                _sessionId  = ResolveUniqueId(root, baseId);
                _sessionDir = Path.Combine(root, _sessionId);
                Directory.CreateDirectory(_sessionDir);
            }

            string capturePath = Path.Combine(_sessionDir, $"{_sessionId}_unity_capture.jsonl");
            string outputPath  = Path.Combine(_sessionDir, $"{_sessionId}_unity_output.jsonl");
            recorder.BeginRecording(capturePath, outputPath);
            _recording = true;

            EgoAnchorLog.For<EvalSession>().Info($"Session 开始：{_sessionDir}  object_id={objectId}  gt={recorder.GtTransformName}");
            if (string.IsNullOrEmpty(recorder.GtTransformName))
                EgoAnchorLog.For<EvalSession>().Warning("GT Transform 未绑定，请在 EvalRecorder 中绑定 groundTruth。");
        }

        /// <summary>停止当前 session 并写 session_manifest.json。</summary>
        public void StopSession()
        {
            if (!_recording)
            {
                EgoAnchorLog.For<EvalSession>().Warning("StopSession 忽略：当前没有进行中的 session。");
                return;
            }

            recorder?.StopRecording();
            _recording = false;
            WriteManifest();
            EgoAnchorLog.For<EvalSession>().Info($"Session 结束：{_sessionDir}");
        }

        // ── Unity 生命周期 ──

        private void Start()
        {
            if (autoStart)
                EgoAnchorLog.For<EvalSession>().Info("autoStart=true，收到第一个 PoseResult 时将自动开始录制。");
        }

        private void LateUpdate()
        {
            if (!autoStart || _recording || _autoStarted) return;
            if (runtimeHub == null) return;
            string pythonId = runtimeHub.LatestPythonSessionId;
            if (!string.IsNullOrEmpty(pythonId))
            {
                _autoStarted = true;
                EgoAnchorLog.For<EvalSession>().Info($"自动启动录制，Python session_id={pythonId}");
                StartSession();
            }
        }

        private void OnDestroy()
        {
            if (_recording) StopSession();
        }

        // ── 内部辅助 ──

        private void WriteManifest()
        {
            if (string.IsNullOrEmpty(_sessionDir) || string.IsNullOrEmpty(_sessionId)) return;

            _variantLabels.Clear();
            _variantConfigs.Clear();
            recorder?.CollectVariantLabels(_variantLabels);
            recorder?.CollectVariantConfigs(_variantConfigs);

            string json = EvalJson.BuildManifest(
                _sessionId, objectId, runMode,
                _pythonLogFilename, _variantLabels, _variantConfigs, notes);

            string path = Path.Combine(_sessionDir, "session_manifest.json");
            File.WriteAllText(path, json, new UTF8Encoding(false));
            EgoAnchorLog.For<EvalSession>().Info($"Manifest 已写入：{path}");
        }

        private string ResolveOutputRoot()
        {
            if (!string.IsNullOrWhiteSpace(outputRoot))
            {
                return Path.IsPathRooted(outputRoot)
                    ? outputRoot
                    : Path.GetFullPath(Path.Combine(Application.dataPath, "..", outputRoot));
            }
            // 默认：<repo>/EgoAnchor_Python/data/eval
            return Path.GetFullPath(
                Path.Combine(Application.dataPath, "..", "..", "EgoAnchor_Python", "data", "eval"));
        }

        /// <summary>构建人类可读 session id；时间取北京时间 UTC+8。</summary>
        public static string BuildSessionId(DateTimeOffset time, string objId)
        {
            string safe = SanitizeToken(string.IsNullOrWhiteSpace(objId) ? "object" : objId);
            return $"{time.ToOffset(TimeSpan.FromHours(8)).ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture)}_{safe}";
        }

        private static string ResolveUniqueId(string root, string baseId)
        {
            string id = baseId;
            int n = 2;
            while (Directory.Exists(Path.Combine(root, id)))
                id = $"{baseId}_{n++:00}";
            return id;
        }

        private static string SanitizeToken(string value)
        {
            var sb = new StringBuilder(value.Length);
            foreach (char c in value)
                sb.Append(char.IsLetterOrDigit(c) || c == '_' || c == '-' ? c : '_');
            string t = sb.ToString().Trim('_', '-');
            return string.IsNullOrEmpty(t) ? "object" : t;
        }
    }
}

