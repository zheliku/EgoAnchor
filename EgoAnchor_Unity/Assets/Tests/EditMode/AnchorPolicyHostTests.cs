using System;
using System.Reflection;
using EgoAnchor.Policy;
using EgoAnchor.Protocol.Generated;
using NUnit.Framework;
using UnityEngine;

namespace EgoAnchor.Tests
{
    /// <summary>
    /// AnchorPolicyHost 生命周期测试，覆盖采集时刻与到达时刻分离后的重定位边界。
    /// </summary>
    public sealed class AnchorPolicyHostTests
    {
        /// <summary>
        /// 高分 register pose 即使推理延迟较大，也不能在到达后一帧立刻被生命周期判 Lost 并请求 server reacquire。
        /// </summary>
        [Test]
        public void HighScoreDelayedRegisterDoesNotImmediatelyRequestServerReacquire()
        {
            GameObject go = new GameObject("AnchorPolicyHostTests");
            try
            {
                AnchorPolicyHost host = go.AddComponent<AnchorPolicyHost>();
                ConstantVelocityModel model = go.AddComponent<ConstantVelocityModel>();
                RawPassthroughStrategy smoothing = go.AddComponent<RawPassthroughStrategy>();
                SetPrivateField(host, "motionModel", model);
                SetPrivateField(host, "smoothingStrategy", smoothing);

                AnchorObservation observation = AnchorObservation.FromAlignedPose(
                    frameId: 42,
                    worldPose: new Pose(new Vector3(0.1f, 0.2f, 0.3f), Quaternion.identity),
                    sampleTimeSeconds: 10.0,
                    reliabilityScore: 1.0f,
                    reliabilityFlags: new[] { "quality_pending" },
                    phase: "REGISTER",
                    poseSource: "REGISTER",
                    captureTimeSeconds: 7.0);

                host.AcceptPose(observation);
                AnchorPolicyOutput output = host.Advance(10.1);

                Assert.That(output.State, Is.Not.EqualTo(AnchorState.Lost));
                Assert.That(host.ConsumeServerReacquireRequest(), Is.False);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>
        /// Python 合并状态 valid_no_valid_depth_overlap 表示颜色有效但深度无交集；Unity 几何仲裁也必须排除 D 项。
        /// </summary>
        [Test]
        public void MapperExcludesMergedInvalidDepthStatusFromGeometryEvidence()
        {
            PoseResult result = new PoseResult
            {
                ReliabilityScore = 0.4f,
                ScoreDepth = 0.0f,
                ScoreReprojection = 1.0f,
                ColorReprojection = -1.0f,
                DepthValidInMask = 1.0f,
                RenderQualityStatus = "valid_no_valid_depth_overlap",
                RenderQualityDepthAlignment = 0.0f,
                RenderQualityDepthInlier = 0.0f,
                RenderQualityDepthResidualM = 0.0f,
            };

            AnchorObservation observation = InvokePolicyMapper(result);

            Assert.That(observation.DepthValid, Is.False);
            Assert.That(observation.GeometryScore(0.2f, 0.8f, out bool hasEvidence), Is.EqualTo(1.0f));
            Assert.That(hasEvidence, Is.False);
        }

        /// <summary>
        /// 反射设置 MonoBehaviour 私有序列化字段，避免测试依赖场景 YAML。
        /// </summary>
        private static void SetPrivateField<T>(object instance, string fieldName, T value)
        {
            FieldInfo field = instance.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"missing field {fieldName}");
            field.SetValue(instance, value);
        }

        /// <summary>
        /// 通过反射调用 internal mapper，避免为了测试扩大运行时代码可见性。
        /// </summary>
        private static AnchorObservation InvokePolicyMapper(PoseResult result)
        {
            Type mapperType = typeof(AnchorObservation).Assembly.GetType("EgoAnchor.Runtime.PoseResultPolicyMapper");
            Assert.That(mapperType, Is.Not.Null, "missing PoseResultPolicyMapper");
            MethodInfo method = mapperType.GetMethod("FromAlignedPose", BindingFlags.Public | BindingFlags.Static);
            Assert.That(method, Is.Not.Null, "missing FromAlignedPose");

            object[] args =
            {
                42L,
                new Pose(Vector3.zero, Quaternion.identity),
                10.0,
                7.0,
                result,
                "TRACK",
                false,
                default(Pose),
            };
            return (AnchorObservation)method.Invoke(null, args);
        }
    }
}
