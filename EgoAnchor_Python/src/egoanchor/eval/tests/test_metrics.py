"""Task 6 公共指标、事件窗口和单调时钟契约测试。"""

from __future__ import annotations

import hashlib
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from egoanchor.eval import (
    ClockDomain,
    DEFAULT_ANALYSIS_PARAMS_PATH,
    MonotonicTimestamp,
    analysis_parameters_sha256,
    build_event_windows,
    candidate_arrival_ms,
    detect_reference_motion,
    durable_recovery_time_ms,
    event_quantiles,
    estimate_angular_lag,
    estimate_translation_lag,
    load_analysis_parameters,
    median_iqr,
    normalize_quaternion,
    pair_occlusion_windows,
    parse_event_markers,
    position_drift_mm,
    position_hp_rms_mm,
    pose_jump_quantiles,
    python_processing_ms,
    rotation_error_deg,
    settling_time_ms,
    translation_error_mm,
    visible_response_ms,
)


class AnalysisParameterTests(unittest.TestCase):
    """验证推荐分析标准已集中冻结在 TOML 中。"""

    def test_recommended_parameters_are_frozen(self) -> None:
        """配置版本和推荐阈值必须与用户确认的标准一致。"""

        params = load_analysis_parameters()

        self.assertEqual(params.contract_version, 2)
        self.assertEqual(params.statistics_unit, "event_segment")
        self.assertEqual(params.quantile_method, "linear")
        self.assertEqual(params.hp_filter_type, "butterworth")
        self.assertEqual(params.hp_filter_order, 2)
        self.assertTrue(params.hp_zero_phase)
        self.assertEqual(params.hp_cutoff_hz, 1.0)
        self.assertEqual(params.drift_window_ms, 1000.0)
        self.assertEqual(params.reference_linear_speed_m_s, 0.05)
        self.assertEqual(params.reference_angular_speed_deg_s, 22.0)
        self.assertEqual(params.reference_speed_median_frames, 7)
        self.assertEqual(params.reference_motion_duration_ms, 100.0)
        self.assertEqual(params.reference_translation_excursion_mm, 5.0)
        self.assertEqual(params.reference_rotation_excursion_deg, 5.0)
        self.assertEqual(params.response_baseline_ms, 500.0)
        self.assertEqual(params.response_position_mm, 5.0)
        self.assertEqual(params.response_rotation_deg, 3.0)
        self.assertEqual(params.response_duration_ms, 100.0)
        self.assertEqual(params.lag_min_ms, 0.0)
        self.assertEqual(params.lag_max_ms, 500.0)
        self.assertEqual(params.lag_step_ms, 5.0)
        self.assertEqual(params.lag_interpolation, "linear_position_slerp_rotation")
        self.assertEqual(params.settling_position_mm, 20.0)
        self.assertEqual(params.settling_duration_ms, 250.0)
        self.assertEqual(params.recovery_position_mm, 20.0)
        self.assertEqual(params.recovery_duration_ms, 250.0)
        self.assertTrue(params.recovery_requires_fresh_output)

    def test_parameter_hash_uses_exact_toml_bytes(self) -> None:
        """parameter_set_id 必须是唯一 TOML 原始字节的 SHA-256。"""

        expected = hashlib.sha256(DEFAULT_ANALYSIS_PARAMS_PATH.read_bytes()).hexdigest()

        self.assertEqual(analysis_parameters_sha256(), expected)

    def test_unknown_parameter_is_rejected(self) -> None:
        """未知 TOML 参数不得被静默忽略。"""

        text = DEFAULT_ANALYSIS_PARAMS_PATH.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "analysis_params.toml"
            path.write_text(text + "\nunknown_parameter = 1 # 测试未知参数。\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "未知参数"):
                load_analysis_parameters(path)

    def test_boolean_cannot_impersonate_integer_parameter(self) -> None:
        """TOML 的布尔值不得通过 Python int 子类关系冒充滤波器阶数。"""

        text = DEFAULT_ANALYSIS_PARAMS_PATH.read_text(encoding="utf-8").replace(
            "filter_order = 2 #",
            "filter_order = true #",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "analysis_params.toml"
            path.write_text(text, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "TOML 类型错误"):
                load_analysis_parameters(path)


class PoseMetricTests(unittest.TestCase):
    """验证位姿误差和相邻显示跳变的解析结果。"""

    def test_translation_and_rotation_errors_have_analytic_values(self) -> None:
        """三四五直角距离和九十度四元数应得到精确结果。"""

        translation = translation_error_mm([0.003, 0.004, 0.0], [0.0, 0.0, 0.0])
        half_angle = math.radians(45.0)
        rotation = rotation_error_deg(
            [0.0, 0.0, math.sin(half_angle), math.cos(half_angle)],
            [0.0, 0.0, 0.0, 1.0],
        )
        antipodal = rotation_error_deg(
            [0.0, 0.0, -math.sin(half_angle), -math.cos(half_angle)],
            [0.0, 0.0, 0.0, 1.0],
        )

        self.assertAlmostEqual(float(translation), 5.0, places=9)
        self.assertAlmostEqual(float(rotation), 90.0, places=9)
        self.assertAlmostEqual(float(antipodal), 90.0, places=9)

    def test_invalid_quaternion_is_rejected(self) -> None:
        """零范数、非有限值和错误维度四元数必须失败。"""

        with self.assertRaises(ValueError):
            normalize_quaternion([0.0, 0.0, 0.0, 0.0])
        with self.assertRaises(ValueError):
            normalize_quaternion([0.0, 0.0, math.nan, 1.0])
        with self.assertRaises(ValueError):
            normalize_quaternion([0.0, 0.0, 1.0])

    def test_pose_jump_reports_p95_and_p99_with_linear_quantiles(self) -> None:
        """跳变只使用同一窗口内相邻有效显示样本。"""

        times = np.arange(0.0, 600.0, 100.0)
        positions = np.array(
            [[0.0, 0.0, 0.0], [0.001, 0.0, 0.0], [0.003, 0.0, 0.0],
             [0.006, 0.0, 0.0], [0.010, 0.0, 0.0], [0.015, 0.0, 0.0]],
        )
        rotations = np.tile([0.0, 0.0, 0.0, 1.0], (len(times), 1))

        result = pose_jump_quantiles(
            times,
            positions,
            rotations,
            np.ones(len(times), dtype=np.bool_),
            load_analysis_parameters(),
        )

        self.assertAlmostEqual(result.translation_p95_mm, 4.8)
        self.assertAlmostEqual(result.translation_p99_mm, 4.96)
        self.assertAlmostEqual(result.rotation_p95_deg, 0.0)
        self.assertAlmostEqual(result.rotation_p99_deg, 0.0)

    def test_pose_jump_does_not_bridge_invalid_display_row(self) -> None:
        """无效 display 行两侧的 pose 不得被当作相邻 tick 计算跳变。"""

        times = np.array([0.0, 10.0, 20.0, 30.0])
        positions = np.array(
            [[0.0, 0.0, 0.0], [0.001, 0.0, 0.0], [math.nan, math.nan, math.nan], [0.011, 0.0, 0.0]],
        )
        rotations = np.tile([0.0, 0.0, 0.0, 1.0], (len(times), 1))

        with self.assertRaisesRegex(ValueError, "相邻样本对不足"):
            pose_jump_quantiles(
                times,
                positions,
                rotations,
                np.ones(len(times), dtype=np.bool_),
                load_analysis_parameters(),
            )

        valid_positions = np.zeros((len(times), 3))
        with self.assertRaisesRegex(ValueError, "finite integers|有限整数"):
            pose_jump_quantiles(
                times,
                valid_positions,
                rotations,
                np.ones(len(times), dtype=np.bool_),
                load_analysis_parameters(),
                render_tick_ids=[0, 1, math.nan, 3],
            )


class WindowTests(unittest.TestCase):
    """验证 marker 角色解析、窗口构造和参考运动检测。"""

    def test_marker_roles_are_joined_from_event_payload(self) -> None:
        """event_role 必须通过 event_row_id 从 payload 表显式联接。"""

        event_rows = [
            {
                "event_row_id": "row-trial",
                "event": "trial_started",
                "session_id": "session-a",
                "experiment_id": "exp1",
                "scenario_id": "occlusion_recovery",
                "trial_id": "trial-1",
                "event_id": "@empty-text",
                "mono_ms": 50.0,
            },
            {
                "event_row_id": "row-1",
                "event": "event_marker",
                "session_id": "session-a",
                "experiment_id": "exp1",
                "scenario_id": "occlusion_recovery",
                "trial_id": "trial-1",
                "event_id": "event-1",
                "mono_ms": 100.0,
            },
            {
                "event_row_id": "row-2",
                "event": "event_marker",
                "session_id": "session-a",
                "experiment_id": "exp1",
                "scenario_id": "occlusion_recovery",
                "trial_id": "trial-1",
                "event_id": "event-2",
                "mono_ms": 300.0,
            },
        ]
        payload_rows = [
            {"event_row_id": "row-trial", "json_path": "payload.event_role", "event_role": "@empty-text"},
            {"event_row_id": "row-1", "json_path": "payload.event_role", "event_role": "occlusion_started"},
            {"event_row_id": "row-2", "json_path": "payload.event_role", "event_role": "target_visible"},
        ]

        markers = parse_event_markers(event_rows, payload_rows)
        windows = build_event_windows(markers, trial_end_ms=500.0)
        occlusions = pair_occlusion_windows(markers, trial_end_ms=500.0)

        self.assertEqual([item.role for item in markers], ["occlusion_started", "target_visible"])
        self.assertEqual([(item.start_ms, item.end_ms) for item in windows], [(100.0, 300.0), (300.0, 500.0)])
        self.assertEqual(occlusions[0].occlusion_start_ms, 100.0)
        self.assertEqual(occlusions[0].visible_start_ms, 300.0)
        self.assertEqual(occlusions[0].end_ms, 500.0)

        duplicate_time = [markers[0], replace(markers[1], mono_ms=markers[0].mono_ms)]
        with self.assertRaisesRegex(ValueError, "严格递增"):
            pair_occlusion_windows(duplicate_time, trial_end_ms=500.0)

    def test_reference_motion_uses_speed_and_excursion_guards(self) -> None:
        """marker 窗内首个运动开始和最后一次停止由平台参考检测。"""

        times = np.arange(0.0, 1100.0, 100.0)
        linear_speed = np.array([0.0, 0.0, 0.06, 0.06, 0.06, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        angular_speed = np.zeros_like(linear_speed)
        positions = np.zeros((len(times), 3))
        positions[2:, 0] = np.array([0.0, 0.004, 0.008, 0.008, 0.008, 0.008, 0.008, 0.008, 0.008])
        rotations = np.tile([0.0, 0.0, 0.0, 1.0], (len(times), 1))

        params = replace(load_analysis_parameters(), reference_speed_median_frames=1)
        interval = detect_reference_motion(
            times,
            linear_speed,
            angular_speed,
            positions,
            rotations,
            params,
        )

        self.assertIsNotNone(interval)
        assert interval is not None
        self.assertEqual(interval.onset_ms, 200.0)
        self.assertEqual(interval.stop_ms, 500.0)

    def test_reference_motion_duration_uses_active_samples(self) -> None:
        """单个活动样本不得借用首个静止样本凑足最短运动时长。"""

        times = np.array([0.0, 100.0, 200.0])
        linear_speed = np.array([0.0, 0.06, 0.0])
        angular_speed = np.zeros_like(linear_speed)
        positions = np.array([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [0.01, 0.0, 0.0]])
        rotations = np.tile([0.0, 0.0, 0.0, 1.0], (len(times), 1))
        params = replace(load_analysis_parameters(), reference_speed_median_frames=1)

        interval = detect_reference_motion(
            times,
            linear_speed,
            angular_speed,
            positions,
            rotations,
            params,
        )

        self.assertIsNone(interval)


class AggregateMetricTests(unittest.TestCase):
    """验证 event-first 汇总、HP-RMS、漂移和状态转换指标。"""

    def test_p95_is_computed_inside_each_event_before_summary(self) -> None:
        """event P95 的中位数不得退化为混池 frame P95。"""

        values = {
            "event-a": np.array([0.0, 0.0, 100.0]),
            "event-b": np.array([10.0, 10.0, 10.0]),
        }

        params = load_analysis_parameters()
        per_event = event_quantiles(values, params.p95_quantile, params)
        summary = median_iqr(per_event.values(), params)
        pooled = float(np.quantile(np.concatenate(list(values.values())), 0.95, method="linear"))

        self.assertAlmostEqual(per_event["event-a"], 90.0)
        self.assertAlmostEqual(per_event["event-b"], 10.0)
        self.assertAlmostEqual(summary.median, 50.0)
        self.assertNotAlmostEqual(summary.median, pooled)

    def test_hp_rms_removes_constant_offset_and_drift_is_analytic(self) -> None:
        """高通应去除常量误差，漂移应使用首尾固定时窗。"""

        times = np.arange(0.0, 5000.0, 10.0)
        constant_error = np.tile([0.01, -0.02, 0.005], (len(times), 1))
        drift_error = np.zeros_like(constant_error)
        drift_error[:, 0] = times / times[-1] * 0.01

        params = load_analysis_parameters()
        valid = np.ones(len(times), dtype=np.bool_)
        hp_rms = position_hp_rms_mm(times, constant_error, valid, params)
        drift = position_drift_mm(times, drift_error, valid, params)

        self.assertLess(hp_rms, 1e-6)
        self.assertAlmostEqual(drift, 8.016032064128256, places=6)

    def test_visible_response_settling_and_recovery_require_duration(self) -> None:
        """响应、沉降和恢复都必须满足冻结的持续时间与 freshness 条件。"""

        times = np.arange(0.0, 1100.0, 50.0)
        positions = np.zeros((len(times), 3))
        positions[times >= 400.0, 0] = 0.006
        rotations = np.tile([0.0, 0.0, 0.0, 1.0], (len(times), 1))
        error_mm = np.where(times < 600.0, 30.0, 10.0)

        params = replace(load_analysis_parameters(), response_baseline_ms=200.0)
        response = visible_response_ms(
            times,
            positions,
            rotations,
            np.ones(len(times), dtype=np.bool_),
            reference_onset_ms=300.0,
            params=params,
        )
        settling = settling_time_ms(
            times,
            error_mm,
            np.ones(len(times), dtype=np.bool_),
            reference_stop_ms=500.0,
            params=params,
        )
        has_output = times == 550.0
        has_timing = has_output.copy()
        source_capture = np.where(has_output, 520.0, np.nan)
        recovery = durable_recovery_time_ms(
            times,
            error_mm,
            np.ones(len(times), dtype=np.bool_),
            has_output,
            has_timing,
            source_capture,
            target_visible_ms=500.0,
            params=params,
        )

        self.assertEqual(response, 100.0)
        self.assertEqual(settling, 100.0)
        self.assertEqual(recovery, 100.0)

    def test_recovery_rejects_stale_hold_without_fresh_output(self) -> None:
        """误差已达标的 held display 不能在没有新鲜 output 时宣告恢复。"""

        times = np.arange(500.0, 1000.0, 50.0)
        errors = np.zeros_like(times)
        has_output = np.zeros_like(times, dtype=np.bool_)
        has_timing = np.zeros_like(times, dtype=np.bool_)
        captures = np.full_like(times, np.nan)

        result = durable_recovery_time_ms(
            times,
            errors,
            np.ones(len(times), dtype=np.bool_),
            has_output,
            has_timing,
            captures,
            target_visible_ms=500.0,
            params=load_analysis_parameters(),
        )

        self.assertIsNone(result)

        has_output[1] = True
        captures[1] = 550.0
        stale_timing = durable_recovery_time_ms(
            times,
            errors,
            np.ones(len(times), dtype=np.bool_),
            has_output,
            has_timing,
            captures,
            target_visible_ms=500.0,
            params=load_analysis_parameters(),
        )
        self.assertIsNone(stale_timing)

    def test_recovery_accepts_marker_between_render_ticks(self) -> None:
        """marker 早于首条恢复 render 一个合法采样间隔时仍属于同一窗口。"""

        times = np.arange(500.0, 1000.0, 50.0)
        errors = np.zeros_like(times)
        has_output = times == 550.0
        has_timing = has_output.copy()
        captures = np.where(has_output, 520.0, np.nan)

        recovery = durable_recovery_time_ms(
            times,
            errors,
            np.ones(len(times), dtype=np.bool_),
            has_output,
            has_timing,
            captures,
            target_visible_ms=490.0,
            params=load_analysis_parameters(),
        )

        self.assertEqual(recovery, 60.0)


class LagAndLatencyTests(unittest.TestCase):
    """验证轨迹 lag 和严格单调时钟约束。"""

    def test_translation_and_rotation_lag_recover_known_shift(self) -> None:
        """平移和旋转合成轨迹应恢复一百毫秒已知滞后。"""

        times = np.arange(0.0, 5000.0, 10.0)
        phase = 2.0 * math.pi * times / 2000.0
        delayed_phase = 2.0 * math.pi * (times - 100.0) / 2000.0
        reference_pos = np.column_stack([np.sin(phase), np.zeros_like(phase), np.zeros_like(phase)])
        display_pos = np.column_stack([np.sin(delayed_phase), np.zeros_like(phase), np.zeros_like(phase)])
        reference_rot = np.column_stack(
            [np.zeros_like(phase), np.zeros_like(phase), np.sin(phase / 4.0), np.cos(phase / 4.0)],
        )
        display_rot = np.column_stack(
            [np.zeros_like(phase), np.zeros_like(phase), np.sin(delayed_phase / 4.0), np.cos(delayed_phase / 4.0)],
        )

        params = load_analysis_parameters()
        valid = np.ones(len(times), dtype=np.bool_)
        translation = estimate_translation_lag(times, display_pos, reference_pos, valid, params)
        angular = estimate_angular_lag(times, display_rot, reference_rot, valid, params)

        self.assertEqual(translation.lag_ms, 100.0)
        self.assertEqual(angular.lag_ms, 100.0)
        self.assertLess(translation.residual, 1e-9)
        self.assertLess(angular.residual, 1e-7)

    def test_translation_lag_does_not_interpolate_across_large_gap(self) -> None:
        """lag 搜索不得利用大间隙两侧样本做跨断点线性插值。"""

        times = np.array([0.0, 10.0, 20.0, 30.0, 40.0, 1000.0, 1010.0, 1020.0, 1030.0, 1040.0])
        reference_x = times / 10.0
        display_x = np.concatenate([reference_x[:5], reference_x[5:] - 10.0])
        reference = np.column_stack([reference_x, np.zeros(len(times)), np.zeros(len(times))])
        display = np.column_stack([display_x, np.zeros(len(times)), np.zeros(len(times))])
        params = replace(
            load_analysis_parameters(),
            lag_minimum_overlap_samples=2,
            lag_minimum_overlap_fraction=0.5,
        )

        estimate = estimate_translation_lag(
            times,
            display,
            reference,
            np.ones(len(times), dtype=np.bool_),
            params,
        )

        self.assertEqual(estimate.lag_ms, 20.0)
        self.assertNotEqual(estimate.lag_ms, 100.0)

    def test_latency_uses_only_same_process_monotonic_clocks(self) -> None:
        """合法同域时延可计算，Unity 与 Python 单调时钟不得相减。"""

        arrival = candidate_arrival_ms(
            MonotonicTimestamp(100.0, ClockDomain.UNITY),
            MonotonicTimestamp(135.0, ClockDomain.UNITY),
        )
        processing = python_processing_ms(
            MonotonicTimestamp(20.0, ClockDomain.PYTHON),
            MonotonicTimestamp(42.0, ClockDomain.PYTHON),
        )

        self.assertEqual(arrival, 35.0)
        self.assertEqual(processing, 22.0)
        with self.assertRaisesRegex(ValueError, "跨单调时钟"):
            candidate_arrival_ms(
                MonotonicTimestamp(100.0, ClockDomain.UNITY),
                MonotonicTimestamp(135.0, ClockDomain.PYTHON),
            )
        with self.assertRaisesRegex(ValueError, "早于开始"):
            python_processing_ms(
                MonotonicTimestamp(42.0, ClockDomain.PYTHON),
                MonotonicTimestamp(20.0, ClockDomain.PYTHON),
            )


if __name__ == "__main__":
    unittest.main()
