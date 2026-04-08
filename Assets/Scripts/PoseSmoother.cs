using UnityEngine;

/// <summary>
/// PoseFollow 的指数平滑插件。
///
/// 用法：
/// 1. 挂到与 PoseFollow 同一个对象，手动指定 poseFollow。
/// 2. 订阅 PoseFollow.BeforePoseApply。
/// 3. 修改 frame.WorldPosition / frame.WorldRotation，实现“可插拔平滑”。
/// </summary>
public class PoseSmoother : MonoBehaviour
{
    [Header("Smoothing")]
    [Min(0.01f)]
    [SerializeField] private float positionSmoothSpeed = 10f;
    [Min(0.01f)]
    [SerializeField] private float rotationSmoothSpeed = 12f;
    [Tooltip("首次收到位姿时是否直接贴合，避免初始跳变。")]
    [SerializeField] private bool snapOnFirstPose = true;

    private bool _hasSmoothedPose;
    private Vector3 _smoothedPosition;
    private Quaternion _smoothedRotation = Quaternion.identity;

    public void ProcessPose(PoseFrame frame)
    {
        if (!_hasSmoothedPose || snapOnFirstPose)
        {
            _smoothedPosition = frame.WorldPosition;
            _smoothedRotation = frame.WorldRotation;
            _hasSmoothedPose = true;

            // 第一次可直接贴合，也可以继续走一次平滑（由 snapOnFirstPose 控制）。
            if (snapOnFirstPose)
            {
                frame.WorldPosition = _smoothedPosition;
                frame.WorldRotation = _smoothedRotation;
                return;
            }
        }

        float dt = Mathf.Max(Time.deltaTime, 1e-5f);
        float posT = 1f - Mathf.Exp(-positionSmoothSpeed * dt);
        float rotT = 1f - Mathf.Exp(-rotationSmoothSpeed * dt);

        _smoothedPosition = Vector3.Lerp(_smoothedPosition, frame.WorldPosition, posT);
        _smoothedRotation = Quaternion.Slerp(_smoothedRotation, frame.WorldRotation, rotT);

        frame.WorldPosition = _smoothedPosition;
        frame.WorldRotation = _smoothedRotation;
    }
}
