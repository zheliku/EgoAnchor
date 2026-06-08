using System;
using EgoAnchor.Protocol.Generated;

namespace EgoAnchor.Quest
{
    /// <summary>
    /// Quest 数据流发布会话信息。
    ///
    /// StereoFrameSource 与 CameraInfoSource 必须使用同一个 session_id，
    /// 否则 Python 端会把 camera_info 与 stereo 误判为不同 Unity 重启会话。
    /// QuestStreamPublisher 在启用时会刷新 session_id，使 Python 能识别 Unity Play Mode 重入和应用重启。
    /// </summary>
    public static class QuestStreamSession
    {
        /// <summary>当前 Unity 发布会话 ID；同一次发布期间 stereo/camera_info 共用。</summary>
        public static string SessionId { get; private set; } = NewSessionId();

        /// <summary>当前 Quest/Unity 客户端 ID。后续如果有设备管理 UI，可替换为持久化设备标识。</summary>
        public const string ClientId = "quest-unity";

        /// <summary>开始一个新的 Unity 发布会话。</summary>
        public static void BeginNewSession()
        {
            SessionId = NewSessionId();
        }

        /// <summary>
        /// 构造共享消息头；frame_id 是后续 frame alignment 的主键。
        /// </summary>
        /// <param name="frameId">当前消息对应的 frame_id；camera_info 没有特定图像帧时填 0。</param>
        /// <param name="unityFrame">Unity 当前 Time.frameCount。</param>
        /// <param name="senderMonoMs">Unity 单调时钟毫秒，用于诊断发送侧时间。</param>
        /// <returns>填好 session/client/frame/timing 的协议消息头。</returns>
        public static MessageHeader BuildHeader(long frameId, int unityFrame, double senderMonoMs)
        {
            return new MessageHeader
            {
                MessageId = Guid.NewGuid().ToString("N"),
                SessionId = SessionId,
                ClientId = ClientId,
                FrameId = frameId,
                UnityFrame = unityFrame,
                SenderMonoMs = senderMonoMs,
                CreatedUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                SchemaVersion = "v1"
            };
        }

        /// <summary>生成新的无分隔符 GUID 字符串作为 session_id。</summary>
        private static string NewSessionId()
        {
            return Guid.NewGuid().ToString("N");
        }
    }
}
