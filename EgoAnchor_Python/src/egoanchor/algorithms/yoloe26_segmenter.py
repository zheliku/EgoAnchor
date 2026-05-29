"""YOLOE-26 单目标分割适配器。

本文件是当前主线实现，目标是保留既有算法链路中验证过的 YOLOE-26 使用方式，
但不 import v1/v2 运行时代码。适配器只输出单个最可信 mask，避免多个误检
合并后污染后续 FoundationPose register。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
import torch
from ultralytics import YOLOE

from egoanchor.algorithms import SegmenterResult


class Yoloe26Segmenter:
    """YOLOE-26 prompt segmentation 封装。"""

    def __init__(
        self,
        model_path: str | Path,
        init_prompt: str | list[str],
        conf: float = 0.1,
        imgsz: int = 640,
        max_det: int = 1,
        mask_threshold: float = 0.5,
        use_half: bool = False,
        device: str | int | None = None,
        mobileclip2_path: str | Path | None = None,
    ) -> None:
        """加载 YOLOE 权重，并设置初始文本提示词。"""

        self.model_path = Path(model_path).expanduser().resolve()
        """YOLOE segmentation 权重绝对路径。"""

        self.conf = float(conf)
        """检测置信度阈值，越低越容易召回但也更容易误检。"""

        self.imgsz = int(imgsz)
        """YOLOE 推理输入尺寸。"""

        self.max_det = int(max_det)
        """最多保留检测数量；默认保持单目标。"""

        self.mask_threshold = float(mask_threshold)
        """mask 概率二值化阈值。"""

        self.use_half = bool(use_half)
        """是否使用半精度推理。"""

        self.device = 0 if device is None and torch.cuda.is_available() else ("cpu" if device is None else device)
        """YOLOE 推理设备；auto 会在有 CUDA 时使用 0 号 GPU。"""

        self.mobileclip2_path = Path(mobileclip2_path).expanduser().resolve() if mobileclip2_path else None
        """本地 mobileclip2_b.ts 路径，用于离线环境。"""

        self._prompt: list[str] = []
        """当前已写入模型的文本提示词缓存。"""

        if not self.model_path.is_file():
            raise FileNotFoundError(f"YOLOE 权重不存在: {self.model_path}")
        self._configure_mobileclip2_path()

        self.model = YOLOE(str(self.model_path))
        """Ultralytics YOLOE 模型实例。"""

        self.set_prompt(init_prompt)
        self.model.fuse()

    def _configure_mobileclip2_path(self) -> None:
        """让 Ultralytics 优先使用项目内的 mobileclip2_b.ts。"""

        if self.mobileclip2_path is None:
            return
        if not self.mobileclip2_path.is_file():
            raise FileNotFoundError(f"mobileclip2 文件不存在: {self.mobileclip2_path}")

        from ultralytics.utils import SETTINGS

        SETTINGS["weights_dir"] = str(self.mobileclip2_path.parent)
        std_name = self.mobileclip2_path.parent / "mobileclip2_b.ts"
        if self.mobileclip2_path.name != "mobileclip2_b.ts" and not std_name.exists():
            shutil.copy2(self.mobileclip2_path, std_name)

    @staticmethod
    def _normalize_prompt(prompt: str | list[str]) -> list[str]:
        """把 prompt 统一成非空字符串列表。"""

        items = [prompt] if isinstance(prompt, str) else list(prompt)
        items = [item.strip() for item in items if item.strip()]
        if not items:
            raise ValueError("YOLOE prompt 不能为空。")
        return items

    @staticmethod
    def _ensure_bgr_u8(image: np.ndarray) -> np.ndarray:
        """把输入图像统一成 OpenCV BGR uint8 三通道。"""

        if image.ndim == 2:
            out = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.ndim == 3:
            out = image[..., :3]
        else:
            raise ValueError("image 维度不正确，应为 (H,W) 或 (H,W,C)。")
        if out.dtype != np.uint8:
            out = np.clip(out, 0, 255).astype(np.uint8)
        return out

    def set_prompt(self, prompt: str | list[str]) -> None:
        """更新文本提示词；只有内容变化时才调用模型 set_classes。"""

        prompt_list = self._normalize_prompt(prompt)
        if prompt_list != self._prompt:
            self.model.set_classes(prompt_list)
            self._prompt = prompt_list

    def infer(self, image_bgr: np.ndarray, prompt: str | list[str] | None = None) -> SegmenterResult:
        """执行单帧分割，返回一个被选中的目标 mask。"""

        if prompt is not None:
            self.set_prompt(prompt)
        frame = self._ensure_bgr_u8(image_bgr)

        t0 = time.perf_counter()
        result = self.model.predict(
            source=frame,
            conf=self.conf,
            imgsz=self.imgsz,
            max_det=self.max_det,
            device=self.device,
            half=self.use_half,
            save=False,
            verbose=False,
        )[0]
        infer_ms = (time.perf_counter() - t0) * 1000.0

        overlay = result.plot()
        det_count = int(len(result.boxes.data)) if result.boxes is not None and result.boxes.data is not None else 0
        selected_index = -1
        selected_score = -1.0

        if result.masks is None or result.masks.data is None or len(result.masks.data) == 0:
            mask_bw = np.zeros(frame.shape[:2], dtype=np.uint8)
        else:
            masks_data = cast(Any, result.masks.data)
            masks = masks_data.detach().cpu().numpy() if hasattr(masks_data, "detach") else np.asarray(masks_data)
            binary_masks = (masks >= self.mask_threshold).astype(np.uint8) * 255

            scores = np.ones((binary_masks.shape[0],), dtype=np.float32)
            if result.boxes is not None and getattr(result.boxes, "conf", None) is not None:
                conf = result.boxes.conf
                scores = conf.detach().cpu().numpy().astype(np.float32) if hasattr(conf, "detach") else np.asarray(conf, dtype=np.float32)

            areas = binary_masks.reshape(binary_masks.shape[0], -1).sum(axis=1)
            valid = areas > 0
            if np.any(valid):
                score = scores[: binary_masks.shape[0]].copy()
                score[~valid] = -1.0
                selected_index = int(np.argmax(score))
                selected_score = float(score[selected_index])
                mask_bw = binary_masks[selected_index]
            else:
                mask_bw = np.zeros(frame.shape[:2], dtype=np.uint8)

        if mask_bw.shape[:2] != frame.shape[:2]:
            mask_bw = cv2.resize(mask_bw, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_NEAREST)

        mask_area_ratio = float(np.count_nonzero(mask_bw)) / float(max(mask_bw.size, 1))
        return SegmenterResult(
            overlay_bgr=overlay,
            mask_bw=mask_bw,
            det_count=det_count,
            infer_ms=infer_ms,
            prompt=list(self._prompt),
            selected_index=selected_index,
            selected_score=selected_score,
            mask_area_ratio=mask_area_ratio,
        )

