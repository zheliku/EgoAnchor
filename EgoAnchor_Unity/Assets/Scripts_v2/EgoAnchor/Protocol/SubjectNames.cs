namespace EgoAnchor.V2.Protocol
{
    /// <summary>
    /// v2 逻辑 channel 名称业务别名。
    ///
    /// ChannelNames.cs 由 EgoAnchor_Protocol/tools/generate_proto.ps1 从 subjects.v1.json 自动生成，
    /// 是 Unity/Python 共享 channel 契约在 C# 侧的直接投影。
    ///
    /// 本类保留 SubjectNames 命名，用于业务脚本表达“订阅/发布哪个语义 subject”，
    /// 同时避免业务代码关心生成文件位置。需要新增/修改 channel 时，请改 subjects.v1.json
    /// 并重新运行生成脚本，不要手写字符串。
    /// </summary>
    public static class SubjectNames
    {
        /// <summary>Unity -> Python，高频双目 JPEG 数据流。</summary>
        public const string QuestStereo = ChannelNames.QuestStereo;

        /// <summary>Unity -> Python，低频 Quest camera intrinsics / lens pose 标定。</summary>
        public const string QuestCameraInfo = ChannelNames.QuestCameraInfo;

        /// <summary>Python -> Unity，相机坐标系物体 pose 估计结果。</summary>
        public const string PoseResult = ChannelNames.PoseResult;

        /// <summary>Python -> Unity，anchor/tracking 状态事件流。</summary>
        public const string AnchorStatus = ChannelNames.AnchorStatus;

        /// <summary>Python -> Unity，服务健康状态和运行心跳。</summary>
        public const string ServerHeartbeat = ChannelNames.ServerHeartbeat;

        /// <summary>Unity -> Python，重置 tracking 的 request/reply subject。</summary>
        public const string ResetTracking = ChannelNames.ResetTracking;

        /// <summary>Unity -> Python，请求重新捕获/重定位 anchor 的 request/reply subject。</summary>
        public const string ReacquireAnchor = ChannelNames.ReacquireAnchor;

        /// <summary>Unity -> Python，暂停、恢复、切 stage 等控制命令的 request/reply subject。</summary>
        public const string AnchorControl = ChannelNames.AnchorControl;
    }
}
