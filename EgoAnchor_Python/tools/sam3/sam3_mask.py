"""SAM3 prompt mask 实时调试工具。

运行方式：
    pixi run tool-sam3-mask

本脚本放在 ``EgoAnchor_Python/tools/sam3``，使用 ``EgoAnchor_Python`` 的 pixi
环境。需要修改提示词、阈值或 RealSense 相机参数时，直接编辑下方全大写配置变量。
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON_DIR = SCRIPT_DIR.parents[1]
SRC_DIR = PYTHON_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from egoanchor.algorithms import Sam3Segmenter, SegmenterResult
from egoanchor.tools import RealSenseCamera, show_depth_window


# 项目内 SAM3 仓库路径；默认使用 EgoAnchor_Python/sam3。
SAM3_REPO_PATH = PYTHON_DIR / "sam3"

# SAM3 checkpoint 路径；默认使用本地下载权重，避免在线下载。
SAM3_CHECKPOINT_PATH = SAM3_REPO_PATH / "assets/sam3_ckpt/sam3.pt"

# 初始提示词；可写字符串，也可写多个候选描述。
PROMPT: str | list[str] = ["quest 3 controller"]

# SAM3 检测置信度阈值；越高越严格，误检多时建议调高。
CONFIDENCE_THRESHOLD = 0.2

# SAM3 processor 输入分辨率；默认沿用官方 image processor。
RESOLUTION = 1008

# mask 二值化阈值；边缘破碎时可适当降低。
MASK_THRESHOLD = 0.5

# 推理设备；auto 表示有 CUDA 时使用 cuda，否则使用 cpu。
DEVICE = "auto"

# 是否允许从 HuggingFace 下载权重；prompt 调试默认使用本地 checkpoint。
LOAD_FROM_HF = False

# 是否跳过 SAM3 构建阶段的位置编码预计算慢路径；当前未启用 torch.compile，建议保持 True。
DISABLE_POSITION_PRECOMPUTE = True

# RealSense 采集参数。
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
CAMERA_SERIAL_NUMBER: str | None = None

# 是否显示对齐深度图，通常调 prompt 时不需要。
SHOW_DEPTH = False

# 按 s 保存当前 color/overlay/mask 快照，便于比较不同 prompt。
ENABLE_SNAPSHOT_SAVE = True
SNAPSHOT_DIR = SCRIPT_DIR / "snapshots"


@dataclass(frozen=True)
class WorkerSnapshot:
    """后台 SAM3 推理状态快照。"""

    result: SegmenterResult | None
    """最近一次完成的 SAM3 结果。"""

    timestamp_ms: float
    """最近一次完成结果对应的 RealSense 时间戳。"""

    busy: bool
    """后台线程当前是否正在推理。"""

    submitted: int
    """累计接受的帧数。"""

    completed: int
    """累计完成的推理次数。"""

    dropped: int
    """因为后台忙而跳过提交的帧数。"""

    error: str
    """后台线程最近一次异常；空字符串表示无异常。"""


class AsyncSam3Worker:
    """单线程 SAM3 后台推理器。

    主线程只负责采集和 OpenCV 窗口刷新；worker 每次只处理最新提交的一帧。
    SAM3 推理慢时会跳过中间帧，避免窗口被同步推理堵住。
    """

    def __init__(self, segmenter: Any) -> None:
        """保存分割器并初始化线程同步状态。"""

        self.segmenter = segmenter
        """实现 infer(image_bgr) 的 SAM3 分割器。"""

        self._condition = threading.Condition()
        """保护待处理帧和状态快照的条件变量。"""

        self._pending_frame: np.ndarray | None = None
        """等待后台处理的最新 BGR 帧。"""

        self._pending_timestamp_ms = 0.0
        """等待处理帧对应的 RealSense 时间戳。"""

        self._latest_result: SegmenterResult | None = None
        """最近一次完成的推理结果。"""

        self._latest_timestamp_ms = 0.0
        """最近一次完成结果对应的 RealSense 时间戳。"""

        self._busy = False
        """后台线程是否正在推理。"""

        self._stopping = False
        """后台线程停止标记。"""

        self._submitted = 0
        """累计接受帧数。"""

        self._completed = 0
        """累计完成推理次数。"""

        self._dropped = 0
        """后台忙时跳过提交的帧数。"""

        self._error = ""
        """后台线程最近一次异常文本。"""

        self._thread = threading.Thread(target=self._run, name="SAM3MaskWorker", daemon=True)
        """后台推理线程。"""

    def start(self) -> None:
        """启动后台线程。"""

        self._thread.start()

    def stop(self) -> None:
        """请求后台线程退出并等待短暂收尾。"""

        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        self._thread.join(timeout=2.0)

    def submit(self, frame_bgr: np.ndarray, timestamp_ms: float) -> bool:
        """提交一帧给后台线程；后台忙时返回 False 并计入 dropped。"""

        with self._condition:
            if self._busy or self._pending_frame is not None:
                self._dropped += 1
                return False
            self._pending_frame = frame_bgr.copy()
            self._pending_timestamp_ms = float(timestamp_ms)
            self._submitted += 1
            self._condition.notify()
            return True

    def snapshot(self) -> WorkerSnapshot:
        """复制当前 worker 状态，供 OpenCV 主线程显示。"""

        with self._condition:
            return WorkerSnapshot(
                result=self._latest_result,
                timestamp_ms=self._latest_timestamp_ms,
                busy=self._busy or self._pending_frame is not None,
                submitted=self._submitted,
                completed=self._completed,
                dropped=self._dropped,
                error=self._error,
            )

    def _run(self) -> None:
        """后台线程主循环。"""

        while True:
            with self._condition:
                while self._pending_frame is None and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                frame = self._pending_frame
                timestamp_ms = self._pending_timestamp_ms
                self._pending_frame = None
                self._busy = True

            try:
                result = self.segmenter.infer(frame)
                error = ""
            except Exception as exc:
                result = None
                error = f"{type(exc).__name__}: {exc}"

            with self._condition:
                self._busy = False
                self._latest_timestamp_ms = float(timestamp_ms)
                if result is not None:
                    self._latest_result = result
                    self._completed += 1
                if error:
                    self._error = error


def draw_status_bar(frame: np.ndarray, result: SegmenterResult, timestamp_ms: float) -> np.ndarray:
    """在 overlay 上绘制 prompt、耗时、检测数量和 mask 面积。"""

    out = frame.copy()
    text = (
        f"infer {result.infer_ms:.1f} ms | det {result.det_count} | "
        f"idx {result.selected_index} | area {result.mask_area_ratio:.3f} | "
        f"t {timestamp_ms:.0f} ms | prompt: {', '.join(result.prompt)}"
    )
    cv2.rectangle(out, (0, 0), (out.shape[1], 38), (0, 0, 0), thickness=-1)
    cv2.putText(out, text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2, cv2.LINE_AA)
    return out


def overlay_mask_on_live_frame(frame_bgr: np.ndarray, mask_bw: np.ndarray) -> np.ndarray:
    """把最近一次 SAM3 mask 叠加到当前实时相机帧上。"""

    out = frame_bgr.copy()
    if mask_bw.size == 0:
        return out

    if mask_bw.shape[:2] != frame_bgr.shape[:2]:
        mask = cv2.resize(mask_bw, (frame_bgr.shape[1], frame_bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
    else:
        mask = mask_bw

    foreground = mask > 0
    if not np.any(foreground):
        return out

    tint_bgr = np.array([35, 220, 255], dtype=np.float32)
    out[foreground] = (out[foreground].astype(np.float32) * 0.55 + tint_bgr * 0.45).astype(np.uint8)
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, contours, -1, (0, 255, 255), 2)
    return out


def draw_worker_status(frame: np.ndarray, snapshot: WorkerSnapshot, prompt: str | list[str]) -> np.ndarray:
    """在实时相机画面上绘制后台推理状态和最近一次结果摘要。"""

    out = frame.copy()
    prompt_items = [prompt] if isinstance(prompt, str) else list(prompt)
    prompt_text = ", ".join(str(item) for item in prompt_items)
    status = "busy" if snapshot.busy else "idle"
    text = (
        f"SAM3 {status} | done {snapshot.completed}/{snapshot.submitted} | "
        f"drop {snapshot.dropped} | prompt: {prompt_text}"
    )
    cv2.rectangle(out, (0, 0), (out.shape[1], 64), (0, 0, 0), thickness=-1)
    cv2.putText(out, text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2, cv2.LINE_AA)
    if snapshot.error:
        cv2.putText(out, snapshot.error[:120], (10, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 80, 255), 2, cv2.LINE_AA)
    elif snapshot.result is not None:
        result = snapshot.result
        result_text = (
            f"last infer {result.infer_ms:.1f} ms | det {result.det_count} | "
            f"idx {result.selected_index} | area {result.mask_area_ratio:.3f} | t {snapshot.timestamp_ms:.0f} ms"
        )
        cv2.putText(out, result_text, (10, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (190, 255, 190), 2, cv2.LINE_AA)
    return out


def compose_live_overlay(frame_bgr: np.ndarray, snapshot: WorkerSnapshot, prompt: str | list[str]) -> np.ndarray:
    """用实时帧作为底图，并叠加最近一次后台 SAM3 mask。"""

    if snapshot.result is None:
        overlay = frame_bgr.copy()
    else:
        overlay = overlay_mask_on_live_frame(frame_bgr, snapshot.result.mask_bw)
    return draw_worker_status(overlay, snapshot, prompt)


def compose_mask_view(mask_bw: np.ndarray, result: SegmenterResult | None) -> np.ndarray:
    """在黑白 mask 右侧拼接当前 SAM3 检测结果分数。"""

    if mask_bw.ndim == 2:
        mask_bgr = cv2.cvtColor(mask_bw, cv2.COLOR_GRAY2BGR)
    else:
        mask_bgr = mask_bw.copy()

    height = int(mask_bgr.shape[0])
    panel_width = 160
    panel = np.zeros((height, panel_width, 3), dtype=np.uint8)
    cv2.putText(panel, "CONFIDENCE", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (190, 255, 190), 1, cv2.LINE_AA)
    score_text = "--" if result is None or result.selected_score < 0.0 else f"{result.selected_score:.2f}"
    cv2.putText(panel, score_text, (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (255, 255, 255), 2, cv2.LINE_AA)
    return np.hstack((mask_bgr, panel))


def save_snapshot(
    color_bgr: np.ndarray,
    result: SegmenterResult,
    snapshot_dir: Path,
    overlay_bgr: np.ndarray | None = None,
) -> None:
    """保存当前 color、overlay 和 mask，便于离线比较 prompt 效果。"""

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    cv2.imwrite(str(snapshot_dir / f"{stamp}_color.jpg"), color_bgr)
    cv2.imwrite(str(snapshot_dir / f"{stamp}_overlay.jpg"), overlay_bgr if overlay_bgr is not None else result.overlay_bgr)
    cv2.imwrite(str(snapshot_dir / f"{stamp}_mask.png"), result.mask_bw)
    print(f"已保存快照: {snapshot_dir / stamp}")


def main() -> None:
    """从顶部配置启动 RealSense + SAM3 prompt mask 调试窗口。"""

    print("正在加载 SAM3，请稍候。")
    load_t0 = time.perf_counter()
    masker = Sam3Segmenter(
        repo_path=SAM3_REPO_PATH,
        checkpoint_path=SAM3_CHECKPOINT_PATH,
        init_prompt=PROMPT,
        confidence_threshold=CONFIDENCE_THRESHOLD,
        resolution=RESOLUTION,
        mask_threshold=MASK_THRESHOLD,
        device=DEVICE,
        load_from_hf=LOAD_FROM_HF,
        disable_position_precompute=DISABLE_POSITION_PRECOMPUTE,
    )
    print(f"SAM3 加载完成，用时 {time.perf_counter() - load_t0:.1f}s。")

    camera = RealSenseCamera(
        width=CAMERA_WIDTH,
        height=CAMERA_HEIGHT,
        fps=CAMERA_FPS,
        serial_number=CAMERA_SERIAL_NUMBER,
    )

    cv2.namedWindow("SAM3 Overlay", cv2.WINDOW_AUTOSIZE)
    cv2.namedWindow("SAM3 Mask BW", cv2.WINDOW_AUTOSIZE)
    if SHOW_DEPTH:
        cv2.namedWindow("RealSense Depth (Aligned)", cv2.WINDOW_AUTOSIZE)

    try:
        camera.start()
        worker = AsyncSam3Worker(masker)
        worker.start()
        print("窗口已打开，按 q 或 ESC 退出；按 s 保存当前帧快照。")
        latest_color: np.ndarray | None = None
        while True:
            rgbd = camera.get_aligned_rgbd_frames()
            latest_color = rgbd.color_bgr
            worker.submit(rgbd.color_bgr, rgbd.timestamp_ms)
            snapshot = worker.snapshot()

            overlay = compose_live_overlay(rgbd.color_bgr, snapshot, PROMPT)
            if snapshot.result is None:
                mask_view = np.zeros(rgbd.color_bgr.shape[:2], dtype=np.uint8)
            else:
                mask_view = snapshot.result.mask_bw

            cv2.imshow("SAM3 Overlay", overlay)
            cv2.imshow("SAM3 Mask BW", compose_mask_view(mask_view, snapshot.result))
            if SHOW_DEPTH:
                show_depth_window(rgbd.depth)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            if key == ord("s") and ENABLE_SNAPSHOT_SAVE and snapshot.result is not None and latest_color is not None:
                save_snapshot(latest_color, snapshot.result, SNAPSHOT_DIR, overlay)
    finally:
        if "worker" in locals():
            worker.stop()
        camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
