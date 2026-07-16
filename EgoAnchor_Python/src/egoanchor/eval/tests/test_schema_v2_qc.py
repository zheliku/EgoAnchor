"""schema-v2 QC 契约测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from egoanchor.eval.schema_v2 import FORMAL_VARIANTS, aggregate_config_hash, load_session_v2, run_schema_qc
from egoanchor.eval.tests.test_schema_v2_reader import _write_minimal_session


class SchemaV2QcTest(unittest.TestCase):
    """验证采集前必须满足的结构性质量门禁。"""

    def test_complete_session_passes_qc(self) -> None:
        """完整的 render tick × variant 矩阵应通过 QC。"""

        with tempfile.TemporaryDirectory() as tmp:
            report = run_schema_qc(load_session_v2(_write_qc_session(Path(tmp))))

            self.assertTrue(report.passed, report.errors)

    def test_completed_task_summary_must_match_lifecycle_events(self) -> None:
        """manifest 不得把没有 trial_ended 的任务伪装成已完成。"""

        with tempfile.TemporaryDirectory() as tmp:
            session = load_session_v2(_write_qc_session(Path(tmp)))
            session.manifest["completed_tasks"] = [
                {
                    "task_number": 1,
                    "experiment_id": "exp1_system_characterization",
                    "scenario_id": "static_head_motion",
                    "trial_id": "trial-missing",
                }
            ]

            report = run_schema_qc(session)

            self.assertFalse(report.passed)
            self.assertTrue(any("accepted lifecycle trials" in error for error in report.errors))

    def test_missing_render_variant_fails_qc(self) -> None:
        """任一 tick 缺少固定变体时必须失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            render_path = session_dir / "unity_render.jsonl"
            render_path.write_text(render_path.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("render tick" in error for error in report.errors))

    def test_pending_python_stats_fail_qc(self) -> None:
        """Python 未停止或 fragment 缺失时，pending 统计不得被当作零丢行。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            (session_dir / "python_session.json").unlink()

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("pending" in error for error in report.errors))

    def test_formal_session_requires_frozen_hashes(self) -> None:
        """Formal session 缺少整体或参数集合 hash 时必须失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            manifest_path = session_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["run_kind"] = "formal"
            manifest["config_hash"] = ""
            manifest["frozen_parameter_set_id"] = ""
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("config_hash" in error for error in report.errors))
            self.assertTrue(any("frozen_parameter_set_id" in error for error in report.errors))

    def test_duplicate_manifest_variant_fails_qc(self) -> None:
        """重复 variant_id 不得被 set 静默吞掉。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            manifest_path = session_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["variant_definitions"].append(dict(manifest["variant_definitions"][0]))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("duplicate variant_id" in error for error in report.errors))

    def test_formal_session_with_exact_variants_and_hash_passes(self) -> None:
        """冻结的 8 个 runtime 与正确 aggregate hash 应通过 Formal QC。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertTrue(report.passed, report.errors)

    def test_formal_session_allows_missing_optional_git_commit(self) -> None:
        """Git commit 是可选审计信息，不得要求操作者在每次采集前填写。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            manifest_path = session_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["egoanchor_git_commit"] = ""
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertTrue(report.passed, report.errors)

    def test_formal_trial_has_no_duration_bounds(self) -> None:
        """Formal trial 可在事件协议完成后立即结束，不设持续时间上下界。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            events_path = session_dir / "unity_events.jsonl"
            events = _read_jsonl(events_path)
            for event in events:
                if event["event_type"] == "trial_ended":
                    event["mono_ms"] = 2000.0
                    event["created_unix_ms"] = 12000.0
            _write_jsonl(events_path, events)
            (session_dir / "events.jsonl").unlink(missing_ok=True)

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertTrue(report.passed, report.errors)
            self.assertEqual(report.metrics["completed_trial_duration_seconds"]["trial-01"], 0.0)

    def test_formal_trial_end_before_start_fails_qc(self) -> None:
        """取消时长门禁后仍必须拒绝结束时刻早于开始时刻的损坏日志。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            events_path = session_dir / "unity_events.jsonl"
            events = _read_jsonl(events_path)
            for event in events:
                if event["event_type"] == "trial_ended":
                    event["mono_ms"] = 1000.0
            _write_jsonl(events_path, events)
            (session_dir / "events.jsonl").unlink(missing_ok=True)

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("precedes trial_started" in error for error in report.errors))

    def test_unknown_admission_variant_fails_qc(self) -> None:
        """Admission 混入 manifest 未声明变体时必须失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            admission_path = session_dir / "unity_admission.jsonl"
            rows = _read_jsonl(admission_path)
            unknown = dict(rows[0])
            unknown["variant_id"] = "unknown"
            unknown["variant_label"] = "unknown"
            rows.append(unknown)
            _write_jsonl(admission_path, rows)
            _set_writer_rows(session_dir, "unity_admission.jsonl", len(rows))

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("unknown admission variants" in error for error in report.errors))

    def test_unconsumed_python_candidate_is_reported_without_faking_admission(self) -> None:
        """latest-only 或停机边界未被 Unity 消费的 Python candidate 应统计警告，不伪造 admission。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            admission_path = session_dir / "unity_admission.jsonl"
            rows = [row for row in _read_jsonl(admission_path) if row["candidate_id"] != "s01:2:1"]
            _write_jsonl(admission_path, rows)
            _set_writer_rows(session_dir, "unity_admission.jsonl", len(rows))

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertTrue(report.passed, report.errors)
            self.assertEqual(report.metrics["python_candidates_without_unity_admission"], 1)
            self.assertTrue(any("not consumed by Unity admission" in warning for warning in report.warnings))

    def test_duplicate_candidate_and_reference_keys_fail_qc(self) -> None:
        """join 右表的 candidate/reference 主键重复必须在 QC 阶段阻断。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            for file_name in ("python_candidates.jsonl", "unity_reference.jsonl"):
                path = session_dir / file_name
                rows = _read_jsonl(path)
                rows.append(dict(rows[0]))
                _write_jsonl(path, rows)
                _set_writer_rows(session_dir, file_name, len(rows))

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("duplicate session_id/candidate_id" in error for error in report.errors))
            self.assertTrue(any("duplicate session_id/frame_id" in error for error in report.errors))

    def test_nested_legacy_field_and_dropped_rows_fail_qc(self) -> None:
        """嵌套旧字段和任一 writer 丢行都不得逃过 QC。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            events_path = session_dir / "unity_events.jsonl"
            events = _read_jsonl(events_path)
            events[0]["payload"] = {"unity_output": "legacy"}
            _write_jsonl(events_path, events)
            (session_dir / "events.jsonl").unlink(missing_ok=True)
            manifest_path = session_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["log_writer_stats"]["unity_render.jsonl"]["dropped_rows"] = 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("forbidden legacy fields" in error for error in report.errors))
            self.assertTrue(any("writer dropped rows" in error for error in report.errors))

    def test_invalid_run_kind_and_aggregate_hash_fail_qc(self) -> None:
        """run kind 拼写和非空但错误的 aggregate hash 都不得绕过门禁。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            manifest_path = session_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["run_kind"] = "forml"
            manifest["config_hash"] = "deadbeefdeadbeef"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("manifest.run_kind" in error for error in report.errors))
            self.assertTrue(any("does not match ordered variant" in error for error in report.errors))

    def test_every_variant_row_requires_matching_config_hash(self) -> None:
        """逐行 hash 为空或不匹配时不得被同变体的其他正确行掩盖。"""

        with tempfile.TemporaryDirectory() as tmp:
            session = load_session_v2(_write_qc_session(Path(tmp)))
            session.unity_admission.loc[0, "config_hash"] = None
            session.unity_render.loc[0, "config_hash"] = "wrong-hash"

            report = run_schema_qc(session)

            self.assertFalse(report.passed)
            self.assertTrue(any("unity_admission row" in error for error in report.errors))
            self.assertTrue(any("unity_render row" in error for error in report.errors))

    def test_missing_render_column_fails_qc_without_exception(self) -> None:
        """直接传入损坏 DataFrame 时，QC 应返回缺列错误而不是抛出 KeyError。"""

        with tempfile.TemporaryDirectory() as tmp:
            session = load_session_v2(_write_qc_session(Path(tmp)))
            session.unity_render.drop(columns="source_frame_id", inplace=True)

            report = run_schema_qc(session)

            self.assertFalse(report.passed)
            self.assertTrue(any("unity_render requires columns: source_frame_id" in error for error in report.errors))

    def test_uninitialized_render_cannot_claim_visible_pose(self) -> None:
        """source_frame_id=-1 只允许尚无 output/display 的初始化行。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            render_path = session_dir / "unity_render.jsonl"
            rows = _read_jsonl(render_path)
            rows[0]["source_frame_id"] = -1
            rows[0]["has_display_pose"] = True
            _write_jsonl(render_path, rows)

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("display/output pose without a source frame" in error for error in report.errors))

    def test_writer_failure_and_error_fail_qc(self) -> None:
        """归一后的 Python failure 和 Unity write_error 均必须失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_qc_session(Path(tmp))
            fragment_path = session_dir / "python_session.json"
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            fragment["log_writer_stats"]["python_candidates.jsonl"]["log_write_failures"] = 1
            fragment_path.write_text(json.dumps(fragment), encoding="utf-8")
            manifest_path = session_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["log_writer_stats"]["unity_render.jsonl"]["write_error"] = "disk error"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("writer failures" in error for error in report.errors))
            self.assertTrue(any("writer error" in error for error in report.errors))

    def test_out_of_range_reliability_scores_fail_qc(self) -> None:
        """candidate 或 admission 的连续评分越界时正式分析门禁必须失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            session = load_session_v2(_write_qc_session(Path(tmp)))
            session.python_candidates.loc[0, "vcd_score"] = 1.01
            session.unity_admission.loc[0, "vcd_score"] = -0.01

            report = run_schema_qc(session)

            self.assertFalse(report.passed)
            self.assertTrue(any("python_candidates.vcd_score" in error for error in report.errors))
            self.assertTrue(any("unity_admission.vcd_score" in error for error in report.errors))


def _write_qc_session(root: Path) -> Path:
    """创建满足唯一 formal run kind 和八 runtime 契约的 QC fixture。"""

    session_dir = _write_minimal_session(root)
    _expand_to_formal_variants(session_dir)
    return session_dir


def _expand_to_formal_variants(session_dir: Path) -> None:
    """把双变体工程 fixture 扩展为冻结的 8-variant Formal fixture。"""

    definitions = [
        {"variant_id": label, "variant_label": label, "config_hash": f"formal-{index:02d}"}
        for index, label in enumerate(FORMAL_VARIANTS)
    ]
    hashes = {item["variant_id"]: item["config_hash"] for item in definitions}
    manifest_path = session_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_kind"] = "formal"
    manifest["variant_definitions"] = definitions
    manifest["config_hash"] = aggregate_config_hash(definitions)
    manifest["completed_tasks"] = [
        {
            "task_number": 1,
            "experiment_id": "exp1_system_characterization",
            "scenario_id": "static_head_motion",
            "trial_id": "trial-01",
        }
    ]

    admission_path = session_dir / "unity_admission.jsonl"
    admission_templates = {}
    for row in _read_jsonl(admission_path):
        admission_templates.setdefault(row["candidate_id"], row)
    admissions = []
    for template in admission_templates.values():
        for label in FORMAL_VARIANTS:
            row = dict(template)
            row.update(variant_id=label, variant_label=label, config_hash=hashes[label])
            admissions.append(row)
    _write_jsonl(admission_path, admissions)

    render_path = session_dir / "unity_render.jsonl"
    render_templates = {}
    for row in _read_jsonl(render_path):
        render_templates.setdefault(row["render_tick_id"], row)
    renders = []
    for template in render_templates.values():
        for label in FORMAL_VARIANTS:
            row = dict(template)
            row.update(variant_id=label, variant_label=label, config_hash=hashes[label])
            renders.append(row)
    _write_jsonl(render_path, renders)

    events_path = session_dir / "unity_events.jsonl"
    events = _read_jsonl(events_path)
    started = dict(events[0])
    started.update(
        event="trial_started",
        event_type="trial_started",
        source="experiment_ui",
        mono_ms=2000.0,
        created_unix_ms=12000.0,
    )
    ended = dict(started)
    ended.update(event="trial_ended", event_type="trial_ended", mono_ms=92000.0, created_unix_ms=102000.0)
    events.extend((started, ended))
    _write_jsonl(events_path, events)

    manifest["log_writer_stats"]["unity_admission.jsonl"]["rows_written"] = len(admissions)
    manifest["log_writer_stats"]["unity_render.jsonl"]["rows_written"] = len(renders)
    manifest["log_writer_stats"]["events.jsonl"]["unity"]["rows_written"] = 4
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    """读取测试 JSONL 为可修改字典列表。"""

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """覆盖写入测试 JSONL。"""

    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _set_writer_rows(session_dir: Path, file_name: str, rows_written: int) -> None:
    """同步 fixture manifest 的 writer row count。"""

    manifest_path = session_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["log_writer_stats"][file_name]["rows_written"] = rows_written
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
