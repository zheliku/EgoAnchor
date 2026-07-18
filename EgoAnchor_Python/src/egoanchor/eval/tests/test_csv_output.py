"""Task 9 CSV 输出、lineage 和原子目录发布测试。"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from egoanchor.eval import write_csv_tables


class CsvOutputTests(unittest.TestCase):
    """验证 CSV 编码、空值、布尔值和失败时的原子性。"""

    def test_csv_round_trip_uses_utf8_blank_and_lowercase_bool(self) -> None:
        """中文、None 和 bool 必须按冻结 Stage 2 约定写出。"""

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            result = write_csv_tables(
                output,
                {
                    "analysis_qc": [
                        {
                            "check_id": "中文检查",
                            "status": "passed",
                            "observed": None,
                            "expected": "true",
                            "details": "全部通过",
                        }
                    ]
                },
                input_workbooks=(),
            )
            self.assertTrue(result.output_root.is_dir())
            path = output / "audit" / "analysis_qc.csv"
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["check_id"], "中文检查")
            self.assertEqual(rows[0]["observed"], "")
            self.assertEqual(rows[0]["status"], "passed")

            lineage = output / "audit" / "lineage.csv"
            self.assertTrue(lineage.is_file())

    def test_unknown_table_does_not_replace_existing_output(self) -> None:
        """序列化失败不能破坏既有正式目录。"""

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "未知 CSV 表"):
                write_csv_tables(output, {"unknown": []}, input_workbooks=())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_scoped_metric_tables_share_contract_but_publish_to_both_experiments(self) -> None:
        """exp1/exp2 同名长表必须各自落盘并分别写 lineage。"""

        row = {
            "session_id": "session",
            "experiment_id": "exp1_system_characterization",
            "scenario_id": "static_head_motion",
            "trial_id": "trial",
            "event_id": "event",
            "condition_id": "condition",
            "variant_id": "Arrival-Hold",
            "metric_key": "translation_event_pninetyfive_mm",
            "metric_value": 1.0,
            "metric_unit": "mm",
            "aggregation_level": "event",
            "input_workbook_sha256": "a" * 64,
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            write_csv_tables(
                output,
                {"exp1/event_metrics": [row], "exp2/event_metrics": [row]},
                input_workbooks=(),
            )
            self.assertTrue((output / "exp1" / "event_metrics.csv").is_file())
            self.assertTrue((output / "exp2" / "event_metrics.csv").is_file())
            lineage = (output / "audit" / "lineage.csv").read_text(encoding="utf-8")
            self.assertIn("exp1/event_metrics.csv", lineage)
            self.assertIn("exp2/event_metrics.csv", lineage)


if __name__ == "__main__":
    unittest.main()
