"""屏幕空间 slip 指标。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .common import is_pose_value, pos_quat_to_mat, project_point
from .stats import rms


DETAIL_COLUMNS = ["render_mono_ms", "condition", "label", "source_frame_id", "slip_px"]
SUMMARY_COLUMNS = ["condition", "label", "n", "slip_rms_px", "slip_peak_px", "insufficient_data"]


def compute_slip(output: pd.DataFrame, k: np.ndarray | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """计算 GT 原点与 anchor 原点投影后的像面距离。"""

    if output.empty:
        return _empty_detail(), _empty_summary()
    intrinsic = k if k is not None else default_intrinsics()
    records: list[dict[str, Any]] = []
    mask = (
        output["valid"].fillna(False).astype(bool)
        & output["has_stable"].fillna(False).astype(bool)
        & output["gt_pos"].map(is_pose_value)
        & output["stable_pos"].map(is_pose_value)
    )
    for _, row in output.loc[mask].iterrows():
        w_t_head = pos_quat_to_mat(row["head_pos"], row["head_rot"])
        gt_uv = project_point(intrinsic, w_t_head, row["gt_pos"])
        stable_uv = project_point(intrinsic, w_t_head, row["stable_pos"])
        slip_px = float(np.linalg.norm(stable_uv - gt_uv))
        records.append(
            {
                "render_mono_ms": float(row["render_mono_ms"]),
                "condition": str(row.get("condition", "unlabeled")),
                "label": str(row["label"]),
                "source_frame_id": int(row.get("source_frame_id", -1)),
                "slip_px": slip_px,
            }
        )
    detail = pd.DataFrame.from_records(records, columns=DETAIL_COLUMNS)
    return detail, summarize_slip(detail)


def summarize_slip(detail: pd.DataFrame) -> pd.DataFrame:
    """按 condition × label 汇总 slip。"""

    if detail.empty:
        return _empty_summary()
    rows: list[dict[str, Any]] = []
    for (condition, label), group in detail.groupby(["condition", "label"], sort=True):
        slip = group["slip_px"].to_numpy(dtype=float)
        slip = slip[np.isfinite(slip)]
        if slip.size == 0:
            rows.append(_insufficient(condition, label, 0))
            continue
        rows.append(
            {
                "condition": condition,
                "label": label,
                "n": int(slip.size),
                "slip_rms_px": rms(slip),
                "slip_peak_px": float(np.max(slip)),
                "insufficient_data": False,
            }
        )
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def default_intrinsics(width: float = 640.0, height: float = 480.0, fov_deg: float = 90.0) -> np.ndarray:
    """构造缺省近似 K；用于没有 camera_info 的 smoke 数据。"""

    fx = (width * 0.5) / np.tan(np.deg2rad(fov_deg) * 0.5)
    fy = (height * 0.5) / np.tan(np.deg2rad(fov_deg) * 0.5)
    return np.array([[fx, 0.0, width * 0.5], [0.0, fy, height * 0.5], [0.0, 0.0, 1.0]], dtype=float)


def _insufficient(condition: str, label: str, count: int) -> dict[str, Any]:
    """构造数据不足行。"""

    return {
        "condition": condition,
        "label": label,
        "n": int(count),
        "slip_rms_px": np.nan,
        "slip_peak_px": np.nan,
        "insufficient_data": True,
    }


def _empty_detail() -> pd.DataFrame:
    """返回空 slip 明细表。"""

    return pd.DataFrame(columns=DETAIL_COLUMNS)


def _empty_summary() -> pd.DataFrame:
    """返回空 slip 汇总表。"""

    return pd.DataFrame(columns=SUMMARY_COLUMNS)


__all__ = ["compute_slip", "default_intrinsics", "summarize_slip"]
