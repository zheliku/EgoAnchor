"""v2 algorithms 层统一导出入口。

约定：
- 外部代码只从 `egoanchor.algorithms` 导入算法数据结构或具体适配器，避免散落
  `egoanchor.algorithms.xxx` 的深层导入路径。
- 本包不再维护只有 `Protocol` 的空基类；当前每类算法只有一个 v2 实现，直接使用
  具体适配器更清晰。
- 具体模型类使用惰性导入，避免纯配置/测试路径 import 本包时就加载 YOLOE、torch、
  FoundationPose 或 Cutie 等重依赖。
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

import numpy as np


@dataclass(slots=True)
class SegmenterResult:
    """2D 分割单帧输出。

    `mask_bw` 是下游真实使用的单目标二值 mask，`overlay_bgr` 只用于 OpenCV debug。
    """

    overlay_bgr: np.ndarray
    mask_bw: np.ndarray
    det_count: int
    infer_ms: float
    prompt: list[str]
    selected_index: int = -1
    mask_area_ratio: float = 0.0


@dataclass(slots=True)
class MaskTrackResult:
    """2D mask tracker 单帧输出。"""

    bbox_xywh: list[int]
    mask: np.ndarray


_LAZY_EXPORTS = {
    "Yoloe26Segmenter": "egoanchor.algorithms.yoloe26_segmenter",
    "FastFoundationStereoDepth": "egoanchor.algorithms.fast_foundationstereo_depth",
    "FoundationPoseObjectEstimator": "egoanchor.algorithms.foundationpose_estimator",
    "CutieMaskTracker": "egoanchor.algorithms.cutie_mask_tracker",
}


def __getattr__(name: str) -> Any:
    """按需加载具体算法实现，减少 import 包时的副作用。"""

    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "SegmenterResult",
    "MaskTrackResult",
    "Yoloe26Segmenter",
    "FastFoundationStereoDepth",
    "FoundationPoseObjectEstimator",
    "CutieMaskTracker",
]
