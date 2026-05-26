using UnityEngine;

namespace EgoAnchor.Reliability
{
    /// <summary>
    /// 短时 anchor coasting 预测器。
    ///
    /// 当前位置使用最近两次 accepted stable pose 的速度做短时线性外推；
    /// 旋转暂时保持上一稳定旋转，避免无 IMU/物体运动模型时引入额外错误。
    /// </summary>
    public sealed class AnchorPredictor
    {
        /// <summary>允许预测的最大时间，单位秒。</summary>
        private readonly double maxCoastSeconds;

        /// <summary>上一 accepted stable pose。</summary>
        private Pose lastPose;

        /// <summary>上一 accepted stable pose 时间，单位秒。</summary>
        private double lastTimeSeconds;

        /// <summary>估计 world-space 线速度，单位米/秒。</summary>
        private Vector3 velocity;

        /// <summary>是否已有预测状态。</summary>
        private bool hasState;

        /// <summary>
        /// 构造短时预测器。
        /// </summary>
        /// <param name="maxCoastSeconds">允许预测的最大时间，单位秒。</param>
        public AnchorPredictor(double maxCoastSeconds = 0.45)
        {
            this.maxCoastSeconds = maxCoastSeconds > 0.0 ? maxCoastSeconds : 0.45;
        }

        /// <summary>是否已有预测状态。</summary>
        public bool HasState => hasState;

        /// <summary>
        /// 用 accepted stable pose 更新预测状态。
        /// </summary>
        /// <param name="pose">最新 accepted stable pose。</param>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        public void Observe(Pose pose, double sampleTimeSeconds)
        {
            if (hasState)
            {
                float dt = Mathf.Max((float)(sampleTimeSeconds - lastTimeSeconds), 1e-5f);
                velocity = (pose.position - lastPose.position) / dt;
            }
            else
            {
                velocity = Vector3.zero;
                hasState = true;
            }

            lastPose = pose;
            lastTimeSeconds = sampleTimeSeconds;
        }

        /// <summary>
        /// 尝试生成短时预测 pose。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="pose">预测出的 world pose。</param>
        /// <returns>是否在允许 coasting 时间内生成预测。</returns>
        public bool TryPredict(double sampleTimeSeconds, out Pose pose)
        {
            pose = lastPose;
            if (!hasState)
            {
                return false;
            }

            double dt = sampleTimeSeconds - lastTimeSeconds;
            if (dt < 0.0 || dt > maxCoastSeconds)
            {
                return false;
            }

            pose = new Pose(lastPose.position + velocity * (float)dt, lastPose.rotation);
            return true;
        }

        /// <summary>
        /// 清空预测状态。
        /// </summary>
        public void Reset()
        {
            hasState = false;
            lastPose = Pose.identity;
            lastTimeSeconds = 0.0;
            velocity = Vector3.zero;
        }
    }
}
