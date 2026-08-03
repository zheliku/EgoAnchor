"""实验三论文表格 TeX 的确定性生成。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from .contracts import MAIN_FAMILY, OUTCOME_LABELS, SCALE_FAMILY


_OUTCOME_LABELS_ZH = {
    "Q1": "静止稳定",
    "Q2": "运动附着",
    "Q3": "姿态一致",
    "Q4": "恢复一致",
    "Q5": "位置正确",
    "Q6": "依赖意愿",
    "Q7": "稳定--响应平衡",
    "AQ_EQ": "AQ 嵌入质量",
    "AQ_IQ": "AQ 交互质量",
    "TIA_RC": "TiA 可靠性/能力",
    "TIA_UP": "TiA 理解/可预测性",
    "STIAS": "S-TIAS",
}
"""中文工作稿中十二项冻结结局的紧凑显示名。"""


def write_subjective_table(
    destination: Path,
    results: pd.DataFrame,
) -> Path:
    """从唯一结果表按家族筛选，写入紧凑的论文主观评价表。"""

    output = destination.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "% 由 pixi run eval analyze exp3 自动生成；请勿手工修改。",
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{实验三十二项参与者内主观评价结果。区块级结局先在三个物体上取均值，"
        + r"TiA 与 S-TIAS 使用方法级单次施测得分；差值为 EgoAnchor$-$One-Euro。"
        + r"$p$ 值来自双侧条件精确 Wilcoxon 检验，并在两个预先固定的统计家族内作 Holm 校正。}",
        r"\label{tab:exp3-subjective}",
        r"\small",
        r"\setlength{\tabcolsep}{3.4pt}",
        r"\begin{tabular}{lccc}",
        r"\toprule",
        r"结局 & $\Delta$Mdn & $p_{\mathrm{Holm}}$ & $r_{rb}$ [95\% CI] \\",
        r"\midrule",
        r"\multicolumn{4}{l}{\emph{主证实家族}} \\",
    ]
    lines.extend(_result_rows(results[results["Family"] == MAIN_FAMILY]))
    lines.extend(
        [
            r"\midrule",
            r"\multicolumn{4}{l}{\emph{已发表量表家族}} \\",
        ]
    )
    lines.extend(_result_rows(results[results["Family"] == SCALE_FAMILY]))
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}", ""])
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def _result_rows(frame: pd.DataFrame) -> list[str]:
    """把一组结果转换为 TeX 表格行。"""

    rows: list[str] = []
    for _, row in frame.iterrows():
        outcome = str(row["Outcome"])
        label = _escape_tex(_OUTCOME_LABELS_ZH.get(outcome, OUTCOME_LABELS.get(outcome, outcome)))
        difference = _format_number(row.get("Difference_Median"), 2)
        p_value = _format_p(row.get("p_Holm"))
        effect = _format_effect(row)
        rows.append(
            f"{label} & {difference} & {p_value} & {effect}" + r" \\"
        )
    return rows


def _format_effect(row: pd.Series) -> str:
    """格式化匹配秩双列相关，并避免把边界退化区间伪报为置信区间。"""

    effect = _format_number(row.get("r_rb"), 2)
    if row.get("r_rb_CI_Status") == "degenerate_at_bound":
        return f"{effect}（全同向）"
    low = _format_number(row.get("r_rb_CI_Low"), 2)
    high = _format_number(row.get("r_rb_CI_High"), 2)
    return f"{effect} [{low}, {high}]"


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
