"""实验二 VCD risk-coverage 的严格平台参考契约测试。"""

from __future__ import annotations

import unittest

import pandas as pd

from egoanchor.eval.experiments.exp2_design_attribution import (
    EXPERIMENT_ID,
    SOURCE_EXPERIMENT_ID,
    compute_vcd_risk_coverage,
)


class Exp2VcdRiskCoverageTest(unittest.TestCase):
    """验证 VCD 分数只诱导阈值，risk 始终来自平台参考误差。"""

    def test_tied_scores_enter_together_and_aurc_uses_millimetres(self) -> None:
        """并列分数不得被任意行顺序拆开，AURC 必须保留毫米单位。"""

        candidates, admissions, references = _tables(
            [(1, 0.9, 0.01, "trial-a"), (2, 0.8, 0.03, "trial-a"), (3, 0.8, 0.05, "trial-a")]
        )

        result = compute_vcd_risk_coverage(candidates, admissions, references)

        self.assertEqual(result.curve["accepted_candidates"].tolist(), [1, 3])
        self.assertEqual(set(result.curve["experiment_id"]), {EXPERIMENT_ID})
        self.assertEqual(result.curve["candidate_count"].tolist(), [3, 3])
        self.assertAlmostEqual(float(result.curve.iloc[0]["selective_risk_mm"]), 10.0)
        self.assertAlmostEqual(float(result.curve.iloc[1]["selective_risk_mm"]), 30.0)
        self.assertAlmostEqual(float(result.aurc.iloc[0]["aurc_mm"]), 70.0 / 3.0)

    def test_aurc_is_computed_per_trial_event_before_session_summary(self) -> None:
        """不同 trial 的候选不得先池化成帧级伪样本。"""

        candidates, admissions, references = _tables(
            [(1, 0.9, 0.01, "trial-a"), (2, 0.8, 0.03, "trial-a"), (3, 0.7, 0.10, "trial-b")]
        )

        result = compute_vcd_risk_coverage(candidates, admissions, references)

        self.assertEqual(len(result.aurc), 2)
        self.assertEqual(set(result.aurc["trial_id"]), {"trial-a", "trial-b"})
        self.assertEqual(int(result.summary.iloc[0]["unit_count"]), 2)
        self.assertAlmostEqual(float(result.summary.iloc[0]["aurc_mm_median"]), 57.5)

    def test_out_of_range_score_is_rejected_without_clipping(self) -> None:
        """越界 VCD 分数必须失败，不能在指标阶段静默裁剪。"""

        candidates, admissions, references = _tables([(1, 1.1, 0.01, "trial-a")])

        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            compute_vcd_risk_coverage(candidates, admissions, references)

    def test_missing_candidate_match_is_rejected(self) -> None:
        """admission 缺少对应 Python candidate 时不得生成伪连接。"""

        candidates, admissions, references = _tables([(1, 0.9, 0.01, "trial-a")])
        candidates.loc[0, "candidate_id"] = "session-a:99:1"

        with self.assertRaisesRegex(ValueError, "未知 candidate_id"):
            compute_vcd_risk_coverage(candidates, admissions, references)

    def test_missing_reference_match_is_counted_as_ineligible(self) -> None:
        """没有同 frame 平台参考时显式排除，不得回退到评分分量。"""

        candidates, admissions, references = _tables([(1, 0.9, 0.01, "trial-a")])
        references.loc[0, "frame_id"] = 99

        with self.assertRaisesRegex(
            ValueError,
            "没有 eligible 候选.*excluded_invalid_reference_count.*1",
        ):
            compute_vcd_risk_coverage(candidates, admissions, references)

    def test_ineligible_candidates_are_reported_by_reason(self) -> None:
        """no-pose、无对齐、无参考和空上下文必须进入可审计排除统计。"""

        candidates, admissions, references = _tables(
            [
                (1, 0.9, 0.01, "eligible"),
                (2, 0.8, 0.02, "no-pose"),
                (3, 0.7, 0.03, "no-aligned"),
                (4, 0.6, 0.04, "no-reference"),
                (5, 0.5, 0.05, "no-context"),
            ]
        )
        candidates.loc[candidates["frame_id"].eq(2), "has_pose"] = False
        admissions.loc[admissions["frame_id"].eq(3), "has_aligned_raw"] = False
        references.loc[references["frame_id"].eq(4), "reference_pose_valid"] = False
        admissions.loc[admissions["frame_id"].eq(5), "event_id"] = ""

        summary = compute_vcd_risk_coverage(candidates, admissions, references).summary.iloc[0]
        self.assertEqual(int(summary["baseline_admission_count"]), 5)
        self.assertEqual(int(summary["eligible_candidate_count"]), 1)
        self.assertEqual(int(summary["excluded_candidate_count"]), 4)
        self.assertEqual(int(summary["excluded_no_pose_count"]), 1)
        self.assertEqual(int(summary["excluded_no_aligned_raw_count"]), 1)
        self.assertEqual(int(summary["excluded_invalid_reference_count"]), 1)
        self.assertEqual(int(summary["excluded_incomplete_context_count"]), 1)

    def test_other_runtime_rows_do_not_duplicate_candidates(self) -> None:
        """同 candidate 的消融 runtime admission 不得重复进入完整系统曲线。"""

        candidates, admissions, references = _tables([(1, 0.9, 0.01, "trial-a")])
        other = admissions.iloc[0].copy()
        other["variant_label"] = "EgoAnchor w/o VCD"
        admissions = pd.concat([admissions, pd.DataFrame([other])], ignore_index=True)

        result = compute_vcd_risk_coverage(candidates, admissions, references)

        self.assertEqual(int(result.curve.iloc[0]["candidate_count"]), 1)
        self.assertEqual(int(result.curve.iloc[0]["accepted_candidates"]), 1)


def _tables(
    rows: list[tuple[int, float, float, str]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """构造 candidate、完整系统 admission 与同帧平台参考。"""

    candidates = []
    admissions = []
    references = []
    for frame_id, score, error_m, trial_id in rows:
        candidate_id = f"session-a:{frame_id}:1"
        candidates.append(
            {
                "session_id": "session-a",
                "candidate_id": candidate_id,
                "frame_id": frame_id,
                "has_pose": True,
                "vcd_score": score,
            }
        )
        admissions.append(
            {
                "session_id": "session-a",
                "experiment_id": SOURCE_EXPERIMENT_ID,
                "scenario_id": "occlusion_recovery",
                "trial_id": trial_id,
                "event_id": f"event-{trial_id}",
                "condition_id": "condition-a",
                "candidate_id": candidate_id,
                "frame_id": frame_id,
                "variant_label": "EgoAnchor",
                "has_aligned_raw": True,
                "aligned_raw_pos": [error_m, 0.0, 0.0],
                "aligned_raw_rot": [0.0, 0.0, 0.0, 1.0],
                "vcd_score": score,
            }
        )
        references.append(
            {
                "session_id": "session-a",
                "frame_id": frame_id,
                "reference_pose_valid": True,
                "reference_pos": [0.0, 0.0, 0.0],
                "reference_rot": [0.0, 0.0, 0.0, 1.0],
            }
        )
    return (
        pd.DataFrame.from_records(candidates),
        pd.DataFrame.from_records(admissions),
        pd.DataFrame.from_records(references),
    )


if __name__ == "__main__":
    unittest.main()
