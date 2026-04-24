using System;
using Meta.XR;
using UnityEngine;
using UnityEngine.Events;

[Serializable]
public class FrameIdEvent : UnityEvent<long> { }

/// <summary>
/// Quest 双目图像编码器。
///
/// 输入：左右 Passthrough Camera 纹理。
/// 输出：单帧 payload（MessagePack，包含 left_image_jpeg/right_image_jpeg/frame_id/sender_mono_ms/unity_frame）。
///
/// 注意：
/// - 本组件只负责编码，不负责发送。
/// - 发送节奏由 PayloadSender 控制。
/// </summary>
public class QuestStereoEncoder : BaseEncoder
{
    [SerializeField] private PassthroughCameraAccess leftCameraAccess;
    [SerializeField] private PassthroughCameraAccess rightCameraAccess;
    [Range(0.25f, 1f)]
    [SerializeField] private float outputScale = 1f;
    [Range(30, 100)]
    [SerializeField] private int jpegQuality = 95;
    [Header("Debug")]
    [SerializeField] private bool enableVerboseDebugLog = true;
    [Range(1, 300)]
    [SerializeField] private int debugLogInterval = 30;

    [Header("Events")]
    [Tooltip("编码出有效帧后触发，参数为 frame_id。可在 Inspector 绑定监听。")]
    public FrameIdEvent OnFrameEncoded = new FrameIdEvent();

    private RenderTexture _leftRenderTexture;
    private RenderTexture _rightRenderTexture;
    private Texture2D _leftReadbackTexture;
    private Texture2D _rightReadbackTexture;
    private bool _hasLoggedTextureTypes;
    private int _encodedFrameCount;
    private double _encodeTimeAccMs;
    private long _payloadBytesAcc;
    private long _senderFrameId;

    // 失败原因计数（用于选择打印频率，避免日志洪水）。
    private int _failCamNullCount;
    private int _failNotPlayingCount;
    private int _failTexNullCount;
    private int _failJpegNullCount;
    private int _failSerializeNullCount;
    private float _lastFailLogTime;

    /// <summary>
    /// 从 Quest 左右相机抓取当前帧并编码为单帧 payload。
    /// </summary>
    public override bool TryEncodePayload(out byte[] payload)
    {
        double encodeStart = Time.realtimeSinceStartupAsDouble;
        payload = null;

        if (leftCameraAccess == null || rightCameraAccess == null)
        {
            _failCamNullCount++;
            MaybeLogFailure();
            return false;
        }

        if (!leftCameraAccess.IsPlaying || !rightCameraAccess.IsPlaying)
        {
            _failNotPlayingCount++;
            MaybeLogFailure();
            return false;
        }

        Texture leftTexture = leftCameraAccess.GetTexture();
        Texture rightTexture = rightCameraAccess.GetTexture();

        if (leftTexture == null || rightTexture == null)
        {
            _failTexNullCount++;
            MaybeLogFailure();
            return false;
        }

        LogTextureTypesOnce(leftTexture, rightTexture);

        EnsureCaptureBuffers(leftTexture, rightTexture);

        double senderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
        long frameId = ++_senderFrameId;
        OnFrameEncoded?.Invoke(frameId);

        BlitToRenderTarget(leftTexture, _leftRenderTexture);
        BlitToRenderTarget(rightTexture, _rightRenderTexture);

        // 新协议：左右图分别编码。
        // 这样接收端可以直接解码成 left/right，避免“发送前拼接 + 接收后拆分”的冗余流程。
        byte[] leftJpeg = EncodeRenderTextureToJpeg(_leftRenderTexture, _leftReadbackTexture);
        byte[] rightJpeg = EncodeRenderTextureToJpeg(_rightRenderTexture, _rightReadbackTexture);
        if (leftJpeg == null || rightJpeg == null)
        {
            _failJpegNullCount++;
            MaybeLogFailure();
            return false;
        }

        QuestStereoMsg message = new QuestStereoMsg
        {
            left_image_jpeg = leftJpeg,
            right_image_jpeg = rightJpeg,
            frame_id = frameId,
            sender_mono_ms = senderMonoMs,
            unity_frame = Time.frameCount,
        };

        payload = message.Serialize();
        if (payload == null)
        {
            _failSerializeNullCount++;
            MaybeLogFailure();
            return false;
        }

        string encodePath = "DualImagePayload";
        LogEncodeStats(payload, encodePath, encodeStart);
        return true;
    }

