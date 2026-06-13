using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using UnityEngine;

namespace EgoAnchorEval
{
    /// <summary>
    /// 播放已录制的 stable anchor 轨迹。该组件用于 supplementary video 复现，不参与算法评估。
    /// </summary>
    [DefaultExecutionOrder(-40)]
    public sealed class AnchorTrajectoryPlayer : MonoBehaviour
    {
        /// <summary>要驱动的 Transform。</summary>
        [Header("Trajectory")]
        [Tooltip("要驱动的 Transform。通常是某个策略变体的可视化物体。")]
        [SerializeField] private Transform targetTransform;

        /// <summary>Unity eval 输出 JSONL 路径。</summary>
        [Tooltip("Unity eval 输出 JSONL 路径。可填绝对路径，或相对 Unity 项目根目录的路径。")]
        [SerializeField] private string outputLogPath = "";

        /// <summary>要播放的策略 label。</summary>
        [Tooltip("要播放的 variants.label，例如 raw_zoh、kalman_cv、oneeuro_vanilla 或 egoanchor_full。")]
        [SerializeField] private string variantLabel = "egoanchor_full";

        /// <summary>是否在 Start 时自动加载并播放。</summary>
        [Header("Playback")]
        [Tooltip("是否在 Start 时自动加载并播放。")]
        [SerializeField] private bool playOnStart;

        /// <summary>是否循环播放。</summary>
        [Tooltip("播完后是否循环播放。")]
        [SerializeField] private bool loop;

        /// <summary>播放速度倍率。</summary>
        [Tooltip("播放速度倍率。1 表示按录制时间间隔播放；2 表示两倍速。")]
        [Min(0.01f)]
        [SerializeField] private float playbackSpeed = 1.0f;

        /// <summary>该帧没有 stable pose 时是否隐藏目标物体。</summary>
        [Tooltip("该帧没有 stable pose 时是否隐藏目标物体；关闭时会保持上一帧可用 pose。")]
        [SerializeField] private bool hideWhenMissingPose = true;

        /// <summary>已加载轨迹样本。</summary>
        private readonly List<TrajectorySample> samples = new List<TrajectorySample>();

        /// <summary>下一条待播放样本索引。</summary>
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

        /// <summary>Unity Start：按需自动播放。</summary>
        private void Start()
        {
            if (playOnStart)
            {
                Play();
            }
        }

        /// <summary>Unity Update：推进到当前回放时间。</summary>
        private void Update()
        {
            if (playing)
            {
                Pump(Time.realtimeSinceStartupAsDouble);
            }
        }

        /// <summary>从 Inspector 配置路径加载轨迹。</summary>
        public void Load()
        {
            LoadFromPath(outputLogPath, variantLabel);
        }

        /// <summary>
        /// 从指定 JSONL 路径加载一个 variant label 的 stable 轨迹。
        /// </summary>
        /// <param name="path">Unity output JSONL 路径。</param>
        /// <param name="label">目标 variants.label。</param>
        public void LoadFromPath(string path, string label)
        {
            samples.Clear();
            cursor = 0;
            string resolved = RecordedReplayJson.ResolvePath(path);
            if (string.IsNullOrEmpty(resolved) || !File.Exists(resolved))
            {
                Debug.LogWarning($"AnchorTrajectoryPlayer 找不到 output log: {resolved}");
                return;
            }

            foreach (string line in File.ReadLines(resolved))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                using JsonDocument document = JsonDocument.Parse(line);
                if (TryReadSample(document.RootElement, label, out TrajectorySample sample))
                {
                    samples.Add(sample);
                }
            }

            samples.Sort((a, b) => a.RenderMonoMs.CompareTo(b.RenderMonoMs));
            firstRenderMonoMs = samples.Count > 0 ? samples[0].RenderMonoMs : 0.0;
        }

