using System.Collections.Generic;
using System.Reflection;
using EgoAnchor.Policy;
using NUnit.Framework;
using UnityEngine;

namespace EgoAnchor.Tests
{
    /// <summary>
    /// 验证 Kalman 协方差数学、低频高时延行为，以及输出策略对校正边界的连续性影响。
    /// </summary>
    public sealed class KalmanPredictionTests
    {
        /// <summary>标准连续白噪声加速度离散化必须给出解析协方差。</summary>
        [Test]
        public void PredictUsesContinuousWhiteAccelerationCovariance()
        {
            ConstVelocityKalman filter = new ConstVelocityKalman();
            filter.Reset(2.0f, -3.0f, 0.4f, 0.7f);

            filter.Predict(0.2f, 0.5f);

            Assert.That(filter.Position, Is.EqualTo(1.4f).Within(1e-6f));
            Assert.That(filter.Velocity, Is.EqualTo(-3.0f).Within(1e-6f));
            Assert.That(filter.P00, Is.EqualTo(0.429333333f).Within(1e-6f));
            Assert.That(filter.P01, Is.EqualTo(0.15f).Within(1e-6f));
            Assert.That(filter.P10, Is.EqualTo(0.15f).Within(1e-6f));
            Assert.That(filter.P11, Is.EqualTo(0.8f).Within(1e-6f));
        }

        /// <summary>同一时间跨度的一次预测与分段预测应保持状态和协方差一致。</summary>
        [Test]
        public void ContinuousWhiteAccelerationPredictionHasSemigroupConsistency()
        {
            ConstVelocityKalman whole = new ConstVelocityKalman();
            ConstVelocityKalman split = new ConstVelocityKalman();
            whole.Reset(0.3f, -0.7f, 0.02f, 0.5f);
            split.Reset(0.3f, -0.7f, 0.02f, 0.5f);

            whole.Predict(0.2f, 0.04f);
            split.Predict(0.1f, 0.04f);
            split.Predict(0.1f, 0.04f);

            Assert.That(split.Position, Is.EqualTo(whole.Position).Within(1e-6f));
            Assert.That(split.Velocity, Is.EqualTo(whole.Velocity).Within(1e-6f));
            Assert.That(split.P00, Is.EqualTo(whole.P00).Within(1e-6f));
            Assert.That(split.P01, Is.EqualTo(whole.P01).Within(1e-6f));
            Assert.That(split.P10, Is.EqualTo(whole.P10).Within(1e-6f));
            Assert.That(split.P11, Is.EqualTo(whole.P11).Within(1e-6f));
        }

        /// <summary>Joseph 校正应匹配解析结果，并保持协方差对称半正定。</summary>
        [Test]
        public void CorrectMatchesScalarUpdateAndKeepsCovariancePositiveSemidefinite()
        {
            ConstVelocityKalman filter = new ConstVelocityKalman();
            filter.Reset(2.0f, -3.0f, 0.4f, 0.7f);
            filter.Predict(0.2f, 0.5f);

            filter.Correct(1.6f, 0.04f);

            Assert.That(filter.Position, Is.EqualTo(1.582954545f).Within(1e-6f));
            Assert.That(filter.Velocity, Is.EqualTo(-2.936079545f).Within(1e-6f));
            Assert.That(filter.P00, Is.EqualTo(0.0365909091f).Within(1e-6f));
            Assert.That(filter.P01, Is.EqualTo(0.0127840909f).Within(1e-6f));
            Assert.That(filter.P10, Is.EqualTo(0.0127840909f).Within(1e-6f));
            Assert.That(filter.P11, Is.EqualTo(0.7520596591f).Within(1e-6f));
            Assert.That(Mathf.Abs(filter.P01 - filter.P10), Is.LessThan(1e-7f));
            Assert.That(filter.P00, Is.GreaterThanOrEqualTo(0.0f));
            Assert.That(filter.P11, Is.GreaterThanOrEqualTo(0.0f));
            Assert.That(filter.P00 * filter.P11 - filter.P01 * filter.P10, Is.GreaterThanOrEqualTo(-1e-7f));
        }

