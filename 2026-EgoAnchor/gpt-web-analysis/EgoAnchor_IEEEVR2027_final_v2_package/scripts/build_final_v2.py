from __future__ import annotations

import csv
import math
import re
import shutil
import subprocess
import zipfile
from collections import defaultdict
from pathlib import Path

import fitz
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path('/mnt/data')
SRC_ZIP = ROOT / 'EgoAnchor_IEEEVR2027_final_package.zip'
WORK = ROOT / '_egoanchor_final_v2_work'
OUT = ROOT / 'EgoAnchor_IEEEVR2027_final_v2'

for path in (WORK, OUT):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)

with zipfile.ZipFile(SRC_ZIP) as zf:
    zf.extractall(WORK)

for sub in ['paper', 'figures/generated', 'figures/panels', 'tables', 'data', 'scripts']:
    (OUT / sub).mkdir(parents=True, exist_ok=True)

# Copy unchanged support files first.
shutil.copy2(WORK / 'paper' / 'egoanchor_cn_refs.bib', OUT / 'paper' / 'egoanchor_cn_refs.bib')
shutil.copy2(WORK / 'figures' / 'pipeline.png', OUT / 'figures' / 'pipeline.png')
for src in (WORK / 'data').glob('*'):
    if src.is_file():
        shutil.copy2(src, OUT / 'data' / src.name)
for src in (WORK / 'scripts').glob('*'):
    if src.is_file():
        shutil.copy2(src, OUT / 'scripts' / src.name)

# -----------------------------------------------------------------------------
# Load audited plotted values. No large XLSX is loaded in this revision pass.
# -----------------------------------------------------------------------------
rows = list(csv.DictReader((WORK / 'data' / 'final_figure_event_data.csv').open(encoding='utf-8-sig')))

methods = ['Arrival-Hold', 'Capture-Hold', 'One-Euro Anchor', 'EgoAnchor']
short = {
    'Arrival-Hold': 'Arrival',
    'Capture-Hold': 'Capture',
    'One-Euro Anchor': 'One-Euro',
    'EgoAnchor': 'EgoAnchor',
}
markers = ['s', 'o', '^', 'D']

static = defaultdict(list)
translation = defaultdict(list)
occlusion = defaultdict(list)
cap = {'full': [], 'disabled': []}
lock = {'full': [], 'disabled': []}
vcd = {'full': [], 'disabled': []}
synth = {'full': [], 'disabled': []}

for r in rows:
    fig, panel = r['figure'], r['panel']
    label = r['method_or_variant']
    x = float(r['x']) if r['x'] else None
    y = float(r['y']) if r['y'] else None
    if fig == 'Fig3':
        if panel == 'world_consistency':
            static[label].append(y)
        elif panel == 'translation_tradeoff':
            translation[label].append((x, y))
        elif panel == 'failure_containment':
            occlusion[label].append(y)
    elif fig == 'Fig4':
        target = {'capture_alignment': cap, 'static_lock': lock, 'vcd': vcd, 'synthesis': synth}[panel]
        target[label].append((x, y) if x is not None else y)

