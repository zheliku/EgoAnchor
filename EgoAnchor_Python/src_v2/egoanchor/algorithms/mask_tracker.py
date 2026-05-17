"""2D mask tracking 算法接口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(slots=True)
class MaskTrackResult:
    """2D mask tracker 单帧输出。

    bbox_xywh 使用图像坐标 [x, y, w, h]；mask 为 0/1 或 0/255 均可，
    pipeline 会在使用前统一二值化。
    """

    bbox_xywh: list[int]
    mask: np.ndarray


class MaskTracker2D(Protocol):
    """Cutie 等 2D mask tracker 的统一协议。"""

    def initialize(
        self,
        frame: np.ndarray,
        init_mask: np.ndarray | None = None,
        init_bbox: list[int] | None = None,
    ) -> MaskTrackResult:
        """用初始 mask 或 bbox 初始化跟踪器。"""

    def track(self, frame: np.ndarray) -> MaskTrackResult:
        """跟踪当前帧并返回 mask/bbox。"""

    def reset(self) -> None:
        """清理时序 memory。"""
