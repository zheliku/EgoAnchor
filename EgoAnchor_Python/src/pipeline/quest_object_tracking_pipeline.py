"""Quest object tracking pipeline: output per-frame 6D object poses."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

# 允许直接以脚本方式运行：python src/pipeline/quest_object_tracking_pipeline.py
if __package__ is None or __package__ == "":
    SRC_DIR = Path(__file__).resolve().parents[1]
    if str(SRC_DIR) not in sys.path:
        sys.path.append(str(SRC_DIR))

from modules import (  # noqa: E402
    AsyncSam3Masker,
    FastFoundationStereoRealtime,
    FoundationPoseEstimator,
    QuestReceiver,
    QuestStereoCalibration,
    QuestStereoMsg,
    Sam3Masker,
    Yoloe26Masker,
)
from modules.cutie import CutieTracker  # noqa: E402
from config import load_runtime_config, print_effective_config  # noqa: E402
from zmq_utils.payload.message.quest_camera_info_msg import QuestCameraInfoMsg  # noqa: E402

THIS_FILE = Path(__file__).resolve()
SRC_DIR = THIS_FILE.parent.parent
PROJECT_DIR = SRC_DIR.parent

# =========================
# 数据结构定义（输入/输出）
# =========================


@dataclass
class PipelineStepTiming:
    """单帧分阶段耗时（毫秒）。"""

    yolo_ms: float = 0.0
    depth_ms: float = 0.0
    cutie_ms: float = 0.0
    pose_ms: float = 0.0


@dataclass
class FrameDiagnostics:
    """单帧几何/对齐诊断数据。"""

    mask_area_ratio: float = 0.0
    depth_valid_in_mask: float = 0.0
    depth_median_in_mask: float = 0.0
    depth_iqr_in_mask: float = 0.0
    segmenter_selected_index: int = -1
    cutie_adjust_applied: bool = False


@dataclass
class TrackingPipelineOutput:
    """Pipeline API 输出：面向外部传输和上层业务。"""

    timestamp_ms: float
    frame_id: int | None
    stage: int
    phase: str
    det_count: int
    depth_valid_ratio: float
    fps: float
    pose_4x4: np.ndarray | None
    timing: PipelineStepTiming
    debug: tuple[np.ndarray, np.ndarray] | None = None


# =========================
# 公共工具函数
# =========================


def _draw_hud(
    img: np.ndarray,
    lines: str | list[str],
    x: int = 12,
    y: int = 28,
    line_gap: int = 24,
) -> None:
    """统一绘制 HUD 文本并按图像宽度自适应换行。"""
    max_chars = max((img.shape[1] - x - 12) // 9, 12)
    wrapped: list[str] = []

    line_list = [lines] if isinstance(lines, str) else lines

    for line in line_list:
        if len(line) <= max_chars:
            wrapped.append(line)
            continue

        words = line.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    wrapped.append(current)
                current = word
        if current:
            wrapped.append(current)

    for idx, line in enumerate(wrapped):
        yy = y + idx * line_gap
        cv2.putText(
            img,
            line,
            (x, yy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (15, 15, 15),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            img,
            line,
            (x, yy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (245, 245, 245),
            1,
            cv2.LINE_AA,
        )


def _colorize_depth(
    depth_m: np.ndarray, min_depth: float, max_depth: float
) -> np.ndarray:
    """把米制深度转为伪彩色，便于人工观察。"""
    depth_f = np.asarray(depth_m, dtype=np.float32)
    denom = max(float(max_depth) - float(min_depth), 1e-6)
    norm = ((depth_f - float(min_depth)) / denom).clip(0.0, 1.0)
    vis = cv2.applyColorMap((norm * 255.0).astype(np.uint8), cv2.COLORMAP_TURBO)

    invalid = (depth_f <= float(min_depth)) | (depth_f >= float(max_depth))
    invalid = invalid | (~np.isfinite(depth_f))
    if invalid.any():
        vis[invalid] = 0
    return vis


def _overlay_mask_contour(
    image_bgr: np.ndarray,
    mask_bw: np.ndarray,
    color: tuple[int, int, int] = (0, 255, 255),
) -> np.ndarray:
    """在图像上叠加真实传入下游的 mask 半透明区域与轮廓。"""
    vis = image_bgr.copy()
    if mask_bw is None or mask_bw.size == 0:
        return vis

    mask = (mask_bw > 0).astype(np.uint8)
    if mask.shape[:2] != vis.shape[:2]:
        mask = cv2.resize(
            mask,
            (vis.shape[1], vis.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )

    color_img = np.zeros_like(vis)
    color_img[mask > 0] = color
    cv2.addWeighted(color_img, 0.35, vis, 1.0, 0.0, vis)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, contours, -1, color, 2)
    return vis


def _tile_debug_dashboard(
    pose_bgr: np.ndarray,
    depth_bgr: np.ndarray,
) -> np.ndarray:
    """合并主调试视图：pose / depth+mask。"""
    h, w = pose_bgr.shape[:2]

    depth_panel = cv2.resize(depth_bgr, (w, h), interpolation=cv2.INTER_AREA)

    _draw_hud(pose_bgr, "POSE", x=8, y=22)
    _draw_hud(depth_panel, "DEPTH+MASK", x=8, y=22)
    return np.hstack((pose_bgr, depth_panel))


def _generate_cube_symmetry_tfs() -> np.ndarray:
    """生成立方体旋转对称群（24 个），用于 FoundationPose 对称约束。"""
    import itertools

    mats: list[np.ndarray] = []
    basis = np.eye(3, dtype=np.float64)

    for perm in itertools.permutations([0, 1, 2]):
        permuted = basis[:, perm]
        for signs in itertools.product([-1.0, 1.0], repeat=3):
            r = permuted @ np.diag(signs)
            if np.linalg.det(r) > 0.9:
                if not any(np.allclose(m, r, atol=1e-6) for m in mats):
                    mats.append(r)

    out: list[np.ndarray] = []
    for r in mats:
        tf = np.eye(4, dtype=np.float64)
        tf[:3, :3] = r
        out.append(tf)
    return np.stack(out, axis=0)


# =========================
# Quest Pipeline 实现
# =========================


class QuestObjectTrackingPipeline:
    """
    Quest object tracking pipeline（结构化独立实现）。

    说明：
    1. `start()`：启动网络接收并重置运行状态。
    2. `run()`：处理一帧并返回 `TrackingPipelineOutput`。
    3. `stop()`：释放接收器资源。

    标定初始化策略：
    - camera_source=network + preload_camera_cache=1：优先用本地 camera_info_latest.json
      预初始化 K 和 PoseEstimator，收到网络 camera_info 后再校验/刷新。
    - camera_source=network + preload_camera_cache=0：严格等待网络 camera_info 后懒初始化。
    - camera_source=local：从本地 camera_info 缓存加载，立即初始化；失败后仍等待网络。
    """

    # 依赖注入。
    cfg: SimpleNamespace
    camera: QuestReceiver
    segmenter: Yoloe26Masker | Sam3Masker | AsyncSam3Masker
    ffs: FastFoundationStereoRealtime
    cutie_tracker: CutieTracker | None

    # 运行期对象与标定状态。
    pose_estimator: FoundationPoseEstimator | None = None
    calib: QuestStereoCalibration | None = None
    cam_k: np.ndarray | None = None
    fx: float = 0.0
    frame_w: int = 0
    frame_h: int = 0

    # 可配置运行参数。
    symmetry_tfs: np.ndarray | None = None
    min_depth: float = 0.1
    max_depth: float = 3.0
    stats_interval: int = 30

    # 流程状态标志。
    stage: int = 4
    _started: bool = False
    _has_pose: bool = False
    _cutie_initialized: bool = False
    _last_processed_frame_id: int | None = None
    _reset_after_frame_id: int | None = None
    _calib_initialized: bool = False  # 标定是否已初始化。
    _last_pose_4x4: np.ndarray | None = None
    _track_reject_count: int = 0
    _segmenter_latest_version: int = 0
    _last_segmenter_result: object | None = None
    _mask_snapshot_shown: bool = False

    # 性能统计累加器。
    _frame_count: int = 0
    _start_t: float = 0.0
    _stats_t: float = 0.0
    _last_frame_t: float = 0.0
    _fps_rt: float = 0.0
    _seg_acc: float = 0.0
    _depth_acc: float = 0.0
    _cutie_acc: float = 0.0
    _pose_acc: float = 0.0

    def __init__(
        self,
        cfg: SimpleNamespace,
        camera: QuestReceiver,
        segmenter: Yoloe26Masker | Sam3Masker | AsyncSam3Masker,
        ffs: FastFoundationStereoRealtime,
        cutie_tracker: CutieTracker | None,
        calib: QuestStereoCalibration | None = None,
    ) -> None:
        """
        初始化 Quest object tracking pipeline。

        参数：
        - cfg: TOML 运行配置。
        - camera: Quest 多 Topic 接收模块。
        - segmenter: 2D 分割模块，当前主线为 YOLOE-26；SAM3/AsyncSam3Masker 仅作为可选历史路径保留。
        - ffs: 双目深度模块。
        - cutie_tracker: 可选 2D 跟踪模块。
        - calib: 可选预加载的 camera_info 标定缓存。
        """
        self.cfg = cfg
        self.camera = camera
        self.segmenter = segmenter
        self.ffs = ffs
        self.cutie_tracker = cutie_tracker

        # 对称约束预先缓存。
        self.symmetry_tfs = (
            _generate_cube_symmetry_tfs()
            if cfg.module.foundationpose.symmetry_mode == "cube"
            else None
        )

        # 深度阈值与统计配置。
        self.min_depth = float(cfg.pipeline.depth.min_depth)
        self.max_depth = float(cfg.pipeline.depth.max_depth)
        self.stats_interval = max(int(cfg.debug.pipeline_stats_interval), 1)

        # 若提供了标定，立即初始化 K 和 PoseEstimator。
        if calib is not None:
            self._init_from_calibration(calib)

    @staticmethod
    def _make_calib_signature(calib: QuestStereoCalibration) -> tuple[float, ...]:
        """生成标定参数签名，用于判断网络标定是否与预加载缓存不同。"""
        return (
            round(float(calib.left_fx), 4),
            round(float(calib.left_fy), 4),
            round(float(calib.left_cx), 4),
            round(float(calib.left_cy), 4),
            round(float(calib.baseline_m), 8),
            float(int(calib.calib_width)),
            float(int(calib.calib_height)),
        )

    def _init_from_calibration(self, calib: QuestStereoCalibration) -> None:
        """根据标定参数初始化 K 和 PoseEstimator。"""
        self.calib = calib
        logging.info(
            "[QuestCalib] fx=%.3f fy=%.3f cx=%.3f cy=%.3f baseline=%.6fm calib=%dx%d",
            calib.left_fx,
            calib.left_fy,
            calib.left_cx,
            calib.left_cy,
            calib.baseline_m,
            calib.calib_width,
            calib.calib_height,
        )

        self.frame_w = max(int(self.cfg.pipeline.calibration.process_width), 0)
        self.frame_h = max(int(self.cfg.pipeline.calibration.process_height), 0)
        if self.frame_w <= 0 or self.frame_h <= 0:
            self.frame_w = int(calib.calib_width)
            self.frame_h = int(calib.calib_height)

        self.cam_k = calib.scaled_k(
            width=self.frame_w,
            height=self.frame_h,
            assume_center_crop=bool(self.cfg.pipeline.calibration.assume_center_crop),
        )
        self.fx = float(self.cam_k[0, 0])

        logging.info(
            "[KMap] mode=%s fx=%.2f fy=%.2f cx=%.2f cy=%.2f frame=%dx%d",
            (
                "center-crop+scale"
                if bool(self.cfg.pipeline.calibration.assume_center_crop)
                else "linear-scale-only"
            ),
            float(self.cam_k[0, 0]),
            float(self.cam_k[1, 1]),
            float(self.cam_k[0, 2]),
            float(self.cam_k[1, 2]),
            self.frame_w,
            self.frame_h,
        )

        self.pose_estimator = FoundationPoseEstimator(
            mesh_path=str(self.cfg.module.foundationpose.mesh_path),
            cam_k=self.cam_k,
            est_refine_iter=int(self.cfg.module.foundationpose.est_refine_iter),
            track_refine_iter=int(self.cfg.module.foundationpose.track_refine_iter),
            symmetry_tfs=self.symmetry_tfs,
            debug=int(self.cfg.module.foundationpose.debug),
            debug_dir=(
                None
                if not self.cfg.module.foundationpose.debug_dir
                else str(self.cfg.module.foundationpose.debug_dir)
            ),
        )
        self._calib_initialized = True
        self._calib_signature = self._make_calib_signature(calib)

    def _try_init_from_network(self) -> bool:
        """尝试从网络 camera_info 消息初始化标定。返回是否成功。"""
        calib = self.camera.get_calibration()
        if calib is None:
            return False
        self._init_from_calibration(calib)
        return True

    def _refresh_calibration_from_network_if_needed(self) -> None:
        """若网络 camera_info 与预加载缓存不同，则刷新 K 与 PoseEstimator。

        使用场景：
        - object_tracking_server 启动时可先用本地 camera_info_latest.json 预初始化 FoundationPose；
        - 后续真正收到 Quest 端 camera_info 后，再用该方法校验是否需要切换到网络标定；
        - 若已经进入跟踪，刷新标定会重置跟踪状态，保证后续 pose 使用正确 K。
        """
        if not bool(self.cfg.pipeline.calibration.network_calib_update):
            return
        if self.camera.get_camera_info() is None:
            return

        calib = self.camera.get_calibration()
        if calib is None:
            return

        new_signature = self._make_calib_signature(calib)
        old_signature = getattr(self, "_calib_signature", None)
        if old_signature == new_signature:
            return

        logging.info("[QuestCalib] 网络 camera_info 与当前标定不同，刷新 K/PoseEstimator")
        self._init_from_calibration(calib)
        self.reset_tracking_state()

    def start(self) -> None:
        """启动 Pipeline：启动接收器并重置运行状态。"""
        if self._started:
            return

        self.camera.start()
        if hasattr(self.segmenter, "start"):
            self.segmenter.start()

        self._started = True
        self._has_pose = False
        self._cutie_initialized = False
        self._last_pose_4x4 = None
        self._track_reject_count = 0
        if self.pose_estimator is not None:
            self.pose_estimator.reset()
        if self.cutie_tracker is not None and hasattr(self.cutie_tracker, "reset"):
            self.cutie_tracker.reset()
        self._frame_count = 0
        self._start_t = time.perf_counter()
        self._stats_t = self._start_t
        self._last_frame_t = 0.0
        self._fps_rt = 0.0
        self._last_processed_frame_id = None
        self._reset_after_frame_id = None
        self._segmenter_latest_version = 0
        self._last_segmenter_result = None
        self._mask_snapshot_shown = False
        self._seg_acc = 0.0
        self._depth_acc = 0.0
        self._cutie_acc = 0.0
        self._pose_acc = 0.0

    def stop(self) -> None:
        """停止 Pipeline：关闭接收器并清理状态。"""
        if not self._started:
            return
        if hasattr(self.segmenter, "stop"):
            self.segmenter.stop()
        self.camera.stop()
        self._started = False

    def set_stage(self, stage: int) -> None:
        """切换执行阶段，并重置跟踪状态避免状态污染。"""
        stage_int = int(stage)
        if stage_int < 1 or stage_int > 4:
            raise ValueError(f"stage 必须在 1..4 之间，当前值: {stage_int}")
        self.stage = stage_int
        self.reset_tracking_state()

    def reset_tracking_state(self) -> None:
        """仅重置位姿跟踪状态，不重启接收器。"""
        self._has_pose = False
        self._cutie_initialized = False
        self._last_pose_4x4 = None
        self._track_reject_count = 0
        self._last_segmenter_result = None
        self._mask_snapshot_shown = False
        self._reset_after_frame_id = self._last_processed_frame_id
        if isinstance(self.segmenter, AsyncSam3Masker):
            self._segmenter_latest_version = 0
            min_frame_id = (
                self._last_processed_frame_id + 1
                if self._last_processed_frame_id is not None
                else None
            )
            self.segmenter.reset_runtime(min_frame_id=min_frame_id)
        if self.pose_estimator is not None:
            self.pose_estimator.reset()
        if self.cutie_tracker is not None and hasattr(self.cutie_tracker, "reset"):
            self.cutie_tracker.reset()

    def _show_mask_snapshot_once(
        self,
        image_bgr: np.ndarray,
        mask_bw: np.ndarray,
        det_count: int,
        selected_index: int = -1,
    ) -> None:
        """检测到首个有效 mask 时显示一张 RGB/mask 对齐快照，不按视频流刷新。"""
        if self._mask_snapshot_shown:
            return
        if not bool(self.cfg.debug.show_mask_snapshot):
            return
        if det_count <= 0 or mask_bw is None or mask_bw.size == 0:
            return
        if np.count_nonzero(mask_bw) <= 0:
            return

        mask = (mask_bw > 0).astype(np.uint8)
        if mask.shape[:2] != image_bgr.shape[:2]:
            mask = cv2.resize(
                mask,
                (image_bgr.shape[1], image_bgr.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )

        rgb_panel = image_bgr.copy()
        mask_panel = cv2.cvtColor(mask * 255, cv2.COLOR_GRAY2BGR)
        overlay_panel = _overlay_mask_contour(image_bgr, mask * 255, (0, 255, 255))

        _draw_hud(rgb_panel, "RGB frame", x=8, y=22)
        _draw_hud(mask_panel, "Mask", x=8, y=22)
        _draw_hud(
            overlay_panel,
            [
                "RGB + mask",
                f"det={det_count} selected={selected_index} area={np.count_nonzero(mask) / float(mask.size):.1%}",
            ],
            x=8,
            y=22,
        )
        snapshot = np.hstack((rgb_panel, mask_panel, overlay_panel))

        window_name = str(self.cfg.debug.mask_snapshot_window)
        cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
        cv2.imshow(window_name, snapshot)
        cv2.waitKey(1)
        self._mask_snapshot_shown = True
        logging.info(
            "[debug] mask snapshot shown: det=%d selected=%d area=%.1f%% window=%s",
            det_count,
            selected_index,
            np.count_nonzero(mask) / float(mask.size) * 100.0,
            window_name,
        )

    def _log_stats_if_due(self, output: TrackingPipelineOutput) -> None:
        """按固定间隔打印统计信息，便于线上观察性能。"""
        if self._frame_count % self.stats_interval != 0:
            return

        now = time.perf_counter()
        interval = max(now - self._stats_t, 1e-6)
        window_fps = self.stats_interval / interval

        q_stats = self.camera.get_stats()
        sender_est_ms = float(q_stats.get("sender_est_delay_ms", 0.0) or 0.0)
        sender_raw_ms = float(q_stats.get("sender_raw_delta_ms", 0.0) or 0.0)
        sender_gap = int(q_stats.get("sender_gap", 0) or 0)
        sender_fps = float(q_stats.get("sender_fps", 0.0) or 0.0)

        logging.info(
            "[stats] frames=%d stage=%d phase=%s rt_fps=%.1f window_fps=%.1f "
            "avg(seg/depth/cutie/pose)=%.1f/%.1f/%.1f/%.1fms depth_valid=%.1f%% "
            "recv=%s decode_fail=%s sender_fps=%.1f sender_est=%.1fms sender_raw=%.1fms sender_gap=%s",
            self._frame_count,
            self.stage,
            output.phase,
            output.fps,
            window_fps,
            self._seg_acc / self.stats_interval,
            self._depth_acc / self.stats_interval,
            self._cutie_acc / self.stats_interval,
            self._pose_acc / self.stats_interval,
            output.depth_valid_ratio * 100.0,
            q_stats.get("received", 0),
            q_stats.get("decode_failed", 0),
            sender_fps,
            sender_est_ms,
            sender_raw_ms,
            sender_gap,
        )

        self._stats_t = now
        self._seg_acc = 0.0
        self._depth_acc = 0.0
        self._cutie_acc = 0.0
        self._pose_acc = 0.0

    def _preprocess_stereo_pair(
        self,
        left: np.ndarray,
        right: np.ndarray,
        target_width: int,
        target_height: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """将实际接收到的 Quest 双目图归一化到算法处理分辨率。

        说明：
        1. 相机内参 K 的映射已经在 QuestStereoCalibration.scaled_k() 中完成；
           本函数只负责把网络解码后的图像尺寸调整到算法输入尺寸。
        2. 若 Unity 端已经输出 640x480，这里不会再把图像扩回 active array，
           也不会重复执行中心裁剪，避免图像与 K 出现二次映射误差。
        3. 若左右图尺寸不同，先对齐到较小公共尺寸，再统一缩放到目标尺寸。
        """
        if self.calib is None:
            raise RuntimeError("标定尚未初始化，无法预处理图像。")

        def _to_bgr(img: np.ndarray) -> np.ndarray:
            if img.ndim == 2:
                return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            return img[..., :3]

        left_bgr = _to_bgr(left)
        right_bgr = _to_bgr(right)

        if left_bgr.shape[:2] != right_bgr.shape[:2]:
            logging.warning(
                "[QuestInput] 左右图尺寸不同 left=%s right=%s，将缩放到公共尺寸；这可能破坏双目几何。",
                left_bgr.shape[:2],
                right_bgr.shape[:2],
            )
            out_h = min(left_bgr.shape[0], right_bgr.shape[0])
            out_w = min(left_bgr.shape[1], right_bgr.shape[1])
            left_bgr = cv2.resize(
                left_bgr, (out_w, out_h), interpolation=cv2.INTER_LINEAR
            )
            right_bgr = cv2.resize(
                right_bgr, (out_w, out_h), interpolation=cv2.INTER_LINEAR
            )

        target_w = int(target_width)
        target_h = int(target_height)
        if target_w > 0 and target_h > 0:
            h, w = left_bgr.shape[:2]
            if w != target_w or h != target_h:
                interpolation = (
                    cv2.INTER_AREA
                    if (target_w < w or target_h < h)
                    else cv2.INTER_LINEAR
                )
                left_bgr = cv2.resize(
                    left_bgr, (target_w, target_h), interpolation=interpolation
                )
                right_bgr = cv2.resize(
                    right_bgr, (target_w, target_h), interpolation=interpolation
                )

        return left_bgr, right_bgr

    def _compute_frame_diagnostics(
        self,
        mask_bw: np.ndarray,
        depth_m: np.ndarray,
        segmenter_selected_index: int = -1,
    ) -> FrameDiagnostics:
        """计算 mask/depth 对齐相关诊断指标。"""
        diag = FrameDiagnostics(segmenter_selected_index=int(segmenter_selected_index))
        if mask_bw is None or mask_bw.size == 0:
            return diag

        mask = mask_bw > 0
        diag.mask_area_ratio = float(mask.mean())
        if not np.any(mask) or depth_m is None or depth_m.size == 0:
            return diag

        depth = np.asarray(depth_m, dtype=np.float32)
        if depth.shape[:2] != mask.shape[:2]:
            return diag

        values = depth[mask]
        valid = values[np.isfinite(values) & (values > 0.0)]
        diag.depth_valid_in_mask = float(valid.size) / float(max(values.size, 1))
        if valid.size > 0:
            q25, q50, q75 = np.percentile(valid, [25, 50, 75])
            diag.depth_median_in_mask = float(q50)
            diag.depth_iqr_in_mask = float(q75 - q25)
        return diag

    def _is_pose_valid(self, pose_4x4: np.ndarray | None) -> bool:
        """基础 pose 合法性过滤，避免 NaN/越界深度进入持续跟踪。"""
        if pose_4x4 is None:
            return False
        pose = np.asarray(pose_4x4)
        if pose.shape != (4, 4) or not np.isfinite(pose).all():
            return False
        z = float(pose[2, 3])
        return self.min_depth <= z <= self.max_depth

    def _is_track_jump(self, pose_4x4: np.ndarray) -> bool:
        """过滤 FoundationPose track 的明显跳变输出。"""
        if self._last_pose_4x4 is None:
            return False

        trans_delta = float(
            np.linalg.norm(pose_4x4[:3, 3] - self._last_pose_4x4[:3, 3])
        )
        rel = pose_4x4[:3, :3] @ self._last_pose_4x4[:3, :3].T
        rot_delta = float(
            np.degrees(
                np.arccos(np.clip((float(np.trace(rel)) - 1.0) * 0.5, -1.0, 1.0))
            )
        )
        return (
            trans_delta > float(self.cfg.module.foundationpose.pose_jump_translation_m)
            or rot_delta > float(self.cfg.module.foundationpose.pose_jump_rotation_deg)
        )

    def _try_recover_by_register(
        self,
        left_rgb: np.ndarray,
        depth_m: np.ndarray,
        mask_bw: np.ndarray,
        diag: FrameDiagnostics,
        timing: PipelineStepTiming,
    ) -> np.ndarray | None:
        """用当前稳定 2D mask 重新 register，作为快速运动导致 track 丢失后的恢复路径。"""
        if self.pose_estimator is None:
            return None
        if not bool(self.cfg.module.foundationpose.re_register_on_track_lost):
            return None
        if diag.depth_valid_in_mask < float(self.cfg.module.foundationpose.register_min_depth_valid_in_mask):
            return None
        if np.count_nonzero(mask_bw) <= 0:
            return None

        t0 = time.perf_counter()
        try:
            self.pose_estimator.reset()
            pose_4x4 = self.pose_estimator.register(
                rgb=left_rgb,
                depth=depth_m.astype(np.float64),
                mask=mask_bw,
            )
            pose_4x4 = np.asarray(pose_4x4, dtype=np.float64).reshape(4, 4)
        except Exception as exc:
            logging.warning("[FoundationPose] re-register 失败: %s", exc)
            self.pose_estimator.reset()
            return None
        finally:
            timing.pose_ms += (time.perf_counter() - t0) * 1000.0

        if not self._is_pose_valid(pose_4x4):
            logging.warning("[FoundationPose] re-register 输出非法或 z 越界。")
            self.pose_estimator.reset()
            return None

        self._has_pose = True
        self._track_reject_count = 0
        self._last_pose_4x4 = pose_4x4.copy()

        if self.cutie_tracker is not None:
            ct0 = time.perf_counter()
            try:
                _ = self.cutie_tracker.initialize(left_rgb, init_mask=mask_bw)
                self._cutie_initialized = True
            except Exception as exc:
                self._cutie_initialized = False
                logging.warning("[cutie] re-register 后初始化失败: %s", exc)
            timing.cutie_ms += (time.perf_counter() - ct0) * 1000.0

        return pose_4x4

    def _run_cutie_on_current_frame(
        self,
        left_rgb: np.ndarray,
        mask_bw: np.ndarray,
        det_count: int,
        diag: FrameDiagnostics,
        timing: PipelineStepTiming,
        allow_reinit: bool = True,
        adjust_pose: bool = False,
    ) -> tuple[np.ndarray | None, list[int]]:
        """在当前帧传播 Cutie mask；SAM3 慢速种子只负责初始化，实时 mask 由这里对齐当前帧。"""
        cutie_bbox = [-1, -1, 0, 0]
        if self.cutie_tracker is None or not self._cutie_initialized:
            return None, cutie_bbox

        ct0 = time.perf_counter()
        cutie_mask: np.ndarray | None = None
        try:
            cutie_result = self.cutie_tracker.track(left_rgb)
            cutie_bbox = cutie_result.bbox_xywh
            cutie_mask = (cutie_result.mask > 0).astype(np.uint8) * 255

            x, y, bw, bh = cutie_bbox
            if bw > 0 and bh > 0:
                cx = float(x + bw / 2.0)
                cy = float(y + bh / 2.0)
                if adjust_pose and bool(self.cfg.module.cutie.adjust_pose):
                    self.pose_estimator.adjust_pose_to_image_point(cx, cy)
                    diag.cutie_adjust_applied = True
            elif allow_reinit and det_count > 0 and np.count_nonzero(mask_bw) > 0:
                _ = self.cutie_tracker.initialize(left_rgb, init_mask=mask_bw)
                self._cutie_initialized = True
        except Exception as exc:
            logging.warning("[cutie] 跟踪失败: %s", exc)
            self._cutie_initialized = False
            cutie_mask = None
        finally:
            timing.cutie_ms += (time.perf_counter() - ct0) * 1000.0

        return cutie_mask, cutie_bbox


    def run(self, return_debug: bool = False) -> TrackingPipelineOutput | None:
        """
        执行一帧 Pipeline，并返回位姿结果。

        若标定未初始化，优先尝试从网络获取 camera_info。
        若当前未收到帧，则返回 None。
        """
        if not self._started:
            raise RuntimeError("Pipeline 尚未启动，请先调用 start()。")

        # 懒初始化标定：等待网络 camera_info。
        if not self._calib_initialized:
            self.camera.poll_all(timeout_ms=int(self.cfg.network.receiver.timeout_ms))
            if not self._try_init_from_network():
                return None

        # 读取一帧网络双目图。
        stereo = self.camera.get_stereo_frames()

        if stereo is None:
            return None

        if stereo.left is None or stereo.right is None or stereo.timestamp_ms is None:
            return None

        # 接收器会缓存最新帧；这里跳过重复 frame_id，避免无新包时重复跑整条算法链。
        if stereo.frame_id is not None:
            frame_id = int(stereo.frame_id)
            if self._last_processed_frame_id == frame_id:
                return None
            self._last_processed_frame_id = frame_id

        # 如果启动时使用了本地缓存预初始化，这里在收到网络 camera_info 后做一次校验刷新。
        self._refresh_calibration_from_network_if_needed()

        left_bgr, right_bgr = self._preprocess_stereo_pair(
            stereo.left,
            stereo.right,
            target_width=self.frame_w,
            target_height=self.frame_h,
        )
        left_rgb = cv2.cvtColor(left_bgr, cv2.COLOR_BGR2RGB)

        stereo_timestamp_ms = float(stereo.timestamp_ms)

        if self.pose_estimator is None:
            raise RuntimeError("pose_estimator 尚未初始化。")
        if self.calib is None:
            raise RuntimeError("标定信息尚未初始化。")

        # 默认占位数据。
        timing = PipelineStepTiming()
        det_count = 0
        phase = "STAGE1_CAMERA"
        pose_4x4: np.ndarray | None = None

        mask_bw = np.zeros(left_bgr.shape[:2], dtype=np.uint8)
        depth_m = np.zeros(left_bgr.shape[:2], dtype=np.float32)
        vis_bgr = left_bgr.copy()
        diag = FrameDiagnostics()
        stage_cutie_mask: np.ndarray | None = None
        stage_cutie_bbox = [-1, -1, 0, 0]

        # 阶段2：通用 2D 分割。当前默认 YOLOE-26；SAM3/AsyncSam3Masker 仅作为可选路径保留。
        if self.stage >= 2:
            segmenter_result = None
            segmenter_name = str(self.cfg.module.segmenter.type).lower()

            if isinstance(self.segmenter, AsyncSam3Masker):
                t0 = time.perf_counter()
                prev_version = self._segmenter_latest_version
                should_submit_sam3 = not (
                    self._has_pose
                    and self._cutie_initialized
                    and not bool(self.cfg.module.sam3.refresh_when_tracking)
                )
                if should_submit_sam3:
                    _ = self.segmenter.submit(
                        left_bgr,
                        frame_id=int(stereo.frame_id) if stereo.frame_id is not None else None,
                        timestamp_ms=stereo_timestamp_ms,
                    )
                latest, version = self.segmenter.get_latest()
                latest_is_new = latest is not None and version != self._segmenter_latest_version
                if (
                    latest_is_new
                    and latest.source_frame_id is not None
                    and self._reset_after_frame_id is not None
                    and latest.source_frame_id <= self._reset_after_frame_id
                ):
                    latest_is_new = False

                if latest is not None and latest_is_new and not self._has_pose:
                    if (
                        not bool(self.cfg.module.sam3.allow_stale_register)
                        and latest.source_timestamp_ms is not None
                    ):
                        age_ms = max(0.0, stereo_timestamp_ms - float(latest.source_timestamp_ms))
                        if age_ms > float(self.cfg.module.sam3.max_result_age_ms):
                            logging.debug(
                                "[SAM3] 异步结果过旧 age=%.0fms，仅保留展示，不直接 register。",
                                age_ms,
                            )
                    self._segmenter_latest_version = version
                    self._reset_after_frame_id = None
                    if (
                        self.cutie_tracker is not None
                        and latest.det_count > 0
                        and np.count_nonzero(latest.mask_bw) > 0
                    ):
                        ct0 = time.perf_counter()
                        try:
                            seed_rgb = (
                                cv2.cvtColor(latest.source_image_bgr, cv2.COLOR_BGR2RGB)
                                if latest.source_image_bgr is not None
                                else left_rgb
                            )
                            _ = self.cutie_tracker.initialize(
                                seed_rgb, init_mask=latest.mask_bw
                            )
                            self._cutie_initialized = True
                        except Exception as exc:
                            self._cutie_initialized = False
                            logging.warning("[cutie] SAM3 种子初始化失败: %s", exc)
                        timing.cutie_ms += (time.perf_counter() - ct0) * 1000.0
                    elif bool(self.cfg.module.sam3.allow_stale_register):
                        segmenter_result = latest
                timing.yolo_ms = (time.perf_counter() - t0) * 1000.0
                stats = self.segmenter.get_stats()
                last_infer = float(stats.get("last_infer_ms", 0.0) or 0.0)
                if last_infer > 0.0 and version != prev_version and latest_is_new:
                    timing.yolo_ms = last_infer
            else:
                t0 = time.perf_counter()
                segmenter_result = self.segmenter.infer(left_bgr)
                timing.yolo_ms = (time.perf_counter() - t0) * 1000.0
            self._seg_acc += timing.yolo_ms

            if segmenter_result is not None:
                self._last_segmenter_result = segmenter_result
                det_count = int(segmenter_result.det_count)
                mask_bw = segmenter_result.mask_bw
                if mask_bw.shape[:2] != left_bgr.shape[:2]:
                    logging.warning(
                        "[segmenter:%s] mask 尺寸与图像不一致 mask=%s image=%s，已按最近邻缩放。",
                        segmenter_name,
                        mask_bw.shape[:2],
                        left_bgr.shape[:2],
                    )
                    mask_bw = cv2.resize(
                        mask_bw,
                        (left_bgr.shape[1], left_bgr.shape[0]),
                        interpolation=cv2.INTER_NEAREST,
                    )
                diag.segmenter_selected_index = int(getattr(segmenter_result, "selected_index", -1))
                diag.mask_area_ratio = float(getattr(segmenter_result, "mask_area_ratio", 0.0))
                vis_bgr = segmenter_result.overlay.copy()
                self._show_mask_snapshot_once(
                    image_bgr=left_bgr,
                    mask_bw=mask_bw,
                    det_count=det_count,
                    selected_index=diag.segmenter_selected_index,
                )

            # SAM3 异步结果可能来自旧帧；启用该历史路径时，当前帧 register 优先使用 Cutie 传播 mask。
            if isinstance(self.segmenter, AsyncSam3Masker) and self._cutie_initialized:
                stage_cutie_mask, stage_cutie_bbox = self._run_cutie_on_current_frame(
                    left_rgb=left_rgb,
                    mask_bw=mask_bw,
                    det_count=det_count,
                    diag=diag,
                    timing=timing,
                    allow_reinit=False,
                    adjust_pose=False,
                )
                if stage_cutie_mask is not None and np.count_nonzero(stage_cutie_mask) > 0:
                    mask_bw = stage_cutie_mask
                    det_count = 1
                    diag.mask_area_ratio = float(np.count_nonzero(mask_bw)) / float(mask_bw.size)
                    vis_bgr = _overlay_mask_contour(left_bgr, mask_bw, (0, 255, 255))
            elif (
                isinstance(self.segmenter, AsyncSam3Masker)
                and not bool(self.cfg.module.sam3.allow_stale_register)
            ):
                det_count = 0

            phase = "STAGE2_SEGMENT"

        # 阶段3：FFS 深度。
        if self.stage >= 3:
            t1 = time.perf_counter()
            depth_m = self.ffs.predict_depth(
                left_image=left_bgr,
                right_image=right_bgr,
                fx=self.fx,
                baseline=float(self.calib.baseline_m),
            )
            timing.depth_ms = (time.perf_counter() - t1) * 1000.0
            self._depth_acc += timing.depth_ms

            depth_m = np.asarray(depth_m, dtype=np.float32)
            if depth_m.shape[:2] != left_bgr.shape[:2]:
                logging.warning(
                    "[FFS] depth 尺寸与图像不一致 depth=%s image=%s，已线性缩放。",
                    depth_m.shape[:2],
                    left_bgr.shape[:2],
                )
                depth_m = cv2.resize(
                    depth_m,
                    (left_bgr.shape[1], left_bgr.shape[0]),
                    interpolation=cv2.INTER_LINEAR,
                )
            invalid = (depth_m < self.min_depth) | (depth_m > self.max_depth)
            depth_m[invalid] = 0.0
            diag = self._compute_frame_diagnostics(
                mask_bw,
                depth_m,
                segmenter_selected_index=diag.segmenter_selected_index,
            )
            phase = "STAGE3_FFS"

        # 阶段4：FoundationPose 注册/跟踪。
        if self.stage >= 4:
            t2 = time.perf_counter()

            cutie_bbox = stage_cutie_bbox
            cutie_mask: np.ndarray | None = stage_cutie_mask

            if not self._has_pose:
                has_valid_mask = det_count > 0 and np.count_nonzero(mask_bw) > 0
                if has_valid_mask and diag.depth_valid_in_mask >= float(self.cfg.module.foundationpose.register_min_depth_valid_in_mask):
                    try:
                        pose_4x4 = self.pose_estimator.register(
                            rgb=left_rgb,
                            depth=depth_m.astype(np.float64),
                            mask=mask_bw,
                        )
                        pose_4x4 = np.asarray(pose_4x4, dtype=np.float64).reshape(4, 4)
                        if not self._is_pose_valid(pose_4x4):
                            logging.warning("[FoundationPose] register 输出非法或 z 越界，丢弃本次结果。")
                            pose_4x4 = None
                            self.pose_estimator.reset()
                            phase = "REJECT_POSE"
                        else:
                            self._has_pose = True
                            self._track_reject_count = 0
                            self._last_pose_4x4 = pose_4x4.copy()
                            vis_bgr = cv2.cvtColor(
                                self.pose_estimator.visualize_pose(left_rgb, pose_4x4),
                                cv2.COLOR_RGB2BGR,
                            )

                            if self.cutie_tracker is not None:
                                ct0 = time.perf_counter()
                                try:
                                    _ = self.cutie_tracker.initialize(
                                        left_rgb, init_mask=mask_bw
                                    )
                                    self._cutie_initialized = True
                                except Exception as exc:
                                    self._cutie_initialized = False
                                    logging.warning("[cutie] 初始化失败: %s", exc)
                                timing.cutie_ms += (time.perf_counter() - ct0) * 1000.0
                            phase = "REGISTER"
                    except Exception as exc:
                        logging.warning("[FoundationPose] register 失败: %s", exc)
                        pose_4x4 = None
                        self.pose_estimator.reset()
                        phase = "REJECT_POSE"
                elif has_valid_mask:
                    phase = "REJECT_DEPTH"
                else:
                    phase = "WAIT_DETECT"

            else:
                if cutie_mask is None:
                    cutie_mask, cutie_bbox = self._run_cutie_on_current_frame(
                        left_rgb=left_rgb,
                        mask_bw=mask_bw,
                        det_count=det_count,
                        diag=diag,
                        timing=timing,
                        allow_reinit=True,
                        adjust_pose=True,
                    )
                elif cutie_bbox[2] > 0 and cutie_bbox[3] > 0 and bool(self.cfg.module.cutie.adjust_pose):
                    x, y, bw, bh = cutie_bbox
                    self.pose_estimator.adjust_pose_to_image_point(float(x + bw / 2.0), float(y + bh / 2.0))
                    diag.cutie_adjust_applied = True

                try:
                    pose_4x4 = self.pose_estimator.track(
                        rgb=left_rgb,
                        depth=depth_m.astype(np.float64),
                    )
                    pose_4x4 = np.asarray(pose_4x4, dtype=np.float64).reshape(4, 4)
                except Exception as exc:
                    logging.warning("[FoundationPose] track 失败: %s", exc)
                    pose_4x4 = None
                    self._track_reject_count += 1
                    self._has_pose = False
                    self.pose_estimator.reset()
                    phase = "REJECT_POSE"

                if pose_4x4 is not None and not self._is_pose_valid(pose_4x4):
                    logging.warning("[FoundationPose] track 输出非法或 z 越界，重置跟踪。")
                    pose_4x4 = None
                    self._track_reject_count += 1
                    self._has_pose = False
                    self.pose_estimator.reset()
                    phase = "REJECT_POSE"
                elif pose_4x4 is not None and self._is_track_jump(pose_4x4):
                    self._track_reject_count += 1
                    logging.warning(
                        "[FoundationPose] track pose 跳变，尝试 re-register (reject_count=%d)。",
                        self._track_reject_count,
                    )
                    pose_4x4 = None
                    self._has_pose = False
                    self.pose_estimator.reset()
                    phase = "REJECT_JUMP"
                elif pose_4x4 is not None:
                    self._track_reject_count = 0
                    self._last_pose_4x4 = pose_4x4.copy()
                    vis_bgr = cv2.cvtColor(
                        self.pose_estimator.visualize_pose(left_rgb, pose_4x4),
                        cv2.COLOR_RGB2BGR,
                    )
                    phase = "TRACK"

                if pose_4x4 is None:
                    recovered_pose = self._try_recover_by_register(
                        left_rgb=left_rgb,
                        depth_m=depth_m,
                        mask_bw=cutie_mask if cutie_mask is not None else mask_bw,
                        diag=self._compute_frame_diagnostics(
                            cutie_mask if cutie_mask is not None else mask_bw,
                            depth_m,
                            segmenter_selected_index=diag.segmenter_selected_index,
                        ),
                        timing=timing,
                    )
                    if recovered_pose is not None:
                        pose_4x4 = recovered_pose
                        vis_bgr = cv2.cvtColor(
                            self.pose_estimator.visualize_pose(left_rgb, pose_4x4),
                            cv2.COLOR_RGB2BGR,
                        )
                        phase = "RE_REGISTER"

                if pose_4x4 is not None and cutie_bbox[2] > 0 and cutie_bbox[3] > 0:
                    x, y, bw, bh = cutie_bbox
                    cv2.rectangle(
                        vis_bgr,
                        (int(x), int(y)),
                        (int(x + bw), int(y + bh)),
                        (0, 255, 255),
                        2,
                    )
                    if cutie_mask is not None:
                        mask_bw = cutie_mask
            timing.pose_ms = (time.perf_counter() - t2) * 1000.0
            self._pose_acc += timing.pose_ms
            self._cutie_acc += timing.cutie_ms

        # 更新帧统计。
        now = time.perf_counter()
        self._frame_count += 1
        if self._last_frame_t > 0.0:
            dt = max(now - self._last_frame_t, 1e-6)
            inst_fps = 1.0 / dt
            self._fps_rt = (
                inst_fps
                if self._fps_rt <= 0.0
                else (self._fps_rt * 0.85 + inst_fps * 0.15)
            )
        fps = self._fps_rt if self._fps_rt > 0.0 else 0.0
        self._last_frame_t = now
        depth_valid_ratio = float((depth_m > 0).mean()) if self.stage >= 3 else 0.0

        debug_data: tuple[np.ndarray, np.ndarray] | None = None
        if return_debug:
            depth_vis_bgr = _colorize_depth(depth_m, self.min_depth, self.max_depth)
            alignment_depth_bgr = _overlay_mask_contour(depth_vis_bgr, mask_bw, (0, 255, 255))
            stereo_vis_bgr = np.hstack((left_bgr, right_bgr))

            _draw_hud(
                vis_bgr,
                [
                    f"fps={fps:.1f} stage={self.stage} {phase} det={det_count}",
                    f"ms seg/d/c/p={timing.yolo_ms:.0f}/{timing.depth_ms:.0f}/{timing.cutie_ms:.0f}/{timing.pose_ms:.0f}",
                    f"depth={depth_valid_ratio:.0%} in_mask={diag.depth_valid_in_mask:.0%} med={diag.depth_median_in_mask:.2f}m",
                    f"mask={diag.mask_area_ratio:.1%} reject={self._track_reject_count}",
                ],
            )
            dashboard_bgr = _tile_debug_dashboard(
                pose_bgr=vis_bgr,
                depth_bgr=alignment_depth_bgr,
            )
            _draw_hud(stereo_vis_bgr, "STEREO", x=8, y=22)

            debug_data = (dashboard_bgr, stereo_vis_bgr)

        output = TrackingPipelineOutput(
            timestamp_ms=stereo_timestamp_ms,
            frame_id=stereo.frame_id,
            stage=self.stage,
            phase=phase,
            det_count=det_count,
            depth_valid_ratio=depth_valid_ratio,
            fps=fps,
            pose_4x4=pose_4x4,
            timing=timing,
            debug=debug_data,
        )

        self._log_stats_if_due(output)
        return output


# =========================
# 参数与构建函数
# =========================


def build_arg_parser() -> argparse.ArgumentParser:
    """构建脚本入口级参数解析器，只负责选择/打印运行配置。"""
    parser = argparse.ArgumentParser(description="Quest 位姿 Pipeline（TOML 配置版）")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="运行配置 TOML 路径；默认读取 config/runtime.toml。",
    )
    parser.add_argument(
        "--print_config",
        action="store_true",
        help="打印解析并完成路径展开后的有效配置，然后退出。",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析入口级命令行参数。"""
    return build_arg_parser().parse_args(argv)


