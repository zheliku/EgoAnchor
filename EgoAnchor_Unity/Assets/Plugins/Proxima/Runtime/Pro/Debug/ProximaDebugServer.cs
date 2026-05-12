using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using UnityEngine;

namespace Proxima
{
    internal class ProximaDebugServer : ProximaServer
    {
        private string _serverUrl;
        private string _displayName;
        private string _password;
        private ConcurrentQueue<(ProximaConnection, ProximaRequest)> _receiveQueue;
        private List<ProximaDebugConnection> _activeConnections = new List<ProximaDebugConnection>();
        private ProximaDebugConnection _pendingConnection;
        private WaitForSeconds _wait = new WaitForSeconds(1);
        private ProximaDispatcher _dispatcher;
        private ProximaStatus _status;

        public ProximaDebugServer(ProximaDispatcher dispatcher, ProximaStatus status, string serverUrl)
        {
            _dispatcher = dispatcher;
            _status = status;

            if (serverUrl.StartsWith("http"))
            {
                serverUrl = "ws" + serverUrl.Substring(4);
            }
            else if (!serverUrl.StartsWith("ws:") && !serverUrl.StartsWith("wss:"))
            {
                serverUrl = "wss://" + serverUrl;
            }

            if (!serverUrl.EndsWith("/api"))
            {
                serverUrl += "/api";
            }

            _serverUrl = serverUrl;
            Log.Info("Proxima connecting to remote server at: " + _serverUrl);
        }

        public void Start(string displayName, string password)
        {
            _displayName = displayName;
            _password = password;
            _receiveQueue = new ConcurrentQueue<(ProximaConnection, ProximaRequest)>();
            _status.SetConnectInfo(_displayName);
            CreateNewConnection();
        }

        public void Stop()
        {
            foreach (var connection in _activeConnections)
            {
                connection.Dispose();
            }

            _activeConnections.Clear();
            _pendingConnection?.Dispose();
            _receiveQueue = null;
        }

        private void CreateNewConnection()
        {
            _pendingConnection = null;
            if (_receiveQueue != null && _dispatcher != null)
            {
                _dispatcher.StartCoroutine(CreateNewConnectionCoroutine());
            }
        }

        private IEnumerator CreateNewConnectionCoroutine()
        {
            yield return _wait;
            if (_pendingConnection != null)
            {
                yield break;
            }

            Log.Verbose("Creating new connection to Proxima server: " + _serverUrl);
            var conn = new ProximaDebugConnection(_serverUrl, _displayName, _password, _dispatcher, _receiveQueue);

            conn.OnConnect += () => {
                Log.Verbose("Connected to Proxima server.");
                _activeConnections.Add(conn);
                _status.IncrementConnections();
                CreateNewConnection();
            };

            conn.OnClose += () => {
                Log.Verbose("Disconnected from Proxima server.");
                conn.Dispose();

                if (conn == _pendingConnection)
                {
                    if (_receiveQueue != null)
                    {
                        Log.Verbose("Failed to connect to Proxima server. Retrying...");
                        _status.SetError("Failed to connect to Proxima server. Retrying...");
                        CreateNewConnection();
                    }
                }
                else
                {
                    _activeConnections.Remove(conn);
                    _status.DecrementConnections();
                }
            };

            _pendingConnection = conn;
        }

        public bool TryGetMessage(out (ProximaConnection, ProximaRequest) message)
        {
            if (_receiveQueue != null)
            {
                return _receiveQueue.TryDequeue(out message);
            }
            else
            {
                message = (null, null);
                return false;
            }
        }
    }
}