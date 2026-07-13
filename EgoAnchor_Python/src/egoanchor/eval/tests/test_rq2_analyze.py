"""RQ2 双任务分析核心与 CLI 单测。"""

from __future__ import annotations

import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from egoanchor.eval.research.rq2 import (
    RQ2_CONDITIONS,
    RQ2Config,
    annotate_active_motion,
    compute_condition_summary,
    compute_session_audit,
    compute_trial_audit,
    run_rq2_analysis,
)


def _yaw_quat(angle_deg: float) -> np.ndarray:
    """构造绕世界 z 轴旋转的 xyzw 四元数。"""

    half = math.radians(angle_deg) / 2.0
    return np.array([0.0, 0.0, math.sin(half), math.cos(half)], dtype=float)


def _paired_output(
    *,
    duration_s: float = 12.0,
    interval_ms: float = 50.0,
) -> pd.DataFrame:
    """构造平移/旋转各一试次的同步 Full 与 ZOH 日志。"""

    rows: list[dict[str, object]] = []
    tick = 0
    for condition, trial_id in (("translation", 1), ("rotation", 2)):
        for sample, render_ms in enumerate(np.arange(0.0, duration_s * 1000.0, interval_ms)):
            seconds = render_ms / 1000.0
            gt_pos = np.array([0.2 * seconds, 0.01 * math.sin(seconds), 0.0])
            gt_rot = _yaw_quat(60.0 * seconds)
            held_seconds = math.floor(seconds * 10.0) / 10.0
            for label in ("Full", "ZOH"):
                display_seconds = seconds - 0.10 if label == "Full" else held_seconds - 0.05
                display_pos = np.array([0.2 * display_seconds, 0.01 * math.sin(display_seconds), 0.0])
                display_rot = _yaw_quat(60.0 * display_seconds)
                rows.append(
                    {
                        "session_id": "synthetic",
                        "tick_index": tick,
                        "render_mono_ms": render_ms + trial_id * 20_000.0,
                        "render_unity_frame": 1000 + tick,
                        "rq2_condition": condition,
                        "rq2_trial_id": trial_id,
                        "rq2_target_linear_speed_m_s": 0.2 if condition == "translation" else np.nan,
                        "rq2_target_angular_speed_deg_s": 60.0 if condition == "rotation" else np.nan,
                        "label": label,
                        "is_primary": label == "Full",
                        "source_frame_id": sample // 2,
                        "gt_pos": gt_pos,
                        "gt_rot": gt_rot,
                        "gt_pose_valid": True,
                        "gt_pose_fresh": True,
                        "gt_pose_keep_alive": False,
                        "gt_pose_fresh_age_ms": 0.0,
                        "valid": True,
                        "has_output_pose": True,
                        "has_display_pose": True,
                        "output_pos": display_pos,
                        "output_rot": display_rot,
                        "display_pos": display_pos,
                        "display_rot": display_rot,
                        "anchor_state": "Streaming",
                        "policy_action": "Apply",
                        "policy_reason": "accepted",
                        "observation_age_ms": 220.0,
                        "smoothing_delay_ms": 290.0 if label == "Full" else 220.0,
                    }
                )
            tick += 1
    return pd.DataFrame.from_records(rows)


def _manifest(session_id: str = "synthetic") -> dict[str, object]:
    """构造通过会话完整性检查的 manifest。"""

    return {
        "session_id": session_id,
        "variant_labels": ["Full", "ZOH"],
        "log_writer_stats": {
            "capture_dropped_rows": 0,
            "output_dropped_rows": 0,
        },
    }


