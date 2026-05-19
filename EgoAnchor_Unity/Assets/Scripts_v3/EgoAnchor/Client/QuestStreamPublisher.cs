using EgoAnchor.V3.Protocol;
using EgoAnchor.V3.Protocol.Generated;
using EgoAnchor.V3.Quest;
using EgoAnchor.V3.Transport;
using Google.Protobuf;
using NetMQ;
using UnityEngine;

namespace EgoAnchor.V3.Client
{
    /// <summary>
    /// Quest 传感器流发布组件。
    ///
    /// 本组件是 v3 通信 demo 的 Unity 场景入口，负责把：
    /// - Quest/StereoFrameSource 采集到的 QuestStereoFrame；
    /// - Quest/CameraInfoSource 采集到的 QuestCameraInfo；
    /// 按不同 topic 通过 Transport/ZmqTopicPublisher 发给 Python v3。
    /// </summary>
    public sealed class QuestStreamPublisher : MonoBehaviour
    {
        /// <summary>Python 接收端 IP。</summary>
        [Header("Network / ZMQ")]
        [Tooltip("Python v3 数据接收端 IP。Quest 真机建议通过 UI/PlayerPrefs 注入开发机局域网 IP，避免长期写死。")]
        [SerializeField] private string serverIp = "127.0.0.1";

        /// <summary>是否启动时从 PlayerPrefs 读取 Python 接收端 IP。</summary>
        [Tooltip("是否在启动时从 PlayerPrefs 读取 Python 接收端 IP。用于后续 UI 配置注入，避免长期写死 IP。")]
        [SerializeField] private bool loadServerIpFromPlayerPrefs = true;

        /// <summary>保存 Python IP 的 PlayerPrefs key。</summary>
        [Tooltip("保存 Python 接收端 IP 的 PlayerPrefs key。UI 设置面板应写入同一个 key。")]
        [SerializeField] private string serverIpPlayerPrefsKey = "EgoAnchor.V3.DataPlaneServerIp";

        /// <summary>Python 接收端端口。</summary>
        [Tooltip("Python v3 数据接收端端口。默认 15557；不要回退到旧链路 5557。")]
        [Min(1)]
        [SerializeField] private int serverPort = 15557;

        /// <summary>ZMQ 发送高水位。</summary>
        [Tooltip("ZMQ 发送高水位。数值越小越倾向丢弃积压帧，适合 latest-only 实时视频流。")]
        [Min(1)]
        [SerializeField] private int sendHighWatermark = 5;

        /// <summary>Socket 关闭 linger 毫秒数。</summary>
        [Tooltip("Socket 关闭时等待未发送消息的毫秒数。Play Mode/应用退出建议保持 0，避免退出卡顿。")]
        [Min(0)]
        [SerializeField] private int socketLingerMs = 0;

        /// <summary>双目图像源。</summary>
        [Header("Quest Sources")]
        [Tooltip("Quest 双目图像源：读取左右 Passthrough texture、JPEG 编码，并记录 frame_id 对应的左目相机位姿。")]
        [SerializeField] private StereoFrameSource stereoSource;

        /// <summary>相机标定源。</summary>
        [Tooltip("Quest 相机标定源：读取左右相机 intrinsics、lens pose、分辨率和 baseline。")]
        [SerializeField] private CameraInfoSource cameraInfoSource;

        /// <summary>双目图像目标发送帧率。</summary>
        [Header("Send Rates")]
        [Tooltip("双目图像目标发送帧率。实际帧率受相机刷新、JPEG 编码耗时和 ZMQ 发送结果影响。")]
        [Min(1)]
        [SerializeField] private int stereoFps = 30;

        /// <summary>相机标定发送频率。</summary>
        [Tooltip("相机标定发送频率。标定低频刷新即可；Python 端按 topic 独立缓存 latest camera_info。")]
        [Min(0.1f)]
        [SerializeField] private float cameraInfoFps = 1f;

        /// <summary>是否输出聚合统计。</summary>
        [Header("Debug")]
        [Tooltip("是否周期性输出发送统计。高频路径默认只打印聚合统计，避免每帧日志拖慢 Quest。")]
        [SerializeField] private bool logStats = true;

        /// <summary>统计输出间隔。</summary>
        [Tooltip("累计发送/丢弃/采集失败达到多少条后打印一次统计。")]
        [Min(1)]
        [SerializeField] private int statsIntervalFrames = 120;

        /// <summary>底层 ZMQ topic 发布器。</summary>
        private ZmqTopicPublisher publisher;

        /// <summary>上次发送 stereo 的 Unity 单调时间。</summary>
        private double lastStereoSendTime;

        /// <summary>上次发送 camera_info 的 Unity 单调时间。</summary>
        private double lastCameraInfoSendTime;

        /// <summary>累计成功发送 stereo 数。</summary>
        private int sentStereo;

        /// <summary>累计成功发送 camera_info 数。</summary>
        private int sentCameraInfo;

