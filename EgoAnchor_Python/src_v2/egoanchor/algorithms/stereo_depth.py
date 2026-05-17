"""双目深度算法接口。"""

from __future__ import annotations

from typing import Protocol

import numpy as np


class StereoDepthEstimator(Protocol):
    """双目深度估计器协议。"""

    def predict_depth(
        self,
        left_image: np.ndarray,
        right_image: np.ndarray,
        fx: float,
        baseline: float,
        return_timing: bool = False,
    ) -> np.ndarray | tuple[np.ndarray, dict[str, float]]:
        """由左右图、焦距和基线预测米制深度图。"""
