using System;
using UnityEngine;
using UnityEngine.Events;

/// <summary>
/// QuestCameraInfoMsg 对外事件类型。
/// </summary>
[Serializable]
public class CameraInfoReceivedEvent : UnityEvent<QuestCameraInfoMsg> { }

/// <summary>
/// Quest 相机静态信息解码器。
///
/// 输入：RawPayload（MessagePack 编码的 QuestCameraInfoMsg）。
/// 输出：OnCameraInfoReceived 事件，参数为反序列化后的 QuestCameraInfoMsg。
/// </summary>
public class CameraInfoDecoder : PayloadDecoder
{
    [Header("Events")]
    [Tooltip("当收到完整相机信息消息时触发")]
    public CameraInfoReceivedEvent OnCameraInfoReceived = new CameraInfoReceivedEvent();

    private void Awake()
    {
        if (OnCameraInfoReceived == null)
        {
            OnCameraInfoReceived = new CameraInfoReceivedEvent();
        }
    }

    public override void HandlePayload(RawPayload payload)
    {
        if (payload.Payload == null || payload.Payload.Length == 0)
        {
            return;
        }

        QuestCameraInfoMsg message = QuestCameraInfoMsg.Deserialize(payload.Payload);
        if (message != null)
        {
            OnCameraInfoReceived?.Invoke(message);
        }
    }
}

