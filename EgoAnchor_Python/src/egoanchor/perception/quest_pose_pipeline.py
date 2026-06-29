"""Quest stereo + 可切换分割后端 + FFS + FoundationPose 的 pose pipeline。

本文件实现 Python 侧本地 debug 用的感知主流程。它接收已由 runtime 提供的最新
Quest Protobuf 消息，输出 camera-space PoseObservation 和 OpenCV debug 图像；不
做 ZMQ/NATS 通信，也不做 Unity 坐标转换。
"""

from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import TYPE_CHECKING

import cv2
import numpy as np

from egoanchor.protocol import extract_frame_id, extract_session_id, quest_pb2
from egoanchor.reliability import PoseScoreConfig, RenderQualityChecker, score_observation_breakdown
from egoanchor.utils import clamp, get_logger

from .async_segmenter import AsyncSegmenterJob, AsyncSegmenterWorker, SegmenterBackend
from .pipeline_types import FrameDiagnostics, MaskSource, PipelineStepTiming, PipelineTrackingState, QuestPosePipelineOutput
from .pose_observation import PoseObservation
from .quest_calibration import QuestStereoCalibration
from .quest_frame import DecodedQuestStereoFrame, decode_quest_stereo_frame, preprocess_stereo_pair

if TYPE_CHECKING:
    from egoanchor.algorithms import CutieMaskTracker, FastFoundationStereoDepth, FoundationPoseObjectEstimator, SegmenterResult

LOGGER = get_logger(__name__, component="QuestPosePipeline")
"""Quest pose pipeline 日志记录器。"""


def _mask_has_pixels(mask: np.ndarray | None) -> bool:
    """判断 mask 是否存在且包含前景像素。"""

    return mask is not None and np.count_nonzero(mask) > 0


