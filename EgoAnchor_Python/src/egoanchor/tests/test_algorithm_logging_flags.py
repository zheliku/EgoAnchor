"""算法库日志开关契约测试。"""

from __future__ import annotations

import unittest

from egoanchor.algorithms import CutieMaskTracker, FastFoundationStereoDepth, FoundationPoseObjectEstimator, Sam3Segmenter
from egoanchor.utils import get_thirdparty_logger, is_thirdparty_logging_enabled


class AlgorithmLoggingFlagTest(unittest.TestCase):
    """验证算法适配器把日志开关传递给对应第三方库。"""

    def test_adapter_logging_flags_update_registry(self) -> None:
        """适配器应把 enable_logging 写入统一第三方日志 registry。"""

        FoundationPoseObjectEstimator._configure_foundationpose_logging(False)
        FastFoundationStereoDepth._configure_ffs_logging(False)
        Sam3Segmenter._configure_sam3_logging(False)
        CutieMaskTracker._configure_cutie_logging(False)
        cutie_model_logger = get_thirdparty_logger("cutie.model")
        self.assertFalse(is_thirdparty_logging_enabled("foundationpose"))
        self.assertFalse(is_thirdparty_logging_enabled("ffs"))
        self.assertFalse(is_thirdparty_logging_enabled("sam3"))
        self.assertFalse(is_thirdparty_logging_enabled("cutie"))
        self.assertTrue(cutie_model_logger.disabled)

        FoundationPoseObjectEstimator._configure_foundationpose_logging(True)
        FastFoundationStereoDepth._configure_ffs_logging(True)
        Sam3Segmenter._configure_sam3_logging(True)
        CutieMaskTracker._configure_cutie_logging(True)
        self.assertTrue(is_thirdparty_logging_enabled("foundationpose"))
        self.assertTrue(is_thirdparty_logging_enabled("ffs"))
        self.assertTrue(is_thirdparty_logging_enabled("sam3"))
        self.assertTrue(is_thirdparty_logging_enabled("cutie"))
        self.assertFalse(cutie_model_logger.disabled)


class FoundationPoseMeshLoadTest(unittest.TestCase):
    """验证 FoundationPose mesh 加载保留 GLB scene 节点变换。"""

    def test_scene_geometry_uses_trimesh_transform_aware_conversion(self) -> None:
        """GLB scene 应走 transform-aware conversion，而不是直接拼接原始 geometry。"""

        class FakeScene:
            """只模拟 helper 需要的 scene API，避免单测触发 native 渲染/几何依赖。"""

            geometry = {"mesh": object()}

            def __init__(self) -> None:
                self.to_geometry_called = False

            def to_geometry(self) -> str:
                self.to_geometry_called = True
                return "transformed_mesh"

        scene = FakeScene()

        mesh = FoundationPoseObjectEstimator._scene_to_transformed_mesh(scene)

        self.assertEqual(mesh, "transformed_mesh")
        self.assertTrue(scene.to_geometry_called)


if __name__ == "__main__":
    unittest.main()
