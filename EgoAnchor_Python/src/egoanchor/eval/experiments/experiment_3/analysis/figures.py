"""直接从实验三内存分析结果生成论文 Figure 4。"""

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

from .contracts import (
    AnalysisTables,
    BLOCK_ITEMS,
    EGOANCHOR,
    MAIN_FAMILY,
    METHOD_LABELS,
    OBJECTS,
    OBJECT_LABELS,
    ONE_EURO,
    ScoreData,
)
from .settings import AnalysisSettings


_COLORS = {ONE_EURO: ONE_EURO_COLOR_HEX, EGOANCHOR: EGOANCHOR_COLOR_HEX}
_METHOD_ORDER = (ONE_EURO, EGOANCHOR)
_METHOD_MARKERS = {ONE_EURO: "o", EGOANCHOR: "s"}
_METHOD_OFFSETS = {ONE_EURO: -0.18, EGOANCHOR: 0.18}
"""两种方法固定使用颜色、形状和左右位置三重编码。"""

_PAIR_COLOR = "#7F8790"
_GRID_COLOR = "#D9DEE3"
_TEXT_COLOR = "#202428"
_MUTED_COLOR = "#4A5158"
"""与实验一、二论文图一致的上下文线、网格和文字颜色。"""

_PAIRED_OUTCOMES = ("Q1", "Q8", "Q3", "Q6")
"""Figure 4 预先冻结的四项区块级结局。"""

_PANEL_LABELS = {
    "Q1": "Static stability",
    "Q8": "Position correctness",
    "Q3": "Recovery consistency",
    "Q6": "Willingness to rely",
}
"""论文图四个面板使用的英文短标题。"""

_CONDITION_COLUMN = "Condition(保密)"
"""派生区块分表中保存盲化方法 ID 的列。"""

def publish_figures(
    scores: ScoreData,
    tables: AnalysisTables,
    output_root: Path,
    settings: AnalysisSettings,
    *,
    paper_eligible: bool,
) -> dict[str, Path]:
    """从同一次分析的内存对象发布 Figure 4 的 PNG/PDF。

    绘图不回读结果工作簿，避免工作簿展示层重命名、四舍五入或删表影响论文图。
    ``scores`` 提供逐参与者评分，``tables`` 提供家族内主检验。来源门禁未通过时，
    图中会保留不可移除的流程演练警告，防止合成响应被误用为论文证据。
    """

    _validate_figure_data(scores.block_scores, tables.results)
    figure_root = output_root.expanduser().resolve() / "figures"
    figure_root.mkdir(parents=True, exist_ok=True)
    _configure(settings.figure_dpi)
    figure = _paired_figure(
        scores.block_scores,
        tables.results,
        figure_size=settings.paired_figure_size,
    )
    if not paper_eligible:
        _mark_rehearsal(figure)
    paired_png, paired_pdf = _save_pair(
        figure,
        figure_root,
        "figure4_exp3_paired",
    )
    return {
        "figure4_png": paired_png,
        "figure4_pdf": paired_pdf,
    }


def _mark_rehearsal(figure: Any) -> None:
    """在未通过来源门禁的图片底部写入醒目但不遮挡数据的警告。"""

    figure.text(
        0.5,
        0.018,
        "SYNTHETIC REHEARSAL — NOT PAPER EVIDENCE",
        ha="center",
        va="bottom",
        fontsize=7.2,
        fontweight="bold",
        color="#B42318",
    )


def _configure(dpi: int) -> None:
    """应用与实验一、二一致且最终排版后不低于 7 pt 的样式。"""

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7.6,
            "axes.labelcolor": _TEXT_COLOR,
            "axes.labelsize": 7.6,
            "axes.titlesize": 7.6,
            "axes.titlepad": 5.0,
            "axes.linewidth": 0.9,
            "axes.edgecolor": "#70767C",
            "xtick.color": _TEXT_COLOR,
            "xtick.labelsize": 7.2,
            "ytick.color": _TEXT_COLOR,
            "ytick.labelsize": 7.2,
            "legend.fontsize": 7.0,
            "savefig.dpi": dpi,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def _paired_figure(
    blocks: pd.DataFrame,
    results: pd.DataFrame,
    *,
    figure_size: tuple[float, float],
) -> Any:
    """绘制四项结局的逐参与者、逐对象配对评分与中位数/IQR。"""

    figure, axes = plt.subplots(2, 2, figsize=figure_size, sharey=True)
    confirmatory = (
        results.loc[results["Family"] == MAIN_FAMILY]
        .drop_duplicates(subset="Outcome", keep=False)
        .set_index("Outcome")
    )
    for panel_index, (axis, outcome) in enumerate(
        zip(axes.flat, _PAIRED_OUTCOMES, strict=True)
    ):
        _draw_outcome_panel(axis, blocks, BLOCK_ITEMS[outcome])
        axis.set_title(
            f"{chr(97 + panel_index)}) {_PANEL_LABELS[outcome]} ({outcome})",
            loc="left",
            fontweight="bold",
            color=_TEXT_COLOR,
        )
        axis.set_title(
            _confirmatory_label(confirmatory.loc[outcome]),
            loc="right",
            fontsize=7.0,
            color=_MUTED_COLOR,
        )
        if panel_index % 2 == 0:
            axis.set_ylabel("Agreement (1-7)")

    figure.legend(
        handles=_method_handles(),
        loc="upper center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, 0.995),
        handlelength=1.4,
        handletextpad=0.55,
        columnspacing=1.8,
    )
    figure.subplots_adjust(
        left=0.064,
        right=0.993,
        bottom=0.085,
        top=0.885,
        wspace=0.12,
        hspace=0.39,
    )
    return figure


