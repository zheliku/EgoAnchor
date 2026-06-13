using System;
using System.Reflection;
using System.Runtime.CompilerServices;
using EgoAnchor.Policy;
using EgoAnchor.Runtime;
using UnityEngine;

static partial class Program
{
    private static void AssertAnchorModulesAreMonoBehaviours()
    {
        foreach (Type type in PolicyModuleTypes())
        {
            Assert(typeof(MonoBehaviour).IsAssignableFrom(type), $"{type.Name} should be a MonoBehaviour module");
        }
    }

    private static void AssertAnchorModulesDoNotExposeModeEnums()
    {
        foreach (Type type in PolicyModuleTypes())
        {
            foreach (Type nested in type.GetNestedTypes(BindingFlags.Public | BindingFlags.NonPublic))
            {
                Assert(!nested.IsEnum || !nested.Name.Contains("Mode", StringComparison.Ordinal), $"{type.Name} should not define nested mode enum {nested.Name}");
            }

            FieldInfo[] fields = type.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
            foreach (FieldInfo field in fields)
            {
                Assert(!field.FieldType.IsEnum || !field.FieldType.Name.Contains("Mode", StringComparison.Ordinal), $"{type.Name}.{field.Name} should not expose mode enum configuration");
            }
        }
    }

    private static void AssertAnchorModulesDoNotExposeCreateFactories()
    {
        foreach (Type type in PolicyModuleTypes())
        {
            MethodInfo[] methods = type.GetMethods(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
            foreach (MethodInfo method in methods)
            {
                Assert(!method.Name.StartsWith("Create", StringComparison.Ordinal), $"{type.Name} should not hide strategy behavior behind factory method {method.Name}");
            }
        }
    }

    private static void AssertAnchorModulesImplementRuntimeMethodsDirectly()
    {
        Assert(typeof(NullGateModule).GetMethod("Evaluate").DeclaringType == typeof(NullGateModule), "NullGateModule should implement Evaluate directly");
        Assert(typeof(ScoreJumpGateModule).GetMethod("Evaluate").DeclaringType == typeof(ScoreJumpGateModule), "ScoreJumpGateModule should implement Evaluate directly");

        Type[] estimators =
        {
            typeof(RawEstimatorModule),
            typeof(LowPassEstimatorModule),
            typeof(KalmanEstimatorModule),
            typeof(OneEuroEstimatorModule),
            typeof(EgoAnchorEstimatorModule),
        };
        foreach (Type type in estimators)
        {
            Assert(type.GetMethod("Snap").DeclaringType == type, $"{type.Name} should implement Snap directly");
            Assert(type.GetMethod("UpdateEstimate").DeclaringType == type, $"{type.Name} should implement UpdateEstimate directly");
            Assert(type.GetMethod("PredictAt").DeclaringType == type, $"{type.Name} should implement PredictAt directly");
        }

        Assert(typeof(PassThroughOutputModule).GetMethod("Condition").DeclaringType == typeof(PassThroughOutputModule), "PassThroughOutputModule should implement Condition directly");
        Assert(typeof(StaticLockRateLimitOutputModule).GetMethod("Condition").DeclaringType == typeof(StaticLockRateLimitOutputModule), "StaticLockRateLimitOutputModule should implement Condition directly");
    }

    private static void AssertAnchorModulesKeepParametersOnMonoBehaviourFields()
    {
        foreach (Type type in PolicyModuleTypes())
        {
            FieldInfo[] fields = type.GetFields(BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.DeclaredOnly);
            foreach (FieldInfo field in fields)
            {
                bool serialized = field.GetCustomAttribute(typeof(SerializeField)) != null;
                if (!serialized)
                {
                    continue;
                }

                Assert(field.DeclaringType == type, $"{type.Name}.{field.Name} should be declared on the concrete MonoBehaviour module");
                Assert(!field.FieldType.Name.Contains("Config", StringComparison.Ordinal), $"{type.Name}.{field.Name} should not wrap parameters in a config object");
            }
        }
    }

    private static void AssertQuaternionLogExpRoundTrips()
    {
        Quaternion rotation = Multiply(YawDegrees(35f), AxisAngle(new Vector3(1f, 0f, 0f), 12f));
        Vector3 tangent = AnchorMath.Log(rotation);
        Quaternion roundTrip = AnchorMath.Exp(tangent);
        Assert(QuaternionAngleDegrees(rotation, roundTrip) < 0.01f, "Quaternion Log/Exp should round-trip a normal rotation");
    }

    private static void AssertQuaternionHemisphereAlignmentUsesShortestArc()
    {
        Quaternion a = YawDegrees(179f);
        Quaternion b = YawDegrees(-179f);
        float shortest = AnchorMath.AngleDegrees(a, b);
        Assert(shortest < 3.0f, $"hemisphere alignment should use shortest arc, got {shortest:F3}deg");
    }

    private static void AssertEstimatorRotationsPredictBetweenSamples()
    {
        AnchorEstimatorModule[] estimators =
        {
            CreateModule<LowPassEstimatorModule>(),
            CreateModule<KalmanEstimatorModule>(),
            CreateModule<OneEuroEstimatorModule>(),
            CreateModule<EgoAnchorEstimatorModule>(),
        };
        foreach (AnchorEstimatorModule estimator in estimators)
        {
            estimator.Snap(MakeTrackObservation(1, new Pose(Vector3.zero, YawDegrees(0f)), 0.0, 1.0f));
            estimator.UpdateEstimate(MakeTrackObservation(2, new Pose(Vector3.zero, YawDegrees(20f)), 0.1, 1.0f));
            AnchorEstimate atMeasurement = estimator.PredictAt(0.1);
            AnchorEstimate ahead = estimator.PredictAt(0.16);
            Assert(QuaternionAngleDegrees(ahead.Pose.rotation, atMeasurement.Pose.rotation) > 0.05f, $"{estimator.ModuleName} should predict rotation between samples");
        }
    }

    private static void AssertNullGateIgnoresScore()
    {
        NullGateModule gate = CreateModule<NullGateModule>();
        Pose pose = new Pose(Vector3.zero, Quaternion.identity);
        AnchorEstimate predicted = AnchorEstimate.Stationary(pose, 0.0);
        GateDecision first = gate.Evaluate(MakeTrackObservation(1, pose, 0.0, 0.0f), predicted, hasEstimate: false);
        GateDecision second = gate.Evaluate(MakeTrackObservation(2, pose, 0.1, 0.0f), predicted, hasEstimate: true);
        Assert(first.Action == GateAction.Snap, "NullGate should snap first pose even at score 0");
        Assert(second.Action == GateAction.Accept, "NullGate should accept tracking pose even at score 0");
    }

    private static void AssertScoreGateRejectsInvalidFlag()
    {
        ScoreJumpGateModule gate = CreateModule<ScoreJumpGateModule>();
        AnchorObservation observation = AnchorObservation.FromAlignedPose(1, Pose.identity, 0.0, 1.0f, new[] { "invalid_pose" }, "TRACK", "TRACK", 0.0);
        GateDecision decision = gate.Evaluate(observation, AnchorEstimate.Stationary(Pose.identity, 0.0), hasEstimate: false);
        Assert(decision.Action == GateAction.Reject, "ScoreJumpGate should reject invalid pose flags");
    }

    private static void AssertScoreGateHoldsLowScore()
    {
        ScoreJumpGateModule gate = CreateModule<ScoreJumpGateModule>();
        AnchorEstimate predicted = AnchorEstimate.Stationary(Pose.identity, 0.0);
        GateDecision decision = gate.Evaluate(MakeTrackObservation(2, Pose.identity, 0.1, 0.15f), predicted, hasEstimate: true);
        Assert(decision.Action == GateAction.Hold, "ScoreJumpGate should hold plausible but low-score tracking measurements");
    }

    private static void AssertScoreGateRejectsAbsoluteJump()
    {
        ScoreJumpGateModule gate = CreateModule<ScoreJumpGateModule>();
        AnchorEstimate predicted = AnchorEstimate.Stationary(Pose.identity, 0.0);
        Pose jumped = new Pose(new Vector3(2.0f, 0.0f, 0.0f), YawDegrees(160f));
        GateDecision decision = gate.Evaluate(MakeTrackObservation(2, jumped, 0.1, 0.9f), predicted, hasEstimate: true);
        Assert(decision.Action == GateAction.Reject, "ScoreJumpGate should reject large translation or rotation jumps");
    }

    private static void AssertAllEstimatorsSnapThenOutputPose()
    {
        Pose pose = new Pose(new Vector3(0.2f, -0.1f, 1.2f), YawDegrees(25f));
        foreach (AnchorEstimatorModule estimator in BaselineAndEgoEstimators())
        {
            estimator.Snap(MakeTrackObservation(1, pose, 0.0, 0.8f));
            AnchorEstimate estimate = estimator.PredictAt(0.0);
            AssertPoseNear(estimate.Pose, pose, 0.001f, 0.1f, $"{estimator.ModuleName} should output snapped pose");
        }
    }

    private static void AssertRawEstimatorIsZeroOrderHold()
    {
        RawEstimatorModule estimator = CreateModule<RawEstimatorModule>();
        Pose first = new Pose(Vector3.zero, Quaternion.identity);
        Pose second = new Pose(new Vector3(0.2f, 0f, 0f), YawDegrees(10f));
        estimator.Snap(MakeTrackObservation(1, first, 0.0, 1.0f));
        estimator.UpdateEstimate(MakeTrackObservation(2, second, 0.1, 1.0f));
        AnchorEstimate ahead = estimator.PredictAt(0.5);
        AssertPoseNear(ahead.Pose, second, 0.0001f, 0.01f, "raw_zoh should hold latest measurement");
    }

    private static void AssertLowPassEstimatorMovesBetweenSamplesWhenPredictionEnabled()
    {
        LowPassEstimatorModule estimator = CreateModule<LowPassEstimatorModule>();
        estimator.Snap(MakeTrackObservation(1, new Pose(Vector3.zero, Quaternion.identity), 0.0, 1.0f));
        estimator.UpdateEstimate(MakeTrackObservation(2, new Pose(new Vector3(0.2f, 0f, 0f), Quaternion.identity), 0.1, 1.0f));
        float atMeasurement = estimator.PredictAt(0.1).Pose.position.x;
        float ahead = estimator.PredictAt(0.16).Pose.position.x;
        Assert(ahead > atMeasurement, "lowpass_predict should move between samples when velocity is known");
    }

    private static void AssertKalmanEstimatorPredictsConstantVelocityBetweenSamples()
    {
        KalmanEstimatorModule estimator = CreateModule<KalmanEstimatorModule>();
        FeedLinearMotion(estimator, score: 1.0f);
        float now = estimator.PredictAt(0.5).Pose.position.x;
        float ahead = estimator.PredictAt(0.58).Pose.position.x;
        Assert(ahead > now, "kalman_cv should predict constant velocity between samples");
    }

    private static void AssertKalmanEstimatorPredictsRotationBetweenSamples()
    {
        KalmanEstimatorModule estimator = CreateModule<KalmanEstimatorModule>();
        FeedYawMotion(estimator, score: 1.0f);
        AnchorEstimate now = estimator.PredictAt(0.5);
        AnchorEstimate ahead = estimator.PredictAt(0.58);
        Assert(QuaternionAngleDegrees(ahead.Pose.rotation, now.Pose.rotation) > 0.05f, "kalman_cv should predict rotation between samples");
    }

    private static void AssertOneEuroEstimatorProducesContinuousRenderOutput()
    {
        OneEuroEstimatorModule estimator = CreateModule<OneEuroEstimatorModule>();
        FeedLinearMotion(estimator, score: 1.0f);
        float now = estimator.PredictAt(0.5).Pose.position.x;
        float ahead = estimator.PredictAt(0.56).Pose.position.x;
        Assert(ahead > now, "oneeuro_vanilla should provide continuous render output");
    }

    private static void AssertOneEuroEstimatorSmoothsRotationWithoutEulerArtifacts()
    {
        OneEuroEstimatorModule estimator = CreateModule<OneEuroEstimatorModule>();
        estimator.Snap(MakeTrackObservation(1, new Pose(Vector3.zero, YawDegrees(179f)), 0.0, 1.0f));
        estimator.UpdateEstimate(MakeTrackObservation(2, new Pose(Vector3.zero, YawDegrees(-179f)), 0.1, 1.0f));
        AnchorEstimate estimate = estimator.PredictAt(0.1);
        float error = Math.Min(
            QuaternionAngleDegrees(estimate.Pose.rotation, YawDegrees(179f)),
            QuaternionAngleDegrees(estimate.Pose.rotation, YawDegrees(-179f))
        );
        Assert(error < 3.0f, $"OneEuro rotation should cross +/-180 by shortest quaternion arc, got error {error:F3}deg");
    }

    private static void AssertEgoAnchorEstimatorModuleDampsPredictionWhenScoreDrops()
    {
        EgoAnchorEstimatorModule high = CreateModule<EgoAnchorEstimatorModule>();
        EgoAnchorEstimatorModule low = CreateModule<EgoAnchorEstimatorModule>();
        FeedLinearMotion(high, score: 1.0f);
        FeedLinearMotion(low, score: 0.0f);
        float highAhead = high.PredictAt(0.58).Pose.position.x;
        float lowAhead = low.PredictAt(0.58).Pose.position.x;
        Assert(highAhead > lowAhead, "EgoAnchor estimator should damp prediction when accepted score is low");
    }

    private static void AssertBaselineEstimatorsIgnoreReliabilityScore()
    {
        Type[] types =
        {
            typeof(RawEstimatorModule),
            typeof(LowPassEstimatorModule),
            typeof(KalmanEstimatorModule),
            typeof(OneEuroEstimatorModule),
        };
        foreach (Type type in types)
        {
            AnchorEstimatorModule high = (AnchorEstimatorModule)CreateModule(type);
            AnchorEstimatorModule low = (AnchorEstimatorModule)CreateModule(type);
            FeedLinearMotion(high, score: 1.0f);
            FeedLinearMotion(low, score: 0.0f);
            AnchorEstimate highEstimate = high.PredictAt(0.58);
            AnchorEstimate lowEstimate = low.PredictAt(0.58);
            AssertPoseNear(highEstimate.Pose, lowEstimate.Pose, 0.0001f, 0.01f, $"{high.ModuleName} baseline should ignore reliability score");
        }
    }

    private static void AssertEstimatorModulesCreateExpectedEstimatorNames()
    {
        Assert(CreateModule<RawEstimatorModule>().ModuleName == "raw_zoh", "RawEstimatorModule label should be raw_zoh");
        Assert(CreateModule<LowPassEstimatorModule>().ModuleName == "lowpass_predict", "LowPassEstimatorModule label should be lowpass_predict");
        Assert(CreateModule<KalmanEstimatorModule>().ModuleName == "kalman_cv", "KalmanEstimatorModule label should be kalman_cv");
        Assert(CreateModule<OneEuroEstimatorModule>().ModuleName == "oneeuro_vanilla", "OneEuroEstimatorModule label should be oneeuro_vanilla");
        Assert(CreateModule<EgoAnchorEstimatorModule>().ModuleName == "egoanchor_estimator", "EgoAnchorEstimatorModule label should be egoanchor_estimator");
    }

    private static void AssertStaticOutputStageLocksSmallResidualSlip()
    {
        StaticLockRateLimitOutputModule output = CreateModule<StaticLockRateLimitOutputModule>();
        Pose basePose = new Pose(Vector3.zero, Quaternion.identity);
        OutputContext context = new OutputContext(0.0, 0.0, 1.0f, AnchorState.Tracking, AnchorMotionState.Static);
        Pose first = output.Condition(new AnchorEstimate(basePose, Vector3.zero, Vector3.zero, 0.0), 0.0, context);
        Pose slipped = output.Condition(new AnchorEstimate(new Pose(new Vector3(0.01f, 0f, 0f), Quaternion.identity), Vector3.zero, Vector3.zero, 0.1), 0.1, context);
        Assert(Vector3.Distance(first.position, slipped.position) < 0.001f, "static output stage should lock small residual slip");
        Assert(output.IsStaticLocked, "static output stage should expose lock diagnostic");
    }

    private static void AssertStaticOutputStageReleasesOnRealMotion()
    {
        StaticLockRateLimitOutputModule output = CreateModule<StaticLockRateLimitOutputModule>();
        OutputContext context = new OutputContext(0.0, 0.0, 1.0f, AnchorState.Tracking, AnchorMotionState.Static);
        output.Condition(new AnchorEstimate(Pose.identity, Vector3.zero, Vector3.zero, 0.0), 0.0, context);
        Pose released = output.Condition(new AnchorEstimate(new Pose(new Vector3(0.08f, 0f, 0f), Quaternion.identity), Vector3.zero, Vector3.zero, 1.0), 1.0, context);
        Assert(released.position.x > 0.04f, "static output stage should release when motion exceeds threshold");
    }

    private static void AssertRateLimitPreventsSingleFrameJump()
    {
        StaticLockRateLimitOutputModule output = CreateModule<StaticLockRateLimitOutputModule>();
        OutputContext moving = new OutputContext(0.0, 0.0, 1.0f, AnchorState.Tracking, AnchorMotionState.Moving);
        output.Condition(new AnchorEstimate(Pose.identity, Vector3.zero, Vector3.zero, 0.0), 0.0, moving);
        Pose limited = output.Condition(new AnchorEstimate(new Pose(new Vector3(10.0f, 0f, 0f), Quaternion.identity), Vector3.zero, Vector3.zero, FrameDt), FrameDt, moving);
        Assert(limited.position.x < 0.1f, "rate limit should prevent a single-frame translation jump");
    }

    private static void AssertPassThroughDoesNotModifyPose()
    {
        PassThroughOutputModule output = CreateModule<PassThroughOutputModule>();
        Pose pose = new Pose(new Vector3(0.2f, 0.3f, 1.0f), YawDegrees(15f));
        OutputContext context = new OutputContext(0.0, 0.0, 1.0f, AnchorState.Tracking, AnchorMotionState.Moving);
        Pose actual = output.Condition(new AnchorEstimate(pose, Vector3.zero, Vector3.zero, 0.0), 0.0, context);
        AssertPoseNear(actual, pose, 0.0001f, 0.01f, "pass-through output should not modify pose");
    }

    private static void AssertPolicyHostMapsGateActionsToPolicyDecision()
    {
        AnchorPolicyHost host = CreatePolicyHost(CreateModule<ScoreJumpGateModule>(), CreateModule<RawEstimatorModule>(), CreateModule<PassThroughOutputModule>());
        AnchorPolicyDecision low = host.AcceptPose(MakeTrackObservation(1, Pose.identity, 0.0, 0.1f));
        Assert(low.Action == AnchorPolicyAction.Reject, "policy host should map gate reject to policy reject");
        AnchorPolicyDecision high = host.AcceptPose(MakeTrackObservation(2, Pose.identity, 0.1, 0.9f));
        Assert(high.Action == AnchorPolicyAction.Snap, "policy host should map first accepted pose to snap");
    }

    private static void AssertPolicyHostAdvancesEveryRenderFrame()
    {
        AnchorPolicyHost host = CreatePolicyHost(CreateModule<NullGateModule>(), CreateModule<LowPassEstimatorModule>(), CreateModule<PassThroughOutputModule>());
        host.AcceptPose(MakeTrackObservation(1, new Pose(Vector3.zero, Quaternion.identity), 0.0, 1.0f));
        host.AcceptPose(MakeTrackObservation(2, new Pose(new Vector3(0.2f, 0f, 0f), Quaternion.identity), 0.1, 1.0f));
        AnchorPolicyOutput a = host.Advance(0.12);
        AnchorPolicyOutput b = host.Advance(0.16);
        Assert(a.HasPose && b.HasPose, "policy host should output a pose each render frame");
        Assert(b.Pose.position.x > a.Pose.position.x, "policy host should advance estimator output each render frame");
    }

    private static void AssertPolicyHostCoastsThenFreezesThenLost()
    {
        AnchorPolicyHost host = CreatePolicyHost(CreateModule<NullGateModule>(), CreateModule<RawEstimatorModule>(), CreateModule<PassThroughOutputModule>());
        host.AcceptPose(MakeTrackObservation(1, Pose.identity, 0.0, 1.0f));
        AnchorPolicyOutput coast = host.Advance(0.2);
        AnchorPolicyOutput frozen = host.Advance(0.8);
        AnchorPolicyOutput lost = host.Advance(2.1);
        Assert(coast.State == AnchorState.Coasting, $"policy host should coast shortly after input stops, got {coast.State}");
        Assert(frozen.State == AnchorState.FrozenUncertain, $"policy host should freeze before lost, got {frozen.State}");
        Assert(lost.State == AnchorState.Lost && !lost.HasPose, "policy host should enter Lost after long input gap");
    }

    private static void AssertPolicyHostRequiresExplicitModules()
    {
        AnchorPolicyHost host = (AnchorPolicyHost)RuntimeHelpers.GetUninitializedObject(typeof(AnchorPolicyHost));
        MakeUnityObjectNonNull(host);
        bool threw = false;
        try
        {
            host.AcceptPose(MakeTrackObservation(1, Pose.identity, 0.0, 1.0f));
        }
        catch (InvalidOperationException)
        {
            threw = true;
        }

        Assert(threw, "policy host should require explicit module references");
    }

    private static void AssertPolicyHostDoesNotUseEnumSelection()
    {
        FieldInfo[] fields = typeof(AnchorPolicyHost).GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        foreach (FieldInfo field in fields)
        {
            bool serialized = field.GetCustomAttribute(typeof(SerializeField)) != null;
            Assert(!serialized || !field.FieldType.IsEnum, $"AnchorPolicyHost should not use serialized enum field selection: {field.Name}");
        }
    }

    private static void AssertPoseToAnchorRuntimeUsesPolicyHostField()
    {
        BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        Assert(typeof(PoseToAnchorRuntime).GetField("policyHost", flags)?.FieldType == typeof(AnchorPolicyHost), "PoseToAnchorRuntime should bind the new AnchorPolicyHost");
    }

    private static void AssertPolicyRuntimeUsesPolicyHostOnly()
    {
        PoseToAnchorRuntime runtime = CreatePoseRuntimeForSmoke();
        AnchorPolicyHost host = CreatePolicyHost(CreateModule<NullGateModule>(), CreateModule<RawEstimatorModule>(), CreateModule<PassThroughOutputModule>());
        BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        typeof(PoseToAnchorRuntime).GetField("policyHost", flags).SetValue(runtime, host);

        Pose pose = new Pose(new Vector3(0.25f, 0.0f, 1.0f), YawDegrees(12f));
        InvokeAlignedWorldPose(runtime, 100, pose, sampleTime: 0.0);
        runtime.AdvanceAnchorOutput(0.05);

        Assert(runtime.TryGetStablePose(out Pose stable), "policy runtime should expose stable pose after Advance");
        AssertPoseNear(stable, pose, 0.0001f, 0.01f, "stable pose should come from AnchorPolicyHost modules");
        Assert(runtime.StrategyLabel == "raw_zoh", "policy runtime should publish strategy label from estimator module");
        Assert(runtime.GateModuleName == "null_gate", "policy runtime should expose gate module metadata");
    }

    private static void AssertDynamicObjectAnchorReadsRuntimeStablePoseOnly()
    {
        BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        Assert(typeof(DynamicObjectAnchor).GetField("outputMode", flags) == null, "DynamicObjectAnchor should not keep an outputMode field");
        Assert(typeof(DynamicObjectAnchor).GetField("runtime", flags)?.FieldType == typeof(PoseToAnchorRuntime), "DynamicObjectAnchor should still read PoseToAnchorRuntime");
    }

    private static void AssertDynamicObjectAnchorHasNoRawSmoothedEnum()
    {
        Assert(typeof(DynamicObjectAnchor).GetNestedType("PoseOutputMode", BindingFlags.Public | BindingFlags.NonPublic) == null, "DynamicObjectAnchor should not expose Raw/Smoothed enum");
        FieldInfo[] fields = typeof(DynamicObjectAnchor).GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        foreach (FieldInfo field in fields)
        {
            Assert(field.FieldType.Name != "PoseOutputMode", "DynamicObjectAnchor should not keep PoseOutputMode fields");
        }
    }

    private static Type[] PolicyModuleTypes()
    {
        return new[]
        {
            typeof(AnchorGateModule),
            typeof(NullGateModule),
            typeof(ScoreJumpGateModule),
            typeof(AnchorEstimatorModule),
            typeof(RawEstimatorModule),
            typeof(LowPassEstimatorModule),
            typeof(KalmanEstimatorModule),
            typeof(OneEuroEstimatorModule),
            typeof(EgoAnchorEstimatorModule),
            typeof(AnchorOutputStageModule),
            typeof(PassThroughOutputModule),
            typeof(StaticLockRateLimitOutputModule),
        };
    }

    private static AnchorEstimatorModule[] BaselineAndEgoEstimators()
    {
        return new AnchorEstimatorModule[]
        {
            CreateModule<RawEstimatorModule>(),
            CreateModule<LowPassEstimatorModule>(),
            CreateModule<KalmanEstimatorModule>(),
            CreateModule<OneEuroEstimatorModule>(),
            CreateModule<EgoAnchorEstimatorModule>(),
        };
    }

    private static T CreateModule<T>() where T : UnityEngine.Object
    {
        return (T)CreateModule(typeof(T));
    }

    private static UnityEngine.Object CreateModule(Type type)
    {
        UnityEngine.Object module = (UnityEngine.Object)RuntimeHelpers.GetUninitializedObject(type);
        MakeUnityObjectNonNull(module);
        if (module is AnchorGateModule gate)
        {
            gate.ResetModule();
        }
        else if (module is AnchorEstimatorModule estimator)
        {
            estimator.ResetModule();
        }
        else if (module is AnchorOutputStageModule output)
        {
            output.ResetModule();
        }

        return module;
    }

    private static AnchorPolicyHost CreatePolicyHost(AnchorGateModule gate, AnchorEstimatorModule estimator, AnchorOutputStageModule output)
    {
        AnchorPolicyHost host = (AnchorPolicyHost)RuntimeHelpers.GetUninitializedObject(typeof(AnchorPolicyHost));
        MakeUnityObjectNonNull(host);
        BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        typeof(AnchorPolicyHost).GetField("gateModule", flags).SetValue(host, gate);
        typeof(AnchorPolicyHost).GetField("estimatorModule", flags).SetValue(host, estimator);
        typeof(AnchorPolicyHost).GetField("outputModule", flags).SetValue(host, output);
        return host;
    }

    private static void FeedLinearMotion(AnchorEstimatorModule estimator, float score)
    {
        for (int i = 0; i <= 5; i++)
        {
            Pose pose = new Pose(new Vector3(i * 0.05f, 0f, 0f), Quaternion.identity);
            AnchorObservation observation = MakeTrackObservation(i + 1, pose, i * 0.1, score);
            if (i == 0)
            {
                estimator.Snap(observation);
            }
            else
            {
                estimator.UpdateEstimate(observation);
            }
        }
    }

    private static void FeedYawMotion(AnchorEstimatorModule estimator, float score)
    {
        for (int i = 0; i <= 5; i++)
        {
            Pose pose = new Pose(Vector3.zero, YawDegrees(i * 8f));
            AnchorObservation observation = MakeTrackObservation(i + 1, pose, i * 0.1, score);
            if (i == 0)
            {
                estimator.Snap(observation);
            }
            else
            {
                estimator.UpdateEstimate(observation);
            }
        }
    }

    private static void AssertPoseNear(Pose actual, Pose expected, float positionToleranceMeters, float rotationToleranceDegrees, string message)
    {
        Assert(Vector3.Distance(actual.position, expected.position) <= positionToleranceMeters, $"{message}: position mismatch {Vector3.Distance(actual.position, expected.position):F6}m");
        Assert(QuaternionAngleDegrees(actual.rotation, expected.rotation) <= rotationToleranceDegrees, $"{message}: rotation mismatch {QuaternionAngleDegrees(actual.rotation, expected.rotation):F6}deg");
    }
}
