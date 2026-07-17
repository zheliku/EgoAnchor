"""schema-v2 reader 契约测试。"""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from egoanchor.eval.schema_v2 import (
    EventRow,
    PythonCandidateRow,
    SchemaV2Error,
    UnityAdmissionRow,
    UnityReferenceRow,
    UnityRenderRow,
    aggregate_config_hash,
    join_candidate_admission,
    join_render_reference,
    load_session_v2,
    merge_event_fragments,
    select_completed_trials,
    select_trials,
)


class SchemaV2ReaderTest(unittest.TestCase):
    """验证 reader 只读取固定的新 schema 文件。"""

    def test_reader_rejects_legacy_manifest(self) -> None:
        """只有旧 manifest 的目录必须给出明确硬切换错误。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "s01"
            session_dir.mkdir()
            (session_dir / "session_manifest.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(SchemaV2Error, "schema-v2 requires manifest.json"):
                load_session_v2(session_dir)

    def test_reader_loads_fixed_files_as_normalized_tables(self) -> None:
        """最小完整 session 应加载为六个稳定成员。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))

            session = load_session_v2(session_dir)

            self.assertEqual(session.manifest["session_id"], "s01")
            self.assertEqual(session.manifest["python_host"], "python-host")
            self.assertEqual(session.manifest["python_version"], "3.11")
            self.assertEqual(len(session.python_candidates), 2)
            self.assertEqual(len(session.unity_reference), 2)
            self.assertEqual(len(session.unity_admission), 4)
            self.assertEqual(len(session.unity_render), 4)
            self.assertEqual(len(session.events), 3)

    def test_merge_event_fragments_is_deterministic_and_counted(self) -> None:
        """模拟 Mutagen 回传两个端的分片，合并结果可重复且行数可核对。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            stats = merge_event_fragments(session_dir)
            first = (session_dir / "events.jsonl").read_text(encoding="utf-8")

            self.assertEqual(stats, {"python_rows": 1, "unity_rows": 2, "rows": 3})
            self.assertEqual(len(first.splitlines()), 3)
            self.assertEqual(merge_event_fragments(session_dir), stats)
            self.assertEqual((session_dir / "events.jsonl").read_text(encoding="utf-8"), first)

    def test_reader_rejects_legacy_shared_events_file(self) -> None:
        """只有旧共享 events.jsonl 的目录不得被当作当前 schema。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            merge_event_fragments(session_dir)
            (session_dir / "python_events.jsonl").unlink()
            (session_dir / "unity_events.jsonl").unlink()

            with self.assertRaisesRegex(SchemaV2Error, "legacy shared event file"):
                load_session_v2(session_dir)

    def test_reader_rejects_event_fragment_stat_mismatch(self) -> None:
        """任一端分片行数与其停止片段统计不一致时不得合并通过。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            fragment_path = session_dir / "python_session.json"
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            fragment["log_writer_stats"]["python_events.jsonl"]["rows_written"] = 2
            fragment_path.write_text(json.dumps(fragment), encoding="utf-8")

            with self.assertRaisesRegex(SchemaV2Error, "python_events.jsonl row count"):
                load_session_v2(session_dir)
            self.assertFalse((session_dir / "events.jsonl").exists())

    def test_reader_does_not_publish_events_while_python_is_running(self) -> None:
        """Python 未停止时即使两个分片存在，也不得留下派生事件文件。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            fragment_path = session_dir / "python_session.json"
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            fragment["state"] = "python_started"
            fragment_path.write_text(json.dumps(fragment), encoding="utf-8")

            with self.assertRaisesRegex(SchemaV2Error, "state must be python_stopped"):
                load_session_v2(session_dir)
            self.assertFalse((session_dir / "events.jsonl").exists())

    def test_reader_retries_after_mutagen_completes_partial_fragment(self) -> None:
        """metadata 先到而事件仍在同步时不发布，补齐后同一目录可以直接重试。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            fragment_path = session_dir / "python_session.json"
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            fragment["log_writer_stats"]["python_events.jsonl"]["rows_written"] = 2
            fragment_path.write_text(json.dumps(fragment), encoding="utf-8")

            with self.assertRaisesRegex(SchemaV2Error, "python_events.jsonl row count"):
                load_session_v2(session_dir)
            self.assertFalse((session_dir / "events.jsonl").exists())

            python_events_path = session_dir / "python_events.jsonl"
            rows = [json.loads(line) for line in python_events_path.read_text(encoding="utf-8").splitlines()]
            second = dict(rows[0])
            second.update(
                event="runtime_stopped",
                event_type="runtime_stopped",
                created_unix_ms=12003.0,
                mono_ms=1203.0,
            )
            _write_jsonl(python_events_path, [*rows, second])

            session = load_session_v2(session_dir)

            self.assertEqual(len(session.events), 4)
            self.assertEqual(len((session_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()), 4)

    def test_reader_atomically_repairs_early_derived_events(self) -> None:
        """完整权威分片到齐后应重建早期生成的部分 events，而不是永久拒绝。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            events_path = session_dir / "events.jsonl"
            events_path.write_text(
                (session_dir / "python_events.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            session = load_session_v2(session_dir)

            self.assertEqual(len(session.events), 3)
            self.assertEqual(len(events_path.read_text(encoding="utf-8").splitlines()), 3)

    def test_event_publish_failure_preserves_existing_file_and_cleans_temp(self) -> None:
        """原子替换失败时不得损坏旧文件，也不得遗留 merge 临时文件。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            events_path = session_dir / "events.jsonl"
            original = "previous-derived-content\n"
            events_path.write_text(original, encoding="utf-8")

            with patch.object(Path, "replace", side_effect=OSError("replace unavailable")):
                with self.assertRaisesRegex(SchemaV2Error, "cannot publish merged events.jsonl"):
                    load_session_v2(session_dir)

            self.assertEqual(events_path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(session_dir.glob(".events.jsonl.*.merge.tmp")), [])

    def test_reader_allows_task_prefix_on_session_directory(self) -> None:
        """跨端都停止后可给目录增加任务前缀，内部 session_id 保持不变。"""

        with tempfile.TemporaryDirectory() as tmp:
            original = _write_minimal_session(Path(tmp))
            renamed = original.parent / "task01_head__s01"
            original.rename(renamed)

            session = load_session_v2(renamed)

            self.assertEqual(session.session_id, "s01")
            self.assertEqual(session.paths.session_dir, renamed)
            self.assertEqual(
                session.manifest["log_writer_stats"]["python_candidates.jsonl"]["status"],
                "merged",
            )
            self.assertEqual(session.manifest["log_writer_stats"]["events.jsonl"]["rows_written"], 3)

    def test_joins_preserve_candidate_and_reference_matches(self) -> None:
        """candidate/admission 与 render/reference join 必须保留全部变体行并命中右表。"""

        with tempfile.TemporaryDirectory() as tmp:
            session = load_session_v2(_write_minimal_session(Path(tmp)))

            candidate_join = join_candidate_admission(session)
            reference_join = join_render_reference(session)

            self.assertEqual(len(candidate_join), 4)
            self.assertTrue(candidate_join["server_receive_mono_ms"].notna().all())
            self.assertEqual(len(reference_join), 4)
            self.assertTrue(reference_join["capture_mono_ms"].notna().all())

    def test_select_trials_filters_all_related_tables(self) -> None:
        """实验筛选必须同步裁剪 candidate、reference、admission、render 与 event。"""

        with tempfile.TemporaryDirectory() as tmp:
            session = load_session_v2(_write_minimal_session(Path(tmp)))

            selected = select_trials(session, "exp1_system_characterization")

            self.assertEqual(len(selected.python_candidates), 1)
            self.assertEqual(len(selected.unity_reference), 1)
            self.assertEqual(len(selected.unity_admission), 2)
            self.assertEqual(len(selected.unity_render), 2)
            self.assertEqual(len(selected.events), 2)
            self.assertEqual(set(selected.events["experiment_id"]), {"", "exp1_system_characterization"})
            self.assertEqual(
                selected.manifest["experiment_ids"],
                ["exp1_system_characterization", "exp2_design_attribution"],
            )

    def test_select_completed_trials_excludes_incomplete_and_rejected_trials(self) -> None:
        """分析视图只保留已结束且没有后续 trial_rejected 的任务。"""

        with tempfile.TemporaryDirectory() as tmp:
            session = load_session_v2(_write_minimal_session(Path(tmp)))
            lifecycle = pd.DataFrame(
                [
                    _trial_event("s01", "exp1_system_characterization", "static_head_motion", "trial-01", "event-01", "trial_ended", 1300.0),
                    _trial_event("s01", "exp2_design_attribution", "ablation_capture_alignment", "trial-02", "event-02", "trial_ended", 1301.0),
                    _trial_event("s01", "exp2_design_attribution", "ablation_capture_alignment", "trial-02", "event-02", "trial_rejected", 1302.0),
                ]
            )
            session = replace(session, events=pd.concat([session.events, lifecycle], ignore_index=True))

            selected = select_completed_trials(session)

            self.assertEqual(set(selected.unity_render["trial_id"]), {"trial-01"})
            self.assertEqual(set(selected.unity_admission["trial_id"]), {"trial-01"})
            self.assertEqual(set(selected.python_candidates["frame_id"]), {1})
            self.assertEqual(set(selected.unity_reference["frame_id"]), {1})
            self.assertNotIn("trial-02", set(selected.events["trial_id"]))

    def test_candidate_join_rejects_unknown_candidate_id(self) -> None:
        """Admission 指向不存在的 candidate_id 时不得产生带空值的伪连接。"""

        with tempfile.TemporaryDirectory() as tmp:
            session = load_session_v2(_write_minimal_session(Path(tmp)))
            session.unity_admission.loc[0, "candidate_id"] = "s01:999:1"

            with self.assertRaisesRegex(SchemaV2Error, "unknown candidate_id"):
                join_candidate_admission(session)

    def test_render_join_rejects_unknown_source_frame_id(self) -> None:
        """Render 指向不存在的 source_frame_id 时不得伪造平台参考。"""

        with tempfile.TemporaryDirectory() as tmp:
            session = load_session_v2(_write_minimal_session(Path(tmp)))
            session.unity_render.loc[0, "source_frame_id"] = 999

            with self.assertRaisesRegex(SchemaV2Error, "unknown source_frame_id"):
                join_render_reference(session)

    def test_render_join_allows_uninitialized_source_frame(self) -> None:
        """尚无观测时的 source_frame_id=-1 是合法启动状态，应保留为未匹配参考行。"""

        with tempfile.TemporaryDirectory() as tmp:
            session = load_session_v2(_write_minimal_session(Path(tmp)))
            session.unity_render.loc[0, "source_frame_id"] = -1

            joined = join_render_reference(session)

            self.assertEqual(len(joined), 4)
            self.assertTrue(math.isnan(float(joined.loc[0, "frame_id"])))

    def test_reader_rejects_null_candidate_id(self) -> None:
        """null candidate_id 不得利用 pandas 的 null 匹配语义形成伪连接。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            candidate_path = session_dir / "python_candidates.jsonl"
            rows = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines()]
            rows[0]["candidate_id"] = None
            _write_jsonl(candidate_path, rows)

            with self.assertRaisesRegex(SchemaV2Error, "candidate_id has invalid type"):
                load_session_v2(session_dir)

    def test_reader_rejects_missing_required_row_field(self) -> None:
        """固定行类型缺少任一 dataclass 字段时必须在读取阶段失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            rows = [
                json.loads(line)
                for line in (session_dir / "unity_render.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            rows[0].pop("has_display_pose")
            _write_jsonl(session_dir / "unity_render.jsonl", rows)

            with self.assertRaisesRegex(SchemaV2Error, "missing required fields.*has_display_pose"):
                load_session_v2(session_dir)

    def test_reader_rejects_string_encoded_boolean(self) -> None:
        """布尔字段不得接受字符串，否则 pandas 后续 bool 转换会反转 false 语义。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            render_path = session_dir / "unity_render.jsonl"
            rows = [json.loads(line) for line in render_path.read_text(encoding="utf-8").splitlines()]
            rows[0]["has_output_pose"] = "false"
            _write_jsonl(render_path, rows)

            with self.assertRaisesRegex(SchemaV2Error, "has_output_pose has invalid type"):
                load_session_v2(session_dir)

    def test_reader_accepts_null_for_optional_admission_time(self) -> None:
        """无 pose candidate 的 Unity 处理时刻允许为 null，Python 3.14 也必须正确识别联合类型。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            admission_path = session_dir / "unity_admission.jsonl"
            rows = [json.loads(line) for line in admission_path.read_text(encoding="utf-8").splitlines()]
            rows[0]["unity_pose_handle_mono_ms"] = None
            _write_jsonl(admission_path, rows)

            session = load_session_v2(session_dir)

            self.assertTrue(pd.isna(session.unity_admission.loc[0, "unity_pose_handle_mono_ms"]))

    def test_reader_rejects_wrong_pose_vector_length(self) -> None:
        """位置与四元数数组必须保持固定维度，防止分析阶段才出现广播错误。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            render_path = session_dir / "unity_render.jsonl"
            rows = [json.loads(line) for line in render_path.read_text(encoding="utf-8").splitlines()]
            rows[0]["display_rot"] = [0.0, 0.0, 1.0]
            _write_jsonl(render_path, rows)

            with self.assertRaisesRegex(SchemaV2Error, "display_rot must contain exactly 4 values"):
                load_session_v2(session_dir)

    def test_reader_rejects_python_fragment_identity_mismatch(self) -> None:
        """Python fragment 与 Unity manifest 的 session_id 不一致时不得合并。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            fragment_path = session_dir / "python_session.json"
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            fragment["session_id"] = "other-session"
            fragment_path.write_text(json.dumps(fragment), encoding="utf-8")

            with self.assertRaisesRegex(SchemaV2Error, "python_session.json session_id does not match"):
                load_session_v2(session_dir)
            self.assertFalse((session_dir / "events.jsonl").exists())

    def test_reader_rejects_candidate_id_frame_mismatch(self) -> None:
        """candidate_id 内嵌 frame 必须与显式 frame_id 完全一致。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            admission_path = session_dir / "unity_admission.jsonl"
            rows = [json.loads(line) for line in admission_path.read_text(encoding="utf-8").splitlines()]
            rows[0]["frame_id"] = 999
            _write_jsonl(admission_path, rows)

            with self.assertRaisesRegex(SchemaV2Error, "candidate_id does not match"):
                load_session_v2(session_dir)

    def test_reader_rejects_python_fragment_file_mapping_mismatch(self) -> None:
        """Python fragment 必须声明与 schema-v2 相同的固定文件映射。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            fragment_path = session_dir / "python_session.json"
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            fragment["python_events_log_filename"] = "other.jsonl"
            fragment_path.write_text(json.dumps(fragment), encoding="utf-8")

            with self.assertRaisesRegex(SchemaV2Error, "python_events_log_filename=python_events.jsonl"):
                load_session_v2(session_dir)
            self.assertFalse((session_dir / "events.jsonl").exists())

    def test_reader_rejects_python_fragment_host_type_coercion(self) -> None:
        """host/version 必须原生为非空字符串，不得把数组或数字强制转换后通过 Formal QC。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            fragment_path = session_dir / "python_session.json"
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            fragment["python_host"] = ["bad-host"]
            fragment_path.write_text(json.dumps(fragment), encoding="utf-8")

            with self.assertRaisesRegex(SchemaV2Error, "python_host must be a non-empty string"):
                load_session_v2(session_dir)


def _write_minimal_session(root: Path) -> Path:
    """写入 reader/QC 共用的最小 schema-v2 session。"""

    session_dir = root / "s01"
    session_dir.mkdir()
    (session_dir / "audit_samples").mkdir()
    variant_definitions = [
        {"variant_id": "arrival", "variant_label": "Arrival-Hold", "config_hash": "arrival-cfg"},
        {"variant_id": "egoanchor", "variant_label": "EgoAnchor", "config_hash": "egoanchor-cfg"},
    ]
    manifest = {
        "schema_version": 2,
        "session_id": "s01",
        "object_id": "controller_right",
        "run_kind": "formal",
        "experiment_ids": ["exp1_system_characterization", "exp2_design_attribution"],
        "operator_id": "operator-01",
        "created_unix_ms": 10000.0,
        "unity_run_mode": "editor_link",
        "python_host": "python-host",
        "unity_version": "6000.3.11f1",
        "python_version": "3.11",
        "egoanchor_git_commit": "0123456789abcdef",
        "protocol_version": "v1",
        "config_hash": aggregate_config_hash(variant_definitions),
        "frozen_parameter_set_id": "dev-1",
        "object_model_id": "controller-mesh-v1",
        "platform_reference": {
            "transform_path": "OVRCameraRig/OVRInteractionComprehensive/OVRControllerVisualRight/OVRControllerPrefab",
            "controller": "RTouch",
            "preflight_passed": True,
        },
        "variant_definitions": variant_definitions,
        "completed_tasks": [],
        "log_files": {
            "python_candidates": "python_candidates.jsonl",
            "unity_reference": "unity_reference.jsonl",
            "unity_admission": "unity_admission.jsonl",
            "unity_render": "unity_render.jsonl",
            "events": "events.jsonl",
        },
        "trial_plan": [
            {"experiment_id": "exp1_system_characterization", "scenario_id": "static_head_motion"},
        ],
        "log_writer_stats": {
            "python_candidates.jsonl": {
                "rows_written": None,
                "dropped_rows": None,
                "status": "pending_python_fragment",
            },
            "unity_reference.jsonl": {"rows_written": 2, "dropped_rows": 0, "write_error": ""},
            "unity_admission.jsonl": {"rows_written": 4, "dropped_rows": 0, "write_error": ""},
            "unity_render.jsonl": {"rows_written": 4, "dropped_rows": 0, "write_error": ""},
            "events.jsonl": {
                "rows_written": None,
                "dropped_rows": None,
                "status": "pending_python_fragment_merge",
                "unity": {"rows_written": 2, "dropped_rows": 0, "write_error": ""},
            },
        },
    }
    (session_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (session_dir / "python_session.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "session_id": "s01",
                "object_id": "controller_right",
                "state": "python_stopped",
                "python_host": "python-host",
                "python_version": "3.11",
                "python_log_filename": "python_candidates.jsonl",
                "python_events_log_filename": "python_events.jsonl",
                "log_files": {
                    "python_candidates": "python_candidates.jsonl",
                    "python_events": "python_events.jsonl",
                },
                "log_writer_stats": {
                    "python_candidates.jsonl": {"rows_written": 2, "dropped_rows": 0, "log_write_failures": 0},
                    "python_events.jsonl": {"rows_written": 1, "dropped_rows": 0, "log_write_failures": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        session_dir / "python_candidates.jsonl",
        [
            PythonCandidateRow(
                session_id="s01", frame_id=frame_id, candidate_id=f"s01:{frame_id}:1",
                server_receive_mono_ms=1000.0 + frame_id, server_publish_mono_ms=1010.0 + frame_id,
                has_pose=True, pose_matrix_cv_camera=[1.0] * 16,
            ).to_dict()
            for frame_id in (1, 2)
        ],
    )
    _write_jsonl(
        session_dir / "unity_reference.jsonl",
        [
            UnityReferenceRow(
                session_id="s01", frame_id=frame_id, capture_mono_ms=900.0 + frame_id,
                capture_unix_ms=10000.0 + frame_id, capture_unity_frame=frame_id,
                sender_mono_ms=905.0 + frame_id, sender_unity_frame=frame_id,
                publish_attempt_mono_ms=906.0 + frame_id, publish_succeeded=True,
                cam_valid=True, camera_reference="Left", reference_pose_valid=True,
            ).to_dict()
            for frame_id in (1, 2)
        ],
    )
    _write_jsonl(
        session_dir / "unity_admission.jsonl",
        [
            UnityAdmissionRow(
                session_id="s01", candidate_id=f"s01:{frame_id}:1", frame_id=frame_id,
                variant_id=variant_id, variant_label=variant_id,
                experiment_id=("exp1_system_characterization" if frame_id == 1 else "exp2_design_attribution"),
                scenario_id=("static_head_motion" if frame_id == 1 else "ablation_capture_alignment"),
                trial_id=f"trial-{frame_id:02d}", event_id=f"event-{frame_id:02d}",
                condition_id=f"condition-{frame_id:02d}",
                unity_pose_handle_mono_ms=1020.0 + frame_id, unity_frame=frame_id,
                world_alignment_mode="CaptureTime", uses_capture_time_alignment=True,
                admission_decision="accepted", policy_action="Accept",
                config_hash=f"{variant_id}-cfg",
            ).to_dict()
            for frame_id in (1, 2)
            for variant_id in ("arrival", "egoanchor")
        ],
    )
    _write_jsonl(
        session_dir / "unity_render.jsonl",
        [
            UnityRenderRow(
                session_id="s01", render_tick_id=frame_id, render_mono_ms=1100.0 + frame_id,
                render_unix_ms=11000.0 + frame_id, render_unity_frame=frame_id,
                variant_id=variant_id, variant_label=variant_id,
                experiment_id=("exp1_system_characterization" if frame_id == 1 else "exp2_design_attribution"),
                scenario_id=("static_head_motion" if frame_id == 1 else "ablation_capture_alignment"),
                trial_id=f"trial-{frame_id:02d}", event_id=f"event-{frame_id:02d}",
                condition_id=f"condition-{frame_id:02d}",
                source_frame_id=frame_id, has_output_pose=True, has_display_pose=True,
                config_hash=f"{variant_id}-cfg",
            ).to_dict()
            for frame_id in (1, 2)
            for variant_id in ("arrival", "egoanchor")
        ],
    )
    _write_jsonl(
        session_dir / "python_events.jsonl",
        [
            EventRow(
                session_id="s01", event="runtime_started", event_type="runtime_started",
                source="python_runtime", created_unix_ms=12000.0, mono_ms=1200.0,
            ).to_dict(),
        ],
    )
    _write_jsonl(
        session_dir / "unity_events.jsonl",
        [
            EventRow(
                session_id="s01", event="event_marker", event_type="event_marker", source="unity",
                created_unix_ms=12001.0, mono_ms=1201.0,
                experiment_id="exp1_system_characterization", scenario_id="static_head_motion",
                trial_id="trial-01", event_id="event-01",
            ).to_dict(),
            EventRow(
                session_id="s01", event="event_marker", event_type="event_marker", source="unity",
                created_unix_ms=12002.0, mono_ms=1202.0,
                experiment_id="exp2_design_attribution", scenario_id="ablation_capture_alignment",
                trial_id="trial-02", event_id="event-02",
            ).to_dict(),
        ],
    )
    return session_dir


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """把测试行写成 UTF-8 JSONL。"""

    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _trial_event(
    session_id: str,
    experiment_id: str,
    scenario_id: str,
    trial_id: str,
    event_id: str,
    event_type: str,
    mono_ms: float,
) -> dict[str, object]:
    """构造一个用于完成态投影测试的 trial 生命周期事件。"""

    return EventRow(
        session_id=session_id,
        event=event_type,
        event_type=event_type,
        source="experiment_ui",
        created_unix_ms=mono_ms + 10000.0,
        mono_ms=mono_ms,
        experiment_id=experiment_id,
        scenario_id=scenario_id,
        trial_id=trial_id,
        event_id=event_id,
    ).to_dict()


__all__ = ["_write_minimal_session"]


if __name__ == "__main__":
    unittest.main()
