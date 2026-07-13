"""RQ1 静止锚定的 XYZ-帧论文图。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from scipy.spatial.transform import Rotation

from egoanchor.eval.metrics import is_pose_value


_REPO_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_FIGS_DIR = _REPO_ROOT / "2026-EgoAnchor-Typst" / "figs" / "rq1"
STATIC_TIMELINE_FRAME_COUNT = 180

POSITION_STEM = "fig_rq1_position_timeline"
ROTATION_STEM = "fig_rq1_rotation_timeline"
TIMELINE_FILENAMES = tuple(
    f"{stem}.{suffix}"
    for stem in (POSITION_STEM, ROTATION_STEM)
    for suffix in ("pdf", "png")
)
WINDOW_COLUMNS = [
    "condition",
    "selection_rule",
    "window_start_unity_frame",
    "window_end_unity_frame",
    "window_frame_span",
    "render_tick_count",
    "window_start_mono_ms",
    "window_end_mono_ms",
]

COLORS = {
    "Reference": "#222222",
    "Full": "#0072B2",
    "No-StaticLock": "#D55E00",
}


@dataclass(frozen=True)
class StaticWindow:
    """不依赖误差大小选择的静止锁定帧窗口。"""

    start_frame: int
    end_frame: int
    start_ms: float
    end_ms: float
    frames: pd.DataFrame


def write_rq1_timelines(
    output: pd.DataFrame,
    output_dir: Path | str,
    *,
    frame_count: int = STATIC_TIMELINE_FRAME_COUNT,
) -> pd.DataFrame:
    """绘制静止位置/旋转 XYZ-帧图，并返回选窗元数据。"""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    _remove_existing_timelines(destination)
    window = _select_static_window(output, frame_count)
    if window is None:
        return pd.DataFrame(columns=WINDOW_COLUMNS)
    _plot_position(window, destination / POSITION_STEM)
    _plot_rotation(window, destination / ROTATION_STEM)
    return pd.DataFrame.from_records(
        [
            {
                "condition": "static_observation",
                "selection_rule": "first_continuous_full_locked_valid_run",
                "window_start_unity_frame": window.start_frame,
                "window_end_unity_frame": window.end_frame,
                "window_frame_span": window.end_frame - window.start_frame,
                "render_tick_count": int(len(_reference_rows(window.frames))),
                "window_start_mono_ms": window.start_ms,
                "window_end_mono_ms": window.end_ms,
            }
        ],
        columns=WINDOW_COLUMNS,
    )


def _select_static_window(output: pd.DataFrame, frame_count: int) -> StaticWindow | None:
    """取首个 Full 已锁定且两变体与参考均有效的连续固定帧段。"""

    if output.empty or frame_count <= 0:
        return None
    static = output[output["rq1_metric"].astype(str).eq("static_observation")].copy()
    if static.empty:
        return None
    full = static[static["label"].astype(str).eq("Full")].copy()
    full = full.sort_values("render_unity_frame", kind="stable").drop_duplicates(
        "render_unity_frame"
    )
    other = static[static["label"].astype(str).eq("No-StaticLock")].copy()
    other_valid = set(
        pd.to_numeric(
            other.loc[_display_valid_mask(other), "render_unity_frame"],
            errors="coerce",
        ).dropna().astype(int)
    )
    full_frames = pd.to_numeric(full["render_unity_frame"], errors="coerce")
    eligible = (
        full["latest_static_locked"].fillna(False).astype(bool)
        & _reference_valid_mask(full)
        & _display_valid_mask(full)
        & full_frames.map(lambda value: int(value) in other_valid if np.isfinite(value) else False)
    ).to_numpy(dtype=bool)
    unity_frames = full_frames.to_numpy(dtype=float)
    times = pd.to_numeric(full["render_mono_ms"], errors="coerce").to_numpy(dtype=float)
    index = 0
    while index < len(full):
        if not eligible[index] or not np.isfinite(unity_frames[index]):
            index += 1
            continue
        start = index
        while (
            index + 1 < len(full)
            and eligible[index + 1]
            and unity_frames[index + 1] == unity_frames[index] + 1
            and np.isfinite(times[index + 1])
            and times[index + 1] > times[index]
        ):
            index += 1
        if index + 1 - start >= frame_count:
            selected = full.iloc[start : start + frame_count]
            selected_frames = set(selected["render_unity_frame"].astype(int).tolist())
            all_variants = static[static["render_unity_frame"].isin(selected_frames)].copy()
            return StaticWindow(
                start_frame=int(selected["render_unity_frame"].min()),
                end_frame=int(selected["render_unity_frame"].max()),
                start_ms=float(selected["render_mono_ms"].min()),
                end_ms=float(selected["render_mono_ms"].max()),
                frames=all_variants,
            )
        index += 1
    return None


def _plot_position(window: StaticWindow, stem: Path) -> None:
    """绘制相对共同参考原点的静止世界系位移。"""

    reference = _reference_rows(window.frames)
    if reference.empty:
        return
    origin = np.asarray(reference.iloc[0]["gt_pos"], dtype=float)
    series = {
        "Reference": (
            _relative_frames(reference, window.start_frame),
            1000.0 * (np.vstack(reference["gt_pos"].to_numpy()) - origin),
        )
    }
    for label in ("Full", "No-StaticLock"):
        rows = _display_rows(window.frames, label)
        values = (
            1000.0 * (np.vstack(rows["display_pos"].to_numpy()) - origin)
            if not rows.empty
            else np.empty((0, 3))
        )
        series[label] = (_relative_frames(rows, window.start_frame), values)
    _draw_xyz(series, stem, unit="mm", frame_span=window.end_frame - window.start_frame)


def _plot_rotation(window: StaticWindow, stem: Path) -> None:
    """绘制相对共同参考姿态的静止世界系旋转向量。"""

    reference = _reference_rows(window.frames)
    if reference.empty:
        return
    origin = np.asarray(reference.iloc[0]["gt_rot"], dtype=float)
    series = {
        "Reference": (
            _relative_frames(reference, window.start_frame),
            np.rad2deg(
                _world_rotation_vectors(
                    origin, np.vstack(reference["gt_rot"].to_numpy())
                )
            ),
        )
    }
    for label in ("Full", "No-StaticLock"):
        rows = _display_rows(window.frames, label)
        values = (
            np.rad2deg(
                _world_rotation_vectors(
                    origin, np.vstack(rows["display_rot"].to_numpy())
                )
            )
            if not rows.empty
            else np.empty((0, 3))
        )
        series[label] = (_relative_frames(rows, window.start_frame), values)
    _draw_xyz(series, stem, unit="deg", frame_span=window.end_frame - window.start_frame)


def _draw_xyz(
    series: dict[str, tuple[np.ndarray, np.ndarray]],
    stem: Path,
    *,
    unit: str,
    frame_span: int,
) -> None:
    """用与 RQ2 一致的紧凑样式绘制三行共享帧轴。"""

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
        for label in ("Reference", "Full", "No-StaticLock"):
            frame, values = series[label]
            if len(frame) == 0:
                continue
            axis.plot(
                frame,
                values[:, component],
                color=COLORS[label],
                linewidth=1.15 if label == "Reference" else 1.0,
                alpha=0.82 if label == "No-StaticLock" else 1.0,
                zorder=3 if label == "Reference" else 2,
            )
        axis.set_ylabel(f"{'XYZ'[component]} ({unit})")
        axis.grid(True, color="#D9D9D9", linewidth=0.45, alpha=0.8)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_xlim(0, max(frame_span, 1))
        axis.tick_params(labelsize=7.0, length=2.5)
    axes[-1].set_xlabel("Relative render frame")
    axes[-1].set_xticks(np.unique(np.rint(np.linspace(0, max(frame_span, 1), 5)).astype(int)))
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


def _reference_valid_mask(rows: pd.DataFrame) -> pd.Series:
    """返回 RQ1 可用平台参考帧。"""

    return (
        rows["gt_pose_valid"].fillna(False).astype(bool)
        & rows["gt_pos"].map(is_pose_value)
        & rows["gt_rot"].map(is_pose_value)
    )


def _display_valid_mask(rows: pd.DataFrame) -> pd.Series:
    """返回用户实际可见显示 pose 的有效帧。"""

    return (
        rows["has_display_pose"].fillna(False).astype(bool)
        & rows["display_pos"].map(is_pose_value)
        & rows["display_rot"].map(is_pose_value)
    )


def _reference_rows(frames: pd.DataFrame) -> pd.DataFrame:
    """从 Full 行提取唯一平台参考帧。"""

    rows = frames[frames["label"].astype(str).eq("Full")].copy()
    rows = rows[_reference_valid_mask(rows)]
    return rows.sort_values("render_unity_frame", kind="stable").drop_duplicates(
        "render_unity_frame"
    )


def _display_rows(frames: pd.DataFrame, label: str) -> pd.DataFrame:
    """提取一个系统配置的唯一显示帧。"""

    rows = frames[frames["label"].astype(str).eq(label)].copy()
    rows = rows[_display_valid_mask(rows)]
    return rows.sort_values("render_unity_frame", kind="stable").drop_duplicates(
        "render_unity_frame"
    )


def _relative_frames(rows: pd.DataFrame, start_frame: int) -> np.ndarray:
    """把 Unity 渲染帧号转换为窗口内相对帧。"""

    if rows.empty:
        return np.empty(0, dtype=float)
    values = pd.to_numeric(rows["render_unity_frame"], errors="coerce").to_numpy(dtype=float)
    return values - float(start_frame)


def _world_rotation_vectors(reference: np.ndarray, rotations: np.ndarray) -> np.ndarray:
    """返回世界系 ``Log(R_k R_0^-1)`` 旋转向量。"""

    if len(rotations) == 0:
        return np.empty((0, 3), dtype=float)
    origin = Rotation.from_quat(reference)
    return np.asarray((Rotation.from_quat(rotations) * origin.inv()).as_rotvec())


def _legend_handles() -> list[Line2D]:
    """返回静止轨迹图的稳定图例。"""

    return [
        Line2D([0], [0], color=COLORS["Reference"], linewidth=1.15, label="Platform ref."),
        Line2D([0], [0], color=COLORS["Full"], linewidth=1.0, label="Full"),
        Line2D(
            [0],
            [0],
            color=COLORS["No-StaticLock"],
            linewidth=1.0,
            alpha=0.82,
            label="No-StaticLock",
        ),
    ]


def _remove_existing_timelines(directory: Path) -> None:
    """删除该绘图管线拥有的旧产物。"""

    for filename in TIMELINE_FILENAMES:
        path = directory / filename
        if path.is_file():
            path.unlink()


__all__ = [
    "DEFAULT_FIGS_DIR",
    "STATIC_TIMELINE_FRAME_COUNT",
    "TIMELINE_FILENAMES",
    "WINDOW_COLUMNS",
    "write_rq1_timelines",
]
