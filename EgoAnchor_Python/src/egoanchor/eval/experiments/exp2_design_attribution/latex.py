"""实验二的稳定 LaTeX 数字宏和归因汇总表。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, cast

import pandas as pd

from .contract import ABLATION_VARIANTS


_MACRO_METRICS = (
    (
        "CaptureAlignmentTranslationMedianDeltaMm",
        ABLATION_VARIANTS[0],
        "display_error.translation_error_mm_median",
        "display_error.",
    ),
    (
        "VCDTranslationMedianDeltaMm",
        ABLATION_VARIANTS[1],
        "display_error.translation_error_mm_median",
        "display_error.",
    ),
    (
        "TemporalVisibleResponseDeltaMs",
        ABLATION_VARIANTS[2],
        "transition.visible_response_time_ms",
        "transition.",
    ),
    (
        "StaticLockPositionHpRmsDeltaMm",
        ABLATION_VARIANTS[3],
        "static.position_hp_rms_mm",
        "static.",
    ),
)

_PAPER_SCENARIOS = {
    "static_head_motion": "Static target + head motion",
    "start_stop_6dof": "Start-stop 6DoF",
    "occlusion_recovery": "Occlusion + recovery",
}
"""论文表格使用的物理场景标签；CSV 继续保留稳定机器标识。"""

_PAPER_METRICS = {
    "display_error.translation_error_mm_median": "Display translation median (mm)",
    "transition.visible_response_time_ms": "Visible response time (ms)",
    "static.position_hp_rms_mm": "Static position HP-RMS (mm)",
}
"""论文表格使用的指标标签；避免把分析内部字段名暴露给读者。"""


def _format_number(value: object) -> str:
    """格式化有限浮点数，缺失值统一写作 ``--``。"""

    try:
        number = float(cast(Any, value))
    except (TypeError, ValueError):
        return "--"
    return format(number, ".4g") if math.isfinite(number) else "--"


def _metric(summary: pd.DataFrame, variant: str, preferred: str, prefix: str) -> str | None:
    """为一个消融选择冻结首选指标或同命名空间的稳定备选。"""

    required = {"variant_label", "metric"}
    if summary.empty or not required.issubset(summary.columns):
        return None
    rows = summary.loc[summary["variant_label"].astype(str).eq(variant)]
    available = set(rows["metric"].dropna().astype(str))
    if preferred in available:
        return preferred
    alternatives = sorted(name for name in available if name.startswith(prefix))
    return alternatives[0] if alternatives else None


def _delta(
    summary: pd.DataFrame,
    variant: str,
    preferred: str,
    prefix: str,
) -> str:
    """读取一个消融的跨 session 中位差。"""

    metric = _metric(summary, variant, preferred, prefix)
    required = {"variant_label", "metric", "delta_median"}
    if metric is None or not required.issubset(summary.columns):
        return "--"
    selected = pd.to_numeric(
        summary.loc[
            summary["variant_label"].astype(str).eq(variant)
            & summary["metric"].astype(str).eq(metric),
            "delta_median",
        ],
        errors="coerce",
    ).dropna()
    return _format_number(selected.median() if not selected.empty else None)


def write_exp2_latex(
    summary: pd.DataFrame,
    aurc: float,
    path: Path | str,
) -> None:
    """生成 ``EAExpTwo`` 前缀的归因数字宏。"""

    lines = [
        "% Auto-generated experiment-two numbers. Do not edit manually.",
        f"\\providecommand{{\\EAExpTwoAURC}}{{{_format_number(aurc)}}}",
    ]
    for suffix, variant, preferred, prefix in _MACRO_METRICS:
        lines.append(
            f"\\providecommand{{\\EAExpTwo{suffix}}}"
            f"{{{_delta(summary, variant, preferred, prefix)}}}"
        )
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_exp2_tables(summary: pd.DataFrame, path: Path | str) -> None:
    r"""把组件差值汇总写为可直接 ``\input`` 的 booktabs 表格。"""

    lines = [
        "% Auto-generated experiment-two table. Do not edit manually.",
        "\\begin{tabular}{lllrr}",
        "\\toprule",
        "Ablation & Source scenario & Outcome & Paired $n$ & Median delta \\\\",
        "\\midrule",
    ]
    wrote_row = False
    required = {"variant_label", "scenario_id", "metric", "paired_n", "delta_median"}
    if not summary.empty and required.issubset(summary.columns):
        for _, variant, preferred, prefix in _MACRO_METRICS:
            metric = _metric(summary, variant, preferred, prefix)
            if metric is None:
                continue
            rows = summary.loc[
                summary["variant_label"].astype(str).eq(variant)
                & summary["metric"].astype(str).eq(metric)
            ].sort_values("scenario_id", kind="stable")
            if rows.empty:
                continue
            row = rows.iloc[0]
            lines.append(
                f"{_escape_latex(variant)} & "
                f"{_escape_latex(_paper_scenario_label(str(row['scenario_id'])))} & "
                f"{_escape_latex(_paper_metric_label(metric))} & "
                f"{int(row['paired_n'])} & {_format_number(row['delta_median'])} \\\\"
            )
            wrote_row = True
    if not wrote_row:
        lines.append("No data & -- & -- & 0 & -- \\\\")
    lines.extend(("\\bottomrule", "\\end{tabular}"))

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _paper_scenario_label(scenario_id: str) -> str:
    """返回论文表格的场景标签，未知值仍保留原文用于审计。"""

    return _PAPER_SCENARIOS.get(scenario_id, scenario_id)


def _paper_metric_label(metric: str) -> str:
    """返回论文表格的指标标签，未知值仍保留原文用于审计。"""

    return _PAPER_METRICS.get(metric, metric)


def _escape_latex(value: str) -> str:
    """逐字符转义表格标签中的 LaTeX 特殊字符。"""

    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


__all__ = ["write_exp2_latex", "write_exp2_tables"]
