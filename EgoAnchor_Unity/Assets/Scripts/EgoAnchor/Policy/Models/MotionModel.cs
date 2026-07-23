using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 运动模型产出的"去噪控制点"：某个观测时刻的 pose + 速度切线。
    /// C 路 (延迟插值) 缓冲这些点做样条插值；B 路 (外推) 主要用 MotionModel.PredictAt，
    /// 但也可读取速度。
    /// </summary>
    public readonly struct ControlPoint
    {
        /// <summary>该控制点对应的时间，单位秒 (观测的 capture/ sample 时间)。</summary>
        public readonly double TimeSeconds;

        /// <summary>去噪后的 world pose。</summary>
        public readonly Pose Pose;

        /// <summary>线速度，单位 m/s。</summary>
        public readonly Vector3 LinearVelocity;

        /// <summary>
        /// 控制点姿态局部坐标系中的 body angular velocity，单位 rad/s。
        /// 调用方用 <c>Pose.rotation * Exp(omega * dt)</c> 积分；不同控制点之间使用前
        /// 必须先搬运到同一切空间。
        /// </summary>
        public readonly Vector3 AngularVelocityRad;

        /// <summary>是否有效。</summary>
        public readonly bool Valid;

        public ControlPoint(double timeSeconds, Pose pose, Vector3 linearVelocity, Vector3 angularVelocityRad)
        {
            TimeSeconds = timeSeconds;
            Pose = pose;
            LinearVelocity = linearVelocity;
            AngularVelocityRad = angularVelocityRad;
            Valid = true;
        }
    }

    /// <summary>
    /// 模块 A：运动模型。吃观测，维护"去噪后的状态点 + 速度"，对外提供：
    ///   - PredictAt(t)：在 t 时刻外推的 pose (给平滑 Kalman 外推策略使用)；
    ///   - LatestControlPoint：最新去噪控制点，供两类历史插值策略使用。
    ///
    /// 继承 MonoBehaviour 的抽象基类，这样 Inspector 只能挂它的子类 (CV / Kalman / OneEuro)，
    /// 而不是任意 Mono。每个子类把自己的参数用 [SerializeField] 暴露在 Inspector。
    ///
    /// 关键：PredictAt 必须是"无限幅外推"——不要 clamp predict-ahead。低频 pose 在高频渲染里
    /// 的平滑由 SmoothingStrategy 负责，不靠在这里截断 (那正是旧实现卡顿的根因)。
    /// </summary>
    public abstract class MotionModel : MonoBehaviour
    {
        /// <summary>日志/eval 用的模型名。</summary>
        public abstract string ModelName { get; }

        /// <summary>写入配置哈希的模型参数指纹；无额外参数的模型返回空字符串。</summary>
        public virtual string ConfigurationFingerprint => string.Empty;

        /// <summary>是否已有可输出状态 (至少一帧观测)。</summary>
        public abstract bool HasState { get; }

        /// <summary>最近一次吸收观测的时间，单位秒。</summary>
        public abstract double LastObservationTimeSeconds { get; }

        /// <summary>当前估计线速度，单位 m/s。</summary>
        public abstract Vector3 LinearVelocity { get; }

        /// <summary>当前估计角速度，单位 rad/s，坐标系为最新控制点姿态的局部切空间。</summary>
        public abstract Vector3 AngularVelocityRad { get; }

        /// <summary>最近一次去噪控制点 (= 最新观测时刻的去噪 pose + 速度)。</summary>
        public abstract ControlPoint LatestControlPoint { get; }

        /// <summary>重定位/首帧/强校正：直接吸附到观测。</summary>
        public abstract void Snap(in AnchorObservation observation);

        /// <summary>用一帧观测更新内部状态。</summary>
        public abstract void UpdateState(in AnchorObservation observation);

        /// <summary>把状态外推到时刻 t (秒)，返回 pose。t 可在过去或未来，不限幅。</summary>
        public abstract Pose PredictAt(double timeSeconds);

        /// <summary>清空内部状态。</summary>
        public abstract void ResetModel();
    }
}