# New externally-facing data file: no software-log "event" terminology.
with (OUT / 'data' / 'final_figure_segment_data.csv').open('w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['figure', 'panel', 'method_or_variant', 'segment_id', 'x', 'y', 'unit_x', 'unit_y'])
    for method in methods:
        for idx, value in enumerate(static[method], 1):
            w.writerow(['Fig3', 'world_consistency', method, f'head_motion_{idx:02d}', '', value, '', 'mm'])
        for idx, (lag, residual) in enumerate(translation[method], 1):
            w.writerow(['Fig3', 'translation_tradeoff', method, f'translation_{idx:02d}', lag, residual, 'ms', 'mm'])
        for idx, value in enumerate(occlusion[method], 1):
            w.writerow(['Fig3', 'failure_containment', method, f'occlusion_{idx:02d}', '', value, '', 'mm'])
    for key, values, prefix in [
        ('capture_alignment', cap, 'head_motion'),
        ('static_lock', lock, 'head_motion'),
        ('vcd', vcd, 'occlusion'),
    ]:
        for state in ['full', 'disabled']:
            for idx, value in enumerate(values[state], 1):
                w.writerow(['Fig4', key, state, f'{prefix}_{idx:02d}', '', value, '', 'mm'])
    for state in ['full', 'disabled']:
        for idx, (lag, residual) in enumerate(synth[state], 1):
            w.writerow(['Fig4', 'synthesis', state, f'translation_{idx:02d}', lag, residual, 'ms', 'mm'])

# Verified from the five workbook sheet_index sheets.
collection_rows = [
    ['scenario_sessions', 5, 'continuous scenario-specific sessions'],
    ['unique_render_timestamps', 29316, 'unique display timeline samples before configuration replay'],
    ['visual_pose_candidates', 6838, 'visual-backend pose candidates'],
    ['configuration_frame_records', 234528, '29,316 timestamps replayed through 8 runtime configurations'],
]
with (OUT / 'data' / 'collection_scale.csv').open('w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['quantity', 'count', 'interpretation'])
    w.writerows(collection_rows)

# -----------------------------------------------------------------------------
# Plot styling.
# -----------------------------------------------------------------------------
plt.rcParams.update({
    'font.family': 'DejaVu Sans',
    'font.size': 10.2,
    'axes.titlesize': 12.3,
    'axes.labelsize': 10.5,
    'xtick.labelsize': 8.9,
    'ytick.labelsize': 8.9,
    'legend.fontsize': 8.8,
    'axes.linewidth': 0.9,
    'savefig.dpi': 260,
})


def clean(ax, grid='y'):
    if grid:
        ax.grid(axis=grid, linestyle=':', linewidth=0.75, alpha=0.35)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)


def save(fig, stem, folder='generated'):
    png = OUT / 'figures' / folder / f'{stem}.png'
    pdf = OUT / 'figures' / folder / f'{stem}.pdf'
    fig.savefig(png, bbox_inches='tight', pad_inches=0.06)
    fig.savefig(pdf, bbox_inches='tight', pad_inches=0.06)
    plt.close(fig)
    return png, pdf


def summary_panel(data, title, subtitle, ylabel, stem):
    fig, ax = plt.subplots(figsize=(4.55, 3.65))
    xs = np.arange(len(methods))
    for idx, method in enumerate(methods):
        vals = np.asarray(data[method], dtype=float)
        offsets = np.linspace(-0.11, 0.11, len(vals))
        sc = ax.scatter(xs[idx] + offsets, vals, s=25, alpha=0.46, marker=markers[idx])
        color = sc.get_facecolor()[0]
        med = float(np.median(vals))
        q1, q3 = np.quantile(vals, [0.25, 0.75])
        ax.errorbar(xs[idx], med, yerr=[[med-q1], [q3-med]], fmt=markers[idx],
                    markersize=7.5, capsize=4, linewidth=1.8, color=color)
    ax.set_xticks(xs, [short[m] for m in methods], rotation=16, ha='right')
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc='left', fontweight='bold', pad=15)
    ax.text(0, 1.01, subtitle, transform=ax.transAxes, ha='left', va='bottom', fontsize=9.1)
    ax.set_ylim(bottom=0)
    clean(ax)
    fig.tight_layout()
    return save(fig, stem, 'panels')

# Fig. 3 panels with segment/episode language.
p1 = summary_panel(
    static,
    '(a) World consistency',
    'Head motion should not move a static anchor',
    'Segment-wise translation P95 (mm)',
    'fig3a_world_consistency_v2',
)

fig, ax = plt.subplots(figsize=(4.7, 3.65))
for idx, method in enumerate(methods):
    pts = np.asarray(translation[method], dtype=float)
    sc = ax.scatter(pts[:, 0], pts[:, 1], s=24, alpha=0.28,
                    marker=markers[idx], label=short[method])
    color = sc.get_facecolor()[0]
    mx, my = np.median(pts, axis=0)
    x1, x3 = np.quantile(pts[:, 0], [0.25, 0.75])
    y1, y3 = np.quantile(pts[:, 1], [0.25, 0.75])
    ax.errorbar(mx, my, xerr=[[mx-x1], [x3-mx]], yerr=[[my-y1], [y3-my]],
                fmt=markers[idx], markersize=8, capsize=3.5, linewidth=1.7, color=color)