def _draw_outcome_panel(axis: Any, blocks: pd.DataFrame, column: str) -> None:
    """在一个面板内按对象画出每位参与者的两方法完整配对。"""

    for object_index, object_key in enumerate(OBJECTS):
        subset = blocks.loc[
            blocks["Object_Key"].astype(str) == object_key,
            ["Participant_ID", _CONDITION_COLUMN, column],
        ]
        pivot = subset.pivot(
            index="Participant_ID",
            columns=_CONDITION_COLUMN,
            values=column,
        )
        complete = pivot.dropna(subset=list(_METHOD_ORDER)).sort_index()
        _draw_participant_pairs(axis, complete, float(object_index))

    axis.set_xlim(-0.52, len(OBJECTS) - 0.48)
    axis.set_ylim(0.65, 7.35)
    axis.set_yticks(range(1, 8))
    axis.set_xticks(range(len(OBJECTS)), [OBJECT_LABELS[item] for item in OBJECTS])
    _clean_axis(axis)


def _draw_participant_pairs(
    axis: Any,
    pairs: pd.DataFrame,
    center: float,
) -> None:
    """绘制一个对象的配对线、两方法端点以及中位数/IQR。

    参与者按稳定 ID 排序后只在横轴上做极小、成对一致的展开；纵轴保持原始 Likert
    评分不变。这样能降低完全重叠，同时不制造虚假的非整数评分。

    """

    if pairs.empty:
        return
    jitter = (
        np.zeros(1, dtype=float)
        if len(pairs) == 1
        else np.linspace(-0.045, 0.045, len(pairs), dtype=float)
    )
    left = center + _METHOD_OFFSETS[ONE_EURO] + jitter
    right = center + _METHOD_OFFSETS[EGOANCHOR] + jitter
    one_euro = pairs[ONE_EURO].to_numpy(dtype=float)
    egoanchor = pairs[EGOANCHOR].to_numpy(dtype=float)

    for x_left, x_right, left_value, right_value in zip(
        left,
        right,
        one_euro,
        egoanchor,
        strict=True,
    ):
        axis.plot(
            [x_left, x_right],
            [left_value, right_value],
            color=_PAIR_COLOR,
            linewidth=0.8,
            alpha=0.35,
            zorder=1,
        )

    axis.scatter(
        left,
        one_euro,
        s=13.0,
        marker=_METHOD_MARKERS[ONE_EURO],
        facecolors="white",
        edgecolors=_COLORS[ONE_EURO],
        linewidths=0.75,
        alpha=0.82,
        zorder=2,
    )
    axis.scatter(
        right,
        egoanchor,
        s=13.0,
        marker=_METHOD_MARKERS[EGOANCHOR],
        facecolors=_COLORS[EGOANCHOR],
        edgecolors=_COLORS[EGOANCHOR],
        linewidths=0.65,
        alpha=0.72,
        zorder=2,
    )

    for method, values in ((ONE_EURO, one_euro), (EGOANCHOR, egoanchor)):
        _draw_summary(
            axis,
            values,
            center + _METHOD_OFFSETS[method],
            _COLORS[method],
        )


def _draw_summary(
    axis: Any,
    values: np.ndarray,
    position: float,
    color: str,
) -> None:
    """在参与者端点之上叠加该方法的中位数与四分位区间。"""

    quartile_low, median, quartile_high = _quartiles(values)
    axis.plot(
        [position, position],
        [quartile_low, quartile_high],
        color=color,
        linewidth=4.2,
        alpha=0.42,
        solid_capstyle="round",
        zorder=4,
    )
    axis.plot(
        [position - 0.072, position + 0.072],
        [median, median],
        color=_TEXT_COLOR,
        linewidth=1.6,
        solid_capstyle="butt",
        zorder=5,
    )


def _method_handles() -> list[Line2D]:
    """返回含颜色、点形和填充冗余编码的统一图例句柄。"""

    return [
        Line2D(
            [],
            [],
            linestyle="none",
            marker=_METHOD_MARKERS[method],
            markersize=4.7,
            markerfacecolor="white" if method == ONE_EURO else _COLORS[method],
            markeredgecolor=_COLORS[method],
            markeredgewidth=0.85,
            label=METHOD_LABELS[method],
        )
        for method in _METHOD_ORDER
    ]


def _quartiles(values: np.ndarray) -> tuple[float, float, float]:
    """返回一组有限值的 Q1、中位数与 Q3。"""

    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return math.nan, math.nan, math.nan
    quartile_low, median, quartile_high = np.percentile(
        finite,
        (25.0, 50.0, 75.0),
    )
    return float(quartile_low), float(median), float(quartile_high)


