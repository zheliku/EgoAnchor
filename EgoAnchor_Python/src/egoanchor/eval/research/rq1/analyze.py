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

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
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


# RQ1 只评估静止场景；slow/fast/rotation 属 RQ2。
RQ1_CONDITIONS: tuple[str, ...] = ("static_observation", "occlusion_recovery")

# 论文图导出默认目录（相对仓库根）。
DEFAULT_FIGS_DIR = Path("2026-EgoAnchor-Typst/figs/rq1")


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


def write_rq1_figure(tables: dict[str, pd.DataFrame], out_path: Path | str) -> Path:
    """绘制 RQ1 静态锚定质量三联图（对齐论文 <fig:rq1-static> caption 的 A/B/C）。

    本函数不重算指标，只消费共享引擎已算好的表：

    - (A) 长期稳定性：``static_observation`` 段 *Full* 变体的锚点平移误差时间线，
      展示无累积漂移。
    - (B) 静止抖动与屏幕漂移：*Full* vs *No-StaticLock* 在 ``static_observation``
      场景的 ``position_jitter_rms_m``（mm）与 ``slip_rms_px``（px）分组柱状对比。
    - (C) 遮挡恢复：``occlusion_recovery`` 段两变体的锚点平移误差时间线，展示遮挡
      期间锚点保持在稳态精度附近、目标重现后无重收敛尖峰。

    Args:
        tables: :func:`egoanchor.eval.metrics.compute_all_metrics` 产出的完整 tables
            （未过滤即可；本函数内部按场景取子集）。
        out_path: 输出文件名主干（不含后缀），同时写 ``.pdf`` 与 ``.png``。

    Returns:
        写出的 PDF 路径。
    """

    detail = tables.get("anchor_error_detail", pd.DataFrame())
    jitter = tables.get("jitter_summary", pd.DataFrame())
    slip = tables.get("slip_summary", pd.DataFrame())

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))

    # ── (A) 长期稳定性：static_observation × Full 误差时间线 ──
    ax_a = axes[0]
    static_full = _select_detail(detail, "static_observation", "Full")
    if static_full.empty:
        _placeholder(ax_a, "(A) long-term stability: no data")
    else:
        t = static_full["render_mono_ms"].to_numpy(dtype=float)
        t = (t - t.min()) * 0.001
        ax_a.plot(t, static_full["translation_error_m"].to_numpy(dtype=float) * 1000.0,
                  color="#2C7FB8", linewidth=1.2)
        ax_a.set_xlabel("time (s)")
        ax_a.set_ylabel("translation error (mm)")
        ax_a.set_title("(A) Long-term stability (Full)")
        ax_a.grid(True, alpha=0.25)

    # ── (B) 静止抖动 + 屏幕漂移：Full vs No-StaticLock 分组柱状 ──
    ax_b = axes[1]
    jitter_mm = _static_metric_by_variant(jitter, "position_jitter_rms_m", scale=1000.0)
    slip_px = _static_metric_by_variant(slip, "slip_rms_px", scale=1.0)
    variants = ["Full", "No-StaticLock"]
    if not jitter_mm and not slip_px:
        _placeholder(ax_b, "(B) jitter / slip: no data")
    else:
        x = np.arange(len(variants))
        width = 0.35
        jitter_vals = [jitter_mm.get(v, np.nan) for v in variants]
        slip_vals = [slip_px.get(v, np.nan) for v in variants]
        ax_b.bar(x - width / 2, jitter_vals, width, label="jitter RMS (mm)", color="#2C7FB8")
        ax_b.bar(x + width / 2, slip_vals, width, label="screen slip RMS (px)", color="#E8853A")
        ax_b.set_xticks(x, variants)
        ax_b.set_title("(B) Static jitter & screen slip")
        ax_b.grid(True, axis="y", alpha=0.25)
        ax_b.legend(loc="best", fontsize=8)

    # ── (C) 遮挡恢复：occlusion_recovery 两变体误差时间线 ──
    ax_c = axes[2]
    occ = _select_detail(detail, "occlusion_recovery", None)
    if occ.empty:
        _placeholder(ax_c, "(C) occlusion recovery: no data")
    else:
        colors = {"Full": "#2C7FB8", "No-StaticLock": "#E8853A"}
        t0 = occ["render_mono_ms"].min()
        for label, group in occ.groupby("label", sort=True):
            group = group.sort_values("render_mono_ms")
            t = (group["render_mono_ms"].to_numpy(dtype=float) - t0) * 0.001
            ax_c.plot(t, group["translation_error_m"].to_numpy(dtype=float) * 1000.0,
                      label=str(label), linewidth=1.0, color=colors.get(str(label)))
        ax_c.set_xlabel("time (s)")
        ax_c.set_ylabel("translation error (mm)")
        ax_c.set_title("(C) Occlusion recovery")
        ax_c.grid(True, alpha=0.25)
        ax_c.legend(loc="best", fontsize=8)

    stem = Path(out_path)
    stem.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(stem.with_suffix(".png"), dpi=160)
    pdf_path = stem.with_suffix(".pdf")
    fig.savefig(pdf_path)
    plt.close(fig)
    return pdf_path


def _select_detail(detail: pd.DataFrame, condition: str, label: str | None) -> pd.DataFrame:
    """从 anchor_error_detail 取指定 condition（可选 label）子集。"""

    if detail.empty or "condition" not in detail.columns:
        return pd.DataFrame()
    view = detail[detail["condition"] == condition]
    if label is not None and "label" in view.columns:
        view = view[view["label"] == label]
    return view


def _static_metric_by_variant(summary: pd.DataFrame, column: str, *, scale: float) -> dict[str, float]:
    """从 summary 表取 static_observation 场景各变体的某列值（乘 scale）。"""

    if summary.empty or "condition" not in summary.columns or column not in summary.columns:
        return {}
    view = summary[summary["condition"] == "static_observation"]
    result: dict[str, float] = {}
    for row in view.itertuples():
        value = getattr(row, column)
        if pd.notna(value):
            result[str(row.label)] = float(value) * scale
    return result


def _placeholder(ax: "plt.Axes", message: str) -> None:
    """空面板提示。"""

    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)
    ax.set_axis_off()


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
    # 论文正文用的三联图（A/B/C），只消费已算好的表，不重算指标。
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
