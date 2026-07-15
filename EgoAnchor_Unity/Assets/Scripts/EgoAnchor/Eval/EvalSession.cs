using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using EgoAnchor.Diagnostics;
using EgoAnchor.Eval.Experiment;
using EgoAnchor.Runtime;
using UnityEngine;
using UnityEngine.Events;

namespace EgoAnchor.Eval
{
    /// <summary>评估 session 的用途；决定正式参数冻结门禁。</summary>
    public enum EvalRunKind
    {
        /// <summary>开发调试。</summary>
        Debug,

        /// <summary>采集链路冒烟。</summary>
        Smoke,

        /// <summary>仅用于冻结正式参数的开发采集。</summary>
        Calibration,

        /// <summary>论文正式采集；使用场景内固定配置和自动元数据。</summary>
        Formal,
    }

    /// <summary>
    /// 评估 session 控制器：管理录制开始/停止，自动从 Python session_id 命名目录，写 schema-v2 manifest.json。
    /// <para>
    /// 推荐工作流：先启动 Python 服务，<see cref="autoStart"/> 为 true 时 Unity 收到第一个 PoseResult
    /// 即自动开始录制；完成任意任务子集并经操作者确认后调用 <see cref="StopSession"/>。
    /// </para>
    /// </summary>
    public sealed class EvalSession : MonoBehaviour
    {
        /// <summary>当前单操作员采集使用的匿名标识，不要求现场填写。</summary>
        private const string OperatorId = "single_operator";

        /// <summary>当前跨端协议版本。</summary>
        private const string ProtocolVersion = "v1";

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

        /// <summary>本次 session 用途。</summary>
        [Tooltip("Session 用途。正式 Experiment12 场景固定为 Formal，开发场景保持 Debug。")]
        [SerializeField] private EvalRunKind runKind = EvalRunKind.Debug;

        /// <summary>收到第一个 PoseResult 时是否自动开始录制。</summary>
        [Tooltip("收到第一个 PoseResult 时自动开始录制；完成本次需要的任意任务子集后由操作者确认停止。")]
        [SerializeField] private bool autoStart = true;

        // ── Events ──

        /// <summary>录制开始时触发；用于重置九任务状态或写入会话边界事件。</summary>
        [Header("Session Events")]
        [Tooltip("录制自动开始时触发。")]
        [SerializeField] private UnityEvent sessionStarted = new UnityEvent();

        /// <summary>录制停止时触发；用于清理实验上下文或写入会话边界事件。</summary>
        [Tooltip("操作者确认完成全部任务或组件销毁时触发。")]
        [SerializeField] private UnityEvent sessionStopped = new UnityEvent();

        // ── State ──

        private string _sessionId;
        private string _sessionDir;
        private bool _recording;
        private bool _autoStarted;
        private double _createdUnixMs;
        private double _nextAutoStartAttemptMonoMs;

        private readonly List<string> _variantLabels = new List<string>();
        private readonly List<EvalVariantConfig> _variantConfigs = new List<EvalVariantConfig>();

        /// <summary>停止录制前冻结的已完成任务摘要。</summary>
        private readonly List<CompletedExperimentTask> _completedTasks = new List<CompletedExperimentTask>();

        // ── Public API ──

        /// <summary>当前 session id。</summary>
        public string SessionId => _sessionId;

        /// <summary>当前 session 输出目录。</summary>
        public string SessionDir => _sessionDir;

        /// <summary>当前是否正在录制。</summary>
        public bool IsRecording => _recording;

        /// <summary>录制开始事件；供固定计划和会话边界回调订阅。</summary>
        public UnityEvent SessionStarted => sessionStarted;

        /// <summary>录制停止事件；供会话边界回调订阅。</summary>
        public UnityEvent SessionStopped => sessionStopped;

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

            if (_recording)
            {
                EgoAnchorLog.For<EvalSession>().Warning("StartSession 忽略：已有进行中的 session，请先调用 StopSession。数据不会被截断。");
                return;
            }

            if (!ValidateFormalConfiguration())
                return;

            string root = ResolveOutputRoot();

