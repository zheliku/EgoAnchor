using System;
using System.Collections;
using System.Text;
using Meta.XR;
using Unity.Collections;
using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// Dumps comprehensive runtime information from PassthroughCameraAccess for left and right cameras.
///
/// Usage:
/// 1) Add this component to any GameObject in scene.
/// 2) Assign left/right PassthroughCameraAccess in Inspector (or keep auto-find enabled).
/// 3) Run on Quest, then press dumpKey or use context menu to print all details.
/// </summary>
public class PcaApiInfoDumper : MonoBehaviour
{
    [Header("Camera Access References")]
    [SerializeField] private PassthroughCameraAccess leftCameraAccess;
    [SerializeField] private PassthroughCameraAccess rightCameraAccess;
    [SerializeField] private bool autoFindInScene = true;

    [Header("Dump Options")]
    [SerializeField] private bool dumpOnStartWhenReady = true;
    [SerializeField] private bool periodicDump = false;
    [SerializeField] private float periodicDumpIntervalSeconds = 5f;
    [SerializeField] private Key dumpKey = Key.P;

    [Header("Detailed Options")]
    [SerializeField] private bool includeColorReadback = false;
    [SerializeField, Range(2, 32)] private int colorSampleGrid = 8;

    private bool _dumpedOnStart;
    private float _nextPeriodicDumpTime;

    private void Start()
    {
        TryAutoBindCameraAccesses();

        if (dumpOnStartWhenReady)
        {
            StartCoroutine(DumpWhenReadyCoroutine());
        }
    }

    private void Update()
    {
        if (autoFindInScene && (leftCameraAccess == null || rightCameraAccess == null))
        {
            TryAutoBindCameraAccesses();
        }

        var keyboard = Keyboard.current;
        if (keyboard != null && keyboard[dumpKey].wasPressedThisFrame)
        {
            DumpNow();
        }

        if (!periodicDump)
        {
            return;
        }

        if (Time.unscaledTime >= _nextPeriodicDumpTime)
        {
            _nextPeriodicDumpTime = Time.unscaledTime + Mathf.Max(0.2f, periodicDumpIntervalSeconds);
            DumpNow();
        }
    }

    [ContextMenu("Dump PCA Info Now")]
    public void DumpNow()
    {
        TryAutoBindCameraAccesses();

        StringBuilder sb = new StringBuilder(8192);
        sb.AppendLine("================ PCA INFO DUMP ================");
        sb.AppendLine($"frame={Time.frameCount}, t={Time.realtimeSinceStartupAsDouble:F3}s");
        sb.AppendLine($"sceneObject={GetHierarchyPath(transform)}");
        sb.AppendLine();

        AppendStaticApiInfo(sb);
        AppendApiCoverage(sb);
        sb.AppendLine();

        AppendCameraAccessDump(sb, "LEFT", leftCameraAccess);
        sb.AppendLine();
        AppendCameraAccessDump(sb, "RIGHT", rightCameraAccess);

        sb.AppendLine("================================================");
        Debug.Log(sb.ToString());
    }

    private IEnumerator DumpWhenReadyCoroutine()
    {
        while (!_dumpedOnStart)
        {
            TryAutoBindCameraAccesses();

            bool leftReady = leftCameraAccess != null && leftCameraAccess.IsPlaying;
            bool rightReady = rightCameraAccess != null && rightCameraAccess.IsPlaying;

            if (leftReady || rightReady)
            {
                DumpNow();
                _dumpedOnStart = true;
                _nextPeriodicDumpTime = Time.unscaledTime + Mathf.Max(0.2f, periodicDumpIntervalSeconds);
                yield break;
            }

            yield return null;
        }
    }

    private void TryAutoBindCameraAccesses()
    {
        if (!autoFindInScene)
        {
            return;
        }

        if (leftCameraAccess != null && rightCameraAccess != null)
        {
            return;
        }

        PassthroughCameraAccess[] all = FindObjectsByType<PassthroughCameraAccess>(
            FindObjectsInactive.Include,
            FindObjectsSortMode.None);
        foreach (PassthroughCameraAccess access in all)
        {
            if (access == null)
            {
                continue;
            }

            if (access.CameraPosition == PassthroughCameraAccess.CameraPositionType.Left && leftCameraAccess == null)
            {
                leftCameraAccess = access;
                continue;
            }

            if (access.CameraPosition == PassthroughCameraAccess.CameraPositionType.Right && rightCameraAccess == null)
            {
                rightCameraAccess = access;
                continue;
            }
        }
    }

    private void AppendStaticApiInfo(StringBuilder sb)
    {
        sb.AppendLine("[PassthroughCameraAccess Static APIs]");
        sb.AppendLine($"  IsSupported: {PassthroughCameraAccess.IsSupported}");

        Vector2Int[] leftRes = PassthroughCameraAccess.GetSupportedResolutions(PassthroughCameraAccess.CameraPositionType.Left);
        Vector2Int[] rightRes = PassthroughCameraAccess.GetSupportedResolutions(PassthroughCameraAccess.CameraPositionType.Right);

        sb.AppendLine($"  GetSupportedResolutions(Left): {FormatResolutionList(leftRes)}");
        sb.AppendLine($"  GetSupportedResolutions(Right): {FormatResolutionList(rightRes)}");
    }