def _load_cached_calib(cfg: SimpleNamespace) -> QuestStereoCalibration | None:
    """尝试从本地 camera_info 缓存加载标定。"""
    import json as _json
    import msgpack as _msgpack
    from zmq_utils.payload.message.quest_camera_info_msg import QuestCameraInfoMsg

    cache_dir = Path(cfg.pipeline.calibration.camera_cache_dir)
    latest_path = cache_dir / "camera_info_latest.json"
    if not latest_path.is_file():
        return None

    try:
        with latest_path.open("r", encoding="utf-8") as f:
            data = _json.load(f)
        # 将 JSON dict 重新序列化为 msgpack 再反序列化，确保字段完整。
        payload = _msgpack.packb(data, use_bin_type=True)
        msg = QuestCameraInfoMsg.deserialize(payload)
        if msg is not None:
            return QuestStereoCalibration.from_camera_info_msg(msg)
    except Exception as exc:
        logging.warning("[pipeline] 读取 camera_info_latest.json 失败: %s", exc)

    return None


def build_quest_object_tracking_pipeline(cfg: SimpleNamespace) -> QuestObjectTrackingPipeline:
    """构建 Quest object tracking pipeline 对象（API 工厂函数）。"""
    # 校验模型文件（仅校验始终需要的）。
    model_paths = [
        cfg.module.ffs.model_path,
        cfg.module.foundationpose.mesh_path,
    ]
    if str(cfg.module.segmenter.type).lower() == "sam3":
        model_paths.append(cfg.module.sam3.checkpoint_path)
    else:
        model_paths.extend([cfg.module.yoloe.model_path, cfg.module.yoloe.mobileclip2_path])
    for path in model_paths:
        if not Path(path).exists():
            raise FileNotFoundError(f"必要文件不存在: {path}")

    # 标定预加载策略：
    # - local：优先用本地 camera_info 缓存初始化；失败后仍可等待网络 camera_info。
    # - network + preload_camera_cache=1：先用本地缓存快速初始化 FoundationPose，
    #   后续收到网络 camera_info 后会按 network_calib_update 策略校验/刷新。
    calib: QuestStereoCalibration | None = None
    should_preload_cached_calib = cfg.pipeline.calibration.camera_source == "local" or bool(
        cfg.pipeline.calibration.preload_camera_cache
    )
    if should_preload_cached_calib:
        calib = _load_cached_calib(cfg)
        if calib is None and cfg.pipeline.calibration.camera_source == "local":
            logging.warning(
                "[pipeline] camera_source=local 但未找到本地 camera_info 缓存，将等待网络 camera_info"
            )
        elif calib is not None and cfg.pipeline.calibration.camera_source == "network":
            logging.info(
                "[pipeline] 已从本地 camera_info 缓存预初始化标定；等待网络 camera_info 后校验"
            )

    camera = QuestReceiver(
        listen_host=str(cfg.network.receiver.listen_host),
        listen_port=int(cfg.network.receiver.listen_port),
        hwm=int(cfg.network.receiver.hwm),
        timeout_ms=int(cfg.network.receiver.timeout_ms),
    )

    if str(cfg.module.segmenter.type).lower() == "sam3":
        sam3_kwargs = {
            "checkpoint_path": cfg.module.sam3.checkpoint_path,
            "prompt": str(cfg.module.segmenter.prompt),
            "confidence_threshold": float(cfg.module.sam3.confidence_threshold),
            "mask_threshold": float(cfg.module.segmenter.mask_threshold),
            "max_det": int(cfg.module.segmenter.max_det),
            "device": str(cfg.module.sam3.device),
            "resolution": int(cfg.module.sam3.resolution),
            "sam3_root": PROJECT_DIR / "sam3",
        }
        segmenter = (
            AsyncSam3Masker(
                masker_kwargs=sam3_kwargs,
                min_interval_sec=float(cfg.module.sam3.interval_sec),
            )
            if bool(cfg.module.sam3.async_enabled)
            else Sam3Masker(**sam3_kwargs)
        )
    else:
        yoloe_device = str(cfg.module.yoloe.device).strip()
        if yoloe_device.lower() == "auto":
            yoloe_device_value = None
        else:
            yoloe_device_value = int(yoloe_device) if yoloe_device.isdigit() else yoloe_device
        segmenter = Yoloe26Masker(
            model_path=str(cfg.module.yoloe.model_path),
            init_prompt=str(cfg.module.segmenter.prompt),
            conf=float(cfg.module.yoloe.conf),
            imgsz=int(cfg.module.yoloe.imgsz),
            max_det=int(cfg.module.segmenter.max_det),
            mask_threshold=float(cfg.module.segmenter.mask_threshold),
            use_half=bool(cfg.module.yoloe.use_half),
            device=yoloe_device_value,
            mobileclip2_path=str(cfg.module.yoloe.mobileclip2_path),
        )

    ffs = FastFoundationStereoRealtime(
        model_dir=str(cfg.module.ffs.model_path),
        device=str(cfg.module.ffs.device),
        scale=float(cfg.module.ffs.scale),
        valid_iters=int(cfg.module.ffs.valid_iters),
        max_disp=int(cfg.module.ffs.max_disp),
        optimize_build_volume=str(cfg.module.ffs.optimize_build_volume),
        seed=int(cfg.module.ffs.seed),
        cudnn_benchmark=bool(cfg.module.ffs.cudnn_benchmark),
        use_trt=bool(cfg.module.ffs.use_trt),
        trt_precision=str(cfg.module.ffs.trt_precision),
        trt_strict=bool(cfg.module.ffs.trt_strict),
        trt_tag=str(cfg.module.ffs.trt_tag),
        trt_platform_tag=str(cfg.module.ffs.trt_platform_tag),
        trt_feature_engine_path=str(cfg.module.ffs.trt_feature_engine_path),
        trt_post_engine_path=str(cfg.module.ffs.trt_post_engine_path),
    )

    use_2d_tracker = bool(cfg.module.cutie.enabled)
    cutie_tracker = (
        CutieTracker(seg_threshold=float(cfg.module.cutie.seg_threshold), erosion_size=int(cfg.module.cutie.erosion_size))
        if use_2d_tracker
        else None
    )

    return QuestObjectTrackingPipeline(
        cfg=cfg,
        camera=camera,
        segmenter=segmenter,
        ffs=ffs,
        cutie_tracker=cutie_tracker,
        calib=calib,
    )


