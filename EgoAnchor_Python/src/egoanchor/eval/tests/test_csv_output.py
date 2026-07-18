"""Task 9 CSV 输出、lineage 和原子目录发布测试。"""

from __future__ import annotations

import csv
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from egoanchor.eval import input_workbook_set_sha256, publish_analysis_outputs


class CsvOutputTests(unittest.TestCase):
    """验证 CSV 编码、空值、布尔值和失败时的原子性。"""

    def test_csv_round_trip_uses_utf8_blank_and_lowercase_bool(self) -> None:
        """中文、None 和 bool 必须按冻结 Stage 2 约定写出。"""

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            result = publish_analysis_outputs(
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
                publish_analysis_outputs(output, {"unknown": []}, input_workbooks=())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_backup_cleanup_retries_after_windows_file_lock(self) -> None:
        """旧结果备份被 Windows 短暂占用时应重试清理并完成发布。"""

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            publish_analysis_outputs(output, {"analysis_qc": []})
            real_rmtree = shutil.rmtree
            backup_failures = 0

            def intermittent_rmtree(path: str | Path) -> None:
                """仅让正式备份目录的第一次删除模拟共享锁失败。"""

                nonlocal backup_failures
                if Path(path).name == ".results.previous" and backup_failures == 0:
                    backup_failures += 1
                    raise PermissionError("simulated Windows file lock")
                real_rmtree(path)

            with patch(
                "shutil.rmtree",
                side_effect=intermittent_rmtree,
            ):
                publish_analysis_outputs(output, {"analysis_qc": []})

            self.assertEqual(backup_failures, 1)
            self.assertTrue(output.is_dir())
            self.assertFalse(output.with_name(".results.previous").exists())

    def test_publish_directory_does_not_use_restrictive_mkdtemp_acl(self) -> None:
        """正式 CSV 目录必须从父目录继承 ACL，不能沿用 mkdtemp 限制。"""

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            with patch(
                "tempfile.mkdtemp",
                side_effect=AssertionError("mkdtemp must not create publish directories"),
            ):
                publish_analysis_outputs(output, {"analysis_qc": []})
            self.assertTrue((output / "audit" / "analysis_qc.csv").is_file())

    def test_committed_publish_ignores_exhausted_backup_cleanup(self) -> None:
        """正式目录提交后旧备份清理失败不得伪装成发布失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            publish_analysis_outputs(output, {"analysis_qc": []})
            with patch(
                "egoanchor.eval.analysis.csv_output._remove_tree",
                side_effect=OSError("persistent Windows file lock"),
            ):
                result = publish_analysis_outputs(output, {"analysis_qc": []})

            self.assertEqual(result.output_root, output)
            self.assertTrue((output / "audit" / "analysis_qc.csv").is_file())
            self.assertTrue(output.with_name(".results.previous").is_dir())

    def test_scoped_table_cannot_escape_publish_directory(self) -> None:
        """作用域前缀不得使用父目录或任意新目录。"""

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            with self.assertRaisesRegex(ValueError, "作用域非法"):
                publish_analysis_outputs(output, {"../outside/event_metrics": []})
            self.assertFalse((Path(tmp) / "outside").exists())

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
            publish_analysis_outputs(
                output,
                {"exp1/event_metrics": [row], "exp2/event_metrics": [row]},
                input_workbooks=(),
            )
            self.assertTrue((output / "exp1" / "event_metrics.csv").is_file())
            self.assertTrue((output / "exp2" / "event_metrics.csv").is_file())
            lineage = (output / "audit" / "lineage.csv").read_text(encoding="utf-8")
            self.assertIn("exp1/event_metrics.csv", lineage)
            self.assertIn("exp2/event_metrics.csv", lineage)

    def test_lineage_names_real_upstream_sheets_and_filter_key(self) -> None:
        """结果 lineage 不得把输出表名和输出主键冒充为上游来源。"""

        row = {
            "session_id": "session",
            "experiment_id": "exp1_system_characterization",
            "scenario_id": "static_head_motion",
            "trial_id": "trial",
            "event_id": "event",
            "condition_id": "condition",
            "variant_id": "EgoAnchor",
            "metric_key": "translation_event_pninetyfive_mm",
            "metric_value": 1.0,
            "metric_unit": "mm",
            "aggregation_level": "event",
            "input_workbook_sha256": "a" * 64,
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            publish_analysis_outputs(output, {"exp1/event_metrics": [row]})
            with (output / "audit" / "lineage.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                lineage = next(
                    item
                    for item in csv.DictReader(handle)
                    if item["output_path"] == "exp1/event_metrics.csv"
                )

        self.assertEqual(
            lineage["source_sheet"],
            "unity_render;events;event_payload;completed_trials",
        )
        self.assertIn("session_id=session", lineage["source_row_key"])
        self.assertIn("event_id=event", lineage["source_row_key"])
        self.assertIn("variant_id=EgoAnchor", lineage["source_row_key"])

    def test_lineage_pairs_each_source_hash_with_its_workbook_paths(self) -> None:
        """单 workbook 和集合 hash 都必须对应准确的输入路径集合。"""

        first = SimpleNamespace(
            path=Path("first.xlsx"),
            sha256="a" * 64,
            session_id="first-session",
            row_count=1,
        )
        second = SimpleNamespace(
            path=Path("second.xlsx"),
            sha256="b" * 64,
            session_id="second-session",
            row_count=1,
        )
        row = {
            "session_id": "first-session",
            "experiment_id": "exp1_system_characterization",
            "scenario_id": "static_head_motion",
            "trial_id": "trial",
            "event_id": "event",
            "condition_id": "condition",
            "variant_id": "EgoAnchor",
            "metric_key": "translation_event_pninetyfive_mm",
            "metric_value": 1.0,
            "metric_unit": "mm",
            "aggregation_level": "event",
            "input_workbook_sha256": first.sha256,
        }
        batch_row = {**row, "session_id": "", "input_workbook_sha256": input_workbook_set_sha256((first.sha256, second.sha256))}
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            publish_analysis_outputs(
                output,
                {"exp1/event_metrics": [row], "exp1/scenario_summary": [batch_row]},
                input_workbooks=(first, second),
            )
            with (output / "audit" / "lineage.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                lineage = list(csv.DictReader(handle))

        event = next(item for item in lineage if item["output_path"] == "exp1/event_metrics.csv")
        summary = next(item for item in lineage if item["output_path"] == "exp1/scenario_summary.csv")
        self.assertEqual(event["input_workbook"], "first.xlsx")
        self.assertEqual(event["input_workbook_sha256"], first.sha256)
        self.assertEqual(summary["input_workbook"], "first.xlsx;second.xlsx")

    def test_paper_source_hash_is_backfilled_from_published_csv(self) -> None:
        """paper 行的 source_sha256 必须是其 source_csv 二进制 hash。"""

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            publish_analysis_outputs(
                output,
                {
                    "analysis_qc": [
                        {
                            "check_id": "paper-source",
                            "status": "passed",
                            "observed": 1,
                            "expected": 1,
                            "details": "source",
                        }
                    ],
                    "numbers": [
                        {
                            "experiment": "exp1_system_characterization",
                            "macro_name": "SessionCount",
                            "value": 1,
                            "source_csv": "audit/analysis_qc.csv",
                            "source_sha256": "a" * 64,
                        }
                    ],
                },
            )
            source = output / "audit" / "analysis_qc.csv"
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            with (output / "paper" / "numbers.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["source_sha256"], expected)


if __name__ == "__main__":
    unittest.main()
