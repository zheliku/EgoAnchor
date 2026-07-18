"""实验一/二 event/segment 级公共科学指标原语。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.signal import butter, sosfiltfilt  # type: ignore[import-untyped]
from scipy.spatial.transform import Rotation, Slerp  # type: ignore[import-untyped]

from .params import AnalysisParameters
from .pose import normalize_quaternion, rotation_error_deg, translation_error_mm


@dataclass(frozen=True, slots=True)
class SummaryStats:
    """保存一组 event/segment 指标的中位数和四分位数。"""

    sample_count: int
    """参与汇总的 event/segment 数量。"""

    median: float
    """event/segment 指标中位数。"""

    q1: float
    """event/segment 指标第一四分位数。"""

    q3: float
    """event/segment 指标第三四分位数。"""

    iqr: float
    """第三四分位数减第一四分位数。"""


@dataclass(frozen=True, slots=True)
class JumpQuantiles:
    """保存同一 event 内 display pose 相邻跳变的 P95/P99。"""

    sample_count: int
    """参与分位数计算的合法相邻 pose 对数量。"""

    translation_p95_mm: float
    """相邻平移跳变 P95，单位毫米。"""

    translation_p99_mm: float
    """相邻平移跳变 P99，单位毫米。"""

    rotation_p95_deg: float
    """相邻旋转跳变 P95，单位度。"""

    rotation_p99_deg: float
    """相邻旋转跳变 P99，单位度。"""


@dataclass(frozen=True, slots=True)
class LagEstimate:
    """保存 effective lag 搜索的最优候选和残差。"""

    lag_ms: float
    """使重叠轨迹 RMSE 最小的非负 lag，单位毫秒。"""

    residual: float
    """最优 lag 下的平移毫米 RMSE 或旋转角度 RMSE。"""

    pninetyfive_residual: float
    """同一最优 lag 和重叠样本上的平移毫米或旋转角度 P95。"""

    overlap_samples: int
    """最优 lag 使用的重叠样本数。"""


def _finite_values(values: Iterable[float], minimum_samples: int, name: str) -> NDArray[np.float64]:
    """返回有限一维数值并执行最少样本检查。

    参数：
        values: 待计算的标量序列。
        minimum_samples: 最少有限样本数。
        name: 校验失败时使用的指标名称。
    """

    array = np.asarray(list(values), dtype=np.float64)
    if array.ndim != 1:
        raise ValueError(f"{name} 必须是一维标量序列")
    finite = array[np.isfinite(array)]
    if len(finite) < minimum_samples:
        raise ValueError(f"{name} 有效样本不足：{len(finite)} < {minimum_samples}")
    return finite


def _quantile(values: NDArray[np.float64], probability: float, params: AnalysisParameters) -> float:
    """使用冻结 linear 方法计算一个经验分位数。

    参数：
        values: 已通过有限值检查的一维数组。
        probability: 位于零到一之间的分位点。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    if not 0.0 <= probability <= 1.0:
        raise ValueError("分位点必须位于 [0, 1]")
    if params.quantile_method != "linear":
        raise ValueError("Task 6 分位数方法必须是 linear")
    return float(np.quantile(values, probability, method="linear"))


def event_quantiles(
    event_values: Mapping[str, ArrayLike],
    probability: float,
    params: AnalysisParameters,
) -> dict[str, float]:
    """先在每个 event/segment 内独立计算分位数。

    参数：
        event_values: event/segment 标识到 frame 级标量序列的映射。
        probability: event 内分位点。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    if not event_values:
        raise ValueError("event 分位数输入不能为空")
    return {
        event_id: _quantile(
            _finite_values(np.asarray(values, dtype=np.float64).reshape(-1), params.minimum_event_samples, event_id),
            probability,
            params,
        )
        for event_id, values in event_values.items()
    }


def median_iqr(values: Iterable[float], params: AnalysisParameters) -> SummaryStats:
    """对 event/segment 指标计算中位数、四分位数和 IQR。

    参数：
        values: 已在各 event/segment 内完成计算的标量指标。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    finite = _finite_values(values, 1, "event summary")
    q1 = _quantile(finite, 0.25, params)
    q3 = _quantile(finite, 0.75, params)
    return SummaryStats(
        sample_count=len(finite),
        median=_quantile(finite, 0.5, params),
        q1=q1,
        q3=q3,
        iqr=q3 - q1,
    )