class QuestPosePipeline:
    """Quest object pose estimation pipeline。"""

    def __init__(
        self,
        segmenter: SegmenterBackend,
        segmenter_name: str,
        depth_estimator: FastFoundationStereoDepth,
        foundationpose_estimator: FoundationPoseObjectEstimator,
        cutie_tracker: CutieMaskTracker | None,
        process_width: int,
        process_height: int,
        assume_center_crop: bool = True,
        network_calib_update: bool = True,
        min_depth_m: float = 0.1,
        max_depth_m: float = 5.0,
        register_min_depth_valid_in_mask: float = 0.05,
        pose_jump_translation_m: float = 0.25,
        pose_jump_rotation_deg: float = 35.0,
        cutie_enabled: bool = False,
        cutie_adjust_pose: bool = False,
        cutie_lost_reset_frames: int = 5,
        log_stats_interval: int = 60,
        show_mask_snapshot: bool = False,
        mask_snapshot_window: str = "EgoAnchor mask",
        async_segmentation: bool = False,
        enable_render_quality: bool = False,
        render_quality_warmup_frames: int = 3,
        render_quality_depth_distance_ratio: float = 0.02,
        render_quality_depth_min_inlier_thresh_m: float = 0.005,
        render_quality_depth_min_coverage: float = 0.10,
        render_quality_downscale: int = 2,
        render_quality_min_render_area_px: int = 50,
        render_quality_color_l_weight: float = 0.3,
        pose_score_config: PoseScoreConfig | None = None,
    ) -> None:
        """注入算法组件和 pipeline 策略参数。"""

        self.segmenter = segmenter
        """单目标分割器；可由 YOLOE-26 或 SAM3 提供。"""

        self.segmenter_name = str(segmenter_name)
        """当前分割后端名称，用于 diagnostics.mask_source。"""

        self.depth_estimator = depth_estimator
        """FFS 深度估计器。"""

        self.estimator = foundationpose_estimator
        """已在 server 启动阶段预加载的 FoundationPose 估计器。"""

        self.cutie = cutie_tracker
        """已在 server 启动阶段预加载的 Cutie mask tracker；禁用时为 None。"""

        self.process_width = int(process_width)
        """算法处理图像宽度。"""

        self.process_height = int(process_height)
        """算法处理图像高度。"""

        self.assume_center_crop = bool(assume_center_crop)
        """是否按 Quest active array 中心裁剪映射 K。"""

        self.network_calib_update = bool(network_calib_update)
        """是否用网络 camera_info 刷新 pipeline 标定。"""

        self.min_depth_m = float(min_depth_m)
        """有效深度最小值。"""

        self.max_depth_m = float(max_depth_m)
        """有效深度最大值。"""

        self.register_min_depth_valid_in_mask = float(register_min_depth_valid_in_mask)
        """允许 register 的 mask 内有效深度最低比例。"""

        self.pose_jump_translation_m = float(pose_jump_translation_m)
        """track pose 平移跳变 reject 阈值，单位米。"""

        self.pose_jump_rotation_deg = float(pose_jump_rotation_deg)
        """track pose 旋转跳变 reject 阈值，单位度。"""

        self.cutie_enabled = bool(cutie_enabled)
        """是否启用 Cutie mask 传播。"""

        self.cutie_adjust_pose = bool(cutie_adjust_pose)
        """是否用 Cutie bbox 中心轻量修正 pose x/y。"""

        self.cutie_lost_reset_frames = max(1, int(cutie_lost_reset_frames))
        """Cutie 连续返回空 mask 多少帧后触发本地重置注册；防单帧抖动误触发。"""

        self.log_stats_interval = int(log_stats_interval)
        """每隔多少帧打印一次 pipeline 诊断。"""

        self.show_mask_snapshot = bool(show_mask_snapshot)
        """是否在首次获得 mask 时弹出独立 snapshot 窗口。"""

        self.mask_snapshot_window = str(mask_snapshot_window)
        """mask snapshot 窗口名。"""

        self.async_segmentation = bool(async_segmentation)
        """是否把初始分割阶段放到后台线程。"""

        self.enable_render_quality = bool(enable_render_quality)
        """是否启用渲染质量检测。"""

        self.render_quality_warmup_frames = max(0, int(render_quality_warmup_frames))
        """register 后跳过渲染质量判定的帧数。"""

        self.render_quality_checker = (
            RenderQualityChecker(
                depth_distance_ratio=render_quality_depth_distance_ratio,
                depth_min_inlier_thresh_m=render_quality_depth_min_inlier_thresh_m,
                depth_min_coverage=render_quality_depth_min_coverage,
                min_render_area_px=render_quality_min_render_area_px,
                color_l_weight=render_quality_color_l_weight,
                downscale=render_quality_downscale,
            )
            if self.enable_render_quality
            else None
        )
        """一次渲染后拆分重投影和深度对齐的质量检测器；配置关闭时为 None。"""

        self.pose_score_config = pose_score_config or PoseScoreConfig()
        """Pose reliability quality 合成参数，用于几何核与有界调制。"""

        self._segmenter_worker: AsyncSegmenterWorker | None = AsyncSegmenterWorker(segmenter) if self.async_segmentation else None
        """异步分割 worker；同步模式下为 None。"""

        if self._segmenter_worker is not None:
            self._segmenter_worker.start()

        self.stage = 4
        """当前 OpenCV debug stage。"""

        self.calibration: QuestStereoCalibration | None = None
        """当前 camera_info 映射出的 stereo calibration。"""

        self.calib_signature: tuple[float, ...] | None = None
        """当前标定签名；变化时重建 FoundationPose。"""

        self.cam_k: np.ndarray | None = None
        """处理分辨率下的左目 K。"""

        self.tracking_state = PipelineTrackingState()
        """FoundationPose/Cutie 时序跟踪状态。"""

        self._last_frame_id: int | None = None
        """上一帧处理过的 frame_id，避免重复处理。"""

        self._last_session_id = ""
        """上一帧处理过的 Unity 发布会话 ID，用于识别 Unity 重启后的 frame_id 回绕。"""

        self._fps = 0.0
        """pipeline FPS EMA。"""

        self._last_process_time: float | None = None
        """上一帧处理完成时间，用于 FPS 估计。"""

        self._processed_count = 0
        """累计处理帧数。"""

    def set_stage(self, stage: int) -> None:
        """设置 debug stage，并限制在 1..4。"""

        self.stage = int(clamp(stage, 1, 4))

    def close(self) -> None:
        """关闭 pipeline 持有的后台资源。"""

        if self._segmenter_worker is not None:
            self._segmenter_worker.stop()
            self._segmenter_worker = None

    def reset_tracking_state(self) -> None:
        """重置时序跟踪状态，下一帧重新分割/register。"""

        self.tracking_state.bump_generation()
        self._last_frame_id = None
        self._last_session_id = ""
        if self._segmenter_worker is not None:
            self._segmenter_worker.clear()
        if self.estimator is not None:
            self.estimator.reset()
        if self.cutie is not None:
            self.cutie.reset()
        LOGGER.info("pose pipeline tracking state reset")

    def process(
        self,
        stereo_msg: quest_pb2.QuestStereoFrame | None,
        camera_info_msg: quest_pb2.QuestCameraInfo | None,
        *,
        server_receive_mono_ms: float = 0.0,
    ) -> QuestPosePipelineOutput:
        """处理最新 Quest stereo/camera_info 并返回 debug 输出。"""

        timing = PipelineStepTiming()
        diagnostics = FrameDiagnostics(stage=self.stage, timing=timing)
        t_total = time.perf_counter()

        if camera_info_msg is not None:
            try:
                self._refresh_calibration(camera_info_msg)
            except ValueError as exc:
                LOGGER.warning("Quest camera_info 无效，继续等待有效标定: %s", exc)
                if self.calibration is None or self.cam_k is None:
                    diagnostics.phase = "WAIT_CALIBRATION"
                    timing.finalize(t_total)
                    obs = self._make_observation(
                        None,
                        diagnostics.phase,
                        False,
                        None,
                        "NONE",
                        diagnostics,
                        timing,
                        failure_reason="invalid_calibration",
                        server_receive_mono_ms=server_receive_mono_ms,
                    )
                    return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=False)

        ready_output = self._take_ready_async_segmentation(t_total)
        if ready_output is not None:
            return ready_output

        if stereo_msg is None:
            diagnostics.phase = "WAIT_STREAM"
            return QuestPosePipelineOutput(observation=None, diagnostics=diagnostics, timing=timing, new_frame_processed=False)

        frame_id = extract_frame_id(stereo_msg)
        session_id = extract_session_id(stereo_msg)
        same_session = not session_id or not self._last_session_id or session_id == self._last_session_id
        if same_session and frame_id is not None and frame_id == self._last_frame_id:
            ready_output = self._take_ready_async_segmentation(t_total)
            if ready_output is not None:
                return ready_output
            diagnostics.phase = "DUPLICATE_FRAME"
            diagnostics.frame_id = frame_id
            return QuestPosePipelineOutput(observation=None, diagnostics=diagnostics, timing=timing, new_frame_processed=False)

        decoded = decode_quest_stereo_frame(stereo_msg, server_receive_mono_ms=server_receive_mono_ms)
        if decoded is None:
            diagnostics.phase = "DECODE_FAILED"
            diagnostics.frame_id = frame_id
            obs = self._make_observation(
                None,
                "DECODE_FAILED",
                False,
                None,
                "NONE",
                diagnostics,
                timing,
                failure_reason="decode_failed",
                server_receive_mono_ms=server_receive_mono_ms,
            )
            return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=False)

        if not same_session:
            self.reset_tracking_state()
            diagnostics.phase = "STREAM_RESTART"

        self._last_frame_id = decoded.frame_id
        self._last_session_id = session_id or self._last_session_id
        diagnostics.frame_id = decoded.frame_id

        left_bgr, right_bgr = preprocess_stereo_pair(decoded.left_bgr, decoded.right_bgr, self.process_width, self.process_height)
        diagnostics.left_bgr = left_bgr
        diagnostics.right_bgr = right_bgr

        if self.calibration is None or self.cam_k is None:
            diagnostics.phase = "WAIT_CALIBRATION"
            timing.finalize(t_total)
            self._update_fps()
            diagnostics.fps = self._fps
            obs = self._make_observation(decoded, diagnostics.phase, False, None, "NONE", diagnostics, timing, failure_reason="wait_calibration")
            return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=True)

        if self.async_segmentation and not self.tracking_state.has_registered:
            job = AsyncSegmenterJob(
                decoded=decoded,
                session_id=session_id,
                left_bgr=left_bgr,
                right_bgr=right_bgr,
                generation=self.tracking_state.generation,
            )
            return self._process_async_segmentation_frame(job, diagnostics, timing, t_total)

        return self._process_prepared_frame(decoded, left_bgr, right_bgr, diagnostics, timing, t_total, async_seg_result=None)

    def _process_async_segmentation_frame(
        self,
        current_job: AsyncSegmenterJob,
        current_diagnostics: FrameDiagnostics,
        current_timing: PipelineStepTiming,
        t_total: float,
    ) -> QuestPosePipelineOutput:
        """异步 SAM3 模式下提交当前帧，并在结果完成时处理对应旧帧。"""

        worker = self._segmenter_worker
        if worker is None:
            return self._process_prepared_frame(
                current_job.decoded,
                current_job.left_bgr,
                current_job.right_bgr,
                current_diagnostics,
                current_timing,
                t_total,
                async_seg_result=None,
            )

        completed_output = self._take_ready_async_segmentation(t_total)
        if completed_output is not None:
            return completed_output

        worker.submit(current_job)
        current_diagnostics.phase = "WAIT_SEGMENTATION"
        self._apply_segmenter_snapshot(current_diagnostics)
        rgb = cv2.cvtColor(current_job.left_bgr, cv2.COLOR_BGR2RGB)
        right_rgb = cv2.cvtColor(current_job.right_bgr, cv2.COLOR_BGR2RGB)
        depth = self._filter_depth(self._predict_depth(rgb, right_rgb, current_timing))
        current_diagnostics.depth = depth
        self._update_depth_diagnostics(current_diagnostics, depth, None)
        current_timing.finalize(t_total)
        # 异步分割等待帧也跑了深度预测，计入 fps，否则 register 前 HUD 一直是 fps=0。
        self._update_fps()
        current_diagnostics.fps = self._fps
        return QuestPosePipelineOutput(observation=None, diagnostics=current_diagnostics, timing=current_timing, new_frame_processed=True)

    def _take_ready_async_segmentation(self, t_total: float) -> QuestPosePipelineOutput | None:
        """若后台分割已有完成结果，则用结果所属帧继续 pipeline。"""

        worker = self._segmenter_worker
        if not self.async_segmentation or worker is None or self.tracking_state.has_registered:
            return None
        if self.calibration is None or self.cam_k is None:
            return None

        completed = worker.take_completed()
        if completed is None:
            return None

        result_job = completed.job
        result_timing = PipelineStepTiming(yolo_ms=completed.elapsed_ms)
        result_diagnostics = FrameDiagnostics(
            left_bgr=result_job.left_bgr,
            right_bgr=result_job.right_bgr,
            stage=self.stage,
            phase="SEGMENTATION_READY",
            frame_id=result_job.decoded.frame_id,
            timing=result_timing,
        )
        self._apply_segmenter_snapshot(result_diagnostics)

        same_generation = result_job.generation == self.tracking_state.generation
        same_session = not self._last_session_id or not result_job.session_id or result_job.session_id == self._last_session_id
        if not same_generation or not same_session:
            return None

        if completed.error:
            result_diagnostics.phase = "SEGMENTATION_FAILED"
            result_timing.finalize(t_total)
            self._update_fps()
            result_diagnostics.fps = self._fps
            obs = self._make_observation(
                result_job.decoded,
                result_diagnostics.phase,
                False,
                None,
                "NONE",
                result_diagnostics,
                result_timing,
                failure_reason="segmentation_failed",
            )
            return QuestPosePipelineOutput(observation=obs, diagnostics=result_diagnostics, timing=result_timing, new_frame_processed=True)

        if completed.result is None:
            return None

        return self._process_prepared_frame(
            result_job.decoded,
            result_job.left_bgr,
            result_job.right_bgr,
            result_diagnostics,
            result_timing,
            t_total,
            async_seg_result=completed.result,
        )

    def _process_prepared_frame(
        self,
        decoded: DecodedQuestStereoFrame,
        left_bgr: np.ndarray,
        right_bgr: np.ndarray,
        diagnostics: FrameDiagnostics,
        timing: PipelineStepTiming,
        t_total: float,
        async_seg_result: SegmenterResult | None,
    ) -> QuestPosePipelineOutput:
        """处理已解码并缩放好的同一帧 stereo 数据。"""

        diagnostics.left_bgr = left_bgr
        diagnostics.right_bgr = right_bgr
        diagnostics.frame_id = decoded.frame_id
        diagnostics.frame_dt_s = self._estimate_frame_dt_s(decoded)
        self._apply_segmenter_snapshot(diagnostics)

        rgb = cv2.cvtColor(left_bgr, cv2.COLOR_BGR2RGB)
        right_rgb = cv2.cvtColor(right_bgr, cv2.COLOR_BGR2RGB)

        mask, early_output = self._run_detect_stage(decoded, left_bgr, rgb, diagnostics, timing, t_total, async_seg_result)
        if early_output is not None:
            return early_output

        depth, early_output = self._run_depth_stage(decoded, rgb, right_rgb, mask, diagnostics, timing, t_total)
        if early_output is not None:
            return early_output

        early_output = self._run_register_stage(decoded, mask, diagnostics, timing, t_total)
        if early_output is not None:
            return early_output

        return self._run_track_stage(decoded, rgb, depth, mask, diagnostics, timing, t_total)

    def _run_detect_stage(
        self,
        decoded: DecodedQuestStereoFrame,
        left_bgr: np.ndarray,
        rgb: np.ndarray,
        diagnostics: FrameDiagnostics,
        timing: PipelineStepTiming,
        t_total: float,
        async_seg_result: SegmenterResult | None,
    ) -> tuple[np.ndarray | None, QuestPosePipelineOutput | None]:
        """执行 detect 或 Cutie mask 阶段；stage<=2 时直接返回输出。

        未注册且暂时没有 mask 时仍继续后续 FFS depth，让启动阶段的深度面板
        能显示实时估计结果；register 前置条件仍在深度之后统一判断。
        """

        if not self.tracking_state.has_registered:
            mask = self._detect_initial_mask(left_bgr, diagnostics, timing, async_seg_result)
            if self.stage <= 2:
                return mask, self._finish_frame(decoded, "MASK_ONLY", False, None, "NONE", diagnostics, timing, t_total, "stage_mask_only")
            return mask, None

        mask, cutie_bbox = self._track_cutie_mask(rgb, timing)
        diagnostics.cutie_bbox_xywh = (
            int(cutie_bbox[0]),
            int(cutie_bbox[1]),
            int(cutie_bbox[2]),
            int(cutie_bbox[3]),
        )
        if mask is not None:
            diagnostics.mask = mask
            diagnostics.mask_source = MaskSource.CUTIE.value
            diagnostics.mask_area_ratio = float(np.count_nonzero(mask > 0)) / float(mask.size) if mask.size else 0.0
        if self.stage <= 2:
            return mask, self._finish_frame(decoded, "TRACK_MASK_ONLY", False, None, "NONE", diagnostics, timing, t_total, "stage_mask_only")
        return mask, None

    def _detect_initial_mask(
        self,
        left_bgr: np.ndarray,
        diagnostics: FrameDiagnostics,
        timing: PipelineStepTiming,
        async_seg_result: SegmenterResult | None,
    ) -> np.ndarray | None:
        """运行初始分割后端，并把 mask 相关诊断写入 diagnostics。"""

        seg_result = async_seg_result if async_seg_result is not None else self._run_segmenter(left_bgr, timing)
        diagnostics.det_count = int(seg_result.det_count)
        diagnostics.segmentation_overlay_bgr = seg_result.overlay_bgr
        diagnostics.mask_area_ratio = float(seg_result.mask_area_ratio)
        if seg_result.mask_bw is None or seg_result.mask_area_ratio <= 0.0:
            return None
        mask = (seg_result.mask_bw > 0).astype(np.uint8)
        diagnostics.mask = mask
        diagnostics.mask_source = self.segmenter_name
        return mask

    def _run_depth_stage(
        self,
        decoded: DecodedQuestStereoFrame,
        rgb: np.ndarray,
        right_rgb: np.ndarray,
        mask: np.ndarray | None,
        diagnostics: FrameDiagnostics,
        timing: PipelineStepTiming,
        t_total: float,
    ) -> tuple[np.ndarray, QuestPosePipelineOutput | None]:
        """执行 FFS depth 阶段；stage<=3 时直接返回输出。"""

        depth = self._filter_depth(self._predict_depth(rgb, right_rgb, timing))
        diagnostics.depth = depth
        self._update_depth_diagnostics(diagnostics, depth, mask)
        if self.stage <= 3:
            output = self._finish_frame(decoded, "DEPTH_ONLY", False, None, "NONE", diagnostics, timing, t_total, "stage_depth_only")
            return depth, output
        return depth, None

    def _run_register_stage(
        self,
        decoded: DecodedQuestStereoFrame,
        mask: np.ndarray | None,
        diagnostics: FrameDiagnostics,
        timing: PipelineStepTiming,
        t_total: float,
    ) -> QuestPosePipelineOutput | None:
        """执行首次 register 前置检查；无早退时返回 None。"""

        if not self.tracking_state.has_registered and not _mask_has_pixels(mask):
            return self._finish_frame(decoded, "NO_MASK", False, None, "NONE", diagnostics, timing, t_total, "no_mask")
        if not self.tracking_state.has_registered and diagnostics.depth_valid_in_mask < self.register_min_depth_valid_in_mask:
            return self._finish_frame(decoded, "REJECT_DEPTH", False, None, "NONE", diagnostics, timing, t_total, "depth_in_mask_low")
        if self._tracked_mask_is_lost(mask):
            self.tracking_state.cutie_lost_frames += 1
            if self.tracking_state.cutie_lost_frames >= self.cutie_lost_reset_frames:
                self.tracking_state.clear_registration()
                if self.estimator is not None:
                    self.estimator.reset()
                if self.cutie is not None:
                    self.cutie.reset()
                LOGGER.info("Cutie mask 连续丢失 %d 帧，重置注册状态等待重新 register。", self.tracking_state.cutie_lost_frames)
            return self._finish_frame(decoded, "TRACK_MASK_LOST", False, None, "NONE", diagnostics, timing, t_total, "track_mask_lost")
        self.tracking_state.cutie_lost_frames = 0
        return None

    def _run_track_stage(
        self,
        decoded: DecodedQuestStereoFrame,
        rgb: np.ndarray,
        depth: np.ndarray,
        mask: np.ndarray | None,
        diagnostics: FrameDiagnostics,
        timing: PipelineStepTiming,
        t_total: float,
    ) -> QuestPosePipelineOutput:
        """执行 FoundationPose register/track，并返回最终 pose 输出。"""

        pose, pose_source, phase = self._estimate_pose(rgb, depth, mask, diagnostics, timing)
        has_pose = pose is not None
        return self._finish_frame(
            decoded,
            phase,
            has_pose,
            pose,
            pose_source,
            diagnostics,
            timing,
            t_total,
            "" if has_pose else phase.lower(),
            rgb=rgb,
            log_stats=True,
        )

    def _finish_frame(
        self,
        decoded: DecodedQuestStereoFrame,
        phase: str,
        has_pose: bool,
        pose: np.ndarray | None,
        pose_source: str,
        diagnostics: FrameDiagnostics,
        timing: PipelineStepTiming,
        t_total: float,
        failure_reason: str,
        *,
        rgb: np.ndarray | None = None,
        log_stats: bool = False,
    ) -> QuestPosePipelineOutput:
        """收尾单帧输出，统一写 total_ms、fps、pose 可视化与 observation。"""

        diagnostics.phase = phase
        if pose is not None and self.estimator is not None:
            if rgb is None:
                raise RuntimeError("生成 pose 可视化时缺少 RGB 图像。")
            try:
                pose_vis_rgb = self.estimator.visualize_pose(rgb, pose)
                diagnostics.pose_vis_bgr = cv2.cvtColor(pose_vis_rgb, cv2.COLOR_RGB2BGR)
            except Exception as exc:
                diagnostics.pose_vis_bgr = None
                LOGGER.warning("FoundationPose pose 可视化失败，跳过本帧 debug 图: %s", exc)

        timing.finalize(t_total)
        # fps 反映真实帧率：每个处理过的帧都更新节拍，不论是否已建立 track。
        self._update_fps()
        diagnostics.fps = self._fps
        diagnostics.timing = timing
        obs = self._make_observation(decoded, phase, has_pose, pose, pose_source, diagnostics, timing, failure_reason=failure_reason)
        if log_stats:
            self._log_stats(diagnostics, obs)
        return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=True)

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
        LOGGER.info("calibration updated: calib=%dx%d baseline=%.4fm fx=%.1f", calibration.calib_width, calibration.calib_height, calibration.baseline_m, self.cam_k[0, 0])

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
            diagnostics.depth_median_m = 0.0
            diagnostics.depth_iqr_m = 0.0
            return
        mask_bool = mask > 0
        mask_count = int(np.count_nonzero(mask_bool))
        diagnostics.mask_area_ratio = float(mask_count) / float(mask_bool.size) if mask_bool.size else 0.0
        if mask_count <= 0:
            diagnostics.depth_valid_in_mask = 0.0
            diagnostics.depth_median_m = 0.0
            diagnostics.depth_iqr_m = 0.0
            return
        in_mask = depth[mask_bool & valid]
        diagnostics.depth_valid_in_mask = float(in_mask.size) / float(mask_count)
        if in_mask.size > 0:
            q25, q50, q75 = np.percentile(in_mask, [25, 50, 75])
            diagnostics.depth_median_m = float(q50)
            diagnostics.depth_iqr_m = float(q75 - q25)

    def _estimate_frame_dt_s(self, decoded: DecodedQuestStereoFrame) -> float:
        """估计当前处理帧与上一处理帧之间的时间间隔，供 frame_dt_s 遥测使用。"""

        state = self.tracking_state
        current_ms = float(decoded.sender_mono_ms) if decoded.sender_mono_ms is not None else time.perf_counter() * 1000.0
        if state.last_sender_mono_ms is None:
            state.last_sender_mono_ms = current_ms
            return 1.0 / 30.0
        dt_s = max((current_ms - state.last_sender_mono_ms) / 1000.0, 1e-3)
        state.last_sender_mono_ms = current_ms
        return dt_s

    def _tracked_mask_is_lost(self, mask: np.ndarray | None) -> bool:
        """判断已注册阶段的 Cutie 传播是否明确返回空 mask。"""

        return bool(self.cutie_enabled and self.tracking_state.cutie_ready and mask is not None and not _mask_has_pixels(mask))

    def _estimate_pose(
        self,
        rgb: np.ndarray,
        depth: np.ndarray,
        mask: np.ndarray | None,
        diagnostics: FrameDiagnostics,
        timing: PipelineStepTiming,
    ) -> tuple[np.ndarray | None, str, str]:
        """根据当前状态选择首次 register 或连续 track。"""

        state = self.tracking_state
        if not state.has_registered:
            if not _mask_has_pixels(mask):
                return None, "NONE", "NO_MASK"
            return self._try_register(rgb, depth, mask, timing)

        t_pose = time.perf_counter()
        try:
            pose = self.estimator.track(rgb, depth)
            timing.pose_ms = (time.perf_counter() - t_pose) * 1000.0
        except Exception as exc:
            LOGGER.warning("FoundationPose track 失败: %s", exc)
            state.track_reject_count += 1
            return None, "NONE", "TRACK_FAILED"
        pose = self._normalize_pose_matrix(pose)
        if pose is None:
            LOGGER.warning("FoundationPose track 返回无效 pose，等待 Unity 侧重获取命令。")
            state.track_reject_count += 1
            return None, "NONE", "TRACK_FAILED"

        t_delta, r_delta = self._track_deltas(pose, state.last_pose)
        diagnostics.last_translation_delta_m = t_delta
        diagnostics.last_rotation_delta_deg = r_delta

        if t_delta > self.pose_jump_translation_m or r_delta > self.pose_jump_rotation_deg:
            state.track_reject_count += 1
            LOGGER.warning("FoundationPose track pose 跳变，输出 no-pose 并等待 Unity 侧重获取命令。reject_count=%d", state.track_reject_count)
            return None, "NONE", "TRACK_REJECT"

        self._check_render_quality(pose, rgb, depth, mask, diagnostics)

        state.track_reject_count = 0
        state.last_pose = pose
        state.frames_since_register += 1
        return pose, "TRACK", "TRACK"

    def _try_register(self, rgb: np.ndarray, depth: np.ndarray, mask: np.ndarray, timing: PipelineStepTiming) -> tuple[np.ndarray | None, str, str]:
        """执行 FoundationPose register，并初始化可选 Cutie。"""

        t_pose = time.perf_counter()
        try:
            pose = self.estimator.register(rgb, depth, mask)
            timing.pose_ms += (time.perf_counter() - t_pose) * 1000.0
        except Exception as exc:
            timing.pose_ms += (time.perf_counter() - t_pose) * 1000.0
            self.tracking_state.has_registered = False
            LOGGER.warning("FoundationPose register 失败: %s", exc)
            return None, "NONE", "REGISTER_FAILED"
        pose = self._normalize_pose_matrix(pose)
        if pose is None:
            self.tracking_state.has_registered = False
            LOGGER.warning("FoundationPose register 返回无效 pose，跳过本帧。")
            return None, "NONE", "REGISTER_FAILED"

        self.tracking_state.has_registered = True
        self.tracking_state.last_pose = pose
        self.tracking_state.track_reject_count = 0
        self.tracking_state.frames_since_register = 0
        self._show_register_mask_snapshot(mask)
        self._initialize_cutie(rgb, mask, timing)
        return pose, "REGISTER", "REGISTER"

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
            LOGGER.warning("Cutie 跟踪失败，将继续尝试 FoundationPose track: %s", exc)
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
            LOGGER.warning("Cutie 初始化失败，将跳过 2D mask tracking: %s", exc)

    def _check_render_quality(
        self,
        pose: np.ndarray,
        rgb: np.ndarray,
        depth: np.ndarray,
        mask: np.ndarray | None,
        diagnostics: FrameDiagnostics,
    ) -> None:
        """对 TRACK pose 做渲染质量检测，并仅写入可靠性评分所需诊断。"""

        checker = self.render_quality_checker
        state = self.tracking_state
        diagnostics.render_quality_evaluated = False
        if checker is None:
            diagnostics.render_quality_status = "disabled"
            return None
        if self.cam_k is None:
            diagnostics.render_quality_status = "no_k"
            return None
        if state.frames_since_register < self.render_quality_warmup_frames:
            diagnostics.render_quality_status = "warmup"
            return None
        if not _mask_has_pixels(mask):
            diagnostics.render_quality_status = "no_mask"
            return None

        diagnostics.render_quality_evaluated = True
        diagnostics.render_quality_status = "rendering"
        t0 = time.perf_counter()
        result = checker.evaluate(
            self.estimator,
            pose,
            rgb,
            mask,
            depth,
            depth_coverage=diagnostics.depth_valid_in_mask,
        )
        diagnostics.render_quality_ms = (time.perf_counter() - t0) * 1000.0
        # 纯色/无纹理物体 color_valid=False：颜色 ZNCC 无方差，置 -1.0 让评分层排除颜色项而非按中性 0.5 降分。
        color_usable = result.reprojection_valid and result.color_valid
        diagnostics.color_reprojection = result.reprojection_score if color_usable else -1.0
        diagnostics.render_quality_status = result.status
        diagnostics.render_quality_mask_iou = result.mask_iou
        diagnostics.render_quality_depth_inlier = result.depth_inlier_ratio
        diagnostics.render_quality_depth_alignment = result.depth_alignment_score
        diagnostics.render_quality_area_ratio_score = result.area_ratio_score
        diagnostics.render_quality_depth_residual_m = result.depth_median_residual_m
        diagnostics.render_quality_render_visible_ratio = result.render_visible_ratio
        diagnostics.render_quality_observed_visible_ratio = result.observed_visible_ratio
        diagnostics.render_quality_render_area_px = result.render_area_px
        diagnostics.render_quality_render_mask = result.render_mask
        diagnostics.render_quality_observed_mask = result.observed_mask
        diagnostics.render_quality_render_depth = result.render_depth_m
        diagnostics.render_quality_observed_depth = result.observed_depth_m
        diagnostics.render_quality_render_rgb = result.render_rgb
        diagnostics.render_quality_observed_rgb = result.observed_rgb

    @staticmethod
    def _track_deltas(pose: np.ndarray, previous_pose: np.ndarray | None) -> tuple[float, float]:
        """计算上一接受 pose 到当前 pose 的平移和旋转增量。"""

        if previous_pose is None:
            return 0.0, 0.0
        current = np.asarray(pose, dtype=np.float64).reshape(4, 4)
        previous = np.asarray(previous_pose, dtype=np.float64).reshape(4, 4)
        dx = float(current[0, 3] - previous[0, 3])
        dy = float(current[1, 3] - previous[1, 3])
        dz = float(current[2, 3] - previous[2, 3])
        t_delta = math.sqrt(dx * dx + dy * dy + dz * dz)
        rotation_trace = sum(float(previous[row, col] * current[row, col]) for row in range(3) for col in range(3))
        r_delta = QuestPosePipeline._rotation_angle_from_trace_deg(rotation_trace)
        return t_delta, r_delta

    @staticmethod
    def _rotation_angle_from_trace_deg(trace: float) -> float:
        """由相对旋转矩阵 trace 计算角度差。"""

        cos_theta = clamp((trace - 1.0) * 0.5, -1.0, 1.0)
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
        server_receive_mono_ms: float = 0.0,
    ) -> PoseObservation:
        """把 pipeline 内部状态打包为 PoseObservation，并附加 reliability score。"""

        diagnostics.phase = phase
        diagnostics.failure_reason = failure_reason
        pose_matrix = self._normalize_pose_matrix(pose)
        actual_has_pose = bool(has_pose and pose_matrix is not None)
        pose_flat = tuple(float(x) for x in pose_matrix.reshape(-1)) if actual_has_pose and pose_matrix is not None else None
        receive_mono_ms = float(decoded.server_receive_mono_ms) if decoded is not None else float(server_receive_mono_ms)
        observation = PoseObservation(
            has_pose=actual_has_pose,
            phase=phase,
            frame_id=decoded.frame_id if decoded is not None else diagnostics.frame_id,
            server_receive_mono_ms=receive_mono_ms,
            pose_matrix_cv_camera=pose_flat,
            pose_source=pose_source,
            tracking_state_hint="TRACKING" if actual_has_pose else "DETECTING",
            stage=self.stage,
            det_count=diagnostics.det_count,
            fps=self._fps,
            depth_valid_ratio=diagnostics.depth_valid_ratio,
            depth_valid_in_mask=diagnostics.depth_valid_in_mask,
            depth_median_m=diagnostics.depth_median_m,
            depth_iqr_m=diagnostics.depth_iqr_m,
            score_reprojection=diagnostics.score_reprojection,
            score_depth=diagnostics.score_depth,
            score_mask=diagnostics.score_mask,
            mask_area_ratio=diagnostics.mask_area_ratio,
            render_quality_evaluated=diagnostics.render_quality_evaluated,
            render_quality_status=diagnostics.render_quality_status,
            color_reprojection=diagnostics.color_reprojection,
            render_quality_mask_iou=diagnostics.render_quality_mask_iou,
            render_quality_depth_inlier=diagnostics.render_quality_depth_inlier,
            render_quality_depth_alignment=diagnostics.render_quality_depth_alignment,
            render_quality_area_ratio_score=diagnostics.render_quality_area_ratio_score,
            render_quality_render_visible_ratio=diagnostics.render_quality_render_visible_ratio,
            render_quality_observed_visible_ratio=diagnostics.render_quality_observed_visible_ratio,
            render_quality_depth_residual_m=diagnostics.render_quality_depth_residual_m,
            render_quality_render_area_px=diagnostics.render_quality_render_area_px,
            last_translation_delta_m=diagnostics.last_translation_delta_m,
            last_rotation_delta_deg=diagnostics.last_rotation_delta_deg,
            frame_dt_s=diagnostics.frame_dt_s,
            track_reject_count=self.tracking_state.track_reject_count,
            yolo_ms=timing.yolo_ms,
            depth_ms=timing.depth_ms,
            cutie_ms=timing.cutie_ms,
            pose_ms=timing.pose_ms,
            total_ms=timing.total_ms,
            failure_reason=failure_reason,
        )
        breakdown = score_observation_breakdown(
            observation,
            config=self.pose_score_config,
        )
        diagnostics.score_reprojection = breakdown.reprojection_score
        diagnostics.score_depth = breakdown.depth_score
        diagnostics.score_mask = breakdown.mask_score
        return replace(
            observation,
            score_reprojection=breakdown.reprojection_score,
            score_depth=breakdown.depth_score,
            score_mask=breakdown.mask_score,
            reliability_score=breakdown.final_score,
            reliability_flags=breakdown.flags,
        )

    @staticmethod
    def _normalize_pose_matrix(pose: np.ndarray | None) -> np.ndarray | None:
        """把 estimator pose 规范为有限 4x4 矩阵；无效时返回 None。"""

        if pose is None:
            return None
        try:
            matrix = np.asarray(pose, dtype=np.float64).reshape(4, 4)
        except (TypeError, ValueError):
            return None
        return matrix if np.all(np.isfinite(matrix)) else None

    def _show_register_mask_snapshot(self, mask: np.ndarray) -> None:
        """每次 register 成功时刷新显示实际用于注册的 mask。"""

        if not self.show_mask_snapshot:
            return
        mask_vis = cv2.cvtColor((mask > 0).astype(np.uint8) * 255, cv2.COLOR_GRAY2BGR)
        cv2.putText(mask_vis, "REGISTER mask", (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 120), 2, cv2.LINE_AA)
        cv2.imshow(self.mask_snapshot_window, mask_vis)

    def _update_fps(self) -> None:
        """更新 pipeline FPS EMA。

        每个真实处理过的帧都应调用（含 register 前的 mask/depth-only 帧），否则
        启动阶段 fps 恒为 0，且首次 track 时 dt 会包含整个启动间隔而算出荒谬低值。
        """

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
        LOGGER.info(
            "pose frame=%s phase=%s has_pose=%s det=%d depth(mask)=%.3f depthAlign=%.2f mask=%.3f score=%.2f fps=%.1f total=%.1fms",
            observation.frame_id,
            observation.phase,
            observation.has_pose,
            diagnostics.det_count,
            diagnostics.depth_valid_in_mask,
            observation.score_depth,
            diagnostics.mask_area_ratio,
            observation.reliability_score,
            observation.fps,
            observation.total_ms,
        )
