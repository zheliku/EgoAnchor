"""Quest pose pipeline 的跟踪与诊断辅助逻辑。"""

from __future__ import annotations

import logging
import math
import time

import cv2
import numpy as np

from egoanchor.algorithms import SegmenterResult
from egoanchor.perception import DecodedQuestStereoFrame, FrameDiagnostics, MaskSource, PipelineStepTiming, PoseObservation, QuestStereoCalibration
from egoanchor.protocol import quest_pb2
from egoanchor.reliability import score_observation


class QuestPosePipelineHelpers:
    """QuestPosePipeline 的私有辅助方法集合。

    该 mixin 不独立实例化，只承载 depth 诊断、FoundationPose/Cutie 跟踪、
    observation 打包和低频日志等可测试的局部逻辑，让主 pipeline 文件聚焦阶段路由。
    """

    def _refresh_calibration(self, msg: quest_pb2.QuestCameraInfo) -> None:
        """根据 camera_info 更新 K，并在变化时重建 FoundationPose。"""

        if not self.network_calib_update and self.calibration is not None:
            return
        calibration = QuestStereoCalibration.from_proto(msg, assume_center_crop=self.assume_center_crop)
        signature = calibration.signature()
        if signature == self.calib_signature:
            return
        self.calibration = calibration
        self.calib_signature = signature
        self.cam_k = calibration.scaled_k(self.process_width, self.process_height)
        self.estimator.update_camera_matrix(self.cam_k)
        self.estimator.reset()
        self.tracking_state.bump_generation()
        if self._segmenter_worker is not None:
            self._segmenter_worker.clear()
        if self.cutie is not None:
            self.cutie.reset()
        logging.info("calibration updated: calib=%dx%d baseline=%.4fm fx=%.1f", calibration.calib_width, calibration.calib_height, calibration.baseline_m, self.cam_k[0, 0])

    def _apply_segmenter_snapshot(self, diagnostics: FrameDiagnostics) -> None:
        """把异步分割 worker 状态填入 diagnostics，供 HUD/日志显示。"""

        diagnostics.segmenter_async = self.async_segmentation
        worker = self._segmenter_worker
        if worker is None:
            return
        snapshot = worker.snapshot()
        diagnostics.segmenter_busy = snapshot.busy
        diagnostics.segmenter_submitted = snapshot.submitted
        diagnostics.segmenter_completed = snapshot.completed
        diagnostics.segmenter_dropped = snapshot.dropped
        diagnostics.segmenter_error = snapshot.error
        if snapshot.error and not diagnostics.failure_reason:
            diagnostics.failure_reason = "segmenter_error"

    def _run_segmenter(self, left_bgr: np.ndarray, timing: PipelineStepTiming) -> SegmenterResult:
        """执行分割后端并记录耗时。"""

        t0 = time.perf_counter()
        result = self.segmenter.infer(left_bgr)
        timing.yolo_ms = result.infer_ms if result.infer_ms > 0 else (time.perf_counter() - t0) * 1000.0
        return result

    def _predict_depth(self, left_rgb: np.ndarray, right_rgb: np.ndarray, timing: PipelineStepTiming) -> np.ndarray:
        """执行 FFS 深度估计并记录耗时。"""

        if self.calibration is None or self.cam_k is None:
            raise RuntimeError("缺少 calibration，不能预测深度。")
        t0 = time.perf_counter()
        depth = self.depth_estimator.predict_depth(left_rgb, right_rgb, fx=float(self.cam_k[0, 0]), baseline=float(self.calibration.baseline_m))
        timing.depth_ms = (time.perf_counter() - t0) * 1000.0
        return depth

    def _filter_depth(self, depth: np.ndarray) -> np.ndarray:
        """过滤非法和超范围深度值。"""

        depth = np.asarray(depth, dtype=np.float32).copy()
        valid = np.isfinite(depth) & (depth >= self.min_depth_m) & (depth <= self.max_depth_m)
        depth[~valid] = 0.0
        return depth

    def _update_depth_diagnostics(self, diagnostics: FrameDiagnostics, depth: np.ndarray, mask: np.ndarray | None) -> None:
        """统计 depth/mask 对齐质量。"""

        valid = np.isfinite(depth) & (depth > 0.0)
        diagnostics.depth_valid_ratio = float(np.count_nonzero(valid)) / float(valid.size) if valid.size else 0.0
        if mask is None:
            diagnostics.depth_valid_in_mask = 0.0
            diagnostics.depth_median_in_mask = 0.0
            diagnostics.depth_iqr_in_mask = 0.0
            return
        mask_bool = mask > 0
        mask_count = int(np.count_nonzero(mask_bool))
        diagnostics.mask_area_ratio = float(mask_count) / float(mask_bool.size) if mask_bool.size else 0.0
        if mask_count <= 0:
            diagnostics.depth_valid_in_mask = 0.0
            diagnostics.depth_median_in_mask = 0.0
            diagnostics.depth_iqr_in_mask = 0.0
            return
        in_mask = depth[mask_bool & valid]
        diagnostics.depth_valid_in_mask = float(in_mask.size) / float(mask_count)
        if in_mask.size > 0:
            q25, q50, q75 = np.percentile(in_mask, [25, 50, 75])
            diagnostics.depth_median_in_mask = float(q50)
            diagnostics.depth_iqr_in_mask = float(q75 - q25)

    def _try_recover_from_tracked_mask_loss(
        self,
        left_bgr: np.ndarray,
        rgb: np.ndarray,
        depth: np.ndarray,
        mask: np.ndarray | None,
        diagnostics: FrameDiagnostics,
        timing: PipelineStepTiming,
    ) -> tuple[np.ndarray | None, str, str] | None:
        """Cutie mask 连续丢失时，主动运行检测 mask 并尝试 re-register。"""

        state = self.tracking_state
        if not state.has_registered or not self.cutie_enabled or self.tracked_mask_lost_frames <= 0:
            return None

        mask_pixels = int(np.count_nonzero(mask)) if mask is not None else 0
        if mask_pixels > 0:
            state.tracked_mask_lost_count = 0
            return None

        state.tracked_mask_lost_count += 1
        if state.tracked_mask_lost_count < self.tracked_mask_lost_frames:
            return None

        state.has_registered = False
        state.cutie_ready = False
        state.last_pose = None
        state.track_reject_count = 0
        state.tracked_mask_lost_count = 0
        self.estimator.reset()
        if self.cutie is not None:
            self.cutie.reset()

        seg_result = self._run_segmenter(left_bgr, timing)
        diagnostics.det_count = int(seg_result.det_count)
        diagnostics.segmentation_overlay_bgr = seg_result.overlay_bgr
        diagnostics.mask_area_ratio = float(seg_result.mask_area_ratio)
        if seg_result.mask_bw is None or seg_result.mask_area_ratio <= 0.0:
            diagnostics.mask = None
            diagnostics.mask_source = MaskSource.NONE.value
            return None, "NONE", "REDETECT_NO_MASK"

        redetect_mask = (seg_result.mask_bw > 0).astype(np.uint8)
        diagnostics.mask = redetect_mask
        diagnostics.mask_source = self.segmenter_name
        self._show_mask_snapshot_once(redetect_mask)
        self._update_depth_diagnostics(diagnostics, depth, redetect_mask)
        if diagnostics.depth_valid_in_mask < self.register_min_depth_valid_in_mask:
            return None, "NONE", "REDETECT_REJECT_DEPTH"
        return self._try_register(rgb, depth, redetect_mask, timing, pose_source="RE_REGISTER", phase="RE_REGISTER")

    def _estimate_pose(self, rgb: np.ndarray, depth: np.ndarray, mask: np.ndarray | None, timing: PipelineStepTiming) -> tuple[np.ndarray | None, str, str]:
        """根据当前状态选择 register、track 或 re-register。"""

        state = self.tracking_state
        if not state.has_registered:
            if mask is None or np.count_nonzero(mask) <= 0:
                return None, "NONE", "NO_MASK"
            state.tracked_mask_lost_count = 0
            return self._try_register(rgb, depth, mask, timing, pose_source="REGISTER", phase="REGISTER")

        t_pose = time.perf_counter()
        try:
            pose = self.estimator.track(rgb, depth)
            timing.pose_ms = (time.perf_counter() - t_pose) * 1000.0
        except Exception as exc:
            logging.warning("FoundationPose track 失败: %s", exc)
            state.has_registered = False
            state.tracked_mask_lost_count = 0
            self.estimator.reset()
            state.track_reject_count += 1
            if self.re_register_on_track_lost and mask is not None and np.count_nonzero(mask) > 0:
                return self._try_register(rgb, depth, mask, timing, pose_source="RE_REGISTER", phase="RE_REGISTER")
            return None, "NONE", "TRACK_FAILED"

        if self._is_track_jump(pose):
            state.track_reject_count += 1
            logging.warning("FoundationPose track pose 跳变，尝试 re-register。reject_count=%d", state.track_reject_count)
            state.has_registered = False
            state.tracked_mask_lost_count = 0
            self.estimator.reset()
            if self.re_register_on_track_lost and mask is not None and np.count_nonzero(mask) > 0:
                return self._try_register(rgb, depth, mask, timing, pose_source="RE_REGISTER", phase="RE_REGISTER")
            if self.accept_track_jump_without_mask and state.track_reject_count < self.max_consecutive_track_rejects:
                state.has_registered = True
                state.last_pose = pose
                logging.warning("FoundationPose track pose 跳变但无 re-register mask，暂时接受该 pose。")
                return pose, "TRACK_ACCEPTED_JUMP", "TRACK_ACCEPTED_JUMP"
            return None, "NONE", "TRACK_REJECT"

        state.track_reject_count = 0
        if mask is not None and np.count_nonzero(mask) > 0:
            state.tracked_mask_lost_count = 0
        state.last_pose = pose
        return pose, "TRACK", "TRACK"

    def _try_register(self, rgb: np.ndarray, depth: np.ndarray, mask: np.ndarray, timing: PipelineStepTiming, pose_source: str, phase: str) -> tuple[np.ndarray | None, str, str]:
        """执行 FoundationPose register，并初始化可选 Cutie。"""

        t_pose = time.perf_counter()
        try:
            pose = self.estimator.register(rgb, depth, mask)
            timing.pose_ms += (time.perf_counter() - t_pose) * 1000.0
        except Exception as exc:
            timing.pose_ms += (time.perf_counter() - t_pose) * 1000.0
            self.tracking_state.has_registered = False
            logging.warning("FoundationPose register 失败: %s", exc)
            return None, "NONE", "REGISTER_FAILED"

        self.tracking_state.has_registered = True
        self.tracking_state.last_pose = pose
        self.tracking_state.track_reject_count = 0
        self.tracking_state.tracked_mask_lost_count = 0
        self._initialize_cutie(rgb, mask, timing)
        return pose, pose_source, phase

    def _track_cutie_mask(self, rgb: np.ndarray, timing: PipelineStepTiming) -> tuple[np.ndarray | None, list[int]]:
        """已 register 后用 Cutie 传播 2D mask，并可用 bbox 中心辅助 FoundationPose。"""

        empty_bbox = [-1, -1, 0, 0]
        if not self.cutie_enabled or self.cutie is None or not self.tracking_state.cutie_ready:
            return None, empty_bbox
        t_cutie = time.perf_counter()
        try:
            track_result = self.cutie.track(rgb)
            timing.cutie_ms += (time.perf_counter() - t_cutie) * 1000.0
        except Exception as exc:
            timing.cutie_ms += (time.perf_counter() - t_cutie) * 1000.0
            self.tracking_state.cutie_ready = False
            logging.warning("Cutie 跟踪失败，将继续尝试 FoundationPose track: %s", exc)
            return None, empty_bbox

        bbox = [int(v) for v in track_result.bbox_xywh]
        mask = (track_result.mask > 0).astype(np.uint8)
        if self.cutie_adjust_pose and bbox[2] > 0 and bbox[3] > 0:
            x, y, w, h = bbox
            self.estimator.adjust_pose_to_image_point(float(x + w * 0.5), float(y + h * 0.5))
        return mask, bbox

    def _initialize_cutie(self, rgb: np.ndarray, mask: np.ndarray, timing: PipelineStepTiming) -> None:
        """在 register 成功后用当前 mask 初始化 Cutie。"""

        if not self.cutie_enabled or self.cutie is None:
            return
        try:
            t_cutie = time.perf_counter()
            self.cutie.reset()
            self.cutie.initialize(rgb, init_mask=mask)
            timing.cutie_ms += (time.perf_counter() - t_cutie) * 1000.0
            self.tracking_state.cutie_ready = True
        except Exception as exc:
            self.tracking_state.cutie_ready = False
            logging.warning("Cutie 初始化失败，将跳过 2D mask tracking: %s", exc)

    def _is_track_jump(self, pose: np.ndarray) -> bool:
        """检测相邻帧 pose 是否出现过大跳变。"""

        if self.tracking_state.last_pose is None:
            return False
        last_pose = self.tracking_state.last_pose
        dx = float(pose[0, 3] - last_pose[0, 3])
        dy = float(pose[1, 3] - last_pose[1, 3])
        dz = float(pose[2, 3] - last_pose[2, 3])
        t_delta = math.sqrt(dx * dx + dy * dy + dz * dz)
        rotation_trace = sum(float(last_pose[row, col] * pose[row, col]) for row in range(3) for col in range(3))
        r_delta = self._rotation_angle_from_trace_deg(rotation_trace)
        return t_delta > self.pose_jump_translation_m or r_delta > self.pose_jump_rotation_deg

    @staticmethod
    def _rotation_angle_deg(rotation_delta: np.ndarray) -> float:
        """由相对旋转矩阵计算角度差。"""

        trace = float(np.trace(rotation_delta))
        return QuestPosePipelineHelpers._rotation_angle_from_trace_deg(trace)

    @staticmethod
    def _rotation_angle_from_trace_deg(trace: float) -> float:
        """由相对旋转矩阵 trace 计算角度差。"""

        cos_theta = max(-1.0, min(1.0, (trace - 1.0) * 0.5))
        return math.degrees(math.acos(cos_theta))

    def _make_observation(
        self,
        decoded: DecodedQuestStereoFrame | None,
        phase: str,
        has_pose: bool,
        pose: np.ndarray | None,
        pose_source: str,
        diagnostics: FrameDiagnostics,
        timing: PipelineStepTiming,
        failure_reason: str,
    ) -> PoseObservation:
        """把 pipeline 内部状态打包为 PoseObservation，并附加 reliability score。"""

        diagnostics.phase = phase
        diagnostics.failure_reason = failure_reason
        pose_flat = tuple(float(x) for x in pose.reshape(-1)) if pose is not None else None
        observation = PoseObservation(
            has_pose=bool(has_pose),
            phase=phase,
            frame_id=decoded.frame_id if decoded is not None else diagnostics.frame_id,
            pose_matrix_cv_camera=pose_flat,
            pose_source=pose_source,
            tracking_state_hint="TRACKING" if has_pose else "DETECTING",
            stage=self.stage,
            det_count=diagnostics.det_count,
            fps=self._fps,
            depth_valid_ratio=diagnostics.depth_valid_ratio,
            depth_valid_in_mask=diagnostics.depth_valid_in_mask,
            depth_median_in_mask=diagnostics.depth_median_in_mask,
            depth_iqr_in_mask=diagnostics.depth_iqr_in_mask,
            mask_area_ratio=diagnostics.mask_area_ratio,
            track_reject_count=self.tracking_state.track_reject_count,
            yolo_ms=timing.yolo_ms,
            depth_ms=timing.depth_ms,
            cutie_ms=timing.cutie_ms,
            pose_ms=timing.pose_ms,
            total_ms=timing.total_ms,
            failure_reason=failure_reason,
        )
        score, flags = score_observation(observation)
        return PoseObservation(
            **{field_name: getattr(observation, field_name) for field_name in observation.__dataclass_fields__ if field_name not in {"reliability_score", "reliability_flags"}},
            reliability_score=score,
            reliability_flags=flags,
        )

    def _show_mask_snapshot_once(self, mask: np.ndarray) -> None:
        """按配置显示一次真实下游 mask，便于确认 YOLOE prompt 质量。"""

        if not self.show_mask_snapshot or self._mask_snapshot_shown:
            return
        mask_vis = (mask > 0).astype(np.uint8) * 255
        cv2.imshow(self.mask_snapshot_window, mask_vis)
        self._mask_snapshot_shown = True

    def _update_fps(self) -> None:
        """更新 pipeline FPS EMA。"""

        now = time.perf_counter()
        if self._last_process_time is not None:
            dt = max(now - self._last_process_time, 1e-6)
            inst_fps = 1.0 / dt
            self._fps = inst_fps if self._fps <= 0 else self._fps * 0.9 + inst_fps * 0.1
        self._last_process_time = now
        self._processed_count += 1

    def _log_stats(self, diagnostics: FrameDiagnostics, observation: PoseObservation) -> None:
        """周期打印关键质量指标，避免高频刷屏。"""

        if self.log_stats_interval <= 0 or self._processed_count % self.log_stats_interval != 0:
            return
        logging.info(
            "pose frame=%s phase=%s has_pose=%s det=%d depth(mask)=%.3f mask=%.3f score=%.2f fps=%.1f total=%.1fms",
            observation.frame_id,
            observation.phase,
            observation.has_pose,
            diagnostics.det_count,
            diagnostics.depth_valid_in_mask,
            diagnostics.mask_area_ratio,
            observation.reliability_score,
            observation.fps,
            observation.total_ms,
        )
