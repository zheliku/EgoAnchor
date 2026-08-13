"""实验三产物契约与绘图推断闭环测试。"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch

from egoanchor.eval.experiments.experiment_3.analysis import (
    EGOANCHOR,
    EXP3_ARTIFACTS,
    MAIN_FAMILY,
    METHODS,
    PRIMARY_OUTCOMES,
    SCALE_FAMILY,
    SCALE_OUTCOMES,
    AnalysisTables,
    ScoreData,
    holm_adjust,
    load_settings,
    publish_figures,
    signed_rank_test,
)


ONE_EURO = METHODS[0]
"""测试夹具使用的稳定 One-Euro 方法 ID。"""


class Experiment3ArtifactContractTests(unittest.TestCase):
    """验证绘图星号不能脱离配对分，且发布产物遵循固定契约。"""

    def test_figures_recompute_rank_statistics_and_family_holm(self) -> None:
        """即使错误 Holm p 仍位于合法范围，绘图入口也必须拒绝。"""

        scores, tables = _analysis_fixture()
        mutations: tuple[tuple[str, float, str], ...] = (
            ("N_Nonzero", 3.0, "N_Nonzero"),
            ("W", 3.0, "W"),
            ("p_Holm", 0.9, "p_Holm"),
        )
        settings = load_settings()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for field, value, expected_error in mutations:
                with self.subTest(field=field):
                    bad_results = tables.results.copy()
                    row = bad_results.index[bad_results["Outcome"] == "Q1"][0]
                    bad_results.at[row, field] = value
                    output = root / field
                    with self.assertRaisesRegex(
                        ValueError,
                        rf"Q1 {expected_error} 与配对分重算结果不一致",
                    ):
                        publish_figures(
                            scores,
                            replace(tables, results=bad_results),
                            output,
                            settings,
                        )
                    self.assertFalse(output.exists())

    def test_artifact_contract_contains_unique_fixed_outputs(self) -> None:
        """单一不可变契约覆盖 XLSX、TeX 与正文复合图的 PNG/PDF。"""

        artifacts = EXP3_ARTIFACTS.outputs
        self.assertEqual(
            tuple(artifact.key for artifact in artifacts),
            (
                "results_workbook",
                "subjective_table",
                "figure4_png",
                "figure4_pdf",
            ),
        )
        self.assertEqual(EXP3_ARTIFACTS.version, 9)
        self.assertEqual(
            EXP3_ARTIFACTS.figure4_png.canonical_name,
            "figure4_exp3_subjective_outcomes.png",
        )
        self.assertEqual(
            EXP3_ARTIFACTS.figure4_pdf.canonical_name,
            "figure4_exp3_subjective_outcomes.pdf",
        )
        self.assertEqual(len({artifact.key for artifact in artifacts}), len(artifacts))
        with self.assertRaises(AttributeError):
            setattr(EXP3_ARTIFACTS.figure4_png, "key", "changed")

    def test_composite_figure_preserves_scales_slots_and_one_legend(self) -> None:
        """单排 Figure 4 必须保持四组轴、等宽槽和单一共享图例。"""

        scores, tables = _analysis_fixture()
        settings = load_settings()
        captured: list[Figure] = []
        save_options: list[dict[str, Any]] = []

        def capture(figure: Figure, *_args: Any, **kwargs: Any) -> None:
            """保留 Figure 与导出选项，供布局和裁剪语义断言。"""

            captured.append(figure)
            save_options.append(kwargs)

        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(Figure, "savefig", autospec=True, side_effect=capture),
        ):
            outputs = publish_figures(
                scores,
                tables,
                Path(directory),
                settings,
            )

        self.assertEqual(set(outputs), {"figure4_png", "figure4_pdf"})
        self.assertEqual(len({id(figure) for figure in captured}), 1)
        self.assertEqual(len(save_options), 2)
        self.assertNotIn("bbox_inches", save_options[0])
        self.assertNotIn("pad_inches", save_options[0])
        self.assertEqual(save_options[1]["bbox_inches"], "tight")
        self.assertAlmostEqual(save_options[1]["pad_inches"], 0.020)
        figure = captured[0]
        self.assertEqual(len(figure.axes), 4)
        self.assertEqual(len(figure.legends), 1)
        self.assertEqual(
            [text.get_text() for text in figure.legends[0].get_texts()],
            ["One-Euro", "EgoAnchor", "Mean"],
        )

        stage_axis, overall_axis, seven_point_axis, tia_axis = figure.axes
        self.assertEqual(
            [tick.get_text() for tick in stage_axis.get_xticklabels()],
            ["Stability", "Attachment", "Orientation", "Recovery"],
        )
        self.assertEqual(
            [tick.get_text() for tick in overall_axis.get_xticklabels()],
            ["Position", "Reliance", "Balance"],
        )
        self.assertEqual(
            [tick.get_text() for tick in seven_point_axis.get_xticklabels()],
            ["AQ-EQ", "AQ-IQ", "S-TIAS"],
        )
        self.assertEqual(
            [tick.get_text() for tick in tia_axis.get_xticklabels()],
            ["TiA R/C", "TiA U/P"],
        )
        for axis in figure.axes:
            self.assertTrue(
                all(abs(float(tick.get_rotation()) - 30.0) < 1.0e-12 for tick in axis.get_xticklabels())
            )
        # 单排首个面板给出七点量尺；同量尺的后续面板不再重复标注读数。
        self.assertEqual(stage_axis.get_ylabel(), "Rating (1-7)")
        self.assertEqual(overall_axis.get_ylabel(), "")
        self.assertEqual(seven_point_axis.get_ylabel(), "")
        self.assertEqual(overall_axis.get_yticklabels(), [])
        self.assertEqual(seven_point_axis.get_yticklabels(), [])
        # TiA 在自身右侧保留 1--5 刻度，避免刻度侵入前一分区。
        self.assertEqual(tia_axis.get_ylabel(), "")
        self.assertEqual(tia_axis.yaxis.get_ticks_position(), "right")
        self.assertFalse(tia_axis.spines["left"].get_visible())
        self.assertTrue(tia_axis.spines["right"].get_visible())
        self.assertEqual(
            stage_axis.get_title(loc="left"),
            "(a) Stage behavior",
        )
        self.assertEqual(
            overall_axis.get_title(loc="left"),
            "(b) Overall judgment",
        )
        self.assertEqual(
            seven_point_axis.get_title(loc="left"),
            "(c) AQ and S-TIAS",
        )
        self.assertEqual(
            tia_axis.get_title(loc="left"),
            "(d) TiA (1-5)",
        )
        self.assertEqual(
            [text.get_text() for text in stage_axis.texts],
            ["*"] * 4,
        )
        self.assertEqual(
            [text.get_text() for text in overall_axis.texts],
            ["*"] * 3,
        )
        self.assertEqual(
            [text.get_text() for text in seven_point_axis.texts],
            ["**"] * 3,
        )
        self.assertEqual(
            [text.get_text() for text in tia_axis.texts],
            ["**"] * 2,
        )
        for axis in figure.axes:
            boxes = [patch for patch in axis.patches if isinstance(patch, PathPatch)]
            bounds = [
                (float(np.min(patch.get_path().vertices[:, 0])), float(np.max(patch.get_path().vertices[:, 0])))
                for patch in boxes
            ]
            self.assertTrue(
                all(abs(right - left - 0.24) < 1.0e-12 for left, right in bounds)
            )
            self.assertTrue(
                all(
                    abs(bounds[index + 1][0] - bounds[index][1] - 0.16)
                    < 1.0e-12
                    for index in range(0, len(bounds), 2)
                )
            )

        stage_box = stage_axis.get_position()
        overall_box = overall_axis.get_position()
        seven_point_box = seven_point_axis.get_position()
        tia_box = tia_axis.get_position()
        self.assertAlmostEqual(stage_box.x0, 0.045, places=8)
        self.assertAlmostEqual(tia_box.x1, 0.980, places=8)
        # 单排四个面板共用同一槽宽，因此各结局的箱体等宽。
        slot_width = stage_box.width / 4.0
        for box, slots in (
            (overall_box, 3.0),
            (seven_point_box, 3.0),
            (tia_box, 2.0),
        ):
            self.assertAlmostEqual(box.width / slots, slot_width, places=8)
        for left_box, right_box in zip(
            (stage_box, overall_box, seven_point_box),
            (overall_box, seven_point_box, tia_box),
            strict=True,
        ):
            self.assertAlmostEqual(right_box.x0 - left_box.x1, 0.035, places=8)
        self.assertTrue(
            all(
                abs(box.y0 - stage_box.y0) < 1.0e-12
                and abs(box.height - stage_box.height) < 1.0e-12
                for box in (overall_box, seven_point_box, tia_box)
            )
        )

def _analysis_fixture() -> tuple[ScoreData, AnalysisTables]:
    """构造无需读取工作簿即可覆盖十二项冻结结局的最小一致分析对象。"""

    outcomes = (*PRIMARY_OUTCOMES, *SCALE_OUTCOMES)
    one_euro: np.ndarray = np.asarray(
        (2.0, 3.0, 3.0, 4.0, 2.0, 3.0, 3.0, 4.0, 2.0, 3.0),
        dtype=float,
    )
    differences: np.ndarray = np.ones_like(one_euro)
    egoanchor: np.ndarray = one_euro + differences
    paired_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        for index, (left, right, difference) in enumerate(
            zip(one_euro, egoanchor, differences, strict=True),
            start=1,
        ):
            paired_rows.append(
                {
                    "Participant_ID": f"P{index:03d}",
                    "Outcome": outcome,
                    ONE_EURO: left,
                    EGOANCHOR: right,
                    "Difference": difference,
                }
            )
        rank = signed_rank_test(differences)
        row: dict[str, Any] = {
            "Family": MAIN_FAMILY if outcome in PRIMARY_OUTCOMES else SCALE_FAMILY,
            "Outcome": outcome,
            "N": len(differences),
            "N_Nonzero": rank["n_nonzero"],
            "W": rank["w"],
            "p_raw": rank["p_value"],
        }
        for prefix, values in (
            ("OneEuro", one_euro),
            ("EgoAnchor", egoanchor),
            ("Difference", differences),
        ):
            q1, median, q3 = np.quantile(
                values,
                (0.25, 0.5, 0.75),
                method="linear",
            )
            row[f"{prefix}_Q1"] = float(q1)
            row[f"{prefix}_Median"] = float(median)
            row[f"{prefix}_Q3"] = float(q3)
        result_rows.append(row)

    results = pd.DataFrame(result_rows)
    for family in (PRIMARY_OUTCOMES, SCALE_OUTCOMES):
        positions = [results.index[results["Outcome"] == outcome][0] for outcome in family]
        results.loc[positions, "p_Holm"] = holm_adjust(
            results.loc[positions, "p_raw"].to_numpy(dtype=float)
        )
    results = results.drop(columns="p_raw")
    scores = ScoreData(
        block_scores=pd.DataFrame(),
        paired_scores=pd.DataFrame(paired_rows),
        reliability_items=pd.DataFrame(),
    )
    tables = AnalysisTables(
        sample=pd.DataFrame(),
        results=results,
        objects=pd.DataFrame(),
        reliability=pd.DataFrame(),
        choices=pd.DataFrame(),
    )
    return scores, tables


if __name__ == "__main__":
    unittest.main()
