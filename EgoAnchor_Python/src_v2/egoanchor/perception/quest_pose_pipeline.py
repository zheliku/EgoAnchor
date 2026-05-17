"""v2 Quest pose pipeline。

职责边界：
- 输入：已由 transport 层缓存的 `QuestStereoFrame` / `QuestCameraInfo` Protobuf。
- 输出：相机坐标系 object pose 观测 `PoseObservation`，以及可选 OpenCV debug 图像。
- 不做：ZMQ/NATS 收发、Unity world transform、anchor runtime/filter/state machine。

本实现复刻旧主线的稳定 pose 估计顺序：
YOLOE-26 mask -> Fast-FoundationStereo depth -> FoundationPose register/track/re-register，
并把算法适配器放到 plan.md 约定的 `algorithms/` 层。
"""

from __future__ import annotations

import itertools
import logging
import time
from dataclasses import dataclass
from types import SimpleNamespace

import cv2
import numpy as np

from egoanchor.algorithms import MaskTracker2D, ObjectPoseEstimator, ObjectSegmenter, SegmenterResult, StereoDepthEstimator
from egoanchor.diagnostics import colorize_depth, draw_hud, overlay_mask_contour, stack_stereo, tile_pose_depth_dashboard
from egoanchor.perception.pose_observation import PoseObservation
from egoanchor.perception.quest_calibration import QuestStereoCalibration
from egoanchor.perception.quest_frame import decode_quest_stereo_frame, preprocess_stereo_pair
from egoanchor.protocol.v1 import quest_pb2
from egoanchor.reliability import score_observation


@dataclass(slots=True)
class PipelineStepTiming:
    """单帧分阶段耗时，单位毫秒。"""

    yolo_ms: float = 0.0
    depth_ms: float = 0.0
    cutie_ms: float = 0.0
    pose_ms: float = 0.0


@dataclass(slots=True)
class FrameDiagnostics:
    """mask/depth/track 相关诊断指标。"""

    mask_area_ratio: float = 0.0
    depth_valid_in_mask: float = 0.0
    depth_median_in_mask: float = 0.0
    depth_iqr_in_mask: float = 0.0
    segmenter_selected_index: int = -1
    cutie_adjust_applied: bool = False


@dataclass(slots=True)
class QuestPosePipelineOutput:
    """QuestPosePipeline 单帧输出。"""

    observation: PoseObservation
    timing: PipelineStepTiming
    debug: tuple[np.ndarray, np.ndarray] | None = None


