"""实验三产物契约、绘图推断闭环和来源门禁入口测试。"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

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
    write_subjective_table,
)


ONE_EURO = METHODS[0]
"""测试夹具使用的稳定 One-Euro 方法 ID。"""


class Experiment3ArtifactContractTests(unittest.TestCase):
    """验证绘图星号不能脱离配对分，且所有发布入口先执行来源门禁。"""

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
                            source_gate_status="approved",
                        )
                    self.assertFalse(output.exists())

    def test_publication_entries_reject_unknown_gate_before_writing(self) -> None:
        """绘图和 TeX 入口对未知门禁状态统一抛出 ValueError 且不落盘。"""

        scores, tables = _analysis_fixture()
        invalid_status = cast(Any, "unexpected")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            figure_root = root / "figures_output"
            with self.assertRaisesRegex(ValueError, "未知实验三来源门禁状态"):
                publish_figures(
                    scores,
                    tables,
                    figure_root,
                    load_settings(),
                    source_gate_status=invalid_status,
                )
            self.assertFalse(figure_root.exists())

            table = root / "tex_output" / "table.tex"
            with self.assertRaisesRegex(ValueError, "未知实验三来源门禁状态"):
                write_subjective_table(
                    table,
                    pd.DataFrame(),
                    source_gate_status=invalid_status,
                )
            self.assertFalse(table.parent.exists())

    def test_artifact_contract_contains_unique_fixed_outputs(self) -> None:
        """单一不可变契约覆盖 XLSX、TeX 与两张图的 PNG/PDF。"""

        artifacts = EXP3_ARTIFACTS.outputs
        self.assertEqual(
            tuple(artifact.key for artifact in artifacts),
            (
                "results_workbook",
                "subjective_table",
                "figure4_png",
                "figure4_pdf",
                "figure5_png",
                "figure5_pdf",
            ),
        )
        self.assertEqual(len({artifact.key for artifact in artifacts}), len(artifacts))
        with self.assertRaises(AttributeError):
            setattr(EXP3_ARTIFACTS.figure4_png, "key", "changed")


def _analysis_fixture() -> tuple[ScoreData, AnalysisTables]:
    """构造无需读取工作簿即可覆盖十二项冻结结局的最小一致分析对象。"""

    outcomes = (*PRIMARY_OUTCOMES, *SCALE_OUTCOMES)
    one_euro = np.asarray((2.0, 3.0, 3.0, 4.0), dtype=float)
    differences = np.asarray((1.0, 1.0, -1.0, 1.0), dtype=float)
    egoanchor = one_euro + differences
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
