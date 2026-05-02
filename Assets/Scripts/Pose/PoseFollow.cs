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
/// - 通过 HandleFrameEncoded 缓存发送 stereo 帧时的 sourceTarget 姿态，用 frame_id 对齐 Python 回包。
/// - 接收 PoseDecoder 输出的相机局部 pose。
/// - 使用对应发送帧的 sourceTarget 姿态，以及可选左相机 LensOffset，把局部 pose 转为 Unity 世界 raw pose。
/// - 在 Update 中按 processors 列表顺序处理 raw pose，并应用最终 processed pose。
/// - OnBeforePoseApply / OnAfterPoseApply 仅用于通知，不用于修改 pose。
/// </summary>
public class PoseFollow : MonoBehaviour
{
    [Header("Alignment")]
    [Tooltip("用于把相机局部位姿转换到 Unity 世界坐标的参考目标。通常绑定 Quest/HMD/CenterEye 或其等价参考节点。")]
    [SerializeField] private Transform sourceTarget;

    [Min(64)]
    [Tooltip("按 frame_id 缓存的发送帧参考姿态数量。需要覆盖 Python 推理与网络回包期间的最大在途帧数。")]
    [SerializeField] private int sourceTargetCacheSize = 512;

    [Header("Camera Offset")]
    [Tooltip("左侧 PassthroughCameraAccess。Python pose 基于左目图像时，用其 Intrinsics.LensOffset 将 sourceTarget 参考系修正到左相机光心。")]
    [SerializeField] private PassthroughCameraAccess sourceCameraAccess;

    [Tooltip("是否把 sourceTarget 与左相机 Intrinsics.LensOffset 组合后再应用 pose。若 sourceTarget 已经是左相机位姿，应关闭以避免重复应用外参。")]
    [SerializeField] private bool applySourceCameraLensOffset = true;

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
    private float _lastCacheBailLogTime = -99f;

    private readonly Dictionary<long, Pose> _sourceTargetPoseCache = new Dictionary<long, Pose>();
    private readonly Queue<long> _sourceTargetPoseOrder = new Queue<long>();

    public Pose RawWorldPose => _rawWorldPose;
    public Pose ProcessedWorldPose => _processedWorldPose;
    public long LatestFrameId => _latestFrameId;
    public bool HasPose => _hasPose;

    private void Awake()
    {
        if (OnPoseReceived == null)
        {
            OnPoseReceived = new PoseReceivedEvent();
        }

        if (OnBeforePoseApply == null)
        {
            OnBeforePoseApply = new PoseApplyEvent();
        }

        if (OnAfterPoseApply == null)
        {
            OnAfterPoseApply = new PoseApplyEvent();
        }
    }

    /// <summary>
    /// 在 QuestStereoEncoder.OnFrameEncoded 中调用：缓存发送该 frame_id 时的参考姿态。
    /// </summary>
    public void HandleFrameEncoded(long frameId)
    {
        if (frameId <= 0 || sourceTarget == null)
        {
            if (sourceTarget == null && Time.realtimeSinceStartup - _lastCacheBailLogTime > 2f)
            {
                _lastCacheBailLogTime = Time.realtimeSinceStartup;
                Debug.LogWarning("[PoseFollow] 无法缓存发送帧姿态：sourceTarget=null。", this);
            }
            return;
        }

        if (!_sourceTargetPoseCache.ContainsKey(frameId))
        {
            _sourceTargetPoseOrder.Enqueue(frameId);
        }

        _sourceTargetPoseCache[frameId] = new Pose(sourceTarget.position, sourceTarget.rotation);
        int maxCount = Mathf.Max(64, sourceTargetCacheSize);
        while (_sourceTargetPoseOrder.Count > maxCount)
        {
            long oldFrameId = _sourceTargetPoseOrder.Dequeue();
            _sourceTargetPoseCache.Remove(oldFrameId);
        }
    }

    /// <summary>
    /// 在 PoseDecoder.OnPoseReceived 中调用：接收解码后的相机局部 pose，并转换为 Unity 世界 raw pose。
    /// </summary>
    public virtual void FollowTarget(Pose pose, long frameId)
    {
        if (frameId <= 0 || !_sourceTargetPoseCache.TryGetValue(frameId, out Pose sourceTargetPose))
        {
            float now = Time.realtimeSinceStartup;
            if (now - _lastFrameMissLogTime > 2f)
            {
                _lastFrameMissLogTime = now;
                Debug.LogWarning(
                    $"[PoseFollow] 未命中发送帧缓存 frameId={frameId} cacheSize={_sourceTargetPoseCache.Count} " +
                    $"sourceTarget={(sourceTarget == null ? "null" : sourceTarget.name)}",
                    this);
            }
            return;
        }

        Vector3 referencePosition = sourceTargetPose.position;
        Quaternion referenceRotation = sourceTargetPose.rotation;

        if (applySourceCameraLensOffset && sourceCameraAccess != null && sourceCameraAccess.IsPlaying)
        {
            Pose lensOffset = sourceCameraAccess.Intrinsics.LensOffset;
            referencePosition += referenceRotation * lensOffset.position;
            referenceRotation *= lensOffset.rotation;
        }

        _rawWorldPose = new Pose(
            referencePosition + referenceRotation * pose.position,
            referenceRotation * pose.rotation
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
            if (processor != null)
            {
                processor.ResetProcessor();
            }
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
            if (processor != null)
            {
                processedPose = processor.Process(processedPose, _latestFrameId, sampleTime);
            }
        }

        _processedWorldPose = processedPose;
        transform.SetPositionAndRotation(_processedWorldPose.position, _processedWorldPose.rotation);
        OnAfterPoseApply?.Invoke(_processedWorldPose, _latestFrameId, sampleTime);
    }
}
