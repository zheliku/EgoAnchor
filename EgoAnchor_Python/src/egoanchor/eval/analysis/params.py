"""读取并校验实验一/二唯一冻结分析参数。"""

from __future__ import annotations

import hashlib
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_ANALYSIS_PARAMS_PATH = Path(__file__).resolve().parents[1] / "config" / "analysis_params.toml"
"""仓库内唯一冻结分析参数文件路径。"""


_PARAMETER_KEYS = {
    "contract": {"version", "unit_system", "statistics_unit", "quantile_method", "invalid_sample_policy", "event_summary"},
    "metrics": {"p95_quantile", "p99_quantile", "minimum_event_samples", "maximum_gap_factor", "drift_window_ms"},
    "hp_rms": {"filter_type", "filter_order", "cutoff_hz", "zero_phase", "resample_method", "minimum_samples"},
    "reference_motion": {"linear_speed_m_s", "angular_speed_deg_s", "speed_median_frames", "minimum_duration_ms", "minimum_translation_excursion_mm", "minimum_rotation_excursion_deg"},
    "visible_response": {"baseline_ms", "position_threshold_mm", "rotation_threshold_deg", "duration_ms"},
    "lag": {"minimum_ms", "maximum_ms", "step_ms", "interpolation", "objective", "tie_break", "minimum_overlap_samples", "minimum_overlap_fraction"},
    "thresholds": {"pose_quaternion_norm_tolerance", "vcd_score_minimum", "vcd_score_maximum", "recovery_position_tolerance_mm", "recovery_duration_ms", "settling_position_tolerance_mm", "settling_duration_ms"},
    "recovery": {"start_role", "requires_fresh_output", "freshness_field", "freshness_clock"},
    "latency": {"candidate_arrival_clock", "python_processing_clock", "cross_clock_policy", "negative_duration_policy"},
    "vcd": {
        "coverage_group_tie",
        "risk_unit",
        "alignment_source",
        "coverage_denominator",
        "score_equality",
        "mean_risk",
        "tail_quantile",
        "aurc_integration",
        "random_reference",
        "sensitivity_cohorts",
    },
}
"""分析参数各 section 允许出现的完整键集合。"""

_BOOLEAN_PARAMETERS = {("hp_rms", "zero_phase"), ("recovery", "requires_fresh_output")}
"""必须使用 TOML 布尔类型的参数。"""

_INTEGER_PARAMETERS = {
    ("contract", "version"),
    ("metrics", "minimum_event_samples"),
    ("hp_rms", "filter_order"),
    ("hp_rms", "minimum_samples"),
    ("reference_motion", "speed_median_frames"),
    ("lag", "minimum_overlap_samples"),
}
"""必须使用 TOML 整数且禁止布尔值冒充的参数。"""

_STRING_PARAMETERS = {
    ("contract", "unit_system"),
    ("contract", "statistics_unit"),
    ("contract", "quantile_method"),
    ("contract", "invalid_sample_policy"),
    ("contract", "event_summary"),
    ("hp_rms", "filter_type"),
    ("hp_rms", "resample_method"),
    ("lag", "interpolation"),
    ("lag", "objective"),
    ("lag", "tie_break"),
    ("recovery", "start_role"),
    ("recovery", "freshness_field"),
    ("recovery", "freshness_clock"),
    ("latency", "candidate_arrival_clock"),
    ("latency", "python_processing_clock"),
    ("latency", "cross_clock_policy"),
    ("latency", "negative_duration_policy"),
    ("vcd", "coverage_group_tie"),
    ("vcd", "risk_unit"),
    ("vcd", "alignment_source"),
    ("vcd", "coverage_denominator"),
    ("vcd", "score_equality"),
    ("vcd", "mean_risk"),
    ("vcd", "aurc_integration"),
    ("vcd", "random_reference"),
    ("vcd", "sensitivity_cohorts"),
}
"""必须使用 TOML 文本类型的参数。"""


