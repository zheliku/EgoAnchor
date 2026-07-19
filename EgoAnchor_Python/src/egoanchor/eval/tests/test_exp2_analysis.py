"""Task 8 实验二组件配对与 VCD risk-coverage 契约测试。"""

from __future__ import annotations

from dataclasses import fields, replace
import itertools
import unittest

import numpy as np

from egoanchor.eval import (
    EXP2_COMPONENTS,
    EXP2_ID,
    EventMarker,
    METRIC_DEFINITIONS,
    MetricRow,
    VcdCandidate,
    VcdTrialContext,
    aggregate_metric_rows,
    analyze_vcd,
    load_analysis_parameters,
    pair_component_metrics,
    summarize_paired_deltas,
    validate_exp2_variant_definitions,
    Exp2VariantDefinition,
    Exp2ComponentResult,
    analyze_exp2_components,
    build_exp2_mechanism_plot_rows,
    build_vcd_operating_plot_row,
    input_workbook_set_sha256,
)


SHA = "a" * 64
"""测试用稳定工作簿 hash。"""


def _unit(metric_key: str) -> str:
    """从公开指标目录读取测试行单位。"""

    return next(metric.unit for metric in METRIC_DEFINITIONS if metric.key == metric_key)


def _row(
    variant_id: str,
    scenario_id: str,
    trial_id: str,
    event_id: str,
    metric_key: str,
    value: float | None,
) -> MetricRow:
    """构造一个最小 event 指标行。"""

    return MetricRow(
        session_id="session-001",
        experiment_id="exp1_system_characterization",
        scenario_id=scenario_id,
        trial_id=trial_id,
        event_id=event_id,
        condition_id=f"exp1_system_characterization/{scenario_id}",
        variant_id=variant_id,
        metric_key=metric_key,
        metric_value=value,
        metric_unit=_unit(metric_key),
        aggregation_level="event",
        input_workbook_sha256=SHA,
    )


def _component_rows() -> list[MetricRow]:
    """为四个组件构造完整系统与消融的配对 event 行。"""

    rows_by_key: dict[tuple[str, str, str, str], MetricRow] = {}
    for component_index, component in enumerate(EXP2_COMPONENTS):
        for metric_index, metric_key in enumerate(component.metric_keys):
            trial_id = f"trial-{component.scenario_id}"
            event_id = f"event-{component.scenario_id}"
            full = _row(
                "EgoAnchor",
                component.scenario_id,
                trial_id,
                event_id,
                metric_key,
                float(metric_index + 1),
            )
            rows_by_key.setdefault(
                (full.variant_id, full.scenario_id, full.event_id, full.metric_key),
                full,
            )
            ablation = _row(
                component.ablation_variant_id,
                component.scenario_id,
                trial_id,
                event_id,
                metric_key,
                float(metric_index + 11),
            )
            rows_by_key[(ablation.variant_id, ablation.scenario_id, ablation.event_id, ablation.metric_key)] = ablation
    return list(rows_by_key.values())


def _marker(role: str, event_id: str, mono_ms: float) -> EventMarker:
    """构造一个 VCD cohort 窗口 marker。"""

    return EventMarker(
        event_row_id=f"events.jsonl:{event_id}",
        session_id="session-001",
        experiment_id="exp1_system_characterization",
        scenario_id="occlusion_recovery",
        trial_id="trial-occlusion",
        event_id=event_id,
        role=role,
        mono_ms=mono_ms,
    )


def _vcd_context() -> VcdTrialContext:
    """构造一个含 marker-covered 与 occlusion-only cohort 的 trial。"""

    return VcdTrialContext(
        session_id="session-001",
        scenario_id="occlusion_recovery",
        trial_id="trial-occlusion",
        trial_end_ms=40.0,
        markers=(_marker("occlusion_started", "event-occlusion", 10.0), _marker("target_visible", "event-visible", 20.0)),
        workbook_sha256=SHA,
    )


def _candidate(index: int, score: float, risk_mm: float, mono_ms: float) -> VcdCandidate:
    """构造一个完整 EgoAnchor 的已到达候选。"""

    return VcdCandidate(
        session_id="session-001",
        scenario_id="occlusion_recovery",
        trial_id="trial-occlusion",
        candidate_id=f"candidate-{index}",
        frame_id=index,
        source_capture_mono_ms=mono_ms,
        variant_id="EgoAnchor",
        admission_decision="accepted",
        vcd_score=score,
        has_aligned_raw=True,
        aligned_raw_position_m=(risk_mm / 1000.0, 0.0, 0.0),
        reference_frame_id=index,
        reference_session_id="session-001",
        reference_pose_valid=True,
        reference_position_m=(0.0, 0.0, 0.0),
        input_workbook_sha256=SHA,
    )


