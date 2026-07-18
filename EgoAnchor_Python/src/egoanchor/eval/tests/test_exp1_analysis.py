"""Task 7 实验一五场景分析与 event-first 汇总测试。"""

from __future__ import annotations

from dataclasses import replace
import unittest

import numpy as np
from scipy.spatial.transform import Rotation  # type: ignore[import-untyped]

from egoanchor.eval import (
    EXP1_VARIANTS,
    EventMarker,
    Exp1Admission,
    Exp1RenderSeries,
    Exp1Trial,
    analyze_trial_events,
    analyze_exp1,
    build_exp1_plot_rows,
    load_analysis_parameters,
)


EXPERIMENT_ID = "exp1_system_characterization"
"""实验一冻结实验标识。"""


def _required_float(value: float | None) -> float:
    """断言测试目标是可用于数值比较的有限汇总值。

    参数：
        value: 契约允许为空的指标值。

    返回：
        已排除空值后的浮点数。
    """

    if value is None:
        raise AssertionError("预期得到非空指标值")
    return value


def _marker(scenario_id: str, event_id: str, role: str, mono_ms: float) -> EventMarker:
    """构造一个属于合成 trial 的显式事件 marker。

    参数：
        scenario_id: marker 所属场景。
        event_id: trial 内事件标识。
        role: 冻结事件角色。
        mono_ms: Unity 单调时钟时间。
    """

    return EventMarker(
        event_row_id=f"row-{scenario_id}-{event_id}",
        session_id=f"session-{scenario_id}",
        experiment_id=EXPERIMENT_ID,
        scenario_id=scenario_id,
        trial_id="trial-001",
        event_id=event_id,
        role=role,
        mono_ms=mono_ms,
    )


def _delayed(values: np.ndarray, delay_samples: int) -> np.ndarray:
    """用首样本保持构造固定采样延迟序列。

    参数：
        values: 原始逐帧向量。
        delay_samples: 延迟的整数采样数。
    """

    return np.concatenate(
        (np.repeat(values[:1], delay_samples, axis=0), values[:-delay_samples]),
        axis=0,
    )


def _series(variant_id: str, scenario_id: str) -> Exp1RenderSeries:
    """构造可解析验证五场景公式的合成 render 长序列。

    参数：
        variant_id: runtime 配置名称。
        scenario_id: 五个冻结场景之一。
    """

    end_ms = 6000.0 if scenario_id == "start_stop_6dof" else 5000.0 if scenario_id == "static_head_motion" else 3000.0
    times = np.arange(0.0, end_ms, 50.0)
    count = len(times)
    positions = np.zeros((count, 3), dtype=np.float64)
    rotations = np.repeat([[0.0, 0.0, 0.0, 1.0]], count, axis=0)
    linear_speed = np.zeros(count, dtype=np.float64)
    angular_speed = np.zeros(count, dtype=np.float64)
    display_positions = positions.copy()
    display_rotations = rotations.copy()

    if scenario_id == "static_head_motion":
        low_error = 0.001 * np.sin(2.0 * np.pi * 2.0 * times / 1000.0)
        high_error = 0.100 + 0.001 * np.sin(2.0 * np.pi * 2.0 * times / 1000.0)
        display_positions[:, 0] = np.where(times < 2500.0, low_error, high_error)
    elif scenario_id == "start_stop_6dof":
        moving = (times >= 800.0) & (times < 1600.0)
        positions[:, 0] = np.clip((times - 800.0) / 800.0, 0.0, 1.0) * 0.1
        linear_speed[moving] = 0.125
        display_positions = _delayed(positions, 2)
    elif scenario_id == "continuous_translation":
        positions[:, 0] = times * 0.0001
        linear_speed[:] = 0.1
        display_positions = _delayed(positions, 2)
    elif scenario_id == "continuous_rotation":
        angles_deg = times * 0.03
        rotations = Rotation.from_euler("z", angles_deg[:, np.newaxis], degrees=True).as_quat()
        angular_speed[:] = 30.0
        display_rotations = _delayed(rotations, 2)
    elif scenario_id == "occlusion_recovery":
        hidden = (times >= 500.0) & (times < 1200.0)
        display_positions[hidden, 0] = 0.030
        display_positions[(times >= 1200.0) & (times < 1400.0), 0] = 0.025
    else:
        raise AssertionError(f"未知测试场景：{scenario_id}")

    has_output = np.ones(count, dtype=np.bool_)
    has_timing = np.ones(count, dtype=np.bool_)
    source_capture = times - 50.0
    source_capture[times >= 1300.0] = times[times >= 1300.0]
    static_locked = np.zeros(count, dtype=np.bool_)
    if variant_id == "EgoAnchor" and scenario_id == "start_stop_6dof":
        static_locked[times < 900.0] = True
        static_locked[times >= 1900.0] = True

    return Exp1RenderSeries(
        variant_id=variant_id,
        render_tick_ids=np.arange(count, dtype=np.int64),
        times_ms=times,
        head_positions_m=np.zeros((count, 3), dtype=np.float64),
        head_rotations=Rotation.from_euler(
            "y",
            (10.0 * np.sin(2.0 * np.pi * times / 1000.0))[:, np.newaxis],
            degrees=True,
        ).as_quat(),
        reference_pose_valid=np.ones(count, dtype=np.bool_),
        reference_positions_m=positions,
        reference_rotations=rotations,
        reference_linear_speed_m_s=linear_speed,
        reference_angular_speed_deg_s=angular_speed,
        has_output_pose=has_output,
        has_source_capture_timing=has_timing,
        source_capture_mono_ms=source_capture,
        has_display_pose=np.ones(count, dtype=np.bool_),
        display_positions_m=display_positions,
        display_rotations=display_rotations,
        latest_static_locked=static_locked,
    )


