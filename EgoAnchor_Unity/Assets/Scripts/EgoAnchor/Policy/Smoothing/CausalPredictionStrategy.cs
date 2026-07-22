using System.Globalization;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 有限时域因果预测策略。
    ///
    /// 每个渲染帧把 Kalman 状态向当前时刻外推，但预测时域不超过固定上限。新观测校正
    /// 模型后，策略计算旧显示 pose 与新模型轨迹之间的完整位置、旋转残差；同一时刻再次
    /// 输出时残差使显示保持 C0 连续，随后按真实时间半衰期收敛到新轨迹。
    ///
    /// 该策略只使用当前及过去观测，不缓冲未来控制点。残差不做幅值截断，避免在校正边界
    /// 人为引入跳变；异常大校正由共享 admission 与 lifecycle 处理。
    /// </summary>
    public sealed class CausalPredictionStrategy : SmoothingStrategy
    {
        /// <summary>最近观测之后允许的最大预测时域，单位秒。</summary>
        [Tooltip("最近观测之后允许的最大预测时域，单位秒。pilot 初值为 0.18。")]
        [Range(0.01f, 1.0f)]
        [SerializeField] private float maxPredictionHorizonSeconds = 0.18f;

        /// <summary>位置与旋转校正残差衰减到一半所需的真实时间，单位秒。</summary>
        [Tooltip("校正残差的真实时间半衰期，单位秒，不依赖渲染刷新率。pilot 初值为 0.06。")]
        [Range(0.005f, 1.0f)]
        [SerializeField] private float correctionHalfLifeSeconds = 0.06f;

        /// <summary>当前尚未消除的位置校正残差，单位米。</summary>
        private Vector3 posResidual;

        /// <summary>当前尚未消除的 body-local 旋转校正残差，单位弧度。</summary>
        private Vector3 rotResidual;

        /// <summary>是否已经产生过可作为连续性边界的显示 pose。</summary>
        private bool hasRendered;

        /// <summary>最近一次实际显示的 pose。</summary>
        private Pose lastRender;

        /// <summary>最近一次显示对应的 Unity 单调时钟，单位秒。</summary>
        private double lastRenderTimeSeconds;

        /// <summary>最近一次输出实际使用的模型预测时域，单位秒。</summary>
        private float predictionHorizonSeconds;

        /// <summary>最近一帧实际施加的位置残差快照，单位米。</summary>
        private float appliedPositionResidualMeters;

        /// <summary>最近一帧实际施加的旋转残差快照，单位度。</summary>
        private float appliedRotationResidualDegrees;

        /// <summary>因异常输入清空连续性状态的累计次数。</summary>
        private long continuityResetCount;

        /// <summary>写入评估日志的稳定策略名。</summary>
        public override string StrategyName => "causal_prediction";

        /// <summary>参与正式配置哈希的全部因果预测参数。</summary>
        public override string ConfigurationFingerprint => string.Format(
            CultureInfo.InvariantCulture,
            "horizon:{0:R}|correction-half-life:{1:R}",
            EffectivePredictionHorizonSeconds,
            EffectiveCorrectionHalfLifeSeconds);

        /// <summary>最近一帧真实施加的有限预测与校正连续性诊断。</summary>
        public override SmoothingDiagnostics Diagnostics => new SmoothingDiagnostics(
            predictionHorizonSeconds * 1000.0f,
            appliedPositionResidualMeters,
            appliedRotationResidualDegrees,
            continuityResetCount);

        /// <summary>运行时生效的有限预测时域。</summary>
        private float EffectivePredictionHorizonSeconds => Mathf.Max(maxPredictionHorizonSeconds, 0.0f);

        /// <summary>运行时生效的校正半衰期。</summary>
        private float EffectiveCorrectionHalfLifeSeconds => Mathf.Max(correctionHalfLifeSeconds, 1e-6f);

        /// <summary>清空显示轨迹、校正残差和当帧诊断，保留累计异常重置计数。</summary>
        public override void ResetStrategy()
        {
            ClearContinuityState();
            predictionHorizonSeconds = 0.0f;
            appliedPositionResidualMeters = 0.0f;
            appliedRotationResidualDegrees = 0.0f;
            OutputTargetTimeSeconds = double.NaN;
        }

        /// <summary>在模型校正后重建相对旧显示轨迹的完整位置和旋转残差。</summary>
        public override void OnObservation(MotionModel model, in AnchorObservation observation)
        {
            // 观测先于本帧渲染到达：此刻"按旧轨迹应渲染到哪" = 上一帧 render。
            // model 已被 host 更新过，这里计算残差让新轨迹从旧渲染位置无缝接上。
            if (!hasRendered || model == null || !model.HasState)
            {
                posResidual = Vector3.zero;
                rotResidual = Vector3.zero;
                return;
            }

            Pose modelAtRenderTime = model.PredictAt(ClampPredictionTime(model, lastRenderTimeSeconds));
            posResidual = lastRender.position - modelAtRenderTime.position;
            rotResidual = AnchorMath.RelativeRotationLog(modelAtRenderTime.rotation, lastRender.rotation);
            if (!IsFinite(posResidual) || !IsFinite(rotResidual))
            {
                RegisterContinuityReset();
            }
        }

        /// <summary>在有限预测时域上叠加按真实时间衰减的校正残差。</summary>
        public override Pose Output(MotionModel model, double nowSeconds)
        {
            if (model == null || !model.HasState)
            {
                ResetStrategy();
                return Pose.identity;
            }

            if (!IsFinite(nowSeconds) || (hasRendered && nowSeconds < lastRenderTimeSeconds))
            {
                RegisterContinuityReset();
                OutputTargetTimeSeconds = double.NaN;
                return model.LatestControlPoint.Valid ? model.LatestControlPoint.Pose : Pose.identity;
            }

            // 先按上一显示帧到当前帧的真实时间衰减。相同绝对时刻的累计衰减只由总时间决定，
            // 因而 72/90/120 Hz 下得到一致结果；同一时刻 dt=0，校正边界保持连续。
            DecayResidual(nowSeconds);
            appliedPositionResidualMeters = posResidual.magnitude;
            appliedRotationResidualDegrees = rotResidual.magnitude * Mathf.Rad2Deg;

            double predictionTime = ClampPredictionTime(model, nowSeconds);
            predictionHorizonSeconds = Mathf.Max(
                (float)(predictionTime - model.LastObservationTimeSeconds),
                0.0f);
            Pose basePose = model.PredictAt(predictionTime);

            Vector3 pos = basePose.position + posResidual;
            Quaternion rot = AnchorMath.Multiply(basePose.rotation, AnchorMath.Exp(rotResidual));
            Pose render = new Pose(pos, rot);
            if (!IsFinite(render))
            {
                RegisterContinuityReset();
                OutputTargetTimeSeconds = double.NaN;
                return model.LatestControlPoint.Valid ? model.LatestControlPoint.Pose : Pose.identity;
            }

            hasRendered = true;
            lastRender = render;
            lastRenderTimeSeconds = nowSeconds;

            // 融合 pose 同时包含有限时域预测和旧轨迹残差，没有唯一的观测语义时刻。
            OutputTargetTimeSeconds = double.NaN;
            return render;
        }

        /// <summary>按真实时间半衰期衰减完整位置和旋转校正残差。</summary>
        private void DecayResidual(double nowSeconds)
        {
            if (!hasRendered)
            {
                return;
            }

            float elapsedSeconds = Mathf.Max((float)(nowSeconds - lastRenderTimeSeconds), 0.0f);
            float decay = Mathf.Pow(0.5f, elapsedSeconds / EffectiveCorrectionHalfLifeSeconds);
            posResidual *= decay;
            rotResidual *= decay;
        }

        /// <summary>把请求时刻限制在最近观测至固定预测时域上限之间。</summary>
        private double ClampPredictionTime(MotionModel model, double requestedTime)
        {
            double observationTime = model.LastObservationTimeSeconds;
            double horizonTime = observationTime + EffectivePredictionHorizonSeconds;
            return System.Math.Max(observationTime, System.Math.Min(requestedTime, horizonTime));
        }

        /// <summary>记录一次异常连续性重置，并清空旧显示轨迹和残差。</summary>
        private void RegisterContinuityReset()
        {
            continuityResetCount++;
            ClearContinuityState();
            predictionHorizonSeconds = 0.0f;
            appliedPositionResidualMeters = 0.0f;
            appliedRotationResidualDegrees = 0.0f;
        }

        /// <summary>清空连续性状态，不改变累计异常计数。</summary>
        private void ClearContinuityState()
        {
            posResidual = Vector3.zero;
            rotResidual = Vector3.zero;
            hasRendered = false;
            lastRender = Pose.identity;
            lastRenderTimeSeconds = 0.0;
        }

        /// <summary>判断时间值是否有限。</summary>
        private static bool IsFinite(double value)
        {
            return !double.IsNaN(value) && !double.IsInfinity(value);
        }

        /// <summary>判断三维向量是否全部有限。</summary>
        private static bool IsFinite(Vector3 value)
        {
            return IsFinite(value.x) && IsFinite(value.y) && IsFinite(value.z);
        }

        /// <summary>判断 pose 的位置和旋转是否全部有限。</summary>
        private static bool IsFinite(Pose value)
        {
            return IsFinite(value.position)
                && IsFinite(value.rotation.x)
                && IsFinite(value.rotation.y)
                && IsFinite(value.rotation.z)
                && IsFinite(value.rotation.w);
        }

        /// <summary>判断单精度值是否有限。</summary>
        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }
    }
}
