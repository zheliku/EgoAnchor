"""
SAM3 语义分割 API（Quest Pipeline 低频种子版）

功能目标：
1. 使用本地 SAM3 checkpoint 根据文本提示生成目标 mask。
2. 输出与 YOLOE 模块兼容的 overlay/mask/det_count/infer_ms 字段。
3. 提供后台异步包装器，让慢速 SAM3 只做低频目标重新发现，避免阻塞 Quest 实时链路。
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from PIL import Image


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SAM3_ROOT = PROJECT_DIR / "sam3"
DEFAULT_SAM3_CHECKPOINT = DEFAULT_SAM3_ROOT / "assets" / "sam3_ckpt" / "sam3.pt"


@dataclass
class Sam3MaskResult:
    """SAM3 单帧输出结果。"""

    # 叠加可视化图。
    overlay: np.ndarray

    # 黑白掩码（白=目标，黑=背景）。
    mask_bw: np.ndarray

    # 检测数量。
    det_count: int

    # 推理耗时（毫秒）。
    infer_ms: float

    # 当前生效的提示词。
    prompt: str

    # 被选中用于下游 FoundationPose 的 mask 下标；无检测时为 -1。
    selected_index: int = -1

    # 被选中 mask 的面积占整幅图比例。
    mask_area_ratio: float = 0.0

    # 被选中目标置信度。
    score: float = 0.0

    # 检测框，格式为 Nx4 xyxy。
    boxes_xyxy: np.ndarray | None = None

    # 结果对应的源帧号。
    source_frame_id: int | None = None

    # 结果对应的源帧时间戳（毫秒）。
    source_timestamp_ms: float | None = None

    # SAM3 推理输入源图像。仅异步 pipeline 用于把同一帧 RGB 与 mask 一起初始化 Cutie/register。
    source_image_bgr: np.ndarray | None = None


class Sam3Masker:
    """SAM3 同步掩码生成器。"""

    def __init__(
        self,
        checkpoint_path: str | Path = DEFAULT_SAM3_CHECKPOINT,
        prompt: str = "white cube",
        confidence_threshold: float = 0.5,
        mask_threshold: float = 0.5,
        max_det: int = 1,
        device: str | None = "cuda",
        resolution: int = 1008,
        compile_model: bool = False,
        sam3_root: str | Path = DEFAULT_SAM3_ROOT,
    ) -> None:
        """
        初始化 SAM3 掩码生成器。

        参数：
        - checkpoint_path: 本地 SAM3 checkpoint，默认使用仓库内 sam3/assets/sam3_ckpt/sam3.pt。
        - prompt: 文本提示词。
        - confidence_threshold: SAM3 检测置信度阈值。
        - mask_threshold: 输出 mask 二值化阈值。
        - max_det: 最多保留检测数量；下游仍只选最高分单目标 mask。
        - device: 推理设备。cuda 不可用时自动回退 cpu。
        - resolution: SAM3 processor 输入分辨率。
        - compile_model: 预留参数；仅在模型支持时尝试 torch.compile。
        - sam3_root: 本地 SAM3 包根目录，用于显式 sys.path 兼容。
        """
        self.checkpoint_path = Path(checkpoint_path).expanduser().resolve()
        self.prompt = str(prompt).strip()
        self.confidence_threshold = float(confidence_threshold)
        self.mask_threshold = float(mask_threshold)
        self.max_det = max(int(max_det), 1)
        self.resolution = int(resolution)
        self.compile_model = bool(compile_model)
        self.sam3_root = Path(sam3_root).expanduser().resolve()

        if not self.prompt:
            raise ValueError("SAM3 prompt 不能为空。")
        if not self.checkpoint_path.exists():
            raise FileNotFoundError(f"SAM3 checkpoint 不存在: {self.checkpoint_path}")
        if not self.sam3_root.exists():
            raise FileNotFoundError(f"SAM3 根目录不存在: {self.sam3_root}")

        if device is None or str(device).strip() == "":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if str(device).startswith("cuda") and not torch.cuda.is_available():
            logging.warning("[SAM3] 请求 CUDA 但当前不可用，回退 CPU。")
            device = "cpu"
        self.device = str(device)

        if str(self.sam3_root) not in sys.path:
            sys.path.insert(0, str(self.sam3_root))

        from sam3.model.sam3_image_processor import Sam3Processor
        from sam3.model_builder import build_sam3_image_model

        logging.info(
            "[SAM3] 加载模型 checkpoint=%s device=%s resolution=%d conf=%.2f",
            self.checkpoint_path,
            self.device,
            self.resolution,
            self.confidence_threshold,
        )
        self.model = build_sam3_image_model(
            checkpoint_path=str(self.checkpoint_path),
            load_from_HF=False,
            device=self.device,
        )
        if self.compile_model and hasattr(torch, "compile"):
            try:
                self.model = torch.compile(self.model)  # type: ignore[assignment]
            except Exception as exc:
                logging.warning("[SAM3] torch.compile 失败，继续使用 eager 模式: %s", exc)
        if hasattr(self.model, "eval"):
            self.model.eval()
        self.processor = Sam3Processor(
            self.model,
            resolution=self.resolution,
            device=self.device,
            confidence_threshold=self.confidence_threshold,
        )

    @staticmethod
    def _ensure_bgr_u8(image: np.ndarray) -> np.ndarray:
        """把输入图像标准化为 BGR uint8 三通道。"""
        if image.ndim == 2:
            image = np.repeat(image[..., None], 3, axis=2)
        elif image.ndim == 3:
            image = image[..., :3]
        else:
            raise ValueError("image 维度不正确，应为 (H,W) 或 (H,W,C)。")
        if image.dtype != np.uint8:
            image = np.clip(image, 0, 255).astype(np.uint8)
        return image

    @staticmethod
    def _to_numpy(value: Any, dtype: np.dtype | type | None = None) -> np.ndarray:
        """兼容 torch.Tensor/list/np.ndarray 转 numpy。"""
        if value is None:
            arr = np.asarray([])
        elif hasattr(value, "detach"):
            arr = value.detach().cpu().numpy()
        else:
            arr = np.asarray(value)
        if dtype is not None:
            arr = arr.astype(dtype, copy=False)
        return arr

    @staticmethod
    def _empty_result(
        frame: np.ndarray,
        prompt: str,
        infer_ms: float,
        source_frame_id: int | None,
        source_timestamp_ms: float | None,
    ) -> Sam3MaskResult:
        """生成无检测结果。"""
        return Sam3MaskResult(
            overlay=frame.copy(),
            mask_bw=np.zeros(frame.shape[:2], dtype=np.uint8),
            det_count=0,
            infer_ms=float(infer_ms),
            prompt=prompt,
            selected_index=-1,
            mask_area_ratio=0.0,
            score=0.0,
            boxes_xyxy=np.zeros((0, 4), dtype=np.float32),
            source_frame_id=source_frame_id,
            source_timestamp_ms=source_timestamp_ms,
            source_image_bgr=frame.copy(),
        )

    def _make_overlay(
        self,
        frame: np.ndarray,
        mask_bw: np.ndarray,
        boxes_xyxy: np.ndarray,
        scores: np.ndarray,
        selected_index: int,
        det_count: int,
    ) -> np.ndarray:
        """用 OpenCV 绘制 SAM3 结果，避免 matplotlib/GPU GUI 依赖。"""
        overlay = frame.copy()
        if mask_bw.size > 0 and np.count_nonzero(mask_bw) > 0:
            color_img = np.zeros_like(overlay)
            color_img[mask_bw > 0] = (0, 255, 255)
            cv2.addWeighted(color_img, 0.35, overlay, 1.0, 0.0, overlay)
            contours, _ = cv2.findContours(
                (mask_bw > 0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(overlay, contours, -1, (0, 255, 255), 2)

        draw_count = min(det_count, int(len(boxes_xyxy)))
        for idx in range(draw_count):
            box = boxes_xyxy[idx]
            x0, y0, x1, y1 = [int(round(float(v))) for v in box]
            color = (0, 255, 255) if idx == selected_index else (128, 200, 255)
            cv2.rectangle(overlay, (x0, y0), (x1, y1), color, 2)
            score = float(scores[idx]) if idx < len(scores) else 0.0
            cv2.putText(
                overlay,
                f"SAM3 {idx}:{score:.2f}",
                (max(x0, 0), max(y0 - 6, 18)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
                cv2.LINE_AA,
            )
        return overlay

    def infer(
        self,
        image_bgr: np.ndarray,
        prompt: str | None = None,
        source_frame_id: int | None = None,
        source_timestamp_ms: float | None = None,
    ) -> Sam3MaskResult:
        """单帧同步推理：BGR 图像 + 文本提示 -> mask/overlay。"""
        if prompt is not None:
            prompt = str(prompt).strip()
            if not prompt:
                raise ValueError("SAM3 prompt 不能为空。")
            self.prompt = prompt

        frame = self._ensure_bgr_u8(image_bgr)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)

        t0 = time.perf_counter()
        with torch.inference_mode():
            state = self.processor.set_image(pil_image, state={})
            output = self.processor.set_text_prompt(state=state, prompt=self.prompt)
        infer_ms = (time.perf_counter() - t0) * 1000.0

        masks = self._to_numpy(output.get("masks"))
        scores = self._to_numpy(output.get("scores"), dtype=np.float32).reshape(-1)
        boxes = self._to_numpy(output.get("boxes"), dtype=np.float32)
        if boxes.size == 0:
            boxes = np.zeros((0, 4), dtype=np.float32)
        else:
            boxes = boxes.reshape(-1, 4)

        if masks.size == 0 or masks.shape[0] == 0:
            return self._empty_result(
                frame, self.prompt, infer_ms, source_frame_id, source_timestamp_ms
            )

        if masks.ndim == 4 and masks.shape[1] == 1:
            masks = masks[:, 0]
        elif masks.ndim == 3:
            pass
        elif masks.ndim == 2:
            masks = masks[None, ...]
        else:
            masks = np.reshape(masks, (masks.shape[0], masks.shape[-2], masks.shape[-1]))

        keep_count = min(int(masks.shape[0]), self.max_det)
        if scores.size < masks.shape[0]:
            padded = np.ones((masks.shape[0],), dtype=np.float32)
            padded[: scores.size] = scores
            scores = padded
        order = np.argsort(scores[: masks.shape[0]])[::-1]
        keep = order[:keep_count]

        selected_index = int(keep[0]) if keep.size > 0 else -1
        if selected_index < 0:
            return self._empty_result(
                frame, self.prompt, infer_ms, source_frame_id, source_timestamp_ms
            )

        selected_mask = masks[selected_index]
        mask_bw = (selected_mask >= float(self.mask_threshold)).astype(np.uint8) * 255
        if mask_bw.shape[:2] != frame.shape[:2]:
            mask_bw = cv2.resize(
                mask_bw,
                (frame.shape[1], frame.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )

        mask_area_ratio = float(np.count_nonzero(mask_bw)) / float(mask_bw.size)
        if mask_area_ratio <= 0.0:
            selected_index = -1

        det_count = int(keep_count)
        overlay = self._make_overlay(
            frame,
            mask_bw,
            boxes,
            scores,
            selected_index=selected_index,
            det_count=det_count,
        )

        return Sam3MaskResult(
            overlay=overlay,
            mask_bw=mask_bw,
            det_count=det_count if selected_index >= 0 else 0,
            infer_ms=infer_ms,
            prompt=self.prompt,
            selected_index=selected_index,
            mask_area_ratio=mask_area_ratio,
            score=float(scores[selected_index]) if selected_index >= 0 else 0.0,
            boxes_xyxy=boxes,
            source_frame_id=source_frame_id,
            source_timestamp_ms=source_timestamp_ms,
            source_image_bgr=frame.copy(),
        )


@dataclass
class _PendingSam3Job:
    image_bgr: np.ndarray
    frame_id: int | None
    timestamp_ms: float | None


class AsyncSam3Masker:
    """SAM3 后台异步包装器：忙时丢帧、只保留最新结果。"""

    def __init__(
        self,
        masker_kwargs: dict[str, Any] | None = None,
        min_interval_sec: float = 1.0,
        masker_factory: type[Sam3Masker] | Any = Sam3Masker,
    ) -> None:
        self.masker_kwargs = dict(masker_kwargs or {})
        self.min_interval_sec = max(float(min_interval_sec), 0.0)
        self.masker_factory = masker_factory

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._pending: _PendingSam3Job | None = None
        self._busy = False
        self._started = False
        self._latest: Sam3MaskResult | None = None
        self._latest_version = 0
        self._last_submit_t = 0.0
        self._last_warning_t = 0.0
        self._min_result_frame_id: int | None = None

        self._submitted = 0
        self._completed = 0
        self._dropped = 0
        self._failed = 0
        self._last_infer_ms = 0.0

    def start(self) -> None:
        """启动后台 worker。"""
        with self._lock:
            if self._started:
                return
            self._stop_requested = False
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="AsyncSam3Masker",
                daemon=True,
            )
            self._started = True
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台 worker。"""
        thread: threading.Thread | None
        with self._cond:
            self._stop_requested = True
            self._pending = None
            self._cond.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        with self._lock:
            self._thread = None
            self._started = False
            self._busy = False

    def submit(
        self,
        image_bgr: np.ndarray,
        frame_id: int | None = None,
        timestamp_ms: float | None = None,
    ) -> bool:
        """
        非阻塞提交。worker 忙或未到节流间隔时丢弃，防止队列积压。
        返回 True 表示本帧已进入待处理槽。
        """
        now = time.perf_counter()
        with self._cond:
            if not self._started or self._stop_requested:
                self._dropped += 1
                return False
            if self._busy or self._pending is not None:
                self._dropped += 1
                return False
            if self._last_submit_t > 0.0 and now - self._last_submit_t < self.min_interval_sec:
                self._dropped += 1
                return False

            self._pending = _PendingSam3Job(
                image_bgr=np.ascontiguousarray(image_bgr.copy()),
                frame_id=frame_id,
                timestamp_ms=timestamp_ms,
            )
            self._last_submit_t = now
            self._submitted += 1
            self._cond.notify()
            return True

    def get_latest(self) -> tuple[Sam3MaskResult | None, int]:
        """返回最新完成结果及版本号。"""
        with self._lock:
            return self._latest, self._latest_version

    def reset_runtime(self, min_frame_id: int | None = None) -> None:
        """
        清空异步运行态，供上层手动重置跟踪时调用。

        说明：
        - latest/pending 会被清空，避免重置后继续使用旧帧 SAM3 mask。
        - 若 worker 正在推理旧帧，设置 min_frame_id 后该旧结果完成时会被丢弃，
          不会重新污染 latest。
        """
        with self._cond:
            self._pending = None
            self._latest = None
            self._latest_version = 0
            self._last_submit_t = 0.0
            self._last_infer_ms = 0.0
            self._min_result_frame_id = min_frame_id
            self._cond.notify_all()

    def get_stats(self) -> dict[str, float | int | bool]:
        """返回异步 SAM3 运行统计。"""
        with self._lock:
            latest_age_ms = 0.0
            if self._latest is not None and self._latest.source_timestamp_ms is not None:
                latest_age_ms = time.time() * 1000.0 - float(
                    self._latest.source_timestamp_ms
                )
            return {
                "submitted": self._submitted,
                "completed": self._completed,
                "dropped": self._dropped,
                "failed": self._failed,
                "busy": self._busy,
                "latest_version": self._latest_version,
                "latest_age_ms": latest_age_ms,
                "last_infer_ms": self._last_infer_ms,
            }

    def _warn_limited(self, message: str, exc: Exception) -> None:
        """限频输出 worker 异常，避免刷屏。"""
        now = time.perf_counter()
        if now - self._last_warning_t >= 5.0:
            logging.warning(message, exc)
            self._last_warning_t = now

    def _worker_loop(self) -> None:
        """后台线程主循环；模型在本线程内构建和调用。"""
        masker: Sam3Masker | None = None
        try:
            masker = self.masker_factory(**self.masker_kwargs)
        except Exception as exc:
            with self._lock:
                self._failed += 1
            self._warn_limited("[SAM3] 后台模型初始化失败: %s", exc)

        while True:
            with self._cond:
                while self._pending is None and not self._stop_requested:
                    self._cond.wait(timeout=0.2)
                if self._stop_requested:
                    return
                job = self._pending
                self._pending = None
                self._busy = True

            try:
                if masker is None:
                    masker = self.masker_factory(**self.masker_kwargs)
                result = masker.infer(
                    job.image_bgr,
                    source_frame_id=job.frame_id,
                    source_timestamp_ms=job.timestamp_ms,
                )
                with self._lock:
                    if self._min_result_frame_id is not None and (
                        job.frame_id is None or job.frame_id < self._min_result_frame_id
                    ):
                        self._dropped += 1
                        continue
                    self._latest = result
                    self._latest_version += 1
                    self._completed += 1
                    self._last_infer_ms = float(result.infer_ms)
            except Exception as exc:
                with self._lock:
                    self._failed += 1
                self._warn_limited("[SAM3] 后台推理失败: %s", exc)
            finally:
                with self._lock:
                    self._busy = False


