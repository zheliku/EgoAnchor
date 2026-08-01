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
from matplotlib.patches import Patch  # noqa: E402

from .contracts import (
    BLOCK_ITEMS,
    EGOANCHOR,
    MAIN_FAMILY,
    METHOD_LABELS,
    OBJECTS,
    OBJECT_LABELS,
    ONE_EURO,
    SCALE_FAMILY,
)
from .settings import AnalysisSettings
from .workbook import (
    OBJECT_RESULTS_SHEET,
    RESULTS_SHEET,
    SCORES_BLOCK_SHEET,
    SCORES_PAIRED_SHEET,
)


_COLORS = {ONE_EURO: ONE_EURO_COLOR_HEX, EGOANCHOR: EGOANCHOR_COLOR_HEX}
_METHOD_ORDER = (ONE_EURO, EGOANCHOR)
_GRID_COLOR = "#E4E7EA"
_TEXT_COLOR = "#202428"
_MUTED_COLOR = "#4A5158"
_RULE_COLOR = "#3C4248"
"""论文图的固定方法顺序与统一视觉编码。"""

_PAIRED_OUTCOMES = ("Q1", "Q8", "Q3", "Q6")
"""图 4 逐物体展开的四项主家族条目。"""

_SCALE_FIGURE_OUTCOMES = ("Q6", "Q7", "AQ_EQ", "AQ_IQ", "TIA_RC", "TIA_UP", "STIAS")
"""图 5 按三物体均值展示的依赖意愿、权衡与五项已发表量表。"""

_OBJECT_PANEL_LABELS = {
    "Q1": "Static stability",
    "Q8": "Position correctness",
    "Q3": "Recovery consistency",
    "Q6": "Willingness to rely",
}
"""图 4 四个宽面板的描述性标题。"""

_SCALE_PANEL_LABELS = {
    "Q6": "Reliance",
    "Q7": "Balance",
    "AQ_EQ": "AQ-EQ",
    "AQ_IQ": "AQ-IQ",
    "TIA_RC": "TiA-R/C",
    "TIA_UP": "TiA-U/P",
    "STIAS": "S-TIAS",
}
"""图 5 八个窄面板与效应量森林图使用的紧凑标签。"""

_METHOD_OFFSET = 0.20
"""同一物体内两种方法的横向偏移。"""

_BUBBLE_AREA_PER_COUNT = 3.6
"""图 4 计数气泡的面积与人数的比例系数（面积正比于人数）。"""

_SWARM_MAX_HALF_WIDTH = 0.34
"""图 5 单个取值箱内蜂群的最大半宽；两方法中心相距 1.0，超过 0.5 就会两组相连。"""


def publish_figures(
    results_workbook: Path,
    output_root: Path,
    settings: AnalysisSettings,
) -> dict[str, Path]:
    """只读结果 XLSX，生成逐物体主图与量表小多图的 PNG/PDF。"""

    source = results_workbook.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"实验三结果工作簿不存在：{source}")
    blocks = pd.read_excel(source, sheet_name=SCORES_BLOCK_SHEET, engine="openpyxl")
    paired = pd.read_excel(source, sheet_name=SCORES_PAIRED_SHEET, engine="openpyxl")
    results = pd.read_excel(source, sheet_name=RESULTS_SHEET, engine="openpyxl")
    objects = pd.read_excel(source, sheet_name=OBJECT_RESULTS_SHEET, engine="openpyxl")
    _validate_figure_data(blocks, paired, results, objects)
    figure_root = output_root.expanduser().resolve() / "figures"
    figure_root.mkdir(parents=True, exist_ok=True)
    _configure(settings.figure_dpi)
    paired_paths = _save_pair(
        _object_figure(blocks, results, objects, settings),
        figure_root,
        "figure4_exp3_paired",
    )
    scale_paths = _save_pair(
        _scale_figure(paired, results, settings),
        figure_root,
        "figure5_exp3_scales",
    )
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
            "axes.titlepad": 5.0,
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