@dataclass(frozen=True, slots=True)
class AnalysisParameters:
    """保存 Task 6 公共指标和 Task 8 VCD 分析使用的冻结参数。"""

    contract_version: int
    """分析参数契约版本。"""

    unit_system: str
    """冻结单位系统。"""

    statistics_unit: str
    """统计单位语义。"""

    quantile_method: str
    """经验分位数插值方法。"""

    invalid_sample_policy: str
    """无效样本处理策略。"""

    event_summary: str
    """event/segment 层汇总方法。"""

    p95_quantile: float
    """event 内 P95 分位点。"""

    p99_quantile: float
    """event 内 P99 分位点。"""

    minimum_event_samples: int
    """普通 event 指标最少有效样本数。"""

    maximum_gap_factor: float
    """连续时间片段允许的最大间隔倍数。"""

    drift_window_ms: float
    """漂移首尾均值时窗长度。"""

    hp_filter_type: str
    """HP-RMS 滤波器类型。"""

    hp_filter_order: int
    """HP-RMS 滤波器阶数。"""

    hp_cutoff_hz: float
    """HP-RMS 高通截止频率。"""

    hp_zero_phase: bool
    """是否使用零相位前向后向滤波。"""

    hp_resample_method: str
    """HP-RMS 重采样方法。"""

    hp_minimum_samples: int
    """可滤波连续片段的最少样本数。"""

    reference_linear_speed_m_s: float
    """参考平移运动速度阈值。"""

    reference_angular_speed_deg_s: float
    """参考旋转运动速度阈值。"""

    reference_speed_median_frames: int
    """参考速度中值滤波帧数。"""

    reference_motion_duration_ms: float
    """参考运动 bout 最短持续时间。"""

    reference_translation_excursion_mm: float
    """参考运动最小平移位移。"""

    reference_rotation_excursion_deg: float
    """参考运动最小旋转位移。"""

    response_baseline_ms: float
    """visible response 的运动前基线长度。"""

    response_position_mm: float
    """display 平移响应阈值。"""

    response_rotation_deg: float
    """display 旋转响应阈值。"""

    response_duration_ms: float
    """display 响应最短持续时间。"""

    lag_min_ms: float
    """effective lag 搜索下界。"""

    lag_max_ms: float
    """effective lag 搜索上界。"""

    lag_step_ms: float
    """effective lag 搜索步长。"""

    lag_interpolation: str
    """lag 对齐插值方法。"""

    lag_objective: str
    """lag 优化目标。"""

    lag_tie_break: str
    """lag 并列候选处理方法。"""

    lag_minimum_overlap_samples: int
    """lag 候选最少重叠样本数。"""

    lag_minimum_overlap_fraction: float
    """lag 候选最少重叠比例。"""

    quaternion_norm_tolerance: float
    """四元数范数检查容差。"""

    vcd_score_minimum: float
    """VCD 合法分数下界。"""

    vcd_score_maximum: float
    """VCD 合法分数上界。"""

    recovery_position_mm: float
    """durable recovery 平移误差阈值。"""

    recovery_duration_ms: float
    """durable recovery 持续时间。"""

    settling_position_mm: float
    """settling 平移误差阈值。"""

    settling_duration_ms: float
    """settling 持续时间。"""

    recovery_start_role: str
    """恢复计时起点的事件角色。"""

    recovery_requires_fresh_output: bool
    """恢复是否要求遮挡后的新鲜输出。"""

    recovery_freshness_field: str
    """恢复 freshness 使用的字段。"""

    recovery_freshness_clock: str
    """恢复 freshness 字段所属时钟。"""

    candidate_arrival_clock: str
    """candidate arrival 所属时钟。"""

    python_processing_clock: str
    """Python processing 所属时钟。"""

    cross_clock_policy: str
    """跨单调时钟相减策略。"""

    negative_duration_policy: str
    """负时延处理策略。"""

    vcd_coverage_group_tie: str
    """VCD 并列分数组纳入策略。"""

    vcd_risk_unit: str
    """VCD risk 单位。"""

    vcd_alignment_source: str
    """VCD risk 位姿来源。"""

    vcd_coverage_denominator: str
    """VCD coverage 分母语义。"""

    vcd_score_equality: str
    """VCD 分数并列判断方法。"""

    vcd_mean_risk: str
    """VCD 主 risk 的汇总方法。"""

    vcd_tail_quantile: float
    """VCD tail-risk 曲线的分位点。"""

    vcd_aurc_integration: str
    """VCD AURC 的积分规则。"""

    vcd_random_reference: str
    """VCD 随机参考的可复现算法。"""

    vcd_sensitivity_cohorts: str
    """VCD 敏感性分析使用的候选 cohort 集合。"""


