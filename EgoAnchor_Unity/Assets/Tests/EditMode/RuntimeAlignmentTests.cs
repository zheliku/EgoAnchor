using EgoAnchor.Alignment;
using EgoAnchor.Runtime;
using NUnit.Framework;
using UnityEngine;

namespace EgoAnchor.Tests
{
    /// <summary>验证采集时刻与到达时刻 world alignment 使用不同相机历史记录。</summary>
    public sealed class RuntimeAlignmentTests
    {
        /// <summary>同一 camera-space pose 在 source frame 与 latest camera pose 不同的历史中应产生不同 world 输出。</summary>
        [Test]
        public void CaptureTimeAndArrivalTimeUseDifferentCameraHistory()
        {
            GameObject historyObject = new GameObject("RuntimeAlignmentTests.FramePoseHistory");
            try
            {
                FramePoseHistory history = historyObject.AddComponent<FramePoseHistory>();
                history.Record(
                    frameId: 10,
                    leftCameraPose: new Pose(new Vector3(1f, 0f, 0f), Quaternion.identity),
                    rightCameraPose: Pose.identity,
                    centerCameraPose: Pose.identity,
                    imageMonoMs: 1000.0,
                    imageUnityFrame: 10,
                    imageTimeOffsetFrames: 0,
                    senderMonoMs: 1001.0,
                    senderUnityFrame: 10);
                history.Record(
                    frameId: 11,
                    leftCameraPose: new Pose(new Vector3(4f, 0f, 0f), Quaternion.identity),
                    rightCameraPose: Pose.identity,
                    centerCameraPose: Pose.identity,
                    imageMonoMs: 1100.0,
                    imageUnityFrame: 11,
                    imageTimeOffsetFrames: 0,
                    senderMonoMs: 1101.0,
                    senderUnityFrame: 11);

                CameraPoseFrameAligner aligner = new CameraPoseFrameAligner(
                    history,
                    CameraReference.Left,
                    AnchorPoseTransform.OpenCvToUnityDefault);
                Pose cameraPose = new Pose(new Vector3(0.2f, 0f, 1f), Quaternion.identity);

                Assert.That(
                    aligner.TryAlign(10, cameraPose, out Pose capturePose),
                    Is.True);
                Assert.That(
                    history.TryGetLatest(out FramePoseRecord latestRecord),
                    Is.True);
                Assert.That(
                    aligner.TryAlignWithCameraPose(
                        cameraPose,
                        latestRecord.LeftCameraPose,
                        CameraReference.Left,
                        out Pose arrivalPose),
                    Is.True);

                Assert.That(latestRecord.FrameId, Is.EqualTo(11));
                Assert.That(capturePose.position.x, Is.EqualTo(1.2f).Within(1e-5f));
                Assert.That(arrivalPose.position.x, Is.EqualTo(4.2f).Within(1e-5f));
                Assert.That(capturePose.position, Is.Not.EqualTo(arrivalPose.position));
            }
            finally
            {
                Object.DestroyImmediate(historyObject);
            }
        }
        /// <summary>默认 runtime 语义必须是采集时刻对齐，并公开稳定的配置摘要。</summary>
        [Test]
        public void WorldAlignmentModeDefaultsToCaptureTime()
        {
            GameObject runtimeObject = new GameObject("RuntimeAlignmentTests.PoseToAnchorRuntime");
            try
            {
                PoseToAnchorRuntime runtime = runtimeObject.AddComponent<PoseToAnchorRuntime>();

                Assert.That(runtime.WorldAlignmentModeName, Is.EqualTo(nameof(WorldAlignmentMode.CaptureTime)));
                Assert.That(runtime.UsesCaptureTimeAlignment, Is.True);
            }
            finally
            {
                Object.DestroyImmediate(runtimeObject);
            }
        }
    }
}
