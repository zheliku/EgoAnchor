"""
RQ1 Complete Analysis Pipeline
完整的RQ1分析流程
"""

from pathlib import Path
import sys
import pandas as pd

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from egoanchor.eval.research.rq1.data_loader import load_and_prepare_data
from egoanchor.eval.research.rq1.gt_alignment import align_gt_with_latency, compute_gt_velocity
from egoanchor.eval.research.rq1.metrics import compute_all_metrics
from egoanchor.eval.research.rq1.plot_comprehensive import create_comprehensive_figure


def main():
    # 配置路径
    data_dir = Path('p:/VSCode-Project/EgoAnchor/EgoAnchor_Python/data/eval/20260706_163825_controller_right')
    output_dir = Path('p:/VSCode-Project/EgoAnchor/2026-EgoAnchor-Typst/figs/rq1')
    report_dir = data_dir / 'rq1_analysis'

    # 创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("RQ1 Complete Analysis Pipeline")
    print("=" * 80)

    # Step 1: 加载和清洗数据
    print("\n[1/5] Loading and cleaning data...")
    df_clean, df_raw = load_and_prepare_data(data_dir)

    # Step 2: GT时延对齐
    print("\n[2/5] Aligning GT with latency compensation...")
    df_aligned = align_gt_with_latency(df_clean, df_raw, latency_ms=None)

    # Step 3: 计算GT速度
    print("\n[3/5] Computing GT velocity...")
    df_aligned = compute_gt_velocity(df_aligned)

    # Step 4: 计算所有指标
    print("\n[4/5] Computing all metrics...")
    metrics = compute_all_metrics(df_aligned)

    # Step 5: 生成可视化
    print("\n[5/5] Creating visualizations...")
    create_comprehensive_figure(
        metrics,
        df_aligned,
        output_dir / 'fig_rq1_comprehensive'
    )

    # 导出结果
    print("\n" + "=" * 80)
    print("Exporting results...")
    print("=" * 80)

    # 保存指标摘要
    for metric_name, metric_df in metrics.items():
        output_file = report_dir / f'{metric_name}_summary.csv'
        metric_df.to_csv(output_file, index=False)
        print(f"Saved: {output_file}")

    # 保存详细数据（用于进一步分析）
    detail_file = report_dir / 'rq1_data_aligned.csv'
    df_aligned.to_csv(detail_file, index=False)
    print(f"Saved: {detail_file}")

    # 打印关键结果摘要
    print("\n" + "=" * 80)
    print("Key Results Summary")
    print("=" * 80)

    print("\n1. ACCURACY (Latency-Compensated):")
    print(metrics['accuracy'].to_string(index=False))

    print("\n2. STABILITY:")
    print(metrics['jitter'].to_string(index=False))

    print("\n3. RESPONSIVENESS:")
    print(metrics['latency'].to_string(index=False))

    print("\n4. LAG:")
    print(metrics['lag'].to_string(index=False))

    print("\n5. SCREEN SPACE DRIFT:")
    print(metrics['screen_drift'].to_string(index=False))

    # 生成LaTeX表格
    print("\n" + "=" * 80)
    print("Generating LaTeX table...")
    print("=" * 80)

    generate_latex_table(metrics, report_dir / 'rq1_results_table.tex')

    print("\n" + "=" * 80)
    print("Analysis complete!")
    print("=" * 80)
    print(f"\nOutputs:")
    print(f"  - Figures: {output_dir}")
    print(f"  - Reports: {report_dir}")


def generate_latex_table(metrics: dict, output_path: Path):
    """生成LaTeX格式的结果表格"""

    accuracy = metrics['accuracy']
    jitter = metrics['jitter']
    latency = metrics['latency']

    # 场景顺序
    conditions = [
        'static_observation',
        'slow_translation',
        'fast_motion',
        'rotation',
        'occlusion_recovery'
    ]

    condition_names = {
        'static_observation': 'Static Observation',
        'slow_translation': 'Slow Translation',
        'fast_motion': 'Fast Motion',
        'rotation': 'Rotation',
        'occlusion_recovery': 'Occlusion Recovery'
    }

    latex = []
    latex.append(r'\begin{table}[t]')
    latex.append(r'\centering')
    latex.append(r'\caption{RQ1 Anchoring Quality Results}')
    latex.append(r'\label{tab:rq1_results}')
    latex.append(r'\begin{tabular}{lrrrrr}')
    latex.append(r'\toprule')
    latex.append(r'Condition & \multicolumn{2}{c}{Translation Error (mm)} & \multicolumn{2}{c}{Rotation Error (deg)} & Latency (ms) \\')
    latex.append(r'\cmidrule(lr){2-3} \cmidrule(lr){4-5}')
    latex.append(r' & Median & P95 & Median & P95 & P50 \\')
    latex.append(r'\midrule')

    for cond in conditions:
        if cond not in accuracy['condition'].values:
            continue

        acc = accuracy[accuracy['condition'] == cond].iloc[0]
        lat = latency[latency['condition'] == cond].iloc[0] if cond in latency['condition'].values else None

        name = condition_names[cond]
        trans_med = acc['trans_median_mm']
        trans_p95 = acc['trans_p95_mm']
        rot_med = acc['rot_median_deg']
        rot_p95 = acc['rot_p95_deg']
        lat_p50 = lat['latency_p50_ms'] if lat is not None else None

        if lat_p50 is not None:
            latex.append(f'{name} & {trans_med:.1f} & {trans_p95:.1f} & {rot_med:.1f} & {rot_p95:.1f} & {lat_p50:.0f} \\\\')
        else:
            latex.append(f'{name} & {trans_med:.1f} & {trans_p95:.1f} & {rot_med:.1f} & {rot_p95:.1f} & --- \\\\')

    latex.append(r'\bottomrule')
    latex.append(r'\end{tabular}')
    latex.append(r'\end{table}')

    output_path.write_text('\n'.join(latex))
    print(f"LaTeX table saved to: {output_path}")


if __name__ == '__main__':
    main()
