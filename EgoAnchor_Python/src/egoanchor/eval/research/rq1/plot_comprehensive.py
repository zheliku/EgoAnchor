"""
RQ1 Visualization: Comprehensive Figure
生成RQ1的核心综合图表（2x2布局）
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path
from typing import Dict


# 设置绘图样式
plt.rcParams['font.family'] = 'Arial'
plt.rcParams['font.size'] = 9
plt.rcParams['axes.labelsize'] = 10
plt.rcParams['axes.titlesize'] = 11
plt.rcParams['xtick.labelsize'] = 9
plt.rcParams['ytick.labelsize'] = 9
plt.rcParams['legend.fontsize'] = 8
plt.rcParams['figure.titlesize'] = 12

# 场景顺序和标签
CONDITION_ORDER = [
    'static_observation',
    'slow_translation',
    'fast_motion',
    'rotation',
    'occlusion_recovery'
]

CONDITION_LABELS = {
    'static_observation': 'Static\nObservation',
    'slow_translation': 'Slow\nTranslation',
    'fast_motion': 'Fast\nMotion',
    'rotation': 'Rotation',
    'occlusion_recovery': 'Occlusion\nRecovery'
}

# 颜色方案
COLOR_NAIVE = '#e74c3c'  # 红色 - 未对齐
COLOR_ALIGNED = '#3498db'  # 蓝色 - 对齐后
COLOR_STATIC = '#2ecc71'  # 绿色 - 静止
COLOR_MOTION = '#f39c12'  # 橙色 - 运动


def plot_accuracy_comparison(ax, metrics: Dict[str, pd.DataFrame], df: pd.DataFrame):
    """
    (A) 精度对比：显示时延补偿前后的误差
    """
    # 准备数据
    accuracy = metrics['accuracy'].copy()

    # 计算naive误差（从原始数据）
    naive_stats = []
    for condition in CONDITION_ORDER:
        subset = df[
            (df['rq1_metric'] == condition) &
            (df['alignment_valid'] == True)
        ]
        if len(subset) > 0:
            naive_stats.append({
                'condition': condition,
                'trans_median_mm': subset['error_naive_translation_m'].median() * 1000,
                'trans_p95_mm': subset['error_naive_translation_m'].quantile(0.95) * 1000,
                'rot_median_deg': subset['error_naive_rotation_deg'].median(),
                'rot_p95_deg': subset['error_naive_rotation_deg'].quantile(0.95),
            })

    naive_df = pd.DataFrame(naive_stats)

    # 合并数据
    plot_data = []
    for condition in CONDITION_ORDER:
        if condition not in accuracy['condition'].values:
            continue

        aligned = accuracy[accuracy['condition'] == condition].iloc[0]
        naive = naive_df[naive_df['condition'] == condition]

        if len(naive) > 0:
            naive = naive.iloc[0]
            plot_data.append({
                'condition': condition,
                'type': 'Before Compensation',
                'trans_median': naive['trans_median_mm'],
                'trans_p95': naive['trans_p95_mm'],
                'rot_median': naive['rot_median_deg'],
                'rot_p95': naive['rot_p95_deg'],
            })

        plot_data.append({
            'condition': condition,
            'type': 'After Compensation',
            'trans_median': aligned['trans_median_mm'],
            'trans_p95': aligned['trans_p95_mm'],
            'rot_median': aligned['rot_median_deg'],
            'rot_p95': aligned['rot_p95_deg'],
        })

    plot_df = pd.DataFrame(plot_data)

    # 绘制分组条形图
    x = np.arange(len(CONDITION_ORDER))
    width = 0.35

    # 平移误差（左Y轴）
    for i, cond in enumerate(CONDITION_ORDER):
        cond_data = plot_df[plot_df['condition'] == cond]

        if len(cond_data) == 0:
            continue

        for j, (type_name, color) in enumerate([
            ('Before Compensation', COLOR_NAIVE),
            ('After Compensation', COLOR_ALIGNED)
        ]):
            type_data = cond_data[cond_data['type'] == type_name]
            if len(type_data) == 0:
                continue

            row = type_data.iloc[0]
            pos = x[i] + (j - 0.5) * width

            # 条形（中位数）
            bar = ax.bar(pos, row['trans_median'], width * 0.8,
                        color=color, alpha=0.7, edgecolor='black', linewidth=0.5)

            # P95误差条
            ax.plot([pos, pos],
                   [row['trans_median'], row['trans_p95']],
                   color='black', linewidth=1.5, alpha=0.6)
            ax.plot([pos - width*0.2, pos + width*0.2],
                   [row['trans_p95'], row['trans_p95']],
                   color='black', linewidth=1.5, alpha=0.6)

    ax.set_ylabel('Translation Error (mm)', fontweight='bold')
    ax.set_xlabel('Condition', fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels([CONDITION_LABELS[c] for c in CONDITION_ORDER], fontsize=8)
    ax.set_ylim(0, None)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    # 图例
    legend_elements = [
        mpatches.Patch(color=COLOR_NAIVE, alpha=0.7, label='Before Compensation'),
        mpatches.Patch(color=COLOR_ALIGNED, alpha=0.7, label='After Compensation'),
        plt.Line2D([0], [0], color='black', linewidth=1.5, label='P95'),
    ]
    ax.legend(handles=legend_elements, loc='upper left', framealpha=0.9)

    ax.set_title('(A) Accuracy: Latency Compensation Effect', fontweight='bold', pad=10)


def plot_stability_analysis(ax, metrics: Dict[str, pd.DataFrame]):
    """
    (B) 稳定性分析：静止期抖动和屏幕空间漂移
    """
    jitter = metrics['jitter']
    screen = metrics['screen_drift']

    # 只对比静止 vs 运动（合并运动场景）
    motion_conditions = ['slow_translation', 'fast_motion', 'rotation']

    # 准备数据
    static_jitter = jitter[jitter['condition'] == 'static_observation'].iloc[0]
    motion_jitter = jitter[jitter['condition'].isin(motion_conditions)]

    static_screen = screen[screen['condition'] == 'static_observation'].iloc[0]
    motion_screen = screen[screen['condition'].isin(motion_conditions)]

    # 计算运动场景的平均值
    motion_jitter_pos = motion_jitter['position_jitter_rms_mm'].mean()
    motion_jitter_rot = motion_jitter['rotation_jitter_rms_deg'].mean()
    motion_screen_drift = motion_screen['screen_drift_median_px'].mean()

    # 绘图
    x = np.arange(2)
    width = 0.35

    # 位置抖动
    bars1 = ax.bar(x - width/2, [static_jitter['position_jitter_rms_mm'], motion_jitter_pos],
                   width, label='Position Jitter (mm)', color=COLOR_STATIC, alpha=0.7,
                   edgecolor='black', linewidth=0.5)

    # 在条形上标注数值
    for i, bar in enumerate(bars1):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}' if i == 0 else f'{height:.1f}',
                ha='center', va='bottom', fontsize=7)

    # 屏幕漂移（使用右Y轴）
    ax2 = ax.twinx()
    bars2 = ax2.bar(x + width/2, [static_screen['screen_drift_median_px'], motion_screen_drift],
                    width, label='Screen Drift (px)', color=COLOR_MOTION, alpha=0.7,
                    edgecolor='black', linewidth=0.5)

    for i, bar in enumerate(bars2):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                 f'{height:.1f}',
                 ha='center', va='bottom', fontsize=7)

    # 设置
    ax.set_ylabel('Position Jitter (mm)', fontweight='bold', color=COLOR_STATIC)
    ax2.set_ylabel('Screen Drift (px)', fontweight='bold', color=COLOR_MOTION)
    ax.tick_params(axis='y', labelcolor=COLOR_STATIC)
    ax2.tick_params(axis='y', labelcolor=COLOR_MOTION)

    ax.set_xticks(x)
    ax.set_xticklabels(['Static\nObservation', 'Motion\n(Average)'], fontsize=9)
    ax.set_ylim(0, None)
    ax2.set_ylim(0, None)

    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    # 合并图例
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc='upper left', framealpha=0.9)

    ax.set_title('(B) Stability: Jitter and Screen Drift', fontweight='bold', pad=10)


def plot_latency_analysis(ax, metrics: Dict[str, pd.DataFrame], df: pd.DataFrame):
    """
    (C) 响应性：时延分布和分解
    """
    latency = metrics['latency']

    # 时延分布（箱线图）
    latency_data = []
    for condition in CONDITION_ORDER:
        subset = df[
            (df['rq1_metric'] == condition) &
            (df['capture_to_render_ms'].notna())
        ]
        if len(subset) > 0:
            latency_data.append(subset['capture_to_render_ms'].values)
        else:
            latency_data.append([])

    # 绘制箱线图
    bp = ax.boxplot(latency_data,
                    positions=range(len(CONDITION_ORDER)),
                    widths=0.6,
                    patch_artist=True,
                    showfliers=False,  # 不显示离群点
                    medianprops=dict(color='red', linewidth=2),
                    boxprops=dict(facecolor=COLOR_ALIGNED, alpha=0.7, edgecolor='black'),
                    whiskerprops=dict(color='black', linewidth=1),
                    capprops=dict(color='black', linewidth=1))

    # 标注中位数
    for i, cond in enumerate(CONDITION_ORDER):
        if cond in latency['condition'].values:
            median = latency[latency['condition'] == cond]['latency_p50_ms'].iloc[0]
            ax.text(i, median, f'{median:.0f}', ha='center', va='bottom',
                   fontsize=7, fontweight='bold', color='red')

    ax.set_ylabel('End-to-End Latency (ms)', fontweight='bold')
    ax.set_xlabel('Condition', fontweight='bold')
    ax.set_xticks(range(len(CONDITION_ORDER)))
    ax.set_xticklabels([CONDITION_LABELS[c] for c in CONDITION_ORDER], fontsize=8)
    ax.set_ylim(50, 200)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    # 添加整体中位数参考线
    overall_median = df['capture_to_render_ms'].median()
    ax.axhline(overall_median, color='red', linestyle='--', linewidth=1.5, alpha=0.5,
              label=f'Overall Median: {overall_median:.1f} ms')
    ax.legend(loc='upper right', framealpha=0.9)

    ax.set_title('(C) Responsiveness: Latency Distribution', fontweight='bold', pad=10)


def plot_latency_impact(ax, df: pd.DataFrame):
    """
    (D) 时延影响：误差增量 vs 速度
    """
    # 只使用运动场景
    motion_conditions = ['slow_translation', 'fast_motion', 'rotation']
    subset = df[
        (df['rq1_metric'].isin(motion_conditions)) &
        (df['alignment_valid'] == True) &
        (df['gt_linear_velocity_cm_s'].notna())
    ].copy()

    # 计算误差增量（naive - aligned）
    subset['error_increment_mm'] = (
        subset['error_naive_translation_m'] - subset['error_aligned_translation_m']
    ) * 1000

    # 绘制散点图（降采样以提高性能）
    sample_size = min(5000, len(subset))
    sample = subset.sample(n=sample_size, random_state=42)

    # 按条件分组绘制
    colors = {
        'slow_translation': '#3498db',
        'fast_motion': '#e74c3c',
        'rotation': '#2ecc71',
    }

    for condition, color in colors.items():
        cond_data = sample[sample['rq1_metric'] == condition]
        if len(cond_data) > 0:
            ax.scatter(cond_data['gt_linear_velocity_cm_s'],
                      cond_data['error_increment_mm'],
                      alpha=0.3, s=10, color=color,
                      label=CONDITION_LABELS[condition].replace('\n', ' '))

    # 拟合线：error_increment = velocity * latency
    median_latency_s = df['capture_to_render_ms'].median() / 1000.0  # 转换为秒
    v_range = np.array([0, subset['gt_linear_velocity_cm_s'].quantile(0.99)])
    error_pred = v_range * median_latency_s * 10  # cm/s * s * 10 = mm

    ax.plot(v_range, error_pred, 'k--', linewidth=2, alpha=0.8,
           label=f'Theory: Δ = v × {median_latency_s*1000:.0f}ms')

    ax.set_xlabel('Object Velocity (cm/s)', fontweight='bold')
    ax.set_ylabel('Error Increment (mm)\n(Before - After Compensation)', fontweight='bold')
    ax.set_xlim(0, None)
    ax.set_ylim(0, None)
    ax.grid(alpha=0.3, linestyle='--')
    ax.legend(loc='upper left', framealpha=0.9, fontsize=7)

    ax.set_title('(D) Latency Impact: Error vs Velocity', fontweight='bold', pad=10)


def create_comprehensive_figure(metrics: Dict[str, pd.DataFrame],
                                df: pd.DataFrame,
                                output_path: Path):
    """
    创建2x2综合图表
    """
    fig = plt.figure(figsize=(12, 10))
    gs = fig.add_gridspec(2, 2, hspace=0.35, wspace=0.35,
                         left=0.08, right=0.95, top=0.94, bottom=0.06)

    # (A) 精度对比
    ax1 = fig.add_subplot(gs[0, 0])
    plot_accuracy_comparison(ax1, metrics, df)

    # (B) 稳定性分析
    ax2 = fig.add_subplot(gs[0, 1])
    plot_stability_analysis(ax2, metrics)

    # (C) 时延分析
    ax3 = fig.add_subplot(gs[1, 0])
    plot_latency_analysis(ax3, metrics, df)

    # (D) 时延影响
    ax4 = fig.add_subplot(gs[1, 1])
    plot_latency_impact(ax4, df)

    # 保存
    plt.savefig(output_path.with_suffix('.pdf'), dpi=300, bbox_inches='tight')
    plt.savefig(output_path.with_suffix('.png'), dpi=300, bbox_inches='tight')
    print(f"Saved figure to: {output_path}")

    plt.close()


if __name__ == '__main__':
    from pathlib import Path
    from .data_loader import load_and_prepare_data
    from .gt_alignment import align_gt_with_latency, compute_gt_velocity
    from .metrics import compute_all_metrics

    data_dir = Path('p:/VSCode-Project/EgoAnchor/EgoAnchor_Python/data/eval/20260706_163825_controller_right')
    output_dir = Path('p:/VSCode-Project/EgoAnchor/2026-EgoAnchor-Typst/figs/rq1')
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=== Loading and preparing data ===")
    df_clean, df_raw = load_and_prepare_data(data_dir)
    df_aligned = align_gt_with_latency(df_clean, df_raw)
    df_aligned = compute_gt_velocity(df_aligned)

    print("\n=== Computing metrics ===")
    metrics = compute_all_metrics(df_aligned)

    print("\n=== Creating figure ===")
    create_comprehensive_figure(
        metrics,
        df_aligned,
        output_dir / 'fig_rq1_comprehensive'
    )

    print("\nDone!")