def _object_figure(
    blocks: pd.DataFrame,
    results: pd.DataFrame,
    objects: pd.DataFrame,
    settings: AnalysisSettings,
) -> Any:
    """绘制四项主家族条目的逐物体计数分布、中位数与显著性括号。"""

    figure, axes = plt.subplots(2, 2, figsize=settings.primary_figure_size, sharey=True)
    confirmatory = results[results["Family"] == MAIN_FAMILY].set_index("Outcome")
    for panel_index, (axis, outcome) in enumerate(
        zip(axes.flat, _PAIRED_OUTCOMES, strict=True)
    ):
        _draw_object_panel(
            axis,
            blocks,
            BLOCK_ITEMS[outcome],
            objects[objects["Outcome"] == outcome].set_index("Object_Key"),
        )
        axis.set_title(
            f"{chr(97 + panel_index)}) {_OBJECT_PANEL_LABELS[outcome]} ({outcome})",
            loc="left",
            fontweight="bold",
            color=_TEXT_COLOR,
        )
        if outcome in confirmatory.index:
            axis.set_title(
                _confirmatory_label(confirmatory.loc[outcome]),
                loc="right",
                fontsize=6.1,
                color=_MUTED_COLOR,
            )
        if panel_index % 2 == 0:
            axis.set_ylabel("Agreement (1–7)")
    figure.legend(
        handles=_method_handles(),
        loc="upper center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, 0.998),
        handlelength=1.4,
        columnspacing=1.6,
    )
    figure.text(
        0.006,
        0.028,
        "Circle area ∝ participants giving that rating; thick tick: median; light bar: IQR.",
        fontsize=5.7,
        color=_MUTED_COLOR,
    )
    figure.text(
        0.006,
        0.005,
        "Per-object brackets are exploratory (Holm-corrected across the three objects); panel headers give the "
        "confirmatory three-object-mean test ($r$ = $r_{rb}$).",
        fontsize=5.7,
        color=_MUTED_COLOR,
    )
    figure.subplots_adjust(
        left=0.062,
        right=0.995,
        bottom=0.112,
        top=0.885,
        wspace=0.10,
        hspace=0.40,
    )
    return figure


def _draw_object_panel(
    axis: Any,
    blocks: pd.DataFrame,
    column: str,
    object_results: pd.DataFrame,
) -> None:
    """在一个面板内按三个物体绘制计数气泡、中位数与探索性显著性括号。"""

    for object_index, object_key in enumerate(OBJECTS):
        subset = blocks[blocks["Object_Key"].astype(str) == object_key]
        pivot = subset.pivot_table(
            index="Participant_ID",
            columns="Condition",
            values=column,
            aggfunc="first",
        )
        if not set(_METHOD_ORDER).issubset(pivot.columns):
            continue
        complete = pivot.dropna(subset=list(_METHOD_ORDER))
        if complete.empty:
            continue
        for method, sign in zip(_METHOD_ORDER, (-1.0, 1.0), strict=True):
            _draw_count_bubbles(
                axis,
                complete[method].to_numpy(dtype=float),
                object_index + sign * _METHOD_OFFSET,
                _COLORS[method],
            )
        if object_key in object_results.index:
            _draw_bracket(
                axis,
                object_index - _METHOD_OFFSET,
                object_index + _METHOD_OFFSET,
                7.35,
                0.18,
                _significance_label(object_results.loc[object_key].get("p_Holm_Panel")),
            )
    axis.set_xlim(-0.62, len(OBJECTS) - 0.38)
    axis.set_ylim(0.55, 8.10)
    axis.set_yticks(range(1, 8))
    axis.set_xticks(range(len(OBJECTS)), [OBJECT_LABELS[item] for item in OBJECTS])
    _clean_axis(axis)


def _draw_count_bubbles(
    axis: Any,
    values: np.ndarray,
    position: float,
    color: str,
) -> None:
    """按每个整数评分的人数绘制面积成比例的气泡，并叠加中位数与 IQR。"""

    levels, counts = np.unique(values, return_counts=True)
    quartile_low, median, quartile_high = _quartiles(values)
    axis.plot(
        [position, position],
        [quartile_low, quartile_high],
        color=color,
        linewidth=3.4,
        alpha=0.26,
        solid_capstyle="round",
        zorder=2,
    )
    axis.scatter(
        np.full(len(levels), position),
        levels,
        s=np.maximum(counts * _BUBBLE_AREA_PER_COUNT, 4.0),
        facecolor=color,
        edgecolor="white",
        linewidth=0.35,
        alpha=0.88,
        zorder=4,
    )
    axis.plot(
        [position - 0.078, position + 0.078],
        [median, median],
        color=_TEXT_COLOR,
        linewidth=1.45,
        solid_capstyle="butt",
        zorder=6,
    )


