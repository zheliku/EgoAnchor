"""
RQ1 Data Loader
加载和清洗实验数据
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple
from scipy.spatial.transform import Rotation as R


def load_unity_output(filepath: Path) -> pd.DataFrame:
    """加载Unity输出日志"""
    records = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)

            # 提取基本信息
            record = {
                'render_mono_ms': data['render_mono_ms'],
                'render_unix_ms': data['render_unix_ms'],
                'render_unity_frame': data['render_unity_frame'],
                'rq1_metric': data['rq1_metric'],
                'rq1_metric_duration': data['rq1_metric_duration'],

                # GT数据
                'gt_pos_x': data['gt_pos'][0],
                'gt_pos_y': data['gt_pos'][1],
                'gt_pos_z': data['gt_pos'][2],
                'gt_rot_x': data['gt_rot'][0],
                'gt_rot_y': data['gt_rot'][1],
                'gt_rot_z': data['gt_rot'][2],
                'gt_rot_w': data['gt_rot'][3],
                'gt_pose_valid': data['gt_pose_valid'],
                'gt_linear_speed_m_s': data.get('gt_linear_speed_m_s', 0),
                'gt_angular_speed_deg_s': data.get('gt_angular_speed_deg_s', 0),

                # Head数据
                'head_pos_x': data['head_pos'][0],
                'head_pos_y': data['head_pos'][1],
                'head_pos_z': data['head_pos'][2],
                'head_rot_x': data['head_rot'][0],
                'head_rot_y': data['head_rot'][1],
                'head_rot_z': data['head_rot'][2],
                'head_rot_w': data['head_rot'][3],
            }

            # 提取anchor数据（假设只有一个variant: egoanchor）
            if data['variants']:
                variant = data['variants'][0]
                record.update({
                    'variant_label': variant['label'],
                    'source_frame_id': variant['source_frame_id'],
                    'has_output_pose': variant['has_output_pose'],
                    'output_pos_x': variant['output_pos'][0] if variant['has_output_pose'] else np.nan,
                    'output_pos_y': variant['output_pos'][1] if variant['has_output_pose'] else np.nan,
                    'output_pos_z': variant['output_pos'][2] if variant['has_output_pose'] else np.nan,
                    'output_rot_x': variant['output_rot'][0] if variant['has_output_pose'] else np.nan,
                    'output_rot_y': variant['output_rot'][1] if variant['has_output_pose'] else np.nan,
                    'output_rot_z': variant['output_rot'][2] if variant['has_output_pose'] else np.nan,
                    'output_rot_w': variant['output_rot'][3] if variant['has_output_pose'] else np.nan,
                    'anchor_state': variant['anchor_state'],
                    'policy_action': variant['policy_action'],
                    'latest_static_locked': variant['latest_static_locked'],
                    'source_capture_mono_ms': variant.get('source_capture_mono_ms'),
                    'source_capture_unity_frame': variant.get('source_capture_unity_frame', -1),
                })

            records.append(record)

    df = pd.DataFrame(records)

    # 计算时间相关字段
    df['time_s'] = (df['render_mono_ms'] - df['render_mono_ms'].iloc[0]) / 1000.0

    # 计算端到端时延
    df['capture_to_render_ms'] = np.nan
    valid_capture = df['source_capture_mono_ms'].notna()
    df.loc[valid_capture, 'capture_to_render_ms'] = (
        df.loc[valid_capture, 'render_mono_ms'] - df.loc[valid_capture, 'source_capture_mono_ms']
    )

    return df


def load_python_runtime(filepath: Path) -> pd.DataFrame:
    """加载Python运行时日志（感知后端）"""
    records = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)

            # 只提取观测相关的日志
            if data.get('event') == 'observation_published':
                record = {
                    'frame_id': data['frame_id'],
                    'capture_mono_ms': data['capture_mono_ms'],
                    'publish_mono_ms': data['publish_mono_ms'],
                    'reliability_score': data.get('reliability_score', np.nan),
                    'reliability_v': data.get('reliability_v', np.nan),
                    'reliability_c': data.get('reliability_c', np.nan),
                    'reliability_d': data.get('reliability_d', np.nan),
                }
                records.append(record)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    return df


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """清洗数据，过滤无效帧"""
    print(f"Original data: {len(df)} frames")

    # 先检查有哪些anchor_state
    print("\nAnchor states distribution:")
    print(df['anchor_state'].value_counts())

    # 过滤条件（放宽anchor_state，接受Coasting等状态）
    # Coasting表示正在追踪但感知输入暂时中断
    valid_states = ['Tracking', 'Coasting', 'FrozenUncertain']

    df_clean = df[
        (df['gt_pose_valid'] == True) &  # GT有效
        (df['anchor_state'].isin(valid_states)) &  # Anchor在可用状态
        (df['has_output_pose'] == True) &  # 有输出位姿
        (df['rq1_metric'] != 'none')  # 不是unlabeled
    ].copy()

    print(f"\nAfter cleaning: {len(df_clean)} frames")
    print(f"Removed: {len(df) - len(df_clean)} frames ({100*(len(df)-len(df_clean))/len(df):.1f}%)")

    # 按场景统计
    print("\nFrames per condition:")
    print(df_clean['rq1_metric'].value_counts().sort_index())

    print("\nStates in cleaned data:")
    print(df_clean['anchor_state'].value_counts())

    return df_clean


def merge_perception_data(df_unity: pd.DataFrame, df_python: pd.DataFrame) -> pd.DataFrame:
    """合并Unity和Python数据"""
    if df_python.empty:
        print("Warning: No Python runtime data found")
        return df_unity

    # 通过frame_id合并
    df_merged = df_unity.merge(
        df_python,
        left_on='source_frame_id',
        right_on='frame_id',
        how='left',
        suffixes=('', '_python')
    )

    print(f"\nMerged {len(df_merged)} frames")
    print(f"Frames with reliability scores: {df_merged['reliability_score'].notna().sum()}")

    return df_merged


def compute_pose_distance(df: pd.DataFrame,
                          pos1_cols: List[str],
                          rot1_cols: List[str],
                          pos2_cols: List[str],
                          rot2_cols: List[str],
                          prefix: str = 'error') -> pd.DataFrame:
    """计算两个位姿之间的距离"""

    # 平移误差（欧氏距离，单位：米）
    pos1 = df[pos1_cols].values
    pos2 = df[pos2_cols].values
    translation_error = np.linalg.norm(pos1 - pos2, axis=1)
    df[f'{prefix}_translation_m'] = translation_error

    # 旋转误差（四元数角距离，单位：弧度→度）
    rot1 = df[rot1_cols].values
    rot2 = df[rot2_cols].values

    # 使用scipy计算四元数角距离
    rotation_errors = []
    for r1, r2 in zip(rot1, rot2):
        try:
            R1 = R.from_quat(r1)
            R2 = R.from_quat(r2)
            # 相对旋转
            R_rel = R1.inv() * R2
            # 旋转角度
            angle = np.abs(R_rel.magnitude())
            rotation_errors.append(np.degrees(angle))
        except:
            rotation_errors.append(np.nan)

    df[f'{prefix}_rotation_deg'] = rotation_errors

    return df


def load_and_prepare_data(data_dir: Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """加载并准备所有数据"""

    # 查找数据文件
    unity_file = list(data_dir.glob('*_unity_output.jsonl'))[0]
    python_file = list(data_dir.glob('*_python_runtime.jsonl'))[0]

    print(f"Loading data from: {data_dir}")
    print(f"  Unity output: {unity_file.name}")
    print(f"  Python runtime: {python_file.name}")
    print()

    # 加载数据
    df_unity = load_unity_output(unity_file)
    df_python = load_python_runtime(python_file)

    # 合并数据
    df_merged = merge_perception_data(df_unity, df_python)

    # 清洗数据
    df_clean = clean_data(df_merged)

    # 计算未对齐的误差（当前帧GT）
    df_clean = compute_pose_distance(
        df_clean,
        pos1_cols=['output_pos_x', 'output_pos_y', 'output_pos_z'],
        rot1_cols=['output_rot_x', 'output_rot_y', 'output_rot_z', 'output_rot_w'],
        pos2_cols=['gt_pos_x', 'gt_pos_y', 'gt_pos_z'],
        rot2_cols=['gt_rot_x', 'gt_rot_y', 'gt_rot_z', 'gt_rot_w'],
        prefix='error_naive'
    )

    return df_clean, df_unity  # 返回原始数据用于GT对齐


if __name__ == '__main__':
    from pathlib import Path

    data_dir = Path('p:/VSCode-Project/EgoAnchor/EgoAnchor_Python/data/eval/20260706_163825_controller_right')

    df_clean, df_raw = load_and_prepare_data(data_dir)

    print("\n=== Data Summary ===")
    print(f"Total valid frames: {len(df_clean)}")
    print(f"Time span: {df_clean['time_s'].min():.1f}s - {df_clean['time_s'].max():.1f}s")
    print(f"Duration: {df_clean['time_s'].max() - df_clean['time_s'].min():.1f}s")
    print("\nConditions:")
    for condition in df_clean['rq1_metric'].unique():
        subset = df_clean[df_clean['rq1_metric'] == condition]
        duration = subset['rq1_metric_duration'].iloc[0] if len(subset) > 0 else 0
        print(f"  {condition:25s}: {len(subset):5d} frames, {duration:6.1f}s")
