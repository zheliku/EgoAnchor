"""评估指标共享几何工具。

本模块只处理离线日志中的 Unity 世界系 pose，不导入 egoanchor runtime。
四元数统一使用 Unity/JSON 中的 xyzw 顺序。
"""

from __future__ import annotations

import math
from typing import Iterable, Iterator

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt
from scipy.spatial.transform import Rotation, Slerp

from egoanchor.utils import clamp


METRIC_GROUP_COLUMNS = (
    "session_id",
    "experiment_id",
    "scenario_id",
    "trial_id",
    "event_id",
    "condition_id",
    "variant_id",
    "variant_label",
)
"""trial/event/variant 级指标使用的固定上下文键。"""


def require_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    *,
    table_name: str,
) -> None:
    """严格要求 DataFrame 包含指定列，缺列时拒绝继续计算指标。"""

    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{table_name} 缺少必需列：{', '.join(missing)}")


def iter_metric_groups(frame: pd.DataFrame) -> Iterator[tuple[dict[str, str], pd.DataFrame]]:
    """按固定上下文键遍历指标组，并返回字符串化上下文和组内副本。"""

    require_columns(frame, METRIC_GROUP_COLUMNS, table_name="metric table")
    grouped = frame.groupby(list(METRIC_GROUP_COLUMNS), dropna=False, sort=True)
    for values, group in grouped:
        value_tuple = values if isinstance(values, tuple) else (values,)
        context = {
            column: str(value)
            for column, value in zip(METRIC_GROUP_COLUMNS, value_tuple, strict=True)
        }
        yield context, group.copy()


def is_pose_vector(value: object, length: int) -> bool:
    """判断值是否为给定长度且全部有限的数值位姿向量。"""

    if (
        length <= 0
        or value is None
        or isinstance(value, (str, bytes))
        or not isinstance(value, Iterable)
    ):
        return False
    try:
        items = list(value)
        if any(isinstance(item, (bool, np.bool_)) for item in items):
            return False
        raw = np.asarray(value)
        vector = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return False
    return (
        raw.dtype.kind != "b"
        and vector.shape == (length,)
        and bool(np.isfinite(vector).all())
    )


def normalize_quat(q: Iterable[float]) -> np.ndarray:
    """归一化 xyzw 四元数，并把零长度输入退化为 identity。"""

    quat = np.asarray(q, dtype=float)
    norm = float(np.linalg.norm(quat))
    if norm <= 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=float)
    return quat / norm


def is_pose_value(value: object) -> bool:
    """判断 DataFrame object 列中是否包含可用 pose 数组。"""

    return value is not None and not (isinstance(value, float) and math.isnan(value))


