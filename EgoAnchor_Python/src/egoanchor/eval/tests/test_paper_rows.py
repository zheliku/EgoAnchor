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
                ("translation_event_pninetyfive_mm", "mm"),
            ),
            "start_stop_6dof": (
                ("visible_response_ms", "ms"),
                ("motion_translation_pninetyfive_mm", "mm"),
            ),
            "continuous_translation": (
                ("effective_translation_lag_ms", "ms"),
                ("translation_event_pninetyfive_mm_continuous", "mm"),
                ("translation_lag_pninetyfive_residual_mm", "mm"),
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
                (("translation_event_pninetyfive_mm", "mm"), ("rotation_event_pninetyfive_deg", "deg")),
            ),
            "vcd_admission": (
                "occlusion_recovery",
                "EgoAnchor w/o VCD",
                (("occlusion_translation_pninetyfive_mm", "mm"), ("durable_recovery_time_ms", "ms")),
            ),
            "temporal_synthesis": (
                "start_stop_6dof",
                "EgoAnchor w/o temporal synthesis",
                (("motion_hold_ratio", "proportion"), ("motion_translation_pninetyfive_mm", "mm")),
            ),
            "static_lock": (
                "static_head_motion",
                "EgoAnchor w/o StaticLock",
                (("position_hp_rms_mm", "mm"), ("absolute_translation_median_mm", "mm")),
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
        self.assertIn("CaptureTimeAlignmentTranslationEventPNinetyFiveMmDeltaMedian", names)
        self.assertIn("TemporalSynthesisMotionHoldRatioPercentagePointDeltaMedian", names)
        self.assertIn("TemporalSynthesisMotionHoldRatioPctPositiveCount", names)
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
        self.assertEqual(len(exp1_cells), 30)
        self.assertEqual(len(exp2_cells), 20)
        self.assertEqual(
            {row["column_key"] for row in exp2_cells},
            {"主指标", "Full median [IQR]", "Ablated median [IQR]", "Delta [IQR]（+/0/-）", "护栏 Delta [IQR]"},
        )
        hold_cell = next(
            row
            for row in exp2_cells
            if row["row_key"] == "时序合成（起停 6DoF）" and row["column_key"] == "Full median [IQR]"
        )
        self.assertEqual(hold_cell["display_value"], "1000 [900, 1100] %")
        hold_delta = next(
            row
            for row in exp2_cells
            if row["row_key"] == "时序合成（起停 6DoF）" and row["column_key"] == "Delta [IQR]（+/0/-）"
        )
        self.assertEqual(hold_delta["display_value"], "200 [100, 300] pp; 3/1/0")
        self.assertEqual(
            {row["row_key"] for row in exp1_cells},
            {
                "世界一致性（静止头动）",
                "静止稳定性（静止头动）",
                "起停转换（起停 6DoF）",
                "平移保真度（持续平移）",
                "旋转保真度（持续旋转）",
                "失效约束（遮挡恢复）",
            },
        )
        self.assertEqual(
            {row["column_key"] for row in exp1_cells},
            {"指标", *variants},
        )
        self.assertEqual(
            {row["row_key"] for row in exp2_cells},
            {
                "采集时刻对齐（静止头动）",
                "VCD 接纳（遮挡恢复）",
                "时序合成（起停 6DoF）",
                "StaticLock（静止头动）",
            },
        )
        formatted_cell = next(
            row
            for row in exp1_cells
            if row["row_key"] == "世界一致性（静止头动）"
            and row["column_key"] == "EgoAnchor"
        )
        self.assertEqual(formatted_cell["display_value"], "13.1 [12.1, 14.1] mm")
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
