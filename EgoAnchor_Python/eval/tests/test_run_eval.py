"""eval/run_eval 指标与报告端到端测试。"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from eval.io import load_session
from eval.metrics.anchor_error import compute_anchor_error, summarize_pose_offset
from eval.metrics import compute_all_metrics
from eval.run_eval import run_eval


class RunEvalTest(unittest.TestCase):
    """验证 Transform GT session 能一条命令产出指标和 report。"""

    def test_compute_all_metrics_direct_transform_gt(self) -> None:
        """metrics 应直接比较 gt_pos/gt_rot 与 stable_pos/stable_rot。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_metric_session(Path(tmp))
            logs = load_session(session_dir)

            metrics = compute_all_metrics(logs)

            anchor_summary = metrics.tables["anchor_error_summary"]
            kalman = anchor_summary[
                (anchor_summary["condition"] == "static") & (anchor_summary["label"] == "kalman")
            ].iloc[0]
            raw = anchor_summary[
                (anchor_summary["condition"] == "static") & (anchor_summary["label"] == "raw")
            ].iloc[0]
            self.assertAlmostEqual(float(kalman["translation_median_m"]), 0.01, places=9)
            self.assertAlmostEqual(float(raw["translation_median_m"]), 0.04, places=9)

            detail = metrics.tables["anchor_error_detail"]
            first_kalman = detail[
                (detail["condition"] == "static") & (detail["label"] == "kalman")
            ].iloc[0]
            self.assertAlmostEqual(float(first_kalman["position_offset_x_m"]), 0.01, places=9)
            self.assertAlmostEqual(float(first_kalman["position_offset_y_m"]), 0.0, places=9)
            self.assertAlmostEqual(float(first_kalman["position_offset_z_m"]), 0.0, places=9)
            self.assertAlmostEqual(float(first_kalman["rotation_offset_euler_x_deg"]), 0.0, places=9)
            self.assertAlmostEqual(float(first_kalman["rotation_offset_euler_y_deg"]), 0.0, places=9)
            self.assertAlmostEqual(float(first_kalman["rotation_offset_euler_z_deg"]), 30.0, places=9)

            offset = metrics.tables["pose_offset_summary"]
            static_kalman_offset = offset[
                (offset["condition"] == "static") & (offset["label"] == "kalman")
            ].iloc[0]
            self.assertAlmostEqual(float(static_kalman_offset["position_offset_median_x_m"]), 0.01, places=9)
            self.assertAlmostEqual(float(static_kalman_offset["rotation_offset_median_euler_z_deg"]), 30.0, places=9)
            self.assertAlmostEqual(float(static_kalman_offset["rotation_offset_median_deg"]), 30.0, places=9)

            self.assertNotIn("aligned_raw_offset_summary", metrics.tables)

            latency = metrics.tables["latency_summary"]
            self.assertIn("capture_to_apply_p50_ms", latency.columns)
            self.assertGreater(float(latency.iloc[0]["capture_to_apply_p50_ms"]), 0.0)
            self.assertIn("reliability_diagnostics_summary", metrics.tables)
            self.assertIn("reliability_score_histogram", metrics.tables)
            self.assertIn("track_consistency_histogram", metrics.tables)
            self.assertIn("policy_distribution", metrics.tables)

            sanity = metrics.sanity
            self.assertEqual(sanity["gt_source"], "transform")
            self.assertEqual(sanity["gt_transform"], "OVRControllerPrefab")
            self.assertIn("aligned_raw_error", sanity)

    def test_run_eval_writes_tables_figures_and_sanity(self) -> None:
        """run_eval 应创建 report 目录并导出 CSV/Markdown/图和 sanity JSON。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_metric_session(Path(tmp))

            report_dir = run_eval(session_dir)

            self.assertTrue((report_dir / "gt_anchor_sanity.json").is_file())
            self.assertTrue((report_dir / "anchor_error_summary.csv").is_file())
            self.assertTrue((report_dir / "pose_offset_summary.csv").is_file())
            self.assertFalse((report_dir / "aligned_raw_offset_summary.csv").is_file())
            self.assertTrue((report_dir / "latency_summary.csv").is_file())
            self.assertTrue((report_dir / "reliability_diagnostics_summary.csv").is_file())
            self.assertTrue((report_dir / "reliability_score_histogram.csv").is_file())
            self.assertTrue((report_dir / "track_consistency_histogram.csv").is_file())
            self.assertTrue((report_dir / "policy_distribution.csv").is_file())
            self.assertTrue((report_dir / "summary.md").is_file())
            self.assertTrue((report_dir / "error_timeline.png").is_file())
            self.assertTrue((report_dir / "latency_breakdown.png").is_file())

    def test_run_eval_script_entrypoint_resolves_eval_package(self) -> None:
        """直接执行 python eval/run_eval.py 时应能解析顶层 eval 包。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_metric_session(Path(tmp))
            script = Path(__file__).resolve().parents[1] / "run_eval.py"

            completed = subprocess.run(
                [sys.executable, str(script), "--session-dir", str(session_dir), "--only", "sanity"],
                cwd=Path(__file__).resolve().parents[2],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((session_dir / "report" / "gt_anchor_sanity.json").is_file())

    def test_pose_offset_summary_unwraps_euler_near_180_deg(self) -> None:
        """Euler 汇总应在 0-360 度区间避免 179/181 度边界误算。"""

        detail = pd.DataFrame(
            [
                _offset_detail_row(179.0),
                _offset_detail_row(181.0),
            ]
        )

        summary = summarize_pose_offset(detail)

        row = summary.iloc[0]
        self.assertAlmostEqual(float(row["rotation_offset_mean_euler_z_deg"]), 180.0, places=9)
        self.assertAlmostEqual(float(row["rotation_offset_median_euler_z_deg"]), 180.0, places=9)
        self.assertLess(float(row["rotation_offset_std_euler_z_deg"]), 2.0)

    def test_anchor_error_detail_records_euler_in_0_360_deg(self) -> None:
        """逐帧 rotation offset 应用 0-360 欧拉角记录，避免负角度。"""

        output = pd.DataFrame(
            [
                {
                    "valid": True,
                    "has_stable": True,
                    "gt_pos": [0.0, 0.0, 1.0],
                    "gt_rot": [0.0, 0.0, 0.0, 1.0],
                    "stable_pos": [0.0, 0.0, 1.0],
                    "stable_rot": _axis_angle_z(-30.0),
                    "tick_index": 1,
                    "render_mono_ms": 100.0,
                    "label": "kalman",
                    "condition": "static",
                    "source_frame_id": 1,
                }
            ]
        )

        detail, _ = compute_anchor_error(output)

        row = detail.iloc[0]
        self.assertAlmostEqual(float(row["rotation_offset_euler_z_deg"]), 330.0, places=9)
        self.assertAlmostEqual(float(row["rotation_error_deg"]), 30.0, places=9)


def _write_metric_session(root: Path) -> Path:
    """写入一个最小但可计算指标的 Transform GT session。"""

    session_dir = root / "metric-session"
    session_dir.mkdir(parents=True)
    manifest = {
        "session_id": "metric-session",
        "object_id": "controller_right",
        "unity_run_mode": "editor_link",
        "gt_source": "transform",
        "gt_transform": "OVRControllerPrefab",
        "python_log_filename": "runtime.jsonl",
        "condition_spans": [
            {"label": "static", "start_mono_ms": 90.0, "end_mono_ms": 140.0},
            {"label": "object_motion", "start_mono_ms": 140.0, "end_mono_ms": 210.0},
        ],
        "event_markers": [{"type": "recovery", "mono_ms": 160.0}],
        "variant_labels": ["kalman", "raw"],
    }
    (session_dir / "session_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    capture_rows = [
        _capture_row(1, 100.0, [0.0, 0.0, 1.0]),
        _capture_row(2, 150.0, [0.1, 0.0, 1.0]),
        _capture_row(3, 190.0, [0.2, 0.0, 1.0]),
    ]
    _write_jsonl(session_dir / "metric-session_unity_capture.jsonl", capture_rows)

    output_rows = [
        _output_row(110.0, 1, [0.0, 0.0, 1.0], 0.01, 0.04),
        _output_row(160.0, 2, [0.1, 0.0, 1.0], 0.02, 0.05),
        _output_row(200.0, 3, [0.2, 0.0, 1.0], 0.03, 0.06),
    ]
    _write_jsonl(session_dir / "metric-session_unity_output.jsonl", output_rows)

    pose_rows = [
        _pose_row(1, 96.0, 105.0, 10.0),
        _pose_row(2, 145.0, 155.0, 11.0),
        _pose_row(3, 185.0, 195.0, 12.0),
    ]
    _write_jsonl(session_dir / "runtime.jsonl", pose_rows)
    return session_dir


def _capture_row(frame_id: int, mono_ms: float, gt_pos: list[float]) -> dict[str, object]:
    """构造 capture 行。"""

    return {
        "event": "unity_capture",
        "frame_id": frame_id,
        "capture_mono_ms": mono_ms,
        "capture_unix_ms": 1000.0 + mono_ms,
        "capture_unity_frame": 100 + frame_id,
        "head_pos": [0.0, 0.0, 0.0],
        "head_rot": [0.0, 0.0, 0.0, 1.0],
        "cam_valid": True,
        "camera_reference": "Left",
        "cam_pos": [0.0, 0.0, 0.0],
        "cam_rot": [0.0, 0.0, 0.0, 1.0],
        "gt_pos": gt_pos,
        "gt_rot": [0.0, 0.0, 0.0, 1.0],
        "gt_pose_valid": True,
        "gt_pose_source": "transform",
    }


def _output_row(
    render_mono_ms: float,
    source_frame_id: int,
    gt_pos: list[float],
    kalman_offset: float,
    raw_offset: float,
) -> dict[str, object]:
    """构造含 kalman/raw 两个变体的 output 行。"""

    return {
        "event": "unity_output",
        "render_mono_ms": render_mono_ms,
        "render_unix_ms": 1000.0 + render_mono_ms,
        "render_unity_frame": 200 + source_frame_id,
        "source_frame_id": source_frame_id,
        "head_pos": [0.0, 0.0, 0.0],
        "head_rot": [0.0, 0.0, 0.0, 1.0],
        "gt_pos": gt_pos,
        "gt_rot": [0.0, 0.0, 0.0, 1.0],
        "gt_pose_valid": True,
        "gt_pose_source": "transform",
        "variants": [
            _variant("kalman", True, source_frame_id, gt_pos, kalman_offset),
            _variant("raw", False, source_frame_id, gt_pos, raw_offset),
        ],
    }


def _variant(
    label: str,
    is_primary: bool,
    source_frame_id: int,
    gt_pos: list[float],
    offset: float,
) -> dict[str, object]:
    """构造 output variant。"""

    stable = np.asarray(gt_pos, dtype=float) + np.array([offset, 0.0, 0.0])
    stable_rot = _axis_angle_z(30.0) if is_primary else [0.0, 0.0, 0.0, 1.0]
    row: dict[str, object] = {
        "label": label,
        "is_primary": is_primary,
        "source_frame_id": source_frame_id,
        "has_stable": True,
        "stable_pos": stable.tolist(),
        "stable_rot": stable_rot,
        "anchor_pose_source": "transform",
        "has_source_capture_timing": True,
        "source_capture_mono_ms": 50.0 + source_frame_id * 50.0,
        "source_capture_unity_frame": 100 + source_frame_id,
        "anchor_state": "Tracking",
        "policy_action": "Accept",
        "policy_reason": "score_accept",
        "latest_phase": "TRACK",
        "latest_failure": "",
    }
    if is_primary:
        row.update(
            {
                "has_aligned_raw": True,
                "aligned_raw_pos": (np.asarray(gt_pos, dtype=float) + np.array([offset * 2.0, 0.0, 0.0])).tolist(),
                "aligned_raw_rot": [0.0, 0.0, 0.0, 1.0],
                "reliability_score": 0.9,
            }
        )
    return row


def _pose_row(frame_id: int, receive_ms: float, publish_ms: float, total_ms: float) -> dict[str, object]:
    """构造 Python pose_result 行。"""

    return {
        "event": "pose_result",
        "frame_id": frame_id,
        "has_pose": True,
        "pose_matrix_cv_camera": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        "pose_score": 0.9,
        "reliability_flags": ["ok"],
        "total_ms": total_ms,
        "yolo_ms": 2.0,
        "depth_ms": 3.0,
        "cutie_ms": 1.0,
        "pose_ms": total_ms - 6.0,
        "server_receive_mono_ms": receive_ms,
        "server_publish_mono_ms": publish_ms,
    }


def _offset_detail_row(euler_z_deg: float) -> dict[str, object]:
    """构造固定偏移汇总测试行。"""

    return {
        "condition": "static",
        "label": "kalman",
        "position_offset_x_m": 0.01,
        "position_offset_y_m": -0.02,
        "position_offset_z_m": 0.03,
        "rotation_offset_euler_x_deg": 0.0,
        "rotation_offset_euler_y_deg": 0.0,
        "rotation_offset_euler_z_deg": euler_z_deg,
        "rotation_error_deg": 180.0,
    }


def _axis_angle_z(degrees: float) -> list[float]:
    """构造绕 z 轴旋转的 xyzw 四元数。"""

    half = math.radians(degrees) * 0.5
    return [0.0, 0.0, math.sin(half), math.cos(half)]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """把 rows 写入 JSONL。"""

    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
