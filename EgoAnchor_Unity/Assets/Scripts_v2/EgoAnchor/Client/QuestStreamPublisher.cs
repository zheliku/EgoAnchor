using EgoAnchor.Protocol.V1;
using EgoAnchor.V2.Protocol;
using EgoAnchor.V2.Quest;
using EgoAnchor.V2.Transport;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.V2.Client
{
    /// <summary>
    /// Quest 传感器流发布组件：把 Quest 侧采集到的双目图像和相机标定发送给 Python v2。
    ///
    /// 命名说明：早期类名为 QuestDataPlanePublisher。data plane 指“高频数据面”，
    /// 用来和 NATS 的 control plane（命令/状态/心跳）区分；但本组件更直观的职责是
    /// 发布 Quest sensor stream，因此改名为 QuestStreamPublisher。
    ///
    /// 目录职责：
    /// - Quest/ 下的 StereoFrameSource、CameraInfoSource 只负责采集和构造 Protobuf。
    /// - Transport/ 下的 ZmqTopicPublisher 只负责 ZMQ socket 和 topic payload 发送。
    /// - 本 Client 组件负责把“数据源 + 传输 + 发送频率 + 统计”组合成 Unity 场景可挂载组件。
    /// </summary>
    public sealed class QuestStreamPublisher : MonoBehaviour
    {
        [Header("Network / ZMQ")]
        [Tooltip("Python v2 数据接收端 IP。127.0.0.1 仅适合本机调试；Quest 真机建议后续由 UI/PlayerPrefs 注入，避免写死 IP。")]
        [SerializeField] private string serverIp = "127.0.0.1";

        [Tooltip("Python v2 数据接收端端口。默认 15557；不要回退到旧链路的 5557。")]
        [Min(1)]
        [SerializeField] private int serverPort = 15557;

        [Tooltip("ZMQ 发送高水位。数值越小越倾向丢弃积压帧，适合 latest-only 实时视频流。")]
        [Min(1)]
        [SerializeField] private int sendHighWatermark = 5;

        [Tooltip("Socket 关闭时等待未发送消息的毫秒数。Play Mode/应用退出建议保持 0，避免退出卡顿。")]
        [Min(0)]
        [SerializeField] private int socketLingerMs = 0;

        [Header("Quest Sources")]
        [Tooltip("Quest 双目图像源：读取左右 Passthrough texture、JPEG 编码，并记录 frame_id 对应的左目相机位姿。")]
        [SerializeField] private StereoFrameSource stereoSource;

        [Tooltip("Quest 相机标定源：读取左右相机 intrinsics、lens pose、分辨率和 baseline。")]
        [SerializeField] private CameraInfoSource cameraInfoSource;

        [Header("Send Rates")]
        [Tooltip("双目图像目标发送帧率。实际帧率还受相机刷新、JPEG 编码耗时和 ZMQ 发送结果影响。")]
        [Min(1)]
        [SerializeField] private int stereoFps = 30;

        [Tooltip("相机标定发送频率。标定低频刷新即可；Python 端按 topic 独立缓存 latest camera_info。")]
        [Min(0.1f)]
        [SerializeField] private float cameraInfoFps = 1f;

        [Header("Debug")]
        [Tooltip("是否周期性输出发送统计。高频路径默认只打印聚合统计，避免每帧日志拖慢 Quest。")]
        [SerializeField] private bool logStats = true;

        [Tooltip("累计发送/丢弃/采集失败达到多少条后打印一次统计。")]
        [Min(1)]
        [SerializeField] private int statsIntervalFrames = 120;

        private ZmqTopicPublisher _publisher;
        private double _lastStereoSendTime;
        private double _lastCameraInfoSendTime;
        private int _sentStereo;
        private int _sentCameraInfo;
        private int _dropped;
        private int _captureFailed;
        private int _lastLoggedTotal;

        private void Start()
        {
            _publisher = new ZmqTopicPublisher();
            _publisher.Connect(serverIp, serverPort, sendHighWatermark, socketLingerMs);
        }

        private void Update()
        {
            double now = Time.realtimeSinceStartupAsDouble;
            TrySendCameraInfo(now);
            TrySendStereo(now);
            MaybeLogStats();
        }

        /// <summary>
        /// 按目标帧率尝试发送一帧 stereo。失败只更新统计，不阻塞主线程。
        /// </summary>
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

        /// <summary>
        /// 按低频节奏发送相机标定。camera_info 与 stereo 分 topic 发送，Python 端独立 latest cache。
        /// </summary>
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

        /// <summary>
        /// 聚合输出链路统计。使用累计间隔而非取模，避免某一帧 total 不变时重复刷屏。
        /// </summary>
        private void MaybeLogStats()
        {
            if (!logStats || statsIntervalFrames <= 0)
            {
                return;
            }

            int total = _sentStereo + _sentCameraInfo + _dropped + _captureFailed;
            if (total > 0 && total - _lastLoggedTotal >= statsIntervalFrames)
            {
                _lastLoggedTotal = total;
                Debug.Log(
                    $"[QuestStreamPublisher] stereo={_sentStereo}, camera_info={_sentCameraInfo}, " +
                    $"dropped={_dropped}, captureFailed={_captureFailed}, endpoint={_publisher?.Endpoint}",
                    this
                );
            }
        }

        private void OnDestroy()
        {
            DisposePublisher();
        }

        private void OnApplicationQuit()
        {
            DisposePublisher();
        }

        /// <summary>
        /// 统一释放 ZMQ publisher，保证 Destroy 和 ApplicationQuit 两条路径都安全可重复调用。
        /// </summary>
        private void DisposePublisher()
        {
            _publisher?.Dispose();
            _publisher = null;
        }
    }
}