def _draw_demo_overlay(
    frame_bgr: np.ndarray,
    result: Sam3MaskResult | None,
    display_fps: float,
    stats: dict[str, float | int | bool],
) -> np.ndarray:
    """
    把后台 SAM3 最新 mask 轻量叠加到当前相机帧，并绘制 HUD。

    注意：异步 SAM3 的 result.overlay 属于旧帧。demo 始终显示当前相机帧，
    只叠加最新 mask，因此前台窗口可保持相机帧率，检测低频独立运行。
    """
    overlay = frame_bgr.copy()
    if result is not None and result.mask_bw is not None and result.mask_bw.size > 0:
        mask = (result.mask_bw > 0).astype(np.uint8)
        if mask.shape[:2] != overlay.shape[:2]:
            mask = cv2.resize(
                mask,
                (overlay.shape[1], overlay.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
        if np.count_nonzero(mask) > 0:
            color_img = np.zeros_like(overlay)
            color_img[mask > 0] = (0, 255, 255)
            cv2.addWeighted(color_img, 0.35, overlay, 1.0, 0.0, overlay)
            contours, _ = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(overlay, contours, -1, (0, 255, 255), 2)

    if result is None:
        line1 = "SAM3 waiting..."
    else:
        line1 = (
            f"SAM3 infer={result.infer_ms:.0f}ms det={result.det_count} "
            f"score={result.score:.2f} mask={result.mask_area_ratio:.1%}"
        )
    line2 = (
        f"display_fps={display_fps:.1f} sam3_done={stats.get('completed', 0)} "
        f"drop={stats.get('dropped', 0)} busy={int(bool(stats.get('busy', False)))}"
    )

    for idx, text in enumerate([line1, line2]):
        y = 28 + idx * 28
        cv2.putText(
            overlay,
            text,
            (10, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (15, 15, 15),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            overlay,
            text,
            (10, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (245, 245, 245),
            1,
            cv2.LINE_AA,
        )
    return overlay


def main() -> None:
    """
    最小实时示例：
    1) 前台用 RealSense 或 OpenCV 摄像头保持高帧率显示。
    2) 后台 AsyncSam3Masker 低频运行 SAM3，忙时丢帧不排队。
    3) 主线程把最新 mask 轻量叠加到当前相机帧。

    退出：按 q 或 ESC。
    """

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # ===== 直接改这里（不使用 argparse） =====
    CAMERA_SOURCE = "realsense"  # "realsense" 或 "opencv"
    CAMERA_INDEX = 0
    CAMERA_WIDTH = 640
    CAMERA_HEIGHT = 480
    CAMERA_FPS = 30

    CHECKPOINT_PATH = DEFAULT_SAM3_CHECKPOINT
    PROMPT = "white cube"
    CONFIDENCE_THRESHOLD = 0.5
    MASK_THRESHOLD = 0.5
    MAX_DET = 1
    DEVICE = "cuda"
    RESOLUTION = 1008
    # 0.0 表示不做人为限速：SAM3 一完成，下一帧相机图像就会被提交给后台。
    # 因为 AsyncSam3Masker 忙时会丢帧且不排队，所以不会拖慢前台相机显示 FPS。
    INTERVAL_SEC = 0.0
    # =====================================

    camera = None
    cap = None
    if CAMERA_SOURCE == "realsense":
        from realsense import RealSenseCamera

        camera = RealSenseCamera(
            width=CAMERA_WIDTH,
            height=CAMERA_HEIGHT,
            fps=CAMERA_FPS,
        )
        camera.start()
    else:
        cap = cv2.VideoCapture(CAMERA_INDEX)
        if not cap.isOpened():
            raise RuntimeError(f"无法打开 OpenCV 摄像头 index={CAMERA_INDEX}")

    masker = AsyncSam3Masker(
        masker_kwargs={
            "checkpoint_path": CHECKPOINT_PATH,
            "prompt": PROMPT,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "mask_threshold": MASK_THRESHOLD,
            "max_det": MAX_DET,
            "device": DEVICE,
            "resolution": RESOLUTION,
            "sam3_root": DEFAULT_SAM3_ROOT,
        },
        min_interval_sec=INTERVAL_SEC,
    )
    masker.start()

    cv2.namedWindow("SAM3 Overlay", cv2.WINDOW_AUTOSIZE)
    cv2.namedWindow("SAM3 Mask BW", cv2.WINDOW_AUTOSIZE)

    frame_id = 0
    latest_result: Sam3MaskResult | None = None
    last_display_t = time.perf_counter()
    display_fps = 0.0

    try:
        logging.info("窗口已打开，按 q 或 ESC 退出。")
        while True:
            if camera is not None:
                rgbd = camera.get_aligned_rgbd_frames()
                frame = rgbd.color_bgr
            else:
                ok, frame = cap.read()
                if not ok or frame is None:
                    logging.warning("[SAM3 demo] 摄像头读取失败。")
                    break

            frame_id += 1
            _ = masker.submit(
                frame,
                frame_id=frame_id,
                timestamp_ms=time.time() * 1000.0,
            )
            latest_result, _ = masker.get_latest()

            now = time.perf_counter()
            dt = max(now - last_display_t, 1e-6)
            inst_fps = 1.0 / dt
            display_fps = inst_fps if display_fps <= 0.0 else display_fps * 0.9 + inst_fps * 0.1
            last_display_t = now

            overlay = _draw_demo_overlay(
                frame,
                latest_result,
                display_fps=display_fps,
                stats=masker.get_stats(),
            )
            mask_bw = (
                latest_result.mask_bw
                if latest_result is not None
                else np.zeros(frame.shape[:2], dtype=np.uint8)
            )
            if mask_bw.shape[:2] != frame.shape[:2]:
                mask_bw = cv2.resize(
                    mask_bw,
                    (frame.shape[1], frame.shape[0]),
                    interpolation=cv2.INTER_NEAREST,
                )

            cv2.imshow("SAM3 Overlay", overlay)
            cv2.imshow("SAM3 Mask BW", mask_bw)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
    finally:
        masker.stop()
        if camera is not None:
            camera.stop()
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()


__all__ = ["Sam3MaskResult", "Sam3Masker", "AsyncSam3Masker"]


if __name__ == "__main__":
    main()