        /// <summary>长时间不规则采样和反复校正后，协方差仍应保持有限、对称和半正定。</summary>
        [Test]
        public void IrregularLongSequenceKeepsCovarianceValid()
        {
            ConstVelocityKalman filter = new ConstVelocityKalman();
            filter.Reset(0.0f, 0.0f, 0.000004f, 1.0f);

            for (int index = 0; index < 2000; index++)
            {
                float dt = 0.04f + 0.013f * (index % 7);
                filter.Predict(dt, 0.002f);
                filter.Correct(Mathf.Sin(index * 0.017f), 0.000004f);

                Assert.That(IsFinite(filter.Position) && IsFinite(filter.Velocity), Is.True);
                Assert.That(IsFinite(filter.P00) && IsFinite(filter.P01) && IsFinite(filter.P10) && IsFinite(filter.P11), Is.True);
                Assert.That(Mathf.Abs(filter.P01 - filter.P10), Is.LessThan(1e-7f));
                Assert.That(filter.P00, Is.GreaterThanOrEqualTo(0.0f));
                Assert.That(filter.P11, Is.GreaterThanOrEqualTo(0.0f));
                Assert.That(filter.P00 * filter.P11 - filter.P01 * filter.P10, Is.GreaterThanOrEqualTo(-1e-7f));
            }
        }

        /// <summary>
        /// 10 Hz 观测和 200 ms 到达延迟本身不应让恒速 6DoF 预测失控。
        /// </summary>
        [Test]
        public void DelayedTenHertzObservationsStayBoundedAtRenderTime()
        {
            GameObject owner = new GameObject("KalmanDelayedPredictionTests");
            try
            {
                KalmanModel model = owner.AddComponent<KalmanModel>();
                Vector3 axis = new Vector3(0.3f, 0.7f, -0.2f).normalized;
                float maxPositionError = 0.0f;
                float maxRotationError = 0.0f;

                for (int index = 0; index < 30; index++)
                {
                    double captureTime = index * 0.1;
                    double arrivalTime = captureTime + 0.2;
                    float sign = index % 2 == 0 ? 1.0f : -1.0f;
                    Pose truthAtCapture = ConstantMotionPose(captureTime, axis);
                    Pose measured = new Pose(
                        truthAtCapture.position + Vector3.right * (0.004f * sign),
                        AnchorMath.Multiply(truthAtCapture.rotation, Quaternion.AngleAxis(0.5f * sign, axis)));
                    AnchorObservation observation = AnchorObservation.FromAlignedPose(
                        index + 1,
                        measured,
                        arrivalTime,
                        1.0f,
                        captureTimeSeconds: captureTime);

                    if (!model.HasState)
                    {
                        model.Snap(observation);
                    }
                    else
                    {
                        model.UpdateState(observation);
                    }

                    Assert.That(model.LastObservationTimeSeconds, Is.EqualTo(captureTime).Within(1e-9));
                    Pose predicted = model.PredictAt(arrivalTime);
                    AssertFinite(predicted, model);
                    if (index >= 10)
                    {
                        Pose truthAtArrival = ConstantMotionPose(arrivalTime, axis);
                        maxPositionError = Mathf.Max(maxPositionError, Vector3.Distance(predicted.position, truthAtArrival.position));
                        maxRotationError = Mathf.Max(maxRotationError, AnchorMath.AngleDegrees(predicted.rotation, truthAtArrival.rotation));
                    }
                }

                Assert.That(maxPositionError, Is.LessThan(0.010f));
                Assert.That(maxRotationError, Is.LessThan(1.0f));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(owner);
            }
        }

