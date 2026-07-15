namespace EgoAnchor.Eval.Experiment
{
    /// <summary>实验一/实验二的场景和固定采集顺序。</summary>
    public static class ExperimentScenario
    {
        /// <summary>实验一场景集合，按正式采集顺序排列。</summary>
        public static readonly string[] SystemScenarios =
        {
            "static_head_motion",
            "start_stop_6dof",
            "continuous_translation",
            "continuous_rotation",
            "occlusion_recovery",
        };

        /// <summary>实验二归因场景集合，紧接实验一执行。</summary>
        public static readonly string[] AttributionScenarios =
        {
            "without_capture_time_alignment",
            "without_vcd_admission",
            "without_temporal_synthesis",
            "without_static_lock",
        };

        /// <summary>一次正式 session 需要完成的场景总数。</summary>
        public static int PlanCount => SystemScenarios.Length + AttributionScenarios.Length;

        /// <summary>按零基索引读取固定采集计划中的实验和场景。</summary>
        public static bool TryGetPlanItem(int index, out string experimentId, out string scenarioId)
        {
            if (index >= 0 && index < SystemScenarios.Length)
            {
                experimentId = ExperimentId.SystemCharacterization;
                scenarioId = SystemScenarios[index];
                return true;
            }

            int attributionIndex = index - SystemScenarios.Length;
            if (attributionIndex >= 0 && attributionIndex < AttributionScenarios.Length)
            {
                experimentId = ExperimentId.DesignAttribution;
                scenarioId = AttributionScenarios[attributionIndex];
                return true;
            }

            experimentId = ExperimentId.None;
            scenarioId = string.Empty;
            return false;
        }

        /// <summary>把场景标识转换为采集界面显示名称。</summary>
        public static string ToDisplayName(string scenarioId)
        {
            switch (scenarioId)
            {
                case "static_head_motion": return "Static target + head motion";
                case "start_stop_6dof": return "Start/stop 6DoF";
                case "continuous_translation": return "Continuous translation";
                case "continuous_rotation": return "Continuous rotation";
                case "occlusion_recovery": return "Occlusion recovery";
                case "without_capture_time_alignment": return "Ablation: capture-time alignment";
                case "without_vcd_admission": return "Ablation: VCD admission";
                case "without_temporal_synthesis": return "Ablation: temporal synthesis";
                case "without_static_lock": return "Ablation: StaticLock";
                default: return "NO SCENARIO";
            }
        }
    }
}
