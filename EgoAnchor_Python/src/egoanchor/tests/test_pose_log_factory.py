"""PoseResult 日志字段构造测试。"""

from __future__ import annotations

import unittest

from egoanchor.protocol import Matrix4x4, PoseResult
from egoanchor.runtime import PoseLogFactory


class PoseLogFactoryTest(unittest.TestCase):
    """验证 PoseResult 日志字段不再依赖 TrackingRuntime 内部方法。"""

    def test_build_extracts_translation_quaternion_and_jump(self) -> None:
        """连续两帧 pose 应输出位置、四元数和相邻平移跳变。"""

        factory = PoseLogFactory()
        first = PoseResult(has_pose=True, pose_matrix_cv_camera=Matrix4x4(values=(1, 0, 0, 0.1, 0, 1, 0, 0.2, 0, 0, 1, 0.3, 0, 0, 0, 1)))
        second = PoseResult(has_pose=True, pose_matrix_cv_camera=Matrix4x4(values=(1, 0, 0, 0.4, 0, 1, 0, 0.2, 0, 0, 1, 0.3, 0, 0, 0, 1)))

        first_fields = factory.build(first)
        second_fields = factory.build(second)

        self.assertAlmostEqual(first_fields["pose_qw"], 1.0)
        self.assertAlmostEqual(first_fields["pose_tx_m"], 0.1)
        self.assertAlmostEqual(second_fields["pose_jump_translation_m"], 0.3)
        self.assertAlmostEqual(second_fields["pose_jump_rotation_deg"], 0.0)

    def test_missing_pose_resets_jump_state(self) -> None:
        """无 pose 帧应清空上一帧矩阵，避免重获后产生跨段 jump。"""

        factory = PoseLogFactory()
        pose = PoseResult(has_pose=True, pose_matrix_cv_camera=Matrix4x4(values=(1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)))

        factory.build(pose)
        factory.build(PoseResult(has_pose=False))
        fields = factory.build(pose)

        self.assertEqual(fields["pose_jump_translation_m"], 0.0)

    def test_non_finite_pose_matrix_resets_jump_state(self) -> None:
        """非有限矩阵不应进入 JSONL pose 字段，也不应污染下一帧 jump。"""

        factory = PoseLogFactory()
        pose = PoseResult(has_pose=True, pose_matrix_cv_camera=Matrix4x4(values=(1, 0, 0, 0.1, 0, 1, 0, 0.2, 0, 0, 1, 0.3, 0, 0, 0, 1)))
        bad_pose = PoseResult(has_pose=True, pose_matrix_cv_camera=Matrix4x4(values=(1, 0, 0, float("nan"), 0, 1, 0, 0.2, 0, 0, 1, 0.3, 0, 0, 0, 1)))

        factory.build(pose)
        self.assertEqual(factory.build(bad_pose), {})
        fields = factory.build(pose)

        self.assertEqual(fields["pose_jump_translation_m"], 0.0)


if __name__ == "__main__":
    unittest.main()
