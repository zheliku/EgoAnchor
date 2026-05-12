using System;
using System.IO;
using ProximaWebSocketSharp;

namespace Proxima
{
    internal class WebSocketClientCs : WebSocketClient
    {
        public event Action OnOpen;
        public event Action<string> OnMessage;
        public event Action OnClose;

        private WebSocket _ws;

        public void Connect(string url, string protocol)
        {
            Log.Verbose("WebSocketClientCs - Connect: " + url);
            _ws = new WebSocket(url, protocol);
            _ws.Log.Level = LogLevel.Error;
            _ws.Log.Output = (data, message) => Log.Verbose("WebSocketClientCs Error:" + data.Level + " " + data.Message + "\n" + data.Caller);
            _ws.OnOpen += (sender, e) => OnOpen?.Invoke();
            _ws.OnMessage += (sender, e) => OnMessage?.Invoke(e.Data);
            _ws.OnClose += (sender, e) => OnClose?.Invoke();
            _ws.ConnectAsync();
        }

        public void Send(MemoryStream data)
        {
            _ws.SendAsTextAsync(data, (b) => {});
        }

        public void Dispose()
        {
            if (_ws != null)
            {
                if (_ws.ReadyState == WebSocketState.Open)
                {
                    _ws.CloseAsync();
                }

                _ws = null;
            }
        }
    }
}