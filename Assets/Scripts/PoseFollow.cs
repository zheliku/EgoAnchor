using System;
using UnityEngine;
using UnityEngine.Events;

/// <summary>
/// 可被处理链修改的位姿帧数据。
///
/// 设计说明：
/// - RawWorldPosition/RawWorldRotation：原始计算值（只读）。
/// - WorldPosition/WorldRotation：最终应用值（可被事件监听器修改）。
/// </summary>
[Serializable]
public class PoseFrame
{
    [SerializeField] private PoseData sourcePose;
    [SerializeField] private Vector3 rawWorldPosition;
    [SerializeField] private Quaternion rawWorldRotation;
    [SerializeField] private float sampleTime;

    public PoseData SourcePose => sourcePose;
    public Vector3 RawWorldPosition => rawWorldPosition;
    public Quaternion RawWorldRotation => rawWorldRotation;
    public float SampleTime => sampleTime;

    /// <summary>
    /// 可被处理器修改，最终会应用到目标 Transform。
    /// </summary>
    public Vector3 WorldPosition;

    /// <summary>
    /// 可被处理器修改，最终会应用到目标 Transform。
    /// </summary>
    public Quaternion WorldRotation;

    public PoseFrame(
        PoseData pose,
        Vector3 worldPosition,
        Quaternion worldRotation,
        float timestamp)
    {
        sourcePose = pose;
        rawWorldPosition = worldPosition;
        rawWorldRotation = worldRotation;
        sampleTime = timestamp;
        WorldPosition = worldPosition;
        WorldRotation = worldRotation;
    }
}

/// <summary>
/// PoseFollow 帧事件。
/// </summary>
[Serializable]
public class PoseFrameEvent : UnityEvent<PoseFrame> { }

/// <summary>
/// 通用位姿消费器。
///
/// 默认行为：
/// - 无任何处理器时，直接同步位姿（不平滑）。
///
/// 可插拔行为：
/// - 通过 OnBeforePoseApply 或 BeforePoseApply 事件挂接处理器，
///   修改 PoseFrame.WorldPosition/WorldRotation 即可实现平滑、约束、滤波等插件能力。
/// </summary>
public class PoseFollow : MonoBehaviour
{
    [Header("Reference Transform")]
    [Tooltip("位姿参考系（通常是相机根节点或世界锚点）。")]
    public Transform target;

    [Header("Events")]
    [Tooltip("收到有效 PoseData 时触发。")]
    public PoseDataEvent OnPoseReceived = new PoseDataEvent();

    [Tooltip("应用位姿前触发。可在监听器中修改 frame.WorldPosition / frame.WorldRotation。")]
    public PoseFrameEvent OnBeforePoseApply = new PoseFrameEvent();

    [Tooltip("位姿应用到 Transform 后触发。")]
    public PoseFrameEvent OnAfterPoseApply = new PoseFrameEvent();

    [Header("Debug")]
    [SerializeField] private bool enableVerboseDebugLog;
    [Range(1, 300)]
    [SerializeField] private int debugLogInterval = 30;

    // 最近一次解码得到的目标位姿（世界坐标）。
    private Vector3 _targetWorldPosition;
    private Quaternion _targetWorldRotation = Quaternion.identity;
    private PoseData _latestPoseData;
    private bool _hasTargetPose;

    // 接收频率统计（按 Decoder 回调频率）。
    private float _lastPoseReceiveTime = -1f;
    private float _receiveIntervalEma;

    // 应用频率统计（按 Update 频率）。
    private float _lastApplyTime = -1f;
    private float _applyIntervalEma;

    private int _applyFrameCount;
    private bool _hasWarnedNoReference;

    private void Awake()
    {
        if (OnPoseReceived == null)
        {
            OnPoseReceived = new PoseDataEvent();
        }

        if (OnBeforePoseApply == null)
        {
            OnBeforePoseApply = new PoseFrameEvent();
        }

        if (OnAfterPoseApply == null)
        {
            OnAfterPoseApply = new PoseFrameEvent();
        }
    }

    /// <summary>
    /// 在 Decoder 事件中调用：接收 pose 并更新 targetPose。
    ///
    /// 注意：
    /// - 这里不直接改 transform。
    /// - 真正的位姿应用在 Update 中每帧执行，避免受网络输入帧率（如 5fps）限制。
    /// </summary>
    public virtual void FollowTarget(PoseData pose)
    {
        if (!pose.HasPose || !pose.PoseMatrix.HasValue)
        {
            return;
        }

        OnPoseReceived?.Invoke(pose);

        Matrix4x4 poseMatrix = pose.PoseMatrix.Value;
        Vector3 localPosition = new Vector3(poseMatrix.m03, poseMatrix.m13, poseMatrix.m23);
        Quaternion localRotation = Quaternion.LookRotation(
            new Vector3(poseMatrix.m02, poseMatrix.m12, poseMatrix.m22),
            new Vector3(poseMatrix.m01, poseMatrix.m11, poseMatrix.m21)
        );

        // 注意命名：
        // - localPosition/localRotation：由 pose_matrix 解出的“参考系下位姿”（通常是相机系）。
        // - worldPosition/worldRotation：转换到 Unity 世界坐标后，最终要应用到 Transform 的位姿。
        Vector3 worldPosition;
        Quaternion worldRotation;

        if (target != null)
        {
            // 正确做法：
            // 1) 位置用 TransformPoint，把参考系旋转和平移都考虑进去。
            // 2) 旋转按 world = reference * local 的顺序组合。
            worldPosition = target.TransformPoint(localPosition);
            worldRotation = target.rotation * localRotation;
        }
        else
        {
            worldPosition = localPosition;
            worldRotation = localRotation;

            if (!_hasWarnedNoReference)
            {
                _hasWarnedNoReference = true;
                Debug.LogWarning("[PoseFollow] target 未指定，按世界坐标直接应用位姿。", this);
            }
        }

        _targetWorldPosition = worldPosition;
        _targetWorldRotation = worldRotation;
        _latestPoseData = pose;
        _hasTargetPose = true;

        UpdateReceiveStats();
    }

    private void Update()
    {
        if (!_hasTargetPose)
        {
            return;
        }

        PoseFrame frame = new PoseFrame(
            _latestPoseData,
            _targetWorldPosition,
            _targetWorldRotation,
            Time.realtimeSinceStartup
        );

        // 先触发处理链，给插件机会修改最终输出位姿。
        OnBeforePoseApply?.Invoke(frame);

        transform.SetPositionAndRotation(frame.WorldPosition, frame.WorldRotation);

        OnAfterPoseApply?.Invoke(frame);

        UpdateDebugStats(frame);
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

    private void UpdateDebugStats(PoseFrame frame)
    {
        float now = frame.SampleTime;
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
        float posError = Vector3.Distance(frame.RawWorldPosition, frame.WorldPosition);
        float rotError = Quaternion.Angle(frame.RawWorldRotation, frame.WorldRotation);

        Debug.Log(
            $"[PoseFollow] recvHz={receiveHz:F2}, applyHz={applyHz:F2}, posDelta={posError:F4}m, rotDelta={rotError:F2}deg",
            this
        );
    }
}