def run_quest_object_tracking_pipeline(cfg: SimpleNamespace) -> None:
    """示例运行函数：循环调用 API，并在这里展示图像。"""
    pipeline = build_quest_object_tracking_pipeline(cfg)
    pipeline.set_stage(int(cfg.server.run_stage))
    pipeline.start()

    cv2.namedWindow("Quest Debug", cv2.WINDOW_AUTOSIZE)
    cv2.namedWindow("Quest Stereo", cv2.WINDOW_AUTOSIZE)

    try:
        logging.info("按 1/2/3/4 切阶段，按 r 重置，按 q/ESC 退出")

        while True:
            output = pipeline.run(return_debug=True)
            if output is None:
                continue

            if output.debug is not None:
                dashboard_bgr, stereo_bgr = output.debug
                cv2.imshow("Quest Debug", dashboard_bgr)
                cv2.imshow("Quest Stereo", stereo_bgr)

            if output.pose_4x4 is not None:
                t = output.pose_4x4[:3, 3]
                logging.debug(
                    "[pose] phase=%s xyz=(%.4f, %.4f, %.4f)",
                    output.phase,
                    float(t[0]),
                    float(t[1]),
                    float(t[2]),
                )

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            if key in (ord("1"), ord("2"), ord("3"), ord("4")):
                pipeline.set_stage(int(chr(key)))
                logging.info("[pipeline] switch stage -> %d", pipeline.stage)
            if key == ord("r"):
                pipeline.reset_tracking_state()
                logging.info("[pipeline] reset -> 等待重新检测")

    except KeyboardInterrupt:
        logging.info("\n[pipeline] 用户中断")
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()


def main(argv: list[str] | None = None) -> None:
    """脚本入口。"""
    cli_args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_runtime_config(cli_args.config)
    if cli_args.print_config:
        print_effective_config(cfg)
        return
    run_quest_object_tracking_pipeline(cfg)


if __name__ == "__main__":
    main()
