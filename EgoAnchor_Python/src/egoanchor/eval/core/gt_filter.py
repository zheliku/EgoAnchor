"""GT 有效性过滤：只信任 Unity 侧写下的 gt_pose_valid。

Unity `EvalRecorder` 已用 keep-alive 处理手柄 sleep：手柄静止进入休眠、OVR 报
tracked=false 时，keep-alive 窗口内继续复用上次有效 pose 并保持 gt_pose_valid=true；
真正跟踪丢失（超出 keep-alive 或未绑定 GT）才写 gt_pose_valid=false。

因此离线端不再用「速度≈0 判休眠」或「首次运动前一律砍掉」这类启发式——静止物体本身
速度就该是 0，用速度过滤会把合法的长时静止帧误删，直接和 Unity 的 keep-alive 打架。
"""

from __future__ import annotations

import pandas as pd


def filter_valid_gt(
    df: pd.DataFrame,
    *,
    startup_grace_s: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """过滤 GT 无效帧，返回 (有效子表, 被过滤子表)。

    过滤逻辑：
    1. gt_pose_valid == False → 无效（OVR 丢失且超出 keep-alive，或未绑定 GT）。
    2. startup_grace_s > 0 → 额外去掉开头这么多秒（仅在显式需要时使用，默认不去）。

    Args:
        df: unity_output 长表，每行一个 variant tick，需含 render_mono_ms、gt_pose_valid。
        startup_grace_s: 显式指定去掉开头这么多秒的收敛热身期。0 表示完全信任 gt_pose_valid。

    Returns:
        (valid_df, dropped_df)
    """
    if df.empty:
        return df.copy(), df.iloc[:0].copy()

    result = df.copy()
    invalid = pd.Series(False, index=result.index)

    # 1. Unity 明确报 GT 无效
    if "gt_pose_valid" in result.columns:
        invalid |= ~result["gt_pose_valid"].fillna(False).astype(bool)

    # 2. 可选启动热身期（默认关闭）
    if startup_grace_s > 0 and "render_mono_ms" in result.columns:
        t0 = result["render_mono_ms"].min()
        t_s = (result["render_mono_ms"] - t0) / 1000.0
        invalid |= t_s < startup_grace_s

    valid = result[~invalid].copy()
    dropped = result[invalid].copy()
    return valid, dropped
