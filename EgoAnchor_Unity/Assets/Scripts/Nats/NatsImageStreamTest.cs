using System;
using System.Collections;
using System.Threading;
using System.Threading.Tasks;
using NATS.Net;
using UnityEngine;

public class NatsImageStreamTest : MonoBehaviour
{
    [Header("NATS")]
    [SerializeField] private string natsUrl = "nats://127.0.0.1:4222";
    [SerializeField] private string subject = "egoanchor.quest.image_jpeg";

    [Header("Image")]
    [SerializeField] private Texture2D sourceImage;
    [Range(1, 100)]
    [SerializeField] private int jpegQuality = 75;
    [Min(1)]
    [SerializeField] private int targetFps = 5;
    [SerializeField] private bool publishOnStart = true;

    private NatsClient _client;
    private byte[] _jpegBytes;
    private Coroutine _publishLoop;
    private CancellationTokenSource _destroyCts;

    private async void Start()
    {
        _destroyCts = new CancellationTokenSource();

        try
        {
            _client = new NatsClient(natsUrl, "EgoAnchor Unity Image Test");
            await _client.ConnectAsync();
            Debug.Log($"[NATS Image] Connected: {natsUrl}");

            PrepareImage();

            if (publishOnStart)
            {
                StartPublishing();
            }
        }
        catch (Exception e)
        {
            Debug.LogError($"[NATS Image] Start failed: {e}");
        }
    }

    [ContextMenu("Prepare Image")]
    private void PrepareImage()
    {
        if (sourceImage == null)
        {
            Debug.LogError("[NATS Image] sourceImage is null. Assign a Texture2D in Inspector.");
            return;
        }

        _jpegBytes = EncodeTextureToJpg(sourceImage, jpegQuality);
        if (_jpegBytes == null || _jpegBytes.Length == 0)
        {
            Debug.LogError("[NATS Image] Failed to encode sourceImage to JPG.");
            return;
        }

        Debug.Log($"[NATS Image] Encoded JPG bytes={_jpegBytes.Length}, size={sourceImage.width}x{sourceImage.height}");
    }

    private static byte[] EncodeTextureToJpg(Texture2D texture, int quality)
    {
        RenderTexture previous = RenderTexture.active;
        RenderTexture rt = RenderTexture.GetTemporary(
            texture.width,
            texture.height,
            0,
            RenderTextureFormat.ARGB32,
            RenderTextureReadWrite.sRGB
        );

        try
        {
            Graphics.Blit(texture, rt);
            RenderTexture.active = rt;

            Texture2D readable = new Texture2D(texture.width, texture.height, TextureFormat.RGB24, false);
            readable.ReadPixels(new Rect(0, 0, texture.width, texture.height), 0, 0);
            readable.Apply(false, false);

            byte[] jpg = readable.EncodeToJPG(Mathf.Clamp(quality, 1, 100));
            Destroy(readable);
            return jpg;
        }
        finally
        {
            RenderTexture.active = previous;
            RenderTexture.ReleaseTemporary(rt);
        }
    }

    [ContextMenu("Start Publishing")]
    public void StartPublishing()
    {
        if (_publishLoop != null)
        {
            return;
        }

        if (_jpegBytes == null || _jpegBytes.Length == 0)
        {
            PrepareImage();
        }

        _publishLoop = StartCoroutine(PublishLoop());
    }

    [ContextMenu("Stop Publishing")]
    public void StopPublishing()
    {
        if (_publishLoop == null)
        {
            return;
        }

        StopCoroutine(_publishLoop);
        _publishLoop = null;
    }

    private IEnumerator PublishLoop()
    {
        WaitForSeconds wait = new WaitForSeconds(1f / Mathf.Max(1, targetFps));

        while (true)
        {
            _ = PublishOnceAsync();
            yield return wait;
        }
    }

    [ContextMenu("Publish Once")]
    public async void PublishOnceFromInspector()
    {
        await PublishOnceAsync();
    }

    private async Task PublishOnceAsync()
    {
        if (_client == null || _jpegBytes == null || _jpegBytes.Length == 0)
        {
            return;
        }

        try
        {
            await _client.PublishAsync<byte[]>(
                subject,
                _jpegBytes,
                cancellationToken: _destroyCts.Token
            );
        }
        catch (Exception e)
        {
            Debug.LogError($"[NATS Image] Publish failed: {e.Message}");
        }
    }

    private async void OnDestroy()
    {
        StopPublishing();

        if (_destroyCts != null)
        {
            _destroyCts.Cancel();
            _destroyCts.Dispose();
            _destroyCts = null;
        }

        if (_client != null)
        {
            await _client.DisposeAsync();
            _client = null;
        }
    }
}
