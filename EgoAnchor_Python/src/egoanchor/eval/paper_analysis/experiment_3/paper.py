"""实验三论文表格 TeX 的确定性生成。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from .contracts import OUTCOME_LABELS


def write_subjective_table(
    destination: Path,
    primary: pd.DataFrame,
    scales: pd.DataFrame,
) -> Path:
    """写入主家族和已发表量表家族的紧凑论文表。"""

    output = destination.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "% 由 pixi run eval experiment3 analyze 自动生成；请勿手工修改。",
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{实验三的参与者内主观评价结果。每位参与者先在三个物体上取均值；差值方向为 EgoAnchor$-$One-Euro。}",
        r"\label{tab:exp3-subjective}",
        r"\small",
        r"\setlength{\tabcolsep}{3.2pt}",
        r"\begin{tabular}{lcccc}",
        r"\toprule",
        r"结局 & One-Euro Mdn [IQR] & EgoAnchor Mdn [IQR] & $p_{\mathrm{Holm}}$ & $r_{rb}$ \\",
        r"\midrule",
        r"\multicolumn{5}{l}{\emph{主证实家族}} \\",
    ]
    lines.extend(_result_rows(primary))
    lines.extend(
        [
            r"\midrule",
            r"\multicolumn{5}{l}{\emph{已发表量表家族}} \\",
        ]
    )
    lines.extend(_result_rows(scales))
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}", ""])
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def _result_rows(frame: pd.DataFrame) -> list[str]:
    """把一组结果转换为 TeX 表格行。"""

    rows: list[str] = []
    for _, row in frame.iterrows():
        outcome = str(row["Outcome"])
        label = _escape_tex(OUTCOME_LABELS.get(outcome, outcome))
        one_euro = _median_iqr(row, "OneEuro")
        egoanchor = _median_iqr(row, "EgoAnchor")
        p_value = _format_p(row.get("p_Holm"))
        effect = _format_number(row.get("r_rb"), 2)
        rows.append(f"{label} & {one_euro} & {egoanchor} & {p_value} & {effect}" + r" \\")
    return rows


def _median_iqr(row: pd.Series, prefix: str) -> str:
    """按 Mdn [Q1, Q3] 格式化一个方法的描述统计。"""

    median = _format_number(row.get(f"{prefix}_Median"), 2)
    q1 = _format_number(row.get(f"{prefix}_Q1"), 2)
    q3 = _format_number(row.get(f"{prefix}_Q3"), 2)
    return f"{median} [{q1}, {q3}]"


def _format_p(value: Any) -> str:
    """格式化表中 Holm p 值。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if not math.isfinite(number):
        return "--"
    return "$<.001$" if number < 0.001 else f"{number:.3f}".lstrip("0")


def _format_number(value: Any, digits: int) -> str:
    """格式化有限数值。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    return f"{number:.{digits}f}" if math.isfinite(number) else "--"


def _escape_tex(text: str) -> str:
    """转义表格标签中的 TeX 特殊字符。"""

    replacements = {"&": r"\&", "%": r"\%", "_": r"\_", "#": r"\#"}
    return "".join(replacements.get(character, character) for character in text)


__all__ = ["write_subjective_table"]
