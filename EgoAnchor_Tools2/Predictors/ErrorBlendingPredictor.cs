using System.Collections.Generic;
using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// 误差平滑淡化预测器 (自包含,非包装器)。
    ///
    /// 这是 VR/网络同步工业管线的标准实现,完整覆盖三步:
    ///   1. 高频外推:用最近观测差分估速度,在 render 帧做匀速外推。
    ///   2. 新息计算:新观测到达时,残差 = 真实观测 - 外推到观测时刻的预测 (外推漂移)。
    ///   3. 误差淡化:残差按 keepRate (如 0.9) 在后续每帧逐步消化,把轨迹平滑拉回正确路线,
    ///      避免新观测到达时的硬跳变。
    ///
    /// 与之前的包装器版本不同:这里外推、新息、淡化三者由同一对象独立管理,
    /// 不依赖外部 inner 预测器,杜绝"inner 校正 + errblend 残差"的双重计算。
    /// 外推用最近 2 个观测差分速度 (匀速模型),简洁且无双重校正风险。
    ///
    /// 旋转残差在切空间 (角轴) 处理,旋转通过右乘 Exp 应用。
    /// </summary>
    public sealed class ErrorBlendingPredictor : IAnchorPredictor
    {
        /// <summary>残差每帧保留比例;0.9 表示每帧消化 10%。</summary>
        private readonly float keepRate;

        /// <summary>允许预测到最近测量之后的最大时长,单位秒。</summary>
        private const float MaxPredictAheadSeconds = 0.2f;

        /// <summary>最近 2 个观测,用于差分速度。</summary>
        private readonly List<PoseObservation> history = new List<PoseObservation>(2);

        /// <summary>当前估计线速度 (m/s),从最近两观测差分得到。</summary>
        private Vec3 linearVelocity = Vec3.Zero;

        /// <summary>当前估计角速度 (rad/s)。</summary>
        private Vec3 angularVelocity = Vec3.Zero;

        /// <summary>当前待消化的位置残差 (世界系,米)。</summary>
        private Vec3 pendingPosCorrection = Vec3.Zero;

        /// <summary>当前待消化的旋转残差 (世界系角轴,rad)。</summary>
        private Vec3 pendingRotCorrection = Vec3.Zero;

        private bool hasEstimate;

        /// <summary>算法标签。</summary>
        public string Label => "error_blending";

        /// <summary>是否已积累至少一个观测。</summary>
        public bool HasEstimate => hasEstimate;

        /// <summary>构造预测器。</summary>
        /// <param name="keepRate">残差每帧保留比例 (0..1),默认 0.9。</param>
        public ErrorBlendingPredictor(float keepRate = 0.9f)
        {
            this.keepRate = AnchorMath.Clamp(keepRate, 0.0f, 0.999f);
        }

        /// <summary>清空状态。</summary>
        public void Reset()
        {
            history.Clear();
            linearVelocity = Vec3.Zero;
            angularVelocity = Vec3.Zero;
            pendingPosCorrection = Vec3.Zero;
            pendingRotCorrection = Vec3.Zero;
            hasEstimate = false;
        }

        /// <summary>提交观测:计算外推残差,更新速度估计。</summary>
        public void SubmitObservation(in PoseObservation observation)
        {
            if (hasEstimate && history.Count >= 1)
            {
                // 1. 新息:用"上一轮状态"外推到本观测时刻,比对真实观测
                PoseObservation prev = history[history.Count - 1];
                float dtObs = (float)(observation.CaptureTimeSeconds - prev.CaptureTimeSeconds);
                if (dtObs > 1e-5f)
                {
                    Vec3 predPos = prev.Position + linearVelocity * dtObs;
                    QuaternionM predRot = AnchorMath.Multiply(prev.Rotation, AnchorMath.Exp(angularVelocity * dtObs));

                    // 残差 = 真实 - 外推预测 (外推漂移)
                    Vec3 dPos = observation.Position - predPos;
                    QuaternionM alignedReal = AnchorMath.AlignHemisphere(predRot, observation.Rotation);
                    Vec3 dRot = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(predRot), alignedReal));

                    // 累积到待消化残差
                    pendingPosCorrection = pendingPosCorrection + dPos;
                    pendingRotCorrection = pendingRotCorrection + dRot;
                }
            }

            // 2. 更新速度估计 (差分)
            history.Add(observation);
            while (history.Count > 2) history.RemoveAt(0);
            if (history.Count == 2)
            {
                PoseObservation a = history[0];
                PoseObservation b = history[1];
                float dt = (float)(b.CaptureTimeSeconds - a.CaptureTimeSeconds);
                if (dt > 1e-5f)
                {
                    linearVelocity = (b.Position - a.Position) / dt;
                    angularVelocity = AnchorMath.AngularVelocity(a.Rotation, b.Rotation, dt);
                }
            }
            hasEstimate = true;
        }

        /// <summary>预测到 render 时间:匀速外推 + 当前残差,然后残差按 keepRate 衰减。</summary>
        public (Vec3 position, QuaternionM rotation) PredictAt(double renderTimeSeconds)
        {
            if (!hasEstimate)
            {
                return (Vec3.Zero, QuaternionM.Identity);
            }

            PoseObservation latest = history[history.Count - 1];
            float ahead = AnchorMath.Clamp((float)(renderTimeSeconds - latest.CaptureTimeSeconds), 0.0f, MaxPredictAheadSeconds);

            // 匀速外推 (纯预测,不含纠偏)
            Vec3 predPos = latest.Position + linearVelocity * ahead;
            QuaternionM predRot = AnchorMath.Multiply(latest.Rotation, AnchorMath.Exp(angularVelocity * ahead));

            // 应用当前残差 (位置世界系直接加,旋转右乘切空间)
            Vec3 outPos = predPos + pendingPosCorrection;
            QuaternionM outRot = AnchorMath.Multiply(predRot, AnchorMath.Exp(pendingRotCorrection));

            // 残差按 keepRate 衰减 (每帧消化 (1-keepRate))
            pendingPosCorrection = pendingPosCorrection * keepRate;
            pendingRotCorrection = pendingRotCorrection * keepRate;

            return (outPos, outRot);
        }
    }
}
