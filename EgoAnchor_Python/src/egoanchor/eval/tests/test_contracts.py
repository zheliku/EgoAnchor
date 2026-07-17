"""Task 2 workbook、CSV、指标和参数契约测试。"""

from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path

from egoanchor.eval.contracts import (
    CSV_TABLE_NAMES,
    METRIC_DEFINITIONS,
    SCENARIO_ORDER,
    SHEET_CONTRACTS,
    SHEET_NAMES,
    contract_catalog,
    metric_catalog,
)


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "analysis_params.toml"
"""冻结分析参数文件路径。"""


class ContractTests(unittest.TestCase):
    """验证 Task 2 契约是稳定、可序列化且没有歧义的。"""

    def test_contract_catalog_is_json_serializable(self) -> None:
        """全部契约目录可以无损转换为 JSON。"""

        encoded = json.dumps(contract_catalog(), ensure_ascii=False, sort_keys=True)
        self.assertIn("workbook", encoded)
        self.assertIn("csv", encoded)
        self.assertIn("versions", encoded)

    def test_workbook_sheet_order_and_keys_are_unique(self) -> None:
        """workbook sheet 顺序、名称、主键和列名均无重复。"""

        self.assertEqual(tuple(sheet.name for sheet in SHEET_CONTRACTS), SHEET_NAMES)
        self.assertEqual(len(SHEET_NAMES), len(set(SHEET_NAMES)))
        for sheet in SHEET_CONTRACTS:
            self.assertTrue(sheet.primary_key, sheet.name)
            self.assertEqual(len(sheet.column_names()), len(set(sheet.column_names())), sheet.name)
            for key in sheet.primary_key:
                self.assertIn(key, sheet.column_names(), sheet.name)

    def test_required_workbook_and_csv_tables_are_present(self) -> None:
        """四阶段路线要求的事实 sheet、审计 sheet 和 CSV 长表均已声明。"""

        for name in (
            "source_files",
            "metadata_kv",
            "python_candidates",
            "candidate_flags",
            "candidate_diag",
            "unity_admission",
            "unity_render",
            "event_payload",
            "qc_checks",
            "data_dictionary",
        ):
            self.assertIn(name, SHEET_NAMES)
        for name in (
            "analysis_run",
            "inputs",
            "metric_catalog",
            "filter_catalog",
            "analysis_qc",
            "lineage",
            "sensitivity",
            "event_metrics",
            "trial_metrics",
            "session_metrics",
            "scenario_summary",
            "paired_deltas",
            "vcd_risk_points",
            "vcd_curve",
            "vcd_aurc",
            "numbers",
            "tables",
        ):
            self.assertIn(name, CSV_TABLE_NAMES)

    def test_metrics_cover_all_scenarios_and_tex_names_have_no_digits(self) -> None:
        """指标覆盖五个场景，TeX 后缀不含阿拉伯数字。"""

        self.assertEqual(
            set(SCENARIO_ORDER),
            {
                "static_head_motion",
                "start_stop_6dof",
                "continuous_translation",
                "continuous_rotation",
                "occlusion_recovery",
            },
        )
        self.assertTrue(METRIC_DEFINITIONS)
        for metric in METRIC_DEFINITIONS:
            self.assertRegex(metric.tex_suffix, r"^[A-Za-z][A-Za-z]*$")
            self.assertTrue(set(metric.scenarios).issubset(set(SCENARIO_ORDER)), metric.key)
        self.assertEqual(len(metric_catalog()), len(METRIC_DEFINITIONS))

    def test_analysis_params_are_valid_and_parameter_lines_have_comments(self) -> None:
        """TOML 可解析，且每个参数赋值行都有中文同行注释。"""

        config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertIn("contract", config)
        self.assertIn("metrics", config)
        self.assertIn("thresholds", config)

        assignment_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=")
        for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
            if assignment_pattern.match(line.strip()):
                self.assertIn("#", line, line)
                self.assertRegex(line, r"#.*[\u4e00-\u9fff]", line)


if __name__ == "__main__":
    unittest.main()
