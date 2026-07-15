"""schema-v2 可靠性诊断指标测试。"""

from __future__ import annotations

import unittest

import pandas as pd

from egoanchor.eval.metrics import compute_reliability_diagnostics


class ReliabilityDiagnosticsTest(unittest.TestCase):
    """验证 VCD 分量和 admission 只按 candidate 统计。"""

    def test_summary_uses_schema_v2_scores_and_excludes_missing_color(self) -> None:
        """颜色不可用的 ``None`` 不得污染分数统计。"""

        result = compute_reliability_diagnostics(
            _candidate_rows(),
            _admission_rows(variant_id="egoanchor", variant_label="EgoAnchor"),
            histogram_bins=5,
        )

        summary = result.summary.iloc[0]
        self.assertEqual(int(summary["candidate_count"]), 2)
        self.assertEqual(int(summary["has_pose_count"]), 2)
        self.assertAlmostEqual(float(summary["vcd_score_p50"]), 0.6)
        self.assertAlmostEqual(float(summary["visibility_score_p50"]), 0.7)
        self.assertAlmostEqual(float(summary["geometry_core_score_p50"]), 0.5)
        self.assertEqual(int(summary["color_projection_score_count"]), 1)
        self.assertAlmostEqual(float(summary["color_projection_score_p50"]), 0.2)
        self.assertAlmostEqual(float(summary["depth_alignment_score_p50"]), 0.5)
        self.assertAlmostEqual(float(summary["depth_abs_score_p50"]), 0.45)
        self.assertAlmostEqual(float(summary["depth_struct_score_p50"]), 0.4)
        self.assertAlmostEqual(float(summary["depth_alpha_p50"]), 0.25)
        self.assertEqual(int(summary["render_quality_evaluated_count"]), 2)
        self.assertEqual(int(summary["render_quality_valid_count"]), 2)
        self.assertAlmostEqual(float(summary["render_quality_ms_p50"]), 5.0)
        self.assertEqual(int(result.vcd_histogram["candidate_count"].sum()), 2)
        self.assertFalse(any("rq" in column.lower() for column in result.summary.columns))

    def test_admission_distribution_counts_candidates_per_variant(self) -> None:
        """多 variant 消费同一 candidate 时，每个 variant 各计一次 candidate。"""

        admission = pd.concat(
            [
                _admission_rows(variant_id="arrival", variant_label="Arrival-Hold"),
                _admission_rows(variant_id="egoanchor", variant_label="EgoAnchor"),
            ],
            ignore_index=True,
        )

        result = compute_reliability_diagnostics(_candidate_rows(), admission)

        totals = result.admission_distribution.groupby("variant_id")["candidate_count"].sum()
        self.assertEqual(int(totals["arrival"]), 2)
        self.assertEqual(int(totals["egoanchor"]), 2)
        shares = result.admission_distribution.groupby("variant_id")["candidate_share"].sum()
        self.assertAlmostEqual(float(shares["arrival"]), 1.0)
        self.assertAlmostEqual(float(shares["egoanchor"]), 1.0)
        self.assertEqual(set(result.summary["variant_id"]), {"arrival", "egoanchor"})

    def test_unknown_candidate_is_rejected(self) -> None:
        """admission 引用未知 candidate 时必须立即失败。"""

        admission = _admission_rows(variant_id="egoanchor", variant_label="EgoAnchor")
        admission.loc[1, "candidate_id"] = "session-a:999:1"

        with self.assertRaisesRegex(ValueError, "未知 candidate_id"):
            compute_reliability_diagnostics(_candidate_rows(), admission)

    def test_out_of_range_vcd_score_is_rejected(self) -> None:
        """VCD 连续评分越界时必须失败，不能裁剪到直方图边界。"""

        candidates = _candidate_rows()
        candidates.loc[0, "vcd_score"] = 1.1

        with self.assertRaisesRegex(ValueError, "必须位于"):
            compute_reliability_diagnostics(
                candidates,
                _admission_rows(variant_id="egoanchor", variant_label="EgoAnchor"),
            )


def _candidate_rows() -> pd.DataFrame:
    """构造两条包含完整 VCD 分量的 schema-v2 candidate。"""

    return pd.DataFrame.from_records(
        [
            {
                "session_id": "session-a",
                "candidate_id": "session-a:1:1",
                "has_pose": True,
                "vcd_score": 0.8,
                "visibility_score": 0.9,
                "geometry_core_score": 0.7,
                "color_projection_score": None,
                "depth_alignment_score": 0.6,
                "depth_abs_score": 0.5,
                "depth_struct_score": 0.45,
                "depth_alpha": 0.25,
                "render_diagnostics": {
                    "render_quality_evaluated": True,
                    "render_quality_status": "valid",
                    "render_quality_mask_iou": 0.6,
                    "render_quality_area_ratio_score": 0.7,
                    "render_quality_render_visible_ratio": 0.8,
                    "render_quality_observed_visible_ratio": 0.9,
                    "render_quality_render_area_px": 120,
                    "render_quality_depth_inlier": 0.7,
                    "render_quality_depth_alignment": 0.6,
                    "render_quality_depth_absolute": 0.5,
                    "render_quality_depth_structural": 0.45,
                    "render_quality_depth_alpha": 0.25,
                    "render_quality_depth_residual_m": 0.01,
                    "render_quality_ms": 4.0,
                },
            },
            {
                "session_id": "session-a",
                "candidate_id": "session-a:2:1",
                "has_pose": True,
                "vcd_score": 0.4,
                "visibility_score": 0.5,
                "geometry_core_score": 0.3,
                "color_projection_score": 0.2,
                "depth_alignment_score": 0.4,
                "depth_abs_score": 0.4,
                "depth_struct_score": 0.35,
                "depth_alpha": 0.25,
                "render_diagnostics": {
                    "render_quality_evaluated": True,
                    "render_quality_status": "valid",
                    "render_quality_mask_iou": 0.4,
                    "render_quality_area_ratio_score": 0.5,
                    "render_quality_render_visible_ratio": 0.6,
                    "render_quality_observed_visible_ratio": 0.7,
                    "render_quality_render_area_px": 100,
                    "render_quality_depth_inlier": 0.5,
                    "render_quality_depth_alignment": 0.4,
                    "render_quality_depth_absolute": 0.4,
                    "render_quality_depth_structural": 0.35,
                    "render_quality_depth_alpha": 0.25,
                    "render_quality_depth_residual_m": 0.02,
                    "render_quality_ms": 6.0,
                },
            },
        ]
    )


def _admission_rows(*, variant_id: str, variant_label: str) -> pd.DataFrame:
    """构造同一上下文内两个 candidate 的 schema-v2 admission。"""

    records = []
    for index, candidate_id in enumerate(("session-a:1:1", "session-a:2:1")):
        accepted = index == 0
        records.append(
            {
                "session_id": "session-a",
                "experiment_id": "exp2_design_attribution",
                "scenario_id": "occlusion_recovery",
                "trial_id": "trial-01",
                "event_id": "event-01",
                "condition_id": "occlusion",
                "variant_id": variant_id,
                "variant_label": variant_label,
                "candidate_id": candidate_id,
                "admission_decision": "accepted" if accepted else "rejected",
                "policy_action": "accept" if accepted else "reject",
                "policy_reason": "score_accept" if accepted else "vcd_below_threshold",
            }
        )
    return pd.DataFrame.from_records(records)


if __name__ == "__main__":
    unittest.main()
