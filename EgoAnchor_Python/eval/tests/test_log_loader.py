"""eval/io 日志加载与 frame_id join 测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from eval.io.log_loader import join_by_frame, label_conditions, load_session
from eval.io.schemas import SchemaError, VariantRow


class LogLoaderTest(unittest.TestCase):
    """验证 Unity/Python 评估日志可以被稳定加载成分析表。"""

    def test_load_session_flattens_logs_and_marks_validity(self) -> None:
        """load_session 应读取四份日志，展开 variants，并标记 GT 有效性。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = self._write_session(Path(tmp))

            logs = load_session(session_dir)

            self.assertEqual(list(logs.capture.index), [1, 2])
            self.assertNotIn("gt_tracked", logs.capture.columns)
            self.assertNotIn("gt_hold_age_ms", logs.capture.columns)
            self.assertTrue(bool(logs.capture.loc[1, "valid"]))
            self.assertFalse(bool(logs.capture.loc[2, "valid"]))
            self.assertEqual(int(logs.capture.loc[1, "capture_unity_frame"]), 10)
            self.assertEqual(logs.capture.loc[1, "camera_reference"], "Left")
            np.testing.assert_allclose(logs.capture.loc[1, "gt_pos"], np.array([0.1, 0.2, 0.3]))

            self.assertEqual(len(logs.output), 4)
            self.assertNotIn("gt_tracked", logs.output.columns)
            self.assertNotIn("gt_hold_age_ms", logs.output.columns)
            self.assertEqual(set(logs.output["label"]), {"kalman", "raw"})
            primary = logs.output[(logs.output["tick_index"] == 0) & (logs.output["label"] == "kalman")].iloc[0]
            self.assertTrue(bool(primary["is_primary"]))
            self.assertAlmostEqual(float(primary["reliability_score"]), 0.8)
            self.assertEqual(primary["strategy_label"], "kalman_blend")
            self.assertEqual(primary["quality_gate"], "disabled")
            self.assertEqual(primary["motion_model"], "kalman")
            self.assertEqual(primary["smoothing_strategy"], "blend")
            self.assertEqual(primary["config_hash"], "abc123")
            self.assertEqual(primary["anchor_pose_source"], "transform")
            self.assertAlmostEqual(float(primary["source_capture_mono_ms"]), 100.0)
            self.assertEqual(int(primary["source_capture_unity_frame"]), 10)
            np.testing.assert_allclose(primary["aligned_raw_pos"], np.array([1.1, 2.1, 3.1]))
            self.assertTrue(bool(primary["has_arrival_time_raw"]))
            np.testing.assert_allclose(primary["arrival_time_raw_pos"], np.array([1.2, 2.2, 3.2]))
            self.assertAlmostEqual(float(primary["arrival_time_raw_mono_ms"]), 125.0)
            self.assertEqual(primary["arrival_time_camera_reference"], "Left")

            self.assertEqual(list(logs.pose.index), [1, 2])
            self.assertEqual(logs.pose.loc[1, "pose_matrix_cv_camera"].shape, (4, 4))
            self.assertAlmostEqual(float(logs.pose.loc[1, "yolo_ms"]), 2.0)
            self.assertEqual(logs.manifest["session_id"], "session-a")

    def test_join_by_frame_keeps_capture_rows_and_combines_validity(self) -> None:
        """join_by_frame 应按 frame_id 左连接 capture 与 pose_result。"""

        with tempfile.TemporaryDirectory() as tmp:
            logs = load_session(self._write_session(Path(tmp)))

            joined = join_by_frame(logs)

            self.assertEqual(list(joined.index), [1, 2])
            self.assertTrue(bool(joined.loc[1, "pose_has_pose"]))
            self.assertTrue(bool(joined.loc[1, "valid"]))
            self.assertFalse(bool(joined.loc[2, "pose_has_pose"]))
            self.assertFalse(bool(joined.loc[2, "valid"]))
            self.assertAlmostEqual(float(joined.loc[1, "pose_yolo_ms"]), 2.0)

    def test_label_conditions_assigns_manifest_spans(self) -> None:
        """label_conditions 应根据 manifest condition_spans 给行打标签。"""

        with tempfile.TemporaryDirectory() as tmp:
            logs = load_session(self._write_session(Path(tmp)))

            capture = label_conditions(logs.capture, logs.manifest, "capture_mono_ms")
            output = label_conditions(logs.output, logs.manifest, "render_mono_ms")

            self.assertEqual(capture.loc[1, "condition"], "static")
            self.assertEqual(capture.loc[2, "condition"], "object_motion")
            self.assertEqual(output.iloc[0]["condition"], "static")
            self.assertEqual(output.iloc[-1]["condition"], "object_motion")

    def test_missing_required_field_raises_clear_schema_error(self) -> None:
        """缺少必需字段时应抛 SchemaError，并指出具体字段。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = self._write_session(Path(tmp))
            capture_path = session_dir / "session-a_unity_capture.jsonl"
            bad_row = json.loads(capture_path.read_text(encoding="utf-8").splitlines()[0])
            bad_row.pop("gt_pos")
            capture_path.write_text(json.dumps(bad_row, ensure_ascii=False) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(SchemaError, "gt_pos"):
                load_session(session_dir)

    def test_variant_reads_module_keys(self) -> None:
        """motion_model/smoothing_strategy/quality_gate 应按当前键名解析。"""

        row = {
            "label": "kalman",
            "is_primary": False,
            "source_frame_id": 7,
            "has_output_pose": True,
            "output_pos": [0.0, 0.0, 0.0],
            "output_rot": [0.0, 0.0, 0.0, 1.0],
            "anchor_state": "Tracking",
            "policy_action": "Accept",
            "policy_reason": "accept",
            "latest_phase": "TRACK",
            "latest_failure": "",
            "anchor_pose_source": "transform",
            "has_source_capture_timing": False,
            "source_capture_mono_ms": None,
            "source_capture_unity_frame": -1,
            "quality_gate": "disabled",
            "motion_model": "kalman",
            "smoothing_strategy": "blend",
        }
        variant = VariantRow.from_dict(row)
        self.assertEqual(variant.quality_gate, "disabled")
        self.assertEqual(variant.motion_model, "kalman")
        self.assertEqual(variant.smoothing_strategy, "blend")

    def _write_session(self, root: Path) -> Path:
        """写入一个最小可 join 的评估 session。"""

        session_dir = root / "session-a"
        session_dir.mkdir(parents=True)
        manifest = {
            "session_id": "session-a",
            "object_id": "controller_right",
            "python_log_filename": "runtime.jsonl",
            "condition_spans": [
                {"label": "static", "start_mono_ms": 90.0, "end_mono_ms": 120.0},
                {"label": "object_motion", "start_mono_ms": 120.0, "end_mono_ms": 180.0},
            ],
            "event_markers": [],
            "variant_labels": ["kalman", "raw"],
            "variant_configs": [
                {
                    "label": "kalman",
                    "strategy_label": "kalman_blend",
                    "quality_gate": "disabled",
                    "motion_model": "kalman",
                    "smoothing_strategy": "blend",
                    "config_hash": "abc123",
                    "parameters": {"motion_model.positionMeasurementNoise": "0.0004"},
                }
            ],
        }
        (session_dir / "session_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        capture_rows = [
            {
                "event": "unity_capture",
                "frame_id": 1,
                "capture_mono_ms": 100.0,
                "capture_unix_ms": 1000.0,
                "capture_unity_frame": 10,
                "head_pos": [0.0, 0.0, 0.0],
                "head_rot": [0.0, 0.0, 0.0, 1.0],
                "cam_valid": True,
                "camera_reference": "Left",
                "cam_pos": [0.0, 0.0, 1.0],
                "cam_rot": [0.0, 0.0, 0.0, 1.0],
                "gt_pos": [0.1, 0.2, 0.3],
                "gt_rot": [0.0, 0.0, 0.0, 1.0],
                "gt_pose_valid": True,
                "gt_pose_source": "transform",
            },
            {
                "event": "unity_capture",
                "frame_id": 2,
                "capture_mono_ms": 130.0,
                "capture_unix_ms": 1030.0,
                "capture_unity_frame": 11,
                "head_pos": [0.0, 0.1, 0.0],
                "head_rot": [0.0, 0.0, 0.0, 1.0],
                "cam_valid": True,
                "camera_reference": "Left",
                "cam_pos": [0.0, 0.0, 1.0],
                "cam_rot": [0.0, 0.0, 0.0, 1.0],
                "gt_pos": None,
                "gt_rot": None,
                "gt_pose_valid": False,
                "gt_pose_source": "none",
            },
        ]
        self._write_jsonl(session_dir / "session-a_unity_capture.jsonl", capture_rows)

        output_rows = [
            self._output_row(100.0, 1),
            self._output_row(130.0, 2),
        ]
        self._write_jsonl(session_dir / "session-a_unity_output.jsonl", output_rows)

        pose_rows = [
            {
                "event": "pose_result",
                "frame_id": 1,
                "has_pose": True,
                "pose_matrix_cv_camera": [1.0, 0.0, 0.0, 0.4, 0.0, 1.0, 0.0, 0.5, 0.0, 0.0, 1.0, 0.6, 0.0, 0.0, 0.0, 1.0],
                "pose_score": 0.8,
                "reliability_flags": ["ok"],
                "total_ms": 10.0,
                "yolo_ms": 2.0,
                "depth_ms": 3.0,
                "cutie_ms": 1.0,
                "pose_ms": 4.0,
                "server_receive_mono_ms": 95.0,
                "server_publish_mono_ms": 105.0,
            },
            {
                "event": "pose_result",
                "frame_id": 2,
                "has_pose": False,
                "pose_score": 0.0,
                "reliability_flags": ["lost"],
                "total_ms": 8.0,
                "yolo_ms": 2.0,
                "depth_ms": 2.0,
                "cutie_ms": 1.0,
                "pose_ms": 3.0,
                "server_receive_mono_ms": 125.0,
                "server_publish_mono_ms": 135.0,
            },
        ]
        self._write_jsonl(session_dir / "runtime.jsonl", pose_rows)
        return session_dir

    def _output_row(self, render_mono_ms: float, source_frame_id: int) -> dict[str, object]:
        """构造一行含两个 variants 的 unity_output。"""

        return {
            "event": "unity_output",
            "render_mono_ms": render_mono_ms,
            "render_unix_ms": 1000.0 + render_mono_ms,
            "render_unity_frame": 20 + source_frame_id,
            "source_frame_id": source_frame_id,
            "head_pos": [0.0, 0.0, 0.0],
            "head_rot": [0.0, 0.0, 0.0, 1.0],
            "gt_pos": [0.1, 0.2, 0.3],
            "gt_rot": [0.0, 0.0, 0.0, 1.0],
            "gt_pose_valid": True,
            "gt_pose_source": "transform",
            "variants": [
                {
                    "label": "kalman",
                    "is_primary": True,
                    "source_frame_id": source_frame_id,
                    "has_output_pose": True,
                    "output_pos": [1.0, 2.0, 3.0],
                    "output_rot": [0.0, 0.0, 0.0, 1.0],
                    "anchor_pose_source": "transform",
                    "has_source_capture_timing": True,
                    "source_capture_mono_ms": 100.0,
                    "source_capture_unity_frame": 10,
                    "anchor_state": "Tracking",
                    "policy_action": "Accept",
                    "policy_reason": "score_accept",
                    "latest_phase": "TRACK",
                    "latest_failure": "",
                    "strategy_label": "kalman_blend",
                    "quality_gate": "disabled",
                    "motion_model": "kalman",
                    "smoothing_strategy": "blend",
                    "config_hash": "abc123",
                    "latest_residual_meters": 0.0,
                    "latest_residual_degrees": 0.0,
                    "latest_accepted_score": 0.8,
                    "latest_static_locked": False,
                    "has_aligned_raw": True,
                    "aligned_raw_pos": [1.1, 2.1, 3.1],
                    "aligned_raw_rot": [0.0, 0.0, 0.0, 1.0],
                    "has_arrival_time_raw": True,
                    "arrival_time_raw_pos": [1.2, 2.2, 3.2],
                    "arrival_time_raw_rot": [0.0, 0.0, 0.0, 1.0],
                    "arrival_time_raw_mono_ms": 125.0,
                    "arrival_time_raw_unity_frame": 25,
                    "arrival_time_camera_reference": "Left",
                    "reliability_score": 0.8,
                },
                {
                    "label": "raw",
                    "is_primary": False,
                    "source_frame_id": source_frame_id,
                    "has_output_pose": True,
                    "output_pos": [1.1, 2.1, 3.1],
                    "output_rot": [0.0, 0.0, 0.0, 1.0],
                    "anchor_pose_source": "transform",
                    "has_source_capture_timing": True,
                    "source_capture_mono_ms": 100.0,
                    "source_capture_unity_frame": 10,
                    "anchor_state": "Tracking",
                    "policy_action": "baseline_accept",
                    "policy_reason": "policy_disabled",
                    "latest_phase": "TRACK",
                    "latest_failure": "",
                    "quality_gate": "disabled",
                },
            ],
        }

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
        """把 dict 列表写成 JSONL。"""

        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