ax.set_xlabel('Effective lag (ms)')
ax.set_ylabel('Lag-aligned translation RMSE (mm)')
ax.set_title('(b) Dynamic translation', loc='left', fontweight='bold', pad=15)
ax.text(0, 1.01, 'Lag and residual form a paired trade-off', transform=ax.transAxes,
        ha='left', va='bottom', fontsize=9.1)
ax.annotate('better', xy=(0.07, 0.08), xytext=(0.26, 0.24),
            xycoords='axes fraction', textcoords='axes fraction',
            arrowprops={'arrowstyle': '->', 'linewidth': 0.9})
clean(ax, grid='both')
ax.legend(frameon=False, ncol=2, loc='upper center')
fig.tight_layout()
p2 = save(fig, 'fig3b_dynamic_translation_v2', 'panels')

p3 = summary_panel(
    occlusion,
    '(c) Failure containment',
    'Low-quality updates should not corrupt the anchor',
    'Occlusion-episode translation P95 (mm)',
    'fig3c_failure_containment_v2',
)

# Combine Fig. 3 panels as a vector PDF.
def combine_pdf(srcs, out, cols, gap=8, pad=5):
    docs = [fitz.open(str(p)) for p in srcs]
    rects = [d[0].rect for d in docs]
    rows_n = math.ceil(len(docs) / cols)
    cw = max(r.width for r in rects)
    ch = max(r.height for r in rects)
    output = fitz.open()
    page = output.new_page(width=pad*2 + cols*cw + (cols-1)*gap,
                           height=pad*2 + rows_n*ch + (rows_n-1)*gap)
    for idx, (doc, rect) in enumerate(zip(docs, rects)):
        rr, cc = divmod(idx, cols)
        x = pad + cc*(cw+gap) + (cw-rect.width)/2
        y = pad + rr*(ch+gap) + (ch-rect.height)/2
        page.show_pdf_page(fitz.Rect(x, y, x+rect.width, y+rect.height), doc, 0)
    output.save(str(out))
    output.close()
    for doc in docs:
        doc.close()


def render_pdf_png(pdf, png, dpi=220):
    doc = fitz.open(str(pdf))
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72), alpha=False)
    pix.save(str(png))
    doc.close()

fig3_pdf = OUT / 'figures' / 'generated' / 'exp1_final_v2.pdf'
fig3_png = OUT / 'figures' / 'generated' / 'exp1_final_v2.png'
combine_pdf([p1[1], p2[1], p3[1]], fig3_pdf, cols=3)
render_pdf_png(fig3_pdf, fig3_png)

# -----------------------------------------------------------------------------
# Merged Fig. 4: two logical panels, not four equal independent panels.
# -----------------------------------------------------------------------------
fig = plt.figure(figsize=(12.0, 3.85))
outer = fig.add_gridspec(1, 2, width_ratios=[1.68, 1.0], wspace=0.30)
left = outer[0].subgridspec(1, 3, wspace=0.42)


def paired_small(ax, full_values, disabled_values, title, subtitle, ylabel):
    for fval, aval in zip(full_values, disabled_values):
        ax.plot([0, 1], [fval, aval], marker='o', linewidth=0.9, alpha=0.40,
                markersize=3.5)
    med = [np.median(full_values), np.median(disabled_values)]
    ax.plot([0, 1], med, marker='D', linewidth=2.35, markersize=6.5)
    ax.set_xticks([0, 1], ['Full', 'Disabled'])
    ax.set_xlim(-0.20, 1.20)
    ax.set_ylim(bottom=0)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontweight='bold', pad=17, fontsize=10.8)
    ax.text(0.5, 1.01, subtitle, transform=ax.transAxes, ha='center', va='bottom',
            fontsize=7.9)
    clean(ax)

ax1 = fig.add_subplot(left[0, 0])
paired_small(ax1, cap['full'], cap['disabled'], 'Capture alignment',
             'prevents head-motion leakage', 'Segment P95 (mm)')
ax2 = fig.add_subplot(left[0, 1])
paired_small(ax2, lock['full'], lock['disabled'], 'StaticLock',
             'stabilizes the resting anchor', 'Stationary median (mm)')
ax3 = fig.add_subplot(left[0, 2])
paired_small(ax3, vcd['full'], vcd['disabled'], 'VCD admission',
             'rejects harmful occlusion updates', 'Occlusion P95 (mm)')

