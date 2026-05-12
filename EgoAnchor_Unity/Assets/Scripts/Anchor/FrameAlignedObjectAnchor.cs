using System;
using System.Collections.Generic;
using Meta.XR;
using UnityEngine;
using UnityEngine.Events;

/// <summary>
/// Anchor pose event.
/// Parameters: worldAnchorPose, frameId.
/// </summary>
[Serializable]
public class AnchorPoseEvent : UnityEvent<Pose, long> { }

/// <summary>
/// Anchor application event.
/// Parameters: worldAnchorPose, frameId, sampleTime.
/// </summary>
[Serializable]
public class AnchorApplyEvent : UnityEvent<Pose, long, float> { }

/// <summary>
/// Frame-aligned real-object anchor applier.
///
/// 职责边界：
/// - 通过 HandleFrameEncoded 缓存发送 stereo 帧时的 Passthrough camera pose，用 frame_id 对齐 Python 回包。
/// - 接收 PoseDecoder 输出的相机局部 object pose。
/// - 使用对应发送帧的 camera pose，把局部 object pose 转为 Unity world anchor pose。
/// - 在 Update 中按 processors 列表顺序处理 raw anchor pose，并应用最终 processed anchor pose。
/// - OnBeforeAnchorApply / OnAfterAnchorApply 仅用于通知，不用于修改 pose。
/// </summary>
public class FrameAlignedObjectAnchor : MonoBehaviour
{
    [Header("Alignment")]
    [Tooltip("左侧 PassthroughCameraAccess。Python pose 基于左目图像时，直接使用 GetCameraPose() 作为发送帧相机世界姿态。")]
    [SerializeField] private PassthroughCameraAccess sourceCameraAccess;

    [Min(64)]
    [Tooltip("按 frame_id 缓存的发送帧 camera pose 数量。需要覆盖 Python 推理与网络回包期间的最大在途帧数。")]
    [SerializeField] private int cameraPoseCacheSize = 512;

    [Header("Processors")]
    [Tooltip("按顺序处理 world raw anchor pose 的处理器列表。例如只放 AnchorSmoother，或只放 AnchorKalmanFilter。")]
    [SerializeField] private List<AnchorProcessor> processors = new List<AnchorProcessor>();

    [Header("Events")]
    [Tooltip("收到有效 pose 并转换到 Unity 世界 anchor 后触发（rawWorldAnchorPose, frameId）。")]
    public AnchorPoseEvent OnAnchorPoseResolved = new AnchorPoseEvent();

    [Tooltip("每帧应用 anchor 前触发（rawWorldAnchorPose, frameId, sampleTime）。通知事件，不通过事件参数修改 pose。")]
    public AnchorApplyEvent OnBeforeAnchorApply = new AnchorApplyEvent();

    [Tooltip("anchor pose 应用到 Transform 后触发（processedAnchorPose, frameId, sampleTime）。")]
    public AnchorApplyEvent OnAfterAnchorApply = new AnchorApplyEvent();

    private Pose _rawWorldAnchorPose = Pose.identity;
    private Pose _processedWorldAnchorPose = Pose.identity;
    private long _latestFrameId = -1;
    private bool _hasAnchorPose;

    private float _lastFrameMissLogTime = -99f;
    private readonly Dictionary<long, Pose> _cameraPoseCache = new Dictionary<long, Pose>();
    private readonly Queue<long> _cameraPoseOrder = new Queue<long>();

    public Pose RawWorldAnchorPose => _rawWorldAnchorPose;
    public Pose ProcessedWorldAnchorPose => _processedWorldAnchorPose;
    public long LatestFrameId => _latestFrameId;
    public bool HasAnchorPose => _hasAnchorPose;

    private void Awake()
    {
        OnAnchorPoseResolved ??= new AnchorPoseEvent();
        OnBeforeAnchorApply ??= new AnchorApplyEvent();
        OnAfterAnchorApply ??= new AnchorApplyEvent();
    }

    /// <summary>
    /// 在 QuestStereoEncoder.OnFrameEncoded 中调用：缓存发送该 frame_id 时的 Passthrough camera 姿态。
    /// </summary>
    public void HandleFrameEncoded(long frameId, Pose cameraPose)
    {
        if (frameId <= 0)
        {
            return;
        }

        if (!_cameraPoseCache.ContainsKey(frameId))
        {
            _cameraPoseOrder.Enqueue(frameId);
        }

        _cameraPoseCache[frameId] = cameraPose;
        int maxCount = Mathf.Max(64, cameraPoseCacheSize);
        while (_cameraPoseOrder.Count > maxCount)
        {
            long oldFrameId = _cameraPoseOrder.Dequeue();
            _cameraPoseCache.Remove(oldFrameId);
        }
    }

    /// <summary>
    /// 在 PoseDecoder.OnPoseReceived 中调用：接收解码后的相机局部 object pose，并转换为 Unity world anchor pose。
    /// </summary>
    public virtual void ApplyCameraPose(Pose cameraLocalObjectPose, long frameId)
    {
        if (frameId <= 0 || !_cameraPoseCache.TryGetValue(frameId, out Pose cameraPose))
        {
            float now = Time.realtimeSinceStartup;
            if (now - _lastFrameMissLogTime > 2f)
            {
                _lastFrameMissLogTime = now;
                Debug.LogWarning(
                    $"[FrameAlignedObjectAnchor] 未命中发送帧 camera pose 缓存 frameId={frameId} cacheSize={_cameraPoseCache.Count} " +
                    $"sourceCameraAccess={(sourceCameraAccess == null ? "null" : sourceCameraAccess.name)}",
                    this);
            }
            return;
        }

        _rawWorldAnchorPose = new Pose(
            cameraPose.position + cameraPose.rotation * cameraLocalObjectPose.position,
            cameraPose.rotation * cameraLocalObjectPose.rotation
        );
        _processedWorldAnchorPose = _rawWorldAnchorPose;
        _latestFrameId = frameId;
        _hasAnchorPose = true;

        OnAnchorPoseResolved?.Invoke(_rawWorldAnchorPose, frameId);
    }

    public void ResetAnchorProcessors()
    {
        foreach (AnchorProcessor processor in processors)
        {
            processor?.ResetProcessor();
        }
    }

    private void Update()
    {
        if (!_hasAnchorPose)
        {
            return;
        }

        float sampleTime = Time.realtimeSinceStartup;
        OnBeforeAnchorApply?.Invoke(_rawWorldAnchorPose, _latestFrameId, sampleTime);

        Pose processedPose = _rawWorldAnchorPose;
        foreach (AnchorProcessor processor in processors)
        {
            processedPose = processor == null
                ? processedPose
                : processor.Process(processedPose, _latestFrameId, sampleTime);
        }

        _processedWorldAnchorPose = processedPose;
        transform.SetPositionAndRotation(_processedWorldAnchorPose.position, _processedWorldAnchorPose.rotation);
        OnAfterAnchorApply?.Invoke(_processedWorldAnchorPose, _latestFrameId, sampleTime);
    }
}