            string pythonId = runtimeHub != null ? runtimeHub.LatestPythonSessionId : string.Empty;
            if (runKind == EvalRunKind.Formal && string.IsNullOrWhiteSpace(pythonId))
            {
                EgoAnchorLog.For<EvalSession>().Error(
                    "Formal session 启动已拒绝：尚未收到 Python session_id，禁止生成无法跨端配对的本地 session。");
                return;
            }
            if (!string.IsNullOrEmpty(pythonId))
            {
                _sessionId  = pythonId;
                _sessionDir = Path.Combine(root, _sessionId);
                Directory.CreateDirectory(_sessionDir);
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
            Directory.CreateDirectory(Path.Combine(_sessionDir, "audit_samples"));

            string referencePath = Path.Combine(_sessionDir, EvalV2Manifest.UnityReferenceFileName);
            string admissionPath = Path.Combine(_sessionDir, EvalV2Manifest.UnityAdmissionFileName);
            string renderPath = Path.Combine(_sessionDir, EvalV2Manifest.UnityRenderFileName);
            string eventsPath = Path.Combine(_sessionDir, EvalV2Manifest.EventsFileName);
            string manifestPath = Path.Combine(_sessionDir, EvalV2Manifest.ManifestFileName);
            if (HasNonEmptyLog(referencePath)
                || HasNonEmptyLog(admissionPath)
                || HasNonEmptyLog(renderPath)
                || HasNonEmptyLog(manifestPath))
            {
                EgoAnchorLog.For<EvalSession>().Error(
                    $"Session 启动已拒绝：目标 Unity 日志已有非空内容，禁止覆盖。session_id={_sessionId}");
                return;
            }

            _createdUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            try
            {
                recorder.BeginRecording(referencePath, admissionPath, renderPath, eventsPath, _sessionId);
            }
            catch (Exception exc)
            {
                EgoAnchorLog.For<EvalSession>().Error($"Session 启动失败，已关闭部分日志：{exc}");
                return;
            }
            _recording = true;
            sessionStarted.Invoke();

            EgoAnchorLog.For<EvalSession>().Info($"Session 开始：{_sessionDir}  object_id={objectId}  platform_reference={recorder.GtTransformName}");
            if (string.IsNullOrEmpty(recorder.GtTransformName))
                EgoAnchorLog.For<EvalSession>().Warning("平台参考 Transform 未绑定，请在 EvalRecorder 中绑定 reference transform。");
        }

        /// <summary>停止当前 session 并写 schema-v2 manifest.json。</summary>
        public void StopSession()
        {
            if (!_recording)
            {
                EgoAnchorLog.For<EvalSession>().Warning("StopSession 忽略：当前没有进行中的 session。");
                return;
            }

            recorder?.CollectCompletedTasks(_completedTasks);
            recorder?.StopRecording();
            _recording = false;
            sessionStopped.Invoke();
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
            double nowMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            if (nowMonoMs < _nextAutoStartAttemptMonoMs) return;
            string pythonId = runtimeHub.LatestPythonSessionId;
            if (!string.IsNullOrEmpty(pythonId))
            {
                EgoAnchorLog.For<EvalSession>().Info($"自动启动录制，Python session_id={pythonId}");
                StartSession();
                _autoStarted = _recording;
                if (!_recording)
                    _nextAutoStartAttemptMonoMs = nowMonoMs + 1000.0;
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

            var metadata = new EvalManifestMetadata(
                _sessionId,
                objectId,
                RunKindName(runKind),
                OperatorId,
                _createdUnixMs,
                ResolveRunMode(),
                string.Empty,
                Application.unityVersion,
                string.Empty,
                string.Empty,
                ProtocolVersion,
                string.Empty,
                objectId,
                string.Empty);
            string json = EvalJson.BuildManifest(
                metadata,
                _variantLabels, _variantConfigs,
                recorder != null ? recorder.ReferenceLogStats : default,
                recorder != null ? recorder.AdmissionLogStats : default,
                recorder != null ? recorder.RenderLogStats : default,
                recorder != null ? recorder.EventsLogStats : default,
                _completedTasks);

            string path = Path.Combine(_sessionDir, EvalV2Manifest.ManifestFileName);
            File.WriteAllText(path, json, new UTF8Encoding(false));
            EgoAnchorLog.For<EvalSession>().Info($"Manifest 已写入：{path}");
        }

        /// <summary>Formal session 只检查自动配置和完整变体矩阵，不要求现场填写审计字段。</summary>
        private bool ValidateFormalConfiguration()
        {
            if (runKind != EvalRunKind.Formal)
                return true;

            var missing = new List<string>();
            if (string.IsNullOrWhiteSpace(objectId)) missing.Add(nameof(objectId));

            string variantError = string.Empty;
            if (recorder == null || !recorder.TryValidateCurrentVariants(out variantError))
                missing.Add(string.IsNullOrWhiteSpace(variantError) ? "variantConfigs" : variantError);
            if (missing.Count == 0)
                return true;

            EgoAnchorLog.For<EvalSession>().Error(
                $"Formal session 启动已拒绝：正式采集配置不完整 {string.Join(", ", missing)}。");
            return false;
        }

        /// <summary>根据当前 Unity 运行环境生成稳定模式标识。</summary>
        private static string ResolveRunMode()
        {
            return Application.isEditor
                ? "editor_link"
                : $"player_{Application.platform.ToString().ToLowerInvariant()}";
        }

        /// <summary>把 Inspector enum 转换为 schema-v2 固定小写值。</summary>
        private static string RunKindName(EvalRunKind value)
        {
            switch (value)
            {
                case EvalRunKind.Smoke: return "smoke";
                case EvalRunKind.Calibration: return "calibration";
                case EvalRunKind.Formal: return "formal";
                default: return "debug";
            }
        }

        /// <summary>检查 Unity 独占日志是否已经包含数据，防止同一 Python session 被再次录制。</summary>
        private static bool HasNonEmptyLog(string path)
        {
            return File.Exists(path) && new FileInfo(path).Length > 0L;
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
