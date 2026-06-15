using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Predictors.Motion;

namespace EgoAnchor.Tools3.Predictors.Interp
{
    /// <summary>原始观测点, 不带速度 (切线交给插值器用相邻点差分)。对应 C 行 DR 列。</summary>
    public sealed class RawControlPoints : IControlPointSource
    {
        public string Name => "raw";

        public void Reset()
        {
        }

        public ControlPoint Accept(in Observation observation)
        {
            return new ControlPoint(
                observation.TimeSeconds,
                observation.Pose.Position,
                observation.Pose.Rotation,
                Vec3.Zero,
                Vec3.Zero,
                hasVelocity: false);
        }
    }

    /// <summary>
    /// 1€ 平滑控制点 + 1€ 平滑速度。对应 C 行 1€ 列。
    /// 复用 OneEuroMotionModel: 它内部已经在跟踪平滑值和平滑速度。
    /// 控制点的 pose = "在该观测时刻的平滑值" (用 PredictAt(t) 取, ahead=0 即平滑当前值)。
    /// </summary>
    public sealed class OneEuroControlPoints : IControlPointSource
    {
        private readonly OneEuroMotionModel model = new();

        public string Name => "oneeuro";

        public void Reset() => model.Reset();

        public ControlPoint Accept(in Observation observation)
        {
            model.OnObservation(observation);
            double t = observation.TimeSeconds;
            // 平滑后的当前 pose (ahead=0) 和"略往前一点"的差分给速度——但 model 已有速度, 直接取:
            Pose at = model.PredictAt(t);
            // 用一个极小 dt 数值估计速度向量 (model 内部速度已含切空间, 这里统一用差分更稳健)
            const double eps = 1e-3;
            Pose ahead = model.PredictAt(t + eps);
            Vec3 linVel = (ahead.Position - at.Position) / eps;
            Vec3 angVel = Quat.Log(at.Rotation.Inverse() * Quat.AlignHemisphere(at.Rotation, ahead.Rotation)) / eps;
            return new ControlPoint(t, at.Position, at.Rotation, linVel, angVel, hasVelocity: true);
        }
    }

    /// <summary>
    /// Kalman 平滑控制点 + Kalman 速度当切线。对应 C 行 Kalman 列 (C3, 不是 RTS)。
    /// 复用 KalmanMotionModel。控制点 pose = 该观测时刻的 Kalman 估计 (ahead=0)。
    /// </summary>
    public sealed class KalmanControlPoints : IControlPointSource
    {
        private readonly KalmanMotionModel model = new();

        public string Name => "kalman";

        public void Reset() => model.Reset();

        public ControlPoint Accept(in Observation observation)
        {
            model.OnObservation(observation);
            double t = observation.TimeSeconds;
            Pose at = model.PredictAt(t);
            const double eps = 1e-3;
            Pose ahead = model.PredictAt(t + eps);
            Vec3 linVel = (ahead.Position - at.Position) / eps;
            Vec3 angVel = Quat.Log(at.Rotation.Inverse() * Quat.AlignHemisphere(at.Rotation, ahead.Rotation)) / eps;
            return new ControlPoint(t, at.Position, at.Rotation, linVel, angVel, hasVelocity: true);
        }
    }
}
