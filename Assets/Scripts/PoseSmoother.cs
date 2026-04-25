using UnityEngine;

/// <summary>
/// PoseFollow 的指数平滑插件。
///
/// 用法：
/// 1. 挂到与 PoseFollow 同一个对象（可自动绑定）。
/// 2. PoseFollow 会调用 ApplySmoothing(Pose) 获取平滑后的位姿。
/// </summary>
public class PoseSmoother : MonoBehaviour
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

    /// <summary>
    /// 对输入世界位姿执行指数平滑。
    /// </summary>
    /// <param name="worldPose">PoseFollow 计算出的原始世界位姿。</param>
    /// <param name="frameId">该位姿对应的输入双目帧号，仅用于调试/未来扩展。</param>
    /// <param name="sampleTime">采样时间，仅用于调试/未来扩展。</param>
    /// <returns>平滑后的世界位姿。</returns>
    public Pose ApplySmoothing(Pose worldPose, long frameId, float sampleTime)
    {
        // 首帧只初始化一次，不能把 snapOnFirstPose 写进条件，
        // 否则在 snapOnFirstPose=true 时会每帧重置，导致完全不平滑。
        if (!_hasSmoothedPose)
        {
            _smoothedPosition = worldPose.position;
            _smoothedRotation = worldPose.rotation;
            _hasSmoothedPose = true;

            // 第一次可直接贴合，也可以继续走一次平滑（由 snapOnFirstPose 控制）。
            if (snapOnFirstPose)
            {
                return new Pose(_smoothedPosition, _smoothedRotation);
            }
        }

        // 使用指数响应形式：速度越大，越快贴近目标；dt 越大，单帧插值比例越大。
        // 相比固定 Lerp 系数，该写法在不同帧率下手感更一致。
        float dt = Mathf.Max(Time.deltaTime, 1e-5f);
        float posT = 1f - Mathf.Exp(-positionSmoothSpeed * dt);
        float rotT = 1f - Mathf.Exp(-rotationSmoothSpeed * dt);

        // 平移用 Lerp，旋转用 Slerp，避免四元数线性插值造成非单位旋转。
        _smoothedPosition = Vector3.Lerp(_smoothedPosition, worldPose.position, posT);
        _smoothedRotation = Quaternion.Slerp(_smoothedRotation, worldPose.rotation, rotT);

        return new Pose(_smoothedPosition, _smoothedRotation);
    }
}