def _strict_times(times_ms: ArrayLike, name: str) -> NDArray[np.float64]:
    """返回至少两个严格递增的有限时间样本。

    参数：
        times_ms: 单调时间序列，单位毫秒。
        name: 校验失败时使用的序列名称。
    """

    times = np.asarray(times_ms, dtype=np.float64)
    if times.ndim != 1 or len(times) < 2 or not np.all(np.isfinite(times)):
        raise ValueError(f"{name} 时间必须是一维且包含至少两个有限样本")
    if np.any(np.diff(times) <= 0.0):
        raise ValueError(f"{name} 时间必须严格递增")
    return times


def _required_valid_mask(valid_mask: ArrayLike, count: int, name: str) -> NDArray[np.bool_]:
    """返回与输入等长的显式 pose 有效性掩码。

    参数：
        valid_mask: 调用方从 has_display_pose 与 reference_pose_valid 构造的掩码。
        count: 输入时间序列长度。
        name: 校验失败时使用的指标名称。
    """

    mask = np.asarray(valid_mask, dtype=np.bool_)
    if mask.shape != (count,):
        raise ValueError(f"{name} valid_mask 必须与时间等长")
    return mask


def _continuous_groups(times: NDArray[np.float64], maximum_gap_factor: float) -> list[NDArray[np.int64]]:
    """按中位间隔倍数把时间序列切成连续索引组。

    参数：
        times: 严格递增的有效时间。
        maximum_gap_factor: 大间隙相对中位采样间隔的倍数。
    """

    intervals = np.diff(times)
    nominal = float(np.median(intervals))
    split_points = np.flatnonzero(intervals > maximum_gap_factor * nominal) + 1
    return [group.astype(np.int64) for group in np.split(np.arange(len(times)), split_points) if len(group)]


