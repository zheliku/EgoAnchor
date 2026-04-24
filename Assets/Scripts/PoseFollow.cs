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
/// - 通过 OnBeforePoseApply/OnAfterPoseApply 监听应用过程。
/// - 需要平滑时由 PoseSmoother 组件处理，不再依赖 PoseFrame 包装对象。
/// </summary>
public class PoseFollow : MonoBehaviour
{
    [Header("Alignment")]
    [Tooltip("发送帧事件来源（通常为 QuestStereoEncoder）。")]
    [SerializeField] private QuestStereoEncoder frameSourceEncoder;
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

    [Header("Debug")]
    [SerializeField] private bool enableVerboseDebugLog;
    [Range(1, 300)]
    [SerializeField] private int debugLogInterval = 30;

    // 最近一次解码得到的目标位姿（世界坐标）。
    private Vector3 _targetWorldPosition;
    private Quaternion _targetWorldRotation = Quaternion.identity;
    private long _latestFrameId = -1;
    private bool _hasTargetPose;

    // 接收频率统计（按 Decoder 回调频率）。
    private float _lastPoseReceiveTime = -1f;
    private float _receiveIntervalEma;

    // 应用频率统计（按 Update 频率）。
    private float _lastApplyTime = -1f;
    private float _applyIntervalEma;

    private int _applyFrameCount;
    private float _lastFrameMissLogTime = -99f;
    private float _lastCacheBailLogTime = -99f;
    private float _lastFollowOkLogTime = -99f;

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

        if (frameSourceEncoder == null)
        {
            frameSourceEncoder = FindFirstObjectByType<QuestStereoEncoder>();
        }

        if (poseSmoother == null)
        {
            poseSmoother = GetComponent<PoseSmoother>();
        }
    }

    private void OnEnable()
    {
        if (frameSourceEncoder != null)
        {
            frameSourceEncoder.OnFrameEncoded.AddListener(HandleFrameEncoded);
        }
    }

    private void OnDisable()
    {
        if (frameSourceEncoder != null)
        {
            frameSourceEncoder.OnFrameEncoded.RemoveListener(HandleFrameEncoded);
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

        // 诊断：每2秒打印一次 FollowTarget 被调用（说明 Decoder→FollowTarget 通了）。
        float now = Time.realtimeSinceStartup;
        if (now - _lastFollowOkLogTime > 2f)
        {
            _lastFollowOkLogTime = now;
            Debug.Log($"[PoseFollow] FollowTarget called frameId={frameId} pose.pos=({pose.position.x:F3},{pose.position.y:F3},{pose.position.z:F3})", this);
        }

        if (!TryGetSourceTargetPose(frameId, out Pose sourceTargetPose))
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

        UpdateReceiveStats();
    }

    public void HandleFrameEncoded(long frameId)
    {
        // 诊断：每2秒打印一次 HandleFrameEncoded 状态。
        float now = Time.realtimeSinceStartup;
        if (now - _lastCacheBailLogTime > 2f)
        {
            _lastCacheBailLogTime = now;
            if (sourceTarget == null)
            {
                Debug.LogWarning(
                    $"[PoseFollow] HandleFrameEncoded bailed: sourceTarget=null (frameSourceEncoder={(frameSourceEncoder == null ? "null" : frameSourceEncoder.name)})", this);
            }
            else
            {
                Debug.Log(
                    $"[PoseFollow] HandleFrameEncoded frameId={frameId} srcPos=({sourceTarget.position.x:F3},{sourceTarget.position.y:F3},{sourceTarget.position.z:F3}) cacheSize={_sourceTargetPoseCache.Count}", this);
            }
        }

        if (frameId <= 0 || sourceTarget == null)
        {
            return;
        }

        CacheSourceTargetPose(
            frameId,
            new Pose(sourceTarget.position, sourceTarget.rotation),
            Mathf.Max(64, sourceTargetCacheSize)
        );
    }

    private bool TryGetSourceTargetPose(long frameId, out Pose sourceTargetPose)
    {
        sourceTargetPose = Pose.identity;
        if (frameId <= 0)
        {
            return false;
        }

        return _sourceTargetPoseCache.TryGetValue(frameId, out sourceTargetPose);
    }

    private void CacheSourceTargetPose(long frameId, Pose pose, int maxCount)
    {
        if (!_sourceTargetPoseCache.ContainsKey(frameId))
        {
            _sourceTargetPoseOrder.Enqueue(frameId);
        }

        _sourceTargetPoseCache[frameId] = pose;
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

        UpdateDebugStats(rawWorldPose, appliedPose, sampleTime);
    }

    private void UpdateReceiveStats()
    {
        float now = Time.realtimeSinceStartup;
        if (_lastPoseReceiveTime > 0f)
        {
            float interval = Mathf.Max(now - _lastPoseReceiveTime, 1e-5f);
            _receiveIntervalEma = _receiveIntervalEma <= 0f
                ? interval
                : (_receiveIntervalEma * 0.85f + interval * 0.15f);
        }
        _lastPoseReceiveTime = now;
    }

    private void UpdateDebugStats(Pose rawWorldPose, Pose appliedPose, float sampleTime)
    {
        float now = sampleTime;
        if (_lastApplyTime > 0f)
        {
            float interval = Mathf.Max(now - _lastApplyTime, 1e-5f);
            _applyIntervalEma = _applyIntervalEma <= 0f
                ? interval
                : (_applyIntervalEma * 0.85f + interval * 0.15f);
        }
        _lastApplyTime = now;

        if (!enableVerboseDebugLog)
        {
            return;
        }

        _applyFrameCount++;
        if (_applyFrameCount % Mathf.Max(1, debugLogInterval) != 0)
        {
            return;
        }

        float applyHz = _applyIntervalEma > 1e-5f ? 1f / _applyIntervalEma : 0f;
        float receiveHz = _receiveIntervalEma > 1e-5f ? 1f / _receiveIntervalEma : 0f;
        float posError = Vector3.Distance(rawWorldPose.position, appliedPose.position);
        float rotError = Quaternion.Angle(rawWorldPose.rotation, appliedPose.rotation);

        Debug.Log(
            $"[PoseFollow] recvHz={receiveHz:F2}, applyHz={applyHz:F2}, posDelta={posError:F4}m, rotDelta={rotError:F2}deg, frameId={_latestFrameId}",
            this
        );
    }
}
