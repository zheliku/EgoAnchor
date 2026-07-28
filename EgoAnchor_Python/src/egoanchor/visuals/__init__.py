"""论文图和定性 replay 共用的视觉编码。"""

from __future__ import annotations


ARRIVAL_COLOR_HEX = "#4C78A8"
"""Arrival-Hold 的论文蓝色。"""

CAPTURE_COLOR_HEX = "#F28E2B"
"""Capture-Hold 的论文橙色。"""

ONE_EURO_COLOR_HEX = "#59A14F"
"""One-Euro Anchor 的论文绿色。"""

EGOANCHOR_COLOR_HEX = "#E15759"
"""EgoAnchor 的论文红色。"""

METHOD_COLORS_HEX = (
    ARRIVAL_COLOR_HEX,
    CAPTURE_COLOR_HEX,
    ONE_EURO_COLOR_HEX,
    EGOANCHOR_COLOR_HEX,
)
"""Arrival、Capture、One-Euro、EgoAnchor 的固定论文顺序。"""


__all__ = [
    "ARRIVAL_COLOR_HEX",
    "CAPTURE_COLOR_HEX",
    "EGOANCHOR_COLOR_HEX",
    "METHOD_COLORS_HEX",
    "ONE_EURO_COLOR_HEX",
]