def _scale_figure(
    paired: pd.DataFrame,
    results: pd.DataFrame,
    settings: AnalysisSettings,
) -> Any:
    """绘制依赖意愿、权衡与五项已发表量表的原生尺度分布与效应量汇总。"""

    figure, axes = plt.subplots(2, 4, figsize=settings.scales_figure_size)
    families = results[results["Family"].isin((MAIN_FAMILY, SCALE_FAMILY))]
    result_map = families.set_index("Outcome")
    for panel_index, (axis, outcome) in enumerate(
        zip(axes.flat[:7], _SCALE_FIGURE_OUTCOMES, strict=True)
    ):
        upper = 5.0 if outcome.startswith("TIA_") else 7.0
        _draw_method_panel(axis, paired[paired["Outcome"] == outcome], upper=upper)
        axis.set_title(
            f"{chr(97 + panel_index)}) {_SCALE_PANEL_LABELS[outcome]} (1–{int(upper)})",
            loc="left",
            fontweight="bold",
            color=_TEXT_COLOR,
        )
        if panel_index in (0, 4):
            axis.set_ylabel("Three-object mean score")
        if outcome in result_map.index:
            _draw_bracket(
                axis,
                0.04,
                0.96,
                upper + 0.24,
                0.11 if upper == 7.0 else 0.08,
                _significance_label(result_map.loc[outcome].get("p_Holm")),
            )
    degenerate = _draw_effect_panel(axes.flat[7], result_map, settings)
    notes = [
        "a–g) Points: participant three-object means; thick tick: median; light bar: IQR.",
        "Brackets: Holm-adjusted within family (* p<.05, ** p<.01, *** p<.001, ns p≥.05).  "
        "h) Filled marker: Holm-significant.",
    ]
    if degenerate:
        notes.append(
            f"◆ {', '.join(degenerate)}: every pair favours one method, so $r_{{rb}}$ sits at the "
            "bound and no interval is estimable."
        )
    for offset, note in enumerate(reversed(notes)):
        figure.text(0.006, 0.006 + offset * 0.024, note, fontsize=5.7, color=_MUTED_COLOR)
    figure.subplots_adjust(
        left=0.070,
        right=0.995,
        bottom=0.145,
        top=0.950,
        wspace=0.40,
        hspace=0.46,
    )
    return figure


def _draw_method_panel(axis: Any, data: pd.DataFrame, *, upper: float) -> None:
    """绘制两种方法的参与者级蜂群分布、中位数与 IQR。"""

    complete = data.dropna(subset=list(_METHOD_ORDER))
    for method, position in zip(_METHOD_ORDER, (0.0, 1.0), strict=True):
        values = complete[method].to_numpy(dtype=float)
        if not len(values):
            continue
        offsets = _swarm_offsets(values, bin_width=(upper - 1.0) / 26.0, spacing=0.052)
        quartile_low, median, quartile_high = _quartiles(values)
        color = _COLORS[method]
        axis.plot(
            [position, position],
            [quartile_low, quartile_high],
            color=color,
            linewidth=4.6,
            alpha=0.24,
            solid_capstyle="round",
            zorder=2,
        )
        axis.scatter(
            position + offsets,
            values,
            s=9.0,
            facecolor=color,
            edgecolor="white",
            linewidth=0.28,
            alpha=0.85,
            zorder=4,
        )
        axis.plot(
            [position - 0.24, position + 0.24],
            [median, median],
            color=_TEXT_COLOR,
            linewidth=1.45,
            solid_capstyle="butt",
            zorder=6,
        )
    axis.set_xlim(-0.52, 1.52)
    axis.set_ylim(0.72, upper + (0.92 if upper == 7.0 else 0.72))
    axis.set_yticks(np.arange(1, int(upper) + 1))
    axis.set_xticks((0, 1), ("One-Euro", "EgoAnchor"))
    for tick, method in zip(axis.get_xticklabels(), _METHOD_ORDER, strict=True):
        tick.set_color(_COLORS[method])
        tick.set_fontweight("bold")
    _clean_axis(axis)


