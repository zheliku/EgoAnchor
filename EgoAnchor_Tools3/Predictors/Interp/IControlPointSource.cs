using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;

namespace EgoAnchor.Tools3.Predictors.Interp
{
    /// <summary>插值用的控制点: 时刻 + 位姿 + (可选)速度/角速度切线。</summary>
    public readonly struct ControlPoint
    {
        public readonly double Time;
        public readonly Vec3 Position;
        public readonly Quat Rotation;
        public readonly Vec3 LinVel;        // m/s, 可能为 0 (由插值器用相邻点补算)
        public readonly Vec3 AngVel;        // 切空间半角向量速度
        public readonly bool HasVelocity;   // 是否自带速度 (Kalman/1€ 自带; 原始点没有)

        public ControlPoint(double time, Vec3 position, Quat rotation, Vec3 linVel, Vec3 angVel, bool hasVelocity)
        {
            Time = time;
            Position = position;
            Rotation = rotation.Normalized();
            LinVel = linVel;
            AngVel = angVel;
            HasVelocity = hasVelocity;
        }
    }

    /// <summary>
    /// 控制点来源: 把 ~5fps 原始观测转成插值用的控制点 (可去噪、可附带速度)。
    /// C 行三个变体的差异就在这里:
    ///   - RawControlPoints:     点 = 原始观测, 不带速度 (插值器用相邻点差分算切线)。
    ///   - OneEuroControlPoints: 点 = 1€ 平滑值, 带 1€ 平滑速度。
    ///   - KalmanControlPoints:  点 = Kalman 平滑值, 带 Kalman 速度。
    /// </summary>
    public interface IControlPointSource
    {
        string Name { get; }
        void Reset();
        /// <summary>吸收一帧观测, 返回对应的控制点 (其 Time = 观测时间)。</summary>
        ControlPoint Accept(in Observation observation);
    }
}