        /// <summary>
        /// 新测量会让直接外推在同一渲染时刻换轨；历史 Linear/SLERP 应保持该时刻输出连续。
        /// </summary>
        [Test]
        public void LinearSlerpKeepsCorrectionBoundaryContinuous()
        {
            GameObject directOwner = new GameObject("KalmanDirectBoundaryTests");
            GameObject smoothOwner = new GameObject("KalmanSmoothBoundaryTests");
            try
            {
                KalmanModel directModel = directOwner.AddComponent<KalmanModel>();
                PredictToNowStrategy directStrategy = directOwner.AddComponent<PredictToNowStrategy>();
                KalmanModel smoothModel = smoothOwner.AddComponent<KalmanModel>();
                LinearSlerpStrategy smoothStrategy = smoothOwner.AddComponent<LinearSlerpStrategy>();
                smoothStrategy.ResetStrategy();

                AnchorObservation first = Observation(1, 0.0, 0.0f, 0.0f);
                AnchorObservation second = Observation(2, 0.1, 0.02f, 5.0f);
                AnchorObservation correction = Observation(3, 0.2, 0.20f, 60.0f);
                Feed(directModel, directStrategy, first);
                Feed(directModel, directStrategy, second);
                Feed(smoothModel, smoothStrategy, first);
                Feed(smoothModel, smoothStrategy, second);

                const double renderTime = 0.3;
                Pose directBefore = directStrategy.Output(directModel, renderTime);
                Pose smoothBefore = smoothStrategy.Output(smoothModel, renderTime);
                Feed(directModel, directStrategy, correction);
                Feed(smoothModel, smoothStrategy, correction);
                Pose directAfter = directStrategy.Output(directModel, renderTime);
                Pose smoothAfter = smoothStrategy.Output(smoothModel, renderTime);

                Assert.That(Vector3.Distance(directBefore.position, directAfter.position), Is.GreaterThan(0.05f));
                Assert.That(AnchorMath.AngleDegrees(directBefore.rotation, directAfter.rotation), Is.GreaterThan(10.0f));
                Assert.That(Vector3.Distance(smoothBefore.position, smoothAfter.position), Is.LessThan(1e-6f));
                Assert.That(AnchorMath.AngleDegrees(smoothBefore.rotation, smoothAfter.rotation), Is.LessThan(1e-4f));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(directOwner);
                UnityEngine.Object.DestroyImmediate(smoothOwner);
            }
        }

        /// <summary>新观测校正后在同一渲染时刻应保持位置与旋转严格连续。</summary>
        [Test]
        public void CausalPredictionKeepsCorrectionBoundaryContinuous()
        {
            GameObject owner = new GameObject("CausalPredictionBoundaryTests");
            try
            {
                ConstantVelocityModel model = owner.AddComponent<ConstantVelocityModel>();
                CausalPredictionStrategy strategy = owner.AddComponent<CausalPredictionStrategy>();
                strategy.ResetStrategy();

                Feed(model, strategy, Observation(1, 0.0, 0.0f, 0.0f));
                Feed(model, strategy, Observation(2, 0.1, 0.02f, 5.0f));

                const double renderTime = 0.25;
                Pose beforeCorrection = strategy.Output(model, renderTime);
                Feed(model, strategy, Observation(3, 0.2, 0.20f, 60.0f));
                Pose afterCorrection = strategy.Output(model, renderTime);

                Assert.That(Vector3.Distance(beforeCorrection.position, afterCorrection.position), Is.LessThan(1e-6f));
                Assert.That(AnchorMath.AngleDegrees(beforeCorrection.rotation, afterCorrection.rotation), Is.LessThan(1e-4f));
                Assert.That(strategy.Diagnostics.CorrectionPositionResidualMeters, Is.GreaterThan(0.0f));
                Assert.That(strategy.Diagnostics.CorrectionRotationResidualDegrees, Is.GreaterThan(0.0f));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(owner);
            }
        }

