"""2D 目标分割算法接口。

Perception pipeline 只依赖这里定义的抽象接口，不直接绑定 YOLOE/SAM3 等具体模型。
这样后续删除旧 src 目录或替换分割器时，pipeline 主逻辑不需要重写。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(slots=True)
class SegmenterResult:
    """单帧分割输出。

    属性说明：
    - overlay_bgr：便于调试显示的 BGR 叠加图。
    - mask_bw：下游实际使用的单目标二值 mask，uint8，0=背景，255=目标。
    - det_count：模型检测到的候选数量。
    - infer_ms：分割模型耗时，单位毫秒。
    - prompt：当前生效的文本提示词列表。
    - selected_index：被选中进入下游的候选下标；无有效目标时为 -1。
    - mask_area_ratio：目标 mask 面积占整幅图比例。
    """

    overlay_bgr: np.ndarray
    mask_bw: np.ndarray
    det_count: int
    infer_ms: float
    prompt: list[str]
    selected_index: int = -1
    mask_area_ratio: float = 0.0


class ObjectSegmenter(Protocol):
    """目标分割器协议。"""

    def infer(self, image_bgr: np.ndarray, prompt: str | list[str] | None = None) -> SegmenterResult:
        """输入 BGR 图像，输出单目标 mask 与调试叠加图。"""
