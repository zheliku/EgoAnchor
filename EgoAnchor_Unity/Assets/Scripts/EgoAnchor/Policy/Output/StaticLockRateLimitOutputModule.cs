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
        [SerializeField] private float maxOutputMetersPerSecond = 1.2f;

        /// <summary>最大输出旋转速度，单位 deg/s。</summary>
        [Tooltip("最大输出旋转速度，单位 deg/s。")]
        [SerializeField] private float maxOutputDegreesPerSecond = 180.0f;

        private int defaultsInitializedVersion = DefaultsVersion;
        private Pose lockedPose = Pose.identity;
        private Pose lastOutputPose = Pose.identity;
        private double lastOutputTimeSeconds;
        private bool hasLock;
        private bool hasOutput;
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
                else
                {
                    float maxMeters = Mathf.Max(maxOutputMetersPerSecond, 0.0f) * dt;
                    float maxDegrees = Mathf.Max(maxOutputDegreesPerSecond, 0.0f) * dt;
                    conditioned = AnchorMath.ClampPoseDelta(lastOutputPose, conditioned, maxMeters, maxDegrees);
                }
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
            lastResidualMeters = 0.0f;
            lastResidualDegrees = 0.0f;
            isStaticLocked = false;
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
            maxOutputMetersPerSecond = 1.2f;
            maxOutputDegreesPerSecond = 180.0f;
            defaultsInitializedVersion = DefaultsVersion;
        }
    }
}
