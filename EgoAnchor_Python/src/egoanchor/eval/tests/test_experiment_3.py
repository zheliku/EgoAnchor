"""实验三正式模板、统计与完整构建产物测试。"""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from dataclasses import replace
from datetime import time
from pathlib import Path
from shutil import copyfile
from typing import Any

from openpyxl import load_workbook  # type: ignore[import-untyped]
from PIL import Image

from egoanchor.eval import cli as eval_cli
from egoanchor.eval.experiments.experiment_3 import (
    ExperimentPaths,
    SettingsSnapshot,
    build_raw_template,
    load_settings,
    load_settings_snapshot,
    plan_assets,
    validate_workflow,
)
from egoanchor.eval.experiments.experiment_3.analysis import (
    MAIN_FAMILY,
    SCALE_FAMILY,
    analyze_scores,
    build_analysis,
    derive_scores,
    publish_figures,
    read_workbook,
    validate_for_analysis,
    write_results_workbook,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
"""包含论文目录与 Python 工程的仓库根目录。"""

RAW_WORKBOOK = (
    REPOSITORY_ROOT
    / "2026-EgoAnchor"
    / "material"
    / "EgoAnchor_Experiment3_RawData_24P_v5_1.xlsx"
)
"""用于结构、质量校验和完整构建回归测试的 v5.1 原始工作簿。"""

PAPER_CONFIG = (
    REPOSITORY_ROOT
    / "EgoAnchor_Python"
    / "src"
    / "egoanchor"
    / "eval"
    / "config"
    / "paper.toml"
)
"""受版本控制的实验三科学参数配置。"""


class Experiment3Tests(unittest.TestCase):
    """验证空白模板、实时公式边界和离线结果链。"""

    def test_settings_freeze_paper_thresholds(self) -> None:
        """发布阈值与 95% CI 口径不可漂移。"""

        settings = load_settings()
        self.assertEqual(settings.alpha, 0.05)
        self.assertEqual(settings.confidence_level, 0.95)
        self.assertEqual(settings.target_participants, 24)
        self.assertEqual(settings.minimum_participants, 18)
        source = PAPER_CONFIG.read_text(encoding="utf-8")
        cases = (
            ("alpha", "alpha = 0.05", "alpha = 0.04", "冻结 alpha=0.05"),
            (
                "confidence",
                "confidence_level = 0.95",
                "confidence_level = 0.90",
                "冻结 confidence_level=0.95",
            ),
            (
                "target",
                "target_participants = 24",
                "target_participants = 23",
                "冻结 target_participants=24",
            ),
            (
                "minimum",
                "minimum_participants = 18",
                "minimum_participants = 1",
                "冻结 minimum_participants=18",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            for name, original, replacement, error in cases:
                with self.subTest(parameter=name):
                    config = Path(directory) / f"{name}.toml"
                    config.write_text(source.replace(original, replacement, 1), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, error):
                        load_settings(config)

    def test_settings_reject_wrong_types_nonfinite_values_and_mutation(self) -> None:
        """科学参数拒绝隐式类型转换、NaN/Inf 和冻结对象内部修改。"""

        settings = load_settings()
        with self.assertRaises(TypeError):
            settings.equivalence_margins["Candidate_Rate_Hz"] = 1.0  # type: ignore[index]
        source = PAPER_CONFIG.read_text(encoding="utf-8")
        cases = (
            (
                "bool_string",
                "q10_enabled = false",
                'q10_enabled = "false"',
                "q10_enabled 必须是 bool",
            ),
            (
                "float_as_int",
                "minimum_participants = 18",
                "minimum_participants = 18.9",
                "minimum_participants 必须是 int",
            ),
            (
                "bool_as_int",
                "[experiment_3.contract]\nversion = 4",
                "[experiment_3.contract]\nversion = true",
                "version 必须是 int",
            ),
            (
                "int_as_float",
                "alpha = 0.05",
                "alpha = 1",
                "alpha 必须是 float",
            ),
            (
                "infinite_margin",
                "candidate_rate_margin_hz = 0.0",
                "candidate_rate_margin_hz = inf",
                "candidate_rate_margin_hz 必须是有限浮点数",
            ),
            (
                "nan_figure",
                "primary_width_inches = 7.15",
                "primary_width_inches = nan",
                "primary_width_inches 必须是有限浮点数",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            for name, original, replacement, error in cases:
                with self.subTest(parameter=name):
                    config = Path(directory) / f"{name}.toml"
                    config.write_text(source.replace(original, replacement, 1), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, error):
                        load_settings(config)

    def test_settings_snapshot_binds_values_and_digest_to_one_document(self) -> None:
        """配置快照取得后不受磁盘后续保存影响，新快照反映新版本。"""

        source = PAPER_CONFIG.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "paper.toml"
            config.write_text(source, encoding="utf-8")
            first = load_settings_snapshot(config)
            config.write_text(
                source.replace("bootstrap_iterations = 10000", "bootstrap_iterations = 10001", 1),
                encoding="utf-8",
            )
            second = load_settings_snapshot(config)
        self.assertEqual(first.settings.bootstrap_iterations, 10000)
        self.assertEqual(second.settings.bootstrap_iterations, 10001)
        self.assertNotEqual(first.sha256, second.sha256)

    def test_raw_template_is_empty_and_keeps_live_formulas_outside_raw_regions(self) -> None:
        """模板只保留设计映射，原始值区为空且公式仅位于派生表。"""

        settings = load_settings()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "experiment3_raw.xlsx"
            build_raw_template(settings, output)
            data = read_workbook(output)
            self.assertEqual(len(data.blocks), 144)
            workbook = load_workbook(output, data_only=False)
            try:
                raw_regions = (
                    ("Participants", range(3, 27), range(12, 25)),
                    ("Records", range(5, 149), range(11, 42)),
                    ("Records", range(152, 200), range(5, 26)),
                    ("Records", range(203, 227), range(2, 12)),
                )
                for sheet_name, rows, columns in raw_regions:
                    with self.subTest(sheet=sheet_name, first_row=rows.start):
                        self.assertFalse(
                            any(
                                workbook[sheet_name].cell(row, column).value is not None
                                for row in rows
                                for column in columns
                            )
                        )
                self.assertEqual(workbook["Records"]["X151"].value, "A/B归属回忆确认")
                self.assertEqual(workbook["Records"]["Y151"].value, "方法级记录有效")
                self.assertTrue(str(workbook["Derived"]["E5"].value).startswith("=IF(AND(COUNTIFS"))
                self.assertEqual(workbook["Derived"]["A307"].value[:2], "D6")
                self.assertIn("Session_Duration_Min", str(workbook["Derived"]["M308"].value))
                self.assertEqual(workbook["Derived"]["Y308"].value, "Discomfort_Change")
                self.assertEqual(workbook["Derived"]["Z308"].value, "Audit_Status")
                self.assertIn("Participants!L3:X3", str(workbook["Derived"]["Z309"].value))
                self.assertEqual(workbook["Derived"]["A334"].value[:2], "D7")
                self.assertEqual(workbook["Derived"]["B336"].value, "blue_mouse")
                self.assertEqual(workbook["Derived"]["B360"].value, "stapler")
                self.assertEqual(workbook["Derived"]["B384"].value, "gamepad")
                self.assertIn("COUNTIFS", str(workbook["Derived"]["C336"].value))
                self.assertIn("AVERAGEIFS", str(workbook["Derived"]["D336"].value))
                self.assertIn("AVERAGEIFS", str(workbook["Derived"]["E336"].value))
                self.assertEqual(
                    workbook["Derived"]["F336"].value,
                    '=IF(OR(D336="",E336=""),"",E336-D336)',
                )
                self.assertEqual(workbook["Analysis"]["A19"].value[:2], "B1")
                self.assertEqual(workbook["Analysis"]["A25"].value[:2], "B2")
                self.assertEqual(workbook["Analysis"]["A58"].value[:2], "B3")
                self.assertEqual(workbook["Analysis"]["A75"].value[:2], "C1")
                self.assertEqual(workbook["Analysis"]["A86"].value[:2], "C2")
                self.assertEqual(workbook["Analysis"]["A88"].value, "Q1")
                self.assertEqual(workbook["Analysis"]["C88"].value, "Mouse")
                self.assertIn(
                    "QUARTILE(Derived!$D$336:$D$359,1)",
                    str(workbook["Analysis"]["E88"].value),
                )
                self.assertEqual(workbook["Analysis"]["A108"].value, "Q7")
                self.assertEqual(workbook["Analysis"]["C108"].value, "Gamepad")
                self.assertEqual(workbook["Analysis"]["A111"].value[:1], "D")
                self.assertEqual(workbook["Analysis"]["A120"].value[:1], "E")
                self.assertEqual(workbook["Analysis"]["A129"].value[:1], "F")
                analysis_formulas = (
                    str(cell.value)
                    for row in workbook["Analysis"].iter_rows()
                    for cell in row
                    if cell.data_type == "f"
                )
                formula_text = "\n".join(analysis_formulas)
                self.assertEqual(formula_text.count("QUARTILE("), 140)
                self.assertNotIn("QUARTILE.INC", formula_text)
                self.assertIn("QUARTILE(Derived!G309:G332,1)", formula_text)
                self.assertEqual(workbook["Analysis"]["A56"].value, "Discomfort_Change")
                self.assertEqual(workbook["Analysis"]["E59"].value, "Expected_at_Actual_N")
                self.assertIn("FILTER", str(workbook["Analysis"]["D77"].value))
                self.assertTrue(workbook.calculation.fullCalcOnLoad)
                self.assertTrue(workbook.calculation.forceFullCalc)
                self.assertEqual(workbook.properties.identifier, "EgoAnchor.Experiment3.RawData.v5.1")
                self.assertEqual(workbook.properties.category, "experiment-3-raw-workbook")
                self.assertEqual(workbook["README"]["B27"].value, "EgoAnchor.Experiment3.RawData.v5.1")
                self.assertEqual(workbook["README"]["B28"].value, "experiment-3-raw-workbook")
                self.assertEqual((workbook["Derived"].max_row, workbook["Derived"].max_column), (407, 26))
                self.assertEqual((workbook["Analysis"].max_row, workbook["Analysis"].max_column), (132, 20))
                self.assertEqual(workbook["Analysis"].auto_filter.ref, "A76:T83")
                self.assertFalse(any("78" in str(item) for item in workbook["Analysis"].merged_cells.ranges))
                self.assertTrue(workbook["Derived"].protection.sheet)
                self.assertTrue(workbook["Analysis"].protection.sheet)
                participant_validations = {
                    str(validation.sqref)
                    for validation in workbook["Participants"].data_validations.dataValidation
                }
                record_validations = {
                    str(validation.sqref)
                    for validation in workbook["Records"].data_validations.dataValidation
                }
                self.assertIn("W3:W26", participant_validations)
                self.assertIn("H203:H226", record_validations)
                self.assertIn("AF5:AF148", record_validations)
                for sheet_name in ("Participants", "Records"):
                    self.assertFalse(
                        any(
                            cell.data_type == "f"
                            for row in workbook[sheet_name].iter_rows()
                            for cell in row
                        )
                    )
                self.assertFalse(
                    any(
                        "#REF!" in str(cell.value).upper()
                        for worksheet in workbook.worksheets
                        for row in worksheet.iter_rows()
                        for cell in row
                    )
                )
            finally:
                workbook.close()
            with self.assertRaises(FileExistsError):
                build_raw_template(settings, output)

    def test_reduced_aq_mode_updates_excel_and_python_contract_together(self) -> None:
        """AQ 缩减模式同时移除 EQ3/IQ1，并把有效区块门槛改为 11 项。"""

        settings = replace(load_settings(), aq_mode="reduced")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "experiment3_reduced.xlsx"
            build_raw_template(settings, output)
            workbook = load_workbook(output, data_only=False)
            try:
                eq_formula = str(workbook["Derived"]["M5"].value)
                iq_formula = str(workbook["Derived"]["N5"].value)
                valid_formula = str(workbook["Derived"]["E5"].value)
                self.assertIn("Records!S5,Records!T5", eq_formula)
                self.assertNotIn("Records!U5", eq_formula)
                self.assertIn("Records!O5,Records!P5", iq_formula)
                self.assertNotIn("Records!V5", iq_formula)
                self.assertIn("=11", valid_formula)
            finally:
                workbook.close()

    def test_reader_rejects_workbook_changed_while_parsing_snapshot(self) -> None:
        """工作簿若在快照解析期间被替换，结果和清单不得绑定到不同版本。"""

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "changing.xlsx"
            copyfile(RAW_WORKBOOK, source)

            def load_then_replace(stream: Any, *args: Any, **kwargs: Any) -> Any:
                """先从内存快照建好工作簿对象，再模拟 Excel 保存覆盖路径。"""

                workbook = load_workbook(stream, *args, **kwargs)
                source.write_bytes(b"workbook changed during read")
                return workbook

            with (
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.analysis.reader.load_workbook",
                    side_effect=load_then_replace,
                ),
                self.assertRaisesRegex(ValueError, "读取期间发生变化"),
            ):
                read_workbook(source)

    def test_reader_enforces_frozen_balance_design_and_v51_method_audits(self) -> None:
        """排列编号、实际平衡单元和 v5.1 方法审核列都属于硬契约。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            fractional = root / "fractional_order.xlsx"
            copyfile(RAW_WORKBOOK, fractional)
            workbook = load_workbook(fractional)
            try:
                for row in range(23, 27):
                    workbook["Participants"].cell(row, 3, 6.5)
                workbook.save(fractional)
            finally:
                workbook.close()
            with self.assertRaisesRegex(ValueError, "物体排列ID必须是 1--6 整数"):
                read_workbook(fractional)

            remapped = root / "remapped_order.xlsx"
            copyfile(RAW_WORKBOOK, remapped)
            workbook = load_workbook(remapped)
            try:
                participants = workbook["Participants"]
                for row in range(3, 7):
                    participants.cell(row, 6, "游戏手柄")
                    participants.cell(row, 7, "固定订书机")
                records = workbook["Records"]
                for row in range(5, 29):
                    object_position = records.cell(row, 4).value
                    if object_position == 2:
                        records.cell(row, 5, "游戏手柄")
                        records.cell(row, 6, "gamepad")
                    elif object_position == 3:
                        records.cell(row, 5, "固定订书机")
                        records.cell(row, 6, "stapler")
                workbook.save(remapped)
            finally:
                workbook.close()
            with self.assertRaisesRegex(ValueError, "未绑定冻结的物体1--3顺序"):
                read_workbook(remapped)

            wrong_unit = root / "wrong_balance_unit.xlsx"
            copyfile(RAW_WORKBOOK, wrong_unit)
            workbook = load_workbook(wrong_unit)
            try:
                workbook["Records"]["C5"] = "O6-S2-OE"
                workbook.save(wrong_unit)
            finally:
                workbook.close()
            with self.assertRaisesRegex(ValueError, "平衡单元=.*期望"):
                read_workbook(wrong_unit)

            legacy_method_audit = root / "legacy_method_audit.xlsx"
            copyfile(RAW_WORKBOOK, legacy_method_audit)
            workbook = load_workbook(legacy_method_audit)
            try:
                workbook["Records"]["X151"] = "旧版可选回忆字段"
                workbook.save(legacy_method_audit)
            finally:
                workbook.close()
            with self.assertRaisesRegex(ValueError, "A/B归属回忆确认"):
                read_workbook(legacy_method_audit)

    def test_build_requires_minimum_complete_pairs_for_every_frozen_outcome(self) -> None:
        """总纳入 N 足够时，任一冻结结局配对 N 不足仍必须拒绝发布。"""

        settings = replace(load_settings(), bootstrap_iterations=1000)
        source = RAW_WORKBOOK.resolve()
        data = read_workbook(source)
        methods = data.methods.copy()
        participant_ids = sorted(methods["Participant_ID"].astype(str).unique())
        insufficient_ids = set(participant_ids[1:])
        rc_items = (
            "TIA_RC1",
            "TIA_RC2",
            "TIA_RC3_REV",
            "TIA_RC4",
            "TIA_RC5_REV",
            "TIA_RC6",
        )
        mask = methods["Participant_ID"].astype(str).isin(insufficient_ids)
        for item in rc_items:
            methods[item] = methods[item].astype(object)
        methods.loc[mask, list(rc_items)] = "无法回答"
        data = replace(data, methods=methods)
        python_root = REPOSITORY_ROOT / "EgoAnchor_Python"
        with tempfile.TemporaryDirectory(dir=python_root / "data") as directory:
            paths = ExperimentPaths(
                project_root=python_root,
                source_template=source,
                input_workbook=source,
                analysis_root=Path(directory) / "analysis",
                paper_root=Path(directory) / "paper",
                figure_destination=Path(directory) / "paper" / "figures",
                table_destination=Path(directory) / "paper" / "tables" / "exp3_subjective.tex",
                batch_config_path=Path(directory) / "batch.toml",
            )
            with (
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.load_paths",
                    return_value=paths,
                ),
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.load_settings_snapshot",
                    return_value=SettingsSnapshot(settings=settings, sha256="0" * 64),
                ),
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.read_workbook",
                    return_value=data,
                ),
                self.assertRaisesRegex(ValueError, r"TIA_RC N=1"),
            ):
                validate_workflow()

            analysis_root = Path(directory) / "analysis"
            analysis_root.mkdir()
            marker = analysis_root / "previous_complete.txt"
            marker.write_text("旧构建必须保留", encoding="utf-8")
            with (
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.analysis.pipeline.read_workbook",
                    return_value=data,
                ),
                self.assertRaisesRegex(ValueError, r"TIA_RC N=1"),
            ):
                build_analysis(
                    settings,
                    input_workbook=source,
                    output_root=analysis_root,
                    project_root=python_root,
                    config_sha256="0" * 64,
                    batch_config_path=Path(directory) / "batch.toml",
                    paper_config_path=Path(directory) / "paper.toml",
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "旧构建必须保留")
            self.assertFalse(tuple(analysis_root.parent.glob(".analysis.build-*")))

    def test_failed_staged_publish_preserves_previous_analysis_tree(self) -> None:
        """写图或写表失败时只清理 staging，上一轮分析目录保持不变。"""

        settings = replace(load_settings(), bootstrap_iterations=1000)
        source = RAW_WORKBOOK.resolve()
        data = read_workbook(source)
        python_root = REPOSITORY_ROOT / "EgoAnchor_Python"
        with tempfile.TemporaryDirectory(dir=python_root / "data") as directory:
            analysis_root = Path(directory) / "analysis"
            analysis_root.mkdir()
            marker = analysis_root / "previous_complete.txt"
            marker.write_bytes(b"previous complete analysis")
            with (
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.analysis.pipeline.read_workbook",
                    return_value=data,
                ),
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.analysis.pipeline.write_subjective_table",
                    side_effect=RuntimeError("simulated TeX failure"),
                ),
                self.assertRaisesRegex(RuntimeError, "simulated TeX failure"),
            ):
                build_analysis(
                    settings,
                    input_workbook=source,
                    output_root=analysis_root,
                    project_root=python_root,
                    config_sha256="0" * 64,
                    batch_config_path=Path(directory) / "batch.toml",
                    paper_config_path=Path(directory) / "paper.toml",
                )
            self.assertEqual(marker.read_bytes(), b"previous complete analysis")
            self.assertEqual({path.name for path in analysis_root.iterdir()}, {marker.name})
            self.assertFalse(tuple(analysis_root.parent.glob(".analysis.build-*")))

    def test_complete_build_plans_both_figures_and_subjective_table(self) -> None:
        """完整构建按固定名称生成两张正文图与完整结果表。"""

        settings = replace(load_settings(), bootstrap_iterations=1000)
        source = RAW_WORKBOOK.resolve()
        data = read_workbook(source)
        python_root = REPOSITORY_ROOT / "EgoAnchor_Python"
        with tempfile.TemporaryDirectory(dir=python_root / "data") as directory:
            sandbox = Path(directory)
            analysis_root = sandbox / "analysis"
            with mock.patch(
                "egoanchor.eval.experiments.experiment_3.analysis.pipeline.read_workbook",
                return_value=data,
            ):
                payload = build_analysis(
                    settings,
                    input_workbook=source,
                    output_root=analysis_root,
                    project_root=python_root,
                    config_sha256="0" * 64,
                    batch_config_path=sandbox / "batch.toml",
                    paper_config_path=sandbox / "paper.toml",
                )
            self.assertEqual(payload["build"]["details"]["included_count"], 24)
            self.assertTrue(
                (analysis_root / "results" / "experiment3_analysis.xlsx").is_file()
            )
            self.assertTrue((analysis_root / "tex" / "exp3_subjective.tex").is_file())

            paths = ExperimentPaths(
                project_root=python_root,
                source_template=source,
                input_workbook=source,
                analysis_root=analysis_root,
                paper_root=sandbox / "paper",
                figure_destination=sandbox / "paper" / "figures",
                table_destination=sandbox / "paper" / "tables" / "exp3_subjective.tex",
                batch_config_path=sandbox / "batch.toml",
            )
            with (
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.load_paths",
                    return_value=paths,
                ),
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.load_settings_snapshot",
                    return_value=SettingsSnapshot(settings=settings, sha256="0" * 64),
                ),
            ):
                plan = plan_assets()
            self.assertEqual(
                {asset.key for asset in plan.assets},
                {
                    "figure4_png",
                    "figure4_pdf",
                    "figure5_png",
                    "figure5_pdf",
                    "subjective_table",
                },
            )

    def test_results_workbook_and_figures_share_one_analysis_object(self) -> None:
        """结果 XLSX 可回读绘图，并同时生成非空 PNG/PDF。"""

        settings = replace(load_settings(), bootstrap_iterations=1000)
        data = read_workbook(RAW_WORKBOOK)
        validation = validate_for_analysis(
            data,
            aq_mode=settings.aq_mode,
            q10_enabled=settings.q10_enabled,
        )
        scores = derive_scores(data, settings)
        tables = analyze_scores(data, scores, settings)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = write_results_workbook(
                root / "experiment3_analysis.xlsx",
                data=data,
                tables=tables,
                settings=settings,
                settings_sha256="0" * 64,
                batch_config_path=root / "batch.toml",
                paper_config_path=root / "paper.toml",
                validation=validation,
            )
            figures = publish_figures(
                scores,
                tables,
                root,
                settings,
            )
            workbook = load_workbook(results, read_only=True, data_only=True)
            try:
                self.assertEqual(
                    workbook.sheetnames,
                    [
                        "说明", "样本与质控", "主结果", "分物体描述", "量表信度", "选择结果",
                    ],
                )
                self.assertEqual(workbook["主结果"].max_row, 16)
                self.assertEqual(workbook["分物体描述"].max_row, 25)
                object_headers = [
                    workbook["分物体描述"].cell(4, column).value
                    for column in range(1, workbook["分物体描述"].max_column + 1)
                ]
                self.assertFalse(any("p" in str(value).lower() for value in object_headers))
                self.assertIn("配对差中位数 [Q1, Q3]", object_headers)
            finally:
                workbook.close()
            self.assertGreater(results.stat().st_size, 20_000)
            self.assertEqual(
                set(figures),
                {"figure4_png", "figure4_pdf", "figure5_png", "figure5_pdf"},
            )
            for path in figures.values():
                self.assertGreater(path.stat().st_size, 10_000)
            expected_sizes = {
                "figure4_png": tuple(
                    round(value * settings.figure_dpi)
                    for value in settings.primary_figure_size
                ),
                "figure5_png": tuple(
                    round(value * settings.figure_dpi)
                    for value in settings.scale_figure_size
                ),
            }
            for key, expected_size in expected_sizes.items():
                with Image.open(figures[key]) as image:
                    self.assertEqual(image.size, expected_size)

            bad_paired = scores.paired_scores.copy()
            bad_paired.at[bad_paired.index[0], "Difference"] += 0.25
            with self.assertRaisesRegex(ValueError, "配对差不等于"):
                publish_figures(
                    replace(scores, paired_scores=bad_paired),
                    tables,
                    root / "bad_difference",
                    settings,
                )

            bad_results = tables.results.copy()
            bad_results.at[bad_results.index[0], "p_Holm"] = 1.5
            with self.assertRaisesRegex(ValueError, "p_Holm 必须位于"):
                publish_figures(
                    scores,
                    replace(tables, results=bad_results),
                    root / "bad_p",
                    settings,
                )

            bad_n = tables.results.copy()
            bad_n.at[bad_n.index[0], "N"] = int(bad_n.at[bad_n.index[0], "N"]) - 1
            with self.assertRaisesRegex(ValueError, "N 与绘图配对人数不一致"):
                publish_figures(
                    scores,
                    replace(tables, results=bad_n),
                    root / "bad_n",
                    settings,
                )

    def test_formal_participant_summary_reports_demographics_duration_and_balance(self) -> None:
        """正式分析严格校验背景字段，并以纳入 N 为分母汇总。"""

        settings = replace(load_settings(), bootstrap_iterations=1000)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "formal_participants.xlsx"
            copyfile(RAW_WORKBOOK, source)
            workbook = load_workbook(source)
            try:
                workbook.properties.identifier = "EgoAnchor.Experiment3.RawData.v5.1"
                workbook.properties.category = "formal-participant-data"
                participants = workbook["Participants"]
                gender = ("女", "男")
                handedness = ("右手", "左手", "双手均可")
                vision = ("正常", "矫正后正常", "其他")
                vrmr = ("从未", "1–5 次", "6–20 次", "超过 20 次", "经常使用")
                physical = ("从未", "1–2 次", "数次", "经常")
                for index, row in enumerate(range(3, 27)):
                    values = (
                        20 + index,
                        gender[index % len(gender)],
                        handedness[index % len(handedness)],
                        vision[index % len(vision)],
                        vrmr[index % len(vrmr)],
                        physical[index % len(physical)],
                        "是",
                        "无",
                        time(9, 0),
                        time(10, 0),
                        "是",
                        "",
                    )
                    for column, value in enumerate(values, start=12):
                        participants.cell(row, column, value)
                finals = workbook["Records"]
                for row in range(152, 200):
                    for column in range(5, 15):
                        if finals.cell(row, column).value is None:
                            finals.cell(row, column, "无法回答")
                for row in range(203, 227):
                    finals.cell(row, 6, "存在可感知差异")
                    finals.cell(row, 7, "跳变会降低信任")
                    finals.cell(row, 8, "无")
                workbook.save(source)
            finally:
                workbook.close()

            data = read_workbook(source)
            validation = validate_for_analysis(
                data,
                aq_mode=settings.aq_mode,
                q10_enabled=settings.q10_enabled,
            )
            scores = derive_scores(data, settings)
            tables = analyze_scores(data, scores, settings)
            summary = tables.sample
            age = summary[summary["Variable"] == "Age"].iloc[0]
            duration = summary[summary["Variable"] == "Session_Duration_Minutes"].iloc[0]
            women = summary[
                (summary["Variable"] == "Gender") & (summary["Category"] == "女")
            ].iloc[0]
            worsened = summary[
                (summary["Variable"] == "Discomfort_Change")
                & (summary["Category"] == "Worsened")
            ].iloc[0]
            self.assertEqual(validation["included_count"], 24)
            self.assertAlmostEqual(float(age["Mean"]), 31.5)
            self.assertEqual(int(age["N"]), 24)
            self.assertEqual(int(age["Denominator"]), 24)
            self.assertAlmostEqual(float(duration["Median"]), 60.0)
            self.assertEqual(int(women["N"]), 12)
            self.assertAlmostEqual(float(women["Proportion"]), 0.5)
            self.assertEqual(int(worsened["N"]), 0)
            self.assertTrue(
                (summary[summary["Section"] == "Design_Balance"]["Status"] == "balanced").all()
            )

            valid_source = Path(directory) / "formal_valid.xlsx"
            copyfile(source, valid_source)

            def edited_case(name: str, edits: tuple[tuple[str, str, object], ...]) -> Path:
                """从同一有效基线制作单一篡改用例。"""

                case = Path(directory) / f"{name}.xlsx"
                copyfile(valid_source, case)
                case_workbook = load_workbook(case)
                try:
                    for sheet, cell, value in edits:
                        case_workbook[sheet][cell] = value
                    case_workbook.save(case)
                finally:
                    case_workbook.close()
                return case

            invalid_baseline = edited_case(
                "invalid_baseline",
                (("Participants", "S3", "严重"),),
            )
            with self.assertRaisesRegex(ValueError, "基线不适"):
                validate_for_analysis(
                    read_workbook(invalid_baseline),
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                )

            pending = edited_case("pending", (("Participants", "V3", None),))
            with self.assertRaisesRegex(ValueError, "明确标记纳入或排除"):
                validate_for_analysis(
                    read_workbook(pending),
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                )

            no_consent = edited_case("no_consent", (("Participants", "R3", None),))
            with self.assertRaisesRegex(ValueError, "先明确签署同意"):
                validate_for_analysis(
                    read_workbook(no_consent),
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                )

            missing_runtime = edited_case("missing_runtime", (("Records", "AF5", None),))
            with self.assertRaisesRegex(ValueError, "Candidate_Rate_Hz"):
                validate_for_analysis(
                    read_workbook(missing_runtime),
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                )

            invalid_method = edited_case("invalid_method", (("Records", "V152", "设备故障"),))
            with self.assertRaisesRegex(ValueError, "技术状态"):
                validate_for_analysis(
                    read_workbook(invalid_method),
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                )

            invalid_safety = edited_case(
                "invalid_safety",
                (
                    ("Participants", "V3", "否"),
                    ("Participants", "W3", "设备故障"),
                    ("Records", "H203", "严重"),
                ),
            )
            with self.assertRaisesRegex(ValueError, "结束不适"):
                validate_for_analysis(
                    read_workbook(invalid_safety),
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                )

            invalid_mapping = edited_case("invalid_mapping", (("Records", "C152", "方法B"),))
            with self.assertRaisesRegex(ValueError, "评分顺序"):
                read_workbook(invalid_mapping)

            invalid_block_order = edited_case(
                "invalid_block_order",
                (
                    ("Records", "B5", 2),
                    ("Records", "B6", 1),
                ),
            )
            with self.assertRaisesRegex(ValueError, "实际区块顺序与 Participants 计划不一致"):
                read_workbook(invalid_block_order)

    def test_cli_exposes_experiment3_as_analyze_target(self) -> None:
        """实验三与实验一/二共享 analyze 生命周期，不再另设 plot。"""

        parser = eval_cli.build_parser()
        args = parser.parse_args(["analyze", "exp3"])
        self.assertEqual(args.target, "exp3")
        self.assertIs(args.handler, eval_cli._run_analyze)

if __name__ == "__main__":
    unittest.main()
