"""跨端事件分片安全物化测试。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from egoanchor.eval import finalize_task_events, run_task_qc

from .test_reader_qc import _read_jsonl, _write_jsonl, _write_valid_task


def _sha256(path: Path) -> str:
    """返回测试文件 SHA-256，不依赖生产 provenance helper。"""

    return hashlib.sha256(path.read_bytes()).hexdigest()


class EventMergeTests(unittest.TestCase):
    """验证缺失事件总表的确定性生成与失败保护。"""

    def test_qc_materializes_missing_events_before_read_only_checks(self) -> None:
        """合法双分片应由 QC 原子生成事件总表并继续通过检查。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            events_path = root / "events.jsonl"
            expected = events_path.read_text(encoding="utf-8")
            events_path.unlink()
            finalize_task_events(root)
            report = run_task_qc(root)

            self.assertTrue(report.passed)
            self.assertEqual(events_path.read_text(encoding="utf-8"), expected)

    def test_finalize_is_idempotent_for_an_existing_valid_file(self) -> None:
        """重复物化不得改变已经存在的合法事件总表。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            events_path = root / "events.jsonl"
            before = events_path.read_bytes()

            result = finalize_task_events(root)

            self.assertEqual(result, events_path)
            self.assertEqual(events_path.read_bytes(), before)

    def test_running_python_never_leaves_a_derived_event_file(self) -> None:
        """Python 未停止时不得生成半同步事件总表。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            events_path = root / "events.jsonl"
            events_path.unlink()
            session_path = root / "python_session.json"
            session = json.loads(session_path.read_text(encoding="utf-8"))
            session["state"] = "python_running"
            session_path.write_text(json.dumps(session), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "python_stopped"):
                finalize_task_events(root)

            self.assertFalse(events_path.exists())
            self.assertFalse(tuple(root.glob(".events.jsonl.*.tmp")))

    def test_fragment_count_mismatch_never_leaves_a_derived_event_file(self) -> None:
        """任一分片行数与停止态统计不一致时不得发布事件总表。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            events_path = root / "events.jsonl"
            events_path.unlink()
            session_path = root / "python_session.json"
            session = json.loads(session_path.read_text(encoding="utf-8"))
            session["log_writer_stats"]["python_events.jsonl"]["rows_written"] += 1
            session_path.write_text(json.dumps(session), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "python_events.jsonl.*行数"):
                finalize_task_events(root)

            self.assertFalse(events_path.exists())
            self.assertFalse(tuple(root.glob(".events.jsonl.*.tmp")))

    def test_invalid_document_schema_never_leaves_a_derived_event_file(self) -> None:
        """任一停止态文档不是 schema-v2 时不得发布事件总表。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            events_path = root / "events.jsonl"
            events_path.unlink()
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema_version"] = 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "schema_version"):
                finalize_task_events(root)

            self.assertFalse(events_path.exists())

    def test_source_change_during_merge_never_publishes_stale_events(self) -> None:
        """来源在读取期间变化时必须失败，不能留下无法自愈的旧快照。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            events_path = root / "events.jsonl"
            events_path.unlink()
            real_hash = _sha256
            calls = 0

            def changing_hash(path: Path) -> str:
                """第二轮重哈希时模拟 Mutagen 替换 Unity 事件分片。"""

                nonlocal calls
                calls += 1
                if calls == 5:
                    unity_path = root / "unity_events.jsonl"
                    rows = _read_jsonl(unity_path)
                    rows[0]["message"] = "changed-during-merge"
                    _write_jsonl(unity_path, rows)
                return real_hash(path)

            with patch("egoanchor.eval.preprocess.events.file_sha256", side_effect=changing_hash):
                with self.assertRaisesRegex(ValueError, "物化期间发生变化"):
                    finalize_task_events(root)

            self.assertFalse(events_path.exists())
            self.assertFalse(tuple(root.glob(".events.jsonl.*.tmp")))

    def test_source_change_immediately_after_publish_removes_owned_target(self) -> None:
        """硬链接后的来源变化必须撤回本轮创建的陈旧总表。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            events_path = root / "events.jsonl"
            events_path.unlink()
            real_hash = _sha256
            calls = 0

            def changing_hash(path: Path) -> str:
                """在发布后的首轮复核中模拟来源被 Mutagen 替换。"""

                nonlocal calls
                calls += 1
                if calls == 9:
                    unity_path = root / "unity_events.jsonl"
                    rows = _read_jsonl(unity_path)
                    rows[0]["message"] = "changed-after-link"
                    _write_jsonl(unity_path, rows)
                return real_hash(path)

            with patch("egoanchor.eval.preprocess.events.file_sha256", side_effect=changing_hash):
                with self.assertRaisesRegex(ValueError, "物化期间发生变化"):
                    finalize_task_events(root)

            self.assertFalse(events_path.exists())
            self.assertFalse(tuple(root.glob(".events.jsonl.*.tmp")))

    def test_source_disappearance_after_publish_removes_owned_target(self) -> None:
        """发布后来源暂时不可读时也必须撤回本轮事件总表。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            events_path = root / "events.jsonl"
            events_path.unlink()
            real_hash = _sha256
            calls = 0

            def disappearing_hash(path: Path) -> str:
                """在发布后的首次来源复核中模拟同步文件短暂消失。"""

                nonlocal calls
                calls += 1
                if calls == 9:
                    raise FileNotFoundError(path)
                return real_hash(path)

            with patch("egoanchor.eval.preprocess.events.file_sha256", side_effect=disappearing_hash):
                with self.assertRaises(FileNotFoundError):
                    finalize_task_events(root)

            self.assertFalse(events_path.exists())

    def test_rollback_failure_preserves_the_source_change_error(self) -> None:
        """撤回文件遇到持续锁时不得遮蔽来源竞态主错误。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            events_path = root / "events.jsonl"
            events_path.unlink()
            real_hash = _sha256
            calls = 0

            def changing_hash(path: Path) -> str:
                """在发布后复核时制造稳定可复现的来源变化。"""

                nonlocal calls
                calls += 1
                if calls == 9:
                    unity_path = root / "unity_events.jsonl"
                    rows = _read_jsonl(unity_path)
                    rows[0]["message"] = "changed-before-rollback"
                    _write_jsonl(unity_path, rows)
                return real_hash(path)

            with (
                patch("egoanchor.eval.preprocess.events.file_sha256", side_effect=changing_hash),
                patch(
                    "egoanchor.eval.preprocess.events._remove_owned_target",
                    side_effect=PermissionError("target locked"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "物化期间发生变化") as caught:
                    finalize_task_events(root)

            self.assertTrue(any("撤回失败" in note for note in getattr(caught.exception, "__notes__", ())))

    def test_concurrent_target_creation_is_never_overwritten(self) -> None:
        """目标在发布瞬间出现时必须保留现有字节并交给后续 QC。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            events_path = root / "events.jsonl"
            events_path.unlink()
            unexpected = b"concurrent-writer\n"

            def concurrent_link(source: Path, destination: Path) -> None:
                """模拟不遵守 task 锁的外部进程抢先创建目标。"""

                del source
                destination.write_bytes(unexpected)
                raise FileExistsError(destination)

            with patch("egoanchor.eval.preprocess.events.os.link", side_effect=concurrent_link):
                finalize_task_events(root)

            self.assertEqual(events_path.read_bytes(), unexpected)

    def test_existing_tampered_file_is_rejected_instead_of_overwritten(self) -> None:
        """已有事件总表只接受验证，物化入口不得替用户掩盖篡改。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_valid_task(Path(tmp))
            events_path = root / "events.jsonl"
            rows = _read_jsonl(events_path)
            rows[0]["message"] = "tampered"
            _write_jsonl(events_path, rows)
            tampered = events_path.read_bytes()

            result = finalize_task_events(root)
            report = run_task_qc(root)

            self.assertEqual(result, events_path)
            self.assertEqual(events_path.read_bytes(), tampered)
            self.assertFalse(report.passed)
            self.assertIn("events_merge", {issue.code for issue in report.errors})


if __name__ == "__main__":
    unittest.main()
