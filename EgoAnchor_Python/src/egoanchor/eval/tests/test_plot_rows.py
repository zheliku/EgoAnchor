"""Stage 2 实验一固定 plot 指标选择测试。"""

from __future__ import annotations

import unittest

from egoanchor.eval import (
    EXP1_VARIANTS,
    MetricRow,
    VcdCurvePoint,
    build_exp1_plot_rows,
    build_vcd_plot_rows,
)


def _row(
    scenario: str,
    metric: str,
    event: str,
    variant: str,
    unit: str = "mm",
) -> MetricRow:
    """创建一条有效 event 指标行。

    参数：
        scenario: 冻结场景标识。
        metric: 与场景匹配的指标键。
        event: 当前测试事件标识。
        variant: 实验一冻结系统配置。
        unit: 冻结指标单位。
    """

    return MetricRow(
        session_id="session",
        experiment_id="exp1_system_characterization",
        scenario_id=scenario,
        trial_id="trial",
        event_id=event,
        condition_id=f"exp1_system_characterization/{scenario}",
        variant_id=variant,
        metric_key=metric,
        metric_value=1.0,
        metric_unit=unit,
        aggregation_level="event",
        input_workbook_sha256="a" * 64,
    )


class PlotRowsTests(unittest.TestCase):
    """验证三张实验一图只选择各自冻结场景指标。"""

    def test_motion_and_occlusion_use_start_stop_and_occlusion_metrics(self) -> None:
        """运动图不得误用持续平移，遮挡图不得误用静止指标。"""

        rows = tuple(
            _row(scenario, metric, event, variant)
            for scenario, metric, event in (
                ("static_head_motion", "translation_event_pninetyfive_mm", "static"),
                ("start_stop_6dof", "motion_translation_pninetyfive_mm", "motion"),
                (
                    "continuous_translation",
                    "translation_event_pninetyfive_mm_continuous",
                    "continuous",
                ),
                (
                    "occlusion_recovery",
                    "occlusion_translation_pninetyfive_mm",
                    "occlusion",
                ),
            )
            for variant in EXP1_VARIANTS
        )
        selected = build_exp1_plot_rows(rows)
        self.assertEqual(len(selected.static_timeline), 4)
        self.assertEqual(len(selected.motion_events), 4)
        self.assertEqual(selected.motion_events[0]["metric_key"], "motion_translation_pninetyfive_mm")
        self.assertEqual(len(selected.occlusion_events), 4)
        self.assertEqual(
            selected.occlusion_events[0]["metric_key"],
            "occlusion_translation_pninetyfive_mm",
        )

    def test_rejects_incomplete_four_variant_event_matrix(self) -> None:
        """任一正式图缺少冻结系统配置时必须拒绝发布。"""

        rows = tuple(
            _row(scenario, metric, event, variant)
            for scenario, metric, event in (
                ("static_head_motion", "translation_event_pninetyfive_mm", "static"),
                ("start_stop_6dof", "motion_translation_pninetyfive_mm", "motion"),
                (
                    "occlusion_recovery",
                    "occlusion_translation_pninetyfive_mm",
                    "occlusion",
                ),
            )
            for variant in EXP1_VARIANTS
            if not (scenario == "occlusion_recovery" and variant == "Capture-Hold")
        )
        with self.assertRaisesRegex(ValueError, "四系统矩阵"):
            build_exp1_plot_rows(rows)

    def test_vcd_plot_keeps_only_pninetyfive_tail_risk(self) -> None:
        """正式曲线不得把 mean 与 P95 risk 交替连接。"""

        rows = tuple(
            VcdCurvePoint(
                scenario_id="occlusion_recovery",
                reference_kind=reference,
                risk_kind=risk_kind,
                point_index=0,
                threshold=0.8 if reference == "vcd" else None,
                coverage=0.5,
                risk_mm=2.0 if risk_kind == "mean" else 4.0,
                group_count=1,
                cumulative_count=1,
                coverage_denominator=2,
                input_workbook_sha256="a" * 64,
            )
            for reference in ("vcd", "random")
            for risk_kind in ("mean", "tail_pninetyfive")
        )
        selected = build_vcd_plot_rows(rows)
        self.assertEqual(len(selected), 2)
        self.assertEqual({row["risk_kind"] for row in selected}, {"tail_pninetyfive"})
        self.assertEqual({row["reference_kind"] for row in selected}, {"vcd", "random"})


if __name__ == "__main__":
    unittest.main()
