using System;
using System.Threading;
using System.Threading.Tasks;
using NATS.Net;
using UnityEngine;

public class NatsResetTest : MonoBehaviour
{
    [SerializeField] private string natsUrl = "nats://127.0.0.1:4222";
    [SerializeField] private string subject = "egoanchor.command.reset_tracking";

    private NatsClient _client;

    private async void Start()
    {
        try
        {
            _client = new NatsClient(natsUrl, "EgoAnchor Unity Test");
            await _client.ConnectAsync();
            Debug.Log($"[NATS] Connected: {natsUrl}");
        }
        catch (Exception e)
        {
            Debug.LogError($"[NATS] Connect failed: {e}");
        }
    }

    [ContextMenu("Send Reset Request")]
    public async void SendResetRequest()
    {
        if (_client == null)
        {
            Debug.LogWarning("[NATS] Client is not connected.");
            return;
        }

        string requestJson =
            "{\"request_id\":\"unity-demo-001\",\"anchor_id\":\"main\",\"command\":\"reset_tracking\"}";

        try
        {
            using CancellationTokenSource cts = new CancellationTokenSource(TimeSpan.FromSeconds(2));

            var reply = await _client.RequestAsync<string, string>(
                subject,
                requestJson,
                cancellationToken: cts.Token
            );

            Debug.Log($"[NATS] Reply: {reply.Data}");
        }
        catch (Exception e)
        {
            Debug.LogError($"[NATS] Request failed: {e}");
        }
    }

    private async void OnDestroy()
    {
        if (_client != null)
        {
            await _client.DisposeAsync();
            _client = null;
        }
    }
}
