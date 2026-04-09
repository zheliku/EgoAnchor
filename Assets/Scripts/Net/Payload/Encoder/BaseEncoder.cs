using UnityEngine;

/// <summary>
/// 统一编码器抽象基类。
///
/// 约定：
/// - 任何业务数据都先编码为 byte[]（single-frame payload）。
/// - Sender 仅消费该抽象，不依赖具体业务类型。
/// </summary>
public abstract class BaseEncoder : MonoBehaviour
{
    /// <summary>
    /// 尝试编码当前帧业务数据。
    /// </summary>
    /// <param name="payload">编码后的单帧 payload。</param>
    /// <returns>编码成功返回 true，否则 false。</returns>
    public abstract bool TryEncodePayload(out byte[] payload);
}