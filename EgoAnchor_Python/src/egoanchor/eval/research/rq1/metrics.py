"""
RQ1 Metrics Computation
计算所有评估指标
"""

import numpy as np
import pandas as pd
from scipy import signal
from typing import Dict, List


def compute_accuracy_metrics(df: pd.DataFrame, group_by: str = 'rq1_metric') -> pd.DataFrame:
    """
    计算精度指标

    Returns:
        DataFrame with columns: [condition, n, trans_rmse_mm, trans_median_mm, trans_p95_mm,
                                 rot_rmse_deg, rot_median_deg, rot_p95_deg]
    """
    results = []

    for condition, group in df.groupby(group_by):
        # 只使用对齐有效的数据
        valid = group[group['alignment_valid'] == True]

        if len(valid) == 0:
            continue

        trans_m = valid['error_aligned_translation_m'].values
        rot_deg = valid['error_aligned_rotation_deg'].values

        # 转换为mm
        trans_mm = trans_m * 1000

        results.append({
            'condition': condition,
            'n': len(valid),
            'trans_rmse_mm': np.sqrt(np.mean(trans_mm**2)),
            'trans_median_mm': np.median(trans_mm),
            'trans_p95_mm': np.percentile(trans_mm, 95),
            'rot_rmse_deg': np.sqrt(np.mean(rot_deg**2)),
            'rot_median_deg': np.median(rot_deg),
            'rot_p95_deg': np.percentile(rot_deg, 95),
        })

    return pd.DataFrame(results)


def compute_jitter_metrics(df: pd.DataFrame,
                           group_by: str = 'rq1_metric',
                           cutoff_hz: float = 1.0,
                           fps: float = 60.0) -> pd.DataFrame:
    """
    计算抖动指标（高通滤波后的RMS）

    Args:
        cutoff_hz: 高通滤波截止频率
        fps: 假设的帧率（用于滤波器设计）
    """
    results = []

    for condition, group in df.groupby(group_by):
        valid = group[group['alignment_valid'] == True].copy()

        if len(valid) < 10:  # 数据太少无法滤波
            continue

        # 按时间排序
        valid = valid.sort_values('render_mono_ms')

        # 提取anchor输出位置
        pos = valid[['output_pos_x', 'output_pos_y', 'output_pos_z']].values

        # 高通滤波
        sos = signal.butter(4, cutoff_hz, btype='highpass', fs=fps, output='sos')
        pos_filtered = signal.sosfiltfilt(sos, pos, axis=0)

        # 计算RMS
        position_rms = np.sqrt(np.mean(np.sum(pos_filtered**2, axis=1)))

        # 旋转抖动（简化版：直接用角距离的高频分量）
        # 这里用欧拉角的差分作为代理
        rot = valid[['output_rot_x', 'output_rot_y', 'output_rot_z', 'output_rot_w']].values
        from scipy.spatial.transform import Rotation as R

        # 计算帧间角度变化
        angle_diffs = []
        for i in range(1, len(rot)):
            r1 = R.from_quat(rot[i-1])
            r2 = R.from_quat(rot[i])
            angle = np.abs((r1.inv() * r2).magnitude())
            angle_diffs.append(np.degrees(angle))

        if len(angle_diffs) > 10:
            angle_filtered = signal.sosfiltfilt(sos, angle_diffs)
            rotation_rms = np.sqrt(np.mean(angle_filtered**2))
        else:
            rotation_rms = np.nan

        results.append({
            'condition': condition,
            'n': len(valid),
            'position_jitter_rms_mm': position_rms * 1000,
            'rotation_jitter_rms_deg': rotation_rms,
        })

    return pd.DataFrame(results)


def compute_latency_metrics(df: pd.DataFrame, group_by: str = 'rq1_metric') -> pd.DataFrame:
    """
    计算时延指标
    """
    results = []

    for condition, group in df.groupby(group_by):
        valid = group[group['capture_to_render_ms'].notna()]

        if len(valid) == 0:
            continue

        latency = valid['capture_to_render_ms'].values

        results.append({
            'condition': condition,
            'n': len(valid),
            'latency_p50_ms': np.median(latency),
            'latency_p90_ms': np.percentile(latency, 90),
            'latency_p95_ms': np.percentile(latency, 95),
            'latency_mean_ms': np.mean(latency),
            'latency_std_ms': np.std(latency),
        })

    return pd.DataFrame(results)