class QuestPosePipeline:
    """Quest stereo + calibration -> camera-space pose observation。"""

    def __init__(
        self,
        cfg: SimpleNamespace,
        segmenter: ObjectSegmenter,
        depth_estimator: StereoDepthEstimator,
        cutie_tracker: MaskTracker2D | None = None,
        initial_calibration: QuestStereoCalibration | None = None,
    ) -> None:
        self.cfg = cfg
        self.segmenter = segmenter
        self.depth_estimator = depth_estimator
        self.cutie_tracker = cutie_tracker

        self.stage = int(cfg.server.run_stage)
        self.min_depth = float(cfg.pipeline.depth.min_depth)
        self.max_depth = float(cfg.pipeline.depth.max_depth)
        self.stats_interval = max(int(cfg.debug.pipeline_stats_interval), 1)

        self.calib: QuestStereoCalibration | None = None
        self.cam_k: np.ndarray | None = None
        self.fx = 0.0
        self.frame_w = 0
        self.frame_h = 0
        self.pose_estimator: ObjectPoseEstimator | None = None
        self.symmetry_tfs = _generate_cube_symmetry_tfs() if str(cfg.module.foundationpose.symmetry_mode).lower() == "cube" else None

        self._calib_signature: tuple[float, ...] | None = None
        self._has_pose = False
        self._cutie_initialized = False
        self._last_pose_4x4: np.ndarray | None = None
        self._last_processed_frame_id: int | None = None
        self._track_reject_count = 0
        self._frame_count = 0
        self._last_frame_t = 0.0
        self._fps_ema = 0.0
        self._stats_t = time.perf_counter()
        self._seg_acc = 0.0
        self._depth_acc = 0.0
        self._cutie_acc = 0.0
        self._pose_acc = 0.0
        self._mask_snapshot_shown = False

        if initial_calibration is not None:
            self._init_from_calibration(initial_calibration)

    def set_stage(self, stage: int) -> None:
        """切换 debug 阶段：1=输入，2=mask，3=depth，4=pose。"""

        stage_int = int(stage)
        if stage_int < 1 or stage_int > 4:
            raise ValueError(f"stage 必须在 1..4 之间，当前: {stage_int}")
        if stage_int != self.stage:
            self.stage = stage_int
            self.reset_tracking_state()

    def reset_tracking_state(self) -> None:
        """仅重置 6D pose 和 Cutie 时序状态，不重置模型权重。"""

        self._has_pose = False
        self._cutie_initialized = False
        self._last_pose_4x4 = None
        self._track_reject_count = 0
        self._mask_snapshot_shown = False
        if self.pose_estimator is not None:
            self.pose_estimator.reset()
        if self.cutie_tracker is not None:
            try:
                self.cutie_tracker.reset()
            except Exception as exc:
                logging.warning("[Cutie] reset 失败: %s", exc)

    def process(
        self,
        stereo_msg: quest_pb2.QuestStereoFrame | None,
        camera_info_msg: quest_pb2.QuestCameraInfo | None,
        return_debug: bool = False,
    ) -> QuestPosePipelineOutput | None:
        """处理一帧 Quest 输入。

        若缺少 camera_info、无新 stereo、JPEG 解码失败或重复 frame_id，则返回 None，
        上层 demo/runtime 可继续 poll 下一帧。
        """

        if camera_info_msg is not None:
            self._refresh_calibration_if_needed(camera_info_msg)
        if self.calib is None or stereo_msg is None:
            return None

        decoded = decode_quest_stereo_frame(stereo_msg)
        if decoded is None:
            logging.warning("[QuestPosePipeline] stereo JPEG 解码失败。")
            return None
        if decoded.frame_id is not None and decoded.frame_id == self._last_processed_frame_id:
            return None
        self._last_processed_frame_id = decoded.frame_id

        left_bgr, right_bgr = preprocess_stereo_pair(decoded.left_bgr, decoded.right_bgr, self.frame_w, self.frame_h)
        left_rgb = cv2.cvtColor(left_bgr, cv2.COLOR_BGR2RGB)

        timing = PipelineStepTiming()
        diag = FrameDiagnostics()
        phase = "STAGE1_CAMERA"
        det_count = 0
        pose_4x4: np.ndarray | None = None
        mask_bw = np.zeros(left_bgr.shape[:2], dtype=np.uint8)
        depth_m = np.zeros(left_bgr.shape[:2], dtype=np.float32)
        vis_bgr = left_bgr.copy()
        cutie_mask: np.ndarray | None = None
        cutie_bbox = [-1, -1, 0, 0]

        if self.stage >= 2:
            t0 = time.perf_counter()
            segmenter_result = self.segmenter.infer(left_bgr)
            timing.yolo_ms = (time.perf_counter() - t0) * 1000.0
            self._seg_acc += timing.yolo_ms
            det_count, mask_bw, vis_bgr, diag = self._consume_segmenter_result(segmenter_result, left_bgr, diag)
            phase = "STAGE2_SEGMENT"

        if self.stage >= 3:
            depth_m, depth_ms = self._predict_depth(left_bgr, right_bgr)
            timing.depth_ms = depth_ms
            self._depth_acc += timing.depth_ms
            diag = self._compute_frame_diagnostics(mask_bw, depth_m, diag.segmenter_selected_index)
            phase = "STAGE3_FFS"

        if self.stage >= 4:
            if self.pose_estimator is None:
                raise RuntimeError("pose_estimator 尚未初始化，请先提供有效 camera_info。")
            pose_begin = time.perf_counter()
            if not self._has_pose:
                pose_4x4, phase = self._try_register(left_rgb, depth_m, mask_bw, det_count, diag, timing)
                if pose_4x4 is not None:
                    vis_bgr = cv2.cvtColor(self.pose_estimator.visualize_pose(left_rgb, pose_4x4), cv2.COLOR_RGB2BGR)
            else:
                cutie_mask, cutie_bbox = self._run_cutie_on_current_frame(left_rgb, mask_bw, det_count, diag, timing, allow_reinit=True, adjust_pose=True)
                pose_4x4, phase = self._try_track_or_recover(left_rgb, depth_m, cutie_mask if cutie_mask is not None else mask_bw, diag, timing)
                if pose_4x4 is not None:
                    vis_bgr = cv2.cvtColor(self.pose_estimator.visualize_pose(left_rgb, pose_4x4), cv2.COLOR_RGB2BGR)
                    if cutie_mask is not None:
                        mask_bw = (cutie_mask > 0).astype(np.uint8) * 255
                        diag = self._compute_frame_diagnostics(mask_bw, depth_m, diag.segmenter_selected_index)
                    if cutie_bbox[2] > 0 and cutie_bbox[3] > 0:
                        x, y, bw, bh = cutie_bbox
                        cv2.rectangle(vis_bgr, (int(x), int(y)), (int(x + bw), int(y + bh)), (0, 255, 255), 2)
            timing.pose_ms = (time.perf_counter() - pose_begin) * 1000.0
            self._pose_acc += timing.pose_ms
            self._cutie_acc += timing.cutie_ms

        fps = self._update_fps()
        depth_valid_ratio = float((depth_m > 0).mean()) if self.stage >= 3 else 0.0
        observation = self._make_observation(decoded.frame_id, phase, det_count, pose_4x4, fps, depth_valid_ratio, diag, timing)
        self._log_stats_if_due(observation)

        debug_data = None
        if return_debug:
            debug_data = self._make_debug_views(left_bgr, right_bgr, vis_bgr, depth_m, mask_bw, observation, timing, diag)
        return QuestPosePipelineOutput(observation=observation, timing=timing, debug=debug_data)

    def _refresh_calibration_if_needed(self, msg: quest_pb2.QuestCameraInfo) -> None:
        """首次或 camera_info 变化时初始化/刷新 K 与 FoundationPose。"""

        calib = QuestStereoCalibration.from_proto(msg)
        signature = calib.signature()
        if self._calib_signature == signature:
            return
        if self._calib_signature is not None and not bool(self.cfg.pipeline.calibration.network_calib_update):
            return
        logging.info("[QuestCalib:v2] camera_info updated: fx=%.2f fy=%.2f baseline=%.6fm calib=%dx%d", calib.left_fx, calib.left_fy, calib.baseline_m, calib.calib_width, calib.calib_height)
        self._init_from_calibration(calib)
        self.reset_tracking_state()

    def _init_from_calibration(self, calib: QuestStereoCalibration) -> None:
        """根据 Quest 标定初始化算法处理尺寸、K 和 FoundationPose。"""

        self.calib = calib
        self._calib_signature = calib.signature()
        self.frame_w = max(int(self.cfg.pipeline.calibration.process_width), 0) or int(calib.calib_width)
        self.frame_h = max(int(self.cfg.pipeline.calibration.process_height), 0) or int(calib.calib_height)
        self.cam_k = calib.scaled_k(self.frame_w, self.frame_h, bool(self.cfg.pipeline.calibration.assume_center_crop))
        self.fx = float(self.cam_k[0, 0])
        logging.info(
            "[KMap:v2] mode=%s fx=%.2f fy=%.2f cx=%.2f cy=%.2f frame=%dx%d",
            "center-crop+scale" if bool(self.cfg.pipeline.calibration.assume_center_crop) else "linear-scale-only",
            float(self.cam_k[0, 0]),
            float(self.cam_k[1, 1]),
            float(self.cam_k[0, 2]),
            float(self.cam_k[1, 2]),
            self.frame_w,
            self.frame_h,
        )
        from egoanchor.algorithms.foundationpose_estimator import FoundationPoseObjectEstimator

        self.pose_estimator = FoundationPoseObjectEstimator(
            mesh_path=self.cfg.module.foundationpose.mesh_path,
            cam_k=self.cam_k,
            est_refine_iter=int(self.cfg.module.foundationpose.est_refine_iter),
            track_refine_iter=int(self.cfg.module.foundationpose.track_refine_iter),
            symmetry_tfs=self.symmetry_tfs,
            debug=int(self.cfg.module.foundationpose.debug),
            debug_dir=str(self.cfg.module.foundationpose.debug_dir) if self.cfg.module.foundationpose.debug_dir else None,
            project_root=self.cfg.paths.python_root,
        )

    def _consume_segmenter_result(
        self,
        result: SegmenterResult,
        left_bgr: np.ndarray,
        diag: FrameDiagnostics,
    ) -> tuple[int, np.ndarray, np.ndarray, FrameDiagnostics]:
        """整理分割结果：尺寸对齐、诊断记录、mask snapshot。"""

        det_count = int(result.det_count)
        mask_bw = result.mask_bw
        if mask_bw.shape[:2] != left_bgr.shape[:2]:
            logging.warning("[segmenter:v2] mask 尺寸与图像不一致 mask=%s image=%s，已缩放。", mask_bw.shape[:2], left_bgr.shape[:2])
            mask_bw = cv2.resize(mask_bw, (left_bgr.shape[1], left_bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
        diag.segmenter_selected_index = int(result.selected_index)
        diag.mask_area_ratio = float(result.mask_area_ratio)
        self._show_mask_snapshot_once(left_bgr, mask_bw, det_count, diag.segmenter_selected_index)
        return det_count, mask_bw, result.overlay_bgr.copy(), diag

    def _predict_depth(self, left_bgr: np.ndarray, right_bgr: np.ndarray) -> tuple[np.ndarray, float]:
        """运行 FFS 并做深度范围裁剪。"""

        if self.calib is None:
            raise RuntimeError("缺少 Quest 标定，无法预测深度。")
        t0 = time.perf_counter()
        depth = self.depth_estimator.predict_depth(left_bgr, right_bgr, fx=self.fx, baseline=float(self.calib.baseline_m))
        depth_ms = (time.perf_counter() - t0) * 1000.0
        depth_m = np.asarray(depth, dtype=np.float32)
        if depth_m.shape[:2] != left_bgr.shape[:2]:
            logging.warning("[FFS:v2] depth 尺寸与图像不一致 depth=%s image=%s，已缩放。", depth_m.shape[:2], left_bgr.shape[:2])
            depth_m = cv2.resize(depth_m, (left_bgr.shape[1], left_bgr.shape[0]), interpolation=cv2.INTER_LINEAR)
        invalid = (depth_m < self.min_depth) | (depth_m > self.max_depth) | (~np.isfinite(depth_m))
        depth_m[invalid] = 0.0
        return depth_m, depth_ms

    def _compute_frame_diagnostics(self, mask_bw: np.ndarray, depth_m: np.ndarray, segmenter_selected_index: int = -1) -> FrameDiagnostics:
        """计算 mask/depth 对齐诊断。"""

        diag = FrameDiagnostics(segmenter_selected_index=int(segmenter_selected_index))
        if mask_bw is None or mask_bw.size == 0:
            return diag
        mask = mask_bw > 0
        diag.mask_area_ratio = float(mask.mean())
        if not np.any(mask) or depth_m is None or depth_m.size == 0 or depth_m.shape[:2] != mask.shape[:2]:
            return diag
        values = np.asarray(depth_m, dtype=np.float32)[mask]
        valid = values[np.isfinite(values) & (values > 0.0)]
        diag.depth_valid_in_mask = float(valid.size) / float(max(values.size, 1))
        if valid.size > 0:
            q25, q50, q75 = np.percentile(valid, [25, 50, 75])
            diag.depth_median_in_mask = float(q50)
            diag.depth_iqr_in_mask = float(q75 - q25)
        return diag

    def _is_pose_valid(self, pose_4x4: np.ndarray | None) -> bool:
        """基础 pose 合法性过滤。"""

        if pose_4x4 is None:
            return False
        pose = np.asarray(pose_4x4)
        if pose.shape != (4, 4) or not np.isfinite(pose).all():
            return False
        z = float(pose[2, 3])
        return self.min_depth <= z <= self.max_depth

    def _is_track_jump(self, pose_4x4: np.ndarray) -> bool:
        """检测 FoundationPose track 的明显跳变。"""

        if self._last_pose_4x4 is None:
            return False
        trans_delta = float(np.linalg.norm(pose_4x4[:3, 3] - self._last_pose_4x4[:3, 3]))
        rel = pose_4x4[:3, :3] @ self._last_pose_4x4[:3, :3].T
        rot_delta = float(np.degrees(np.arccos(np.clip((float(np.trace(rel)) - 1.0) * 0.5, -1.0, 1.0))))
        return trans_delta > float(self.cfg.module.foundationpose.pose_jump_translation_m) or rot_delta > float(self.cfg.module.foundationpose.pose_jump_rotation_deg)

    def _try_register(
        self,
        left_rgb: np.ndarray,
        depth_m: np.ndarray,
        mask_bw: np.ndarray,
        det_count: int,
        diag: FrameDiagnostics,
        timing: PipelineStepTiming,
    ) -> tuple[np.ndarray | None, str]:
        """尝试首帧 register。"""

        assert self.pose_estimator is not None
        has_valid_mask = det_count > 0 and np.count_nonzero(mask_bw) > 0
        if not has_valid_mask:
            return None, "WAIT_DETECT"
        if diag.depth_valid_in_mask < float(self.cfg.module.foundationpose.register_min_depth_valid_in_mask):
            return None, "REJECT_DEPTH"
        try:
            pose_4x4 = self.pose_estimator.register(left_rgb, depth_m, mask_bw)
            pose_4x4 = np.asarray(pose_4x4, dtype=np.float64).reshape(4, 4)
        except Exception as exc:
            logging.warning("[FoundationPose:v2] register 失败: %s", exc)
            self.pose_estimator.reset()
            return None, "REJECT_POSE"
        if not self._is_pose_valid(pose_4x4):
            logging.warning("[FoundationPose:v2] register 输出非法或 z 越界。")
            self.pose_estimator.reset()
            return None, "REJECT_POSE"

        self._has_pose = True
        self._track_reject_count = 0
        self._last_pose_4x4 = pose_4x4.copy()
        self._initialize_cutie_if_enabled(left_rgb, mask_bw, timing)
        return pose_4x4, "REGISTER"

    def _try_track_or_recover(
        self,
        left_rgb: np.ndarray,
        depth_m: np.ndarray,
        current_mask_bw: np.ndarray,
        diag: FrameDiagnostics,
        timing: PipelineStepTiming,
    ) -> tuple[np.ndarray | None, str]:
        """尝试 track；失败/跳变时按配置 re-register。"""

        assert self.pose_estimator is not None
        phase = "REJECT_POSE"
        try:
            pose_4x4 = self.pose_estimator.track(left_rgb, depth_m)
            pose_4x4 = np.asarray(pose_4x4, dtype=np.float64).reshape(4, 4)
        except Exception as exc:
            logging.warning("[FoundationPose:v2] track 失败: %s", exc)
            pose_4x4 = None
            self._track_reject_count += 1
            self._has_pose = False
            self.pose_estimator.reset()
            phase = "REJECT_POSE"
        else:
            if not self._is_pose_valid(pose_4x4):
                logging.warning("[FoundationPose:v2] track 输出非法或 z 越界。")
                pose_4x4 = None
                self._track_reject_count += 1
                self._has_pose = False
                self.pose_estimator.reset()
                phase = "REJECT_POSE"
            elif self._is_track_jump(pose_4x4):
                self._track_reject_count += 1
                logging.warning("[FoundationPose:v2] track pose 跳变，尝试 re-register (reject=%d)。", self._track_reject_count)
                pose_4x4 = None
                self._has_pose = False
                self.pose_estimator.reset()
                phase = "REJECT_JUMP"
            else:
                self._track_reject_count = 0
                self._last_pose_4x4 = pose_4x4.copy()
                return pose_4x4, "TRACK"

        recovered = self._try_recover_by_register(left_rgb, depth_m, current_mask_bw, timing)
        if recovered is not None:
            return recovered, "RE_REGISTER"
        return None, phase

    def _try_recover_by_register(self, left_rgb: np.ndarray, depth_m: np.ndarray, mask_bw: np.ndarray, timing: PipelineStepTiming) -> np.ndarray | None:
        """track 丢失时用当前 2D mask 重新 register。"""

        assert self.pose_estimator is not None
        if not bool(self.cfg.module.foundationpose.re_register_on_track_lost):
            return None
        if np.count_nonzero(mask_bw) <= 0:
            return None
        diag = self._compute_frame_diagnostics(mask_bw, depth_m)
        if diag.depth_valid_in_mask < float(self.cfg.module.foundationpose.register_min_depth_valid_in_mask):
            return None
        begin = time.perf_counter()
        try:
            self.pose_estimator.reset()
            pose_4x4 = self.pose_estimator.register(left_rgb, depth_m, mask_bw)
            pose_4x4 = np.asarray(pose_4x4, dtype=np.float64).reshape(4, 4)
        except Exception as exc:
            logging.warning("[FoundationPose:v2] re-register 失败: %s", exc)
            self.pose_estimator.reset()
            return None
        finally:
            timing.pose_ms += (time.perf_counter() - begin) * 1000.0
        if not self._is_pose_valid(pose_4x4):
            self.pose_estimator.reset()
            return None
        self._has_pose = True
        self._track_reject_count = 0
        self._last_pose_4x4 = pose_4x4.copy()
        self._initialize_cutie_if_enabled(left_rgb, mask_bw, timing)
        return pose_4x4

    def _initialize_cutie_if_enabled(self, left_rgb: np.ndarray, mask_bw: np.ndarray, timing: PipelineStepTiming) -> None:
        """register/re-register 成功后，用当前 mask 初始化 Cutie。"""

        if self.cutie_tracker is None or np.count_nonzero(mask_bw) <= 0:
            return
        begin = time.perf_counter()
        try:
            self.cutie_tracker.initialize(left_rgb, init_mask=mask_bw)
            self._cutie_initialized = True
        except Exception as exc:
            self._cutie_initialized = False
            logging.warning("[Cutie:v2] 初始化失败: %s", exc)
        finally:
            timing.cutie_ms += (time.perf_counter() - begin) * 1000.0

    def _run_cutie_on_current_frame(
        self,
        left_rgb: np.ndarray,
        mask_bw: np.ndarray,
        det_count: int,
        diag: FrameDiagnostics,
        timing: PipelineStepTiming,
        allow_reinit: bool,
        adjust_pose: bool,
    ) -> tuple[np.ndarray | None, list[int]]:
        """传播 Cutie mask，并可用 bbox 中心辅助修正 pose_last。"""

        cutie_bbox = [-1, -1, 0, 0]
        if self.cutie_tracker is None or not self._cutie_initialized:
            return None, cutie_bbox
        begin = time.perf_counter()
        cutie_mask: np.ndarray | None = None
        try:
            result = self.cutie_tracker.track(left_rgb)
            cutie_bbox = result.bbox_xywh
            cutie_mask = (result.mask > 0).astype(np.uint8) * 255
            x, y, bw, bh = cutie_bbox
            if bw > 0 and bh > 0 and adjust_pose and bool(self.cfg.module.cutie.adjust_pose) and self.pose_estimator is not None:
                self.pose_estimator.adjust_pose_to_image_point(float(x + bw / 2.0), float(y + bh / 2.0))
                diag.cutie_adjust_applied = True
            elif allow_reinit and det_count > 0 and np.count_nonzero(mask_bw) > 0:
                self.cutie_tracker.initialize(left_rgb, init_mask=mask_bw)
                self._cutie_initialized = True
        except Exception as exc:
            logging.warning("[Cutie:v2] 跟踪失败: %s", exc)
            self._cutie_initialized = False
            cutie_mask = None
        finally:
            timing.cutie_ms += (time.perf_counter() - begin) * 1000.0
        return cutie_mask, cutie_bbox

    def _make_observation(
        self,
        frame_id: int | None,
        phase: str,
        det_count: int,
        pose_4x4: np.ndarray | None,
        fps: float,
        depth_valid_ratio: float,
        diag: FrameDiagnostics,
        timing: PipelineStepTiming,
    ) -> PoseObservation:
        """把 pipeline 内部结果转换为 `PoseObservation`。"""

        has_pose = pose_4x4 is not None
        matrix_tuple = tuple(float(x) for x in np.asarray(pose_4x4, dtype=np.float64).reshape(-1)) if has_pose else None
        obs = PoseObservation(
            has_pose=has_pose,
            phase=phase,
            frame_id=frame_id,
            pose_matrix_cv_camera=matrix_tuple,
            stage=self.stage,
            det_count=int(det_count),
            fps=float(fps),
            depth_valid_ratio=float(depth_valid_ratio),
            depth_valid_in_mask=float(diag.depth_valid_in_mask),
            depth_median_in_mask=float(diag.depth_median_in_mask),
            depth_iqr_in_mask=float(diag.depth_iqr_in_mask),
            mask_area_ratio=float(diag.mask_area_ratio),
            track_reject_count=int(self._track_reject_count),
            yolo_ms=float(timing.yolo_ms),
            depth_ms=float(timing.depth_ms),
            cutie_ms=float(timing.cutie_ms),
            pose_ms=float(timing.pose_ms),
            reliability_score=0.0,
        )
        return PoseObservation(**{**obs.__dict__, "reliability_score": score_observation(obs)})

    def _make_debug_views(
        self,
        left_bgr: np.ndarray,
        right_bgr: np.ndarray,
        vis_bgr: np.ndarray,
        depth_m: np.ndarray,
        mask_bw: np.ndarray,
        observation: PoseObservation,
        timing: PipelineStepTiming,
        diag: FrameDiagnostics,
    ) -> tuple[np.ndarray, np.ndarray]:
        """生成主 debug dashboard 与 stereo 窗口图。"""

        depth_vis = colorize_depth(depth_m, self.min_depth, self.max_depth)
        depth_mask = overlay_mask_contour(depth_vis, mask_bw, (0, 255, 255))
        pose_panel = overlay_mask_contour(vis_bgr, mask_bw, (0, 255, 255)) if observation.phase in {"WAIT_DETECT", "REJECT_DEPTH", "STAGE2_SEGMENT", "STAGE3_FFS"} else vis_bgr.copy()
        draw_hud(
            pose_panel,
            [
                f"fps={observation.fps:.1f} stage={self.stage} {observation.phase} det={observation.det_count} rel={observation.reliability_score:.2f}",
                f"ms seg/d/c/p={timing.yolo_ms:.0f}/{timing.depth_ms:.0f}/{timing.cutie_ms:.0f}/{timing.pose_ms:.0f}",
                f"depth={observation.depth_valid_ratio:.0%} in_mask={diag.depth_valid_in_mask:.0%} med={diag.depth_median_in_mask:.2f}m iqr={diag.depth_iqr_in_mask:.2f}",
                f"mask={diag.mask_area_ratio:.1%} reject={self._track_reject_count} cutie_adjust={diag.cutie_adjust_applied}",
            ],
        )
        dashboard = tile_pose_depth_dashboard(pose_panel, depth_mask)
        stereo = stack_stereo(left_bgr, right_bgr)
        draw_hud(stereo, f"STEREO frame_id={observation.frame_id}", x=8, y=22)
        return dashboard, stereo

    def _show_mask_snapshot_once(self, image_bgr: np.ndarray, mask_bw: np.ndarray, det_count: int, selected_index: int) -> None:
        """首次检测到有效 mask 时显示一次 RGB/mask/overlay 对齐快照。"""

        if self._mask_snapshot_shown or not bool(self.cfg.debug.show_mask_snapshot) or det_count <= 0 or np.count_nonzero(mask_bw) <= 0:
            return
        mask = (mask_bw > 0).astype(np.uint8)
        mask_panel = cv2.cvtColor(mask * 255, cv2.COLOR_GRAY2BGR)
        overlay_panel = overlay_mask_contour(image_bgr, mask * 255, (0, 255, 255))
        rgb_panel = image_bgr.copy()
        draw_hud(rgb_panel, "RGB frame", x=8, y=22)
        draw_hud(mask_panel, "Mask", x=8, y=22)
        draw_hud(overlay_panel, ["RGB + mask", f"det={det_count} selected={selected_index} area={mask.mean():.1%}"], x=8, y=22)
        snapshot = np.hstack((rgb_panel, mask_panel, overlay_panel))
        window_name = str(self.cfg.debug.mask_snapshot_window)
        cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
        cv2.imshow(window_name, snapshot)
        cv2.waitKey(1)
        self._mask_snapshot_shown = True

    def _update_fps(self) -> float:
        """更新实时 FPS EMA。"""

        now = time.perf_counter()
        self._frame_count += 1
        if self._last_frame_t > 0.0:
            dt = max(now - self._last_frame_t, 1e-6)
            inst = 1.0 / dt
            self._fps_ema = inst if self._fps_ema <= 0.0 else self._fps_ema * 0.85 + inst * 0.15
        self._last_frame_t = now
        return self._fps_ema if self._fps_ema > 0.0 else 0.0

    def _log_stats_if_due(self, observation: PoseObservation) -> None:
        """按固定帧间隔打印性能统计。"""

        if self._frame_count % self.stats_interval != 0:
            return
        now = time.perf_counter()
        interval = max(now - self._stats_t, 1e-6)
        window_fps = self.stats_interval / interval
        logging.info(
            "[PosePipeline:v2] frames=%d stage=%d phase=%s fps=%.1f window_fps=%.1f avg(seg/depth/cutie/pose)=%.1f/%.1f/%.1f/%.1fms depth=%.1f%% in_mask=%.1f%% rel=%.2f",
            self._frame_count,
            self.stage,
            observation.phase,
            observation.fps,
            window_fps,
            self._seg_acc / self.stats_interval,
            self._depth_acc / self.stats_interval,
            self._cutie_acc / self.stats_interval,
            self._pose_acc / self.stats_interval,
            observation.depth_valid_ratio * 100.0,
            observation.depth_valid_in_mask * 100.0,
            observation.reliability_score,
        )
        self._stats_t = now
        self._seg_acc = 0.0
        self._depth_acc = 0.0
        self._cutie_acc = 0.0
        self._pose_acc = 0.0


def _generate_cube_symmetry_tfs() -> np.ndarray:
    """生成立方体 24 个旋转对称变换，用于 FoundationPose 对称约束。"""

    def permutation_parity(perm: tuple[int, int, int]) -> float:
        """3 元排列的奇偶性；避免调用 numpy.linalg.det 触发 Windows DLL 问题。"""

        inversions = 0
        for i in range(len(perm)):
            for j in range(i + 1, len(perm)):
                if perm[i] > perm[j]:
                    inversions += 1
        return -1.0 if inversions % 2 else 1.0

    mats: list[np.ndarray] = []
    seen: set[tuple[float, ...]] = set()
    for perm in itertools.permutations([0, 1, 2]):
        for signs in itertools.product([-1.0, 1.0], repeat=3):
            det_sign = permutation_parity(perm) * float(signs[0] * signs[1] * signs[2])
            if det_sign <= 0.0:
                continue
            r = np.zeros((3, 3), dtype=np.float64)
            for col, row in enumerate(perm):
                r[row, col] = float(signs[col])
            key = tuple(float(x) for x in r.reshape(-1))
            if key not in seen:
                seen.add(key)
                mats.append(r)
    out: list[np.ndarray] = []
    for r in mats:
        tf = np.eye(4, dtype=np.float64)
        tf[:3, :3] = r
        out.append(tf)
    return np.stack(out, axis=0)


def build_quest_pose_pipeline(cfg: SimpleNamespace) -> QuestPosePipeline:
    """按 v2 配置构建 QuestPosePipeline。

    当前默认只支持 plan.md 指定的 YOLOE-26 + FFS + FoundationPose 路径。
    SAM3 保留为未来可选算法，不在本次 pose debug demo 中启用。
    """

    segmenter_type = str(cfg.module.segmenter.type).lower()
    if segmenter_type != "yoloe26":
        raise ValueError(f"v2 pose debug 当前仅实现 yoloe26 segmenter，收到: {segmenter_type}")

    # 具体模型适配器在工厂内惰性导入，避免 import 本模块时提前加载 torch/ultralytics/CUDA。
    from egoanchor.algorithms.fast_foundationstereo_depth import FastFoundationStereoDepth
    from egoanchor.algorithms.yoloe26_segmenter import Yoloe26Segmenter

    yoloe_device = str(cfg.module.yoloe.device).strip()
    if yoloe_device.lower() == "auto":
        device_value: str | int | None = None
    else:
        device_value = int(yoloe_device) if yoloe_device.isdigit() else yoloe_device

    segmenter = Yoloe26Segmenter(
        model_path=cfg.module.yoloe.model_path,
        init_prompt=str(cfg.module.segmenter.prompt),
        conf=float(cfg.module.yoloe.conf),
        imgsz=int(cfg.module.yoloe.imgsz),
        max_det=int(cfg.module.segmenter.max_det),
        mask_threshold=float(cfg.module.segmenter.mask_threshold),
        use_half=bool(cfg.module.yoloe.use_half),
        device=device_value,
        mobileclip2_path=cfg.module.yoloe.mobileclip2_path,
    )
    depth = FastFoundationStereoDepth(
        model_dir=cfg.module.ffs.model_path,
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
        project_root=cfg.paths.python_root,
    )
    if bool(cfg.module.cutie.enabled):
        from egoanchor.algorithms.cutie_mask_tracker import CutieMaskTracker

        cutie = CutieMaskTracker(
            seg_threshold=float(cfg.module.cutie.seg_threshold),
            erosion_size=int(cfg.module.cutie.erosion_size),
            project_root=cfg.paths.python_root,
        )
    else:
        cutie = None
    return QuestPosePipeline(cfg=cfg, segmenter=segmenter, depth_estimator=depth, cutie_tracker=cutie)
