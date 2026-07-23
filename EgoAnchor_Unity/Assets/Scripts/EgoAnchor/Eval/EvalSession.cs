using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using EgoAnchor.Diagnostics;
using EgoAnchor.Eval.Experiment;
using EgoAnchor.Runtime;
using UnityEngine;
using UnityEngine.Events;

namespace EgoAnchor.Eval
{
    /// <summary>
    /// 评估 session 控制器：管理录制开始/停止，自动从 Python session_id 命名目录，写 schema-v2 manifest.json。
    /// <para>
    /// 推荐工作流：先启动 Python 服务，在 Unity 中选择任务后按一次开始动作；该动作会同时
    /// 启动 session 与当前 trial。操作者可在任意时刻通过实验输入调用 <see cref="StopSession"/>。
    /// </para>
    /// </summary>
    public sealed class EvalSession : MonoBehaviour
    {
        /// <summary>当前单操作员采集使用的匿名标识，不要求现场填写。</summary>
        private const string OperatorId = "single_operator";

        /// <summary>当前跨端协议版本。</summary>
        private const string ProtocolVersion = "v1";

        /// <summary>等待远端 Python session 的头显状态文本。</summary>
        private const string WaitingForPythonStatus = "WAITING FOR PYTHON SESSION ID";

        /// <summary>当前 Python session 已存在 Unity 日志时的头显状态文本。</summary>
        private const string UsedPythonSessionStatus = "PYTHON SESSION ALREADY HAS UNITY LOGS - RESTART PYTHON";

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

        /// <summary>收到第一个 PoseResult 时是否自动开始录制；正式采集应保持关闭。</summary>
        [Tooltip("仅供诊断使用；正式采集保持关闭，由 Enter/A 一次启动 session 与当前任务。")]
        [SerializeField] private bool autoStart;

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

        /// <summary>最近一次被 Unity 日志占用而拒绝的 Python session_id。</summary>
        private string _lastRejectedPythonSessionId = string.Empty;

        /// <summary>当前 session 启动状态，供头显状态面板显示阻断原因。</summary>
        private string _sessionStatusMessage = WaitingForPythonStatus;

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

        /// <summary>当前 session 启动状态或阻断原因；空值表示没有额外诊断信息。</summary>
        public string SessionStatusMessage => _sessionStatusMessage;

        /// <summary>是否已收到一个尚未被本机日志占用的 Python session_id。</summary>
        public bool HasPendingPythonSession
        {
            get
            {
                string pythonId = runtimeHub != null ? runtimeHub.LatestPythonSessionId : string.Empty;
                return !string.IsNullOrWhiteSpace(pythonId)
                    && !string.Equals(_lastRejectedPythonSessionId, pythonId, StringComparison.Ordinal);
            }
        }

        /// <summary>录制开始事件；供固定计划和会话边界回调订阅。</summary>
        public UnityEvent SessionStarted => sessionStarted;

        /// <summary>录制停止事件；供会话边界回调订阅。</summary>
        public UnityEvent SessionStopped => sessionStopped;

