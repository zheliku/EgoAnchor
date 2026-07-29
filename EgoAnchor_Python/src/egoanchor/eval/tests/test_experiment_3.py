"""实验三正式模板、统计与完整构建产物测试。"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import time
from pathlib import Path
from shutil import copyfile

from openpyxl import load_workbook  # type: ignore[import-untyped]

from egoanchor.eval import cli as eval_cli
from egoanchor.eval.experiments.experiment_3 import build_raw_template, load_settings
from egoanchor.eval.experiments.experiment_3.analysis import (
    analyze_scores,
    derive_scores,
    publish_figures,
    read_workbook,
    signed_rank_test,
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


class Experiment3Tests(unittest.TestCase):
    """验证空白模板、实时公式边界和离线结果链。"""

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

    def test_r2_simulation_reproduces_frozen_family_directions(self) -> None:
        """模拟输入只用于验证计分、配对方向和家族校正实现。"""

        settings = replace(load_settings(), bootstrap_iterations=1000, clmm_enabled=False)
        data = read_workbook(R2_WORKBOOK)
        validation = validate_for_analysis(
            data,
            minimum_participants=settings.minimum_participants,
            aq_mode=settings.aq_mode,
            q10_enabled=settings.q10_enabled,
            allow_synthetic=True,
        )
        scores = derive_scores(data, settings)
        tables = analyze_scores(data, scores, settings)
        primary = tables.primary.set_index("Outcome")
        scales = tables.scales.set_index("Outcome")
        participant_summary = tables.participant_summary
        included_row = participant_summary[
            (participant_summary["Section"] == "Sample_Flow")
            & (participant_summary["Variable"] == "Included")
        ].iloc[0]
        age_row = participant_summary[participant_summary["Variable"] == "Age"].iloc[0]
        self.assertEqual(validation["included_count"], 24)
        self.assertEqual(int(included_row["N"]), 24)
        self.assertEqual(int(age_row["Missing_N"]), 24)
        self.assertTrue((tables.participant_balance["Status"] == "balanced").all())
        self.assertEqual(len(tables.participant_audit), 24)
        self.assertEqual(int(primary.loc["Q1", "N"]), 24)
        self.assertLess(float(primary.loc["Q1", "p_Holm"]), 0.01)
        self.assertGreater(float(primary.loc["Q2", "p_Holm"]), 0.05)
        self.assertLess(float(scales.loc["STIAS", "p_Holm"]), 0.01)
        workbook = load_workbook(R2_WORKBOOK, data_only=True, read_only=True)
        try:
            analysis = workbook["Analysis"]
            for row_number, outcome in enumerate(
                ("Q1", "Q8", "Q2", "Q9", "Q3", "Q6", "Q7"),
                start=5,
            ):
                offline = primary.loc[outcome]
                self.assertAlmostEqual(
                    float(analysis.cell(row_number, 5).value),
                    float(offline["Difference_Median"]),
                )
                self.assertAlmostEqual(
                    float(analysis.cell(row_number, 6).value),
                    float(offline["Difference_Mean"]),
                )
                self.assertAlmostEqual(
                    float(analysis.cell(row_number, 7).value),
                    float(offline["Difference_SD"]),
                )
                self.assertAlmostEqual(
                    float(analysis.cell(row_number, 8).value),
                    float(offline["dz"]),
                )
            for row_number, outcome in enumerate(
                ("AQ_EQ", "AQ_IQ", "TIA_RC", "TIA_UP", "STIAS"),
                start=15,
            ):
                offline = scales.loc[outcome]
                self.assertAlmostEqual(
                    float(analysis.cell(row_number, 4).value),
                    float(offline["Difference_Median"]),
                )
                self.assertAlmostEqual(
                    float(analysis.cell(row_number, 5).value),
                    float(offline["Difference_SD"]),
                )
                self.assertAlmostEqual(
                    float(analysis.cell(row_number, 6).value),
                    float(offline["dz"]),
                )
        finally:
            workbook.close()

    def test_results_workbook_and_figures_share_one_analysis_object(self) -> None:
        """结果 XLSX 可回读绘图，并同时生成非空 PNG/PDF。"""

        settings = replace(load_settings(), bootstrap_iterations=1000, clmm_enabled=False)
        data = read_workbook(R2_WORKBOOK)
        validation = validate_for_analysis(
            data,
            minimum_participants=settings.minimum_participants,
            aq_mode=settings.aq_mode,
            q10_enabled=settings.q10_enabled,
            allow_synthetic=True,
        )
        scores = derive_scores(data, settings)
        tables = analyze_scores(data, scores, settings)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = write_results_workbook(
                root / "experiment3_analysis.xlsx",
                data=data,
                scores=scores,
                tables=tables,
                clmm_coefficients=tables.primary.iloc[0:0],
                clmm_contrasts=tables.primary.iloc[0:0],
            settings=settings,
            settings_sha256="0" * 64,
            batch_config_path=root / "batch.toml",
            paper_config_path=root / "paper.toml",
            validation=validation,
        )
            figures = publish_figures(results, root, settings)
            workbook = load_workbook(results, read_only=True, data_only=True)
            try:
                self.assertIn("Participant_Summary", workbook.sheetnames)
                self.assertIn("Participant_Balance", workbook.sheetnames)
                self.assertIn("Participant_Audit", workbook.sheetnames)
                self.assertEqual(workbook["Participant_Audit"].max_row, 25)
                summary = workbook["Participant_Summary"]
                headers = [summary.cell(1, column).value for column in range(1, summary.max_column + 1)]
                proportion_column = headers.index("Proportion") + 1
                self.assertEqual(summary.cell(2, proportion_column).number_format, "0.0%")
            finally:
                workbook.close()
            self.assertGreater(results.stat().st_size, 50_000)
            self.assertEqual(set(figures), {"paired_png", "paired_pdf", "scales_png", "scales_pdf"})
            for path in figures.values():
                self.assertGreater(path.stat().st_size, 10_000)

    def test_formal_participant_summary_reports_demographics_duration_and_balance(self) -> None:
        """正式分析严格校验背景字段，并以纳入 N 为分母汇总。"""

        settings = replace(load_settings(), bootstrap_iterations=1000, clmm_enabled=False)
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
            )
            scores = derive_scores(data, settings)
            tables = analyze_scores(data, scores, settings)
            summary = tables.participant_summary
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
            self.assertEqual(int(age["Missing_N"]), 0)
            self.assertAlmostEqual(float(duration["Median"]), 60.0)
            self.assertEqual(int(women["N"]), 12)
            self.assertAlmostEqual(float(women["Proportion"]), 0.5)
            self.assertEqual(int(worsened["N"]), 0)
            self.assertTrue((tables.participant_balance["Status"] == "balanced").all())

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
                )

            pending = edited_case("pending", (("Participants", "V3", None),))
            with self.assertRaisesRegex(ValueError, "明确标记纳入或排除"):
                validate_for_analysis(
                    read_workbook(pending),
                    minimum_participants=settings.minimum_participants,
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                )

            no_consent = edited_case("no_consent", (("Participants", "R3", None),))
            with self.assertRaisesRegex(ValueError, "先明确签署同意"):
                validate_for_analysis(
                    read_workbook(no_consent),
                    minimum_participants=settings.minimum_participants,
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                )

            missing_runtime = edited_case("missing_runtime", (("Records", "AF5", None),))
            with self.assertRaisesRegex(ValueError, "Candidate_Rate_Hz"):
                validate_for_analysis(
                    read_workbook(missing_runtime),
                    minimum_participants=settings.minimum_participants,
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                )

            invalid_method = edited_case("invalid_method", (("Records", "V152", "设备故障"),))
            with self.assertRaisesRegex(ValueError, "技术状态"):
                validate_for_analysis(
                    read_workbook(invalid_method),
                    minimum_participants=settings.minimum_participants,
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
                    minimum_participants=settings.minimum_participants,
                    aq_mode=settings.aq_mode,
                    q10_enabled=settings.q10_enabled,
                )

            invalid_mapping = edited_case("invalid_mapping", (("Records", "C152", "方法B"),))
            with self.assertRaisesRegex(ValueError, "评分顺序"):
                read_workbook(invalid_mapping)

    def test_signed_rank_exact_sign_dp_handles_zeros_and_ties(self) -> None:
        """精确秩检验删除零差，并以平均秩保留并列。"""

        result = signed_rank_test([0.0, 1.0, 1.0, -2.0])
        self.assertEqual(result["n_nonzero"], 3)
        self.assertAlmostEqual(float(result["w"]), 3.0)
        self.assertAlmostEqual(float(result["rank_biserial"]), 0.0)
        self.assertEqual(float(result["p_value"]), 1.0)

    def test_cli_exposes_experiment3_as_analyze_target(self) -> None:
        """实验三与实验一/二共享 analyze 生命周期，不再另设 plot。"""

        parser = eval_cli.build_parser()
        args = parser.parse_args(["analyze", "exp3"])
        self.assertEqual(args.target, "exp3")
        self.assertIs(args.handler, eval_cli._run_analyze)


if __name__ == "__main__":
    unittest.main()
