using System;
using System.IO;
using System.Reflection;
using EgoAnchor.QualitativeReplay;
using NUnit.Framework;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace EgoAnchor.Tests.EditMode
{
    /// <summary>定性 replay 的坐标、标定和专用场景契约测试。</summary>
    public sealed class ReplayCaptureTests
    {
        /// <summary>Unity y-up 到 OpenCV y-down 应同时变换平移和旋转基。</summary>
        [Test]
        public void ProjectionMatrixFlipsUnityCameraY()
        {
            Pose camera = Pose.identity;
            Pose display = new Pose(new Vector3(1f, 2f, 3f), Quaternion.identity);

            float[] matrix = ReplayCaptureGeometry.ToOpenCvObjectMatrix(camera, display);

            Assert.That(matrix, Has.Length.EqualTo(16));
            Assert.That(matrix[3], Is.EqualTo(1f).Within(1e-6f));
            Assert.That(matrix[7], Is.EqualTo(-2f).Within(1e-6f));
            Assert.That(matrix[11], Is.EqualTo(3f).Within(1e-6f));
            Assert.That(matrix[0], Is.EqualTo(1f).Within(1e-6f));
            Assert.That(matrix[5], Is.EqualTo(1f).Within(1e-6f));
            Assert.That(matrix[10], Is.EqualTo(1f).Within(1e-6f));
            Assert.That(matrix[15], Is.EqualTo(1f).Within(1e-6f));
        }

        /// <summary>camera world pose 必须先求逆，不能把 world translation 当 camera-local translation。</summary>
        [Test]
        public void ProjectionMatrixUsesCameraRelativePose()
        {
            Pose camera = new Pose(new Vector3(10f, 0f, 0f), Quaternion.identity);
            Pose display = new Pose(new Vector3(11f, 0f, 2f), Quaternion.identity);

            float[] matrix = ReplayCaptureGeometry.ToOpenCvObjectMatrix(camera, display);

            Assert.That(matrix[3], Is.EqualTo(1f).Within(1e-6f));
            Assert.That(matrix[7], Is.EqualTo(0f).Within(1e-6f));
            Assert.That(matrix[11], Is.EqualTo(2f).Within(1e-6f));
        }

        /// <summary>同宽高比缩放应与 Python QuestStereoCalibration.scaled_k 一致。</summary>
        [Test]
        public void ScaledIntrinsicsPreserveSameAspectRatio()
        {
            ReplayCaptureRecorder.ComputeScaledIntrinsics(
                2000.0, 2100.0, 2000.0, 1500.0,
                4000, 3000, 640, 480,
                out double fx, out double fy, out double cx, out double cy);

            Assert.That(fx, Is.EqualTo(320.0).Within(1e-9));
            Assert.That(fy, Is.EqualTo(336.0).Within(1e-9));
            Assert.That(cx, Is.EqualTo(320.0).Within(1e-9));
            Assert.That(cy, Is.EqualTo(240.0).Within(1e-9));
        }

        /// <summary>宽屏输出应先中心裁掉传感器上下区域，再缩放主点。</summary>
        [Test]
        public void ScaledIntrinsicsApplyCenterCrop()
        {
            ReplayCaptureRecorder.ComputeScaledIntrinsics(
                2000.0, 2000.0, 2000.0, 1500.0,
                4000, 3000, 640, 360,
                out double fx, out double fy, out double cx, out double cy);

            Assert.That(fx, Is.EqualTo(320.0).Within(1e-9));
            Assert.That(fy, Is.EqualTo(320.0).Within(1e-9));
            Assert.That(cx, Is.EqualTo(320.0).Within(1e-9));
            Assert.That(cy, Is.EqualTo(180.0).Within(1e-9));
        }

        /// <summary>Quest Link 默认输出必须直接落到仓库 Python 本地数据目录。</summary>
        [Test]
        public void DefaultOutputRootUsesRepositoryPythonDataDirectory()
        {
            string assets = Path.Combine("P:\\", "repo", "EgoAnchor_Unity", "Assets");

            string output = ReplayCaptureRecorder.ResolveDefaultEditorOutputRoot(assets);

            Assert.That(
                output.Replace('\\', '/'),
                Does.EndWith("/repo/EgoAnchor_Python/data/replay_capture"));
        }

        /// <summary>记录器必须晚于 DynamicObjectAnchor 的默认 order 0 执行。</summary>
        [Test]
        public void RecorderRunsAfterDisplayPresenter()
        {
            DefaultExecutionOrder attribute = (DefaultExecutionOrder)Attribute.GetCustomAttribute(
                typeof(ReplayCaptureRecorder),
                typeof(DefaultExecutionOrder));

            Assert.That(attribute, Is.Not.Null);
            Assert.That(attribute.order, Is.GreaterThan(0));
        }

        /// <summary>后台 writer 停止时必须排空队列，并让 JPEG 行与 JSONL 行一一对应。</summary>
        [Test]
        public void WriterDrainsQueuedSamplesBeforeStopping()
        {
            string directory = Path.Combine(
                Application.temporaryCachePath,
                "egoanchor-replay-writer-" + Guid.NewGuid().ToString("N"));
            try
            {
                using (var writer = new ReplayCaptureWriter(directory, capacity: 4))
                {
                    Assert.That(
                        writer.TryEnqueue(ReplayWriteItem.FromBytes(
                            new byte[] { 1, 2, 3 },
                            "images/000000001.jpg",
                            "{\"sample_id\":\"000000001\"}")),
                        Is.True);
                    Assert.That(
                        writer.TryEnqueue(ReplayWriteItem.FromBytes(
                            new byte[] { 4, 5 },
                            "images/000000002.jpg",
                            "{\"sample_id\":\"000000002\"}")),
                        Is.True);
                    writer.CompleteAndWait();

                    ReplayWriterStats stats = writer.Stats;
                    Assert.That(stats.SamplesWritten, Is.EqualTo(2));
                    Assert.That(stats.QueueDropped, Is.Zero);
                    Assert.That(stats.WriteFailures, Is.Zero);
                    Assert.That(stats.ImageBytesWritten, Is.EqualTo(5));
                }

                Assert.That(File.ReadAllLines(Path.Combine(directory, "samples.jsonl")), Has.Length.EqualTo(2));
                Assert.That(File.Exists(Path.Combine(directory, "images", "000000001.jpg")), Is.True);
                Assert.That(File.Exists(Path.Combine(directory, "images", "000000002.jpg")), Is.True);
            }
            finally
            {
                if (Directory.Exists(directory))
                {
                    Directory.Delete(directory, recursive: true);
                }
            }
        }

        /// <summary>writer 必须拒绝逃逸 capture 目录的相对图像路径。</summary>
        [Test]
        public void WriterRejectsEscapedImagePath()
        {
            string directory = Path.Combine(
                Application.temporaryCachePath,
                "egoanchor-replay-boundary-" + Guid.NewGuid().ToString("N"));
            string escapedName = Path.GetFileName(directory) + ".jpg";
            try
            {
                using (var writer = new ReplayCaptureWriter(directory, capacity: 1))
                {
                    Assert.That(
                        writer.TryEnqueue(ReplayWriteItem.FromBytes(
                            new byte[] { 1 },
                            "../" + escapedName,
                            "{}")),
                        Is.True);
                    writer.CompleteAndWait();

                    Assert.That(writer.Stats.SamplesWritten, Is.Zero);
                    Assert.That(writer.Stats.WriteFailures, Is.EqualTo(1));
                }
                Assert.That(
                    File.Exists(Path.Combine(Path.GetDirectoryName(directory) ?? string.Empty, escapedName)),
                    Is.False);
            }
            finally
            {
                if (Directory.Exists(directory))
                {
                    Directory.Delete(directory, recursive: true);
                }
            }
        }

        /// <summary>专用场景不得重新挂回正式 EvalRecorder 或实验二 runtime。</summary>
        [Test]
        public void DedicatedSceneContainsOnlyReplayCaptureWorkflow()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-ReplayCapture.unity");
            string yaml = File.ReadAllText(path);

            StringAssert.Contains("m_Name: ReplayCapture", yaml);
            StringAssert.Contains(
                "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.QualitativeReplay.ReplayCaptureRecorder",
                yaml);
            StringAssert.DoesNotContain(
                "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.EvalRecorder",
                yaml);
            StringAssert.DoesNotContain("m_Name: Experiment 2 - Design Attribution", yaml);
            StringAssert.Contains("captureFps: 0", yaml);
            StringAssert.DoesNotContain("platformReference: {fileID: 0}", yaml);
        }

        /// <summary>专用场景四路 runtime/presenter 必须唯一、配对且符合冻结方法组合。</summary>
        [Test]
        public void DedicatedSceneBindingsMatchFourExperimentOneMethods()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-ReplayCapture.unity");
            Scene scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Additive);
            try
            {
                ReplayCaptureRecorder recorder = null;
                foreach (GameObject root in scene.GetRootGameObjects())
                {
                    recorder = root.GetComponentInChildren<ReplayCaptureRecorder>(includeInactive: true);
                    if (recorder != null)
                    {
                        break;
                    }
                }
                Assert.That(recorder, Is.Not.Null);
                MethodInfo validate = typeof(ReplayCaptureRecorder).GetMethod(
                    "ValidateBindings",
                    BindingFlags.Instance | BindingFlags.NonPublic);
                Assert.That(validate, Is.Not.Null);
                object[] arguments = { null };
                bool valid = (bool)validate.Invoke(recorder, arguments);
                Assert.That(valid, Is.True, arguments[0] as string);
            }
            finally
            {
                EditorSceneManager.CloseScene(scene, removeScene: true);
            }
        }
    }
}
