"""GT 有效性过滤：剔除控制器未激活或休眠冻结的帧。

两类无效帧：
1. OVR 明确报告跟踪丢失：gt_pose_valid == False
2. 控制器冻结（休眠但 OVR 尚未报丢失）：连续多帧速度 ≈ 0 且周围有有效性转变
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def filter_valid_gt(
    df: pd.DataFrame,
    *,
    frozen_window_s: float = 2.0,
    frozen_speed_m_s: float = 5e-4,
    frozen_deg_s: float = 0.1,
    startup_grace_s: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """过滤 GT 无效帧，返回 (有效子表, 被过滤子表)。

    过滤逻辑（按优先级）：
    1. gt_pose_valid == False → 无效（OVR 明确报告丢失）
    2. 连续速度极低超过 frozen_window_s → 推断控制器冻结休眠
    3. startup_grace_s > 0 → 去掉开头 grace 秒（收敛期）

    Args:
        df: unity_output 长表，每行一个 variant tick，需含
            render_mono_ms、gt_pose_valid、gt_linear_speed_m_s、gt_angular_speed_deg_s。
        frozen_window_s: 连续冻结多少秒算无效。默认 2s。
        frozen_speed_m_s: 判定冻结的线速度上限，单位 m/s。默认 0.5 mm/s。
        frozen_deg_s: 判定冻结的角速度上限，单位 deg/s。默认 0.1 deg/s。
        startup_grace_s: 直接去掉开头这么多秒（收敛热身期）。0 表示不去。

    Returns:
        (valid_df, dropped_df)
    """
    if df.empty:
        return df.copy(), df.iloc[:0].copy()

    result = df.copy()

    # ── 计算时间轴（秒） ──
    t0 = result["render_mono_ms"].min()
    result["_t_s"] = (result["render_mono_ms"] - t0) / 1000.0

    # ── 标记每行是否无效 ──
    invalid = pd.Series(False, index=result.index)

    # 1. OVR 明确报无效
    if "gt_pose_valid" in result.columns:
        invalid |= ~result["gt_pose_valid"].fillna(False).astype(bool)

    # 2. 冻结检测：连续速度极低超过 frozen_window_s
    invalid |= _detect_frozen(result, frozen_window_s, frozen_speed_m_s, frozen_deg_s)

    # 3. 启动热身期
    if startup_grace_s > 0:
        invalid |= result["_t_s"] < startup_grace_s

    result = result.drop(columns=["_t_s"])
    valid = result[~invalid].copy()
    dropped = result[invalid].copy()
    return valid, dropped


def suggest_startup_cutoff(df: pd.DataFrame, *, speed_threshold_m_s: float = 0.01) -> float:
    """估算控制器首次真正激活的时间点（秒）。

    通过检测 GT 线速度首次持续超过 speed_threshold_m_s 来判断。
    返回建议的跳过时长（秒）；如果整段都没有超过，返回 0。
    """
    if df.empty or "gt_linear_speed_m_s" not in df.columns:
        return 0.0

    t0 = df["render_mono_ms"].min()
    t_s = (df["render_mono_ms"] - t0) / 1000.0
    speed = df["gt_linear_speed_m_s"].fillna(0.0).values

    # 找第一个速度超过阈值的帧
    active_idx = np.where(speed > speed_threshold_m_s)[0]
    if len(active_idx) == 0:
        return 0.0
    return float(t_s.iloc[active_idx[0]])


# ── 内部工具 ──

def _detect_frozen(
    df: pd.DataFrame,
    window_s: float,
    speed_m_s: float,
    deg_s: float,
) -> pd.Series:
    """检测连续冻结帧（速度极低超过 window_s 秒）。"""
    if "gt_linear_speed_m_s" not in df.columns or "gt_angular_speed_deg_s" not in df.columns:
        return pd.Series(False, index=df.index)

    lin = df["gt_linear_speed_m_s"].fillna(0.0).values
    ang = df["gt_angular_speed_deg_s"].fillna(0.0).values
    t_s = ((df["render_mono_ms"] - df["render_mono_ms"].min()) / 1000.0).values

    is_slow = (lin <= speed_m_s) & (ang <= deg_s)

    # 对每帧：向前看 window_s 秒内是否全部 slow
    frozen = np.zeros(len(df), dtype=bool)
    n = len(df)
    j = 0
    for i in range(n):
        # 移动右指针到 t_s[i] + window_s 之外
        while j < n and t_s[j] <= t_s[i] + window_s:
            j += 1
        # [i, j) 窗口全为 slow → 冻结
        if j > i and is_slow[i:j].all():
            frozen[i:j] = True

    return pd.Series(frozen, index=df.index)