    private void AppendApiCoverage(StringBuilder sb)
    {
        sb.AppendLine("[API Coverage]");
        sb.AppendLine("  Static:");
        sb.AppendLine("    IsSupported");
        sb.AppendLine("    GetSupportedResolutions(CameraPositionType)");
        sb.AppendLine("  Instance fields/properties:");
        sb.AppendLine("    CameraPosition, RequestedResolution, TargetMaterial");
        sb.AppendLine("    MaxFramerate, TexturePropertyName");
        sb.AppendLine("    IsPlaying, IsUpdatedThisFrame, Timestamp, CurrentResolution, Intrinsics");
        sb.AppendLine("  Instance methods:");
        sb.AppendLine("    GetTexture(), GetCameraPose()");
        sb.AppendLine("    ViewportPointToRay(Vector2), WorldToViewportPoint(Vector3)");
        sb.AppendLine("    GetColors() [optional by includeColorReadback]");
    }

    private void AppendCameraAccessDump(StringBuilder sb, string label, PassthroughCameraAccess access)
    {
        sb.AppendLine($"[{label} Camera]");
        if (access == null)
        {
            sb.AppendLine("  reference: null");
            return;
        }

        sb.AppendLine($"  object: {GetHierarchyPath(access.transform)}");
        sb.AppendLine($"  enabled: {access.enabled}");
        sb.AppendLine($"  activeInHierarchy: {access.gameObject.activeInHierarchy}");
        sb.AppendLine($"  isActiveAndEnabled: {access.isActiveAndEnabled}");

        sb.AppendLine("  [Public Fields / Properties]");
        sb.AppendLine($"    CameraPosition: {access.CameraPosition}");
        sb.AppendLine($"    RequestedResolution: {FormatResolution(access.RequestedResolution)}");
        sb.AppendLine($"    CurrentResolution: {FormatResolution(access.CurrentResolution)}");
        sb.AppendLine($"    MaxFramerate: {access.MaxFramerate}");
        sb.AppendLine($"    TexturePropertyName: '{access.TexturePropertyName}'");
        sb.AppendLine($"    TargetMaterial: {FormatMaterial(access.TargetMaterial)}");
        sb.AppendLine($"    IsPlaying: {access.IsPlaying}");
        sb.AppendLine($"    IsUpdatedThisFrame: {access.IsUpdatedThisFrame}");
        sb.AppendLine($"    Timestamp: {access.Timestamp:O}");

        PassthroughCameraAccess.CameraIntrinsics intrinsics = access.Intrinsics;
        sb.AppendLine("  [Intrinsics]");
        sb.AppendLine($"    FocalLength: {FormatVector2(intrinsics.FocalLength)}");
        sb.AppendLine($"    PrincipalPoint: {FormatVector2(intrinsics.PrincipalPoint)}");
        sb.AppendLine($"    SensorResolution: {FormatResolution(intrinsics.SensorResolution)}");
        sb.AppendLine($"    LensOffset.position: {FormatVector3(intrinsics.LensOffset.position)}");
        sb.AppendLine($"    LensOffset.rotation(quat): {FormatQuaternion(intrinsics.LensOffset.rotation)}");
        sb.AppendLine($"    LensOffset.rotation(euler): {FormatVector3(intrinsics.LensOffset.rotation.eulerAngles)}");

        sb.AppendLine("  [Public Methods]");
        Texture texture = null;
        try
        {
            texture = access.GetTexture();
            sb.AppendLine($"    GetTexture(): {FormatTexture(texture)}");
        }
        catch (Exception ex)
        {
            sb.AppendLine($"    GetTexture(): <exception: {ex.Message}>");
        }

        if (!access.IsPlaying)
        {
            sb.AppendLine("    GetCameraPose(): <not playing>");
            sb.AppendLine("    ViewportPointToRay(0.5,0.5): <not playing>");
            sb.AppendLine("    WorldToViewportPoint(...): <not playing>");
            sb.AppendLine("    GetColors(): <not playing>");
            return;
        }

        Pose cameraPose;
        try
        {
            cameraPose = access.GetCameraPose();
            sb.AppendLine($"    GetCameraPose().position: {FormatVector3(cameraPose.position)}");
            sb.AppendLine($"    GetCameraPose().rotation(quat): {FormatQuaternion(cameraPose.rotation)}");
            sb.AppendLine($"    GetCameraPose().rotation(euler): {FormatVector3(cameraPose.rotation.eulerAngles)}");
        }
        catch (Exception ex)
        {
            sb.AppendLine($"    GetCameraPose(): <exception: {ex.Message}>");
            return;
        }

        try
        {
            Ray centerRay = access.ViewportPointToRay(new Vector2(0.5f, 0.5f));
            sb.AppendLine($"    ViewportPointToRay(0.5,0.5).origin: {FormatVector3(centerRay.origin)}");
            sb.AppendLine($"    ViewportPointToRay(0.5,0.5).direction: {FormatVector3(centerRay.direction)}");

            Vector3 topLeftRay = access.ViewportPointToRay(new Vector2(0f, 1f)).direction;
            Vector3 bottomRightRay = access.ViewportPointToRay(new Vector2(1f, 0f)).direction;
            sb.AppendLine($"    ViewportPointToRay(0,1).direction: {FormatVector3(topLeftRay)}");
            sb.AppendLine($"    ViewportPointToRay(1,0).direction: {FormatVector3(bottomRightRay)}");

            Vector3 worldPoint = cameraPose.position + cameraPose.rotation * Vector3.forward * 1.0f;
            Vector2 viewport = access.WorldToViewportPoint(worldPoint);
            sb.AppendLine($"    WorldToViewportPoint(cameraForward@1m): {FormatVector2(viewport)}");
        }
        catch (Exception ex)
        {
            sb.AppendLine($"    Viewport/World projection APIs: <exception: {ex.Message}>");
        }

        if (!includeColorReadback)
        {
            sb.AppendLine("    GetColors(): <skipped, includeColorReadback=false>");
            return;
        }

        try
        {
            NativeArray<Color32> colors = access.GetColors();
            int width = Mathf.Max(1, access.CurrentResolution.x);
            int height = Mathf.Max(1, access.CurrentResolution.y);
            int expectedLen = width * height;

            sb.AppendLine($"    GetColors().Length: {colors.Length} (expected {expectedLen})");

            if (colors.Length >= expectedLen)
            {
                int gx = Mathf.Clamp(colorSampleGrid, 2, 32);
                int gy = gx;
                float lumaSum = 0f;
                int count = 0;

                for (int y = 0; y < gy; y++)
                {
                    int py = Mathf.Clamp(Mathf.RoundToInt((y + 0.5f) / gy * (height - 1)), 0, height - 1);
                    for (int x = 0; x < gx; x++)
                    {
                        int px = Mathf.Clamp(Mathf.RoundToInt((x + 0.5f) / gx * (width - 1)), 0, width - 1);
                        Color32 c = colors[py * width + px];
                        float luma = 0.2126f * c.r + 0.7152f * c.g + 0.0722f * c.b;
                        lumaSum += luma;
                        count++;
                    }
                }

                Color32 center = colors[(height / 2) * width + (width / 2)];
                float avgLuma01 = count > 0 ? (lumaSum / count) / 255f : 0f;
                sb.AppendLine($"    GetColors().CenterPixel(RGBA): ({center.r}, {center.g}, {center.b}, {center.a})");
                sb.AppendLine($"    GetColors().SampledAvgLuma01({gx}x{gy}): {avgLuma01:F4}");
            }
            else
            {
                sb.AppendLine("    GetColors(): <buffer length smaller than expected resolution>");
            }
        }
        catch (Exception ex)
        {
            sb.AppendLine($"    GetColors(): <exception: {ex.Message}>");
        }
    }

