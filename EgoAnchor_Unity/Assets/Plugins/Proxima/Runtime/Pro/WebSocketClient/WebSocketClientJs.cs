#if UNITY_WEBGL

using System;
using System.IO;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using AOT;

namespace Proxima
{
    internal class WebSocketClientJs : WebSocketClient
    {
        public event Action OnOpen;
        public event Action<string> OnMessage;
        public event Action OnClose;

        [DllImport("__Internal")]
        private static extern int ProximaWebSocketCreate(string url, string protocol, Action<int> OnOpen, Action<int> OnClose, Action<int, string> OnMessage);

        [DllImport("__Internal")]
        private static extern int ProximaWebSocketSend(int id, string data);

        [DllImport("__Internal")]
        private static extern int ProximaWebSocketDestroy(int id);

        private int _id;
        private static Dictionary<int, WebSocketClientJs> _sockets = new Dictionary<int, WebSocketClientJs>();

        public void Connect(string url, string protocol)
        {
            _id = ProximaWebSocketCreate(url, protocol, HandleOpen, HandleClose, HandleMessage);
            _sockets.Add(_id, this);
        }

        [MonoPInvokeCallback(typeof(Action<int>))]
        private static void HandleOpen(int id)
        {
            if (_sockets.TryGetValue(id, out var socket))
            {
                socket.OnOpen?.Invoke();
            }
        }

        [MonoPInvokeCallback(typeof(Action<int>))]
        private static void HandleClose(int id)
        {
            if (_sockets.TryGetValue(id, out var socket))
            {
                socket.OnClose?.Invoke();
            }
        }

        [MonoPInvokeCallback(typeof(Action<int, string>))]
        private static void HandleMessage(int id, string data)
        {
            if (_sockets.TryGetValue(id, out var socket))
            {
                socket.OnMessage?.Invoke(data);
            }
        }

        public void Send(MemoryStream data)
        {
            var str = Encoding.UTF8.GetString(data.GetBuffer(), 0, (int)data.Length);
            ProximaWebSocketSend(_id, str);
        }

        public void Dispose()
        {
            ProximaWebSocketDestroy(_id);
        }
    }
}

#endif