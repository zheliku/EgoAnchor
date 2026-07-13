"""RQ2 论文用 XYZ-t 平移与旋转时间线。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.ticker import FormatStrFormatter

from egoanchor.eval.metrics import is_pose_value

from .contract import RQ2_CONDITIONS, RQ2Config
from .trajectory import (
    reference_valid_mask,
    unique_trial_frames,
    world_rotation_vectors_from_reference,
)


POSITION_STEM = "fig_rq2_position_timeline"
ROTATION_STEM = "fig_rq2_rotation_timeline"
TIMELINE_FILENAMES = tuple(
    f"{stem}.{suffix}"
    for stem in (POSITION_STEM, ROTATION_STEM)
    for suffix in ("pdf", "png")
)

WINDOW_COLUMNS = [
    "session_id",
    "condition",
    "rq2_trial_id",
    "window_start_unity_frame",
    "window_end_unity_frame",
    "window_frame_span",
    "render_tick_count",
    "window_start_mono_ms",
    "window_end_mono_ms",
    "reference_speed_median",
    "reference_speed_unit",
]

COLORS = {
    "Reference": "#222222",
    "Full": "#0072B2",
    "ZOH": "#D55E00",
}


@dataclass(frozen=True)
class TimelineWindow:
    """由平台参考轨迹唯一决定的论文帧窗口。"""

    session_id: str
    condition: str
    trial_id: int
    start_ms: float
    end_ms: float
    start_unity_frame: int
    end_unity_frame: int
    reference_speed_median: float
    reference_speed_unit: str
    frames: pd.DataFrame


def write_rq2_timelines(
    output: pd.DataFrame,
    output_dir: Path | str,
    *,
    config: RQ2Config | None = None,
) -> pd.DataFrame:
    """输出两张三行共享横轴的时间线，并返回可复现选窗元数据。"""

    settings = config or RQ2Config()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    _remove_existing_timelines(destination)
    windows: list[TimelineWindow] = []
    for condition in RQ2_CONDITIONS:
        window = _select_window(output, condition, settings.zoom_frame_count)
        if window is None:
            continue
        windows.append(window)
        if condition == "translation":
            _plot_position(window, destination / POSITION_STEM)
        else:
            _plot_rotation(window, destination / ROTATION_STEM)
    return pd.DataFrame.from_records(
        [_window_record(window) for window in windows],
        columns=WINDOW_COLUMNS,
    )


def _select_window(
    output: pd.DataFrame,
    condition: str,
    frame_count: int,
) -> TimelineWindow | None:
    """按试次中位参考速度选择最长连续段中央的固定帧窗口。"""

    if output.empty or frame_count <= 0:
        return None
    task = output[
        output["rq2_condition"].astype(str).eq(condition)
        & output["label"].astype(str).eq("Full")
    ]
    speed_column = (
        "gt_angular_speed_smooth_deg_s"
        if condition == "rotation"
        else "gt_linear_speed_smooth_m_s"
    )
    speed_unit = "deg/s" if condition == "rotation" else "m/s"
    candidates: list[tuple[str, int, float, pd.DataFrame]] = []
    for (session_id, trial_id), group in task.groupby(
        ["session_id", "rq2_trial_id"], sort=True
    ):
        frames = unique_trial_frames(group)
        included = frames["analysis_motion"].fillna(False).astype(bool)
        speed = pd.to_numeric(frames.loc[included, speed_column], errors="coerce")
        speed = speed[np.isfinite(speed)]
        if not included.any() or speed.empty:
            continue
        candidates.append((str(session_id), int(trial_id), float(speed.median()), frames))
    if not candidates:
        return None

    task_included = task["analysis_motion"].fillna(False).astype(bool)
    task_speed = pd.to_numeric(task.loc[task_included, speed_column], errors="coerce")
    task_speed = task_speed[np.isfinite(task_speed)]
    task_median = float(task_speed.median())
    session_id, trial_id, _, frames = min(
        candidates,
        key=lambda value: (abs(value[2] - task_median), value[0], value[1]),
    )
    run = _longest_analysis_run(frames)
    if run.empty:
        return None
    if len(run) > frame_count:
        offset = (len(run) - frame_count) // 2
        selected_frames = run.iloc[offset : offset + frame_count].copy()
    else:
        selected_frames = run.copy()

    key = "tick_index" if "tick_index" in selected_frames.columns else "render_unity_frame"
    selected_keys = set(selected_frames[key].tolist())
    all_variants = output[
        output["session_id"].astype(str).eq(session_id)
        & output["rq2_condition"].astype(str).eq(condition)
        & pd.to_numeric(output["rq2_trial_id"], errors="coerce").eq(trial_id)
        & output[key].isin(selected_keys)
    ].copy()
    start_ms = float(pd.to_numeric(selected_frames["render_mono_ms"], errors="coerce").min())
    end_ms = float(pd.to_numeric(selected_frames["render_mono_ms"], errors="coerce").max())
    unity_frames = pd.to_numeric(selected_frames["render_unity_frame"], errors="coerce")
    if not np.isfinite(unity_frames).all():
        return None
    speed = pd.to_numeric(selected_frames[speed_column], errors="coerce")
    speed = speed[np.isfinite(speed)]
    return TimelineWindow(
        session_id=session_id,
        condition=condition,
        trial_id=trial_id,
        start_ms=start_ms,
        end_ms=end_ms,
        start_unity_frame=int(unity_frames.min()),
        end_unity_frame=int(unity_frames.max()),
        reference_speed_median=float(speed.median()),
        reference_speed_unit=speed_unit,
        frames=all_variants,
    )


def _longest_analysis_run(frames: pd.DataFrame) -> pd.DataFrame:
    """返回最长的连续纳入帧段。"""

    if frames.empty:
        return frames.iloc[0:0].copy()
    work = frames.sort_values("render_mono_ms", kind="stable").reset_index(drop=True)
    included = work["analysis_motion"].fillna(False).astype(bool).to_numpy()
    times = pd.to_numeric(work["render_mono_ms"], errors="coerce").to_numpy(dtype=float)
    intervals = np.diff(times)
    positive = intervals[np.isfinite(intervals) & (intervals > 0.0)]
    maximum_gap = max(100.0, 2.5 * float(np.median(positive))) if len(positive) else 100.0
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(work):
        if not included[index] or not np.isfinite(times[index]):
            index += 1
            continue
        start = index
        while (
            index + 1 < len(work)
            and included[index + 1]
            and np.isfinite(times[index + 1])
            and 0.0 < times[index + 1] - times[index] <= maximum_gap
        ):
            index += 1
        runs.append((start, index + 1))
        index += 1
    if not runs:
        return work.iloc[0:0].copy()
    start, end = max(runs, key=lambda value: (value[1] - value[0], -value[0]))
    return work.iloc[start:end].copy()


def _plot_position(window: TimelineWindow, stem: Path) -> None:
    """绘制相对共同平台参考原点的世界系 X/Y/Z 位移。"""

    reference = _reference_rows(window.frames)
    if reference.empty:
        return
    origin = np.asarray(reference.iloc[0]["gt_pos"], dtype=float)
    reference_values = np.vstack(reference["gt_pos"].to_numpy()) - origin
    series = {
        "Reference": (_relative_seconds(reference, window.start_ms), 100.0 * reference_values),
    }
    for label in ("Full", "ZOH"):
        rows = _display_rows(window.frames, label)
        values = np.vstack(rows["display_pos"].to_numpy()) - origin if not rows.empty else np.empty((0, 3))
        series[label] = (_relative_seconds(rows, window.start_ms), 100.0 * values)
    _draw_xyz(
        series,
        stem,
        unit="cm",
        duration_s=(window.end_ms - window.start_ms) / 1000.0,
        start_frame=window.start_unity_frame,
        end_frame=window.end_unity_frame,
    )


def _plot_rotation(window: TimelineWindow, stem: Path) -> None:
    """绘制相对共同起点的世界系 SO(3) 对数向量 X/Y/Z 分量。"""

    reference = _reference_rows(window.frames)
    if reference.empty:
        return
    common_reference = np.asarray(reference.iloc[0]["gt_rot"], dtype=float)
    series = {
        "Reference": (
            _relative_seconds(reference, window.start_ms),
            np.rad2deg(
                world_rotation_vectors_from_reference(
                    common_reference, np.vstack(reference["gt_rot"].to_numpy())
                )
            ),
        )
    }
    for label in ("Full", "ZOH"):
        rows = _display_rows(window.frames, label)
        values = (
            np.rad2deg(
                world_rotation_vectors_from_reference(
                    common_reference, np.vstack(rows["display_rot"].to_numpy())
                )
            )
            if not rows.empty
            else np.empty((0, 3))
        )
        series[label] = (_relative_seconds(rows, window.start_ms), values)
    _draw_xyz(
        series,
        stem,
        unit="deg",
        duration_s=(window.end_ms - window.start_ms) / 1000.0,
        start_frame=window.start_unity_frame,
        end_frame=window.end_unity_frame,
    )


def _draw_xyz(
    series: dict[str, tuple[np.ndarray, np.ndarray]],
    stem: Path,
    *,
    unit: str,
    duration_s: float,
    start_frame: int,
    end_frame: int,
) -> None:
    """用统一紧凑样式绘制三行共享时间轴的世界系分量。"""

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.size": 8.0,
            "axes.linewidth": 0.7,
            "xtick.major.width": 0.7,
            "ytick.major.width": 0.7,
        }
    )
    fig, axes = plt.subplots(3, 1, figsize=(3.45, 2.75), sharex=True)
    for component, axis in enumerate(axes):
        for label in ("Reference", "Full", "ZOH"):
            time_s, values = series[label]
            if len(time_s) == 0:
                continue
            axis.plot(
                time_s,
                values[:, component],
                color=COLORS[label],
                linewidth=1.15 if label == "Reference" else 1.0,
                drawstyle="steps-post" if label == "ZOH" else "default",
                zorder=3 if label == "Reference" else 2,
            )
        axis.set_ylabel(f"{'XYZ'[component]} ({unit})")
        axis.grid(True, color="#D9D9D9", linewidth=0.45, alpha=0.8)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_xlim(0, max(duration_s, 1e-6))
        axis.tick_params(labelsize=7.0, length=2.5)
    axes[-1].set_xlabel(f"Time (s) | Unity frames {start_frame}-{end_frame}")
    axes[-1].set_xticks(np.linspace(0.0, max(duration_s, 1e-6), 4))
    axes[-1].xaxis.set_major_formatter(FormatStrFormatter("%.1f"))
    fig.legend(
        handles=_legend_handles(),
        loc="upper center",
        ncol=3,
        frameon=False,
        bbox_to_anchor=(0.5, 0.995),
        handlelength=2.2,
        columnspacing=1.1,
    )
    fig.align_ylabels(axes)
    fig.subplots_adjust(left=0.20, right=0.98, bottom=0.16, top=0.88, hspace=0.08)
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(stem.with_suffix(".png"), dpi=300, bbox_inches="tight")
    plt.close(fig)


def _reference_rows(frames: pd.DataFrame) -> pd.DataFrame:
    """从 Full 行提取每个渲染帧唯一且有效的平台参考 pose。"""

    rows = frames[frames["label"].astype(str).eq("Full")].copy()
    rows = rows[
        reference_valid_mask(rows)
        & rows["gt_pos"].map(is_pose_value)
        & rows["gt_rot"].map(is_pose_value)
    ]
    return rows.sort_values("render_unity_frame", kind="stable").drop_duplicates("render_unity_frame")


def _display_rows(frames: pd.DataFrame, label: str) -> pd.DataFrame:
    """提取一个系统配置的有效显示 pose。"""

    rows = frames[frames["label"].astype(str).eq(label)].copy()
    rows = rows[
        rows["has_display_pose"].fillna(False).astype(bool)
        & rows["display_pos"].map(is_pose_value)
        & rows["display_rot"].map(is_pose_value)
    ]
    return rows.sort_values("render_unity_frame", kind="stable").drop_duplicates("render_unity_frame")


def _relative_seconds(rows: pd.DataFrame, start_ms: float) -> np.ndarray:
    """把真实渲染时间戳转换为窗口内相对秒。"""

    if rows.empty:
        return np.empty(0, dtype=float)
    times = pd.to_numeric(rows["render_mono_ms"], errors="coerce").to_numpy(dtype=float)
    return (times - float(start_ms)) / 1000.0


def _window_record(window: TimelineWindow) -> dict[str, object]:
    """把选窗信息转换为 CSV 记录。"""

    return {
        "session_id": window.session_id,
        "condition": window.condition,
        "rq2_trial_id": window.trial_id,
        "window_start_unity_frame": window.start_unity_frame,
        "window_end_unity_frame": window.end_unity_frame,
        "window_frame_span": window.end_unity_frame - window.start_unity_frame,
        "render_tick_count": int(len(_reference_rows(window.frames))),
        "window_start_mono_ms": window.start_ms,
        "window_end_mono_ms": window.end_ms,
        "reference_speed_median": window.reference_speed_median,
        "reference_speed_unit": window.reference_speed_unit,
    }


def _legend_handles() -> list[Line2D]:
    """返回三条轨迹的稳定图例。"""

    return [
        Line2D([0], [0], color=COLORS["Reference"], linewidth=1.15, label="Platform ref."),
        Line2D([0], [0], color=COLORS["Full"], linewidth=1.0, label="Full"),
        Line2D(
            [0],
            [0],
            color=COLORS["ZOH"],
            linewidth=1.0,
            drawstyle="steps-post",
            label="ZOH",
        ),
    ]


def _remove_existing_timelines(directory: Path) -> None:
    """在本次绘图前清除旧产物，拒收时不会残留上一次图片。"""

    for filename in TIMELINE_FILENAMES:
        path = directory / filename
        if path.is_file():
            path.unlink()


__all__ = [
    "TIMELINE_FILENAMES",
    "WINDOW_COLUMNS",
    "write_rq2_timelines",
]
