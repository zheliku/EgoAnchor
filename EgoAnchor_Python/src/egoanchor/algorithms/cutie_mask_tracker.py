"""Cutie 2D mask tracker 适配器。

Cutie 只负责 2D mask/bbox 的时序传播，是否用 bbox 轻量修正 6D pose 由
perception pipeline 决定。本文件不引用旧 v1/v2 封装。
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

from .foundationpose_estimator import FoundationPoseObjectEstimator


class CutieMaskTracker:
    """Cutie 2D mask tracker 封装。"""

    def __init__(
        self,
        seg_threshold: float = 0.1,
        erosion_size: int = 5,
        project_root: str | Path | None = None,
        enable_logging: bool = False,
    ) -> None:
        """初始化 Cutie 模型与时序推理核心。"""

        self.seg_threshold = float(seg_threshold)
        """Cutie 分割概率阈值；当前保留给后续概率图过滤。"""

        self.erosion_size = int(erosion_size)
        """从 mask 提取 bbox 前使用的腐蚀核大小。"""

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        """Cutie 推理设备。"""

        self.enable_logging = bool(enable_logging)
        """是否允许 Cutie 内部 stdout/stderr/logging 输出到 console。"""

        self.project_root = Path(project_root).resolve() if project_root is not None else Path(__file__).resolve().parents[3]
        """EgoAnchor_Python 项目根目录。"""

        if str(self.project_root) not in sys.path:
            sys.path.insert(0, str(self.project_root))

        cutie_pkg = FoundationPoseObjectEstimator.call_with_logging_control(
            importlib.import_module,
            "Cutie.cutie",
            enable_logging=self.enable_logging,
        )
        sys.modules["cutie"] = cutie_pkg

        InferenceCore, get_default_model = FoundationPoseObjectEstimator.call_with_logging_control(
            self._load_cutie_symbols,
            enable_logging=self.enable_logging,
        )

        self.InferenceCore = InferenceCore
        """Cutie 时序推理核心类型。"""

        self.model: Any = FoundationPoseObjectEstimator.call_with_logging_control(get_default_model, enable_logging=self.enable_logging)
        """Cutie 默认模型实例。"""

        if hasattr(self.model, "to"):
            self.model = self.model.to(self.device)
        self.processor = FoundationPoseObjectEstimator.call_with_logging_control(
            self.InferenceCore,
            self.model,
            cfg=self.model.cfg,
            enable_logging=self.enable_logging,
        )
        """当前时序推理核心，持有上一帧 memory。"""

        self.processor.max_internal_size = -1

    @staticmethod
    def _ensure_rgb(frame: np.ndarray) -> np.ndarray:
        """统一输入为 RGB 三通道。"""

        if frame.ndim == 2:
            return np.repeat(frame[..., None], 3, axis=2)
        if frame.ndim == 3:
            return frame[..., :3]
        raise ValueError("frame 维度不正确，应为 (H,W) 或 (H,W,C)。")

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

    def initialize(self, frame: np.ndarray, init_mask: np.ndarray | None = None, init_bbox: list[int] | None = None) -> MaskTrackResult:
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
        """跟踪当前 RGB 帧并输出 mask 与 bbox。"""

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
        """重建 InferenceCore，清空上一目标的时序 memory。"""

        self.processor = FoundationPoseObjectEstimator.call_with_logging_control(
            self.InferenceCore,
            self.model,
            cfg=self.model.cfg,
            enable_logging=self.enable_logging,
        )
        self.processor.max_internal_size = -1

    @staticmethod
    def _load_cutie_symbols() -> tuple[Any, Any]:
        """导入 Cutie 推理核心和默认模型入口，便于统一控制第三方 import 输出。"""

        from cutie.inference.inference_core import InferenceCore
        from cutie.utils.get_default_model import get_default_model

        return InferenceCore, get_default_model