        /// <summary>60 ms 半衰期在 72、90、120 Hz 渲染下必须产生相同输出。</summary>
        [Test]
        public void CausalPredictionHalfLifeIsIndependentOfRenderRate()
        {
            Pose at72Hz = RunCausalHalfLifeAtFrameRate(72, out SmoothingDiagnostics diagnostics72Hz);
            Pose at90Hz = RunCausalHalfLifeAtFrameRate(90, out SmoothingDiagnostics diagnostics90Hz);
            Pose at120Hz = RunCausalHalfLifeAtFrameRate(120, out SmoothingDiagnostics diagnostics120Hz);

            Assert.That(at72Hz.position.x, Is.EqualTo(0.15f).Within(1e-5f));
            Assert.That(at90Hz.position.x, Is.EqualTo(at72Hz.position.x).Within(1e-5f));
            Assert.That(at120Hz.position.x, Is.EqualTo(at72Hz.position.x).Within(1e-5f));
            Assert.That(AnchorMath.AngleDegrees(at72Hz.rotation, at90Hz.rotation), Is.LessThan(1e-3f));
            Assert.That(AnchorMath.AngleDegrees(at72Hz.rotation, at120Hz.rotation), Is.LessThan(1e-3f));
            Assert.That(diagnostics72Hz.CorrectionPositionResidualMeters, Is.EqualTo(0.05f).Within(1e-5f));
            Assert.That(diagnostics90Hz.CorrectionPositionResidualMeters, Is.EqualTo(0.05f).Within(1e-5f));
            Assert.That(diagnostics120Hz.CorrectionPositionResidualMeters, Is.EqualTo(0.05f).Within(1e-5f));
            Assert.That(diagnostics72Hz.CorrectionRotationResidualDegrees, Is.EqualTo(5.0f).Within(1e-3f));
            Assert.That(diagnostics72Hz.ContinuityResetCount, Is.Zero);
        }

        /// <summary>长时间无观测时，实际预测时域和输出都必须停在 180 ms 上限。</summary>
        [Test]
        public void CausalPredictionNeverExceedsConfiguredHorizon()
        {
            GameObject owner = new GameObject("CausalPredictionHorizonTests");
            try
            {
                ConstantVelocityModel model = owner.AddComponent<ConstantVelocityModel>();
                CausalPredictionStrategy strategy = owner.AddComponent<CausalPredictionStrategy>();
                strategy.ResetStrategy();

                Feed(model, strategy, Observation(1, 0.0, 0.0f, 0.0f));
                Feed(model, strategy, Observation(2, 0.1, 0.1f, 10.0f));
                Pose output = strategy.Output(model, 1.0);

                Assert.That(strategy.Diagnostics.PredictionHorizonMilliseconds, Is.EqualTo(180.0f).Within(1e-4f));
                Assert.That(output.position.x, Is.EqualTo(0.28f).Within(1e-5f));
                Assert.That(AnchorMath.AngleDegrees(Quaternion.identity, output.rotation), Is.EqualTo(28.0f).Within(1e-3f));

                strategy.Output(model, 0.9);
                Assert.That(strategy.Diagnostics.ContinuityResetCount, Is.EqualTo(1));
                strategy.ResetStrategy();
                Assert.That(strategy.Diagnostics.ContinuityResetCount, Is.EqualTo(1), "显式 reset 不应回退累计异常计数。");
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(owner);
            }
        }

