"""从 Stage 1 workbook 重放 Kalman 的两种时序输出策略。

该模块只用于反事实离线诊断。原始 session 没有记录 Kalman 内部协方差、
延迟估计 EMA 和 StaticLock 内部状态，因此这里的结果不能当作新采集 runtime。
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation  # type: ignore[import-untyped]

from .figures import _clean_axis, _configure
from .xlsx import iter_rows


FULL_VARIANT = "EgoAnchor"
"""重放使用的完整系统候选子集。"""

PREDICT_TO_NOW = "Kalman Predict-to-Now (offline replay)"
"""把 Kalman 状态直接预测到当前渲染时刻的反事实策略。"""

DELAYED_HERMITE = "Kalman Delayed Hermite Interpolation (offline replay)"
"""在带意图延迟的历史控制点之间进行 Hermite 插值的反事实策略。"""


@dataclass(frozen=True, slots=True)
class TemporalReplaySettings:
    """保存与 Unity Kalman/HermiteStrategy 对齐的重放参数。"""

    position_process_noise: float = 0.20
    """位置过程噪声，单位 m²/s。"""

    position_measurement_noise: float = 0.0004
    """位置测量噪声，单位 m²。"""

    rotation_process_noise: float = 0.40
    """旋转过程噪声，单位 rad²/s。"""

    rotation_measurement_noise: float = 0.0025
    """旋转测量噪声，单位 rad²。"""

    tangent_chord_ratio: float = 3.0
    """Hermite 端点速度相对控制点弦长的限幅倍数。"""


@dataclass(slots=True)
class _ScalarKalman:
    """一维常速度 Kalman 状态，复刻 Unity 的位置/速度更新。"""

    position: float = 0.0
    velocity: float = 0.0
    p00: float = 0.0
    p01: float = 0.0
    p10: float = 0.0
    p11: float = 0.0
    has_state: bool = False

    def reset(self, position: float, variance: float) -> None:
        """将状态吸附到首个观测。"""

        self.position = float(position)
        self.velocity = 0.0
        self.p00 = max(float(variance), 1e-9)
        self.p01 = 0.0
        self.p10 = 0.0
        self.p11 = 1.0
        self.has_state = True

    def predict(self, dt: float, process_noise: float) -> None:
        """执行常速度模型预测。"""

        if not self.has_state:
            return
        safe_dt = max(float(dt), 0.0)
        q = max(float(process_noise), 0.0)
        self.position += self.velocity * safe_dt
        next_p00 = self.p00 + safe_dt * (self.p10 + self.p01) + safe_dt * safe_dt * self.p11 + q * safe_dt
        next_p01 = self.p01 + safe_dt * self.p11
        next_p10 = self.p10 + safe_dt * self.p11
        next_p11 = self.p11 + q * safe_dt
        self.p00, self.p01, self.p10, self.p11 = next_p00, next_p01, next_p10, next_p11

    def correct(self, measurement: float, measurement_noise: float) -> None:
        """执行位置测量校正。"""

        if not self.has_state:
            self.reset(measurement, measurement_noise)
            return
        r = max(float(measurement_noise), 1e-9)
        innovation = float(measurement) - self.position
        s = max(self.p00 + r, 1e-12)
        k0 = self.p00 / s
        k1 = self.p10 / s
        self.position += k0 * innovation
        self.velocity += k1 * innovation
        next_p00 = (1.0 - k0) * self.p00
        next_p01 = (1.0 - k0) * self.p01
        next_p10 = self.p10 - k1 * self.p00
        next_p11 = self.p11 - k1 * self.p01
        self.p00, self.p01, self.p10, self.p11 = next_p00, next_p01, next_p10, next_p11


@dataclass(frozen=True, slots=True)
class _ControlPoint:
    """一个带时间和速度切线的 Kalman 去噪控制点。"""

    time_ms: float
    position: np.ndarray
    rotation: np.ndarray
    linear_velocity: np.ndarray
    angular_velocity: np.ndarray


class _KalmanPoseReplay:
    """复刻 Unity KalmanModel 的平移与旋转切空间状态。"""

    def __init__(self, settings: TemporalReplaySettings) -> None:
        """创建空状态。"""

        self.settings = settings
        self._position = [_ScalarKalman() for _ in range(3)]
        self._rotation = [_ScalarKalman() for _ in range(3)]
        self._rotation_reference = Rotation.identity()
        self._last_time_ms = 0.0
        self._has_state = False

    def update(self, time_ms: float, position: np.ndarray, quaternion_xyzw: np.ndarray) -> _ControlPoint:
        """吸收一条采集时刻世界位姿并返回最新控制点。"""

        measurement_time = float(time_ms)
        measured_position = np.asarray(position, dtype=float)
        measured_rotation = Rotation.from_quat(_normalize_quaternion(quaternion_xyzw))
        if not self._has_state:
            for state, value in zip(self._position, measured_position, strict=True):
                state.reset(float(value), self.settings.position_measurement_noise)
            self._rotation_reference = measured_rotation
            for state in self._rotation:
                state.reset(0.0, self.settings.rotation_measurement_noise)
            self._last_time_ms = measurement_time
            self._has_state = True
            return self.control_point()

        dt_seconds = max((measurement_time - self._last_time_ms) / 1000.0, 0.0)
        for state in self._position:
            state.predict(dt_seconds, self.settings.position_process_noise)
        for state in self._rotation:
            state.predict(dt_seconds, self.settings.rotation_process_noise)
        self._last_time_ms = measurement_time
        for state, value in zip(self._position, measured_position, strict=True):
            state.correct(float(value), self.settings.position_measurement_noise)
        relative = self._rotation_reference.inv() * measured_rotation
        error = relative.as_rotvec()
        for state, value in zip(self._rotation, error, strict=True):
            state.correct(float(value), self.settings.rotation_measurement_noise)
        return self.control_point()

    def position_at(self, time_ms: float) -> np.ndarray:
        """把平移状态预测到指定时刻。"""

        ahead = (float(time_ms) - self._last_time_ms) / 1000.0
        return np.asarray([state.position + state.velocity * ahead for state in self._position], dtype=float)

    def rotation_at(self, time_ms: float) -> Rotation:
        """把旋转切空间状态预测到指定时刻。"""

        ahead = (float(time_ms) - self._last_time_ms) / 1000.0
        rotvec = np.asarray([state.position + state.velocity * ahead for state in self._rotation], dtype=float)
        return self._rotation_reference * Rotation.from_rotvec(rotvec)

    def predict_at(self, time_ms: float) -> tuple[np.ndarray, np.ndarray]:
        """返回 Predict-to-Now 的当前时刻位姿。"""

        return self.position_at(time_ms), self.rotation_at(time_ms).as_quat()

    def control_point(self) -> _ControlPoint:
        """读取最近一次观测时刻的去噪控制点。"""

        position = np.asarray([state.position for state in self._position], dtype=float)
        velocity = np.asarray([state.velocity for state in self._position], dtype=float)
        rotvec = np.asarray([state.position for state in self._rotation], dtype=float)
        angular_velocity = np.asarray([state.velocity for state in self._rotation], dtype=float)
        rotation = (self._rotation_reference * Rotation.from_rotvec(rotvec)).as_quat()
        return _ControlPoint(self._last_time_ms, position, rotation, velocity, angular_velocity)


def _normalize_quaternion(quaternion: np.ndarray) -> np.ndarray:
    """归一化四元数；非法输入抛出数据错误。"""

    value = np.asarray(quaternion, dtype=float)
    norm = float(np.linalg.norm(value))
    if value.shape != (4,) or not math.isfinite(norm) or norm < 1e-9:
        raise ValueError("重放遇到非法四元数")
    return value / norm


def _hermite_vector(p1: np.ndarray, v1: np.ndarray, p2: np.ndarray, v2: np.ndarray, u: float, span_seconds: float) -> np.ndarray:
    """计算三次 Hermite 向量插值。"""

    u2 = u * u
    u3 = u2 * u
    h00 = 2.0 * u3 - 3.0 * u2 + 1.0
    h10 = u3 - 2.0 * u2 + u
    h01 = -2.0 * u3 + 3.0 * u2
    h11 = u3 - u2
    return p1 * h00 + (v1 * span_seconds) * h10 + p2 * h01 + (v2 * span_seconds) * h11


def _clamp_vector(value: np.ndarray, maximum: float) -> np.ndarray:
    """按模长限制 Hermite 端点速度。"""

    norm = float(np.linalg.norm(value))
    if norm < 1e-9 or norm <= maximum:
        return value
    return value * (maximum / norm)


def _delayed_pose(points: Sequence[_ControlPoint], target_ms: float, settings: TemporalReplaySettings) -> tuple[np.ndarray, np.ndarray]:
    """在控制点之间执行 Delayed Hermite 插值。"""

    if not points:
        raise ValueError("Hermite 重放缺少控制点")
    if len(points) == 1 or target_ms <= points[0].time_ms:
        return points[0].position.copy(), points[0].rotation.copy()
    if target_ms >= points[-1].time_ms:
        last = points[-1]
        ahead = (target_ms - last.time_ms) / 1000.0
        position = last.position + last.linear_velocity * ahead
        rotation = Rotation.from_quat(last.rotation) * Rotation.from_rotvec(last.angular_velocity * ahead)
        return position, rotation.as_quat()
    index = max(i for i in range(len(points) - 1) if points[i].time_ms <= target_ms)
    first, second = points[index], points[index + 1]
    span_seconds = max((second.time_ms - first.time_ms) / 1000.0, 1e-6)
    u = float(np.clip((target_ms - first.time_ms) / (second.time_ms - first.time_ms), 0.0, 1.0))
    position_chord = second.position - first.position
    position_cap = settings.tangent_chord_ratio * float(np.linalg.norm(position_chord)) / span_seconds
    position = _hermite_vector(
        first.position,
        _clamp_vector(first.linear_velocity, position_cap),
        second.position,
        _clamp_vector(second.linear_velocity, position_cap),
        u,
        span_seconds,
    )
    first_rotation = Rotation.from_quat(first.rotation)
    second_rotation = Rotation.from_quat(second.rotation)
    log_end = (first_rotation.inv() * second_rotation).as_rotvec()
    rotation_cap = settings.tangent_chord_ratio * float(np.linalg.norm(log_end)) / span_seconds
    rotvec = _hermite_vector(
        np.zeros(3),
        _clamp_vector(first.angular_velocity, rotation_cap),
        log_end,
        _clamp_vector(second.angular_velocity, rotation_cap),
        u,
        span_seconds,
    )
    return position, (first_rotation * Rotation.from_rotvec(rotvec)).as_quat()


def _read_vector(row: Mapping[str, Any], field: str, length: int) -> np.ndarray | None:
    """读取原始数组或 Stage 1 展平后的固定长度向量。"""

    value = row.get(field)
    if isinstance(value, (list, tuple)) and len(value) == length:
        array = np.asarray(value, dtype=float)
    else:
        suffixes = ("x_m", "y_m", "z_m") if field.endswith("_pos") else ("x", "y", "z", "w")
        if len(suffixes) != length:
            return None
        try:
            array = np.asarray([float(row[f"{field}_{suffix}"]) for suffix in suffixes], dtype=float)
        except (KeyError, TypeError, ValueError):
            return None
    return array if np.isfinite(array).all() else None


def _is_valid_event(row: Mapping[str, Any]) -> bool:
    """排除事件外的 warmup 行。"""

    return row.get("event_id") not in {None, "", "@empty-text"}


def _quantile(values: Iterable[float], probability: float) -> float:
    """计算有限样本分位数。"""

    array = np.asarray([float(value) for value in values if math.isfinite(float(value))], dtype=float)
    return float(np.quantile(array, probability, method="linear")) if array.size else math.nan


def _fitted_translation_lag(times: np.ndarray, display: np.ndarray, reference: np.ndarray) -> tuple[float, float]:
    """用与 GPT v4 相同的 0--600 ms 网格计算有效时延和对齐 RMSE。"""

    best_rmse = math.inf
    best_lag = math.nan
    for lag_ms in np.arange(0.0, 600.01, 5.0):
        query = times - lag_ms
        valid = (query >= times[0]) & (query <= times[-1])
        if int(valid.sum()) < 30:
            continue
        interpolated = np.column_stack([np.interp(query[valid], times, reference[:, axis]) for axis in range(3)])
        distances_mm = 1000.0 * np.linalg.norm(display[valid] - interpolated, axis=1)
        rmse = float(np.sqrt(np.mean(np.square(distances_mm))))
        if rmse < best_rmse:
            best_rmse, best_lag = rmse, float(lag_ms)
    return best_lag, best_rmse


def _scenario_rows(workbooks: Sequence[Path], sheet: str, columns: Sequence[str], scenario: str) -> list[dict[str, Any]]:
    """读取指定场景的 Stage 1 行，并保留事件前 warmup。"""

    rows: list[dict[str, Any]] = []
    for workbook in workbooks:
        for row in iter_rows(workbook, sheet, columns):
            if str(row.get("scenario_id", "")) == scenario:
                rows.append(row)
    return rows


def _replay_event(
    admissions: Sequence[Mapping[str, Any]],
    renders: Sequence[Mapping[str, Any]],
    settings: TemporalReplaySettings,
) -> list[dict[str, Any]]:
    """按时间顺序重放一个动作事件的两种策略。"""

    ordered_admissions = sorted(admissions, key=lambda row: float(row["unity_pose_handle_mono_ms"]))
    ordered_renders = sorted(renders, key=lambda row: float(row["render_mono_ms"]))
    model = _KalmanPoseReplay(settings)
    points: list[_ControlPoint] = []
    replay_rows: list[dict[str, Any]] = []
    admission_index = 0
    seen_candidates: set[str] = set()
    latency_estimate_seconds = 0.0
    delay_seconds = 0.25
    previous_render_ms = 0.0
    for render in ordered_renders:
        render_time = float(render["render_mono_ms"])
        while admission_index < len(ordered_admissions):
            admission = ordered_admissions[admission_index]
            handle_time = float(admission["unity_pose_handle_mono_ms"])
            if handle_time > render_time + 1e-6:
                break
            admission_index += 1
            candidate_id = str(admission.get("candidate_id", ""))
            if candidate_id in seen_candidates or admission.get("admission_decision") != "accepted":
                continue
            position = _read_vector(admission, "aligned_raw_pos", 3)
            rotation = _read_vector(admission, "aligned_raw_rot", 4)
            if position is None or rotation is None:
                continue
            seen_candidates.add(candidate_id)
            point = model.update(float(admission["source_capture_mono_ms"]), position, rotation)
            points.append(point)
            if len(points) > 64:
                del points[:-64]
        if not points:
            continue
        reference = _read_vector(render, "reference_pos", 3)
        reference_rotation = _read_vector(render, "reference_rot", 4)
        if reference is None or reference_rotation is None:
            continue
        predict_position, predict_rotation = model.predict_at(render_time)
        observed_latency = max((render_time - points[-1].time_ms) / 1000.0, 0.0)
        follow = 0.5 if observed_latency > latency_estimate_seconds else 0.05
        latency_estimate_seconds += follow * (observed_latency - latency_estimate_seconds)
        target_delay = max(latency_estimate_seconds * 1.15, 0.25)
        max_delta = 0.05 * max((render_time - previous_render_ms) / 1000.0, 0.0)
        delay_seconds += float(np.clip(target_delay - delay_seconds, -max_delta, max_delta))
        previous_render_ms = render_time
        target_ms = render_time - delay_seconds * 1000.0
        delayed_position, delayed_rotation = _delayed_pose(points, target_ms, settings)
        for strategy, position, rotation in (
            (PREDICT_TO_NOW, predict_position, predict_rotation),
            (DELAYED_HERMITE, delayed_position, delayed_rotation),
        ):
            replay_rows.append(
                {
                    "session_id": str(render.get("session_id", "")),
                    "scenario_id": str(render.get("scenario_id", "")),
                    "trial_id": str(render.get("trial_id", "")),
                    "event_id": str(render.get("event_id", "")),
                    "render_mono_ms": render_time,
                    "strategy": strategy,
                    "effective_lag_ms": render_time - target_ms if strategy == DELAYED_HERMITE else 0.0,
                    "position": position,
                    "rotation": rotation,
                    "reference_position": reference,
                    "reference_rotation": reference_rotation,
                }
            )
    return replay_rows


def _event_metrics(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把逐渲染帧重放结果汇总为事件级指标。"""

    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        if not _is_valid_event(row):
            continue
        key = (str(row["session_id"]), str(row["trial_id"]), str(row["event_id"]), str(row["strategy"]))
        grouped.setdefault(key, []).append(row)
    metrics: list[dict[str, Any]] = []
    for (session_id, trial_id, event_id, strategy), group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda row: float(row["render_mono_ms"]))
        positions = np.asarray([row["position"] for row in ordered], dtype=float)
        references = np.asarray([row["reference_position"] for row in ordered], dtype=float)
        times = np.asarray([float(row["render_mono_ms"]) for row in ordered], dtype=float)
        errors_mm = 1000.0 * np.linalg.norm(positions - references, axis=1)
        increments_mm = 1000.0 * np.linalg.norm(np.diff(positions, axis=0), axis=1)
        fitted_lag_ms, aligned_rmse_mm = _fitted_translation_lag(times, positions, references)
        tail_count = max(2, int(math.ceil(len(increments_mm) * 0.2))) if increments_mm.size else 0
        tail = increments_mm[-tail_count:] if tail_count else np.asarray([], dtype=float)
        metrics.append(
            {
                "session_id": session_id,
                "trial_id": trial_id,
                "event_id": event_id,
                "strategy": strategy,
                "effective_lag_ms": fitted_lag_ms,
                "lag_aligned_rmse_mm": aligned_rmse_mm,
                "translation_p95_mm": _quantile(errors_mm, 0.95),
                "frame_increment_p95_mm": _quantile(increments_mm, 0.95),
                "near_zero_increment_ratio": float(np.mean(increments_mm < 0.05)) if increments_mm.size else math.nan,
                "post_stop_increment_p95_mm": _quantile(tail, 0.95),
                "render_samples": int(len(ordered)),
            }
        )
    return metrics


