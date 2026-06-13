using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using EgoAnchor.Runtime;
using UnityEngine;

namespace EgoAnchorEval
{
    /// <summary>
    /// 从 Unity eval 的 `unity_output.jsonl` 读取 primary aligned raw pose，并在 Unity 内重跑指定 runtime。
    /// 该组件只服务定性回放验证，不连接 NATS，不启动 Python，也不重新做 camera-space 到 world-space 转换。
    /// </summary>
    [DefaultExecutionOrder(-60)]
    public sealed class RecordedAnchorReplaySource : MonoBehaviour
    {
        /// <summary>接收回放 aligned raw pose 的 runtime。</summary>
        [Header("Replay Input")]
        [Tooltip("接收回放 aligned raw pose 的 PoseToAnchorRuntime。该 runtime 可挂载任意 Gate/Estimator/Output 模块组合。")]
        [SerializeField] private PoseToAnchorRuntime runtime;

        /// <summary>Unity eval 输出 JSONL 路径。</summary>
        [Tooltip("Unity eval 输出 JSONL 路径。可填绝对路径，或相对 Unity 项目根目录的路径，例如 EgoAnchor_Python/data/eval/offline_data/..._unity_output.jsonl。")]
        [SerializeField] private string outputLogPath = "";

        /// <summary>优先选择的 primary variant label；为空时使用 is_primary=true 的 variant。</summary>
        [Tooltip("优先选择的 primary variant label。为空时使用 is_primary=true 的 variant；找不到时退化到第一条含 aligned_raw 的 variant。")]
        [SerializeField] private string primaryVariantLabel = "";

        /// <summary>是否在 Start 时自动加载并播放。</summary>
        [Header("Playback")]
        [Tooltip("是否在 Start 时自动加载并播放。")]
        [SerializeField] private bool playOnStart;

        /// <summary>是否循环播放。</summary>
        [Tooltip("播完后是否从第一条 replay 样本重新开始。")]
        [SerializeField] private bool loop;

        /// <summary>播放速度倍率。</summary>
        [Tooltip("播放速度倍率。1 表示按录制时间间隔播放；2 表示两倍速。")]
        [Min(0.01f)]
        [SerializeField] private float playbackSpeed = 1.0f;

        /// <summary>注入样本后是否立刻用同一回放时钟推进 runtime 输出。</summary>
        [Tooltip("注入样本后是否立刻用同一回放时钟调用 AdvanceAnchorOutput，保证 pipeline 输出与回放时间轴一致。")]
        [SerializeField] private bool driveRuntimeOutput = true;

        /// <summary>已加载的去重回放样本。</summary>
        private readonly List<ReplaySample> samples = new List<ReplaySample>();

        /// <summary>下一条待提交样本索引。</summary>
        private int cursor;

        /// <summary>本轮播放开始的 Unity realtime 秒值。</summary>
        private double playbackStartSeconds;

        /// <summary>第一条样本的录制 render_mono_ms。</summary>
        private double firstRenderMonoMs;

        /// <summary>当前是否正在播放。</summary>
        private bool playing;

        /// <summary>已加载样本数。</summary>
        public int SampleCount => samples.Count;

        /// <summary>下一条待播放样本索引。</summary>
        public int Cursor => cursor;

        /// <summary>当前是否正在播放。</summary>
        public bool IsPlaying => playing;

        /// <summary>播放速度倍率。</summary>
        public float PlaybackSpeed
        {
            get => playbackSpeed;
            set => playbackSpeed = Mathf.Max(0.01f, value);
        }

        /// <summary>是否循环播放。</summary>
        public bool Loop
        {
            get => loop;
            set => loop = value;
        }

        /// <summary>Unity Start：按需自动开始回放。</summary>
        private void Start()
        {
            if (playOnStart)
            {
                Play();
            }
        }

        /// <summary>Unity Update：按录制时间轴提交已经到达的样本。</summary>
        private void Update()
        {
            if (playing)
            {
                Pump(Time.realtimeSinceStartupAsDouble);
            }
        }

        /// <summary>
        /// 从 Inspector 配置路径加载日志。
        /// </summary>
        public void Load()
        {
            LoadFromPath(outputLogPath);
        }

