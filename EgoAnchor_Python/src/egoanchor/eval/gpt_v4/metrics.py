"""从五本 Stage 1 XLSX 复刻 GPT corrected-newdata-v4 指标。"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation, Slerp  # type: ignore[import-untyped]

from .settings import GptV4Settings, load_settings
from .xlsx import iter_rows, workbook_sha256


FULL_VARIANT = "EgoAnchor"
"""正式论文中完整 Linear/SLERP 系统的 variant ID。"""

HERMITE_VARIANT = "EgoAnchor Hermite"
"""v3 中保留的 Hermite 对照 variant ID。"""

METHODS = ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", FULL_VARIANT)
"""实验一正式比较的四种系统配置。"""

NO_STATIC_LOCK = "EgoAnchor w/o StaticLock"
NO_VCD = "EgoAnchor w/o VCD"
NO_TEMPORAL_SYNTHESIS = "EgoAnchor w/o temporal synthesis"


@dataclass(frozen=True, slots=True)
class GptV4Results:
    """保存 GPT v4 图、表和论文文字需要的全部片段级结果。"""

    workbook_sha256: Mapping[str, str]
    """五本只读 Stage 1 XLSX 的文件摘要。"""

    static_segments: Mapping[str, tuple[Mapping[str, Any], ...]]
    """静止头动片段的中心化、绝对和帧间增量 P95。"""

    translation_segments: Mapping[str, tuple[Mapping[str, Any], ...]]
    """持续平移片段的有效时延和对齐 RMSE。"""

    rotation_segments: Mapping[str, tuple[Mapping[str, Any], ...]]
    """持续旋转片段的有效角时延和对齐角 RMSE。"""

    occlusion_episodes: Mapping[str, tuple[Mapping[str, Any], ...]]
    """遮挡过程的平移 P95 与灾难性失效标识。"""

    transition_segments: Mapping[str, tuple[Mapping[str, Any], ...]]
    """起停片段的显示响应代价。"""

    capture_alignment: tuple[Mapping[str, Any], ...]
    """同一候选 capture-time 与 arrival-time 世界复合的片段级比较。"""

    performance: Mapping[str, float | int]
    """Python 候选处理和发布间隔审计。"""


def segment_identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """返回跨配置严格配对使用的片段身份。"""

    return str(row["session_id"]), str(row["trial_id"]), str(row["segment_id"])


def paired_metric_matrix(
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    variants: Sequence[str],
    keys: Sequence[str],
) -> np.ndarray:
    """按片段身份组成 ``episode x variant x metric`` 矩阵。"""

    if not variants:
        raise ValueError("严格配对至少需要一个配置")
    per_variant: dict[str, dict[tuple[str, str, str], tuple[float, ...]]] = {}
    for variant in variants:
        values: dict[tuple[str, str, str], tuple[float, ...]] = {}
        for row in rows.get(variant, ()):
            identity = segment_identity(row)
            if identity in values:
                raise ValueError(f"片段键重复：{variant}/{identity}")
            metrics = tuple(float(row[key]) for key in keys)
            if all(np.isfinite(metrics)):
                values[identity] = metrics
        per_variant[variant] = values
    expected = set(per_variant[variants[0]])
    if not expected or any(set(per_variant[variant]) != expected for variant in variants[1:]):
        counts = ", ".join(f"{variant}={len(per_variant[variant])}" for variant in variants)
        raise ValueError(f"配置片段配对不完整：{counts}")
    return np.asarray(
        [
            [per_variant[variant][identity] for variant in variants]
            for identity in sorted(expected)
        ],
        dtype=float,
    )


def _truthy(value: Any) -> bool:
    """统一解释 XLSX 中的布尔值。"""

    return value is True or (isinstance(value, str) and value.lower() == "true") or value == 1


def _finite_vector(row: Mapping[str, Any], prefix: str, suffixes: Sequence[str]) -> np.ndarray | None:
    """读取固定长度向量；缺失或非有限值返回 ``None``。"""

    try:
        vector = np.asarray([float(row[f"{prefix}_{suffix}"]) for suffix in suffixes], dtype=float)
    except (KeyError, TypeError, ValueError):
        return None
    return vector if np.isfinite(vector).all() else None


def _quantile(values: np.ndarray, probability: float) -> float:
    """使用 NumPy linear 分位数，与 GPT 示例的 ``np.quantile`` 保持一致。"""

    if values.size == 0:
        return math.nan
    return float(np.quantile(values, probability, method="linear"))


def _valid_event(row: Mapping[str, Any]) -> bool:
    """排除未处于人工动作片段内的空 event 行。"""

    event_id = row.get("event_id")
    return event_id not in {None, "", "@empty-text"}


def _segment_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """用 session、trial、event 和 variant 保持跨 workbook 片段唯一。"""

    return (
        str(row.get("session_id", "")),
        str(row.get("trial_id", "")),
        str(row.get("event_id", "")),
        str(row.get("variant_id", "")),
    )


def _scenario_matches(value: Any, token: str) -> bool:
    """允许代码和采集配置在 6DoF 拼写上存在大小写差异。"""

    return token in str(value or "").lower().replace("-", "_")


_RENDER_COLUMNS = (
    "session_id",
    "scenario_id",
    "trial_id",
    "event_id",
    "variant_id",
    "render_mono_ms",
    "has_display_pose",
    "reference_pose_valid",
    "display_pos_x_m",
    "display_pos_y_m",
    "display_pos_z_m",
    "reference_pos_x_m",
    "reference_pos_y_m",
    "reference_pos_z_m",
    "display_rot_x",
    "display_rot_y",
    "display_rot_z",
    "display_rot_w",
    "reference_rot_x",
    "reference_rot_y",
    "reference_rot_z",
    "reference_rot_w",
)


def _collect_render(
    workbooks: Sequence[Path],
) -> Mapping[tuple[str, str, str, str, str], list[tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray]]]:
    """读取有效 display/reference 行并按动作片段分组。"""

    grouped: defaultdict[
        tuple[str, str, str, str, str],
        list[tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
    ] = defaultdict(list)
    for workbook in workbooks:
        for row in iter_rows(workbook, "unity_render", _RENDER_COLUMNS):
            if not _valid_event(row) or not _truthy(row.get("has_display_pose")):
                continue
            if not _truthy(row.get("reference_pose_valid")):
                continue
            display_position = _finite_vector(row, "display_pos", ("x_m", "y_m", "z_m"))
            reference_position = _finite_vector(row, "reference_pos", ("x_m", "y_m", "z_m"))
            display_rotation = _finite_vector(row, "display_rot", ("x", "y", "z", "w"))
            reference_rotation = _finite_vector(row, "reference_rot", ("x", "y", "z", "w"))
            try:
                time_ms = float(row["render_mono_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            if any(value is None for value in (display_position, reference_position, display_rotation, reference_rotation)):
                continue
            key = _segment_key(row)
            scenario = str(row.get("scenario_id", ""))
            grouped[(scenario, *key)].append(
                (
                    time_ms,
                    display_position,  # type: ignore[arg-type]
                    reference_position,  # type: ignore[arg-type]
                    display_rotation,  # type: ignore[arg-type]
                    reference_rotation,  # type: ignore[arg-type]
                )
            )
    return grouped


def _event_roles(workbooks: Sequence[Path]) -> Mapping[tuple[str, str, str], str]:
    """从事件总表恢复每个动作片段的人工角色。"""

    roles: dict[tuple[str, str, str], str] = {}
    event_columns = ("event_row_id", "session_id", "trial_id", "event_id")
    payload_columns = ("event_row_id", "event_role")
    for workbook in workbooks:
        contexts = {
            str(row["event_row_id"]): (
                str(row.get("session_id", "")),
                str(row.get("trial_id", "")),
                str(row.get("event_id", "")),
            )
            for row in iter_rows(workbook, "events", event_columns)
            if _valid_event(row)
        }
        for row in iter_rows(workbook, "event_payload", payload_columns):
            role = str(row.get("event_role") or "")
            context = contexts.get(str(row.get("event_row_id", "")))
            if context is None or not role:
                continue
            previous = roles.setdefault(context, role)
            if previous != role:
                raise ValueError(f"同一动作片段存在冲突 event_role：{context}: {previous} / {role}")
    return roles


def _sorted_arrays(
    rows: Iterable[tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """按时间排序并去除同一 render 时刻的重复样本。"""

    ordered = sorted(rows, key=lambda item: item[0])
    times = np.asarray([item[0] for item in ordered], dtype=float)
    unique_times, indices = np.unique(times, return_index=True)
    display_positions = np.asarray([ordered[index][1] for index in indices], dtype=float)
    reference_positions = np.asarray([ordered[index][2] for index in indices], dtype=float)
    display_rotations = np.asarray([ordered[index][3] for index in indices], dtype=float)
    reference_rotations = np.asarray([ordered[index][4] for index in indices], dtype=float)
    return unique_times, display_positions, reference_positions, display_rotations, reference_rotations


def _lag_grid(settings: GptV4Settings) -> np.ndarray:
    """构造包含上界的冻结有效时延网格。"""

    return np.arange(
        settings.lag_minimum_ms,
        settings.lag_maximum_ms + settings.lag_step_ms * 0.5,
        settings.lag_step_ms,
    )


def _translation_lag(
    times: np.ndarray,
    display: np.ndarray,
    reference: np.ndarray,
    settings: GptV4Settings,
) -> tuple[float, float]:
    """搜索使 display 与历史 reference 位置 RMSE 最小的有效时延。"""

    best = (math.inf, math.nan)
    for lag_ms in _lag_grid(settings):
        query_times = times - lag_ms
        valid = (query_times >= times[0]) & (query_times <= times[-1])
        if int(valid.sum()) < settings.lag_minimum_samples:
            continue
        interpolated = np.column_stack(
            [np.interp(query_times[valid], times, reference[:, axis]) for axis in range(3)]
        )
        distances_mm = 1000.0 * np.linalg.norm(display[valid] - interpolated, axis=1)
        rmse_mm = float(np.sqrt(np.mean(np.square(distances_mm))))
        if rmse_mm < best[0]:
            best = (rmse_mm, float(lag_ms))
    return best[1], best[0]


def _rotation_lag(
    times: np.ndarray,
    display: np.ndarray,
    reference: np.ndarray,
    settings: GptV4Settings,
) -> tuple[float, float]:
    """使用四元数 Slerp 搜索角 RMSE 最小的有效时延。"""

    display = display / np.linalg.norm(display, axis=1, keepdims=True)
    reference = reference / np.linalg.norm(reference, axis=1, keepdims=True)
    display_rotation = Rotation.from_quat(display)
    reference_slerp = Slerp(times, Rotation.from_quat(reference))
    best = (math.inf, math.nan)
    for lag_ms in _lag_grid(settings):
        query_times = times - lag_ms
        valid = (query_times >= times[0]) & (query_times <= times[-1])
        if int(valid.sum()) < settings.lag_minimum_samples:
            continue
        relative = display_rotation[valid].inv() * reference_slerp(query_times[valid])
        errors_deg = np.degrees(relative.magnitude())
        rmse_deg = float(np.sqrt(np.mean(np.square(errors_deg))))
        if rmse_deg < best[0]:
            best = (rmse_deg, float(lag_ms))
    return best[1], best[0]


def _first_sustained(
    times: np.ndarray,
    values: np.ndarray,
    threshold: float,
    persistence_ms: float,
) -> int | None:
    """返回首次持续超过阈值的样本索引。"""

    above = values >= threshold
    for index in np.flatnonzero(above):
        end = int(np.searchsorted(times, times[index] + persistence_ms, side="left"))
        if end >= len(times):
            break
        if bool(above[index : end + 1].all()):
            return int(index)
    return None


def _transition_response(
    times: np.ndarray,
    display: np.ndarray,
    reference: np.ndarray,
    settings: GptV4Settings,
) -> float:
    """复刻 GPT v4 的 250 ms 基线、5 mm、100 ms 持续响应定义。"""

    elapsed = times - times[0]
    baseline = elapsed <= settings.transition_baseline_ms
    if not bool(baseline.any()):
        return math.nan
    display_origin = np.median(display[baseline], axis=0)
    reference_origin = np.median(reference[baseline], axis=0)
    display_displacement = 1000.0 * np.linalg.norm(display - display_origin, axis=1)
    reference_displacement = 1000.0 * np.linalg.norm(reference - reference_origin, axis=1)
    reference_index = _first_sustained(
        times,
        reference_displacement,
        settings.transition_displacement_mm,
        settings.transition_persistence_ms,
    )
    display_index = _first_sustained(
        times,
        display_displacement,
        settings.transition_displacement_mm,
        settings.transition_persistence_ms,
    )
    if reference_index is None or display_index is None:
        return math.nan
    return max(0.0, float(times[display_index] - times[reference_index]))


def _render_metrics(
    render: Mapping[tuple[str, str, str, str, str], list[tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray]]],
    event_roles: Mapping[tuple[str, str, str], str],
    settings: GptV4Settings,
) -> tuple[
    Mapping[str, tuple[Mapping[str, Any], ...]],
    Mapping[str, tuple[Mapping[str, Any], ...]],
    Mapping[str, tuple[Mapping[str, Any], ...]],
    Mapping[str, tuple[Mapping[str, Any], ...]],
    Mapping[str, tuple[Mapping[str, Any], ...]],
]:
    """一次遍历生成五类 render 片段指标。"""

    static: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    translation: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    rotation: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    occlusion: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    transition: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for key, rows in render.items():
        scenario, session_id, trial_id, event_id, variant_id = key
        times, display, reference, display_rotation, reference_rotation = _sorted_arrays(rows)
        identity = {"session_id": session_id, "trial_id": trial_id, "segment_id": event_id}
        if _scenario_matches(scenario, "static_head_motion"):
            errors = display - reference
            centered = errors - np.median(errors, axis=0)
            increments = 1000.0 * np.linalg.norm(np.diff(display, axis=0), axis=1)
            static[variant_id].append(
                {
                    **identity,
                    "centered_p95_mm": _quantile(1000.0 * np.linalg.norm(centered, axis=1), 0.95),
                    "absolute_p95_mm": _quantile(1000.0 * np.linalg.norm(errors, axis=1), 0.95),
                    "frame_increment_p95_mm": _quantile(increments, 0.95),
                }
            )
        elif _scenario_matches(scenario, "continuous_translation"):
            lag, residual = _translation_lag(times, display, reference, settings)
            translation[variant_id].append(
                {**identity, "effective_lag_ms": lag, "aligned_rmse_mm": residual}
            )
        elif _scenario_matches(scenario, "continuous_rotation"):
            lag, residual = _rotation_lag(times, display_rotation, reference_rotation, settings)
            rotation[variant_id].append(
                {**identity, "effective_lag_ms": lag, "aligned_rmse_deg": residual}
            )
        elif _scenario_matches(scenario, "occlusion_recovery"):
            if event_roles.get((session_id, trial_id, event_id)) != "occlusion_started":
                continue
            errors_mm = 1000.0 * np.linalg.norm(display - reference, axis=1)
            p95 = _quantile(errors_mm, 0.95)
            occlusion[variant_id].append(
                {
                    **identity,
                    "translation_p95_mm": p95,
                    "catastrophic_gt40": p95 > settings.occlusion_catastrophic_mm,
                }
            )
        elif _scenario_matches(scenario, "start_stop"):
            transition[variant_id].append(
                {
                    **identity,
                    "response_ms": _transition_response(times, display, reference, settings),
                }
            )
    normalize = lambda rows: {key: tuple(value) for key, value in sorted(rows.items())}
    return normalize(static), normalize(translation), normalize(rotation), normalize(occlusion), normalize(transition)


def _capture_alignment(workbooks: Sequence[Path]) -> tuple[Mapping[str, Any], ...]:
    """直接比较完整系统同一 raw candidate 的 capture/arrival 世界复合误差。"""

    references: dict[tuple[str, int], np.ndarray] = {}
    reference_columns = (
        "session_id",
        "frame_id",
        "reference_pose_valid",
        "reference_pos_x_m",
        "reference_pos_y_m",
        "reference_pos_z_m",
    )
    for workbook in workbooks:
        for row in iter_rows(workbook, "unity_reference", reference_columns):
            if not _truthy(row.get("reference_pose_valid")):
                continue
            position = _finite_vector(row, "reference_pos", ("x_m", "y_m", "z_m"))
            try:
                frame_id = int(row["frame_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if position is not None:
                references[(str(row.get("session_id", "")), frame_id)] = position

    grouped: defaultdict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    admission_columns = (
        "session_id",
        "scenario_id",
        "trial_id",
        "event_id",
        "variant_id",
        "frame_id",
        "has_aligned_raw",
        "has_arrival_time_raw",
        "aligned_raw_pos_x_m",
        "aligned_raw_pos_y_m",
        "aligned_raw_pos_z_m",
        "arrival_time_raw_pos_x_m",
        "arrival_time_raw_pos_y_m",
        "arrival_time_raw_pos_z_m",
    )
    for workbook in workbooks:
        for row in iter_rows(workbook, "unity_admission", admission_columns):
            if row.get("variant_id") != FULL_VARIANT or not _valid_event(row):
                continue
            if not _scenario_matches(row.get("scenario_id"), "static_head_motion"):
                continue
            if not _truthy(row.get("has_aligned_raw")) or not _truthy(row.get("has_arrival_time_raw")):
                continue
            aligned = _finite_vector(row, "aligned_raw_pos", ("x_m", "y_m", "z_m"))
            arrival = _finite_vector(row, "arrival_time_raw_pos", ("x_m", "y_m", "z_m"))
            try:
                frame_id = int(row["frame_id"])
            except (KeyError, TypeError, ValueError):
                continue
            reference = references.get((str(row.get("session_id", "")), frame_id))
            if aligned is None or arrival is None or reference is None:
                continue
            key = (str(row.get("session_id", "")), str(row.get("trial_id", "")), str(row["event_id"]))
            grouped[key].append(
                (
                    1000.0 * float(np.linalg.norm(aligned - reference)),
                    1000.0 * float(np.linalg.norm(arrival - reference)),
                )
            )
    output: list[Mapping[str, Any]] = []
    for (session_id, trial_id, segment_id), values in sorted(grouped.items()):
        array = np.asarray(values, dtype=float)
        capture_p95 = _quantile(array[:, 0], 0.95)
        arrival_p95 = _quantile(array[:, 1], 0.95)
        output.append(
            {
                "session_id": session_id,
                "trial_id": trial_id,
                "segment_id": segment_id,
                "capture_p95_mm": capture_p95,
                "arrival_p95_mm": arrival_p95,
                "paired_reduction_mm": arrival_p95 - capture_p95,
                "n_candidates": int(len(array)),
            }
        )
    return tuple(output)


def _performance(workbooks: Sequence[Path]) -> Mapping[str, float | int]:
    """从 Python candidate 日志汇总 GPT v4 的运行时审计数字。"""

    track: list[float] = []
    register: list[float] = []
    intervals: list[float] = []
    columns = ("phase", "total_ms", "has_pose", "server_publish_mono_ms")
    for workbook in workbooks:
        published: list[float] = []
        for row in iter_rows(workbook, "python_candidates", columns):
            try:
                total_ms = float(row["total_ms"])
            except (KeyError, TypeError, ValueError):
                total_ms = math.nan
            if math.isfinite(total_ms):
                if row.get("phase") == "TRACK":
                    track.append(total_ms)
                elif row.get("phase") == "REGISTER":
                    register.append(total_ms)
            if _truthy(row.get("has_pose")):
                try:
                    published.append(float(row["server_publish_mono_ms"]))
                except (KeyError, TypeError, ValueError):
                    pass
        if len(published) > 1:
            intervals.extend(np.diff(np.asarray(sorted(published), dtype=float)).tolist())
    if not track or not register or not intervals:
        raise ValueError("五本 workbook 缺少 TRACK、REGISTER 或 pose publish 性能样本")
    return {
        "track_total_ms_median": float(np.median(track)),
        "track_total_ms_p95": _quantile(np.asarray(track), 0.95),
        "track_n": len(track),
        "register_total_ms_median": float(np.median(register)),
        "register_n": len(register),
        "pose_publish_interval_ms_median": float(np.median(intervals)),
        "pose_publish_rate_hz_from_median": float(1000.0 / np.median(intervals)),
        "pose_publish_interval_n": len(intervals),
    }


def analyze_workbooks(
    workbooks: Sequence[Path],
    settings: GptV4Settings | None = None,
) -> GptV4Results:
    """只读五本 Stage 1 XLSX，返回 GPT v4 论文所需结果。"""

    normalized = tuple(path.expanduser().resolve() for path in workbooks)
    if not normalized:
        raise ValueError("至少需要一本 Stage 1 XLSX")
    for path in normalized:
        if path.suffix.lower() != ".xlsx":
            raise ValueError(f"GPT v4 分析只接受 Stage 1 XLSX：{path}")
        if not path.is_file():
            raise FileNotFoundError(path)
    active_settings = settings or load_settings()
    render = _collect_render(normalized)
    event_roles = _event_roles(normalized)
    static, translation, rotation, occlusion, transition = _render_metrics(
        render,
        event_roles,
        active_settings,
    )
    return GptV4Results(
        workbook_sha256={str(path): workbook_sha256(path) for path in normalized},
        static_segments=static,
        translation_segments=translation,
        rotation_segments=rotation,
        occlusion_episodes=occlusion,
        transition_segments=transition,
        capture_alignment=_capture_alignment(normalized),
        performance=_performance(normalized),
    )


__all__ = [
    "FULL_VARIANT",
    "GptV4Results",
    "HERMITE_VARIANT",
    "METHODS",
    "NO_STATIC_LOCK",
    "NO_TEMPORAL_SYNTHESIS",
    "NO_VCD",
    "analyze_workbooks",
    "paired_metric_matrix",
    "segment_identity",
]
