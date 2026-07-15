"""实验一的论文 PDF 图表生成器。"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import matplotlib
import pandas as pd

from .contract import VARIANTS

matplotlib.use("Agg")
import matplotlib.pyplot as plt


# 四种颜色与系统顺序一一对应，所有图都复用该映射，避免结果排序改变语义颜色。
_VARIANT_COLORS = dict(
    zip(VARIANTS, ("#4C78A8", "#F58518", "#54A24B", "#E45756"), strict=True)
)

_FIGURE_SPECS = (
    (
        "exp1_static_timeline.pdf",
        "Static quality",
        "exp1_static_quality",
        "translation_error_mm_median",
        "Translation error (mm)",
        1.0,
        None,
    ),
    (
        "exp1_motion_timeline.pdf",
        "Transition response",
        "exp1_transition_response",
        "peak_translation_error_mm",
        "Peak translation error (mm)",
        1.0,
        None,
    ),
    (
        "exp1_occlusion_recovery.pdf",
        "Occlusion recovery",
        "exp1_occlusion_recovery",
        "display_availability",
        "Display availability (%)",
        100.0,
        None,
    ),
    (
        "exp1_system_summary.pdf",
        "System summary",
        "exp1_condition_summary",
        "median",
        "Translation error (mm)",
        1.0,
        "translation_error_mm_median",
    ),
)


def _variant_values(
    table: pd.DataFrame,
    metric: str,
    scale: float,
    metric_name: str | None,
) -> list[float]:
    """按冻结系统顺序提取指标均值，缺失条件保留为空值。"""

    if metric_name is not None:
        if "metric_name" not in table:
            return [float("nan")] * len(VARIANTS)
        table = table.loc[table["metric_name"].astype(str).eq(metric_name)]
    if table.empty or "variant_label" not in table or metric not in table:
        return [float("nan")] * len(VARIANTS)

    labels = table["variant_label"].astype(str)
    values: list[float] = []
    for variant in VARIANTS:
        selected = pd.to_numeric(table.loc[labels == variant, metric], errors="coerce")
        values.append(float(selected.median() * scale) if selected.notna().any() else float("nan"))
    return values


def _draw_variant_bars(
    ax: plt.Axes,
    table: pd.DataFrame,
    metric: str,
    ylabel: str,
    scale: float,
    metric_name: str | None,
) -> None:
    """用固定类别顺序和固定颜色绘制系统对比柱。"""

    values = _variant_values(table, metric, scale, metric_name)
    for index, (variant, value) in enumerate(zip(VARIANTS, values, strict=True)):
        ax.bar(index, value, color=_VARIANT_COLORS[variant], label=variant, width=0.72)

    ax.set_xticks(range(len(VARIANTS)), ("Arrival", "Capture", "One-Euro", "EgoAnchor"))
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)


def write_exp1_figures(
    render: pd.DataFrame,
    tables: Mapping[str, pd.DataFrame],
    output_dir: str | Path,
) -> list[Path]:
    """按固定契约生成四个实验一 PDF；无有效值时仍保留完整类别骨架。"""

    del render  # 当前论文图只消费分析层公开表，保留参数以稳定调用接口。
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    for filename, title, table_name, metric, ylabel, scale, metric_name in _FIGURE_SPECS:
        figure, axes = plt.subplots(figsize=(7.0, 4.0))
        table = tables.get(table_name, pd.DataFrame())
        _draw_variant_bars(axes, table, metric, ylabel, scale, metric_name)
        handles, labels = axes.get_legend_handles_labels()
        figure.suptitle(title, y=0.98)
        figure.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.91),
            frameon=False,
            fontsize=8,
            ncols=len(VARIANTS),
        )
        figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.82))

        path = output / filename
        figure.savefig(path, format="pdf")
        plt.close(figure)
        paths.append(path)

    return paths


__all__ = ["write_exp1_figures"]
