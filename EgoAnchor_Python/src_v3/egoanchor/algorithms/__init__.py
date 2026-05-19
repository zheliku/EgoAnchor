"""v3 algorithms 层包级入口。

本层只负责把单个模型或第三方算法封装成清晰的小适配器，不理解 ZMQ、NATS、
Unity world anchor 或 runtime 状态机。外部代码应从 `egoanchor.algorithms` 包级
入口导入数据结构和算法类，避免依赖具体文件路径，便于后续替换实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

import numpy as np


@dataclass(slots=True)
class SegmenterResult:
    """2D 单目标分割结果。"""

    overlay_bgr: np.ndarray
    """用于 OpenCV debug 的 BGR 可视化图。"""

    mask_bw: np.ndarray
    """下游真实使用的单目标二值 mask，uint8，前景为 255。"""

    det_count: int
    """模型原始检测数量，便于判断是否处于 WAIT_DETECT。"""

    infer_ms: float
    """分割模型单帧推理耗时，单位毫秒。"""

    prompt: list[str]
    """当前 YOLOE 文本提示词列表。"""

    selected_index: int = -1
    """被选中的 mask 下标；没有有效 mask 时为 -1。"""

    mask_area_ratio: float = 0.0
    """mask 前景面积占整图比例，用于可靠性诊断。"""


@dataclass(slots=True)
class MaskTrackResult:
    """2D mask tracker 单帧输出。"""

    bbox_xywh: list[int]
    """由 tracker mask 提取出的 bbox，格式为 [x, y, w, h]。"""

    mask: np.ndarray
    """tracker 输出的二值或标签 mask，shape 与输入图像一致。"""


_LAZY_EXPORTS = {
    "Yoloe26Segmenter": "egoanchor.algorithms.yoloe26_segmenter",
    "FastFoundationStereoDepth": "egoanchor.algorithms.fast_foundationstereo_depth",
    "FoundationPoseObjectEstimator": "egoanchor.algorithms.foundationpose_estimator",
    "CutieMaskTracker": "egoanchor.algorithms.cutie_mask_tracker",
}


def __getattr__(name: str) -> Any:
    """惰性加载重模型适配器，避免普通 import 触发 CUDA/torch 初始化。"""

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
