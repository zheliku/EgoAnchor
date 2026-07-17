"""实验一 LaTeX 数字宏和汇总表生成器。"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Mapping, cast

import pandas as pd

from .contract import VARIANTS


_NUMBER_METRICS = (
    ("TranslationMedianMm", "translation_error_mm_median", "median", 1.0),
    ("TranslationPNinetyFiveMm", "translation_error_mm_p95", "median", 1.0),
    ("RotationMedianDeg", "rotation_error_deg_median", "median", 1.0),
    ("RotationPNinetyFiveDeg", "rotation_error_deg_p95", "median", 1.0),
    ("DisplayCoveragePct", "display_coverage", "median", 100.0),
    ("OutputCoveragePct", "output_coverage", "median", 100.0),
    ("ObservationAgePFiftyMs", "observation_age_p50_ms", "median", 1.0),
    ("ObservationAgePNinetyFiveMs", "observation_age_p95_ms", "median", 1.0),
)


def _macro_part(value: object) -> str:
    """把系统显示名转换为合法且稳定的 TeX 命令片段。"""

    words = re.findall(r"[A-Za-z]+", str(value))
    return "".join(word[:1].upper() + word[1:] for word in words) or "Condition"


def _number(value: object, scale: float, format_spec: str = ".4g") -> str:
    """格式化单个分析数字；缺失和非有限值统一写作 ``--``。"""

    try:
        number = float(cast(Any, value)) * scale
    except (TypeError, ValueError):
        return "--"
    if not math.isfinite(number):
        return "--"
    return format(number, format_spec)


def _summary_value(
    summary: pd.DataFrame,
    variant: str,
    metric_name: str,
    statistic: str,
) -> object:
    """从条件长表读取指定系统、指标与汇总统计。"""

    required = {"variant_label", "metric_name", statistic}
    if summary.empty or not required.issubset(summary.columns):
        return None
    selected = summary.loc[
        summary["variant_label"].astype(str).eq(variant)
        & summary["metric_name"].astype(str).eq(metric_name),
        statistic,
    ]
    numeric = pd.to_numeric(selected, errors="coerce").dropna()
    return numeric.median() if not numeric.empty else None


def _trial_count(summary: pd.DataFrame, variant: str) -> str:
    """用该系统各指标中最大的有限 trial 数生成稳定样本量宏。"""

    required = {"variant_label", "metric_name", "trial_count"}
    if summary.empty or not required.issubset(summary.columns):
        return "--"
    selected = pd.to_numeric(
        summary.loc[
            summary["variant_label"].astype(str).eq(variant)
            & summary["metric_name"].astype(str).eq("translation_error_mm_median"),
            "trial_count",
        ],
        errors="coerce",
    ).dropna()
    return str(int(selected.sum())) if not selected.empty else "--"


def _write_numbers(summary: pd.DataFrame, path: Path, session_count: int | None) -> None:
    """为四个冻结系统写出相同的宏集合。"""

    lines = ["% Auto-generated experiment-one numbers. Do not edit manually."]
    if session_count is not None and session_count < 1:
        raise ValueError("实验一 LaTeX 发布的 session_count 必须为正整数。")
    lines.append(
        f"\\providecommand{{\\EAExpOneSessionCount}}"
        f"{{{session_count if session_count is not None else '--'}}}"
    )
    for variant in VARIANTS:
        prefix = f"EAExpOne{_macro_part(variant)}"
        lines.append(f"\\providecommand{{\\{prefix}NTrials}}{{{_trial_count(summary, variant)}}}")
        for suffix, metric_name, statistic, scale in _NUMBER_METRICS:
            raw_value = _summary_value(summary, variant, metric_name, statistic)
            value = _number(raw_value, scale)
            lines.append(f"\\providecommand{{\\{prefix}{suffix}}}{{{value}}}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_table(summary: pd.DataFrame, path: Path) -> None:
    """写出正文可直接 ``input`` 的紧凑系统汇总表。"""

    lines = [
        "% Auto-generated experiment-one table. Do not edit manually.",
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "System & Trans. (mm) & Rot. (deg) & Display (\\%) & Latency (ms) \\\\",
        "\\midrule",
    ]
    for variant in VARIANTS:
        values = (
            _number(_summary_value(summary, variant, "translation_error_mm_median", "median"), 1.0),
            _number(_summary_value(summary, variant, "rotation_error_deg_median", "median"), 1.0),
            _number(_summary_value(summary, variant, "display_coverage", "median"), 100.0),
            _number(_summary_value(summary, variant, "observation_age_p50_ms", "median"), 1.0),
        )
        lines.append(f"{variant} & {' & '.join(values)} \\\\")
    lines.extend(("\\bottomrule", "\\end{tabular}"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_exp1_latex(
    tables: Mapping[str, pd.DataFrame],
    output_dir: str | Path,
    *,
    session_count: int | None = None,
) -> list[Path]:
    """生成固定文件名、固定系统顺序的实验一 LaTeX 片段。"""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary = tables.get("exp1_condition_summary", pd.DataFrame())

    numbers_path = output / "exp1_numbers.tex"
    tables_path = output / "exp1_tables.tex"
    _write_numbers(summary, numbers_path, session_count)
    _write_table(summary, tables_path)
    return [numbers_path, tables_path]


__all__ = ["write_exp1_latex"]
