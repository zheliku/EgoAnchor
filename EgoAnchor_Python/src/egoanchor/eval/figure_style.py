"""IEEE VR 论文图的共享风格、配色与可复用绘图基元。

本模块是实验一/二两套论文图的唯一美学来源：固定语义配色、字体与线宽，
并提供分布 glyph、面板标号、事件阴影和矢量 PDF 导出等基元，使不同图在颜色、
字号和留白上保持一致。所有函数均不修改传入数据，只负责渲染。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch


# ---------------------------------------------------------------------------
# 版式常量：IEEE VR / TVCG 双栏模板的可用宽度（英寸）。
# ---------------------------------------------------------------------------

COLUMN_WIDTH_IN = 3.5
"""单栏图的目标宽度。"""

TEXT_WIDTH_IN = 7.16
"""跨栏 ``figure*`` 的目标宽度。"""

GOLDEN = 0.618
"""缺省高宽比，用于生成视觉稳定的单图。"""


# ---------------------------------------------------------------------------
# 语义配色：颜色随系统语义固定，绝不随结果排序变化。
# EgoAnchor 始终是高饱和红色 hero，基线使用低调冷/中性色。
# ---------------------------------------------------------------------------

VARIANT_ORDER = ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", "EgoAnchor")
"""实验一四配置的固定顺序，同时决定配对基线与图例次序。"""

VARIANT_SHORT = {
    "Arrival-Hold": "Arrival",
    "Capture-Hold": "Capture",
    "One-Euro Anchor": "One-Euro",
    "EgoAnchor": "EgoAnchor",
}
"""坐标轴刻度使用的紧凑系统名。"""


@dataclass(frozen=True)
class VariantStyle:
    """一个系统配置在所有图中的固定视觉编码。"""

    color: str
    linestyle: str
    linewidth: float
    marker: str
    zorder: int


# hero 优先：EgoAnchor 实线、更粗、最高 zorder，其余基线弱化以突出对比。
_VARIANT_STYLES: dict[str, VariantStyle] = {
    "Arrival-Hold": VariantStyle("#5B8FB0", (0, (5, 2)), 1.1, "o", 2),
    "Capture-Hold": VariantStyle("#E8963A", (0, (4, 1, 1, 1)), 1.1, "s", 3),
    "One-Euro Anchor": VariantStyle("#5CA65C", (0, (1, 1.2)), 1.1, "^", 4),
    "EgoAnchor": VariantStyle("#D1495B", "solid", 1.9, "D", 6),
}

# 实验二组件消融：Full=EgoAnchor 红，四个消融各用独立可区分色。
ABLATION_ORDER = (
    "EgoAnchor",
    "EgoAnchor w/o capture-time alignment",
    "EgoAnchor w/o VCD",
    "EgoAnchor w/o temporal synthesis",
    "EgoAnchor w/o StaticLock",
)
"""实验二图例与坐标轴的固定消融顺序（Full 在前）。"""

ABLATION_SHORT = {
    "EgoAnchor": "Full",
    "EgoAnchor w/o capture-time alignment": "w/o Align",
    "EgoAnchor w/o VCD": "w/o VCD",
    "EgoAnchor w/o temporal synthesis": "w/o Synth",
    "EgoAnchor w/o StaticLock": "w/o Lock",
}
"""消融配置的紧凑刻度名。"""

_ABLATION_COLORS = {
    "EgoAnchor": "#D1495B",
    "EgoAnchor w/o capture-time alignment": "#E8963A",
    "EgoAnchor w/o VCD": "#5B8FB0",
    "EgoAnchor w/o temporal synthesis": "#8E7CC3",
    "EgoAnchor w/o StaticLock": "#5CA65C",
}

# 场景 → 论文展示名，供多场景网格标题复用。
SCENARIO_TITLE = {
    "static_head_motion": "Static + head motion",
    "start_stop_6dof": "Start–stop 6DoF",
    "continuous_translation": "Continuous translation",
    "continuous_rotation": "Continuous rotation",
    "occlusion_recovery": "Occlusion recovery",
}

_DIVERGING_WORSE = "#C1443C"
"""热力图中“消融比完整系统更差”的暖色。"""

_DIVERGING_BETTER = "#3B75AF"
"""热力图中“消融反而更好”的冷色。"""


def variant_color(label: str) -> str:
    """返回系统配置的固定语义颜色；未知配置回退中性灰。"""

    style = _VARIANT_STYLES.get(label)
    return style.color if style is not None else "#8C8C8C"


def variant_style(label: str) -> VariantStyle:
    """返回系统配置的完整线型编码；未知配置回退中性样式。"""

    return _VARIANT_STYLES.get(label, VariantStyle("#8C8C8C", "solid", 1.1, "o", 1))


def ablation_color(label: str) -> str:
    """返回实验二消融配置的固定颜色；未知配置回退中性灰。"""

    return _ABLATION_COLORS.get(label, "#8C8C8C")


def apply_paper_style() -> None:
    """设置全局 rcParams，保证字体嵌入与 IEEE VR camera-ready 风格一致。"""

    plt.rcParams.update(
        {
            # 42 = TrueType 嵌入，避免投稿系统拒绝 Type-3 字体。
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
            "font.size": 8.0,
            "axes.titlesize": 8.5,
            "axes.labelsize": 8.0,
            "xtick.labelsize": 7.0,
            "ytick.labelsize": 7.0,
            "legend.fontsize": 7.0,
            "axes.linewidth": 0.6,
            "axes.edgecolor": "#333333",
            "axes.labelcolor": "#1A1A1A",
            "text.color": "#1A1A1A",
            "xtick.color": "#333333",
            "ytick.color": "#333333",
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "xtick.major.size": 2.6,
            "ytick.major.size": 2.6,
            "lines.solid_capstyle": "round",
            "legend.frameon": False,
            "legend.handlelength": 1.8,
            "legend.columnspacing": 1.1,
            "legend.handletextpad": 0.5,
            "figure.dpi": 200,
            "savefig.dpi": 200,
            "axes.grid": False,
            "axes.axisbelow": True,
        }
    )


def new_figure(width_in: float, height_in: float) -> tuple[Figure, Axes]:
    """在应用论文风格后创建单轴图。"""

    apply_paper_style()
    figure, axes = plt.subplots(figsize=(width_in, height_in))
    style_axes(axes)
    return figure, axes


def style_axes(axes: Axes, *, grid_axis: str | None = "y") -> None:
    """去除上/右边框并施加低对比网格，统一所有子图观感。"""

    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    if grid_axis is not None:
        axes.grid(
            axis=grid_axis,
            color="#B8B8B8",
            alpha=0.35,
            linewidth=0.5,
            zorder=0,
        )


def panel_label(axes: Axes, text: str) -> None:
    """在子图左上角外侧放置面板标号，避免与标题或图例重叠。

    示例金标准图的缺陷正是标号压住了子图标题；这里统一放到坐标轴左上角
    外侧（轴坐标略高于 1.0、略偏左），与标题水平错开。
    """

    axes.annotate(
        text,
        xy=(0.0, 1.0),
        xycoords="axes fraction",
        xytext=(-26.0, 10.0),
        textcoords="offset points",
        fontsize=10.0,
        fontweight="bold",
        va="bottom",
        ha="left",
        annotation_clip=False,
    )


def distribution_glyph(
    axes: Axes,
    position: float,
    *,
    median: float,
    q1: float,
    q3: float,
    p95: float,
    color: str,
    width: float = 0.28,
    p5: float | None = None,
) -> None:
    """绘制 median/IQR/P95 分布 glyph（对标示例图 B 面板）。

    竖线覆盖 ``[p5 或 q1, p95]`` 的须，粗条表示 IQR，菱形标记中位数。该 glyph
    在极小面积内同时表达中心趋势、离散度与右尾，比单根柱信息量高得多。
    """

    lower = q1 if p5 is None else p5
    axes.vlines(position, lower, p95, color=color, linewidth=0.9, zorder=3)
    axes.add_patch(
        plt.Rectangle(
            (position - width / 2.0, q1),
            width,
            max(q3 - q1, 0.0),
            facecolor=color,
            edgecolor="none",
            alpha=0.85,
            zorder=4,
        )
    )
    axes.plot(
        position,
        median,
        marker="D",
        markersize=4.5,
        markerfacecolor="white",
        markeredgecolor=color,
        markeredgewidth=1.1,
        zorder=5,
    )


def shade_intervals(
    axes: Axes,
    intervals: Iterable[tuple[float, float]],
    *,
    color: str = "#7A7A7A",
    alpha: float = 0.14,
    label: str | None = None,
) -> None:
    """对一组 ``(start, end)`` 时间区间加背景阴影（如遮挡时段）。"""

    first = True
    for start, end in intervals:
        if not (np.isfinite(start) and np.isfinite(end)) or end <= start:
            continue
        axes.axvspan(
            start,
            end,
            color=color,
            alpha=alpha,
            linewidth=0.0,
            zorder=0,
            label=label if first else None,
        )
        first = False


def event_markers(
    axes: Axes,
    times: Iterable[float],
    *,
    color: str = "#555555",
) -> None:
    """在给定时刻画竖直参考线，用于标注相位或转换事件。"""

    for value in times:
        if np.isfinite(value):
            axes.axvline(
                value,
                color=color,
                linestyle=(0, (2, 2)),
                linewidth=0.6,
                alpha=0.55,
                zorder=1,
            )


def variant_legend(
    figure: Figure,
    labels: Sequence[str],
    *,
    kind: str = "line",
    ncol: int | None = None,
    y: float = 1.005,
) -> None:
    """在图顶部放置一行系统图例，颜色与线型来自固定语义编码。"""

    handles: list[Line2D | Patch] = []
    for label in labels:
        if kind == "line":
            style = variant_style(label)
            handles.append(
                Line2D(
                    [0],
                    [0],
                    color=style.color,
                    linestyle=style.linestyle,
                    linewidth=max(style.linewidth, 1.4),
                    label=label,
                )
            )
        else:
            color = variant_color(label) if kind == "variant" else ablation_color(label)
            handles.append(Patch(facecolor=color, edgecolor="none", label=label))
    figure.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, y),
        ncol=ncol or len(labels),
        frameon=False,
    )


def diverging_color(value: float, vmax: float) -> str:
    """把有符号差值映射到发散配色：正值(更差)暖、负值(更好)冷。"""

    if not np.isfinite(value) or vmax <= 0.0:
        return "#F0F0F0"
    magnitude = min(abs(value) / vmax, 1.0)
    base = _DIVERGING_WORSE if value >= 0.0 else _DIVERGING_BETTER
    # 在白底与目标色之间线性插值，magnitude 越大颜色越饱和。
    white = np.array([1.0, 1.0, 1.0])
    target = np.array(_hex_to_rgb(base))
    blended = white + (target - white) * (0.18 + 0.82 * magnitude)
    return _rgb_to_hex(blended)


def readable_text_color(background_hex: str) -> str:
    """按背景亮度返回黑或白文字色，保证热力图注释可读。"""

    r, g, b = _hex_to_rgb(background_hex)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#1A1A1A" if luminance > 0.6 else "#FFFFFF"


def save_figure(figure: Figure, path: str | Path) -> Path:
    """以矢量 PDF 保存并关闭图，使用紧凑 bbox 去除多余留白。"""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, format="pdf", bbox_inches="tight", pad_inches=0.02)
    plt.close(figure)
    return destination


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    """把 ``#RRGGBB`` 转为 0--1 浮点三元组。"""

    text = value.lstrip("#")
    return tuple(int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: np.ndarray) -> str:
    """把 0--1 浮点 RGB 数组转回 ``#RRGGBB``。"""

    clipped = np.clip(rgb, 0.0, 1.0)
    return "#" + "".join(f"{int(round(channel * 255)):02X}" for channel in clipped)


__all__ = [
    "ABLATION_ORDER",
    "ABLATION_SHORT",
    "COLUMN_WIDTH_IN",
    "GOLDEN",
    "SCENARIO_TITLE",
    "TEXT_WIDTH_IN",
    "VARIANT_ORDER",
    "VARIANT_SHORT",
    "VariantStyle",
    "ablation_color",
    "apply_paper_style",
    "diverging_color",
    "distribution_glyph",
    "event_markers",
    "new_figure",
    "panel_label",
    "readable_text_color",
    "readable_text_color",
    "save_figure",
    "shade_intervals",
    "style_axes",
    "variant_color",
    "variant_legend",
    "variant_style",
]
