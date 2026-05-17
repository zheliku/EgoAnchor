"""v2 pose pipeline 轻量基础测试。

这些测试不加载 YOLOE/FFS/FoundationPose 模型，只验证 perception/reliability
中可快速执行的基础契约，避免把 GPU 依赖引入单元测试。
"""

from __future__ import annotations

import unittest

from egoanchor.perception.pose_observation import PoseObservation
from egoanchor.perception.quest_calibration import QuestStereoCalibration
from egoanchor.perception.quest_pose_pipeline import _generate_cube_symmetry_tfs
from egoanchor.protocol.v1 import quest_pb2
from egoanchor.reliability import score_observation


class PosePipelineBasicsTest(unittest.TestCase):
    def test_camera_info_to_scaled_k(self) -> None:
        """QuestCameraInfo 应能转换为运行分辨率 K。"""

        msg = quest_pb2.QuestCameraInfo(
            left_fx=600.0,
            left_fy=610.0,
            left_cx=320.0,
            left_cy=240.0,
            baseline_m=0.064,
            sensor_width=640,
            sensor_height=480,
            active_left=0,
            active_top=0,
            active_right=640,
            active_bottom=480,
        )
        calib = QuestStereoCalibration.from_proto(msg)
        k = calib.scaled_k(640, 480, assume_center_crop=True)

        self.assertEqual(k.shape, (3, 3))
        self.assertAlmostEqual(float(k[0, 0]), 600.0)
        self.assertAlmostEqual(float(k[1, 1]), 610.0)
        self.assertAlmostEqual(float(k[0, 2]), 320.0)
        self.assertAlmostEqual(float(k[1, 2]), 240.0)

    def test_cube_symmetry_count(self) -> None:
        """立方体对称群应生成 24 个 4x4 变换。"""

        tfs = _generate_cube_symmetry_tfs()
        self.assertEqual(tfs.shape, (24, 4, 4))

    def test_reliability_score_uses_pose_diagnostics(self) -> None:
        """有 pose 且诊断较好时，可靠性分数应大于 0。"""

        obs = PoseObservation(
            has_pose=True,
            phase="TRACK",
            depth_valid_ratio=0.8,
            depth_valid_in_mask=0.7,
            mask_area_ratio=0.02,
        )
        self.assertGreater(score_observation(obs), 0.5)
        self.assertEqual(score_observation(PoseObservation(has_pose=False, phase="WAIT_DETECT")), 0.0)


if __name__ == "__main__":
    unittest.main()