    /// <summary>
    /// 每 2 秒最多打印一次失败统计，帮助定位为何 stereo 发不出去。
    /// </summary>
    private void MaybeLogFailure()
    {
        float now = Time.realtimeSinceStartup;
        if (now - _lastFailLogTime < 2.0f)
        {
            return;
        }
        _lastFailLogTime = now;
        Debug.LogWarning(
            $"[QuestStereoEncoder] TryEncode failures in last 2s: " +
            $"CamNull={_failCamNullCount}, NotPlaying={_failNotPlayingCount}, " +
            $"GetTextureNull={_failTexNullCount}, JpegNull={_failJpegNullCount}, " +
            $"SerializeNull={_failSerializeNullCount}. " +
            $"LeftPlaying={(leftCameraAccess != null && leftCameraAccess.IsPlaying)}, " +
            $"RightPlaying={(rightCameraAccess != null && rightCameraAccess.IsPlaying)}."
        );
        _failCamNullCount = 0;
        _failNotPlayingCount = 0;
        _failTexNullCount = 0;
        _failJpegNullCount = 0;
        _failSerializeNullCount = 0;
    }

    private void Awake()
    {
        if (OnFrameEncoded == null)
        {
            OnFrameEncoded = new FrameIdEvent();
        }
    }

    /// <summary>
    /// 确保左右采集缓冲区尺寸与源纹理一致。
    /// </summary>
    private void EnsureCaptureBuffers(Texture leftTexture, Texture rightTexture)
    {
        int leftWidth = Mathf.Max(1, Mathf.RoundToInt(leftTexture.width * outputScale));
        int leftHeight = Mathf.Max(1, Mathf.RoundToInt(leftTexture.height * outputScale));
        int rightWidth = Mathf.Max(1, Mathf.RoundToInt(rightTexture.width * outputScale));
        int rightHeight = Mathf.Max(1, Mathf.RoundToInt(rightTexture.height * outputScale));

        EnsureBuffer(ref _leftRenderTexture, ref _leftReadbackTexture, leftWidth, leftHeight);
        EnsureBuffer(ref _rightRenderTexture, ref _rightReadbackTexture, rightWidth, rightHeight);
    }

    private void EnsureBuffer(
        ref RenderTexture renderTexture,
        ref Texture2D readbackTexture,
        int width,
        int height)
    {
        bool needsCreate =
            renderTexture == null ||
            readbackTexture == null ||
            renderTexture.width != width ||
            renderTexture.height != height;

        if (!needsCreate)
        {
            return;
        }

        ReleaseBuffer(ref renderTexture, ref readbackTexture);

        renderTexture = new RenderTexture(width, height, 0, RenderTextureFormat.ARGB32);
        readbackTexture = new Texture2D(width, height, TextureFormat.RGB24, false);
    }

    private static void BlitToRenderTarget(Texture source, RenderTexture target)
    {
        if (source == null || target == null)
        {
            return;
        }

        Graphics.Blit(source, target);
    }

    private void LogTextureTypesOnce(Texture leftTexture, Texture rightTexture)
    {
        if (_hasLoggedTextureTypes)
        {
            return;
        }

        _hasLoggedTextureTypes = true;
        string leftType = leftTexture.GetType().Name;
        string rightType = rightTexture.GetType().Name;
        Debug.Log($"[QuestStereoEncoder] LeftType={leftType}, RightType={rightType}, OutputScale={outputScale:F2}, Codec=JPEG(q={jpegQuality})");
        if (enableVerboseDebugLog)
        {
            LogTextureDetails("Left", leftTexture);
            LogTextureDetails("Right", rightTexture);
        }
    }

