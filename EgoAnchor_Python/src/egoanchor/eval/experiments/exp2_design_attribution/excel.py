"""实验二的多 sheet Excel 导出。

产物文件 ``exp2_analysis.xlsx`` 包含：
- ``component_matrix``：4 组件×多指标的配对差透视（供快速横向对比）；
- ``component_deltas``：完整配对差明细表（每个 trial/event 一行）；
- ``vcd_risk_coverage``：VCD 诱导的 risk-coverage 采样点，供自绘曲线；
- ``vcd_aurc``：每个 trial/event 单元的 AURC 统计。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from egoanchor.eval.excel import write_workbook

from .contract import ABLATION_VARIANTS, BASELINE_VARIANT


EXCEL_FILENAME = "exp2_analysis.xlsx"
"""实验二 Excel 产物的固定文件名。"""


def write_exp2_excel(
    tables: Mapping[str, pd.DataFrame],
    output_dir: str | Path,
) -> Path:
    """写出实验二多 sheet 分析 Excel，返回文件路径。"""

    output = Path(output_dir)
    sheets = {
        "component_matrix": _component_matrix(tables.get("exp2_component_delta_summary", pd.DataFrame())),
        "component_deltas": _rounded(tables.get("exp2_component_deltas", pd.DataFrame())),
        "vcd_risk_coverage": _rounded(tables.get("exp2_vcd_risk_coverage", pd.DataFrame())),
        "vcd_aurc": _rounded(tables.get("exp2_vcd_aurc", pd.DataFrame())),
        "session_qc": _rounded(tables.get("exp2_session_qc", pd.DataFrame())),
    }
    return write_workbook(sheets, output / EXCEL_FILENAME)


def _component_matrix(summary: pd.DataFrame) -> pd.DataFrame:
    """把组件×指标的中位配对差整理为宽表，行=消融、列=指标。"""

    if summary.empty:
        return summary.copy()
    if not {"variant_label", "metric", "delta_median"}.issubset(summary.columns):
        return summary.copy()
    try:
        pivot = summary.pivot_table(
            index="variant_label",
            columns="metric",
            values="delta_median",
            aggfunc="median",
        ).round(4)
        # 按固定消融顺序排列行。
        ordered = [v for v in ABLATION_VARIANTS if v in pivot.index]
        return pivot.loc[ordered].reset_index()
    except Exception:
        return summary.copy()


def _rounded(frame: pd.DataFrame, digits: int = 4) -> pd.DataFrame:
    """对数值列四舍五入，减小体积并提升可读性。"""

    if frame.empty:
        return frame.copy()
    result = frame.copy()
    for column in result.columns:
        if pd.api.types.is_float_dtype(result[column]):
            result[column] = result[column].round(digits)
    return result


__all__ = ["EXCEL_FILENAME", "write_exp2_excel"]
