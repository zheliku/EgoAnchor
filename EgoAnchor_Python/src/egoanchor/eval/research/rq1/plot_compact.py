"""
RQ1 Visualization: 4x1 Compact Layout
生成RQ1的紧凑型4×1图表（节省纵向空间）
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path
from typing import Dict


# 设置绘图样式
plt.rcParams['font.family'] = 'Arial'
plt.rcParams['font.size'] = 8
plt.rcParams['axes.labelsize'] = 9
plt.rcParams['axes.titlesize'] = 10
plt.rcParams['xtick.labelsize'] = 7
plt.rcParams['ytick.labelsize'] = 7
plt.rcParams['legend.fontsize'] = 7
plt.rcParams['figure.titlesize'] = 11

# 场景顺序和标签
CONDITION_ORDER = [
    'static_observation',
    'slow_translation',
    'fast_motion',
    'rotation',
    'occlusion_recovery'
]

CONDITION_LABELS = {
    'static_observation': 'Static',
    'slow_translation': 'Slow',
    'fast_motion': 'Fast',
    'rotation': 'Rotation',
    'occlusion_recovery': 'Recovery'
}

# 颜色方案
COLOR_NAIVE = '#e74c3c'
COLOR_ALIGNED = '#3498db'
COLOR_STATIC = '#2ecc71'
COLOR_MOTION = '#f39c12'


def plot_accuracy_comparison(ax, metrics: Dict[str, pd.DataFrame], df: pd.DataFrame):
    """(A) 精度对比"""
    accuracy = metrics['accuracy'].copy()

    # 计算naive误差
    naive_stats = []
    for condition in CONDITION_ORDER:
        subset = df[(df['rq1_metric'] == condition) & (df['alignment_valid'] == True)]
        if len(subset) > 0:
            naive_stats.append({
                'condition': condition,
                'trans_median_mm': subset['error_naive_translation_m'].median() * 1000,
                'trans_p95_mm': subset['error_naive_translation_m'].quantile(0.95) * 1000,
            })
    naive_df = pd.DataFrame(naive_stats)

    x = np.arange(len(CONDITION_ORDER))
    width = 0.35

    for i, cond in enumerate(CONDITION_ORDER):
        if cond not in accuracy['condition'].values:
            continue

        aligned = accuracy[accuracy['condition'] == cond].iloc[0]
        naive = naive_df[naive_df['condition'] == cond]

        # Before compensation
        if len(naive) > 0:
            naive_row = naive.iloc[0]
            ax.bar(x[i] - width/2, naive_row['trans_median_mm'], width * 0.8,
                  color=COLOR_NAIVE, alpha=0.7, edgecolor='black', linewidth=0.5)
            ax.plot([x[i] - width/2, x[i] - width/2],
                   [naive_row['trans_median_mm'], naive_row['trans_p95_mm']],
                   color='black', linewidth=1, alpha=0.6)

        # After compensation
        ax.bar(x[i] + width/2, aligned['trans_median_mm'], width * 0.8,
              color=COLOR_ALIGNED, alpha=0.7, edgecolor='black', linewidth=0.5)
        ax.plot([x[i] + width/2, x[i] + width/2],
               [aligned['trans_median_mm'], aligned['trans_p95_mm']],
               color='black', linewidth=1, alpha=0.6)

    ax.set_ylabel('Translation Error (mm)', fontweight='bold', fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([CONDITION_LABELS[c] for c in CONDITION_ORDER], fontsize=7)
    ax.set_ylim(0, None)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    legend_elements = [
        mpatches.Patch(color=COLOR_NAIVE, alpha=0.7, label='Before'),
        mpatches.Patch(color=COLOR_ALIGNED, alpha=0.7, label='After'),
        plt.Line2D([0], [0], color='black', linewidth=1, label='P95'),
    ]
    ax.legend(handles=legend_elements, loc='upper left', framealpha=0.9, fontsize=6)
    ax.set_title('(A) Accuracy', fontweight='bold', pad=5, fontsize=9)


def plot_stability_analysis(ax, metrics: Dict[str, pd.DataFrame]):
    """(B) 稳定性分析"""
    jitter = metrics['jitter']
    screen = metrics['screen_drift']

    motion_conditions = ['slow_translation', 'fast_motion', 'rotation']

    static_jitter = jitter[jitter['condition'] == 'static_observation'].iloc[0]
    motion_jitter = jitter[jitter['condition'].isin(motion_conditions)]

    static_screen = screen[screen['condition'] == 'static_observation'].iloc[0]
    motion_screen = screen[screen['condition'].isin(motion_conditions)]

    motion_jitter_pos = motion_jitter['position_jitter_rms_mm'].mean()
    motion_screen_drift = motion_screen['screen_drift_median_px'].mean()

    x = np.arange(2)
    width = 0.35

    bars1 = ax.bar(x - width/2, [static_jitter['position_jitter_rms_mm'], motion_jitter_pos],
                   width, label='Jitter (mm)', color=COLOR_STATIC, alpha=0.7,
                   edgecolor='black', linewidth=0.5)

    for bar in bars1:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}' if height < 1 else f'{height:.1f}',
                ha='center', va='bottom', fontsize=6)

    ax2 = ax.twinx()
    bars2 = ax2.bar(x + width/2, [static_screen['screen_drift_median_px'], motion_screen_drift],
                    width, label='Drift (px)', color=COLOR_MOTION, alpha=0.7,
                    edgecolor='black', linewidth=0.5)

    for bar in bars2:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                 f'{height:.1f}', ha='center', va='bottom', fontsize=6)

    ax.set_ylabel('Jitter (mm)', fontweight='bold', color=COLOR_STATIC, fontsize=8)
    ax2.set_ylabel('Drift (px)', fontweight='bold', color=COLOR_MOTION, fontsize=8)
    ax.tick_params(axis='y', labelcolor=COLOR_STATIC, labelsize=7)
    ax2.tick_params(axis='y', labelcolor=COLOR_MOTION, labelsize=7)

    ax.set_xticks(x)
    ax.set_xticklabels(['Static', 'Motion'], fontsize=7)
    ax.set_ylim(0, None)
    ax2.set_ylim(0, None)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc='upper left', framealpha=0.9, fontsize=6)
    ax.set_title('(B) Stability', fontweight='bold', pad=5, fontsize=9)


def plot_latency_analysis(ax, metrics: Dict[str, pd.DataFrame], df: pd.DataFrame):
    """(C) 响应性"""
    latency_data = []
    for condition in CONDITION_ORDER:
        subset = df[(df['rq1_metric'] == condition) & (df['capture_to_render_ms'].notna())]
        if len(subset) > 0:
            latency_data.append(subset['capture_to_render_ms'].values)
        else:
            latency_data.append([])

    bp = ax.boxplot(latency_data, positions=range(len(CONDITION_ORDER)), widths=0.5,
                    patch_artist=True, showfliers=False,
                    medianprops=dict(color='red', linewidth=1.5),
                    boxprops=dict(facecolor=COLOR_ALIGNED, alpha=0.7, edgecolor='black'),
                    whiskerprops=dict(color='black', linewidth=0.8),
                    capprops=dict(color='black', linewidth=0.8))

    latency = metrics['latency']
    for i, cond in enumerate(CONDITION_ORDER):
        if cond in latency['condition'].values:
            median = latency[latency['condition'] == cond]['latency_p50_ms'].iloc[0]
            ax.text(i, median, f'{median:.0f}', ha='center', va='bottom',
                   fontsize=6, fontweight='bold', color='red')

    ax.set_ylabel('Latency (ms)', fontweight='bold', fontsize=8)
    ax.set_xticks(range(len(CONDITION_ORDER)))
    ax.set_xticklabels([CONDITION_LABELS[c] for c in CONDITION_ORDER], fontsize=7)
    ax.set_ylim(50, 200)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    overall_median = df['capture_to_render_ms'].median()
    ax.axhline(overall_median, color='red', linestyle='--', linewidth=1, alpha=0.5,
              label=f'Median: {overall_median:.0f}ms')
    ax.legend(loc='upper right', framealpha=0.9, fontsize=6)
    ax.set_title('(C) Responsiveness', fontweight='bold', pad=5, fontsize=9)


def plot_latency_impact(ax, df: pd.DataFrame):
    """(D) 时延影响"""
    motion_conditions = ['slow_translation', 'fast_motion', 'rotation']
    subset = df[
        (df['rq1_metric'].isin(motion_conditions)) &
        (df['alignment_valid'] == True) &
        (df['gt_linear_velocity_cm_s'].notna())
    ].copy()

    subset['error_increment_mm'] = (
        subset['error_naive_translation_m'] - subset['error_aligned_translation_m']
    ) * 1000

    sample_size = min(3000, len(subset))
    sample = subset.sample(n=sample_size, random_state=42)

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
                      alpha=0.2, s=5, color=color,
                      label=CONDITION_LABELS[condition])

    median_latency_s = df['capture_to_render_ms'].median() / 1000.0
    v_range = np.array([0, subset['gt_linear_velocity_cm_s'].quantile(0.99)])
    error_pred = v_range * median_latency_s * 10

    ax.plot(v_range, error_pred, 'k--', linewidth=1.5, alpha=0.8,
           label=f'Theory: Δ=v×{median_latency_s*1000:.0f}ms')

    ax.set_xlabel('Velocity (cm/s)', fontweight='bold', fontsize=8)
    ax.set_ylabel('Error Increment (mm)', fontweight='bold', fontsize=8)
    ax.set_xlim(0, None)
    ax.set_ylim(0, None)
    ax.grid(alpha=0.3, linestyle='--')
    ax.legend(loc='upper left', framealpha=0.9, fontsize=6)
    ax.set_title('(D) Latency Impact', fontweight='bold', pad=5, fontsize=9)


def create_compact_figure(metrics: Dict[str, pd.DataFrame],
                         df: pd.DataFrame,
                         output_path: Path):
    """创建4×1紧凑图表"""
    fig, axes = plt.subplots(1, 4, figsize=(11, 2.5))

    plot_accuracy_comparison(axes[0], metrics, df)
    plot_stability_analysis(axes[1], metrics)
    plot_latency_analysis(axes[2], metrics, df)
    plot_latency_impact(axes[3], df)

    plt.tight_layout(pad=0.5, w_pad=1.5)

    plt.savefig(output_path.with_suffix('.pdf'), dpi=300, bbox_inches='tight')
    plt.savefig(output_path.with_suffix('.png'), dpi=300, bbox_inches='tight')
    print(f"Saved figure to: {output_path}")

    plt.close()


if __name__ == '__main__':
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

    from egoanchor.eval.research.rq1.data_loader import load_and_prepare_data
    from egoanchor.eval.research.rq1.gt_alignment import align_gt_with_latency, compute_gt_velocity
    from egoanchor.eval.research.rq1.metrics import compute_all_metrics

    data_dir = Path('p:/VSCode-Project/EgoAnchor/EgoAnchor_Python/data/eval/20260706_163825_controller_right')
    output_dir = Path('p:/VSCode-Project/EgoAnchor/2026-EgoAnchor-Typst/figs/rq1')
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading and preparing data...")
    df_clean, df_raw = load_and_prepare_data(data_dir)
    df_aligned = align_gt_with_latency(df_clean, df_raw)
    df_aligned = compute_gt_velocity(df_aligned)

    print("\nComputing metrics...")
    metrics = compute_all_metrics(df_aligned)

    print("\nCreating compact 4x1 figure...")
    create_compact_figure(metrics, df_aligned, output_dir / 'fig_rq1_compact')

    print("\nDone!")
