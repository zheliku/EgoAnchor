using System;
using System.Globalization;
using System.IO;
using UnityEngine;
using UnityEngine.InputSystem;

namespace EgoAnchorEval
{
    /// <summary>
    /// U1/U2 手动验收辅助组件：在 Play Mode 中打印手柄 GT，并触发 recorder 写入短时 smoke 日志。
    /// </summary>
    public sealed class EvalManualSmokeDriver : MonoBehaviour
    {
        /// <summary>待测试的手柄 GT provider。</summary>
        [Header("References")]
        [Tooltip("待测试的手柄 GT provider。")]
        [SerializeField] private ControllerGroundTruthProvider gt;

        /// <summary>待测试的评估记录器。</summary>
        [Tooltip("待测试的评估记录器。")]
        [SerializeField] private AnchorEvalRecorder recorder;

        /// <summary>测试日志根目录；为空时自动写到 EgoAnchor_Python/data/eval/manual_smoke。</summary>
        [Header("Smoke Output")]
        [Tooltip("测试日志根目录；为空时自动写到 EgoAnchor_Python/data/eval/manual_smoke。可填绝对路径。")]
        [SerializeField] private string outputRoot = string.Empty;

        /// <summary>测试 session 名称前缀。</summary>
        [Tooltip("测试 session 名称前缀，会追加 UTC 时间戳，避免覆盖上一轮测试。")]
        [SerializeField] private string sessionPrefix = "u1_u2_manual_smoke";

        /// <summary>是否在 Play 后自动开始打印 GT。</summary>
        [Header("Hotkeys")]
        [Tooltip("是否在 Play 后自动开始每秒打印一次 GT pose。")]
        [SerializeField] private bool logGroundTruthOnStart;

        /// <summary>切换 GT 日志的按键。</summary>
        [Tooltip("切换 GT 日志的按键。默认 F6。")]
        [SerializeField] private Key toggleGroundTruthLogKey = Key.F6;

        /// <summary>开始录制的按键。</summary>
        [Tooltip("开始 U2 smoke 录制的按键。默认 F7。")]
        [SerializeField] private Key beginRecordingKey = Key.F7;

        /// <summary>停止录制的按键。</summary>
        [Tooltip("停止 U2 smoke 录制的按键。默认 F8。")]
        [SerializeField] private Key stopRecordingKey = Key.F8;

        /// <summary>GT 日志打印间隔。</summary>
        [Tooltip("GT 日志打印间隔，单位秒。")]
        [Min(0.1f)]
        [SerializeField] private float gtLogIntervalSeconds = 1.0f;

        /// <summary>是否正在周期打印 GT。</summary>
        private bool loggingGroundTruth;

        /// <summary>下一次 GT 日志时间。</summary>
        private double nextGroundTruthLogTime;

        /// <summary>当前 smoke session 目录。</summary>
        private string currentSessionDir;

        /// <summary>当前 smoke session ID。</summary>
        private string currentSessionId;

        /// <summary>
        /// Play Mode 启动时可选开启 GT 日志。
        /// </summary>
        private void Start()
        {
            loggingGroundTruth = logGroundTruthOnStart;
            nextGroundTruthLogTime = 0.0;
            Debug.Log("[EgoAnchorEval][Smoke] F6 toggles GT logging, F7 begins recording, F8 stops recording.");
        }

        /// <summary>
        /// Play Mode 热键入口。
        /// </summary>
        private void Update()
        {
            if (WasPressedThisFrame(toggleGroundTruthLogKey))
            {
                ToggleGroundTruthLogging();
            }

            if (WasPressedThisFrame(beginRecordingKey))
            {
                BeginSmokeRecording();
            }

            if (WasPressedThisFrame(stopRecordingKey))
            {
                StopSmokeRecording();
            }

            if (loggingGroundTruth && Time.realtimeSinceStartupAsDouble >= nextGroundTruthLogTime)
            {
                LogGroundTruthOnce();
                nextGroundTruthLogTime = Time.realtimeSinceStartupAsDouble + Mathf.Max(0.1f, gtLogIntervalSeconds);
            }
        }

