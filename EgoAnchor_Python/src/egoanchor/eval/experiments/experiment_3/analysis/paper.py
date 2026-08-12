"""实验三论文表格 TeX 的确定性生成。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from .contracts import MAIN_FAMILY, OUTCOME_LABELS, PRIMARY_OUTCOMES, SCALE_FAMILY


_OUTCOME_LABELS_ZH = {
    "Q1": "静止稳定",
    "Q2": "运动附着",
    "Q3": "姿态一致",
    "Q4": "恢复一致",
    "Q5": "位置正确",
    "Q6": "依赖意愿",
    "Q7": "稳定--响应平衡",
    "AQ_EQ": "AQ嵌入质量",
    "AQ_IQ": "AQ交互质量",
    "TIA_RC": "TiA可靠性/能力",
    "TIA_UP": "TiA理解/可预测性",
    "STIAS": "S-TIAS",
}
"""中文工作稿中十二项冻结结局的紧凑显示名。

结局列按自然宽度排版（``l`` 而非 ``tabularx`` 的 ``X``），最长的
``TiA理解/可预测性`` 定出该列 72.93~pt，列内不再折行，因此不需要
``\\allowbreak\\mbox{}`` 钉折行位置。
"""

_ITEM_BLOCKS = (
    ("阶段锚点行为", ("Q1", "Q2", "Q3", "Q4")),
    ("整体锚定判断", ("Q5", "Q6", "Q7")),
)
"""对象锚定条目在表中的两个子块：逐阶段行为与跨阶段整体判断。

分块只作陈述分组，与 ``MAIN_FAMILY`` 的 Holm 校正口径无关；校正仍在
七项条目构成的同一家族内进行。
"""

_SCALE_BLOCKS = (
    ("增强质量", ("AQ_EQ", "AQ_IQ")),
    ("信任", ("TIA_RC", "TIA_UP", "STIAS")),
)
"""已发表量表在表中的两个子块：增强质量与信任。

