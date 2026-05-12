using UnityEngine;
using NetMQ;
using NetMQ.Sockets;

public class MultipartClient : MonoBehaviour
{
    private RequestSocket _client;

    void Start()
    {
        AsyncIO.ForceDotNet.Force();
        _client = new RequestSocket();
        _client.Connect("tcp://localhost:5555");

        // 发送一个触发请求
        Debug.Log("Unity: 请求数据...");
        _client.SendFrame("GIVE_ME_DATA");

        // 接收逻辑
        ReceiveMultipartData();
    }

    void ReceiveMultipartData()
    {
        // 1. 接收第一帧 (这是我们的指令)
        // 使用 out bool more 来检查后面是否还有数据
        bool more;
        string command = _client.ReceiveFrameString(out more);

        Debug.Log($"Unity: 收到指令帧: {command}");

        if (more)
        {
            // 2. 还有数据！继续接收第二帧 (这是我们的二进制数据)
            byte[] data = _client.ReceiveFrameBytes(out more);
            Debug.Log($"Unity: 收到数据帧，长度: {data.Length}, 内容: {System.BitConverter.ToString(data)}");

            if (!more)
            {
                Debug.Log("Unity: 所有消息接收完毕。");
            }
        }
    }

    void OnDestroy()
    {
        if (_client != null) _client.Dispose();
        NetMQConfig.Cleanup();
    }
}