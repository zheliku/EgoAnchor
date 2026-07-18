"""Task 2 workbook、CSV、指标和参数契约测试。"""

from __future__ import annotations

from dataclasses import replace
import json
import re
import tomllib
import unittest
from pathlib import Path

from egoanchor.eval import (
    CONTRACT_CHANGELOG,
    CONTRACT_VERSIONS,
    CSV_TABLE_CONTRACTS,
    CSV_TABLE_NAMES,
    METRIC_DEFINITIONS,
    SCENARIO_ORDER,
    SHEET_CONTRACTS,
    SHEET_NAMES,
    contract_catalog,
    get_sheet_contract,
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
            "sheet_index",
            "metadata_kv",
            "row_kv",
            "large_values",
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
            "paired_summary",
            "vcd_risk_points",
            "vcd_curve",
            "vcd_aurc",
            "numbers",
            "tables",
        ):
            self.assertIn(name, CSV_TABLE_NAMES)

    def test_scenario_summary_keeps_low_sample_statistics(self) -> None:
        """场景汇总必须显式保存低样本量报告所需的完整统计量。"""

        contract = next(table for table in CSV_TABLE_CONTRACTS if table.name == "scenario_summary")
        self.assertEqual(
            {
                "attempt_count",
                "sample_count",
                "success_rate",
                "median",
                "q1",
                "q3",
                "iqr",
                "minimum",
                "maximum",
            },
            {
                column.name
                for column in contract.columns
                if column.name
                in {
                    "attempt_count",
                    "sample_count",
                    "success_rate",
                    "median",
                    "q1",
                    "q3",
                    "iqr",
                    "minimum",
                    "maximum",
                }
            },
        )

    def test_workbook_contract_is_breaking_version_two(self) -> None:
        """无损 Stage 1 工作簿使用明确递增的 breaking v2 契约。"""

        versions = {contract.name: contract.version for contract in CONTRACT_VERSIONS}
        self.assertEqual(versions["workbook"], 2)
        changes = {change.version: change for change in CONTRACT_CHANGELOG}
        self.assertIn("workbook-v2", changes)
        self.assertTrue(changes["workbook-v2"].breaking)

    def test_workbook_fact_sheets_keep_critical_pose_and_time_fields(self) -> None:
        """reference、admission 与 render 保留后续科学分析依赖的关键字段。"""

        expected_columns = {
            "unity_reference": {
                "sender_mono_ms",
                "sender_unity_frame",
                "reference_sample_mono_ms",
                "image_time_basis",
                "image_time_offset_frames",
                "publish_attempt_mono_ms",
                "publish_succeeded",
                "head_pos_x_m",
                "head_pos_y_m",
                "head_pos_z_m",
                "head_rot_x",
                "head_rot_y",
                "head_rot_z",
                "head_rot_w",
                "cam_valid",
                "camera_reference",
                "cam_pos_x_m",
                "cam_pos_y_m",
                "cam_pos_z_m",
                "cam_rot_x",
                "cam_rot_y",
                "cam_rot_z",
                "cam_rot_w",
                "reference_pose_fresh",
                "reference_pose_keep_alive",
                "reference_pose_fresh_age_ms",
            },
            "unity_admission": {
                "frame_id",
                "unity_frame",
                "source_capture_mono_ms",
                "source_capture_unity_frame",
                "has_aligned_raw",
                "aligned_raw_pos_x_m",
                "aligned_raw_pos_y_m",
                "aligned_raw_pos_z_m",
                "aligned_raw_rot_x",
                "aligned_raw_rot_y",
                "aligned_raw_rot_z",
                "aligned_raw_rot_w",
                "has_arrival_time_raw",
                "arrival_time_raw_pos_x_m",
                "arrival_time_raw_pos_y_m",
                "arrival_time_raw_pos_z_m",
                "arrival_time_raw_rot_x",
                "arrival_time_raw_rot_y",
                "arrival_time_raw_rot_z",
                "arrival_time_raw_rot_w",
                "arrival_time_raw_mono_ms",
            },
            "unity_render": {
                "render_unix_ms",
                "render_unity_frame",
                "head_pos_x_m",
                "head_pos_y_m",
                "head_pos_z_m",
                "head_rot_x",
                "head_rot_y",
                "head_rot_z",
                "head_rot_w",
                "reference_pose_source",
                "reference_pose_fresh",
                "reference_pose_keep_alive",
                "reference_pose_fresh_age_ms",
                "reference_linear_speed_m_s",
                "reference_angular_speed_deg_s",
                "reference_pos_x_m",
                "reference_pos_y_m",
                "reference_pos_z_m",
                "reference_rot_x",
                "reference_rot_y",
                "reference_rot_z",
                "reference_rot_w",
                "output_pos_x_m",
                "output_pos_y_m",
                "output_pos_z_m",
                "output_rot_x",
                "output_rot_y",
                "output_rot_z",
                "output_rot_w",
                "display_pos_x_m",
                "display_pos_y_m",
                "display_pos_z_m",
                "display_rot_x",
                "display_rot_y",
                "display_rot_z",
                "display_rot_w",
                "anchor_pose_source",
                "has_source_capture_timing",
                "source_capture_mono_ms",
                "source_capture_unity_frame",
                "policy_output_target_mono_ms",
                "unity_pose_handle_mono_ms",
            },
        }
        for sheet_name, expected in expected_columns.items():
            actual = set(get_sheet_contract(sheet_name).column_names())
            self.assertFalse(expected - actual, f"{sheet_name} 缺少字段：{sorted(expected - actual)}")

    def test_workbook_primary_keys_are_non_nullable_and_foreign_keys_are_explicit(self) -> None:
        """主键列不可为空，candidate 与 variant 的跨 sheet 连接必须显式声明。"""

        for sheet in SHEET_CONTRACTS:
            columns = {column.name: column for column in sheet.columns}
            for key in sheet.primary_key:
                self.assertFalse(columns[key].nullable, f"{sheet.name}.{key}")

        expected_foreign_keys = {
            "candidate_flags": {
                (("session_id", "candidate_id"), "python_candidates", ("session_id", "candidate_id")),
            },
            "candidate_diag": {
                (("session_id", "candidate_id"), "python_candidates", ("session_id", "candidate_id")),
            },
            "unity_admission": {
                (("session_id", "candidate_id"), "python_candidates", ("session_id", "candidate_id")),
                (("session_id", "variant_id"), "variants", ("session_id", "variant_id")),
            },
            "unity_render": {
                (("session_id", "variant_id"), "variants", ("session_id", "variant_id")),
            },
        }
        for sheet_name, expected in expected_foreign_keys.items():
            sheet = get_sheet_contract(sheet_name)
            actual = {
                (foreign_key.columns, foreign_key.ref_sheet, foreign_key.ref_columns)
                for foreign_key in sheet.foreign_keys
            }
            self.assertTrue(expected.issubset(actual), f"{sheet_name} 缺少外键：{sorted(expected - actual)}")

    def test_pose_vectors_are_scalar_columns_not_json_cells(self) -> None:
        """姿态事实表不把 pose 数组序列化为 Excel JSON 单元格。"""

        pose_sheets = ("python_candidates", "unity_reference", "unity_admission", "unity_render")
        for sheet_name in pose_sheets:
            for column in get_sheet_contract(sheet_name).columns:
                is_pose_column = "_pos" in column.name or "_rot" in column.name or "pose_matrix_" in column.name
                if is_pose_column:
                    self.assertNotEqual(column.dtype, "json", f"{sheet_name}.{column.name}")

    def test_workbook_columns_have_chinese_descriptions_and_source_paths(self) -> None:
        """每列均声明中文含义和可审计来源路径，供 data dictionary 直接发布。"""

        for sheet in SHEET_CONTRACTS:
            for column in sheet.columns:
                self.assertRegex(column.description, r"[\u4e00-\u9fff]", f"{sheet.name}.{column.name}")
                self.assertTrue(column.source_path.strip(), f"{sheet.name}.{column.name}")

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
        metric_keys = [metric.key for metric in METRIC_DEFINITIONS]
        tex_suffixes = [metric.tex_suffix for metric in METRIC_DEFINITIONS]
        self.assertEqual(len(metric_keys), len(set(metric_keys)))
        self.assertEqual(len(tex_suffixes), len(set(tex_suffixes)))
        self.assertIn("jump_pninetynine_mm", metric_keys)
        self.assertIn("jump_pninetynine_deg", metric_keys)
        for metric in METRIC_DEFINITIONS:
            self.assertRegex(metric.tex_suffix, r"^[A-Za-z][A-Za-z]*$")
            self.assertTrue(set(metric.scenarios).issubset(set(SCENARIO_ORDER)), metric.key)
        self.assertEqual(len(metric_catalog()), len(METRIC_DEFINITIONS))

        with self.assertRaisesRegex(ValueError, "TeX 后缀"):
            replace(METRIC_DEFINITIONS[0], tex_suffix="中文后缀")

    def test_metric_source_columns_exist_in_workbook_v2(self) -> None:
        """每个指标来源必须是 ``sheet.column`` 且真实存在于 workbook-v2。"""

        for metric in METRIC_DEFINITIONS:
            self.assertTrue(metric.source_columns, metric.key)
            for source in metric.source_columns:
                self.assertRegex(source, r"^[a-z_]+\.[a-z0-9_]+$", f"{metric.key}: {source}")
                sheet_name, column_name = source.split(".", 1)
                columns = {column.name for column in get_sheet_contract(sheet_name).columns}
                self.assertIn(column_name, columns, f"{metric.key}: {source}")

    def test_task6_contract_versions_and_breaking_changes_are_recorded(self) -> None:
        """metrics 和 analysis_params v2 必须与 breaking changelog 同步。"""

        versions = {item.name: item.version for item in CONTRACT_VERSIONS}
        changes = {item.version: item for item in CONTRACT_CHANGELOG}

        self.assertGreaterEqual(versions["metrics"], 2)
        self.assertGreaterEqual(versions["analysis_params"], 2)
        self.assertTrue(changes["metrics-v2"].breaking)
        self.assertTrue(changes["analysis_params-v2"].breaking)

    def test_task7_contract_versions_and_guardrails_are_recorded(self) -> None:
        """Task 7 与 Task 8 修订后的 CSV、指标 breaking 版本必须完整记录。"""

        versions = {item.name: item.version for item in CONTRACT_VERSIONS}
        changes = {item.version: item for item in CONTRACT_CHANGELOG}
        metric_by_key = {metric.key: metric for metric in METRIC_DEFINITIONS}

        self.assertEqual(versions["csv"], 4)
        self.assertEqual(versions["metrics"], 5)
        self.assertEqual(versions["analysis_params"], 4)
        self.assertEqual(versions["analysis_workbook"], 1)
        self.assertTrue(changes["csv-v2"].breaking)
        self.assertTrue(changes["metrics-v3"].breaking)
        self.assertTrue(changes["csv-v3"].breaking)
        self.assertTrue(changes["metrics-v4"].breaking)
        self.assertTrue(changes["metrics-v5"].breaking)
        self.assertTrue(changes["analysis_params-v4"].breaking)
        self.assertEqual(versions["csv"], 4)
        self.assertTrue(changes["csv-v4"].breaking)
        expected_scenarios = {
            "start_stop_rotation_pninetyfive_deg": "start_stop_6dof",
            "motion_translation_peak_mm": "start_stop_6dof",
            "unlock_time_ms": "start_stop_6dof",
            "relock_time_ms": "start_stop_6dof",
            "translation_lag_residual_mm": "continuous_translation",
            "translation_lag_pninetyfive_residual_mm": "continuous_translation",
            "angular_lag_residual_deg": "continuous_rotation",
            "angular_lag_pninetyfive_residual_deg": "continuous_rotation",
            "post_stop_position_jitter_rms_mm": "start_stop_6dof",
            "motion_hold_ratio": "start_stop_6dof",
            "occlusion_output_coverage": "occlusion_recovery",
            "reappearance_translation_pninetyfive_mm": "occlusion_recovery",
            "occlusion_rotation_pninetyfive_deg": "occlusion_recovery",
            "occlusion_error_update_count": "occlusion_recovery",
            "fresh_output_time_ms": "occlusion_recovery",
        }
        for metric_key, scenario_id in expected_scenarios.items():
            self.assertIn(metric_key, metric_by_key)
            self.assertEqual(metric_by_key[metric_key].scenarios, (scenario_id,))

    def test_task8_csv_keys_cover_components_vcd_dimensions_and_sensitivity(self) -> None:
        """Task 8 长表主键必须容纳双静止消融、曲线维度和多个敏感性替代项。"""

        contracts = {table.name: table for table in CSV_TABLE_CONTRACTS}
        self.assertIn("component_id", contracts["paired_deltas"].primary_key)
        self.assertEqual(
            contracts["vcd_curve"].primary_key,
            ("scenario_id", "reference_kind", "risk_kind", "point_index"),
        )
        self.assertIn("alternative_id", contracts["sensitivity"].primary_key)
        risk_columns = {column.name for column in contracts["vcd_risk_points"].columns}
        self.assertTrue({"eligible", "exclusion_reason", "has_aligned_raw", "reference_pose_valid"}.issubset(risk_columns))
        metric_keys = {metric.key for metric in METRIC_DEFINITIONS}
        self.assertIn("vcd_mean_risk_aurc_mm", metric_keys)
        self.assertNotIn("vcd_tail_risk_aurc_mm", metric_keys)
        component_plot = contracts["exp2_component_deltas"]
        self.assertTrue(
            {"session_id", "scenario_id", "trial_id", "component_id"}.issubset(
                component_plot.primary_key
            )
        )
        curve_plot = contracts["exp2_vcd_curve"]
        self.assertTrue(
            {"reference_kind", "risk_kind", "point_index"}.issubset(curve_plot.primary_key)
        )

    def test_exp1_behavior_plot_contracts_replace_old_event_plot_tables(self) -> None:
        """实验一四面板必须使用专用 plot-ready 表，不保留旧三图契约。"""

        contracts = {table.name: table for table in CSV_TABLE_CONTRACTS}
        for table_name in (
            "exp1_head_motion_trace",
            "exp1_start_stop_trace",
            "exp1_lag_tradeoff",
            "exp1_occlusion_trace",
        ):
            self.assertIn(table_name, contracts)
            self.assertIn("plot_id", contracts[table_name].primary_key)
            self.assertIn("panel_id", contracts[table_name].primary_key)
        self.assertNotIn("exp1_static_timeline", contracts)
        self.assertNotIn("exp1_motion_events", contracts)
        self.assertNotIn("exp1_occlusion_events", contracts)

    def test_analysis_params_are_valid_and_parameter_lines_have_comments(self) -> None:
        """TOML 可解析，且每个参数赋值行都有中文同行注释。"""

        config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertIn("contract", config)
        self.assertIn("metrics", config)
        self.assertIn("thresholds", config)
        self.assertEqual(config["contract"]["version"], 4)

        assignment_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=")
        for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
            if assignment_pattern.match(line.strip()):
                self.assertIn("#", line, line)
                self.assertRegex(line, r"#.*[\u4e00-\u9fff]", line)


if __name__ == "__main__":
    unittest.main()
