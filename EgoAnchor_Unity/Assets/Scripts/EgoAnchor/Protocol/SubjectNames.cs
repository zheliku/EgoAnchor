namespace EgoAnchor.Protocol
{
    /// <summary>
    /// Unity 侧逻辑 subject 名称常量。
    /// 本文件由 EgoAnchor_Protocol/tools/generate_proto.ps1 从 subjects.v1.json 生成。
    /// 不要手动修改；subject 变更请改 subjects.v1.json 后重新运行生成脚本。
    /// </summary>
    public static class SubjectNames
    {
        /// <summary>Unity -> Python：Quest 双目 JPEG 图像数据面。</summary>
        public const string QuestStereo = "egoanchor.v1.quest.stereo";
        /// <summary>Unity -> Python：Quest 相机标定数据面。</summary>
        public const string QuestCameraInfo = "egoanchor.v1.quest.camera_info";
        /// <summary>Python -> Unity：pose result 控制面消息。</summary>
        public const string PoseResult = "egoanchor.v1.pose.result";
        /// <summary>Python -> Unity：anchor 状态事件。</summary>
        public const string AnchorStatus = "egoanchor.v1.anchor.status";
        /// <summary>Python -> Unity：服务心跳。</summary>
        public const string ServerHeartbeat = "egoanchor.v1.server.heartbeat";
        /// <summary>Unity -> Python：reset request/reply 命令。</summary>
        public const string ResetTracking = "egoanchor.v1.cmd.anchor.reset";
        /// <summary>Unity -> Python：reacquire request/reply 命令。</summary>
        public const string ReacquireAnchor = "egoanchor.v1.cmd.anchor.reacquire";
        /// <summary>Unity -> Python：anchor control request/reply 命令。</summary>
        public const string AnchorControl = "egoanchor.v1.cmd.anchor.control";
    }
}
