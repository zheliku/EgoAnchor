"""Quest stereo + 可切换分割后端 + FFS + FoundationPose 的 pose pipeline。

本文件实现 Python 侧本地 debug 用的感知主流程。它接收已由 runtime 提供的最新
Quest Protobuf 消息，输出 camera-space PoseObservation 和 OpenCV debug 图像；不
做 ZMQ/NATS 通信，也不做 Unity 坐标转换。
"""

from __future__ import annotations

import logging
import time

import cv2
import numpy as np

from egoanchor.algorithms import CutieMaskTracker, FastFoundationStereoDepth, FoundationPoseObjectEstimator, SegmenterResult
from egoanchor.perception import (
    AsyncSegmenterJob,
    AsyncSegmenterWorker,
    DecodedQuestStereoFrame,
    FrameDiagnostics,
    MaskSource,
    PipelineStepTiming,
    PipelineTrackingState,
    QuestStereoCalibration,
    QuestPosePipelineOutput,
    SegmenterBackend,
    decode_quest_stereo_frame,
    preprocess_stereo_pair,
)
from egoanchor.perception.pipeline_helpers import QuestPosePipelineHelpers
from egoanchor.protocol import extract_session_id, quest_pb2


class QuestPosePipeline(QuestPosePipelineHelpers):
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
        re_register_on_track_lost: bool = True,
        pose_jump_translation_m: float = 0.25,
        pose_jump_rotation_deg: float = 35.0,
        accept_track_jump_without_mask: bool = False,
        max_consecutive_track_rejects: int = 3,
        tracked_mask_lost_frames: int = 3,
        cutie_enabled: bool = False,
        cutie_adjust_pose: bool = False,
        log_stats_interval: int = 60,
        show_mask_snapshot: bool = False,
        mask_snapshot_window: str = "EgoAnchor mask",
        async_segmentation: bool = False,
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

        self.re_register_on_track_lost = bool(re_register_on_track_lost)
        """track 丢失或跳变时是否尝试 re-register。"""

        self.pose_jump_translation_m = float(pose_jump_translation_m)
        """track pose 平移跳变 reject 阈值，单位米。"""

        self.pose_jump_rotation_deg = float(pose_jump_rotation_deg)
        """track pose 旋转跳变 reject 阈值，单位度。"""

        self.accept_track_jump_without_mask = bool(accept_track_jump_without_mask)
        """track 跳变但没有 re-register mask 时是否暂时接受该 pose。"""

        self.max_consecutive_track_rejects = max(1, int(max_consecutive_track_rejects))
        """连续 track reject 达到该值后强制回到 detect/register。"""

        self.tracked_mask_lost_frames = max(0, int(tracked_mask_lost_frames))
        """已注册后连续多少帧没有有效 Cutie mask 时主动回到 detect/register；0 表示关闭。"""

        self.cutie_enabled = bool(cutie_enabled)
        """是否启用 Cutie mask 传播。"""

        self.cutie_adjust_pose = bool(cutie_adjust_pose)
        """是否用 Cutie bbox 中心轻量修正 pose x/y。"""

        self.log_stats_interval = int(log_stats_interval)
        """每隔多少帧打印一次 pipeline 诊断。"""

        self.show_mask_snapshot = bool(show_mask_snapshot)
        """是否在首次获得 mask 时弹出独立 snapshot 窗口。"""

        self.mask_snapshot_window = str(mask_snapshot_window)
        """mask snapshot 窗口名。"""

        self.async_segmentation = bool(async_segmentation)
        """是否把初始分割阶段放到后台线程。"""

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

        self._mask_snapshot_shown = False
        """mask snapshot 是否已经显示过。"""

    def set_stage(self, stage: int) -> None:
        """设置 debug stage，并限制在 1..4。"""

        self.stage = max(1, min(4, int(stage)))

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
        logging.info("pose pipeline tracking state reset")

    def process(self, stereo_msg: quest_pb2.QuestStereoFrame | None, camera_info_msg: quest_pb2.QuestCameraInfo | None) -> QuestPosePipelineOutput:
        """处理最新 Quest stereo/camera_info 并返回 debug 输出。"""

        timing = PipelineStepTiming()
        diagnostics = FrameDiagnostics(stage=self.stage, timing=timing)
        t_total = time.perf_counter()

        if camera_info_msg is not None:
            self._refresh_calibration(camera_info_msg)

        ready_output = self._take_ready_async_segmentation(t_total)
        if ready_output is not None:
            return ready_output

        if stereo_msg is None:
            diagnostics.phase = "WAIT_STREAM"
            return QuestPosePipelineOutput(observation=None, diagnostics=diagnostics, timing=timing, new_frame_processed=False)

        decoded = decode_quest_stereo_frame(stereo_msg)
        if decoded is None:
            diagnostics.phase = "DECODE_FAILED"
            obs = self._make_observation(None, "DECODE_FAILED", False, None, "NONE", diagnostics, timing, failure_reason="decode_failed")
            return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=False)

        session_id = extract_session_id(stereo_msg)
        same_session = not session_id or not self._last_session_id or session_id == self._last_session_id
        if same_session and decoded.frame_id is not None and decoded.frame_id == self._last_frame_id:
            ready_output = self._take_ready_async_segmentation(t_total)
            if ready_output is not None:
                return ready_output
            diagnostics.phase = "DUPLICATE_FRAME"
            diagnostics.frame_id = decoded.frame_id
            return QuestPosePipelineOutput(observation=None, diagnostics=diagnostics, timing=timing, new_frame_processed=False)

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
        current_timing.finalize(t_total)
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

        if completed.error:
            result_diagnostics.phase = "SEGMENTATION_FAILED"
            result_timing.finalize(t_total)
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

        same_generation = result_job.generation == self.tracking_state.generation
        same_session = not self._last_session_id or not result_job.session_id or result_job.session_id == self._last_session_id
        if completed.result is None or not same_generation or not same_session:
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
        self._apply_segmenter_snapshot(diagnostics)

        rgb = cv2.cvtColor(left_bgr, cv2.COLOR_BGR2RGB)
        right_rgb = cv2.cvtColor(right_bgr, cv2.COLOR_BGR2RGB)

        mask, early_output = self._run_detect_stage(decoded, left_bgr, rgb, diagnostics, timing, t_total, async_seg_result)
        if early_output is not None:
            return early_output

        depth, early_output = self._run_depth_stage(decoded, rgb, right_rgb, mask, diagnostics, timing, t_total)
        if early_output is not None:
            return early_output

        early_output = self._run_register_stage(decoded, left_bgr, rgb, depth, mask, diagnostics, timing, t_total)
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
        """执行 detect 或 Cutie mask 阶段；stage<=2 时直接返回输出。"""

        if not self.tracking_state.has_registered:
            mask = self._detect_initial_mask(left_bgr, diagnostics, timing, async_seg_result)
            if self.stage <= 2:
                return mask, self._finish_frame(decoded, "MASK_ONLY", False, None, "NONE", diagnostics, timing, t_total, "stage_mask_only")
            if mask is None:
                return None, self._finish_frame(decoded, "NO_MASK", False, None, "NONE", diagnostics, timing, t_total, "no_mask")
            return mask, None

        mask, cutie_bbox = self._track_cutie_mask(rgb, timing)
        diagnostics.cutie_bbox_xywh = tuple(int(v) for v in cutie_bbox)
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
        self._show_mask_snapshot_once(mask)
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
        left_bgr: np.ndarray,
        rgb: np.ndarray,
        depth: np.ndarray,
        mask: np.ndarray | None,
        diagnostics: FrameDiagnostics,
        timing: PipelineStepTiming,
        t_total: float,
    ) -> QuestPosePipelineOutput | None:
        """执行丢失恢复和 register 前置检查；无早退时返回 None。"""

        recovery = self._try_recover_from_tracked_mask_loss(left_bgr, rgb, depth, mask, diagnostics, timing)
        if recovery is not None:
            pose, pose_source, phase = recovery
            return self._finish_frame(
                decoded,
                phase,
                pose is not None,
                pose,
                pose_source,
                diagnostics,
                timing,
                t_total,
                "" if pose is not None else phase.lower(),
                rgb=rgb,
                update_fps=True,
            )

        if not self.tracking_state.has_registered and diagnostics.depth_valid_in_mask < self.register_min_depth_valid_in_mask:
            return self._finish_frame(decoded, "REJECT_DEPTH", False, None, "NONE", diagnostics, timing, t_total, "depth_in_mask_low")
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

        pose, pose_source, phase = self._estimate_pose(rgb, depth, mask, timing)
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
            update_fps=True,
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
        update_fps: bool = False,
    ) -> QuestPosePipelineOutput:
        """收尾单帧输出，统一写 total_ms、fps、pose 可视化与 observation。"""

        diagnostics.phase = phase
        if pose is not None and self.estimator is not None:
            if rgb is None:
                raise RuntimeError("生成 pose 可视化时缺少 RGB 图像。")
            pose_vis_rgb = self.estimator.visualize_pose(rgb, pose)
            diagnostics.pose_vis_bgr = cv2.cvtColor(pose_vis_rgb, cv2.COLOR_RGB2BGR)

        timing.finalize(t_total)
        if update_fps:
            self._update_fps()
        diagnostics.fps = self._fps
        diagnostics.timing = timing
        obs = self._make_observation(decoded, phase, has_pose, pose, pose_source, diagnostics, timing, failure_reason=failure_reason)
        if update_fps:
            self._log_stats(diagnostics, obs)
        return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=True)
