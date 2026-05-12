using System;
using System.Collections.Generic;
using Meta.XR;
using UnityEngine;
using UnityEngine.Events;

/// <summary>
/// 位姿应用事件。
/// 参数：worldPose, frameId, sampleTime。
/// </summary>
[Serializable]
public class PoseApplyEvent : UnityEvent<Pose, long, float> { }

/// <summary>
/// 通用位姿消费器。
///
/// 职责边界：
/// - 通过 HandleFrameEncoded 缓存发送 stereo 帧时的 Passthrough camera 姿态，用 frame_id 对齐 Python 回包。
/// - 接收 PoseDecoder 输出的相机局部 pose。
/// - 使用对应发送帧的 camera pose，把局部 pose 转为 Unity 世界 raw pose。
/// - 在 Update 中按 processors 列表顺序处理 raw pose，并应用最终 processed pose。
/// - OnBeforePoseApply / OnAfterPoseApply 仅用于通知，不用于修改 pose。
/// </summary>
public class PoseFollow : MonoBehaviour
{
    [Header("Alignment")]
    [Tooltip("左侧 PassthroughCameraAccess。Python pose 基于左目图像时，直接使用 GetCameraPose() 作为发送帧相机世界姿态。")]
    [SerializeField] private PassthroughCameraAccess sourceCameraAccess;

    [Min(64)]
    [Tooltip("按 frame_id 缓存的发送帧 camera pose 数量。需要覆盖 Python 推理与网络回包期间的最大在途帧数。")]
    [SerializeField] private int cameraPoseCacheSize = 512;

    [Header("Processors")]
    [Tooltip("按顺序处理 world raw pose 的处理器列表。例如只放 PoseSmoother，或只放 PoseKalmanFilter。")]
    [SerializeField] private List<PoseProcessor> processors = new List<PoseProcessor>();

    [Header("Events")]
    [Tooltip("收到有效 pose 并转换到 Unity 世界坐标后触发（rawWorldPose, frameId）。")]
    public PoseReceivedEvent OnPoseReceived = new PoseReceivedEvent();

    [Tooltip("每帧应用位姿前触发（rawWorldPose, frameId, sampleTime）。通知事件，不通过事件参数修改 pose。")]
    public PoseApplyEvent OnBeforePoseApply = new PoseApplyEvent();

    [Tooltip("位姿应用到 Transform 后触发（processedPose, frameId, sampleTime）。")]
    public PoseApplyEvent OnAfterPoseApply = new PoseApplyEvent();

    private Pose _rawWorldPose = Pose.identity;
    private Pose _processedWorldPose = Pose.identity;
    private long _latestFrameId = -1;
    private bool _hasPose;

    private float _lastFrameMissLogTime = -99f;
    private readonly Dictionary<long, Pose> _cameraPoseCache = new Dictionary<long, Pose>();
    private readonly Queue<long> _cameraPoseOrder = new Queue<long>();

    public Pose RawWorldPose => _rawWorldPose;
    public Pose ProcessedWorldPose => _processedWorldPose;
    public long LatestFrameId => _latestFrameId;
    public bool HasPose => _hasPose;

    private void Awake()
    {
        OnPoseReceived ??= new PoseReceivedEvent();
        OnBeforePoseApply ??= new PoseApplyEvent();
        OnAfterPoseApply ??= new PoseApplyEvent();
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
    /// 在 PoseDecoder.OnPoseReceived 中调用：接收解码后的相机局部 pose，并转换为 Unity 世界 raw pose。
    /// </summary>
    public virtual void FollowTarget(Pose pose, long frameId)
    {
        if (frameId <= 0 || !_cameraPoseCache.TryGetValue(frameId, out Pose cameraPose))
        {
            float now = Time.realtimeSinceStartup;
            if (now - _lastFrameMissLogTime > 2f)
            {
                _lastFrameMissLogTime = now;
                Debug.LogWarning(
                    $"[PoseFollow] 未命中发送帧 camera pose 缓存 frameId={frameId} cacheSize={_cameraPoseCache.Count} " +
                    $"sourceCameraAccess={(sourceCameraAccess == null ? "null" : sourceCameraAccess.name)}",
                    this);
            }
            return;
        }

        _rawWorldPose = new Pose(
            cameraPose.position + cameraPose.rotation * pose.position,
            cameraPose.rotation * pose.rotation
        );
        _processedWorldPose = _rawWorldPose;
        _latestFrameId = frameId;
        _hasPose = true;

        OnPoseReceived?.Invoke(_rawWorldPose, frameId);
    }

    public void ResetProcessors()
    {
        foreach (PoseProcessor processor in processors)
        {
            processor?.ResetProcessor();
        }
    }

    private void Update()
    {
        if (!_hasPose)
        {
            return;
        }

        float sampleTime = Time.realtimeSinceStartup;
        OnBeforePoseApply?.Invoke(_rawWorldPose, _latestFrameId, sampleTime);

        Pose processedPose = _rawWorldPose;
        foreach (PoseProcessor processor in processors)
        {
            processedPose = processor == null
                ? processedPose
                : processor.Process(processedPose, _latestFrameId, sampleTime);
        }

        _processedWorldPose = processedPose;
        transform.SetPositionAndRotation(_processedWorldPose.position, _processedWorldPose.rotation);
        OnAfterPoseApply?.Invoke(_processedWorldPose, _latestFrameId, sampleTime);
    }
}
