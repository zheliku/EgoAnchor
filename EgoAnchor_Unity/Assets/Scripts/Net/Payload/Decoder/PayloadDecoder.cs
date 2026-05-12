using UnityEngine;

/// <summary>
/// 业务 payload 解码器抽象。
///
/// Receiver 负责网络收包和 topic 路由；PayloadDecoder 只负责把某个 topic
/// 的 RawPayload 解码成业务事件。
/// </summary>
public abstract class PayloadDecoder : MonoBehaviour
{
    /// <summary>
    /// 解码并处理一条网络 payload。
    /// </summary>
    /// <remarks>
    /// Unity 与 Python 的命名保持对称：
    /// Unity 使用 HandlePayload(RawPayload payload)，Python 使用 PayloadDecoder.decode(...)。
    /// 本方法在 Unity 主线程被调用，因此子类可以安全触发 UnityEvent 或访问场景对象；
    /// 网络线程只负责收包和缓存，不直接调用 decoder，避免跨线程碰 Unity API。
    /// </remarks>
    public abstract void HandlePayload(RawPayload payload);
}