        /// <summary>
        /// 从指定 JSONL 路径加载 primary aligned raw 样本，并按 source frame 去重。
        /// </summary>
        /// <param name="path">Unity output JSONL 路径。</param>
        public void LoadFromPath(string path)
        {
            samples.Clear();
            cursor = 0;
            string resolved = RecordedReplayJson.ResolvePath(path);
            if (string.IsNullOrEmpty(resolved) || !File.Exists(resolved))
            {
                Debug.LogWarning($"RecordedAnchorReplaySource 找不到 output log: {resolved}");
                return;
            }

            HashSet<long> seenFrames = new HashSet<long>();
            foreach (string line in File.ReadLines(resolved))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                using JsonDocument document = JsonDocument.Parse(line);
                if (TryReadSample(document.RootElement, seenFrames, out ReplaySample sample))
                {
                    samples.Add(sample);
                }
            }

            samples.Sort((a, b) => a.RenderMonoMs.CompareTo(b.RenderMonoMs));
            firstRenderMonoMs = samples.Count > 0 ? samples[0].RenderMonoMs : 0.0;
        }

        /// <summary>
        /// 开始或继续播放；尚未加载时会先按 Inspector 路径加载。
        /// </summary>
        public void Play()
        {
            if (samples.Count == 0)
            {
                Load();
            }

            if (samples.Count == 0 || runtime == null)
            {
                playing = false;
                return;
            }

            playbackStartSeconds = Time.realtimeSinceStartupAsDouble - RecordedElapsedSeconds(samples[Mathf.Clamp(cursor, 0, samples.Count - 1)].RenderMonoMs);
            playing = true;
        }

        /// <summary>暂停播放，保留当前 cursor。</summary>
        public void Pause()
        {
            playing = false;
        }

        /// <summary>停止播放并回到第一条样本。</summary>
        public void Stop()
        {
            playing = false;
            cursor = 0;
        }

        /// <summary>从第一条样本重新播放。</summary>
        public void Restart()
        {
            cursor = 0;
            if (samples.Count == 0)
            {
                Load();
            }

            playbackStartSeconds = Time.realtimeSinceStartupAsDouble;
            playing = samples.Count > 0 && runtime != null;
        }

        /// <summary>
        /// 按当前回放时间提交所有到达样本。该方法便于 smoke 或 Editor 工具显式驱动。
        /// </summary>
        /// <param name="nowSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <returns>本次提交的样本数。</returns>
        public int Pump(double nowSeconds)
        {
            if (runtime == null || samples.Count == 0)
            {
                return 0;
            }

            double targetMonoMs = firstRenderMonoMs + (nowSeconds - playbackStartSeconds) * 1000.0 * Mathf.Max(0.01f, playbackSpeed);
            int submitted = 0;
            while (cursor < samples.Count && samples[cursor].RenderMonoMs <= targetMonoMs)
            {
                Inject(samples[cursor]);
                cursor++;
                submitted++;
            }

            if (cursor >= samples.Count)
            {
                if (loop)
                {
                    cursor = 0;
                    playbackStartSeconds = nowSeconds;
                }
                else
                {
                    playing = false;
                }
            }

            return submitted;
        }

        /// <summary>
        /// 把一条已解析 replay 样本提交给 runtime。
        /// </summary>
        private void Inject(in ReplaySample sample)
        {
            double sampleTimeSeconds = ToReplaySeconds(sample.RenderMonoMs);
            double captureTimeSeconds = sample.HasCaptureTime
                ? ToReplaySeconds(sample.SourceCaptureMonoMs)
                : -1.0;
            runtime.AcceptAlignedWorldPoseForReplay(
                sample.FrameId,
                sample.Pose,
                captureTimeSeconds,
                sample.ReliabilityScore,
                sample.ReliabilityFlags,
                sample.Phase,
                sample.PoseSource,
                sampleTimeSeconds);
            if (driveRuntimeOutput)
            {
                runtime.AdvanceAnchorOutput(sampleTimeSeconds);
            }
        }

