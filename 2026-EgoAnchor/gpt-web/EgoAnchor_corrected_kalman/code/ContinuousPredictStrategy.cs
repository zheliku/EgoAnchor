using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Production render strategy for a delayed, low-rate motion model.
    ///
    /// It differs from raw Predict-to-Now in two essential ways:
    /// 1) prediction is bounded to a finite horizon;
    /// 2) when a new observation changes the model trajectory, the trajectory
    ///    correction is represented as a residual and repaid exponentially.
    ///
    /// The rendered trajectory is C0-continuous across asynchronous Kalman
    /// corrections while retaining a low-latency predictive response.
    /// </summary>
    public sealed class ContinuousPredictStrategy : SmoothingStrategy
    {
        [Tooltip("Maximum prediction horizon after the latest measurement time, seconds. Exploratory default from the supplied logs.")]
        [Range(0.02f, 0.5f)]
        [SerializeField] private float maxPredictionSeconds = 0.18f;

        [Tooltip("Half-life of the correction residual, seconds. Smaller is more responsive; larger is smoother.")]
        [Range(0.01f, 0.5f)]
        [SerializeField] private float correctionHalfLifeSeconds = 0.06f;

        [Tooltip("Safety clamp for a single positional correction residual, metres.")]
        [Min(0.001f)]
        [SerializeField] private float maxPositionResidualMeters = 0.15f;

        [Tooltip("Safety clamp for a single rotational correction residual, degrees.")]
        [Range(1.0f, 180.0f)]
        [SerializeField] private float maxRotationResidualDegrees = 45.0f;

        private Vector3 positionResidual;
        private Vector3 rotationResidualRad;
        private bool hasRendered;
        private Pose lastRenderedPose;
        private double lastRenderTimeSeconds;

        public override string StrategyName => "continuous_predict";

        public override void ResetStrategy()
        {
            positionResidual = Vector3.zero;
            rotationResidualRad = Vector3.zero;
            hasRendered = false;
            lastRenderedPose = Pose.identity;
            lastRenderTimeSeconds = 0.0;
            OutputTargetTimeSeconds = double.NaN;
        }

        /// <summary>
        /// Must be called after the accepted observation has updated the model.
        /// Recompute the trajectory residual at the preceding render time so
        /// the next output continues from the visible pose rather than snapping
        /// to the newly corrected model trajectory.
        /// </summary>
        public override void OnObservation(MotionModel model, in AnchorObservation observation)
        {
            if (!hasRendered || model == null || !model.HasState)
            {
                positionResidual = Vector3.zero;
                rotationResidualRad = Vector3.zero;
                return;
            }

            Pose correctedTrajectoryAtLastRender = PredictBounded(model, lastRenderTimeSeconds);
            positionResidual = lastRenderedPose.position - correctedTrajectoryAtLastRender.position;
            positionResidual = Vector3.ClampMagnitude(
                positionResidual,
                Mathf.Max(maxPositionResidualMeters, 0.001f));

            rotationResidualRad = AnchorMath.RelativeRotationLog(
                correctedTrajectoryAtLastRender.rotation,
                lastRenderedPose.rotation);
            rotationResidualRad = Vector3.ClampMagnitude(
                rotationResidualRad,
                Mathf.Max(maxRotationResidualDegrees, 1.0f) * Mathf.Deg2Rad);
        }

        public override Pose Output(MotionModel model, double nowSeconds)
        {
            if (model == null || !model.HasState)
            {
                OutputTargetTimeSeconds = double.NaN;
                return Pose.identity;
            }

            // Residual blending means there is generally no unique source-time
            // semantics for the final pose.
            OutputTargetTimeSeconds = double.NaN;

            Pose predicted = PredictBounded(model, nowSeconds);
            Pose rendered = new Pose(
                predicted.position + positionResidual,
                AnchorMath.Normalize(AnchorMath.Multiply(
                    predicted.rotation,
                    AnchorMath.Exp(rotationResidualRad))));

            if (hasRendered)
            {
                float dt = Mathf.Max((float)(nowSeconds - lastRenderTimeSeconds), 0.0f);
                float halfLife = Mathf.Max(correctionHalfLifeSeconds, 1e-4f);
                float decay = Mathf.Exp(-Mathf.Log(2.0f) * dt / halfLife);
                positionResidual *= decay;
                rotationResidualRad *= decay;
            }

            hasRendered = true;
            lastRenderedPose = rendered;
            lastRenderTimeSeconds = nowSeconds;
            return rendered;
        }

        private Pose PredictBounded(MotionModel model, double requestedTimeSeconds)
        {
            double latest = model.LastObservationTimeSeconds;
            double maxTime = latest + Mathf.Max(maxPredictionSeconds, 0.0f);
            double bounded = requestedTimeSeconds > maxTime ? maxTime : requestedTimeSeconds;
            return model.PredictAt(bounded);
        }
    }
}
