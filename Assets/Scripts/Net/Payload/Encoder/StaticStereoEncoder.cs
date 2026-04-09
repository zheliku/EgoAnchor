using UnityEngine;

/// <summary>
/// 静态双图编码器（用于联调与回归测试）。
///
/// 输入：Inspector 指定的左右纹理。
/// 输出：单帧 packed_jpg。
///
/// 设计点：
/// - 当输入纹理未变化时复用已编码 payload，减少重复编码开销。
/// </summary>
public class StaticStereoEncoder : BaseEncoder
{
    [SerializeField] private Texture leftTexture;
    [SerializeField] private Texture rightTexture;
    [Range(30, 100)]
    [SerializeField] private int jpegQuality = 80;

    private Texture _cachedLeftTexture;
    private Texture _cachedRightTexture;
    private byte[] _cachedPayload;

    /// <summary>
    /// 编码当前静态纹理为单帧 payload。
    /// </summary>
    public override bool TryEncodePayload(out byte[] payload)
    {
        payload = null;

        if (leftTexture == null || rightTexture == null)
        {
            return false;
        }

        if (_cachedLeftTexture != leftTexture || _cachedRightTexture != rightTexture || _cachedPayload == null)
        {
            _cachedPayload = EncodePackedStereoToJpeg(leftTexture, rightTexture);
            _cachedLeftTexture = leftTexture;
            _cachedRightTexture = rightTexture;
        }

        if (_cachedPayload == null || _cachedPayload.Length == 0)
        {
            return false;
        }

        payload = _cachedPayload;
        return true;
    }

    /// <summary>
    /// 将左右纹理横向拼接后编码为 JPEG 字节。
    /// </summary>
    private byte[] EncodePackedStereoToJpeg(Texture leftSource, Texture rightSource)
    {
        if (leftSource == null || rightSource == null)
        {
            return null;
        }

        int leftWidth = Mathf.Max(1, leftSource.width);
        int leftHeight = Mathf.Max(1, leftSource.height);
        int rightWidth = Mathf.Max(1, rightSource.width);
        int rightHeight = Mathf.Max(1, rightSource.height);
        int packedWidth = leftWidth + rightWidth;
        int packedHeight = Mathf.Min(leftHeight, rightHeight);

        if (packedWidth <= 1 || packedHeight <= 1)
        {
            return null;
        }

        RenderTexture leftRt = RenderTexture.GetTemporary(leftWidth, leftHeight, 0, RenderTextureFormat.ARGB32);
        RenderTexture rightRt = RenderTexture.GetTemporary(rightWidth, rightHeight, 0, RenderTextureFormat.ARGB32);
        RenderTexture packedRt = RenderTexture.GetTemporary(packedWidth, packedHeight, 0, RenderTextureFormat.ARGB32);
        Texture2D readback = new Texture2D(packedWidth, packedHeight, TextureFormat.RGB24, false);

        Graphics.Blit(leftSource, leftRt);
        Graphics.Blit(rightSource, rightRt);

        RenderTexture previous = RenderTexture.active;

        RenderTexture.active = packedRt;
        GL.PushMatrix();
        GL.LoadPixelMatrix(0, packedWidth, packedHeight, 0);
        Graphics.DrawTexture(new Rect(0, 0, leftWidth, packedHeight), leftRt);
        Graphics.DrawTexture(new Rect(leftWidth, 0, rightWidth, packedHeight), rightRt);
        GL.PopMatrix();

        readback.ReadPixels(new Rect(0, 0, packedRt.width, packedRt.height), 0, 0, false);
        readback.Apply(false, false);

        RenderTexture.active = previous;
        byte[] jpeg = readback.EncodeToJPG(jpegQuality);

        RenderTexture.ReleaseTemporary(leftRt);
        RenderTexture.ReleaseTemporary(rightRt);
        RenderTexture.ReleaseTemporary(packedRt);
        Destroy(readback);

        return jpeg;
    }
}