与 §6.3.2「增强质量与信任」的两个 \\textbf 段落标题完全对应。
分块只作陈述分组，与 ``SCALE_FAMILY`` 的 Holm 校正口径无关；校正仍在
五项量表构成的同一家族内进行。
"""


def write_subjective_table(
    destination: Path,
    results: pd.DataFrame,
) -> Path:
    """从唯一结果表按家族筛选，写入紧凑的论文主观评价表。"""

    output = destination.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    blocks = _validated_item_blocks()
    main = results[results["Family"] == MAIN_FAMILY]
    lines = [
        "% 由 pixi run eval analyze exp3 自动生成；请勿手工修改。",
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{实验三的十二项参与者内主观结果，按第~\ref{sec:exp3-design}~节的测量结构分组。"
        + r"对象锚定条目与 AQ 子量表先在三个物体上取条件级均值，TiA 与 S-TIAS 为方法级单次施测。"
        + r"中位数列按 One-Euro / EgoAnchor 顺序给出，"
        + r"$W$ 与 $p_{\mathrm{adj}}$ 为 Wilcoxon 符号秩检验统计量及家族内 Holm 校正后的 $p$ 值，"
        + r"$r_{\mathrm{rb}}$ 为匹配秩双列相关，正值表示 EgoAnchor 更高。"
        + r"TiA 用五点量尺，其余用七点量尺；箭头表示得分越高评价越正向。"
        + _sample_note(results)
        + r"分布见图~\ref{fig:exp3-subjective}。}",
        r"\label{tab:exp3-subjective}",
        # 与实验一三张表同一体例：单栏、模板字号、按自然宽度排版，不横向撑满，
        # 唯一的控宽手段是列距。实测（\columnwidth 240.94~pt）五列净宽合计
        # 219.14~pt，模板 6~pt 列距下为 267.14~pt、超出 26.20~pt，收到 2~pt 得
        # 235.14~pt。最宽的是结局列 72.93~pt，其次 95% CI 列 53.49~pt 与中位数
        # 列 47.49~pt，$W$ 与 $p$ 两列各约 20--25~pt。
        r"\setlength{\tabcolsep}{2pt}",
        r"\begin{tabular}{@{}lcccc@{}}",
        r"\toprule",
        r"结局 & \shortstack{One-Euro /\\EgoAnchor\,$\uparrow$}"
        + r" & $W$ & $p_{\mathrm{adj}}$"
        + r" & \shortstack{$r_{\mathrm{rb}}$\\{[}95\% CI{]}} \\",
        r"\midrule",
    ]
    for index, (block_label, outcomes) in enumerate(blocks):
        if index:
            lines.append(r"\addlinespace")
        lines.append(rf"\multicolumn{{5}}{{@{{}}l}}{{\textit{{{block_label}}}}} \\")
        lines.extend(_result_rows(main[main["Outcome"].isin(outcomes)]))

    scale_blocks = _validated_scale_blocks()
    scales = results[results["Family"] == SCALE_FAMILY]
    for index, (block_label, outcomes) in enumerate(scale_blocks):
        if index == 0:
            lines.append(r"\midrule")
        else:
            lines.append(r"\addlinespace")
        lines.append(rf"\multicolumn{{5}}{{@{{}}l}}{{\textit{{{block_label}}}}} \\")
        lines.extend(_result_rows(scales[scales["Outcome"].isin(outcomes)]))

    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def _validated_item_blocks() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """要求条目子块无重复地覆盖全部冻结的七项对象锚定条目。"""

    outcomes = tuple(
        outcome for block in _ITEM_BLOCKS for outcome in block[1]
    )
    if set(outcomes) != set(PRIMARY_OUTCOMES):
        raise ValueError("条目子块必须无重复地覆盖全部七项对象锚定条目")
    return _ITEM_BLOCKS


def _validated_scale_blocks() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """要求量表子块无重复地覆盖全部冻结的五项已发表量表。"""

    from .contracts import SCALE_OUTCOMES

    outcomes = tuple(
        outcome for block in _SCALE_BLOCKS for outcome in block[1]
    )
    if set(outcomes) != set(SCALE_OUTCOMES):
        raise ValueError("量表子块必须无重复地覆盖全部五项已发表量表")
    return _SCALE_BLOCKS


def _sample_note(results: pd.DataFrame) -> str:
    """写出配对样本量脚注，配对数由数据计算而非写死。"""

    paired = pd.to_numeric(results.get("N"), errors="coerce").dropna()
    nonzero = pd.to_numeric(results.get("N_Nonzero"), errors="coerce").dropna()
    if paired.empty or nonzero.empty:
        raise ValueError("论文表缺少配对样本量：N 或 N_Nonzero")
    if paired.nunique() != 1:
        raise ValueError("配对样本量在各结局间不一致，脚注口径需重新裁定")
    total = int(paired.iloc[0])
    # 正文已给出 (N=24)，故只声明配对完整性与零差口径，不再把逐结局的非零差
    # 范围拉回 caption——该数字容易被误读为样本量缩减。
    note = f"所有结局均有 {total} 组完整配对；零差不进入 Wilcoxon 秩统计。"
    status = results["r_rb_CI_Status"] if "r_rb_CI_Status" in results else pd.Series(dtype=object)
    if bool((status == "degenerate_at_bound").any()):
        note += (
            r"标 $\dagger$ 的结局全部非零配对差同向，$r_{\mathrm{rb}}$ 取到边界值，"
            r"故不报告自举置信区间。"
        )
    return note


def _result_rows(frame: pd.DataFrame) -> list[str]:
    """把一组结果转换为 TeX 表格行，两种方法的中位数合并为一列。"""

    rows: list[str] = []
    for _, row in frame.iterrows():
        outcome = str(row["Outcome"])
        label = _escape_tex(_OUTCOME_LABELS_ZH.get(outcome, OUTCOME_LABELS.get(outcome, outcome)))
        one_euro = _format_signed(row.get("OneEuro_Median"))
        egoanchor = _format_signed(row.get("EgoAnchor_Median"))
        statistic = _format_statistic(row.get("W"))
        p_value = _format_p(row.get("p_Holm"))
        effect = _format_effect(row)
        rows.append(
            f"{label} & {one_euro} / {egoanchor} & {statistic} & "
            f"{p_value} & {effect}" + r" \\"
        )
    return rows


def _format_statistic(value: Any) -> str:
    """格式化 Wilcoxon 统计量，半整数保留一位小数，整数不补零。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if not math.isfinite(number):
        return "--"
    return f"{number:g}"


def _format_signed(value: Any) -> str:
    """格式化保留整数位的数值，负号用数学减号而非连字符排版。"""

    formatted = _format_number(value, 2)
    return "$-$" + formatted[1:] if formatted.startswith("-") else formatted


def _format_effect(row: pd.Series) -> str:
    """格式化匹配秩双列相关，并避免把边界退化区间伪报为置信区间。"""

    effect = _format_bounded(row.get("r_rb"))
    if row.get("r_rb_CI_Status") == "degenerate_at_bound":
        return f"{effect}$^{{\\dagger}}$"
    low = _format_bounded(row.get("r_rb_CI_Low"))
    high = _format_bounded(row.get("r_rb_CI_High"))
    return f"{effect} [{low}, {high}]"


def _format_bounded(value: Any) -> str:
    """格式化取值域含 $\\pm 1$ 的统计量，按惯例省去整数位前导零。"""

    formatted = _format_number(value, 2)
    if formatted == "--":
        return formatted
    if formatted.startswith("0."):
        return formatted[1:]
    if formatted.startswith("-0."):
        return "$-$" + formatted[2:]
    return formatted


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
