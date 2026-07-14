namespace EgoAnchor.Eval.Experiment
{
    /// <summary>实验一/实验二的稳定标识。</summary>
    public static class ExperimentId
    {
        /// <summary>端到端系统表征实验标识。</summary>
        public const string SystemCharacterization = "exp1_system_characterization";

        /// <summary>系统设计归因实验标识。</summary>
        public const string DesignAttribution = "exp2_design_attribution";

        /// <summary>无选择状态的空标识。</summary>
        public const string None = "";

        /// <summary>把实验标识转换为采集界面显示名称。</summary>
        public static string ToDisplayName(string experimentId)
        {
            switch (experimentId)
            {
                case SystemCharacterization: return "EXP1 | SYSTEM CHARACTERIZATION";
                case DesignAttribution: return "EXP2 | DESIGN ATTRIBUTION";
                default: return "NO EXPERIMENT";
            }
        }
    }
}
