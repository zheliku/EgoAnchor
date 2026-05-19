using UnityEngine;

namespace EgoAnchor.V3.Anchor
{
    /// <summary>
    /// v3 anchor 指数平滑处理器。
    ///
    /// 这是轻量 low-pass baseline，不应被误认为论文最终方法。需要更强抖动抑制时，
    /// 可以在处理器链中改用 AnchorKalmanPoseProcessor，或后续替换为 One Euro / reliability-aware filter。
    /// </summary>
    public sealed class AnchorLowPassPoseProcessor : AnchorPoseProcessor
    {
        /// <summary>位置指数平滑速度。</summary>
        [Header("Smoothing")]
        [Tooltip("位置指数平滑速度，单位约为 1/s。越大越贴近 raw，越小越稳但延迟更明显。")]
        [Min(0.01f)]
        [SerializeField] private float positionSmoothSpeed = 3f;

        /// <summary>旋转指数平滑速度。</summary>
        [Tooltip("旋转指数平滑速度，单位约为 1/s。越大越贴近 raw，越小越稳但延迟更明显。")]
        [Min(0.01f)]
        [SerializeField] private float rotationSmoothSpeed = 3f;

        /// <summary>首次收到位姿时是否直接贴合。</summary>
        [Tooltip("首次收到位姿时是否直接贴合，避免初始从原点缓慢收敛。")]
        [SerializeField] private bool snapOnFirstPose = true;

        /// <summary>当前是否已有平滑状态。</summary>
        private bool hasSmoothedPose;

        /// <summary>平滑后的位置。</summary>
        private Vector3 smoothedPosition;

        /// <summary>平滑后的旋转。</summary>
        private Quaternion smoothedRotation = Quaternion.identity;

        /// <summary>上一帧样本时间，单位秒。</summary>
        private double lastSampleTime;

        /// <summary>当前平滑输出，仅用于调试读取。</summary>
        public Pose SmoothedPose => new Pose(smoothedPosition, smoothedRotation);

        /// <summary>
        /// 对 raw world pose 做指数平滑。
        /// </summary>
        protected override Pose ProcessPose(Pose inputPose, long frameId, double sampleTime)
        {
            if (!hasSmoothedPose)
            {
                smoothedPosition = inputPose.position;
                smoothedRotation = inputPose.rotation;
                lastSampleTime = sampleTime;
                hasSmoothedPose = true;

                if (snapOnFirstPose)
                {
                    return SmoothedPose;
                }
            }

            float dt = Mathf.Max((float)(sampleTime - lastSampleTime), 1e-5f);
            lastSampleTime = sampleTime;
            float posT = 1f - Mathf.Exp(-Mathf.Max(positionSmoothSpeed, 0.01f) * dt);
            float rotT = 1f - Mathf.Exp(-Mathf.Max(rotationSmoothSpeed, 0.01f) * dt);

            smoothedPosition = Vector3.Lerp(smoothedPosition, inputPose.position, posT);
            smoothedRotation = Quaternion.Slerp(smoothedRotation, inputPose.rotation, rotT);
            return SmoothedPose;
        }

        /// <summary>
        /// 清空平滑状态，让下一条 pose 重新初始化。
        /// </summary>
        public override void ResetProcessor()
        {
            hasSmoothedPose = false;
            smoothedPosition = Vector3.zero;
            smoothedRotation = Quaternion.identity;
            lastSampleTime = 0.0;
        }
    }
}
