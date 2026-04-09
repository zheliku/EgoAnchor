using UnityEngine;

/// <summary>
/// RGBD 协议解码器。
///
/// 输入协议：
/// - parts[0] = color_jpg
/// - parts[1] = depth_png
///
/// 使用方式：
/// - 在 PayloadReceiver 的 OnPayloadReceived 事件中，绑定本类 OnPayloadReceived。
/// - 本类再对外发出 OnRGBDReceived（单事件，包含完整 RGBDMsg）。
/// </summary>
public class RGBDDecoder : BaseDecoder
{
    [Header("Events")]
    [Tooltip("当收到完整 RGBD 消息时触发")]
    public RGBDMsgEvent OnRGBDReceived = new RGBDMsgEvent();

    /// <summary>
    /// 初始化事件实例，避免序列化异常导致空引用。
    /// </summary>
    private void Awake()
    {
        if (OnRGBDReceived == null)
            OnRGBDReceived = new RGBDMsgEvent();
    }

    /// <summary>
    /// Receiver 事件回调入口：解析 payload 并派发完整 RGBD 事件。
    /// </summary>
    public override void OnPayloadReceived(RawPayload payload)
    {
        byte[][] parts = payload.Parts;
        if (parts == null || parts.Length != 2)
        {
            return;
        }

        OnRGBDReceived?.Invoke(new RGBDMsg(parts[0], parts[1], payload.TimestampMs));
    }
}