        /// <summary>
        /// 读取单行 unity_output 中的 primary aligned raw 样本。
        /// </summary>
        private bool TryReadSample(JsonElement row, HashSet<long> seenFrames, out ReplaySample sample)
        {
            sample = default;
            if (!row.TryGetProperty("variants", out JsonElement variants) || variants.ValueKind != JsonValueKind.Array)
            {
                return false;
            }

            JsonElement selected = default;
            bool hasSelected = false;
            foreach (JsonElement variant in variants.EnumerateArray())
            {
                string label = RecordedReplayJson.ReadString(variant, "label", "");
                bool labelMatched = !string.IsNullOrEmpty(primaryVariantLabel) && label == primaryVariantLabel;
                bool primaryMatched = string.IsNullOrEmpty(primaryVariantLabel) && RecordedReplayJson.ReadBool(variant, "is_primary", false);
                bool hasAlignedRaw = RecordedReplayJson.ReadBool(variant, "has_aligned_raw", false);
                if (hasAlignedRaw && (labelMatched || primaryMatched))
                {
                    selected = variant;
                    hasSelected = true;
                    break;
                }

                if (!hasSelected && hasAlignedRaw)
                {
                    selected = variant;
                    hasSelected = true;
                }
            }

            if (!hasSelected || !RecordedReplayJson.TryReadPose(selected, "aligned_raw_pos", "aligned_raw_rot", out Pose pose))
            {
                return false;
            }

            long frameId = RecordedReplayJson.ReadLong(selected, "source_frame_id", RecordedReplayJson.ReadLong(row, "source_frame_id", -1));
            if (frameId < 0 || !seenFrames.Add(frameId))
            {
                return false;
            }

            double renderMonoMs = RecordedReplayJson.ReadDouble(row, "render_mono_ms", 0.0);
            double sourceCaptureMonoMs = RecordedReplayJson.ReadDouble(selected, "source_capture_mono_ms", double.NaN);
            sample = new ReplaySample(
                frameId,
                renderMonoMs,
                sourceCaptureMonoMs,
                pose,
                RecordedReplayJson.ReadFloat(selected, "reliability_score", 1.0f),
                RecordedReplayJson.ReadStringArray(selected, "reliability_flags"),
                RecordedReplayJson.ReadString(selected, "latest_phase", "TRACK"),
                RecordedReplayJson.ReadString(selected, "pose_source", "TRACK"));
            return true;
        }

        /// <summary>
        /// 把录制 render_mono_ms 映射到当前播放时间轴。
        /// </summary>
        private double ToReplaySeconds(double recordedMonoMs)
        {
            return playbackStartSeconds + RecordedElapsedSeconds(recordedMonoMs);
        }

        /// <summary>
        /// 计算相对第一条样本的回放秒值。
        /// </summary>
        private double RecordedElapsedSeconds(double recordedMonoMs)
        {
            return (recordedMonoMs - firstRenderMonoMs) / (1000.0 * Mathf.Max(0.01f, playbackSpeed));
        }

