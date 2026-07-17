"""实验一 LaTeX 数字宏和按场景汇总表生成器。

旧实现把五个场景再取一次中位，得到会否定系统的混池数字。新实现按场景生成
宏和表格：每个场景各系统的平移中位/尾部与静止抖动都保留在场景内，正文因此
可以按“静止/遮挡稳定、连续运动有代价”的真实结构引用数字。
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Mapping, cast

import pandas as pd

from .contract import VARIANTS
from .metrics import SCENARIO_ORDER, build_scenario_headline


# 场景 → 稳定 TeX 宏片段（不含阿拉伯数字，避免 TeX 在数字处截断命令名）。
_SCENARIO_MACRO = {
    "static_head_motion": "Static",
    "start_stop_6dof": "StartStop",
    "continuous_translation": "ContTranslation",
    "continuous_rotation": "ContRotation",
    "occlusion_recovery": "Occlusion",
}

# 场景 → 论文表格展示名。
_SCENARIO_LABEL = {
    "static_head_motion": "Static + head motion",
    "start_stop_6dof": "Start--stop 6DoF",
    "continuous_translation": "Continuous translation",
    "continuous_rotation": "Continuous rotation",
    "occlusion_recovery": "Occlusion recovery",
}

# 每个场景/配置导出的宏后缀 → headline 列。
_SCENARIO_METRICS = (
    ("TranslationMedianMm", "translation_median_mm"),
    ("TranslationPNinetyFiveMm", "translation_p95_mm"),
    ("RotationMedianDeg", "rotation_median_deg"),
    ("RotationPNinetyFiveDeg", "rotation_p95_deg"),
    ("JitterHpRmsMm", "position_hp_rms_mm"),
)


def write_exp1_latex(
    tables: Mapping[str, pd.DataFrame],
    output_dir: str | Path,
    *,
    session_count: int | None = None,
) -> list[Path]:
    """生成固定文件名、按场景组织的实验一 LaTeX 片段。"""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    headline = build_scenario_headline(dict(tables))

    numbers_path = output / "exp1_numbers.tex"
    tables_path = output / "exp1_tables.tex"
    _write_numbers(headline, numbers_path, session_count)
    _append_runtime_numbers(dict(tables), numbers_path)
    _append_abstract_summary(headline, dict(tables), numbers_path)
    _write_table(headline, tables_path)
    return [numbers_path, tables_path]


def _append_runtime_numbers(tables: Mapping[str, pd.DataFrame], path: Path) -> None:
    """追加与场景无关的运行时时效性宏（观测年龄 P50/P95）。

    观测年龄反映各配置的时间语义（到达时刻保持 vs 采集时刻插值使用历史控制点），
    是相对场景稳定的运行时属性，因此按配置在场景间取中位是正当的，不会掩盖任何
    以场景为条件的精度权衡。
    """

    latency = tables.get("exp1_latency_summary", pd.DataFrame())
    lines: list[str] = ["% Runtime timing macros (scenario-independent)."]
    for variant in VARIANTS:
        prefix = f"EAExpOne{_macro_part(variant)}"
        p50 = _pooled_median(latency, variant, "observation_age_p50_ms")
        p95 = _pooled_median(latency, variant, "observation_age_p95_ms")
        lines.append(
            f"\\providecommand{{\\{prefix}ObservationAgePFiftyMs}}{{{_number(p50)}}}"
        )
        lines.append(
            f"\\providecommand{{\\{prefix}ObservationAgePNinetyFiveMs}}{{{_number(p95)}}}"
        )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _pooled_median(latency: pd.DataFrame, variant: str, column: str) -> float:
    """跨场景对一个配置的运行时时延取中位；缺失返回 NaN。"""

    required = {"variant_label", column}
    if latency.empty or not required.issubset(latency.columns):
        return float("nan")
    selected = pd.to_numeric(
        latency.loc[latency["variant_label"].astype(str).eq(variant), column],
        errors="coerce",
    ).dropna()
    return float(selected.median()) if not selected.empty else float("nan")


def _append_abstract_summary(
    headline: pd.DataFrame,
    tables: Mapping[str, pd.DataFrame],
    path: Path,
) -> None:
    """追加跨场景池化的摘要级宏，供 abstract 引用。

    摘要需要高度概括的数字，按配置跨场景取中位虽然掩盖场景条件差异，但在
    abstract 语境是可接受的。这些宏不应在结果章节使用——结果章节必须用
    按场景宏以如实呈现权衡。
    """

    condition = tables.get("exp1_condition_summary", pd.DataFrame())
    lines: list[str] = ["% Abstract-level pooled summary (use in abstract only)."]

    # EgoAnchor 的跨场景中位 trial 数、覆盖率、平移/旋转误差。
    variant = "EgoAnchor"
    prefix = f"EAExpOne{_macro_part(variant)}"

    trial_count = _trial_count_pooled(condition, variant)
    lines.append(f"\\providecommand{{\\{prefix}NTrials}}{{{trial_count}}}")

    display_cov = _pooled_headline_median(headline, variant, "display_coverage") * 100
    lines.append(f"\\providecommand{{\\{prefix}DisplayCoveragePct}}{{{_int_or_dash(display_cov)}}}")

    trans_median = _pooled_headline_median(headline, variant, "translation_median_mm")
    lines.append(f"\\providecommand{{\\{prefix}TranslationMedianMm}}{{{_number(trans_median)}}}")

    rot_median = _pooled_headline_median(headline, variant, "rotation_median_deg")
    lines.append(f"\\providecommand{{\\{prefix}RotationMedianDeg}}{{{_number(rot_median)}}}")

    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _trial_count_pooled(condition: pd.DataFrame, variant: str) -> int:
    """跨场景对一个配置的 trial 总数求和；缺失返回 0。"""

    required = {"variant_label", "metric_name", "trial_count"}
    if condition.empty or not required.issubset(condition.columns):
        return 0
    selected = pd.to_numeric(
        condition.loc[
            condition["variant_label"].astype(str).eq(variant)
            & condition["metric_name"].astype(str).eq("translation_error_mm_median"),
            "trial_count",
        ],
        errors="coerce",
    ).dropna()
    return int(selected.sum()) if not selected.empty else 0


def _pooled_headline_median(headline: pd.DataFrame, variant: str, column: str) -> float:
    """跨场景对一个配置的 headline 指标取中位；缺失返回 NaN。"""

    required = {"variant_label", column}
    if headline.empty or not required.issubset(headline.columns):
        return float("nan")
    selected = pd.to_numeric(
        headline.loc[headline["variant_label"].astype(str).eq(variant), column],
        errors="coerce",
    ).dropna()
    return float(selected.median()) if not selected.empty else float("nan")


def _write_numbers(headline: pd.DataFrame, path: Path, session_count: int | None) -> None:
    """为每个场景×配置写出按场景的误差与抖动宏。"""

    if session_count is not None and session_count < 1:
        raise ValueError("实验一 LaTeX 发布的 session_count 必须为正整数。")
    lines = ["% Auto-generated experiment-one numbers. Do not edit manually."]
    lines.append(
        f"\\providecommand{{\\EAExpOneSessionCount}}"
        f"{{{session_count if session_count is not None else '--'}}}"
    )
    lines.append(
        f"\\providecommand{{\\EAExpOneScenarioCount}}{{{len(SCENARIO_ORDER)}}}"
    )
    for scenario in SCENARIO_ORDER:
        scenario_rows = headline.loc[headline["scenario_id"].astype(str).eq(scenario)]
        scenario_macro = _SCENARIO_MACRO[scenario]
        for variant in VARIANTS:
            prefix = f"EAExpOne{_macro_part(variant)}{scenario_macro}"
            trials = _headline_value(scenario_rows, variant, "trial_count")
            lines.append(
                f"\\providecommand{{\\{prefix}NTrials}}{{{_int_or_dash(trials)}}}"
            )
            for suffix, column in _SCENARIO_METRICS:
                value = _headline_value(scenario_rows, variant, column)
                lines.append(f"\\providecommand{{\\{prefix}{suffix}}}{{{_number(value)}}}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_table(headline: pd.DataFrame, path: Path) -> None:
    r"""写出正文可 ``\input`` 的按场景平移中位/P95/抖动汇总表。

    列为四配置，行按场景分组，每个场景给出平移中位(mm)、P95(mm)与静止抖动
    HP-RMS(mm)；连续运动场景不做隐藏，读者可直接看到 EgoAnchor 的权衡结构。
    """

    header_variants = " & ".join(_short_variant(variant) for variant in VARIANTS)
    lines = [
        "% Auto-generated experiment-one table. Do not edit manually.",
        "\\begin{tabular}{ll" + "r" * len(VARIANTS) + "}",
        "\\toprule",
        f"Scenario & Metric & {header_variants} \\\\",
        "\\midrule",
    ]
    metric_rows = (
        ("Trans. median (mm)", "translation_median_mm", False),
        ("Trans. P95 (mm)", "translation_p95_mm", False),
        ("Jitter HP-RMS (mm)", "position_hp_rms_mm", False),
    )
    for scenario_index, scenario in enumerate(SCENARIO_ORDER):
        scenario_rows = headline.loc[headline["scenario_id"].astype(str).eq(scenario)]
        label = _SCENARIO_LABEL[scenario]
        for metric_index, (metric_label, column, _) in enumerate(metric_rows):
            values = [
                _headline_value(scenario_rows, variant, column) for variant in VARIANTS
            ]
            cells = _format_row_with_best(values)
            scenario_cell = f"\\multirow{{{len(metric_rows)}}}{{*}}{{{label}}}" if metric_index == 0 else ""
            lines.append(f"{scenario_cell} & {metric_label} & {' & '.join(cells)} \\\\")
        if scenario_index != len(SCENARIO_ORDER) - 1:
            lines.append("\\midrule")
    lines.extend(("\\bottomrule", "\\end{tabular}"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_row_with_best(values: list[float]) -> list[str]:
    """格式化一行数值，并对最小（最优）有限值加粗。"""

    finite = [(index, value) for index, value in enumerate(values) if _finite(value)]
    best_index = min(finite, key=lambda item: item[1])[0] if finite else -1
    cells: list[str] = []
    for index, value in enumerate(values):
        text = _number(value)
        cells.append(f"\\textbf{{{text}}}" if index == best_index and text != "--" else text)
    return cells


def _macro_part(value: object) -> str:
    """把系统显示名转换为合法且稳定的 TeX 命令片段。"""

    words = re.findall(r"[A-Za-z]+", str(value))
    return "".join(word[:1].upper() + word[1:] for word in words) or "Condition"


def _short_variant(variant: str) -> str:
    """返回表头用的紧凑配置名。"""

    return {
        "Arrival-Hold": "Arrival",
        "Capture-Hold": "Capture",
        "One-Euro Anchor": "One-Euro",
        "EgoAnchor": "EgoAnchor",
    }.get(variant, variant)


def _headline_value(scenario_rows: pd.DataFrame, variant: str, column: str) -> float:
    """从场景切片读取一个配置的展示指标；缺失返回 NaN。"""

    if scenario_rows.empty or column not in scenario_rows.columns:
        return float("nan")
    selected = pd.to_numeric(
        scenario_rows.loc[scenario_rows["variant_label"].astype(str).eq(variant), column],
        errors="coerce",
    ).dropna()
    return float(selected.iloc[0]) if not selected.empty else float("nan")


def _number(value: object, format_spec: str = ".3g") -> str:
    """格式化单个分析数字；缺失和非有限值统一写作 ``--``。"""

    try:
        number = float(cast(Any, value))
    except (TypeError, ValueError):
        return "--"
    if not math.isfinite(number):
        return "--"
    return format(number, format_spec)


def _int_or_dash(value: object) -> str:
    """把有限计数格式化为整数，缺失写作 ``--``。"""

    try:
        number = float(cast(Any, value))
    except (TypeError, ValueError):
        return "--"
    return str(int(number)) if math.isfinite(number) else "--"


def _finite(value: object) -> bool:
    """判断值是否为有限数值。"""

    try:
        return math.isfinite(float(cast(Any, value)))
    except (TypeError, ValueError):
        return False


__all__ = ["write_exp1_latex"]