def _draw_effect_panel(
    axis: Any,
    result_map: pd.DataFrame,
    settings: AnalysisSettings,
) -> list[str]:
    """在末面板汇总七项结局的匹配秩效应量与自举置信区间。

    返回区间在边界退化、因而不可解释为置信区间的结局列表，交由调用方写入脚注。
    """

    outcomes = [outcome for outcome in _SCALE_FIGURE_OUTCOMES if outcome in result_map.index]
    positions = np.arange(len(outcomes), dtype=float)
    lows: list[float] = []
    highs: list[float] = []
    degenerate: list[str] = []
    for position, outcome in zip(positions, outcomes, strict=True):
        row = result_map.loc[outcome]
        effect = float(row.get("r_rb", math.nan))
        low = float(row.get("r_rb_CI_Low", math.nan))
        high = float(row.get("r_rb_CI_High", math.nan))
        significant = read_significance(row.get("Significant"))
        usable = str(row.get("r_rb_CI_Status", "")) not in {"degenerate_at_bound", "not_estimable"}
        lows.append(low)
        highs.append(high)
        if math.isfinite(low) and math.isfinite(high) and usable:
            axis.plot(
                [low, high],
                [position, position],
                color=EGOANCHOR_COLOR_HEX,
                linewidth=1.05,
                alpha=0.75,
                solid_capstyle="round",
                zorder=3,
            )
        if not usable:
            degenerate.append(_SCALE_PANEL_LABELS[outcome])
        axis.scatter(
            [effect],
            [position],
            s=15 if usable else 19,
            marker="o" if usable else "D",
            facecolor=EGOANCHOR_COLOR_HEX if significant else "white",
            edgecolor=EGOANCHOR_COLOR_HEX,
            linewidth=0.95,
            zorder=5,
        )
    finite = [value for value in (*lows, *highs) if math.isfinite(value)]
    lower = min([0.0, *finite]) - 0.09 if finite else -1.0
    axis.axvline(0.0, color=_RULE_COLOR, linewidth=0.6, linestyle=(0, (3, 2)), zorder=1)
    axis.set_xlim(max(-1.12, lower), 1.12)
    axis.set_xticks((0.0, 0.5, 1.0))
    axis.set_ylim(len(outcomes) - 0.5, -0.5)
    axis.set_yticks(positions, [_SCALE_PANEL_LABELS[outcome] for outcome in outcomes])
    axis.tick_params(axis="y", labelsize=6.2)
    axis.set_xlabel(f"$r_{{rb}}$ [{settings.confidence_level:.0%} CI]")
    axis.set_title("h) Effect sizes", loc="left", fontweight="bold", color=_TEXT_COLOR)
    axis.set_axisbelow(True)
    axis.grid(axis="x", color=_GRID_COLOR, linestyle="-", linewidth=0.48, alpha=0.80)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="both", length=2.5, width=0.65, pad=1.8)
    return degenerate


def _draw_bracket(
    axis: Any,
    left: float,
    right: float,
    base: float,
    height: float,
    label: str,
) -> None:
    """在两组分布之上绘制显著性括号与标记。"""

    axis.plot(
        [left, left, right, right],
        [base, base + height, base + height, base],
        color=_RULE_COLOR,
        linewidth=0.70,
        clip_on=False,
        zorder=6,
    )
    axis.text(
        (left + right) / 2.0,
        base + height + height * 0.28,
        label,
        ha="center",
        va="bottom",
        fontsize=6.6,
        fontweight="bold",
        color=_TEXT_COLOR,
        clip_on=False,
        zorder=6,
    )


def _method_handles() -> list[Any]:
    """返回两种方法的统一图例句柄。"""

    return [
        Patch(
            facecolor=_COLORS[method],
            edgecolor="white",
            linewidth=0.35,
            label=METHOD_LABELS[method],
        )
        for method in _METHOD_ORDER
    ]


def _swarm_offsets(values: np.ndarray, *, bin_width: float, spacing: float) -> np.ndarray:
    """按取值分箱生成确定性对称蜂群偏移，重复构建不引入随机差异。

    半宽被限制在 ``_SWARM_MAX_HALF_WIDTH`` 内：两种方法的中心相距 1.0，若某一箱人数很多
    （天花板效应下可能全部 24 人同分），未受限的 ``count * spacing`` 会越过两组中点、把两
    个蜂群画成一片，读者无法再分辨点属于哪种方法。超限时压缩箱内间距而不裁掉点。
    """

    offsets = np.zeros(len(values), dtype=float)
    if not len(values) or bin_width <= 0.0:
        return offsets
    bins = np.floor(np.asarray(values, dtype=float) / bin_width)
    for bin_index in np.unique(bins):
        members = np.flatnonzero(bins == bin_index)
        count = len(members)
        if count <= 1:
            continue
        step = min(spacing, 2.0 * _SWARM_MAX_HALF_WIDTH / (count - 1))
        centered = np.arange(count, dtype=float) - (count - 1) / 2.0
        offsets[members] = centered * step
    return offsets


def _quartiles(values: np.ndarray) -> tuple[float, float, float]:
    """返回一组值的 Q1、中位数与 Q3。"""

    if not len(values):
        return math.nan, math.nan, math.nan
    quartile_low, median, quartile_high = np.percentile(values, (25.0, 50.0, 75.0))
    return float(quartile_low), float(median), float(quartile_high)


