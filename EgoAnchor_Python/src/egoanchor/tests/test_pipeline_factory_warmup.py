"""pipeline 工厂的 FFS 启动预热契约测试。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from egoanchor.algorithms import CutieMaskTracker, FastFoundationStereoDepth, FoundationPoseObjectEstimator, Sam3Segmenter, Yoloe26Segmenter
from egoanchor.config import load_config
from egoanchor.perception import build_quest_pose_pipeline


class PipelineFactoryWarmUpTest(unittest.TestCase):
    """验证工厂在模型构建阶段使用固定处理尺寸预热 FFS。"""

    def test_build_warms_ffs_with_configured_process_size(self) -> None:
        """TRT 尺寸匹配必须在 Unity 首帧到达前完成。"""

        cfg = load_config()
        depth_estimator = MagicMock()

        with (
            patch("egoanchor.algorithms.FastFoundationStereoDepth", return_value=depth_estimator),
            patch("egoanchor.algorithms.Yoloe26Segmenter", return_value=MagicMock()),
            patch("egoanchor.algorithms.FoundationPoseObjectEstimator", return_value=MagicMock()),
            patch("egoanchor.algorithms.CutieMaskTracker", return_value=MagicMock()),
            patch("egoanchor.algorithms.Sam3Segmenter", return_value=MagicMock()),
        ):
            pipeline = build_quest_pose_pipeline(cfg)

        self.assertEqual(pipeline.process_width, cfg.pipeline.calibration.process_width)
        self.assertEqual(pipeline.process_height, cfg.pipeline.calibration.process_height)
        depth_estimator.warm_up.assert_called_once_with(
            cfg.pipeline.calibration.process_height,
            cfg.pipeline.calibration.process_width,
        )


if __name__ == "__main__":
    unittest.main()
