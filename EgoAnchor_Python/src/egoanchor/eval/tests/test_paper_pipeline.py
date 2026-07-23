"""论文分析入口的边界与最小计算测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from openpyxl import Workbook  # type: ignore[import-untyped]

from egoanchor.eval import cli as eval_cli
from egoanchor.eval.paper_analysis import (
    METHODS,
    TEMPORAL_STRATEGY_VARIANTS,
    analyze_workbooks,
    build_analysis,
    build_point_panel,
    build_translation_panel,
    eligible_trials,
    iter_rows,
    paired_metric_matrix,
    risk_coverage_curve,
    settings_sha256,
    summarize_risk_coverage,
)


class PaperPipelineTests(unittest.TestCase):
    """冻结新管线只读取 Stage 1 XLSX 且不恢复旧阶段命令。"""

    def test_formal_cli_does_not_allow_parameter_overrides(self) -> None:
        """正式论文入口只能读取冻结的 paper.toml。"""

        arguments = eval_cli.build_parser().parse_args(["analyze"])

        self.assertFalse(hasattr(arguments, "settings"))
        self.assertEqual(len(settings_sha256()), 64)

    def test_temporal_panel_uses_extrapolation_linear_and_hermite_order(self) -> None:
        """图 3(d) 固定比较无 StaticLock 的外推、默认 Linear/SLERP 与 Hermite。"""

        self.assertEqual(
            TEMPORAL_STRATEGY_VARIANTS,
            (
                "Smoothed KF Extrapolation",
                "EgoAnchor w/o StaticLock",
                "Hermite Interpolation",
            ),
        )

    def test_vcd_risk_coverage_keeps_score_ties_indivisible(self) -> None:
        """同分候选必须整组进入曲线，AURC 不得依赖候选行顺序。"""

        curve, aurc = risk_coverage_curve((0.9, 0.9, 0.2), (1.0, 9.0, 2.0))
        reordered, reordered_aurc = risk_coverage_curve((0.9, 0.2, 0.9), (9.0, 2.0, 1.0))

        self.assertEqual([row["coverage"] for row in curve], [2.0 / 3.0, 1.0])
        self.assertEqual([row["score_tie_count"] for row in curve], [2, 1])
        self.assertAlmostEqual(float(curve[0]["selective_risk_mm"]), 5.0)
        self.assertAlmostEqual(aurc, 14.0 / 3.0)
        self.assertEqual(curve, reordered)
        self.assertAlmostEqual(aurc, reordered_aurc)

    def test_vcd_risk_coverage_all_equal_scores_reduce_to_full_risk(self) -> None:
        """所有分数相同时只有全覆盖点，AURC 等于候选平均风险。"""

        curve, aurc = risk_coverage_curve((0.5, 0.5, 0.5), (1.0, 2.0, 6.0))

        self.assertEqual(len(curve), 1)
        self.assertEqual(curve[0]["coverage"], 1.0)
        self.assertAlmostEqual(aurc, 3.0)

    def test_vcd_risk_coverage_rejects_invalid_scores(self) -> None:
        """缺失、非有限或越界分数不得静默进入论文指标。"""

        for scores in ((), (float("nan"),), (-0.01,), (1.01,)):
            with self.subTest(scores=scores), self.assertRaises(ValueError):
                risk_coverage_curve(scores, (1.0,) if scores else ())

    def test_vcd_plot_summary_uses_whole_tie_group_at_target_coverage(self) -> None:
        """固定 coverage 汇总不得在 event 的首个完整同分组内部插值。"""

        rows = (
            {"session_id": "s", "trial_id": "t", "segment_id": "a", "coverage": 0.6, "selective_risk_mm": 2.0},
            {"session_id": "s", "trial_id": "t", "segment_id": "a", "coverage": 1.0, "selective_risk_mm": 4.0},
            {"session_id": "s", "trial_id": "t", "segment_id": "b", "coverage": 0.4, "selective_risk_mm": 6.0},
            {"session_id": "s", "trial_id": "t", "segment_id": "b", "coverage": 1.0, "selective_risk_mm": 8.0},
        )

        summary = summarize_risk_coverage(rows)

        self.assertEqual(len(summary), 20)
        self.assertAlmostEqual(float(summary[0]["coverage"]), 0.05)
        self.assertAlmostEqual(float(summary[0]["selective_risk_median_mm"]), 4.0)
        self.assertAlmostEqual(float(summary[-1]["selective_risk_median_mm"]), 6.0)

    def test_xlsx_reader_streams_selected_columns_from_stage_one_sheet(self) -> None:
        """新分析 reader 直接消费 Stage 1 sheet，不改写原始 workbook。"""

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "task_1_complete.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "unity_render"
            sheet.append(("session_id", "variant_id", "render_mono_ms", "unused"))
            sheet.append(("session", "EgoAnchor", 123.5, "ignored"))
            workbook.save(path)
            before = path.read_bytes()

            rows = list(iter_rows(path, "unity_render", ("variant_id", "render_mono_ms")))

            self.assertEqual(
                rows,
                [{"variant_id": "EgoAnchor", "render_mono_ms": 123.5}],
            )
            self.assertEqual(path.read_bytes(), before)

    def test_build_analysis_rejects_non_xlsx_input_before_writing(self) -> None:
        """分析入口拒绝 JSON/CSV，保持初始 XLSX 是唯一分析桥梁。"""

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "task_1.json"
            source.write_text("{}", encoding="utf-8")
            output = root / "output"

            with self.assertRaisesRegex(ValueError, "五本 Stage 1 XLSX"):
                build_analysis((source,), output, "figures/panels")
            self.assertFalse(output.exists())

    def test_v3_stage_one_workbook_is_rejected_before_analysis(self) -> None:
        """旧 linear_v2 工作簿不得被新时序策略矩阵的论文入口接受。"""

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "task_1_complete.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "metadata_kv"
            sheet.append(("document", "json_path", "value_json"))
            sheet.append(("manifest.json", "variant_matrix_id", '"exp12_9_linear_v2"'))
            workbook.save(path)

            with self.assertRaisesRegex(ValueError, "exp12_9_smoothed_hermite_v4"):
                analyze_workbooks((path,))

    def test_eligible_trials_exclude_rejected_retries(self) -> None:
        """论文指标只接受最终结束且没有后续作废的 trial。"""

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "task_1_complete.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "events"
            sheet.append(
                (
                    "session_id",
                    "trial_id",
                    "event",
                    "event_type",
                    "mono_ms",
                    "created_unix_ms",
                    "event_row_id",
                )
            )
            sheet.append(("s", "old", "trial_ended", "trial_ended", 10.0, 10.0, "e1"))
            sheet.append(("s", "old", "trial_rejected", "trial_rejected", 11.0, 11.0, "e2"))
            sheet.append(("s", "new", "trial_ended", "trial_ended", 20.0, 20.0, "e3"))
            workbook.save(path)

            self.assertEqual(eligible_trials((path,)), frozenset({("s", "new")}))

    def test_figure_pairing_uses_event_identity_instead_of_row_position(self) -> None:
        """实验一折线必须按稳定片段键配对，即使各方法行顺序不同。"""

        rows = {}
        for method_index, method in enumerate(METHODS):
            method_rows = [
                {"session_id": "s", "trial_id": "t", "segment_id": "b", "value": method_index + 10.0},
                {"session_id": "s", "trial_id": "t", "segment_id": "a", "value": method_index + 1.0},
            ]
            if method_index % 2:
                method_rows.reverse()
            rows[method] = tuple(method_rows)

        matrix = paired_metric_matrix(rows, METHODS, ("value",))

        self.assertEqual(matrix[:, :, 0].tolist(), [[1.0, 2.0, 3.0, 4.0], [10.0, 11.0, 12.0, 13.0]])

    def test_figure_pairing_rejects_missing_method_episode(self) -> None:
        """任一方法缺失 episode 时禁止生成看似配对的趋势线。"""

        rows = {
            method: ({"session_id": "s", "trial_id": "t", "segment_id": "a", "value": 1.0},)
            for method in METHODS
        }
        rows[METHODS[-1]] = ()

        with self.assertRaisesRegex(ValueError, "配对不完整"):
            paired_metric_matrix(rows, METHODS, ("value",))

    def test_experiment_one_point_panels_avoid_repeated_legends(self) -> None:
        """图二(a)/(c) 已有横轴方法名，不再放重复图例；散点图保留图例。"""

        values = {method: np.asarray((1.0, 2.0)) for method in METHODS}
        point_figure = build_point_panel(
            values,
            "Metric",
            np.asarray(((1.0, 1.1, 1.2, 1.3), (2.0, 2.1, 2.2, 2.3))),
        )
        rows = {
            method: (
                {
                    "session_id": "s",
                    "trial_id": "t",
                    "segment_id": "a",
                    "effective_lag_ms": 200.0 + index,
                    "aligned_rmse_mm": 4.0 + index,
                },
                {
                    "session_id": "s",
                    "trial_id": "t",
                    "segment_id": "b",
                    "effective_lag_ms": 220.0 + index,
                    "aligned_rmse_mm": 5.0 + index,
                },
            )
            for index, method in enumerate(METHODS)
        }
        translation_figure = build_translation_panel(
            SimpleNamespace(translation_segments=rows)
        )

        self.assertIsNone(point_figure.axes[0].get_legend())
        self.assertIsNotNone(translation_figure.axes[0].get_legend())

    def test_translation_panel_does_not_connect_methods(self) -> None:
        """图二(b) 不连接跨方法散点，避免方法顺序造成视觉混淆。"""

        rows = {
            method: (
                {
                    "session_id": "s",
                    "trial_id": "t",
                    "segment_id": "a",
                    "effective_lag_ms": 200.0 + index,
                    "aligned_rmse_mm": 4.0 + index,
                },
            )
            for index, method in enumerate(METHODS)
        }
        figure = build_translation_panel(SimpleNamespace(translation_segments=rows))

        paired_lines = [line for line in figure.axes[0].lines if line.get_alpha() == 0.20]
        self.assertEqual(paired_lines, [])

    def test_panel_titles_are_owned_by_latex(self) -> None:
        """绘图代码不重复写入由 LaTeX subcaption 承担的小标题。"""

        values = {method: np.asarray((1.0, 2.0)) for method in METHODS}
        figure = build_point_panel(
            values,
            "Metric",
            np.asarray(((1.0, 1.1, 1.2, 1.3), (2.0, 2.1, 2.2, 2.3))),
        )

        self.assertEqual(figure.axes[0].get_title(), "")


if __name__ == "__main__":
    unittest.main()
