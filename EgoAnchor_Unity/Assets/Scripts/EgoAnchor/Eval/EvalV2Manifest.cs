using System.Collections.Generic;

namespace EgoAnchor.Eval
{
    /// <summary>schema-v2 session 的固定文件名契约。</summary>
    public static class EvalV2Manifest
    {
        /// <summary>当前正式场景的九路 runtime 矩阵标识。</summary>
        public const string VariantMatrixId = "exp12_9_smoothed_hermite_v4";

        /// <summary>正式九路场景名；只有该场景执行严格矩阵启动门禁。</summary>
        public const string FormalSceneName = "EgoAnchor-Experiment12";

        /// <summary>平滑 Kalman 外推变体的稳定日志标签。</summary>
        public const string SmoothedExtrapolationVariantLabel = "Smoothed KF Extrapolation";

        /// <summary>Hermite 插值变体的稳定日志标签。</summary>
        public const string HermiteInterpolationVariantLabel = "Hermite Interpolation";

        /// <summary>正式变体的结构语义契约，不包含 pilot 尚未冻结的数值参数。</summary>
        public readonly struct FormalVariantContract
        {
            /// <summary>变体日志标签。</summary>
            public readonly string Label;
            /// <summary>运动模型名称。</summary>
            public readonly string MotionModel;
            /// <summary>逐帧输出策略名称。</summary>
            public readonly string SmoothingStrategy;
            /// <summary>质量接纳门控状态。</summary>
            public readonly string QualityGate;
            /// <summary>世界复合时间模式。</summary>
            public readonly string WorldAlignmentMode;
            /// <summary>是否使用采集时刻对齐。</summary>
            public readonly bool UsesCaptureTimeAlignment;
            /// <summary>是否使用 VCD 接纳。</summary>
            public readonly bool UsesVcdAdmission;
            /// <summary>是否使用连续时序合成。</summary>
            public readonly bool UsesTemporalSynthesis;
            /// <summary>是否使用 StaticLock。</summary>
            public readonly bool UsesStaticLock;
            /// <summary>是否启用低分重获取。</summary>
            public readonly bool UsesLowScoreReacquire;
            /// <summary>是否启用服务器重获取。</summary>
            public readonly bool UsesServerReacquire;

            /// <summary>创建一条正式变体结构契约。</summary>
            public FormalVariantContract(
                string label,
                string motionModel,
                string smoothingStrategy,
                string qualityGate,
                string worldAlignmentMode,
                bool usesCaptureTimeAlignment,
                bool usesVcdAdmission,
                bool usesTemporalSynthesis,
                bool usesStaticLock,
                bool usesLowScoreReacquire,
                bool usesServerReacquire)
            {
                Label = label;
                MotionModel = motionModel;
                SmoothingStrategy = smoothingStrategy;
                QualityGate = qualityGate;
                WorldAlignmentMode = worldAlignmentMode;
                UsesCaptureTimeAlignment = usesCaptureTimeAlignment;
                UsesVcdAdmission = usesVcdAdmission;
                UsesTemporalSynthesis = usesTemporalSynthesis;
                UsesStaticLock = usesStaticLock;
                UsesLowScoreReacquire = usesLowScoreReacquire;
                UsesServerReacquire = usesServerReacquire;
            }
        }

        /// <summary>按 Experiment12 Inspector 顺序冻结的九路结构契约。</summary>
        public static IReadOnlyList<FormalVariantContract> FormalVariantContracts { get; } = new[]
        {
            new FormalVariantContract("Arrival-Hold", "cv", "hold", "disabled", "ArrivalTime", false, false, false, false, false, false),
            new FormalVariantContract("Capture-Hold", "cv", "hold", "disabled", "CaptureTime", true, false, false, false, false, false),
            new FormalVariantContract("One-Euro Anchor", "oneeuro", "linear_slerp", "enabled", "CaptureTime", true, true, true, false, true, true),
            new FormalVariantContract("EgoAnchor", "kalman", "linear_slerp", "enabled", "CaptureTime", true, true, true, true, true, true),
            new FormalVariantContract("EgoAnchor w/o capture-time alignment", "kalman", "linear_slerp", "enabled", "ArrivalTime", false, true, true, true, true, true),
            new FormalVariantContract("EgoAnchor w/o VCD", "kalman", "linear_slerp", "disabled", "CaptureTime", true, false, true, true, false, true),
            new FormalVariantContract(SmoothedExtrapolationVariantLabel, "kalman", "smoothed_kf_extrapolation", "enabled", "CaptureTime", true, true, true, false, true, true),
            new FormalVariantContract("EgoAnchor w/o StaticLock", "kalman", "linear_slerp", "enabled", "CaptureTime", true, true, true, false, true, true),
            new FormalVariantContract(HermiteInterpolationVariantLabel, "kalman", "hermite_interpolation", "enabled", "CaptureTime", true, true, true, false, true, true),
        };

        /// <summary>会话元数据文件名。</summary>
        public const string ManifestFileName = "manifest.json";

        /// <summary>Python candidate 日志文件名。</summary>
        public const string PythonCandidatesFileName = "python_candidates.jsonl";

        /// <summary>Unity 平台参考日志文件名。</summary>
        public const string UnityReferenceFileName = "unity_reference.jsonl";

        /// <summary>Unity admission 长表文件名。</summary>
        public const string UnityAdmissionFileName = "unity_admission.jsonl";

        /// <summary>Unity render 长表文件名。</summary>
        public const string UnityRenderFileName = "unity_render.jsonl";

        /// <summary>Unity session 与实验事件分片文件名；由本机独占写入。</summary>
        public const string UnityEventsFileName = "unity_events.jsonl";

        /// <summary>session 边界与运行事件文件名。</summary>
        public const string EventsFileName = "events.jsonl";

        /// <summary>manifest 中必须声明的固定日志文件名集合。</summary>
        public static IReadOnlyList<string> FixedLogFileNames { get; } = new[]
        {
            PythonCandidatesFileName,
            UnityReferenceFileName,
            UnityAdmissionFileName,
            UnityRenderFileName,
            UnityEventsFileName,
            EventsFileName,
        };
    }
}
