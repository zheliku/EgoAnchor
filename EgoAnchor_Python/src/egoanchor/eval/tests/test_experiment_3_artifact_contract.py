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
        self.assertEqual(EXP3_ARTIFACTS.version, 7)
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
        """双排 Figure 4 必须保持三组轴、等宽槽和单一共享图例。"""

        scores, tables = _analysis_fixture()
        settings = load_settings()
        captured: list[Figure] = []

        def capture(figure: Figure, *_args: Any, **_kwargs: Any) -> None:
            """保留关闭后的 Figure 对象，供布局语义断言。"""

            captured.append(figure)

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
        figure = captured[0]
        self.assertEqual(len(figure.axes), 3)
        self.assertEqual(len(figure.legends), 1)
        self.assertEqual(
            [text.get_text() for text in figure.legends[0].get_texts()],
            ["One-Euro", "EgoAnchor", "Mean"],
        )

        primary_axis, seven_point_axis, tia_axis = figure.axes
        self.assertEqual(
            [tick.get_text() for tick in primary_axis.get_xticklabels()],
            [
                "Stability",
                "Attachment",
                "Recovery",
                "Reliance",
                "Balance",
                "Position",
                "Orientation",
            ],
        )
        self.assertEqual(
            [tick.get_text() for tick in seven_point_axis.get_xticklabels()],
            ["AQ-EQ", "AQ-IQ", "S-TIAS"],
        )
        self.assertEqual(
            [tick.get_text() for tick in tia_axis.get_xticklabels()],
            ["TiA R/C", "TiA U/P"],
        )
        self.assertEqual(primary_axis.get_ylabel(), "Rating (1-7)")
        self.assertEqual(seven_point_axis.get_ylabel(), "Rating (1-7)")
        self.assertEqual(tia_axis.get_ylabel(), "Rating (1-5)")
        self.assertEqual(tia_axis.yaxis.get_label_position(), "right")
        self.assertEqual(tia_axis.yaxis.get_ticks_position(), "right")
        self.assertEqual(primary_axis.get_title(loc="left"), "(a) Primary outcomes")
        self.assertEqual(
            seven_point_axis.get_title(loc="left"),
            "(b) Published scales (1-7)",
        )
        self.assertEqual(
            tia_axis.get_title(loc="left"),
            "(c) TiA scales (1-5)",
        )
        self.assertEqual(
            [text.get_text() for text in primary_axis.texts],
            ["*<.05"] * 7,
        )
        self.assertEqual(
            [text.get_text() for text in seven_point_axis.texts],
            ["**<.01"] * 3,
        )
        self.assertEqual(
            [text.get_text() for text in tia_axis.texts],
            ["**<.01"] * 2,
        )

        primary_box = primary_axis.get_position()
        seven_point_box = seven_point_axis.get_position()
        tia_box = tia_axis.get_position()
        slot_width = primary_box.width / 7.0
        self.assertAlmostEqual(seven_point_box.width / 3.0, slot_width, places=8)
        self.assertAlmostEqual(tia_box.width / 2.0, slot_width, places=8)
        self.assertGreater(tia_box.x0 - seven_point_box.x1, 0.0)
        self.assertLess(tia_box.x0 - seven_point_box.x1, slot_width / 4.0)
        self.assertAlmostEqual(
            (seven_point_box.x0 + tia_box.x1) / 2.0,
            (primary_box.x0 + primary_box.x1) / 2.0,
            places=8,
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
        manipulation=pd.DataFrame(),
        choices=pd.DataFrame(),
    )
    return scores, tables


if __name__ == "__main__":
    unittest.main()