class TestRQ2Analysis(unittest.TestCase):
    """双任务契约应只生成正文需要的描述性结果。"""

    def test_contract_has_only_translation_and_rotation(self) -> None:
        self.assertEqual(RQ2_CONDITIONS, ("translation", "rotation"))

    def test_speed_cap_is_applied_after_active_motion_detection(self) -> None:
        output = _paired_output(duration_s=2.0)
        annotated = annotate_active_motion(
            output,
            RQ2Config(max_translation_speed_m_s=0.1, max_rotation_speed_deg_s=30.0),
        )

        self.assertTrue(bool(annotated["active_motion"].any()))
        self.assertFalse(bool(annotated["analysis_motion"].any()))

    def test_active_motion_isolated_by_session_id(self) -> None:
        moving = _paired_output(duration_s=2.0)
        stationary = moving.copy()
        stationary["session_id"] = "stationary"
        stationary["gt_pos"] = stationary["gt_pos"].map(lambda _: np.zeros(3))
        stationary["gt_rot"] = stationary["gt_rot"].map(lambda _: _yaw_quat(0.0))

        annotated = annotate_active_motion(
            pd.concat([moving, stationary], ignore_index=True)
        )

        self.assertTrue(bool(annotated.loc[annotated["session_id"].eq("synthetic"), "active_motion"].any()))
        self.assertFalse(bool(annotated.loc[annotated["session_id"].eq("stationary"), "active_motion"].any()))

    def test_audit_accepts_complete_two_task_session(self) -> None:
        annotated = annotate_active_motion(_paired_output())
        session = compute_session_audit(annotated, _manifest()).iloc[0]
        trials = compute_trial_audit(annotated)

        self.assertTrue(bool(session["accepted"]), session["issues"])
        self.assertEqual(len(trials), 2)
        self.assertTrue(bool(trials["accepted"].all()), trials["issues"].tolist())
        self.assertTrue(bool(trials["pair_complete"].all()))

    def test_session_audit_rejects_missing_freshness_contract(self) -> None:
        annotated = annotate_active_motion(_paired_output()).drop(
            columns=["gt_pose_fresh", "gt_pose_keep_alive", "gt_pose_fresh_age_ms"]
        )

        audit = compute_session_audit(annotated, _manifest()).iloc[0]

        self.assertFalse(bool(audit["accepted"]))
        self.assertIn("missing_freshness_fields", str(audit["issues"]))

    def test_condition_summary_reports_continuity_tradeoff(self) -> None:
        annotated = annotate_active_motion(_paired_output())
        summary = compute_condition_summary(annotated)
        translation = summary[summary["condition"].eq("translation")].set_index("label")

        self.assertGreater(
            float(translation.loc["Full", "display_update_rate_hz"]),
            float(translation.loc["ZOH", "display_update_rate_hz"]),
        )
        self.assertLess(
            float(translation.loc["Full", "display_hold_fraction"]),
            float(translation.loc["ZOH", "display_hold_fraction"]),
        )
        self.assertAlmostEqual(float(translation.loc["Full", "tracking_availability"]), 1.0)
        self.assertEqual(translation.loc["Full", "main_error_unit"], "m")

    def test_source_count_requires_positive_frame_id(self) -> None:
        annotated = annotate_active_motion(_paired_output())
        translation = annotated["rq2_condition"].eq("translation")
        annotated.loc[translation, "source_frame_id"] = 0
        positive_rows = annotated.index[translation][-20:]
        annotated.loc[positive_rows, "source_frame_id"] = 7

        summary = compute_condition_summary(annotated)
        row = summary[
            summary["condition"].eq("translation") & summary["label"].eq("Full")
        ].iloc[0]

        self.assertEqual(int(row["source_frame_count"]), 1)

    def test_analysis_duration_requires_both_interval_endpoints(self) -> None:
        annotated = annotate_active_motion(_paired_output(duration_s=2.0))
        translation = annotated["rq2_condition"].eq("translation")
        annotated.loc[translation, "analysis_motion"] = False
        ticks = sorted(annotated.loc[translation, "tick_index"].unique())
        isolated = annotated["tick_index"].isin((ticks[1], ticks[3]))
        annotated.loc[translation & isolated, "analysis_motion"] = True

        audit = compute_trial_audit(
            annotated,
            RQ2Config(min_analysis_duration_s=0.0),
        )
        row = audit[audit["condition"].eq("translation")].iloc[0]

        self.assertEqual(float(row["analysis_duration_s"]), 0.0)

    def test_condition_summary_does_not_connect_trial_boundaries(self) -> None:
        annotated = annotate_active_motion(_paired_output(duration_s=2.0))
        translation = annotated[annotated["rq2_condition"].eq("translation")]
        first_tick = int(translation["tick_index"].min())
        first = translation[translation["tick_index"].eq(first_tick)].copy()
        second = first.copy()
        second["rq2_trial_id"] = 99
        second["tick_index"] = first_tick + 1000
        second["render_mono_ms"] = first["render_mono_ms"] + 1000.0
        second["display_pos"] = second["display_pos"].map(
            lambda value: np.asarray(value, dtype=float) + np.array([1.0, 0.0, 0.0])
        )
        isolated = pd.concat([first, second], ignore_index=True)
        isolated["analysis_motion"] = True

        summary = compute_condition_summary(isolated)

        self.assertTrue((summary["display_pair_count"] == 0).all())
        self.assertTrue(summary["display_update_rate_hz"].isna().all())

    def test_pipeline_writes_only_minimal_tables_and_timelines(self) -> None:
        output = _paired_output()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / "session"
            report_dir = root / "report"
            figs_dir = root / "figs"
            session_dir.mkdir()
            logs = SimpleNamespace(output=output.drop(columns="session_id"), manifest=_manifest())
            with patch(
                "egoanchor.eval.research.rq2.pipeline.load_session",
                return_value=logs,
            ):
                tables = run_rq2_analysis(
                    session_dir,
                    report_dir=report_dir,
                    figs_dir=figs_dir,
                    config=RQ2Config(zoom_frame_count=20),
                )

            self.assertEqual(
                set(tables),
                {
                    "rq2_session_audit",
                    "rq2_trial_audit",
                    "rq2_trial_summary",
                    "rq2_condition_summary",
                    "rq2_response_summary",
                    "rq2_timeline_windows",
                },
            )
            self.assertEqual(len(list(report_dir.glob("*.csv"))), 6)
            self.assertEqual(len(list(report_dir.glob("*.pdf"))), 2)
            self.assertEqual(len(list(figs_dir.glob("*.pdf"))), 2)

    def test_pipeline_rejects_duplicate_session_id(self) -> None:
        output = _paired_output().drop(columns="session_id")
        logs = SimpleNamespace(output=output, manifest=_manifest())
        with tempfile.TemporaryDirectory() as tmp, patch(
            "egoanchor.eval.research.rq2.pipeline.load_session",
            return_value=logs,
        ):
            with self.assertRaisesRegex(ValueError, "重复 session_id"):
                run_rq2_analysis(
                    [Path(tmp) / "first", Path(tmp) / "second"],
                    report_dir=Path(tmp) / "report",
                )

    def test_module_cli_has_no_reimport_warning(self) -> None:
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

if __name__ == "__main__":
    unittest.main()
