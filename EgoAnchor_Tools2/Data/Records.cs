using EgoAnchor.Tools2.Math;

namespace EgoAnchor.Tools2.Data
{
    /// <summary>
    /// 单个观测记录:5fps 左右的 frame-aligned Unity world pose。
    ///
    /// 这是所有预测算法共享的中性输入,对应 unity_output.jsonl 里 is_primary variant 携带的 aligned_raw。
    /// 时间戳取 source_capture_mono_ms (采集时刻),与 Unity estimator 的 MeasurementTime 一致,
    /// 保证测量在时间轴上对齐到 capture 时刻而不是消息到达时刻。
    /// </summary>
    public readonly struct PoseObservation
    {
        /// <summary>该观测对应的 Quest stereo frame_id。</summary>
        public readonly long FrameId;

        /// <summary>采集单调时间,单位秒 (source_capture_mono_ms / 1000)。</summary>
        public readonly double CaptureTimeSeconds;

        /// <summary>frame-aligned Unity world 位置,单位米。</summary>
        public readonly Vec3 Position;

        /// <summary>frame-aligned Unity world 旋转。</summary>
        public readonly QuaternionM Rotation;

        /// <summary>Python 感知侧可靠性评分,范围 0..1。</summary>
        public readonly float Score;

        /// <summary>构造观测记录。</summary>
        public PoseObservation(long frameId, double captureTimeSeconds, Vec3 position, QuaternionM rotation, float score)
        {
            FrameId = frameId;
            CaptureTimeSeconds = captureTimeSeconds;
            Position = position;
            Rotation = rotation;
            Score = AnchorMath.Clamp01(score);
        }
    }

    /// <summary>
    /// session 中的一个实验条件分段 (static / slow_head / fast_head / object_motion)。
    /// 来自 manifest 的 condition_spans,用于把长轨迹按条件切分画图,避免观测点挤在一起。
    /// </summary>
    public readonly struct ConditionSpan
    {
        /// <summary>条件标签 (static、slow_head、fast_head、object_motion)。</summary>
        public readonly string Label;

        /// <summary>分段起始单调时间,单位秒 (start_mono_ms / 1000)。</summary>
        public readonly double StartSeconds;

        /// <summary>分段结束单调时间,单位秒 (end_mono_ms / 1000)。</summary>
        public readonly double EndSeconds;

        /// <summary>构造条件分段。</summary>
        public ConditionSpan(string label, double startSeconds, double endSeconds)
        {
            Label = label ?? string.Empty;
            StartSeconds = startSeconds;
            EndSeconds = endSeconds;
        }

        /// <summary>分段时长,单位秒。</summary>
        public double DurationSeconds => EndSeconds - StartSeconds;
    }

    /// <summary>
    /// 单个 render 帧的时间记录,用于驱动 PredictAt。
    /// 对应 unity_output.jsonl 的 render_mono_ms 序列 (~60fps)。
    /// </summary>
    public readonly struct RenderTick
    {
        /// <summary>渲染单调时间,单位秒 (render_mono_ms / 1000)。</summary>
        public readonly double RenderTimeSeconds;

        /// <summary>该 render 帧对应的 source frame_id (诊断用,不进入预测)。</summary>
        public readonly long SourceFrameId;

        /// <summary>构造 render tick。</summary>
        public RenderTick(double renderTimeSeconds, long sourceFrameId)
        {
            RenderTimeSeconds = renderTimeSeconds;
            SourceFrameId = sourceFrameId;
        }
    }

    /// <summary>
    /// 单个算法在一帧 render 上的预测输出。
    /// </summary>
    public readonly struct PredictSample
    {
        /// <summary>渲染单调时间,单位秒。</summary>
        public readonly double RenderTimeSeconds;

        /// <summary>预测位置,单位米。</summary>
        public readonly Vec3 Position;

        /// <summary>预测旋转。</summary>
        public readonly QuaternionM Rotation;

        /// <summary>本帧预测的前推时长 (renderTime - 最后观测时间),单位秒。</summary>
        public readonly float PredictAheadSeconds;

        /// <summary>构造预测样本。</summary>
        public PredictSample(double renderTimeSeconds, Vec3 position, QuaternionM rotation, float predictAheadSeconds)
        {
            RenderTimeSeconds = renderTimeSeconds;
            Position = position;
            Rotation = rotation;
            PredictAheadSeconds = predictAheadSeconds;
        }
    }
}
