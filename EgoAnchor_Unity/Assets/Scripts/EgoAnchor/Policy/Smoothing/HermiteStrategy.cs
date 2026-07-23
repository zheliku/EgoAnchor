using System.Globalization;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 使用 Kalman 速度切线的历史缓冲三次 Hermite 输出策略。
    ///
    /// 位置直接在世界系插值；旋转在首控制点的 SO(3) Log 切空间插值。端点切线按
    /// 控制点弦长限幅，避免急停时残留速度把曲线推出端点之间的合理范围。
    /// </summary>
    public sealed class HermiteStrategy : HistoricalInterpolationStrategy
    {
        /// <summary>端点切线模长相对控制点弦长的上限倍数。</summary>
        [Tooltip("Hermite 端点切线模长上限 = 该倍数 × 控制点弦长。默认 3。")]
        [Range(1.0f, 8.0f)]
        [SerializeField] private float tangentChordRatio = 3.0f;

        /// <summary>写入评估日志的稳定策略名。</summary>
        public override string StrategyName => "hermite_interpolation";

        /// <summary>参与正式配置哈希的缓冲参数和切线限幅。</summary>
        public override string ConfigurationFingerprint => string.Format(
            CultureInfo.InvariantCulture,
            "{0}|tangent:{1:R}",
            base.ConfigurationFingerprint,
            tangentChordRatio);

        /// <summary>在相邻控制点之间执行位置和旋转三次 Hermite 插值。</summary>
        protected override Pose Interpolate(
            in ControlPoint first,
            in ControlPoint second,
            float amount,
            float spanSeconds)
        {
            float ratio = Mathf.Max(tangentChordRatio, 1.0f);

            Vector3 positionChord = second.Pose.position - first.Pose.position;
            float positionSpeedLimit = ratio * positionChord.magnitude / spanSeconds;
            Vector3 firstLinearVelocity = ClampMagnitude(first.LinearVelocity, positionSpeedLimit);
            Vector3 secondLinearVelocity = ClampMagnitude(second.LinearVelocity, positionSpeedLimit);
            Vector3 position = Hermite(
                first.Pose.position,
                firstLinearVelocity,
                second.Pose.position,
                secondLinearVelocity,
                amount,
                spanSeconds);

            Vector3 rotationEnd = AnchorMath.RelativeRotationLog(first.Pose.rotation, second.Pose.rotation);
            float angularSpeedLimit = ratio * rotationEnd.magnitude / spanSeconds;
            Vector3 firstAngularVelocity = ClampMagnitude(first.AngularVelocityRad, angularSpeedLimit);
            Vector3 secondLogRate = AnchorMath.ApplyRightJacobianInverse(
                rotationEnd,
                second.AngularVelocityRad);
            Vector3 secondAngularVelocity = ClampMagnitude(secondLogRate, angularSpeedLimit);
            Vector3 rotationVector = Hermite(
                Vector3.zero,
                firstAngularVelocity,
                rotationEnd,
                secondAngularVelocity,
                amount,
                spanSeconds);
            Quaternion rotation = AnchorMath.Multiply(first.Pose.rotation, AnchorMath.Exp(rotationVector));
            return new Pose(position, rotation);
        }

        /// <summary>计算以每秒导数为端点切线的三次 Hermite 插值。</summary>
        private static Vector3 Hermite(
            Vector3 first,
            Vector3 firstVelocity,
            Vector3 second,
            Vector3 secondVelocity,
            float amount,
            float spanSeconds)
        {
            float amountSquared = amount * amount;
            float amountCubed = amountSquared * amount;
            float firstBasis = 2.0f * amountCubed - 3.0f * amountSquared + 1.0f;
            float firstTangentBasis = amountCubed - 2.0f * amountSquared + amount;
            float secondBasis = -2.0f * amountCubed + 3.0f * amountSquared;
            float secondTangentBasis = amountCubed - amountSquared;
            return first * firstBasis
                + firstVelocity * spanSeconds * firstTangentBasis
                + second * secondBasis
                + secondVelocity * spanSeconds * secondTangentBasis;
        }

        /// <summary>把向量模长限制到非负上限；急停弦长接近零时切线随之归零。</summary>
        private static Vector3 ClampMagnitude(Vector3 value, float maxMagnitude)
        {
            float magnitude = value.magnitude;
            if (magnitude <= maxMagnitude || magnitude < 1e-9f)
            {
                return value;
            }

            return value * (maxMagnitude / magnitude);
        }
    }
}
