"""实验三结果工作簿输入摘要与回读防篡改测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook  # type: ignore[import-untyped]

from egoanchor.eval.experiments.experiment_3.analysis import (
    MAIN_FAMILY,
    OBJECTS,
    PRIMARY_OUTCOMES,
    SCALE_FAMILY,
    SCALE_OUTCOMES,
    AnalysisTables,
    Exp3Data,
    load_settings,
    write_results_workbook,
)
from egoanchor.eval.experiments.experiment_3.analysis import workbook as workbook_module


_INPUT_SHA = "1" * 64
_SETTINGS_SHA = "3" * 64
_INCLUDED = tuple(f"P{index:03d}" for index in range(1, 19))
"""单元测试使用的稳定摘要与最低完整配对参与者集合。"""


class Experiment3WorkbookIntegrityTests(unittest.TestCase):
    """验证结果簿输入摘要与冻结结果键不能在写出后静默漂移。"""

    def test_readback_rejects_tampered_input_and_settings_digests(self) -> None:
        """说明页任一输入或配置摘要被改写后，回读必须失败。"""

        tampered_facts = {
            "输入 SHA-256": "4" * 64,
            "参数 SHA-256": "5" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, replacement in tampered_facts.items():
                with self.subTest(label=label):
                    output = _write(
                        root / f"tampered_{len(label)}.xlsx",
                    )
                    _replace_info_fact(output, label, replacement)
                    with self.assertRaisesRegex(ValueError, label):
                        _verify(output)

    def test_readback_rejects_replaced_outcome_object_key(self) -> None:
        """21 行数量不变时，重复或替换任一物体键仍必须失败。"""

        with tempfile.TemporaryDirectory() as directory:
            output = _write(
                Path(directory) / "tampered_object.xlsx",
            )
            workbook = load_workbook(output)
            try:
                worksheet = workbook["分物体描述"]
                worksheet.cell(5, 2, "错误物体")
                workbook.save(output)
            finally:
                workbook.close()
            with self.assertRaisesRegex(ValueError, "七个主条目乘三个对象"):
                _verify(output)


def _data() -> Exp3Data:
    """构造只供结果簿契约测试使用的最小输入快照。"""

    return Exp3Data(
        participants=pd.DataFrame(),
        blocks=pd.DataFrame(),
        methods=pd.DataFrame(),
        finals=pd.DataFrame(),
        source_path="P:/test/source.xlsx",
        source_sha256=_INPUT_SHA,
    )


def _validation() -> dict[str, Any]:
    """构造与读取器返回字段一致的最小验证摘要。"""

    return {
        "included_participants": _INCLUDED,
        "included_count": len(_INCLUDED),
        "warnings": (),
    }


def _tables() -> AnalysisTables:
    """构造覆盖六页写入路径且冻结键完整的最小结果表。"""

    sample = pd.DataFrame(
        columns=(
            "Section",
            "Variable",
            "Category",
            "N",
            "Denominator",
            "Proportion",
            "Mean",
            "SD",
            "Q1",
            "Median",
            "Q3",
            "Min",
            "Max",
            "Expected_At_Actual_N",
            "Deviation_From_Actual_Balance",
            "Status",
        )
    )
    results = pd.DataFrame(
        _result_row(outcome, MAIN_FAMILY)
        for outcome in PRIMARY_OUTCOMES
    )
    scale_results = pd.DataFrame(
        _result_row(outcome, SCALE_FAMILY)
        for outcome in SCALE_OUTCOMES
    )
    results = pd.concat((results, scale_results), ignore_index=True)
    objects = pd.DataFrame(
        _object_row(outcome, object_key)
        for outcome in PRIMARY_OUTCOMES
        for object_key in OBJECTS
    )
    return AnalysisTables(
        sample=sample,
        results=results,
        objects=objects,
        reliability=pd.DataFrame(),
        manipulation=pd.DataFrame(columns=("Type",)),
        choices=pd.DataFrame(columns=("Measure", "Category")),
    )


def _result_row(outcome: str, family: str) -> dict[str, Any]:
    """返回一行可写入主结果页的中性推断结果。"""

    return {
        "Family": family,
        "Outcome": outcome,
        "N": len(_INCLUDED),
        "N_Nonzero": len(_INCLUDED),
        "OneEuro_Q1": 3.0,
        "OneEuro_Median": 4.0,
        "OneEuro_Q3": 5.0,
        "EgoAnchor_Q1": 3.0,
        "EgoAnchor_Median": 4.0,
        "EgoAnchor_Q3": 5.0,
        "Difference_Q1": -1.0,
        "Difference_Median": 0.0,
        "Difference_Q3": 1.0,
        "W": 40.0,
        "p_Holm": 1.0,
        "r_rb": 0.0,
        "r_rb_CI_Low": -0.2,
        "r_rb_CI_High": 0.2,
        "r_rb_CI_Status": "estimated",
    }


def _object_row(outcome: str, object_key: str) -> dict[str, Any]:
    """返回一行可写入分物体描述页的中性结果。"""

    row = _result_row(outcome, MAIN_FAMILY)
    row.update({"Object_Key": object_key, "Direction": "median_tie"})
    return row


def _write(destination: Path) -> Path:
    """通过公开入口写出并完成第一次回读验证。"""

    return write_results_workbook(
        destination,
        data=_data(),
        tables=_tables(),
        settings=load_settings(),
        settings_sha256=_SETTINGS_SHA,
        batch_config_path=destination.parent / "batch.toml",
        paper_config_path=destination.parent / "paper.toml",
        validation=_validation(),
    )


def _verify(path: Path) -> None:
    """按最初写入事实重新执行内部回读器。"""

    workbook_module._verify_results_workbook(
        path,
        input_sha256=_INPUT_SHA,
        settings_sha256=_SETTINGS_SHA,
        included_count=len(_INCLUDED),
    )


def _replace_info_fact(path: Path, label: str, replacement: str) -> None:
    """在保留其余结构的前提下篡改单个说明页事实。"""

    workbook = load_workbook(path)
    try:
        worksheet = workbook["说明"]
        for row in range(1, worksheet.max_row + 1):
            if worksheet.cell(row, 1).value == label:
                worksheet.cell(row, 2, replacement)
                workbook.save(path)
                return
        raise AssertionError(f"测试工作簿缺少说明页事实：{label}")
    finally:
        workbook.close()


if __name__ == "__main__":
    unittest.main()
