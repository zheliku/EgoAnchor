"""从实验三内存分析结果生成主条目与已发表量表箱线图。"""

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

from .artifacts import EXP3_ARTIFACTS
from .contracts import (
    AnalysisTables,
    EGOANCHOR,
    MAIN_FAMILY,
    ONE_EURO,
    PRIMARY_OUTCOMES,
    SCALE_FAMILY,
    SCALE_OUTCOMES,
    ScoreData,
)
from .inference import holm_adjust, signed_rank_test
from .settings import AnalysisSettings


_TEXT_COLOR = "#202428"
_MUTED_COLOR = "#596168"
_PAIR_COLOR = "#8E969E"
_GRID_COLOR = "#D6DBDF"
"""与实验一、二共用的正文文字、配对线和网格颜色。"""

_METHODS = (ONE_EURO, EGOANCHOR)
_METHOD_LABELS = ("One-Euro", "EgoAnchor")
_METHOD_COLORS = (ONE_EURO_COLOR_HEX, EGOANCHOR_COLOR_HEX)
_METHOD_MARKERS = ("o", "s")
_PRIMARY_LABELS = {
    "Q1": "Static stability",
    "Q8": "Position correctness",
    "Q2": "Motion attachment",
    "Q9": "Orientation consistency",
    "Q3": "Recovery consistency",
    "Q6": "Willingness to rely",
    "Q7": "Stability-response balance",
}
"""Figure 4 七个主条目的紧凑英文面板标题。"""

_SCALE_LABELS = {
    "AQ_EQ": "AQ-EQ",
    "AQ_IQ": "AQ-IQ",
    "TIA_RC": "TiA R/C",
    "TIA_UP": "TiA U/P",
    "STIAS": "S-TIAS",
}
"""Figure 5 的紧凑量表缩写；完整名称由论文图注解释。"""

_SCALE_RANGES = {
    "AQ_EQ": (1, 7),
    "AQ_IQ": (1, 7),
    "TIA_RC": (1, 5),
    "TIA_UP": (1, 5),
    "STIAS": (1, 7),
}
"""各已发表量表的理论计分范围。"""


def publish_figures(
    scores: ScoreData,
    tables: AnalysisTables,
    output_root: Path,
    settings: AnalysisSettings,
) -> dict[str, Path]:
    """发布主条目 Figure 4 和已发表量表 Figure 5。

    两张图都使用与主分析一致的参与者级得分：区块级结局先在三个物体上取
    均值，TiA 与 S-TIAS 使用方法级单次施测得分。显著性括号只编码各冻结
    家族内的 Holm 校正结果，不对三个物体分别检验或标星。
    """

    ordered = _validate_figure_data(scores.paired_scores, tables.results)
    primary_png = EXP3_ARTIFACTS.figure4_png.path_under(output_root)
    primary_pdf = EXP3_ARTIFACTS.figure4_pdf.path_under(output_root)
    _configure(settings.figure_dpi)

    primary = _boxplot_grid(
        scores.paired_scores,
        ordered,
        outcomes=PRIMARY_OUTCOMES,
        labels=_PRIMARY_LABELS,
        ranges={outcome: (1, 7) for outcome in PRIMARY_OUTCOMES},
        columns=4,
        figure_size=settings.primary_figure_size,
        y_label="Agreement score",
    )
    primary_png, primary_pdf = _save_pair(
        primary,
        primary_png,
        primary_pdf,
    )
    scale_png = EXP3_ARTIFACTS.figure5_png.path_under(output_root)
    scale_pdf = EXP3_ARTIFACTS.figure5_pdf.path_under(output_root)
    scales = _boxplot_grid(
        scores.paired_scores,
        ordered,
        outcomes=SCALE_OUTCOMES,
        labels=_SCALE_LABELS,
        ranges=_SCALE_RANGES,
        columns=5,
        figure_size=settings.scale_figure_size,
        y_label="Scale score",
    )
    scale_png, scale_pdf = _save_pair(
        scales,
        scale_png,
        scale_pdf,
    )
    return {
        EXP3_ARTIFACTS.figure4_png.key: primary_png,
        EXP3_ARTIFACTS.figure4_pdf.key: primary_pdf,
        EXP3_ARTIFACTS.figure5_png.key: scale_png,
        EXP3_ARTIFACTS.figure5_pdf.key: scale_pdf,
    }


