"""端到端 latency 与 Python 分模块耗时指标。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


DETAIL_COLUMNS = [
    "label",
    "condition",
    "frame_id",
    "render_mono_ms",
    "source_capture_mono_ms",
    "capture_to_apply_ms",
    "perception_total_ms",
    "yolo_ms",
    "depth_ms",
    "cutie_ms",
    "pose_ms",
    "publish_to_apply_est_ms",
]
"""逐 frame latency 表字段。"""

SUMMARY_COLUMNS = [
    "condition",
    "label",
    "n",
    "capture_to_apply_p50_ms",
    "capture_to_apply_p90_ms",
    "capture_to_apply_p95_ms",
    "perception_total_p50_ms",
    "yolo_p50_ms",
    "depth_p50_ms",
    "cutie_p50_ms",
    "pose_p50_ms",
    "publish_to_apply_est_p50_ms",
]
"""latency 汇总字段。"""


def compute_latency(output: pd.DataFrame, pose: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """计算每个 source frame 首次出现在输出中的端到端延迟。"""

    if output.empty:
        return _empty_detail(), _empty_summary()
    mask = (
        output["has_source_capture_timing"].fillna(False).astype(bool)
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
        total_ms = _float(row.get("total_ms"))
        records.append(
            {
                "label": str(row["label"]),
                "condition": str(row.get("condition", "unlabeled")),
                "frame_id": int(row["frame_id"]),
                "render_mono_ms": float(row["render_mono_ms"]),
                "source_capture_mono_ms": float(row["source_capture_mono_ms"]),
                "capture_to_apply_ms": capture_to_apply,
                "perception_total_ms": total_ms,
                "yolo_ms": _float(row.get("yolo_ms")),
                "depth_ms": _float(row.get("depth_ms")),
                "cutie_ms": _float(row.get("cutie_ms")),
                "pose_ms": _float(row.get("pose_ms")),
                "publish_to_apply_est_ms": max(0.0, capture_to_apply - total_ms) if np.isfinite(total_ms) else np.nan,
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
                "capture_to_apply_p50_ms": _percentile(group["capture_to_apply_ms"], 50),
                "capture_to_apply_p90_ms": _percentile(group["capture_to_apply_ms"], 90),
                "capture_to_apply_p95_ms": _percentile(group["capture_to_apply_ms"], 95),
                "perception_total_p50_ms": _percentile(group["perception_total_ms"], 50),
                "yolo_p50_ms": _percentile(group["yolo_ms"], 50),
                "depth_p50_ms": _percentile(group["depth_ms"], 50),
                "cutie_p50_ms": _percentile(group["cutie_ms"], 50),
                "pose_p50_ms": _percentile(group["pose_ms"], 50),
                "publish_to_apply_est_p50_ms": _percentile(group["publish_to_apply_est_ms"], 50),
            }
        )
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def _float(value: object) -> float:
    """宽容读取 float。"""

    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _percentile(series: pd.Series, percentile: float) -> float:
    """忽略 NaN 的百分位。"""

    values = series.to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return np.nan
    return float(np.percentile(values, percentile))


def _empty_detail() -> pd.DataFrame:
    """返回空逐 frame latency 表。"""

    return pd.DataFrame(columns=DETAIL_COLUMNS)


def _empty_summary() -> pd.DataFrame:
    """返回空 latency 汇总表。"""

    return pd.DataFrame(columns=SUMMARY_COLUMNS)


__all__ = ["compute_latency", "summarize_latency"]
