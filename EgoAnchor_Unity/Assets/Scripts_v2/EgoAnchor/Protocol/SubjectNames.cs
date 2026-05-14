namespace EgoAnchor.V2.Protocol
{
    /// <summary>
    /// Unity 侧 v2 subject 名称常量。
    /// 本文件由 EgoAnchor_Protocol/tools/generate_proto.ps1 从 subjects.v1.json 生成。
    /// 不要手动修改；subject 变更请改 subjects.v1.json 后重新运行生成脚本。
    /// </summary>
    public static class SubjectNames
    {
        public const string QuestStereo = "egoanchor.v1.quest.stereo";
        public const string QuestCameraInfo = "egoanchor.v1.quest.camera_info";
        public const string PoseResult = "egoanchor.v1.pose.result";
        public const string AnchorStatus = "egoanchor.v1.anchor.status";
        public const string ServerHeartbeat = "egoanchor.v1.server.heartbeat";
        public const string ResetTracking = "egoanchor.v1.cmd.anchor.reset";
        public const string ReacquireAnchor = "egoanchor.v1.cmd.anchor.reacquire";
        public const string AnchorControl = "egoanchor.v1.cmd.anchor.control";
    }
}