def _configure(dpi: int) -> None:
    """应用实验一、二的固定字体、线宽和矢量字体导出规则。"""

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7.2,
            "axes.labelcolor": _TEXT_COLOR,
            "axes.labelsize": 7.2,
            "axes.titlesize": 7.2,
            "axes.titlepad": 3.0,
            "axes.linewidth": 0.8,
            "axes.edgecolor": "#70767C",
            "xtick.color": _TEXT_COLOR,
            "xtick.labelsize": 6.8,
            "ytick.color": _TEXT_COLOR,
            "ytick.labelsize": 6.8,
            "savefig.dpi": dpi,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def _boxplot_grid(
    paired_scores: pd.DataFrame,
    results: pd.DataFrame,
    *,
    outcomes: tuple[str, ...],
    labels: dict[str, str],
    ranges: dict[str, tuple[int, int]],
    columns: int,
    figure_size: tuple[float, float],
    y_label: str,
) -> Any:
    """按参考论文版式生成一组紧凑的两方法箱线图。"""

    rows = math.ceil(len(outcomes) / columns)
    figure = plt.figure(figsize=figure_size)
    axes = _panel_axes(
        figure,
        outcome_count=len(outcomes),
        rows=rows,
        columns=columns,
    )
    for index, outcome in enumerate(outcomes):
        axis = axes[index]
        subset = paired_scores.loc[
            paired_scores["Outcome"].astype(str) == outcome
        ].sort_values("Participant_ID")
        values = tuple(
            pd.to_numeric(subset[method], errors="coerce").to_numpy(dtype=float)
            for method in _METHODS
        )
        _draw_box_panel(
            axis,
            values,
            score_range=ranges[outcome],
            p_holm=results.loc[outcome, "p_Holm"],
        )
        panel = chr(ord("a") + index)
        axis.set_title(
            f"({panel}) {labels[outcome]}",
            loc="left",
            y=1.025,
            va="bottom",
            fontsize=7.2,
            fontweight="bold",
            color=_TEXT_COLOR,
            linespacing=1.05,
        )
        if index == 0 or (rows > 1 and index == columns):
            axis.set_ylabel(y_label)
    figure.subplots_adjust(
        left=0.062,
        right=0.995,
        bottom=0.155 if rows == 1 else 0.105,
        top=0.900,
        wspace=0.34 if rows > 1 else 0.30,
        hspace=0.54 if rows > 1 else 0.0,
    )
    return figure


