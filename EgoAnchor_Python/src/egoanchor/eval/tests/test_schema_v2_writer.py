"""schema-v2 JSONL writer 契约测试。"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
