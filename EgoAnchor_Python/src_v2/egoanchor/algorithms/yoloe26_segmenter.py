"""YOLOE-26 分割器 v2 适配器。

该文件把旧主线中有效的 YOLOE 调用方式迁移到 v2 algorithms 层，
但不 import `EgoAnchor_Python/src/modules/yoloe26.py`。后续删除旧 src 目录时，
v2 pipeline 仍然自洽可运行。
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

from egoanchor.algorithms.segmenter import SegmenterResult


class Yoloe26Segmenter:
    """YOLOE-26 单目标 prompt segmentation 适配器。

    设计要点：
    - 只输出一个被选中的目标 mask，避免多误检 union 污染 FoundationPose。
    - prompt 变化时才更新模型类别，减少实时循环开销。
    - 输入输出均使用 OpenCV BGR / uint8，pipeline 里再按需要转 RGB。
    """

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
        self.model_path = Path(model_path).expanduser().resolve()
        self.conf = float(conf)
        self.imgsz = int(imgsz)
        self.max_det = int(max_det)
        self.mask_threshold = float(mask_threshold)
        self.use_half = bool(use_half)
        self.device = 0 if device is None and torch.cuda.is_available() else ("cpu" if device is None else device)
        self.mobileclip2_path = Path(mobileclip2_path).expanduser().resolve() if mobileclip2_path else None
        self._prompt: list[str] = []

        if not self.model_path.is_file():
            raise FileNotFoundError(f"YOLOE 权重不存在: {self.model_path}")
        self._configure_mobileclip2_path()

        self.model = YOLOE(str(self.model_path))
        self.set_prompt(init_prompt)
        self.model.fuse()

    def _configure_mobileclip2_path(self) -> None:
        """让 Ultralytics 在离线/内网环境优先使用本地 mobileclip2_b.ts。"""

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
        """统一 prompt 为非空字符串列表。"""

        items = [prompt] if isinstance(prompt, str) else list(prompt)
        items = [x.strip() for x in items if x.strip()]
        if not items:
            raise ValueError("YOLOE prompt 不能为空。")
        return items

    @staticmethod
    def _ensure_bgr_u8(image: np.ndarray) -> np.ndarray:
        """把输入图像标准化为 BGR uint8 三通道。"""

        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.ndim == 3:
            image = image[..., :3]
        else:
            raise ValueError("image 维度不正确，应为 (H,W) 或 (H,W,C)。")
        if image.dtype != np.uint8:
            image = np.clip(image, 0, 255).astype(np.uint8)
        return image

    def set_prompt(self, prompt: str | list[str]) -> None:
        """更新文本提示词，仅在变化时调用 YOLOE set_classes。"""

        prompt_list = self._normalize_prompt(prompt)
        if prompt_list != self._prompt:
            self.model.set_classes(prompt_list)
            self._prompt = prompt_list

    def infer(self, image_bgr: np.ndarray, prompt: str | list[str] | None = None) -> SegmenterResult:
        """执行单帧分割并返回单目标 mask。"""

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

        # Ultralytics plot() 返回 BGR 图，可直接给 OpenCV 显示。
        overlay = result.plot()
        det_count = int(len(result.boxes.data)) if result.boxes is not None and result.boxes.data is not None else 0

        selected_index = -1
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
                mask_bw = binary_masks[selected_index]
            else:
                mask_bw = np.zeros(frame.shape[:2], dtype=np.uint8)

        if mask_bw.shape[:2] != frame.shape[:2]:
            mask_bw = cv2.resize(mask_bw, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_NEAREST)

        mask_area_ratio = float(np.count_nonzero(mask_bw)) / float(mask_bw.size)
        return SegmenterResult(
            overlay_bgr=overlay,
            mask_bw=mask_bw,
            det_count=det_count,
            infer_ms=infer_ms,
            prompt=list(self._prompt),
            selected_index=selected_index,
            mask_area_ratio=mask_area_ratio,
        )