def position_hp_rms_mm(
    times_ms: ArrayLike,
    position_error_m: ArrayLike,
    valid_mask: ArrayLike,
    params: AnalysisParameters,
) -> float:
    """计算参考相对三轴位置误差的零相位高通 RMS，单位毫米。

    参数：
        times_ms: 同一 event 内的 render 单调时间。
        position_error_m: ``display_pos-reference_pos`` 三轴误差，单位米。
        valid_mask: ``has_display_pose`` 与 ``reference_pose_valid`` 的联合掩码。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    times = np.asarray(times_ms, dtype=np.float64)
    errors = np.asarray(position_error_m, dtype=np.float64)
    if times.ndim != 1 or errors.shape != (len(times), 3):
        raise ValueError("HP-RMS 输入形状必须是 (N,) 和 (N,3)")
    valid = _required_valid_mask(valid_mask, len(times), "HP-RMS")
    valid &= np.isfinite(times) & np.all(np.isfinite(errors), axis=1)
    times = _strict_times(times[valid], "HP-RMS")
    errors = errors[valid]
    filtered_segments: list[NDArray[np.float64]] = []
    for group in _continuous_groups(times, params.maximum_gap_factor):
        if len(group) < params.hp_minimum_samples:
            continue
        group_times = times[group]
        group_errors = errors[group]
        interval_ms = float(np.median(np.diff(group_times)))
        sample_rate_hz = 1000.0 / interval_ms
        if params.hp_cutoff_hz >= 0.5 * sample_rate_hz:
            raise ValueError("HP-RMS 截止频率必须低于 event 采样率的 Nyquist 频率")
        grid = np.arange(group_times[0], group_times[-1] + 0.5 * interval_ms, interval_ms)
        grid = grid[grid <= group_times[-1]]
        if len(grid) < params.hp_minimum_samples:
            continue
        resampled = np.column_stack(
            [np.interp(grid, group_times, group_errors[:, axis]) for axis in range(3)],
        )
        sos = butter(
            params.hp_filter_order,
            params.hp_cutoff_hz,
            btype="highpass",
            fs=sample_rate_hz,
            output="sos",
        )
        filtered_segments.append(sosfiltfilt(sos, resampled, axis=0))
    if not filtered_segments:
        raise ValueError("HP-RMS 没有达到最少样本数的连续片段")
    filtered = np.concatenate(filtered_segments, axis=0)
    return float(1000.0 * np.sqrt(np.mean(np.sum(np.square(filtered), axis=1))))


def position_drift_mm(
    times_ms: ArrayLike,
    position_error_m: ArrayLike,
    valid_mask: ArrayLike,
    params: AnalysisParameters,
) -> float:
    """计算参考相对误差末窗均值与首窗均值的距离，单位毫米。

    参数：
        times_ms: 同一 event 内的 render 单调时间。
        position_error_m: ``display_pos-reference_pos`` 三轴误差，单位米。
        valid_mask: ``has_display_pose`` 与 ``reference_pose_valid`` 的联合掩码。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    times = np.asarray(times_ms, dtype=np.float64)
    errors = np.asarray(position_error_m, dtype=np.float64)
    if times.ndim != 1 or errors.shape != (len(times), 3):
        raise ValueError("drift 输入形状必须是 (N,) 和 (N,3)")
    valid = _required_valid_mask(valid_mask, len(times), "drift")
    valid &= np.isfinite(times) & np.all(np.isfinite(errors), axis=1)
    times = _strict_times(times[valid], "drift")
    errors = errors[valid]
    if times[-1] - times[0] < 2.0 * params.drift_window_ms:
        raise ValueError("drift event 不足以容纳互不重叠的首尾时窗")
    first = errors[times < times[0] + params.drift_window_ms]
    last = errors[times > times[-1] - params.drift_window_ms]
    if len(first) < params.minimum_event_samples or len(last) < params.minimum_event_samples:
        raise ValueError("drift 首尾时窗有效样本不足")
    return float(1000.0 * np.linalg.norm(np.mean(last, axis=0) - np.mean(first, axis=0)))


def _first_sustained_start(
    times: NDArray[np.float64],
    condition: NDArray[np.bool_],
    earliest_ms: float,
    duration_ms: float,
    maximum_gap_factor: float,
) -> float | None:
    """返回首次连续满足布尔条件达到指定时长的窗口起点。

    参数：
        times: 严格递增时间序列。
        condition: 与时间等长的条件序列。
        earliest_ms: 允许窗口开始的最早时间。
        duration_ms: 条件必须持续满足的长度。
        maximum_gap_factor: 允许的最大相邻时间间隔倍数。
    """

    nominal = float(np.median(np.diff(times)))
    maximum_gap = maximum_gap_factor * nominal
    start: int | None = None
    for index, current_time in enumerate(times):
        eligible = bool(condition[index]) and current_time >= earliest_ms
        continues = (
            start is not None
            and eligible
            and index > 0
            and times[index] - times[index - 1] <= maximum_gap
        )
        if not continues:
            start = index if eligible else None
        if start is not None and current_time - times[start] >= duration_ms:
            return float(times[start])
    return None


def _time_near_window(
    value_ms: float,
    times: NDArray[np.float64],
    maximum_gap_factor: float,
) -> bool:
    """判断事件时间位于 render 范围内或相邻一个合法采样间隔内。

    参数：
        value_ms: 待检查的事件时间。
        times: 当前 event 的严格递增时间序列。
        maximum_gap_factor: 合法边界间隔相对中位采样间隔的倍数。
    """

    margin = maximum_gap_factor * float(np.median(np.diff(times)))
    return bool(np.isfinite(value_ms) and times[0] - margin <= value_ms <= times[-1] + margin)