def _panel_axes(
    figure: Any,
    *,
    outcome_count: int,
    rows: int,
    columns: int,
) -> tuple[Any, ...]:
    """创建规则面板；七项主结果的第二行使用半列偏移居中。"""

    if outcome_count == 7 and rows == 2 and columns == 4:
        grid = figure.add_gridspec(2, 8)
        positions = (
            (0, slice(0, 2)),
            (0, slice(2, 4)),
            (0, slice(4, 6)),
            (0, slice(6, 8)),
            (1, slice(1, 3)),
            (1, slice(3, 5)),
            (1, slice(5, 7)),
        )
        return tuple(
            figure.add_subplot(grid[row, columns_])
            for row, columns_ in positions
        )
    grid = figure.add_gridspec(rows, columns)
    return tuple(
        figure.add_subplot(grid[index // columns, index % columns])
        for index in range(outcome_count)
    )


def _draw_box_panel(
    axis: Any,
    values: tuple[np.ndarray, np.ndarray],
    *,
    score_range: tuple[int, int],
    p_holm: Any,
) -> None:
    """绘制一项结局的参与者级配对点、箱线图和 Holm 显著性括号。"""

    if values[0].size == 0 or values[0].size != values[1].size:
        raise ValueError("实验三箱线图缺少完整参与者配对")
    count = values[0].size
    offsets = np.zeros(1) if count == 1 else np.linspace(-0.065, 0.065, count)
    for participant in range(count):
        axis.plot(
            [offsets[participant], 1.0 + offsets[participant]],
            [values[0][participant], values[1][participant]],
            color=_PAIR_COLOR,
            linewidth=0.55,
            alpha=0.22,
            zorder=1,
        )
    for method_index, (method_values, color, marker) in enumerate(
        zip(values, _METHOD_COLORS, _METHOD_MARKERS, strict=True)
    ):
        axis.scatter(
            float(method_index) + offsets,
            method_values,
            s=9.0,
            marker=marker,
            facecolors="white" if method_index == 0 else color,
            edgecolors=color,
            linewidths=0.55,
            alpha=0.68,
            zorder=2,
        )
    boxplot = axis.boxplot(
        values,
        positions=(0.0, 1.0),
        widths=0.50,
        patch_artist=True,
        showfliers=False,
        whis=1.5,
        boxprops={"linewidth": 0.95},
        whiskerprops={"color": _MUTED_COLOR, "linewidth": 0.85},
        capprops={"color": _MUTED_COLOR, "linewidth": 0.85},
        medianprops={"linewidth": 1.55},
        zorder=3,
    )
    for patch, color in zip(boxplot["boxes"], _METHOD_COLORS, strict=True):
        patch.set_facecolor(color)
        patch.set_alpha(0.42)
        patch.set_edgecolor(color)
    for median in boxplot["medians"]:
        median.set_color(_TEXT_COLOR)
    lower, upper = score_range
    headroom = 0.82 if upper == 7 else 0.72
    axis.set_ylim(lower - 0.30, upper + headroom)
    axis.set_yticks(range(lower, upper + 1))
    axis.set_xticks((0.0, 1.0), _METHOD_LABELS)
    axis.set_xlim(-0.48, 1.48)
    _draw_significance(axis, p_holm, float(upper), headroom)
    _clean_axis(axis)


def _draw_significance(axis: Any, p_holm: Any, scale_upper: float, headroom: float) -> None:
    """仅为家族内 Holm 校正后显著的比较绘制括号和星号。"""

    stars = _significance_label(p_holm)
    if not stars:
        return
    bracket = scale_upper + headroom * 0.38
    height = headroom * 0.16
    axis.plot(
        [0.0, 0.0, 1.0, 1.0],
        [bracket, bracket + height, bracket + height, bracket],
        color=_TEXT_COLOR,
        linewidth=0.85,
        clip_on=False,
        zorder=5,
    )
    axis.text(
        0.5,
        bracket + height + headroom * 0.04,
        stars,
        ha="center",
        va="bottom",
        color=_TEXT_COLOR,
        fontsize=7.2,
        fontweight="bold",
        clip_on=False,
    )


def _ordered_results(results: pd.DataFrame) -> pd.DataFrame:
    """按冻结家族和顺序返回唯一十二项结果索引。"""

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
    """从配对分重算冻结推断，并核对结果表和箱线图的全部数字。"""

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

    expected = {
        "OneEuro": np.quantile(one_euro, (0.25, 0.5, 0.75), method="linear"),
        "EgoAnchor": np.quantile(egoanchor, (0.25, 0.5, 0.75), method="linear"),
        "Difference": np.quantile(
            np.round(difference, decimals=12),
            (0.25, 0.5, 0.75),
            method="linear",
        ),
    }
    for prefix, values in expected.items():
        recorded = np.asarray(
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
        linewidth=0.65,
        alpha=0.55,
    )
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="both", length=2.5, width=0.75, pad=2.0)


def _save_pair(figure: Any, png: Path, pdf: Path) -> tuple[Path, Path]:
    """同时保存 300 dpi PNG 与嵌入 TrueType 字体的 PDF。"""

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
    """把 Holm p 值转换为参考论文使用的显著性星号。"""

    number = _finite_number(value)
    if not math.isfinite(number):
        return ""
    if number < 0.001:
        return "***"
    if number < 0.01:
        return "**"
    if number < 0.05:
        return "*"
    return ""


__all__ = ["publish_figures"]
