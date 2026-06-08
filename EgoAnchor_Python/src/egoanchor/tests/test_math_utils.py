"""通用数学工具测试。"""

from __future__ import annotations

import math
import unittest

from egoanchor.utils import clamp, clamp01


class MathUtilsTest(unittest.TestCase):
    """验证通用数学工具的边界输入行为。"""

    def test_clamp_limits_to_custom_bounds(self) -> None:
        """任意闭区间限幅应处理上下界、无穷和反向边界。"""

        self.assertEqual(clamp(-2.0, -1.0, 3.0), -1.0)
        self.assertEqual(clamp(2.0, -1.0, 3.0), 2.0)
        self.assertEqual(clamp(5.0, -1.0, 3.0), 3.0)
        self.assertEqual(clamp(math.inf, -1.0, 3.0), 3.0)
        self.assertEqual(clamp(2.0, 3.0, -1.0), 2.0)

    def test_clamp_rejects_nan_as_lower_bound(self) -> None:
        """NaN 不应传播到角度或评分计算，退化为明确下界。"""

        self.assertEqual(clamp(math.nan, -1.0, 3.0), -1.0)

    def test_clamp01_rejects_nan_as_zero(self) -> None:
        """NaN 不应沿评分链传播，应被压成明确的 0 分。"""

        self.assertEqual(clamp01(math.nan), 0.0)

    def test_clamp01_keeps_existing_bounds(self) -> None:
        """普通数值与无穷仍按 0..1 闭区间限幅。"""

        self.assertEqual(clamp01(-1.0), 0.0)
        self.assertEqual(clamp01(0.4), 0.4)
        self.assertEqual(clamp01(2.0), 1.0)
        self.assertEqual(clamp01(math.inf), 1.0)


if __name__ == "__main__":
    unittest.main()
