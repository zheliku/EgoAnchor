using System;
using EgoAnchor.Diagnostics;
using EgoAnchor.Protocol.Generated;
using Meta.XR;
using UnityEngine;

namespace EgoAnchor.Quest
{
    /// <summary>
    /// Quest 相机标定信息源。
    ///
    /// 本类只负责从 PassthroughCameraAccess 读取 intrinsics、lens pose 和分辨率，
    /// 并构造 QuestCameraInfo Protobuf。网络发送由 Client 层负责。
    /// </summary>
    public sealed class CameraInfoSource : MonoBehaviour
    {
        /// <summary>统一日志通道。</summary>
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<CameraInfoSource>();

        /// <summary>低频标定采集失败的日志限频间隔。</summary>
        private const int FailureLogInterval = 30;

        /// <summary>左目 PassthroughCameraAccess。</summary>
        [Header("Passthrough Cameras")]
        [Tooltip("左目 PassthroughCameraAccess，用于读取左目 intrinsics、lens pose 和当前分辨率。")]
        [SerializeField] private PassthroughCameraAccess leftCameraAccess;

        /// <summary>右目 PassthroughCameraAccess。</summary>
        [Tooltip("右目 PassthroughCameraAccess，用于读取右目 intrinsics、lens pose，并与左目计算 baseline。")]
        [SerializeField] private PassthroughCameraAccess rightCameraAccess;

        /// <summary>读取 Quest camera_info 失败次数。</summary>
        private int captureFailures;

        /// <summary>
        /// 尝试读取当前 Quest camera_info。
        /// </summary>
        /// <param name="info">成功时输出可直接序列化发送的 QuestCameraInfo。</param>
        /// <returns>左右相机是否可用且标定读取成功。</returns>
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

            try
            {
                PassthroughCameraAccess.CameraIntrinsics leftIntr = leftCameraAccess.Intrinsics;
                PassthroughCameraAccess.CameraIntrinsics rightIntr = rightCameraAccess.Intrinsics;
                Vector2Int leftRes = leftCameraAccess.CurrentResolution;

                int sensorWidth = leftIntr.SensorResolution.x;
                int sensorHeight = leftIntr.SensorResolution.y;
                double senderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;

                info = new QuestCameraInfo
                {
                    Header = QuestStreamSession.BuildHeader(0, Time.frameCount, senderMonoMs),
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
                    RightLensPose = ToLensPose(rightIntr.LensOffset)
                };
            }
            catch (Exception exc)
            {
                captureFailures++;
                LogCaptureFailure(captureFailures, exc);
                info = null;
                return false;
            }

            // 当前协议只有一组 current_width/current_height 字段，按旧约定填左目当前分辨率。
            // 如果左右分辨率未来可能不同，应在 proto 中非破坏性追加右目 current 字段。
            return true;
        }

        /// <summary>
        /// 限频输出标定采集失败日志，避免 Quest 启动/权限边界每帧刷屏。
        /// </summary>
        private void LogCaptureFailure(int count, Exception exc)
        {
            if (count <= 3 || count % FailureLogInterval == 0)
            {
                Log.Warning($"camera_info capture failed count={count}, reason={exc.Message}", this);
            }
        }

        /// <summary>
        /// 将 Unity Pose 转为协议中的 LensPose。字段保持 Unity 坐标语义。
        /// </summary>
        private static LensPose ToLensPose(Pose pose)
        {
            return new LensPose
            {
                Position = new Vec3
                {
                    X = pose.position.x,
                    Y = pose.position.y,
                    Z = pose.position.z
                },
                Rotation = new Quat
                {
                    X = pose.rotation.x,
                    Y = pose.rotation.y,
                    Z = pose.rotation.z,
                    W = pose.rotation.w
                }
            };
        }
    }
}
