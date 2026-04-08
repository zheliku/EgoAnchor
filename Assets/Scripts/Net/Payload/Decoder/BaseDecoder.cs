using UnityEngine;

/// <summary>
/// 统一解码器抽象基类。
///
/// 约定：
/// - 输入统一为 RawPayload。
/// - Decoder 只负责协议解析与事件派发，不处理网络收发。
/// </summary>
public abstract class BaseDecoder : MonoBehaviour
{
    /// <summary>
    /// 解码并处理一条 payload。
    /// </summary>
    public abstract void OnPayloadReceived(RawPayload payload);
}