def _trial(scenario_id: str, *, include_ablation: bool = True) -> Exp1Trial:
    """构造一个包含四系统和可选消融 runtime 的场景 trial。

    参数：
        scenario_id: 五个冻结场景之一。
        include_ablation: 是否加入必须被实验一投影排除的消融序列。
    """

    marker_specs = {
        "static_head_motion": (("event-001", "generic_marker", 0.0), ("event-002", "generic_marker", 2500.0)),
        "start_stop_6dof": (("event-001", "transition_started", 0.0),),
        "continuous_translation": (("event-001", "generic_marker", 0.0),),
        "continuous_rotation": (("event-001", "generic_marker", 0.0),),
        "occlusion_recovery": (
            ("event-001", "occlusion_started", 500.0),
            ("event-002", "target_visible", 1200.0),
        ),
    }
    series = [_series(variant_id, scenario_id) for variant_id in EXP1_VARIANTS]
    if include_ablation:
        series.append(_series("EgoAnchor w/o VCD", scenario_id))
    admissions: list[Exp1Admission] = []
    if scenario_id == "occlusion_recovery":
        for variant_id in (*EXP1_VARIANTS, "EgoAnchor w/o VCD"):
            admissions.extend(
                Exp1Admission(f"{variant_id}-{index}", variant_id, capture_ms, "accepted")
                for index, capture_ms in enumerate((700.0, 1000.0, 1600.0))
            )
    return Exp1Trial(
        session_id=f"session-{scenario_id}",
        experiment_id=EXPERIMENT_ID,
        scenario_id=scenario_id,
        trial_id="trial-001",
        condition_id=f"{EXPERIMENT_ID}/{scenario_id}",
        workbook_sha256=(scenario_id.encode("ascii").hex() + "0" * 64)[:64],
        trial_end_ms=(
            6000.0
            if scenario_id == "start_stop_6dof"
            else 5000.0
            if scenario_id == "static_head_motion"
            else 3000.0
        ),
        markers=tuple(_marker(scenario_id, *spec) for spec in marker_specs[scenario_id]),
        render_series=tuple(series),
        admissions=tuple(admissions),
    )


