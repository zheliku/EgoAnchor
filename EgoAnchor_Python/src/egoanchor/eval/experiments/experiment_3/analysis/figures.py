"""从实验三内存分析结果生成十二项主观结局的双排复合图。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

from egoanchor.visuals import (
    EGOANCHOR_COLOR_HEX,
    ONE_EURO_COLOR_HEX,
    PAPER_GRID_COLOR,
    PAPER_MUTED_COLOR,
    PAPER_PAIR_COLOR,
    PAPER_TEXT_COLOR,
    apply_paper_style,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from .artifacts import EXP3_ARTIFACTS
from .contracts import (
    AnalysisTables,
    EGOANCHOR,
    MAIN_FAMILY,
    METHOD_LABELS,
    METHODS,
    ONE_EURO,
    PRIMARY_OUTCOMES,
    SCALE_FAMILY,
    SCALE_OUTCOMES,
    ScoreData,
)
from .inference import holm_adjust, signed_rank_test
from .settings import AnalysisSettings


_PAIR_COLOR = PAPER_PAIR_COLOR
_GRID_COLOR = PAPER_GRID_COLOR
"""与实验一、二共用的配对线和网格颜色。"""

_PANEL_FONT_SIZE = 7.4
"""与实验一、二组合图一致的坐标、刻度和显著性字号。"""

_METHOD_COLORS = {
    ONE_EURO: ONE_EURO_COLOR_HEX,
    EGOANCHOR: EGOANCHOR_COLOR_HEX,
}
_METHOD_MARKERS = {
    ONE_EURO: "D",
    EGOANCHOR: "s",
}
"""方法 ID 到论文颜色和点形的唯一映射。"""
_OUTCOME_LABELS = {
    "Q1": "Stability",
    "Q2": "Attachment",
    "Q3": "Orientation",
    "Q4": "Recovery",
    "Q5": "Position",
    "Q6": "Reliance",
    "Q7": "Balance",
}
"""Figure 4 横轴上的七项紧凑主结局标签。"""

_SCALE_LABELS = {
    "AQ_EQ": "AQ-EQ",
    "AQ_IQ": "AQ-IQ",
    "TIA_RC": "TiA R/C",
    "TIA_UP": "TiA U/P",
    "STIAS": "S-TIAS",
}
"""Figure 4 下排使用的已发表量表缩写。"""

_SCALE_GROUPS = (
    (("AQ_EQ", "AQ_IQ", "STIAS"), 7, "(b) Published scales (1-7)"),
    (("TIA_RC", "TIA_UP"), 5, "(c) TiA scales (1-5)"),
)
"""下排两个量尺分区的结局、理论上限和面板标题。"""

_SLOT_COUNT = len(PRIMARY_OUTCOMES)
_PLOT_LEFT = 0.064
_PLOT_RIGHT = 0.995
_TOP_AXIS_BOTTOM = 0.565
_BOTTOM_AXIS_BOTTOM = 0.105
_ROW_HEIGHT = 0.325
_SCALE_GUTTER = 0.018
"""双排 Figure 4 的七槽绘图区、行高和量尺分区间距。"""


def publish_figures(
    scores: ScoreData,
    tables: AnalysisTables,
    output_root: Path,
    settings: AnalysisSettings,
) -> dict[str, Path]:
    """发布包含主结局和已发表量表的双排 Figure 4。

    七项区块级结局先按参与者在三个物体上取均值，并保留原始 1--7 分量尺。
    AQ 子量表同样按三个物体取均值，TiA 与 S-TIAS 使用方法级单次施测得分。
    显著性括号只编码两个预先固定统计家族内的 Holm 校正结果，不对三个物体分别检验或标星。
    """

    ordered = _validate_figure_data(scores.paired_scores, tables.results)
    outcomes_png = EXP3_ARTIFACTS.figure4_png.path_under(output_root)
    outcomes_pdf = EXP3_ARTIFACTS.figure4_pdf.path_under(output_root)
    _configure(settings.figure_dpi)
    figure = _subjective_figure(
        scores.paired_scores,
        ordered,
        figure_size=settings.figure_size,
    )
    outcomes_png, outcomes_pdf = _save_pair(
        figure,
        outcomes_png,
        outcomes_pdf,
    )
    return {
        EXP3_ARTIFACTS.figure4_png.key: outcomes_png,
        EXP3_ARTIFACTS.figure4_pdf.key: outcomes_pdf,
    }


def _configure(dpi: int) -> None:
    """应用实验一至三共享的字体、线宽和矢量字体导出规则。"""

    apply_paper_style(font_size=_PANEL_FONT_SIZE, dpi=dpi)


def _subjective_figure(
    paired_scores: pd.DataFrame,
    results: pd.DataFrame,
    *,
    figure_size: tuple[float, float],
) -> Any:
    """生成上排七项主结局、下排五项已发表量表的复合图。"""

    scale_groups = _validated_scale_groups()
    figure = plt.figure(figsize=figure_size)
    plot_width = _PLOT_RIGHT - _PLOT_LEFT
    slot_width = plot_width / _SLOT_COUNT
    lower_width = (
        slot_width * sum(len(outcomes) for outcomes, _, _ in scale_groups)
        + _SCALE_GUTTER * (len(scale_groups) - 1)
    )
    lower_left = _PLOT_LEFT + (plot_width - lower_width) / 2.0
    axis = figure.add_axes(
        (_PLOT_LEFT, _TOP_AXIS_BOTTOM, plot_width, _ROW_HEIGHT)
    )
    _draw_outcomes(
        axis,
        paired_scores,
        results,
        outcomes=PRIMARY_OUTCOMES,
        scale_upper=7,
    )
    _format_outcome_axis(
        axis,
        outcomes=PRIMARY_OUTCOMES,
        labels=_OUTCOME_LABELS,
        scale_upper=7,
    )
    axis.set_title(
        "(a) Primary outcomes",
        loc="left",
        fontsize=_PANEL_FONT_SIZE - 0.2,
        fontweight="bold",
        color=PAPER_TEXT_COLOR,
    )
    scale_axes: list[Any] = []
    next_left = lower_left
    for outcomes, scale_upper, title in scale_groups:
        axis_width = slot_width * len(outcomes)
        scale_axis = figure.add_axes(
            (next_left, _BOTTOM_AXIS_BOTTOM, axis_width, _ROW_HEIGHT)
        )
        scale_axes.append(scale_axis)
        _draw_outcomes(
            scale_axis,
            paired_scores,
            results,
            outcomes=outcomes,
            scale_upper=scale_upper,
        )
        _format_outcome_axis(
            scale_axis,
            outcomes=outcomes,
            labels=_SCALE_LABELS,
            scale_upper=scale_upper,
        )
        scale_axis.set_title(
            title,
            loc="left",
            fontsize=_PANEL_FONT_SIZE - 0.2,
            fontweight="bold",
            color=PAPER_TEXT_COLOR,
        )
        next_left += axis_width + _SCALE_GUTTER
    right_axis = scale_axes[-1]
    right_axis.yaxis.tick_right()
    right_axis.yaxis.set_label_position("right")
    right_axis.spines["left"].set_visible(False)
    right_axis.spines["right"].set_visible(True)
    figure.legend(
        handles=_method_legend_handles(),
        loc="upper center",
        bbox_to_anchor=(0.5, 0.985),
        ncol=3,
        frameon=False,
        handletextpad=0.35,
        columnspacing=1.4,
    )
    return figure


def _draw_outcomes(
    axis: Any,
    paired_scores: pd.DataFrame,
    results: pd.DataFrame,
    *,
    outcomes: tuple[str, ...],
    scale_upper: int,
) -> None:
    """把一组同量尺结局绘制到同一坐标轴。"""

    for index, outcome in enumerate(outcomes):
        subset = paired_scores.loc[
            paired_scores["Outcome"].astype(str) == outcome
        ].sort_values("Participant_ID")
        values = tuple(
            pd.to_numeric(subset[method], errors="coerce").to_numpy(dtype=float)
            for method in METHODS
        )
        _draw_outcome_group(
            axis,
            float(index),
            values,
            p_holm=results.loc[outcome, "p_Holm"],
            scale_upper=scale_upper,
        )


def _format_outcome_axis(
    axis: Any,
    *,
    outcomes: tuple[str, ...],
    labels: dict[str, str],
    scale_upper: int,
) -> None:
    """设置同量尺结局轴的标签、范围和共享样式。"""

    centers: np.ndarray = np.arange(len(outcomes), dtype=float)
    axis.set_xticks(centers, [labels[outcome] for outcome in outcomes])
    axis.set_xlim(-0.50, len(outcomes) - 0.50)
    axis.set_ylim(0.75, scale_upper + 0.50)
    axis.set_yticks(np.arange(1.0, scale_upper + 1.0, 1.0))
    axis.set_ylabel(f"Rating (1-{scale_upper})")
    _clean_axis(axis)


def _draw_outcome_group(
    axis: Any,
    center: float,
    values: tuple[np.ndarray, np.ndarray],
    *,
    p_holm: Any,
    scale_upper: int,
) -> None:
    """用透明箱线图、均值点和参与者配对线绘制一项结局。"""

    if values[0].size == 0 or values[0].size != values[1].size:
        raise ValueError("实验三配对图缺少完整参与者配对")
    count = values[0].size
    positions = (center - 0.17, center + 0.17)
    jitter: np.ndarray = (
        np.zeros(1) if count == 1 else np.linspace(-0.036, 0.036, count)
    )
    for participant in range(count):
        axis.plot(
            [positions[0] + jitter[participant], positions[1] + jitter[participant]],
            [values[0][participant], values[1][participant]],
            color=_PAIR_COLOR,
            linewidth=0.60,
            alpha=0.14,
            zorder=1,
        )
    for method_index, (method, method_values) in enumerate(
        zip(METHODS, values, strict=True)
    ):
        color = _METHOD_COLORS[method]
        marker = _METHOD_MARKERS[method]
        axis.scatter(
            positions[method_index] + jitter,
            method_values,
            s=6.0,
            marker=marker,
            facecolors=color,
            edgecolors=color,
            linewidths=0.45,
            alpha=0.18,
            zorder=2,
        )
        axis.boxplot(
            [method_values],
            positions=[positions[method_index]],
            widths=0.18,
            patch_artist=True,
            manage_ticks=False,
            showfliers=False,
            showmeans=True,
            whis=1.5,
            boxprops={
                "facecolor": "none",
                "edgecolor": color,
                "linewidth": 1.10,
            },
            medianprops={"color": color, "linewidth": 1.60},
            whiskerprops={"color": color, "linewidth": 0.85},
            capprops={"color": color, "linewidth": 0.85},
            meanprops={
                "marker": "o",
                "markerfacecolor": color,
                "markeredgecolor": "white",
                "markeredgewidth": 0.45,
                "markersize": 3.8,
            },
            zorder=3,
        )
    _draw_significance(axis, p_holm, positions, scale_upper=scale_upper)


def _draw_significance(
    axis: Any,
    p_holm: Any,
    positions: tuple[float, float],
    *,
    scale_upper: int,
) -> None:
    """仅为家族内 Holm 校正后显著的比较绘制括号和阈值标签。"""

    stars = _significance_label(p_holm)
    if not stars:
        return
    bracket = scale_upper + 0.08
    height = 0.10
    axis.plot(
        [positions[0], positions[0], positions[1], positions[1]],
        [bracket, bracket + height, bracket + height, bracket],
        color=PAPER_MUTED_COLOR,
        linewidth=0.65,
        clip_on=False,
        zorder=5,
    )
    axis.text(
        sum(positions) / 2.0,
        bracket + height + 0.03,
        stars,
        ha="center",
        va="bottom",
        color=PAPER_MUTED_COLOR,
        fontsize=_PANEL_FONT_SIZE - 0.6,
        fontweight="bold",
        clip_on=False,
    )


def _method_legend_handles() -> tuple[Line2D, Line2D, Line2D]:
    """返回两方法箱体与均值点的共享图例。"""

    methods: list[Line2D] = []
    for method in METHODS:
        color = _METHOD_COLORS[method]
        marker = _METHOD_MARKERS[method]
        methods.append(
            Line2D(
                [],
                [],
                color=color,
                linestyle="-",
                linewidth=1.10,
                marker=marker,
                markersize=6.0,
                markerfacecolor=color,
                markeredgecolor=color,
                markeredgewidth=0.8,
                label=METHOD_LABELS[method],
            )
        )
    mean = Line2D(
        [],
        [],
        linestyle="none",
        marker="o",
        markersize=3.8,
        markerfacecolor=PAPER_TEXT_COLOR,
        markeredgecolor="white",
        markeredgewidth=0.45,
        label="Mean",
    )
    return methods[0], methods[1], mean


def _validated_scale_groups() -> tuple[tuple[tuple[str, ...], int, str], ...]:
    """要求下排布局恰好覆盖冻结的五项已发表量表结局。"""

    outcomes = tuple(
        outcome
        for group, _, _ in _SCALE_GROUPS
        for outcome in group
    )
    if len(outcomes) != len(set(outcomes)) or set(outcomes) != set(SCALE_OUTCOMES):
        missing = set(SCALE_OUTCOMES).difference(outcomes)
        unexpected = set(outcomes).difference(SCALE_OUTCOMES)
        raise ValueError(
            "Figure 4 下排量表分区必须无重复地覆盖全部冻结结局："
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    return _SCALE_GROUPS


def _ordered_results(results: pd.DataFrame) -> pd.DataFrame:
    """按预先固定的统计家族和顺序返回唯一十二项结果索引。"""

    summary_columns = {
        f"{prefix}_{statistic}"
        for prefix in ("OneEuro", "EgoAnchor", "Difference")
        for statistic in ("Q1", "Median", "Q3")
    }
    _require_columns(
        results,
        {
            "Family",
            "Outcome",
            "N",
            "N_Nonzero",
            "W",
            "p_Holm",
            *summary_columns,
        },
        "AnalysisTables.results",
    )
    expected = (*PRIMARY_OUTCOMES, *SCALE_OUTCOMES)
    selected = results.loc[results["Family"].isin((MAIN_FAMILY, SCALE_FAMILY))].copy()
    duplicates = selected.loc[selected["Outcome"].duplicated(keep=False), "Outcome"]
    if not duplicates.empty:
        raise ValueError(
            "AnalysisTables.results 存在重复冻结结局："
            f"{sorted(duplicates.astype(str).unique())}"
        )
    indexed = selected.set_index("Outcome")
    if set(indexed.index.astype(str)) != set(expected):
        missing = set(expected).difference(indexed.index.astype(str))
        unexpected = set(indexed.index.astype(str)).difference(expected)
        raise ValueError(
            "AnalysisTables.results 必须恰好包含十二项冻结结局："
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    if not (indexed.loc[list(PRIMARY_OUTCOMES), "Family"] == MAIN_FAMILY).all():
        raise ValueError("主条目的结果家族归属不正确")
    if not (indexed.loc[list(SCALE_OUTCOMES), "Family"] == SCALE_FAMILY).all():
        raise ValueError("已发表量表的结果家族归属不正确")
    return indexed.loc[list(expected)]


def _validate_figure_data(paired: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """从配对分重算冻结推断，并核对结果表和配对图的全部数字。"""

    ordered = _ordered_results(results)
    _require_columns(
        paired,
        {"Participant_ID", "Outcome", ONE_EURO, EGOANCHOR, "Difference"},
        "ScoreData.paired_scores",
    )
    expected = (*PRIMARY_OUTCOMES, *SCALE_OUTCOMES)
    selected = paired.loc[paired["Outcome"].astype(str).isin(expected)]
    identities = selected.loc[:, ["Participant_ID", "Outcome"]]
    if identities.duplicated().any():
        duplicates = identities.loc[identities.duplicated(keep=False)].drop_duplicates()
        raise ValueError(
            "ScoreData.paired_scores 存在重复参与者×结局："
            f"{duplicates.astype(str).to_dict('records')}"
        )
    missing = set(expected).difference(selected["Outcome"].astype(str))
    if missing:
        raise ValueError(f"ScoreData.paired_scores 缺少冻结结局：{sorted(missing)}")
    recomputed: dict[str, dict[str, float | int]] = {}
    for outcome in expected:
        subset = selected.loc[selected["Outcome"].astype(str) == outcome]
        complete = subset.loc[:, [ONE_EURO, EGOANCHOR, "Difference"]].apply(
            pd.to_numeric,
            errors="coerce",
        )
        if complete.empty or not np.isfinite(complete.to_numpy(dtype=float)).all():
            raise ValueError(f"ScoreData.paired_scores 的 {outcome} 含非有限配对值")
        one_euro = complete[ONE_EURO].to_numpy(dtype=float)
        egoanchor = complete[EGOANCHOR].to_numpy(dtype=float)
        difference = complete["Difference"].to_numpy(dtype=float)
        if not np.allclose(
            difference,
            egoanchor - one_euro,
            rtol=0.0,
            atol=1.0e-12,
        ):
            raise ValueError(f"ScoreData.paired_scores 的 {outcome} 配对差不等于 EgoAnchor−One-Euro")
        result_row = ordered.loc[outcome]
        result_n = _finite_number(result_row["N"])
        if (
            not math.isfinite(result_n)
            or result_n % 1 != 0
            or int(result_n) != len(complete)
        ):
            raise ValueError(f"AnalysisTables.results 的 {outcome} N 与绘图配对人数不一致")
        p_holm = _finite_number(result_row["p_Holm"])
        if not math.isfinite(p_holm) or not 0.0 <= p_holm <= 1.0:
            raise ValueError(f"AnalysisTables.results 的 {outcome} p_Holm 必须位于 [0,1]")
        rank = signed_rank_test(difference)
        recomputed[outcome] = {
            "N_Nonzero": int(rank["n_nonzero"]),
            "W": float(rank["w"]),
            "p_raw": float(rank["p_value"]),
        }
        _validate_result_summaries(
            outcome,
            result_row,
            one_euro,
            egoanchor,
            difference,
        )
    for family in (PRIMARY_OUTCOMES, SCALE_OUTCOMES):
        adjusted = holm_adjust(
            [float(recomputed[outcome]["p_raw"]) for outcome in family]
        )
        for outcome, p_holm in zip(family, adjusted, strict=True):
            recomputed[outcome]["p_Holm"] = float(p_holm)

    validated = ordered.copy()
    for outcome in expected:
        _validate_recomputed_inference(
            outcome,
            ordered.loc[outcome],
            recomputed[outcome],
        )
        for field in ("N_Nonzero", "W", "p_Holm"):
            validated.at[outcome, field] = recomputed[outcome][field]
    return validated


def _validate_recomputed_inference(
    outcome: str,
    result: pd.Series,
    recomputed: dict[str, float | int],
) -> None:
    """要求结果表的非零 N、W 和 Holm p 与当前配对分重算值一致。

    ``p_raw`` 仅作为家族内 Holm 的内部输入，不在精简结果表中重复发布；因此
    对其完整重算后，通过最终 ``p_Holm`` 与结果表闭环核对。
    """

    recorded_nonzero = _finite_number(result["N_Nonzero"])
    expected_nonzero = int(recomputed["N_Nonzero"])
    if (
        not math.isfinite(recorded_nonzero)
        or recorded_nonzero % 1 != 0
        or int(recorded_nonzero) != expected_nonzero
    ):
        raise ValueError(
            f"AnalysisTables.results 的 {outcome} N_Nonzero 与配对分重算结果不一致"
        )
    for field in ("W", "p_Holm"):
        recorded = _finite_number(result[field])
        expected = float(recomputed[field])
        if not math.isclose(recorded, expected, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError(
                f"AnalysisTables.results 的 {outcome} {field} 与配对分重算结果不一致"
            )


def _validate_result_summaries(
    outcome: str,
    result: pd.Series,
    one_euro: np.ndarray,
    egoanchor: np.ndarray,
    difference: np.ndarray,
) -> None:
    """要求显著性来源表与实际绘图分数拥有相同的四分位摘要。"""

    expected: dict[str, np.ndarray] = {
        "OneEuro": np.quantile(one_euro, (0.25, 0.5, 0.75), method="linear"),
        "EgoAnchor": np.quantile(egoanchor, (0.25, 0.5, 0.75), method="linear"),
        "Difference": np.quantile(
            np.round(difference, decimals=12),
            (0.25, 0.5, 0.75),
            method="linear",
        ),
    }
    for prefix, values in expected.items():
        recorded: np.ndarray = np.asarray(
            [
                _finite_number(result[f"{prefix}_Q1"]),
                _finite_number(result[f"{prefix}_Median"]),
                _finite_number(result[f"{prefix}_Q3"]),
            ],
            dtype=float,
        )
        if not np.allclose(recorded, values, rtol=0.0, atol=1.0e-12):
            raise ValueError(
                f"AnalysisTables.results 的 {outcome} {prefix} 描述统计与绘图数据不一致"
            )


def _require_columns(frame: pd.DataFrame, columns: set[str], source_name: str) -> None:
    """要求内存输入表包含指定列。"""

    missing = columns.difference(frame.columns)
    if missing:
        raise ValueError(f"{source_name} 缺少绘图列：{sorted(missing)}")


def _clean_axis(axis: Any) -> None:
    """应用实验一、二的浅点状横网格并移除多余边框。"""

    axis.set_axisbelow(True)
    axis.grid(
        axis="y",
        color=_GRID_COLOR,
        linestyle=":",
        linewidth=0.70,
        alpha=0.65,
    )
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="both", length=2.6, width=0.75, pad=2.0)


def _save_pair(figure: Any, png: Path, pdf: Path) -> tuple[Path, Path]:
    """以固定画布保存正文复合图的 PNG/PDF。"""

    if (
        png.parent != pdf.parent
        or png.suffix.lower() != ".png"
        or pdf.suffix.lower() != ".pdf"
    ):
        raise ValueError("实验三图产物契约必须提供同目录的 PNG/PDF 路径")
    png.parent.mkdir(parents=True, exist_ok=True)
    try:
        figure.savefig(png, facecolor="white")
        figure.savefig(
            pdf,
            facecolor="white",
            metadata={"CreationDate": None, "ModDate": None},
        )
    finally:
        plt.close(figure)
    return png, pdf


def _finite_number(value: Any) -> float:
    """把可转换且有限的值保留为浮点数，否则返回 NaN。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _significance_label(value: Any) -> str:
    """把 Holm p 值转换为带阈值的显著性标签。"""

    number = _finite_number(value)
    if not math.isfinite(number):
        return ""
    if number < 0.001:
        return "***<.001"
    if number < 0.01:
        return "**<.01"
    if number < 0.05:
        return "*<.05"
    return ""


__all__ = ["publish_figures"]
