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

from egoanchor.eval import cli as eval_cli
from egoanchor.eval.experiments.experiment_3 import (
    ExperimentPaths,
    analyze_workflow,
    build_raw_template,
    describe_workflow,
    load_settings,
    plan_assets,
    validate_workflow,
)
from egoanchor.eval.experiments.experiment_3.analysis import (
    Exp3Data,
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

R2_WORKBOOK = (
    REPOSITORY_ROOT
    / "2026-EgoAnchor"
    / "material"
    / "reference"
    / "EgoAnchor_Experiment3_Simulated_Claude-Opus-5-1M_R2_v5_1_24P.xlsx"
)
"""只用于测试分析契约的冻结结构模拟工作簿。"""

GPT_WORKBOOK = (
    REPOSITORY_ROOT
    / "2026-EgoAnchor"
    / "material"
    / "reference"
    / "GPT-5.6-Thinking_v3_AnalysisFilled_VSCodeSafe.xlsx"
)
"""已逐格审计并冻结的 GPT 合成响应参考。"""

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

    def test_settings_freeze_paper_thresholds_and_start_without_approved_source(self) -> None:
        """发布阈值与 95% CI 口径不可漂移，真实采集前批准列表为空。"""

        settings = load_settings()
        self.assertEqual(settings.alpha, 0.05)
        self.assertEqual(settings.confidence_level, 0.95)
        self.assertEqual(settings.approved_response_fingerprints, frozenset())
        source = PAPER_CONFIG.read_text(encoding="utf-8")
        cases = (
            ("alpha", "alpha = 0.05", "alpha = 0.04", "冻结 alpha=0.05"),
            (
                "confidence",
                "confidence_level = 0.95",
                "confidence_level = 0.90",
                "冻结 confidence_level=0.95",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            for name, original, replacement, error in cases:
                with self.subTest(parameter=name):
                    config = Path(directory) / f"{name}.toml"
                    config.write_text(source.replace(original, replacement, 1), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, error):
                        load_settings(config)

    def test_raw_template_is_empty_and_keeps_live_formulas_outside_raw_regions(self) -> None:
        """模板只保留设计映射，原始值区为空且公式仅位于派生表。"""

        settings = load_settings()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "experiment3_raw.xlsx"
            build_raw_template(settings, output)
            data = read_workbook(output)
            self.assertEqual(data.source_kind, "formal")
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
                self.assertEqual(workbook.properties.category, "formal-participant-data")
                self.assertEqual(workbook["README"]["B27"].value, "EgoAnchor.Experiment3.RawData.v5.1")
                self.assertEqual(workbook["README"]["B28"].value, "formal-participant-data")
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

    def test_source_gate_fingerprints_only_audited_core_responses(self) -> None:
        """非核心日志和备注不能绕过门禁，核心评分变化必须改变指纹。"""

        settings = load_settings()

        def validate(
            data: Exp3Data,
            approvals: frozenset[str] | None = None,
        ) -> dict[str, Any]:
            """按正式分析入口返回一份已读取数据的来源门禁结果。"""

            return validate_for_analysis(
                data,
                minimum_participants=settings.minimum_participants,
                aq_mode=settings.aq_mode,
                q10_enabled=settings.q10_enabled,
                approved_response_fingerprints=(
                    settings.approved_response_fingerprints
                    if approvals is None
                    else approvals
                ),
            )

        audited_fingerprint = "5993ef77a827eb89c99fb9c1db85f29ae09d1a2f423f88f2713b6fa3789fe84a"
        data = replace(read_workbook(GPT_WORKBOOK), source_kind="formal")
        baseline = validate(data, frozenset({audited_fingerprint}))
        self.assertEqual(baseline["response_fingerprint"], audited_fingerprint)
        self.assertFalse(baseline["paper_eligible"])
        self.assertIn("已知 GPT 合成参考", baseline["source_gate_reason"])

        noncore_blocks = data.blocks.copy()
        noncore_methods = data.methods.copy()
        noncore_finals = data.finals.copy()
        noncore_blocks.at[0, "Candidate_Rate_Hz"] = (
            float(noncore_blocks.at[0, "Candidate_Rate_Hz"]) + 0.125
        )
        noncore_blocks.at[0, "备注"] = "仅修改区块运行时备注"
        noncore_methods.at[0, "备注"] = "仅修改方法级备注"
        noncore_finals.at[0, "访谈备注"] = "仅修改最终访谈备注"
        noncore_result = validate(
            replace(
                data,
                blocks=noncore_blocks,
                methods=noncore_methods,
                finals=noncore_finals,
            ),
            frozenset({audited_fingerprint}),
        )
        self.assertEqual(noncore_result["response_fingerprint"], audited_fingerprint)
        self.assertFalse(noncore_result["paper_eligible"])

        reordered_result = validate(
            replace(
                data,
                blocks=data.blocks.sample(frac=1.0, random_state=11).reset_index(drop=True),
                methods=data.methods.sample(frac=1.0, random_state=12).reset_index(drop=True),
                finals=data.finals.sample(frac=1.0, random_state=13).reset_index(drop=True),
            ),
            frozenset({audited_fingerprint}),
        )
        self.assertEqual(reordered_result["response_fingerprint"], audited_fingerprint)
        self.assertFalse(reordered_result["paper_eligible"])

        core_blocks = data.blocks.copy()
        core_blocks.at[0, "Q1"] = 2 if core_blocks.at[0, "Q1"] == 1 else 1
        changed_data = replace(data, blocks=core_blocks)
        unapproved = validate(changed_data)
        changed_fingerprint = unapproved["response_fingerprint"]
        self.assertNotEqual(changed_fingerprint, audited_fingerprint)
        self.assertFalse(unapproved["paper_eligible"])
        self.assertIn("尚未经来源核验", unapproved["source_gate_reason"])

        approved = validate(changed_data, frozenset({changed_fingerprint}))
        self.assertTrue(approved["paper_eligible"])
        self.assertEqual(approved["warnings"], ())

        approved_reordered = validate(
            replace(
                changed_data,
                blocks=changed_data.blocks.sample(frac=1.0, random_state=21).reset_index(drop=True),
                methods=changed_data.methods.sample(frac=1.0, random_state=22).reset_index(drop=True),
                finals=changed_data.finals.sample(frac=1.0, random_state=23).reset_index(drop=True),
            ),
            frozenset({changed_fingerprint}),
        )
        self.assertEqual(approved_reordered["response_fingerprint"], changed_fingerprint)
        self.assertTrue(approved_reordered["paper_eligible"])

    def test_ineligible_build_persists_gate_and_cannot_plan_paper_assets(self) -> None:
        """构建清单必须保存门禁结果，后续命令不得诱导或执行论文复制。"""

        settings = replace(load_settings(), bootstrap_iterations=1000)
        source = GPT_WORKBOOK.resolve()
        data = replace(read_workbook(source), source_kind="formal")
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
            self.assertFalse(payload["build"]["details"]["paper_eligible"])
            results_path = analysis_root / "results" / "experiment3_analysis.xlsx"
            workbook = load_workbook(results_path, read_only=True, data_only=True)
            try:
                readme_text = " ".join(
                    str(cell.value or "")
                    for row in workbook["说明"].iter_rows()
                    for cell in row
                )
            finally:
                workbook.close()
            self.assertIn("流程演练", readme_text)
            tex_text = (analysis_root / "tex" / "exp3_subjective.tex").read_text(
                encoding="utf-8"
            )
            self.assertIn("流程演练，禁止作为论文证据", tex_text)

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
            with mock.patch(
                "egoanchor.eval.experiments.experiment_3.workflow.load_paths",
                return_value=paths,
            ):
                status = describe_workflow()
                self.assertFalse(status["build"]["paper_eligible"])
                self.assertTrue(
                    any("来源完整性门禁" in item for item in status["build"]["warnings"])
                )
                with self.assertRaisesRegex(ValueError, "来源完整性门禁"):
                    plan_assets()

            with (
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.load_paths",
                    return_value=paths,
                ),
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.load_settings",
                    return_value=settings,
                ),
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.read_workbook",
                    return_value=data,
                ),
            ):
                validation_status = validate_workflow()
            self.assertFalse(validation_status["passed"])
            self.assertFalse(validation_status["paper_eligible"])
            self.assertIn("来源完整性门禁", validation_status["reason"])

            mocked_build = {
                "passed": True,
                "build": {"details": {"paper_eligible": False}},
            }
            with (
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.load_paths",
                    return_value=paths,
                ),
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.load_settings",
                    return_value=settings,
                ),
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.settings_sha256",
                    return_value="0" * 64,
                ),
                mock.patch(
                    "egoanchor.eval.experiments.experiment_3.workflow.build_analysis",
                    return_value=mocked_build,
                ),
            ):
                workflow_result = analyze_workflow()
            self.assertIn("真实参与者数据", workflow_result["next_command"])

    def test_eligible_build_plans_only_figure4_and_subjective_table(self) -> None:
        """通过来源门禁后，论文资源计划只包含 Figure 4 与完整结果表。"""

        settings = replace(load_settings(), bootstrap_iterations=1000)
        source = GPT_WORKBOOK.resolve()
        data = replace(read_workbook(source), source_kind="formal")
        blocks = data.blocks.copy()
        blocks.at[0, "Q1"] = 2 if blocks.at[0, "Q1"] == 1 else 1
        data = replace(data, blocks=blocks)
        unapproved = validate_for_analysis(
            data,
            minimum_participants=settings.minimum_participants,
            aq_mode=settings.aq_mode,
            q10_enabled=settings.q10_enabled,
            approved_response_fingerprints=settings.approved_response_fingerprints,
        )
        settings = replace(
            settings,
            approved_response_fingerprints=frozenset({unapproved["response_fingerprint"]}),
        )
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
            self.assertTrue(payload["build"]["details"]["paper_eligible"])

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
                    "egoanchor.eval.experiments.experiment_3.workflow.settings_sha256",
                    return_value="0" * 64,
                ),
            ):
                plan = plan_assets()
            self.assertEqual(
                {asset.key for asset in plan.assets},
                {"figure4_png", "figure4_pdf", "subjective_table"},
            )

    def test_r2_simulation_reproduces_frozen_family_directions(self) -> None:
        """模拟输入只用于验证计分、配对方向和家族校正实现。"""

        settings = replace(load_settings(), bootstrap_iterations=1000)
        data = read_workbook(R2_WORKBOOK)
        validation = validate_for_analysis(
            data,
            minimum_participants=settings.minimum_participants,
            aq_mode=settings.aq_mode,
            q10_enabled=settings.q10_enabled,
            approved_response_fingerprints=settings.approved_response_fingerprints,
            allow_synthetic=True,
        )
        scores = derive_scores(data, settings)
        tables = analyze_scores(data, scores, settings)
        primary = tables.results[tables.results["Family"] == MAIN_FAMILY].set_index("Outcome")
        scales = tables.results[tables.results["Family"] == SCALE_FAMILY].set_index("Outcome")
        sample = tables.sample
        included_row = sample[
            (sample["Section"] == "Sample_Flow") & (sample["Variable"] == "Included")
        ].iloc[0]
        age_row = sample[sample["Variable"] == "Age"].iloc[0]
        balance = sample[sample["Section"] == "Design_Balance"]
        self.assertEqual(validation["included_count"], 24)
        self.assertEqual(int(included_row["N"]), 24)
        self.assertEqual(int(age_row["N"]), 0)
        self.assertEqual(int(age_row["Denominator"]), 24)
        self.assertNotIn("Missing_N", sample.columns)
        self.assertTrue((balance["Status"] == "balanced").all())
        self.assertEqual(
            tuple(type(scores).__dataclass_fields__),
            ("block_scores", "paired_scores", "reliability_items"),
        )
        self.assertEqual(
            tuple(tables.results.columns),
            (
                "Family",
                "Outcome",
                "N",
                "N_Nonzero",
                "OneEuro_Q1",
                "OneEuro_Median",
                "OneEuro_Q3",
                "EgoAnchor_Q1",
                "EgoAnchor_Median",
                "EgoAnchor_Q3",
                "Difference_Q1",
                "Difference_Median",
                "Difference_Q3",
                "W",
                "r_rb",
                "r_rb_CI_Low",
                "r_rb_CI_High",
                "r_rb_CI_Status",
                "p_Holm",
            ),
        )
        self.assertEqual(int(primary.loc["Q1", "N"]), 24)
        self.assertLess(float(primary.loc["Q1", "p_Holm"]), 0.01)
        self.assertGreater(float(primary.loc["Q2", "p_Holm"]), 0.05)
        self.assertLess(float(scales.loc["STIAS", "p_Holm"]), 0.01)

    def test_results_workbook_and_figures_share_one_analysis_object(self) -> None:
        """结果 XLSX 可回读绘图，并同时生成非空 PNG/PDF。"""

        settings = replace(load_settings(), bootstrap_iterations=1000)
        data = read_workbook(R2_WORKBOOK)
        validation = validate_for_analysis(
            data,
            minimum_participants=settings.minimum_participants,
            aq_mode=settings.aq_mode,
            q10_enabled=settings.q10_enabled,
            approved_response_fingerprints=settings.approved_response_fingerprints,
            allow_synthetic=True,
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
                paper_eligible=validation["paper_eligible"],
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
            self.assertEqual(set(figures), {"figure4_png", "figure4_pdf"})
            for path in figures.values():
                self.assertGreater(path.stat().st_size, 10_000)

    def test_formal_participant_summary_reports_demographics_duration_and_balance(self) -> None:
        """正式分析严格校验背景字段，并以纳入 N 为分母汇总。"""

        settings = replace(load_settings(), bootstrap_iterations=1000)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "formal_participants.xlsx"
            copyfile(R2_WORKBOOK, source)
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
                minimum_participants=settings.minimum_participants,
                aq_mode=settings.aq_mode,
                q10_enabled=settings.q10_enabled,
                approved_response_fingerprints=settings.approved_response_fingerprints,
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
                    minimum_participants=settings.minimum_participants,
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                    approved_response_fingerprints=settings.approved_response_fingerprints,
                )

            pending = edited_case("pending", (("Participants", "V3", None),))
            with self.assertRaisesRegex(ValueError, "明确标记纳入或排除"):
                validate_for_analysis(
                    read_workbook(pending),
                    minimum_participants=settings.minimum_participants,
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                    approved_response_fingerprints=settings.approved_response_fingerprints,
                )

            no_consent = edited_case("no_consent", (("Participants", "R3", None),))
            with self.assertRaisesRegex(ValueError, "先明确签署同意"):
                validate_for_analysis(
                    read_workbook(no_consent),
                    minimum_participants=settings.minimum_participants,
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                    approved_response_fingerprints=settings.approved_response_fingerprints,
                )

            missing_runtime = edited_case("missing_runtime", (("Records", "AF5", None),))
            with self.assertRaisesRegex(ValueError, "Candidate_Rate_Hz"):
                validate_for_analysis(
                    read_workbook(missing_runtime),
                    minimum_participants=settings.minimum_participants,
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                    approved_response_fingerprints=settings.approved_response_fingerprints,
                )

            invalid_method = edited_case("invalid_method", (("Records", "V152", "设备故障"),))
            with self.assertRaisesRegex(ValueError, "技术状态"):
                validate_for_analysis(
                    read_workbook(invalid_method),
                    minimum_participants=settings.minimum_participants,
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                    approved_response_fingerprints=settings.approved_response_fingerprints,
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
                    minimum_participants=settings.minimum_participants,
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                    approved_response_fingerprints=settings.approved_response_fingerprints,
                )

            invalid_mapping = edited_case("invalid_mapping", (("Records", "C152", "方法B"),))
            with self.assertRaisesRegex(ValueError, "评分顺序"):
                read_workbook(invalid_mapping)

    def test_cli_exposes_experiment3_as_analyze_target(self) -> None:
        """实验三与实验一/二共享 analyze 生命周期，不再另设 plot。"""

        parser = eval_cli.build_parser()
        args = parser.parse_args(["analyze", "exp3"])
        self.assertEqual(args.target, "exp3")
        self.assertIs(args.handler, eval_cli._run_analyze)


if __name__ == "__main__":
    unittest.main()