def visible_response_ms(
    times_ms: ArrayLike,
    display_positions_m: ArrayLike,
    display_rotations: ArrayLike,
    valid_mask: ArrayLike,
    *,
    reference_onset_ms: float,
    params: AnalysisParameters,
) -> float | None:
    """计算参考实际运动开始到 display 持久响应的时间。

    参数：
        times_ms: marker 窗内 render 单调时间。
        display_positions_m: display 世界位置，单位米。
        display_rotations: display xyzw 四元数。
        valid_mask: ``has_display_pose`` 的显式有效性掩码。
        reference_onset_ms: 平台参考检测得到的实际运动开始时间。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    times = _strict_times(times_ms, "visible response")
    positions = np.asarray(display_positions_m, dtype=np.float64)
    rotations = np.asarray(display_rotations, dtype=np.float64)
    if positions.shape != (len(times), 3) or rotations.shape != (len(times), 4):
        raise ValueError("visible response pose 形状必须是 (N,3) 和 (N,4)")
    if not _time_near_window(reference_onset_ms, times, params.maximum_gap_factor):
        raise ValueError("reference_onset_ms 必须是 event 窗内有限时间")
    valid = _required_valid_mask(valid_mask, len(times), "visible response")
    valid &= np.all(np.isfinite(positions), axis=1) & np.all(np.isfinite(rotations), axis=1)
    baseline_mask = valid & (times >= reference_onset_ms - params.response_baseline_ms) & (times < reference_onset_ms)
    if np.count_nonzero(baseline_mask) < params.minimum_event_samples:
        raise ValueError("visible response 运动前基线样本不足")
    baseline_position = np.median(positions[baseline_mask], axis=0)
    baseline_rotations = rotations[baseline_mask].copy()
    baseline_rotations[np.sum(baseline_rotations * baseline_rotations[0], axis=1) < 0.0] *= -1.0
    baseline_rotation = normalize_quaternion(
        np.median(baseline_rotations, axis=0),
        params.quaternion_norm_tolerance,
    )
    active = np.zeros(len(times), dtype=np.bool_)
    valid_indices = np.flatnonzero(valid)
    position_delta = translation_error_mm(positions[valid_indices], baseline_position)
    rotation_delta = rotation_error_deg(
        rotations[valid_indices],
        baseline_rotation,
        params.quaternion_norm_tolerance,
    )
    active[valid_indices] = (position_delta >= params.response_position_mm) | (
        rotation_delta >= params.response_rotation_deg
    )
    response_start = _first_sustained_start(
        times,
        active,
        reference_onset_ms,
        params.response_duration_ms,
        params.maximum_gap_factor,
    )
    return None if response_start is None else response_start - reference_onset_ms


def settling_time_ms(
    times_ms: ArrayLike,
    translation_error_values_mm: ArrayLike,
    valid_mask: ArrayLike,
    *,
    reference_stop_ms: float,
    params: AnalysisParameters,
) -> float | None:
    """计算参考实际停止后 display 平移误差持久达标的时间。

    参数：
        times_ms: marker 窗内 render 单调时间。
        translation_error_values_mm: display 相对平台参考的平移误差。
        valid_mask: ``has_display_pose`` 与 ``reference_pose_valid`` 的联合掩码。
        reference_stop_ms: 平台参考检测得到的实际停止时间。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    times = _strict_times(times_ms, "settling")
    errors = np.asarray(translation_error_values_mm, dtype=np.float64)
    if errors.shape != times.shape:
        raise ValueError("settling 误差必须与时间等长")
    if not _time_near_window(reference_stop_ms, times, params.maximum_gap_factor):
        raise ValueError("reference_stop_ms 必须是 event 窗内有限时间")
    valid = _required_valid_mask(valid_mask, len(times), "settling")
    settled = valid & np.isfinite(errors) & (errors <= params.settling_position_mm)
    start = _first_sustained_start(
        times,
        settled,
        reference_stop_ms,
        params.settling_duration_ms,
        params.maximum_gap_factor,
    )
    return None if start is None else start - reference_stop_ms


