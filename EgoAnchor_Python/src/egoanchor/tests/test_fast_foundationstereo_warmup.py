"""Fast-FoundationStereo 启动预热契约测试。"""

from __future__ import annotations

import unittest
from unittest.mock import Mock

import numpy as np

from egoanchor.algorithms import FastFoundationStereoDepth


class FastFoundationStereoWarmUpTest(unittest.TestCase):
    """验证 FFS 预热使用正式处理尺寸且不依赖真实 Quest 输入。"""

    def test_warm_up_runs_one_neutral_stereo_prediction(self) -> None:
        """预热应以中性同尺寸图像完成一次完整深度推理。"""

        estimator = object.__new__(FastFoundationStereoDepth)
        estimator.runtime_backend = "trt"
        estimator.predict_depth = Mock(return_value=np.ones((480, 640), dtype=np.float32))

        estimator.warm_up(input_height=480, input_width=640)

        estimator.predict_depth.assert_called_once()
        left_image, right_image = estimator.predict_depth.call_args.args
        self.assertEqual(left_image.shape, (480, 640, 3))
        self.assertEqual(right_image.shape, (480, 640, 3))
        self.assertTrue(np.array_equal(left_image, right_image))
        self.assertTrue(np.all(left_image == 127))
        self.assertEqual(estimator.predict_depth.call_args.kwargs, {"fx": 1.0, "baseline": 1.0})

    def test_warm_up_rejects_non_positive_input_size(self) -> None:
        """无效处理尺寸必须在任何模型调用前失败。"""

        estimator = object.__new__(FastFoundationStereoDepth)
        estimator.predict_depth = Mock()

        with self.assertRaisesRegex(ValueError, "必须为正数"):
            estimator.warm_up(input_height=0, input_width=640)

        estimator.predict_depth.assert_not_called()


if __name__ == "__main__":
    unittest.main()
