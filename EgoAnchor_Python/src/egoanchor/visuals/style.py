"""实验图共用的论文视觉样式。"""

from __future__ import annotations

from typing import Any, cast

import matplotlib


PAPER_FONT_FAMILY = "DejaVu Sans"
"""论文图默认使用的跨平台无衬线字体。"""

PAPER_FONT_SIZE = 9.0
"""按双栏最终物理尺寸导出时的基础字号。"""

PAPER_DPI = 300
"""位图论文资源的默认导出分辨率。"""

PAPER_TEXT_COLOR = "#202428"
"""坐标、标题和正文标注使用的近黑色。"""

PAPER_MUTED_COLOR = "#596168"
"""次要标注和须弱化视觉层级的中性灰。"""

PAPER_PAIR_COLOR = "#8E969E"
"""配对线和逐样本辅助连线使用的浅灰。"""

PAPER_GRID_COLOR = "#D6DBDF"
"""浅色横向参考网格。"""

PAPER_EDGE_COLOR = "#70767C"
"""坐标轴边框使用的中性灰。"""


def apply_paper_style(*, font_size: float = PAPER_FONT_SIZE, dpi: int = PAPER_DPI) -> None:
    """把统一字号、颜色和矢量字体设置应用到 Matplotlib。"""

    if font_size <= 0.0:
        raise ValueError("论文图字号必须为正数")
    if dpi <= 0:
        raise ValueError("论文图 DPI 必须为正整数")
    parameters = _paper_rc_params(font_size=font_size, dpi=dpi)
    matplotlib.rcParams.update(cast(Any, parameters))


def _paper_rc_params(*, font_size: float, dpi: int) -> dict[str, Any]:
    """构造各实验共享的 Matplotlib 参数，避免局部样式逐渐分叉。"""

    tick_size = max(7.5, font_size - 0.6)
    legend_size = max(7.5, font_size - 0.5)
    return {
        "font.family": PAPER_FONT_FAMILY,
        "font.size": font_size,
        "text.color": PAPER_TEXT_COLOR,
        "axes.labelcolor": PAPER_TEXT_COLOR,
        "axes.labelsize": font_size,
        "axes.titlesize": font_size,
        "axes.titleweight": "bold",
        "axes.titlepad": 4.0,
        "axes.linewidth": 0.8,
        "axes.edgecolor": PAPER_EDGE_COLOR,
        "xtick.color": PAPER_TEXT_COLOR,
        "xtick.labelsize": tick_size,
        "ytick.color": PAPER_TEXT_COLOR,
        "ytick.labelsize": tick_size,
        "legend.fontsize": legend_size,
        "savefig.dpi": dpi,
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }


__all__ = [
    "PAPER_DPI",
    "PAPER_EDGE_COLOR",
    "PAPER_FONT_FAMILY",
    "PAPER_FONT_SIZE",
    "PAPER_GRID_COLOR",
    "PAPER_MUTED_COLOR",
    "PAPER_PAIR_COLOR",
    "PAPER_TEXT_COLOR",
    "apply_paper_style",
]
