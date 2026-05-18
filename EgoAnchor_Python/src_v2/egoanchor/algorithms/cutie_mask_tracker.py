"""Cutie mask tracker v2 适配器。

该实现重新落地旧主线的 Cutie 封装，不 import `src/modules/cutie.py`。
它只负责 2D mask/bbox 跟踪，6D pose 修正由 perception pipeline 决定。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from torchvision.transforms.functional import to_tensor

from egoanchor.algorithms import MaskTrackResult


class CutieMaskTracker:
    """Cutie 2D mask tracker 适配器。"""

    def __init__(self, seg_threshold: float = 0.1, erosion_size: int = 5, project_root: str | Path | None = None) -> None:
        """初始化 Cutie 模型与时序推理核心。"""

        # 基础后处理参数：seg_threshold 当前保留给后续概率阈值扩展，erosion_size 用于 bbox 抗噪。
        self.seg_threshold = float(seg_threshold)
        self.erosion_size = int(erosion_size)
        # Cutie 只负责 2D mask 传播；设备选择在适配器内部完成，不暴露到 perception pipeline。
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.project_root = Path(project_root).resolve() if project_root is not None else Path(__file__).resolve().parents[3]

        if str(self.project_root) not in sys.path:
            sys.path.insert(0, str(self.project_root))

        # Cutie 包内部大量使用 `from cutie.xxx import ...`，因此把真正包注册为顶级别名。
        cutie_pkg = importlib.import_module("Cutie.cutie")
        sys.modules["cutie"] = cutie_pkg

        from cutie.inference.inference_core import InferenceCore
        from cutie.utils.get_default_model import get_default_model

        # InferenceCore 持有时序 memory；reset() 会重建它，避免旧目标污染新 register。
        self.InferenceCore = InferenceCore
        self.model: Any = get_default_model()
        if hasattr(self.model, "to"):
            self.model = self.model.to(self.device)
        self.processor = self.InferenceCore(self.model, cfg=self.model.cfg)
        self.processor.max_internal_size = -1

    @staticmethod
    def _ensure_rgb(frame: np.ndarray) -> np.ndarray:
        """统一输入为 RGB 三通道。"""

        if frame.ndim == 2:
            frame = np.repeat(frame[..., None], 3, axis=2)
        elif frame.ndim == 3:
            frame = frame[..., :3]
        else:
            raise ValueError("frame 维度不正确，应为 (H,W) 或 (H,W,C)。")
        return frame

    @staticmethod
    def _mask_from_bbox(height: int, width: int, bbox_xywh: list[int]) -> np.ndarray:
        """由 bbox 生成初始化 mask。"""

        x, y, bw, bh = [int(v) for v in bbox_xywh]
        mask = np.zeros((height, width), dtype=np.uint8)
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(width, x + max(0, bw))
        y1 = min(height, y + max(0, bh))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = 1
        return mask

    def _bbox_from_mask(self, mask: np.ndarray) -> list[int]:
        """从 mask 提取 [x,y,w,h]，先腐蚀以减少边缘噪声。"""

        kernel_size = max(int(self.erosion_size), 1)
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        mask_eroded = cv2.erode((mask > 0).astype(np.uint8), kernel, iterations=1)
        rows = np.any(mask_eroded, axis=1)
        cols = np.any(mask_eroded, axis=0)
        if np.any(rows) and np.any(cols):
            y_min, y_max = np.where(rows)[0][[0, -1]]
            x_min, x_max = np.where(cols)[0][[0, -1]]
            return [int(x_min), int(y_min), int(x_max - x_min), int(y_max - y_min)]
        return [-1, -1, 0, 0]

    def initialize(
        self,
        frame: np.ndarray,
        init_mask: np.ndarray | None = None,
        init_bbox: list[int] | None = None,
    ) -> MaskTrackResult:
        """用首帧 mask 或 bbox 初始化 Cutie memory。"""

        frame = self._ensure_rgb(frame)
        if init_mask is None and init_bbox is None:
            raise ValueError("Cutie initialize 需要 init_mask 或 init_bbox。")
        if init_mask is None:
            init_mask = self._mask_from_bbox(frame.shape[0], frame.shape[1], init_bbox or [-1, -1, 0, 0])
        else:
            init_mask = (init_mask > 0).astype(np.uint8)

        with torch.no_grad():
            frame_t = to_tensor(frame).to(self.device).float()
            mask_t = torch.from_numpy(init_mask).to(self.device)
            objects = np.unique(init_mask)
            objects = objects[objects != 0].tolist()
            prob = self.processor.step(frame_t, mask_t, objects=objects)
            out_mask_t = self.processor.output_prob_to_mask(prob)
            out_mask = out_mask_t.detach().cpu().numpy().astype(np.uint8)

        bbox_xywh = self._bbox_from_mask(out_mask)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return MaskTrackResult(bbox_xywh=bbox_xywh, mask=out_mask)

    def track(self, frame: np.ndarray) -> MaskTrackResult:
        """跟踪当前 RGB 帧。"""

        frame = self._ensure_rgb(frame)
        with torch.no_grad():
            frame_t = to_tensor(frame).to(self.device).float()
            prob = self.processor.step(frame_t)
            out_mask_t = self.processor.output_prob_to_mask(prob)
            out_mask = out_mask_t.detach().cpu().numpy().astype(np.uint8)

        bbox_xywh = self._bbox_from_mask(out_mask)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return MaskTrackResult(bbox_xywh=bbox_xywh, mask=out_mask)

    def reset(self) -> None:
        """重建 InferenceCore，清理上一目标的时序 memory。"""

        self.processor = self.InferenceCore(self.model, cfg=self.model.cfg)
        self.processor.max_internal_size = -1