def durable_recovery_time_ms(
    times_ms: ArrayLike,
    translation_error_values_mm: ArrayLike,
    valid_mask: ArrayLike,
    has_output_pose: ArrayLike,
    has_source_capture_timing: ArrayLike,
    source_capture_mono_ms: ArrayLike,
    *,
    target_visible_ms: float,
    params: AnalysisParameters,
) -> float | None:
    """计算 target_visible 后首次新鲜 output 支持的持久恢复时间。

    参数：
        times_ms: 恢复观察窗内 render 单调时间。
        translation_error_values_mm: display 相对平台参考的平移误差。
        valid_mask: ``has_display_pose`` 与 ``reference_pose_valid`` 的联合掩码。
        has_output_pose: 每个 render tick 是否有 runtime output。
        has_source_capture_timing: 每个 output 是否携带合法的 Unity 采集时间代理。
        source_capture_mono_ms: output 来源帧的 Unity 采集时间代理。
        target_visible_ms: ``target_visible`` marker 的 Unity 单调时间。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    times = _strict_times(times_ms, "durable recovery")
    errors = np.asarray(translation_error_values_mm, dtype=np.float64)
    valid = _required_valid_mask(valid_mask, len(times), "durable recovery")
    has_output = np.asarray(has_output_pose, dtype=np.bool_)
    has_timing = np.asarray(has_source_capture_timing, dtype=np.bool_)
    captures = np.asarray(source_capture_mono_ms, dtype=np.float64)
    if (
        errors.shape != times.shape
        or has_output.shape != times.shape
        or has_timing.shape != times.shape
        or captures.shape != times.shape
    ):
        raise ValueError("recovery 输入序列必须与时间等长")
    if not _time_near_window(target_visible_ms, times, params.maximum_gap_factor):
        raise ValueError("target_visible_ms 必须是恢复窗口内有限时间")
    earliest = target_visible_ms
    if params.recovery_requires_fresh_output:
        fresh = (
            has_output
            & has_timing
            & np.isfinite(captures)
            & (captures >= target_visible_ms)
            & (times >= target_visible_ms)
        )
        fresh_indices = np.flatnonzero(fresh)
        if not len(fresh_indices):
            return None
        earliest = float(times[fresh_indices[0]])
    recovered = valid & np.isfinite(errors) & (errors <= params.recovery_position_mm)
    start = _first_sustained_start(
        times,
        recovered,
        earliest,
        params.recovery_duration_ms,
        params.maximum_gap_factor,
    )
    return None if start is None else start - target_visible_ms


def post_stop_position_jitter_rms_mm(
    times_ms: ArrayLike,
    error_vectors_m: ArrayLike,
    valid_mask: ArrayLike,
    *,
    reference_stop_ms: float,
    params: AnalysisParameters,
) -> float | None:
    """计算参考停止后固定公共窗口内的去中心位置 jitter RMS。

    参数：
        times_ms: transition event 内严格递增的 render 时间。
        error_vectors_m: ``display-reference`` 三轴误差，单位米。
        valid_mask: display 与平台参考联合有效性掩码。
        reference_stop_ms: 由平台参考运动检测得到的实际停止时间。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    times = _strict_times(times_ms, "post-stop jitter")
    errors = np.asarray(error_vectors_m, dtype=np.float64)
    if errors.shape != (len(times), 3):
        raise ValueError("post-stop jitter 误差必须是 (N,3)")
    if not _time_near_window(reference_stop_ms, times, params.maximum_gap_factor):
        raise ValueError("reference_stop_ms 必须是 transition event 窗内有限时间")
    valid = _required_valid_mask(valid_mask, len(times), "post-stop jitter")
    start = reference_stop_ms + params.post_stop_guard_ms
    end = start + params.post_stop_window_ms
    nominal = float(np.median(np.diff(times)))
    if times[-1] < end - params.maximum_gap_factor * nominal:
        return None
    selected = (
        valid
        & (times >= start)
        & (times < end)
        & np.all(np.isfinite(errors), axis=1)
    )
    values_mm = errors[selected] * 1000.0
    if len(values_mm) < params.minimum_event_samples:
        return None
    centered = values_mm - np.median(values_mm, axis=0)
    return float(np.sqrt(np.mean(np.sum(np.square(centered), axis=1))))


