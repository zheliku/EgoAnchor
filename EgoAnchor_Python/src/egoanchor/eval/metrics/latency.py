"""端到端 latency 与 Python 分模块耗时指标。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .stats import finite_percentile


DETAIL_COLUMNS = [
    "label",
    "condition",
    "frame_id",
    "render_mono_ms",
    "source_capture_mono_ms",
    "capture_to_apply_ms",
    "image_to_handle_ms",
    "observation_age_ms",
    "effective_policy_delay_ms",
    "smoothing_delay_ms",
    "perception_total_ms",
    "yolo_ms",
    "depth_ms",
    "cutie_ms",
    "pose_ms",
]
"""逐 frame latency 表字段。"""

SUMMARY_COLUMNS = [
    "condition",
    "label",
    "n",
    "capture_to_apply_p50_ms",
    "capture_to_apply_p90_ms",
    "capture_to_apply_p95_ms",
    "image_to_handle_p50_ms",
    "observation_age_p50_ms",
    "effective_policy_delay_p50_ms",
    "smoothing_delay_p50_ms",
    "perception_total_p50_ms",
    "yolo_p50_ms",
    "depth_p50_ms",
    "cutie_p50_ms",
    "pose_p50_ms",
]
"""latency 汇总字段。"""


def compute_latency(output: pd.DataFrame, pose: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """计算每个 source frame 首次出现在输出中的端到端延迟。"""

    if output.empty:
        return _empty_detail(), _empty_summary()
    mask = (
        output["has_source_capture_timing"].fillna(False).astype(bool)
        & output["has_output_pose"].fillna(False).astype(bool)
        & output["source_capture_mono_ms"].notna()
        & output["source_frame_id"].notna()
    )
    candidates = output.loc[mask].copy()
    if candidates.empty:
        return _empty_detail(), _empty_summary()

    candidates["frame_id"] = candidates["source_frame_id"].astype(int)
    candidates = candidates[candidates["frame_id"] >= 0]
    candidates = candidates.sort_values(["label", "frame_id", "render_mono_ms"])
    first_apply = candidates.drop_duplicates(["label", "frame_id"], keep="first")

    pose_cols = [
        "frame_id",
        "total_ms",
        "yolo_ms",
        "depth_ms",
        "cutie_ms",
        "pose_ms",
        "server_publish_mono_ms",
    ]
    pose_frame = pose.reset_index(drop=True)
    pose_frame = pose_frame[[col for col in pose_cols if col in pose_frame.columns]].copy()
    merged = first_apply.merge(pose_frame, on="frame_id", how="left", suffixes=("", "_pose"))

    records: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        capture_to_apply = float(row["render_mono_ms"]) - float(row["source_capture_mono_ms"])
        image_to_handle = _difference(
            row.get("unity_pose_handle_mono_ms"), row.get("source_capture_mono_ms")
        )
        effective_policy_delay = _difference(
            row.get("render_mono_ms"), row.get("policy_output_target_mono_ms")
        )
        records.append(
            {
                "label": str(row["label"]),
                "condition": str(row.get("condition", "unlabeled")),
                "frame_id": int(row["frame_id"]),
                "render_mono_ms": float(row["render_mono_ms"]),
                "source_capture_mono_ms": float(row["source_capture_mono_ms"]),
                "capture_to_apply_ms": capture_to_apply,
                "image_to_handle_ms": image_to_handle,
                "observation_age_ms": _float(row.get("observation_age_ms")),
                "effective_policy_delay_ms": effective_policy_delay,
                "smoothing_delay_ms": _float(row.get("smoothing_delay_ms")),
                "perception_total_ms": _float(row.get("total_ms")),
                "yolo_ms": _float(row.get("yolo_ms")),
                "depth_ms": _float(row.get("depth_ms")),
                "cutie_ms": _float(row.get("cutie_ms")),
                "pose_ms": _float(row.get("pose_ms")),
            }
        )
    detail = pd.DataFrame.from_records(records, columns=DETAIL_COLUMNS)
    return detail, summarize_latency(detail)


def summarize_latency(detail: pd.DataFrame) -> pd.DataFrame:
    """按 condition × label 汇总 latency。"""

    if detail.empty:
        return _empty_summary()
    rows: list[dict[str, Any]] = []
    for (condition, label), group in detail.groupby(["condition", "label"], sort=True):
        rows.append(
            {
                "condition": condition,
                "label": label,
                "n": int(len(group)),
                "capture_to_apply_p50_ms": finite_percentile(group["capture_to_apply_ms"], 50),
                "capture_to_apply_p90_ms": finite_percentile(group["capture_to_apply_ms"], 90),
                "capture_to_apply_p95_ms": finite_percentile(group["capture_to_apply_ms"], 95),
                "image_to_handle_p50_ms": finite_percentile(group["image_to_handle_ms"], 50),
                "observation_age_p50_ms": finite_percentile(group["observation_age_ms"], 50),
                "effective_policy_delay_p50_ms": finite_percentile(
                    group["effective_policy_delay_ms"], 50
                ),
                "smoothing_delay_p50_ms": finite_percentile(group["smoothing_delay_ms"], 50),
                "perception_total_p50_ms": finite_percentile(group["perception_total_ms"], 50),
                "yolo_p50_ms": finite_percentile(group["yolo_ms"], 50),
                "depth_p50_ms": finite_percentile(group["depth_ms"], 50),
                "cutie_p50_ms": finite_percentile(group["cutie_ms"], 50),
                "pose_p50_ms": finite_percentile(group["pose_ms"], 50),
            }
        )
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def _float(value: object) -> float:
    """宽容读取 float。"""

    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _difference(later: object, earlier: object) -> float:
    """计算两个日志时刻之差；任一不可得时返回 NaN。"""

    later_value = _float(later)
    earlier_value = _float(earlier)
    if not np.isfinite(later_value) or not np.isfinite(earlier_value):
        return np.nan
    return float(later_value - earlier_value)


def _empty_detail() -> pd.DataFrame:
    """返回空逐 frame latency 表。"""

    return pd.DataFrame(columns=DETAIL_COLUMNS)


def _empty_summary() -> pd.DataFrame:
    """返回空 latency 汇总表。"""

    return pd.DataFrame(columns=SUMMARY_COLUMNS)


__all__ = ["compute_latency", "summarize_latency"]
