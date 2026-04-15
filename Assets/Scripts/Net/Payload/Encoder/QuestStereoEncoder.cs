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
/// 输出：单帧 payload（MessagePack，包含 image_jpeg/frame_id/sender_mono_ms/unity_frame）。
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
    private RenderTexture _packedRenderTexture;
    private Texture2D _leftReadbackTexture;
    private Texture2D _rightReadbackTexture;
    private Texture2D _packedReadbackTexture;
    private bool _hasLoggedTextureTypes;
    private int _encodedFrameCount;
    private double _encodeTimeAccMs;
    private long _payloadBytesAcc;
    private long _senderFrameId;

    /// <summary>
    /// 从 Quest 左右相机抓取当前帧并编码为单帧 payload。
    /// </summary>
    public override bool TryEncodePayload(out byte[] payload)
    {
        double encodeStart = Time.realtimeSinceStartupAsDouble;
        payload = null;

        if (leftCameraAccess == null || rightCameraAccess == null)
        {
            return false;
        }

        if (!leftCameraAccess.IsPlaying || !rightCameraAccess.IsPlaying)
        {
            return false;
        }

        Texture leftTexture = leftCameraAccess.GetTexture();
        Texture rightTexture = rightCameraAccess.GetTexture();

        if (leftTexture == null || rightTexture == null)
        {
            return false;
        }

        LogTextureTypesOnce(leftTexture, rightTexture);

        EnsureCaptureBuffers(leftTexture, rightTexture);

        double senderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
        long frameId = ++_senderFrameId;
        OnFrameEncoded?.Invoke(frameId);

        BlitToRenderTarget(leftTexture, _leftRenderTexture);
        BlitToRenderTarget(rightTexture, _rightRenderTexture);

        byte[] packedImage = CapturePackedStereo(
            _leftRenderTexture,
            _rightRenderTexture,
            _packedRenderTexture,
            _packedReadbackTexture);

        if (packedImage == null)
        {
            return false;
        }

        QuestStereoMsg message = new QuestStereoMsg
        {
            image_jpeg = packedImage,
            frame_id = frameId,
            sender_mono_ms = senderMonoMs,
            unity_frame = Time.frameCount,
        };

        payload = message.Serialize();
        if (payload == null)
        {
            return false;
        }

        string encodePath = "PackedPayload";
        LogEncodeStats(payload, encodePath, encodeStart);
        return true;
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
        int packedWidth = leftWidth + rightWidth;
        int packedHeight = Mathf.Min(leftHeight, rightHeight);

        EnsureBuffer(ref _leftRenderTexture, ref _leftReadbackTexture, leftWidth, leftHeight);
        EnsureBuffer(ref _rightRenderTexture, ref _rightReadbackTexture, rightWidth, rightHeight);
        EnsureBuffer(ref _packedRenderTexture, ref _packedReadbackTexture, packedWidth, packedHeight);
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

    private byte[] CapturePackedStereo(
        RenderTexture leftSource,
        RenderTexture rightSource,
        RenderTexture packedTarget,
        Texture2D packedReadbackTexture)
    {
        if (leftSource == null || rightSource == null || packedTarget == null || packedReadbackTexture == null)
        {
            return null;
        }

        RenderTexture previous = RenderTexture.active;
        RenderTexture.active = packedTarget;

        GL.PushMatrix();
        GL.LoadPixelMatrix(0, packedTarget.width, packedTarget.height, 0);

        int leftWidth = leftSource.width;
        int rightWidth = rightSource.width;
        int packedHeight = packedTarget.height;

        Graphics.DrawTexture(new Rect(0, 0, leftWidth, packedHeight), leftSource);
        Graphics.DrawTexture(new Rect(leftWidth, 0, rightWidth, packedHeight), rightSource);

        GL.PopMatrix();

        packedReadbackTexture.ReadPixels(new Rect(0, 0, packedTarget.width, packedTarget.height), 0, 0, false);
        RenderTexture.active = previous;
        return EncodeTexture(packedReadbackTexture);
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
        ReleaseBuffer(ref _packedRenderTexture, ref _packedReadbackTexture);
    }
}
