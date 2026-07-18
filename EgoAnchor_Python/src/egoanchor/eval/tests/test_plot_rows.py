"""Stage 2 VCD 固定 plot 指标选择测试。"""

from __future__ import annotations

import unittest

from egoanchor.eval import (
    VcdCurvePoint,
    build_vcd_plot_rows,
)


class PlotRowsTests(unittest.TestCase):
    """验证 VCD 正式图只保留成对 P95 tail-risk 曲线。"""

    def test_vcd_plot_keeps_only_pninetyfive_tail_risk(self) -> None:
        """正式曲线不得把 mean 与 P95 risk 交替连接。"""

        rows = tuple(
            VcdCurvePoint(
                scenario_id="occlusion_recovery",
                reference_kind=reference,
                risk_kind=risk_kind,
                point_index=0,
                threshold=0.8 if reference == "vcd" else None,
                coverage=0.5,
                risk_mm=2.0 if risk_kind == "mean" else 4.0,
                group_count=1,
                cumulative_count=1,
                coverage_denominator=2,
                input_workbook_sha256="a" * 64,
            )
            for reference in ("vcd", "random")
            for risk_kind in ("mean", "tail_pninetyfive")
        )
        selected = build_vcd_plot_rows(rows)
        self.assertEqual(len(selected), 2)
        self.assertEqual({row["risk_kind"] for row in selected}, {"tail_pninetyfive"})
        self.assertEqual({row["reference_kind"] for row in selected}, {"vcd", "random"})


if __name__ == "__main__":
    unittest.main()