class Exp2ComponentTests(unittest.TestCase):
    """验证组件配置矩阵、精确配对和 delta 汇总。"""

    def test_component_matrix_has_one_disabled_core_component(self) -> None:
        """四个消融必须分别只关闭一个核心组件。"""

        definitions = (
            Exp2VariantDefinition("EgoAnchor", True, True, True, True, True, True, "CaptureTime", "enabled", "kalman", "interp_hermite"),
            Exp2VariantDefinition("EgoAnchor w/o capture-time alignment", False, True, True, True, True, True, "ArrivalTime", "enabled", "kalman", "interp_hermite"),
            Exp2VariantDefinition(
                "EgoAnchor w/o VCD",
                True,
                False,
                True,
                True,
                False,
                True,
                "CaptureTime",
                "disabled",
                "kalman",
                "interp_hermite",
            ),
            Exp2VariantDefinition("EgoAnchor w/o temporal synthesis", True, True, False, True, True, True, "CaptureTime", "enabled", "cv", "raw_passthrough"),
            Exp2VariantDefinition("EgoAnchor w/o StaticLock", True, True, True, False, True, True, "CaptureTime", "enabled", "kalman", "interp_hermite"),
        )
        validate_exp2_variant_definitions(definitions)
        with self.assertRaisesRegex(ValueError, "只能关闭一个"):
            validate_exp2_variant_definitions(
                (*definitions[:-1], replace(definitions[-1], uses_capture_time_alignment=False))
            )
        with self.assertRaisesRegex(ValueError, "原生 bool"):
            replace(definitions[0], uses_capture_time_alignment=1)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "描述性配置"):
            validate_exp2_variant_definitions(
                (replace(definitions[0], quality_gate="disabled"), *definitions[1:])
            )
        with self.assertRaisesRegex(ValueError, "五个正式场景"):
            analyze_exp2_components((), definitions, load_analysis_parameters())

        temporal = next(
            component for component in EXP2_COMPONENTS if component.component_id == "temporal_synthesis"
        )
        self.assertEqual(temporal.scenario_id, "continuous_translation")
        self.assertEqual(
            temporal.primary_metric_keys,
            ("effective_translation_lag_ms", "translation_lag_residual_mm"),
        )

    def test_pair_delta_uses_ablation_minus_full_and_component_key(self) -> None:
        """静止两个消融共享 metric 时仍必须有不同 component 主键。"""

        rows = pair_component_metrics(_component_rows())
        self.assertEqual(len(rows), sum(len(component.metric_keys) for component in EXP2_COMPONENTS))
        static_components = {
            row.component_id
            for row in rows
            if row.scenario_id == "static_head_motion"
            and row.metric_key == "translation_event_pninetyfive_mm"
        }
        self.assertEqual(static_components, {"capture_time_alignment", "static_lock"})
        first = rows[0]
        self.assertEqual(first.experiment_id, EXP2_ID)
        self.assertEqual(first.delta, 10.0)
        self.assertEqual(first.pair_status, "complete")

    def test_missing_or_duplicate_pair_is_hard_failure(self) -> None:
        """缺一侧、重复一侧和错 event 均不得取交集静默缩样本。"""

        rows = _component_rows()
        self.assertRaises(ValueError, pair_component_metrics, rows[:-1])
        self.assertRaises(ValueError, pair_component_metrics, (*rows, rows[0]))
        wrong = replace(rows[1], event_id="event-wrong")
        self.assertRaises(ValueError, pair_component_metrics, (*rows[:1], wrong, *rows[2:]))

    def test_none_pair_is_retained_and_summary_counts_attempt(self) -> None:
        """科学值为空时保留配对尝试，不能把它当作缺行。"""

        rows = _component_rows()
        target = rows.index(
            next(row for row in rows if row.variant_id == "EgoAnchor w/o VCD" and row.metric_key == "jump_pninetyfive_mm")
        )
        rows[target] = replace(rows[target], metric_value=None)
        paired = pair_component_metrics(rows)
        missing = next(row for row in paired if row.component_id == "vcd_admission" and row.metric_key == "jump_pninetyfive_mm")
        self.assertIsNone(missing.delta)
        self.assertEqual(missing.pair_status, "value_missing")
        summary = summarize_paired_deltas(paired, load_analysis_parameters())
        item = next(row for row in summary if row.component_id == "vcd_admission" and row.metric_key == "jump_pninetyfive_mm")
        self.assertEqual(item.attempt_count, 1)
        self.assertEqual(item.sample_count, 0)
        self.assertEqual(item.full_median, 2.0)
        self.assertIsNone(item.ablation_median)

    def test_summary_preserves_full_ablation_and_delta_distributions(self) -> None:
        """实验二汇总必须同时保存完整系统、消融和差值的 event 分布。"""

        summary = summarize_paired_deltas(pair_component_metrics(_component_rows()), load_analysis_parameters())
        item = next(
            row
            for row in summary
            if row.component_id == "vcd_admission"
            and row.metric_key == "occlusion_translation_pninetyfive_mm"
        )
        self.assertEqual(item.full_median, 1.0)
        self.assertEqual(item.ablation_median, 11.0)
        self.assertEqual(item.median, 10.0)
        self.assertEqual((item.positive_count, item.zero_count, item.negative_count), (1, 0, 0))

    def test_mechanism_plot_rows_use_stage2_linear_delta_median(self) -> None:
        """机制图注必须复用 Stage 2 linear median，不得由绘图层取下中位数。"""

        paired = pair_component_metrics(_component_rows())
        target = next(
            row
            for row in paired
            if row.component_id == "capture_time_alignment"
            and row.metric_key == "translation_event_pninetyfive_mm"
        )
        first = replace(
            target,
            full_value=1.0,
            ablation_value=1.0,
            delta=0.0,
            metric_value=0.0,
        )
        second = replace(
            target,
            trial_id="trial-static-2",
            event_id="event-static-2",
            full_value=1.0,
            ablation_value=11.0,
            delta=10.0,
            metric_value=10.0,
        )
        selected = tuple(
            row
            for row in paired
            if row.component_id != "capture_time_alignment"
            or row.metric_key != "translation_event_pninetyfive_mm"
        )
        rows = (first, second, *selected)
        summaries = summarize_paired_deltas(rows, load_analysis_parameters())
        plot_rows = build_exp2_mechanism_plot_rows(rows, summaries)
        capture_rows = [
            row for row in plot_rows if row["component_id"] == "capture_time_alignment"
        ]
        self.assertEqual(len(capture_rows), 2)
        self.assertTrue(all(row["delta_median"] == 5.0 for row in capture_rows))

    def test_shared_trial_aggregation_accepts_exp2_variant_order(self) -> None:
        """公共 trial 聚合不得把实验一四系统顺序硬编码到消融分析。"""

        rows = _component_rows()
        source = tuple(
            row
            for row in rows
            if row.scenario_id == "static_head_motion"
            and row.metric_key == "translation_event_pninetyfive_mm"
        )
        aggregated = aggregate_metric_rows(
            source,
            "trial",
            (
                "EgoAnchor",
                "EgoAnchor w/o capture-time alignment",
                "EgoAnchor w/o StaticLock",
            ),
        )
        self.assertEqual(len(aggregated), 3)
        self.assertIn("session_metrics", {field.name for field in fields(Exp2ComponentResult)})


