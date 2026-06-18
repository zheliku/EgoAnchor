"""QuestPosePipeline 分割后端接入测试。"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import cv2
import numpy as np

from egoanchor.algorithms import SegmenterResult
from egoanchor.protocol import common_pb2, quest_pb2
from egoanchor.perception import AsyncSegmenterJob, AsyncSegmenterOutput, DecodedQuestStereoFrame, FrameDiagnostics, PipelineStepTiming, QuestPosePipeline


class _FakeSegmenter:
    """单测用分割器，避免加载真实 YOLOE/SAM3。"""

    def __init__(self, delay_s: float = 0.0) -> None:
        """保存可选延迟，用于模拟 SAM3 慢推理。"""

        self.delay_s = float(delay_s)
        self.calls = 0

    def infer(self, image_bgr: np.ndarray, prompt: str | list[str] | None = None) -> SegmenterResult:
        """返回固定的单目标 mask。"""

        self.calls += 1
        if self.delay_s > 0.0:
            time.sleep(self.delay_s)
        mask = np.zeros(image_bgr.shape[:2], dtype=np.uint8)
        mask[1:3, 2:4] = 255
        return SegmenterResult(
            overlay_bgr=image_bgr.copy(),
            mask_bw=mask,
            det_count=1,
            infer_ms=1.5,
            prompt=["unit test"],
            selected_index=0,
            mask_area_ratio=float(np.count_nonzero(mask)) / float(mask.size),
        )


class _EmptySegmenter:
    """单测用空分割器，模拟启动阶段尚未找到目标。"""

    def __init__(self) -> None:
        """初始化调用计数。"""

        self.calls = 0

    def infer(self, image_bgr: np.ndarray, prompt: str | list[str] | None = None) -> SegmenterResult:
        """返回无 mask 的分割结果。"""

        self.calls += 1
        return SegmenterResult(
            overlay_bgr=image_bgr.copy(),
            mask_bw=None,
            det_count=0,
            infer_ms=1.0,
            prompt=["unit test"],
            selected_index=-1,
            mask_area_ratio=0.0,
        )


class _FakeDepthEstimator:
    """单测用深度估计器，返回稳定小深度图。"""

    def __init__(self) -> None:
        """初始化调用计数。"""

        self.calls = 0

    def predict_depth(self, left_rgb: np.ndarray, right_rgb: np.ndarray, fx: float, baseline: float) -> np.ndarray:
        """返回全图有效深度，避免真实 FFS 依赖。"""

        self.calls += 1
        return np.full(left_rgb.shape[:2], 1.0, dtype=np.float32)


class _FakeFoundationPoseEstimator:
    """单测用 FoundationPose 估计器，记录 register 输入。"""

    def __init__(self, fail_visualize: bool = False) -> None:
        """初始化 register 记录。"""

        self.register_calls: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        self.fail_visualize = bool(fail_visualize)
        """是否让 visualize_pose 抛异常，用于验证 debug 失败不影响 pose 输出。"""

    def update_camera_matrix(self, cam_k: np.ndarray) -> None:
        """测试中不需要真实相机矩阵更新。"""

    def reset(self) -> None:
        """测试中不需要真实重置逻辑。"""

    def register(self, rgb: np.ndarray, depth: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """记录 FoundationPose 收到的 RGB、depth 和 mask。"""

        self.register_calls.append((rgb.copy(), depth.copy(), mask.copy()))
        return np.eye(4, dtype=np.float64)

    def track(self, rgb: np.ndarray, depth: np.ndarray) -> np.ndarray:
        """返回固定 pose，避免真实 FoundationPose 依赖。"""

        return np.eye(4, dtype=np.float64)

    def visualize_pose(self, rgb: np.ndarray, pose: np.ndarray) -> np.ndarray:
        """直接返回输入图，避免绘制依赖。"""

        if self.fail_visualize:
            raise RuntimeError("visualize failed")
        return rgb.copy()


class _InvalidRegisterPoseEstimator(_FakeFoundationPoseEstimator):
    """单测用 FoundationPose 估计器，register 返回非有限 pose。"""

    def register(self, rgb: np.ndarray, depth: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """返回包含 NaN 的 4x4 pose，模拟模型异常输出。"""

        pose = super().register(rgb, depth, mask)
        pose[0, 3] = np.nan
        return pose


class _InvalidTrackPoseEstimator(_FakeFoundationPoseEstimator):
    """单测用 FoundationPose 估计器，track 返回非有限 pose。"""

    def track(self, rgb: np.ndarray, depth: np.ndarray) -> np.ndarray:
        """返回包含 NaN 的 4x4 pose，模拟 track 阶段异常输出。"""

        pose = np.eye(4, dtype=np.float64)
        pose[1, 3] = np.nan
        return pose


class _EmptyCutieTracker:
    """单测用 Cutie；初始化成功，但 track 时连续返回空 mask。"""

    def reset(self) -> None:
        """测试中不需要真实重置。"""

    def initialize(self, rgb: np.ndarray, init_mask: np.ndarray) -> None:
        """测试中不需要真实初始化。"""

    def track(self, rgb: np.ndarray) -> SimpleNamespace:
        """返回空 mask，模拟目标出镜或 Cutie 丢失目标。"""

        return SimpleNamespace(mask=np.zeros(rgb.shape[:2], dtype=np.uint8), bbox_xywh=[-1, -1, 0, 0])


class _CompletedAsyncWorker:
    """单测用异步 worker，只返回预置 completed output。"""

    def __init__(self, completed: AsyncSegmenterOutput) -> None:
        """保存待消费的异步分割结果。"""

        self.completed = completed

    def take_completed(self) -> AsyncSegmenterOutput | None:
        """模拟 AsyncSegmenterWorker.take_completed。"""

        completed = self.completed
        self.completed = None
        return completed

    def snapshot(self) -> SimpleNamespace:
        """返回 diagnostics 需要的最小状态快照。"""

        return SimpleNamespace(busy=False, submitted=1, completed=1, dropped=0, error="")


def _make_stereo_frame(frame_id: int, color_bgr: tuple[int, int, int]) -> quest_pb2.QuestStereoFrame:
    """创建带 JPEG 的最小 QuestStereoFrame。"""

    image = np.full((8, 8, 3), color_bgr, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    if not ok:
        raise RuntimeError("测试 JPEG 编码失败。")
    return quest_pb2.QuestStereoFrame(
        header=common_pb2.MessageHeader(frame_id=frame_id, session_id="unit"),
        left_image_jpeg=encoded.tobytes(),
        right_image_jpeg=encoded.tobytes(),
        left_width=8,
        left_height=8,
        right_width=8,
        right_height=8,
    )


def _make_camera_info() -> quest_pb2.QuestCameraInfo:
    """创建可通过 calibration 映射的最小 QuestCameraInfo。"""

    return quest_pb2.QuestCameraInfo(
        header=common_pb2.MessageHeader(frame_id=0, session_id="unit"),
        is_supported=True,
        left_fx=8.0,
        left_fy=8.0,
        left_cx=4.0,
        left_cy=4.0,
        right_fx=8.0,
        right_fy=8.0,
        right_cx=4.0,
        right_cy=4.0,
        baseline_m=0.05,
        sensor_width=8,
        sensor_height=8,
        current_width=8,
        current_height=8,
    )


def _make_decoded_frame(frame_id: int) -> DecodedQuestStereoFrame:
    """创建无需 JPEG 解码的最小 decoded stereo frame。"""

    image = np.zeros((8, 8, 3), dtype=np.uint8)
    return DecodedQuestStereoFrame(
        frame_id=frame_id,
        sender_mono_ms=None,
        unity_frame=None,
        left_bgr=image,
        right_bgr=image,
    )


class QuestPosePipelineSegmenterTest(unittest.TestCase):
    """验证 pipeline 对分割后端只依赖统一接口。"""

    def test_track_deltas_reports_translation_and_rotation(self) -> None:
        """相邻 pose 的平移和旋转增量应稳定供可靠性评分使用。"""

        previous = np.eye(4, dtype=np.float64)
        current = np.eye(4, dtype=np.float64)
        current[0, 3] = 0.3
        current[:3, :3] = np.array(
            [
                [0.0, -1.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )

        translation_m, rotation_deg = QuestPosePipeline._track_deltas(current, previous)

        self.assertAlmostEqual(translation_m, 0.3)
        self.assertAlmostEqual(rotation_deg, 90.0)

    def test_segmenter_name_is_used_as_mask_source(self) -> None:
        """SAM3 后端进入 pipeline 时 diagnostics.mask_source 应显示 sam3。"""

        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(),
            segmenter_name="sam3",
            depth_estimator=object(),
            foundationpose_estimator=object(),
            cutie_tracker=None,
            process_width=4,
            process_height=4,
        )
        diagnostics = FrameDiagnostics()
        timing = PipelineStepTiming()
        result = pipeline._run_segmenter(np.zeros((4, 4, 3), dtype=np.uint8), timing)
        if result.mask_area_ratio > 0.0:
            diagnostics.mask_source = pipeline.segmenter_name

        self.assertEqual(diagnostics.mask_source, "sam3")
        self.assertEqual(timing.yolo_ms, 1.5)

    def test_startup_without_mask_still_predicts_depth(self) -> None:
        """启动阶段未找到目标 mask 时也应运行 FFS depth，避免 depth 面板黑屏。"""

        depth_estimator = _FakeDepthEstimator()
        pipeline = QuestPosePipeline(
            segmenter=_EmptySegmenter(),
            segmenter_name="yoloe26",
            depth_estimator=depth_estimator,
            foundationpose_estimator=_FakeFoundationPoseEstimator(),
            cutie_tracker=None,
            process_width=8,
            process_height=8,
        )

        output = pipeline.process(_make_stereo_frame(1, (10, 20, 30)), _make_camera_info(), server_receive_mono_ms=222.5)

        self.assertIsNotNone(output.observation)
        self.assertFalse(output.observation.has_pose)
        self.assertEqual(output.observation.phase, "NO_MASK")
        self.assertAlmostEqual(output.observation.server_receive_mono_ms, 222.5)
        self.assertEqual(depth_estimator.calls, 1)
        self.assertIsNotNone(output.diagnostics.depth)
        self.assertGreater(float(np.mean(output.diagnostics.depth)), 0.0)

    def test_fps_is_reported_before_tracking_is_established(self) -> None:
        """register 前的帧（NO_MASK 等）也应统计 fps，否则启动阶段 HUD 一直 fps=0。"""

        pipeline = QuestPosePipeline(
            segmenter=_EmptySegmenter(),
            segmenter_name="yoloe26",
            depth_estimator=_FakeDepthEstimator(),
            foundationpose_estimator=_FakeFoundationPoseEstimator(),
            cutie_tracker=None,
            process_width=8,
            process_height=8,
        )
        camera_info = _make_camera_info()

        first = pipeline.process(_make_stereo_frame(1, (10, 20, 30)), camera_info, server_receive_mono_ms=10.0)
        # 第一帧建立计时基线，第二帧才有 dt 可算 fps（此时仍未建立 track）。
        second = pipeline.process(_make_stereo_frame(2, (12, 22, 32)), camera_info, server_receive_mono_ms=20.0)

        self.assertEqual(first.observation.phase, "NO_MASK")
        self.assertEqual(second.observation.phase, "NO_MASK")
        self.assertFalse(second.observation.has_pose)
        # 关键断言：追踪建立前 fps 已经在更新，diagnostics 与 observation 一致。
        self.assertGreater(second.diagnostics.fps, 0.0)
        self.assertEqual(second.observation.fps, second.diagnostics.fps)


        """无效 camera_info 不应把 pipeline 变成 runtime 异常。"""

        depth_estimator = _FakeDepthEstimator()
        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(),
            segmenter_name="yoloe26",
            depth_estimator=depth_estimator,
            foundationpose_estimator=_FakeFoundationPoseEstimator(),
            cutie_tracker=None,
            process_width=8,
            process_height=8,
        )

        output = pipeline.process(_make_stereo_frame(1, (10, 20, 30)), quest_pb2.QuestCameraInfo())

        self.assertIsNotNone(output.observation)
        self.assertFalse(output.observation.has_pose)
        self.assertEqual(output.observation.phase, "WAIT_CALIBRATION")
        self.assertEqual(output.observation.failure_reason, "invalid_calibration")
        self.assertEqual(depth_estimator.calls, 0)

    def test_async_sam3_first_frame_returns_without_waiting_for_segmentation(self) -> None:
        """SAM3 异步模式下，第一帧只提交后台分割，不应阻塞 pipeline 主循环。"""

        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(delay_s=0.2),
            segmenter_name="sam3",
            depth_estimator=(depth_estimator := _FakeDepthEstimator()),
            foundationpose_estimator=_FakeFoundationPoseEstimator(),
            cutie_tracker=None,
            process_width=8,
            process_height=8,
            async_segmentation=True,
        )

        t0 = time.perf_counter()
        output = pipeline.process(_make_stereo_frame(1, (10, 20, 30)), _make_camera_info())
        elapsed_s = time.perf_counter() - t0
        pipeline.close()

        self.assertLess(elapsed_s, 0.1)
        self.assertEqual(output.diagnostics.phase, "WAIT_SEGMENTATION")
        self.assertIsNone(output.observation)
        self.assertEqual(depth_estimator.calls, 1)
        self.assertIsNotNone(output.diagnostics.depth)

    def test_pose_visualization_failure_does_not_drop_pose(self) -> None:
        """debug 可视化失败时仍应保留本帧有效 pose 输出。"""

        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(),
            segmenter_name="yoloe26",
            depth_estimator=_FakeDepthEstimator(),
            foundationpose_estimator=_FakeFoundationPoseEstimator(fail_visualize=True),
            cutie_tracker=None,
            process_width=8,
            process_height=8,
        )

        output = pipeline.process(_make_stereo_frame(1, (10, 20, 30)), _make_camera_info())

        self.assertIsNotNone(output.observation)
        self.assertTrue(output.observation.has_pose)
        self.assertEqual(output.observation.pose_source, "REGISTER")
        self.assertIsNone(output.diagnostics.pose_vis_bgr)

    def test_invalid_register_pose_becomes_no_pose_without_exception(self) -> None:
        """FoundationPose register 返回 NaN/Inf 时应降级为 no-pose，而不是打断 runtime。"""

        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(),
            segmenter_name="yoloe26",
            depth_estimator=_FakeDepthEstimator(),
            foundationpose_estimator=_InvalidRegisterPoseEstimator(),
            cutie_tracker=None,
            process_width=8,
            process_height=8,
        )

        output = pipeline.process(_make_stereo_frame(1, (10, 20, 30)), _make_camera_info())

        self.assertIsNotNone(output.observation)
        self.assertFalse(output.observation.has_pose)
        self.assertEqual(output.observation.phase, "REGISTER_FAILED")
        self.assertEqual(output.observation.failure_reason, "register_failed")
        self.assertIsNone(output.observation.pose_matrix_cv_camera)
        self.assertFalse(pipeline.tracking_state.has_registered)

    def test_invalid_track_pose_clears_registration_without_exception(self) -> None:
        """FoundationPose track 返回 NaN/Inf 时应清空注册状态，等待后续重获。"""

        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(),
            segmenter_name="yoloe26",
            depth_estimator=_FakeDepthEstimator(),
            foundationpose_estimator=_InvalidTrackPoseEstimator(),
            cutie_tracker=None,
            process_width=8,
            process_height=8,
        )

        first = pipeline.process(_make_stereo_frame(1, (10, 20, 30)), _make_camera_info())
        second = pipeline.process(_make_stereo_frame(2, (10, 20, 30)), _make_camera_info())

        self.assertTrue(first.observation.has_pose)
        self.assertIsNotNone(second.observation)
        self.assertFalse(second.observation.has_pose)
        self.assertEqual(second.observation.phase, "TRACK_FAILED")
        self.assertFalse(pipeline.tracking_state.has_registered)

    def test_async_sam3_registers_with_the_frame_that_produced_mask(self) -> None:
        """后台 mask 完成后，应使用同一帧 RGB/mask 进入 FoundationPose register。"""

        segmenter = _FakeSegmenter(delay_s=0.01)
        estimator = _FakeFoundationPoseEstimator()
        pipeline = QuestPosePipeline(
            segmenter=segmenter,
            segmenter_name="sam3",
            depth_estimator=_FakeDepthEstimator(),
            foundationpose_estimator=estimator,
            cutie_tracker=None,
            process_width=8,
            process_height=8,
            async_segmentation=True,
        )
        try:
            pipeline.process(_make_stereo_frame(1, (10, 20, 30)), _make_camera_info())
            deadline = time.perf_counter() + 1.0
            output = None
            while time.perf_counter() < deadline:
                output = pipeline.process(_make_stereo_frame(2, (200, 210, 220)), _make_camera_info())
                if output.observation is not None and output.observation.has_pose:
                    break
                time.sleep(0.01)

            self.assertIsNotNone(output)
            self.assertIsNotNone(output.observation)
            self.assertTrue(output.observation.has_pose)
            self.assertEqual(output.diagnostics.frame_id, 1)
            self.assertEqual(len(estimator.register_calls), 1)
            registered_rgb = estimator.register_calls[0][0]
            expected_rgb = cv2.cvtColor(
                cv2.imdecode(
                    np.frombuffer(_make_stereo_frame(1, (10, 20, 30)).left_image_jpeg, dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                ),
                cv2.COLOR_BGR2RGB,
            )
            self.assertLess(float(np.mean(np.abs(registered_rgb.astype(np.int16) - expected_rgb.astype(np.int16)))), 2.0)
        finally:
            pipeline.close()

    def test_duplicate_frame_is_rejected_before_jpeg_decode(self) -> None:
        """重复 frame_id 应在 header 阶段丢弃，避免高频 latest cache 重复解 JPEG。"""

        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(),
            segmenter_name="yoloe26",
            depth_estimator=_FakeDepthEstimator(),
            foundationpose_estimator=_FakeFoundationPoseEstimator(),
            cutie_tracker=None,
            process_width=8,
            process_height=8,
        )

        first = pipeline.process(_make_stereo_frame(1, (10, 20, 30)), _make_camera_info())
        with patch("egoanchor.perception.quest_pose_pipeline.decode_quest_stereo_frame") as decode:
            second = pipeline.process(_make_stereo_frame(1, (200, 210, 220)), _make_camera_info())

        self.assertTrue(first.new_frame_processed)
        self.assertFalse(second.new_frame_processed)
        self.assertEqual(second.diagnostics.phase, "DUPLICATE_FRAME")
        decode.assert_not_called()

    def test_stale_async_segmentation_error_is_discarded(self) -> None:
        """旧 generation/session 的异步分割异常不应污染当前 pipeline 状态。"""

        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(),
            segmenter_name="sam3",
            depth_estimator=_FakeDepthEstimator(),
            foundationpose_estimator=_FakeFoundationPoseEstimator(),
            cutie_tracker=None,
            process_width=8,
            process_height=8,
        )
        job = AsyncSegmenterJob(
            decoded=_make_decoded_frame(7),
            session_id="old-session",
            left_bgr=np.zeros((8, 8, 3), dtype=np.uint8),
            right_bgr=np.zeros((8, 8, 3), dtype=np.uint8),
            generation=pipeline.tracking_state.generation,
        )
        pipeline.async_segmentation = True
        pipeline._segmenter_worker = _CompletedAsyncWorker(
            AsyncSegmenterOutput(job=job, result=None, elapsed_ms=1.0, error="RuntimeError: stale")
        )
        pipeline._last_session_id = "current-session"
        pipeline.cam_k = np.eye(3, dtype=np.float32)
        pipeline.calibration = object()

        output = pipeline._take_ready_async_segmentation(time.perf_counter())

        self.assertIsNone(output)

    def test_registered_pipeline_re_registers_when_cutie_mask_is_lost(self) -> None:
        """已注册后若 Cutie mask 连续丢失，应主动用检测 mask 重注册。"""

        segmenter = _FakeSegmenter()
        estimator = _FakeFoundationPoseEstimator()
        pipeline = QuestPosePipeline(
            segmenter=segmenter,
            segmenter_name="yoloe26",
            depth_estimator=_FakeDepthEstimator(),
            foundationpose_estimator=estimator,
            cutie_tracker=_EmptyCutieTracker(),
            process_width=8,
            process_height=8,
            cutie_enabled=True,
            tracked_mask_lost_frames=1,
        )

        first = pipeline.process(_make_stereo_frame(1, (10, 20, 30)), _make_camera_info())
        second = pipeline.process(_make_stereo_frame(2, (10, 20, 30)), _make_camera_info())

        self.assertTrue(first.observation.has_pose)
        self.assertEqual(first.observation.pose_source, "REGISTER")
        self.assertTrue(second.observation.has_pose)
        self.assertEqual(second.observation.pose_source, "RE_REGISTER")
        self.assertEqual(second.observation.phase, "RE_REGISTER")
        self.assertEqual(len(estimator.register_calls), 2)

    def test_register_mask_snapshot_refreshes_on_each_register(self) -> None:
        """register 和 re-register 成功时都应刷新显示实际用于注册的 mask。"""

        estimator = _FakeFoundationPoseEstimator()
        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(),
            segmenter_name="yoloe26",
            depth_estimator=_FakeDepthEstimator(),
            foundationpose_estimator=estimator,
            cutie_tracker=_EmptyCutieTracker(),
            process_width=8,
            process_height=8,
            cutie_enabled=True,
            tracked_mask_lost_frames=1,
            show_mask_snapshot=True,
            mask_snapshot_window="unit mask",
        )

        with patch("egoanchor.perception.quest_pose_pipeline.cv2.imshow") as imshow:
            pipeline.process(_make_stereo_frame(1, (10, 20, 30)), _make_camera_info())
            pipeline.process(_make_stereo_frame(2, (10, 20, 30)), _make_camera_info())

        self.assertEqual(imshow.call_count, 2)

    def test_mask_lost_counter_survives_wrong_track_pose_until_threshold(self) -> None:
        """即使 FoundationPose 仍返回 TRACK，空 Cutie mask 也应累计到阈值触发重注册。"""

        estimator = _FakeFoundationPoseEstimator()
        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(),
            segmenter_name="yoloe26",
            depth_estimator=_FakeDepthEstimator(),
            foundationpose_estimator=estimator,
            cutie_tracker=_EmptyCutieTracker(),
            process_width=8,
            process_height=8,
            cutie_enabled=True,
            tracked_mask_lost_frames=3,
        )

        first = pipeline.process(_make_stereo_frame(1, (10, 20, 30)), _make_camera_info())
        second = pipeline.process(_make_stereo_frame(2, (10, 20, 30)), _make_camera_info())
        third = pipeline.process(_make_stereo_frame(3, (10, 20, 30)), _make_camera_info())
        fourth = pipeline.process(_make_stereo_frame(4, (10, 20, 30)), _make_camera_info())

        self.assertEqual(first.observation.pose_source, "REGISTER")
        self.assertEqual(second.observation.pose_source, "TRACK")
        self.assertEqual(third.observation.pose_source, "TRACK")
        self.assertEqual(fourth.observation.pose_source, "RE_REGISTER")
        self.assertEqual(len(estimator.register_calls), 2)


if __name__ == "__main__":
    unittest.main()
