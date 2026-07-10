"""RQ2 动态追踪分析的合成轨迹测试。"""

from __future__ import annotations

import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from egoanchor.eval.research.rq2 import (
    build_source_observations,
    compute_motion_delay,
    compute_trial_summary,
    run_rq2_analysis,
)
from egoanchor.eval.io import SessionLogs


class RQ2AnalyzeTest(unittest.TestCase):
    """验证 RQ2 的时间插值、运动项和试次统计契约。"""

    def test_translation_motion_keeps_capture_bias_in_handle_residual(self) -> None:
        """handle 有符号残差应等于独立 capture 偏置与时延暴露量之和。"""

        output = self._trajectory("slow_translation", trial_id=1, angular=False)
        output["rq2_target_linear_speed_m_s"] = 2.0
        self._set_raw_pose(output, position=np.array([0.38, 0.0, 0.0]))

        source = build_source_observations(output)
        delay = compute_motion_delay(source, output)

        frame = source[source["source_frame_id"] == 4]
        self.assertEqual(len(frame), 1)
        self.assertAlmostEqual(float(frame.iloc[0]["first_render_mono_ms"]), 500.0)
        motion = delay[delay["source_frame_id"] == 4].iloc[0]
        self.assertNotIn("translation_delay_handle_m", motion.index)
        self.assertAlmostEqual(
            float(motion["reference_translation_motion_handle_m"]), 0.1, places=6
        )
        self.assertAlmostEqual(float(motion["expected_translation_handle_m"]), 0.1, places=6)
        self.assertAlmostEqual(
            float(motion["raw_translation_lag_error_capture_m"]), 0.02, places=6
        )
        self.assertAlmostEqual(
            float(motion["raw_translation_lag_error_handle_m"]), 0.12, places=6
        )

    def test_rotation_motion_keeps_capture_bias_in_handle_residual(self) -> None:
        """旋转残差应在预图像世界旋转轴上保留 capture 偏置。"""

        output = self._trajectory("rotation", trial_id=2, angular=True)
        output["rq2_target_angular_speed_deg_s"] = 180.0
        self._set_raw_pose(output, rotation=self._yaw_quat(34.0))

        source = build_source_observations(output)
        delay = compute_motion_delay(source, output)

        motion = delay[delay["source_frame_id"] == 4].iloc[0]
        self.assertNotIn("rotation_delay_handle_deg", motion.index)
        self.assertAlmostEqual(
            float(motion["reference_rotation_motion_handle_deg"]), 9.0, places=5
        )
        self.assertAlmostEqual(float(motion["expected_rotation_handle_deg"]), 9.0, places=5)
        self.assertAlmostEqual(
            float(motion["raw_rotation_lag_error_capture_deg"]), 2.0, places=5
        )
        self.assertAlmostEqual(
            float(motion["raw_rotation_lag_error_handle_deg"]), 11.0, places=5
        )

    def test_reverse_motion_uses_signed_world_direction_and_axis(self) -> None:
        """反向平移与旋转的滞后残差仍应沿各自运动方向为正。"""

        translation = self._trajectory("slow_translation", trial_id=3, angular=False)
        for index, render_ms in translation["render_mono_ms"].items():
            pose = np.array([-float(render_ms) / 1000.0, 0.0, 0.0])
            translation.at[index, "gt_pos"] = pose
            translation.at[index, "output_pos"] = pose.copy()
        self._set_raw_pose(translation, position=np.array([-0.38, 0.0, 0.0]))
        translation_motion = compute_motion_delay(
            build_source_observations(translation), translation
        ).iloc[0]

        rotation = self._trajectory("rotation", trial_id=4, angular=True)
        for index, render_ms in rotation["render_mono_ms"].items():
            pose = self._yaw_quat(-90.0 * float(render_ms) / 1000.0)
            rotation.at[index, "gt_rot"] = pose
            rotation.at[index, "output_rot"] = pose.copy()
        self._set_raw_pose(rotation, rotation=self._yaw_quat(-34.0))
        rotation_motion = compute_motion_delay(build_source_observations(rotation), rotation).iloc[0]

        self.assertAlmostEqual(
            float(translation_motion["raw_translation_lag_error_capture_m"]), 0.02, places=6
        )
        self.assertAlmostEqual(
            float(translation_motion["raw_translation_lag_error_handle_m"]), 0.12, places=6
        )
        self.assertAlmostEqual(
            float(rotation_motion["raw_rotation_lag_error_capture_deg"]), 2.0, places=5
        )
        self.assertAlmostEqual(
            float(rotation_motion["raw_rotation_lag_error_handle_deg"]), 11.0, places=5
        )

    def test_pre_image_fit_is_robust_to_single_gt_outlier(self) -> None:
        """固定前序窗口中的单个位置离群点不应主导速度预测。"""

        output = self._trajectory("slow_translation", trial_id=5, angular=False)
        outlier = output["render_mono_ms"] == 200.0
        output.loc[outlier, "gt_pos"] = output.loc[outlier, "gt_pos"].map(
            lambda _: np.array([2.2, 0.0, 0.0])
        )
        motion = compute_motion_delay(build_source_observations(output), output).iloc[0]

        self.assertAlmostEqual(float(motion["pre_image_linear_speed_m_s"]), 1.0, places=6)
        self.assertAlmostEqual(float(motion["expected_translation_handle_m"]), 0.1, places=6)

    def test_pre_image_fit_requires_complete_history_window(self) -> None:
        """图像前历史不足固定窗口时，方向、速度和模型残差应为 NaN。"""

        output = self._trajectory("slow_translation", trial_id=6, angular=False)
        mask = output["source_frame_id"] == 4
        output.loc[mask, "source_capture_mono_ms"] = 100.0
        output.loc[mask, "unity_pose_handle_mono_ms"] = 200.0
        self._set_raw_pose(output, position=np.array([0.1, 0.0, 0.0]))
        motion = compute_motion_delay(build_source_observations(output), output).iloc[0]

        for column in (
            "pre_image_linear_speed_m_s",
            "reference_translation_motion_handle_m",
            "raw_translation_lag_error_capture_m",
            "raw_translation_lag_error_handle_m",
            "expected_translation_handle_m",
        ):
            self.assertTrue(np.isnan(float(motion[column])), column)

    def test_reference_interpolation_does_not_cross_invalid_gt_gap(self) -> None:
        """图像代理时刻落在 GT 失效空窗内时，不得跨空窗合成参考 pose。"""

        output = self._lag_trajectory()
        gap = (output["render_mono_ms"] > 2000.0) & (output["render_mono_ms"] < 3000.0)
        output.loc[gap, ["gt_pose_valid", "valid"]] = False

        source = build_source_observations(output)
        frame = source[source["source_frame_id"] == 125].iloc[0]

        self.assertIsNone(frame["gt_image_pos"])
        self.assertIsNone(frame["gt_image_rot"])
        self.assertTrue(np.isnan(float(frame["raw_translation_error_image_m"])))
        self.assertTrue(np.isnan(float(frame["raw_rotation_error_image_deg"])))

    def test_reference_interpolation_preserves_single_sample_gt_gap(self) -> None:
        """单个采样点的 GT 失效也必须切断参考轨迹，不能被间隔阈值吞掉。"""

        output = self._lag_trajectory()
        output.loc[output["render_mono_ms"] == 40.0, ["gt_pose_valid", "valid"]] = False
        target = output["render_mono_ms"] == 60.0
        output.loc[target, "source_capture_mono_ms"] = 40.0

        source = build_source_observations(output)
        frame = source[source["source_frame_id"] == 3].iloc[0]

        self.assertIsNone(frame["gt_image_pos"])
        self.assertIsNone(frame["gt_image_rot"])
        self.assertTrue(np.isnan(float(frame["raw_translation_error_image_m"])))

    def test_pre_image_fit_does_not_cross_invalid_gt_gap(self) -> None:
        """400 ms 速度窗口含 GT 失效空窗时不得跨段拟合。"""

        output = self._lag_trajectory()
        gap = (output["render_mono_ms"] > 2150.0) & (output["render_mono_ms"] < 2250.0)
        output.loc[gap, ["gt_pose_valid", "valid"]] = False

        motion_table = compute_motion_delay(build_source_observations(output), output)
        motion = motion_table[motion_table["source_frame_id"] == 125].iloc[0]

        self.assertTrue(np.isnan(float(motion["pre_image_linear_speed_m_s"])))
        self.assertTrue(np.isnan(float(motion["expected_translation_handle_m"])))

    def test_build_source_does_not_require_tick_index(self) -> None:
        """直接构造的 output 表缺少 tick_index 时仍应按渲染时间去重。"""

        output = self._trajectory("slow_translation", trial_id=8, angular=False).drop(
            columns="tick_index"
        )

        source = build_source_observations(output)

        self.assertEqual(len(source), 1)

    def test_trial_summary_counts_frames_without_output_in_availability(self) -> None:
        """可用率分母应包含有效试次内没有输出 pose 的渲染帧。"""

        output = self._trajectory("fast_motion", trial_id=7, angular=False)
        output.loc[output["render_mono_ms"] == 700.0, ["has_output_pose", "output_pos", "output_rot"]] = [
            False,
            None,
            None,
        ]
        source = build_source_observations(output)

        summary = compute_trial_summary(output, source)

        self.assertEqual(len(summary), 1)
        trial = summary.iloc[0]
        self.assertEqual(int(trial["rq2_trial_id"]), 7)
        self.assertEqual(int(trial["render_frame_count"]), 11)
        self.assertEqual(int(trial["output_frame_count"]), 10)
        self.assertAlmostEqual(float(trial["tracking_availability"]), 10.0 / 11.0)
        self.assertEqual(int(trial["display_error_sample_count"]), 10)
        self.assertEqual(int(trial["raw_error_sample_count"]), 1)

    def test_trial_summary_keeps_hold_last_display_error_out_of_availability(self) -> None:
        """hold-last pose 应进入显示误差，但 runtime 可用率仍记为失效。"""

        output = self._trajectory("fast_motion", trial_id=14, angular=False)
        held = output["render_mono_ms"] == 700.0
        output["has_display_pose"] = True
        output["display_pos"] = output["output_pos"].map(np.copy)
        output["display_rot"] = output["output_rot"].map(np.copy)
        output.loc[held, "has_output_pose"] = False
        for index in output.index[held]:
            output.at[index, "output_pos"] = None
            output.at[index, "output_rot"] = None
            output.at[index, "display_pos"] = np.array([0.5, 0.0, 0.0])

        trial = compute_trial_summary(output, build_source_observations(output)).iloc[0]

        self.assertEqual(int(trial["output_frame_count"]), 10)
        self.assertAlmostEqual(float(trial["tracking_availability"]), 10.0 / 11.0)
        self.assertEqual(int(trial["display_error_sample_count"]), 11)

    def test_trial_summary_uses_display_columns_for_each_variant(self) -> None:
        """每个系统变体都应使用通用 display 指标列，不绑定 Full 标签。"""

        full = self._trajectory("fast_motion", trial_id=15, angular=False)
        baseline = full.copy(deep=True)
        baseline["label"] = "Raw-ZOH"
        baseline["is_primary"] = False
        for index in range(1, len(baseline), 2):
            baseline.at[index, "output_pos"] = baseline.at[index - 1, "output_pos"].copy()
            baseline.at[index, "output_rot"] = baseline.at[index - 1, "output_rot"].copy()
        output = pd.concat([full, baseline], ignore_index=True)

        source = build_source_observations(output)
        summary = compute_trial_summary(output, source)

        self.assertEqual(set(source["label"]), {"Full"})
        self.assertEqual(set(summary["label"]), {"Full", "Raw-ZOH"})
        self.assertTrue((summary["raw_error_sample_count"] > 0).all())
        by_label = summary.set_index("label")
        self.assertAlmostEqual(float(by_label.loc["Full", "display_hold_fraction"]), 0.0)
        self.assertAlmostEqual(float(by_label.loc["Full", "display_update_rate_hz"]), 10.0)
        self.assertAlmostEqual(float(by_label.loc["Raw-ZOH", "display_hold_fraction"]), 0.5)
        self.assertAlmostEqual(float(by_label.loc["Raw-ZOH", "display_update_rate_hz"]), 5.0)
        expected = {
            "display_error_sample_count",
            "display_update_rate_hz",
            "display_hold_fraction",
            "display_translation_median_m",
            "display_translation_p95_m",
            "display_rotation_median_deg",
            "display_rotation_p95_deg",
            "display_translation_lag_ms",
            "display_minus_raw_translation_lag_ms",
            "display_rotation_lag_ms",
            "display_minus_raw_rotation_lag_ms",
            "display_lag_segment_count",
        }
        self.assertTrue(expected.issubset(summary.columns))
        self.assertFalse(any(column.startswith("full_") for column in summary.columns))

    def test_trial_summary_accepts_empty_source_with_fixed_columns(self) -> None:
        """没有有效 raw source 时仍应正常汇总各变体的显示输出。"""

        output = self._trajectory("fast_motion", trial_id=10, angular=False)

        summary = compute_trial_summary(output, pd.DataFrame())

        self.assertEqual(len(summary), 1)
        self.assertEqual(int(summary.iloc[0]["raw_error_sample_count"]), 0)
        self.assertTrue(np.isnan(float(summary.iloc[0]["raw_translation_median_m"])))

    def test_trial_summary_reports_positive_raw_and_display_lag(self) -> None:
        """已知 100/200 ms 滞后应给出正 lag，并得到显示相对 raw 的增量。"""

        output = self._lag_trajectory()
        source = build_source_observations(output)

        summary = compute_trial_summary(output, source)

        trial = summary.iloc[0]
        self.assertAlmostEqual(float(trial["raw_translation_lag_ms"]), 100.0, delta=25.0)
        self.assertAlmostEqual(float(trial["display_translation_lag_ms"]), 200.0, delta=25.0)
        self.assertAlmostEqual(
            float(trial["display_minus_raw_translation_lag_ms"]), 100.0, delta=25.0
        )
        self.assertAlmostEqual(float(trial["raw_rotation_lag_ms"]), 100.0, delta=25.0)
        self.assertAlmostEqual(float(trial["display_rotation_lag_ms"]), 200.0, delta=25.0)
        self.assertAlmostEqual(
            float(trial["display_minus_raw_rotation_lag_ms"]), 100.0, delta=25.0
        )

    def test_rotation_lag_is_nan_for_constant_speed_without_branch_crossing(self) -> None:
        """未跨 180°的纯匀速旋转缺少可辨识激励，rotation lag 应为 NaN。"""

        output = self._constant_rotation_lag_trajectory(duration_ms=1000.0, speed_deg_s=30.0)
        summary = compute_trial_summary(output, build_source_observations(output)).iloc[0]

        self.assertTrue(np.isnan(float(summary["raw_rotation_lag_ms"])))
        self.assertTrue(np.isnan(float(summary["display_rotation_lag_ms"])))

    def test_rotation_lag_is_nan_for_constant_speed_crossing_180_degrees(self) -> None:
        """跨 180°的纯匀速旋转不得因 rotvec 主值跳变产生虚假 lag。"""

        output = self._constant_rotation_lag_trajectory(duration_ms=5000.0, speed_deg_s=90.0)
        summary = compute_trial_summary(output, build_source_observations(output)).iloc[0]

        self.assertTrue(np.isnan(float(summary["raw_rotation_lag_ms"])))
        self.assertTrue(np.isnan(float(summary["display_rotation_lag_ms"])))

    def test_lag_splits_tracking_gaps_before_resampling(self) -> None:
        """raw/显示轨迹的 tracking 缺口不得被 Slerp 跨越。"""

        output = self._lag_trajectory()
        gap = (output["render_mono_ms"] > 2000.0) & (output["render_mono_ms"] < 3000.0)
        output.loc[gap, "has_aligned_raw"] = False
        output.loc[gap, "has_source_capture_timing"] = False
        output.loc[gap, "unity_pose_handle_mono_ms"] = np.nan
        output.loc[gap, "has_output_pose"] = False
        for index in output.index[gap]:
            output.at[index, "aligned_raw_pos"] = None
            output.at[index, "aligned_raw_rot"] = None
            output.at[index, "output_pos"] = None
            output.at[index, "output_rot"] = None

        summary = compute_trial_summary(output, build_source_observations(output)).iloc[0]

        self.assertEqual(int(summary["raw_lag_segment_count"]), 2)
        self.assertEqual(int(summary["display_lag_segment_count"]), 2)
        self.assertAlmostEqual(float(summary["raw_rotation_lag_ms"]), 100.0, delta=25.0)
        self.assertAlmostEqual(float(summary["display_rotation_lag_ms"]), 200.0, delta=25.0)

    def test_lag_keeps_continuous_seven_fps_stream_in_one_segment(self) -> None:
        """约 140 ms 的稳定 source 间隔不应被绝对阈值误判为 reacquire 缺口。"""

        output = self._lag_trajectory().iloc[::7].reset_index(drop=True)
        output["tick_index"] = np.arange(len(output))
        summary = compute_trial_summary(output, build_source_observations(output)).iloc[0]

        self.assertEqual(int(summary["raw_lag_segment_count"]), 1)
        self.assertEqual(int(summary["display_lag_segment_count"]), 1)

    def test_lag_is_nan_for_independent_noise(self) -> None:
        """只有方差但与参考运动不相关的轨迹不得被强制解释为具体 lag。"""

        output = self._lag_trajectory()
        rng = np.random.default_rng(20260710)
        for index in output.index:
            raw_position = rng.normal(0.0, 0.2, size=3)
            display_position = rng.normal(0.0, 0.2, size=3)
            raw_rotation = self._yaw_quat(float(rng.normal(0.0, 30.0)))
            display_rotation = self._yaw_quat(float(rng.normal(0.0, 30.0)))
            output.at[index, "aligned_raw_pos"] = raw_position
            output.at[index, "aligned_raw_rot"] = raw_rotation
            output.at[index, "output_pos"] = display_position
            output.at[index, "output_rot"] = display_rotation

        summary = compute_trial_summary(output, build_source_observations(output)).iloc[0]

        for column in (
            "raw_translation_lag_ms",
            "display_translation_lag_ms",
            "raw_rotation_lag_ms",
            "display_rotation_lag_ms",
        ):
            self.assertTrue(np.isnan(float(summary[column])), column)

    def test_lag_is_nan_for_short_independent_noise(self) -> None:
        """短轨迹上的偶然高相关不得被报告为可辨识 lag。"""

        output = self._lag_trajectory().iloc[:12].copy().reset_index(drop=True)
        output["tick_index"] = np.arange(len(output))
        rng = np.random.default_rng(37)
        for index in output.index:
            output.at[index, "aligned_raw_pos"] = rng.normal(0.0, 0.2, size=3)
            output.at[index, "aligned_raw_rot"] = self._yaw_quat(
                float(rng.normal(0.0, 30.0))
            )
            output.at[index, "output_pos"] = rng.normal(0.0, 0.2, size=3)
            output.at[index, "output_rot"] = self._yaw_quat(
                float(rng.normal(0.0, 30.0))
            )

        summary = compute_trial_summary(output, build_source_observations(output)).iloc[0]

        for column in (
            "raw_translation_lag_ms",
            "display_translation_lag_ms",
            "raw_rotation_lag_ms",
            "display_rotation_lag_ms",
        ):
            self.assertTrue(np.isnan(float(summary[column])), column)

    def test_trial_smoothing_delay_uses_all_motion_render_frames(self) -> None:
        """策略延迟应按试次全部渲染帧汇总，而非 source 首现子集。"""

        output = self._trajectory("slow_translation", trial_id=9, angular=False)
        output["smoothing_delay_ms"] = 200.0
        output.loc[output["source_frame_id"] == 4, "smoothing_delay_ms"] = 10.0
        output["policy_output_target_mono_ms"] = output["render_mono_ms"] - 200.0
        output.loc[output["source_frame_id"] == 4, "policy_output_target_mono_ms"] = (
            output.loc[output["source_frame_id"] == 4, "render_mono_ms"] - 10.0
        )
        source = build_source_observations(output)

        summary = compute_trial_summary(output, source)

        self.assertAlmostEqual(float(summary.iloc[0]["smoothing_delay_p50_ms"]), 200.0)
        self.assertAlmostEqual(float(summary.iloc[0]["effective_policy_delay_p50_ms"]), 200.0)

    def test_run_analysis_writes_trial_level_tables(self) -> None:
        """全链路入口应保留四张既有表并新增模型一致性表。"""

        full = self._trajectory("slow_translation", trial_id=12, angular=False)
        baseline = full.copy(deep=True)
        baseline["label"] = "Raw-ZOH"
        baseline["is_primary"] = False
        output = pd.concat([full, baseline], ignore_index=True)
        logs = SessionLogs(
            capture=pd.DataFrame(),
            output=output,
            pose=pd.DataFrame(),
            manifest={"session_id": "synthetic"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "session"
            report_dir = Path(tmp) / "report"
            session_dir.mkdir()
            with patch("egoanchor.eval.research.rq2.core.load_session", return_value=logs):
                tables = run_rq2_analysis(session_dir, report_dir=report_dir)

            self.assertEqual(
                set(tables),
                {
                    "rq2_source_error",
                    "rq2_motion_delay",
                    "rq2_trial_summary",
                    "rq2_latency_summary",
                    "rq2_model_summary",
                },
            )
            self.assertEqual(set(tables["rq2_trial_summary"]["label"]), {"Full", "Raw-ZOH"})
            latency = tables["rq2_latency_summary"].set_index("label")
            self.assertAlmostEqual(float(latency.loc["Full", "effective_policy_delay_p50_ms"]), 120.0)
            self.assertAlmostEqual(
                float(latency.loc["Raw-ZOH", "effective_policy_delay_p50_ms"]), 120.0
            )
            self.assertGreater(int(latency.loc["Full", "source_frame_count"]), 0)
            self.assertEqual(
                int(latency.loc["Raw-ZOH", "source_frame_count"]),
                int(latency.loc["Full", "source_frame_count"]),
            )
            self.assertAlmostEqual(
                float(latency.loc["Raw-ZOH", "observation_delay_p50_ms"]),
                float(latency.loc["Full", "observation_delay_p50_ms"]),
            )
            latency_columns = tables["rq2_latency_summary"].columns
            self.assertIn("display_translation_lag_ms", latency_columns)
            self.assertIn("display_minus_raw_translation_lag_ms", latency_columns)
            self.assertNotIn("full_translation_lag_ms", latency_columns)
            for name in tables:
                self.assertTrue((report_dir / f"{name}.csv").is_file())

    def test_model_summary_uses_trials_as_bootstrap_clusters(self) -> None:
        """模型一致性应先按 trial 汇总，并以 trial 为 bootstrap cluster。"""

        from egoanchor.eval.research.rq2 import compute_model_summary

        rows: list[dict[str, object]] = []
        for trial_id, predicted in enumerate((0.04, 0.08, 0.12, 0.16), start=1):
            for frame_id in range(3):
                rows.append(
                    {
                        "condition": "slow_translation",
                        "rq2_trial_id": trial_id,
                        "label": "Full",
                        "source_frame_id": frame_id,
                        "expected_translation_handle_m": predicted,
                        "raw_translation_lag_error_handle_m": 0.01 + 2.0 * predicted,
                        "expected_rotation_handle_deg": np.nan,
                        "raw_rotation_lag_error_handle_deg": np.nan,
                    }
                )

        summary = compute_model_summary(pd.DataFrame.from_records(rows))
        trial_rows = summary[(summary["level"] == "trial") & (summary["channel"] == "translation")]
        scene = summary[(summary["level"] == "scene") & (summary["channel"] == "translation")].iloc[0]

        self.assertEqual(len(trial_rows), 4)
        self.assertTrue((trial_rows["n"] == 3).all())
        self.assertAlmostEqual(float(trial_rows.iloc[0]["bias"]), 0.05, places=6)
        self.assertAlmostEqual(float(scene["slope"]), 2.0, places=6)
        self.assertAlmostEqual(float(scene["intercept"]), 0.01, places=6)
        self.assertTrue(np.isfinite(float(scene["slope_ci_low"])))
        self.assertTrue(np.isfinite(float(scene["slope_ci_high"])))

    def test_module_cli_has_no_runpy_reimport_warning(self) -> None:
        """包级显式 re-export 不应污染 ``python -m ...analyze`` CLI。"""

        result = subprocess.run(
            [sys.executable, "-m", "egoanchor.eval.research.rq2.analyze", "--help"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("RuntimeWarning", result.stderr)

    @classmethod
    def _trajectory(cls, condition: str, *, trial_id: int, angular: bool) -> pd.DataFrame:
        """构造 0--1 s 匀速轨迹，并让 frame 4 在两个渲染 tick 重复出现。"""

        rows: list[dict[str, object]] = []
        for index, render_ms in enumerate(np.arange(0.0, 1000.1, 100.0)):
            seconds = render_ms / 1000.0
            gt_pos = np.array([0.0 if angular else seconds, 0.0, 0.0])
            gt_rot = cls._yaw_quat(90.0 * seconds if angular else 0.0)
            source_frame = 4 if render_ms in (500.0, 600.0) else index + 100
            has_raw = source_frame == 4
            image_ms = 400.0 if has_raw else np.nan
            raw_seconds = image_ms / 1000.0 if has_raw else 0.0
            rows.append(
                {
                    "tick_index": index,
                    "label": "Full",
                    "is_primary": True,
                    "render_mono_ms": render_ms,
                    "render_source_frame_id": source_frame,
                    "source_frame_id": source_frame,
                    "gt_pos": gt_pos,
                    "gt_rot": gt_rot,
                    "gt_pose_valid": True,
                    "valid": True,
                    "has_output_pose": True,
                    "output_pos": gt_pos.copy(),
                    "output_rot": gt_rot.copy(),
                    "has_source_capture_timing": has_raw,
                    "source_capture_mono_ms": image_ms,
                    "has_aligned_raw": has_raw,
                    "aligned_raw_pos": (
                        np.array([0.0 if angular else raw_seconds, 0.0, 0.0]) if has_raw else None
                    ),
                    "aligned_raw_rot": cls._yaw_quat(90.0 * raw_seconds if angular else 0.0) if has_raw else None,
                    "unity_pose_handle_mono_ms": 500.0 if has_raw else np.nan,
                    "policy_output_target_mono_ms": render_ms - 120.0,
                    "observation_age_ms": 100.0 if has_raw else np.nan,
                    "smoothing_delay_ms": 120.0,
                    "rq2_condition": condition,
                    "rq2_trial_id": trial_id,
                    "rq2_target_linear_speed_m_s": np.nan if angular else 1.0,
                    "rq2_target_angular_speed_deg_s": 90.0 if angular else np.nan,
                }
            )
        return pd.DataFrame.from_records(rows)

    @staticmethod
    def _yaw_quat(angle_deg: float) -> np.ndarray:
        """构造绕 z 轴旋转的 xyzw 四元数。"""

        half = math.radians(angle_deg) / 2.0
        return np.array([0.0, 0.0, math.sin(half), math.cos(half)], dtype=float)

    @classmethod
    def _lag_trajectory(cls) -> pd.DataFrame:
        """构造同时含 100 ms raw 滞后和 200 ms 显示滞后的周期轨迹。"""

        rows: list[dict[str, object]] = []
        for index, render_ms in enumerate(np.arange(0.0, 5000.1, 20.0)):
            raw_ms = render_ms - 100.0
            display_ms = render_ms - 200.0
            gt_pos, gt_rot = cls._periodic_pose(render_ms)
            raw_pos, raw_rot = cls._periodic_pose(raw_ms)
            display_pos, display_rot = cls._periodic_pose(display_ms)
            rows.append(
                {
                    "tick_index": index,
                    "label": "Full",
                    "is_primary": True,
                    "render_mono_ms": render_ms,
                    "render_source_frame_id": index,
                    "source_frame_id": index,
                    "gt_pos": gt_pos,
                    "gt_rot": gt_rot,
                    "gt_pose_valid": True,
                    "valid": True,
                    "has_output_pose": True,
                    "output_pos": display_pos,
                    "output_rot": display_rot,
                    "has_source_capture_timing": True,
                    "source_capture_mono_ms": raw_ms,
                    "has_aligned_raw": True,
                    "aligned_raw_pos": raw_pos,
                    "aligned_raw_rot": raw_rot,
                    "unity_pose_handle_mono_ms": render_ms,
                    "policy_output_target_mono_ms": display_ms,
                    "observation_age_ms": 100.0,
                    "smoothing_delay_ms": 200.0,
                    "rq2_condition": "fast_motion",
                    "rq2_trial_id": 11,
                    "rq2_target_linear_speed_m_s": np.nan,
                    "rq2_target_angular_speed_deg_s": np.nan,
                }
            )
        return pd.DataFrame.from_records(rows)

    @classmethod
    def _periodic_pose(cls, mono_ms: float) -> tuple[np.ndarray, np.ndarray]:
        """生成非同频平移与旋转信号，避免互相关的周期歧义。"""

        seconds = mono_ms / 1000.0
        position = np.array(
            [math.sin(2.0 * math.pi * seconds / 1.3), 0.15 * math.sin(2.0 * math.pi * seconds / 0.7), 0.0]
        )
        yaw = 35.0 * math.sin(2.0 * math.pi * seconds / 1.1) + 8.0 * math.sin(
            2.0 * math.pi * seconds / 0.43
        )
        return position, cls._yaw_quat(yaw)

    @classmethod
    def _constant_rotation_lag_trajectory(
        cls,
        *,
        duration_ms: float,
        speed_deg_s: float,
    ) -> pd.DataFrame:
        """构造角速度恒定、raw/显示输出分别滞后 100/200 ms 的旋转轨迹。"""

        rows: list[dict[str, object]] = []
        for index, render_ms in enumerate(np.arange(0.0, duration_ms + 0.1, 20.0)):
            image_ms = render_ms - 100.0
            display_ms = render_ms - 200.0
            rows.append(
                {
                    "tick_index": index,
                    "label": "Full",
                    "is_primary": True,
                    "render_mono_ms": render_ms,
                    "render_source_frame_id": index,
                    "source_frame_id": index,
                    "gt_pos": np.zeros(3),
                    "gt_rot": cls._yaw_quat(speed_deg_s * render_ms / 1000.0),
                    "gt_pose_valid": True,
                    "valid": True,
                    "has_output_pose": True,
                    "output_pos": np.zeros(3),
                    "output_rot": cls._yaw_quat(speed_deg_s * display_ms / 1000.0),
                    "has_source_capture_timing": True,
                    "source_capture_mono_ms": image_ms,
                    "has_aligned_raw": True,
                    "aligned_raw_pos": np.zeros(3),
                    "aligned_raw_rot": cls._yaw_quat(speed_deg_s * image_ms / 1000.0),
                    "unity_pose_handle_mono_ms": render_ms,
                    "policy_output_target_mono_ms": display_ms,
                    "observation_age_ms": 100.0,
                    "smoothing_delay_ms": 200.0,
                    "rq2_condition": "rotation",
                    "rq2_trial_id": 13,
                    "rq2_target_linear_speed_m_s": np.nan,
                    "rq2_target_angular_speed_deg_s": speed_deg_s,
                }
            )
        return pd.DataFrame.from_records(rows)

    @staticmethod
    def _set_raw_pose(
        output: pd.DataFrame,
        *,
        position: np.ndarray | None = None,
        rotation: np.ndarray | None = None,
    ) -> None:
        """修改重复出现的 source frame 4 raw pose。"""

        for index in output.index[output["source_frame_id"] == 4]:
            if position is not None:
                output.at[index, "aligned_raw_pos"] = position.copy()
            if rotation is not None:
                output.at[index, "aligned_raw_rot"] = rotation.copy()


if __name__ == "__main__":
    unittest.main()
