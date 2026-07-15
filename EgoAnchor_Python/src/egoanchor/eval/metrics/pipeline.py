"""组合 schema-v2 的中性离线评估指标。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from egoanchor.eval.schema_v2 import EvalSessionV2

from .anchor_error import compute_anchor_error, summarize_pose_offset
from .diagnostics import compute_reliability_diagnostics
from .jitter import compute_static_metrics
from .latency import compute_latency
from .recovery import compute_occlusion_metrics, compute_transition_metrics


@dataclass(frozen=True)
class MetricsResult:
    """一个 schema-v2 session 的全部中性指标表。"""

    tables: dict[str, pd.DataFrame]
    """稳定表名到 DataFrame 的映射；表名不得携带旧 RQ 语义。"""


def compute_all_metrics(session: EvalSessionV2) -> MetricsResult:
    """从 normalized schema-v2 表计算 trial/event/variant 级指标。

    平台 reference 只用于同一 Quest 时间线下的系统行为比较，不在本函数或输出中
    称为外部真值。display error 包含 hold-last；runtime output availability 由恢复指标
    单独读取 ``has_output_pose``。
    """

    render = session.unity_render
    display_error_detail, display_error_summary = compute_anchor_error(render)
    latency = compute_latency(
        render,
        session.unity_reference,
        session.python_candidates,
        session.unity_admission,
    )
    reliability = compute_reliability_diagnostics(
        session.python_candidates,
        session.unity_admission,
    )
    tables = {
        "display_error_detail": display_error_detail,
        "display_error_summary": display_error_summary,
        "display_offset_summary": summarize_pose_offset(display_error_detail),
        "static_metrics": compute_static_metrics(render),
        "transition_metrics": compute_transition_metrics(render, session.events),
        "occlusion_recovery_metrics": compute_occlusion_metrics(render, session.events),
        "latency_candidate_detail": latency.candidate_detail,
        "latency_render_detail": latency.render_detail,
        "latency_summary": latency.summary,
        "reliability_summary": reliability.summary,
        "vcd_histogram": reliability.vcd_histogram,
        "admission_distribution": reliability.admission_distribution,
    }
    _reject_legacy_table_names(tables)
    return MetricsResult(tables=tables)


def _reject_legacy_table_names(tables: dict[str, pd.DataFrame]) -> None:
    """防止旧 RQ 命名重新进入正式输出接口。"""

    legacy = sorted(name for name in tables if "rq" in name.lower())
    if legacy:
        raise ValueError(f"指标表名不得包含旧 RQ 语义：{legacy}")


__all__ = ["MetricsResult", "compute_all_metrics"]
