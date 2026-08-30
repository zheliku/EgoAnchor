"""Python pose debug 应用入口。"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import time
from types import SimpleNamespace

import cv2
import numpy as np

from egoanchor.config import load_config
from egoanchor.diagnostics import make_pose_waiting_image, make_score_debug_view, tile_pose_depth_dashboard
from egoanchor.perception import QuestPosePipelineOutput
from egoanchor.protocol import SubjectRegistry
from egoanchor.runtime import TrackingRuntime
from egoanchor.utils import configure_logging, get_logger

LOGGER = get_logger(__name__, component="TrackingServer")
"""Python pose debug 应用日志记录器。"""


class DebugVideoRecorder:
    """异步调试视频录制器；用 H.264 MP4 保存实际生成的诊断帧。"""

    def __init__(self, output_dir: Path, fps: float) -> None:
        """初始化录制目录和编码参数。"""
        self.output_dir = output_dir
        self.fps = max(float(fps), 1.0)
        self._writers: dict[str, cv2.VideoWriter] = {}
        self._queue: Queue[tuple[str, np.ndarray] | None] = Queue()
        self._thread: Thread | None = None
        self.active = False

    def start(self) -> None:
        """开始新一组录制文件。"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self._session_dir = self.output_dir / stamp
        self._session_dir.mkdir(parents=True, exist_ok=False)
        self._queue = Queue()
        self.active = True
        self._thread = Thread(target=self._run, name="debug-video-recorder", daemon=True)
        self._thread.start()
        LOGGER.info("开始异步 debug 视频录制：%s", self._session_dir)

    def _write(self, name: str, image: np.ndarray, fps: float) -> None:
        """按需创建 MP4 writer，并按面板原始尺寸写入一帧。"""
        height, width = image.shape[:2]
        writer = self._writers.get(name)
        if writer is None:
            path = self._session_dir / f"{name}.mp4"
            writer = self._open_mp4_writer(path, fps, (width, height))
            self._writers[name] = writer
        writer.write(np.asarray(image, dtype=np.uint8))

    @staticmethod
    def _open_mp4_writer(path: Path, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
        """优先使用 Windows H.264 编码器，其他平台回退到可用的 MP4 编码器。"""
        if os.name == "nt":
            writer = cv2.VideoWriter(str(path), cv2.CAP_MSMF, cv2.VideoWriter_fourcc(*"avc1"), fps, size)
            if writer.isOpened():
                return writer
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
        if writer.isOpened():
            LOGGER.warning("H.264 编码器不可用，debug 视频回退为 MPEG-4 Part 2: %s", path)
            return writer
        raise OSError(f"无法创建 MP4 视频文件: {path}")

    def submit(self, kind: str, image: np.ndarray, mask: np.ndarray | None = None) -> None:
        """非阻塞提交新画布；后台按顺序保留每一张实际生成的诊断帧。"""
        if not self.active:
            return
        if kind == "pose":
            mask_frame = np.zeros((480, 640), dtype=np.uint8) if mask is None else np.asarray(mask).copy()
            self._queue.put_nowait(("mask", mask_frame))
        self._queue.put_nowait((str(kind), image))

    def _run(self) -> None:
        """在后台线程持续消费画布并编码各面板。"""
        while True:
            try:
                item = self._queue.get(timeout=0.25)
            except Empty:
                if not self.active:
                    break
                continue
            if item is None:
                self._queue.task_done()
                break
            kind, image = item
            if kind == "pose":
                self._write_pose_panels(image)
            elif kind == "vcd":
                self._write_vcd_panels(image)
            elif kind == "mask":
                self._write_mask(image)
            self._queue.task_done()

    @staticmethod
    def _panel_top(image: np.ndarray) -> int:
        """从总窗口底部反推两行面板之前的 HUD 高度。"""
        top = max(image.shape[0] - 2 * 480 - 60, 0)
        return top

    def _write_pose_panels(self, image: np.ndarray) -> None:
        """从 pose 总窗口精确裁出五张 640x480 面板。"""
        top = self._panel_top(image)
        specs = (
            ("pose_left", 0, top),
            ("pose_right", 640, top),
            ("pose_mask", 1280, top),
            ("pose_depth", 0, top + 510),
            ("pose_pose", 640, top + 510),
        )
        for name, x, y in specs:
            self._write(name, image[y : y + 480, x : x + 640], self.fps)

    def _write_vcd_panels(self, image: np.ndarray) -> None:
        """裁出四张 640x480 基础图和两张含独立色标的 728x480 对比图。"""
        top = self._panel_top(image)
        specs = (
            ("vcd_observed_rgb", 0, top, 640),
            ("vcd_render_rgb", 640, top, 640),
            ("vcd_lab_residual", 1280, top, 728),
            ("vcd_observed_depth", 0, top + 510, 640),
            ("vcd_render_depth", 640, top + 510, 640),
            ("vcd_depth_residual", 1280, top + 510, 728),
        )
        for name, x, y, width in specs:
            self._write(name, image[y : y + 480, x : x + width], self.fps)

    def _write_mask(self, mask: np.ndarray) -> None:
        """写入连续二值 mask 视频，白色为前景、黑色为背景。"""
        mask_u8 = (np.asarray(mask) > 0).astype(np.uint8) * 255
        if mask_u8.ndim != 2:
            mask_u8 = np.squeeze(mask_u8)
        mask_u8 = cv2.resize(mask_u8, (640, 480), interpolation=cv2.INTER_NEAREST)
        self._write("mask_binary", cv2.cvtColor(mask_u8, cv2.COLOR_GRAY2BGR), self.fps)

    def stop(self) -> None:
        """停止录制并释放所有编码器。"""
        if not self.active and self._thread is None:
            return
        self.active = False
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join()
            self._thread = None
        for writer in self._writers.values():
            writer.release()
        count = len(self._writers)
        self._writers.clear()
        if count:
            LOGGER.info("已停止 debug 视频录制，关闭 %d 个视频流。", count)


def _handle_key(runtime: TrackingRuntime, key: int) -> bool:
    """处理 OpenCV 键盘输入；返回 False 表示退出主循环。"""

    if key in (ord("q"), ord("Q"), 27):
        return False
    if key in (ord("1"), ord("2"), ord("3"), ord("4")):
        stage = key - ord("0")
        runtime.set_stage(stage)
        LOGGER.info("切换 pose debug stage=%d", stage)
    elif key in (ord("r"), ord("R")):
        runtime.reset_tracking_state()
    return True


def _is_snapshot_key(key: int) -> bool:
    """判断 OpenCV 按键是否请求保存当前两张高分辨率调试图。"""

    return key in (ord("s"), ord("S"))


def _is_record_key(key: int) -> bool:
    """判断是否切换调试视频录制状态。"""
    return key in (ord("v"), ord("V"))


def _resolve_snapshot_dir(python_root: Path, configured_dir: str) -> Path:
    """解析 debug 快照目录；相对路径固定以 EgoAnchor_Python 根目录为基准。"""

    output_dir = Path(str(configured_dir)).expanduser()
    if output_dir.is_absolute():
        return output_dir
    return python_root / output_dir


def _write_png(path: Path, image: np.ndarray) -> None:
    """把 OpenCV 图像无损写成 PNG，并把静默写入失败转换为明确异常。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
        raise OSError(f"OpenCV 无法写入 PNG: {path}")


def _save_debug_snapshots(
    output: QuestPosePipelineOutput,
    pose_cfg: SimpleNamespace,
    depth_cfg: SimpleNamespace,
    python_root: Path,
) -> tuple[Path, Path]:
    """按独立高分辨率重新生成当前 pose 与 VCD dashboard，并保存为无损 PNG。"""

    diagnostics = output.diagnostics
    observation = output.observation
    pose_image = tile_pose_depth_dashboard(
        diagnostics,
        observation,
        width=int(pose_cfg.snapshot_pose_width),
        height=int(pose_cfg.snapshot_pose_height),
        min_depth=float(depth_cfg.min_depth),
        max_depth=float(depth_cfg.max_depth),
    )
    score_image = make_score_debug_view(
        diagnostics,
        observation,
        width=int(pose_cfg.snapshot_score_width),
        height=int(pose_cfg.snapshot_score_height),
        min_depth=float(depth_cfg.min_depth),
        max_depth=float(depth_cfg.max_depth),
    )

    output_dir = _resolve_snapshot_dir(python_root, str(pose_cfg.snapshot_output_dir))
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    frame_id = int(getattr(diagnostics, "frame_id", -1))
    stem = f"{timestamp}_frame-{frame_id}"
    pose_path = output_dir / f"{stem}_pose.png"
    score_path = output_dir / f"{stem}_vcd.png"
    _write_png(pose_path, pose_image)
    _write_png(score_path, score_image)
    return pose_path, score_path


def should_show_waiting_frame(has_debug_frame: bool) -> bool:
    """判断 idle tick 是否应显示等待画面。

    已经显示过真实 dashboard 后，不再用 waiting 图覆盖窗口，避免异步 SAM3 等待
    阶段在 dashboard 与 waiting 之间来回闪烁。
    """

    return not bool(has_debug_frame)


def _should_render_debug_frame(now_s: float, last_render_s: float | None, max_fps: float) -> bool:
    """判断某个 OpenCV debug 窗口本轮是否需要重绘。"""

    fps = float(max_fps)
    if fps <= 0.0 or last_render_s is None:
        return True
    return float(now_s) - float(last_render_s) >= 1.0 / fps


def _create_image_window(name: str, width: int, height: int) -> None:
    """创建按图像像素显示的 OpenCV 窗口，避免大画布被窗口二次缩放。"""

    del width, height
    cv2.namedWindow(name, cv2.WINDOW_AUTOSIZE)


def _destroy_window_if_created(name: str, created: bool) -> None:
    """仅销毁已经创建过的 OpenCV 窗口，避免启动失败时掩盖真实异常。"""

    if not created:
        return
    try:
        cv2.destroyWindow(name)
    except cv2.error as exc:
        LOGGER.debug("OpenCV 窗口销毁失败，忽略清理异常: window=%s error=%s", name, exc)


def run_tracking_server(config_path: str | None = None, object_name: str | None = None) -> None:
    """运行 Python-only pose estimation debug server。"""

    cfg = load_config(config_path, object_name=object_name)
    subjects = SubjectRegistry.load(cfg.paths.subjects_path)
    pose_cfg = cfg.demo.pose
    depth_cfg = cfg.pipeline.depth
    show_tracking_window = bool(getattr(getattr(cfg, "debug", object()), "enable_tracking_window", True))

    runtime = TrackingRuntime(cfg, subjects)
    debug_window = str(pose_cfg.debug_window_name)
    score_window = str(getattr(pose_cfg, "score_window_name", "EgoAnchor Score Debug"))
    waiting = make_pose_waiting_image(int(pose_cfg.debug_window_width), int(pose_cfg.debug_window_height), "EgoAnchor Pose Debug") if show_tracking_window else None
    last_wait_log_time = 0.0
    has_debug_frame = False
    debug_window_created = False
    score_window_created = False
    last_debug_render_time: float | None = None
    latest_debug_output: QuestPosePipelineOutput | None = None
    debug_window_max_fps = float(getattr(pose_cfg, "debug_window_max_fps", 0.0))
    python_root = Path(getattr(cfg.paths, "python_root", Path.cwd()))
    recorder = DebugVideoRecorder(
        _resolve_snapshot_dir(python_root, str(getattr(pose_cfg, "video_output_dir", "data/debug/videos"))),
        fps=float(getattr(pose_cfg, "video_fps", 10.0)),
    )

    # 调试窗口渲染性能统计
    debug_render_ms = 0.0
    score_render_ms = 0.0

    try:
        LOGGER.info("正在启动 pose debug runtime；首次加载模型可能需要较长时间。")
        runtime.start()
        if show_tracking_window:
            _create_image_window(debug_window, int(pose_cfg.debug_window_width), int(pose_cfg.debug_window_height))
            debug_window_created = True
            _create_image_window(score_window, int(getattr(pose_cfg, "score_window_width", 2008)), int(getattr(pose_cfg, "score_window_height", 1236)))
            score_window_created = True
            assert waiting is not None
            cv2.imshow(debug_window, waiting)
            LOGGER.info("listening on %s. Keys: 1/2/3/4 stage, r reset, s save PNG, v record video, q/ESC quit.", runtime.endpoint)
        else:
            LOGGER.info("listening on %s. OpenCV debug windows are disabled.", runtime.endpoint)

        while True:
            if show_tracking_window:
                key = cv2.waitKey(1) & 0xFF
                if key != 255:
                    if _is_record_key(key):
                        if recorder.active:
                            recorder.stop()
                        else:
                            recorder.start()
                    elif _is_snapshot_key(key):
                        if latest_debug_output is None:
                            LOGGER.warning("尚无可保存的 debug 帧；请等待首帧处理完成后再按 S。")
                        else:
                            try:
                                pose_path, score_path = _save_debug_snapshots(latest_debug_output, pose_cfg, depth_cfg, cfg.paths.python_root)
                            except (OSError, ValueError, cv2.error) as exc:
                                LOGGER.error("保存 debug PNG 失败: %s", exc)
                            else:
                                LOGGER.info("已保存高分辨率 debug PNG: pose=%s vcd=%s", pose_path, score_path)
                    elif not _handle_key(runtime, key):
                        break

            result = runtime.tick(return_debug=show_tracking_window)
            output = result.pipeline_output
            if output is None or not result.new_frame_processed:
                now = time.perf_counter()
                if now - last_wait_log_time >= float(pose_cfg.wait_log_interval_s):
                    stats = runtime.get_stats()
                    publish_stats = runtime.get_pose_publish_stats()
                    LOGGER.info(
                        "waiting/idle received=%d stereo=%d camera_info=%d decode_failed=%d latest_frame=%s pose_pub=%s/%s failed=%s",
                        stats.received,
                        stats.decoded_stereo,
                        stats.decoded_camera_info,
                        stats.decode_failed,
                        stats.latest_stereo_frame_id,
                        publish_stats.get("submitted", 0),
                        publish_stats.get("attempts", 0),
                        publish_stats.get("failed", 0),
                    )
                    last_wait_log_time = now
                if show_tracking_window and waiting is not None and should_show_waiting_frame(has_debug_frame):
                    cv2.imshow(debug_window, waiting)
                continue

            if not show_tracking_window:
                continue

            latest_debug_output = output

            # 在渲染新帧前，先把上一帧的渲染耗时写入当前帧的 diagnostics
            output.diagnostics.debug_render_ms = debug_render_ms
            output.diagnostics.score_render_ms = score_render_ms

            now = time.perf_counter()
            dashboard = None
            score_debug = None
            if _should_render_debug_frame(now, last_debug_render_time, debug_window_max_fps):
                t_render_start = time.perf_counter()
                dashboard = tile_pose_depth_dashboard(
                    output.diagnostics,
                    output.observation,
                    width=int(pose_cfg.debug_window_width),
                    height=int(pose_cfg.debug_window_height),
                    min_depth=float(depth_cfg.min_depth),
                    max_depth=float(depth_cfg.max_depth),
                )
                cv2.imshow(debug_window, dashboard)
                debug_render_ms = (time.perf_counter() - t_render_start) * 1000.0
                last_debug_render_time = now
                has_debug_frame = True
            if dashboard is not None:
                t_score_start = time.perf_counter()
                score_debug = make_score_debug_view(
                    output.diagnostics,
                    output.observation,
                    width=int(getattr(pose_cfg, "score_window_width", 2008)),
                    height=int(getattr(pose_cfg, "score_window_height", 1236)),
                    min_depth=float(depth_cfg.min_depth),
                    max_depth=float(depth_cfg.max_depth),
                )
                cv2.imshow(score_window, score_debug)
                score_render_ms = (time.perf_counter() - t_score_start) * 1000.0
            if dashboard is not None:
                recorder.submit("pose", dashboard, output.diagnostics.mask)
                if recorder.active:
                    if score_debug is None:
                        raise RuntimeError("录制同步约束失败：Pose 帧缺少同源 VCD 画面。")
                    recorder.submit("vcd", score_debug)
    finally:
        recorder.stop()
        runtime.close()
        _destroy_window_if_created(debug_window, debug_window_created)
        _destroy_window_if_created(score_window, score_window_created)


def main() -> None:
    """解析命令行并启动 pose debug。"""

    parser = argparse.ArgumentParser(description="EgoAnchor Python-only pose estimation debug server")
    parser.add_argument("--config", default=None, help="可选 TOML 配置路径；默认使用包内 defaults.toml")
    parser.add_argument("--object", dest="object_name", default=None, help="目标物体名；来自 src/egoanchor/config/defaults.toml 的 [objects.*] 表")
    parser.add_argument("--log", default="INFO", help="日志级别，例如 DEBUG/INFO/WARNING")
    parser.add_argument("--log-color", choices=("auto", "always", "never"), default="auto", help="console 日志颜色：auto/always/never")
    args = parser.parse_args()

    configure_logging(args.log, force=True, color=args.log_color)
    run_tracking_server(args.config, args.object_name)
