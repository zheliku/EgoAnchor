"""诊断图像工具测试。"""

from __future__ import annotations

import unittest

import numpy as np

from egoanchor.diagnostics import fit_to_size, stack_stereo


class DiagnosticsImageUtilsTest(unittest.TestCase):
    """验证共享图像缩放和双目拼接工具。"""

    def test_fit_to_size_preserves_canvas_shape(self) -> None:
        """任意输入图像缩放后应稳定落在目标画布尺寸。"""

        image = np.full((20, 40, 3), 255, dtype=np.uint8)

        fitted = fit_to_size(image, 100, 50)

        self.assertEqual(fitted.shape, (50, 100, 3))

    def test_stack_stereo_handles_missing_side(self) -> None:
        """缺失一侧图像时应使用另一侧同尺寸占位图。"""

        right = np.ones((10, 20, 3), dtype=np.uint8)

        stacked = stack_stereo(None, right)

        self.assertEqual(stacked.shape, (10, 40, 3))


if __name__ == "__main__":
    unittest.main()
