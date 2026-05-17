using EgoAnchor.Protocol.V1;
using EgoAnchor.V2.Protocol;
using EgoAnchor.V2.Quest;
using EgoAnchor.V2.Transport;
using Google.Protobuf;
using NetMQ;
using UnityEngine;

namespace EgoAnchor.V2.Client
{
    /// <summary>
    /// Quest -> Python v2 数据面发布 MonoBehaviour。
    ///
    /// 场景组织建议：
    /// - 在 v2 测试场景中新建一个 EgoAnchorClient GameObject。
    /// - 挂载 ZmqDataPlanePublisher 依赖由本组件内部创建，不需要单独挂脚本。
    /// - 同一 GameObject 或子对象挂 QuestStereoFrameSource、QuestCameraInfoSource、FramePoseHistory。
    /// - Inspector 中把 stereoSource/cameraInfoSource 引用绑定到本组件。
    ///
    /// 当前 demo 只发送：
    /// - egoanchor.v1.quest.stereo -> QuestStereoFrame
    /// - egoanchor.v1.quest.camera_info -> QuestCameraInfo
    /// </summary>
    public sealed class QuestDataPlanePublisher : MonoBehaviour
    {
        [Header("Network")]
        [SerializeField] private string serverIp = "127.0.0.1";
        [SerializeField] private int serverPort = 15557;
        [SerializeField] private int sendHighWatermark = 5;
        [SerializeField] private int socketLingerMs = 0;

        [Header("Sources")]
        [SerializeField] private QuestStereoFrameSource stereoSource;
        [SerializeField] private QuestCameraInfoSource cameraInfoSource;

        [Header("Rates")]
        [SerializeField] private int stereoFps = 30;
        [SerializeField] private float cameraInfoFps = 1f;

        [Header("Debug")]
        [SerializeField] private bool logStats = true;
        [SerializeField] private int statsIntervalFrames = 120;

        private ZmqDataPlanePublisher _publisher;
        private double _lastStereoSendTime;
        private double _lastCameraInfoSendTime;
        private int _sentStereo;
        private int _sentCameraInfo;
        private int _dropped;
        private int _captureFailed;

        private void Start()
        {
            _publisher = new ZmqDataPlanePublisher();
            _publisher.Connect(serverIp, serverPort, sendHighWatermark, socketLingerMs);
        }

        private void Update()
        {
            double now = Time.realtimeSinceStartupAsDouble;
            TrySendCameraInfo(now);
            TrySendStereo(now);
            MaybeLogStats();
        }

        private void TrySendStereo(double now)
        {
            double interval = 1.0 / Mathf.Max(1, stereoFps);
            if (now - _lastStereoSendTime < interval)
            {
                return;
            }
            _lastStereoSendTime = now;

            if (stereoSource == null || !stereoSource.TryCapture(out QuestStereoFrame frame))
            {
                _captureFailed++;
                return;
            }

            bool sent = _publisher != null && _publisher.TrySend(SubjectNames.QuestStereo, frame.ToByteArray());
            if (sent)
            {
                _sentStereo++;
            }
            else
            {
                _dropped++;
            }
        }

        private void TrySendCameraInfo(double now)
        {
            double interval = 1.0 / Mathf.Max(0.1f, cameraInfoFps);
            if (now - _lastCameraInfoSendTime < interval)
            {
                return;
            }
            _lastCameraInfoSendTime = now;

            if (cameraInfoSource == null || !cameraInfoSource.TryCapture(out QuestCameraInfo info))
            {
                _captureFailed++;
                return;
            }

            bool sent = _publisher != null && _publisher.TrySend(SubjectNames.QuestCameraInfo, info.ToByteArray());
            if (sent)
            {
                _sentCameraInfo++;
            }
            else
            {
                _dropped++;
            }
        }

        private void MaybeLogStats()
        {
            if (!logStats || statsIntervalFrames <= 0)
            {
                return;
            }

            int total = _sentStereo + _sentCameraInfo + _dropped + _captureFailed;
            if (total > 0 && total % statsIntervalFrames == 0)
            {
                Debug.Log(
                    $"[QuestDataPlanePublisher] stereo={_sentStereo}, camera_info={_sentCameraInfo}, " +
                    $"dropped={_dropped}, captureFailed={_captureFailed}, endpoint={_publisher?.Endpoint}",
                    this
                );
            }
        }

        private void OnDestroy()
        {
            _publisher?.Dispose();
            _publisher = null;
            NetMQConfig.Cleanup(false);
        }

        private void OnApplicationQuit()
        {
            _publisher?.Dispose();
            _publisher = null;
        }
    }
}
