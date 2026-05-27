namespace EgoAnchor.Alignment
{
    /// <summary>
    /// Unity 本地 anchor 对齐参考相机。
    ///
    /// Python 当前始终输出左目 OpenCV camera-space pose。该枚举只控制 Unity
    /// 在本地用哪一个 capture-time camera world pose 组合 object pose，不写入通信协议，
    /// 也不需要 Python 服务器知道。Right/Center/None 主要用于本地对照、补偿和诊断。
    /// </summary>
    public enum CameraReference
    {
        /// <summary>不做 camera frame 对齐；直接把 camera-local pose 当作 world pose 使用，主要用于诊断。</summary>
        None = 0,

        /// <summary>左目 camera 坐标系；当前 Python 感知 pipeline 的默认输出参考系。</summary>
        Left = 1,

        /// <summary>右目 capture-time camera world pose；用于本地对照或补偿实验。</summary>
        Right = 2,

        /// <summary>双眼中心/CenterEye capture-time camera world pose；用于中心眼视觉折中实验。</summary>
        Center = 3,
    }
}