class VcdTests(unittest.TestCase):
    """验证 VCD risk-coverage、随机参考和 cohort 敏感性。"""

    def setUp(self) -> None:
        """加载唯一冻结分析参数。"""

        self.params = load_analysis_parameters()
        self.context = _vcd_context()
        self.candidates = tuple(
            _candidate(index, score, risk, mono_ms)
            for index, (score, risk, mono_ms) in enumerate(
                ((0.9, 1.0, 5.0), (0.9, 3.0, 12.0), (0.5, 8.0, 15.0), (0.1, 12.0, 25.0))
            )
        )

    def test_tie_group_curve_and_right_step_mean_aurc(self) -> None:
        """并列分数整组纳入，P95 使用 linear，AURC 包含首个非零 coverage 区间。"""

        result = analyze_vcd(self.candidates, (self.context,), self.params)
        vcd_mean = [row for row in result.curve if row.reference_kind == "vcd" and row.risk_kind == "mean"]
        vcd_tail = [row for row in result.curve if row.reference_kind == "vcd" and row.risk_kind == "tail_pninetyfive"]
        self.assertEqual([row.coverage for row in vcd_mean], [0.5, 0.75, 1.0])
        self.assertEqual([row.group_count for row in vcd_mean], [2, 1, 1])
        self.assertEqual([row.cumulative_count for row in vcd_mean], [2, 3, 4])
        np.testing.assert_allclose([row.risk_mm for row in vcd_mean], [2.0, 4.0, 6.0])
        np.testing.assert_allclose([row.risk_mm for row in vcd_tail], [2.9, 7.5, 11.4])
        aurc = next(row for row in result.aurc if row.reference_kind == "vcd")
        self.assertAlmostEqual(aurc.aurc_mm, 3.5)

    def test_random_reference_is_exact_and_order_invariant(self) -> None:
        """随机参考使用无放回精确期望，候选输入顺序不影响结果。"""

        result = analyze_vcd(self.candidates, (self.context,), self.params)
        shuffled = analyze_vcd(tuple(reversed(self.candidates)), (self.context,), self.params)
        random_mean = [row for row in result.curve if row.reference_kind == "random" and row.risk_kind == "mean"]
        self.assertTrue(all(row.risk_mm == 6.0 for row in random_mean))
        first_random_tail = next(
            row for row in result.curve if row.reference_kind == "random" and row.risk_kind == "tail_pninetyfive"
        )
        expected = np.mean(
            [
                float(np.quantile(values, self.params.vcd_tail_quantile, method="linear"))
                for values in itertools.combinations((1.0, 3.0, 8.0, 12.0), 2)
            ]
        )
        self.assertAlmostEqual(first_random_tail.risk_mm, expected)
        self.assertEqual(
            [(row.coverage, row.risk_kind, row.reference_kind, row.risk_mm) for row in result.curve],
            [(row.coverage, row.risk_kind, row.reference_kind, row.risk_mm) for row in shuffled.curve],
        )

    def test_exclusion_reasons_and_rejected_label_do_not_change_curve(self) -> None:
        """无对齐 pose、无 reference 和 invalid reference 分原因排除，decision 文本不参与排序。"""

        no_alignment = replace(self.candidates[0], has_aligned_raw=False)
        no_reference = replace(
            self.candidates[1],
            reference_session_id=None,
            reference_frame_id=None,
            reference_pose_valid=None,
        )
        invalid_reference = replace(self.candidates[2], reference_pose_valid=False)
        candidates = (
            no_alignment,
            no_reference,
            invalid_reference,
            self.candidates[3],
            _candidate(9, 0.05, 15.0, 30.0),
        )
        result = analyze_vcd(candidates, (self.context,), self.params)
        self.assertEqual(sum(point.eligible for point in result.risk_points), 2)
        reasons = {point.exclusion_reason for point in result.risk_points if not point.eligible}
        self.assertEqual(reasons, {"no_aligned_raw", "missing_reference", "invalid_reference"})
        flipped = replace(self.candidates[0], admission_decision="rejected")
        baseline = analyze_vcd((flipped, *self.candidates[1:]), (self.context,), self.params)
        self.assertEqual(
            [(row.coverage, row.risk_mm) for row in baseline.curve if row.reference_kind == "vcd" and row.risk_kind == "mean"],
            [(row.coverage, row.risk_mm) for row in analyze_vcd(self.candidates, (self.context,), self.params).curve if row.reference_kind == "vcd" and row.risk_kind == "mean"],
        )

    def test_operating_point_reuses_analysis_result_and_set_lineage(self) -> None:
        """实际接纳工作点必须复用分析结果并记录全部 eligible 工作簿 hash。"""

        first_hash = "a" * 64
        second_hash = "b" * 64
        candidates = tuple(
            replace(
                candidate,
                admission_decision="rejected" if index == 3 else "accepted",
                input_workbook_sha256=first_hash if index < 2 else second_hash,
            )
            for index, candidate in enumerate(self.candidates)
        )
        result = analyze_vcd(candidates, (self.context,), self.params)
        row = build_vcd_operating_plot_row(result)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertAlmostEqual(float(row["coverage"]), 0.75)
        self.assertEqual(row["risk_mm"], result.operating_tail_risk_mm)
        expected_hash = input_workbook_set_sha256((first_hash, second_hash))
        self.assertEqual(result.operating_input_workbook_sha256, expected_hash)
        self.assertEqual(row["input_workbook_sha256"], expected_hash)

    def test_non_full_variant_reference_mismatch_and_zero_eligible_are_hard_failures(self) -> None:
        """VCD 不得混入消融、跨 frame reference 或空 cohort。"""

        self.assertRaises(ValueError, analyze_vcd, (replace(self.candidates[0], variant_id="EgoAnchor w/o VCD"), *self.candidates[1:]), (self.context,), self.params)
        self.assertRaises(ValueError, analyze_vcd, (replace(self.candidates[0], reference_frame_id=99), *self.candidates[1:]), (self.context,), self.params)
        self.assertRaises(ValueError, analyze_vcd, (replace(self.candidates[0], reference_session_id="session-other"), *self.candidates[1:]), (self.context,), self.params)
        self.assertRaises(ValueError, analyze_vcd, tuple(replace(candidate, has_aligned_raw=False) for candidate in self.candidates), (self.context,), self.params)

    def test_cohort_sensitivity_contains_two_frozen_alternatives(self) -> None:
        """敏感性表必须比较 completed、marker-covered 和 occlusion-only cohort。"""

        result = analyze_vcd(self.candidates, (self.context,), self.params)
        self.assertEqual(
            {row.alternative_setting for row in result.sensitivity},
            {"marker_covered", "occlusion_only"},
        )
        self.assertTrue(all(row.parameter_name == "candidate_cohort" for row in result.sensitivity))


if __name__ == "__main__":
    unittest.main()
