"""
RQ1 GT Alignment
GT时延对齐：根据端到端时延，将anchor输出与历史GT对齐
"""

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline
from scipy.spatial.transform import Rotation as R
from scipy.spatial.transform import Slerp


def interpolate_gt_poses(df: pd.DataFrame,
                         target_times: np.ndarray,
                         time_col: str = 'render_mono_ms') -> pd.DataFrame:
    """
    对GT位姿进行时间插值

    Args:
        df: 包含GT位姿的DataFrame（必须是完整的时间序列，包括非tracking帧）
        target_times: 目标时间点（单位：ms）
        time_col: 时间列名

    Returns:
        插值后的DataFrame，包含aligned_gt_*列
    """
    # 提取GT位姿时间序列（使用所有有效GT，不仅仅是tracking帧）
    df_gt = df[df['gt_pose_valid'] == True].copy()
    df_gt = df_gt.sort_values(time_col)

    times = df_gt[time_col].values

    # 位置插值（三次样条）
    pos_x = df_gt['gt_pos_x'].values
    pos_y = df_gt['gt_pos_y'].values
    pos_z = df_gt['gt_pos_z'].values

    cs_x = CubicSpline(times, pos_x, extrapolate=False)
    cs_y = CubicSpline(times, pos_y, extrapolate=False)
    cs_z = CubicSpline(times, pos_z, extrapolate=False)

    # 旋转插值（Slerp）
    rotations = R.from_quat(df_gt[['gt_rot_x', 'gt_rot_y', 'gt_rot_z', 'gt_rot_w']].values)
    slerp = Slerp(times, rotations)

    # 在目标时间点插值
    # 过滤掉超出范围的时间点
    valid_mask = (target_times >= times.min()) & (target_times <= times.max())

    aligned_pos_x = np.full(len(target_times), np.nan)
    aligned_pos_y = np.full(len(target_times), np.nan)
    aligned_pos_z = np.full(len(target_times), np.nan)
    aligned_rot = np.full((len(target_times), 4), np.nan)

    if valid_mask.any():
        valid_times = target_times[valid_mask]
        aligned_pos_x[valid_mask] = cs_x(valid_times)
        aligned_pos_y[valid_mask] = cs_y(valid_times)
        aligned_pos_z[valid_mask] = cs_z(valid_times)
        aligned_rot[valid_mask] = slerp(valid_times).as_quat()

    # 创建结果DataFrame
    result = pd.DataFrame({
        'target_time_ms': target_times,
        'aligned_gt_pos_x': aligned_pos_x,
        'aligned_gt_pos_y': aligned_pos_y,
        'aligned_gt_pos_z': aligned_pos_z,
        'aligned_gt_rot_x': aligned_rot[:, 0],
        'aligned_gt_rot_y': aligned_rot[:, 1],
        'aligned_gt_rot_z': aligned_rot[:, 2],
        'aligned_gt_rot_w': aligned_rot[:, 3],
        'alignment_valid': valid_mask,
    })

    return result


def align_gt_with_latency(df_tracking: pd.DataFrame,
                          df_raw: pd.DataFrame,
                          latency_ms: float = None) -> pd.DataFrame:
    """
    根据端到端时延对齐GT

    Args:
        df_tracking: 清洗后的tracking数据
        df_raw: 原始数据（包含所有帧，用于GT插值）
        latency_ms: 端到端时延（ms）。如果为None，使用实测的capture_to_render_ms

    Returns:
        添加了aligned_gt_*和error_aligned_*列的DataFrame
    """
    df = df_tracking.copy()

    # 确定对齐时间
    if latency_ms is not None:
        # 使用固定时延
        print(f"Using fixed latency: {latency_ms:.1f} ms")
        df['alignment_latency_ms'] = latency_ms
        df['aligned_capture_time_ms'] = df['render_mono_ms'] - latency_ms
    else:
        # 使用实测时延
        print("Using measured latency (capture_to_render_ms)")
        valid_latency = df['capture_to_render_ms'].notna()

        if not valid_latency.any():
            raise ValueError("No valid capture_to_render_ms found in data")

        # 对于没有实测时延的帧，使用中位数
        median_latency = df.loc[valid_latency, 'capture_to_render_ms'].median()
        df['alignment_latency_ms'] = df['capture_to_render_ms'].fillna(median_latency)
        df['aligned_capture_time_ms'] = df['render_mono_ms'] - df['alignment_latency_ms']

    print(f"Latency stats: median={df['alignment_latency_ms'].median():.1f}ms, "
          f"p90={df['alignment_latency_ms'].quantile(0.9):.1f}ms, "
          f"p95={df['alignment_latency_ms'].quantile(0.95):.1f}ms")

    # 插值GT位姿
    print("Interpolating GT poses...")
    aligned_gt = interpolate_gt_poses(
        df_raw,
        df['aligned_capture_time_ms'].values,
        time_col='render_mono_ms'
    )

    # 合并回原数据
    df = pd.concat([df.reset_index(drop=True), aligned_gt.reset_index(drop=True)], axis=1)

    # 检查对齐有效性
    alignment_valid = df['alignment_valid'].sum()
    print(f"Successfully aligned: {alignment_valid}/{len(df)} frames "
          f"({100*alignment_valid/len(df):.1f}%)")

    # 计算对齐后的误差
    valid_mask = df['alignment_valid'] == True

    if valid_mask.sum() > 0:
        from .data_loader import compute_pose_distance

        df_valid = df[valid_mask].copy()
        df_valid = compute_pose_distance(
            df_valid,
            pos1_cols=['output_pos_x', 'output_pos_y', 'output_pos_z'],
            rot1_cols=['output_rot_x', 'output_rot_y', 'output_rot_z', 'output_rot_w'],
            pos2_cols=['aligned_gt_pos_x', 'aligned_gt_pos_y', 'aligned_gt_pos_z'],
            rot2_cols=['aligned_gt_rot_x', 'aligned_gt_rot_y', 'aligned_gt_rot_z', 'aligned_gt_rot_w'],
            prefix='error_aligned'
        )

        # 更新回原DataFrame
        df.loc[valid_mask, 'error_aligned_translation_m'] = df_valid['error_aligned_translation_m']
        df.loc[valid_mask, 'error_aligned_rotation_deg'] = df_valid['error_aligned_rotation_deg']

    return df


