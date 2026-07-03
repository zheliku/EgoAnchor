"""RQ1 单 session 锚定质量分析。

从 `data/eval/<session_id>/` 读取日志，输出到 `data/research/rq1/<session_id>/`。
分析步骤：
1. 加载 session 日志（capture + output + pose_result + manifest）
2. 自动检测场景片段（静止 / 慢速 / 快速 / 旋转 / 遮挡）
3. 计算 RQ1 核心指标：anchor_error、jitter、lag、latency、recovery
4. 写 CSV 和 Markdown 摘要
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _df_to_md(df: pd.DataFrame) -> str:
    """把 DataFrame 转成 Markdown 表格，不依赖 tabulate。"""
    if df.empty:
        return ""
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep    = "| " + " | ".join("---" for _ in cols) + " |"
    rows = []
    for _, row in df.iterrows():
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append(f"{v:.4g}")
            else:
                cells.append(str(v))
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep] + rows)

from egoanchor.eval.core.auto_scenario_detection import detect_scenarios, summarize_segments
from egoanchor.eval.core.gt_filter import filter_valid_gt, suggest_startup_cutoff
from egoanchor.eval.io import load_session, SessionLogs
from egoanchor.eval.metrics import compute_all_metrics
from egoanchor.eval.report import write_tables


def analyze_session(
    session_dir: Path | str,
    output_dir: Path | str | None = None,
    *,
    label_filter: str | None = None,
    startup_grace_s: float = 0.0,
    frozen_window_s: float = 2.0,
) -> Path:
    """分析一个 session 并写结果到 output_dir。

    Args:
        session_dir: `data/eval/<session_id>` 目录路径。
        output_dir: 分析结果输出目录；默认在 `data/research/rq1/<session_id>`。
        label_filter: 只分析指定 variant label；为空则分析所有变体。
        startup_grace_s: 去掉开头这么多秒（控制器激活热身期）；0 表示自动推断。
        frozen_window_s: 连续零速度超过此秒数则判定为控制器休眠并剔除。
    """
    session_path = Path(session_dir)
    if output_dir is None:
        research_root = session_path.parent.parent / "research" / "rq1"
        out_path = research_root / session_path.name
    else:
        out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # ── 加载日志 ──
    logs = load_session(session_path)

    # ── GT 有效性过滤 ──
    primary_raw = _extract_primary(logs.output)
    if not primary_raw.empty:
        # 若未指定热身时长，自动估算控制器首次真正激活的时间
        grace = startup_grace_s
        if grace == 0.0:
            grace = suggest_startup_cutoff(primary_raw)

        valid_primary, dropped_primary = filter_valid_gt(
            primary_raw,
            startup_grace_s=grace,
            frozen_window_s=frozen_window_s,
        )
        n_total  = len(primary_raw)
        n_valid  = len(valid_primary)
        n_drop   = n_total - n_valid
        drop_pct = 100.0 * n_drop / n_total if n_total > 0 else 0.0
    else:
        valid_primary = primary_raw
        n_total = n_valid = n_drop = 0
        drop_pct = 0.0
        grace = 0.0

    # ── 写过滤统计 ──
    _write_filter_report(out_path, n_total, n_valid, n_drop, drop_pct, grace, frozen_window_s)

    # ── 自动场景检测（仅用有效帧） ──
    if not valid_primary.empty:
        segments = detect_scenarios(valid_primary)
        seg_df = summarize_segments(segments)
        seg_df.to_csv(out_path / "segments.csv", index=False)
        seg_df.pipe(_df_to_md)
    else:
        segments = []

    # ── 过滤 logs.output 并重新组装 SessionLogs ──
    filtered_logs = _apply_filter_to_logs(logs, valid_primary)

    # ── 计算全量指标 ──
    result = compute_all_metrics(filtered_logs)

    # ── 写报告 ──
    write_tables(result, out_path)

    # ── 写速查摘要 ──
    _write_summary(result, logs, segments, out_path, n_total, n_valid)

    return out_path


def _apply_filter_to_logs(logs: SessionLogs, valid_primary: pd.DataFrame) -> SessionLogs:
    """用有效主变体的 render_mono_ms 集合过滤 logs.output，保持 SessionLogs 结构。"""
    if valid_primary.empty or logs.output.empty:
        return logs
    valid_times = set(valid_primary["render_mono_ms"].values)
    filtered_output = logs.output[logs.output["render_mono_ms"].isin(valid_times)].copy()
    return SessionLogs(
        capture=logs.capture,
        output=filtered_output,
        pose=logs.pose,
        manifest=logs.manifest,
    )


def _write_filter_report(
    out_path: Path,
    n_total: int,
    n_valid: int,
    n_drop: int,
    drop_pct: float,
    grace_s: float,
    frozen_window_s: float,
) -> None:
    """写 gt_filter_report.txt，记录过滤统计。"""
    lines = [
        "GT Filter Report",
        "================",
        f"total frames : {n_total}",
        f"valid frames : {n_valid}",
        f"dropped      : {n_drop} ({drop_pct:.1f}%)",
        f"startup grace: {grace_s:.2f} s (auto-estimated or user-set)",
        f"frozen window: {frozen_window_s:.1f} s",
    ]
    (out_path / "gt_filter_report.txt").write_text("\n".join(lines), encoding="utf-8")




def _extract_primary(output_df: pd.DataFrame) -> pd.DataFrame:
    """从 output 长表中提取主变体行，每个 tick 一行，去重。

    优先级：
    1. is_primary == True 的行
    2. 若无主变体标记，取第一个 label 的所有行
    3. 仍为空则直接去重返回（每 tick 只保留第一行）
    """
    if output_df.empty:
        return output_df

    primary = pd.DataFrame()

    # 尝试 is_primary 列
    if "is_primary" in output_df.columns:
        primary = output_df[output_df["is_primary"].fillna(False).astype(bool)].copy()

    # 回退：取第一个 label
    if primary.empty and "label" in output_df.columns:
        first_label = output_df["label"].iloc[0]
        primary = output_df[output_df["label"] == first_label].copy()

    # 兜底：整表去重
    if primary.empty:
        primary = output_df.copy()

    if "render_mono_ms" in primary.columns:
        primary = primary.sort_values("render_mono_ms").drop_duplicates(subset=["render_mono_ms"])
    return primary.reset_index(drop=True)


def _write_summary(result: Any, logs: Any, segments: list, out_path: Path,
                   n_total: int = 0, n_valid: int = 0) -> None:
    """写人类可读的 summary.md 摘要。"""
    lines: list[str] = []
    lines.append(f"# RQ1 摘要 — {out_path.name}\n")
    lines.append(f"**session**: `{logs.manifest.get('session_id', out_path.name)}`  ")
    lines.append(f"**object**: `{logs.manifest.get('object_id', '?')}`  ")
    if n_total > 0:
        lines.append(f"**有效帧**: {n_valid}/{n_total} ({100*n_valid/n_total:.0f}%)\n")
    else:
        lines.append("")

    # 场景片段概览
    if segments:
        lines.append("## 场景片段\n")
        from egoanchor.eval.core.auto_scenario_detection import ScenarioType
        from collections import Counter
        cnt = Counter(s.scenario_type.value for s in segments)
        for stype, n in sorted(cnt.items()):
            dur = sum(s.duration for s in segments if s.scenario_type.value == stype)
            lines.append(f"- **{stype}**: {n} 段，共 {dur:.1f} s")
        lines.append("")

    # anchor_error 表
    if hasattr(result, "anchor_error_summary") and not result.anchor_error_summary.empty:
        lines.append("## Anchor Error\n")
        lines.append(result.anchor_error_summary.pipe(_df_to_md))
        lines.append("")

    # jitter 表
    if hasattr(result, "jitter_summary") and not result.jitter_summary.empty:
        lines.append("## 抖动 (Jitter)\n")
        lines.append(result.jitter_summary.pipe(_df_to_md))
        lines.append("")

    # lag 表
    if hasattr(result, "lag_summary") and not result.lag_summary.empty:
        lines.append("## 运动滞后 (Lag)\n")
        lines.append(result.lag_summary.pipe(_df_to_md))
        lines.append("")

    # pipeline latency
    if hasattr(result, "latency_summary") and not result.latency_summary.empty:
        lines.append("## 端到端时延 (Latency)\n")
        lines.append(result.latency_summary.pipe(_df_to_md))
        lines.append("")

    out_path.joinpath("summary.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="RQ1 单 session 锚定质量分析")
    parser.add_argument("--session", required=True, type=Path, help="data/eval/<session_id> 目录")
    parser.add_argument("--output", type=Path, default=None, help="分析结果输出目录（默认 data/research/rq1/<session_id>）")
    parser.add_argument("--label", default=None, help="只分析指定 variant label")
    args = parser.parse_args(argv)

    out = analyze_session(args.session, args.output, label_filter=args.label)
    print(f"分析完成: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

