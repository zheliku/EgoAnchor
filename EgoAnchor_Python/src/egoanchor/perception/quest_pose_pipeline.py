"""Quest stereo + 可切换分割后端 + FFS + FoundationPose 的 pose pipeline。

本文件实现 Python 侧本地 debug 用的感知主流程。它接收已由 runtime 提供的最新
Quest Protobuf 消息，输出 camera-space PoseObservation 和 OpenCV debug 图像；不
做 ZMQ/NATS 通信，也不做 Unity 坐标转换。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

import cv2
import numpy as np

from egoanchor.algorithms import CutieMaskTracker, FastFoundationStereoDepth, FoundationPoseObjectEstimator, SegmenterResult
from egoanchor.perception import PoseObservation, QuestStereoCalibration, DecodedQuestStereoFrame, decode_quest_stereo_frame, preprocess_stereo_pair
from egoanchor.protocol import quest_pb2
from egoanchor.reliability import score_observation


@dataclass(slots=True)
class PipelineStepTiming:
    """单帧 pipeline 各阶段耗时。"""

    yolo_ms: float = 0.0
    """分割后端耗时，单位毫秒；字段名沿用旧 PoseObservation 契约。"""

    depth_ms: float = 0.0
    """FFS 深度估计耗时，单位毫秒。"""

    cutie_ms: float = 0.0
    """Cutie mask tracker 耗时，单位毫秒。"""

    pose_ms: float = 0.0
    """FoundationPose register/track 耗时，单位毫秒。"""

    total_ms: float = 0.0
    """整帧处理耗时，单位毫秒。"""


class SegmenterBackend(Protocol):
    """QuestPosePipeline 依赖的最小分割后端接口。"""

    def infer(self, image_bgr: np.ndarray, prompt: str | list[str] | None = None) -> SegmenterResult:
        """执行单帧分割并返回统一 SegmenterResult。"""


@dataclass(slots=True)
class AsyncSegmenterJob:
    """提交给后台分割线程的单帧数据包。"""

    decoded: DecodedQuestStereoFrame
    """解码后的 Quest 双目帧元数据和原图。"""

    session_id: str
    """Unity 发布会话 ID，用于丢弃旧 session 结果。"""

    left_bgr: np.ndarray
    """处理分辨率下的左目 BGR 图；SAM3 在该图上生成 mask。"""

    right_bgr: np.ndarray
    """处理分辨率下的右目 BGR 图；后续 FFS 与 register 使用同一帧。"""

    generation: int
    """pipeline reset/calibration 代数；结果回来时必须一致。"""


@dataclass(slots=True)
class AsyncSegmenterOutput:
    """后台分割线程完成的一次结果。"""

    job: AsyncSegmenterJob
    """产生该结果的输入帧包。"""

    result: SegmenterResult | None
    """分割结果；异常时为 None。"""

    elapsed_ms: float
    """后台线程测得的总耗时，单位毫秒。"""

    error: str = ""
    """异常文本；空字符串表示成功。"""


@dataclass(frozen=True, slots=True)
class AsyncSegmenterSnapshot:
    """后台分割 worker 的轻量状态快照。"""

    busy: bool
    """后台线程是否正在推理或已有待处理帧。"""

    submitted: int
    """累计接受的帧数。"""

    completed: int
    """累计完成的推理次数。"""

    dropped: int
    """因为 worker 忙或结果未消费而丢弃的提交次数。"""

    error: str
    """最近一次异常文本。"""


class AsyncSegmenterWorker:
    """单线程 latest-only 分割 worker。

    worker 只运行 SAM3/分割模型，不运行 FFS、FoundationPose 或 Cutie。完成后主
    pipeline 线程会用同一帧的 left/right RGB 与 mask 继续 register，避免 RGB/mask
    错帧。
    """

    def __init__(self, segmenter: SegmenterBackend) -> None:
        """保存分割器并初始化线程同步状态。"""

        self.segmenter = segmenter
        """实际分割后端。"""

        self._condition = threading.Condition()
        """保护 pending/completed 状态的条件变量。"""

        self._pending: AsyncSegmenterJob | None = None
        """等待后台处理的最新帧。"""

        self._completed_output: AsyncSegmenterOutput | None = None
        """等待主线程消费的最新完成结果。"""

        self._busy = False
        """后台线程是否正在推理。"""

        self._stopping = False
        """后台线程停止标记。"""

        self._submitted = 0
        """累计接受帧数。"""

        self._completed = 0
        """累计完成推理次数。"""

        self._dropped = 0
        """丢弃提交次数。"""

        self._error = ""
        """最近一次异常文本。"""

        self._thread = threading.Thread(target=self._run, name="EgoAnchorAsyncSegmenter", daemon=True)
        """后台分割线程。"""

    def start(self) -> None:
        """启动后台分割线程。"""

        self._thread.start()

    def stop(self) -> None:
        """请求后台线程退出并等待短暂收尾。"""

        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        self._thread.join(timeout=2.0)

    def clear(self) -> None:
        """丢弃未开始处理的帧和未消费结果；正在推理的帧靠 generation 过滤。"""

        with self._condition:
            self._pending = None
            self._completed_output = None
            self._error = ""

    def submit(self, job: AsyncSegmenterJob) -> bool:
        """提交一帧给后台；忙或旧结果未消费时返回 False。"""

        with self._condition:
            if self._busy or self._pending is not None or self._completed_output is not None:
                self._dropped += 1
                return False
            self._pending = AsyncSegmenterJob(
                decoded=job.decoded,
                session_id=job.session_id,
                left_bgr=job.left_bgr.copy(),
                right_bgr=job.right_bgr.copy(),
                generation=int(job.generation),
            )
            self._submitted += 1
            self._condition.notify()
            return True

    def take_completed(self) -> AsyncSegmenterOutput | None:
        """取走最新完成结果；没有结果时返回 None。"""

        with self._condition:
            output = self._completed_output
            self._completed_output = None
            return output

    def snapshot(self) -> AsyncSegmenterSnapshot:
        """返回 worker 当前状态快照。"""

        with self._condition:
            return AsyncSegmenterSnapshot(
                busy=self._busy or self._pending is not None,
                submitted=self._submitted,
                completed=self._completed,
                dropped=self._dropped,
                error=self._error,
            )

    def _run(self) -> None:
        """后台线程主循环。"""

        while True:
            with self._condition:
                while self._pending is None and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                job = self._pending
                self._pending = None
                self._busy = True

            t0 = time.perf_counter()
            try:
                result = self.segmenter.infer(job.left_bgr)
                error = ""
            except Exception as exc:
                result = None
                error = f"{type(exc).__name__}: {exc}"
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            with self._condition:
                self._busy = False
                self._completed_output = AsyncSegmenterOutput(job=job, result=result, elapsed_ms=elapsed_ms, error=error)
                self._completed += 1
                if error:
                    self._error = error


@dataclass(slots=True)
class FrameDiagnostics:
    """用于 debug 显示的中间图像和诊断数值。"""

    left_bgr: np.ndarray | None = None
    """处理分辨率下的左目 BGR 图。"""

    right_bgr: np.ndarray | None = None
    """处理分辨率下的右目 BGR 图。"""

    mask: np.ndarray | None = None
    """当前使用的二值 mask。"""

    segmentation_overlay_bgr: np.ndarray | None = None
    """分割后端原始 overlay 图。"""

    depth: np.ndarray | None = None
    """FFS 输出深度图，单位米。"""

    pose_vis_bgr: np.ndarray | None = None
    """FoundationPose 可视化图。"""

    stage: int = 4
    """当前 debug stage。"""

    phase: str = "WAIT_STREAM"
    """当前 pipeline phase。"""

    frame_id: int | None = None
    """当前处理帧 frame_id。"""

    det_count: int = 0
    """分割后端返回的检测数量。"""

    mask_area_ratio: float = 0.0
    """mask 面积比例。"""

    mask_source: str = "none"
    """当前 mask 来源：none、yoloe、sam3 或 cutie。"""

    cutie_bbox_xywh: tuple[int, int, int, int] = (-1, -1, 0, 0)
    """Cutie 输出 bbox，用于 debug 可视化。"""

    depth_valid_ratio: float = 0.0
    """全图有效深度比例。"""

    depth_valid_in_mask: float = 0.0
    """mask 内有效深度比例。"""

    depth_median_in_mask: float = 0.0
    """mask 内深度中位数。"""

    depth_iqr_in_mask: float = 0.0
    """mask 内深度 IQR。"""

    fps: float = 0.0
    """pipeline FPS EMA。"""

    failure_reason: str = ""
    """当前帧失败原因。"""

    segmenter_async: bool = False
    """当前分割后端是否使用后台异步推理。"""

    segmenter_busy: bool = False
    """后台分割线程是否忙。"""

    segmenter_submitted: int = 0
    """异步分割累计提交帧数。"""

    segmenter_completed: int = 0
    """异步分割累计完成次数。"""

    segmenter_dropped: int = 0
    """异步分割因忙而丢弃的提交次数。"""

    segmenter_error: str = ""
    """异步分割最近一次异常。"""

    timing: PipelineStepTiming = field(default_factory=PipelineStepTiming)
    """当前帧耗时。"""


@dataclass(slots=True)
class QuestPosePipelineOutput:
    """Quest pose pipeline 的单次处理输出。"""

    observation: PoseObservation | None
    """camera-space pose observation；无输入时可为 None。"""

    diagnostics: FrameDiagnostics
    """OpenCV debug 所需中间结果。"""

    timing: PipelineStepTiming
    """单帧耗时统计。"""

    new_frame_processed: bool
    """本次调用是否实际处理了新的 stereo frame。"""


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
        re_register_on_track_lost: bool = True,
        pose_jump_translation_m: float = 0.25,
        pose_jump_rotation_deg: float = 35.0,
        accept_track_jump_without_mask: bool = False,
        max_consecutive_track_rejects: int = 3,
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

        self._has_registered = False
        """FoundationPose 是否已经 register。"""

        self._cutie_ready = False
        """Cutie 是否已经用当前目标初始化。"""

        self._last_pose: np.ndarray | None = None
        """上一帧接受的 4x4 pose，用于跳变检测。"""

        self._last_frame_id: int | None = None
        """上一帧处理过的 frame_id，避免重复处理。"""

        self._last_session_id = ""
        """上一帧处理过的 Unity 发布会话 ID，用于识别 Unity 重启后的 frame_id 回绕。"""

        self._track_reject_count = 0
        """连续 track reject 次数。"""

        self._fps = 0.0
        """pipeline FPS EMA。"""

        self._last_process_time: float | None = None
        """上一帧处理完成时间，用于 FPS 估计。"""

        self._processed_count = 0
        """累计处理帧数。"""

        self._mask_snapshot_shown = False
        """mask snapshot 是否已经显示过。"""

        self._generation = 0
        """pipeline tracking generation；reset/calibration 后递增，用于过滤旧异步结果。"""

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

        self._generation += 1
        self._has_registered = False
        self._cutie_ready = False
        self._last_pose = None
        self._last_frame_id = None
        self._last_session_id = ""
        self._track_reject_count = 0
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

        session_id = self._extract_session_id(stereo_msg)
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
            timing.total_ms = (time.perf_counter() - t_total) * 1000.0
            obs = self._make_observation(decoded, diagnostics.phase, False, None, "NONE", diagnostics, timing, failure_reason="wait_calibration")
            return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=True)

        if self.async_segmentation and not self._has_registered:
            job = AsyncSegmenterJob(
                decoded=decoded,
                session_id=session_id,
                left_bgr=left_bgr,
                right_bgr=right_bgr,
                generation=self._generation,
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
        current_timing.total_ms = (time.perf_counter() - t_total) * 1000.0
        return QuestPosePipelineOutput(observation=None, diagnostics=current_diagnostics, timing=current_timing, new_frame_processed=True)

    def _take_ready_async_segmentation(self, t_total: float) -> QuestPosePipelineOutput | None:
        """若后台分割已有完成结果，则用结果所属帧继续 pipeline。"""

        worker = self._segmenter_worker
        if not self.async_segmentation or worker is None or self._has_registered:
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
            result_timing.total_ms = (time.perf_counter() - t_total) * 1000.0
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

        same_generation = result_job.generation == self._generation
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

        mask: np.ndarray | None = None
        if not self._has_registered:
            seg_result = async_seg_result if async_seg_result is not None else self._run_segmenter(left_bgr, timing)
            diagnostics.det_count = int(seg_result.det_count)
            diagnostics.segmentation_overlay_bgr = seg_result.overlay_bgr
            diagnostics.mask_area_ratio = float(seg_result.mask_area_ratio)
            if seg_result.mask_bw is not None and seg_result.mask_area_ratio > 0.0:
                mask = (seg_result.mask_bw > 0).astype(np.uint8)
                diagnostics.mask = mask
                diagnostics.mask_source = self.segmenter_name
                self._show_mask_snapshot_once(mask)

            if self.stage <= 2:
                timing.total_ms = (time.perf_counter() - t_total) * 1000.0
                obs = self._make_observation(decoded, "MASK_ONLY", False, None, "NONE", diagnostics, timing, failure_reason="stage_mask_only")
                return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=True)

            if mask is None:
                diagnostics.phase = "NO_MASK"
                timing.total_ms = (time.perf_counter() - t_total) * 1000.0
                obs = self._make_observation(decoded, diagnostics.phase, False, None, "NONE", diagnostics, timing, failure_reason="no_mask")
                return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=True)
        else:
            mask, cutie_bbox = self._track_cutie_mask(rgb, timing)
            diagnostics.cutie_bbox_xywh = tuple(int(v) for v in cutie_bbox)
            if mask is not None:
                diagnostics.mask = mask
                diagnostics.mask_source = "cutie"
                diagnostics.mask_area_ratio = float(np.count_nonzero(mask > 0)) / float(mask.size) if mask.size else 0.0

            if self.stage <= 2:
                timing.total_ms = (time.perf_counter() - t_total) * 1000.0
                obs = self._make_observation(decoded, "TRACK_MASK_ONLY", False, None, "NONE", diagnostics, timing, failure_reason="stage_mask_only")
                return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=True)

        depth = self._predict_depth(rgb, right_rgb, timing)
        depth = self._filter_depth(depth)
        diagnostics.depth = depth
        self._update_depth_diagnostics(diagnostics, depth, mask)

        if self.stage <= 3:
            timing.total_ms = (time.perf_counter() - t_total) * 1000.0
            obs = self._make_observation(decoded, "DEPTH_ONLY", False, None, "NONE", diagnostics, timing, failure_reason="stage_depth_only")
            return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=True)

        if not self._has_registered and diagnostics.depth_valid_in_mask < self.register_min_depth_valid_in_mask:
            diagnostics.phase = "REJECT_DEPTH"
            timing.total_ms = (time.perf_counter() - t_total) * 1000.0
            obs = self._make_observation(decoded, diagnostics.phase, False, None, "NONE", diagnostics, timing, failure_reason="depth_in_mask_low")
            return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=True)

        pose, pose_source, phase = self._estimate_pose(rgb, depth, mask, timing)
        diagnostics.phase = phase
        has_pose = pose is not None
        if pose is not None and self.estimator is not None:
            pose_vis_rgb = self.estimator.visualize_pose(rgb, pose)
            diagnostics.pose_vis_bgr = cv2.cvtColor(pose_vis_rgb, cv2.COLOR_RGB2BGR)

        timing.total_ms = (time.perf_counter() - t_total) * 1000.0
        self._update_fps()
        diagnostics.fps = self._fps
        diagnostics.timing = timing
        obs = self._make_observation(decoded, phase, has_pose, pose, pose_source, diagnostics, timing, failure_reason="" if has_pose else phase.lower())
        self._log_stats(diagnostics, obs)
        return QuestPosePipelineOutput(observation=obs, diagnostics=diagnostics, timing=timing, new_frame_processed=True)

    @staticmethod
    def _extract_session_id(stereo_msg: quest_pb2.QuestStereoFrame) -> str:
        """从 stereo message header 中提取 Unity 发布会话 ID；缺失时返回空字符串。"""

        if not stereo_msg.HasField("header"):
            return ""
        return str(getattr(stereo_msg.header, "session_id", ""))

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
        self._generation += 1
        self._has_registered = False
        self._last_pose = None
        self._track_reject_count = 0
        self._cutie_ready = False
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

    def _estimate_pose(self, rgb: np.ndarray, depth: np.ndarray, mask: np.ndarray | None, timing: PipelineStepTiming) -> tuple[np.ndarray | None, str, str]:
        """根据当前状态选择 register、track 或 re-register。"""

        if not self._has_registered:
            if mask is None or np.count_nonzero(mask) <= 0:
                return None, "NONE", "NO_MASK"
            return self._try_register(rgb, depth, mask, timing, pose_source="REGISTER", phase="REGISTER")

        t_pose = time.perf_counter()
        try:
            pose = self.estimator.track(rgb, depth)
            timing.pose_ms = (time.perf_counter() - t_pose) * 1000.0
        except Exception as exc:
            logging.warning("FoundationPose track 失败: %s", exc)
            self._has_registered = False
            self.estimator.reset()
            self._track_reject_count += 1
            if self.re_register_on_track_lost and mask is not None and np.count_nonzero(mask) > 0:
                return self._try_register(rgb, depth, mask, timing, pose_source="RE_REGISTER", phase="RE_REGISTER")
            return None, "NONE", "TRACK_FAILED"

        if self._is_track_jump(pose):
            self._track_reject_count += 1
            logging.warning("FoundationPose track pose 跳变，尝试 re-register。reject_count=%d", self._track_reject_count)
            self._has_registered = False
            self.estimator.reset()
            if self.re_register_on_track_lost and mask is not None and np.count_nonzero(mask) > 0:
                return self._try_register(rgb, depth, mask, timing, pose_source="RE_REGISTER", phase="RE_REGISTER")
            if self.accept_track_jump_without_mask and self._track_reject_count < self.max_consecutive_track_rejects:
                self._has_registered = True
                self._last_pose = pose
                logging.warning("FoundationPose track pose 跳变但无 re-register mask，暂时接受该 pose。")
                return pose, "TRACK_ACCEPTED_JUMP", "TRACK_ACCEPTED_JUMP"
            return None, "NONE", "TRACK_REJECT"

        self._track_reject_count = 0
        self._last_pose = pose
        return pose, "TRACK", "TRACK"

    def _try_register(self, rgb: np.ndarray, depth: np.ndarray, mask: np.ndarray, timing: PipelineStepTiming, pose_source: str, phase: str) -> tuple[np.ndarray | None, str, str]:
        """执行 FoundationPose register，并初始化可选 Cutie。"""

        t_pose = time.perf_counter()
        try:
            pose = self.estimator.register(rgb, depth, mask)
            timing.pose_ms += (time.perf_counter() - t_pose) * 1000.0
        except Exception as exc:
            timing.pose_ms += (time.perf_counter() - t_pose) * 1000.0
            self._has_registered = False
            logging.warning("FoundationPose register 失败: %s", exc)
            return None, "NONE", "REGISTER_FAILED"

        self._has_registered = True
        self._last_pose = pose
        self._track_reject_count = 0
        self._initialize_cutie(rgb, mask, timing)
        return pose, pose_source, phase

    def _track_cutie_mask(self, rgb: np.ndarray, timing: PipelineStepTiming) -> tuple[np.ndarray | None, list[int]]:
        """已 register 后用 Cutie 传播 2D mask，并可用 bbox 中心辅助 FoundationPose。

        注意：这里不再要求 YOLOE 每帧检测成功。YOLOE 只负责初始注册或丢失后重新
        获取目标；正常跟踪阶段依赖 Cutie 维持 2D mask，FoundationPose 继续用上一帧
        pose_last 做 6D track，因此目标短时转角、遮挡或 YOLOE 漏检不会直接导致 pose 消失。
        """

        empty_bbox = [-1, -1, 0, 0]
        if not self.cutie_enabled or self.cutie is None or not self._cutie_ready:
            return None, empty_bbox
        t_cutie = time.perf_counter()
        try:
            track_result = self.cutie.track(rgb)
            timing.cutie_ms += (time.perf_counter() - t_cutie) * 1000.0
        except Exception as exc:
            timing.cutie_ms += (time.perf_counter() - t_cutie) * 1000.0
            self._cutie_ready = False
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
            self._cutie_ready = True
        except Exception as exc:
            self._cutie_ready = False
            logging.warning("Cutie 初始化失败，将跳过 2D mask tracking: %s", exc)

    def _is_track_jump(self, pose: np.ndarray) -> bool:
        """检测相邻帧 pose 是否出现过大跳变。"""

        if self._last_pose is None:
            return False
        t_delta = float(np.linalg.norm(pose[:3, 3] - self._last_pose[:3, 3]))
        r_delta = self._rotation_angle_deg(self._last_pose[:3, :3].T @ pose[:3, :3])
        return t_delta > self.pose_jump_translation_m or r_delta > self.pose_jump_rotation_deg

    @staticmethod
    def _rotation_angle_deg(rotation_delta: np.ndarray) -> float:
        """由相对旋转矩阵计算角度差。"""

        trace = float(np.trace(rotation_delta))
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
            track_reject_count=self._track_reject_count,
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