        /// <summary>
        /// 启动一个新的正式评估 session，并严格复用 NATS 到达的 Python session_id。
        /// </summary>
        public void StartSession()
        {
            if (recorder == null)
            {
                SetSessionStatus("EVAL RECORDER NOT CONFIGURED");
                EgoAnchorLog.For<EvalSession>().Warning("EvalRecorder 未绑定，session 未启动。");
                return;
            }

            if (_recording)
            {
                SetSessionStatus("RECORDING");
                EgoAnchorLog.For<EvalSession>().Warning("StartSession 忽略：已有进行中的 session，请先调用 StopSession。数据不会被截断。");
                return;
            }

            if (!ValidateConfiguration())
                return;

            string root = ResolveOutputRoot();

            string pythonId = runtimeHub != null ? runtimeHub.LatestPythonSessionId : string.Empty;
            if (string.IsNullOrWhiteSpace(pythonId))
            {
                SetSessionStatus("WAITING FOR PYTHON SESSION ID - START THE REMOTE PYTHON SERVER");
                EgoAnchorLog.For<EvalSession>().Error(
                    "Formal session 启动已拒绝：尚未收到 Python session_id，禁止生成无法跨端配对的本地 session。");
                return;
            }
            _sessionId = pythonId;
            _sessionDir = Path.Combine(root, _sessionId);

            // 同一个远端 session 的 Unity 日志一旦存在，就不再每帧重复检查和刷屏；
            // 只有收到不同的 Python session_id 后才重新尝试。
            if (string.Equals(_lastRejectedPythonSessionId, pythonId, StringComparison.Ordinal))
                return;

            Directory.CreateDirectory(_sessionDir);
            EgoAnchorLog.For<EvalSession>().Info($"复用 Python session_id：{_sessionId}");

            string referencePath = Path.Combine(_sessionDir, EvalV2Manifest.UnityReferenceFileName);
            string admissionPath = Path.Combine(_sessionDir, EvalV2Manifest.UnityAdmissionFileName);
            string renderPath = Path.Combine(_sessionDir, EvalV2Manifest.UnityRenderFileName);
            string unityEventsPath = Path.Combine(_sessionDir, EvalV2Manifest.UnityEventsFileName);
            string mergedEventsPath = Path.Combine(_sessionDir, EvalV2Manifest.EventsFileName);
            string manifestPath = Path.Combine(_sessionDir, EvalV2Manifest.ManifestFileName);
            if (HasNonEmptyLog(referencePath)
                || HasNonEmptyLog(admissionPath)
                || HasNonEmptyLog(renderPath)
                || HasNonEmptyLog(unityEventsPath)
                || HasNonEmptyLog(mergedEventsPath)
                || HasNonEmptyLog(manifestPath))
            {
                EgoAnchorLog.For<EvalSession>().Error(
                    $"Session 启动已拒绝：目标 Unity 日志已有非空内容，禁止覆盖。session_id={_sessionId}");
                _lastRejectedPythonSessionId = pythonId;
                SetSessionStatus(UsedPythonSessionStatus);
                return;
            }

            _createdUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            try
            {
                recorder.BeginRecording(referencePath, admissionPath, renderPath, unityEventsPath, _sessionId);
            }
            catch (Exception exc)
            {
                SetSessionStatus("SESSION START FAILED - CHECK LOG PATH AND RECORDER");
                EgoAnchorLog.For<EvalSession>().Error($"Session 启动失败，已关闭部分日志：{exc}");
                return;
            }
            _recording = true;
            SetSessionStatus("RECORDING");
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
            SetSessionStatus("SESSION STOPPED");
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
                if (string.Equals(_lastRejectedPythonSessionId, pythonId, StringComparison.Ordinal))
                {
                    SetSessionStatus(UsedPythonSessionStatus);
                    return;
                }

                EgoAnchorLog.For<EvalSession>().Info($"自动启动录制，Python session_id={pythonId}");
                StartSession();
                _autoStarted = _recording;
                if (!_recording)
                    _nextAutoStartAttemptMonoMs = nowMonoMs + 1000.0;
            }
        }

        /// <summary>更新状态面板文本；重复状态不触发额外日志或状态抖动。</summary>
        private void SetSessionStatus(string message)
        {
            _sessionStatusMessage = message ?? string.Empty;
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
                string.Empty,
                recorder != null ? recorder.PlatformReferenceTransformPath : string.Empty,
                recorder != null ? recorder.PlatformReferenceController : string.Empty,
                recorder != null && recorder.PlatformReferencePreflightPassed);
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

        /// <summary>所有评估 session 都检查正式自动配置和完整变体矩阵。</summary>
        private bool ValidateConfiguration()
        {
            var missing = new List<string>();
            if (string.IsNullOrWhiteSpace(objectId)) missing.Add(nameof(objectId));

            string variantError = string.Empty;
            bool variantMatrixValid = recorder != null
                && (gameObject.scene.name == EvalV2Manifest.FormalSceneName
                    ? recorder.TryValidateFormalVariantMatrix(out variantError)
                    : recorder.TryValidateCurrentVariants(out variantError));
            if (!variantMatrixValid)
                missing.Add(string.IsNullOrWhiteSpace(variantError) ? "variantConfigs" : variantError);
            string referenceError = string.Empty;
            if (recorder == null || !recorder.TryValidatePlatformReference(objectId, out referenceError))
                missing.Add(string.IsNullOrWhiteSpace(referenceError)
                    ? "platformReference"
                    : referenceError);
            if (missing.Count == 0)
                return true;

            SetSessionStatus("FORMAL CONFIGURATION INCOMPLETE - CHECK INSPECTOR");
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

    }
}