def _clean_axis(axis: Any) -> None:
    """应用浅点状水平网格并移除不必要的上、右边框。"""

    axis.set_axisbelow(True)
    axis.grid(axis="y", color=_GRID_COLOR, linestyle=":", linewidth=0.75, alpha=0.35)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="both", length=2.5, width=0.75, pad=2.0)


def _save_pair(figure: Any, root: Path, stem: str) -> tuple[Path, Path]:
    """按固定画布同时保存 300 dpi PNG 与嵌入 TrueType 字体的 PDF。"""

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


def _validate_figure_data(blocks: pd.DataFrame, results: pd.DataFrame) -> None:
    """拒绝缺列、重复区块、缺方法、缺对象或缺主检验的内存输入。"""

    block_columns = {
        "Participant_ID",
        _CONDITION_COLUMN,
        "Object_Key",
        *(BLOCK_ITEMS[outcome] for outcome in _PAIRED_OUTCOMES),
    }
    _require_columns(blocks, block_columns, "ScoreData.block_scores")
    _require_columns(
        results,
        {"Family", "Outcome", "p_Holm", "r_rb"},
        "AnalysisTables.results",
    )
    identities = blocks.loc[:, ["Participant_ID", _CONDITION_COLUMN, "Object_Key"]]
    if identities.duplicated().any():
        duplicates = identities.loc[identities.duplicated(keep=False)].drop_duplicates()
        raise ValueError(
            "ScoreData.block_scores 存在重复的参与者×方法×对象区块："
            f"{duplicates.astype(str).to_dict('records')}"
        )
    missing_methods = set(_METHOD_ORDER).difference(blocks[_CONDITION_COLUMN].astype(str))
    if missing_methods:
        raise ValueError(f"ScoreData.block_scores 缺少方法：{sorted(missing_methods)}")
    missing_objects = set(OBJECTS).difference(blocks["Object_Key"].astype(str))
    if missing_objects:
        raise ValueError(f"ScoreData.block_scores 缺少对象：{sorted(missing_objects)}")

    confirmatory = results.loc[results["Family"] == MAIN_FAMILY]
    duplicated_outcomes = confirmatory.loc[
        confirmatory["Outcome"].duplicated(keep=False),
        "Outcome",
    ]
    if not duplicated_outcomes.empty:
        raise ValueError(
            "AnalysisTables.results 的主家族包含重复结局："
            f"{sorted(duplicated_outcomes.astype(str).unique())}"
        )
    missing_outcomes = set(_PAIRED_OUTCOMES).difference(confirmatory["Outcome"].astype(str))
    if missing_outcomes:
        raise ValueError(
            "AnalysisTables.results 缺少 Figure 4 主检验："
            f"{sorted(missing_outcomes)}"
        )

    for outcome in _PAIRED_OUTCOMES:
        column = BLOCK_ITEMS[outcome]
        for object_key in OBJECTS:
            subset = blocks.loc[
                blocks["Object_Key"].astype(str) == object_key,
                ["Participant_ID", _CONDITION_COLUMN, column],
            ]
            pivot = subset.pivot(
                index="Participant_ID",
                columns=_CONDITION_COLUMN,
                values=column,
            )
            if not set(_METHOD_ORDER).issubset(pivot.columns):
                raise ValueError(f"{outcome}/{object_key} 缺少两种方法的评分")
            if pivot.dropna(subset=list(_METHOD_ORDER)).empty:
                raise ValueError(f"{outcome}/{object_key} 没有可绘制的完整参与者配对")


def _require_columns(frame: pd.DataFrame, columns: set[str], source_name: str) -> None:
    """要求内存输入表包含指定列。"""

    missing = columns.difference(frame.columns)
    if missing:
        raise ValueError(f"{source_name} 缺少绘图列：{sorted(missing)}")


def _confirmatory_label(result: pd.Series) -> str:
    """生成三物体均值主检验在面板右上角的紧凑摘要。"""

    p_value = result.get("p_Holm")
    stars = _significance_label(p_value)
    effect = _format_decimal(result.get("r_rb"), 2)
    p_text = _format_p(p_value)
    return rf"$p_{{\mathrm{{Holm}}}}{p_text}$ {stars}  $r_{{rb}}={effect}$"


def _format_p(value: Any) -> str:
    """按论文图规范格式化 Holm 校正 p 值。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "=NA"
    if not math.isfinite(number):
        return "=NA"
    return "<.001" if number < 0.001 else f"={_format_decimal(number, 3)}"


def _format_decimal(value: Any, digits: int) -> str:
    """格式化有限小数，并省略绝对值小于 1 时的小数点前零。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NA"
    if not math.isfinite(number):
        return "NA"
    formatted = f"{number:.{digits}f}"
    if formatted.startswith("-0."):
        return f"-.{formatted[3:]}"
    if formatted.startswith("0."):
        return f".{formatted[2:]}"
    return formatted


def _significance_label(value: Any) -> str:
    """把主检验 Holm p 值转换为面板级显著性标记。"""

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


__all__ = ["publish_figures"]