def motion_hold_ratio(
    times_ms: ArrayLike,
    display_positions_m: ArrayLike,
    display_rotations: ArrayLike,
    valid_mask: ArrayLike,
    params: AnalysisParameters,
) -> float:
    """计算参考运动窗口内近零 display pose 增量的相邻 pair 比例。

    参数：
        times_ms: 已切为同一参考运动窗口的 render 时间。
        display_positions_m: display 世界位置，单位米。
        display_rotations: display xyzw 四元数。
        valid_mask: ``has_display_pose`` 的显式有效性掩码。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    times = _strict_times(times_ms, "motion hold")
    positions = np.asarray(display_positions_m, dtype=np.float64)
    rotations = np.asarray(display_rotations, dtype=np.float64)
    if positions.shape != (len(times), 3) or rotations.shape != (len(times), 4):
        raise ValueError("motion hold 输入形状必须是 (N,3) 和 (N,4)")
    valid = _required_valid_mask(valid_mask, len(times), "motion hold")
    valid &= np.all(np.isfinite(positions), axis=1) & np.all(np.isfinite(rotations), axis=1)
    intervals = np.diff(times)
    nominal = float(np.median(intervals))
    adjacent = valid[:-1] & valid[1:] & (intervals <= params.maximum_gap_factor * nominal)
    indices = np.flatnonzero(adjacent)
    if len(indices) < params.minimum_event_samples - 1:
        raise ValueError("motion hold 合法相邻样本对不足")
    translation_mm = translation_error_mm(positions[indices + 1], positions[indices])
    rotation_deg = rotation_error_deg(
        rotations[indices + 1],
        rotations[indices],
        params.quaternion_norm_tolerance,
    )
    held = (
        (translation_mm <= params.hold_position_tolerance_mm)
        & (rotation_deg <= params.hold_rotation_tolerance_deg)
    )
    return float(np.count_nonzero(held) / len(indices))


def pose_jump_quantiles(
    times_ms: ArrayLike,
    display_positions_m: ArrayLike,
    display_rotations: ArrayLike,
    valid_mask: ArrayLike,
    params: AnalysisParameters,
    *,
    render_tick_ids: ArrayLike | None = None,
) -> JumpQuantiles:
    """计算同一 event 内相邻合法 display pose 的 P95/P99 跳变。

    参数：
        times_ms: 同一 variant 的 render 单调时间。
        display_positions_m: display 世界位置，单位米。
        display_rotations: display xyzw 四元数。
        valid_mask: ``has_display_pose`` 的显式有效性掩码。
        params: 唯一 TOML 解析得到的冻结参数对象。
        render_tick_ids: 可选 render tick 标识；提供时只接受编号相邻的 pose 对。
    """

    times = _strict_times(times_ms, "pose jump")
    positions = np.asarray(display_positions_m, dtype=np.float64)
    rotations = np.asarray(display_rotations, dtype=np.float64)
    if positions.shape != (len(times), 3) or rotations.shape != (len(times), 4):
        raise ValueError("pose jump 输入形状必须是 (N,3) 和 (N,4)")
    valid = _required_valid_mask(valid_mask, len(times), "pose jump")
    valid &= np.all(np.isfinite(positions), axis=1) & np.all(np.isfinite(rotations), axis=1)
    intervals = np.diff(times)
    nominal = float(np.median(intervals))
    adjacent = valid[:-1] & valid[1:] & (intervals <= params.maximum_gap_factor * nominal)
    if render_tick_ids is not None:
        try:
            ticks = np.asarray(render_tick_ids, dtype=np.float64)
        except (TypeError, ValueError) as error:
            raise ValueError("render_tick_ids 必须是有限整数") from error
        if ticks.shape != times.shape:
            raise ValueError("render_tick_ids 必须与时间等长")
        if not np.all(np.isfinite(ticks)) or not np.all(ticks == np.round(ticks)):
            raise ValueError("render_tick_ids 必须是有限整数")
        adjacent &= np.diff(ticks.astype(np.int64)) == 1
    indices = np.flatnonzero(adjacent)
    if len(indices) < params.minimum_event_samples:
        raise ValueError("pose jump 合法相邻样本对不足")
    translations = translation_error_mm(positions[indices + 1], positions[indices])
    rotations_deg = rotation_error_deg(
        rotations[indices + 1],
        rotations[indices],
        params.quaternion_norm_tolerance,
    )
    return JumpQuantiles(
        sample_count=len(indices),
        translation_p95_mm=_quantile(translations, params.p95_quantile, params),
        translation_p99_mm=_quantile(translations, params.p99_quantile, params),
        rotation_p95_deg=_quantile(rotations_deg, params.p95_quantile, params),
        rotation_p99_deg=_quantile(rotations_deg, params.p99_quantile, params),
    )


def _lag_grid(params: AnalysisParameters) -> NDArray[np.float64]:
    """返回包含冻结上下界的 lag 候选网格。

    参数：
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    count = int(round((params.lag_max_ms - params.lag_min_ms) / params.lag_step_ms))
    grid = params.lag_min_ms + np.arange(count + 1, dtype=np.float64) * params.lag_step_ms
    return grid[grid <= params.lag_max_ms + 1e-9]


