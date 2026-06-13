using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 静止锁 + 单帧限速 output stage。
    /// 静止时吸收小残余 slip；非静止时只做显示限速，防止单帧跳变。
    /// </summary>
    public sealed class StaticLockRateLimitOutputModule : AnchorOutputStageModule
    {
        private const int DefaultsVersion = 1;

        /// <summary>是否启用静止锁。</summary>
        [Tooltip("是否启用静止锁；仅在 MotionState=Static 时吸收小残余 slip。")]
        [SerializeField] private bool enableStaticLock = true;

        /// <summary>静止锁释放平移阈值，单位米。</summary>
        [Tooltip("静止锁释放平移阈值，单位米；超过后认为目标真实移动并释放锁。")]
        [SerializeField] private float staticReleaseMeters = 0.030f;

        /// <summary>静止锁释放旋转阈值，单位度。</summary>
        [Tooltip("静止锁释放旋转阈值，单位度。")]
        [SerializeField] private float staticReleaseDegrees = 3.0f;

        /// <summary>是否启用输出限速。</summary>
        [Tooltip("是否启用输出限速；限制单渲染帧输出跳变。")]
        [SerializeField] private bool enableRateLimit = true;

        /// <summary>最大输出平移速度，单位 m/s。</summary>
        [Tooltip("最大输出平移速度，单位 m/s。")]
        [SerializeField] private float maxOutputMetersPerSecond = 4.0f;

        /// <summary>最大输出旋转速度，单位 deg/s。</summary>
        [Tooltip("最大输出旋转速度，单位 deg/s。")]
        [SerializeField] private float maxOutputDegreesPerSecond = 720.0f;

        /// <summary>是否启用输出加速度限制。</summary>
        [Tooltip("是否启用输出加速度限制；让显示速度连续变化，减少速度突变造成的卡顿。")]
        [SerializeField] private bool enableAccelerationLimit = true;

        /// <summary>最大输出平移加速度，单位 m/s^2。</summary>
        [Tooltip("最大输出平移加速度，单位 m/s^2；越大越跟手，越小越平滑。")]
        [SerializeField] private float maxOutputAccelerationMetersPerSecond2 = 80.0f;

        /// <summary>最大输出角加速度，单位 deg/s^2。</summary>
        [Tooltip("最大输出角加速度，单位 deg/s^2；越大越跟手，越小越平滑。")]
        [SerializeField] private float maxOutputAngularAccelerationDegreesPerSecond2 = 28800.0f;

        private int defaultsInitializedVersion = DefaultsVersion;
        private Pose lockedPose = Pose.identity;
        private Pose lastOutputPose = Pose.identity;
        private double lastOutputTimeSeconds;
        private bool hasLock;
        private bool hasOutput;
        private Vector3 outputVelocity;
        private Vector3 outputAngularVelocityRad;
        private float lastResidualMeters;
        private float lastResidualDegrees;
        private bool isStaticLocked;

        /// <summary>日志和 eval 使用的模块名。</summary>
        public override string ModuleName => "static_lock_rate_limit";

        /// <summary>最近一次输出整形前后的平移残差，单位米。</summary>
        public override float LastResidualMeters => lastResidualMeters;

        /// <summary>最近一次输出整形前后的旋转残差，单位度。</summary>
        public override float LastResidualDegrees => lastResidualDegrees;

        /// <summary>最近一次输出是否被静止锁定。</summary>
        public override bool IsStaticLocked => isStaticLocked;

        /// <summary>先按静止锁处理，再做单帧限速。</summary>
        public override Pose Condition(in AnchorEstimate estimate, double renderTimeSeconds, in OutputContext context)
        {
            EnsureDefaults();
            Pose conditioned = estimate.Pose;
            isStaticLocked = false;

            if (enableStaticLock && context.MotionState == AnchorMotionState.Static)
            {
                conditioned = ApplyStaticLock(conditioned);
            }
            else
            {
                hasLock = false;
            }

            if (enableRateLimit && hasOutput)
            {
                float dt = Mathf.Max((float)(renderTimeSeconds - lastOutputTimeSeconds), 0.0f);
                if (dt <= 0.0f)
                {
                    conditioned = lastOutputPose;
                }
                else if (enableAccelerationLimit)
                {
                    conditioned = ApplyAccelerationLimitedRate(conditioned, dt);
                }
                else
                {
                    float maxMeters = Mathf.Max(maxOutputMetersPerSecond, 0.0f) * dt;
                    float maxDegrees = Mathf.Max(maxOutputDegreesPerSecond, 0.0f) * dt;
                    conditioned = AnchorMath.ClampPoseDelta(lastOutputPose, conditioned, maxMeters, maxDegrees);
                }
            }

            if (isStaticLocked)
            {
                outputVelocity = Vector3.zero;
                outputAngularVelocityRad = Vector3.zero;
            }

            lastResidualMeters = Vector3.Distance(estimate.Pose.position, conditioned.position);
            lastResidualDegrees = AnchorMath.AngleDegrees(estimate.Pose.rotation, conditioned.rotation);
            lastOutputPose = conditioned;
            lastOutputTimeSeconds = renderTimeSeconds;
            hasOutput = true;
            return conditioned;
        }

        /// <summary>清空静止锁和限速历史。</summary>
        public override void ResetModule()
        {
            EnsureDefaults();
            lockedPose = Pose.identity;
            lastOutputPose = Pose.identity;
            lastOutputTimeSeconds = 0.0;
            hasLock = false;
            hasOutput = false;
            outputVelocity = Vector3.zero;
            outputAngularVelocityRad = Vector3.zero;
            lastResidualMeters = 0.0f;
            lastResidualDegrees = 0.0f;
            isStaticLocked = false;
        }

        private Pose ApplyAccelerationLimitedRate(in Pose target, float dt)
        {
            Vector3 position = ApplyTranslationRate(target.position, dt);
            Quaternion rotation = ApplyRotationRate(target.rotation, dt);
            return new Pose(position, rotation);
        }

        private Vector3 ApplyTranslationRate(Vector3 targetPosition, float dt)
        {
            Vector3 toTarget = targetPosition - lastOutputPose.position;
            if (toTarget.sqrMagnitude <= 1e-12f)
            {
                outputVelocity = Vector3.zero;
                return targetPosition;
            }

            Vector3 desiredVelocity = toTarget / dt;
            float maxSpeed = Mathf.Max(maxOutputMetersPerSecond, 0.0f);
            if (maxSpeed > 0.0f && desiredVelocity.magnitude > maxSpeed)
            {
                desiredVelocity = desiredVelocity.normalized * maxSpeed;
            }

            float maxDeltaSpeed = Mathf.Max(maxOutputAccelerationMetersPerSecond2, 0.0f) * dt;
            outputVelocity = MoveVectorTowards(outputVelocity, desiredVelocity, maxDeltaSpeed);
            Vector3 step = outputVelocity * dt;
            if (step.magnitude >= toTarget.magnitude)
            {
                outputVelocity = desiredVelocity;
                return targetPosition;
            }

            return lastOutputPose.position + step;
        }

        private Quaternion ApplyRotationRate(Quaternion targetRotation, float dt)
        {
            Quaternion alignedTarget = AnchorMath.AlignHemisphere(lastOutputPose.rotation, targetRotation);
            Vector3 toTarget = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(lastOutputPose.rotation), alignedTarget));
            if (toTarget.sqrMagnitude <= 1e-12f)
            {
                outputAngularVelocityRad = Vector3.zero;
                return alignedTarget;
            }

            Vector3 desiredAngularVelocity = toTarget / dt;
            float maxAngularSpeed = Mathf.Max(maxOutputDegreesPerSecond, 0.0f) * Mathf.Deg2Rad;
            if (maxAngularSpeed > 0.0f && desiredAngularVelocity.magnitude > maxAngularSpeed)
            {
                desiredAngularVelocity = desiredAngularVelocity.normalized * maxAngularSpeed;
            }

            float maxDeltaAngularSpeed = Mathf.Max(maxOutputAngularAccelerationDegreesPerSecond2, 0.0f) * Mathf.Deg2Rad * dt;
            outputAngularVelocityRad = MoveVectorTowards(outputAngularVelocityRad, desiredAngularVelocity, maxDeltaAngularSpeed);
            Vector3 step = outputAngularVelocityRad * dt;
            if (step.magnitude >= toTarget.magnitude)
            {
                outputAngularVelocityRad = desiredAngularVelocity;
                return alignedTarget;
            }

            return AnchorMath.Multiply(lastOutputPose.rotation, AnchorMath.Exp(step));
        }

        private static Vector3 MoveVectorTowards(Vector3 current, Vector3 target, float maxDelta)
        {
            Vector3 delta = target - current;
            float distance = delta.magnitude;
            if (distance <= maxDelta || distance <= 1e-8f)
            {
                return target;
            }

            return current + delta / distance * Mathf.Max(maxDelta, 0.0f);
        }

        private Pose ApplyStaticLock(Pose estimatePose)
        {
            if (!hasLock)
            {
                lockedPose = estimatePose;
                hasLock = true;
                isStaticLocked = true;
                return lockedPose;
            }

            float translation = Vector3.Distance(lockedPose.position, estimatePose.position);
            float rotation = AnchorMath.AngleDegrees(lockedPose.rotation, estimatePose.rotation);
            if (translation <= staticReleaseMeters && rotation <= staticReleaseDegrees)
            {
                isStaticLocked = true;
                return lockedPose;
            }

            lockedPose = estimatePose;
            isStaticLocked = false;
            return estimatePose;
        }

        private void EnsureDefaults()
        {
            if (defaultsInitializedVersion == DefaultsVersion)
            {
                return;
            }

            enableStaticLock = true;
            staticReleaseMeters = 0.030f;
            staticReleaseDegrees = 3.0f;
            enableRateLimit = true;
            maxOutputMetersPerSecond = 4.0f;
            maxOutputDegreesPerSecond = 720.0f;
            enableAccelerationLimit = true;
            maxOutputAccelerationMetersPerSecond2 = 80.0f;
            maxOutputAngularAccelerationDegreesPerSecond2 = 28800.0f;
            defaultsInitializedVersion = DefaultsVersion;
        }
    }
}