    private static string FormatResolutionList(Vector2Int[] resolutions)
    {
        if (resolutions == null)
        {
            return "<null>";
        }

        if (resolutions.Length == 0)
        {
            return "<empty>";
        }

        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < resolutions.Length; i++)
        {
            if (i > 0)
            {
                sb.Append(", ");
            }

            sb.Append(FormatResolution(resolutions[i]));
        }

        return sb.ToString();
    }

    private static string FormatResolution(Vector2Int value)
    {
        return $"{value.x}x{value.y}";
    }

    private static string FormatMaterial(Material material)
    {
        if (material == null)
        {
            return "null";
        }

        return material.name;
    }

    private static string FormatTexture(Texture texture)
    {
        if (texture == null)
        {
            return "<null>";
        }

        return $"type={texture.GetType().Name}, size={texture.width}x{texture.height}, format={texture.graphicsFormat}, mip={texture.mipmapCount}";
    }

    private static string FormatVector2(Vector2 value)
    {
        return $"({value.x:F4}, {value.y:F4})";
    }

    private static string FormatVector3(Vector3 value)
    {
        return $"({value.x:F4}, {value.y:F4}, {value.z:F4})";
    }

    private static string FormatQuaternion(Quaternion q)
    {
        return $"({q.x:F5}, {q.y:F5}, {q.z:F5}, {q.w:F5})";
    }

    private static string GetHierarchyPath(Transform t)
    {
        if (t == null)
        {
            return "<null>";
        }

        StringBuilder sb = new StringBuilder(128);
        while (t != null)
        {
            if (sb.Length == 0)
            {
                sb.Insert(0, t.name);
            }
            else
            {
                sb.Insert(0, '/').Insert(0, t.name);
            }

            t = t.parent;
        }

        return sb.ToString();
    }
}
