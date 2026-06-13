"""评估表格与 sanity JSON 导出。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from eval.metrics import MetricsResult


SUMMARY_TABLES = [
    "anchor_error_summary",
    "pose_offset_summary",
    "latency_summary",
    "jitter_summary",
    "slip_summary",
    "rq1_raw_mapping_error_summary",
    "rq1_raw_mapping_slip_summary",
    "lag_summary",
    "jump_suppression_summary",
    "recovery_summary",
]
"""默认写入 summary.md 的表。"""


def write_tables(result: MetricsResult, report_dir: Path | str) -> None:
    """导出 CSV 和 summary.md。"""

    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, table in result.tables.items():
        table.to_csv(output_dir / f"{name}.csv", index=False)
    (output_dir / "summary.md").write_text(_build_summary_markdown(result), encoding="utf-8")


def write_sanity(result: MetricsResult, report_dir: Path | str) -> None:
    """导出 GT/anchor 语义一致性 JSON。"""

    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "gt_anchor_sanity.json").write_text(
        json.dumps(_json_ready(result.sanity), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_summary_markdown(result: MetricsResult) -> str:
    """构造 Markdown summary。"""

    lines = [
        "# EgoAnchor Eval Summary",
        "",
        "## GT / Anchor Sanity",
        "",
        f"- session_id: `{result.sanity.get('session_id', '')}`",
        f"- object_id: `{result.sanity.get('object_id', '')}`",
        f"- gt_source: `{result.sanity.get('gt_source', '')}`",
        f"- gt_transform: `{result.sanity.get('gt_transform', '')}`",
        "",
    ]
    for name in SUMMARY_TABLES:
        table = result.tables.get(name, pd.DataFrame())
        lines.append(f"## {name}")
        lines.append("")
        lines.append(_to_markdown(table))
        lines.append("")
    return "\n".join(lines)


def _to_markdown(table: pd.DataFrame, max_rows: int = 20) -> str:
    """不依赖 tabulate 的简易 Markdown 表格。"""

    if table.empty:
        return "_insufficient_data_"
    view = table.head(max_rows).copy()
    columns = [str(col) for col in view.columns]
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in view.iterrows():
        rows.append("| " + " | ".join(_format_cell(row[col]) for col in view.columns) + " |")
    if len(table) > max_rows:
        rows.append(f"\n_显示前 {max_rows} 行，共 {len(table)} 行。_")
    return "\n".join(rows)


def _format_cell(value: Any) -> str:
    """格式化 Markdown 单元格。"""

    if value is None:
        return ""
    if isinstance(value, float):
        if not np.isfinite(value):
            return "nan"
        return f"{value:.6g}"
    text = str(value)
    return text.replace("|", "\\|")


def _json_ready(value: Any) -> Any:
    """把 numpy/pandas 值转换为 JSON 友好结构。"""

    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_ready(item) for item in value.tolist()]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


__all__ = ["write_sanity", "write_tables"]
