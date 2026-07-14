"""schema-v2 reader 契约测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from egoanchor.eval.schema_v2 import SchemaV2Error, load_session_v2


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
            self.assertEqual(len(session.python_candidates), 1)
            self.assertEqual(len(session.unity_reference), 1)
            self.assertEqual(len(session.unity_admission), 2)
            self.assertEqual(len(session.unity_render), 2)
            self.assertEqual(len(session.events), 1)


def _write_minimal_session(root: Path) -> Path:
    """写入 reader/QC 共用的最小 schema-v2 session。"""

    session_dir = root / "s01"
    session_dir.mkdir()
    (session_dir / "audit_samples").mkdir()
    manifest = {
        "schema_version": 2,
        "session_id": "s01",
        "object_id": "controller_right",
        "run_kind": "smoke",
        "config_hash": "cfg-1",
        "frozen_parameter_set_id": "dev-1",
        "variant_definitions": [
            {"variant_id": "arrival", "variant_label": "Arrival-Hold"},
            {"variant_id": "egoanchor", "variant_label": "EgoAnchor"},
        ],
        "log_files": {
            "python_candidates": "python_candidates.jsonl",
            "unity_reference": "unity_reference.jsonl",
            "unity_admission": "unity_admission.jsonl",
            "unity_render": "unity_render.jsonl",
            "events": "events.jsonl",
        },
        "log_writer_stats": {
            "python_candidates.jsonl": {"dropped_rows": 0},
            "unity_reference.jsonl": {"dropped_rows": 0},
            "unity_admission.jsonl": {"dropped_rows": 0},
            "unity_render.jsonl": {"dropped_rows": 0},
            "events.jsonl": {"dropped_rows": 0},
        },
    }
    (session_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _write_jsonl(
        session_dir / "python_candidates.jsonl",
        [{"schema_version": 2, "event": "python_candidate", "session_id": "s01", "frame_id": 1}],
    )
    _write_jsonl(
        session_dir / "unity_reference.jsonl",
        [{"schema_version": 2, "event": "unity_reference", "session_id": "s01", "frame_id": 1}],
    )
    _write_jsonl(
        session_dir / "unity_admission.jsonl",
        [
            {
                "schema_version": 2,
                "event": "unity_admission",
                "session_id": "s01",
                "candidate_id": "s01:1:1",
                "variant_id": variant_id,
            }
            for variant_id in ("arrival", "egoanchor")
        ],
    )
    _write_jsonl(
        session_dir / "unity_render.jsonl",
        [
            {
                "schema_version": 2,
                "event": "unity_render",
                "session_id": "s01",
                "render_tick_id": 1,
                "variant_id": variant_id,
            }
            for variant_id in ("arrival", "egoanchor")
        ],
    )
    _write_jsonl(
        session_dir / "events.jsonl",
        [{"schema_version": 2, "event": "session_started", "session_id": "s01"}],
    )
    return session_dir


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """把测试行写成 UTF-8 JSONL。"""

    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


__all__ = ["_write_minimal_session"]


if __name__ == "__main__":
    unittest.main()