        /// <summary>合成起停序列应有有界响应，停止校正不得产生反向回动。</summary>
        [Test]
        public void CausalPredictionStartStopResponseHasNoReverseRebound()
        {
            GameObject owner = new GameObject("CausalPredictionStartStopTests");
            try
            {
                ConstantVelocityModel model = owner.AddComponent<ConstantVelocityModel>();
                CausalPredictionStrategy strategy = owner.AddComponent<CausalPredictionStrategy>();
                strategy.ResetStrategy();

                Feed(model, strategy, Observation(1, 0.0, 0.0f, 0.0f));
                strategy.Output(model, 0.0);
                Feed(model, strategy, Observation(2, 0.1, 0.1f, 0.0f));
                strategy.Output(model, 0.1);

                double startResponseSeconds = double.NaN;
                for (int tick = 1; tick <= 9; tick++)
                {
                    double time = 0.1 + tick / 90.0;
                    Pose output = strategy.Output(model, time);
                    if (double.IsNaN(startResponseSeconds) && output.position.x >= 0.05f)
                    {
                        startResponseSeconds = time - 0.1;
                    }
                }

                Feed(model, strategy, Observation(3, 0.2, 0.2f, 0.0f));
                for (int tick = 1; tick <= 9; tick++)
                {
                    strategy.Output(model, 0.2 + tick / 90.0);
                }

                Pose beforeStop = strategy.Output(model, 0.3);
                Feed(model, strategy, Observation(4, 0.3, 0.2f, 0.0f));
                Pose atStop = strategy.Output(model, 0.3);

                float peakForwardOvershoot = atStop.position.x - 0.2f;
                float peakReverseReturn = atStop.position.x - 0.2f;
                double settlingTimeSeconds = double.NaN;
                for (int tick = 1; tick <= 90; tick++)
                {
                    double time = 0.3 + tick / 90.0;
                    float error = strategy.Output(model, time).position.x - 0.2f;
                    peakForwardOvershoot = Mathf.Max(peakForwardOvershoot, error);
                    peakReverseReturn = Mathf.Min(peakReverseReturn, error);
                    if (double.IsNaN(settlingTimeSeconds) && Mathf.Abs(error) <= 0.001f)
                    {
                        settlingTimeSeconds = time - 0.3;
                    }
                }

                Assert.That(startResponseSeconds, Is.LessThanOrEqualTo(0.06));
                Assert.That(Vector3.Distance(beforeStop.position, atStop.position), Is.LessThan(1e-6f));
                Assert.That(peakForwardOvershoot, Is.LessThanOrEqualTo(0.11f));
                Assert.That(peakReverseReturn, Is.GreaterThanOrEqualTo(-1e-5f));
                Assert.That(settlingTimeSeconds, Is.LessThanOrEqualTo(0.75));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(owner);
            }
        }

        /// <summary>共享入口必须拒绝重复和非法测量时间，且不能污染模型与插值历史。</summary>
        [Test]
        public void HostRejectsNonMonotonicMeasurementTimeWithoutChangingState()
        {
            GameObject owner = new GameObject("KalmanMeasurementTimeTests");
            try
            {
                AnchorPolicyHost host = owner.AddComponent<AnchorPolicyHost>();
                KalmanModel model = owner.AddComponent<KalmanModel>();
                LinearSlerpStrategy strategy = owner.AddComponent<LinearSlerpStrategy>();
                SetPrivateField(host, "motionModel", model);
                SetPrivateField(host, "smoothingStrategy", strategy);

                AnchorPolicyDecision firstDecision = host.AcceptPose(Observation(1, 1.0, 0.1f, 5.0f));
                Pose acceptedPose = model.LatestControlPoint.Pose;
                AnchorPolicyDecision duplicateDecision = host.AcceptPose(Observation(2, 1.0, 9.0f, 170.0f));
                AnchorPolicyDecision invalidDecision = host.AcceptPose(AnchorObservation.FromAlignedPose(
                    3,
                    new Pose(Vector3.one, Quaternion.identity),
                    double.NaN,
                    1.0f,
                    captureTimeSeconds: -1.0));
                List<ControlPoint> points = GetPrivateField<List<ControlPoint>>(strategy, "points");

                Assert.That(firstDecision.Action, Is.EqualTo(AnchorPolicyAction.Snap));
                Assert.That(duplicateDecision.Action, Is.EqualTo(AnchorPolicyAction.Reject));
                Assert.That(duplicateDecision.Reason, Is.EqualTo("non_monotonic_measurement_time"));
                Assert.That(invalidDecision.Action, Is.EqualTo(AnchorPolicyAction.Reject));
                Assert.That(invalidDecision.Reason, Is.EqualTo("invalid_measurement_time"));
                Assert.That(model.LastObservationTimeSeconds, Is.EqualTo(1.0));
                Assert.That(Vector3.Distance(model.LatestControlPoint.Pose.position, acceptedPose.position), Is.LessThan(1e-6f));
                Assert.That(points, Has.Count.EqualTo(1));
                Assert.That(host.AcceptedCount, Is.EqualTo(1));
                Assert.That(host.RejectedCount, Is.EqualTo(2));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(owner);
            }
        }

