using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 渲染层 anchor 输出平滑器。
    ///
    /// AnchorPoseFilter 负责把低频 pose 测量融合成一个目标 pose；本类负责把目标 pose
    /// 转换成每个渲染帧真正显示的 pose。静止时使用输出锁吸收 frame alignment 残余抖动，
    /// 运动时按 render dt 追踪目标 pose，把低频 pose 更新摊到高帧率渲染帧上。
    /// 本类不读取 Unity Time，不修改 Transform，可由 smoke 工具直接驱动。
    /// </summary>
    public sealed class AnchorOutputSmoother
    {
        /// <summary>当前参数包。</summary>
        private AnchorPolicyConfig config;

        /// <summary>渲染层最终输出 pose。</summary>
        private Pose outputPose;

        /// <summary>是否已有渲染层输出 pose。</summary>
        private bool hasOutputPose;

        /// <summary>最近一次渲染层输出时间，单位秒。</summary>
        private double outputTimeSeconds = -1.0;

        /// <summary>静止输出锁是否已启用。锁启用后小范围目标抖动不会移动显示 pose。</summary>
        private bool staticOutputLocked;

        /// <summary>
        /// 构造渲染层输出平滑器。
        /// </summary>
        /// <param name="config">参数包；为空时使用默认参数。</param>
        public AnchorOutputSmoother(AnchorPolicyConfig config = null)
        {
            this.config = config ?? new AnchorPolicyConfig();
        }

        /// <summary>
        /// 热更参数包，不清空输出状态。
        /// </summary>
        /// <param name="newConfig">新的参数包。</param>
        public void ApplyConfig(AnchorPolicyConfig newConfig)
        {
            if (newConfig != null)
            {
                config = newConfig;
            }
        }

        /// <summary>
        /// 清空渲染层输出状态。
        /// </summary>
        public void Reset()
        {
            outputPose = Pose.identity;
            hasOutputPose = false;
            outputTimeSeconds = -1.0;
            staticOutputLocked = false;
        }

        /// <summary>
        /// 硬设置渲染层输出 pose。首测量、重定位和真实瞬移恢复应立即贴合，不经过平滑。
        /// </summary>
        /// <param name="pose">要输出的 world pose。</param>
        /// <param name="sampleTimeSeconds">输出时间，单位秒。</param>
        public void Snap(Pose pose, double sampleTimeSeconds)
        {
            outputPose = pose;
            hasOutputPose = true;
            outputTimeSeconds = sampleTimeSeconds;
            staticOutputLocked = false;
        }

        /// <summary>
        /// 将滤波器目标 pose 转换成最终渲染输出。
        /// </summary>
        /// <param name="targetPose">滤波器预测出的目标 world pose。</param>
        /// <param name="mode">本帧预测模式。</param>
        /// <param name="state">本帧 anchor 生命周期状态。</param>
        /// <param name="isStatic">运动分类器是否认为目标静止。</param>
        /// <param name="nowSeconds">当前渲染时间，单位秒。</param>
        /// <returns>本帧最终显示 pose。</returns>
        public Pose Advance(Pose targetPose, AnchorPredictMode mode, AnchorState state, bool isStatic, double nowSeconds)
        {
            if (!hasOutputPose)
            {
                Snap(targetPose, nowSeconds);
                return outputPose;
            }

            float dt = Mathf.Clamp((float)(nowSeconds - outputTimeSeconds), 0f, 0.05f);
            outputTimeSeconds = nowSeconds;

            if (mode == AnchorPredictMode.Hold || state == AnchorState.FrozenUncertain || state == AnchorState.Lost)
            {
                return outputPose;
            }

            if (isStatic && !staticOutputLocked)
            {
                staticOutputLocked = true;
            }

            if (staticOutputLocked && ShouldKeepStaticLock(targetPose, isStatic, dt))
            {
                return outputPose;
            }

            staticOutputLocked = false;
            if (dt <= 0f)
            {
                return outputPose;
            }

            if (mode == AnchorPredictMode.Coast)
            {
                targetPose = new Pose(targetPose.position, outputPose.rotation);
            }

            outputPose = FollowTarget(
                targetPose,
                dt,
                config.movingOutputSmoothingTauSeconds,
                config.maxOutputSpeedMps,
                config.maxOutputAngularSpeedDps);
            return outputPose;
        }

        /// <summary>
        /// 判断静止输出锁是否应该继续保持；静止确认期间可慢速归中。
        /// </summary>
        private bool ShouldKeepStaticLock(Pose targetPose, bool isStatic, float dt)
        {
            float positionDelta = Vector3.Distance(outputPose.position, targetPose.position);
            float rotationDelta = Quaternion.Angle(outputPose.rotation, targetPose.rotation);
            bool withinReleaseBand = positionDelta <= config.staticOutputReleaseMeters
                && rotationDelta <= config.staticOutputReleaseDegrees;
            if (!withinReleaseBand)
            {
                return false;
            }

            if (isStatic)
            {
                outputPose = FollowTarget(
                    targetPose,
                    dt,
                    config.staticOutputSmoothingTauSeconds,
                    config.maxStaticOutputSpeedMps,
                    config.maxStaticOutputAngularSpeedDps);
            }

            return true;
        }

        /// <summary>
        /// 按给定时间常数与速度上限追踪目标 pose。
        /// </summary>
        private Pose FollowTarget(Pose targetPose, float dt, float tauSeconds, float maxSpeedMps, float maxAngularSpeedDps)
        {
            float alpha = 1f - Mathf.Exp(-dt / Mathf.Max(tauSeconds, 1e-4f));
            return new Pose(
                StepPosition(outputPose.position, targetPose.position, alpha, maxSpeedMps * dt),
                StepRotation(outputPose.rotation, targetPose.rotation, alpha, maxAngularSpeedDps * dt)
            );
        }

        /// <summary>
        /// 按指数追踪比例与最大步长推进位置，避免单帧速度尖峰。
        /// </summary>
        private static Vector3 StepPosition(Vector3 current, Vector3 target, float alpha, float maxStep)
        {
            Vector3 step = (target - current) * Mathf.Clamp01(alpha);
            float stepMagnitude = step.magnitude;
            if (stepMagnitude > maxStep && stepMagnitude > 1e-8f)
            {
                step *= maxStep / stepMagnitude;
            }

            return current + step;
        }

        /// <summary>
        /// 按指数追踪比例与最大角步长推进旋转，避免单帧角速度尖峰。
        /// </summary>
        private static Quaternion StepRotation(Quaternion current, Quaternion target, float alpha, float maxAngleDegrees)
        {
            float angle = Quaternion.Angle(current, target);
            if (angle <= 1e-5f)
            {
                return target;
            }

            float stepAngle = Mathf.Min(angle * Mathf.Clamp01(alpha), maxAngleDegrees);
            float t = Mathf.Clamp01(stepAngle / angle);
            return NlerpShortest(current, target, t);
        }

        /// <summary>
        /// 纯 C# 最短弧归一化线性插值，避免 smoke 离线环境调用 Unity ECall。
        /// </summary>
        private static Quaternion NlerpShortest(Quaternion current, Quaternion target, float t)
        {
            float dot = current.x * target.x + current.y * target.y + current.z * target.z + current.w * target.w;
            if (dot < 0f)
            {
                target = new Quaternion(-target.x, -target.y, -target.z, -target.w);
            }

            return NormalizeQuaternion(new Quaternion(
                current.x + (target.x - current.x) * t,
                current.y + (target.y - current.y) * t,
                current.z + (target.z - current.z) * t,
                current.w + (target.w - current.w) * t
            ));
        }

        /// <summary>
        /// 四元数归一化；模长过小时回退 identity。
        /// </summary>
        private static Quaternion NormalizeQuaternion(Quaternion q)
        {
            float norm = Mathf.Sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
            if (norm <= 1e-12f)
            {
                return Quaternion.identity;
            }

            float inv = 1f / norm;
            return new Quaternion(q.x * inv, q.y * inv, q.z * inv, q.w * inv);
        }
    }
}
