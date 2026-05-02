using UnityEngine;

/// <summary>
/// PoseFollow 的指数平滑处理器。
///
/// 放入 PoseFollow.processors 列表后生效。处理器内部缓存平滑状态，
/// 每帧接收上游 pose 并返回平滑后的 pose。
/// </summary>
public class PoseSmoother : PoseProcessor
{
    [Header("Smoothing")]
    [Min(0.01f)]
    [SerializeField] private float positionSmoothSpeed = 3f;
    [Min(0.01f)]
    [SerializeField] private float rotationSmoothSpeed = 3f;
    [Tooltip("首次收到位姿时是否直接贴合，避免初始跳变。")]
    [SerializeField] private bool snapOnFirstPose = true;

    private bool _hasSmoothedPose;
    private Vector3 _smoothedPosition;
    private Quaternion _smoothedRotation = Quaternion.identity;

    public Pose SmoothedPose => new Pose(_smoothedPosition, _smoothedRotation);

    protected override Pose ProcessPose(Pose inputPose, long frameId, float sampleTime)
    {
        if (!_hasSmoothedPose)
        {
            _smoothedPosition = inputPose.position;
            _smoothedRotation = inputPose.rotation;
            _hasSmoothedPose = true;

            if (snapOnFirstPose)
            {
                return SmoothedPose;
            }
        }

        // 使用指数响应形式：速度越大，越快贴近目标；dt 越大，单帧插值比例越大。
        // 相比固定 Lerp 系数，该写法在不同帧率下手感更一致。
        float dt = Mathf.Max(Time.deltaTime, 1e-5f);
        float posT = 1f - Mathf.Exp(-positionSmoothSpeed * dt);
        float rotT = 1f - Mathf.Exp(-rotationSmoothSpeed * dt);

        _smoothedPosition = Vector3.Lerp(_smoothedPosition, inputPose.position, posT);
        _smoothedRotation = Quaternion.Slerp(_smoothedRotation, inputPose.rotation, rotT);
        return SmoothedPose;
    }

    public override void ResetProcessor()
    {
        _hasSmoothedPose = false;
        _smoothedPosition = Vector3.zero;
        _smoothedRotation = Quaternion.identity;
    }
}