    private void LogTextureDetails(string label, Texture texture)
    {
        if (texture == null)
        {
            Debug.Log($"[QuestStereoEncoder] {label} Texture=null");
            return;
        }

        string baseInfo =
            $"[QuestStereoEncoder] {label} TexInfo type={texture.GetType().Name}, size={texture.width}x{texture.height}, dimension={texture.dimension}, graphicsFormat={texture.graphicsFormat}, mipCount={texture.mipmapCount}, filter={texture.filterMode}";

        if (texture is RenderTexture rt)
        {
            Debug.Log(
                baseInfo +
                $", rtFormat={rt.format}, depth={rt.depth}, msaa={rt.antiAliasing}, useMipMap={rt.useMipMap}, sRGB={rt.sRGB}"
            );
            return;
        }

        if (texture is Texture2D t2d)
        {
            Debug.Log(
                baseInfo +
                $", tex2DFormat={t2d.format}, readable={t2d.isReadable}"
            );
            return;
        }

        Debug.Log(baseInfo);
    }

    private void LogEncodeStats(byte[] payload, string encodePath, double encodeStart)
    {
        if (!enableVerboseDebugLog)
        {
            return;
        }

        _encodedFrameCount++;
        double elapsedMs = (Time.realtimeSinceStartupAsDouble - encodeStart) * 1000.0;
        _encodeTimeAccMs += elapsedMs;

        long bytes = payload == null ? 0 : payload.LongLength;
        _payloadBytesAcc += bytes;

        int interval = Mathf.Max(1, debugLogInterval);
        if (_encodedFrameCount % interval != 0)
        {
            return;
        }

        double avgEncodeMs = _encodeTimeAccMs / interval;
        double avgPayloadKB = (_payloadBytesAcc / (double)interval) / 1024.0;

        Debug.Log(
            $"[QuestStereoEncoder] EncodeStats frames={_encodedFrameCount}, mode={encodePath}, avgEncode={avgEncodeMs:F2}ms, avgPayload={avgPayloadKB:F1}KB, codec=Jpeg"
        );

        _encodeTimeAccMs = 0.0;
        _payloadBytesAcc = 0;
    }

    /// <summary>
    /// 将单个 RenderTexture 回读并编码为 JPEG。
    ///
    /// 设计说明：
    /// - 这里复用传入的 readback 纹理，避免每帧 new Texture2D 产生 GC 压力。
    /// - 使用 RenderTexture.active + ReadPixels 的同步回读方式，逻辑直观稳定。
    /// </summary>
    private byte[] EncodeRenderTextureToJpeg(
        RenderTexture source,
        Texture2D readbackTexture)
    {
        if (source == null || readbackTexture == null)
        {
            return null;
        }

        RenderTexture previous = RenderTexture.active;
        RenderTexture.active = source;
        readbackTexture.ReadPixels(new Rect(0, 0, source.width, source.height), 0, 0, false);
        readbackTexture.Apply(false, false);
        RenderTexture.active = previous;
        return EncodeTexture(readbackTexture);
    }

    private byte[] EncodeTexture(Texture2D texture)
    {
        if (texture == null)
        {
            return null;
        }

        return texture.EncodeToJPG(jpegQuality);
    }

    /// <summary>
    /// 释放一侧采集缓冲资源。
    /// </summary>
    private void ReleaseBuffer(ref RenderTexture renderTexture, ref Texture2D readbackTexture)
    {
        if (renderTexture != null)
        {
            renderTexture.Release();
            Destroy(renderTexture);
            renderTexture = null;
        }

        if (readbackTexture != null)
        {
            Destroy(readbackTexture);
            readbackTexture = null;
        }
    }

    /// <summary>
    /// 对象销毁时释放左右缓冲资源，防止纹理泄漏。
    /// </summary>
    private void OnDestroy()
    {
        ReleaseBuffer(ref _leftRenderTexture, ref _leftReadbackTexture);
        ReleaseBuffer(ref _rightRenderTexture, ref _rightReadbackTexture);
    }
}
