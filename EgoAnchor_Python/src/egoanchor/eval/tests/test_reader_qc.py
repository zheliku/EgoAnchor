"""schema-v2 流式 reader 与 Stage 1 QC 测试。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from egoanchor.eval import flatten_json, read_task, run_task_qc


VARIANT_SPECS = (
    ("Arrival-Hold", "cv", "hold", "disabled", "ArrivalTime", False, False, False, False, False, False),
    ("Capture-Hold", "cv", "hold", "disabled", "CaptureTime", True, False, False, False, False, False),
    ("One-Euro Anchor", "oneeuro", "linear_slerp", "enabled", "CaptureTime", True, True, True, False, True, True),
    ("EgoAnchor", "kalman", "linear_slerp", "enabled", "CaptureTime", True, True, True, True, True, True),
    ("EgoAnchor Causal Prediction", "kalman", "causal_prediction", "enabled", "CaptureTime", True, True, True, False, True, True),
    ("EgoAnchor w/o capture-time alignment", "kalman", "linear_slerp", "enabled", "ArrivalTime", False, True, True, True, True, True),
    ("EgoAnchor w/o VCD", "kalman", "linear_slerp", "disabled", "CaptureTime", True, False, True, True, False, True),
    ("EgoAnchor w/o temporal synthesis", "kalman", "predict_to_now", "enabled", "CaptureTime", True, True, False, True, True, True),
    ("EgoAnchor w/o StaticLock", "kalman", "linear_slerp", "enabled", "CaptureTime", True, True, True, False, True, True),
)
"""与当前正式采集冻结矩阵一致的九个测试 variant。"""

class ReaderQcTests(unittest.TestCase):
    """验证 reader 来源追踪与 Stage 1 硬 QC。"""

    def test_reader_records_source_line_hash_and_normalizes_nested_values(self) -> None:
        """JSONL 行保留来源行号、行哈希并可展开嵌套字段。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            task = read_task(root)
            row = next(task.iter_rows("python_candidates"))
            raw = (root / "python_candidates.jsonl").read_bytes().splitlines()[0]

            self.assertEqual(row.source_line, 1)
            self.assertEqual(row.source_row_sha256, hashlib.sha256(raw).hexdigest())
            normalized = list(flatten_json(row.data["render_diagnostics"], prefix="render_diagnostics"))
            self.assertEqual(normalized[0].json_path, "render_diagnostics.score")
            self.assertEqual(normalized[0].value, 0.5)

    def test_valid_task_passes_without_writing_outputs(self) -> None:
        """合法 task 通过 QC，且 QC 前后目录文件集合完全不变。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            before = _file_snapshot(root)

            report = run_task_qc(root)

            self.assertTrue(report.passed, report.to_dict())
            self.assertEqual(_file_snapshot(root), before)
            self.assertEqual(report.metrics["variant_count"], 9)

    def test_causal_pair_replaces_hermite_without_changing_direct_ablation(self) -> None:
        """九路矩阵保留直接预测消融，并用关闭 StaticLock 的因果策略替换 Hermite。"""

        specs = {str(spec[0]): spec for spec in VARIANT_SPECS}

        self.assertNotIn("EgoAnchor Hermite", specs)
        self.assertEqual(specs["EgoAnchor w/o temporal synthesis"][2], "predict_to_now")
        self.assertFalse(bool(specs["EgoAnchor w/o temporal synthesis"][7]))
        self.assertEqual(specs["EgoAnchor Causal Prediction"][2], "causal_prediction")
        self.assertTrue(bool(specs["EgoAnchor Causal Prediction"][7]))
        self.assertFalse(bool(specs["EgoAnchor Causal Prediction"][8]))

    def test_current_matrix_id_rejects_missing_causal_control_variant(self) -> None:
        """新 session 即使其余八路完整，也不得缺少因果预测配对策略。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp), include_causal_control=False)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["variant_matrix_id"] = "exp12_9_causal_v3"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = run_task_qc(root)

            self.assertFalse(report.passed)
            self.assertIn("variant_count", {issue.code for issue in report.errors})

    def test_missing_variant_matrix_id_is_not_treated_as_archive(self) -> None:
        """正式 QC 不再为无矩阵标识的旧八路数据保留兼容分支。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("variant_matrix_id")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = run_task_qc(root)

            self.assertFalse(report.passed)
            self.assertIn("variant_matrix_id", {issue.code for issue in report.errors})

    def test_unknown_admission_candidate_is_hard_error(self) -> None:
        """Unity admission 指向未知 Python candidate 时必须失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            rows = _read_jsonl(root / "unity_admission.jsonl")
            rows[0]["candidate_id"] = "s01:unknown:1"
            _write_jsonl(root / "unity_admission.jsonl", rows)

            report = run_task_qc(root)

            self.assertFalse(report.passed)
            self.assertIn("admission_candidate_fk", {issue.code for issue in report.errors})

    def test_causal_prediction_horizon_is_bounded(self) -> None:
        """因果预测日志中的实际预测时域不得超过冻结的 180 ms。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            path = root / "unity_render.jsonl"
            rows = _read_jsonl(path)
            causal = next(row for row in rows if row["smoothing_strategy"] == "causal_prediction")
            causal["prediction_horizon_ms"] = 180.1
            _write_jsonl(path, rows)

            report = run_task_qc(root)

            self.assertFalse(report.passed)
            self.assertIn("causal_prediction_horizon", {issue.code for issue in report.errors})

    def test_causal_diagnostics_do_not_leak_to_other_strategies(self) -> None:
        """非因果策略不得写入因果预测专用的浮点诊断。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            path = root / "unity_render.jsonl"
            rows = _read_jsonl(path)
            non_causal = next(row for row in rows if row["smoothing_strategy"] == "linear_slerp")
            non_causal["correction_position_residual_m"] = 0.001
            _write_jsonl(path, rows)

            report = run_task_qc(root)

            self.assertFalse(report.passed)
            self.assertIn("causal_diagnostics_scope", {issue.code for issue in report.errors})

    def test_occlusion_roles_must_start_hidden_and_alternate(self) -> None:
        """遮挡恢复 marker 必须从 occlusion_started 开始并严格交替闭合。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp), scenario_id="occlusion_recovery", marker_roles=("target_visible",))

            report = run_task_qc(root)

            self.assertFalse(report.passed)
            self.assertIn("occlusion_event_sequence", {issue.code for issue in report.errors})

    def test_transition_roles_must_start_motion_and_close(self) -> None:
        """起停 marker 必须从 transition_started 开始并以 transition_stopped 闭合。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(
                Path(tmp),
                scenario_id="start_stop_6dof",
                marker_roles=("transition_started",),
            )

            report = run_task_qc(root)

            self.assertFalse(report.passed)
            self.assertIn("transition_event_sequence", {issue.code for issue in report.errors})

    def test_nonfinite_json_constant_is_rejected(self) -> None:
        """JSONL 中的 NaN/Infinity 必须转为稳定 reader_error。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            candidate_path = root / "python_candidates.jsonl"
            candidate_path.write_text(
                candidate_path.read_text(encoding="utf-8").replace('"vcd_score":0.5', '"vcd_score":NaN'),
                encoding="utf-8",
            )

            report = run_task_qc(root)

            self.assertFalse(report.passed)
            self.assertIn("reader_error", {issue.code for issue in report.errors})

    def test_event_and_event_type_must_match(self) -> None:
        """事件行的两个稳定名称字段冲突时必须硬失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            rows = _read_jsonl(root / "unity_events.jsonl")
            rows[0]["event_type"] = "conflicting_event"
            _write_jsonl(root / "unity_events.jsonl", rows)

            report = run_task_qc(root)

            self.assertFalse(report.passed)
            self.assertIn("event_name_mismatch", {issue.code for issue in report.errors})

    def test_parameter_fingerprint_is_required_and_hash_bound(self) -> None:
        """数值参数指纹缺失或脱离 config_hash 修改时必须硬失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["variant_configs"][0]["configuration_fingerprint"] = "changed-without-rehash"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = run_task_qc(root)

            self.assertFalse(report.passed)
            self.assertIn("variant_config_hash", {issue.code for issue in report.errors})


def _write_valid_task(
    parent: Path,
    *,
    scenario_id: str = "static_head_motion",
    marker_roles: tuple[str, ...] = ("generic_marker",),
    include_causal_control: bool = True,
) -> Path:
    """写出一个包含当前九路 variant 的最小合法 task。"""

    root = parent / "task_1_s01_controller_right"
    root.mkdir()
    session_id = "s01"
    variant_configs: list[dict[str, object]] = []
    variant_definitions: list[dict[str, object]] = []
    admissions: list[dict[str, object]] = []
    renders: list[dict[str, object]] = []
    variant_specs = tuple(
        spec for spec in VARIANT_SPECS
        if include_causal_control or spec[0] != "EgoAnchor Causal Prediction"
    )
    for spec in variant_specs:
        label, motion, smoothing, gate, alignment, capture, vcd, temporal, static, low_score, server = spec
        configuration_fingerprint = (
            "fixture:causal|horizon:0.18|correction-half-life:0.06"
            if smoothing == "causal_prediction"
            else f"fixture:{label}"
        )
        config_hash = _variant_hash(spec, configuration_fingerprint)
        variant_config = {
            "label": label,
            "motion_model": motion,
            "smoothing_strategy": smoothing,
            "quality_gate": gate,
            "configuration_fingerprint": configuration_fingerprint,
            "config_hash": config_hash,
        }
        variant_configs.append(variant_config)
        variant_definitions.append(
            {
                "variant_id": label,
                "variant_label": label,
                "world_alignment_mode": alignment,
                "uses_capture_time_alignment": capture,
                "uses_vcd_admission": vcd,
                "uses_temporal_synthesis": temporal,
                "uses_static_lock": static,
                "uses_low_score_reacquire": low_score,
                "uses_server_reacquire": server,
                "config_hash": config_hash,
            }
        )
        admissions.append(
            {
                "schema_version": 2,
                "event": "unity_admission",
                "session_id": session_id,
                "candidate_id": "s01:1:1",
                "frame_id": 1,
                "variant_id": label,
                "variant_label": label,
                "unity_pose_handle_mono_ms": 10.0,
                "unity_frame": 1,
                "world_alignment_mode": alignment,
                "uses_capture_time_alignment": capture,
                "source_capture_mono_ms": 5.0,
                "source_capture_unity_frame": 1,
                "has_aligned_raw": False,
                "aligned_raw_pos": None,
                "aligned_raw_rot": None,
                "has_arrival_time_raw": False,
                "arrival_time_raw_pos": None,
                "arrival_time_raw_rot": None,
                "arrival_time_raw_mono_ms": None,
                "uses_vcd_admission": vcd,
                "vcd_score": 0.8,
                "quality_gate": gate,
                "admission_decision": "accepted",
                "policy_action": "Accept",
                "policy_reason": "accept",
                "anchor_state": "Tracking",
                "motion_model": motion,
                "smoothing_strategy": smoothing,
                "uses_temporal_synthesis": temporal,
                "uses_static_lock": static,
                "config_hash": config_hash,
                "experiment_id": "exp1_system_characterization",
                "scenario_id": scenario_id,
                "trial_id": "trial_001",
                "event_id": "event_001",
                "condition_id": f"exp1_system_characterization/{scenario_id}",
            }
        )
        renders.append(
            {
                "schema_version": 2,
                "event": "unity_render",
                "session_id": session_id,
                "render_tick_id": 1,
                "render_mono_ms": 11.0,
                "render_unix_ms": 1011.0,
                "render_unity_frame": 1,
                "variant_id": label,
                "variant_label": label,
                "source_frame_id": -1,
                "head_pos": None,
                "head_rot": None,
                "reference_pose_valid": True,
                "reference_pose_source": "transform",
                "reference_pose_fresh": True,
                "reference_pose_keep_alive": False,
                "reference_pose_fresh_age_ms": 0.0,
                "reference_pos": [0.0, 0.0, 0.0],
                "reference_rot": [0.0, 0.0, 0.0, 1.0],
                "reference_linear_speed_m_s": 0.0,
                "reference_angular_speed_deg_s": 0.0,
                "experiment_id": "exp1_system_characterization",
                "scenario_id": scenario_id,
                "trial_id": "trial_001",
                "event_id": "event_001",
                "condition_id": f"exp1_system_characterization/{scenario_id}",
                "has_output_pose": False,
                "output_pos": None,
                "output_rot": None,
                "has_display_pose": False,
                "display_pos": None,
                "display_rot": None,
                "anchor_state": "Lost",
                "policy_action": "Hold",
                "policy_reason": "no_pose",
                "observation_age_ms": None,
                "policy_output_target_mono_ms": None,
                "smoothing_delay_ms": None,
                "prediction_horizon_ms": 0.0 if smoothing == "causal_prediction" else None,
                "correction_position_residual_m": 0.0 if smoothing == "causal_prediction" else None,
                "correction_rotation_residual_deg": 0.0 if smoothing == "causal_prediction" else None,
                "continuity_reset_count": 0,
                "latest_static_locked": False,
                "latest_accepted_score": None,
                "quality_gate": gate,
                "motion_model": motion,
                "smoothing_strategy": smoothing,
                "config_hash": config_hash,
            }
        )

    aggregate_hash = _aggregate_hash([str(item["config_hash"]) for item in variant_configs])
    unity_events = [_event(session_id, "session_started", 2.0, scenario_id=scenario_id)]
    unity_events.append(_event(session_id, "trial_started", 3.0, scenario_id=scenario_id, trial_id="trial_001"))
    for index, role in enumerate(marker_roles, start=1):
        unity_events.append(
            _event(
                session_id,
                "event_marker",
                3.0 + index,
                scenario_id=scenario_id,
                trial_id="trial_001",
                event_id=f"event_{index:03d}",
                role=role,
            )
        )
    unity_events.append(
        _event(
            session_id,
            "trial_ended",
            4.0 + len(marker_roles),
            scenario_id=scenario_id,
            trial_id="trial_001",
            event_id=f"event_{len(marker_roles):03d}",
            role=marker_roles[-1],
        )
    )
    python_events = [
        _event(session_id, "runtime_started", 1.0, source="python_runtime"),
        _event(session_id, "runtime_stopped", 10.0, source="python_runtime"),
    ]
    merged_events = sorted(python_events + unity_events, key=lambda row: float(row["created_unix_ms"]))

    manifest = {
        "schema_version": 2,
        "session_id": session_id,
        "object_id": "controller_right",
        "run_kind": "formal",
        "experiment_ids": ["exp1_system_characterization", "exp2_design_attribution"],
        "operator_id": "single_operator",
        "created_unix_ms": 1000.0,
        "unity_run_mode": "test",
        "python_host": "test-host",
        "unity_version": "test",
        "python_version": "3.test",
        "egoanchor_git_commit": "",
        "protocol_version": "v1",
        "config_hash": aggregate_hash,
        "frozen_parameter_set_id": aggregate_hash,
        "object_model_id": "controller_right",
        "platform_reference": {"preflight_passed": True},
        "log_files": {
            "python_candidates": "python_candidates.jsonl",
            "unity_reference": "unity_reference.jsonl",
            "unity_admission": "unity_admission.jsonl",
            "unity_render": "unity_render.jsonl",
            "events": "events.jsonl",
        },
        "variant_labels": [str(item["label"]) for item in variant_configs],
        "variant_configs": variant_configs,
        "variant_definitions": variant_definitions,
        "completed_tasks": [
            {
                "task_number": 1,
                "experiment_id": "exp1_system_characterization",
                "scenario_id": scenario_id,
                "trial_id": "trial_001",
            }
        ],
        "trial_plan": [
            {"experiment_id": "exp1_system_characterization", "scenario_id": scenario_id}
        ],
        "log_writer_stats": {
            "python_candidates.jsonl": {"rows_written": None, "status": "pending_python_fragment"},
            "unity_reference.jsonl": {"rows_written": 1, "dropped_rows": 0, "write_error": ""},
            "unity_admission.jsonl": {"rows_written": len(variant_specs), "dropped_rows": 0, "write_error": ""},
            "unity_render.jsonl": {"rows_written": len(variant_specs), "dropped_rows": 0, "write_error": ""},
            "events.jsonl": {
                "rows_written": None,
                "status": "pending_python_fragment_merge",
                "unity": {"rows_written": len(unity_events), "dropped_rows": 0, "write_error": ""},
            },
        },
    }
    manifest["variant_matrix_id"] = "exp12_9_causal_v3"
    python_session = {
        "schema_version": 2,
        "session_id": session_id,
        "object_id": "controller_right",
        "python_log_filename": "python_candidates.jsonl",
        "python_events_log_filename": "python_events.jsonl",
        "log_files": {
            "python_candidates": "python_candidates.jsonl",
            "python_events": "python_events.jsonl",
        },
        "state": "python_stopped",
        "python_host": "test-host",
        "python_version": "3.test",
        "log_writer_stats": {
            "python_candidates.jsonl": {"rows_written": 1, "dropped_rows": 0, "log_write_failures": 0},
            "python_events.jsonl": {"rows_written": 2, "dropped_rows": 0, "log_write_failures": 0},
        },
    }
    candidate = {
        "schema_version": 2,
        "event": "python_candidate",
        "session_id": session_id,
        "frame_id": 1,
        "candidate_id": "s01:1:1",
        "server_receive_mono_ms": 1.0,
        "server_publish_mono_ms": 2.0,
        "has_pose": False,
        "pose_matrix_cv_camera": None,
        "pose_tx_m": None,
        "pose_ty_m": None,
        "pose_tz_m": None,
        "pose_qx": None,
        "pose_qy": None,
        "pose_qz": None,
        "pose_qw": None,
        "pose_source": "NONE",
        "phase": "WAITING",
        "stage": 4,
        "failure_reason": "no_pose",
        "vcd_score": 0.5,
        "visibility_score": 0.5,
        "geometry_core_score": 0.5,
        "color_projection_score": None,
        "depth_alignment_score": 0.5,
        "depth_abs_score": 0.5,
        "depth_struct_score": 0.5,
        "depth_alpha": 0.5,
        "reliability_flags": [],
        "render_diagnostics": {"score": 0.5},
        "total_ms": 1.0,
        "yolo_ms": 0.0,
        "depth_ms": 0.0,
        "cutie_ms": 0.0,
        "pose_ms": 0.0,
    }
    reference = {
        "schema_version": 2,
        "event": "unity_reference",
        "session_id": session_id,
        "frame_id": 1,
        "capture_mono_ms": 5.0,
        "capture_unix_ms": 1005.0,
        "capture_unity_frame": 1,
        "sender_mono_ms": 5.0,
        "sender_unity_frame": 1,
        "image_time_basis": "camera_pose_history_proxy",
        "image_time_offset_frames": 0,
        "publish_attempt_mono_ms": 5.0,
        "publish_succeeded": True,
        "head_pos": None,
        "head_rot": None,
        "cam_valid": True,
        "camera_reference": "test",
        "cam_pos": None,
        "cam_rot": None,
        "reference_pose_valid": True,
        "reference_pose_source": "transform",
        "reference_pose_fresh": True,
        "reference_pose_keep_alive": False,
        "reference_pose_fresh_age_ms": 0.0,
        "reference_pos": [0.0, 0.0, 0.0],
        "reference_rot": [0.0, 0.0, 0.0, 1.0],
    }

    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "python_session.json").write_text(json.dumps(python_session), encoding="utf-8")
    _write_jsonl(root / "python_candidates.jsonl", [candidate])
    _write_jsonl(root / "python_events.jsonl", python_events)
    _write_jsonl(root / "unity_reference.jsonl", [reference])
    _write_jsonl(root / "unity_admission.jsonl", admissions)
    _write_jsonl(root / "unity_render.jsonl", renders)
    _write_jsonl(root / "unity_events.jsonl", unity_events)
    _write_jsonl(root / "events.jsonl", merged_events)
    return root


def _event(
    session_id: str,
    event: str,
    created_unix_ms: float,
    *,
    source: str = "experiment_ui",
    scenario_id: str = "",
    trial_id: str = "",
    event_id: str = "",
    role: str = "",
) -> dict[str, object]:
    """构造最小 schema-v2 事件行。"""

    return {
        "schema_version": 2,
        "event": event,
        "event_type": event,
        "session_id": session_id,
        "source": source,
        "created_unix_ms": created_unix_ms,
        "mono_ms": created_unix_ms,
        "unity_frame": -1,
        "severity": "info",
        "experiment_id": "exp1_system_characterization" if scenario_id else "",
        "scenario_id": scenario_id,
        "trial_id": trial_id,
        "event_id": event_id,
        "variant_id": "",
        "message": event,
        "payload": {
            "condition_id": f"exp1_system_characterization/{scenario_id}" if scenario_id else "",
            "event_role": role,
        },
    }


def _variant_hash(
    spec: tuple[object, ...],
    configuration_fingerprint: str,
) -> str:
    """按 Unity FNV-1a 规则计算测试 variant 配置哈希。"""

    values = [str(value) for value in spec[:5]]
    values.append(configuration_fingerprint)
    values.extend("1" if bool(value) else "0" for value in spec[5:])
    return _fnv1a("|".join(values).encode("utf-8"))


def _aggregate_hash(config_hashes: list[str]) -> str:
    """按 manifest 顺序计算整体配置哈希。"""

    return _fnv1a("".join(config_hashes).encode("utf-8"))


def _fnv1a(data: bytes) -> str:
    """返回 64 位 FNV-1a 十六进制摘要。"""

    value = 14695981039346656037
    for byte in data:
        value ^= byte
        value = (value * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """写出测试 JSONL，不复用生产 reader。"""

    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    """读取测试 JSONL 为可修改行列表。"""

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _file_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    """返回目录内全部文件的长度和 SHA-256，验证 QC 只读。"""

    return {
        str(path.relative_to(root)): (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


if __name__ == "__main__":
    unittest.main()
