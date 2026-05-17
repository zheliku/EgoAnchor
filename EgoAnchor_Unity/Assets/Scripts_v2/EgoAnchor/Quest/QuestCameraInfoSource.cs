using System;
using EgoAnchor.Protocol.V1;
using Meta.XR;
using UnityEngine;

namespace EgoAnchor.V2.Quest
{
    /// <summary>
    /// Quest 相机标定信息源。
    ///
    /// 职责边界：
    /// - 从左右 PassthroughCameraAccess 读取 intrinsics / lens pose。
    /// - 构造 QuestCameraInfo Protobuf。
    /// - 不负责 ZMQ socket，不负责发送频率。
    /// </summary>
    public sealed class QuestCameraInfoSource : MonoBehaviour
    {
        [SerializeField] private PassthroughCameraAccess leftCameraAccess;
        [SerializeField] private PassthroughCameraAccess rightCameraAccess;

        /// <summary>
        /// 尝试读取当前 Quest camera_info。
        /// </summary>
        public bool TryCapture(out QuestCameraInfo info)
        {
            info = null;
            if (leftCameraAccess == null || rightCameraAccess == null)
            {
                return false;
            }

            if (!leftCameraAccess.IsPlaying || !rightCameraAccess.IsPlaying)
            {
                return false;
            }

            PassthroughCameraAccess.CameraIntrinsics leftIntr = leftCameraAccess.Intrinsics;
            PassthroughCameraAccess.CameraIntrinsics rightIntr = rightCameraAccess.Intrinsics;
            Vector2Int leftRes = leftCameraAccess.CurrentResolution;

            int sensorWidth = leftIntr.SensorResolution.x;
            int sensorHeight = leftIntr.SensorResolution.y;
            double senderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;

            info = new QuestCameraInfo
            {
                Header = new MessageHeader
                {
                    MessageId = Guid.NewGuid().ToString("N"),
                    FrameId = 0,
                    UnityFrame = Time.frameCount,
                    SenderMonoMs = senderMonoMs,
                    CreatedUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    SchemaVersion = "v1",
                },
                IsSupported = PassthroughCameraAccess.IsSupported,
                LeftFx = leftIntr.FocalLength.x,
                LeftFy = leftIntr.FocalLength.y,
                LeftCx = leftIntr.PrincipalPoint.x,
                LeftCy = leftIntr.PrincipalPoint.y,
                RightFx = rightIntr.FocalLength.x,
                RightFy = rightIntr.FocalLength.y,
                RightCx = rightIntr.PrincipalPoint.x,
                RightCy = rightIntr.PrincipalPoint.y,
                BaselineM = Vector3.Distance(leftIntr.LensOffset.position, rightIntr.LensOffset.position),
                SensorWidth = sensorWidth,
                SensorHeight = sensorHeight,
                ActiveLeft = 0,
                ActiveTop = 0,
                ActiveRight = sensorWidth,
                ActiveBottom = sensorHeight,
                LeftRequestedWidth = leftCameraAccess.RequestedResolution.x,
                LeftRequestedHeight = leftCameraAccess.RequestedResolution.y,
                RightRequestedWidth = rightCameraAccess.RequestedResolution.x,
                RightRequestedHeight = rightCameraAccess.RequestedResolution.y,
                CurrentWidth = leftRes.x,
                CurrentHeight = leftRes.y,
                MaxFramerate = leftCameraAccess.MaxFramerate,
                LeftLensPose = ToLensPose(leftIntr.LensOffset),
                RightLensPose = ToLensPose(rightIntr.LensOffset),
            };
            return true;
        }

        private static LensPose ToLensPose(Pose pose)
        {
            return new LensPose
            {
                Position = new Vec3
                {
                    X = pose.position.x,
                    Y = pose.position.y,
                    Z = pose.position.z,
                },
                Rotation = new Quat
                {
                    X = pose.rotation.x,
                    Y = pose.rotation.y,
                    Z = pose.rotation.z,
                    W = pose.rotation.w,
                },
            };
        }
    }
}