ax4 = fig.add_subplot(outer[0, 1])
full = np.asarray(synth['full'], dtype=float)
disabled = np.asarray(synth['disabled'], dtype=float)
for fpoint, dpoint in zip(full, disabled):
    ax4.plot([fpoint[0], dpoint[0]], [fpoint[1], dpoint[1]], linewidth=0.82, alpha=0.26)
ax4.scatter(full[:, 0], full[:, 1], marker='D', s=27, alpha=0.42, label='Full')
ax4.scatter(disabled[:, 0], disabled[:, 1], marker='X', s=34, alpha=0.42,
            label='Synthesis disabled')
ax4.scatter(*np.median(full, axis=0), marker='D', s=95)
ax4.scatter(*np.median(disabled, axis=0), marker='X', s=110)
ax4.set_xlabel('Effective lag (ms)')
ax4.set_ylabel('Lag-aligned translation RMSE (mm)')
ax4.set_title('(b) Temporal synthesis trade-off', loc='left', fontweight='bold', pad=17)
ax4.text(0, 1.01, 'additional delay buys a more faithful continuous trajectory',
         transform=ax4.transAxes, ha='left', va='bottom', fontsize=8.6)
ax4.annotate('better', xy=(0.07, 0.08), xytext=(0.25, 0.24),
             xycoords='axes fraction', textcoords='axes fraction',
             arrowprops={'arrowstyle': '->', 'linewidth': 0.9})
clean(ax4, grid='both')
ax4.legend(frameon=False, loc='upper right')

# One overarching label for the three compact attribution plots.
fig.text(0.012, 0.985, '(a) Targeted component effects', ha='left', va='top',
         fontweight='bold', fontsize=12.3)
fig.subplots_adjust(left=0.055, right=0.99, top=0.80, bottom=0.20)
fig4_png, fig4_pdf = save(fig, 'exp2_merged_final_v2', 'generated')

# Also retain a panel copy for convenience.
shutil.copy2(fig4_png, OUT / 'figures' / 'panels' / 'fig4_merged.png')
shutil.copy2(fig4_pdf, OUT / 'figures' / 'panels' / 'fig4_merged.pdf')

# -----------------------------------------------------------------------------
# Paper text patches.
# -----------------------------------------------------------------------------

