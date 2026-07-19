"""实验二 VCD candidate risk、risk-coverage 与 cohort 敏感性分析。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from scipy.special import gammaln  # type: ignore[import-untyped]

from .lineage import input_workbook_set_sha256
from .params import AnalysisParameters
from .windows import EventMarker, pair_occlusion_windows


VCD_SCENARIO_ID = "occlusion_recovery"
"""VCD 风险诊断唯一允许使用的物理场景。"""

VCD_FULL_VARIANT_ID = "EgoAnchor"
"""VCD 风险诊断唯一允许使用的完整系统配置。"""

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
"""Stage 1 工作簿 SHA-256 的规范格式。"""


@dataclass(frozen=True, slots=True)
class VcdTrialContext:
    """保存 VCD cohort 敏感性所需的已完成遮挡 trial 边界。"""

    session_id: str
    """trial 所属 session。"""

    scenario_id: str
    """trial 场景，必须是遮挡恢复。"""

    trial_id: str
    """session 内稳定 trial 标识。"""

    trial_end_ms: float
    """通过 lifecycle QC 的 trial 结束单调时间。"""

    markers: tuple[EventMarker, ...]
    """显式遮挡与重新可见 marker。"""

    workbook_sha256: str
    """直接输入 Stage 1 XLSX 的 SHA-256。"""

    def __post_init__(self) -> None:
        """拒绝错误场景、空上下文、非法时间或来源 hash。"""

        if not self.session_id or not self.trial_id:
            raise ValueError("VCD trial context 的 session 和 trial 不能为空")
        if self.scenario_id != VCD_SCENARIO_ID:
            raise ValueError("VCD trial context 只能来自 occlusion_recovery")
        if not math.isfinite(self.trial_end_ms):
            raise ValueError("VCD trial_end_ms 必须有限")
        if not self.markers:
            raise ValueError("VCD trial context 必须包含显式 marker")
        if not _SHA256_PATTERN.fullmatch(self.workbook_sha256):
            raise ValueError("VCD trial context 的工作簿 hash 格式错误")
        for marker in self.markers:
            if (
                marker.session_id != self.session_id
                or marker.scenario_id != self.scenario_id
                or marker.trial_id != self.trial_id
            ):
                raise ValueError("VCD marker 不得跨 session、scenario 或 trial")


@dataclass(frozen=True, slots=True)
class VcdCandidate:
    """表示 Task 9 从完整 EgoAnchor admission 与同帧 reference 联接的候选。"""

    session_id: str
    """候选所属 session。"""

    scenario_id: str
    """候选所属场景，必须是遮挡恢复。"""

    trial_id: str
    """候选所属最终完成 trial。"""

    candidate_id: str
    """实际到达 Unity 的稳定候选标识。"""

    frame_id: int
    """候选来源帧标识。"""

    source_capture_mono_ms: float
    """候选来源帧在 Unity 单调时钟的采集时间代理。"""

    variant_id: str
    """候选 admission 所属 runtime，必须是完整 EgoAnchor。"""

    admission_decision: str
    """运行时 admission 文本，仅供审计，不参与 risk-coverage 筛选。"""

    vcd_score: float
    """VCD 输出的连续可靠性分数。"""

    has_aligned_raw: bool
    """是否记录了 capture-time aligned raw 位姿。"""

    aligned_raw_position_m: tuple[float, float, float]
    """采集时刻对齐后的 raw 世界位置，单位米。"""

    reference_frame_id: int | None
    """联接到的平台参考 frame；缺 reference 时为空。"""

    reference_session_id: str | None
    """联接到的平台参考 session；缺 reference 时为空。"""

    reference_pose_valid: bool | None
    """同 frame 平台参考是否有效；缺 reference 时为空。"""

    reference_position_m: tuple[float, float, float]
    """同 frame 平台参考世界位置，单位米；缺失允许保留 NaN。"""

    input_workbook_sha256: str
    """直接输入 Stage 1 XLSX 的 SHA-256。"""

    def __post_init__(self) -> None:
        """校验标识、时间、向量形状和来源 hash，不提前过滤科学缺失。"""

        if not self.session_id or not self.trial_id or not self.candidate_id:
            raise ValueError("VCD candidate 的 session、trial 和 candidate 不能为空")
        if self.scenario_id != VCD_SCENARIO_ID:
            raise ValueError("VCD candidate 只能来自 occlusion_recovery")
        if self.frame_id < 0 or not math.isfinite(self.source_capture_mono_ms):
            raise ValueError("VCD candidate 的 frame_id 或采集时间非法")
        if not self.variant_id or not self.admission_decision:
            raise ValueError("VCD candidate 的 variant 和 admission decision 不能为空")
        if len(self.aligned_raw_position_m) != 3 or len(self.reference_position_m) != 3:
            raise ValueError("VCD candidate 的位置必须是三维向量")
        if not _SHA256_PATTERN.fullmatch(self.input_workbook_sha256):
            raise ValueError("VCD candidate 的工作簿 hash 格式错误")


@dataclass(frozen=True, slots=True)
class VcdRiskPoint:
    """表示一个实际到达 Unity 候选的 risk 或明确排除原因。"""

    session_id: str
    """候选所属 session。"""

    experiment_id: str
    """输出实验标识，固定为实验二。"""

    scenario_id: str
    """输出场景，固定为遮挡恢复。"""

    trial_id: str
    """候选所属完成 trial。"""

    candidate_id: str
    """候选稳定标识。"""

    frame_id: int
    """候选来源 frame。"""

    source_capture_mono_ms: float
    """候选来源帧的 Unity 采集时间代理。"""

    variant_id: str
    """候选 runtime，固定为完整 EgoAnchor。"""

    admission_decision: str
    """候选在 Unity runtime 的实际 admission 文本。"""

    vcd_score: float
    """合法的有限 VCD 分数。"""

    risk_mm: float | None
    """aligned raw 相对同 frame reference 的平移误差，排除时为空。"""

    eligible: bool
    """候选是否进入 coverage 分母与曲线。"""

    exclusion_reason: str
    """eligible 或一个稳定排除原因。"""

    has_aligned_raw: bool
    """输入是否带 capture-time aligned raw 位姿。"""

    reference_pose_valid: bool | None
    """同 frame reference 有效状态；缺 reference 时为空。"""

    reference_session_id: str | None
    """同 frame reference 的 session；缺 reference 时为空。"""

    reference_frame_id: int | None
    """同 session reference 的 frame；缺 reference 时为空。"""

    input_workbook_sha256: str
    """候选来源工作簿 SHA-256。"""

    def __post_init__(self) -> None:
        """确保 eligibility、risk 和排除原因彼此一致。"""

        if self.eligible:
            if self.exclusion_reason != "eligible":
                raise ValueError("eligible VCD risk point 的原因必须是 eligible")
            if self.risk_mm is None or not math.isfinite(self.risk_mm) or self.risk_mm < 0.0:
                raise ValueError("eligible VCD risk 必须是有限非负毫米值")
        elif self.risk_mm is not None or self.exclusion_reason == "eligible":
            raise ValueError("被排除的 VCD risk point 必须保留空 risk 和明确原因")


@dataclass(frozen=True, slots=True)
class VcdCurvePoint:
    """表示一个 tie-group coverage 上的 VCD 或随机参考风险。"""

    scenario_id: str
    """曲线场景，固定为遮挡恢复。"""

    reference_kind: str
    """曲线来源，取 vcd 或 random。"""

    risk_kind: str
    """风险汇总，取 mean 或 tail_pninetyfive。"""

    point_index: int
    """按 VCD threshold 降序排列的零基稳定点序号。"""

    threshold: float | None
    """VCD 分数阈值；随机参考没有阈值。"""

    coverage: float
    """累计候选数除以 eligible received candidate 分母。"""

    risk_mm: float
    """当前 coverage 的风险，单位毫米。"""

    group_count: int
    """当前 VCD tie group 新纳入的候选数。"""

    cumulative_count: int
    """当前 coverage 累计纳入候选数。"""

    coverage_denominator: int
    """eligible received candidate 总数。"""

    input_workbook_sha256: str
    """一个工作簿 hash 或稳定输入 hash 集合摘要。"""

    def __post_init__(self) -> None:
        """校验曲线维度、计数、coverage、风险和来源 hash。"""

        if self.reference_kind not in {"vcd", "random"}:
            raise ValueError("VCD curve reference_kind 非法")
        if self.risk_kind not in {"mean", "tail_pninetyfive"}:
            raise ValueError("VCD curve risk_kind 非法")
        if self.point_index < 0 or self.group_count < 1:
            raise ValueError("VCD curve point index 或 tie group 数非法")
        if not 1 <= self.cumulative_count <= self.coverage_denominator:
            raise ValueError("VCD curve 累计计数非法")
        if not math.isclose(
            self.coverage,
            self.cumulative_count / self.coverage_denominator,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("VCD curve coverage 与计数不一致")
        if not math.isfinite(self.risk_mm) or self.risk_mm < 0.0:
            raise ValueError("VCD curve risk 必须有限且非负")
        if self.reference_kind == "vcd" and self.threshold is None:
            raise ValueError("VCD 曲线点必须保存 threshold")
        if self.reference_kind == "random" and self.threshold is not None:
            raise ValueError("随机参考曲线不得伪造 VCD threshold")
        if not _SHA256_PATTERN.fullmatch(self.input_workbook_sha256):
            raise ValueError("VCD curve 来源 hash 格式错误")


@dataclass(frozen=True, slots=True)
class VcdAurcRow:
    """保存 mean-risk 右阶梯 AURC 与完整候选 cohort 审计计数。"""

    scenario_id: str
    """AURC 场景，固定为遮挡恢复。"""

    reference_kind: str
    """AURC 来源，取 vcd 或 random。"""

    risk_kind: str
    """AURC 风险类型，Task 8 主指标固定为 mean。"""

    aurc_mm: float
    """从 coverage 0 到 1 的右阶梯面积，单位毫米。"""

    candidate_count: int
    """进入曲线的 eligible candidate 数。"""

    coverage_denominator: int
    """coverage 分母，与 candidate_count 相同。"""

    arrived_count: int
    """实际到达 Unity 的完整 EgoAnchor candidate 总数。"""

    excluded_no_aligned_count: int
    """因没有 aligned raw pose 排除的候选数。"""

    excluded_missing_reference_count: int
    """因没有同 frame reference 排除的候选数。"""

    excluded_invalid_reference_count: int
    """因 reference_pose_valid 为 false 排除的候选数。"""

    excluded_non_finite_pose_count: int
    """因 aligned/reference 位置非有限排除的候选数。"""

    input_workbook_sha256: str
    """一个工作簿 hash 或稳定输入 hash 集合摘要。"""


@dataclass(frozen=True, slots=True)
class VcdSensitivityRow:
    """表示 candidate cohort 变化对 mean-risk AURC 的影响。"""

    scenario_id: str
    """敏感性场景，固定为遮挡恢复。"""

    metric_key: str
    """被冻结比较的指标键。"""

    parameter_name: str
    """敏感性参数，固定为 candidate_cohort。"""

    alternative_id: str
    """替代 cohort 的稳定行标识。"""

    base_setting: str
    """主分析 cohort，固定为 completed_trial。"""

    alternative_setting: str
    """替代 cohort，取 marker_covered 或 occlusion_only。"""

    base_value: float
    """主 cohort 的 mean-risk AURC。"""

    alternative_value: float | None
    """替代 cohort 的 mean-risk AURC；样本不足时为空。"""

    delta: float | None
    """替代值减主值；替代 cohort 样本不足时为空。"""

    input_workbook_sha256: str
    """一个工作簿 hash 或稳定输入 hash 集合摘要。"""


@dataclass(frozen=True, slots=True)
class VcdAnalysisResult:
    """保存 Task 8 交给 Task 9 发布的 VCD 结构化结果。"""

    risk_points: tuple[VcdRiskPoint, ...]
    """所有实际到达候选及其 eligibility 审计。"""

    curve: tuple[VcdCurvePoint, ...]
    """VCD 与精确随机参考的 mean/P95 risk-coverage 曲线。"""

    aurc: tuple[VcdAurcRow, ...]
    """VCD 与随机参考的 mean-risk AURC。"""

    sensitivity: tuple[VcdSensitivityRow, ...]
    """marker-covered 与 occlusion-only cohort 敏感性。"""

    operating_accepted_count: int
    """实际 admission=accepted 且 risk eligible 的候选数。"""

    operating_eligible_count: int
    """全部 risk eligible 到达候选数。"""

    operating_coverage: float
    """实际接纳 eligible 子集占 eligible 候选的比例。"""

    operating_tail_risk_mm: float | None
    """实际接纳 eligible 子集的 candidate-level P95 risk。"""

    operating_input_workbook_sha256: str
    """全部 operating-point eligible 输入工作簿的集合 hash。"""


def _risk_point(candidate: VcdCandidate, params: AnalysisParameters) -> VcdRiskPoint:
    """计算一个已到达候选的 risk 或稳定排除原因。

    参数：
        candidate: 完整 EgoAnchor admission 与 reference 联接结果。
        params: 唯一冻结分析参数。
    """

    if candidate.variant_id != VCD_FULL_VARIANT_ID:
        raise ValueError("VCD risk-coverage 只能使用完整 EgoAnchor candidate")
    if not math.isfinite(candidate.vcd_score) or not (
        params.vcd_score_minimum <= candidate.vcd_score <= params.vcd_score_maximum
    ):
        raise ValueError("VCD candidate 分数必须有限且位于 [0, 1]")
    reason = "eligible"
    risk_mm: float | None = None
    if not candidate.has_aligned_raw:
        reason = "no_aligned_raw"
    elif candidate.reference_frame_id is None or candidate.reference_session_id is None:
        reason = "missing_reference"
    elif (
        candidate.reference_session_id != candidate.session_id
        or candidate.reference_frame_id != candidate.frame_id
    ):
        raise ValueError("VCD reference 必须按相同 session 与 frame_id 联接")
    elif candidate.reference_pose_valid is not True:
        reason = "invalid_reference"
    else:
        aligned = np.asarray(candidate.aligned_raw_position_m, dtype=np.float64)
        reference = np.asarray(candidate.reference_position_m, dtype=np.float64)
        if not np.all(np.isfinite(aligned)) or not np.all(np.isfinite(reference)):
            reason = "non_finite_pose"
        else:
            risk_mm = float(np.linalg.norm(aligned - reference) * 1000.0)
    return VcdRiskPoint(
        session_id=candidate.session_id,
        experiment_id="exp2_design_attribution",
        scenario_id=candidate.scenario_id,
        trial_id=candidate.trial_id,
        candidate_id=candidate.candidate_id,
        frame_id=candidate.frame_id,
        source_capture_mono_ms=candidate.source_capture_mono_ms,
        variant_id=candidate.variant_id,
        admission_decision=candidate.admission_decision,
        vcd_score=float(candidate.vcd_score),
        risk_mm=risk_mm,
        eligible=reason == "eligible",
        exclusion_reason=reason,
        has_aligned_raw=candidate.has_aligned_raw,
        reference_pose_valid=candidate.reference_pose_valid,
        reference_session_id=candidate.reference_session_id,
        reference_frame_id=candidate.reference_frame_id,
        input_workbook_sha256=candidate.input_workbook_sha256,
    )


def _expected_order_statistic(
    sorted_population: np.ndarray,
    sample_size: int,
    order_index: int,
) -> float:
    """计算有限总体无放回样本指定顺序统计量的精确期望。

    参数：
        sorted_population: 升序排列的完整候选 risk。
        sample_size: 无放回随机子样本大小。
        order_index: 子样本内零基顺序统计量索引。
    """

    population_size = len(sorted_population)
    if not 1 <= sample_size <= population_size or not 0 <= order_index < sample_size:
        raise ValueError("随机参考顺序统计量参数非法")
    population_indices = np.arange(
        order_index,
        population_size - sample_size + order_index + 1,
        dtype=np.int64,
    )
    before = population_indices.astype(np.float64)
    after = (population_size - population_indices - 1).astype(np.float64)
    log_denominator = (
        gammaln(population_size + 1)
        - gammaln(sample_size + 1)
        - gammaln(population_size - sample_size + 1)
    )
    log_probabilities = (
        gammaln(before + 1)
        - gammaln(order_index + 1)
        - gammaln(before - order_index + 1)
        + gammaln(after + 1)
        - gammaln(sample_size - order_index)
        - gammaln(after - (sample_size - order_index - 1) + 1)
        - log_denominator
    )
    probabilities = np.exp(log_probabilities - np.max(log_probabilities))
    probabilities /= np.sum(probabilities)
    return float(np.dot(sorted_population[population_indices], probabilities))


def _expected_random_quantile(
    sorted_population: np.ndarray,
    sample_size: int,
    quantile: float,
) -> float:
    """计算无放回随机子样本 linear quantile 的精确期望。

    参数：
        sorted_population: 升序排列的完整候选 risk。
        sample_size: 当前 coverage 的累计候选数。
        quantile: 冻结 tail quantile。
    """

    position = (sample_size - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    fraction = position - lower
    lower_value = _expected_order_statistic(sorted_population, sample_size, lower)
    if upper == lower:
        return lower_value
    upper_value = _expected_order_statistic(sorted_population, sample_size, upper)
    return (1.0 - fraction) * lower_value + fraction * upper_value


def _curve_rows(
    eligible: Sequence[VcdRiskPoint],
    params: AnalysisParameters,
) -> tuple[VcdCurvePoint, ...]:
    """按精确 tie group 构造 VCD 与随机参考的 mean/P95 曲线。

    参数：
        eligible: risk 已定义的实际到达候选。
        params: 唯一冻结分析参数。
    """

    ordered = sorted(eligible, key=lambda row: (-row.vcd_score, row.session_id, row.candidate_id))
    denominator = len(ordered)
    if denominator < params.minimum_event_samples:
        raise ValueError("VCD risk-coverage 的 eligible candidate 数不足")
    source_hash = input_workbook_set_sha256(row.input_workbook_sha256 for row in ordered)
    all_risks = np.asarray([row.risk_mm for row in ordered], dtype=np.float64)
    sorted_population = np.sort(all_risks)
    random_mean = float(np.mean(all_risks))
    rows: list[VcdCurvePoint] = []
    start = 0
    point_index = 0
    while start < denominator:
        threshold = ordered[start].vcd_score
        end = start + 1
        while end < denominator and ordered[end].vcd_score == threshold:
            end += 1
        cumulative_risks = all_risks[:end]
        values = {
            ("vcd", "mean"): float(np.mean(cumulative_risks)),
            ("vcd", "tail_pninetyfive"): float(
                np.quantile(cumulative_risks, params.vcd_tail_quantile, method="linear")
            ),
            ("random", "mean"): random_mean,
            ("random", "tail_pninetyfive"): _expected_random_quantile(
                sorted_population,
                end,
                params.vcd_tail_quantile,
            ),
        }
        for (reference_kind, risk_kind), risk_mm in values.items():
            rows.append(
                VcdCurvePoint(
                    scenario_id=VCD_SCENARIO_ID,
                    reference_kind=reference_kind,
                    risk_kind=risk_kind,
                    point_index=point_index,
                    threshold=threshold if reference_kind == "vcd" else None,
                    coverage=end / denominator,
                    risk_mm=risk_mm,
                    group_count=end - start,
                    cumulative_count=end,
                    coverage_denominator=denominator,
                    input_workbook_sha256=source_hash,
                )
            )
        start = end
        point_index += 1
    return tuple(rows)


def _right_step_aurc(curve: Sequence[VcdCurvePoint]) -> float:
    """对一个 reference/risk 曲线执行从 coverage 0 开始的右阶梯积分。

    参数：
        curve: coverage 严格递增且最终为一的曲线点。
    """

    ordered = sorted(curve, key=lambda row: row.point_index)
    if not ordered or not math.isclose(ordered[-1].coverage, 1.0, abs_tol=1e-12):
        raise ValueError("AURC 曲线必须非空并覆盖到 1")
    previous = 0.0
    area = 0.0
    for row in ordered:
        if row.coverage <= previous:
            raise ValueError("AURC coverage 必须严格递增")
        area += (row.coverage - previous) * row.risk_mm
        previous = row.coverage
    return float(area)


def _mean_aurc(eligible: Sequence[VcdRiskPoint], params: AnalysisParameters) -> float:
    """计算一个 candidate cohort 的 VCD mean-risk AURC。

    参数：
        eligible: cohort 内 risk 可计算的候选。
        params: 唯一冻结分析参数。
    """

    curve = _curve_rows(eligible, params)
    mean_curve = [
        row for row in curve if row.reference_kind == "vcd" and row.risk_kind == "mean"
    ]
    return _right_step_aurc(mean_curve)


def _context_map(contexts: Iterable[VcdTrialContext]) -> dict[tuple[str, str], VcdTrialContext]:
    """建立唯一 trial context 映射并验证遮挡事件闭合。

    参数：
        contexts: 完成 trial 的显式 marker 上下文。
    """

    result: dict[tuple[str, str], VcdTrialContext] = {}
    for context in contexts:
        key = (context.session_id, context.trial_id)
        if key in result:
            raise ValueError("VCD trial context 主键重复")
        pair_occlusion_windows(context.markers, context.trial_end_ms)
        result[key] = context
    if not result:
        raise ValueError("VCD trial context 不能为空")
    return result


def _sensitivity_rows(
    points: Sequence[VcdRiskPoint],
    contexts: dict[tuple[str, str], VcdTrialContext],
    base_aurc: float,
    params: AnalysisParameters,
) -> tuple[VcdSensitivityRow, ...]:
    """计算 marker-covered 与 occlusion-only cohort 的 mean-risk AURC 敏感性。

    参数：
        points: 全部实际到达候选的 risk 审计行。
        contexts: 唯一完成 trial context 映射。
        base_aurc: completed-trial 主 cohort 的 mean-risk AURC。
        params: 唯一冻结分析参数。
    """

    alternatives: dict[str, list[VcdRiskPoint]] = {
        "marker_covered": [],
        "occlusion_only": [],
    }
    first_markers = {
        key: min(marker.mono_ms for marker in context.markers)
        for key, context in contexts.items()
    }
    hidden_windows = {
        key: pair_occlusion_windows(context.markers, context.trial_end_ms)
        for key, context in contexts.items()
    }
    for point in points:
        if not point.eligible:
            continue
        context_key = (point.session_id, point.trial_id)
        context = contexts[context_key]
        first_marker_ms = first_markers[context_key]
        if first_marker_ms <= point.source_capture_mono_ms < context.trial_end_ms:
            alternatives["marker_covered"].append(point)
        if any(
            window.occlusion_start_ms <= point.source_capture_mono_ms < window.visible_start_ms
            for window in hidden_windows[context_key]
        ):
            alternatives["occlusion_only"].append(point)

    source_hash = input_workbook_set_sha256(point.input_workbook_sha256 for point in points)
    rows: list[VcdSensitivityRow] = []
    for alternative_id in ("marker_covered", "occlusion_only"):
        alternative_points = alternatives[alternative_id]
        alternative_value = (
            _mean_aurc(alternative_points, params)
            if len(alternative_points) >= params.minimum_event_samples
            else None
        )
        rows.append(
            VcdSensitivityRow(
                scenario_id=VCD_SCENARIO_ID,
                metric_key="vcd_mean_risk_aurc_mm",
                parameter_name="candidate_cohort",
                alternative_id=alternative_id,
                base_setting="completed_trial",
                alternative_setting=alternative_id,
                base_value=base_aurc,
                alternative_value=alternative_value,
                delta=(alternative_value - base_aurc if alternative_value is not None else None),
                input_workbook_sha256=source_hash,
            )
        )
    return tuple(rows)


def analyze_vcd(
    candidates: Iterable[VcdCandidate],
    trial_contexts: Iterable[VcdTrialContext],
    params: AnalysisParameters,
) -> VcdAnalysisResult:
    """计算完整 EgoAnchor 的 VCD risk、曲线、AURC 与 cohort 敏感性。

    参数：
        candidates: Task 9 从完整 EgoAnchor admission 投影的已到达候选。
        trial_contexts: 完成遮挡 trial 的显式 marker 与结束边界。
        params: 唯一 TOML 解析得到的冻结分析参数。
    """

    materialized = tuple(candidates)
    if not materialized:
        raise ValueError("VCD candidate 输入不能为空")
    keys = [(candidate.session_id, candidate.candidate_id) for candidate in materialized]
    if len(keys) != len(set(keys)):
        raise ValueError("VCD candidate 主键重复")
    contexts = _context_map(trial_contexts)
    for candidate in materialized:
        if (candidate.session_id, candidate.trial_id) not in contexts:
            raise ValueError("VCD candidate 没有对应完成 trial context")

    points = tuple(
        sorted(
            (_risk_point(candidate, params) for candidate in materialized),
            key=lambda row: (row.session_id, row.candidate_id),
        )
    )
    eligible = tuple(point for point in points if point.eligible)
    curve = _curve_rows(eligible, params)
    mean_curves = {
        reference_kind: [
            row
            for row in curve
            if row.reference_kind == reference_kind and row.risk_kind == "mean"
        ]
        for reference_kind in ("vcd", "random")
    }
    counts = {
        reason: sum(point.exclusion_reason == reason for point in points)
        for reason in (
            "no_aligned_raw",
            "missing_reference",
            "invalid_reference",
            "non_finite_pose",
        )
    }
    source_hash = input_workbook_set_sha256(point.input_workbook_sha256 for point in points)
    aurc = tuple(
        VcdAurcRow(
            scenario_id=VCD_SCENARIO_ID,
            reference_kind=reference_kind,
            risk_kind="mean",
            aurc_mm=_right_step_aurc(mean_curves[reference_kind]),
            candidate_count=len(eligible),
            coverage_denominator=len(eligible),
            arrived_count=len(points),
            excluded_no_aligned_count=counts["no_aligned_raw"],
            excluded_missing_reference_count=counts["missing_reference"],
            excluded_invalid_reference_count=counts["invalid_reference"],
            excluded_non_finite_pose_count=counts["non_finite_pose"],
            input_workbook_sha256=source_hash,
        )
        for reference_kind in ("vcd", "random")
    )
    base_aurc = next(row.aurc_mm for row in aurc if row.reference_kind == "vcd")
    accepted = tuple(
        point
        for point in eligible
        if point.admission_decision.strip().lower() == "accepted"
    )
    accepted_risks = np.asarray(
        [point.risk_mm for point in accepted if point.risk_mm is not None],
        dtype=np.float64,
    )
    return VcdAnalysisResult(
        risk_points=points,
        curve=curve,
        aurc=aurc,
        sensitivity=_sensitivity_rows(points, contexts, base_aurc, params),
        operating_accepted_count=len(accepted),
        operating_eligible_count=len(eligible),
        operating_coverage=(len(accepted) / len(eligible)) if eligible else 0.0,
        operating_tail_risk_mm=(
            float(np.quantile(accepted_risks, params.vcd_tail_quantile, method="linear"))
            if len(accepted_risks)
            else None
        ),
        operating_input_workbook_sha256=input_workbook_set_sha256(
            point.input_workbook_sha256 for point in eligible
        ),
    )


__all__ = [
    "VCD_FULL_VARIANT_ID",
    "VCD_SCENARIO_ID",
    "VcdAnalysisResult",
    "VcdAurcRow",
    "VcdCandidate",
    "VcdCurvePoint",
    "VcdRiskPoint",
    "VcdSensitivityRow",
    "VcdTrialContext",
    "analyze_vcd",
]
