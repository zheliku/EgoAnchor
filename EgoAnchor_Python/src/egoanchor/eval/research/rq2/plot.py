"""RQ2 论文结果所需的精简图表导出。"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from egoanchor.eval.metrics import is_pose_value

from .trajectory import reference_valid_mask


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
    """绘制容限内有效率与动态精度诊断概览。"""

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


def _save(
    fig: plt.Figure,
    stem: Path,
    *,
    rect: tuple[float, float, float, float] | None = None,
    tight: bool = True,
) -> None:
    """同时保存 PNG 和 PDF。"""

    if tight:
        fig.tight_layout(rect=rect)
    fig.savefig(stem.with_suffix(".png"), dpi=180)
    fig.savefig(stem.with_suffix(".pdf"))
    plt.close(fig)


def write_rq2_hero_figure(
    output: pd.DataFrame,
    output_dir: Path | str,
    *,
    preliminary: bool = True,
) -> Path | None:
    """导出实时轨迹 hero 图：参考真值 / 完整锚定 / ZOH / 稀疏感知观测的时序对比。

    三面板：(a) 慢速平移 trial 的平移 X 分量，(b) 快速运动 trial 的平移 X 分量，
    (c) 参考线速度–t。一眼对比完整锚定平滑曲线与零阶保持阶梯跳变，并诚实暴露
    完整锚定的相位滞后。单会话数据默认带 _preliminary 标识。
    """

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    slow = _select_trial(output, "slow_translation")
    fast = _select_trial(output, "fast_motion")
    if slow is None and fast is None:
        return None
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 8.4), sharex=False)
    _plot_trajectory_panel(axes[0], slow, title="(a) Slow translation: X component")
    _plot_trajectory_panel(axes[1], fast, title="(b) Fast motion: X component")
    _plot_speed_panel(
        axes[2], slow if slow is not None else fast, title="(c) Reference linear speed"
    )
    if preliminary:
        fig.suptitle(
            "RQ2 realtime trajectory (single-session pilot; not for population inference)",
            color="crimson",
            fontsize=11,
        )
    suffix = "_preliminary" if preliminary else ""
    stem = f"rq2_hero_trajectory{suffix}"
    _save(fig, destination / stem)
    return destination / f"{stem}.pdf"


def _select_trial(output: pd.DataFrame, condition: str) -> pd.DataFrame | None:
    """选出指定 condition 的首个合法 trial（含各变体）。"""

    if output.empty or "rq2_condition" not in output.columns:
        return None
    trial_id = pd.to_numeric(output.get("rq2_trial_id"), errors="coerce")
    subset = output[
        output["rq2_condition"].fillna("none").astype(str).eq(condition)
        & (trial_id > 0)
    ].copy()
    if subset.empty:
        return None
    first_trial = int(pd.to_numeric(subset["rq2_trial_id"], errors="coerce").min())
    return subset[pd.to_numeric(subset["rq2_trial_id"], errors="coerce").eq(first_trial)]


def _component_series(
    frame: pd.DataFrame,
    column: str,
    index: int,
    *,
    mask_column: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """抽取按时间排序的 (t_s, 分量值) 序列，供轨迹面板绘制。"""

    ordered = frame.sort_values("render_mono_ms")
    if mask_column is not None and mask_column in ordered.columns:
        ordered = ordered[ordered[mask_column].fillna(False).astype(bool)]
    times: list[float] = []
    values: list[float] = []
    for _, row in ordered.iterrows():
        vec = row.get(column)
        stamp = row.get("render_mono_ms")
        if is_pose_value(vec) and np.isfinite(stamp):
            times.append(float(stamp) / 1000.0)
            values.append(float(vec[index]))
    return np.asarray(times, dtype=float), np.asarray(values, dtype=float)


def _plot_trajectory_panel(ax, trial: pd.DataFrame | None, *, title: str) -> None:
    """在一个子图上叠加参考真值 / 完整锚定 / ZOH / 稀疏感知观测。"""

    ax.set_title(title, fontsize=10, loc="left")
    ax.set_ylabel("X (m)")
    ax.set_xlabel("t (s)")
    if trial is None or trial.empty:
        ax.text(0.5, 0.5, "no valid trial", ha="center", va="center", transform=ax.transAxes)
        return
    t0 = float(pd.to_numeric(trial["render_mono_ms"], errors="coerce").min()) / 1000.0
    full = trial[trial["label"].astype(str).eq("Full")]
    zoh = trial[trial["label"].astype(str).eq("Raw-ZOH")]
    gt_t, gt_v = _component_series(full, "gt_pos", 0)
    if gt_t.size:
        ax.plot(gt_t - t0, gt_v, color="0.2", linewidth=1.4, label="Reference (GT)")
    full_t, full_v = _component_series(full, "display_pos", 0, mask_column="has_display_pose")
    if full_t.size:
        ax.plot(full_t - t0, full_v, color="tab:blue", linewidth=1.2, label="Full anchoring")
    zoh_t, zoh_v = _component_series(zoh, "display_pos", 0, mask_column="has_display_pose")
    if zoh_t.size:
        ax.plot(
            zoh_t - t0,
            zoh_v,
            color="tab:orange",
            linewidth=1.0,
            linestyle="--",
            drawstyle="steps-post",
            label="Zero-order hold (ZOH)",
        )
    raw_t, raw_v = _component_series(full, "aligned_raw_pos", 0)
    if raw_t.size:
        ax.scatter(
            raw_t - t0,
            raw_v,
            s=14,
            color="tab:green",
            zorder=5,
            label="Spatiotemporally aligned obs.",
        )
    ax.legend(fontsize=7, loc="best")


def _plot_speed_panel(ax, trial: pd.DataFrame | None, *, title: str) -> None:
    """绘制参考线速度–t，作为运动强度背景。"""

    ax.set_title(title, fontsize=10, loc="left")
    ax.set_ylabel("speed (m/s)")
    ax.set_xlabel("t (s)")
    if trial is None or trial.empty:
        ax.text(0.5, 0.5, "no valid trial", ha="center", va="center", transform=ax.transAxes)
        return
    full = trial[trial["label"].astype(str).eq("Full")].sort_values("render_mono_ms")
    if "gt_linear_speed_m_s" not in full.columns or full.empty:
        ax.text(0.5, 0.5, "no speed data", ha="center", va="center", transform=ax.transAxes)
        return
    t0 = float(pd.to_numeric(full["render_mono_ms"], errors="coerce").min()) / 1000.0
    times = pd.to_numeric(full["render_mono_ms"], errors="coerce").to_numpy(dtype=float) / 1000.0
    speed = pd.to_numeric(full["gt_linear_speed_m_s"], errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(times) & np.isfinite(speed)
    if np.any(finite):
        ax.plot(times[finite] - t0, speed[finite], color="tab:purple", linewidth=1.0)


_CONDITION_ORDER = ("slow_translation", "fast_motion", "rotation")
_CONDITION_LABELS = {
    "slow_translation": "Slow\ntranslation",
    "fast_motion": "Fast\nmotion",
    "rotation": "Rotation",
}
_FULL_COLOR = "tab:blue"
_ZOH_COLOR = "tab:orange"
_PLATFORM_COLOR = "0.18"
_OBSERVATION_COLOR = "tab:green"
_ZOOM_DURATION_S = 5.0
_ZOOM_MIN_RUN_S = 6.0


def write_rq2_dynamic_figure(
    hero_output: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    output_dir: Path | str,
    *,
    preliminary: bool = True,
) -> Path | None:
    """导出论文用 RQ2 时间分辨轨迹与描述统计合成图。

    两个上方面板只依据平台参考轨迹选择固定 5 秒窗口，分别展示主平移轴与
    主旋转轴；下方面板报告保持帧比例和与场景匹配的渲染时刻误差。运动—时延
    散点保留为诊断图，不再与 RQ2 主结果争夺版面。
    """

    trial_summary = tables.get("rq2_trial_summary", pd.DataFrame())
    if trial_summary.empty:
        return None
    accepted = trial_summary
    if "audit_accepted" in trial_summary.columns:
        accepted = trial_summary[
            trial_summary["audit_accepted"].fillna(False).astype(bool)
        ]
    if accepted.empty:
        return None

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(11.0, 6.2))
    grid = fig.add_gridspec(
        2,
        2,
        height_ratios=(1.18, 1.0),
        left=0.075,
        right=0.985,
        bottom=0.11,
        top=0.88,
        hspace=0.55,
        wspace=0.28,
    )
    translation_ax = fig.add_subplot(grid[0, 0])
    rotation_ax = fig.add_subplot(grid[0, 1])
    continuity_ax = fig.add_subplot(grid[1, 0])
    error_grid = grid[1, 1].subgridspec(1, 2, width_ratios=(1.65, 1.0), wspace=0.36)
    translation_error_ax = fig.add_subplot(error_grid[0, 0])
    rotation_error_ax = fig.add_subplot(error_grid[0, 1])

    _panel_translation(translation_ax, hero_output, accepted)
    _panel_rotation(rotation_ax, hero_output, accepted)
    _panel_hold_fraction(continuity_ax, accepted)
    _panel_render_error(translation_error_ax, rotation_error_ax, accepted)
    fig.legend(
        handles=_trajectory_legend_handles(),
        loc="upper center",
        bbox_to_anchor=(0.5, 0.97),
        ncol=4,
        frameon=False,
        fontsize=8,
    )

    suffix = "_preliminary" if preliminary else ""
    stem = f"fig_rq2_dynamic{suffix}"
    _save(fig, destination / stem, tight=False)
    return destination / f"{stem}.pdf"


def _ordered_conditions(view: pd.DataFrame) -> list[str]:
    """返回按固定顺序排列且实际存在的 condition。"""

    present = set(view["condition"].astype(str))
    return [c for c in _CONDITION_ORDER if c in present]


def _panel_translation(ax, output: pd.DataFrame, accepted: pd.DataFrame) -> None:
    """绘制 GT-only 规则选出的快速平移 5 秒主轴轨迹。"""

    ax.set_title("(A) Fast translation, fixed 5 s zoom", fontsize=10, loc="left")
    ax.set_xlabel("time in window (s)")
    ax.set_ylabel("principal-axis position (cm)")
    trial = _select_exemplar_trial(output, accepted, "fast_motion")
    if trial is None:
        trial = _select_exemplar_trial(output, accepted, "slow_translation")
    zoom = _active_zoom_window(trial)
    if zoom is None:
        _empty_panel(ax, "no eligible 5 s active run")
        return
    window, start_ms = zoom
    full = window[window["label"].astype(str).eq("Full")]
    zoh = window[window["label"].astype(str).eq("Raw-ZOH")]
    gt_time, gt_position = _pose_series(full, "gt_pos", expected_length=3)
    if len(gt_position) < 2:
        _empty_panel(ax, "no platform reference")
        return
    axis = _principal_axis(gt_position)
    origin = gt_position[0]
    _plot_projected_positions(
        ax,
        gt_time,
        gt_position,
        start_ms,
        origin,
        axis,
        color=_PLATFORM_COLOR,
        linewidth=1.55,
    )
    for frame, color, drawstyle in (
        (full, _FULL_COLOR, "default"),
        (zoh, _ZOH_COLOR, "steps-post"),
    ):
        times, positions = _pose_series(
            frame,
            "display_pos",
            expected_length=3,
            mask_column="has_display_pose",
        )
        _plot_projected_positions(
            ax,
            times,
            positions,
            start_ms,
            origin,
            axis,
            color=color,
            linewidth=1.25,
            drawstyle=drawstyle,
        )
    raw_time, raw_position = _pose_series(
        full,
        "aligned_raw_pos",
        expected_length=3,
        mask_column="has_aligned_raw",
        dedupe_source=True,
    )
    if len(raw_position):
        raw_value = (raw_position - origin) @ axis * 100.0
        ax.scatter(
            raw_time - start_ms / 1000.0,
            raw_value,
            s=16,
            facecolors="white",
            edgecolors=_OBSERVATION_COLOR,
            linewidths=0.8,
            zorder=5,
        )
    _finish_timeline_axis(ax)


def _panel_rotation(ax, output: pd.DataFrame, accepted: pd.DataFrame) -> None:
    """绘制 GT-only 规则选出的旋转 5 秒主轴累计角轨迹。"""

    ax.set_title("(B) Rotation, fixed 5 s zoom", fontsize=10, loc="left")
    ax.set_xlabel("time in window (s)")
    ax.set_ylabel("signed principal-axis angle (deg)")
    trial = _select_exemplar_trial(output, accepted, "rotation")
    zoom = _active_zoom_window(trial)
    if zoom is None:
        _empty_panel(ax, "no eligible 5 s active run")
        return
    window, start_ms = zoom
    full = window[window["label"].astype(str).eq("Full")]
    zoh = window[window["label"].astype(str).eq("Raw-ZOH")]
    gt_time, gt_rotation = _pose_series(full, "gt_rot", expected_length=4)
    if len(gt_rotation) < 2:
        _empty_panel(ax, "no platform reference")
        return
    axis = _principal_rotation_axis(gt_rotation)
    reference = Rotation.from_quat(gt_rotation[0])
    _plot_signed_rotations(
        ax,
        gt_time,
        gt_rotation,
        start_ms,
        reference,
        axis,
        color=_PLATFORM_COLOR,
        linewidth=1.55,
    )
    for frame, color, drawstyle in (
        (full, _FULL_COLOR, "default"),
        (zoh, _ZOH_COLOR, "steps-post"),
    ):
        times, rotations = _pose_series(
            frame,
            "display_rot",
            expected_length=4,
            mask_column="has_display_pose",
        )
        _plot_signed_rotations(
            ax,
            times,
            rotations,
            start_ms,
            reference,
            axis,
            color=color,
            linewidth=1.25,
            drawstyle=drawstyle,
        )
    raw_time, raw_rotation = _pose_series(
        full,
        "aligned_raw_rot",
        expected_length=4,
        mask_column="has_aligned_raw",
        dedupe_source=True,
    )
    raw_angle = _signed_rotation_values(raw_rotation, reference, axis)
    if len(raw_angle):
        ax.scatter(
            raw_time - start_ms / 1000.0,
            raw_angle,
            s=16,
            facecolors="white",
            edgecolors=_OBSERVATION_COLOR,
            linewidths=0.8,
            zorder=5,
        )
    _finish_timeline_axis(ax)


def _panel_hold_fraction(ax, view: pd.DataFrame) -> None:
    """以 paired dots 报告三类运动的保持帧比例。"""

    conditions = _ordered_conditions(view)
    ax.set_title("(C) Held display frames", fontsize=10, loc="left")
    ax.set_ylabel("held adjacent frames (%)")
    if not conditions:
        _empty_panel(ax, "no accepted trials")
        return
    for position, condition in enumerate(conditions):
        rows = view[view["condition"].astype(str).eq(condition)]
        pairs = _paired_metric_rows(rows, "display_hold_fraction")
        for full_value, zoh_value in pairs:
            ax.plot(
                [position - 0.10, position + 0.10],
                [full_value * 100.0, zoh_value * 100.0],
                color="0.75",
                linewidth=0.8,
                zorder=1,
            )
        full = pd.to_numeric(
            rows.loc[rows["label"].astype(str).eq("Full"), "display_hold_fraction"],
            errors="coerce",
        ).dropna()
        zoh = pd.to_numeric(
            rows.loc[rows["label"].astype(str).eq("Raw-ZOH"), "display_hold_fraction"],
            errors="coerce",
        ).dropna()
        ax.scatter(
            np.full(len(full), position - 0.10),
            full * 100.0,
            s=20,
            color=_FULL_COLOR,
            alpha=0.35,
        )
        ax.scatter(
            np.full(len(zoh), position + 0.10),
            zoh * 100.0,
            s=20,
            marker="s",
            color=_ZOH_COLOR,
            alpha=0.35,
        )
        if len(full):
            ax.scatter(position - 0.10, full.mean() * 100.0, s=42, color=_FULL_COLOR)
        if len(zoh):
            ax.scatter(
                position + 0.10,
                zoh.mean() * 100.0,
                s=42,
                marker="s",
                color=_ZOH_COLOR,
            )
    ax.set_xticks(range(len(conditions)), [_CONDITION_LABELS[c] for c in conditions])
    ax.set_ylim(0.0, 100.0)
    ax.grid(axis="y", alpha=0.18)


def _panel_render_error(translation_ax, rotation_ax, view: pd.DataFrame) -> None:
    """分别以毫米和角度报告与运动类型匹配的 P50/P95 误差。"""

    _plot_error_axis(
        translation_ax,
        view,
        conditions=("slow_translation", "fast_motion"),
        median_column="display_translation_median_m",
        p95_column="display_translation_p95_m",
        scale=1000.0,
        threshold=50.0,
        ylabel="translation (mm)",
        title="(D) Render-time error\nTranslation",
    )
    _plot_error_axis(
        rotation_ax,
        view,
        conditions=("rotation",),
        median_column="display_rotation_median_deg",
        p95_column="display_rotation_p95_deg",
        scale=1.0,
        threshold=10.0,
        ylabel="rotation (deg)",
        title="Rotation",
    )


def _plot_error_axis(
    ax,
    view: pd.DataFrame,
    *,
    conditions: tuple[str, ...],
    median_column: str,
    p95_column: str,
    scale: float,
    threshold: float,
    ylabel: str,
    title: str,
) -> None:
    """画出 trial 均值的中位误差点及通向 P95 的描述性线段。"""

    available = [condition for condition in conditions if condition in set(view["condition"])]
    ax.set_title(title, fontsize=9, loc="left")
    ax.set_ylabel(ylabel, fontsize=8)
    if not available:
        _empty_panel(ax, "no data")
        return
    offsets = {"Full": -0.10, "Raw-ZOH": 0.10}
    markers = {"Full": "o", "Raw-ZOH": "s"}
    colors = {"Full": _FULL_COLOR, "Raw-ZOH": _ZOH_COLOR}
    for position, condition in enumerate(available):
        for label in ("Full", "Raw-ZOH"):
            rows = view[
                view["condition"].astype(str).eq(condition)
                & view["label"].astype(str).eq(label)
            ]
            median = _mean_or_nan(rows, median_column) * scale
            p95 = _mean_or_nan(rows, p95_column) * scale
            if not np.isfinite(median) or not np.isfinite(p95):
                continue
            x = position + offsets[label]
            ax.vlines(x, median, p95, color=colors[label], linewidth=1.5, alpha=0.75)
            ax.scatter(x, median, s=38, marker=markers[label], color=colors[label], zorder=3)
            ax.scatter(
                x,
                p95,
                s=28,
                marker=markers[label],
                facecolors="white",
                edgecolors=colors[label],
                linewidths=1.0,
                zorder=3,
            )
    ax.axhline(threshold, color="0.5", linewidth=0.9, linestyle=":")
    ax.set_xticks(range(len(available)), [_CONDITION_LABELS[c] for c in available])
    ax.set_ylim(bottom=0.0)
    ax.grid(axis="y", alpha=0.18)


def _select_exemplar_trial(
    output: pd.DataFrame,
    accepted: pd.DataFrame,
    condition: str,
) -> pd.DataFrame | None:
    """仅依平台参考速度选择最接近该场景 trial 中位速度的代表试次。"""

    if output.empty or "rq2_condition" not in output.columns:
        return None
    trial_ids = pd.to_numeric(output.get("rq2_trial_id"), errors="coerce")
    subset = output[
        output["rq2_condition"].fillna("none").astype(str).eq(condition)
        & (trial_ids > 0)
    ].copy()
    if subset.empty:
        return None
    if not accepted.empty and {"condition", "rq2_trial_id"}.issubset(accepted.columns):
        allowed = set(
            pd.to_numeric(
                accepted.loc[
                    accepted["condition"].astype(str).eq(condition), "rq2_trial_id"
                ],
                errors="coerce",
            ).dropna().astype(int)
        )
        if allowed:
            subset = subset[
                pd.to_numeric(subset["rq2_trial_id"], errors="coerce").isin(allowed)
            ]
    speed_column = (
        "gt_angular_speed_smooth_rad_s"
        if condition == "rotation"
        else "gt_linear_speed_smooth_m_s"
    )
    candidates: list[tuple[int, float]] = []
    for trial_id, group in subset.groupby("rq2_trial_id", sort=True):
        full = group[group["label"].astype(str).eq("Full")]
        if speed_column not in full.columns:
            continue
        active = (
            full["active_motion"].fillna(False).astype(bool)
            if "active_motion" in full.columns
            else pd.Series(True, index=full.index)
        )
        speed = pd.to_numeric(full[speed_column], errors="coerce")
        values = speed[active & speed.notna()]
        if len(values):
            candidates.append((int(trial_id), float(values.median())))
    if candidates:
        target = float(np.median([speed for _, speed in candidates]))
        selected = min(candidates, key=lambda item: (abs(item[1] - target), item[0]))[0]
    else:
        selected = int(pd.to_numeric(subset["rq2_trial_id"], errors="coerce").min())
    return subset[
        pd.to_numeric(subset["rq2_trial_id"], errors="coerce").eq(selected)
    ].copy()


def _active_zoom_window(
    trial: pd.DataFrame | None,
) -> tuple[pd.DataFrame, float] | None:
    """从最长平台参考有效 active run 中截取正中央固定 5 秒。"""

    if trial is None or trial.empty:
        return None
    full = (
        trial[trial["label"].astype(str).eq("Full")]
        .sort_values("render_mono_ms")
        .reset_index(drop=True)
    )
    if full.empty:
        return None
    active = (
        full["active_motion"].fillna(False).astype(bool).reset_index(drop=True)
        if "active_motion" in full.columns
        else pd.Series(True, index=range(len(full)), dtype=bool)
    )
    reference = reference_valid_mask(full).reset_index(drop=True)
    valid = active & reference
    starts = valid & ~valid.shift(fill_value=False)
    run_ids = starts.cumsum()
    runs: list[tuple[float, float]] = []
    times = pd.to_numeric(full["render_mono_ms"], errors="coerce").reset_index(drop=True)
    for _, indices in full[valid.to_numpy(dtype=bool)].groupby(
        run_ids[valid].to_numpy(), sort=True
    ).groups.items():
        run_times = times.iloc[list(indices)].dropna()
        if len(run_times) >= 2:
            runs.append((float(run_times.iloc[0]), float(run_times.iloc[-1])))
    if not runs:
        return None
    run_start, run_end = min(runs, key=lambda run: (-(run[1] - run[0]), run[0]))
    if run_end - run_start < _ZOOM_MIN_RUN_S * 1000.0:
        return None
    window_ms = _ZOOM_DURATION_S * 1000.0
    start_ms = (run_start + run_end - window_ms) / 2.0
    end_ms = start_ms + window_ms
    trial_time = pd.to_numeric(trial["render_mono_ms"], errors="coerce")
    window = trial[trial_time.between(start_ms, end_ms, inclusive="both")].copy()
    return window, start_ms


def _pose_series(
    frame: pd.DataFrame,
    column: str,
    *,
    expected_length: int,
    mask_column: str | None = None,
    dedupe_source: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """抽取按渲染时刻排序的有效位置或四元数序列。"""

    ordered = frame.sort_values("render_mono_ms", kind="stable")
    if mask_column is not None and mask_column in ordered.columns:
        ordered = ordered[ordered[mask_column].fillna(False).astype(bool)]
    if dedupe_source and "source_frame_id" in ordered.columns:
        ordered = ordered.drop_duplicates("source_frame_id", keep="first")
    times: list[float] = []
    poses: list[list[float]] = []
    for _, row in ordered.iterrows():
        pose = row.get(column)
        stamp = row.get("render_mono_ms")
        if (
            is_pose_value(pose)
            and len(pose) == expected_length
            and stamp is not None
            and np.isfinite(float(stamp))
        ):
            times.append(float(stamp) / 1000.0)
            poses.append([float(value) for value in pose])
    shape = (0, expected_length)
    return np.asarray(times, dtype=float), np.asarray(poses, dtype=float).reshape(
        (-1, expected_length) if poses else shape
    )


def _principal_axis(positions: np.ndarray) -> np.ndarray:
    """从平台参考位置求主运动轴，并固定符号以保证复现。"""

    centered = positions - np.mean(positions, axis=0)
    if len(centered) < 2 or float(np.linalg.norm(centered)) <= 1e-12:
        return np.array([1.0, 0.0, 0.0])
    _, _, vectors = np.linalg.svd(centered, full_matrices=False)
    return _canonical_axis(vectors[0])


def _principal_rotation_axis(rotations: np.ndarray) -> np.ndarray:
    """从平台参考相邻旋转增量求主旋转轴。"""

    orientation = Rotation.from_quat(rotations)
    increments = (orientation[1:] * orientation[:-1].inv()).as_rotvec()
    usable = increments[np.linalg.norm(increments, axis=1) > 1e-9]
    if len(usable) == 0:
        return np.array([0.0, 0.0, 1.0])
    _, _, vectors = np.linalg.svd(usable, full_matrices=False)
    return _canonical_axis(vectors[0])


def _canonical_axis(axis: np.ndarray) -> np.ndarray:
    """把单位轴的最大绝对分量固定为正，消除 SVD 符号歧义。"""

    unit = np.asarray(axis, dtype=float)
    norm = float(np.linalg.norm(unit))
    if norm <= 1e-12:
        return np.array([1.0, 0.0, 0.0])
    unit = unit / norm
    pivot = int(np.argmax(np.abs(unit)))
    return -unit if unit[pivot] < 0.0 else unit


def _plot_projected_positions(
    ax,
    times: np.ndarray,
    positions: np.ndarray,
    start_ms: float,
    origin: np.ndarray,
    axis: np.ndarray,
    **style,
) -> None:
    """把世界位置投影到平台参考主轴后绘图。"""

    if len(positions) == 0:
        return
    values = (positions - origin) @ axis * 100.0
    ax.plot(times - start_ms / 1000.0, values, **style)


def _plot_signed_rotations(
    ax,
    times: np.ndarray,
    rotations: np.ndarray,
    start_ms: float,
    reference: Rotation,
    axis: np.ndarray,
    **style,
) -> None:
    """把姿态序列投影为主轴上的累计有符号旋转角后绘图。"""

    values = _signed_rotation_values(rotations, reference, axis)
    if len(values):
        ax.plot(times - start_ms / 1000.0, values, **style)


def _signed_rotation_values(
    rotations: np.ndarray,
    reference: Rotation,
    axis: np.ndarray,
) -> np.ndarray:
    """计算相对同一参考姿态的主轴累计有符号角，单位度。"""

    if len(rotations) == 0:
        return np.asarray([], dtype=float)
    orientation = Rotation.from_quat(rotations)
    initial = float(np.dot((orientation[0] * reference.inv()).as_rotvec(), axis))
    if len(rotations) == 1:
        return np.asarray([np.degrees(initial)], dtype=float)
    increments = (orientation[1:] * orientation[:-1].inv()).as_rotvec() @ axis
    return np.degrees(initial + np.concatenate(([0.0], np.cumsum(increments))))


def _paired_metric_rows(rows: pd.DataFrame, column: str) -> list[tuple[float, float]]:
    """按 session × trial 配对读取 Full 与 Raw-ZOH 指标。"""

    keys = [key for key in ("session_id", "rq2_trial_id") if key in rows.columns]
    if not keys:
        full = _mean_or_nan(rows[rows["label"].astype(str).eq("Full")], column)
        zoh = _mean_or_nan(rows[rows["label"].astype(str).eq("Raw-ZOH")], column)
        return [(full, zoh)] if np.isfinite(full) and np.isfinite(zoh) else []
    pairs: list[tuple[float, float]] = []
    for _, group in rows.groupby(keys, sort=True):
        full = _mean_or_nan(group[group["label"].astype(str).eq("Full")], column)
        zoh = _mean_or_nan(group[group["label"].astype(str).eq("Raw-ZOH")], column)
        if np.isfinite(full) and np.isfinite(zoh):
            pairs.append((full, zoh))
    return pairs


def _finish_timeline_axis(ax) -> None:
    """统一时间分辨轨迹面板的范围与网格。"""

    ax.set_xlim(0.0, _ZOOM_DURATION_S)
    ax.grid(axis="y", alpha=0.18)


def _empty_panel(ax, message: str) -> None:
    """在无合格数据时保持固定 panel 尺寸并给出原因。"""

    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)


def _trajectory_legend_handles() -> list[Line2D]:
    """返回论文合成图共享图例。"""

    return [
        Line2D([0], [0], color=_PLATFORM_COLOR, linewidth=1.55, label="Platform reference"),
        Line2D([0], [0], color=_FULL_COLOR, linewidth=1.25, label="Full"),
        Line2D(
            [0],
            [0],
            color=_ZOH_COLOR,
            linewidth=1.25,
            drawstyle="steps-post",
            label="Raw-ZOH",
        ),
        Line2D(
            [0],
            [0],
            color=_OBSERVATION_COLOR,
            marker="o",
            markerfacecolor="white",
            linestyle="none",
            label="Aligned obs. (first render)",
        ),
    ]


def _mean_or_nan(rows: pd.DataFrame, column: str) -> float:
    """安全取列均值；缺列或空表返回 NaN。"""

    if rows.empty or column not in rows.columns:
        return float("nan")
    values = pd.to_numeric(rows[column], errors="coerce")
    return float(values.mean()) if values.notna().any() else float("nan")


__all__ = ["write_rq2_dynamic_figure", "write_rq2_hero_figure", "write_rq2_plots"]
