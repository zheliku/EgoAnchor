"""RQ1 手动场景提取。

从 unity_output JSONL 的 ``rq1_metric`` 字段提取用户在 Unity 侧手动按键标注的
场景片段，替代原有的速度阈值自动分类方案（``auto_scenario_detection.py``）。

用法示例::

    from egoanchor.eval.core.manual_scenario_extraction import (
        extract_manual_segments,
        summarize_manual_segments,
        print_segment_summary,
    )

    segments = extract_manual_segments(primary_df)
    print_segment_summary(segments)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import pandas as pd


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ManualSegment:
    """一段连续的手动标注片段。

    Attributes:
        metric:         指标名称，与 Unity 侧 ``RQ1MetricType.ToLogString()`` 一致，
                        例如 ``"static_observation"``、``"fast_motion"``。
        start_mono_ms:  片段首帧的 ``render_mono_ms``（毫秒）。
        end_mono_ms:    片段末帧的 ``render_mono_ms``（毫秒）。
        duration:       片段持续时长（秒）。
        frame_count:    片段内的帧数。
    """

    metric: str
    start_mono_ms: float
    end_mono_ms: float
    duration: float
    frame_count: int


# 已知的合法指标名，与 RQ1MetricTypeExtensions.ToLogString() 保持一致
KNOWN_METRICS: frozenset[str] = frozenset(
    {
        "static_observation",
        "slow_translation",
        "fast_motion",
        "rotation",
        "occlusion_recovery",
    }
)

# 各指标建议显示名（中文）
METRIC_DISPLAY: dict[str, str] = {
    "static_observation":  "长时静止",
    "slow_translation":    "慢速平移",
    "fast_motion":         "快速挥动",
    "rotation":            "旋转运动",
    "occlusion_recovery":  "遮挡恢复",
}


# ── 核心函数 ──────────────────────────────────────────────────────────────────

def extract_manual_segments(df: pd.DataFrame) -> list[ManualSegment]:
    """从 output 数据帧中提取连续的手动标注片段。

    Args:
        df: 包含 ``rq1_metric`` 和 ``render_mono_ms`` 列的 DataFrame（primary 变体行，
            已按时间排序或未排序均可）。

    Returns:
        ``ManualSegment`` 列表，按时间顺序排列，已排除 ``"none"`` 和空值片段。
        若 DataFrame 不含 ``rq1_metric`` 列，返回空列表。
    """
    if df.empty or "rq1_metric" not in df.columns:
        return []

    work = df.sort_values("render_mono_ms").copy()
    metric_col = work["rq1_metric"].fillna("none").astype(str)

    # 用 cumsum 找到连续相同 metric 的 run（值变化时 run_id 加 1）
    run_id = (metric_col != metric_col.shift()).cumsum()
    work["_run_id"] = run_id

    segments: list[ManualSegment] = []
    for _, group in work.groupby("_run_id", sort=False):
        metric = str(group["rq1_metric"].iloc[0])
        if metric in ("none", "None", "", "nan"):
            continue

        start_ms = float(group["render_mono_ms"].iloc[0])
        end_ms   = float(group["render_mono_ms"].iloc[-1])
        duration = max((end_ms - start_ms) / 1000.0, 0.0)

        segments.append(
            ManualSegment(
                metric=metric,
                start_mono_ms=start_ms,
                end_mono_ms=end_ms,
                duration=duration,
                frame_count=len(group),
            )
        )

    return segments


def summarize_manual_segments(segments: list[ManualSegment]) -> pd.DataFrame:
    """将片段列表汇总为 DataFrame（每种指标一行）。

    列：``metric``、``n_segments``、``total_duration_s``、``total_frames``。
    """
    if not segments:
        return pd.DataFrame(
            columns=["metric", "n_segments", "total_duration_s", "total_frames"]
        )

    metrics = sorted({s.metric for s in segments})
    rows = []
    for metric in metrics:
        segs = [s for s in segments if s.metric == metric]
        rows.append(
            {
                "metric":           metric,
                "n_segments":       len(segs),
                "total_duration_s": round(sum(s.duration for s in segs), 3),
                "total_frames":     sum(s.frame_count for s in segs),
            }
        )
    return pd.DataFrame(rows)


def print_segment_summary(segments: list[ManualSegment]) -> None:
    """在终端打印可读的片段摘要。"""
    if not segments:
        print("  （无手动标注片段）")
        return

    cnt = Counter(s.metric for s in segments)
    print(f"  手动标注片段共 {len(segments)} 段，涉及 {len(cnt)} 种指标：")
    for metric in sorted(cnt):
        segs  = [s for s in segments if s.metric == metric]
        total = sum(s.duration for s in segs)
        name  = METRIC_DISPLAY.get(metric, metric)
        print(f"    {metric:<22}  {name}  × {cnt[metric]}段  共 {total:.1f}s")
