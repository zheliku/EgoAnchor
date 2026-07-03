"""评估图表导出。"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from egoanchor.eval.metrics import MetricsResult


def write_figures(result: MetricsResult, report_dir: Path | str) -> None:
    """导出当前可用的评估图。"""

    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_error_timeline(result.tables.get("anchor_error_detail", pd.DataFrame()), output_dir)
    _write_latency_breakdown(result.tables.get("latency_summary", pd.DataFrame()), output_dir)
    _write_jitter_lag(result.tables.get("jitter_summary", pd.DataFrame()), result.tables.get("lag_summary", pd.DataFrame()), output_dir)
    _write_slip_timeline(result.tables.get("slip_detail", pd.DataFrame()), output_dir)
    _write_recovery(result.tables.get("recovery_summary", pd.DataFrame()), output_dir)


def _write_error_timeline(detail: pd.DataFrame, output_dir: Path) -> None:
    """写误差时间线。"""

    fig, ax = plt.subplots(figsize=(9, 4.5))
    if detail.empty:
        _placeholder(ax, "anchor error: insufficient data")
    else:
        for label, group in detail.groupby("label", sort=True):
            ax.plot(
                group["render_mono_ms"].to_numpy(dtype=float) * 0.001,
                group["translation_error_m"].to_numpy(dtype=float),
                label=str(label),
                linewidth=1.6,
            )
        ax.set_xlabel("time (s)")
        ax.set_ylabel("translation error (m)")
        ax.set_title("Anchor Error Timeline")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best")
    _save(fig, output_dir / "error_timeline")


def _write_latency_breakdown(summary: pd.DataFrame, output_dir: Path) -> None:
    """写 latency breakdown 柱状图。"""

    fig, ax = plt.subplots(figsize=(9, 4.5))
    if summary.empty:
        _placeholder(ax, "latency breakdown: insufficient data")
    else:
        labels = [f"{row.condition}/{row.label}" for row in summary.itertuples()]
        perception = summary["perception_total_p50_ms"].fillna(0.0).to_numpy(dtype=float)
        residual = summary["publish_to_apply_est_p50_ms"].fillna(0.0).to_numpy(dtype=float)
        x = np.arange(len(summary))
        ax.bar(x, perception, label="perception p50")
        ax.bar(x, residual, bottom=perception, label="publish/apply estimate p50")
        ax.set_xticks(x, labels, rotation=35, ha="right")
        ax.set_ylabel("milliseconds")
        ax.set_title("Latency Breakdown")
        ax.grid(True, axis="y", alpha=0.25)
        ax.legend(loc="best")
    _save(fig, output_dir / "latency_breakdown")


def _write_jitter_lag(jitter: pd.DataFrame, lag: pd.DataFrame, output_dir: Path) -> None:
    """写 jitter-lag tradeoff 散点图。"""

    fig, ax = plt.subplots(figsize=(6, 4.5))
    if jitter.empty or lag.empty:
        _placeholder(ax, "jitter-lag: insufficient data")
    else:
        merged = jitter.merge(lag, on=["condition", "label"], how="inner")
        merged = merged[np.isfinite(merged["position_jitter_rms_m"]) & np.isfinite(merged["lag_ms"])]
        if merged.empty:
            _placeholder(ax, "jitter-lag: insufficient data")
        else:
            for label, group in merged.groupby("label", sort=True):
                ax.scatter(group["lag_ms"], group["position_jitter_rms_m"], label=str(label), s=50)
            ax.set_xlabel("lag (ms)")
            ax.set_ylabel("position jitter RMS (m)")
            ax.set_title("Jitter / Lag Tradeoff")
            ax.grid(True, alpha=0.25)
            ax.legend(loc="best")
    _save(fig, output_dir / "jitter_lag")


def _write_slip_timeline(detail: pd.DataFrame, output_dir: Path) -> None:
    """写 slip 时间线。"""

    fig, ax = plt.subplots(figsize=(9, 4.5))
    if detail.empty:
        _placeholder(ax, "slip: insufficient data")
    else:
        for label, group in detail.groupby("label", sort=True):
            ax.plot(group["render_mono_ms"] * 0.001, group["slip_px"], label=str(label), linewidth=1.6)
        ax.set_xlabel("time (s)")
        ax.set_ylabel("slip (px)")
        ax.set_title("Screen-Space Slip")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best")
    _save(fig, output_dir / "slip_timeline")


def _write_recovery(summary: pd.DataFrame, output_dir: Path) -> None:
    """写 recovery 汇总图。"""

    fig, ax = plt.subplots(figsize=(7, 4.5))
    if summary.empty:
        _placeholder(ax, "recovery: insufficient data")
    else:
        view = summary[np.isfinite(summary["recovery_time_ms"])]
        if view.empty:
            _placeholder(ax, "recovery: insufficient data")
        else:
            labels = [f"{row.event_type}/{row.label}" for row in view.itertuples()]
            ax.bar(np.arange(len(view)), view["recovery_time_ms"].to_numpy(dtype=float))
            ax.set_xticks(np.arange(len(view)), labels, rotation=35, ha="right")
            ax.set_ylabel("recovery time (ms)")
            ax.set_title("Recovery Time")
            ax.grid(True, axis="y", alpha=0.25)
    _save(fig, output_dir / "recovery_timeline")


def _placeholder(ax: plt.Axes, message: str) -> None:
    """在空图中写数据不足提示。"""

    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)
    ax.set_axis_off()


def _save(fig: plt.Figure, stem: Path) -> None:
    """同时保存 PNG 和 PDF。"""

    fig.tight_layout()
    fig.savefig(stem.with_suffix(".png"), dpi=160)
    fig.savefig(stem.with_suffix(".pdf"))
    plt.close(fig)


__all__ = ["write_figures"]