def _section(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    """返回必需 TOML section，缺失或类型错误时立即失败。

    参数：
        config: 已解析的 TOML 根映射。
        name: 需要读取的 section 名称。
    """

    value = config.get(name)
    if not isinstance(value, Mapping):
        raise ValueError(f"分析参数缺少 [{name}] section")
    return value


def _validate_structure(config: Mapping[str, Any]) -> None:
    """严格拒绝未知、缺失或 TOML 类型错误的参数。

    参数：
        config: 已解析的 TOML 根映射。
    """

    sections = set(config)
    expected_sections = set(_PARAMETER_KEYS)
    unknown_sections = sorted(sections - expected_sections)
    missing_sections = sorted(expected_sections - sections)
    if unknown_sections:
        raise ValueError(f"分析参数包含未知 section：{unknown_sections}")
    if missing_sections:
        raise ValueError(f"分析参数缺少 section：{missing_sections}")
    for section_name, expected_keys in _PARAMETER_KEYS.items():
        section = _section(config, section_name)
        keys = set(section)
        unknown = sorted(keys - expected_keys)
        missing = sorted(expected_keys - keys)
        if unknown:
            raise ValueError(f"[{section_name}] 包含未知参数：{unknown}")
        if missing:
            raise ValueError(f"[{section_name}] 缺少参数：{missing}")
        for key, value in section.items():
            identity = (section_name, key)
            if identity in _BOOLEAN_PARAMETERS:
                valid = isinstance(value, bool)
            elif identity in _INTEGER_PARAMETERS:
                valid = isinstance(value, int) and not isinstance(value, bool)
            elif identity in _STRING_PARAMETERS:
                valid = isinstance(value, str)
            else:
                valid = isinstance(value, (int, float)) and not isinstance(value, bool)
            if not valid:
                raise ValueError(f"[{section_name}].{key} 的 TOML 类型错误")


def _require_positive(value: float, name: str, *, allow_zero: bool = False) -> None:
    """校验参数为有限正数，允许时接受零。

    参数：
        value: 待检查的数值。
        name: 报错时使用的参数名。
        allow_zero: 是否允许数值等于零。
    """

    valid = math.isfinite(value) and (value >= 0.0 if allow_zero else value > 0.0)
    if not valid:
        qualifier = "非负" if allow_zero else "正"
        raise ValueError(f"{name} 必须是有限{qualifier}数")


def _validate_contract(params: AnalysisParameters) -> None:
    """检查参数版本、单位、统计层级和分位数语义。

    参数：
        params: 已完成字段映射的冻结参数。
    """

    if params.contract_version != 3:
        raise ValueError("Task 8 只接受 analysis_params v3")
    if params.unit_system != "metric" or params.statistics_unit != "event_segment":
        raise ValueError("单位系统或统计单位不符合冻结契约")
    if params.quantile_method != "linear" or params.event_summary != "median_iqr":
        raise ValueError("分位数或 event 汇总方法不符合冻结契约")
    if params.invalid_sample_policy != "exclude_non_finite_and_invalid_pose":
        raise ValueError("无效样本策略不符合冻结契约")
    if not 0.0 < params.p95_quantile < params.p99_quantile < 1.0:
        raise ValueError("P95/P99 分位点必须严格递增且位于 (0, 1)")


def _validate_filter_and_windows(params: AnalysisParameters) -> None:
    """检查滤波器、样本数量和参考运动窗口参数。

    参数：
        params: 已完成字段映射的冻结参数。
    """

    if params.minimum_event_samples < 2 or params.hp_minimum_samples < 2:
        raise ValueError("最少样本数不得小于 2")
    if params.reference_speed_median_frames < 1 or params.reference_speed_median_frames % 2 == 0:
        raise ValueError("参考速度中值窗口必须是正奇数")
    if params.hp_filter_type != "butterworth" or not 1 <= params.hp_filter_order <= 8:
        raise ValueError("HP-RMS 只接受 1--8 阶 Butterworth 滤波器")
    if not params.hp_zero_phase or params.hp_resample_method != "median_valid_interval":
        raise ValueError("HP-RMS 必须使用冻结的零相位与重采样方法")


def _validate_lag(params: AnalysisParameters) -> None:
    """检查 lag 的插值、目标、搜索范围和重叠门槛。

    参数：
        params: 已完成字段映射的冻结参数。
    """

    if params.lag_interpolation != "linear_position_slerp_rotation" or params.lag_objective != "rmse":
        raise ValueError("lag 插值或目标函数不符合冻结契约")
    if params.lag_tie_break != "smallest_lag":
        raise ValueError("lag 并列候选必须选择最小值")
    if not 0.0 < params.lag_minimum_overlap_fraction <= 1.0:
        raise ValueError("lag 最少重叠比例必须位于 (0, 1]")
    if params.lag_minimum_overlap_samples < 2 or params.lag_max_ms <= params.lag_min_ms:
        raise ValueError("lag 搜索范围或最少重叠样本非法")
    _require_positive(params.lag_step_ms, "lag_step_ms")
    lag_steps = (params.lag_max_ms - params.lag_min_ms) / params.lag_step_ms
    if not math.isclose(lag_steps, round(lag_steps), rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("lag 步长必须整除冻结搜索范围")


def _validate_ranges(params: AnalysisParameters) -> None:
    """检查所有连续数值阈值是有限正数或允许的非负数。

    参数：
        params: 已完成字段映射的冻结参数。
    """

    for name, value, allow_zero in (
        ("maximum_gap_factor", params.maximum_gap_factor, False),
        ("drift_window_ms", params.drift_window_ms, False),
        ("hp_cutoff_hz", params.hp_cutoff_hz, False),
        ("reference_linear_speed_m_s", params.reference_linear_speed_m_s, False),
        ("reference_angular_speed_deg_s", params.reference_angular_speed_deg_s, False),
        ("reference_motion_duration_ms", params.reference_motion_duration_ms, False),
        ("reference_translation_excursion_mm", params.reference_translation_excursion_mm, False),
        ("reference_rotation_excursion_deg", params.reference_rotation_excursion_deg, False),
        ("response_baseline_ms", params.response_baseline_ms, False),
        ("response_position_mm", params.response_position_mm, False),
        ("response_rotation_deg", params.response_rotation_deg, False),
        ("response_duration_ms", params.response_duration_ms, False),
        ("lag_min_ms", params.lag_min_ms, True),
        ("lag_max_ms", params.lag_max_ms, False),
        ("lag_step_ms", params.lag_step_ms, False),
        ("quaternion_norm_tolerance", params.quaternion_norm_tolerance, False),
        ("recovery_position_mm", params.recovery_position_mm, False),
        ("recovery_duration_ms", params.recovery_duration_ms, False),
        ("settling_position_mm", params.settling_position_mm, False),
        ("settling_duration_ms", params.settling_duration_ms, False),
        ("vcd_tail_quantile", params.vcd_tail_quantile, False),
    ):
        _require_positive(value, name, allow_zero=allow_zero)


def _validate_lineage(params: AnalysisParameters) -> None:
    """检查恢复、时钟域和 VCD risk 的固定 lineage 语义。

    参数：
        params: 已完成字段映射的冻结参数。
    """

    if params.recovery_start_role != "target_visible" or not params.recovery_requires_fresh_output:
        raise ValueError("恢复必须从 target_visible 开始并要求新鲜输出")
    if params.recovery_freshness_field != "source_capture_mono_ms":
        raise ValueError("恢复 freshness 字段不符合冻结契约")
    if params.recovery_freshness_clock != "unity_monotonic":
        raise ValueError("恢复 freshness 时钟不符合冻结契约")
    if params.candidate_arrival_clock != "unity_monotonic":
        raise ValueError("candidate arrival 时钟不符合冻结契约")
    if params.python_processing_clock != "python_monotonic":
        raise ValueError("Python processing 时钟不符合冻结契约")
    if params.cross_clock_policy != "reject" or params.negative_duration_policy != "reject":
        raise ValueError("单调时钟失败策略必须是 reject")
    if params.vcd_score_minimum != 0.0 or params.vcd_score_maximum != 1.0:
        raise ValueError("VCD 合法分数范围必须冻结为 [0, 1]")
    if params.vcd_coverage_group_tie != "include_all":
        raise ValueError("VCD 并列分数组必须整体纳入")
    if params.vcd_risk_unit != "mm" or params.vcd_alignment_source != "capture_time_aligned_raw":
        raise ValueError("VCD risk 单位或位姿来源不符合冻结契约")
    if params.vcd_coverage_denominator != "eligible_received_candidates":
        raise ValueError("VCD coverage 分母必须是 eligible received candidates")
    if params.vcd_score_equality != "exact_float":
        raise ValueError("VCD 分数并列必须使用 exact float")
    if params.vcd_mean_risk != "arithmetic_mean":
        raise ValueError("VCD mean risk 必须使用算术平均")
    if not 0.0 < params.vcd_tail_quantile < 1.0:
        raise ValueError("VCD tail quantile 必须位于 (0, 1)")
    if params.vcd_aurc_integration != "right_step":
        raise ValueError("VCD AURC 必须使用 right-step 积分")
    if params.vcd_random_reference != "exact_without_replacement_expectation":
        raise ValueError("VCD 随机参考必须使用精确无放回期望")
    if params.vcd_sensitivity_cohorts != "completed_trial_marker_covered_occlusion_only":
        raise ValueError("VCD sensitivity cohort 语义未冻结")


def _validate(params: AnalysisParameters) -> None:
    """按职责顺序执行完整冻结参数校验。

    参数：
        params: 已完成字段映射的冻结参数。
    """

    _validate_contract(params)
    _validate_filter_and_windows(params)
    _validate_lag(params)
    _validate_ranges(params)
    _validate_lineage(params)


def load_analysis_parameters(path: Path | None = None) -> AnalysisParameters:
    """读取唯一 TOML 并返回通过完整校验的冻结参数。

    参数：
        path: 测试可覆盖的参数文件路径；省略时读取仓库内唯一正式配置。
    """

    config_path = path or DEFAULT_ANALYSIS_PARAMS_PATH
    with config_path.open("rb") as stream:
        config = tomllib.load(stream)
    _validate_structure(config)
    contract = _section(config, "contract")
    metrics = _section(config, "metrics")
    hp = _section(config, "hp_rms")
    motion = _section(config, "reference_motion")
    response = _section(config, "visible_response")
    lag = _section(config, "lag")
    thresholds = _section(config, "thresholds")
    recovery = _section(config, "recovery")
    latency = _section(config, "latency")
    vcd = _section(config, "vcd")
    params = AnalysisParameters(
        contract_version=int(contract["version"]),
        unit_system=str(contract["unit_system"]),
        statistics_unit=str(contract["statistics_unit"]),
        quantile_method=str(contract["quantile_method"]),
        invalid_sample_policy=str(contract["invalid_sample_policy"]),
        event_summary=str(contract["event_summary"]),
        p95_quantile=float(metrics["p95_quantile"]),
        p99_quantile=float(metrics["p99_quantile"]),
        minimum_event_samples=int(metrics["minimum_event_samples"]),
        maximum_gap_factor=float(metrics["maximum_gap_factor"]),
        drift_window_ms=float(metrics["drift_window_ms"]),
        hp_filter_type=str(hp["filter_type"]),
        hp_filter_order=int(hp["filter_order"]),
        hp_cutoff_hz=float(hp["cutoff_hz"]),
        hp_zero_phase=bool(hp["zero_phase"]),
        hp_resample_method=str(hp["resample_method"]),
        hp_minimum_samples=int(hp["minimum_samples"]),
        reference_linear_speed_m_s=float(motion["linear_speed_m_s"]),
        reference_angular_speed_deg_s=float(motion["angular_speed_deg_s"]),
        reference_speed_median_frames=int(motion["speed_median_frames"]),
        reference_motion_duration_ms=float(motion["minimum_duration_ms"]),
        reference_translation_excursion_mm=float(motion["minimum_translation_excursion_mm"]),
        reference_rotation_excursion_deg=float(motion["minimum_rotation_excursion_deg"]),
        response_baseline_ms=float(response["baseline_ms"]),
        response_position_mm=float(response["position_threshold_mm"]),
        response_rotation_deg=float(response["rotation_threshold_deg"]),
        response_duration_ms=float(response["duration_ms"]),
        lag_min_ms=float(lag["minimum_ms"]),
        lag_max_ms=float(lag["maximum_ms"]),
        lag_step_ms=float(lag["step_ms"]),
        lag_interpolation=str(lag["interpolation"]),
        lag_objective=str(lag["objective"]),
        lag_tie_break=str(lag["tie_break"]),
        lag_minimum_overlap_samples=int(lag["minimum_overlap_samples"]),
        lag_minimum_overlap_fraction=float(lag["minimum_overlap_fraction"]),
        quaternion_norm_tolerance=float(thresholds["pose_quaternion_norm_tolerance"]),
        vcd_score_minimum=float(thresholds["vcd_score_minimum"]),
        vcd_score_maximum=float(thresholds["vcd_score_maximum"]),
        recovery_position_mm=float(thresholds["recovery_position_tolerance_mm"]),
        recovery_duration_ms=float(thresholds["recovery_duration_ms"]),
        settling_position_mm=float(thresholds["settling_position_tolerance_mm"]),
        settling_duration_ms=float(thresholds["settling_duration_ms"]),
        recovery_start_role=str(recovery["start_role"]),
        recovery_requires_fresh_output=bool(recovery["requires_fresh_output"]),
        recovery_freshness_field=str(recovery["freshness_field"]),
        recovery_freshness_clock=str(recovery["freshness_clock"]),
        candidate_arrival_clock=str(latency["candidate_arrival_clock"]),
        python_processing_clock=str(latency["python_processing_clock"]),
        cross_clock_policy=str(latency["cross_clock_policy"]),
        negative_duration_policy=str(latency["negative_duration_policy"]),
        vcd_coverage_group_tie=str(vcd["coverage_group_tie"]),
        vcd_risk_unit=str(vcd["risk_unit"]),
        vcd_alignment_source=str(vcd["alignment_source"]),
        vcd_coverage_denominator=str(vcd["coverage_denominator"]),
        vcd_score_equality=str(vcd["score_equality"]),
        vcd_mean_risk=str(vcd["mean_risk"]),
        vcd_tail_quantile=float(vcd["tail_quantile"]),
        vcd_aurc_integration=str(vcd["aurc_integration"]),
        vcd_random_reference=str(vcd["random_reference"]),
        vcd_sensitivity_cohorts=str(vcd["sensitivity_cohorts"]),
    )
    _validate(params)
    return params


def analysis_parameters_sha256(path: Path | None = None) -> str:
    """返回冻结 TOML 原始字节的 SHA-256，供 Stage 2 lineage 使用。

    参数：
        path: 测试可覆盖的参数文件路径；省略时读取唯一正式配置。
    """

    config_path = path or DEFAULT_ANALYSIS_PARAMS_PATH
    return hashlib.sha256(config_path.read_bytes()).hexdigest()


__all__ = [
    "AnalysisParameters",
    "DEFAULT_ANALYSIS_PARAMS_PATH",
    "analysis_parameters_sha256",
    "load_analysis_parameters",
]