def run_temporal_replay(
    workbooks: Sequence[Path],
    output_dir: Path,
    *,
    scenario: str = "start_stop_6dof",
    settings: TemporalReplaySettings | None = None,
) -> Mapping[str, Path]:
    """从 workbook 生成逐帧和事件级时序反事实结果。"""

    replay_settings = settings or TemporalReplaySettings()
    admission_columns = (
        "session_id", "scenario_id", "trial_id", "event_id", "variant_id", "candidate_id",
        "unity_pose_handle_mono_ms", "source_capture_mono_ms", "has_aligned_raw", "aligned_raw_pos",
        "aligned_raw_rot", "aligned_raw_pos_x_m", "aligned_raw_pos_y_m", "aligned_raw_pos_z_m",
        "aligned_raw_rot_x", "aligned_raw_rot_y", "aligned_raw_rot_z", "aligned_raw_rot_w", "admission_decision",
    )
    render_columns = (
        "session_id", "scenario_id", "trial_id", "event_id", "variant_id", "render_mono_ms",
        "reference_pose_valid", "reference_pos", "reference_rot", "reference_pos_x_m", "reference_pos_y_m",
        "reference_pos_z_m", "reference_rot_x", "reference_rot_y", "reference_rot_z", "reference_rot_w",
        "policy_output_target_mono_ms", "smoothing_delay_ms",
    )
    admissions = [
        row for row in _scenario_rows(workbooks, "unity_admission", admission_columns, scenario)
        if row.get("variant_id") == FULL_VARIANT and row.get("has_aligned_raw") is True
    ]
    renders = [
        row for row in _scenario_rows(workbooks, "unity_render", render_columns, scenario)
        if row.get("variant_id") == FULL_VARIANT and row.get("reference_pose_valid") is True
    ]
    admission_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    render_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in admissions:
        key = (str(row["session_id"]), str(row["trial_id"]))
        admission_groups.setdefault(key, []).append(row)
    for row in renders:
        key = (str(row["session_id"]), str(row["trial_id"]))
        render_groups.setdefault(key, []).append(row)
    frame_rows: list[dict[str, Any]] = []
    for key in sorted(set(admission_groups) & set(render_groups)):
        frame_rows.extend(_replay_event(admission_groups[key], render_groups[key], replay_settings))
    metric_rows = _event_metrics(frame_rows)
    destination = output_dir.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    frame_path = destination / f"temporal_replay_{scenario}_frames.csv"
    metric_path = destination / f"temporal_replay_{scenario}_metrics.csv"
    settings_path = destination / f"temporal_replay_{scenario}_settings.csv"
    with metric_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(metric_rows[0]) if metric_rows else (
            "session_id", "trial_id", "event_id", "strategy", "effective_lag_ms", "translation_p95_mm",
            "lag_aligned_rmse_mm", "frame_increment_p95_mm", "near_zero_increment_ratio",
            "post_stop_increment_p95_mm", "render_samples",
        ))
        writer.writeheader()
        writer.writerows(metric_rows)
    frame_fields = (
        "session_id", "scenario_id", "trial_id", "event_id", "render_mono_ms", "strategy",
        "effective_lag_ms", "position_x_m", "position_y_m", "position_z_m", "reference_x_m",
        "reference_y_m", "reference_z_m",
    )
    with frame_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=frame_fields)
        writer.writeheader()
        for row in frame_rows:
            position = np.asarray(row["position"], dtype=float)
            reference = np.asarray(row["reference_position"], dtype=float)
            writer.writerow({
                "session_id": row["session_id"], "scenario_id": row["scenario_id"], "trial_id": row["trial_id"],
                "event_id": row["event_id"], "render_mono_ms": row["render_mono_ms"], "strategy": row["strategy"],
                "effective_lag_ms": row["effective_lag_ms"], "position_x_m": position[0], "position_y_m": position[1],
                "position_z_m": position[2], "reference_x_m": reference[0], "reference_y_m": reference[1],
                "reference_z_m": reference[2],
            })
    with settings_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("parameter", "value", "note"))
        writer.writeheader()
        writer.writerows([
            {"parameter": "position_process_noise", "value": replay_settings.position_process_noise, "note": "复刻 Unity KalmanModel"},
            {"parameter": "position_measurement_noise", "value": replay_settings.position_measurement_noise, "note": "复刻 Unity KalmanModel"},
            {"parameter": "rotation_process_noise", "value": replay_settings.rotation_process_noise, "note": "复刻 Unity KalmanModel"},
            {"parameter": "rotation_measurement_noise", "value": replay_settings.rotation_measurement_noise, "note": "复刻 Unity KalmanModel"},
            {"parameter": "tangent_chord_ratio", "value": replay_settings.tangent_chord_ratio, "note": "复刻 HermiteStrategy"},
            {"parameter": "scenario", "value": scenario, "note": "离线反事实诊断场景"},
        ])
    return {"frames": frame_path, "metrics": metric_path, "settings": settings_path}


