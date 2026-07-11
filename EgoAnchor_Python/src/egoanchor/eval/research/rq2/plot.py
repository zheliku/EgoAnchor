"""RQ2 论文结果所需的精简图表导出。"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def write_rq2_plots(tables: dict[str, pd.DataFrame], output_dir: Path | str) -> None:
    """只在存在正式可用数据时导出四类 RQ2 图。"""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    _plot_accuracy(tables.get("rq2_trial_summary", pd.DataFrame()), destination)
    _plot_paired(tables.get("rq2_paired_summary", pd.DataFrame()), destination)
    _plot_delay(
        tables.get("rq2_motion_delay", pd.DataFrame()),
        tables.get("rq2_trial_audit", pd.DataFrame()),
        destination,
    )
    _plot_envelope(tables.get("rq2_operating_envelope", pd.DataFrame()), destination)


def _plot_accuracy(summary: pd.DataFrame, output_dir: Path) -> None:
    """绘制主终点与动态精度概览。"""

    if summary.empty or "audit_accepted" not in summary.columns:
        return
    view = summary[summary["audit_accepted"].fillna(False).astype(bool)]
    if view.empty:
        return
    grouped = view.groupby(["condition", "label"], sort=True).agg(
        within=("within_tolerance_valid_tracking_rate", "mean"),
        error=("display_translation_p95_m", "mean"),
    ).reset_index()
    if grouped.empty:
        return
    labels = [f"{row.condition}\n{row.label}" for row in grouped.itertuples()]
    x = np.arange(len(grouped))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    axes[0].bar(x, grouped["within"].to_numpy(dtype=float))
    axes[0].set_ylim(0.0, 1.0)
    axes[0].set_ylabel("valid tracking rate")
    axes[0].set_xticks(x, labels, rotation=35, ha="right")
    axes[1].bar(x, grouped["error"].to_numpy(dtype=float) * 1000.0)
    axes[1].set_ylabel("translation P95 (mm)")
    axes[1].set_xticks(x, labels, rotation=35, ha="right")
    _save(fig, output_dir / "rq2_accuracy_primary")


def _plot_paired(paired: pd.DataFrame, output_dir: Path) -> None:
    """绘制 Full 相对 Raw-ZOH 的连续性—响应性配对权衡。"""

    if paired.empty:
        return
    scene = paired[paired["level"].eq("condition")]
    tolerance = scene[
        scene["metric"].eq("within_tolerance_valid_tracking_rate")
    ][["condition", "delta_mean"]].rename(columns={"delta_mean": "tolerance_delta"})
    lag = scene[scene["metric"].eq("display_translation_lag_ms")][
        ["condition", "delta_mean"]
    ].rename(columns={"delta_mean": "lag_delta"})
    merged = tolerance.merge(lag, on="condition", how="inner").dropna()
    if merged.empty:
        return
    fig, ax = plt.subplots(figsize=(6, 4.5))
    ax.axhline(0.0, color="0.75", linewidth=1.0)
    ax.axvline(0.0, color="0.75", linewidth=1.0)
    ax.scatter(merged["lag_delta"], merged["tolerance_delta"], s=55)
    for row in merged.itertuples():
        ax.annotate(str(row.condition), (row.lag_delta, row.tolerance_delta))
    ax.set_xlabel("Full - Raw-ZOH display lag (ms)")
    ax.set_ylabel("Full - Raw-ZOH valid tracking rate")
    _save(fig, output_dir / "rq2_paired_tradeoff")


def _plot_delay(
    motion: pd.DataFrame,
    audit: pd.DataFrame,
    output_dir: Path,
) -> None:
    """绘制 eligible pre-image 运动—时延残差关联。"""

    if motion.empty or audit.empty:
        return
    accepted = audit[audit["accepted"].fillna(False).astype(bool)][
        ["session_id", "condition", "rq2_trial_id"]
    ]
    motion = motion.merge(
        accepted,
        on=["session_id", "condition", "rq2_trial_id"],
        how="inner",
    )
    if motion.empty:
        return
    definitions = (
        (
            "translation",
            "translation_model_eligible",
            "expected_translation_handle_m",
            "raw_translation_lag_error_handle_m",
            1000.0,
            "mm",
        ),
        (
            "rotation",
            "rotation_model_eligible",
            "expected_rotation_handle_rad",
            "raw_rotation_lag_error_handle_rad",
            180.0 / np.pi,
            "deg",
        ),
    )
    usable = []
    for definition in definitions:
        _, eligible, predicted, observed, _, _ = definition
        if {eligible, predicted, observed}.issubset(motion.columns):
            current = motion[motion[eligible].fillna(False).astype(bool)]
            if not current.empty:
                usable.append(definition)
    if not usable:
        return
    fig, axes = plt.subplots(1, len(usable), figsize=(5.2 * len(usable), 4.3))
    axes = np.atleast_1d(axes)
    for ax, definition in zip(axes, usable):
        channel, eligible, predicted, observed, scale, unit = definition
        current = motion[motion[eligible].fillna(False).astype(bool)].copy()
        x = pd.to_numeric(current[predicted], errors="coerce") * scale
        y = pd.to_numeric(current[observed], errors="coerce") * scale
        valid = np.isfinite(x) & np.isfinite(y)
        ax.scatter(x[valid], y[valid], s=10, alpha=0.35)
        ax.set_xlabel(f"pre-image speed × delay ({unit})")
        ax.set_ylabel(f"signed raw residual ({unit})")
        ax.set_title(channel)
    _save(fig, output_dir / "rq2_delay_association")


def _plot_envelope(envelope: pd.DataFrame, output_dir: Path) -> None:
    """绘制按实测速度分箱的经验运行包络。"""

    if envelope.empty:
        return
    view = envelope[envelope["level"].eq("aggregate")].dropna(
        subset=["speed_median", "within_tolerance_valid_tracking_rate"]
    )
    if view.empty:
        return
    channels = list(view["channel"].drop_duplicates())
    fig, axes = plt.subplots(1, len(channels), figsize=(5.2 * len(channels), 4.3))
    axes = np.atleast_1d(axes)
    for ax, channel in zip(axes, channels):
        channel_rows = view[view["channel"].eq(channel)]
        for label, group in channel_rows.groupby("label", sort=True):
            ordered = group.sort_values("speed_median")
            ax.plot(
                ordered["speed_median"],
                ordered["within_tolerance_valid_tracking_rate"],
                marker="o",
                label=str(label),
            )
        ax.set_ylim(0.0, 1.0)
        ax.set_xlabel(str(channel_rows.iloc[0]["speed_unit"]))
        ax.set_ylabel("within-tolerance valid tracking rate")
        ax.set_title(str(channel))
        ax.legend(loc="best")
    _save(fig, output_dir / "rq2_operating_envelope")


def _save(fig: plt.Figure, stem: Path) -> None:
    """同时保存 PNG 和 PDF。"""

    fig.tight_layout()
    fig.savefig(stem.with_suffix(".png"), dpi=180)
    fig.savefig(stem.with_suffix(".pdf"))
    plt.close(fig)


__all__ = ["write_rq2_plots"]
