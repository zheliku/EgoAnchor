"""Task 11 Stage 2 paper CSV 补全测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from egoanchor.eval import build_paper_rows


def _summary(
    scenario: str,
    variant: str,
    metric: str,
    value: float,
    unit: str,
) -> SimpleNamespace:
    """创建最小实验一场景汇总行。"""

    return SimpleNamespace(
        experiment_id="exp1_system_characterization",
        scenario_id=scenario,
        variant_id=variant,
        metric_key=metric,
        metric_value=value,
        metric_unit=unit,
        median=value,
        q1=value - 1.0,
        q3=value + 1.0,
        sample_count=4,
        input_workbook_sha256="a" * 64,
    )


class PaperRowsTests(unittest.TestCase):
    """验证 Stage 2 向 Task 11 提供完整、纯字母宏和两实验表格。"""

    def test_builds_counts_metrics_and_both_experiment_tables(self) -> None:
        """计数、实验一主指标、实验二配对和 VCD AURC 必须全部进入 paper CSV。"""

        variants = ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", "EgoAnchor")
        scenarios = {
            "static_head_motion": (
                ("position_hp_rms_mm", "mm"),
                ("centered_translation_pninetyfive_mm", "mm"),
                ("translation_event_pninetyfive_mm", "mm"),
            ),
            "start_stop_6dof": (
                ("visible_response_ms", "ms"),
                ("motion_translation_pninetyfive_mm", "mm"),
            ),
            "continuous_translation": (
                ("effective_translation_lag_ms", "ms"),
                ("translation_event_pninetyfive_mm_continuous", "mm"),
                ("translation_lag_residual_mm", "mm"),
            ),
            "continuous_rotation": (
                ("effective_angular_lag_ms", "ms"),
                ("rotation_event_pninetyfive_deg_continuous", "deg"),
                ("angular_lag_pninetyfive_residual_deg", "deg"),
            ),
            "occlusion_recovery": (
                ("occlusion_translation_pninetyfive_mm", "mm"),
                ("durable_recovery_time_ms", "ms"),
            ),
        }
        trials = tuple(
            SimpleNamespace(
                session_id=f"s{index}",
                scenario_id=scenario,
                workbook_sha256="a" * 64,
            )
            for index, scenario in enumerate(scenarios, 1)
        )
        exp1 = SimpleNamespace(
            scenario_summary=tuple(
                _summary(scenario, variant, metric, 10.123456 + index, unit)
                for scenario, metrics in scenarios.items()
                for metric, unit in metrics
                for index, variant in enumerate(variants)
            )
        )
        component_metrics = {
            "capture_time_alignment": (
                "static_head_motion",
                "EgoAnchor w/o capture-time alignment",
                (("capture_alignment_raw_translation_pninetyfive_mm", "mm"), ("capture_alignment_raw_rotation_pninetyfive_deg", "deg")),
            ),
            "vcd_admission": (
                "occlusion_recovery",
                "EgoAnchor w/o VCD",
                (("occlusion_translation_pninetyfive_mm", "mm"), ("occlusion_catastrophic_failure_rate", "proportion")),
            ),
            "temporal_synthesis": (
                "continuous_translation",
                "EgoAnchor w/o temporal synthesis",
                (("translation_lag_residual_mm", "mm"), ("effective_translation_lag_ms", "ms")),
            ),
            "static_lock": (
                "static_head_motion",
                "EgoAnchor w/o StaticLock",
                (("centered_translation_pninetyfive_mm", "mm"), ("jump_pninetyfive_mm", "mm")),
            ),
        }
        paired_rows = tuple(
            SimpleNamespace(
                experiment_id="exp2_design_attribution",
                scenario_id=scenario,
                component_id=component,
                ablation_variant_id=ablation,
                metric_key=metric,
                metric_unit=unit,
                sample_count=4,
                median=2.0,
                q1=1.0,
                q3=3.0,
                full_median=10.0,
                full_q1=9.0,
                full_q3=11.0,
                ablation_median=12.0,
                ablation_q1=11.0,
                ablation_q3=13.0,
                positive_count=3,
                zero_count=1,
                negative_count=0,
                input_workbook_sha256="a" * 64,
            )
            for component, (scenario, ablation, metrics) in component_metrics.items()
            for metric, unit in metrics
        )
        exp2 = SimpleNamespace(
            components=SimpleNamespace(paired_summary=paired_rows),
            vcd=SimpleNamespace(
                operating_coverage=0.75,
                operating_tail_risk_mm=8.5,
                operating_accepted_count=9,
                operating_eligible_count=12,
                aurc=(
                    SimpleNamespace(
                        reference_kind="vcd",
                        risk_kind="mean",
                        aurc_mm=2.3,
                        candidate_count=12,
                        input_workbook_sha256="a" * 64,
                    ),
                    SimpleNamespace(
                        reference_kind="random",
                        risk_kind="mean",
                        aurc_mm=4.1,
                        candidate_count=12,
                        input_workbook_sha256="a" * 64,
                    ),
                )
            ),
        )
        result = build_paper_rows(trials, exp1, exp2)
        names = {str(row["macro_name"]) for row in result.numbers}
        self.assertIn("SessionCount", names)
        self.assertIn("EgoAnchorStaticHeadMotionTranslationEventPNinetyFiveMm", names)
        self.assertIn("CaptureTimeAlignmentCaptureAlignmentRawTranslationPNinetyFiveMmDeltaMedian", names)
        self.assertIn("TemporalSynthesisTranslationLagResidualMmDeltaMedian", names)
        self.assertIn("TemporalSynthesisTranslationLagResidualMmPositiveCount", names)
        self.assertIn("VcdMeanRiskAurcMm", names)
        operating = next(
            row
            for row in result.numbers
            if row["macro_name"] == "ActualAdmittedCoveragePct"
        )
        self.assertEqual(operating["source_csv"], "plots/exp2_vcd_curve.csv")
        self.assertTrue(all(name.isascii() and name.isalpha() for name in names))
        formatted_number = next(
            row
            for row in result.numbers
            if row["macro_name"]
            == "EgoAnchorStaticHeadMotionTranslationEventPNinetyFiveMm"
        )
        self.assertEqual(formatted_number["value"], "13.1")
        exp2_session = next(
            row
            for row in result.numbers
            if row["experiment"] == "exp2_design_attribution"
            and row["macro_name"] == "SessionCount"
        )
        self.assertEqual(exp2_session["value"], 3)
        experiments = {str(row["experiment"]) for row in result.tables}
        self.assertEqual(
            experiments,
            {"exp1_system_characterization", "exp2_design_attribution"},
        )
        exp1_cells = [row for row in result.tables if row["experiment"] == "exp1_system_characterization"]
        exp2_cells = [row for row in result.tables if row["experiment"] == "exp2_design_attribution"]
        self.assertEqual(len(exp1_cells), 20)
        self.assertEqual(len(exp2_cells), 16)
        self.assertEqual(
            {row["column_key"] for row in exp2_cells},
            {"对应系统行为", "Full EgoAnchor", "关闭后的效应", "护栏 / 解释"},
        )
        hold_cell = next(
            row
            for row in exp2_cells
            if row["row_key"] == "时序合成" and row["column_key"] == "Full EgoAnchor"
        )
        self.assertIn("mm", hold_cell["display_value"])
        hold_delta = next(
            row
            for row in exp2_cells
            if row["row_key"] == "时序合成" and row["column_key"] == "关闭后的效应"
        )
        self.assertIn("mm", hold_delta["display_value"])
        self.assertEqual(
            {row["row_key"] for row in exp1_cells},
            {
                "Arrival-Hold",
                "Capture-Hold",
                "One-Euro Anchor",
                "EgoAnchor",
            },
        )
        self.assertEqual(
            {row["column_key"] for row in exp1_cells},
            {
                "中心化波动 P95 (mm)",
                "HP--RMS (mm)",
                "Lag / aligned RMSE (ms / mm)",
                "遮挡窗 P95 (mm)",
                "Start-transition (ms)",
            },
        )
        self.assertEqual(
            {row["row_key"] for row in exp2_cells},
            {
                "采集时刻对齐",
                "VCD 接纳",
                "时序合成",
                "StaticLock",
            },
        )
        formatted_cell = next(
            row
            for row in exp1_cells
            if row["row_key"] == "EgoAnchor"
            and row["column_key"] == "中心化波动 P95 (mm)"
        )
        self.assertIn("13.1", formatted_cell["display_value"])
        with self.assertRaisesRegex(ValueError, "主指标缺失"):
            build_paper_rows(
                trials,
                SimpleNamespace(
                    scenario_summary=tuple(
                        row
                        for row in exp1.scenario_summary
                        if not (
                            row.scenario_id == "occlusion_recovery"
                            and row.variant_id == "EgoAnchor"
                            and row.metric_key == "occlusion_translation_pninetyfive_mm"
                        )
                    )
                ),
                exp2,
            )
        with self.assertRaisesRegex(ValueError, "VCD/random"):
            build_paper_rows(
                trials,
                exp1,
                SimpleNamespace(
                    components=exp2.components,
                    vcd=SimpleNamespace(aurc=exp2.vcd.aurc[:1]),
                ),
            )


if __name__ == "__main__":
    unittest.main()