def publish_temporal_replay_figure(metrics_path: Path, pdf_path: Path, png_path: Path) -> Mapping[str, Path]:
    """绘制时序 replay 的事件级 lag--residual 配对图。"""

    with metrics_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    grouped: dict[str, list[Mapping[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["event_id"], []).append(row)
    _configure()
    colors = {PREDICT_TO_NOW: "#B07AA1", DELAYED_HERMITE: "#E15759"}
    labels = {PREDICT_TO_NOW: "Predict-to-Now", DELAYED_HERMITE: "Delayed Hermite"}
    figure, axis = plt.subplots(figsize=(4.7, 3.1), dpi=180)
    for event_id, event_rows in sorted(grouped.items()):
        points = {
            row["strategy"]: (float(row["effective_lag_ms"]), float(row["lag_aligned_rmse_mm"]))
            for row in event_rows
        }
        if PREDICT_TO_NOW not in points or DELAYED_HERMITE not in points:
            continue
        predict = points[PREDICT_TO_NOW]
        delayed = points[DELAYED_HERMITE]
        axis.plot([predict[0], delayed[0]], [predict[1], delayed[1]], color="#7F8790", linewidth=0.75, alpha=0.35)
        for strategy, point in ((PREDICT_TO_NOW, predict), (DELAYED_HERMITE, delayed)):
            axis.scatter(point[0], point[1], s=24, color=colors[strategy], edgecolor="white", linewidth=0.4,
                          label=labels[strategy] if event_id == sorted(grouped)[0] else None, zorder=3)
    axis.set_xlabel("Fitted effective lag (ms)")
    axis.set_ylabel("Lag-aligned translation RMSE (mm)")
    axis.set_title("Start-stop temporal replay (offline counterfactual)", loc="left", fontweight="bold", pad=15)
    _clean_axis(axis, "both")
    axis.legend(frameon=False, loc="upper right")
    figure.tight_layout(pad=0.6)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(pdf_path, bbox_inches="tight")
    figure.savefig(png_path, bbox_inches="tight", dpi=220)
    plt.close(figure)
    return {"pdf": pdf_path, "png": png_path}


def temporal_replay_summary(metrics_path: Path) -> Mapping[str, Mapping[str, float]]:
    """汇总两种策略的事件级中位数。"""

    with metrics_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    summary: dict[str, Mapping[str, float]] = {}
    for strategy in (DELAYED_HERMITE, PREDICT_TO_NOW):
        selected = [row for row in rows if row["strategy"] == strategy]
        summary[strategy] = {
            "event_count": float(len(selected)),
            "effective_lag_ms": float(np.median([float(row["effective_lag_ms"]) for row in selected])),
            "lag_aligned_rmse_mm": float(np.median([float(row["lag_aligned_rmse_mm"]) for row in selected])),
            "post_stop_increment_p95_mm": float(np.median([float(row["post_stop_increment_p95_mm"]) for row in selected])),
        }
    return summary


__all__ = [
    "DELAYED_HERMITE",
    "FULL_VARIANT",
    "PREDICT_TO_NOW",
    "TemporalReplaySettings",
    "run_temporal_replay",
    "publish_temporal_replay_figure",
    "temporal_replay_summary",
]
