"""schema-v2 实际显示位姿的世界系误差指标。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .common import (
    METRIC_GROUP_COLUMNS,
    is_pose_vector,
    iter_metric_groups,
    pose_error,
    quat_to_euler_deg,
    relative_rotation_quat,
    require_columns,
    wrap_angle_360_deg,
)
from .stats import finite_percentile, rms


_RENDER_COLUMNS = (
    *METRIC_GROUP_COLUMNS,
    "render_tick_id",
    "render_mono_ms",
    "source_frame_id",
    "reference_pose_valid",
    "reference_pos",
    "reference_rot",
    "has_display_pose",
    "display_pos",
    "display_rot",
)
"""显示误差计算依赖的 schema-v2 render 列。"""

DETAIL_COLUMNS = [
    *METRIC_GROUP_COLUMNS,
    "render_tick_id",
    "render_mono_ms",
    "source_frame_id",
    "position_offset_x_m",
    "position_offset_y_m",
    "position_offset_z_m",
    "rotation_offset_euler_x_deg",
    "rotation_offset_euler_y_deg",
    "rotation_offset_euler_z_deg",
    "translation_error_m",
    "translation_error_mm",
    "rotation_error_deg",
    "anchor_state",
    "policy_action",
    "policy_reason",
]
"""逐 render tick 的显示误差字段。"""

SUMMARY_COLUMNS = [
    *METRIC_GROUP_COLUMNS,
    "n",
    "translation_error_mm_median",
    "translation_error_mm_iqr",
    "translation_error_mm_p95",
    "rotation_error_deg_median",
    "rotation_error_deg_iqr",
    "rotation_error_deg_p95",
]
"""trial/event/variant 级显示误差汇总字段。"""

OFFSET_SUMMARY_COLUMNS = [
    *METRIC_GROUP_COLUMNS,
    "n",
    "position_offset_mean_x_m",
    "position_offset_mean_y_m",
    "position_offset_mean_z_m",
    "position_offset_median_x_m",
    "position_offset_median_y_m",
    "position_offset_median_z_m",
    "position_offset_std_x_m",
    "position_offset_std_y_m",
    "position_offset_std_z_m",
    "position_offset_median_norm_m",
    "position_residual_after_median_p50_m",
    "position_residual_after_median_p95_m",
    "position_residual_after_median_rmse_m",
    "rotation_offset_mean_euler_x_deg",
    "rotation_offset_mean_euler_y_deg",
    "rotation_offset_mean_euler_z_deg",
    "rotation_offset_median_euler_x_deg",
    "rotation_offset_median_euler_y_deg",
    "rotation_offset_median_euler_z_deg",
    "rotation_offset_std_euler_x_deg",
    "rotation_offset_std_euler_y_deg",
    "rotation_offset_std_euler_z_deg",
    "rotation_offset_median_deg",
    "rotation_offset_p95_deg",
]
"""trial/event/variant 级固定偏移诊断字段。"""


def compute_anchor_error(render: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """以平台参考和用户实际看到的 display pose 计算世界系误差。"""

    require_columns(render, _RENDER_COLUMNS, table_name="unity_render")
    if render.empty:
        return _empty_detail(), _empty_summary()

    usable = (
        render["reference_pose_valid"].fillna(False).astype(bool)
        & render["has_display_pose"].fillna(False).astype(bool)
        & render["reference_pos"].map(lambda value: is_pose_vector(value, 3))
        & render["reference_rot"].map(lambda value: is_pose_vector(value, 4))
        & render["display_pos"].map(lambda value: is_pose_vector(value, 3))
        & render["display_rot"].map(lambda value: is_pose_vector(value, 4))
    )
    records = [_error_record(row) for _, row in render.loc[usable].iterrows()]
    detail = pd.DataFrame.from_records(records, columns=DETAIL_COLUMNS)
    return detail, summarize_anchor_error(detail)


def _error_record(row: pd.Series) -> dict[str, Any]:
    """把一行有效 render 转换成显示误差明细。"""

    translation_m, rotation_deg = pose_error(
        row["reference_pos"],
        row["reference_rot"],
        row["display_pos"],
        row["display_rot"],
    )
    position_offset = np.asarray(row["display_pos"], dtype=float) - np.asarray(
        row["reference_pos"], dtype=float
    )
    rotation_offset = relative_rotation_quat(row["reference_rot"], row["display_rot"])
    rotation_euler = quat_to_euler_deg(rotation_offset)
    context = {column: str(row[column]) for column in METRIC_GROUP_COLUMNS}
    return {
        **context,
        "render_tick_id": int(row["render_tick_id"]),
        "render_mono_ms": float(row["render_mono_ms"]),
        "source_frame_id": int(row["source_frame_id"]),
        "position_offset_x_m": float(position_offset[0]),
        "position_offset_y_m": float(position_offset[1]),
        "position_offset_z_m": float(position_offset[2]),
        "rotation_offset_euler_x_deg": float(rotation_euler[0]),
        "rotation_offset_euler_y_deg": float(rotation_euler[1]),
        "rotation_offset_euler_z_deg": float(rotation_euler[2]),
        "translation_error_m": translation_m,
        "translation_error_mm": translation_m * 1000.0,
        "rotation_error_deg": rotation_deg,
        "anchor_state": str(row.get("anchor_state", "")),
        "policy_action": str(row.get("policy_action", "")),
        "policy_reason": str(row.get("policy_reason", "")),
    }


def summarize_anchor_error(detail: pd.DataFrame) -> pd.DataFrame:
    """按固定上下文键汇总 display pose 的平移和旋转误差。"""

    require_columns(
        detail,
        (*METRIC_GROUP_COLUMNS, "translation_error_mm", "rotation_error_deg"),
        table_name="anchor_error_detail",
    )
    rows: list[dict[str, Any]] = []
    for context, group in iter_metric_groups(detail):
        translation = group["translation_error_mm"].to_numpy(dtype=float)
        rotation = group["rotation_error_deg"].to_numpy(dtype=float)
        rows.append(
            {
                **context,
                "n": int(len(group)),
                "translation_error_mm_median": finite_percentile(translation, 50),
                "translation_error_mm_iqr": _iqr(translation),
                "translation_error_mm_p95": finite_percentile(translation, 95),
                "rotation_error_deg_median": finite_percentile(rotation, 50),
                "rotation_error_deg_iqr": _iqr(rotation),
                "rotation_error_deg_p95": finite_percentile(rotation, 95),
            }
        )
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def summarize_pose_offset(detail: pd.DataFrame) -> pd.DataFrame:
    """按固定上下文键汇总有符号位置偏移和相对旋转偏移。"""

    required = (
        *METRIC_GROUP_COLUMNS,
        "position_offset_x_m",
        "position_offset_y_m",
        "position_offset_z_m",
        "rotation_offset_euler_x_deg",
        "rotation_offset_euler_y_deg",
        "rotation_offset_euler_z_deg",
        "rotation_error_deg",
    )
    require_columns(detail, required, table_name="anchor_error_detail")
    rows = [_offset_summary(context, group) for context, group in iter_metric_groups(detail)]
    return pd.DataFrame.from_records(rows, columns=OFFSET_SUMMARY_COLUMNS)


def _offset_summary(context: dict[str, str], group: pd.DataFrame) -> dict[str, Any]:
    """汇总一个上下文组内的固定位置与旋转偏移。"""

    position = group[
        ["position_offset_x_m", "position_offset_y_m", "position_offset_z_m"]
    ].to_numpy(dtype=float)
    rotation_euler = group[
        [
            "rotation_offset_euler_x_deg",
            "rotation_offset_euler_y_deg",
            "rotation_offset_euler_z_deg",
        ]
    ].to_numpy(dtype=float)
    position_mean = np.nanmean(position, axis=0)
    position_median = np.nanmedian(position, axis=0)
    position_std = np.nanstd(position, axis=0)
    rotation_unwrapped = np.column_stack(
        [_unwrap_angle_deg(rotation_euler[:, axis]) for axis in range(rotation_euler.shape[1])]
    )
    euler_mean = np.asarray(
        [wrap_angle_360_deg(value) for value in np.nanmean(rotation_unwrapped, axis=0)]
    )
    euler_median = np.asarray(
        [wrap_angle_360_deg(value) for value in np.nanmedian(rotation_unwrapped, axis=0)]
    )
    euler_std = np.nanstd(rotation_unwrapped, axis=0)
    residual_norm = np.linalg.norm(position - position_median, axis=1)
    rotation_error = group["rotation_error_deg"].to_numpy(dtype=float)
    return {
        **context,
        "n": int(len(group)),
        "position_offset_mean_x_m": float(position_mean[0]),
        "position_offset_mean_y_m": float(position_mean[1]),
        "position_offset_mean_z_m": float(position_mean[2]),
        "position_offset_median_x_m": float(position_median[0]),
        "position_offset_median_y_m": float(position_median[1]),
        "position_offset_median_z_m": float(position_median[2]),
        "position_offset_std_x_m": float(position_std[0]),
        "position_offset_std_y_m": float(position_std[1]),
        "position_offset_std_z_m": float(position_std[2]),
        "position_offset_median_norm_m": float(np.linalg.norm(position_median)),
        "position_residual_after_median_p50_m": finite_percentile(residual_norm, 50),
        "position_residual_after_median_p95_m": finite_percentile(residual_norm, 95),
        "position_residual_after_median_rmse_m": rms(residual_norm),
        "rotation_offset_mean_euler_x_deg": float(euler_mean[0]),
        "rotation_offset_mean_euler_y_deg": float(euler_mean[1]),
        "rotation_offset_mean_euler_z_deg": float(euler_mean[2]),
        "rotation_offset_median_euler_x_deg": float(euler_median[0]),
        "rotation_offset_median_euler_y_deg": float(euler_median[1]),
        "rotation_offset_median_euler_z_deg": float(euler_median[2]),
        "rotation_offset_std_euler_x_deg": float(euler_std[0]),
        "rotation_offset_std_euler_y_deg": float(euler_std[1]),
        "rotation_offset_std_euler_z_deg": float(euler_std[2]),
        "rotation_offset_median_deg": finite_percentile(rotation_error, 50),
        "rotation_offset_p95_deg": finite_percentile(rotation_error, 95),
    }


def _iqr(values: np.ndarray) -> float:
    """返回有限值的四分位距。"""

    return finite_percentile(values, 75) - finite_percentile(values, 25)


def _unwrap_angle_deg(values: np.ndarray) -> np.ndarray:
    """把角度序列展开到连续区间，避免 359/1 边界影响汇总。"""

    angles = np.asarray(values, dtype=float)
    unwrapped = angles.copy()
    finite = np.isfinite(angles)
    if finite.any():
        unwrapped[finite] = np.rad2deg(np.unwrap(np.deg2rad(angles[finite])))
    return unwrapped


def _empty_detail() -> pd.DataFrame:
    """返回包含固定字段的空显示误差表。"""

    return pd.DataFrame(columns=DETAIL_COLUMNS)


def _empty_summary() -> pd.DataFrame:
    """返回包含固定字段的空显示误差汇总表。"""

    return pd.DataFrame(columns=SUMMARY_COLUMNS)


__all__ = ["compute_anchor_error", "summarize_anchor_error", "summarize_pose_offset"]
