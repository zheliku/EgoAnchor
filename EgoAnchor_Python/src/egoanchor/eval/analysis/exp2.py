"""实验二四组件适用场景、event 配对差值与主分析入口。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Iterable, Sequence

import numpy as np

from ..contracts import SCENARIO_ORDER, get_metric_definition
from .exp1 import (
    Exp1Trial,
    MetricRow,
    aggregate_metric_rows,
    analyze_trial_events,
)
from .metrics import median_iqr
from .lineage import input_workbook_set_sha256
from .params import AnalysisParameters
from .vcd import (
    VcdAnalysisResult,
    VcdCandidate,
    VcdTrialContext,
    analyze_vcd,
)


EXP2_ID = "exp2_design_attribution"
"""实验二输出使用的冻结实验标识。"""

EXP2_FULL_VARIANT_ID = "EgoAnchor"
"""所有组件归因配对使用的完整系统配置。"""

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
"""Stage 1 工作簿 SHA-256 的规范格式。"""


@dataclass(frozen=True, slots=True)
class Exp2ComponentDefinition:
    """冻结一个组件消融的场景、配置与 event 指标集合。"""

    component_id: str
    """机器可读组件标识。"""

    scenario_id: str
    """归因该组件的唯一适用场景。"""

    ablation_variant_id: str
    """关闭该组件的冻结 runtime 配置。"""

    metric_keys: tuple[str, ...]
    """必须逐 event 配对的主指标与 guardrail。"""

    primary_metric_keys: tuple[str, ...]
    """正式批次至少要有一个有限配对值的主指标。"""

    def __post_init__(self) -> None:
        """校验标识、指标集合和主指标子集。"""

        if not self.component_id or not self.scenario_id or not self.ablation_variant_id:
            raise ValueError("实验二组件定义的标识、场景和消融不能为空")
        if not self.metric_keys or len(self.metric_keys) != len(set(self.metric_keys)):
            raise ValueError("实验二组件指标必须非空且唯一")
        if not self.primary_metric_keys or not set(self.primary_metric_keys).issubset(self.metric_keys):
            raise ValueError("实验二主指标必须是冻结组件指标的非空子集")
        for metric_key in self.metric_keys:
            definition = get_metric_definition(metric_key)
            if self.scenario_id not in definition.scenarios:
                raise ValueError(f"组件指标 {metric_key} 不适用于 {self.scenario_id}")


EXP2_COMPONENTS = (
    Exp2ComponentDefinition(
        "capture_time_alignment",
        "static_head_motion",
        "EgoAnchor w/o capture-time alignment",
        ("translation_event_pninetyfive_mm", "rotation_event_pninetyfive_deg"),
        ("translation_event_pninetyfive_mm",),
    ),
    Exp2ComponentDefinition(
        "vcd_admission",
        "occlusion_recovery",
        "EgoAnchor w/o VCD",
        (
            "occlusion_translation_pninetyfive_mm",
            "jump_pninetyfive_mm",
            "durable_recovery_time_ms",
            "durable_recovery_success",
        ),
        ("occlusion_translation_pninetyfive_mm", "jump_pninetyfive_mm"),
    ),
    Exp2ComponentDefinition(
        "temporal_synthesis",
        "continuous_translation",
        "EgoAnchor w/o temporal synthesis",
        (
            "effective_translation_lag_ms",
            "translation_lag_residual_mm",
        ),
        ("effective_translation_lag_ms", "translation_lag_residual_mm"),
    ),
    Exp2ComponentDefinition(
        "static_lock",
        "static_head_motion",
        "EgoAnchor w/o StaticLock",
        (
            "position_hp_rms_mm",
            "translation_event_pninetyfive_mm",
            "absolute_translation_median_mm",
            "position_drift_mm",
        ),
        ("position_hp_rms_mm",),
    ),
)
"""四个单组件消融的冻结适用场景、主指标与 guardrail。"""

EXP2_VARIANT_ORDER = (
    EXP2_FULL_VARIANT_ID,
    *(component.ablation_variant_id for component in EXP2_COMPONENTS),
)
"""实验二完整系统与四个消融的稳定报告顺序。"""


@dataclass(frozen=True, slots=True)
class Exp2VariantDefinition:
    """保存实验二核心四组件开关，用于拒绝名称与开关错配。"""

    variant_id: str
    """runtime 配置稳定名称。"""

    uses_capture_time_alignment: bool
    """是否启用采集时刻世界对齐。"""

    uses_vcd_admission: bool
    """是否启用 VCD admission。"""

    uses_temporal_synthesis: bool
    """是否启用 Kalman-Hermite 时序合成。"""

    uses_static_lock: bool
    """是否启用显式 StaticLock。"""

    uses_low_score_reacquire: bool
    """是否启用低分重获取；它属于 VCD admission 组件的运行时子开关。"""

    uses_server_reacquire: bool
    """是否启用服务器重获取；正式四组件归因中必须保持开启。"""

    world_alignment_mode: str
    """运行时记录的世界对齐模式，必须与采集时刻开关一致。"""

    quality_gate: str
    """运行时记录的质量门控模式，用于核对 VCD 消融。"""

    motion_model: str
    """运行时记录的运动模型，用于核对时序合成消融。"""

    smoothing_strategy: str
    """运行时记录的平滑策略，用于核对时序合成消融。"""

    def __post_init__(self) -> None:
        """拒绝空 variant 名称。"""

        if not self.variant_id:
            raise ValueError("实验二 variant_id 不能为空")
        if any(type(value) is not bool for value in self.extended_switches()):
            raise ValueError("实验二 variant 开关必须是原生 bool 类型")
        descriptive = (
            self.world_alignment_mode,
            self.quality_gate,
            self.motion_model,
            self.smoothing_strategy,
        )
        if any(type(value) is not str or not value for value in descriptive):
            raise ValueError("实验二 variant 描述性配置必须是非空文本")

    def switches(self) -> tuple[bool, bool, bool, bool]:
        """按冻结组件顺序返回四个布尔开关。"""

        return (
            self.uses_capture_time_alignment,
            self.uses_vcd_admission,
            self.uses_temporal_synthesis,
            self.uses_static_lock,
        )

    def extended_switches(self) -> tuple[bool, bool, bool, bool, bool, bool]:
        """按正式 schema-v2 顺序返回四组件和两个重获取开关。"""

        return (*self.switches(), self.uses_low_score_reacquire, self.uses_server_reacquire)


@dataclass(frozen=True, slots=True)
class PairedDeltaRow:
    """表示同 trial/event 内单组件消融减完整系统的指标差值。"""

    session_id: str
    """配对所属 session。"""

    experiment_id: str
    """输出实验标识，固定为实验二。"""

    scenario_id: str
    """组件适用场景。"""

    trial_id: str
    """配对所属 trial。"""

    event_id: str
    """配对所属 event/segment。"""

    condition_id: str
    """实验二组件与场景条件标识。"""

    variant_id: str
    """共享结果列中的 variant，固定写消融配置。"""

    component_id: str
    """归因组件稳定标识。"""

    full_variant_id: str
    """完整系统配置，固定为 EgoAnchor。"""

    ablation_variant_id: str
    """单组件消融配置。"""

    metric_key: str
    """冻结指标键。"""

    metric_value: float | None
    """共享结果列中的指标值，必须与 delta 相同。"""

    full_value: float | None
    """完整系统的 event 指标值。"""

    ablation_value: float | None
    """消融配置的 event 指标值。"""

    delta: float | None
    """消融值减完整系统值；任一侧为空时为空。"""

    metric_unit: str
    """冻结指标单位。"""

    pair_status: str
    """complete 或 value_missing；缺行会在构造前硬失败。"""

    aggregation_level: str
    """配对语义，固定为 paired_event_ablation_minus_full。"""

    input_workbook_sha256: str
    """配对两侧共同来源的 Stage 1 XLSX SHA-256。"""

    def __post_init__(self) -> None:
        """校验 delta、状态、单位和来源 hash 一致。"""

        if self.experiment_id != EXP2_ID or self.full_variant_id != EXP2_FULL_VARIANT_ID:
            raise ValueError("实验二 paired delta 的实验或完整系统标识错误")
        if self.variant_id != self.ablation_variant_id:
            raise ValueError("paired delta 的 variant_id 必须等于消融配置")
        if self.metric_value != self.delta:
            raise ValueError("paired delta 的 metric_value 必须等于 delta")
        definition = get_metric_definition(self.metric_key)
        if self.scenario_id not in definition.scenarios or self.metric_unit != definition.unit:
            raise ValueError("paired delta 与冻结指标目录不一致")
        if self.pair_status == "complete":
            if self.full_value is None or self.ablation_value is None or self.delta is None:
                raise ValueError("complete paired delta 的三项数值必须完整")
            if not math.isclose(
                self.delta,
                self.ablation_value - self.full_value,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError("paired delta 必须等于 ablation - full")
        elif self.pair_status == "value_missing":
            if self.full_value is not None and self.ablation_value is not None:
                raise ValueError("数值完整的配对不得标记为 value_missing")
            if self.delta is not None:
                raise ValueError("value_missing 配对的 delta 必须为空")
        else:
            raise ValueError("paired delta 使用了未知 pair_status")
        if not _SHA256_PATTERN.fullmatch(self.input_workbook_sha256):
            raise ValueError("paired delta 的工作簿 hash 格式错误")


@dataclass(frozen=True, slots=True)
class PairedDeltaSummaryRow:
    """保存一个组件与指标的低样本量 delta 汇总和方向计数。"""

    experiment_id: str
    """输出实验标识，固定为实验二。"""

    scenario_id: str
    """组件适用场景。"""

    component_id: str
    """归因组件稳定标识。"""

    full_variant_id: str
    """完整系统配置。"""

    ablation_variant_id: str
    """消融配置。"""

    metric_key: str
    """冻结指标键。"""

    metric_unit: str
    """冻结指标单位。"""

    full_median: float | None
    """完整 EgoAnchor event 指标的中位数。"""

    full_q1: float | None
    """完整 EgoAnchor event 指标的第一四分位数。"""

    full_q3: float | None
    """完整 EgoAnchor event 指标的第三四分位数。"""

    ablation_median: float | None
    """单组件消融 event 指标的中位数。"""

    ablation_q1: float | None
    """单组件消融 event 指标的第一四分位数。"""

    ablation_q3: float | None
    """单组件消融 event 指标的第三四分位数。"""

    attempt_count: int
    """进入汇总的全部 event 配对尝试数。"""

    sample_count: int
    """两侧数值均定义的完整配对数。"""

    median: float | None
    """有限 delta 的中位数。"""

    q1: float | None
    """有限 delta 的第一四分位数。"""

    q3: float | None
    """有限 delta 的第三四分位数。"""

    iqr: float | None
    """有限 delta 的四分位距。"""

    minimum: float | None
    """有限 delta 的最小值。"""

    maximum: float | None
    """有限 delta 的最大值。"""

    positive_count: int
    """delta 大于零的完整配对数。"""

    zero_count: int
    """delta 等于零的完整配对数。"""

    negative_count: int
    """delta 小于零的完整配对数。"""

    input_workbook_sha256: str
    """一个工作簿 hash 或稳定输入 hash 集合摘要。"""


@dataclass(frozen=True, slots=True)
class Exp2ComponentResult:
    """保存四组件 event/trial/session 指标、配对 delta 和汇总。"""

    event_metrics: tuple[MetricRow, ...]
    """完整系统与对应消融在适用场景的冻结 event 指标。"""

    trial_metrics: tuple[MetricRow, ...]
    """event 指标在 trial 内的中位数汇总。"""

    session_metrics: tuple[MetricRow, ...]
    """trial 指标在 session 内的等权中位数汇总。"""

    paired_deltas: tuple[PairedDeltaRow, ...]
    """严格同 trial/event 配对的消融减完整系统差值。"""

    paired_summary: tuple[PairedDeltaSummaryRow, ...]
    """event-level delta 的 median[IQR]、范围与方向。"""


@dataclass(frozen=True, slots=True)
class Exp2AnalysisResult:
    """保存 Task 8 完整组件归因与 VCD 诊断结果。"""

    components: Exp2ComponentResult
    """四个单组件的 event-level 配对分析。"""

    vcd: VcdAnalysisResult
    """完整 EgoAnchor VCD risk-coverage 诊断。"""


def validate_exp2_variant_definitions(
    definitions: Iterable[Exp2VariantDefinition],
) -> None:
    """验证完整系统全开且四个消融分别只关闭对应组件。

    参数：
        definitions: Task 9 从 XLSX variants sheet 投影的配置定义。
    """

    materialized = tuple(definitions)
    by_id = {definition.variant_id: definition for definition in materialized}
    if len(by_id) != len(materialized):
        raise ValueError("实验二 variant 定义包含重复名称")
    expected = {
        EXP2_FULL_VARIANT_ID: (True, True, True, True, True, True),
        "EgoAnchor w/o capture-time alignment": (False, True, True, True, True, True),
        "EgoAnchor w/o VCD": (True, False, True, True, False, True),
        "EgoAnchor w/o temporal synthesis": (True, True, False, True, True, True),
        "EgoAnchor w/o StaticLock": (True, True, True, False, True, True),
    }
    missing = set(expected) - set(by_id)
    if missing:
        raise ValueError(f"实验二缺少完整系统或消融配置：{sorted(missing)}")
    for variant_id, expected_switches in expected.items():
        actual = by_id[variant_id].extended_switches()
        if actual != expected_switches:
            raise ValueError(f"实验二消融 {variant_id} 必须且只能关闭一个对应组件")

    descriptive_fields = (
        "world_alignment_mode",
        "quality_gate",
        "motion_model",
        "smoothing_strategy",
    )
    expected_descriptive = {
        EXP2_FULL_VARIANT_ID: ("CaptureTime", "enabled", "kalman", "interp_hermite"),
        "EgoAnchor w/o capture-time alignment": ("ArrivalTime", "enabled", "kalman", "interp_hermite"),
        "EgoAnchor w/o VCD": ("CaptureTime", "disabled", "kalman", "interp_hermite"),
        "EgoAnchor w/o temporal synthesis": ("CaptureTime", "enabled", "cv", "raw_passthrough"),
        "EgoAnchor w/o StaticLock": ("CaptureTime", "enabled", "kalman", "interp_hermite"),
    }
    for variant_id, expected_values in expected_descriptive.items():
        actual_values = tuple(getattr(by_id[variant_id], field) for field in descriptive_fields)
        if actual_values != expected_values:
            raise ValueError(f"实验二 variant {variant_id} 的描述性配置与冻结矩阵不一致")


def _event_pair_key(row: MetricRow) -> tuple[str, str, str, str]:
    """返回同 session/trial/event/metric 的双边配对键。

    参数：
        row: 完整系统或消融的 event 指标行。
    """

    return (row.session_id, row.trial_id, row.event_id, row.metric_key)


def _unique_rows(rows: Iterable[MetricRow], side: str) -> dict[tuple[str, str, str, str], MetricRow]:
    """建立一侧 event 指标唯一映射，重复时立即失败。

    参数：
        rows: 同一组件与 variant 的 event 指标。
        side: 报错时标识 full 或 ablation。
    """

    result: dict[tuple[str, str, str, str], MetricRow] = {}
    for row in rows:
        key = _event_pair_key(row)
        if key in result:
            raise ValueError(f"实验二 {side} event 指标主键重复：{key}")
        result[key] = row
    return result


def pair_component_metrics(
    event_metrics: Iterable[MetricRow],
    components: Sequence[Exp2ComponentDefinition] = EXP2_COMPONENTS,
) -> tuple[PairedDeltaRow, ...]:
    """对四组件执行双边 exact join，并计算 ablation - full。

    参数：
        event_metrics: 完整系统与消融的 event 指标并集。
        components: 冻结组件定义；测试可传入等价定义。
    """

    materialized = tuple(event_metrics)
    paired: list[PairedDeltaRow] = []
    for component in components:
        relevant = [
            row
            for row in materialized
            if row.scenario_id == component.scenario_id
            and row.metric_key in component.metric_keys
        ]
        full = _unique_rows(
            (row for row in relevant if row.variant_id == EXP2_FULL_VARIANT_ID),
            "full",
        )
        ablation = _unique_rows(
            (row for row in relevant if row.variant_id == component.ablation_variant_id),
            "ablation",
        )
        if not full or not ablation or set(full) != set(ablation):
            missing_full = sorted(set(ablation) - set(full))
            missing_ablation = sorted(set(full) - set(ablation))
            raise ValueError(
                f"实验二组件 {component.component_id} 缺少精确配对；"
                f"full={missing_full}，ablation={missing_ablation}"
            )
        for key in sorted(full):
            full_row = full[key]
            ablation_row = ablation[key]
            if (
                full_row.metric_unit != ablation_row.metric_unit
                or full_row.condition_id != ablation_row.condition_id
                or full_row.input_workbook_sha256 != ablation_row.input_workbook_sha256
            ):
                raise ValueError("实验二配对两侧的单位、条件或工作簿来源不一致")
            if full_row.metric_value is None or ablation_row.metric_value is None:
                delta = None
            else:
                delta = ablation_row.metric_value - full_row.metric_value
            complete = delta is not None
            paired.append(
                PairedDeltaRow(
                    session_id=full_row.session_id,
                    experiment_id=EXP2_ID,
                    scenario_id=component.scenario_id,
                    trial_id=full_row.trial_id,
                    event_id=full_row.event_id,
                    condition_id=f"{EXP2_ID}/{component.component_id}/{component.scenario_id}",
                    variant_id=component.ablation_variant_id,
                    component_id=component.component_id,
                    full_variant_id=EXP2_FULL_VARIANT_ID,
                    ablation_variant_id=component.ablation_variant_id,
                    metric_key=full_row.metric_key,
                    metric_value=delta,
                    full_value=full_row.metric_value,
                    ablation_value=ablation_row.metric_value,
                    delta=delta,
                    metric_unit=full_row.metric_unit,
                    pair_status="complete" if complete else "value_missing",
                    aggregation_level="paired_event_ablation_minus_full",
                    input_workbook_sha256=full_row.input_workbook_sha256,
                )
            )
    component_order = {
        component.component_id: index for index, component in enumerate(components)
    }
    return tuple(
        sorted(
            paired,
            key=lambda row: (
                component_order[row.component_id],
                row.session_id,
                row.trial_id,
                row.event_id,
                row.metric_key,
            ),
        )
    )


def summarize_paired_deltas(
    paired_deltas: Iterable[PairedDeltaRow],
    params: AnalysisParameters,
) -> tuple[PairedDeltaSummaryRow, ...]:
    """按组件与指标汇总 event delta，并保留范围和配对方向。

    参数：
        paired_deltas: event-level 消融减完整系统差值。
        params: 唯一冻结分析参数。
    """

    groups: dict[tuple[str, str, str], list[PairedDeltaRow]] = {}
    for row in paired_deltas:
        groups.setdefault((row.scenario_id, row.component_id, row.metric_key), []).append(row)
    if not groups:
        raise ValueError("实验二 paired delta 不能为空")
    summaries: list[PairedDeltaSummaryRow] = []
    for (scenario_id, component_id, metric_key), rows in groups.items():
        values = [row.delta for row in rows if row.delta is not None]
        stats = median_iqr(values, params) if values else None
        full_values = [row.full_value for row in rows if row.full_value is not None]
        ablation_values = [row.ablation_value for row in rows if row.ablation_value is not None]
        full_stats = median_iqr(full_values, params) if full_values else None
        ablation_stats = median_iqr(ablation_values, params) if ablation_values else None
        first = rows[0]
        summaries.append(
            PairedDeltaSummaryRow(
                experiment_id=EXP2_ID,
                scenario_id=scenario_id,
                component_id=component_id,
                full_variant_id=EXP2_FULL_VARIANT_ID,
                ablation_variant_id=first.ablation_variant_id,
                metric_key=metric_key,
                metric_unit=first.metric_unit,
                full_median=full_stats.median if full_stats is not None else None,
                full_q1=full_stats.q1 if full_stats is not None else None,
                full_q3=full_stats.q3 if full_stats is not None else None,
                ablation_median=ablation_stats.median if ablation_stats is not None else None,
                ablation_q1=ablation_stats.q1 if ablation_stats is not None else None,
                ablation_q3=ablation_stats.q3 if ablation_stats is not None else None,
                attempt_count=len(rows),
                sample_count=len(values),
                median=stats.median if stats is not None else None,
                q1=stats.q1 if stats is not None else None,
                q3=stats.q3 if stats is not None else None,
                iqr=stats.iqr if stats is not None else None,
                minimum=float(np.min(values)) if values else None,
                maximum=float(np.max(values)) if values else None,
                positive_count=sum(value > 0.0 for value in values),
                zero_count=sum(value == 0.0 for value in values),
                negative_count=sum(value < 0.0 for value in values),
                input_workbook_sha256=input_workbook_set_sha256(
                    row.input_workbook_sha256 for row in rows
                ),
            )
        )
    component_order = {component.component_id: index for index, component in enumerate(EXP2_COMPONENTS)}
    return tuple(
        sorted(
            summaries,
            key=lambda row: (component_order[row.component_id], row.metric_key),
        )
    )


def _relabel_event_row(row: MetricRow) -> MetricRow:
    """把共享科学指标行标记为实验二输出而不改变数值。

    参数：
        row: Task 7 公共 event 计算器生成的指标行。
    """

    return replace(
        row,
        experiment_id=EXP2_ID,
        condition_id=f"{EXP2_ID}/{row.scenario_id}",
    )


def analyze_exp2_components(
    trials: Iterable[Exp1Trial],
    variant_definitions: Iterable[Exp2VariantDefinition],
    params: AnalysisParameters,
) -> Exp2ComponentResult:
    """计算四个组件在适用场景内的 event 指标与严格配对差值。

    参数：
        trials: Task 9 从 Stage 1 XLSX 联接得到的完成 trial。
        variant_definitions: XLSX variants sheet 投影的核心组件开关。
        params: 唯一 TOML 解析得到的冻结分析参数。
    """

    validate_exp2_variant_definitions(variant_definitions)
    materialized = tuple(trials)
    required_scenarios = set(SCENARIO_ORDER)
    present_scenarios = {trial.scenario_id for trial in materialized}
    if not required_scenarios.issubset(present_scenarios):
        raise ValueError(
            f"实验二批次必须覆盖五个正式场景：{sorted(required_scenarios - present_scenarios)}"
        )
    metrics_by_scenario: dict[str, set[str]] = {}
    variants_by_scenario: dict[str, set[str]] = {}
    for component in EXP2_COMPONENTS:
        metrics_by_scenario.setdefault(component.scenario_id, set()).update(component.metric_keys)
        variants_by_scenario.setdefault(component.scenario_id, {EXP2_FULL_VARIANT_ID}).add(
            component.ablation_variant_id
        )

    event_rows: list[MetricRow] = []
    for trial in materialized:
        if trial.scenario_id not in variants_by_scenario:
            continue
        calculated = analyze_trial_events(
            trial,
            params,
            tuple(sorted(variants_by_scenario[trial.scenario_id])),
        )
        event_rows.extend(
            _relabel_event_row(row)
            for row in calculated
            if row.metric_key in metrics_by_scenario[trial.scenario_id]
        )
    event_metrics = tuple(
        sorted(
            event_rows,
            key=lambda row: (
                row.scenario_id,
                row.session_id,
                row.trial_id,
                row.event_id,
                row.variant_id,
                row.metric_key,
            ),
        )
    )
    paired = pair_component_metrics(event_metrics)
    for component in EXP2_COMPONENTS:
        for metric_key in component.primary_metric_keys:
            if not any(
                row.component_id == component.component_id
                and row.metric_key == metric_key
                and row.pair_status == "complete"
                for row in paired
            ):
                raise ValueError(
                    f"实验二组件 {component.component_id} 的冻结主指标 {metric_key} 没有有限配对"
                )
    trial_metrics = aggregate_metric_rows(event_metrics, "trial", EXP2_VARIANT_ORDER)
    return Exp2ComponentResult(
        event_metrics=event_metrics,
        trial_metrics=trial_metrics,
        session_metrics=aggregate_metric_rows(
            trial_metrics,
            "session",
            EXP2_VARIANT_ORDER,
        ),
        paired_deltas=paired,
        paired_summary=summarize_paired_deltas(paired, params),
    )


def analyze_exp2(
    trials: Iterable[Exp1Trial],
    variant_definitions: Iterable[Exp2VariantDefinition],
    vcd_candidates: Iterable[VcdCandidate],
    params: AnalysisParameters,
) -> Exp2AnalysisResult:
    """运行实验二组件归因与 VCD 诊断的完整纯计算层。

    参数：
        trials: Task 9 从 Stage 1 XLSX 联接得到的全部完成 trial。
        variant_definitions: variants sheet 投影的核心组件开关。
        vcd_candidates: 完整 EgoAnchor 已到达 admission 与同帧 reference 联接结果。
        params: 唯一 TOML 解析得到的冻结分析参数。
    """

    materialized = tuple(trials)
    contexts = tuple(
        VcdTrialContext(
            session_id=trial.session_id,
            scenario_id=trial.scenario_id,
            trial_id=trial.trial_id,
            trial_end_ms=trial.trial_end_ms,
            markers=trial.markers,
            workbook_sha256=trial.workbook_sha256,
        )
        for trial in materialized
        if trial.scenario_id == "occlusion_recovery"
    )
    return Exp2AnalysisResult(
        components=analyze_exp2_components(materialized, variant_definitions, params),
        vcd=analyze_vcd(vcd_candidates, contexts, params),
    )


__all__ = [
    "EXP2_COMPONENTS",
    "EXP2_FULL_VARIANT_ID",
    "EXP2_ID",
    "EXP2_VARIANT_ORDER",
    "Exp2AnalysisResult",
    "Exp2ComponentDefinition",
    "Exp2ComponentResult",
    "Exp2VariantDefinition",
    "PairedDeltaRow",
    "PairedDeltaSummaryRow",
    "analyze_exp2",
    "analyze_exp2_components",
    "pair_component_metrics",
    "summarize_paired_deltas",
    "validate_exp2_variant_definitions",
]
