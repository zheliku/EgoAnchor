namespace EgoAnchor.V2.Protocol
{
    /// <summary>
    /// v2 逻辑 channel 名称别名。
    ///
    /// ChannelNames.cs 由 EgoAnchor_Protocol/tools/generate_proto.ps1 自动生成。
    /// 本类只提供 plan.md 中使用的 SubjectNames 命名，避免业务脚本依赖生成文件的物理位置。
    /// </summary>
    public static class SubjectNames
    {
        public const string QuestStereo = ChannelNames.QuestStereo;
        public const string QuestCameraInfo = ChannelNames.QuestCameraInfo;
        public const string PoseResult = ChannelNames.PoseResult;
        public const string AnchorStatus = ChannelNames.AnchorStatus;
        public const string ServerHeartbeat = ChannelNames.ServerHeartbeat;
        public const string ResetTracking = ChannelNames.ResetTracking;
        public const string ReacquireAnchor = ChannelNames.ReacquireAnchor;
        public const string AnchorControl = ChannelNames.AnchorControl;
    }
}
