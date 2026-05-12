using UnityEngine;

/// <summary>
/// 业务 payload 编码器抽象。
///
/// 传输层只认识 topic 和 byte[]，具体图像、相机信息、pose 等业务格式
/// 都在各自的 PayloadEncoder 子类里完成。
/// </summary>
public abstract class PayloadEncoder : MonoBehaviour
{
    /// <summary>
    /// 尝试把当前业务状态编码成单帧 MessagePack payload。
    /// </summary>
    /// <remarks>
    /// Unity 与 Python 的命名保持对称：
    /// Unity 使用 TryEncode(out byte[] payload)，Python 使用 PayloadEncoder.encode(...)。
    /// 返回 false 表示当前帧没有可发送数据，传输层会跳过该 entry，不发送空包。
    /// </remarks>
    public abstract bool TryEncode(out byte[] payload);
}