def mat_to_pos_quat(transform: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """把 4x4 齐次矩阵转换成 pos + xyzw 四元数。"""

    matrix = np.asarray(transform, dtype=float)
    if matrix.shape != (4, 4):
        raise ValueError(f"transform 期望 shape=(4,4)，实际 {matrix.shape}。")
    pos = matrix[:3, 3].copy()
    quat = Rotation.from_matrix(matrix[:3, :3]).as_quat()
    return pos, normalize_quat(quat)


def pos_quat_to_mat(pos: Iterable[float], quat: Iterable[float]) -> np.ndarray:
    """把 Unity world pos + xyzw 四元数转换成 4x4 齐次矩阵。"""

    position = np.asarray(pos, dtype=float)
    if position.shape != (3,):
        raise ValueError(f"pos 期望 shape=(3,)，实际 {position.shape}。")
    q = normalize_quat(quat)
    matrix = np.eye(4, dtype=float)
    matrix[:3, :3] = Rotation.from_quat(q).as_matrix()
    matrix[:3, 3] = position
    return matrix


def pose_error(
    reference_pos: Iterable[float],
    reference_quat: Iterable[float],
    display_pos: Iterable[float],
    display_quat: Iterable[float],
) -> tuple[float, float]:
    """直接计算平台 reference 与实际 display pose 的 SE(3) 误差。

    返回:
        `(translation_m, rotation_deg)`，其中误差矩阵为
        `inv(W_T_Reference) @ W_T_Display`。
    """

    w_t_reference = pos_quat_to_mat(reference_pos, reference_quat)
    w_t_display = pos_quat_to_mat(display_pos, display_quat)
    error = np.linalg.inv(w_t_reference) @ w_t_display
    translation_m = float(np.linalg.norm(error[:3, 3]))
    rotation_deg = angle_deg(Rotation.from_matrix(error[:3, :3]).as_quat())
    return translation_m, rotation_deg


def relative_rotation_quat(reference_quat: Iterable[float], display_quat: Iterable[float]) -> np.ndarray:
    """计算 `inv(q_reference) * q_display` 的相对旋转四元数。

    返回 xyzw 顺序，并统一到 `qw >= 0`，方便跨帧求均值和写 CSV。
    """

    relative = (
        Rotation.from_quat(normalize_quat(reference_quat)).inv()
        * Rotation.from_quat(normalize_quat(display_quat))
    ).as_quat()
    if relative[3] < 0.0:
        relative = -relative
    return normalize_quat(relative)


def quat_to_euler_deg(quat: Iterable[float]) -> np.ndarray:
    """把 xyzw 四元数转换为 `xyz` 欧拉角，单位为度，范围为 `[0, 360)`。"""

    return wrap_angle_360_deg(Rotation.from_quat(normalize_quat(quat)).as_euler("xyz", degrees=True))


def wrap_angle_360_deg(angle: Iterable[float] | float) -> np.ndarray | float:
    """把角度包到 `[0, 360)` 区间，方便人读 CSV。"""

    wrapped = np.mod(np.asarray(angle, dtype=float), 360.0)
    wrapped = np.where(np.isclose(wrapped, 360.0, atol=1e-9), 0.0, wrapped)
    if np.ndim(wrapped) == 0:
        return float(wrapped)
    return wrapped


def angle_deg(quat: Iterable[float]) -> float:
    """返回 xyzw 四元数表示的最小旋转角度，单位为度。"""

    q = normalize_quat(quat)
    w = clamp(abs(float(q[3])), -1.0, 1.0)
    return float(math.degrees(2.0 * math.acos(w)))


def slerp_lerp_resample(
    t_src: Iterable[float],
    positions: np.ndarray,
    quaternions: np.ndarray,
    t_dst: Iterable[float],
) -> tuple[np.ndarray, np.ndarray]:
    """把离散位姿重采样到目标时间戳。

    位置使用线性插值，旋转使用 Slerp。目标时间会 clamp 到源时间范围内，
    适合离线 lag/recovery 对齐。
    """

    src = np.asarray(t_src, dtype=float)
    dst = np.asarray(t_dst, dtype=float)
    pos = np.asarray(positions, dtype=float)
    quat = np.asarray(quaternions, dtype=float)
    if src.ndim != 1 or len(src) == 0:
        raise ValueError("t_src 必须是一维且非空。")
    if pos.shape != (len(src), 3):
        raise ValueError(f"positions 期望 shape=({len(src)},3)，实际 {pos.shape}。")
    if quat.shape != (len(src), 4):
        raise ValueError(f"quaternions 期望 shape=({len(src)},4)，实际 {quat.shape}。")
    if len(src) == 1:
        return np.repeat(pos[:1], len(dst), axis=0), np.repeat(np.asarray([normalize_quat(quat[0])]), len(dst), axis=0)

    order = np.argsort(src)
    src_sorted = src[order]
    pos_sorted = pos[order]
    quat_sorted = np.asarray([normalize_quat(q) for q in quat[order]], dtype=float)
    dst_clamped = np.clip(dst, src_sorted[0], src_sorted[-1])

    out_pos = np.column_stack(
        [np.interp(dst_clamped, src_sorted, pos_sorted[:, axis]) for axis in range(3)]
    )
    slerp = Slerp(src_sorted, Rotation.from_quat(quat_sorted))
    out_quat = slerp(dst_clamped).as_quat()
    return out_pos, np.asarray([normalize_quat(q) for q in out_quat], dtype=float)


def highpass(signal: np.ndarray, dt: float, cutoff_hz: float) -> np.ndarray:
    """对一维或二维信号做 Butterworth 高通滤波。

    数据太短无法 `filtfilt` 时，退化为减均值，保证 smoke session 也能出数。
    """

    values = np.asarray(signal, dtype=float)
    if values.size == 0:
        return values.copy()
    if values.ndim == 1:
        work = values[:, None]
        squeeze = True
    elif values.ndim == 2:
        work = values
        squeeze = False
    else:
        raise ValueError(f"signal 只支持 1D/2D，实际 {values.shape}。")

    if dt <= 0.0 or cutoff_hz <= 0.0 or len(work) < 8:
        filtered = work - np.nanmean(work, axis=0, keepdims=True)
        return filtered[:, 0] if squeeze else filtered

    nyquist = 0.5 / dt
    normal_cutoff = min(0.99, cutoff_hz / nyquist)
    if normal_cutoff <= 0.0:
        filtered = work - np.nanmean(work, axis=0, keepdims=True)
    else:
        b, a = butter(2, normal_cutoff, btype="highpass")
        padlen = 3 * max(len(a), len(b))
        if len(work) <= padlen:
            filtered = work - np.nanmean(work, axis=0, keepdims=True)
        else:
            filtered = filtfilt(b, a, work, axis=0)
    return filtered[:, 0] if squeeze else filtered


def project_point(k: np.ndarray, w_t_cam: np.ndarray, p_world: Iterable[float]) -> np.ndarray:
    """把世界点投影到相机像面。

    Args:
        k: 3x3 内参矩阵。
        w_t_cam: 相机在世界系下的 4x4 pose。
        p_world: 世界点。
    """

    intrinsic = np.asarray(k, dtype=float)
    if intrinsic.shape != (3, 3):
        raise ValueError(f"K 期望 shape=(3,3)，实际 {intrinsic.shape}。")
    point = np.asarray(p_world, dtype=float)
    if point.shape != (3,):
        raise ValueError(f"p_world 期望 shape=(3,)，实际 {point.shape}。")
    cam_t_world = np.linalg.inv(np.asarray(w_t_cam, dtype=float))
    p_cam = cam_t_world @ np.array([point[0], point[1], point[2], 1.0], dtype=float)
    if p_cam[2] <= 1e-9:
        return np.array([np.nan, np.nan], dtype=float)
    projected = intrinsic @ p_cam[:3]
    return projected[:2] / projected[2]


__all__ = [
    "METRIC_GROUP_COLUMNS",
    "angle_deg",
    "highpass",
    "is_pose_vector",
    "is_pose_value",
    "iter_metric_groups",
    "mat_to_pos_quat",
    "normalize_quat",
    "pose_error",
    "pos_quat_to_mat",
    "project_point",
    "quat_to_euler_deg",
    "relative_rotation_quat",
    "require_columns",
    "slerp_lerp_resample",
    "wrap_angle_360_deg",
]