        /// <summary>
        /// 回放样本。
        /// </summary>
        private readonly struct ReplaySample
        {
            /// <summary>source frame_id。</summary>
            public readonly long FrameId;

            /// <summary>该样本在原日志中的 render_mono_ms。</summary>
            public readonly double RenderMonoMs;

            /// <summary>source frame 采集单调时间，单位毫秒。</summary>
            public readonly double SourceCaptureMonoMs;

            /// <summary>aligned raw Unity world pose。</summary>
            public readonly Pose Pose;

            /// <summary>可靠性分数。</summary>
            public readonly float ReliabilityScore;

            /// <summary>可靠性 flags。</summary>
            public readonly string[] ReliabilityFlags;

            /// <summary>Python phase。</summary>
            public readonly string Phase;

            /// <summary>Python pose source。</summary>
            public readonly string PoseSource;

            /// <summary>是否有有效采集时间。</summary>
            public bool HasCaptureTime => !double.IsNaN(SourceCaptureMonoMs) && !double.IsInfinity(SourceCaptureMonoMs);

            /// <summary>构造回放样本。</summary>
            public ReplaySample(
                long frameId,
                double renderMonoMs,
                double sourceCaptureMonoMs,
                Pose pose,
                float reliabilityScore,
                string[] reliabilityFlags,
                string phase,
                string poseSource)
            {
                FrameId = frameId;
                RenderMonoMs = renderMonoMs;
                SourceCaptureMonoMs = sourceCaptureMonoMs;
                Pose = pose;
                ReliabilityScore = reliabilityScore;
                ReliabilityFlags = reliabilityFlags ?? Array.Empty<string>();
                Phase = phase ?? string.Empty;
                PoseSource = poseSource ?? string.Empty;
            }
        }
    }

    /// <summary>
    /// Eval replay JSONL 解析辅助函数。它只处理 Unity output 日志中的基本类型和 pose 数组。
    /// </summary>
    internal static class RecordedReplayJson
    {
        /// <summary>
        /// 解析绝对路径或相对 Unity 项目根目录的路径。
        /// </summary>
        public static string ResolvePath(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                return string.Empty;
            }

            if (Path.IsPathRooted(path))
            {
                return Path.GetFullPath(path);
            }

            string projectRoot = Directory.GetCurrentDirectory();
            try
            {
                string dataPath = Application.dataPath;
                DirectoryInfo parent = Directory.GetParent(dataPath);
                if (parent != null)
                {
                    projectRoot = parent.FullName;
                }
            }
            catch
            {
                projectRoot = Directory.GetCurrentDirectory();
            }

            return Path.GetFullPath(Path.Combine(projectRoot, path));
        }

        /// <summary>
        /// 尝试从 JSON object 中读取 Pose。
        /// </summary>
        public static bool TryReadPose(JsonElement row, string posName, string rotName, out Pose pose)
        {
            pose = Pose.identity;
            if (!row.TryGetProperty(posName, out JsonElement pos) || pos.ValueKind == JsonValueKind.Null)
            {
                return false;
            }

            if (!row.TryGetProperty(rotName, out JsonElement rot) || rot.ValueKind == JsonValueKind.Null)
            {
                return false;
            }

            if (pos.ValueKind != JsonValueKind.Array || pos.GetArrayLength() != 3 || rot.ValueKind != JsonValueKind.Array || rot.GetArrayLength() != 4)
            {
                return false;
            }

            pose = new Pose(ReadVector3(pos), ReadQuaternion(rot));
            return true;
        }

        /// <summary>
        /// 读取 double 字段。
        /// </summary>
        public static double ReadDouble(JsonElement row, string name, double defaultValue)
        {
            return row.TryGetProperty(name, out JsonElement value) && value.ValueKind != JsonValueKind.Null
                ? value.GetDouble()
                : defaultValue;
        }

        /// <summary>
        /// 读取 float 字段。
        /// </summary>
        public static float ReadFloat(JsonElement row, string name, float defaultValue)
        {
            return row.TryGetProperty(name, out JsonElement value) && value.ValueKind != JsonValueKind.Null
                ? (float)value.GetDouble()
                : defaultValue;
        }

        /// <summary>
        /// 读取 long 字段。
        /// </summary>
        public static long ReadLong(JsonElement row, string name, long defaultValue)
        {
            return row.TryGetProperty(name, out JsonElement value) && value.ValueKind != JsonValueKind.Null
                ? value.GetInt64()
                : defaultValue;
        }

        /// <summary>
        /// 读取 bool 字段。
        /// </summary>
        public static bool ReadBool(JsonElement row, string name, bool defaultValue)
        {
            return row.TryGetProperty(name, out JsonElement value) && value.ValueKind != JsonValueKind.Null
                ? value.GetBoolean()
                : defaultValue;
        }

        /// <summary>
        /// 读取 string 字段。
        /// </summary>
        public static string ReadString(JsonElement row, string name, string defaultValue)
        {
            return row.TryGetProperty(name, out JsonElement value) && value.ValueKind != JsonValueKind.Null
                ? value.GetString() ?? defaultValue
                : defaultValue;
        }

        /// <summary>
        /// 读取 string array 字段；旧日志缺失时返回空数组。
        /// </summary>
        public static string[] ReadStringArray(JsonElement row, string name)
        {
            if (!row.TryGetProperty(name, out JsonElement value) || value.ValueKind != JsonValueKind.Array)
            {
                return Array.Empty<string>();
            }

            List<string> result = new List<string>();
            foreach (JsonElement item in value.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.String)
                {
                    result.Add(item.GetString() ?? string.Empty);
                }
            }

            return result.ToArray();
        }

        /// <summary>
        /// 读取 Vector3 数组。
        /// </summary>
        private static Vector3 ReadVector3(JsonElement value)
        {
            return new Vector3(
                (float)value[0].GetDouble(),
                (float)value[1].GetDouble(),
                (float)value[2].GetDouble());
        }

        /// <summary>
        /// 读取 Quaternion 数组，顺序为 xyzw。
        /// </summary>
        private static Quaternion ReadQuaternion(JsonElement value)
        {
            return new Quaternion(
                (float)value[0].GetDouble(),
                (float)value[1].GetDouble(),
                (float)value[2].GetDouble(),
                (float)value[3].GetDouble());
        }
    }
}