        /// <summary>开始或继续播放；尚未加载时会先加载。</summary>
        public void Play()
        {
            if (samples.Count == 0)
            {
                Load();
            }

            if (samples.Count == 0 || targetTransform == null)
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

        /// <summary>停止播放并回到第一帧。</summary>
        public void Stop()
        {
            playing = false;
            cursor = 0;
        }

        /// <summary>从第一帧重新播放。</summary>
        public void Restart()
        {
            cursor = 0;
            if (samples.Count == 0)
            {
                Load();
            }

            playbackStartSeconds = Time.realtimeSinceStartupAsDouble;
            playing = samples.Count > 0 && targetTransform != null;
        }

        /// <summary>
        /// 按当前回放时间应用所有到达的轨迹样本。
        /// </summary>
        /// <param name="nowSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <returns>本次应用的样本数。</returns>
        public int Pump(double nowSeconds)
        {
            if (targetTransform == null || samples.Count == 0)
            {
                return 0;
            }

            double targetMonoMs = firstRenderMonoMs + (nowSeconds - playbackStartSeconds) * 1000.0 * Mathf.Max(0.01f, playbackSpeed);
            int applied = 0;
            while (cursor < samples.Count && samples[cursor].RenderMonoMs <= targetMonoMs)
            {
                Apply(samples[cursor]);
                cursor++;
                applied++;
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

            return applied;
        }

        /// <summary>
        /// 应用一条 stable pose 样本。
        /// </summary>
        private void Apply(in TrajectorySample sample)
        {
            if (!sample.HasPose)
            {
                if (hideWhenMissingPose && targetTransform.gameObject.activeSelf)
                {
                    targetTransform.gameObject.SetActive(false);
                }

                return;
            }

            if (hideWhenMissingPose && !targetTransform.gameObject.activeSelf)
            {
                targetTransform.gameObject.SetActive(true);
            }

            targetTransform.SetPositionAndRotation(sample.Pose.position, sample.Pose.rotation);
        }

        /// <summary>
        /// 从一行 unity_output 读取目标 variant 的 stable pose。
        /// </summary>
        private static bool TryReadSample(JsonElement row, string label, out TrajectorySample sample)
        {
            sample = default;
            if (!row.TryGetProperty("variants", out JsonElement variants) || variants.ValueKind != JsonValueKind.Array)
            {
                return false;
            }

            foreach (JsonElement variant in variants.EnumerateArray())
            {
                if (RecordedReplayJson.ReadString(variant, "label", "") != label)
                {
                    continue;
                }

                double renderMonoMs = RecordedReplayJson.ReadDouble(row, "render_mono_ms", 0.0);
                bool hasStable = RecordedReplayJson.ReadBool(variant, "has_stable", false);
                Pose pose = Pose.identity;
                bool hasPose = hasStable && RecordedReplayJson.TryReadPose(variant, "stable_pos", "stable_rot", out pose);
                sample = new TrajectorySample(renderMonoMs, hasPose, pose);
                return true;
            }

            return false;
        }

        /// <summary>
        /// 计算相对第一条样本的回放秒值。
        /// </summary>
        private double RecordedElapsedSeconds(double recordedMonoMs)
        {
            return (recordedMonoMs - firstRenderMonoMs) / (1000.0 * Mathf.Max(0.01f, playbackSpeed));
        }

        /// <summary>
        /// 轨迹样本。
        /// </summary>
        private readonly struct TrajectorySample
        {
            /// <summary>原日志 render_mono_ms。</summary>
            public readonly double RenderMonoMs;

            /// <summary>是否有 stable pose。</summary>
            public readonly bool HasPose;

            /// <summary>stable pose。</summary>
            public readonly Pose Pose;

            /// <summary>构造轨迹样本。</summary>
            public TrajectorySample(double renderMonoMs, bool hasPose, Pose pose)
            {
                RenderMonoMs = renderMonoMs;
                HasPose = hasPose;
                Pose = pose;
            }
        }
    }
}
