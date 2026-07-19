"""实验一四系统、五场景的 event-first 指标计算与分层汇总。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from ..contracts import SCENARIO_ORDER, get_metric_definition
from .metrics import (
    durable_recovery_time_ms,
    estimate_angular_lag,
    estimate_translation_lag,
    event_quantiles,
    median_iqr,
    motion_hold_ratio,
    pose_jump_quantiles,
    position_drift_mm,
    position_hp_rms_mm,
    post_stop_position_jitter_rms_mm,
    settling_time_ms,
    visible_response_ms,
)
from .lineage import input_workbook_set_sha256
from .params import AnalysisParameters
from .pose import rotation_error_deg, translation_error_mm
from .windows import (
    EventMarker,
    EventWindow,
    OcclusionWindow,
    build_event_windows,
    detect_reference_motion,
    pair_occlusion_windows,
)


EXP1_ID = "exp1_system_characterization"
"""实验一在 schema-v2 中使用的冻结实验标识。"""

EXP1_VARIANTS = (
    "Arrival-Hold",
    "Capture-Hold",
    "One-Euro Anchor",
    "EgoAnchor",
)
"""实验一仅允许进入结果的四个系统配置，顺序也是报告顺序。"""

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
"""工作簿 SHA-256 的规范小写十六进制格式。"""

FloatArray = NDArray[np.float64]
"""实验一内部统一使用的双精度数组类型。"""

BoolArray = NDArray[np.bool_]
"""实验一 pose、output 和状态掩码使用的布尔数组类型。"""


@dataclass(frozen=True, slots=True)
class Exp1Admission:
    """表示 Task 9 从 XLSX admission sheet 投影的一条实验一记录。"""

    candidate_id: str
    """跨 runtime 共用的稳定候选标识。"""

    variant_id: str
    """实际执行 admission 的 runtime 配置。"""

    source_capture_mono_ms: float
    """候选来源帧在 Unity 单调时钟中的采集时间代理。"""

    admission_decision: str
    """runtime 写出的 admission 决策文本。"""

    def __post_init__(self) -> None:
        """拒绝缺标识、非有限时间或空决策的 admission 投影。"""

        if not self.candidate_id or not self.variant_id or not self.admission_decision:
            raise ValueError("实验一 admission 的候选、variant 和决策不能为空")
        if not math.isfinite(self.source_capture_mono_ms):
            raise ValueError("实验一 admission 的采集时间必须是有限值")


@dataclass(frozen=True, slots=True)
class Exp1AlignmentObservation:
    """保存 admission 层采集时刻/到达时刻 raw pose 与同帧参考的联接。"""

    candidate_id: str
    """跨 runtime 共用的候选标识。"""

    variant_id: str
    """产生该 raw pose 的 runtime 配置。"""

    frame_id: int
    """候选对应的 Unity frame 标识。"""

    source_capture_mono_ms: float
    """候选来源帧的采集时间代理，单位毫秒。"""

    uses_capture_time_alignment: bool
    """该 variant 是否使用采集时刻世界对齐。"""

    has_aligned_raw: bool
    """采集时刻 raw pose 是否有效。"""

    aligned_raw_position_m: tuple[float, float, float]
    """采集时刻 raw 世界位置，单位米。"""

    aligned_raw_rotation: tuple[float, float, float, float]
    """采集时刻 raw 世界旋转，xyzw 四元数。"""

    has_arrival_time_raw: bool
    """到达时刻 raw pose 是否有效。"""

    arrival_time_raw_position_m: tuple[float, float, float]
    """到达时刻 raw 世界位置，单位米。"""

    arrival_time_raw_rotation: tuple[float, float, float, float]
    """到达时刻 raw 世界旋转，xyzw 四元数。"""

    reference_pose_valid: bool
    """同 frame 平台参考 pose 是否有效。"""

    reference_position_m: tuple[float, float, float]
    """同 frame 平台参考世界位置，单位米。"""

    reference_rotation: tuple[float, float, float, float]
    """同 frame 平台参考世界旋转，xyzw 四元数。"""

    admission_decision: str
    """该候选在 runtime 中记录的 admission 决策；raw 对齐指标不按此筛选。"""

    def __post_init__(self) -> None:
        """校验 raw 联接的标识、时间、frame 和 pose 维度。"""

        if not self.candidate_id or not self.variant_id or not self.admission_decision:
            raise ValueError("alignment observation 的标识和决策不能为空")
        if self.frame_id < 0 or not math.isfinite(self.source_capture_mono_ms):
            raise ValueError("alignment observation 的 frame/time 非法")
        for name, value, width in (
            ("aligned_raw_position_m", self.aligned_raw_position_m, 3),
            ("aligned_raw_rotation", self.aligned_raw_rotation, 4),
            ("arrival_time_raw_position_m", self.arrival_time_raw_position_m, 3),
            ("arrival_time_raw_rotation", self.arrival_time_raw_rotation, 4),
            ("reference_position_m", self.reference_position_m, 3),
            ("reference_rotation", self.reference_rotation, 4),
        ):
            if len(value) != width:
                raise ValueError(f"{name} 维度错误")


@dataclass(frozen=True, slots=True)
class Exp1RenderSeries:
    """保存同一 trial 与 variant 的时间对齐 render 序列。"""

    variant_id: str
    """render 序列所属系统配置。"""

    render_tick_ids: NDArray[np.int64]
    """Unity render tick 的严格递增整数标识。"""

    times_ms: FloatArray
    """Unity render 单调时间，单位毫秒。"""

    head_positions_m: FloatArray
    """头显世界位置，形状为 ``(N,3)``，单位米。"""

    head_rotations: FloatArray
    """头显世界 xyzw 四元数，形状为 ``(N,4)``。"""

    reference_pose_valid: BoolArray
    """同 tick 平台参考 pose 是否有效。"""

    reference_positions_m: FloatArray
    """平台参考世界位置，形状为 ``(N,3)``，单位米。"""

    reference_rotations: FloatArray
    """平台参考 xyzw 四元数，形状为 ``(N,4)``。"""

    reference_linear_speed_m_s: FloatArray
    """平台参考线速度，单位米每秒。"""

    reference_angular_speed_deg_s: FloatArray
    """平台参考角速度，单位度每秒。"""

    has_output_pose: BoolArray
    """runtime 在当前 tick 是否有 output pose。"""

    has_source_capture_timing: BoolArray
    """当前 output 是否带合法采集时间代理。"""

    source_capture_mono_ms: FloatArray
    """当前 output 来源帧的 Unity 采集时间代理。"""

    has_display_pose: BoolArray
    """用户当前是否实际看到 display pose，包括 hold-last。"""

    display_positions_m: FloatArray
    """display 世界位置，形状为 ``(N,3)``，单位米。"""

    display_rotations: FloatArray
    """display xyzw 四元数，形状为 ``(N,4)``。"""

    latest_static_locked: BoolArray
    """完整 EgoAnchor 的 StaticLock 运行时状态。"""

    def __post_init__(self) -> None:
        """归一化数组 dtype，并校验所有逐 tick 字段的形状和时间顺序。"""

        if not self.variant_id:
            raise ValueError("实验一 render variant 不能为空")
        times = np.asarray(self.times_ms, dtype=np.float64)
        ticks_raw = np.asarray(self.render_tick_ids)
        if times.ndim != 1 or len(times) < 2 or not np.all(np.isfinite(times)):
            raise ValueError("实验一 render 时间必须包含至少两个有限样本")
        if np.any(np.diff(times) <= 0.0):
            raise ValueError("实验一 render 时间必须严格递增")
        if ticks_raw.shape != times.shape or not np.issubdtype(ticks_raw.dtype, np.integer):
            raise ValueError("render_tick_ids 必须是与时间等长的整数序列")
        ticks = ticks_raw.astype(np.int64, copy=False)
        if np.any(np.diff(ticks) <= 0):
            raise ValueError("render_tick_ids 必须严格递增")

        count = len(times)
        vector_fields = {
            "head_positions_m": (self.head_positions_m, 3),
            "head_rotations": (self.head_rotations, 4),
            "reference_positions_m": (self.reference_positions_m, 3),
            "reference_rotations": (self.reference_rotations, 4),
            "display_positions_m": (self.display_positions_m, 3),
            "display_rotations": (self.display_rotations, 4),
        }
        for name, (raw_values, width) in vector_fields.items():
            values = np.asarray(raw_values, dtype=np.float64)
            if values.shape != (count, width):
                raise ValueError(f"{name} 必须是 ({count},{width}) 数组")
            object.__setattr__(self, name, values)

        scalar_fields = {
            "reference_linear_speed_m_s": self.reference_linear_speed_m_s,
            "reference_angular_speed_deg_s": self.reference_angular_speed_deg_s,
            "source_capture_mono_ms": self.source_capture_mono_ms,
        }
        for name, scalar_values in scalar_fields.items():
            float_values = np.asarray(scalar_values, dtype=np.float64)
            if float_values.shape != (count,):
                raise ValueError(f"{name} 必须与 render 时间等长")
            object.__setattr__(self, name, float_values)

        bool_fields = {
            "reference_pose_valid": self.reference_pose_valid,
            "has_output_pose": self.has_output_pose,
            "has_source_capture_timing": self.has_source_capture_timing,
            "has_display_pose": self.has_display_pose,
            "latest_static_locked": self.latest_static_locked,
        }
        for name, mask_values in bool_fields.items():
            bool_values = np.asarray(mask_values, dtype=np.bool_)
            if bool_values.shape != (count,):
                raise ValueError(f"{name} 必须与 render 时间等长")
            object.__setattr__(self, name, bool_values)

        object.__setattr__(self, "times_ms", times)
        object.__setattr__(self, "render_tick_ids", ticks)


@dataclass(frozen=True, slots=True)
class Exp1Trial:
    """表示已由 Task 9 XLSX loader 完成联接的一个正式 trial。"""

    session_id: str
    """trial 所属 schema-v2 session。"""

    experiment_id: str
    """冻结实验标识，实验一必须为 ``exp1_system_characterization``。"""

    scenario_id: str
    """五个正式物理场景之一。"""

    trial_id: str
    """session 内稳定 trial 标识。"""

    condition_id: str
    """日志记录的实验与场景条件标识。"""

    workbook_sha256: str
    """直接输入 Stage 1 XLSX 的 SHA-256。"""

    trial_end_ms: float
    """通过 lifecycle QC 的 trial 结束单调时间。"""

    markers: tuple[EventMarker, ...]
    """当前 trial 的显式 event markers。"""

    render_series: tuple[Exp1RenderSeries, ...]
    """当前 trial 的全部 runtime render 序列，可包含消融。"""

    admissions: tuple[Exp1Admission, ...] = ()
    """当前 trial 的 admission 记录，遮挡错误更新指标使用。"""

    alignment_observations: tuple[Exp1AlignmentObservation, ...] = ()
    """当前 trial 的 admission raw pose 与同帧参考联接，供组件归因使用。"""

    def __post_init__(self) -> None:
        """校验 trial 上下文、来源 hash、marker 和四系统矩阵。"""

        if self.experiment_id != EXP1_ID:
            raise ValueError(f"实验一 trial 使用了错误 experiment_id：{self.experiment_id}")
        if self.scenario_id not in SCENARIO_ORDER:
            raise ValueError(f"实验一 trial 使用了未知场景：{self.scenario_id}")
        if not self.session_id or not self.trial_id or not self.condition_id:
            raise ValueError("实验一 trial 的 session、trial 和 condition 不能为空")
        if not _SHA256_PATTERN.fullmatch(self.workbook_sha256):
            raise ValueError("实验一 workbook_sha256 必须是 64 位小写十六进制")
        if not math.isfinite(self.trial_end_ms):
            raise ValueError("实验一 trial_end_ms 必须是有限值")
        if not self.markers:
            raise ValueError("实验一完成 trial 必须至少包含一个 marker")
        for marker in self.markers:
            if (
                marker.session_id != self.session_id
                or marker.experiment_id != self.experiment_id
                or marker.scenario_id != self.scenario_id
                or marker.trial_id != self.trial_id
            ):
                raise ValueError("实验一 marker 不得跨 session、experiment、scenario 或 trial")
        variant_ids = [series.variant_id for series in self.render_series]
        if len(variant_ids) != len(set(variant_ids)):
            raise ValueError("同一实验一 trial 的 render variant 不得重复")
        missing = set(EXP1_VARIANTS) - set(variant_ids)
        if missing:
            raise ValueError(f"实验一 trial 缺少四个系统配置：{sorted(missing)}")


@dataclass(frozen=True, slots=True)
class MetricRow:
    """表示 event、trial 或 session 长表中的一个指标单元。"""

    session_id: str
    """结果所属 session。"""

    experiment_id: str
    """结果所属实验。"""

    scenario_id: str
    """结果所属物理场景。"""

    trial_id: str
    """结果所属 trial；session 级为空。"""

    event_id: str
    """结果所属 event；trial/session 级为空。"""

    condition_id: str
    """结果所属实验条件。"""

    variant_id: str
    """结果所属系统配置。"""

    metric_key: str
    """冻结指标目录中的稳定键。"""

    metric_value: float | None
    """指标值；无法恢复等定义内失败允许为空。"""

    metric_unit: str
    """冻结指标单位。"""

    aggregation_level: str
    """当前行的 event、trial 或 session 汇总语义。"""

    input_workbook_sha256: str
    """直接贡献该行的 Stage 1 XLSX SHA-256。"""

    def __post_init__(self) -> None:
        """校验指标目录、场景、单位、数值和来源 hash 一致。"""

        definition = get_metric_definition(self.metric_key)
        if self.scenario_id not in definition.scenarios:
            raise ValueError(f"指标 {self.metric_key} 不适用于场景 {self.scenario_id}")
        if self.metric_unit != definition.unit:
            raise ValueError(f"指标 {self.metric_key} 的单位不符合冻结目录")
        if self.metric_value is not None and not math.isfinite(self.metric_value):
            raise ValueError(f"指标 {self.metric_key} 不能写入非有限值")
        if not _SHA256_PATTERN.fullmatch(self.input_workbook_sha256):
            raise ValueError("指标行的 input_workbook_sha256 格式错误")


@dataclass(frozen=True, slots=True)
class ScenarioSummaryRow:
    """表示一个场景、variant 和指标的低样本量完整汇总。"""

    session_id: str
    """场景可能跨 session 汇总，因此固定为空。"""

    experiment_id: str
    """结果所属实验。"""

    scenario_id: str
    """当前独立汇总的物理场景。"""

    trial_id: str
    """场景跨 trial 汇总，因此固定为空。"""

    event_id: str
    """场景跨 event 汇总，因此固定为空。"""

    condition_id: str
    """实验与场景条件标识。"""

    variant_id: str
    """当前独立汇总的系统配置。"""

    metric_key: str
    """冻结指标目录中的稳定键。"""

    metric_value: float | None
    """存在有限结果时与 median 相等；全部尝试失败时为空。"""

    metric_unit: str
    """冻结指标单位。"""

    aggregation_level: str
    """场景汇总使用的 event 或 session 统计层级。"""

    input_workbook_sha256: str
    """唯一输入 hash，或多个贡献工作簿 hash 的稳定集合摘要。"""

    attempt_count: int
    """进入汇总的全部 event/segment 或 session 尝试数量。"""

    sample_count: int
    """全部尝试中得到有限指标值的数量。"""

    success_rate: float
    """有限指标值数量除以全部尝试数量。"""

    median: float | None
    """有限指标值的中位数；没有有限值时为空。"""

    q1: float | None
    """有限指标值的第一四分位数；没有有限值时为空。"""

    q3: float | None
    """有限指标值的第三四分位数；没有有限值时为空。"""

    iqr: float | None
    """第三四分位数与第一四分位数之差；没有有限值时为空。"""

    minimum: float | None
    """有限指标值的最小值；没有有限值时为空。"""

    maximum: float | None
    """有限指标值的最大值；没有有限值时为空。"""

    def __post_init__(self) -> None:
        """校验尝试计数、成功率和可空分布统计彼此一致。"""

        definition = get_metric_definition(self.metric_key)
        if self.scenario_id not in definition.scenarios or self.metric_unit != definition.unit:
            raise ValueError("场景汇总与冻结指标目录不一致")
        values = (self.metric_value, self.median, self.q1, self.q3, self.iqr, self.minimum, self.maximum)
        if self.attempt_count < 1 or not 0 <= self.sample_count <= self.attempt_count:
            raise ValueError("场景汇总的尝试数和有限样本数非法")
        expected_rate = self.sample_count / self.attempt_count
        if not math.isfinite(self.success_rate) or not math.isclose(
            self.success_rate,
            expected_rate,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("场景汇总的 success_rate 与计数不一致")
        if self.sample_count == 0:
            if any(value is not None for value in values):
                raise ValueError("没有有限样本时场景分布统计必须全部为空")
            if not _SHA256_PATTERN.fullmatch(self.input_workbook_sha256):
                raise ValueError("场景汇总的 input_workbook_sha256 格式错误")
            return
        if any(value is None or not math.isfinite(value) for value in values):
            raise ValueError("存在有限样本时场景分布统计必须完整且有限")
        assert self.metric_value is not None and self.median is not None
        assert self.q1 is not None and self.q3 is not None and self.iqr is not None
        assert self.minimum is not None and self.maximum is not None
        if not math.isclose(self.metric_value, self.median, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("scenario_summary 的 metric_value 必须等于 median")
        if not self.minimum <= self.q1 <= self.median <= self.q3 <= self.maximum:
            raise ValueError("场景汇总的范围、四分位数和中位数顺序错误")
        if not math.isclose(self.iqr, self.q3 - self.q1, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("场景汇总的 IQR 与四分位数不一致")
        if not _SHA256_PATTERN.fullmatch(self.input_workbook_sha256):
            raise ValueError("场景汇总的 input_workbook_sha256 格式错误")


@dataclass(frozen=True, slots=True)
class Exp1AnalysisResult:
    """保存 Task 7 交给 Task 9 发布的四张实验一结构化长表。"""

    event_metrics: tuple[MetricRow, ...]
    """每个 event、variant 和指标的原始统计点。"""

    trial_metrics: tuple[MetricRow, ...]
    """每个 trial、variant 和指标的 event 汇总。"""

    session_metrics: tuple[MetricRow, ...]
    """每个 session、scenario、variant 和指标的 trial 等权汇总。"""

    scenario_summary: tuple[ScenarioSummaryRow, ...]
    """每个 scenario、variant 和指标的 median、IQR 与范围。"""


def _finite_mask(*arrays: ArrayLike) -> BoolArray:
    """返回所有标量或向量数组逐行均有限的联合掩码。

    参数：
        arrays: 末维可不同、首维必须相同的数值数组。
    """

    masks: list[BoolArray] = []
    for raw_values in arrays:
        values = np.asarray(raw_values, dtype=np.float64)
        masks.append(np.isfinite(values) if values.ndim == 1 else np.all(np.isfinite(values), axis=1))
    if not masks:
        raise ValueError("有限值掩码至少需要一个数组")
    if len({mask.shape for mask in masks}) != 1:
        raise ValueError("有限值掩码输入的首维必须一致")
    return np.logical_and.reduce(masks)


def _pose_errors(series: Exp1RenderSeries, params: AnalysisParameters) -> tuple[FloatArray, FloatArray, BoolArray]:
    """计算整条序列的平移/旋转误差，并为无效行保留 NaN。

    参数：
        series: 同一 variant 的 render 序列。
        params: 唯一冻结分析参数。
    """

    valid = (
        series.has_display_pose
        & series.reference_pose_valid
        & _finite_mask(
            series.display_positions_m,
            series.reference_positions_m,
            series.display_rotations,
            series.reference_rotations,
        )
    )
    translation = np.full(len(series.times_ms), np.nan, dtype=np.float64)
    rotation = np.full(len(series.times_ms), np.nan, dtype=np.float64)
    translation[valid] = translation_error_mm(
        series.display_positions_m[valid],
        series.reference_positions_m[valid],
    )
    rotation[valid] = rotation_error_deg(
        series.display_rotations[valid],
        series.reference_rotations[valid],
        params.quaternion_norm_tolerance,
    )
    return translation, rotation, valid


def _window_indices(series: Exp1RenderSeries, start_ms: float, end_ms: float) -> NDArray[np.int64]:
    """返回落在半开 event 窗口内的 render 行索引。

    参数：
        series: 待切窗的 render 序列。
        start_ms: 包含的窗口起点。
        end_ms: 不包含的窗口终点。
    """

    indices = np.flatnonzero((series.times_ms >= start_ms) & (series.times_ms < end_ms)).astype(np.int64)
    if len(indices) < 2:
        raise ValueError(f"event 窗口 render 样本不足：[{start_ms}, {end_ms})")
    return indices


def _quantile(values: ArrayLike, params: AnalysisParameters) -> float:
    """对一个 event 内的有限标量计算冻结 P95。

    参数：
        values: event 内 frame 级标量。
        params: 唯一冻结分析参数。
    """

    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    return event_quantiles({"event": finite}, params.p95_quantile, params)["event"]


def _capture_alignment_raw_rows(
    trial: Exp1Trial,
    variant_id: str,
    window: EventWindow,
    params: AnalysisParameters,
) -> list[MetricRow]:
    """按 v1 语义计算 admission raw 对齐误差，而不是最终 display 误差。

    参数：
        trial: 已联接 workbook 的静止头动 trial。
        variant_id: 当前 runtime 配置。
        window: 当前 marker 定义的 event 窗口。
        params: 唯一冻结分析参数。

    说明：采集时刻对齐发生在 VCD、StaticLock 和时序合成之前，因此该组件
    必须比较 admission raw pose 与同 frame 平台参考。最终 display P95 仍由
    ``translation_event_pninetyfive_mm`` 保留为下游状态护栏，不能替代这里的
    组件近端测量。raw 指标不按 admission decision 筛选，以保持两 variant 的
    同候选比较和 v1 的阶段统计语义。
    """

    observations = tuple(
        observation
        for observation in trial.alignment_observations
        if observation.variant_id == variant_id
        and window.start_ms <= observation.source_capture_mono_ms < window.end_ms
    )
    if not observations:
        return []
    translation_values: list[float] = []
    rotation_values: list[float] = []
    for observation in observations:
        if not observation.reference_pose_valid:
            continue
        if observation.uses_capture_time_alignment:
            if not observation.has_aligned_raw:
                continue
            raw_position = observation.aligned_raw_position_m
            raw_rotation = observation.aligned_raw_rotation
        else:
            if not observation.has_arrival_time_raw:
                continue
            raw_position = observation.arrival_time_raw_position_m
            raw_rotation = observation.arrival_time_raw_rotation
        if not np.all(
            np.isfinite(
                np.asarray(
                    (*raw_position, *raw_rotation, *observation.reference_position_m, *observation.reference_rotation),
                    dtype=np.float64,
                )
            )
        ):
            continue
        translation_values.append(
            float(
                translation_error_mm(
                    np.asarray(raw_position, dtype=np.float64),
                    np.asarray(observation.reference_position_m, dtype=np.float64),
                )
            )
        )
        rotation_values.append(
            float(
                rotation_error_deg(
                    np.asarray(raw_rotation, dtype=np.float64),
                    np.asarray(observation.reference_rotation, dtype=np.float64),
                    params.quaternion_norm_tolerance,
                )
            )
        )
    return [
        _metric_row(
            trial,
            variant_id,
            window.marker.event_id,
            "capture_alignment_raw_translation_pninetyfive_mm",
            _quantile(translation_values, params) if translation_values else None,
        ),
        _metric_row(
            trial,
            variant_id,
            window.marker.event_id,
            "capture_alignment_raw_rotation_pninetyfive_deg",
            _quantile(rotation_values, params) if rotation_values else None,
        ),
    ]


def _metric_row(
    trial: Exp1Trial,
    variant_id: str,
    event_id: str,
    metric_key: str,
    metric_value: float | None,
    aggregation_level: str = "event",
) -> MetricRow:
    """按冻结指标目录构造一个可发布长表行。

    参数：
        trial: 指标来源 trial。
        variant_id: 指标所属系统配置。
        event_id: event 级标识；更高层级为空。
        metric_key: 冻结指标键。
        metric_value: 有限指标值或定义内允许的缺失值。
        aggregation_level: 当前结果的汇总层级说明。
    """

    definition = get_metric_definition(metric_key)
    return MetricRow(
        session_id=trial.session_id,
        experiment_id=trial.experiment_id,
        scenario_id=trial.scenario_id,
        trial_id=trial.trial_id,
        event_id=event_id,
        condition_id=trial.condition_id,
        variant_id=variant_id,
        metric_key=metric_key,
        metric_value=None if metric_value is None else float(metric_value),
        metric_unit=definition.unit,
        aggregation_level=aggregation_level,
        input_workbook_sha256=trial.workbook_sha256,
    )


def _common_event_rows(
    trial: Exp1Trial,
    series: Exp1RenderSeries,
    event_id: str,
    indices: NDArray[np.int64],
    params: AnalysisParameters,
) -> list[MetricRow]:
    """计算所有场景共享的 jump 和 output/display coverage。

    参数：
        trial: 指标来源 trial。
        series: 当前系统 render 序列。
        event_id: 当前 event 标识。
        indices: 当前 event 的 render 行索引。
        params: 唯一冻结分析参数。
    """

    jumps = pose_jump_quantiles(
        series.times_ms[indices],
        series.display_positions_m[indices],
        series.display_rotations[indices],
        series.has_display_pose[indices],
        params,
        render_tick_ids=series.render_tick_ids[indices],
    )
    values = {
        "jump_pninetyfive_mm": jumps.translation_p95_mm,
        "jump_pninetynine_mm": jumps.translation_p99_mm,
        "jump_pninetyfive_deg": jumps.rotation_p95_deg,
        "jump_pninetynine_deg": jumps.rotation_p99_deg,
        "display_coverage": float(np.mean(series.has_display_pose[indices])),
        "output_coverage": float(np.mean(series.has_output_pose[indices])),
    }
    return [
        _metric_row(trial, series.variant_id, event_id, key, value)
        for key, value in values.items()
    ]


def _static_rows(
    trial: Exp1Trial,
    series: Exp1RenderSeries,
    window: EventWindow,
    params: AnalysisParameters,
) -> list[MetricRow]:
    """计算静止头动 event 的主指标与冻结 guardrail。

    参数：
        trial: 静止头动 trial。
        series: 当前系统 render 序列。
        window: marker 定义的静止 event 窗口。
        params: 唯一冻结分析参数。
    """

    indices = _window_indices(series, window.start_ms, window.end_ms)
    translation, rotation, valid = _pose_errors(series, params)
    errors_m = series.display_positions_m - series.reference_positions_m
    valid_errors = errors_m[indices][valid[indices]]
    centered_errors_m = valid_errors - np.median(valid_errors, axis=0)
    centered_translation = 1000.0 * np.linalg.norm(centered_errors_m, axis=1)
    values = {
        "translation_event_pninetyfive_mm": _quantile(translation[indices], params),
        "centered_translation_pninetyfive_mm": _quantile(centered_translation, params),
        "position_hp_rms_mm": position_hp_rms_mm(
            series.times_ms[indices],
            errors_m[indices],
            valid[indices],
            params,
        ),
        "rotation_event_pninetyfive_deg": _quantile(rotation[indices], params),
        "absolute_translation_median_mm": float(np.median(translation[indices][np.isfinite(translation[indices])])),
        "position_drift_mm": position_drift_mm(
            series.times_ms[indices],
            errors_m[indices],
            valid[indices],
            params,
        ),
    }
    rows = [_metric_row(trial, series.variant_id, window.marker.event_id, key, value) for key, value in values.items()]
    rows.extend(_capture_alignment_raw_rows(trial, series.variant_id, window, params))
    rows.extend(_common_event_rows(trial, series, window.marker.event_id, indices, params))
    return rows


def _motion_indices(
    series: Exp1RenderSeries,
    indices: NDArray[np.int64],
    params: AnalysisParameters,
) -> tuple[NDArray[np.int64], float, float]:
    """在 marker 窗内检测参考运动，并返回运动行、起点和停止时间。

    参数：
        series: 当前系统 render 序列。
        indices: marker 窗口 render 行。
        params: 唯一冻结分析参数。
    """

    reference_valid = (
        series.reference_pose_valid[indices]
        & _finite_mask(
            series.reference_positions_m[indices],
            series.reference_rotations[indices],
            series.reference_linear_speed_m_s[indices],
            series.reference_angular_speed_deg_s[indices],
        )
    )
    reference_indices = indices[reference_valid]
    motion = detect_reference_motion(
        series.times_ms[reference_indices],
        series.reference_linear_speed_m_s[reference_indices],
        series.reference_angular_speed_deg_s[reference_indices],
        series.reference_positions_m[reference_indices],
        series.reference_rotations[reference_indices],
        params,
    )
    if motion is None:
        raise ValueError("transition_started 窗口没有检测到满足门槛的参考运动")
    motion_indices = indices[
        (series.times_ms[indices] >= motion.onset_ms)
        & (series.times_ms[indices] <= motion.stop_ms)
    ]
    if len(motion_indices) < params.minimum_event_samples:
        raise ValueError("参考运动窗口有效 render 样本不足")
    return motion_indices, motion.onset_ms, motion.stop_ms


def _state_transition_delay(
    times_ms: FloatArray,
    states: BoolArray,
    reference_ms: float,
    from_state: bool,
    to_state: bool,
) -> float | None:
    """计算参考时间后显式布尔状态首次发生指定切换的延迟。

    参数：
        times_ms: 同一 event 的严格递增 render 时间。
        states: 与时间等长的 runtime 状态。
        reference_ms: 延迟计时起点。
        from_state: 切换前状态。
        to_state: 切换后状态。
    """

    for index in range(1, len(times_ms)):
        if times_ms[index] >= reference_ms and states[index - 1] == from_state and states[index] == to_state:
            return float(times_ms[index] - reference_ms)
    return None


def _start_stop_rows(
    trial: Exp1Trial,
    series: Exp1RenderSeries,
    window: EventWindow,
    params: AnalysisParameters,
) -> list[MetricRow]:
    """计算起停 6DoF event 的响应、误差、沉降和状态诊断。

    参数：
        trial: 起停 6DoF trial。
        series: 当前系统 render 序列。
        window: transition_started marker 定义的搜索窗。
        params: 唯一冻结分析参数。
    """

    indices = _window_indices(series, window.start_ms, window.end_ms)
    motion_indices, onset_ms, stop_ms = _motion_indices(series, indices, params)
    translation, rotation, valid = _pose_errors(series, params)
    errors_m = series.display_positions_m - series.reference_positions_m
    values: dict[str, float | None] = {
        "visible_response_ms": visible_response_ms(
            series.times_ms[indices],
            series.display_positions_m[indices],
            series.display_rotations[indices],
            series.has_display_pose[indices],
            reference_onset_ms=onset_ms,
            params=params,
        ),
        "settling_time_ms": settling_time_ms(
            series.times_ms[indices],
            translation[indices],
            valid[indices],
            reference_stop_ms=stop_ms,
            params=params,
        ),
        "post_stop_position_jitter_rms_mm": post_stop_position_jitter_rms_mm(
            series.times_ms[indices],
            errors_m[indices],
            valid[indices],
            reference_stop_ms=stop_ms,
            params=params,
        ),
        "motion_hold_ratio": motion_hold_ratio(
            series.times_ms[motion_indices],
            series.display_positions_m[motion_indices],
            series.display_rotations[motion_indices],
            series.has_display_pose[motion_indices],
            params,
        ),
        "motion_translation_pninetyfive_mm": _quantile(translation[motion_indices], params),
        "start_stop_rotation_pninetyfive_deg": _quantile(rotation[motion_indices], params),
        "motion_translation_peak_mm": float(np.nanmax(translation[motion_indices])),
    }
    if series.variant_id == "EgoAnchor":
        values["unlock_time_ms"] = _state_transition_delay(
            series.times_ms[indices],
            series.latest_static_locked[indices],
            onset_ms,
            True,
            False,
        )
        values["relock_time_ms"] = _state_transition_delay(
            series.times_ms[indices],
            series.latest_static_locked[indices],
            stop_ms,
            False,
            True,
        )
    rows = [_metric_row(trial, series.variant_id, window.marker.event_id, key, value) for key, value in values.items()]
    rows.extend(_common_event_rows(trial, series, window.marker.event_id, indices, params))
    return rows


def _translation_rows(
    trial: Exp1Trial,
    series: Exp1RenderSeries,
    window: EventWindow,
    params: AnalysisParameters,
) -> list[MetricRow]:
    """计算持续平移 segment 的 P95、effective lag 和补偿残差。

    参数：
        trial: 持续平移 trial。
        series: 当前系统 render 序列。
        window: generic marker 定义的平移 segment。
        params: 唯一冻结分析参数。
    """

    indices = _window_indices(series, window.start_ms, window.end_ms)
    translation, _, valid = _pose_errors(series, params)
    lag = estimate_translation_lag(
        series.times_ms[indices],
        series.display_positions_m[indices],
        series.reference_positions_m[indices],
        valid[indices],
        params,
    )
    values = {
        "translation_event_pninetyfive_mm_continuous": _quantile(translation[indices], params),
        "effective_translation_lag_ms": lag.lag_ms,
        "translation_lag_residual_mm": lag.residual,
        "translation_lag_pninetyfive_residual_mm": lag.pninetyfive_residual,
    }
    rows = [_metric_row(trial, series.variant_id, window.marker.event_id, key, value) for key, value in values.items()]
    rows.extend(_common_event_rows(trial, series, window.marker.event_id, indices, params))
    return rows


def _rotation_rows(
    trial: Exp1Trial,
    series: Exp1RenderSeries,
    window: EventWindow,
    params: AnalysisParameters,
) -> list[MetricRow]:
    """计算持续旋转 segment 的 P95、effective angular lag 和残差。

    参数：
        trial: 持续旋转 trial。
        series: 当前系统 render 序列。
        window: generic marker 定义的旋转 segment。
        params: 唯一冻结分析参数。
    """

    indices = _window_indices(series, window.start_ms, window.end_ms)
    _, rotation, valid = _pose_errors(series, params)
    lag = estimate_angular_lag(
        series.times_ms[indices],
        series.display_rotations[indices],
        series.reference_rotations[indices],
        valid[indices],
        params,
    )
    values = {
        "rotation_event_pninetyfive_deg_continuous": _quantile(rotation[indices], params),
        "effective_angular_lag_ms": lag.lag_ms,
        "angular_lag_residual_deg": lag.residual,
        "angular_lag_pninetyfive_residual_deg": lag.pninetyfive_residual,
    }
    rows = [_metric_row(trial, series.variant_id, window.marker.event_id, key, value) for key, value in values.items()]
    rows.extend(_common_event_rows(trial, series, window.marker.event_id, indices, params))
    return rows


def _fresh_output_time_ms(
    series: Exp1RenderSeries,
    indices: NDArray[np.int64],
    target_visible_ms: float,
) -> float | None:
    """返回重新可见后首个采集时间同样新鲜的 output 延迟。

    参数：
        series: 当前系统 render 序列。
        indices: 恢复观察窗 render 行。
        target_visible_ms: 重新可见 marker 时间。
    """

    fresh = (
        series.has_output_pose[indices]
        & series.has_source_capture_timing[indices]
        & np.isfinite(series.source_capture_mono_ms[indices])
        & (series.source_capture_mono_ms[indices] >= target_visible_ms)
        & (series.times_ms[indices] >= target_visible_ms)
    )
    matches = indices[np.flatnonzero(fresh)]
    return None if not len(matches) else float(series.times_ms[matches[0]] - target_visible_ms)


def _error_update_count(
    admissions: Sequence[Exp1Admission],
    variant_id: str,
    window: OcclusionWindow,
) -> float:
    """统计遮挡采集窗内被 runtime 接纳的唯一 candidate 数。

    参数：
        admissions: 当前 trial 的 admission 投影。
        variant_id: 当前系统配置。
        window: 闭合遮挡窗口。
    """

    candidate_ids = {
        row.candidate_id
        for row in admissions
        if row.variant_id == variant_id
        and window.occlusion_start_ms <= row.source_capture_mono_ms < window.visible_start_ms
        and row.admission_decision.strip().lower() == "accepted"
    }
    return float(len(candidate_ids))


def _occlusion_rows(
    trial: Exp1Trial,
    series: Exp1RenderSeries,
    window: OcclusionWindow,
    params: AnalysisParameters,
) -> list[MetricRow]:
    """计算一组遮挡、重新可见与恢复观察窗的完整指标。

    参数：
        trial: 遮挡恢复 trial。
        series: 当前系统 render 序列。
        window: 严格闭合的遮挡恢复窗口。
        params: 唯一冻结分析参数。
    """

    full_indices = _window_indices(series, window.occlusion_start_ms, window.end_ms)
    hidden_indices = _window_indices(series, window.occlusion_start_ms, window.visible_start_ms)
    recovery_indices = _window_indices(series, window.visible_start_ms, window.end_ms)
    reappearance_end_ms = window.visible_start_ms + params.reappearance_window_ms
    reappearance_indices = None
    if window.end_ms >= reappearance_end_ms:
        reappearance_indices = _window_indices(
            series,
            window.visible_start_ms,
            reappearance_end_ms,
        )
    translation, rotation, valid = _pose_errors(series, params)
    recovery_time = durable_recovery_time_ms(
        series.times_ms[recovery_indices],
        translation[recovery_indices],
        valid[recovery_indices],
        series.has_output_pose[recovery_indices],
        series.has_source_capture_timing[recovery_indices],
        series.source_capture_mono_ms[recovery_indices],
        target_visible_ms=window.visible_start_ms,
        params=params,
    )
    occlusion_translation_p95 = _quantile(translation[hidden_indices], params)
    values: dict[str, float | None] = {
        "occlusion_translation_pninetyfive_mm": occlusion_translation_p95,
        "occlusion_catastrophic_failure_rate": float(
            occlusion_translation_p95 > params.occlusion_catastrophic_threshold_mm
        ),
        "occlusion_rotation_pninetyfive_deg": _quantile(rotation[hidden_indices], params),
        "occlusion_output_coverage": float(np.mean(series.has_output_pose[hidden_indices])),
        "reappearance_translation_pninetyfive_mm": (
            None
            if reappearance_indices is None
            else _quantile(translation[reappearance_indices], params)
        ),
        "durable_recovery_time_ms": recovery_time,
        "durable_recovery_success": 0.0 if recovery_time is None else 1.0,
        "fresh_output_time_ms": _fresh_output_time_ms(series, recovery_indices, window.visible_start_ms),
        "occlusion_error_update_count": _error_update_count(trial.admissions, series.variant_id, window),
    }
    rows = [_metric_row(trial, series.variant_id, window.event_id, key, value) for key, value in values.items()]
    rows.extend(_common_event_rows(trial, series, window.event_id, full_indices, params))
    return rows


def analyze_trial_events(
    trial: Exp1Trial,
    params: AnalysisParameters,
    variant_ids: Sequence[str] = EXP1_VARIANTS,
) -> tuple[MetricRow, ...]:
    """为指定 runtime 配置计算一个 trial 的全部 event 指标。

    参数：
        trial: 已联接且通过输入校验的实验一 trial。
        params: 唯一冻结分析参数。
        variant_ids: 需要计算的 runtime 配置；实验一默认使用四系统。
    """

    by_variant = {series.variant_id: series for series in trial.render_series}
    if not variant_ids or len(variant_ids) != len(set(variant_ids)):
        raise ValueError("event 指标投影的 variant 列表必须非空且唯一")
    missing_variants = set(variant_ids) - set(by_variant)
    if missing_variants:
        raise ValueError(f"trial 缺少请求的 runtime 配置：{sorted(missing_variants)}")
    rows: list[MetricRow] = []
    if trial.scenario_id == "occlusion_recovery":
        occlusion_windows = pair_occlusion_windows(trial.markers, trial.trial_end_ms)
        for occlusion_window in occlusion_windows:
            for variant_id in variant_ids:
                rows.extend(_occlusion_rows(trial, by_variant[variant_id], occlusion_window, params))
        return tuple(rows)

    event_windows = build_event_windows(trial.markers, trial.trial_end_ms)
    calculators: dict[
        str,
        Callable[[Exp1Trial, Exp1RenderSeries, EventWindow, AnalysisParameters], list[MetricRow]],
    ] = {
        "static_head_motion": _static_rows,
        "start_stop_6dof": _start_stop_rows,
        "continuous_translation": _translation_rows,
        "continuous_rotation": _rotation_rows,
    }
    calculator = calculators[trial.scenario_id]
    expected_role = "transition_started" if trial.scenario_id == "start_stop_6dof" else "generic_marker"
    selected_windows = tuple(window for window in event_windows if window.marker.role == expected_role)
    if not selected_windows:
        raise ValueError(f"场景 {trial.scenario_id} 缺少必需事件角色 {expected_role}")
    for event_window in selected_windows:
        for variant_id in variant_ids:
            rows.extend(calculator(trial, by_variant[variant_id], event_window, params))
    return tuple(rows)


def _aggregate_value(rows: Sequence[MetricRow], source_level: str) -> tuple[float | None, str]:
    """按指标语义计算相邻统计层级的聚合值。

    参数：
        rows: 同一上下文、variant 和 metric 的来源行。
        source_level: 来源行的 ``event`` 或 ``trial`` 层级。
    """

    values = np.asarray(
        [row.metric_value for row in rows if row.metric_value is not None],
        dtype=np.float64,
    )
    if not len(values):
        return None, f"{source_level}_missing"
    if rows[0].metric_key in {"durable_recovery_success", "occlusion_catastrophic_failure_rate"}:
        return float(np.mean(values)), f"{source_level}_proportion"
    return float(np.median(values)), f"{source_level}_median"


def aggregate_metric_rows(
    source_rows: Sequence[MetricRow],
    level: str,
    variant_order: Sequence[str] = EXP1_VARIANTS,
) -> tuple[MetricRow, ...]:
    """从相邻下层结果生成 trial 或 session 长表。

    参数：
        source_rows: trial 聚合使用 event 行，session 聚合使用 trial 行。
        level: 只能是 ``trial`` 或 ``session``。
        variant_order: 当前分析允许的稳定 runtime 报告顺序。
    """

    if level not in {"trial", "session"}:
        raise ValueError("实验一聚合层级只能是 trial 或 session")
    if not variant_order or len(variant_order) != len(set(variant_order)):
        raise ValueError("指标聚合的 variant 顺序必须非空且唯一")
    source_level = "event" if level == "trial" else "trial"
    groups: dict[tuple[str, ...], list[MetricRow]] = {}
    for row in source_rows:
        key = (
            row.session_id,
            row.scenario_id,
            *( (row.trial_id,) if level == "trial" else () ),
            row.variant_id,
            row.metric_key,
        )
        groups.setdefault(key, []).append(row)

    aggregated: list[MetricRow] = []
    for rows in groups.values():
        first = rows[0]
        value, method = _aggregate_value(rows, source_level)
        aggregated.append(
            MetricRow(
                session_id=first.session_id,
                experiment_id=first.experiment_id,
                scenario_id=first.scenario_id,
                trial_id=first.trial_id if level == "trial" else "",
                event_id="",
                condition_id=first.condition_id,
                variant_id=first.variant_id,
                metric_key=first.metric_key,
                metric_value=value,
                metric_unit=first.metric_unit,
                aggregation_level=f"{level}_{method}",
                input_workbook_sha256=first.input_workbook_sha256,
            ),
        )
    return tuple(sorted(aggregated, key=lambda row: _metric_sort_key(row, variant_order)))


def _scenario_rows(
    event_rows: Sequence[MetricRow],
    session_rows: Sequence[MetricRow],
    params: AnalysisParameters,
) -> tuple[ScenarioSummaryRow, ...]:
    """生成不跨场景的尝试计数、成功率、median、IQR 和范围。

    参数：
        event_rows: 全部 event 指标点。
        session_rows: durable recovery success 的 session 比例来源。
        params: 唯一冻结分析参数。
    """

    sources = [row for row in event_rows if row.metric_key != "durable_recovery_success"]
    sources.extend(row for row in session_rows if row.metric_key == "durable_recovery_success")
    groups: dict[tuple[str, str, str], list[MetricRow]] = {}
    for row in sources:
        groups.setdefault((row.scenario_id, row.variant_id, row.metric_key), []).append(row)

    summaries: list[ScenarioSummaryRow] = []
    for (scenario_id, variant_id, metric_key), rows in groups.items():
        values = [row.metric_value for row in rows if row.metric_value is not None]
        definition = get_metric_definition(metric_key)
        stats = median_iqr(values, params) if values else None
        summaries.append(
            ScenarioSummaryRow(
                session_id="",
                experiment_id=EXP1_ID,
                scenario_id=scenario_id,
                trial_id="",
                event_id="",
                condition_id=f"{EXP1_ID}/{scenario_id}",
                variant_id=variant_id,
                metric_key=metric_key,
                metric_value=stats.median if stats is not None else None,
                metric_unit=definition.unit,
                aggregation_level=(
                    "scenario_session_median_iqr"
                    if metric_key == "durable_recovery_success"
                    else "scenario_event_median_iqr"
                ),
                input_workbook_sha256=input_workbook_set_sha256(
                    row.input_workbook_sha256 for row in rows
                ),
                attempt_count=len(rows),
                sample_count=len(values),
                success_rate=len(values) / len(rows),
                median=stats.median if stats is not None else None,
                q1=stats.q1 if stats is not None else None,
                q3=stats.q3 if stats is not None else None,
                iqr=stats.iqr if stats is not None else None,
                minimum=float(np.min(values)) if values else None,
                maximum=float(np.max(values)) if values else None,
            ),
        )
    return tuple(sorted(summaries, key=_summary_sort_key))


def _metric_sort_key(
    row: MetricRow,
    variant_order: Sequence[str] = EXP1_VARIANTS,
) -> tuple[object, ...]:
    """返回 event/trial/session 长表的稳定排序键。

    参数：
        row: 待排序指标行。
        variant_order: 当前结果允许的稳定 runtime 报告顺序。
    """

    return (
        SCENARIO_ORDER.index(row.scenario_id),
        row.session_id,
        row.trial_id,
        row.event_id,
        variant_order.index(row.variant_id),
        row.metric_key,
    )


def _summary_sort_key(row: ScenarioSummaryRow) -> tuple[object, ...]:
    """返回场景汇总表的稳定排序键。

    参数：
        row: 待排序场景汇总行。
    """

    return (
        SCENARIO_ORDER.index(row.scenario_id),
        EXP1_VARIANTS.index(row.variant_id),
        row.metric_key,
    )


def analyze_exp1(
    trials: Iterable[Exp1Trial],
    params: AnalysisParameters,
) -> Exp1AnalysisResult:
    """计算实验一五场景并返回 Task 9 将发布的四张结构化结果表。

    参数：
        trials: Task 9 从 Stage 1 XLSX 联接得到的完成 trial；不得来自原始 JSONL。
        params: 唯一 TOML 解析得到的冻结分析参数。
    """

    materialized = tuple(trials)
    if not materialized:
        raise ValueError("实验一分析输入不能为空")
    scenarios = {trial.scenario_id for trial in materialized}
    if scenarios != set(SCENARIO_ORDER):
        missing = set(SCENARIO_ORDER) - scenarios
        extra = scenarios - set(SCENARIO_ORDER)
        raise ValueError(f"实验一批次必须覆盖五个场景；缺少={sorted(missing)}，额外={sorted(extra)}")
    trial_keys = [(trial.session_id, trial.trial_id) for trial in materialized]
    if len(trial_keys) != len(set(trial_keys)):
        raise ValueError("实验一批次包含重复 session/trial")

    event_rows = tuple(
        sorted(
            (row for trial in materialized for row in analyze_trial_events(trial, params)),
            key=_metric_sort_key,
        ),
    )
    trial_rows = aggregate_metric_rows(event_rows, "trial")
    session_rows = aggregate_metric_rows(trial_rows, "session")
    return Exp1AnalysisResult(
        event_metrics=event_rows,
        trial_metrics=trial_rows,
        session_metrics=session_rows,
        scenario_summary=_scenario_rows(event_rows, session_rows, params),
    )


__all__ = [
    "EXP1_ID",
    "EXP1_VARIANTS",
    "Exp1Admission",
    "Exp1AlignmentObservation",
    "Exp1AnalysisResult",
    "Exp1RenderSeries",
    "Exp1Trial",
    "MetricRow",
    "ScenarioSummaryRow",
    "aggregate_metric_rows",
    "analyze_exp1",
    "analyze_trial_events",
]
