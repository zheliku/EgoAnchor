using System;

namespace EgoAnchor.Eval.Experiment
{
    /// <summary>实验一/实验二的场景和归因组件稳定标识。</summary>
    public static class ExperimentScenario
    {
        /// <summary>实验一场景集合，顺序对应数字键 1 至 5。</summary>
        public static readonly string[] SystemScenarios =
        {
            "static_head_motion",
            "start_stop_6dof",
            "continuous_translation",
            "continuous_rotation",
            "occlusion_recovery",
        };

        /// <summary>实验二归因场景集合，顺序对应 Shift+数字键 1 至 4。</summary>
        public static readonly string[] AttributionScenarios =
        {
            "without_capture_time_alignment",
            "without_vcd_admission",
            "without_temporal_synthesis",
            "without_static_lock",
        };

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

        /// <summary>获取指定数字键对应的实验一场景；非法键返回空值。</summary>
        public static string GetSystemScenario(int key)
        {
            return key >= 1 && key <= SystemScenarios.Length ? SystemScenarios[key - 1] : string.Empty;
        }

        /// <summary>获取指定数字键对应的实验二归因场景；非法键返回空值。</summary>
        public static string GetAttributionScenario(int key)
        {
            return key >= 1 && key <= AttributionScenarios.Length ? AttributionScenarios[key - 1] : string.Empty;
        }

        /// <summary>判断场景标识是否属于当前实验计划。</summary>
        public static bool IsKnown(string scenarioId)
        {
            return Array.IndexOf(SystemScenarios, scenarioId) >= 0
                || Array.IndexOf(AttributionScenarios, scenarioId) >= 0;
        }
    }
}
