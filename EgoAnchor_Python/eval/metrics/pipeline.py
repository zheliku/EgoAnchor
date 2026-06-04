"""组合所有离线评估指标。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from eval.io import SessionLogs, label_conditions

from .anchor_error import compute_anchor_error, summarize_pose_offset
from .common import pose_error
from .diagnostics import compute_reliability_diagnostics
from .jitter import compute_jitter
from .jump_suppression import compute_jump_suppression
from .lag import compute_lag
from .latency import compute_latency
from .recovery import compute_recovery
from .slip import compute_slip


@dataclass(frozen=True)
class MetricsResult:
    """一次 session 的全部离线评估结果。"""

    tables: dict[str, pd.DataFrame]
    """表名到 DataFrame 的映射。"""

    sanity: dict[str, Any]
    """GT/anchor 语义一致性诊断。"""


def compute_all_metrics(logs: SessionLogs) -> MetricsResult:
    """对一个已加载 session 计算所有可用指标。"""

    output = label_conditions(logs.output, logs.manifest, "render_mono_ms")
    anchor_detail, anchor_summary = compute_anchor_error(output)
    latency_detail, latency_summary = compute_latency(output, logs.pose)
    slip_detail, slip_summary = compute_slip(output)
    reliability = compute_reliability_diagnostics(logs.pose, output, anchor_detail)
    tables = {
        "anchor_error_detail": anchor_detail,
        "anchor_error_summary": anchor_summary,
        "pose_offset_summary": summarize_pose_offset(anchor_detail),
        "latency_detail": latency_detail,
        "latency_summary": latency_summary,
        "jitter_summary": compute_jitter(output),
        "slip_detail": slip_detail,
        "slip_summary": slip_summary,
        "lag_summary": compute_lag(output),
        "jump_suppression_summary": compute_jump_suppression(anchor_detail),
        "recovery_summary": compute_recovery(anchor_detail, logs.manifest),
        "reliability_diagnostics_summary": reliability.summary,
        "reliability_score_histogram": reliability.score_histogram,
        "track_consistency_histogram": reliability.consistency_histogram,
        "policy_distribution": reliability.policy_distribution,
    }
    return MetricsResult(tables=tables, sanity=build_sanity(logs, output))


def build_sanity(logs: SessionLogs, output: pd.DataFrame) -> dict[str, Any]:
    """生成 GT Transform 与各 variant 输出的语义一致性诊断。"""

    manifest = logs.manifest
    sanity: dict[str, Any] = {
        "session_id": str(manifest.get("session_id", "")),
        "object_id": str(manifest.get("object_id", "")),
        "gt_source": str(manifest.get("gt_source", "")),
        "gt_transform": str(manifest.get("gt_transform", "")),
        "variant_labels": list(manifest.get("variant_labels", [])),
        "capture_rows": int(len(logs.capture)),
        "output_rows": int(len(output)),
        "pose_rows": int(len(logs.pose)),
        "gt_valid_output_rows": int(output["valid"].fillna(False).astype(bool).sum()) if "valid" in output else 0,
        "variants": {},
    }
    for label, group in output.groupby("label", sort=True):
        stable_mask = group["has_stable"].fillna(False).astype(bool)
        source_counts = group["anchor_pose_source"].astype(str).value_counts().to_dict()
        sanity["variants"][str(label)] = {
            "rows": int(len(group)),
            "stable_rows": int(stable_mask.sum()),
            "anchor_pose_source_counts": {str(key): int(value) for key, value in source_counts.items()},
        }

    aligned_raw = output[
        output["is_primary"].fillna(False).astype(bool)
        & output["has_aligned_raw"].fillna(False).astype(bool)
        & output["gt_pos"].map(lambda value: value is not None)
        & output["gt_rot"].map(lambda value: value is not None)
        & output["aligned_raw_pos"].map(lambda value: value is not None)
        & output["aligned_raw_rot"].map(lambda value: value is not None)
    ]
    sanity["aligned_raw_error"] = _aligned_raw_error_summary(aligned_raw)
    return sanity


def _aligned_raw_error_summary(rows: pd.DataFrame) -> dict[str, Any]:
    """汇总主变体 aligned raw 与 GT 的直接误差。"""

    if rows.empty:
        return {"n": 0, "translation_median_m": np.nan, "translation_p95_m": np.nan, "rotation_median_deg": np.nan}
    translations = []
    rotations = []
    for _, row in rows.iterrows():
        t, r = pose_error(row["gt_pos"], row["gt_rot"], row["aligned_raw_pos"], row["aligned_raw_rot"])
        translations.append(t)
        rotations.append(r)
    t_arr = np.asarray(translations, dtype=float)
    r_arr = np.asarray(rotations, dtype=float)
    return {
        "n": int(len(rows)),
        "translation_median_m": float(np.nanmedian(t_arr)),
        "translation_p95_m": float(np.nanpercentile(t_arr, 95)),
        "rotation_median_deg": float(np.nanmedian(r_arr)),
    }


__all__ = ["MetricsResult", "build_sanity", "compute_all_metrics"]
