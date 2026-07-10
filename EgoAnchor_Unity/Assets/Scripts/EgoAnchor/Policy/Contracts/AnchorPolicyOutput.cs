using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 每渲染帧 Advance 的输出：唯一的 anchor pose 输出权威。
    ///
    /// 消息驱动的 AcceptPose 只做"测量提交"并返回输入分类（AnchorPolicyDecision）；
    /// 渲染输出统一由 Advance 按提交态预测到当前时刻得到，因此低频 pose 流
    /// 也能产生逐帧连续的 anchor 运动。
    /// </summary>
    public readonly struct AnchorPolicyOutput
    {
        /// <summary>是否有可输出的 anchor pose。</summary>
        public readonly bool HasPose;

        /// <summary>输出的 Unity world pose；HasPose=false 时为 Pose.identity。</summary>
        public readonly Pose Pose;

        /// <summary>当前 anchor 生命周期状态。</summary>
        public readonly AnchorState State;

        /// <summary>当前运动状态。</summary>
        public readonly AnchorMotionState MotionState;

        /// <summary>本帧实际使用的前推时长，单位秒。跟踪态为延迟隐藏量，续航态为已外推时长。</summary>
        public readonly float PredictAheadSeconds;

        /// <summary>当前渲染时刻距最近观测语义时刻的年龄，单位秒。</summary>
        public readonly double ObservationAgeSeconds;

        /// <summary>本帧 policy 输出 pose 对应的 Unity 单调时钟语义时刻，单位秒。</summary>
        public readonly double OutputTargetTimeSeconds;

        /// <summary>当前渲染时刻相对输出语义时刻的实际平滑延迟，单位秒。</summary>
        public readonly double SmoothingDelaySeconds;

        /// <summary>本帧输出的解释原因。</summary>
        public readonly string Reason;

        /// <summary>
        /// 构造每帧输出。
        /// </summary>
        /// <param name="hasPose">是否有可输出的 anchor pose。</param>
        /// <param name="pose">输出的 Unity world pose。</param>
        /// <param name="state">当前 anchor 生命周期状态。</param>
        /// <param name="motionState">当前运动状态。</param>
        /// <param name="predictAheadSeconds">本帧实际使用的前推时长，单位秒。</param>
        /// <param name="observationAgeSeconds">当前渲染时刻距最近观测语义时刻的年龄，单位秒。</param>
        /// <param name="outputTargetTimeSeconds">本帧输出 pose 对应的 Unity 单调时钟语义时刻，单位秒。</param>
        /// <param name="smoothingDelaySeconds">当前渲染时刻相对输出语义时刻的实际平滑延迟，单位秒。</param>
        /// <param name="reason">本帧输出的解释原因。</param>
        public AnchorPolicyOutput(
            bool hasPose,
            Pose pose,
            AnchorState state,
            AnchorMotionState motionState,
            float predictAheadSeconds,
            double observationAgeSeconds,
            double outputTargetTimeSeconds,
            double smoothingDelaySeconds,
            string reason)
        {
            HasPose = hasPose;
            Pose = pose;
            State = state;
            MotionState = motionState;
            PredictAheadSeconds = predictAheadSeconds;
            ObservationAgeSeconds = observationAgeSeconds;
            OutputTargetTimeSeconds = outputTargetTimeSeconds;
            SmoothingDelaySeconds = smoothingDelaySeconds;
            Reason = reason ?? string.Empty;
        }

        /// <summary>
        /// 构造无可输出 pose 的占位输出。
        /// </summary>
        /// <param name="state">当前 anchor 生命周期状态。</param>
        /// <param name="reason">解释原因。</param>
        /// <param name="observationAgeSeconds">当前渲染时刻距最近观测语义时刻的年龄，单位秒；未知时为 NaN。</param>
        /// <returns>HasPose=false 的输出。</returns>
        public static AnchorPolicyOutput None(AnchorState state, string reason, double observationAgeSeconds = double.NaN)
        {
            return new AnchorPolicyOutput(
                false,
                Pose.identity,
                state,
                AnchorMotionState.Unknown,
                0f,
                observationAgeSeconds,
                double.NaN,
                double.NaN,
                reason);
        }
    }
}
