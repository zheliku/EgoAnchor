using System;
using System.Collections.Generic;
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
/// 默认行为：
/// - 无任何处理器时，直接同步位姿（不平滑）。
///
/// 可插拔行为：
/// - 在 Inspector 中把 QuestStereoEncoder.OnFrameEncoded 绑定到 HandleFrameEncoded。
/// - 通过 OnBeforePoseApply/OnAfterPoseApply 监听应用过程。
/// - 需要平滑时由 PoseSmoother 组件处理，不再依赖 PoseFrame 包装对象。
/// </summary>
public class PoseFollow : MonoBehaviour
{
    [Header("Alignment")]
    [Tooltip("用于对齐回包位姿的发送时参考目标。通常绑定发送端相机或其父节点。")]
    [SerializeField] private Transform sourceTarget;
    [Min(64)]
    [SerializeField] private int sourceTargetCacheSize = 512;

    [Header("Smoothing")]
    [Tooltip("可选平滑器。为空时直接应用原始位姿。")]
    [SerializeField] private PoseSmoother poseSmoother;

    [Header("Events")]
    [Tooltip("收到有效 Pose 时触发。")]
    public PoseReceivedEvent OnPoseReceived = new PoseReceivedEvent();

    [Tooltip("应用位姿前触发（worldPose, frameId, sampleTime）。")]
    public PoseApplyEvent OnBeforePoseApply = new PoseApplyEvent();

    [Tooltip("位姿应用到 Transform 后触发（worldPose, frameId, sampleTime）。")]
    public PoseApplyEvent OnAfterPoseApply = new PoseApplyEvent();

    // 最近一次解码得到的目标位姿（世界坐标）。
    private Vector3 _targetWorldPosition;
    private Quaternion _targetWorldRotation = Quaternion.identity;
    private long _latestFrameId = -1;
    private bool _hasTargetPose;

    private float _lastFrameMissLogTime = -99f;
    private float _lastCacheBailLogTime = -99f;

    private readonly Dictionary<long, Pose> _sourceTargetPoseCache =
        new Dictionary<long, Pose>();
    private readonly Queue<long> _sourceTargetPoseOrder = new Queue<long>();

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

        if (poseSmoother == null)
        {
            poseSmoother = GetComponent<PoseSmoother>();
        }
    }

    /// <summary>
    /// 在 Decoder 事件中调用：接收 pose 并更新 targetPose。
    ///
    /// 注意：
    /// - 这里不直接改 transform。
    /// - 真正的位姿应用在 Update 中每帧执行，避免受网络输入帧率（如 5fps）限制。
    /// </summary>
    public virtual void FollowTarget(Pose pose, long frameId)
    {
        OnPoseReceived?.Invoke(pose, frameId);

        float now = Time.realtimeSinceStartup;
        if (frameId <= 0 || !_sourceTargetPoseCache.TryGetValue(frameId, out Pose sourceTargetPose))
        {
            if (now - _lastFrameMissLogTime > 2f)
            {
                _lastFrameMissLogTime = now;
                int cacheCount = _sourceTargetPoseCache.Count;
                Debug.LogWarning(
                    $"[PoseFollow] 未命中发送帧缓存 frameId={frameId} cacheSize={cacheCount} " +
                    $"sourceTarget={(sourceTarget == null ? "null" : sourceTarget.name)}", this);
            }
            return;
        }

        Vector3 localPosition = pose.position;
        Quaternion localRotation = pose.rotation;

        // 注意命名：
        // - localPosition/localRotation：由 pose_matrix 解出的“参考系下位姿”（通常是相机系）。
        // - worldPosition/worldRotation：转换到 Unity 世界坐标后，最终要应用到 Transform 的位姿。
        Vector3 worldPosition;
        Quaternion worldRotation;

        worldPosition = sourceTargetPose.position + sourceTargetPose.rotation * localPosition;
        worldRotation = sourceTargetPose.rotation * localRotation;

        _targetWorldPosition = worldPosition;
        _targetWorldRotation = worldRotation;
        _latestFrameId = frameId;
        _hasTargetPose = true;
    }

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

    private void Update()
    {
        if (!_hasTargetPose)
        {
            return;
        }

        float sampleTime = Time.realtimeSinceStartup;
        Pose rawWorldPose = new Pose(_targetWorldPosition, _targetWorldRotation);
        OnBeforePoseApply?.Invoke(rawWorldPose, _latestFrameId, sampleTime);

        Pose appliedPose = rawWorldPose;
        if (poseSmoother != null)
        {
            appliedPose = poseSmoother.ApplySmoothing(rawWorldPose, _latestFrameId, sampleTime);
        }

        transform.SetPositionAndRotation(appliedPose.position, appliedPose.rotation);
        OnAfterPoseApply?.Invoke(appliedPose, _latestFrameId, sampleTime);
    }
}
