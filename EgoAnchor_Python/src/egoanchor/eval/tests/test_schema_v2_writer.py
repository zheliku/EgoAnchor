"""schema-v2 JSONL writer 契约测试。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from egoanchor.eval.schema_v2 import JsonlTableWriter, SchemaV2Error


class SchemaV2WriterTest(unittest.TestCase):
    """验证 writer 只接受当前 schema 字段。"""

    def test_writer_rejects_legacy_rq_fields(self) -> None:
        """任意层级的旧 RQ 字段都必须阻止写入。"""

        for row in (
            {"schema_version": 2, "event": "event_marker", "session_id": "s01", "rq1_metric": "jitter"},
            {
                "schema_version": 2,
                "event": "event_marker",
                "session_id": "s01",
                "payload": {"rq2_trial_id": 3},
            },
        ):
            with self.subTest(row=row), tempfile.TemporaryDirectory() as tmp:
                writer = JsonlTableWriter(Path(tmp) / "events.jsonl")
                with self.assertRaises(SchemaV2Error):
                    writer.write(row)
                writer.close()

    def test_writer_serializes_dataclass_compatible_mapping(self) -> None:
        """合法行应写为严格 JSON，并暴露写入统计。"""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with JsonlTableWriter(path) as writer:
                writer.write(
                    {
                        "schema_version": 2,
                        "event": "event_marker",
                        "session_id": "s01",
                        "score": float("nan"),
                    }
                )

            row = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsNone(row["score"])
            self.assertEqual(writer.rows_written, 1)
            self.assertEqual(writer.dropped_rows, 0)

    def test_shared_append_serializes_concurrent_writers(self) -> None:
        """两个共享 writer 并发写同一文件时，每一行仍必须是独立合法 JSON。"""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            writers = [JsonlTableWriter(path, shared_append=True) for _ in range(2)]

            def write_rows(writer: JsonlTableWriter, source: str) -> None:
                """写入一组带来源标记的并发行。"""

                for index in range(100):
                    writer.write(
                        {
                            "schema_version": 2,
                            "event": "event_marker",
                            "session_id": "s01",
                            "source": source,
                            "index": index,
                        }
                    )

            threads = [
                threading.Thread(target=write_rows, args=(writer, f"writer-{index}"))
                for index, writer in enumerate(writers)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            for writer in writers:
                writer.close()

            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 200)
            self.assertEqual(sum(writer.rows_written for writer in writers), 200)
            self.assertEqual(sum(writer.dropped_rows for writer in writers), 0)
            self.assertFalse(Path(f"{path}.lock").exists())

    def test_shared_append_retries_transient_windows_permission_error(self) -> None:
        """Windows 锁文件竞态产生一次 PermissionError 时应在 deadline 内重试。"""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            writer = JsonlTableWriter(path, shared_append=True)
            original_open = os.open
            attempts = 0

            def open_with_transient_error(*args: object, **kwargs: object) -> int:
                """第一次模拟 Windows 锁竞争，随后调用真实 os.open。"""

                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise PermissionError("transient lock contention")
                return original_open(*args, **kwargs)

            with patch("egoanchor.eval.schema_v2.writers.os.open", side_effect=open_with_transient_error):
                writer.write({"schema_version": 2, "event": "event_marker", "session_id": "s01"})
            writer.close()

            self.assertEqual(attempts, 2)
            self.assertEqual(writer.rows_written, 1)
            self.assertEqual(writer.dropped_rows, 0)

    def test_shared_append_treats_locked_stale_check_as_active_contention(self) -> None:
        """无法 stat 锁文件时应视为对端仍持锁，而不是让 PermissionError 穿透。"""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            writer = JsonlTableWriter(path, shared_append=True)
            lock_path = Path(f"{path}.lock")
            lock_path.touch()

            with patch.object(Path, "stat", side_effect=PermissionError("lock is exclusively held")):
                writer._remove_stale_lock(lock_path)

            self.assertTrue(lock_path.exists())

    def test_shared_append_retries_transient_lock_release_error(self) -> None:
        """行已持久化后，锁释放的一次共享冲突不得把该行计为丢失。"""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            writer = JsonlTableWriter(path, shared_append=True)
            lock_path = Path(f"{path}.lock")
            original_unlink = Path.unlink
            release_attempts = 0

            def unlink_with_transient_error(target: Path, *args: object, **kwargs: object) -> None:
                """第一次释放目标锁时模拟 FileShare.None 竞争。"""

                nonlocal release_attempts
                if target == lock_path:
                    release_attempts += 1
                    if release_attempts == 1:
                        raise PermissionError("transient lock release contention")
                original_unlink(target, *args, **kwargs)

            with patch.object(Path, "unlink", new=unlink_with_transient_error):
                writer.write({"schema_version": 2, "event": "event_marker", "session_id": "s01"})
            writer.close()

            self.assertEqual(release_attempts, 2)
            self.assertEqual(writer.rows_written, 1)
            self.assertEqual(writer.dropped_rows, 0)
            self.assertFalse(lock_path.exists())


if __name__ == "__main__":
    unittest.main()
