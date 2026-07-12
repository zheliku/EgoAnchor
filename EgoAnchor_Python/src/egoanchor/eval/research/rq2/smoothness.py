"""RQ2 运动平滑度指标：谱弧长（SPARC）与 jerk RMS。

SPARC（Balasubramanian et al. 2015, JNER）度量速度谱的弧长，越接近 0
越平滑；对幅度归一化、无量纲、抗噪。零阶保持产生的阶梯信号谱能量在高频
展宽，弧长更长（更负），因而 SPARC 能定量区分 Full 平滑曲线与 Raw-ZOH 阶梯。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from egoanchor.eval.metrics import is_pose_value

SMOOTHNESS_COLUMNS = [
    "session_id",
    "condition",
    "rq2_trial_id",
    "label",
    "sample_count",
    "sparc_translation",
    "jerk_rms_translation_m_s3",
    "sparc_speed",
    "jerk_rms_speed",
]
"""按 condition × label 汇总的平滑度字段。"""


def sparc(signal: np.ndarray, dt_s: float, *, cutoff_hz: float = 10.0,
          amplitude_threshold: float = 0.05) -> float:
    """计算一维信号的谱弧长平滑度（越接近 0 越平滑，退化返回 NaN）。"""

    values = np.asarray(signal, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 2 or dt_s <= 0.0:
        return np.nan
    values = values - float(np.mean(values))
    if not np.any(np.abs(values) > 0.0):
        return np.nan
    n_fft = int(2 ** np.ceil(np.log2(values.size * 4)))
    magnitude = np.abs(np.fft.rfft(values, n=n_fft))
    if not np.any(magnitude > 0.0):
        return np.nan
    magnitude = magnitude / float(np.max(magnitude))
    freq = np.fft.rfftfreq(n_fft, d=dt_s)
    band = freq <= cutoff_hz
    magnitude = magnitude[band]
    freq = freq[band]
    keep = magnitude >= amplitude_threshold
    if np.count_nonzero(keep) < 2:
        return np.nan
    last = np.max(np.nonzero(keep))
    magnitude = magnitude[: last + 1]
    freq = freq[: last + 1]
    df_norm = np.diff(freq) / (freq[-1] - freq[0]) if freq[-1] > freq[0] else None
    if df_norm is None:
        return np.nan
    dmag = np.diff(magnitude)
    arc = -float(np.sum(np.sqrt(df_norm ** 2 + dmag ** 2)))
    return arc


def jerk_rms(positions: np.ndarray, times_s: np.ndarray) -> float:
    """计算位置序列三阶差分（jerk）的 RMS（m/s³，样本不足返回 NaN）。"""

    pos = np.asarray(positions, dtype=float)
    times = np.asarray(times_s, dtype=float)
    if pos.ndim == 1:
        pos = pos.reshape(-1, 1)
    if pos.shape[0] < 4 or times.shape[0] != pos.shape[0]:
        return np.nan
    dt = float(np.median(np.diff(times)))
    if not np.isfinite(dt) or dt <= 0.0:
        return np.nan
    jerk = np.diff(pos, n=3, axis=0) / (dt ** 3)
    magnitude = np.linalg.norm(jerk, axis=1)
    magnitude = magnitude[np.isfinite(magnitude)]
    if magnitude.size == 0:
        return np.nan
    return float(np.sqrt(np.mean(magnitude ** 2)))


def compute_smoothness_summary(output: pd.DataFrame, *, session_id: str = "") -> pd.DataFrame:
    """按 condition × label 汇总 display 轨迹的 SPARC 与 jerk RMS。"""

    required = ("rq2_condition", "rq2_trial_id", "label")
    if output.empty or any(column not in output.columns for column in required):
        return pd.DataFrame(columns=SMOOTHNESS_COLUMNS)
    trial_id = pd.to_numeric(output["rq2_trial_id"], errors="coerce")
    motion = output.loc[
        output["rq2_condition"].fillna("none").astype(str).isin(
            ("slow_translation", "fast_motion", "rotation")
        )
        & (trial_id > 0)
    ].copy()
    if motion.empty:
        return pd.DataFrame(columns=SMOOTHNESS_COLUMNS)
    rows: list[dict[str, object]] = []
    for (condition, current_trial, label), group in motion.groupby(
        ["rq2_condition", "rq2_trial_id", "label"], sort=True
    ):
        times, series = _display_series(group)
        if times.size < 4:
            rows.append(_empty_row(session_id, condition, current_trial, label, times.size))
            continue
        dt = float(np.median(np.diff(times)))
        speed = np.linalg.norm(np.diff(series, axis=0), axis=1) / dt if dt > 0 else np.array([])
        rows.append(
            {
                "session_id": str(session_id),
                "condition": str(condition),
                "rq2_trial_id": int(current_trial),
                "label": str(label),
                "sample_count": int(times.size),
                "sparc_translation": sparc(series[:, 0], dt) if dt > 0 else np.nan,
                "jerk_rms_translation_m_s3": jerk_rms(series, times),
                "sparc_speed": sparc(speed, dt) if speed.size >= 2 and dt > 0 else np.nan,
                "jerk_rms_speed": np.nan,
            }
        )
    return pd.DataFrame.from_records(rows, columns=SMOOTHNESS_COLUMNS)


def _display_series(group: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """抽取按时间排序的有效 display 位置序列。"""

    frame = group.sort_values("render_mono_ms")
    display_mask = (
        frame["has_display_pose"].fillna(False).astype(bool)
        if "has_display_pose" in frame.columns
        else pd.Series(True, index=frame.index)
    )
    times: list[float] = []
    positions: list[list[float]] = []
    for _, row in frame[display_mask].iterrows():
        pos = row.get("display_pos", row.get("output_pos"))
        stamp = row.get("render_mono_ms")
        if is_pose_value(pos) and np.isfinite(stamp):
            times.append(float(stamp) / 1000.0)
            positions.append([float(v) for v in pos])
    if not times:
        return np.asarray([], dtype=float), np.zeros((0, 3), dtype=float)
    return np.asarray(times, dtype=float), np.asarray(positions, dtype=float)


def _empty_row(session_id: str, condition: str, trial: int, label: str,
               sample_count: int) -> dict[str, object]:
    """样本不足时的 NaN 行。"""

    return {
        "session_id": str(session_id),
        "condition": str(condition),
        "rq2_trial_id": int(trial),
        "label": str(label),
        "sample_count": int(sample_count),
        "sparc_translation": np.nan,
        "jerk_rms_translation_m_s3": np.nan,
        "sparc_speed": np.nan,
        "jerk_rms_speed": np.nan,
    }


__all__ = [
    "SMOOTHNESS_COLUMNS",
    "compute_smoothness_summary",
    "jerk_rms",
    "sparc",
]