def patch_text(text: str, standalone: bool) -> str:
    # Rename generated figure paths.
    text = text.replace('../figures/generated/exp1_final.pdf', '../figures/generated/exp1_final_v2.pdf')
    text = text.replace('../figures/generated/exp2_final.pdf', '../figures/generated/exp2_merged_final_v2.pdf')
    text = text.replace('figures/generated/exp1_final.pdf', '../figures/generated/exp1_final_v2.pdf')
    text = text.replace('figures/generated/exp2_final.pdf', '../figures/generated/exp2_merged_final_v2.pdf')

    # Abstract: remove the undefined event terminology.
    text = text.replace(
        '并在同一视觉候选流、渲染时间线和平台参考下进行事件级配对表征。静止头动时，EgoAnchor 的平移 event-P95 为 3.679~mm，',
        '并在同一视觉候选流、渲染时间线和平台参考下进行配对系统表征。静止头动时，EgoAnchor 的片段内平移 P95 为 3.679~mm，'
    )

    # Replace the experiment-design/statistics paragraph as a whole.
    old_design = re.compile(
        r'数据由五个场景专用 session 构成，每个场景采集一条连续 trial，并在其中预先标记重复事件：.*?事件间波动解释为跨环境或跨操作者的总体推断。',
        re.S
    )
    new_design = (
        '数据由五个场景专用连续 session 构成，共记录 29,316 个唯一渲染时刻与 6,838 个视觉位姿候选。'
        '相同数据流在 8 种运行时配置下同步回放后形成 234,528 条 configuration--frame records；'
        '该记录数反映配对重放规模，并不代表 234,528 次独立采集。相邻渲染帧具有强时间相关性，'
        '因此帧仅用于重建连续轨迹，不作为独立统计样本。各指标首先在预定义的重复动作片段或遮挡过程内计算，'
        '再汇总片段间的 median [IQR]。由于每个场景仅有一条连续 trial，本文不进行帧级显著性检验，'
        '也不将片段间波动解释为跨环境或跨操作者的总体推断。'
    )
    text, count = old_design.subn(new_design, text)
    if count != 1:
        raise RuntimeError(f'Could not replace design paragraph, matches={count}')

    replacements = {
        '图~\\ref{fig:exp1-final} 叠加全部事件点与 median--IQR 汇总。':
            '图~\\ref{fig:exp1-final} 叠加全部重复动作实例与 median--IQR 汇总。',
        '实验一的事件级系统表征，数值为 median。':
            '实验一的片段级系统表征，数值为重复动作片段或遮挡过程的 median。',
        '完整 IQR 与逐事件分布见图~\\ref{fig:exp1-final}。':
            '完整 IQR 与片段分布见图~\\ref{fig:exp1-final}。',
        '平移 event-P95': '片段内平移 P95',
        '实验一的核心系统行为。事件级散点叠加在 median--IQR 汇总上。':
            '实验一的核心系统行为。小标记表示重复动作片段或遮挡过程，大标记与误差棒表示 median--IQR。',
        '表~\\ref{tab:exp2-final} 以完整系统为锚点报告关闭组件后的事件级变化，图~\\ref{fig:exp2-final} 展示同一事件的 Full--Disabled 配对。':
            '表~\\ref{tab:exp2-final} 以完整系统为锚点报告关闭组件后的片段级变化，图~\\ref{fig:exp2-final} 将三个目标组件效应合并，并以独立面板呈现时序合成的时延--残差权衡。',
        '“关闭后的效应”是消融减完整系统的事件级 median [IQR]。':
            '“关闭后的效应”是消融减完整系统的片段级 median [IQR]。',
        '4/4 个头动事件变差': '所有重复头动片段均变差',
        '实验二的事件级组件归因。每条细线连接同一事件的完整系统与关闭组件后的结果；粗线或大标记表示中位数。采集时刻对齐防止头动泄漏，StaticLock 稳定静止锚点，VCD 在遮挡时拒绝有害更新，时序合成则以额外时延换取更低的 lag-aligned 轨迹残差。前三个绝对误差面板从零开始；右下权衡图按数据范围缩放。':
            '实验二的组件归因被合并为两个逻辑面板。左侧三个紧凑配对图分别显示采集时刻对齐、StaticLock 与 VCD 的目标效应；每条细线连接同一重复动作片段或遮挡过程的 Full--Disabled 结果，粗线表示中位数。右侧单独显示时序合成的 fitted-lag--aligned-residual 权衡。左侧绝对误差坐标从零开始，右侧权衡图按数据范围缩放。',
        '关闭采集时刻对齐后，4/4 个头动事件均向不利方向变化，':
            '关闭采集时刻对齐后，所有重复头动片段均向不利方向变化，',
        '在每个事件内通过冻结 lag 网格搜索得到':
            '在每个连续动作片段内通过冻结 lag 网格搜索得到',
        '本文以 median [IQR] 和同事件配对差值为主':
            '本文以 median [IQR] 和同一动作片段内的配对差值为主',
        '候选级 VCD risk--coverage 独立于事件级系统比较':
            '候选级 VCD risk--coverage 独立于片段级系统比较',
        '所有参数、事件边界和指标契约':
            '所有参数、动作片段边界和指标契约',
        '完整逐事件表、图源数据和流式解析脚本':
            '完整片段级表、图源数据和流式解析脚本',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Remove obsolete FloatBarrier directly after Fig. 3 only if duplicated by previous build.
    text = text.replace('\\end{figure*}\n\\FloatBarrier\n\n\\subsection{实验二：组件归因}',
                        '\\end{figure*}\n\n\\subsection{实验二：组件归因}')

    # Ensure the merged figure uses a little more width.
    text = text.replace('\\includegraphics[width=0.92\\textwidth]{../figures/generated/exp2_merged_final_v2.pdf}',
                        '\\includegraphics[width=0.99\\textwidth]{../figures/generated/exp2_merged_final_v2.pdf}')

    return text

src_standalone = WORK / 'paper' / 'EgoAnchor_IEEEVR2027_final_standalone.tex'
src_vgtc = WORK / 'paper' / 'EgoAnchor_IEEEVR2027_final_vgtc.tex'

standalone_text = patch_text(src_standalone.read_text(encoding='utf-8'), True)
vgtc_text = patch_text(src_vgtc.read_text(encoding='utf-8'), False)

standalone_name = 'EgoAnchor_IEEEVR2027_final_v2_standalone.tex'
vgtc_name = 'EgoAnchor_IEEEVR2027_final_v2_vgtc.tex'
(OUT / 'paper' / standalone_name).write_text(standalone_text, encoding='utf-8')
(OUT / 'paper' / vgtc_name).write_text(vgtc_text, encoding='utf-8')

# Extract updated table snippets from the standalone source.
for label, table_id in [
    ('experiment1_final_v2_table.tex', 'tab:exp1-final'),
    ('experiment2_final_v2_table.tex', 'tab:exp2-final'),
]:
    pattern = re.compile(r'\\begin\{table\*\}\[t\].*?\\label\{' + re.escape(table_id) + r'\}.*?\\end\{table\*\}', re.S)
    match = pattern.search(standalone_text)
    if not match:
        raise RuntimeError(f'Could not extract {table_id}')
    (OUT / 'tables' / label).write_text(match.group(0), encoding='utf-8')

# Save the revision script itself.
shutil.copy2(Path(__file__), OUT / 'scripts' / 'build_final_v2.py')

# -----------------------------------------------------------------------------
# Compile standalone TeX.
# -----------------------------------------------------------------------------
paper_dir = OUT / 'paper'
stem = standalone_name[:-4]
build_log = []
commands = [
    ['xelatex', '-interaction=nonstopmode', '-halt-on-error', standalone_name],
    ['bibtex.original', stem],
    ['xelatex', '-interaction=nonstopmode', '-halt-on-error', standalone_name],
    ['xelatex', '-interaction=nonstopmode', '-halt-on-error', standalone_name],
]
for cmd in commands:
    proc = subprocess.run(cmd, cwd=paper_dir, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    build_log.append('$ ' + ' '.join(cmd) + '\n' + proc.stdout)
    if proc.returncode != 0:
        (paper_dir / 'build_v2.log').write_text('\n'.join(build_log), encoding='utf-8')
        raise RuntimeError(proc.stdout[-5000:])
(paper_dir / 'build_v2.log').write_text('\n'.join(build_log), encoding='utf-8')

compiled_pdf = paper_dir / f'{stem}.pdf'
final_pdf = paper_dir / 'EgoAnchor_IEEEVR2027_final_v2.pdf'
shutil.copy2(compiled_pdf, final_pdf)

# Top-level convenience copies.
shutil.copy2(final_pdf, ROOT / 'EgoAnchor_IEEEVR2027_final_v2.pdf')
shutil.copy2(paper_dir / standalone_name, ROOT / standalone_name)
shutil.copy2(paper_dir / vgtc_name, ROOT / vgtc_name)

notes = '''# EgoAnchor IEEE VR 2027 - Final v2 revision

This revision implements two presentation changes:

1. The paper no longer exposes the internal term `event` as the primary statistical unit. It reports the acquisition scale (5 continuous sessions, 29,316 unique render timestamps, 6,838 visual candidates, and 234,528 configuration-frame records) while retaining a statistically valid segment-wise analysis. Frames reconstruct continuous trajectories and are not treated as independent samples.
2. Experiment 2 is merged into two logical panels: three compact targeted component-effect plots and one temporal-synthesis lag-residual trade-off plot.

The package includes the final PDF, standalone and VGTC TeX sources, vector/PNG figures, LaTeX table snippets, segment-level plot data, collection-scale metadata, and the rebuild script.
'''
(OUT / 'README.md').write_text(notes, encoding='utf-8')

# Remove old event-named external figure-data file from the new package to avoid confusion.
old_data = OUT / 'data' / 'final_figure_event_data.csv'
if old_data.exists():
    old_data.unlink()

zip_path = ROOT / 'EgoAnchor_IEEEVR2027_final_v2_package.zip'
if zip_path.exists():
    zip_path.unlink()
shutil.make_archive(str(zip_path.with_suffix('')), 'zip', OUT)

print(final_pdf)
print(ROOT / standalone_name)
print(ROOT / vgtc_name)
print(zip_path)