        /// <summary>累计发送失败或队列满丢弃数。</summary>
        private int dropped;

        /// <summary>累计采集失败数。</summary>
        private int captureFailed;

        /// <summary>上次打印统计时的总计数。</summary>
        private int lastLoggedTotal;

        /// <summary>
        /// 更新 Python 接收端 IP，并可选择写入 PlayerPrefs。
        /// </summary>
        /// <param name="ip">新的 Python 接收端 IP。</param>
        /// <param name="persistToPlayerPrefs">是否持久化到 PlayerPrefs。</param>
        public void SetServerIp(string ip, bool persistToPlayerPrefs)
        {
            if (string.IsNullOrWhiteSpace(ip))
            {
                return;
            }

            serverIp = ip.Trim();
            if (persistToPlayerPrefs && !string.IsNullOrEmpty(serverIpPlayerPrefsKey))
            {
                PlayerPrefs.SetString(serverIpPlayerPrefsKey, serverIp);
                PlayerPrefs.Save();
            }
        }

        /// <summary>
        /// Unity Start：加载持久化配置并连接 ZMQ。
        /// </summary>
        private void Start()
        {
            LoadServerIpFromPlayerPrefs();
            publisher = new ZmqTopicPublisher();
            publisher.Connect(serverIp, serverPort, sendHighWatermark, socketLingerMs);
        }

        /// <summary>
        /// Unity Update：按配置频率发送 camera_info 与 stereo。
        /// </summary>
        private void Update()
        {
            double now = Time.realtimeSinceStartupAsDouble;
            TrySendCameraInfo(now);
            TrySendStereo(now);
            MaybeLogStats();
        }

        /// <summary>
        /// 按目标帧率尝试发送一帧 stereo。
        /// </summary>
        private void TrySendStereo(double now)
        {
            double interval = 1.0 / Mathf.Max(1, stereoFps);
            if (now - lastStereoSendTime < interval)
            {
                return;
            }
            lastStereoSendTime = now;

            if (stereoSource == null || !stereoSource.TryCapture(out QuestStereoFrame frame))
            {
                captureFailed++;
                return;
            }

            bool sent = publisher != null && publisher.TrySend(SubjectNames.QuestStereo, frame.ToByteArray());
            if (sent)
            {
                sentStereo++;
            }
            else
            {
                dropped++;
            }
        }

        /// <summary>
        /// 按低频节奏发送相机标定。
        /// </summary>
        private void TrySendCameraInfo(double now)
        {
            double interval = 1.0 / Mathf.Max(0.1f, cameraInfoFps);
            if (now - lastCameraInfoSendTime < interval)
            {
                return;
            }
            lastCameraInfoSendTime = now;

            if (cameraInfoSource == null || !cameraInfoSource.TryCapture(out QuestCameraInfo info))
            {
                captureFailed++;
                return;
            }

            bool sent = publisher != null && publisher.TrySend(SubjectNames.QuestCameraInfo, info.ToByteArray());
            if (sent)
            {
                sentCameraInfo++;
            }
            else
            {
                dropped++;
            }
        }

        /// <summary>
        /// 聚合输出发送统计。
        /// </summary>
        private void MaybeLogStats()
        {
            if (!logStats || statsIntervalFrames <= 0)
            {
                return;
            }

            int total = sentStereo + sentCameraInfo + dropped + captureFailed;
            if (total > 0 && total - lastLoggedTotal >= statsIntervalFrames)
            {
                lastLoggedTotal = total;
                Debug.Log(
                    $"[V3 QuestStreamPublisher] stereo={sentStereo}, camera_info={sentCameraInfo}, " +
                    $"dropped={dropped}, captureFailed={captureFailed}, endpoint={publisher?.Endpoint}",
                    this);
            }
        }

        /// <summary>
        /// 从 PlayerPrefs 读取 Python 接收端 IP。
        /// </summary>
        private void LoadServerIpFromPlayerPrefs()
        {
            if (!loadServerIpFromPlayerPrefs || string.IsNullOrEmpty(serverIpPlayerPrefsKey))
            {
                return;
            }

            string storedIp = PlayerPrefs.GetString(serverIpPlayerPrefsKey, string.Empty);
            if (!string.IsNullOrWhiteSpace(storedIp))
            {
                serverIp = storedIp.Trim();
            }
        }

        /// <summary>
        /// Unity 销毁组件时释放 ZMQ。
        /// </summary>
        private void OnDestroy()
        {
            DisposePublisher();
            NetMQConfig.Cleanup(false);
        }

        /// <summary>
        /// 应用退出时释放 ZMQ。
        /// </summary>
        private void OnApplicationQuit()
        {
            DisposePublisher();
        }

        /// <summary>
        /// 统一释放 publisher，确保可重复调用。
        /// </summary>
        private void DisposePublisher()
        {
            publisher?.Dispose();
            publisher = null;
        }
    }
}