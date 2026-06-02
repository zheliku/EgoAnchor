"""Anchor Transform 与 Transform GT 的直接误差指标。"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .common import pose_error, quat_to_euler_deg, relative_rotation_quat, wrap_angle_360_deg


DETAIL_COLUMNS = [
    "tick_index",
    "render_mono_ms",
    "label",
    "condition",
    "source_frame_id",
    "position_offset_x_m",
    "position_offset_y_m",
    "position_offset_z_m",
    "rotation_offset_euler_x_deg",
    "rotation_offset_euler_y_deg",
    "rotation_offset_euler_z_deg",
    "translation_error_m",
    "rotation_error_deg",
    "anchor_state",
    "policy_action",
    "policy_reason",
]
"""逐行误差表字段。"""

SUMMARY_COLUMNS = [
    "condition",
    "label",
    "n",
    "translation_rmse_m",
    "translation_median_m",
    "translation_p95_m",
    "rotation_rmse_deg",
    "rotation_median_deg",
    "rotation_p95_deg",
]
"""误差汇总表字段。"""

OFFSET_SUMMARY_COLUMNS = [
    "condition",
    "label",
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
"""固定偏移诊断汇总表字段。"""


def compute_anchor_error(output: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """计算各 output variant 的世界系 anchor error。"""

    detail_records: list[dict[str, Any]] = []
    if output.empty:
        return _empty_detail(), _empty_summary()

    mask = (
        output["valid"].fillna(False).astype(bool)
        & output["has_stable"].fillna(False).astype(bool)
        & output["gt_pos"].map(_is_pose_value)
        & output["gt_rot"].map(_is_pose_value)
        & output["stable_pos"].map(_is_pose_value)
        & output["stable_rot"].map(_is_pose_value)
    )
    for _, row in output.loc[mask].iterrows():
        translation_m, rotation_deg = pose_error(row["gt_pos"], row["gt_rot"], row["stable_pos"], row["stable_rot"])
        position_offset = np.asarray(row["stable_pos"], dtype=float) - np.asarray(row["gt_pos"], dtype=float)
        rotation_offset = relative_rotation_quat(row["gt_rot"], row["stable_rot"])
        rotation_euler = quat_to_euler_deg(rotation_offset)
        detail_records.append(
            {
                "tick_index": int(row.get("tick_index", -1)),
                "render_mono_ms": float(row["render_mono_ms"]),
                "label": str(row["label"]),
                "condition": str(row.get("condition", "unlabeled")),
                "source_frame_id": int(row.get("source_frame_id", row.get("render_source_frame_id", -1))),
                "position_offset_x_m": float(position_offset[0]),
                "position_offset_y_m": float(position_offset[1]),
                "position_offset_z_m": float(position_offset[2]),
                "rotation_offset_euler_x_deg": float(rotation_euler[0]),
                "rotation_offset_euler_y_deg": float(rotation_euler[1]),
                "rotation_offset_euler_z_deg": float(rotation_euler[2]),
                "translation_error_m": translation_m,
                "rotation_error_deg": rotation_deg,
                "anchor_state": str(row.get("anchor_state", "")),
                "policy_action": str(row.get("policy_action", "")),
                "policy_reason": str(row.get("policy_reason", "")),
            }
        )

    detail = pd.DataFrame.from_records(detail_records, columns=DETAIL_COLUMNS)
    return detail, summarize_anchor_error(detail)


def summarize_anchor_error(detail: pd.DataFrame) -> pd.DataFrame:
    """按 condition × label 汇总 anchor error。"""

    if detail.empty:
        return _empty_summary()
    rows: list[dict[str, Any]] = []
    for (condition, label), group in detail.groupby(["condition", "label"], sort=True):
        t = group["translation_error_m"].to_numpy(dtype=float)
        r = group["rotation_error_deg"].to_numpy(dtype=float)
        rows.append(
            {
                "condition": condition,
                "label": label,
                "n": int(len(group)),
                "translation_rmse_m": _rmse(t),
                "translation_median_m": float(np.nanmedian(t)),
                "translation_p95_m": float(np.nanpercentile(t, 95)),
                "rotation_rmse_deg": _rmse(r),
                "rotation_median_deg": float(np.nanmedian(r)),
                "rotation_p95_deg": float(np.nanpercentile(r, 95)),
            }
        )
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def summarize_pose_offset(detail: pd.DataFrame) -> pd.DataFrame:
    """按 condition × label 汇总 signed position offset 和相对旋转 offset。"""

    if detail.empty:
        return pd.DataFrame(columns=OFFSET_SUMMARY_COLUMNS)
    rows: list[dict[str, Any]] = []
    for (condition, label), group in detail.groupby(["condition", "label"], sort=True):
        position = group[["position_offset_x_m", "position_offset_y_m", "position_offset_z_m"]].to_numpy(dtype=float)
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
        rotation_euler_unwrapped = np.column_stack(
            [_unwrap_angle_deg(rotation_euler[:, axis]) for axis in range(rotation_euler.shape[1])]
        )
        euler_mean = np.asarray([wrap_angle_360_deg(value) for value in np.nanmean(rotation_euler_unwrapped, axis=0)])
        euler_median = np.asarray([wrap_angle_360_deg(value) for value in np.nanmedian(rotation_euler_unwrapped, axis=0)])
        euler_std = np.nanstd(rotation_euler_unwrapped, axis=0)
        residual = position - position_median
        residual_norm = np.linalg.norm(residual, axis=1)
        rows.append(
            {
                "condition": condition,
                "label": label,
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
                "position_residual_after_median_p50_m": float(np.nanmedian(residual_norm)),
                "position_residual_after_median_p95_m": float(np.nanpercentile(residual_norm, 95)),
                "position_residual_after_median_rmse_m": _rmse(residual_norm),
                "rotation_offset_mean_euler_x_deg": float(euler_mean[0]),
                "rotation_offset_mean_euler_y_deg": float(euler_mean[1]),
                "rotation_offset_mean_euler_z_deg": float(euler_mean[2]),
                "rotation_offset_median_euler_x_deg": float(euler_median[0]),
                "rotation_offset_median_euler_y_deg": float(euler_median[1]),
                "rotation_offset_median_euler_z_deg": float(euler_median[2]),
                "rotation_offset_std_euler_x_deg": float(euler_std[0]),
                "rotation_offset_std_euler_y_deg": float(euler_std[1]),
                "rotation_offset_std_euler_z_deg": float(euler_std[2]),
                "rotation_offset_median_deg": float(np.nanmedian(group["rotation_error_deg"].to_numpy(dtype=float))),
                "rotation_offset_p95_deg": float(np.nanpercentile(group["rotation_error_deg"].to_numpy(dtype=float), 95)),
            }
        )
    return pd.DataFrame.from_records(rows, columns=OFFSET_SUMMARY_COLUMNS)


def _is_pose_value(value: object) -> bool:
    """判断 object 列中是否有可用 pose 数组。"""

    return value is not None and not (isinstance(value, float) and math.isnan(value))


def _rmse(values: np.ndarray) -> float:
    """计算 RMSE，忽略 NaN。"""

    if values.size == 0:
        return float("nan")
    return float(np.sqrt(np.nanmean(values * values)))


def _unwrap_angle_deg(values: np.ndarray) -> np.ndarray:
    """把角度序列展开到连续区间，避免 359/1 边界影响汇总。"""

    angles = np.asarray(values, dtype=float)
    unwrapped = angles.copy()
    finite = np.isfinite(angles)
    if not finite.any():
        return unwrapped
    unwrapped[finite] = np.rad2deg(np.unwrap(np.deg2rad(angles[finite])))
    return unwrapped


def _empty_detail() -> pd.DataFrame:
    """返回空逐行误差表。"""

    return pd.DataFrame(columns=DETAIL_COLUMNS)


def _empty_summary() -> pd.DataFrame:
    """返回空误差汇总表。"""

    return pd.DataFrame(columns=SUMMARY_COLUMNS)


__all__ = ["compute_anchor_error", "summarize_anchor_error", "summarize_pose_offset"]
