"""RQ1（静态锚定质量）分析薄封装。

本模块不重算任何指标：调用共享引擎 :func:`egoanchor.eval.metrics.compute_all_metrics`
产出全部指标，再按 RQ1 关注的静止场景（``static_observation``、``occlusion_recovery``）
过滤，并把 *Full* vs *No-StaticLock* 双变体逐场景对比组织成论文视图。

遮挡恢复恢复时间依赖 ``manifest.event_markers``，而 Unity 契约层当前恒写空数组；
因此本模块从 ``rq1_metric == "occlusion_recovery"`` 段的起始时刻在内存合成 marker，
注入临时 manifest 后再交给共享引擎的 recovery 指标，无需改动契约层。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    # 直接执行本脚本时，把 src/ 加入 sys.path 以解析 egoanchor 包。
    # 本文件位于 src/egoanchor/eval/research/rq1/analyze.py，src = parents[4]。
    _package_root = Path(__file__).resolve().parents[4]
    if str(_package_root) not in sys.path:
        sys.path.insert(0, str(_package_root))

from egoanchor.eval.io import SessionLogs, load_session
from egoanchor.eval.metrics import compute_all_metrics
from egoanchor.eval.report import write_figures, write_sanity, write_tables
# 纯绘图层单独成模块（无 cv2/metrics 重依赖），analyze 与轻量复现脚本共用同一实现。
# DEFAULT_FIGS_DIR / STATIC_STEADY_WINDOW_S / write_rq1_figure 均在 plot.py 中定义，
# 此处 re-export 以保持既有 `from ...analyze import ...` 调用点与测试不变。
from egoanchor.eval.research.rq1.plot import (
    DEFAULT_FIGS_DIR,
    STATIC_STEADY_WINDOW_S,
    write_rq1_figure,
)


# RQ1 只评估静止场景；slow/fast/rotation 属 RQ2。
RQ1_CONDITIONS: tuple[str, ...] = ("static_observation", "occlusion_recovery")


def synthesize_occlusion_markers(output: pd.DataFrame) -> list[dict[str, Any]]:
    """从 ``rq1_metric == "occlusion_recovery"`` 连续段起点合成事件 marker。

    每个连续遮挡段生成一个 ``{"type": "occlusion_recovery", "mono_ms": <段首 render_mono_ms>}``，
    供 :func:`egoanchor.eval.metrics.recovery.compute_recovery` 计算恢复时间。

    Args:
        output: 含 ``rq1_metric`` 与 ``render_mono_ms`` 列的 output 长表。

    Returns:
        marker 字典列表，按时间升序；无遮挡段或缺列时返回空列表。
    """

    if output.empty or "rq1_metric" not in output.columns or "render_mono_ms" not in output.columns:
        return []

    work = output.sort_values("render_mono_ms").copy()
    metric = work["rq1_metric"].fillna("none").astype(str)
    run_id = (metric != metric.shift()).cumsum()

    markers: list[dict[str, Any]] = []
    for _, group in work.groupby(run_id, sort=False):
        if str(group["rq1_metric"].iloc[0]) != "occlusion_recovery":
            continue
        markers.append(
            {"type": "occlusion_recovery", "mono_ms": float(group["render_mono_ms"].iloc[0])}
        )
    return markers


def filter_rq1_tables(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """把每张含 ``condition`` 列的表过滤到 RQ1 场景；无该列的表原样保留。"""

    filtered: dict[str, pd.DataFrame] = {}
    for name, table in tables.items():
        if isinstance(table, pd.DataFrame) and "condition" in table.columns:
            filtered[name] = table[table["condition"].isin(RQ1_CONDITIONS)].reset_index(drop=True)
        else:
            filtered[name] = table
    return filtered


def _inject_markers(logs: SessionLogs) -> SessionLogs:
    """把合成的遮挡 marker 注入 manifest 的 event_markers（不改原 logs 引用）。"""

    markers = synthesize_occlusion_markers(logs.output)
    if not markers:
        return logs
    manifest = dict(logs.manifest)
    manifest["event_markers"] = list(manifest.get("event_markers", [])) + markers
    return SessionLogs(capture=logs.capture, output=logs.output, pose=logs.pose, manifest=manifest)


def run_rq1_analysis(
    session_dir: Path | str,
    *,
    report_dir: Path | str | None = None,
    figs_dir: Path | str | None = None,
) -> dict[str, pd.DataFrame]:
    """运行 RQ1 全链路分析：加载 → 合成遮挡 marker → 计算 → 过滤 → 导出。

    Args:
        session_dir: ``data/eval/<session_id>`` 目录。
        report_dir: CSV/summary 输出目录，默认 ``<session_dir>/report``。
        figs_dir: 论文图输出目录，默认仓库根 ``2026-EgoAnchor-Typst/figs/rq1``。

    Returns:
        过滤到 RQ1 场景后的 tables dict。
    """

    session_path = Path(session_dir)
    logs = _inject_markers(load_session(session_path))
    result = compute_all_metrics(logs)

    out_report = Path(report_dir) if report_dir is not None else session_path / "report"
    write_tables(result, out_report)
    write_sanity(result, out_report)

    figs = Path(figs_dir) if figs_dir is not None else DEFAULT_FIGS_DIR
    write_figures(result, figs)
    # 论文正文用的 2×2 网格图（行=平移/旋转指标，列=静止/遮挡场景）；
    # 只消费已算好的表，不重算指标。
    write_rq1_figure(result.tables, figs / "fig_rq1_static")

    return filter_rq1_tables(result.tables)


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数。"""

    parser = argparse.ArgumentParser(description="Run EgoAnchor RQ1 static anchoring analysis.")
    parser.add_argument("--session-dir", required=True, help="data/eval/<session_id> 目录。")
    parser.add_argument("--report-dir", default=None, help="可选 report 输出目录，默认 <session_dir>/report。")
    parser.add_argument("--figs-dir", default=None, help="可选论文图目录，默认 2026-EgoAnchor-Typst/figs/rq1。")
    args = parser.parse_args(argv)

    tables = run_rq1_analysis(
        Path(args.session_dir),
        report_dir=Path(args.report_dir) if args.report_dir else None,
        figs_dir=Path(args.figs_dir) if args.figs_dir else None,
    )

    accuracy = tables.get("anchor_error_summary", pd.DataFrame())
    print("RQ1 anchor_error_summary (static scenes, Full vs No-StaticLock):")
    print(accuracy.to_string(index=False) if not accuracy.empty else "  <no data>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