def _overlap_mask(times: NDArray[np.float64], lag_ms: float) -> NDArray[np.bool_]:
    """返回 ``reference(t-lag)`` 位于原参考时间范围内的样本掩码。

    参数：
        times: display 与 reference 共用的 render 时间。
        lag_ms: 当前候选 lag。
    """

    query = times - lag_ms
    return (query >= times[0]) & (query <= times[-1])


def _valid_overlap(count: int, total: int, params: AnalysisParameters) -> bool:
    """判断 lag 候选是否满足冻结的重叠数量与比例。

    参数：
        count: 当前候选的重叠样本数。
        total: event 有效样本总数。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    return count >= params.lag_minimum_overlap_samples and count / total >= params.lag_minimum_overlap_fraction


def estimate_translation_lag(
    times_ms: ArrayLike,
    display_positions_m: ArrayLike,
    reference_positions_m: ArrayLike,
    valid_mask: ArrayLike,
    params: AnalysisParameters,
) -> LagEstimate:
    """搜索最小化 ``display(t)-reference(t-lag)`` 的平移 lag。

    参数：
        times_ms: 同一 event 的 render 单调时间。
        display_positions_m: display 世界位置，单位米。
        reference_positions_m: 同 tick 平台参考世界位置，单位米。
        valid_mask: ``has_display_pose`` 与 ``reference_pose_valid`` 的联合掩码。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    times = np.asarray(times_ms, dtype=np.float64)
    display = np.asarray(display_positions_m, dtype=np.float64)
    reference = np.asarray(reference_positions_m, dtype=np.float64)
    if times.ndim != 1 or display.shape != (len(times), 3) or reference.shape != (len(times), 3):
        raise ValueError("translation lag 输入形状必须是 (N,) 和两个 (N,3)")
    valid = _required_valid_mask(valid_mask, len(times), "translation lag")
    valid &= np.isfinite(times) & np.all(np.isfinite(display), axis=1) & np.all(np.isfinite(reference), axis=1)
    times = _strict_times(times[valid], "translation lag")
    display = display[valid]
    reference = reference[valid]
    groups = [group for group in _continuous_groups(times, params.maximum_gap_factor) if len(group) >= 2]
    best: LagEstimate | None = None
    for lag in _lag_grid(params):
        residual_parts: list[NDArray[np.float64]] = []
        count = 0
        for group in groups:
            group_times = times[group]
            overlap = _overlap_mask(group_times, float(lag))
            group_count = int(np.count_nonzero(overlap))
            if not group_count:
                continue
            query = group_times[overlap] - lag
            group_reference = reference[group]
            shifted_reference = np.column_stack(
                [np.interp(query, group_times, group_reference[:, axis]) for axis in range(3)],
            )
            residual_parts.append(translation_error_mm(display[group][overlap], shifted_reference))
            count += group_count
        if not _valid_overlap(count, len(times), params):
            continue
        residuals_mm = np.concatenate(residual_parts)
        residual = float(np.sqrt(np.mean(np.square(residuals_mm))))
        if best is None or residual < best.residual - 1e-12:
            best = LagEstimate(
                float(lag),
                residual,
                _quantile(residuals_mm, params.p95_quantile, params),
                count,
            )
    if best is None:
        raise ValueError("translation lag 没有满足重叠契约的候选")
    return best