def compute_lag_metrics(df: pd.DataFrame,
                        group_by: str = 'rq1_metric',
                        max_lag_ms: float = 1000.0) -> pd.DataFrame:
    """
    计算运动滞后（速度互相关）
    """
    results = []

    for condition, group in df.groupby(group_by):
        valid = group[
            (group['alignment_valid'] == True) &
            (group['gt_linear_velocity_m_s'].notna())
        ].copy()

        if len(valid) < 50:  # 数据太少无法计算互相关
            continue

        # 按时间排序
        valid = valid.sort_values('render_mono_ms')

        # 计算anchor速度
        dt = np.diff(valid['render_mono_ms'].values) / 1000.0
        dx = np.diff(valid['output_pos_x'].values)
        dy = np.diff(valid['output_pos_y'].values)
        dz = np.diff(valid['output_pos_z'].values)
        anchor_v = np.sqrt(dx**2 + dy**2 + dz**2) / dt

        # GT速度
        gt_v = valid['gt_linear_velocity_m_s'].iloc[1:].values

        # 计算互相关
        correlation = signal.correlate(anchor_v, gt_v, mode='same')
        lags = signal.correlation_lags(len(anchor_v), len(gt_v), mode='same')

        # 转换为时间（假设恒定帧率）
        median_dt = np.median(dt) * 1000  # ms
        lag_times = lags * median_dt

        # 找到峰值（限制在合理范围内）
        valid_mask = np.abs(lag_times) <= max_lag_ms
        if valid_mask.sum() == 0:
            continue

        peak_idx = np.argmax(correlation[valid_mask])
        lag_ms = lag_times[valid_mask][peak_idx]
        corr_value = correlation[valid_mask][peak_idx] / (np.std(anchor_v) * np.std(gt_v) * len(anchor_v))

        results.append({
            'condition': condition,
            'n': len(valid),
            'lag_ms': lag_ms,
            'correlation': corr_value,
        })

    return pd.DataFrame(results)


def compute_screen_space_drift(df: pd.DataFrame,
                                group_by: str = 'rq1_metric',
                                focal_length_px: float = 500.0) -> pd.DataFrame:
    """
    计算屏幕空间漂移（投影到像平面的距离）

    简化版本：使用简单的针孔相机模型
    """
    results = []

    for condition, group in df.groupby(group_by):
        valid = group[group['alignment_valid'] == True].copy()

        if len(valid) == 0:
            continue

        # 误差在相机坐标系下（假设head看向物体）
        # 简化：直接用误差的横向分量除以深度，乘以焦距
        error_3d = valid[['error_aligned_translation_m']].values.flatten()
        depth = np.sqrt(
            valid['gt_pos_x']**2 +
            valid['gt_pos_y']**2 +
            valid['gt_pos_z']**2
        ).values

        # 屏幕空间误差（像素）
        # 简化公式：pixel_error ≈ (error_3d / depth) * focal_length
        screen_error_px = (error_3d / depth) * focal_length_px

        results.append({
            'condition': condition,
            'n': len(valid),
            'screen_drift_median_px': np.median(screen_error_px),
            'screen_drift_p95_px': np.percentile(screen_error_px, 95),
            'screen_drift_mean_px': np.mean(screen_error_px),
        })

    return pd.DataFrame(results)


def compute_all_metrics(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    计算所有指标

    Returns:
        字典，键为指标类型，值为DataFrame
    """
    print("Computing accuracy metrics...")
    accuracy = compute_accuracy_metrics(df)

    print("Computing jitter metrics...")
    jitter = compute_jitter_metrics(df)

    print("Computing latency metrics...")
    latency = compute_latency_metrics(df)

    print("Computing lag metrics...")
    lag = compute_lag_metrics(df)

    print("Computing screen space drift...")
    screen_drift = compute_screen_space_drift(df)

    return {
        'accuracy': accuracy,
        'jitter': jitter,
        'latency': latency,
        'lag': lag,
        'screen_drift': screen_drift,
    }


if __name__ == '__main__':
    from pathlib import Path
    from .data_loader import load_and_prepare_data
    from .gt_alignment import align_gt_with_latency, compute_gt_velocity

    data_dir = Path('p:/VSCode-Project/EgoAnchor/EgoAnchor_Python/data/eval/20260706_163825_controller_right')

    print("=== Loading and preparing data ===")
    df_clean, df_raw = load_and_prepare_data(data_dir)
    df_aligned = align_gt_with_latency(df_clean, df_raw)
    df_aligned = compute_gt_velocity(df_aligned)

    print("\n=== Computing metrics ===")
    metrics = compute_all_metrics(df_aligned)

    print("\n=== Results ===")
    for metric_name, metric_df in metrics.items():
        print(f"\n{metric_name.upper()}:")
        print(metric_df.to_string(index=False))
