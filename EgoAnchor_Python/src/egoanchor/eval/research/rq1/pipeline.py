"""RQ1 静态锚定质量的分析管线。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from egoanchor.eval.io import SessionLogs, load_session
from egoanchor.eval.metrics import MetricsResult, compute_all_metrics
from egoanchor.eval.report import write_sanity, write_tables

from .plot import DEFAULT_FIGS_DIR, write_rq1_timelines


RQ1_CONDITIONS: tuple[str, ...] = ("static_observation", "occlusion_recovery")


def synthesize_occlusion_markers(output: pd.DataFrame) -> list[dict[str, Any]]:
    """从连续遮挡标记段的起点合成恢复事件 marker。"""

    if (
        output.empty
        or "rq1_metric" not in output.columns
        or "render_mono_ms" not in output.columns
    ):
        return []
    work = output.sort_values("render_mono_ms").copy()
    metric = work["rq1_metric"].fillna("none").astype(str)
    run_id = (metric != metric.shift()).cumsum()
    markers: list[dict[str, Any]] = []
    for _, group in work.groupby(run_id, sort=False):
        if str(group["rq1_metric"].iloc[0]) == "occlusion_recovery":
            markers.append(
                {
                    "type": "occlusion_recovery",
                    "mono_ms": float(group["render_mono_ms"].iloc[0]),
                }
            )
    return markers


def filter_rq1_tables(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """把含 condition 列的表过滤到 RQ1 两个静止场景。"""

    filtered: dict[str, pd.DataFrame] = {}
    for name, table in tables.items():
        if isinstance(table, pd.DataFrame) and "condition" in table.columns:
            filtered[name] = table[table["condition"].isin(RQ1_CONDITIONS)].reset_index(
                drop=True
            )
        else:
            filtered[name] = table
    return filtered


def run_rq1_analysis(
    session_dir: Path | str,
    *,
    report_dir: Path | str | None = None,
    figs_dir: Path | str | None = None,
) -> dict[str, pd.DataFrame]:
    """加载正式会话，计算 RQ1 指标并输出静止 XYZ-帧图。"""

    session_path = Path(session_dir)
    logs = _inject_markers(load_session(session_path))
    result = compute_all_metrics(logs)
    tables = filter_rq1_tables(result.tables)
    filtered_result = MetricsResult(tables=tables, sanity=result.sanity)
    out_report = Path(report_dir) if report_dir is not None else session_path / "report"
    write_tables(filtered_result, out_report)
    write_sanity(filtered_result, out_report)

    figs = Path(figs_dir) if figs_dir is not None else DEFAULT_FIGS_DIR
    timeline_window = write_rq1_timelines(logs.output, figs)
    timeline_window.to_csv(
        out_report / "rq1_timeline_window.csv",
        index=False,
        float_format="%.9g",
    )
    tables["rq1_timeline_window"] = timeline_window
    return tables


def _inject_markers(logs: SessionLogs) -> SessionLogs:
    """把合成的遮挡 marker 注入临时 manifest。"""

    markers = synthesize_occlusion_markers(logs.output)
    if not markers:
        return logs
    manifest = dict(logs.manifest)
    manifest["event_markers"] = list(manifest.get("event_markers", [])) + markers
    return SessionLogs(
        capture=logs.capture,
        output=logs.output,
        pose=logs.pose,
        manifest=manifest,
    )


__all__ = [
    "RQ1_CONDITIONS",
    "filter_rq1_tables",
    "run_rq1_analysis",
    "synthesize_occlusion_markers",
]
