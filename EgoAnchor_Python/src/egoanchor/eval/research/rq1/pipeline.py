"""RQ1 静态锚定质量的分析管线。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from egoanchor.eval.io import load_session
from egoanchor.eval.metrics import MetricsResult, compute_all_metrics
from egoanchor.eval.report import write_sanity, write_tables

from .plot import DEFAULT_FIGS_DIR, write_rq1_timelines


RQ1_CONDITIONS: tuple[str, ...] = ("static_observation", "occlusion_recovery")


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
    """加载正式会话，计算 RQ1 指标并输出静止 XYZ-t 图。"""

    session_path = Path(session_dir)
    logs = load_session(session_path)
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


__all__ = [
    "RQ1_CONDITIONS",
    "filter_rq1_tables",
    "run_rq1_analysis",
]
