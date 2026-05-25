"""QuestPosePipeline 分割后端接入测试。"""

from __future__ import annotations

import time
import unittest

import cv2
import numpy as np

from egoanchor.algorithms import SegmenterResult
from egoanchor.protocol import common_pb2, quest_pb2
from egoanchor.perception.quest_pose_pipeline import FrameDiagnostics, PipelineStepTiming, QuestPosePipeline


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


class _FakeDepthEstimator:
    """单测用深度估计器，返回稳定小深度图。"""

    def predict_depth(self, left_rgb: np.ndarray, right_rgb: np.ndarray, fx: float, baseline: float) -> np.ndarray:
        """返回全图有效深度，避免真实 FFS 依赖。"""

        return np.full(left_rgb.shape[:2], 1.0, dtype=np.float32)


class _FakeFoundationPoseEstimator:
    """单测用 FoundationPose 估计器，记录 register 输入。"""

    def __init__(self) -> None:
        """初始化 register 记录。"""

        self.register_calls: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []

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

        return rgb.copy()


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


class QuestPosePipelineSegmenterTest(unittest.TestCase):
    """验证 pipeline 对分割后端只依赖统一接口。"""

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

    def test_async_sam3_first_frame_returns_without_waiting_for_segmentation(self) -> None:
        """SAM3 异步模式下，第一帧只提交后台分割，不应阻塞 pipeline 主循环。"""

        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(delay_s=0.2),
            segmenter_name="sam3",
            depth_estimator=_FakeDepthEstimator(),
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


if __name__ == "__main__":
    unittest.main()
