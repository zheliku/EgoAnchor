using System;
using System.Collections.Concurrent;
using System.IO;
using UnityEngine;

namespace Proxima
{
    internal class ProximaDebugConnection : ProximaConnection, IDisposable
    {
        public event Action OnConnect;
        public event Action OnClose;

        public bool Open => _ws != null;

        private WebSocketClient _ws;
        private ProximaDispatcher _dispatcher;
        private ConcurrentQueue<(ProximaConnection, ProximaRequest)> _receiveQueue;

        private bool _passwordProvided;
        private ProximaInstanceHello _hello;

        public ProximaDebugConnection(string serverUrl, string displayName,
            string password, ProximaDispatcher dispatcher,
            ConcurrentQueue<(ProximaConnection, ProximaRequest)> queue)
        {
            _receiveQueue = queue;
            _dispatcher = dispatcher;
            _hello = ProximaSerialization.CreateHello(displayName, password);

            #if UNITY_WEBGL && !UNITY_EDITOR
                _ws = new WebSocketClientJs();
            #else
                _ws = new WebSocketClientCs();
            #endif

            _ws.OnOpen += OnWebSocketOpen;
            _ws.OnClose += OnWebSocketClose;
            _ws.OnMessage += OnWebSocketMessage;
            _ws.Connect(serverUrl, "proxima");
        }

        public void SendMessage(MemoryStream data)
        {
            Log.Verbose("Sending: " + System.Text.Encoding.UTF8.GetString(data.GetBuffer(), 0, (int)data.Length));
            _ws?.Send(data);
        }

        private void OnWebSocketOpen()
        {
            _dispatcher.Dispatch(() => {

                SendMessage(FastJson.Serialize(_hello));
            });
        }

        private void OnWebSocketMessage(string message)
        {
            Log.Verbose("Received: " + message);

            ProximaRequest request;

            try
            {
                request = JsonUtility.FromJson<ProximaRequest>(message);
            }
            catch (Exception ex)
            {
                Log.Error("Failed to parse request: " + ex.Message);
                return;
            }

            if (_passwordProvided)
            {
                _receiveQueue.Enqueue((this, request));
            }
            else
            {
                if (request.Type == ProximaRequestType.Select)
                {
                    if (request.Cmd != _hello.InstanceId)
                    {
                        Log.Verbose("Invalid app name provided.");
                    }
                    else if (request.Args.Length != 1 || request.Args[0] != _hello.Password)
                    {
                        Log.Verbose("Invalid password provided.");
                    }
                    else
                    {
                        _passwordProvided = true;
                        _dispatcher.Dispatch(() => OnConnect?.Invoke());
                    }
                }
                else
                {
                    Log.Verbose("Unknown request: " + request.Type);
                }
            }
        }

        private void OnWebSocketClose()
        {
            _dispatcher.Dispatch(() => OnClose?.Invoke());
        }

        public void Dispose()
        {
            _ws?.Dispose();
            _ws = null;
        }
    }
}