        /// <summary>
        /// Inspector ContextMenu：切换每秒 GT 日志。
        /// </summary>
        [ContextMenu("EgoAnchor Eval/Toggle Ground Truth Logging")]
        public void ToggleGroundTruthLogging()
        {
            loggingGroundTruth = !loggingGroundTruth;
            nextGroundTruthLogTime = 0.0;
            Debug.Log($"[EgoAnchorEval][U1] Ground truth logging: {loggingGroundTruth}");
        }

        /// <summary>
        /// Inspector ContextMenu：立即打印一次手柄 GT pose。
        /// </summary>
        [ContextMenu("EgoAnchor Eval/Log Ground Truth Once")]
        public void LogGroundTruthOnce()
        {
            if (gt == null)
            {
                Debug.LogWarning("[EgoAnchorEval][U1] Missing ControllerGroundTruthProvider reference.");
                return;
            }

            bool hasPose = gt.TryGetWorldPose(out Pose pose, out bool tracked);
            Vector3 p = pose.position;
            Quaternion q = pose.rotation;
            Debug.Log(
                "[EgoAnchorEval][U1] "
                + $"controller={gt.Controller} has_pose={hasPose} tracked={tracked} "
                + $"pos=({Format(p.x)},{Format(p.y)},{Format(p.z)}) "
                + $"rot_xyzw=({Format(q.x)},{Format(q.y)},{Format(q.z)},{Format(q.w)})");
        }

        /// <summary>
        /// Inspector ContextMenu：开始 U2 smoke 录制。
        /// </summary>
        [ContextMenu("EgoAnchor Eval/Begin U1 U2 Smoke Recording")]
        public void BeginSmokeRecording()
        {
            if (recorder == null)
            {
                Debug.LogWarning("[EgoAnchorEval][U2] Missing AnchorEvalRecorder reference.");
                return;
            }

            currentSessionId = $"{sessionPrefix}_{DateTimeOffset.UtcNow.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture)}";
            currentSessionDir = Path.Combine(ResolveOutputRoot(), currentSessionId);
            string capturePath = Path.Combine(currentSessionDir, $"{currentSessionId}_unity_capture.jsonl");
            string outputPath = Path.Combine(currentSessionDir, $"{currentSessionId}_unity_output.jsonl");
            recorder.BeginRecording(capturePath, outputPath);
            Debug.Log($"[EgoAnchorEval][U2] Recording started: {currentSessionDir}");
            Debug.Log($"[EgoAnchorEval][U2] capture={capturePath}");
            Debug.Log($"[EgoAnchorEval][U2] output={outputPath}");
        }

        /// <summary>
        /// Inspector ContextMenu：停止 U2 smoke 录制。
        /// </summary>
        [ContextMenu("EgoAnchor Eval/Stop U1 U2 Smoke Recording")]
        public void StopSmokeRecording()
        {
            if (recorder == null)
            {
                Debug.LogWarning("[EgoAnchorEval][U2] Missing AnchorEvalRecorder reference.");
                return;
            }

            recorder.StopRecording();
            Debug.Log($"[EgoAnchorEval][U2] Recording stopped: {currentSessionDir}");
        }

        /// <summary>
        /// 解析测试输出根目录。
        /// </summary>
        private string ResolveOutputRoot()
        {
            if (!string.IsNullOrWhiteSpace(outputRoot))
            {
                return Path.IsPathRooted(outputRoot)
                    ? outputRoot
                    : Path.GetFullPath(Path.Combine(Application.dataPath, "..", outputRoot));
            }

            return Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "EgoAnchor_Python", "data", "eval", "manual_smoke"));
        }

        /// <summary>
        /// 使用 Unity 新 Input System 检查单帧按键。
        /// </summary>
        private static bool WasPressedThisFrame(Key key)
        {
            return key != Key.None
                && Keyboard.current != null
                && Keyboard.current[key].wasPressedThisFrame;
        }

        /// <summary>
        /// 用 invariant round-trip 格式输出调试数字。
        /// </summary>
        private static string Format(float value)
        {
            return value.ToString("R", CultureInfo.InvariantCulture);
        }
    }
}