        /// <summary>构造测试使用的恒速平移和固定轴旋转真值。</summary>
        private static Pose ConstantMotionPose(double timeSeconds, Vector3 axis)
        {
            float time = (float)timeSeconds;
            return new Pose(Vector3.right * (0.25f * time), Quaternion.AngleAxis(30.0f * time, axis));
        }

        /// <summary>构造按 capture time 归属的单帧测试观测。</summary>
        private static AnchorObservation Observation(long frameId, double captureTime, float positionX, float angleDegrees)
        {
            return AnchorObservation.FromAlignedPose(
                frameId,
                new Pose(Vector3.right * positionX, Quaternion.Euler(0.0f, angleDegrees, 0.0f)),
                captureTime + 0.1,
                1.0f,
                captureTimeSeconds: captureTime);
        }

        /// <summary>将观测同时交给运动模型与对应输出策略。</summary>
        private static void Feed(MotionModel model, SmoothingStrategy strategy, in AnchorObservation observation)
        {
            if (model.HasState)
            {
                model.UpdateState(observation);
            }
            else
            {
                model.Snap(observation);
            }

            strategy.OnObservation(model, observation);
        }

        /// <summary>在指定渲染帧率下运行一次具有位置和旋转校正残差的半衰期测试。</summary>
        private static Pose RunCausalHalfLifeAtFrameRate(
            int framesPerSecond,
            out SmoothingDiagnostics diagnostics)
        {
            GameObject owner = new GameObject($"CausalHalfLife{framesPerSecond}HzTests");
            try
            {
                ConstantVelocityModel model = owner.AddComponent<ConstantVelocityModel>();
                CausalPredictionStrategy strategy = owner.AddComponent<CausalPredictionStrategy>();
                strategy.ResetStrategy();

                Feed(model, strategy, Observation(1, 0.0, 0.0f, 0.0f));
                Feed(model, strategy, Observation(2, 0.1, 0.1f, 10.0f));
                strategy.Output(model, 0.2);
                Feed(model, strategy, Observation(3, 0.2, 0.1f, 10.0f));
                strategy.Output(model, 0.2);

                double finalTime = 0.26;
                double frameInterval = 1.0 / framesPerSecond;
                for (double time = 0.2 + frameInterval; time < finalTime; time += frameInterval)
                {
                    strategy.Output(model, time);
                }

                Pose output = strategy.Output(model, finalTime);
                diagnostics = strategy.Diagnostics;
                return output;
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(owner);
            }
        }

        /// <summary>断言预测 pose 与速度没有 NaN 或无穷值。</summary>
        private static void AssertFinite(Pose pose, MotionModel model)
        {
            Assert.That(IsFinite(pose.position.x) && IsFinite(pose.position.y) && IsFinite(pose.position.z), Is.True);
            Assert.That(IsFinite(pose.rotation.x) && IsFinite(pose.rotation.y) && IsFinite(pose.rotation.z) && IsFinite(pose.rotation.w), Is.True);
            Assert.That(IsFinite(model.LinearVelocity.x) && IsFinite(model.LinearVelocity.y) && IsFinite(model.LinearVelocity.z), Is.True);
            Assert.That(IsFinite(model.AngularVelocityRad.x) && IsFinite(model.AngularVelocityRad.y) && IsFinite(model.AngularVelocityRad.z), Is.True);
        }

        /// <summary>判断单精度数值是否有限。</summary>
        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }

        /// <summary>设置序列化私有字段，复用运行时真实组件组合。</summary>
        private static void SetPrivateField<T>(object instance, string fieldName, T value)
        {
            FieldInfo field = instance.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"找不到字段 {fieldName}");
            field.SetValue(instance, value);
        }

        /// <summary>读取测试所需的私有运行时状态。</summary>
        private static T GetPrivateField<T>(object instance, string fieldName)
        {
            FieldInfo field = instance.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"找不到字段 {fieldName}");
            return (T)field.GetValue(instance);
        }
    }
}
