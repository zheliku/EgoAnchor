using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Corrected constant-velocity Kalman motion model.
    ///
    /// Position uses three independent [position, velocity] filters with the
    /// continuous-white-acceleration process covariance
    ///
    ///     Q = q_a * [ dt^3/3  dt^2/2 ; dt^2/2  dt ].
    ///
    /// Rotation is maintained in a local SO(3) tangent chart. The chart is
    /// rebased after every accepted observation, preventing the fixed-reference
    /// log-map wrap that occurs during large rotations.
    ///
    /// This class estimates state only. Render-time continuity and prediction
    /// horizon limiting belong in a SmoothingStrategy such as
    /// ContinuousPredictStrategy.
    /// </summary>
    public sealed class KalmanModel : MotionModel
    {
        [Header("Position")]
        [Tooltip("Continuous white-acceleration spectral density, m^2/s^3. Exploratory default calibrated on the supplied logs.")]
        [Min(0.0f)]
        [SerializeField] private float positionAccelerationNoiseDensity = 0.10f;

        [Tooltip("Accepted-candidate position measurement standard deviation in metres. Variance is computed internally.")]
        [Min(0.0001f)]
        [SerializeField] private float positionMeasurementStdMeters = 0.008f;

        [Tooltip("Initial linear-velocity standard deviation in m/s.")]
        [Min(0.001f)]
        [SerializeField] private float initialLinearVelocityStd = 0.50f;

        [Header("Rotation")]
        [Tooltip("Continuous white-angular-acceleration spectral density, rad^2/s^3.")]
        [Min(0.0f)]
        [SerializeField] private float rotationAngularAccelerationNoiseDensity = 0.30f;

        [Tooltip("Accepted-candidate rotation measurement standard deviation in degrees.")]
        [Min(0.01f)]
        [SerializeField] private float rotationMeasurementStdDegrees = 2.0f;

        [Tooltip("Initial angular-velocity standard deviation in rad/s.")]
        [Min(0.001f)]
        [SerializeField] private float initialAngularVelocityStd = 1.0f;

        [Header("Robustness")]
        [Tooltip("Per-axis normalized-innovation soft gate. Set <= 0 to disable. Values beyond the gate inflate R instead of hard snapping.")]
        [SerializeField] private float innovationGateSigma = 4.0f;

        [Tooltip("Reject observations whose measurement timestamp is not newer than the current state timestamp.")]
        [SerializeField] private bool rejectNonIncreasingTimestamps = true;

        private CvKalman1D x;
        private CvKalman1D y;
        private CvKalman1D z;
        private CvKalman1D rx;
        private CvKalman1D ry;
        private CvKalman1D rz;

        // Rotation represented as rotationReference * Exp(localRotationVector).
        // The local vector is injected into the reference and reset after each
        // accepted correction, keeping the tangent chart small.
        private Quaternion rotationReference;
        private double lastTimeSeconds;
        private bool hasState;

        public override string ModelName => "kalman_corrected";

        public override string ConfigurationFingerprint =>
            $"pa={positionAccelerationNoiseDensity:F6};" +
            $"ps={positionMeasurementStdMeters:F6};" +
            $"pv0={initialLinearVelocityStd:F6};" +
            $"ra={rotationAngularAccelerationNoiseDensity:F6};" +
            $"rsd={rotationMeasurementStdDegrees:F6};" +
            $"rv0={initialAngularVelocityStd:F6};" +
            $"gate={innovationGateSigma:F3};" +
            $"monotonic={rejectNonIncreasingTimestamps}";

        public override bool HasState => hasState;
        public override double LastObservationTimeSeconds => lastTimeSeconds;
        public override Vector3 LinearVelocity => new Vector3(x.Velocity, y.Velocity, z.Velocity);
        public override Vector3 AngularVelocityRad => new Vector3(rx.Velocity, ry.Velocity, rz.Velocity);

        public override ControlPoint LatestControlPoint
        {
            get
            {
                if (!hasState)
                {
                    return default;
                }

                return new ControlPoint(
                    lastTimeSeconds,
                    new Pose(CurrentPosition(), CurrentRotation()),
                    LinearVelocity,
                    AngularVelocityRad);
            }
        }

        public override void Snap(in AnchorObservation observation)
        {
            float positionVariance = Square(Mathf.Max(positionMeasurementStdMeters, 1e-5f));
            float velocityVariance = Square(Mathf.Max(initialLinearVelocityStd, 1e-4f));

            Vector3 p = observation.WorldPose.position;
            x.Reset(p.x, positionVariance, velocityVariance);
            y.Reset(p.y, positionVariance, velocityVariance);
            z.Reset(p.z, positionVariance, velocityVariance);

            float rotationStdRad = Mathf.Max(rotationMeasurementStdDegrees, 1e-3f) * Mathf.Deg2Rad;
            float rotationVariance = Square(rotationStdRad);
            float angularVelocityVariance = Square(Mathf.Max(initialAngularVelocityStd, 1e-4f));

            rotationReference = AnchorMath.Normalize(observation.WorldPose.rotation);
            rx.Reset(0.0f, rotationVariance, angularVelocityVariance);
            ry.Reset(0.0f, rotationVariance, angularVelocityVariance);
            rz.Reset(0.0f, rotationVariance, angularVelocityVariance);

            lastTimeSeconds = observation.MeasurementTimeSeconds;
            hasState = true;
        }

        public override void UpdateState(in AnchorObservation observation)
        {
            if (!hasState)
            {
                Snap(observation);
                return;
            }

            double t = observation.MeasurementTimeSeconds;
            double dtDouble = t - lastTimeSeconds;
            if (rejectNonIncreasingTimestamps && dtDouble <= 1e-6)
            {
                return;
            }

            float dt = Mathf.Max((float)dtDouble, 0.0f);
            if (dt <= 0.0f)
            {
                return;
            }

            float positionVariance = Square(Mathf.Max(positionMeasurementStdMeters, 1e-5f));
            float rotationStdRad = Mathf.Max(rotationMeasurementStdDegrees, 1e-3f) * Mathf.Deg2Rad;
            float rotationVariance = Square(rotationStdRad);

            x.Predict(dt, positionAccelerationNoiseDensity);
            y.Predict(dt, positionAccelerationNoiseDensity);
            z.Predict(dt, positionAccelerationNoiseDensity);

            Vector3 measuredPosition = observation.WorldPose.position;
            x.Correct(measuredPosition.x, positionVariance, innovationGateSigma);
            y.Correct(measuredPosition.y, positionVariance, innovationGateSigma);
            z.Correct(measuredPosition.z, positionVariance, innovationGateSigma);

            // Predict the local rotation vector and angular velocity.
            rx.Predict(dt, rotationAngularAccelerationNoiseDensity);
            ry.Predict(dt, rotationAngularAccelerationNoiseDensity);
            rz.Predict(dt, rotationAngularAccelerationNoiseDensity);

            Quaternion predictedRotation = CurrentRotation();
            Quaternion measuredRotation = AnchorMath.AlignHemisphere(
                predictedRotation,
                observation.WorldPose.rotation);

            // Measurement in the current local tangent chart.
            Vector3 measuredLocalRotation = AnchorMath.RelativeRotationLog(
                rotationReference,
                measuredRotation);

            rx.Correct(measuredLocalRotation.x, rotationVariance, innovationGateSigma);
            ry.Correct(measuredLocalRotation.y, rotationVariance, innovationGateSigma);
            rz.Correct(measuredLocalRotation.z, rotationVariance, innovationGateSigma);

            // Inject the corrected local rotation into the quaternion reference.
            // Rebase every observation so the log-map state remains near zero.
            Vector3 injectedRotation = CurrentRotationVector();
            Quaternion delta = AnchorMath.Exp(injectedRotation);
            rotationReference = AnchorMath.Normalize(
                AnchorMath.Multiply(rotationReference, delta));

            // Angular velocity is expressed in the local reference frame.
            // Rotate it into the newly rebased frame. With isotropic per-axis
            // noise this is a sound small-error approximation without a full
            // 6x6 covariance implementation.
            Vector3 rebasedAngularVelocity = Quaternion.Inverse(delta) * AngularVelocityRad;
            rx.InjectPositionReset(rebasedAngularVelocity.x);
            ry.InjectPositionReset(rebasedAngularVelocity.y);
            rz.InjectPositionReset(rebasedAngularVelocity.z);

            lastTimeSeconds = t;
        }

        public override Pose PredictAt(double timeSeconds)
        {
            if (!hasState)
            {
                return Pose.identity;
            }

            float ahead = (float)(timeSeconds - lastTimeSeconds);
            Vector3 position = CurrentPosition() + LinearVelocity * ahead;
            Quaternion rotation = AnchorMath.Multiply(
                rotationReference,
                AnchorMath.Exp(AngularVelocityRad * ahead));
            return new Pose(position, AnchorMath.Normalize(rotation));
        }

        public override void ResetModel()
        {
            x.Clear();
            y.Clear();
            z.Clear();
            rx.Clear();
            ry.Clear();
            rz.Clear();
            rotationReference = Quaternion.identity;
            lastTimeSeconds = 0.0;
            hasState = false;
        }

        private Vector3 CurrentPosition() => new Vector3(x.Position, y.Position, z.Position);
        private Vector3 CurrentRotationVector() => new Vector3(rx.Position, ry.Position, rz.Position);

        private Quaternion CurrentRotation()
        {
            return AnchorMath.Normalize(
                AnchorMath.Multiply(rotationReference, AnchorMath.Exp(CurrentRotationVector())));
        }

        private static float Square(float value) => value * value;

        /// <summary>
        /// One-dimensional constant-velocity Kalman filter.
        /// State: [position, velocity]. Covariance is stored symmetrically.
        /// </summary>
        private struct CvKalman1D
        {
            public float Position { get; private set; }
            public float Velocity { get; private set; }

            private double p00;
            private double p01;
            private double p11;
            private bool initialized;

            public void Reset(float position, float positionVariance, float velocityVariance)
            {
                Position = position;
                Velocity = 0.0f;
                p00 = Mathf.Max(positionVariance, 1e-12f);
                p01 = 0.0;
                p11 = Mathf.Max(velocityVariance, 1e-12f);
                initialized = true;
            }

            public void Predict(float dt, float accelerationNoiseDensity)
            {
                if (!initialized || !(dt > 0.0f))
                {
                    return;
                }

                double d = dt;
                double oldP00 = p00;
                double oldP01 = p01;
                double oldP11 = p11;
                double q = System.Math.Max(accelerationNoiseDensity, 0.0f);

                Position += Velocity * dt;

                // F P F^T + Q, Q from continuous white acceleration.
                p00 = oldP00 + 2.0 * d * oldP01 + d * d * oldP11
                    + q * d * d * d / 3.0;
                p01 = oldP01 + d * oldP11 + q * d * d / 2.0;
                p11 = oldP11 + q * d;
                StabilizeCovariance();
            }

            public void Correct(float measurement, float measurementVariance, float gateSigma)
            {
                if (!initialized)
                {
                    Reset(measurement, measurementVariance, 1.0f);
                    return;
                }

                double innovation = measurement - Position;
                double usedR = System.Math.Max(measurementVariance, 1e-12f);

                // Soft innovation gate: inflate R for extreme residuals instead
                // of injecting almost the entire outlier into the state.
                if (gateSigma > 0.0f)
                {
                    double gate2 = gateSigma * gateSigma;
                    double nominalS = System.Math.Max(p00 + usedR, 1e-15);
                    double nis = innovation * innovation / nominalS;
                    if (nis > gate2)
                    {
                        usedR = System.Math.Max(
                            usedR,
                            innovation * innovation / gate2 - p00);
                    }
                }

                double s = System.Math.Max(p00 + usedR, 1e-15);
                double k0 = p00 / s;
                double k1 = p01 / s;

                Position += (float)(k0 * innovation);
                Velocity += (float)(k1 * innovation);

                // Joseph covariance update: (I-KH)P(I-KH)^T + K R K^T.
                double oldP00 = p00;
                double oldP01 = p01;
                double oldP11 = p11;
                double a = 1.0 - k0;

                double newP00 = a * a * oldP00 + k0 * k0 * usedR;
                double newP01 = a * (oldP01 - k1 * oldP00) + k0 * k1 * usedR;
                double newP11 = oldP11 - 2.0 * k1 * oldP01
                    + k1 * k1 * oldP00 + k1 * k1 * usedR;

                p00 = newP00;
                p01 = newP01;
                p11 = newP11;
                StabilizeCovariance();
            }

            /// <summary>
            /// Error-state injection used by the rotation channel: set the
            /// local angle mean to zero while preserving covariance and replace
            /// angular velocity with the value expressed in the new chart.
            /// </summary>
            public void InjectPositionReset(float rebasedVelocity)
            {
                Position = 0.0f;
                Velocity = rebasedVelocity;
                StabilizeCovariance();
            }

            public void Clear()
            {
                Position = 0.0f;
                Velocity = 0.0f;
                p00 = 0.0;
                p01 = 0.0;
                p11 = 0.0;
                initialized = false;
            }

            private void StabilizeCovariance()
            {
                p00 = System.Math.Max(p00, 0.0);
                p11 = System.Math.Max(p11, 0.0);

                // Enforce |p01| <= sqrt(p00*p11), preserving positive
                // semidefiniteness under finite-precision arithmetic.
                double bound = System.Math.Sqrt(System.Math.Max(p00 * p11, 0.0));
                if (p01 > bound)
                {
                    p01 = bound;
                }
                else if (p01 < -bound)
                {
                    p01 = -bound;
                }
            }
        }
    }
}
