using EgoAnchor.V2.Client;
using UnityEngine;

namespace EgoAnchor.V2.Adapters
{
    /// <summary>
    /// v2 网络组件与现有 FrameAlignedObjectAnchor 的桥接器。
    ///
    /// 目的：保持 anchor transform 逻辑不关心 NATS/Protobuf。
    /// - QuestStreamPublisher.OnFrameEncoded -> FrameAlignedObjectAnchor.HandleFrameEncoded
    /// - PoseResultReceiver.OnPoseReceived -> FrameAlignedObjectAnchor.ApplyCameraPose
    ///
    /// 这样旧 ZMQ 链路和 v2 NATS 链路可以复用同一套 frame-aligned anchor 应用逻辑。
    /// </summary>
    public class FrameAlignedAnchorBridge : MonoBehaviour
    {
        [SerializeField] private QuestStreamPublisher streamPublisher;
        [SerializeField] private PoseResultReceiver poseResultReceiver;
        [SerializeField] private FrameAlignedObjectAnchor anchor;

        private void OnEnable()
        {
            if (streamPublisher != null && anchor != null)
            {
                streamPublisher.OnFrameEncoded.AddListener(anchor.HandleFrameEncoded);
            }

            if (poseResultReceiver != null && anchor != null)
            {
                poseResultReceiver.OnPoseReceived.AddListener(anchor.ApplyCameraPose);
            }
        }

        private void OnDisable()
        {
            if (streamPublisher != null && anchor != null)
            {
                streamPublisher.OnFrameEncoded.RemoveListener(anchor.HandleFrameEncoded);
            }

            if (poseResultReceiver != null && anchor != null)
            {
                poseResultReceiver.OnPoseReceived.RemoveListener(anchor.ApplyCameraPose);
            }
        }
    }
}
