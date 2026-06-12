using System.Collections.Generic;
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
    /// 进入静止用"测量散布窗口"判定：持续 staticEnterDuration 内被接受测量围绕窗口均值的
    /// 位置/旋转散布足够小才进入。直接以测量为证据，与滤波器速度估计噪声解耦
    ///（常速度 KF 在运动过程噪声下的速度估计噪声可达数厘米/秒，不能作为静止依据）。
    /// 退出静止是立即的：单帧 innovation 马氏距离、测量位移或旋转差任一超阈即退出，
    /// 保证物体被移动时立刻恢复跟随。不对称滞回 = 慢进快出。全部时间显式传入。
    /// </summary>
    public sealed class MotionStateClassifier
    {
        /// <summary>进入静止至少需要的测量数，避免长间隔两帧偶然接近就判静止。</summary>
        private const int MinStaticSampleCount = 3;

        /// <summary>当前参数包。</summary>
        private AnchorPolicyConfig config;

        /// <summary>当前运动状态。</summary>
        private AnchorMotionState state = AnchorMotionState.Unknown;

        /// <summary>静止候选滑动窗口，保存最近一段被接受测量。</summary>
        private readonly List<MotionSample> window = new List<MotionSample>();

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
            window.Clear();
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
                if (ShouldExitStatic(in innovation))
                {
                    state = AnchorMotionState.Moving;
                    ResetWindow(measuredPose, timeSeconds);
                }

                return;
            }

            AddWindowSample(measuredPose, timeSeconds);
            if (HasStableWindow(timeSeconds))
            {
                state = AnchorMotionState.Static;
            }
            else
            {
                // 候选期内仍按运动处理，先保证跟随。
                state = AnchorMotionState.Moving;
            }
        }

        /// <summary>
        /// 静止模式下是否出现足以立即恢复运动跟随的证据。
        /// </summary>
        private bool ShouldExitStatic(in InnovationStats innovation)
        {
            return innovation.PosD2 > config.motionSpikeD2
                || innovation.TranslationMeters > config.staticExitDisplacement
                || innovation.RotationDegrees > config.staticExitRotationDeg;
        }

        /// <summary>
        /// 写入一帧候选测量，并淘汰超过静止判定时长的旧样本。
        /// </summary>
        private void AddWindowSample(Pose measuredPose, double timeSeconds)
        {
            window.Add(new MotionSample(measuredPose, timeSeconds));
            double minTime = timeSeconds - config.staticEnterDuration;
            while (window.Count > 1 && window[1].TimeSeconds <= minTime)
            {
                window.RemoveAt(0);
            }
        }

        /// <summary>
        /// 以当前测量重新开始静止候选窗口。
        /// </summary>
        private void ResetWindow(Pose measuredPose, double timeSeconds)
        {
            window.Clear();
            window.Add(new MotionSample(measuredPose, timeSeconds));
        }

        /// <summary>
        /// 判断滑动窗口是否已经提供足够稳定的静止证据。
        /// </summary>
        private bool HasStableWindow(double timeSeconds)
        {
            if (window.Count < MinStaticSampleCount)
            {
                return false;
            }

            double oldestTime = -1.0;
            Vector3 meanPosition = Vector3.zero;
            Quaternion meanRotation = Quaternion.identity;
            if (!TryComputeWindowMean(out meanPosition, out meanRotation, out oldestTime))
            {
                return false;
            }

            if (timeSeconds - oldestTime < config.staticEnterDuration)
            {
                return false;
            }

            foreach (MotionSample sample in window)
            {
                if (Vector3.Distance(sample.Pose.position, meanPosition) > config.staticEnterRadius)
                {
                    return false;
                }

                if (Quaternion.Angle(sample.Pose.rotation, meanRotation) > config.staticEnterRotationDeg)
                {
                    return false;
                }
            }

            return true;
        }

        /// <summary>
        /// 计算窗口 pose 均值；旋转用同半球四元数平均近似，足够服务小角度静止散布判定。
        /// </summary>
        private bool TryComputeWindowMean(out Vector3 meanPosition, out Quaternion meanRotation, out double oldestTime)
        {
            meanPosition = Vector3.zero;
            meanRotation = Quaternion.identity;
            oldestTime = -1.0;
            if (window.Count <= 0)
            {
                return false;
            }

            Quaternion referenceRotation = Quaternion.identity;
            Vector4 rotationSum = Vector4.zero;
            bool hasReference = false;
            foreach (MotionSample sample in window)
            {
                if (oldestTime < 0.0)
                {
                    oldestTime = sample.TimeSeconds;
                }

                meanPosition += sample.Pose.position;
                Quaternion rotation = sample.Pose.rotation;
                if (!hasReference)
                {
                    referenceRotation = rotation;
                    hasReference = true;
                }

                rotation = AlignSign(referenceRotation, rotation);
                rotationSum += new Vector4(rotation.x, rotation.y, rotation.z, rotation.w);
            }

            meanPosition /= window.Count;
            meanRotation = NormalizeQuaternion(new Quaternion(
                rotationSum.x,
                rotationSum.y,
                rotationSum.z,
                rotationSum.w));
            return true;
        }

        /// <summary>
        /// 保证 value 与 reference 位于同一四元数半球。
        /// </summary>
        private static Quaternion AlignSign(Quaternion reference, Quaternion value)
        {
            float dot = reference.x * value.x + reference.y * value.y + reference.z * value.z + reference.w * value.w;
            return dot < 0f
                ? new Quaternion(-value.x, -value.y, -value.z, -value.w)
                : value;
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

        /// <summary>
        /// 静止判定窗口中的一帧测量样本。
        /// </summary>
        private readonly struct MotionSample
        {
            /// <summary>测量 pose。</summary>
            public readonly Pose Pose;

            /// <summary>测量时间，单位秒。</summary>
            public readonly double TimeSeconds;

            /// <summary>构造窗口样本。</summary>
            public MotionSample(Pose pose, double timeSeconds)
            {
                Pose = pose;
                TimeSeconds = timeSeconds;
            }
        }
    }
}
