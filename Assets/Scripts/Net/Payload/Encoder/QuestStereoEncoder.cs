using Meta.XR;
using UnityEngine;

/// <summary>
/// Quest 双目图像编码器。
///
/// 输入：左右 Passthrough Camera 纹理。
/// 输出：multipart [left_jpg, right_jpg]。
///
/// 注意：
/// - 本组件只负责编码，不负责发送。
/// - 发送节奏由 PayloadSender 控制。
/// </summary>
public class QuestStereoEncoder : BaseEncoder
{
    private enum StereoImageCodec
    {
        Jpeg = 0,
        Png = 1,
    }

    [SerializeField] private PassthroughCameraAccess leftCameraAccess;
    [SerializeField] private PassthroughCameraAccess rightCameraAccess;
    [SerializeField] private bool packStereoIntoSingleJpeg = false;
    [Range(0.25f, 1f)]
    [SerializeField] private float outputScale = 1f;
    [Range(30, 100)]
    [SerializeField] private int jpegQuality = 95;
    [SerializeField] private StereoImageCodec imageCodec = StereoImageCodec.Jpeg;
    [Header("Debug")]
    [SerializeField] private bool enableVerboseDebugLog = true;
    [Range(1, 300)]
    [SerializeField] private int debugLogInterval = 30;

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

    /// <summary>
    /// 从 Quest 左右相机抓取当前帧并编码为双帧 payload。
    /// </summary>
    public override bool TryEncodePayload(out byte[][] payloadParts)
    {
        double encodeStart = Time.realtimeSinceStartupAsDouble;
        payloadParts = null;

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

        string encodePath;

        if (packStereoIntoSingleJpeg)
        {
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

            payloadParts = new[] { packedImage };
            encodePath = "Packed";
            LogEncodeStats(payloadParts, encodePath, encodeStart);
            return true;
        }

        bool leftDirect = TryEncodeTexture2DDirect(leftTexture, out byte[] leftImage);
        bool rightDirect = TryEncodeTexture2DDirect(rightTexture, out byte[] rightImage);

        if (!leftDirect)
        {
            leftImage = CaptureAsEncodedBytes(leftTexture, _leftRenderTexture, _leftReadbackTexture);
        }

        if (!rightDirect)
        {
            rightImage = CaptureAsEncodedBytes(rightTexture, _rightRenderTexture, _rightReadbackTexture);
        }

        if (leftImage == null || rightImage == null)
        {
            return false;
        }

        payloadParts = new[] { leftImage, rightImage };
        encodePath = $"Dual(L:{(leftDirect ? "Direct" : "Readback")},R:{(rightDirect ? "Direct" : "Readback")})";
        LogEncodeStats(payloadParts, encodePath, encodeStart);
        return true;
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

    /// <summary>
    /// 将 source 纹理回读并编码。
    /// 若 source 已是匹配尺寸的 RenderTexture，则直接回读，避免一次额外 Blit。
    /// </summary>
    private byte[] CaptureAsEncodedBytes(Texture source, RenderTexture target, Texture2D readbackTexture)
    {
        if (source == null || target == null || readbackTexture == null)
        {
            return null;
        }

        RenderTexture readSource = target;
        if (source is RenderTexture sourceRt &&
            sourceRt.width == target.width &&
            sourceRt.height == target.height)
        {
            readSource = sourceRt;
        }
        else
        {
            Graphics.Blit(source, target);
        }

        RenderTexture previous = RenderTexture.active;
        RenderTexture.active = readSource;

        readbackTexture.ReadPixels(new Rect(0, 0, readSource.width, readSource.height), 0, 0, false);

        RenderTexture.active = previous;
        return EncodeTexture(readbackTexture);
    }

    private static void BlitToRenderTarget(Texture source, RenderTexture target)
    {
        if (source == null || target == null)
        {
            return;
        }

        Graphics.Blit(source, target);
    }

    private bool TryEncodeTexture2DDirect(Texture source, out byte[] encoded)
    {
        encoded = null;

        if (!Mathf.Approximately(outputScale, 1f))
        {
            return false;
        }

        if (source is not Texture2D texture2D)
        {
            return false;
        }

        try
        {
            encoded = EncodeTexture(texture2D);
            return encoded != null && encoded.Length > 0;
        }
        catch
        {
            return false;
        }
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
        string codecDesc = imageCodec == StereoImageCodec.Jpeg
            ? $"JPEG(q={jpegQuality})"
            : "PNG(lossless)";
        Debug.Log($"[QuestStereoEncoder] LeftType={leftType}, RightType={rightType}, OutputScale={outputScale:F2}, PackSingleJpeg={packStereoIntoSingleJpeg}, Codec={codecDesc}");
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

    private void LogEncodeStats(byte[][] payloadParts, string encodePath, double encodeStart)
    {
        if (!enableVerboseDebugLog)
        {
            return;
        }

        _encodedFrameCount++;
        double elapsedMs = (Time.realtimeSinceStartupAsDouble - encodeStart) * 1000.0;
        _encodeTimeAccMs += elapsedMs;

        long bytes = 0;
        if (payloadParts != null)
        {
            for (int i = 0; i < payloadParts.Length; i++)
            {
                if (payloadParts[i] != null)
                {
                    bytes += payloadParts[i].LongLength;
                }
            }
        }
        _payloadBytesAcc += bytes;

        int interval = Mathf.Max(1, debugLogInterval);
        if (_encodedFrameCount % interval != 0)
        {
            return;
        }

        double avgEncodeMs = _encodeTimeAccMs / interval;
        double avgPayloadKB = (_payloadBytesAcc / (double)interval) / 1024.0;
        int partCount = payloadParts == null ? 0 : payloadParts.Length;

        Debug.Log(
            $"[QuestStereoEncoder] EncodeStats frames={_encodedFrameCount}, mode={encodePath}, parts={partCount}, avgEncode={avgEncodeMs:F2}ms, avgPayload={avgPayloadKB:F1}KB, codec={imageCodec}"
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

        if (imageCodec == StereoImageCodec.Png)
        {
            return texture.EncodeToPNG();
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