class Exp1AnalysisTests(unittest.TestCase):
    """验证实验一投影、五场景指标和分层汇总。"""

    def setUp(self) -> None:
        """读取唯一冻结参数并构造完整五场景批次。"""

        self.params = load_analysis_parameters()
        self.trials = tuple(
            _trial(scenario_id)
            for scenario_id in (
                "static_head_motion",
                "start_stop_6dof",
                "continuous_translation",
                "continuous_rotation",
                "occlusion_recovery",
            )
        )

    def test_five_scenarios_project_only_four_system_variants(self) -> None:
        """实验一必须排除所有消融并为五场景生成主指标。"""

        result = analyze_exp1(self.trials, self.params)
        self.assertEqual(
            set(EXP1_VARIANTS),
            {row.variant_id for row in result.event_metrics},
        )
        primary_keys = {
            (row.scenario_id, row.metric_key)
            for row in result.event_metrics
        }
        for expected in (
            ("static_head_motion", "translation_event_pninetyfive_mm"),
            ("static_head_motion", "position_hp_rms_mm"),
            ("start_stop_6dof", "visible_response_ms"),
            ("start_stop_6dof", "settling_time_ms"),
            ("start_stop_6dof", "post_stop_position_jitter_rms_mm"),
            ("start_stop_6dof", "motion_hold_ratio"),
            ("start_stop_6dof", "motion_translation_peak_mm"),
            ("continuous_translation", "effective_translation_lag_ms"),
            ("continuous_translation", "translation_lag_residual_mm"),
            ("continuous_translation", "translation_lag_pninetyfive_residual_mm"),
            ("continuous_rotation", "effective_angular_lag_ms"),
            ("continuous_rotation", "angular_lag_residual_deg"),
            ("continuous_rotation", "angular_lag_pninetyfive_residual_deg"),
            ("occlusion_recovery", "durable_recovery_time_ms"),
            ("occlusion_recovery", "fresh_output_time_ms"),
            ("occlusion_recovery", "occlusion_error_update_count"),
            ("occlusion_recovery", "occlusion_output_coverage"),
            ("occlusion_recovery", "reappearance_translation_pninetyfive_mm"),
        ):
            self.assertIn(expected, primary_keys)

    def test_reappearance_window_is_not_silently_truncated(self) -> None:
        """固定重新可见窗口不完整时应保留空值，而不是计算短窗 P95。"""

        short_trial = replace(_trial("occlusion_recovery"), trial_end_ms=2000.0)
        rows = analyze_trial_events(short_trial, self.params)
        reappearance = [
            row
            for row in rows
            if row.metric_key == "reappearance_translation_pninetyfive_mm"
        ]
        self.assertEqual(len(reappearance), len(EXP1_VARIANTS))
        self.assertTrue(all(row.metric_value is None for row in reappearance))

    def test_behavior_plot_rows_freeze_representative_traces_and_lag_summary(self) -> None:
        """四面板数据必须在 Stage 2 完成代表事件选择、切窗和汇总。"""

        result = analyze_exp1(self.trials, self.params)
        plots = build_exp1_plot_rows(result, self.trials, self.params)

        self.assertEqual(
            {row["variant_id"] for row in plots.head_motion_trace},
            {"Arrival-Hold", "Capture-Hold", "EgoAnchor"},
        )
        self.assertEqual(
            {row["variant_id"] for row in plots.start_stop_trace},
            set(EXP1_VARIANTS),
        )
        self.assertTrue(
            {"motion", "post_stop"}.issubset(
                {row["phase"] for row in plots.start_stop_trace}
            )
        )
        self.assertEqual(
            {row["point_kind"] for row in plots.lag_tradeoff},
            {"event", "summary"},
        )
        self.assertEqual(
            {row["variant_id"] for row in plots.occlusion_trace},
            set(EXP1_VARIANTS),
        )
        self.assertEqual(
            {row["occluded"] for row in plots.occlusion_trace},
            {False, True},
        )

    def test_static_p95_summary_is_event_first_and_keeps_range(self) -> None:
        """静止 P95 必须先按 event 计算，再汇总 median、IQR 和范围。"""

        result = analyze_exp1(self.trials, self.params)
        points = [
            row.metric_value
            for row in result.event_metrics
            if row.scenario_id == "static_head_motion"
            and row.variant_id == "EgoAnchor"
            and row.metric_key == "translation_event_pninetyfive_mm"
        ]
        summary = next(
            row
            for row in result.scenario_summary
            if row.scenario_id == "static_head_motion"
            and row.variant_id == "EgoAnchor"
            and row.metric_key == "translation_event_pninetyfive_mm"
        )
        finite_points = np.asarray([value for value in points if value is not None])
        self.assertEqual(summary.sample_count, 2)
        self.assertEqual(summary.attempt_count, 2)
        self.assertEqual(summary.success_rate, 1.0)
        median = _required_float(summary.median)
        minimum = _required_float(summary.minimum)
        maximum = _required_float(summary.maximum)
        self.assertAlmostEqual(median, float(np.median(finite_points)))
        self.assertAlmostEqual(_required_float(summary.metric_value), median)
        self.assertAlmostEqual(minimum, float(np.min(finite_points)))
        self.assertAlmostEqual(maximum, float(np.max(finite_points)))
        self.assertGreater(maximum - minimum, 90.0)

    def test_failed_response_is_counted_instead_of_silently_dropped(self) -> None:
        """未响应 event 必须保留尝试数、零成功率和空条件统计量。"""

        trials = list(self.trials)
        start_stop = trials[1]
        frozen_series = next(
            series for series in start_stop.render_series if series.variant_id == "Arrival-Hold"
        )
        no_response = replace(
            frozen_series,
            display_positions_m=np.zeros_like(frozen_series.display_positions_m),
            display_rotations=np.repeat(
                [[0.0, 0.0, 0.0, 1.0]],
                len(frozen_series.times_ms),
                axis=0,
            ),
        )
        trials[1] = replace(
            start_stop,
            render_series=tuple(
                no_response if series.variant_id == "Arrival-Hold" else series
                for series in start_stop.render_series
            ),
        )

        result = analyze_exp1(trials, self.params)
        summary = next(
            row
            for row in result.scenario_summary
            if row.scenario_id == "start_stop_6dof"
            and row.variant_id == "Arrival-Hold"
            and row.metric_key == "visible_response_ms"
        )
        self.assertEqual(summary.attempt_count, 1)
        self.assertEqual(summary.sample_count, 0)
        self.assertEqual(summary.success_rate, 0.0)
        self.assertIsNone(summary.metric_value)
        self.assertIsNone(summary.median)
        self.assertIsNone(summary.minimum)
        self.assertIsNone(summary.maximum)

    def test_session_metrics_aggregate_trial_metrics_without_event_weighting(self) -> None:
        """session 必须等权汇总 trial，不能让 marker 更多的 trial 获得额外权重。"""

        first = self.trials[0]
        second_trial_id = "trial-002"
        second_marker = EventMarker(
            event_row_id="row-static-second",
            session_id=first.session_id,
            experiment_id=first.experiment_id,
            scenario_id=first.scenario_id,
            trial_id=second_trial_id,
            event_id="event-001",
            role="generic_marker",
            mono_ms=0.0,
        )
        second_series = tuple(
            replace(
                series,
                display_positions_m=series.reference_positions_m
                + np.asarray([0.200, 0.0, 0.0]),
            )
            for series in first.render_series
        )
        second = Exp1Trial(
            session_id=first.session_id,
            experiment_id=first.experiment_id,
            scenario_id=first.scenario_id,
            trial_id=second_trial_id,
            condition_id=first.condition_id,
            workbook_sha256=first.workbook_sha256,
            trial_end_ms=first.trial_end_ms,
            markers=(second_marker,),
            render_series=second_series,
            admissions=(),
        )
        result = analyze_exp1((first, second, *self.trials[1:]), self.params)
        trial_values = [
            row.metric_value
            for row in result.trial_metrics
            if row.session_id == first.session_id
            and row.variant_id == "EgoAnchor"
            and row.metric_key == "translation_event_pninetyfive_mm"
        ]
        session_value = next(
            row.metric_value
            for row in result.session_metrics
            if row.session_id == first.session_id
            and row.variant_id == "EgoAnchor"
            and row.metric_key == "translation_event_pninetyfive_mm"
        )
        self.assertEqual(len(trial_values), 2)
        finite_trial_values = [_required_float(value) for value in trial_values]
        self.assertAlmostEqual(
            _required_float(session_value),
            float(np.median(finite_trial_values)),
        )

    def test_start_stop_uses_only_transition_started_windows(self) -> None:
        """起停分析只计算 transition_started 窗，其他显式角色仅保留边界作用。"""

        trials = list(self.trials)
        start_stop = trials[1]
        extra_marker = EventMarker(
            event_row_id="row-start-stop-extra",
            session_id=start_stop.session_id,
            experiment_id=start_stop.experiment_id,
            scenario_id=start_stop.scenario_id,
            trial_id=start_stop.trial_id,
            event_id="event-extra",
            role="generic_marker",
            mono_ms=2500.0,
        )
        trials[1] = replace(start_stop, markers=(*start_stop.markers, extra_marker))

        result = analyze_exp1(trials, self.params)
        start_stop_event_ids = {
            row.event_id
            for row in result.event_metrics
            if row.scenario_id == "start_stop_6dof"
        }
        self.assertEqual(start_stop_event_ids, {"event-001"})

    def test_four_result_tables_have_unique_keys_and_no_ablation(self) -> None:
        """四级结果表主键必须唯一，且任何层级都不得混入消融。"""

        result = analyze_exp1(self.trials, self.params)
        table_keys = (
            (
                result.event_metrics,
                lambda row: (
                    row.session_id,
                    row.scenario_id,
                    row.trial_id,
                    row.event_id,
                    row.variant_id,
                    row.metric_key,
                ),
            ),
            (
                result.trial_metrics,
                lambda row: (
                    row.session_id,
                    row.scenario_id,
                    row.trial_id,
                    row.variant_id,
                    row.metric_key,
                ),
            ),
            (
                result.session_metrics,
                lambda row: (
                    row.session_id,
                    row.scenario_id,
                    row.variant_id,
                    row.metric_key,
                ),
            ),
            (
                result.scenario_summary,
                lambda row: (row.scenario_id, row.variant_id, row.metric_key),
            ),
        )
        for rows, key_factory in table_keys:
            keys = [key_factory(row) for row in rows]
            self.assertEqual(len(keys), len(set(keys)))
            self.assertTrue({row.variant_id for row in rows}.issubset(set(EXP1_VARIANTS)))

    def test_occlusion_error_updates_count_unique_admitted_candidates(self) -> None:
        """遮挡期错误更新按采集时间和唯一 candidate 计数，不按 render frame 计数。"""

        result = analyze_exp1(self.trials, self.params)
        row = next(
            item
            for item in result.event_metrics
            if item.scenario_id == "occlusion_recovery"
            and item.variant_id == "EgoAnchor"
            and item.metric_key == "occlusion_error_update_count"
        )
        self.assertEqual(row.metric_value, 2.0)

    def test_missing_scenario_or_system_variant_is_a_contract_error(self) -> None:
        """五场景覆盖或四系统矩阵不完整时不得静默发布部分结果。"""

        with self.assertRaisesRegex(ValueError, "五个场景"):
            analyze_exp1(self.trials[:-1], self.params)

        with self.assertRaisesRegex(ValueError, "四个系统"):
            trial = self.trials[0]
            Exp1Trial(
                session_id=trial.session_id,
                experiment_id=trial.experiment_id,
                scenario_id=trial.scenario_id,
                trial_id=trial.trial_id,
                condition_id=trial.condition_id,
                workbook_sha256=trial.workbook_sha256,
                trial_end_ms=trial.trial_end_ms,
                markers=trial.markers,
                render_series=trial.render_series[:-2],
                admissions=trial.admissions,
            )


if __name__ == "__main__":
    unittest.main()
