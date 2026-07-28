"""从实验三结果工作簿生成论文结果小多图。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

from egoanchor.visuals import EGOANCHOR_COLOR_HEX, ONE_EURO_COLOR_HEX

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from .contracts import (
    EGOANCHOR,
    METHOD_LABELS,
    OBJECTS,
    OBJECT_LABELS,
    ONE_EURO,
    OUTCOME_LABELS,
    SCALE_OUTCOMES,
)
from .settings import AnalysisSettings


_COLORS = {ONE_EURO: ONE_EURO_COLOR_HEX, EGOANCHOR: EGOANCHOR_COLOR_HEX}
_GRID_COLOR = "#E4E7EA"
_TEXT_COLOR = "#202428"
_METHOD_ORDER = (ONE_EURO, EGOANCHOR)
_PAIRED_OUTCOMES = ("Q1", "Q8", "Q3", "Q6")
_SCALE_FIGURE_OUTCOMES = ("Q6", "Q7", "AQ_EQ", "AQ_IQ", "TIA_RC", "TIA_UP", "STIAS")
"""论文图的固定方法、结局顺序与视觉编码。"""


def publish_figures(
    results_workbook: Path,
    output_root: Path,
    settings: AnalysisSettings,
) -> dict[str, Path]:
    """只读结果 XLSX，生成冻结四面板与量表小多图的 PNG/PDF。"""

    source = results_workbook.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"实验三结果工作簿不存在：{source}")
    paired_data = pd.read_excel(source, sheet_name="Plot_Paired", engine="openpyxl")
    scale_data = pd.read_excel(source, sheet_name="Plot_Scales", engine="openpyxl")
    primary_results = pd.read_excel(source, sheet_name="Main_Results", engine="openpyxl")
    scale_results = pd.read_excel(source, sheet_name="Scale_Results", engine="openpyxl")
    _validate_plot_data(paired_data, _PAIRED_OUTCOMES, "Plot_Paired", require_object=True)
    _validate_plot_data(scale_data, _SCALE_FIGURE_OUTCOMES, "Plot_Scales")
    figure_root = output_root.expanduser().resolve() / "figures"
    figure_root.mkdir(parents=True, exist_ok=True)
    _configure(settings.figure_dpi)
    paired_figure = _paired_figure(paired_data, primary_results, settings)
    paired_paths = _save_pair(paired_figure, figure_root, "figure4_exp3_paired")
    scale_figure = _scale_figure(scale_data, primary_results, scale_results, settings)
    scale_paths = _save_pair(scale_figure, figure_root, "figure5_exp3_scales")
    return {
        "paired_png": paired_paths[0],
        "paired_pdf": paired_paths[1],
        "scales_png": scale_paths[0],
        "scales_pdf": scale_paths[1],
    }


def _configure(dpi: int) -> None:
    """应用双栏论文尺寸下仍可读的字体和矢量导出参数。"""

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7.1,
            "axes.labelcolor": _TEXT_COLOR,
            "axes.labelsize": 7.1,
            "axes.titlesize": 7.6,
            "axes.titlepad": 5.5,
            "axes.linewidth": 0.65,
            "axes.edgecolor": "#70767C",
            "xtick.color": _TEXT_COLOR,
            "xtick.labelsize": 6.6,
            "ytick.color": _TEXT_COLOR,
            "ytick.labelsize": 6.6,
            "legend.fontsize": 6.9,
            "savefig.dpi": dpi,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def _paired_figure(
    data: pd.DataFrame,
    results: pd.DataFrame,
    settings: AnalysisSettings,
) -> Any:
    """绘制按物体展开的四项冻结主图结局。"""

    figure, axes = plt.subplots(2, 2, figsize=settings.primary_figure_size, sharey=True)
    result_map = results.set_index("Outcome")
    for panel_index, (axis, outcome) in enumerate(
        zip(axes.flat, _PAIRED_OUTCOMES, strict=True)
    ):
        _draw_object_panel(axis, data[data["Outcome"] == outcome])
        axis.set_title(
            f"{chr(97 + panel_index)}) {OUTCOME_LABELS[outcome]} ({outcome})",
            loc="left",
            fontweight="bold",
            color=_TEXT_COLOR,
        )
        if panel_index % 2 == 0:
            axis.set_ylabel("Agreement (1–7)")
        if outcome in result_map.index:
            _draw_global_result(axis, result_map.loc[outcome])
    figure.legend(
        handles=_method_handles(include_mean=True),
        loc="upper center",
        ncol=3,
        frameon=False,
        bbox_to_anchor=(0.5, 0.995),
        handlelength=1.4,
        columnspacing=1.35,
    )
    figure.subplots_adjust(
        left=0.064,
        right=0.995,
        bottom=0.085,
        top=0.88,
        wspace=0.15,
        hspace=0.36,
    )
    return figure


def _draw_object_panel(axis: Any, data: pd.DataFrame) -> None:
    """按三个物体绘制原始点、箱线和均值。"""

    for object_index, object_key in enumerate(OBJECTS):
        subset = data[data["Object_Key"] == object_key]
        pivot = subset.pivot_table(
            index="Participant_ID",
            columns="Condition",
            values="Value",
            aggfunc="first",
        )
        if not set(_METHOD_ORDER).issubset(pivot.columns):
            continue
        paired = pivot.dropna(subset=list(_METHOD_ORDER)).sort_index()
        if paired.empty:
            continue
        jitter = _symmetric_jitter(len(paired), 0.043)
        left_positions = object_index - 0.18 + jitter
        right_positions = object_index + 0.18 + jitter
        _draw_distribution(
            axis,
            paired[ONE_EURO].to_numpy(dtype=float),
            object_index - 0.18,
            _COLORS[ONE_EURO],
            left_positions,
        )
        _draw_distribution(
            axis,
            paired[EGOANCHOR].to_numpy(dtype=float),
            object_index + 0.18,
            _COLORS[EGOANCHOR],
            right_positions,
        )
    axis.set_xlim(-0.55, len(OBJECTS) - 0.45)
    axis.set_ylim(0.72, 8.42)
    axis.set_yticks(range(1, 8))
    axis.set_xticks(range(len(OBJECTS)), [OBJECT_LABELS[item] for item in OBJECTS])
    _clean_axis(axis)


def _draw_global_result(axis: Any, result: pd.Series) -> None:
    """在面板右上角紧凑标出跨三物体主检验与匹配秩效应量。"""

    p_text = _format_p(result.get("p_Holm"))
    effect = _format_number(result.get("r_rb"), 2)
    low = _format_number(result.get("r_rb_CI_Low"), 2)
    high = _format_number(result.get("r_rb_CI_High"), 2)
    axis.text(
        0.985,
        0.975,
        f"Holm p {p_text}  {_significance_label(result.get('p_Holm'))}"
        f"   $r_{{rb}}$={effect} [{low}, {high}]",
        transform=axis.transAxes,
        ha="right",
        va="top",
        fontsize=6.15,
        color="#4A5056",
    )


def _scale_figure(
    data: pd.DataFrame,
    primary_results: pd.DataFrame,
    scale_results: pd.DataFrame,
    settings: AnalysisSettings,
) -> Any:
    """绘制 Q6/Q7 和五项已发表量表的原生尺度小多图。"""

    figure, axes = plt.subplots(2, 4, figsize=settings.scales_figure_size)
    results = pd.concat(
        (
            primary_results[primary_results["Outcome"].isin(("Q6", "Q7"))],
            scale_results,
        ),
        ignore_index=True,
    )
    result_map = results.set_index("Outcome")
    for panel_index, (axis, outcome) in enumerate(
        zip(axes.flat[:7], _SCALE_FIGURE_OUTCOMES, strict=True)
    ):
        upper = 5.0 if outcome.startswith("TIA_") else 7.0
        _draw_method_panel(axis, data[data["Outcome"] == outcome], upper=upper)
        axis.set_title(
            f"{chr(97 + panel_index)}) {_short_outcome_label(outcome)}",
            loc="left",
            fontweight="bold",
            color=_TEXT_COLOR,
        )
        if panel_index in (0, 4):
            axis.set_ylabel(f"Score (1–{int(upper)})")
        if outcome in result_map.index:
            _significance_bracket(axis, result_map.loc[outcome].get("p_Holm"), upper)
            axis.text(
                0.97,
                0.045,
                f"$r_{{rb}}$={_format_number(result_map.loc[outcome].get('r_rb'), 2)}",
                transform=axis.transAxes,
                ha="right",
                va="bottom",
                fontsize=6.1,
                color="#4A5158",
            )
    _draw_legend_panel(axes.flat[7])
    figure.subplots_adjust(
        left=0.062,
        right=0.995,
        bottom=0.09,
        top=0.96,
        wspace=0.20,
        hspace=0.38,
    )
    return figure


def _draw_method_panel(axis: Any, data: pd.DataFrame, *, upper: float) -> None:
    """绘制参与者级原始点和两组箱线。"""

    pivot = data.pivot_table(
        index="Participant_ID",
        columns="Condition",
        values="Value",
        aggfunc="first",
    )
    if not set(_METHOD_ORDER).issubset(pivot.columns):
        return
    paired = pivot.dropna(subset=list(_METHOD_ORDER)).sort_index()
    if paired.empty:
        return
    jitter = _symmetric_jitter(len(paired), 0.105)
    left_positions = jitter
    right_positions = 1.0 + jitter
    _draw_distribution(
        axis,
        paired[ONE_EURO].to_numpy(dtype=float),
        0.0,
        _COLORS[ONE_EURO],
        left_positions,
    )
    _draw_distribution(
        axis,
        paired[EGOANCHOR].to_numpy(dtype=float),
        1.0,
        _COLORS[EGOANCHOR],
        right_positions,
    )
    extra = 1.05 if upper == 7.0 else 0.90
    axis.set_xlim(-0.48, 1.48)
    axis.set_ylim(0.72, upper + extra)
    axis.set_yticks(np.arange(1, int(upper) + 1))
    axis.set_xticks((0, 1), ("One-Euro", "EgoAnchor"))
    for tick, method in zip(axis.get_xticklabels(), _METHOD_ORDER, strict=True):
        tick.set_color(_COLORS[method])
        tick.set_fontweight("bold")
    _clean_axis(axis)


def _draw_distribution(
    axis: Any,
    values: np.ndarray,
    position: float,
    color: str,
    point_positions: np.ndarray,
) -> None:
    """绘制一组原始点、箱线和空心均值圆点。"""

    axis.scatter(
        point_positions,
        values,
        s=9.5,
        facecolor=color,
        edgecolor="white",
        linewidth=0.28,
        alpha=0.70,
        zorder=4,
    )
    box = axis.boxplot(
        [values],
        positions=[position],
        widths=0.25,
        patch_artist=True,
        showfliers=False,
        whis=1.5,
        boxprops={
            "facecolor": color,
            "edgecolor": color,
            "linewidth": 0.9,
            "alpha": 0.30,
        },
        medianprops={"color": _TEXT_COLOR, "linewidth": 1.15},
        whiskerprops={"color": color, "linewidth": 0.75},
        capprops={"color": color, "linewidth": 0.75},
    )
    for patch in box["boxes"]:
        patch.set_zorder(3)
    axis.scatter(
        [position],
        [float(np.mean(values))],
        s=18,
        marker="o",
        facecolor="white",
        edgecolor=color,
        linewidth=0.95,
        zorder=6,
    )


def _significance_bracket(axis: Any, value: Any, upper: float) -> None:
    """在两方法箱线之上画 Holm 校正显著性括号。"""

    y = upper + (0.26 if upper == 7.0 else 0.22)
    height = 0.10 if upper == 7.0 else 0.08
    axis.plot(
        [0.04, 0.04, 0.96, 0.96],
        [y, y + height, y + height, y],
        color="#3C4248",
        linewidth=0.70,
        clip_on=False,
        zorder=6,
    )
    axis.text(
        0.5,
        y + height + 0.025,
        _significance_label(value),
        ha="center",
        va="bottom",
        fontsize=6.8,
        fontweight="bold",
        color=_TEXT_COLOR,
    )


def _draw_legend_panel(axis: Any) -> None:
    """在量表图空余面板集中放置视觉编码。"""

    axis.axis("off")
    axis.legend(
        handles=_method_handles(include_mean=True),
        loc="upper left",
        frameon=False,
        borderaxespad=0.0,
        handlelength=1.6,
        labelspacing=0.85,
    )
    axis.text(
        0.0,
        0.34,
        "Circle: mean; bar: median\nBracket: Holm-adjusted p",
        transform=axis.transAxes,
        ha="left",
        va="top",
        fontsize=6.0,
        color="#4A5158",
        linespacing=1.4,
    )
    axis.text(
        0.0,
        0.04,
        "* p < .05   ** p < .01\n*** p < .001   ns: p ≥ .05",
        transform=axis.transAxes,
        ha="left",
        va="bottom",
        fontsize=5.9,
        color="#4A5158",
        linespacing=1.4,
    )


def _method_handles(*, include_mean: bool) -> list[Any]:
    """返回方法箱线和可选均值菱形的统一图例句柄。"""

    handles: list[Any] = [
        Patch(
            facecolor=_COLORS[method],
            edgecolor=_COLORS[method],
            alpha=0.25,
            label=METHOD_LABELS[method],
        )
        for method in _METHOD_ORDER
    ]
    if include_mean:
        handles.append(
            Line2D(
                [],
                [],
                marker="o",
                linestyle="none",
                markerfacecolor="white",
                markeredgecolor="#4A5158",
                markersize=4.6,
                label="Mean",
            )
        )
    return handles


def _symmetric_jitter(count: int, width: float) -> np.ndarray:
    """返回确定性的对称横向偏移，重复构建不引入随机差异。"""

    if count <= 1:
        return np.zeros(max(count, 0), dtype=float)
    return np.linspace(-width, width, count)


def _clean_axis(axis: Any) -> None:
    """应用浅色水平网格并压低非数据墨水。"""

    axis.set_axisbelow(True)
    axis.grid(axis="y", color=_GRID_COLOR, linestyle="-", linewidth=0.48, alpha=0.80)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="both", length=2.5, width=0.65, pad=1.8)


def _save_pair(figure: Any, root: Path, stem: str) -> tuple[Path, Path]:
    """以相同内容保存 300 dpi PNG 和嵌入字体的矢量 PDF。"""

    png = root / f"{stem}.png"
    pdf = root / f"{stem}.pdf"
    figure.savefig(png, facecolor="white")
    figure.savefig(
        pdf,
        facecolor="white",
        metadata={"CreationDate": None, "ModDate": None},
    )
    plt.close(figure)
    return png, pdf


def _validate_plot_data(
    data: pd.DataFrame,
    outcomes: tuple[str, ...],
    sheet_name: str,
    *,
    require_object: bool = False,
) -> None:
    """拒绝缺列、缺结局或缺方法的结果工作簿。"""

    required = {"Participant_ID", "Condition", "Outcome", "Value"}
    if require_object:
        required.add("Object_Key")
    missing_columns = required.difference(data.columns)
    if missing_columns:
        raise ValueError(f"{sheet_name} 缺少绘图列：{sorted(missing_columns)}")
    missing_outcomes = set(outcomes).difference(set(data["Outcome"].astype(str)))
    if missing_outcomes:
        raise ValueError(f"{sheet_name} 缺少结局：{sorted(missing_outcomes)}")
    missing_methods = set(_METHOD_ORDER).difference(set(data["Condition"].astype(str)))
    if missing_methods:
        raise ValueError(f"{sheet_name} 缺少方法：{sorted(missing_methods)}")


def _format_p(value: Any) -> str:
    """格式化图内 p 值。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NA"
    if not math.isfinite(number):
        return "NA"
    return "< .001" if number < 0.001 else f"= {number:.3f}".replace("0.", ".")


def _format_number(value: Any, digits: int) -> str:
    """格式化有限小数。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NA"
    return f"{number:.{digits}f}" if math.isfinite(number) else "NA"


def _significance_label(value: Any) -> str:
    """把 Holm p 转换为图内显著性标记。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    if number < 0.001:
        return "***"
    if number < 0.01:
        return "**"
    if number < 0.05:
        return "*"
    return "ns"


def _short_outcome_label(outcome: str) -> str:
    """返回量表小多图的紧凑面板标题。"""

    return {
        "Q6": "Reliance",
        "Q7": "Balance",
        "AQ_EQ": "AQ-EQ",
        "AQ_IQ": "AQ-IQ",
        "TIA_RC": "TiA-R/C",
        "TIA_UP": "TiA-U/P",
        "STIAS": "S-TIAS",
    }[outcome]


__all__ = ["publish_figures"]
