using System;
using System.IO;

namespace Proxima
{
    internal interface WebSocketClient : IDisposable
    {
        event Action OnOpen;
        event Action<string> OnMessage;
        event Action OnClose;

        void Connect(string url, string protocol);
        void Send(MemoryStream data);
    }
}