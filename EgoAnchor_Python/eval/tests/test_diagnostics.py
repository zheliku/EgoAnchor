"""轻量可靠性诊断指标测试。"""

from __future__ import annotations

import unittest

import pandas as pd

from eval.io.schemas import PoseResultRow
from eval.metrics.diagnostics import compute_reliability_diagnostics


class ReliabilityDiagnosticsTest(unittest.TestCase):
    """验证 Python reliability 分布诊断不依赖 runtime 或模型。"""

    def test_pose_result_row_preserves_render_quality_fields(self) -> None:
        """runtime JSONL 中的渲染质量旁路字段应进入 pose DataFrame。"""

        row = PoseResultRow.from_dict(
            {
                "event": "pose_result",
                "frame_id": 7,
                "has_pose": True,
                "pose_matrix_cv_camera": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                "pose_score": 0.73,
                "reliability_flags": ["reprojection_low"],
                "score_phase": 1.0,
                "score_reprojection": 0.42,
                "score_depth": 0.71,
                "score_jump": 0.95,
                "score_mask": 1.0,
                "score_reject": 1.0,
                "score_confidence": 0.88,
                "color_reprojection": 0.42,
                "render_quality_evaluated": True,
                "render_quality_status": "valid",
                "render_quality_mask_iou": 0.35,
                "render_quality_area_ratio_score": 0.31,
                "render_quality_render_visible_ratio": 0.52,
                "render_quality_observed_visible_ratio": 0.63,
                "render_quality_render_area_px": 128,
                "render_quality_depth_inlier": 0.58,
                "render_quality_depth_alignment": 0.62,
                "render_quality_depth_residual_m": 0.014,
                "render_quality_ms": 4.2,
            },
            source="unit",
        )

        record = row.to_record()

        self.assertAlmostEqual(record["score_phase"], 1.0)
        self.assertAlmostEqual(record["score_reprojection"], 0.42)
        self.assertAlmostEqual(record["score_depth"], 0.71)
        self.assertAlmostEqual(record["score_jump"], 0.95)
        self.assertAlmostEqual(record["score_mask"], 1.0)
        self.assertAlmostEqual(record["score_reject"], 1.0)
        self.assertAlmostEqual(record["score_confidence"], 0.88)
        self.assertAlmostEqual(record["color_reprojection"], 0.42)
        self.assertTrue(record["render_quality_evaluated"])
        self.assertEqual(record["render_quality_status"], "valid")
        self.assertAlmostEqual(record["render_quality_mask_iou"], 0.35)
        self.assertAlmostEqual(record["render_quality_area_ratio_score"], 0.31)
        self.assertAlmostEqual(record["render_quality_render_visible_ratio"], 0.52)
        self.assertAlmostEqual(record["render_quality_observed_visible_ratio"], 0.63)
        self.assertEqual(record["render_quality_render_area_px"], 128)
        self.assertAlmostEqual(record["render_quality_depth_inlier"], 0.58)
        self.assertAlmostEqual(record["render_quality_depth_alignment"], 0.62)
        self.assertAlmostEqual(record["render_quality_depth_residual_m"], 0.014)
        self.assertAlmostEqual(record["render_quality_ms"], 4.2)

    def test_compute_reliability_diagnostics_summarizes_distribution(self) -> None:
        """诊断应输出 score 展开程度、渲染质量开销和 policy 分布。"""

        pose = pd.DataFrame(
            {
                "pose_score": [1.0, 1.0, 0.4],
                "color_reprojection": [-1.0, 0.8, 0.3],
                "render_quality_ms": [0.0, 4.0, 6.0],
            }
        )
        output = pd.DataFrame(
            {
                "label": ["policy", "policy", "raw"],
                "policy_action": ["Accept", "Reject", "Hold"],
                "policy_reason": ["score_accept", "reprojection_low", "coast"],
            }
        )

        result = compute_reliability_diagnostics(pose, output)
        summary = result.summary.iloc[0]

        self.assertEqual(int(summary["pose_rows"]), 3)
        self.assertEqual(int(summary["score_unique_count"]), 2)
        self.assertAlmostEqual(float(summary["score_mode_share"]), 2.0 / 3.0)
        self.assertEqual(int(summary["color_reprojection_valid_count"]), 2)
        self.assertAlmostEqual(float(summary["render_quality_ms_p50"]), 5.0)
        self.assertAlmostEqual(float(summary["render_quality_ms_p95"]), 5.9)
        self.assertEqual(int(result.score_histogram["count"].sum()), 3)
        self.assertEqual(int(result.color_reprojection_histogram["count"].sum()), 2)
        self.assertEqual(int(result.policy_distribution["count"].sum()), 3)


if __name__ == "__main__":
    unittest.main()