def _clean_axis(axis: Any) -> None:
    """应用浅色水平网格并压低非数据墨水。"""

    axis.set_axisbelow(True)
    axis.grid(axis="y", color=_GRID_COLOR, linestyle="-", linewidth=0.48, alpha=0.80)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="both", length=2.5, width=0.65, pad=1.8)


def _save_pair(figure: Any, root: Path, stem: str) -> tuple[Path, Path]:
    """以相同内容保存 PNG 和嵌入字体的矢量 PDF。"""

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


def _validate_figure_data(
    blocks: pd.DataFrame,
    paired: pd.DataFrame,
    results: pd.DataFrame,
    objects: pd.DataFrame,
) -> None:
    """拒绝缺列、缺结局、缺方法或缺逐对象显著性的结果工作簿。"""

    _require_columns(
        blocks,
        {"Participant_ID", "Condition", "Object_Key", *(BLOCK_ITEMS[item] for item in _PAIRED_OUTCOMES)},
        SCORES_BLOCK_SHEET,
    )
    _require_columns(paired, {"Participant_ID", "Outcome", ONE_EURO, EGOANCHOR}, SCORES_PAIRED_SHEET)
    _require_columns(results, {"Family", "Outcome", "p_Holm", "r_rb", "Significant"}, RESULTS_SHEET)
    _require_columns(objects, {"Outcome", "Object_Key", "p_Holm_Panel"}, OBJECT_RESULTS_SHEET)
    missing_methods = set(_METHOD_ORDER).difference(set(blocks["Condition"].astype(str)))
    if missing_methods:
        raise ValueError(f"{SCORES_BLOCK_SHEET} 缺少方法：{sorted(missing_methods)}")
    missing_objects = set(OBJECTS).difference(set(blocks["Object_Key"].astype(str)))
    if missing_objects:
        raise ValueError(f"{SCORES_BLOCK_SHEET} 缺少对象：{sorted(missing_objects)}")
    missing_outcomes = set(_SCALE_FIGURE_OUTCOMES).difference(set(paired["Outcome"].astype(str)))
    if missing_outcomes:
        raise ValueError(f"{SCORES_PAIRED_SHEET} 缺少结局：{sorted(missing_outcomes)}")
    families = set(results["Family"].astype(str))
    if not {MAIN_FAMILY, SCALE_FAMILY}.issubset(families):
        raise ValueError(f"{RESULTS_SHEET} 缺少论文图需要的家族：{sorted(families)}")
    covered = set(map(tuple, objects.loc[:, ("Outcome", "Object_Key")].astype(str).to_numpy()))
    required = {(outcome, object_key) for outcome in _PAIRED_OUTCOMES for object_key in OBJECTS}
    if not required.issubset(covered):
        raise ValueError(f"{OBJECT_RESULTS_SHEET} 缺少逐对象结果：{sorted(required - covered)}")


def _require_columns(frame: pd.DataFrame, columns: set[str], sheet_name: str) -> None:
    """要求绘图输入表包含指定列。"""

    missing = columns.difference(frame.columns)
    if missing:
        raise ValueError(f"{sheet_name} 缺少绘图列：{sorted(missing)}")


def _confirmatory_label(result: pd.Series) -> str:
    """生成面板右上角的三物体均值确证检验摘要。"""

    stars = _significance_label(result.get("p_Holm"))
    effect = _format_number(result.get("r_rb"), 2).lstrip("0")
    return f"mean: p{_format_p(result.get('p_Holm'))} {stars}  $r$={effect}"


def _format_p(value: Any) -> str:
    """格式化图内 p 值。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return " NA"
    if not math.isfinite(number):
        return " NA"
    return "<.001" if number < 0.001 else f"={number:.3f}".replace("0.", ".")


def _format_number(value: Any, digits: int) -> str:
    """格式化有限小数。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NA"
    return f"{number:.{digits}f}" if math.isfinite(number) else "NA"


def read_significance(value: Any) -> bool:
    """判定结果工作簿回读后的显著性结论是否为真。

    ``Results`` 的 ``Significant`` 含探索性家族的空值，因此整列回读为 float64，真值表现为
    ``1.0`` 而不是 ``True``；空值表示"该家族未做结论"，必须按 False 处理。直接用 ``bool()``
    会把空值判成 True，用 ``is True`` 则会把 ``1.0`` 判成 False，两者都会静默画错森林图。
    """

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1"}
    try:
        return float(value) != 0.0
    except (TypeError, ValueError):
        return False


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


__all__ = ["publish_figures", "read_significance"]
