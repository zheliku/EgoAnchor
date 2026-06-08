"""SAM3 文本提示分割适配器。

本适配器把项目内 ``EgoAnchor_Python/sam3`` 的 SAM3 image processor 包装为
EgoAnchor algorithms 层统一的 ``SegmenterResult``。它只负责单帧 2D mask，不理解
ZMQ/NATS、Quest frame_id、FoundationPose 或 Unity anchor 语义。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from egoanchor.algorithms import SegmenterResult
from egoanchor.utils import configure_thirdparty_logging, ensure_bgr_u8
from .segmenter_utils import normalize_prompt, select_best_mask, to_numpy


def select_best_sam3_mask(
    masks: Any,
    scores: Any | None,
    frame_shape: tuple[int, int],
    threshold: float = 0.5,
) -> tuple[np.ndarray, int, float, float]:
    """从 SAM3 多实例输出中选择最高分的非空 mask。

    下游 FoundationPose register 需要单目标 mask，因此这里不做 union。空 mask
    即使分数高也会被跳过，避免误把无效检测当作目标。
    """

    return select_best_mask(masks, scores, frame_shape, threshold)


def disable_sam3_position_precompute(model_builder_module: Any) -> None:
    """禁用 SAM3 构建阶段的位置编码预计算慢路径。

    SAM3 官方 builder 会用 ``precompute_resolution=1008`` 预先计算多尺度
    position encoding 缓存。EgoAnchor 当前没有启用 torch.compile，这个预计算
    不是必需路径；在 Windows/CUDA 上它会造成启动阶段长时间无窗口刷新。
    """

    if getattr(model_builder_module, "_egoanchor_position_precompute_disabled", False):
        return
    original = model_builder_module._create_position_encoding

    def _create_position_encoding_without_precompute(precompute_resolution: int | None = None) -> Any:
        """忽略官方 hardcoded precompute_resolution，改为后续按需计算。"""

        return original(precompute_resolution=None)

    model_builder_module._create_position_encoding = _create_position_encoding_without_precompute
    model_builder_module._egoanchor_position_precompute_disabled = True


class Sam3Segmenter:
    """SAM3 文本提示单目标分割器。"""

    def __init__(
        self,
        repo_path: str | Path,
        checkpoint_path: str | Path,
        init_prompt: str | list[str],
        confidence_threshold: float = 0.5,
        resolution: int = 1008,
        mask_threshold: float = 0.5,
        device: str = "auto",
        load_from_hf: bool = False,
        disable_position_precompute: bool = True,
        enable_logging: bool = False,
    ) -> None:
        """加载 SAM3 image model，并设置初始文本提示词。"""

        self.repo_path = Path(repo_path).expanduser().resolve()
        """项目内 SAM3 仓库根目录，即包含二级 sam3 package 的目录。"""

        self.checkpoint_path = Path(checkpoint_path).expanduser().resolve()
        """SAM3 checkpoint 文件路径。"""

        self.confidence_threshold = float(confidence_threshold)
        """SAM3 检测置信度阈值，越高越严格。"""

        self.resolution = int(resolution)
        """SAM3 processor 输入分辨率。"""

        self.mask_threshold = float(mask_threshold)
        """SAM3 mask 概率或布尔 mask 的二值化阈值。"""

        self.device = self._normalize_device(device)
        """SAM3 推理设备。"""

        self.load_from_hf = bool(load_from_hf)
        """是否允许从 HuggingFace 下载权重；主线默认关闭，使用本地 checkpoint。"""

        self.disable_position_precompute = bool(disable_position_precompute)
        """是否跳过 SAM3 构建阶段的位置编码预计算慢路径。"""

        self.enable_logging = bool(enable_logging)
        """是否允许 SAM3 内部 stdout/stderr/logging 输出到 console。"""

        self._prompt = normalize_prompt(init_prompt, "SAM3")
        """当前文本提示词缓存。"""

        if not self.repo_path.is_dir():
            raise FileNotFoundError(f"SAM3 仓库目录不存在: {self.repo_path}")
        if not self.checkpoint_path.is_file() and not self.load_from_hf:
            raise FileNotFoundError(f"SAM3 checkpoint 不存在: {self.checkpoint_path}")

        self._configure_sam3_logging(self.enable_logging)
        Sam3Processor, sam3_model_builder = self._load_sam3_symbols()

        if self.disable_position_precompute:
            disable_sam3_position_precompute(sam3_model_builder)

        checkpoint = str(self.checkpoint_path) if self.checkpoint_path.is_file() else None
        self.model = sam3_model_builder.build_sam3_image_model(
            checkpoint_path=checkpoint,
            load_from_HF=self.load_from_hf,
            device=self.device,
        )
        """SAM3 image model。"""

        self.processor = Sam3Processor(
            self.model,
            resolution=self.resolution,
            device=self.device,
            confidence_threshold=self.confidence_threshold,
        )
        """SAM3 image processor。"""

    @staticmethod
    def _configure_sam3_logging(enabled: bool) -> None:
        """配置 SAM3 子工程 logger，默认不向 console 传播。"""

        configure_thirdparty_logging("sam3", enabled)

    @staticmethod
    def _load_sam3_symbols() -> tuple[Any, Any]:
        """导入 SAM3 image processor 和 builder，便于统一控制第三方 import 输出。"""

        from sam3.model.sam3_image_processor import Sam3Processor
        import sam3.model_builder as sam3_model_builder

        return Sam3Processor, sam3_model_builder

    @staticmethod
    def _normalize_device(device: str) -> str:
        """把配置中的 device 字段转为 SAM3 processor 可接受的值。"""

        value = str(device).strip().lower()
        if value in {"", "auto", "none"}:
            try:
                import torch

                return "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                return "cpu"
        return value

    def set_prompt(self, prompt: str | list[str]) -> None:
        """更新文本提示词缓存。"""

        self._prompt = normalize_prompt(prompt, "SAM3")

    def infer(self, image_bgr: np.ndarray, prompt: str | list[str] | None = None) -> SegmenterResult:
        """执行单帧 SAM3 文本提示分割。"""

        if prompt is not None:
            self.set_prompt(prompt)
        frame = ensure_bgr_u8(image_bgr, subject="image ")
        image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(image_rgb)

        t0 = time.perf_counter()
        state = self.processor.set_image(image)
        best_output: dict[str, Any] | None = None
        best_prompt = ""
        best_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        best_selected_index = -1
        best_area_ratio = 0.0
        best_score = -1.0
        total_det_count = 0

        for prompt_text in self._prompt:
            try:
                self.processor.reset_all_prompts(state)
            except Exception:
                pass
            output = self.processor.set_text_prompt(state=state, prompt=prompt_text)
            masks = output.get("masks", np.empty((0, frame.shape[0], frame.shape[1]), dtype=np.uint8))
            scores = output.get("scores", None)
            det_count = int(len(scores)) if scores is not None else int(len(masks))
            total_det_count += det_count
            mask_bw, selected_index, area_ratio, selected_score = select_best_sam3_mask(
                masks=masks,
                scores=scores,
                frame_shape=frame.shape[:2],
                threshold=self.mask_threshold,
            )
            if selected_index >= 0 and (selected_score > best_score or best_selected_index < 0):
                best_output = output
                best_prompt = prompt_text
                best_mask = mask_bw
                best_selected_index = selected_index
                best_area_ratio = area_ratio
                best_score = selected_score

        infer_ms = (time.perf_counter() - t0) * 1000.0

        boxes = best_output.get("boxes", None) if best_output is not None else None
        scores = best_output.get("scores", None) if best_output is not None else None
        overlay = self._make_overlay(frame, best_mask, boxes, scores, best_selected_index)

        return SegmenterResult(
            overlay_bgr=overlay,
            mask_bw=best_mask,
            det_count=total_det_count,
            infer_ms=infer_ms,
            prompt=[best_prompt] if best_prompt else list(self._prompt),
            selected_index=best_selected_index,
            selected_score=best_score,
            mask_area_ratio=best_area_ratio,
        )

    def _make_overlay(self, frame: np.ndarray, mask_bw: np.ndarray, boxes: Any | None, scores: Any | None, selected_index: int) -> np.ndarray:
        """绘制 SAM3 mask 轮廓、bbox 和分数，供 OpenCV debug 查看。"""

        overlay = frame.copy()
        if np.count_nonzero(mask_bw) > 0:
            color_layer = np.zeros_like(overlay)
            color_layer[:, :, 1] = mask_bw
            overlay = cv2.addWeighted(overlay, 1.0, color_layer, 0.35, 0.0)
            contours, _ = cv2.findContours(mask_bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(overlay, contours, -1, (0, 255, 255), 2)

        if selected_index >= 0 and boxes is not None:
            boxes_np = to_numpy(boxes).reshape(-1, 4)
            if selected_index < boxes_np.shape[0]:
                x0, y0, x1, y1 = [int(round(float(v))) for v in boxes_np[selected_index]]
                cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 255, 255), 2)
                label = f"sam3 {selected_index}"
                if scores is not None:
                    scores_np = to_numpy(scores).reshape(-1)
                    if selected_index < scores_np.shape[0]:
                        label += f" {float(scores_np[selected_index]):.2f}"
                cv2.putText(overlay, label, (max(x0, 0), max(y0 - 8, 16)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
        return overlay
