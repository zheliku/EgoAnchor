"""RQ1 纯绘图层测试。

绘图逻辑已从 analyze 拆到 :mod:`egoanchor.eval.research.rq1.plot`（无 cv2/metrics
重依赖），故本测试**只 import plot**，在轻量环境下即可运行，不受 metrics 引擎的
cv2 依赖影响。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from egoanchor.eval.research.rq1.plot import write_rq1_figure


class WriteRq1FigureTest(unittest.TestCase):
    """RQ1 2×2 网格图导出：写 PDF/PNG，空数据不抛异常，窗口裁剪可选。"""

    def _detail(self) -> pd.DataFrame:
        """构造最小 anchor_error_detail（含 static 与 occlusion 两场景两变体）。"""

        rows = []
        for condition in ("static_observation", "occlusion_recovery"):
            for label in ("Full", "No-StaticLock"):
                for i in range(5):
                    rows.append(
                        {
                            "render_mono_ms": float(i * 10),
                            "condition": condition,
                            "label": label,
                            "translation_error_m": 0.005,
                            "rotation_error_deg": 2.0,
                        }
                    )
        return pd.DataFrame(rows)

    def test_writes_pdf_and_png(self) -> None:
        """有数据时写出 2×2 网格图的 .pdf 与 .png，返回 PDF 路径。"""

        tables = {"anchor_error_detail": self._detail()}
        with tempfile.TemporaryDirectory() as tmp:
            out = write_rq1_figure(tables, Path(tmp) / "fig_rq1_static")
            self.assertTrue(out.with_suffix(".pdf").exists())
            self.assertTrue(out.with_suffix(".png").exists())

    def test_empty_tables_still_write_placeholders(self) -> None:
        """全空表也写出文件（占位面板），不抛异常。"""

        with tempfile.TemporaryDirectory() as tmp:
            out = write_rq1_figure({}, Path(tmp) / "fig_rq1_static")
            self.assertTrue(out.with_suffix(".pdf").exists())

    def test_full_sequence_by_default_no_clip(self) -> None:
        """默认（static_window_s=None）画完整序列，不裁剪最优区间。"""

        tables = {"anchor_error_detail": self._detail()}
        with tempfile.TemporaryDirectory() as tmp:
            # 默认不裁剪：即便传窗口=None 也应正常写出（回归保护）。
            out = write_rq1_figure(tables, Path(tmp) / "fig", static_window_s=None)
            self.assertTrue(out.with_suffix(".png").exists())

    def test_static_window_clip_still_supported(self) -> None:
        """显式传窗口时仍可裁剪 static 列（保留旧口径能力）。"""

        tables = {"anchor_error_detail": self._detail()}
        with tempfile.TemporaryDirectory() as tmp:
            out = write_rq1_figure(tables, Path(tmp) / "fig", static_window_s=(0.0, 30.0))
            self.assertTrue(out.with_suffix(".png").exists())


if __name__ == "__main__":
    unittest.main()
