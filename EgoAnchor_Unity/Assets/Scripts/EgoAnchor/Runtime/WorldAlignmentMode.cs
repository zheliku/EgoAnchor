namespace EgoAnchor.Runtime
{
    /// <summary>camera-space pose 复合到 Unity world 时使用的参考时刻。</summary>
    public enum WorldAlignmentMode
    {
        /// <summary>使用 PoseResult.frame_id 对应的图像采集时刻相机姿态。</summary>
        CaptureTime = 0,
        /// <summary>使用 PoseResult 到达 Unity 时最新可用的相机姿态。</summary>
        ArrivalTime = 1,
    }
}
