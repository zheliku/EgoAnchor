"""轻量可靠性诊断指标测试。"""

from __future__ import annotations

import unittest

import pandas as pd

from eval.io.schemas import PoseResultRow
from eval.metrics.diagnostics import compute_reliability_diagnostics


class ReliabilityDiagnosticsTest(unittest.TestCase):
    """验证 Python reliability 分布诊断不依赖 runtime 或模型。"""

    def test_pose_result_row_preserves_consistency_fields(self) -> None:
        """runtime JSONL 中的一致性旁路字段应进入 pose DataFrame。"""

        row = PoseResultRow.from_dict(
            {
                "event": "pose_result",
                "frame_id": 7,
                "has_pose": True,
                "pose_matrix_cv_camera": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                "pose_score": 0.73,
                "reliability_flags": ["consistency_low"],
                "depth_quality_score": 0.71,
                "track_consistency": 0.42,
                "consistency_mask_iou": 0.35,
                "consistency_depth_inlier": 0.58,
                "consistency_depth_residual_m": 0.014,
                "consistency_ms": 4.2,
            },
            source="unit",
        )

        record = row.to_record()

        self.assertAlmostEqual(record["depth_quality_score"], 0.71)
        self.assertAlmostEqual(record["track_consistency"], 0.42)
        self.assertAlmostEqual(record["consistency_mask_iou"], 0.35)
        self.assertAlmostEqual(record["consistency_depth_inlier"], 0.58)
        self.assertAlmostEqual(record["consistency_depth_residual_m"], 0.014)
        self.assertAlmostEqual(record["consistency_ms"], 4.2)

    def test_compute_reliability_diagnostics_summarizes_distribution(self) -> None:
        """诊断应输出 score 展开程度、一致性开销和 policy 分布。"""

        pose = pd.DataFrame(
            {
                "pose_score": [1.0, 1.0, 0.4],
                "track_consistency": [-1.0, 0.8, 0.3],
                "consistency_ms": [0.0, 4.0, 6.0],
            }
        )
        output = pd.DataFrame(
            {
                "label": ["policy", "policy", "raw"],
                "policy_action": ["Accept", "Reject", "Hold"],
                "policy_reason": ["score_accept", "consistency_low", "coast"],
            }
        )

        result = compute_reliability_diagnostics(pose, output)
        summary = result.summary.iloc[0]

        self.assertEqual(int(summary["pose_rows"]), 3)
        self.assertEqual(int(summary["score_unique_count"]), 2)
        self.assertAlmostEqual(float(summary["score_mode_share"]), 2.0 / 3.0)
        self.assertEqual(int(summary["consistency_valid_count"]), 2)
        self.assertAlmostEqual(float(summary["consistency_ms_p50"]), 5.0)
        self.assertAlmostEqual(float(summary["consistency_ms_p95"]), 5.9)
        self.assertEqual(int(result.score_histogram["count"].sum()), 3)
        self.assertEqual(int(result.consistency_histogram["count"].sum()), 2)
        self.assertEqual(int(result.policy_distribution["count"].sum()), 3)


if __name__ == "__main__":
    unittest.main()
