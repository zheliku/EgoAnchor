using System;
using EgoAnchor.Protocol.V1;
using EgoAnchor.V2.Protocol;
using EgoAnchor.V2.Transport;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.V2.Client
{
    /// <summary>
    /// v2 本地图片流发布器。
    ///
    /// 这是第一阶段手动联调组件：不依赖 Quest PassthroughCamera，直接把 Inspector
    /// 中配置的 Texture2D 编码为 QuestStereoFrame protobuf，通过 NATS 发给 Python。
    /// Python 端 `local_image_stream_server.py` 会订阅并显示图像。
    /// </summary>
    public class LocalImageStreamPublisher : MonoBehaviour
    {
        [SerializeField] private NatsConnection connection;
        [SerializeField] private Texture2D leftImage;
        [SerializeField] private Texture2D rightImage;
        [SerializeField] private string clientId = "unity-local-image";
        [SerializeField] private string anchorId = "main";
        [SerializeField] private float publishFps = 2f;
        [Range(30, 100)]
        [SerializeField] private int jpegQuality = 90;
        [SerializeField] private bool publishOnStart = true;
        [SerializeField] private bool enableStatsLog = true;
        [SerializeField] private float statsLogIntervalSeconds = 2f;
        [SerializeField] private bool cacheEncodedImages = true;

        private long _frameId;
        private double _nextPublishAt;
        private double _statsWindowStart;
        private int _producedInWindow;
        private int _enqueuedInWindow;
        private long _payloadBytesInWindow;
        private int _failMissingConnection;
        private int _failMissingImage;
        private int _failEncode;
        private int _failPublish;
        private Texture2D _cachedLeftImage;
        private Texture2D _cachedRightImage;
        private int _cachedJpegQuality;
        private byte[] _cachedLeftJpeg;
        private byte[] _cachedRightJpeg;

        private void Start()
        {
            if (publishOnStart)
            {
                PublishOnce();
            }
        }

        private void Update()
        {
            if (publishFps > 0f && Time.realtimeSinceStartupAsDouble >= _nextPublishAt)
            {
                _nextPublishAt = Time.realtimeSinceStartupAsDouble + 1.0 / publishFps;
                PublishOnce();
            }

            MaybeLogStats();
        }

        [ContextMenu("V2 Publish Local Image Once")]
        public void PublishOnceFromContextMenu()
        {
            PublishOnce();
        }

        private void PublishOnce()
        {
            if (connection == null)
            {
                _failMissingConnection++;
                return;
            }

            if (leftImage == null)
            {
                _failMissingImage++;
                return;
            }

            try
            {
                Texture2D right = rightImage != null ? rightImage : leftImage;
                if (!TryGetEncodedImages(right, out byte[] leftJpeg, out byte[] rightJpeg))
                {
                    _failEncode++;
                    return;
                }

                long frameId = ++_frameId;
                QuestStereoFrame frame = new QuestStereoFrame
                {
                    Header = CreateHeader(frameId),
                    LeftImageJpeg = ByteString.CopyFrom(leftJpeg),
                    RightImageJpeg = ByteString.CopyFrom(rightJpeg),
                    LeftWidth = leftImage.width,
                    LeftHeight = leftImage.height,
                    RightWidth = right.width,
                    RightHeight = right.height,
                    JpegQuality = jpegQuality,
                };

                byte[] payload = frame.ToByteArray();
                _producedInWindow++;
                if (connection.PublishLatest(SubjectNames.QuestStereo, payload))
                {
                    _enqueuedInWindow++;
                    _payloadBytesInWindow += payload.Length;
                }
                else
                {
                    _failPublish++;
                }
            }
            catch (Exception e)
            {
                _failPublish++;
                Debug.LogWarning($"[EgoAnchorV2] Local image publish failed: {e.Message}", this);
            }
        }

        private MessageHeader CreateHeader(long frameId)
        {
            return new MessageHeader
            {
                MessageId = Guid.NewGuid().ToString("N"),
                ClientId = clientId,
                AnchorId = anchorId,
                FrameId = frameId,
                UnityFrame = Time.frameCount,
                SenderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0,
                CreatedUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                SchemaVersion = "v1",
            };
        }

        private byte[] EncodeTextureToJpeg(Texture2D source)
        {
            // Texture2D.EncodeToJPG 不支持压缩纹理。这里先把任意 Texture2D
            // Blit/ReadPixels 到 RGB24 临时纹理，再编码，避免 Inspector 拖入压缩贴图时报错。
            RenderTexture previous = RenderTexture.active;
            RenderTexture rt = RenderTexture.GetTemporary(source.width, source.height, 0, RenderTextureFormat.ARGB32);
            Texture2D readable = null;
            try
            {
                Graphics.Blit(source, rt);
                RenderTexture.active = rt;
                readable = new Texture2D(source.width, source.height, TextureFormat.RGB24, false);
                readable.ReadPixels(new Rect(0, 0, source.width, source.height), 0, 0, false);
                readable.Apply(false, false);
                return readable.EncodeToJPG(jpegQuality);
            }
            finally
            {
                RenderTexture.active = previous;
                RenderTexture.ReleaseTemporary(rt);
                if (readable != null)
                {
                    Destroy(readable);
                }
            }
        }

        private bool TryGetEncodedImages(Texture2D right, out byte[] leftJpeg, out byte[] rightJpeg)
        {
            if (cacheEncodedImages &&
                _cachedLeftImage == leftImage &&
                _cachedRightImage == right &&
                _cachedJpegQuality == jpegQuality &&
                _cachedLeftJpeg != null &&
                _cachedRightJpeg != null)
            {
                leftJpeg = _cachedLeftJpeg;
                rightJpeg = _cachedRightJpeg;
                return true;
            }

            leftJpeg = EncodeTextureToJpeg(leftImage);
            rightJpeg = EncodeTextureToJpeg(right);
            bool ok = leftJpeg != null && rightJpeg != null && leftJpeg.Length > 0 && rightJpeg.Length > 0;
            if (ok && cacheEncodedImages)
            {
                _cachedLeftImage = leftImage;
                _cachedRightImage = right;
                _cachedJpegQuality = jpegQuality;
                _cachedLeftJpeg = leftJpeg;
                _cachedRightJpeg = rightJpeg;
            }
            return ok;
        }

        private void MaybeLogStats()
        {
            if (!enableStatsLog)
            {
                return;
            }

            double now = Time.realtimeSinceStartupAsDouble;
            if (_statsWindowStart <= 0.0)
            {
                _statsWindowStart = now;
                return;
            }

            double elapsed = now - _statsWindowStart;
            if (elapsed < Mathf.Max(0.5f, statsLogIntervalSeconds))
            {
                return;
            }

            NatsConnection.LatestPublishStats netStats = connection != null
                ? connection.GetLatestPublishStats(SubjectNames.QuestStereo, true)
                : NatsConnection.LatestPublishStats.Empty;
            double producedFps = _producedInWindow / Math.Max(elapsed, 1e-6);
            double sentFps = netStats.Sent / Math.Max(elapsed, 1e-6);
            double avgKb = _enqueuedInWindow > 0 ? (_payloadBytesInWindow / 1024.0) / _enqueuedInWindow : 0.0;
            Debug.Log(
                $"[EgoAnchorV2] LocalImageStats produced={_producedInWindow} ({producedFps:F1}fps) " +
                $"enqueued={_enqueuedInWindow} sent={netStats.Sent} ({sentFps:F1}fps) overwritten={netStats.Overwritten} " +
                $"timeout={netStats.TimedOut} failed={netStats.Failed} avgPayload={avgKb:F1}KB " +
                $"fail conn/img/enc/pub={_failMissingConnection}/{_failMissingImage}/{_failEncode}/{_failPublish}" +
                (string.IsNullOrEmpty(netStats.LastError) ? string.Empty : $" lastNetError={netStats.LastError}"),
                this);

            _statsWindowStart = now;
            _producedInWindow = 0;
            _enqueuedInWindow = 0;
            _payloadBytesInWindow = 0;
            _failMissingConnection = 0;
            _failMissingImage = 0;
            _failEncode = 0;
            _failPublish = 0;
        }
    }
}