def compute_gt_velocity(df: pd.DataFrame,
                        window_size: int = 5) -> pd.DataFrame:
    """
    计算GT速度（用于时延影响分析）

    Args:
        df: DataFrame with GT poses
        window_size: 平滑窗口大小（帧数）

    Returns:
        添加了gt_velocity_*列的DataFrame
    """
    df = df.copy()

    # 计算位置差分
    dt = np.diff(df['render_mono_ms'].values) / 1000.0  # 秒

    dx = np.diff(df['gt_pos_x'].values)
    dy = np.diff(df['gt_pos_y'].values)
    dz = np.diff(df['gt_pos_z'].values)

    # 线速度（m/s）
    v = np.sqrt(dx**2 + dy**2 + dz**2) / dt

    # 平滑
    v_smooth = pd.Series(v).rolling(window=window_size, center=True, min_periods=1).mean().values

    # 添加到DataFrame（第一帧没有速度）
    df['gt_linear_velocity_m_s'] = np.concatenate([[np.nan], v_smooth])

    # 转换为cm/s（更直观）
    df['gt_linear_velocity_cm_s'] = df['gt_linear_velocity_m_s'] * 100

    return df


if __name__ == '__main__':
    from pathlib import Path
    from .data_loader import load_and_prepare_data

    data_dir = Path('p:/VSCode-Project/EgoAnchor/EgoAnchor_Python/data/eval/20260706_163825_controller_right')

    print("=== Loading data ===")
    df_clean, df_raw = load_and_prepare_data(data_dir)

    print("\n=== Aligning GT with latency ===")
    df_aligned = align_gt_with_latency(df_clean, df_raw, latency_ms=None)

    print("\n=== Computing GT velocity ===")
    df_aligned = compute_gt_velocity(df_aligned)

    print("\n=== Results ===")
    print("\nError comparison (naive vs aligned):")
    for condition in sorted(df_aligned['rq1_metric'].unique()):
        subset = df_aligned[
            (df_aligned['rq1_metric'] == condition) &
            (df_aligned['alignment_valid'] == True)
        ]

        if len(subset) == 0:
            continue

        naive_trans = subset['error_naive_translation_m'].median() * 1000
        aligned_trans = subset['error_aligned_translation_m'].median() * 1000
        improvement = (naive_trans - aligned_trans) / naive_trans * 100

        print(f"  {condition:25s}: naive={naive_trans:6.1f}mm, "
              f"aligned={aligned_trans:6.1f}mm, "
              f"improvement={improvement:5.1f}%")

    print("\nVelocity stats by condition:")
    for condition in sorted(df_aligned['rq1_metric'].unique()):
        subset = df_aligned[df_aligned['rq1_metric'] == condition]
        v = subset['gt_linear_velocity_cm_s'].dropna()

        if len(v) == 0:
            continue

        print(f"  {condition:25s}: mean={v.mean():6.2f} cm/s, "
              f"median={v.median():6.2f} cm/s, "
              f"p95={v.quantile(0.95):6.2f} cm/s")
