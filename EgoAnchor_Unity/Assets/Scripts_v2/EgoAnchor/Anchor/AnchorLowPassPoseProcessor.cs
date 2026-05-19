using UnityEngine;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// v2 anchor 指数平滑处理器。
    ///
    /// 这是轻量 low-pass baseline，不应被误认为论文最终方法。需要更强抖动抑制时，
    /// 推荐在处理器链中使用 AnchorKalmanPoseProcessor，或后续替换为 One Euro / reliability-aware filter。
    /// </summary>
    public sealed class AnchorLowPassPoseProcessor : AnchorPoseProcessor
    {
        [Header("Smoothing")]
        [Tooltip("位置指数平滑速度，单位约为 1/s。越大越贴近 raw，越小越稳但延迟更明显。")]
        [Min(0.01f)]
        [SerializeField] private float positionSmoothSpeed = 3f;

        [Tooltip("旋转指数平滑速度，单位约为 1/s。越大越贴近 raw，越小越稳但延迟更明显。")]
        [Min(0.01f)]
        [SerializeField] private float rotationSmoothSpeed = 3f;

        [Tooltip("首次收到位姿时是否直接贴合，避免初始跳变。")]
        [SerializeField] private bool snapOnFirstPose = true;

        private bool _hasSmoothedPose;
        private Vector3 _smoothedPosition;
        private Quaternion _smoothedRotation = Quaternion.identity;
        private double _lastSampleTime;

        /// <summary>当前平滑输出，仅用于调试读取。</summary>
        public Pose SmoothedPose => new Pose(_smoothedPosition, _smoothedRotation);

        protected override Pose ProcessPose(Pose inputPose, long frameId, double sampleTime)
        {
            if (!_hasSmoothedPose)
            {
                _smoothedPosition = inputPose.position;
                _smoothedRotation = inputPose.rotation;
                _lastSampleTime = sampleTime;
                _hasSmoothedPose = true;

                if (snapOnFirstPose)
                {
                    return SmoothedPose;
                }
            }

            float dt = Mathf.Max((float)(sampleTime - _lastSampleTime), 1e-5f);
            _lastSampleTime = sampleTime;
            float posT = 1f - Mathf.Exp(-Mathf.Max(positionSmoothSpeed, 0.01f) * dt);
            float rotT = 1f - Mathf.Exp(-Mathf.Max(rotationSmoothSpeed, 0.01f) * dt);

            _smoothedPosition = Vector3.Lerp(_smoothedPosition, inputPose.position, posT);
            _smoothedRotation = Quaternion.Slerp(_smoothedRotation, inputPose.rotation, rotT);
            return SmoothedPose;
        }

        public override void ResetProcessor()
        {
            _hasSmoothedPose = false;
            _smoothedPosition = Vector3.zero;
            _smoothedRotation = Quaternion.identity;
            _lastSampleTime = 0.0;
        }
    }
}
