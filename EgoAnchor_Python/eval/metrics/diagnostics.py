"""可靠性与渲染质量轻量分布诊断。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .stats import finite_percentile


@dataclass(frozen=True)
class ReliabilityDiagnosticsResult:
    """可靠性诊断输出表集合。"""

    summary: pd.DataFrame
    """单行汇总，包括 score 展开程度、重投影有效帧数和渲染质量耗时。"""

    score_histogram: pd.DataFrame
    """`pose_score` 的 0..1 直方图。"""

    track_reprojection_histogram: pd.DataFrame
    """有效 `track_reprojection` 的 0..1 直方图。"""

    policy_distribution: pd.DataFrame
    """Unity policy action/reason 分布计数。"""


def compute_reliability_diagnostics(
    pose: pd.DataFrame,
    output: pd.DataFrame | None = None,
    anchor_error_detail: pd.DataFrame | None = None,
    *,
    spike_threshold_m: float = 0.05,
) -> ReliabilityDiagnosticsResult:
    """计算不依赖 GT 标定的 reliability 轻量诊断。

    该函数只消费离线 DataFrame，不导入 runtime 或模型。它回答两个问题：
    score 是否仍坍缩、渲染质量检测开销是否可接受，以及 Unity policy 是否真的在
    产生 reject/hold/coast 等动作。
    """

    pose_frame = pose.copy() if pose is not None else pd.DataFrame()
    scores = _numeric_series(pose_frame, "pose_score")
    track_reprojection = _numeric_series(pose_frame, "track_reprojection")
    valid_track_reprojection = track_reprojection[track_reprojection >= 0.0]
    render_quality_ms = _numeric_series(pose_frame, "render_quality_ms")
    if not valid_track_reprojection.empty and not render_quality_ms.empty:
        render_quality_ms = render_quality_ms.loc[valid_track_reprojection.index]
    else:
        render_quality_ms = pd.Series(dtype=float)

    summary = pd.DataFrame.from_records(
        [
            {
                "pose_rows": int(len(pose_frame)),
                "score_unique_count": int(scores.nunique(dropna=True)) if not scores.empty else 0,
                "score_mode": _mode_value(scores),
                "score_mode_share": _mode_share(scores),
                "score_min": _nan_stat(scores, np.nanmin),
                "score_p50": _nan_stat(scores, np.nanmedian),
                "score_p95": finite_percentile(scores, 95),
                "track_reprojection_valid_count": int(len(valid_track_reprojection)),
                "track_reprojection_min": _nan_stat(valid_track_reprojection, np.nanmin),
                "track_reprojection_p50": _nan_stat(valid_track_reprojection, np.nanmedian),
                "track_reprojection_p95": finite_percentile(valid_track_reprojection, 95),
                "render_quality_ms_p50": _nan_stat(render_quality_ms, np.nanmedian),
                "render_quality_ms_p95": finite_percentile(render_quality_ms, 95),
                **_spike_summary(anchor_error_detail, spike_threshold_m=spike_threshold_m),
            }
        ]
    )

    return ReliabilityDiagnosticsResult(
        summary=summary,
        score_histogram=_histogram(scores, value_name="pose_score"),
        track_reprojection_histogram=_histogram(valid_track_reprojection, value_name="track_reprojection"),
        policy_distribution=_policy_distribution(output),
    )


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    """读取数值列；缺列时返回空 Series。"""

    if frame is None or column not in frame:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _histogram(values: pd.Series, *, value_name: str, bins: int = 10) -> pd.DataFrame:
    """生成 0..1 直方图表。"""

    columns = ["value", "bin_left", "bin_right", "count"]
    if values.empty:
        return pd.DataFrame(columns=columns)
    clipped = np.clip(values.to_numpy(dtype=float), 0.0, 1.0)
    counts, edges = np.histogram(clipped, bins=bins, range=(0.0, 1.0))
    rows = [
        {
            "value": value_name,
            "bin_left": float(edges[index]),
            "bin_right": float(edges[index + 1]),
            "count": int(count),
        }
        for index, count in enumerate(counts)
    ]
    return pd.DataFrame.from_records(rows, columns=columns)


def _policy_distribution(output: pd.DataFrame | None) -> pd.DataFrame:
    """按 label/action/reason 统计 Unity policy 分布。"""

    columns = ["label", "policy_action", "policy_reason", "count"]
    if output is None or output.empty or "policy_action" not in output or "policy_reason" not in output:
        return pd.DataFrame(columns=columns)
    frame = output.copy()
    if "label" not in frame:
        frame["label"] = "unknown"
    grouped = frame.groupby(["label", "policy_action", "policy_reason"], dropna=False, sort=True).size().reset_index(name="count")
    return grouped[columns]


def _spike_summary(anchor_error_detail: pd.DataFrame | None, *, spike_threshold_m: float) -> dict[str, Any]:
    """用已有 anchor error 明细估计尖峰是否被 policy 拒绝或 hold。"""

    if anchor_error_detail is None or anchor_error_detail.empty or "translation_error_m" not in anchor_error_detail:
        return {"spike_threshold_m": float(spike_threshold_m), "spike_count": 0, "spike_missed_count": 0, "spike_missed_rate": np.nan}
    errors = pd.to_numeric(anchor_error_detail["translation_error_m"], errors="coerce")
    spike_mask = errors > float(spike_threshold_m)
    spike_count = int(spike_mask.sum())
    if spike_count <= 0 or "policy_action" not in anchor_error_detail:
        return {"spike_threshold_m": float(spike_threshold_m), "spike_count": spike_count, "spike_missed_count": 0, "spike_missed_rate": 0.0 if spike_count == 0 else np.nan}
    actions = anchor_error_detail.loc[spike_mask, "policy_action"].astype(str).str.lower()
    caught = actions.str.contains("reject|hold", regex=True, na=False)
    missed = int((~caught).sum())
    return {
        "spike_threshold_m": float(spike_threshold_m),
        "spike_count": spike_count,
        "spike_missed_count": missed,
        "spike_missed_rate": float(missed / spike_count),
    }


def _mode_value(values: pd.Series) -> float:
    """返回众数；空输入返回 NaN。"""

    if values.empty:
        return float("nan")
    modes = values.mode(dropna=True)
    return float(modes.iloc[0]) if not modes.empty else float("nan")


def _mode_share(values: pd.Series) -> float:
    """返回众数占比；用于识别 score 是否坍缩。"""

    if values.empty:
        return float("nan")
    counts = values.value_counts(dropna=True)
    return float(counts.iloc[0] / len(values)) if not counts.empty else float("nan")


def _nan_stat(values: pd.Series, fn: Any) -> float:
    """对非空 Series 计算统计量；空输入返回 NaN。"""

    if values.empty:
        return float("nan")
    return float(fn(values.to_numpy(dtype=float)))


__all__ = ["ReliabilityDiagnosticsResult", "compute_reliability_diagnostics"]
