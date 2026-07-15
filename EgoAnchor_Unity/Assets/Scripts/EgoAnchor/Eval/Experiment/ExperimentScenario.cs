namespace EgoAnchor.Eval.Experiment
{
    /// <summary>一个正式采集任务的稳定标识、显示名和冻结时长范围。</summary>
    public readonly struct ExperimentTask
    {
        /// <summary>所属实验标识。</summary>
        public readonly string ExperimentId;

        /// <summary>场景稳定标识。</summary>
        public readonly string ScenarioId;

        /// <summary>头显面板使用的完整名称。</summary>
        public readonly string DisplayName;

        /// <summary>九宫格使用的短名称。</summary>
        public readonly string ShortName;

        /// <summary>论文协议允许的最短采集秒数。</summary>
        public readonly int MinimumSeconds;

        /// <summary>论文协议建议的最长采集秒数。</summary>
        public readonly int MaximumSeconds;

        /// <summary>构造一个正式采集任务定义。</summary>
        public ExperimentTask(
            string experimentId,
            string scenarioId,
            string displayName,
            string shortName,
            int minimumSeconds = 90,
            int maximumSeconds = 120)
        {
            ExperimentId = experimentId;
            ScenarioId = scenarioId;
            DisplayName = displayName;
            ShortName = shortName;
            MinimumSeconds = minimumSeconds;
            MaximumSeconds = maximumSeconds;
        }
    }

    /// <summary>一个 session 中最终保留的已完成任务摘要。</summary>
    public readonly struct CompletedExperimentTask
    {
        /// <summary>UI 和键盘使用的一基任务编号。</summary>
        public readonly int TaskNumber;

        /// <summary>所属实验标识。</summary>
        public readonly string ExperimentId;

        /// <summary>场景稳定标识。</summary>
        public readonly string ScenarioId;

        /// <summary>最终未作废的 trial 标识。</summary>
        public readonly string TrialId;

        /// <summary>构造一个可写入 manifest 的完成任务摘要。</summary>
        public CompletedExperimentTask(
            int taskNumber,
            string experimentId,
            string scenarioId,
            string trialId)
        {
            TaskNumber = taskNumber;
            ExperimentId = experimentId ?? string.Empty;
            ScenarioId = scenarioId ?? string.Empty;
            TrialId = trialId ?? string.Empty;
        }
    }

    /// <summary>实验一/实验二的九项正式采集任务和论文冻结时长。</summary>
    public static class ExperimentScenario
    {
        /// <summary>九项任务按键盘 1--9 和手柄九宫格顺序排列。</summary>
        public static readonly ExperimentTask[] Tasks =
        {
            new ExperimentTask(
                ExperimentId.SystemCharacterization,
                "static_head_motion",
                "Static target + head motion",
                "HEAD"),
            new ExperimentTask(
                ExperimentId.SystemCharacterization,
                "start_stop_6dof",
                "Start/stop 6DoF",
                "6DOF"),
            new ExperimentTask(
                ExperimentId.SystemCharacterization,
                "continuous_translation",
                "Continuous translation",
                "MOVE"),
            new ExperimentTask(
                ExperimentId.SystemCharacterization,
                "continuous_rotation",
                "Continuous rotation",
                "ROT"),
            new ExperimentTask(
                ExperimentId.SystemCharacterization,
                "occlusion_recovery",
                "Occlusion recovery",
                "OCC"),
            new ExperimentTask(
                ExperimentId.DesignAttribution,
                "without_capture_time_alignment",
                "Ablation: capture-time alignment",
                "ALIGN"),
            new ExperimentTask(
                ExperimentId.DesignAttribution,
                "without_vcd_admission",
                "Ablation: VCD admission",
                "VCD"),
            new ExperimentTask(
                ExperimentId.DesignAttribution,
                "without_temporal_synthesis",
                "Ablation: temporal synthesis",
                "TEMP"),
            new ExperimentTask(
                ExperimentId.DesignAttribution,
                "without_static_lock",
                "Ablation: StaticLock",
                "LOCK"),
        };

        /// <summary>一个完整采集批次需要覆盖的任务总数；单个 session 可只采其中任意子集。</summary>
        public static int PlanCount => Tasks.Length;

        /// <summary>按零基索引读取一项任务。</summary>
        public static bool TryGetTask(int index, out ExperimentTask task)
        {
            if (index >= 0 && index < Tasks.Length)
            {
                task = Tasks[index];
                return true;
            }

            task = default;
            return false;
        }

        /// <summary>按稳定场景标识返回任务索引；未知场景返回 -1。</summary>
        public static int FindTask(string scenarioId)
        {
            for (int index = 0; index < Tasks.Length; index++)
            {
                if (Tasks[index].ScenarioId == scenarioId)
                    return index;
            }

            return -1;
        }

        /// <summary>把场景标识转换为头显面板显示名称。</summary>
        public static string ToDisplayName(string scenarioId)
        {
            int index = FindTask(scenarioId);
            return index >= 0 ? Tasks[index].DisplayName : "NO SCENARIO";
        }
    }
}