def estimate_angular_lag(
    times_ms: ArrayLike,
    display_rotations: ArrayLike,
    reference_rotations: ArrayLike,
    valid_mask: ArrayLike,
    params: AnalysisParameters,
) -> LagEstimate:
    """搜索最小化 ``display(t)`` 与 ``reference(t-lag)`` 角残差的 lag。

    参数：
        times_ms: 同一 event 的 render 单调时间。
        display_rotations: display xyzw 四元数。
        reference_rotations: 同 tick 平台参考 xyzw 四元数。
        valid_mask: ``has_display_pose`` 与 ``reference_pose_valid`` 的联合掩码。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    times = np.asarray(times_ms, dtype=np.float64)
    display = np.asarray(display_rotations, dtype=np.float64)
    reference = np.asarray(reference_rotations, dtype=np.float64)
    if times.ndim != 1 or display.shape != (len(times), 4) or reference.shape != (len(times), 4):
        raise ValueError("angular lag 输入形状必须是 (N,) 和两个 (N,4)")
    valid = _required_valid_mask(valid_mask, len(times), "angular lag")
    valid &= np.isfinite(times) & np.all(np.isfinite(display), axis=1) & np.all(np.isfinite(reference), axis=1)
    times = _strict_times(times[valid], "angular lag")
    display = normalize_quaternion(display[valid], params.quaternion_norm_tolerance)
    reference = normalize_quaternion(reference[valid], params.quaternion_norm_tolerance)
    groups = [group for group in _continuous_groups(times, params.maximum_gap_factor) if len(group) >= 2]
    interpolators = [Slerp(times[group], Rotation.from_quat(reference[group])) for group in groups]
    best: LagEstimate | None = None
    for lag in _lag_grid(params):
        residual_parts: list[NDArray[np.float64]] = []
        count = 0
        for group, interpolator in zip(groups, interpolators):
            group_times = times[group]
            overlap = _overlap_mask(group_times, float(lag))
            group_count = int(np.count_nonzero(overlap))
            if not group_count:
                continue
            shifted_reference = interpolator(group_times[overlap] - lag).as_quat()
            residual_parts.append(
                rotation_error_deg(
                    display[group][overlap],
                    shifted_reference,
                    params.quaternion_norm_tolerance,
                ),
            )
            count += group_count
        if not _valid_overlap(count, len(times), params):
            continue
        residuals_deg = np.concatenate(residual_parts)
        residual = float(np.sqrt(np.mean(np.square(residuals_deg))))
        if best is None or residual < best.residual - 1e-12:
            best = LagEstimate(
                float(lag),
                residual,
                _quantile(residuals_deg, params.p95_quantile, params),
                count,
            )
    if best is None:
        raise ValueError("angular lag 没有满足重叠契约的候选")
    return best


__all__ = [
    "JumpQuantiles",
    "LagEstimate",
    "SummaryStats",
    "durable_recovery_time_ms",
    "estimate_angular_lag",
    "estimate_translation_lag",
    "event_quantiles",
    "median_iqr",
    "motion_hold_ratio",
    "post_stop_position_jitter_rms_mm",
    "pose_jump_quantiles",
    "position_drift_mm",
    "position_hp_rms_mm",
    "settling_time_ms",
    "visible_response_ms",
]
