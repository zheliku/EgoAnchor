"""Stage 2 科学结果到 display-ready paper CSV 行的投影。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from ..contracts import get_metric_definition
from .exp1 import EXP1_ID, EXP1_VARIANTS, Exp1AnalysisResult, Exp1Trial
from .exp2 import EXP2_COMPONENTS, EXP2_ID, Exp2AnalysisResult, PairedDeltaSummaryRow
from .lineage import input_workbook_set_sha256


_SCENARIO_TOKENS = {
    "static_head_motion": "StaticHeadMotion",
    "start_stop_6dof": "StartStopSixDof",
    "continuous_translation": "ContinuousTranslation",
    "continuous_rotation": "ContinuousRotation",
    "occlusion_recovery": "OcclusionRecovery",
}
"""场景机器键到纯字母宏 token 的冻结映射。"""

_SCENARIO_LABELS = {
    "static_head_motion": "静止头动",
    "start_stop_6dof": "起停 6DoF",
    "continuous_translation": "持续平移",
    "continuous_rotation": "持续旋转",
    "occlusion_recovery": "遮挡恢复",
}
"""场景机器键到论文表格标签的映射。"""

_VARIANT_TOKENS = {
    "Arrival-Hold": "ArrivalHold",
    "Capture-Hold": "CaptureHold",
    "One-Euro Anchor": "OneEuroAnchor",
    "EgoAnchor": "EgoAnchor",
}
"""实验一 variant 到纯字母宏 token 的映射。"""

_COMPONENT_TOKENS = {
    "capture_time_alignment": "CaptureTimeAlignment",
    "vcd_admission": "VcdAdmission",
    "temporal_synthesis": "TemporalSynthesis",
    "static_lock": "StaticLock",
}
"""实验二组件到纯字母宏 token 的映射。"""

_COMPONENT_LABELS = {
    "capture_time_alignment": "采集时刻对齐",
    "vcd_admission": "VCD 接纳",
    "temporal_synthesis": "时序合成",
    "static_lock": "StaticLock",
}
"""实验二组件到论文表格标签的映射。"""

_EXP2_TABLE_METRICS = {
    "capture_time_alignment": (
        "translation_event_pninetyfive_mm",
        "rotation_event_pninetyfive_deg",
    ),
    "vcd_admission": (
        "occlusion_translation_pninetyfive_mm",
        "durable_recovery_time_ms",
    ),
    "temporal_synthesis": ("motion_hold_ratio", "motion_translation_pninetyfive_mm"),
    "static_lock": ("position_hp_rms_mm", "absolute_translation_median_mm"),
}
"""实验二四行表的主效应与代价/guardrail 指标。"""


@dataclass(frozen=True, slots=True)
class PaperRows:
    """保存 Stage 2 的 paper/numbers 和 paper/tables 行。"""

    numbers: tuple[dict[str, object], ...]
    """宏名、数值和上游 lineage 行。"""

    tables: tuple[dict[str, object], ...]
    """display-ready 表格单元格和上游 lineage 行。"""


def _display_number(value: float) -> str:
    """以最多三位有效数字和三位小数格式化论文显示值。

    参数：
        value: 已由科学计算层验证的有限数值。
    """

    if value == 0.0:
        return "0"
    magnitude = math.floor(math.log10(abs(value)))
    decimal_places = min(3, max(0, 2 - magnitude))
    text = format(value, f".{decimal_places}f")
    if decimal_places > 0:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _metric_value(value: float, unit: str, tex_suffix: str) -> tuple[float, str, str]:
    """将 proportion 转为百分数，其余指标保持冻结单位。

    参数：
        value: 科学结果原始数值。
        unit: 冻结指标单位。
        tex_suffix: 指标目录的纯字母 TeX 后缀。
    """

    if unit == "proportion":
        return value * 100.0, f"{tex_suffix}Pct", "%"
    return value, tex_suffix, unit


def _direction_arrow(metric_key: str) -> str:
    """返回 CV 风格表头使用的指标优劣方向箭头。"""

    direction = get_metric_definition(metric_key).direction
    if direction == "lower_is_better":
        return "↓"
    if direction == "higher_is_better":
        return "↑"
    return "↕"


def _delta_metric_value(value: float, unit: str, tex_suffix: str) -> tuple[float, str, str]:
    """将指标差值转换为论文单位，比例差使用百分点。

    参数：
        value: 消融减完整系统的科学结果差值。
        unit: 冻结指标单位。
        tex_suffix: 指标目录的纯字母 TeX 后缀。
    """

    if unit == "proportion":
        return value * 100.0, f"{tex_suffix}PercentagePoint", "pp"
    return value, tex_suffix, unit


def _number_row(
    experiment: str,
    macro_name: str,
    value: object,
    source_csv: str,
    source_sha256: str,
) -> dict[str, object]:
    """创建一条符合 numbers.csv 契约的行。

    参数：
        experiment: 冻结实验标识。
        macro_name: 不含实验前缀的纯字母宏后缀。
        value: 待写入 CSV 的有限数值或计数。
        source_csv: 直接提供该值的 Stage 2 CSV。
        source_sha256: 写出前占位 hash；CSV writer 会回填 source_csv 实际 hash。
    """

    if not macro_name.isascii() or not macro_name.isalpha():
        raise ValueError(f"paper macro 后缀必须只含 ASCII 字母：{macro_name}")
    display_value = _display_number(value) if isinstance(value, float) else value
    return {
        "experiment": experiment,
        "macro_name": macro_name,
        "value": display_value,
        "source_csv": source_csv,
        "source_sha256": source_sha256,
    }


def _table_cell(
    experiment: str,
    table_name: str,
    row_key: str,
    column_key: str,
    display_value: str,
    source_csv: str,
    source_sha256: str,
) -> dict[str, object]:
    """创建一条符合 tables.csv 契约的 display-ready 单元格。

    参数：
        experiment: 冻结实验标识。
        table_name: 表格稳定机器名。
        row_key: 读者可读且唯一的行标签。
        column_key: 读者可读且唯一的列标签。
        display_value: 已格式化但尚未 TeX 转义的单元格文本。
        source_csv: 直接提供该单元格的 Stage 2 CSV。
        source_sha256: 写出前占位 hash；CSV writer 会回填实际 hash。
    """

    return {
        "experiment": experiment,
        "table_name": table_name,
        "row_key": row_key,
        "column_key": column_key,
        "display_value": display_value,
        "source_csv": source_csv,
        "source_sha256": source_sha256,
    }


def _exp1_rows(
    trials: tuple[Exp1Trial, ...],
    result: Exp1AnalysisResult,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """构造实验一计数、场景宏和主指标四系统表格。

    参数：
        trials: 五场景完成 trial。
        result: 已完成 event/session 汇总的实验一结果。
    """

    source_hash = input_workbook_set_sha256(trial.workbook_sha256 for trial in trials)
    numbers = [
        _number_row(EXP1_ID, "SessionCount", len({trial.session_id for trial in trials}), "common/trial_windows.csv", source_hash),
        _number_row(EXP1_ID, "ScenarioCount", len({trial.scenario_id for trial in trials}), "common/trial_windows.csv", source_hash),
    ]
    for variant in EXP1_VARIANTS:
        numbers.append(
            _number_row(EXP1_ID, f"{_VARIANT_TOKENS[variant]}TrialCount", len(trials), "common/trial_windows.csv", source_hash)
        )

    summaries = tuple(result.scenario_summary)
    summary_by_key = {
        (summary.scenario_id, summary.variant_id, summary.metric_key): summary
        for summary in summaries
    }
    if len(summary_by_key) != len(summaries):
        raise ValueError("实验一 scenario_summary 包含重复键")
    for summary in summaries:
        if summary.metric_value is None:
            continue
        definition = get_metric_definition(summary.metric_key)
        value, suffix, _ = _metric_value(
            summary.metric_value,
            summary.metric_unit,
            definition.tex_suffix,
        )
        macro_name = (
            f"{_VARIANT_TOKENS[summary.variant_id]}"
            f"{_SCENARIO_TOKENS[summary.scenario_id]}{suffix}"
        )
        numbers.append(
            _number_row(
                EXP1_ID,
                macro_name,
                value,
                "exp1/scenario_summary.csv",
                summary.input_workbook_sha256,
            )
        )

    table_cells: list[dict[str, object]] = []
    table_metrics = (
        ("World P95 ↓", "static_head_motion", "translation_event_pninetyfive_mm"),
        ("HP--RMS ↓", "static_head_motion", "position_hp_rms_mm"),
        ("Response ↓", "start_stop_6dof", "visible_response_ms"),
        ("Trans. residual ↓", "continuous_translation", "translation_lag_pninetyfive_residual_mm"),
        ("Rot. residual ↓", "continuous_rotation", "angular_lag_pninetyfive_residual_deg"),
        ("Occlusion P95 ↓", "occlusion_recovery", "occlusion_translation_pninetyfive_mm"),
    )
    formatted: dict[tuple[str, str], tuple[str, float, str]] = {}
    for column_key, scenario_id, metric_key in table_metrics:
        definition = get_metric_definition(metric_key)
        selected_by_variant = {
            variant_id: summary_by_key.get((scenario_id, variant_id, metric_key))
            for variant_id in EXP1_VARIANTS
        }
        if any(summary is None for summary in selected_by_variant.values()):
            raise ValueError(f"实验一论文主指标缺失或未定义：{scenario_id}/{metric_key}")
        medians: dict[str, float] = {}
        for variant_id, selected_summary in selected_by_variant.items():
            assert selected_summary is not None
            if selected_summary.median is None or selected_summary.q1 is None or selected_summary.q3 is None:
                raise ValueError(f"实验一论文主指标统计量不完整：{scenario_id}/{variant_id}/{metric_key}")
            median, _, unit = _metric_value(selected_summary.median, selected_summary.metric_unit, definition.tex_suffix)
            q1, _, _ = _metric_value(selected_summary.q1, selected_summary.metric_unit, definition.tex_suffix)
            q3, _, _ = _metric_value(selected_summary.q3, selected_summary.metric_unit, definition.tex_suffix)
            formatted[(variant_id, column_key)] = (
                f"{_display_number(median)} [{_display_number(q1)}, {_display_number(q3)}] {unit}",
                median,
                selected_summary.input_workbook_sha256,
            )
            medians[variant_id] = median
        best = (
            min(medians.values())
            if definition.direction == "lower_is_better"
            else max(medians.values())
        )
        for variant_id, median in medians.items():
            display_text, _, source_hash = formatted[(variant_id, column_key)]
            if math.isclose(median, best, rel_tol=0.0, abs_tol=1e-12):
                formatted[(variant_id, column_key)] = (f"[BEST]{display_text}", median, source_hash)
    for variant_id in EXP1_VARIANTS:
        for column_key, _, _ in table_metrics:
            display_text, _, source_hash = formatted[(variant_id, column_key)]
            table_cells.append(
                _table_cell(
                    EXP1_ID,
                    "exp1_scenario_summary",
                    variant_id,
                    column_key,
                    display_text,
                    "exp1/scenario_summary.csv",
                    source_hash,
                )
            )
    return numbers, table_cells


def _exp2_rows(
    trials: tuple[Exp1Trial, ...],
    result: Exp2AnalysisResult,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """构造实验二配对宏、VCD 宏和四组件 display-ready 表格。

    参数：
        trials: 同一五场景批次的完成 trial。
        result: 已完成组件配对和 VCD AURC 的实验二结果。
    """

    source_hash = input_workbook_set_sha256(trial.workbook_sha256 for trial in trials)
    component_scenarios = {component.scenario_id for component in EXP2_COMPONENTS}
    numbers = [
        _number_row(
            EXP2_ID,
            "SessionCount",
            len({trial.session_id for trial in trials if trial.scenario_id in component_scenarios}),
            "common/trial_windows.csv",
            source_hash,
        ),
        _number_row(EXP2_ID, "ComponentCount", len(EXP2_COMPONENTS), "exp2/paired_summary.csv", source_hash),
    ]
    summaries = tuple(result.components.paired_summary)
    summary_by_key = {
        (summary.component_id, summary.metric_key): summary for summary in summaries
    }
    if len(summary_by_key) != len(summaries):
        raise ValueError("实验二 paired_summary 包含重复组件指标")
    for summary in summaries:
        definition = get_metric_definition(summary.metric_key)
        component_token = _COMPONENT_TOKENS[summary.component_id]
        source_csv = "exp2/paired_summary.csv"
        display_suffix = _metric_value(0.0, summary.metric_unit, definition.tex_suffix)[1]
        if summary.median is not None and summary.q1 is not None and summary.q3 is not None:
            value, suffix, _ = _delta_metric_value(
                summary.median,
                summary.metric_unit,
                definition.tex_suffix,
            )
            numbers.extend(
                (
                    _number_row(EXP2_ID, f"{component_token}{suffix}DeltaMedian", value, source_csv, summary.input_workbook_sha256),
                    _number_row(EXP2_ID, f"{component_token}{suffix}DeltaQOne", _delta_metric_value(summary.q1, summary.metric_unit, definition.tex_suffix)[0], source_csv, summary.input_workbook_sha256),
                    _number_row(EXP2_ID, f"{component_token}{suffix}DeltaQThree", _delta_metric_value(summary.q3, summary.metric_unit, definition.tex_suffix)[0], source_csv, summary.input_workbook_sha256),
                )
            )
        numbers.append(
            _number_row(EXP2_ID, f"{component_token}{definition.tex_suffix}PairCount", summary.sample_count, source_csv, summary.input_workbook_sha256)
        )
        numbers.extend(
            (
                _number_row(EXP2_ID, f"{component_token}{display_suffix}PositiveCount", summary.positive_count, source_csv, summary.input_workbook_sha256),
                _number_row(EXP2_ID, f"{component_token}{display_suffix}ZeroCount", summary.zero_count, source_csv, summary.input_workbook_sha256),
                _number_row(EXP2_ID, f"{component_token}{display_suffix}NegativeCount", summary.negative_count, source_csv, summary.input_workbook_sha256),
            )
        )

    table_cells: list[dict[str, object]] = []
    for component in EXP2_COMPONENTS:
        main_key, guardrail_key = _EXP2_TABLE_METRICS[component.component_id]
        main = summary_by_key.get((component.component_id, main_key))
        guardrail = summary_by_key.get((component.component_id, guardrail_key))
        required = (main, guardrail)
        if any(
            summary is None
            or summary.median is None
            or summary.q1 is None
            or summary.q3 is None
            for summary in required
        ):
            raise ValueError(f"实验二论文主效应或 guardrail 缺失：{component.component_id}")
        assert main is not None and guardrail is not None

        def delta_text(summary: PairedDeltaSummaryRow) -> str:
            """格式化一条已验证的配对差值 median[IQR]。

            参数：
                summary: 数值完整的组件配对汇总行。
            """

            assert summary.median is not None and summary.q1 is not None and summary.q3 is not None
            definition = get_metric_definition(summary.metric_key)
            median, _, unit = _delta_metric_value(summary.median, summary.metric_unit, definition.tex_suffix)
            q1, _, _ = _delta_metric_value(summary.q1, summary.metric_unit, definition.tex_suffix)
            q3, _, _ = _delta_metric_value(summary.q3, summary.metric_unit, definition.tex_suffix)
            return f"{_display_number(median)} [{_display_number(q1)}, {_display_number(q3)}] {unit}"

        if any(
            value is None
            for value in (
                main.full_median,
                main.full_q1,
                main.full_q3,
                main.ablation_median,
                main.ablation_q1,
                main.ablation_q3,
            )
        ):
            raise ValueError(f"实验二论文主指标缺少 Full/Ablated 汇总：{component.component_id}")

        def distribution_text(summary: PairedDeltaSummaryRow, prefix: str) -> str:
            """格式化 Full 或 Ablated 的 event median [IQR]。"""

            median = getattr(summary, f"{prefix}_median")
            q1 = getattr(summary, f"{prefix}_q1")
            q3 = getattr(summary, f"{prefix}_q3")
            assert median is not None and q1 is not None and q3 is not None
            definition = get_metric_definition(summary.metric_key)
            median_value, _, unit = _metric_value(median, summary.metric_unit, definition.tex_suffix)
            q1_value, _, _ = _metric_value(q1, summary.metric_unit, definition.tex_suffix)
            q3_value, _, _ = _metric_value(q3, summary.metric_unit, definition.tex_suffix)
            return f"{_display_number(median_value)} [{_display_number(q1_value)}, {_display_number(q3_value)}] {unit}"

        row_label = (
            f"{_COMPONENT_LABELS[component.component_id]}"
            f"（{_SCENARIO_LABELS[component.scenario_id]}）"
        )
        values = {
            "主指标": f"{get_metric_definition(main_key).label} {_direction_arrow(main_key)}",
            "Full median [IQR]": distribution_text(main, "full"),
            "Ablated median [IQR]": distribution_text(main, "ablation"),
            "Delta [IQR]（+/0/-）": (
                f"{delta_text(main)}; "
                f"{main.positive_count}/{main.zero_count}/{main.negative_count}"
            ),
            "护栏 Delta [IQR]": (
                f"{get_metric_definition(guardrail_key).label} {_direction_arrow(guardrail_key)}: {delta_text(guardrail)}"
            ),
        }
        for column_key, display_value in values.items():
            table_cells.append(
                _table_cell(
                    EXP2_ID,
                    "exp2_mechanism_attribution",
                    row_label,
                    column_key,
                    display_value,
                    source_csv,
                    main.input_workbook_sha256,
                )
            )

    aurc_rows = tuple(result.vcd.aurc)
    aurc_by_key = {
        (aurc_row.reference_kind, aurc_row.risk_kind): aurc_row
        for aurc_row in aurc_rows
    }
    expected_aurc = {("vcd", "mean"), ("random", "mean")}
    if len(aurc_by_key) != len(aurc_rows) or set(aurc_by_key) != expected_aurc:
        raise ValueError("实验二 paper 宏要求且只允许 VCD/random mean-risk AURC")
    for reference_kind in ("vcd", "random"):
        aurc_row = aurc_by_key[(reference_kind, "mean")]
        reference = "Vcd" if reference_kind == "vcd" else "Random"
        source_csv = "exp2/vcd_aurc.csv"
        numbers.extend(
            (
                _number_row(EXP2_ID, f"{reference}MeanRiskAurcMm", aurc_row.aurc_mm, source_csv, aurc_row.input_workbook_sha256),
                _number_row(EXP2_ID, f"{reference}MeanRiskCandidateCount", aurc_row.candidate_count, source_csv, aurc_row.input_workbook_sha256),
            )
        )
    operating_source = "plots/exp2_vcd_curve.csv"
    operating_values = (
        ("ActualAdmittedCoveragePct", result.vcd.operating_coverage * 100.0),
        ("ActualAdmittedTailRiskMm", result.vcd.operating_tail_risk_mm),
        ("ActualAdmittedCandidateCount", result.vcd.operating_accepted_count),
        ("EligibleCandidateCount", result.vcd.operating_eligible_count),
    )
    for macro_name, operating_value in operating_values:
        if operating_value is not None:
            numbers.append(_number_row(EXP2_ID, macro_name, operating_value, operating_source, source_hash))
    return numbers, table_cells


def build_paper_rows(
    trials: Iterable[Exp1Trial],
    exp1_result: Exp1AnalysisResult,
    exp2_result: Exp2AnalysisResult,
) -> PaperRows:
    """从已计算结果构造 Task 11 唯一允许读取的两个 paper CSV。

    参数：
        trials: Stage 2 loader 验证后的完成 trial。
        exp1_result: 实验一完整分析结果。
        exp2_result: 实验二组件和 VCD 分析结果。
    """

    materialized = tuple(trials)
    if not materialized:
        raise ValueError("paper CSV 需要至少一个完成 trial")
    exp1_numbers, exp1_tables = _exp1_rows(materialized, exp1_result)
    exp2_numbers, exp2_tables = _exp2_rows(materialized, exp2_result)
    return PaperRows(
        numbers=tuple((*exp1_numbers, *exp2_numbers)),
        tables=tuple((*exp1_tables, *exp2_tables)),
    )


__all__ = ["PaperRows", "build_paper_rows"]
