"""algorithms 层包级入口。

本层只负责把单个模型或第三方算法封装成清晰的小适配器，不理解 ZMQ、NATS、
Unity world anchor 或 runtime 状态机。外部代码应从 `egoanchor.algorithms` 包级
入口导入数据结构和算法类，避免依赖具体文件路径，便于后续替换实现。
"""

from __future__ import annotations

from dataclasses import dataclass

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
    """当前分割后端使用的文本提示词列表。"""

    selected_index: int = -1
    """被选中的 mask 下标；没有有效 mask 时为 -1。"""

    mask_area_ratio: float = 0.0
    """mask 前景面积占整图比例，用于可靠性诊断。"""

    selected_score: float = -1.0
    """被选中检测结果的模型分数；没有有效检测或后端未提供分数时为 -1。"""


@dataclass(slots=True)
class MaskTrackResult:
    """2D mask tracker 单帧输出。"""

    bbox_xywh: list[int]
    """由 tracker mask 提取出的 bbox，格式为 [x, y, w, h]。"""

    mask: np.ndarray
    """tracker 输出的二值或标签 mask，shape 与输入图像一致。"""


from .cutie_mask_tracker import CutieMaskTracker
from .fast_foundationstereo_depth import FastFoundationStereoDepth
from .foundationpose_estimator import FoundationPoseObjectEstimator
from .sam3_segmenter import Sam3Segmenter, disable_sam3_position_precompute, select_best_sam3_mask
from .yoloe26_segmenter import Yoloe26Segmenter


__all__ = [
    "SegmenterResult",
    "MaskTrackResult",
    "Yoloe26Segmenter",
    "Sam3Segmenter",
    "select_best_sam3_mask",
    "disable_sam3_position_precompute",
    "FastFoundationStereoDepth",
    "FoundationPoseObjectEstimator",
    "CutieMaskTracker",
]

