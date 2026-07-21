using System.Collections.Generic;

namespace EgoAnchor.Eval
{
    /// <summary>schema-v2 session 的固定文件名契约。</summary>
    public static class EvalV2Manifest
    {
        /// <summary>当前正式场景的九路 runtime 矩阵标识；用于阻止新 session 缺失策略候选。</summary>
        public const string VariantMatrixId = "exp12_9_strategy_v1";

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
            EventsFileName,
        };
    }
}
