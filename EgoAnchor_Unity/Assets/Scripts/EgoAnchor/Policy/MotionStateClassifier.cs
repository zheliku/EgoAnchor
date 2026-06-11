using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// anchor 目标的运动状态。
    /// </summary>
    public enum AnchorMotionState
    {
        /// <summary>暂无足够证据（冷启动或刚贴合），按运动模式参数处理。</summary>
        Unknown,

        /// <summary>静止：启用 ZUPT 与放大的测量噪声，输出不外推，抖动最小。</summary>
        Static,

        /// <summary>运动：基准噪声 + 速度外推，延迟最小。</summary>
        Moving,
    }

    /// <summary>
    /// 静止/运动状态分类器。
    ///
    /// 进入静止用"测量散布窗口"判定：持续 staticEnterDuration 内所有被接受测量的
    /// 位置/旋转都落在窗口锚点附近才进入。直接以测量为证据，与滤波器速度估计噪声解耦
    ///（常速度 KF 在运动过程噪声下的速度估计噪声可达数厘米/秒，不能作为静止依据）。
    /// 退出静止是立即的：单帧 innovation 马氏距离、测量位移或旋转差任一超阈即退出，
    /// 保证物体被移动时立刻恢复跟随。不对称滞回 = 慢进快出。全部时间显式传入。
    /// </summary>
    public sealed class MotionStateClassifier
    {
        /// <summary>当前参数包。</summary>
        private AnchorPolicyConfig config;

        /// <summary>当前运动状态。</summary>
        private AnchorMotionState state = AnchorMotionState.Unknown;

        /// <summary>静止候选窗口的锚点 pose（窗口首个测量）。</summary>
        private Pose windowAnchorPose;

        /// <summary>静止候选窗口的起始时间，单位秒；-1 表示尚无窗口。</summary>
        private double windowStartTime = -1.0;

        /// <summary>
        /// 构造运动状态分类器。
        /// </summary>
        /// <param name="config">参数包；为空时使用默认参数。</param>
        public MotionStateClassifier(AnchorPolicyConfig config = null)
        {
            this.config = config ?? new AnchorPolicyConfig();
        }

        /// <summary>当前运动状态。</summary>
        public AnchorMotionState State => state;

        /// <summary>是否处于静止状态。</summary>
        public bool IsStatic => state == AnchorMotionState.Static;

        /// <summary>
        /// 热更参数包，不清空分类状态。
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
        /// 清空到 Unknown。贴合/重定位后调用，重新积累静止证据。
        /// </summary>
        public void Reset()
        {
            state = AnchorMotionState.Unknown;
            windowStartTime = -1.0;
            windowAnchorPose = Pose.identity;
        }

        /// <summary>
        /// 用一帧被接受的测量更新运动状态。
        /// </summary>
        /// <param name="measuredPose">本帧被接受的测量 pose（滤波前）。</param>
        /// <param name="innovation">本帧测量相对预测的 innovation 统计。</param>
        /// <param name="timeSeconds">本帧测量时间，单位秒。</param>
        public void Observe(Pose measuredPose, in InnovationStats innovation, double timeSeconds)
        {
            if (state == AnchorMotionState.Static)
            {
                // 退出静止是立即的：任一运动证据出现就恢复跟随。
                bool exit = innovation.PosD2 > config.motionSpikeD2
                    || innovation.TranslationMeters > config.staticExitDisplacement
                    || innovation.RotationDegrees > config.staticExitRotationDeg;
                if (exit)
                {
                    state = AnchorMotionState.Moving;
                    RestartWindow(measuredPose, timeSeconds);
                }

                return;
            }

            bool insideWindow = windowStartTime >= 0.0
                && Vector3.Distance(measuredPose.position, windowAnchorPose.position) <= config.staticEnterRadius
                && Quaternion.Angle(measuredPose.rotation, windowAnchorPose.rotation) <= config.staticEnterRotationDeg;

            if (!insideWindow)
            {
                state = AnchorMotionState.Moving;
                RestartWindow(measuredPose, timeSeconds);
                return;
            }

            if (timeSeconds - windowStartTime >= config.staticEnterDuration)
            {
                state = AnchorMotionState.Static;
            }
            else if (state == AnchorMotionState.Unknown)
            {
                // 候选期内仍按运动处理，先保证跟随。
                state = AnchorMotionState.Moving;
            }
        }

        /// <summary>
        /// 以当前测量为锚点重新开始静止候选窗口。
        /// </summary>
        private void RestartWindow(Pose measuredPose, double timeSeconds)
        {
            windowAnchorPose = measuredPose;
            windowStartTime = timeSeconds;
        }
    }
}
