using UnityEngine;

/// <summary>
/// 静态双图编码器（用于联调与回归测试）。
///
/// 输入：Inspector 指定的左右纹理。
/// 输出：multipart [left_jpg, right_jpg]。
///
/// 设计点：
/// - 当输入纹理未变化时复用已编码 JPEG，减少重复编码开销。
/// </summary>
public class StaticStereoEncoder : BaseEncoder
{
    [SerializeField] private Texture leftTexture;
    [SerializeField] private Texture rightTexture;
    [Range(30, 100)]
    [SerializeField] private int jpegQuality = 80;

    private Texture _cachedLeftTexture;
    private Texture _cachedRightTexture;
    private byte[] _cachedLeftJpeg;
    private byte[] _cachedRightJpeg;

    /// <summary>
    /// 编码当前静态纹理为双帧 payload。
    /// </summary>
    public override bool TryEncodePayload(out byte[][] payloadParts)
    {
        payloadParts = null;

        if (leftTexture == null || rightTexture == null)
        {
            return false;
        }

        if (_cachedLeftTexture != leftTexture || _cachedRightTexture != rightTexture ||
            _cachedLeftJpeg == null || _cachedRightJpeg == null)
        {
            _cachedLeftJpeg = EncodeTextureToJpeg(leftTexture);
            _cachedRightJpeg = EncodeTextureToJpeg(rightTexture);
            _cachedLeftTexture = leftTexture;
            _cachedRightTexture = rightTexture;
        }

        if (_cachedLeftJpeg == null || _cachedRightJpeg == null)
        {
            return false;
        }

        payloadParts = new[] { _cachedLeftJpeg, _cachedRightJpeg };
        return true;
    }

    /// <summary>
    /// 将单张纹理编码为 JPEG 字节。
    /// </summary>
    private byte[] EncodeTextureToJpeg(Texture source)
    {
        if (source == null || source.width <= 0 || source.height <= 0)
        {
            return null;
        }

        RenderTexture target = RenderTexture.GetTemporary(source.width, source.height, 0, RenderTextureFormat.ARGB32);
        Texture2D readback = new Texture2D(source.width, source.height, TextureFormat.RGB24, false);

        RenderTexture previous = RenderTexture.active;
        Graphics.Blit(source, target);
        RenderTexture.active = target;

        readback.ReadPixels(new Rect(0, 0, target.width, target.height), 0, 0, false);
        readback.Apply(false, false);

        RenderTexture.active = previous;
        byte[] jpeg = readback.EncodeToJPG(jpegQuality);

        RenderTexture.ReleaseTemporary(target);
        Destroy(readback);

        return jpeg;
    }
}
