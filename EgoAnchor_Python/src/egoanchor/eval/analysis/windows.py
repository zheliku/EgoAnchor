"""从 Stage 2 事件投影构造 event、遮挡和参考运动窗口。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .params import AnalysisParameters
from .pose import rotation_error_deg, translation_error_mm


@dataclass(frozen=True, slots=True)
class EventMarker:
    """表示从 events 与 event_payload 联接得到的一条 marker。"""

    event_row_id: str
    """合并事件表中的稳定行标识。"""

    session_id: str
    """marker 所属 session。"""

    experiment_id: str
    """marker 所属实验。"""

    scenario_id: str
    """marker 所属物理场景。"""

    trial_id: str
    """marker 所属 trial。"""

    event_id: str
    """trial 内稳定事件标识。"""

    role: str
    """payload 中显式记录的事件角色。"""

    mono_ms: float
    """Unity 单调时钟下的 marker 时间。"""

    @property
    def trial_key(self) -> tuple[str, str, str, str]:
        """返回禁止跨越的 session/experiment/scenario/trial 边界键。"""

        return (self.session_id, self.experiment_id, self.scenario_id, self.trial_id)


@dataclass(frozen=True, slots=True)
class EventWindow:
    """表示从一个 marker 到下一 marker 或 trial 结束的半开窗口。"""

    marker: EventMarker
    """定义窗口起点和角色的 marker。"""

    start_ms: float
    """窗口起点，包含该时间。"""

    end_ms: float
    """窗口终点，不包含该时间。"""


@dataclass(frozen=True, slots=True)
class OcclusionWindow:
    """表示一组严格闭合的遮挡和重新可见窗口。"""

    event_id: str
    """遮挡开始 marker 的事件标识。"""

    occlusion_start_ms: float
    """遮挡开始时间。"""

    visible_start_ms: float
    """目标重新可见时间，也是恢复计时起点。"""

    end_ms: float
    """恢复观察窗终点。"""


@dataclass(frozen=True, slots=True)
class MotionInterval:
    """表示 marker 窗内从首个有效运动到最后一次停止的区间。"""

    onset_ms: float
    """首个有效参考运动 bout 的起点。"""

    stop_ms: float
    """最后一个有效参考运动 bout 后的首个静止样本时间。"""

    bout_count: int
    """合并区间内通过速度、时长和位移门槛的 bout 数量。"""


def _text(row: Mapping[str, Any], name: str) -> str:
    """读取必需非空文本字段。

    参数：
        row: Stage 2 行映射。
        name: 待读取的列名。
    """

    value = str(row.get(name) or "").strip()
    if not value or value == "@empty-text":
        raise ValueError(f"事件行缺少 {name}")
    return value


def parse_event_markers(
    event_rows: Iterable[Mapping[str, Any]],
    payload_rows: Iterable[Mapping[str, Any]],
) -> tuple[EventMarker, ...]:
    """按 ``event_row_id`` 联接并解析所有显式 event marker。

    参数：
        event_rows: Stage 1 工作簿 ``events`` sheet 的行映射。
        payload_rows: ``event_payload`` sheet 的行映射。
    """

    events = list(event_rows)
    marker_row_ids = {
        _text(row, "event_row_id")
        for row in events
        if str(row.get("event") or "") == "event_marker"
    }
    roles: dict[str, str] = {}
    for row in payload_rows:
        if str(row.get("json_path") or "") != "payload.event_role":
            continue
        row_id = str(row.get("event_row_id") or "").strip()
        if row_id not in marker_row_ids:
            continue
        role = _text(row, "event_role")
        if row_id in roles and roles[row_id] != role:
            raise ValueError(f"同一 event_row_id 出现冲突角色：{row_id}")
        roles[row_id] = role

    markers: list[EventMarker] = []
    for row in events:
        if str(row.get("event") or "") != "event_marker":
            continue
        row_id = _text(row, "event_row_id")
        if row_id not in roles:
            raise ValueError(f"event marker 缺少 event_role：{row_id}")
        raw_mono_ms = row.get("mono_ms")
        if not isinstance(raw_mono_ms, (int, float)) or isinstance(raw_mono_ms, bool):
            raise ValueError(f"event marker 时间类型错误：{row_id}")
        mono_ms = float(raw_mono_ms)
        if not math.isfinite(mono_ms):
            raise ValueError(f"event marker 时间不是有限值：{row_id}")
        markers.append(
            EventMarker(
                event_row_id=row_id,
                session_id=_text(row, "session_id"),
                experiment_id=_text(row, "experiment_id"),
                scenario_id=_text(row, "scenario_id"),
                trial_id=_text(row, "trial_id"),
                event_id=_text(row, "event_id"),
                role=roles[row_id],
                mono_ms=mono_ms,
            ),
        )
    markers.sort(key=lambda item: (item.trial_key, item.mono_ms, item.event_id))
    if len({item.event_row_id for item in markers}) != len(markers):
        raise ValueError("event marker 的 event_row_id 必须唯一")
    return tuple(markers)


def _single_trial(markers: Sequence[EventMarker]) -> None:
    """确保窗口构造输入没有跨 trial。

    参数：
        markers: 按时间排序的 marker 集合。
    """

    if markers and len({item.trial_key for item in markers}) != 1:
        raise ValueError("事件窗口不得跨 session、experiment、scenario 或 trial")


def build_event_windows(
    markers: Sequence[EventMarker],
    trial_end_ms: float,
) -> tuple[EventWindow, ...]:
    """把同一 trial 的 marker 构造成连续半开 event 窗口。

    参数：
        markers: 同一 trial 内按时间排序的 marker。
        trial_end_ms: 已通过 lifecycle QC 的 trial 结束时间。
    """

    _single_trial(markers)
    if not math.isfinite(trial_end_ms):
        raise ValueError("trial 结束时间必须是有限值")
    ordered = sorted(markers, key=lambda item: item.mono_ms)
    if any(left.mono_ms >= right.mono_ms for left, right in zip(ordered, ordered[1:])):
        raise ValueError("event marker 时间必须严格递增")
    if ordered and trial_end_ms <= ordered[-1].mono_ms:
        raise ValueError("trial 结束时间必须晚于最后一个 marker")
    ends = [item.mono_ms for item in ordered[1:]] + ([trial_end_ms] if ordered else [])
    return tuple(
        EventWindow(marker=marker, start_ms=marker.mono_ms, end_ms=end)
        for marker, end in zip(ordered, ends)
    )


def pair_occlusion_windows(
    markers: Sequence[EventMarker],
    trial_end_ms: float,
) -> tuple[OcclusionWindow, ...]:
    """严格配对 ``occlusion_started`` 与 ``target_visible`` marker。

    参数：
        markers: 同一遮挡恢复 trial 的 marker。
        trial_end_ms: 已通过 lifecycle QC 的 trial 结束时间。
    """

    _single_trial(markers)
    ordered = sorted(markers, key=lambda item: item.mono_ms)
    if not math.isfinite(trial_end_ms):
        raise ValueError("trial 结束时间必须是有限值")
    if any(left.mono_ms >= right.mono_ms for left, right in zip(ordered, ordered[1:])):
        raise ValueError("遮挡 marker 时间必须严格递增")
    expected = ["occlusion_started" if index % 2 == 0 else "target_visible" for index in range(len(ordered))]
    if not ordered or len(ordered) % 2 != 0 or [item.role for item in ordered] != expected:
        raise ValueError("遮挡 marker 必须从 occlusion_started 开始并与 target_visible 严格交替闭合")
    if trial_end_ms <= ordered[-1].mono_ms:
        raise ValueError("trial 结束时间必须晚于最后一次 target_visible")
    windows: list[OcclusionWindow] = []
    for index in range(0, len(ordered), 2):
        hidden = ordered[index]
        visible = ordered[index + 1]
        end = ordered[index + 2].mono_ms if index + 2 < len(ordered) else trial_end_ms
        windows.append(
            OcclusionWindow(
                event_id=hidden.event_id,
                occlusion_start_ms=hidden.mono_ms,
                visible_start_ms=visible.mono_ms,
                end_ms=end,
            ),
        )
    return tuple(windows)


def _median_filter(values: NDArray[np.float64], width: int) -> NDArray[np.float64]:
    """使用缩短边界窗的居中中值滤波，避免填充值污染速度。

    参数：
        values: 一维速度序列。
        width: 正奇数窗口宽度。
    """

    radius = width // 2
    return np.asarray(
        [np.median(values[max(0, index - radius) : min(len(values), index + radius + 1)]) for index in range(len(values))],
        dtype=np.float64,
    )


def _true_runs(mask: NDArray[np.bool_]) -> list[tuple[int, int]]:
    """返回布尔序列中所有连续 true 区间的闭区间索引。

    参数：
        mask: 一维运动状态布尔序列。
    """

    padded = np.concatenate(([False], mask, [False])).astype(np.int8)
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    stops = np.flatnonzero(changes == -1) - 1
    return list(zip(starts.tolist(), stops.tolist()))


def detect_reference_motion(
    times_ms: ArrayLike,
    linear_speed_m_s: ArrayLike,
    angular_speed_deg_s: ArrayLike,
    reference_positions_m: ArrayLike,
    reference_rotations: ArrayLike,
    params: AnalysisParameters,
) -> MotionInterval | None:
    """按冻结速度、时长和位移门槛检测 marker 窗内参考运动。

    参数：
        times_ms: Unity render 单调时间，单位毫秒。
        linear_speed_m_s: 平台参考线速度。
        angular_speed_deg_s: 平台参考角速度。
        reference_positions_m: 平台参考世界位置，单位米。
        reference_rotations: 平台参考 xyzw 四元数。
        params: 唯一 TOML 解析得到的冻结参数对象。
    """

    times = np.asarray(times_ms, dtype=np.float64)
    linear = np.asarray(linear_speed_m_s, dtype=np.float64)
    angular = np.asarray(angular_speed_deg_s, dtype=np.float64)
    positions = np.asarray(reference_positions_m, dtype=np.float64)
    rotations = np.asarray(reference_rotations, dtype=np.float64)
    count = len(times)
    if times.ndim != 1 or linear.shape != (count,) or angular.shape != (count,):
        raise ValueError("参考运动时间和速度必须是一维等长序列")
    if positions.shape != (count, 3) or rotations.shape != (count, 4):
        raise ValueError("参考运动 pose 形状必须是 (N,3) 和 (N,4)")
    if count < 2 or not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0.0):
        raise ValueError("参考运动时间必须包含至少两个严格递增有限样本")
    if not np.all(np.isfinite(linear)) or not np.all(np.isfinite(angular)):
        raise ValueError("参考速度包含非有限值")
    active = (
        _median_filter(linear, params.reference_speed_median_frames) >= params.reference_linear_speed_m_s
    ) | (
        _median_filter(angular, params.reference_speed_median_frames) >= params.reference_angular_speed_deg_s
    )
    nominal_gap = float(np.median(np.diff(times)))
    active[1:] &= np.diff(times) <= params.maximum_gap_factor * nominal_gap
    accepted: list[tuple[int, float]] = []
    for start, last_active in _true_runs(active):
        if last_active == count - 1:
            continue
        stop_index = min(last_active + 1, count - 1)
        stop_ms = float(times[stop_index])
        active_duration_ms = float(times[last_active] - times[start])
        if active_duration_ms < params.reference_motion_duration_ms:
            continue
        translation = float(np.max(translation_error_mm(positions[start : last_active + 1], positions[start])))
        rotation = float(
            np.max(
                rotation_error_deg(
                    rotations[start : last_active + 1],
                    rotations[start],
                    params.quaternion_norm_tolerance,
                ),
            ),
        )
        if translation < params.reference_translation_excursion_mm and rotation < params.reference_rotation_excursion_deg:
            continue
        accepted.append((start, stop_ms))
    if not accepted:
        return None
    return MotionInterval(
        onset_ms=float(times[accepted[0][0]]),
        stop_ms=accepted[-1][1],
        bout_count=len(accepted),
    )


__all__ = [
    "EventMarker",
    "EventWindow",
    "MotionInterval",
    "OcclusionWindow",
    "build_event_windows",
    "detect_reference_motion",
    "pair_occlusion_windows",
    "parse_event_markers",
]
