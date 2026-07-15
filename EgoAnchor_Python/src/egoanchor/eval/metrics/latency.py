"""schema-v2 的候选处理、运行时时效性与频率诊断。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .common import METRIC_GROUP_COLUMNS, iter_metric_groups, require_columns
from .stats import finite_percentile


CANDIDATE_DETAIL_COLUMNS = [
    *METRIC_GROUP_COLUMNS,
    "candidate_id",
    "frame_id",
    "reference_capture_mono_ms",
    "source_capture_mono_ms",
    "server_receive_mono_ms",
    "server_publish_mono_ms",
    "unity_pose_handle_mono_ms",
    "candidate_arrival_ms",
    "candidate_processing_ms",
    "total_ms",
    "yolo_ms",
    "depth_ms",
    "cutie_ms",
    "pose_ms",
]
"""逐 candidate×variant 的处理时延字段。"""

RENDER_DETAIL_COLUMNS = [
    *METRIC_GROUP_COLUMNS,
    "render_tick_id",
    "render_mono_ms",
    "source_frame_id",
    "has_output_pose",
    "has_display_pose",
    "observation_age_ms",
    "smoothing_delay_ms",
]
"""逐 render tick×variant 的运行时时效性字段。"""

SUMMARY_COLUMNS = [
    *METRIC_GROUP_COLUMNS,
    "candidate_count",
    "render_tick_count",
    "candidate_arrival_p50_ms",
    "candidate_arrival_p95_ms",
    "candidate_processing_p50_ms",
    "candidate_processing_p95_ms",
    "observation_age_p50_ms",
    "observation_age_p95_ms",
    "smoothing_delay_p50_ms",
    "smoothing_delay_p95_ms",
    "visual_perception_hz",
    "render_hz",
]
"""每个 trial/event/variant 的时延与频率汇总字段。"""


@dataclass(frozen=True)
class LatencyMetricsResult:
    """一次 schema-v2 session 的时延诊断表集合。"""

    candidate_detail: pd.DataFrame
    """逐 candidate×variant 的跨端到达与 Python 处理时延。"""

    render_detail: pd.DataFrame
    """逐 tick×variant 的观测年龄和主动平滑延迟。"""

    summary: pd.DataFrame
    """按完整实验上下文和 variant 汇总的时延与频率。"""


def compute_latency(
    unity_render: pd.DataFrame,
    unity_reference: pd.DataFrame,
    python_candidates: pd.DataFrame,
    unity_admission: pd.DataFrame,
) -> LatencyMetricsResult:
    """连接 schema-v2 四张表并计算候选处理、输出时效性和系统频率。

    candidate 必须通过 ``candidate_id`` 连接 admission；同一 ``frame_id`` 的多个
    candidate 保持为多行，禁止用 frame 去重。视觉频率以每个上下文内 candidate 的
    Python 发布时间计算，render 频率以唯一 render tick 的时间计算。
    """

    _validate_inputs(unity_render, unity_reference, python_candidates, unity_admission)
    candidate_detail = _build_candidate_detail(
        unity_reference,
        python_candidates,
        unity_admission,
    )
    render_detail = _build_render_detail(unity_render)
    summary = _summarize_latency(candidate_detail, render_detail)
    return LatencyMetricsResult(
        candidate_detail=candidate_detail,
        render_detail=render_detail,
        summary=summary,
    )


def _validate_inputs(
    render: pd.DataFrame,
    reference: pd.DataFrame,
    candidates: pd.DataFrame,
    admission: pd.DataFrame,
) -> None:
    """校验连接和指标计算所需的最小字段集合。"""

    require_columns(
        render,
        {
            *METRIC_GROUP_COLUMNS,
            "render_tick_id",
            "render_mono_ms",
            "source_frame_id",
            "has_output_pose",
            "has_display_pose",
            "observation_age_ms",
            "smoothing_delay_ms",
        },
        table_name="unity_render",
    )
    require_columns(
        reference,
        {"session_id", "frame_id", "capture_mono_ms"},
        table_name="unity_reference",
    )
    require_columns(
        candidates,
        {
            "session_id",
            "candidate_id",
            "frame_id",
            "server_receive_mono_ms",
            "server_publish_mono_ms",
            "total_ms",
            "yolo_ms",
            "depth_ms",
            "cutie_ms",
            "pose_ms",
        },
        table_name="python_candidates",
    )
    require_columns(
        admission,
        {
            *METRIC_GROUP_COLUMNS,
            "candidate_id",
            "frame_id",
            "source_capture_mono_ms",
            "unity_pose_handle_mono_ms",
        },
        table_name="unity_admission",
    )

    _require_unique(reference, ["session_id", "frame_id"], "unity_reference")
    _require_unique(candidates, ["session_id", "candidate_id"], "python_candidates")
    _require_unique(
        admission,
        ["session_id", "candidate_id", "variant_id"],
        "unity_admission",
    )


def _build_candidate_detail(
    reference: pd.DataFrame,
    candidates: pd.DataFrame,
    admission: pd.DataFrame,
) -> pd.DataFrame:
    """构造逐 candidate×variant 明细，不折叠同帧多 candidate。"""

    if candidates.empty or admission.empty:
        return pd.DataFrame(columns=CANDIDATE_DETAIL_COLUMNS)

    candidate_columns = [
        "session_id",
        "candidate_id",
        "frame_id",
        "server_receive_mono_ms",
        "server_publish_mono_ms",
        "total_ms",
        "yolo_ms",
        "depth_ms",
        "cutie_ms",
        "pose_ms",
    ]
    admission_columns = [
        *METRIC_GROUP_COLUMNS,
        "candidate_id",
        "frame_id",
        "source_capture_mono_ms",
        "unity_pose_handle_mono_ms",
    ]
    merged = admission[admission_columns].merge(
        candidates[candidate_columns],
        on=["session_id", "candidate_id", "frame_id"],
        how="left",
        validate="many_to_one",
        indicator="_candidate_join",
    )
    _require_complete_join(merged, "_candidate_join", "unity_admission -> python_candidates")
    merged = merged.drop(columns="_candidate_join")
    merged = merged.merge(
        reference[["session_id", "frame_id", "capture_mono_ms"]].rename(
            columns={"capture_mono_ms": "reference_capture_mono_ms"}
        ),
        on=["session_id", "frame_id"],
        how="left",
        validate="many_to_one",
        indicator="_reference_join",
    )
    _require_complete_join(merged, "_reference_join", "python_candidates -> unity_reference")
    merged = merged.drop(columns="_reference_join")
    if merged.empty:
        return pd.DataFrame(columns=CANDIDATE_DETAIL_COLUMNS)
    _validate_capture_provenance(merged)

    records: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        record = {column: str(row[column]) for column in METRIC_GROUP_COLUMNS}
        record.update(
            {
                "candidate_id": str(row["candidate_id"]),
                "frame_id": int(row["frame_id"]),
                "reference_capture_mono_ms": _number(row["reference_capture_mono_ms"]),
                "source_capture_mono_ms": _number(row["source_capture_mono_ms"]),
                "server_receive_mono_ms": _number(row["server_receive_mono_ms"]),
                "server_publish_mono_ms": _number(row["server_publish_mono_ms"]),
                "unity_pose_handle_mono_ms": _number(row["unity_pose_handle_mono_ms"]),
                "candidate_arrival_ms": _difference(
                    row["unity_pose_handle_mono_ms"], row["source_capture_mono_ms"]
                ),
                "candidate_processing_ms": _difference(
                    row["server_publish_mono_ms"], row["server_receive_mono_ms"]
                ),
                "total_ms": _number(row["total_ms"]),
                "yolo_ms": _number(row["yolo_ms"]),
                "depth_ms": _number(row["depth_ms"]),
                "cutie_ms": _number(row["cutie_ms"]),
                "pose_ms": _number(row["pose_ms"]),
            }
        )
        records.append(record)
    return pd.DataFrame.from_records(records, columns=CANDIDATE_DETAIL_COLUMNS)


def _build_render_detail(render: pd.DataFrame) -> pd.DataFrame:
    """选择逐 tick 时效性字段并规范数值类型。"""

    if render.empty:
        return pd.DataFrame(columns=RENDER_DETAIL_COLUMNS)
    records: list[dict[str, Any]] = []
    for _, row in render.iterrows():
        record = {column: str(row[column]) for column in METRIC_GROUP_COLUMNS}
        record.update(
            {
                "render_tick_id": int(row["render_tick_id"]),
                "render_mono_ms": _number(row["render_mono_ms"]),
                "source_frame_id": int(row["source_frame_id"]),
                "has_output_pose": bool(row["has_output_pose"]),
                "has_display_pose": bool(row["has_display_pose"]),
                "observation_age_ms": _number(row["observation_age_ms"]),
                "smoothing_delay_ms": _number(row["smoothing_delay_ms"]),
            }
        )
        records.append(record)
    return pd.DataFrame.from_records(records, columns=RENDER_DETAIL_COLUMNS)


def _summarize_latency(
    candidate_detail: pd.DataFrame,
    render_detail: pd.DataFrame,
) -> pd.DataFrame:
    """按完整实验上下文与 variant 合并候选和 render 统计。"""

    candidate_groups = _group_map(candidate_detail)
    render_groups = _group_map(render_detail)
    group_keys = sorted(set(candidate_groups) | set(render_groups))
    rows: list[dict[str, Any]] = []
    for key in group_keys:
        candidates = candidate_groups.get(key, pd.DataFrame(columns=CANDIDATE_DETAIL_COLUMNS))
        render = render_groups.get(key, pd.DataFrame(columns=RENDER_DETAIL_COLUMNS))
        context_source = candidates if not candidates.empty else render
        context = {
            column: str(context_source.iloc[0][column])
            for column in METRIC_GROUP_COLUMNS
        }
        rows.append(
            {
                **context,
                "candidate_count": int(candidates["candidate_id"].nunique()),
                "render_tick_count": int(render["render_tick_id"].nunique()),
                "candidate_arrival_p50_ms": _percentile(candidates, "candidate_arrival_ms", 50),
                "candidate_arrival_p95_ms": _percentile(candidates, "candidate_arrival_ms", 95),
                "candidate_processing_p50_ms": _percentile(candidates, "candidate_processing_ms", 50),
                "candidate_processing_p95_ms": _percentile(candidates, "candidate_processing_ms", 95),
                "observation_age_p50_ms": _percentile(render, "observation_age_ms", 50),
                "observation_age_p95_ms": _percentile(render, "observation_age_ms", 95),
                "smoothing_delay_p50_ms": _percentile(render, "smoothing_delay_ms", 50),
                "smoothing_delay_p95_ms": _percentile(render, "smoothing_delay_ms", 95),
                "visual_perception_hz": _frequency_hz(
                    candidates,
                    id_column="candidate_id",
                    time_column="server_publish_mono_ms",
                ),
                "render_hz": _frequency_hz(
                    render,
                    id_column="render_tick_id",
                    time_column="render_mono_ms",
                ),
            }
        )
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def _group_map(frame: pd.DataFrame) -> dict[tuple[str, ...], pd.DataFrame]:
    """把共享分组迭代器转换成可跨表合并的稳定键映射。"""

    if frame.empty:
        return {}
    return {
        tuple(context[column] for column in METRIC_GROUP_COLUMNS): group
        for context, group in iter_metric_groups(frame)
    }


def _require_unique(frame: pd.DataFrame, columns: list[str], table_name: str) -> None:
    """拒绝会使跨表连接产生笛卡尔复制的重复主键。"""

    if frame.duplicated(columns, keep=False).any():
        raise ValueError(f"{table_name} 的主键 {columns} 不唯一。")


def _require_complete_join(frame: pd.DataFrame, indicator: str, join_name: str) -> None:
    """拒绝跨表连接缺失，避免指标阶段静默丢弃 candidate。"""

    missing = frame[indicator].ne("both")
    if missing.any():
        raise ValueError(f"{join_name} 有 {int(missing.sum())} 行无法匹配。")


def _validate_capture_provenance(frame: pd.DataFrame, *, tolerance_ms: float = 1e-3) -> None:
    """要求 admission 来源时刻与同 frame reference 的采集时刻一致。"""

    source = pd.to_numeric(frame["source_capture_mono_ms"], errors="coerce").to_numpy(dtype=float)
    reference = pd.to_numeric(frame["reference_capture_mono_ms"], errors="coerce").to_numpy(dtype=float)
    comparable = np.isfinite(source) & np.isfinite(reference)
    mismatch = comparable & (np.abs(source - reference) > tolerance_ms)
    if mismatch.any():
        raise ValueError(
            "unity_admission 与 unity_reference 的 capture provenance "
            f"有 {int(mismatch.sum())} 行不一致。"
        )


def _percentile(frame: pd.DataFrame, column: str, percentile: float) -> float:
    """对可选明细列计算有限值分位数。"""

    if frame.empty or column not in frame:
        return np.nan
    return finite_percentile(pd.to_numeric(frame[column], errors="coerce"), percentile)


def _frequency_hz(frame: pd.DataFrame, *, id_column: str, time_column: str) -> float:
    """以唯一事件的首个时间戳估计平均频率；不足两个事件时返回 NaN。"""

    if frame.empty:
        return np.nan
    events = frame[[id_column, time_column]].drop_duplicates(id_column, keep="first")
    times = pd.to_numeric(events[time_column], errors="coerce").dropna().to_numpy(dtype=float)
    times = np.sort(times[np.isfinite(times)])
    if len(times) < 2:
        return np.nan
    span_ms = float(times[-1] - times[0])
    if span_ms <= 0.0:
        return np.nan
    return float((len(times) - 1) * 1000.0 / span_ms)


def _number(value: object) -> float:
    """把可选数值转换成有限 float，不可用时返回 NaN。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


def _difference(later: object, earlier: object) -> float:
    """计算两个时刻之差；任一不可用时返回 NaN。"""

    later_value = _number(later)
    earlier_value = _number(earlier)
    if not np.isfinite(later_value) or not np.isfinite(earlier_value):
        return np.nan
    return float(later_value - earlier_value)


__all__ = ["LatencyMetricsResult", "compute_latency"]
