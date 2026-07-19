from __future__ import annotations
import json, math, re, shutil, subprocess
from pathlib import Path

import fitz
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path('/mnt/data')
SRC = ROOT / 'EgoAnchor_corrected_newdata_v3'
OUT = ROOT / 'EgoAnchor_corrected_newdata_v4'
if OUT.exists():
    shutil.rmtree(OUT)
shutil.copytree(SRC, OUT)

# -----------------------------------------------------------------------------
# Rebuild the two figures with identical dynamic-panel limits/ticks.
# -----------------------------------------------------------------------------
DATA = OUT / 'data'
T1 = json.loads((DATA / 'task1_corrected_metrics.json').read_text())
T3 = json.loads((DATA / 'task3_translation_metrics.json').read_text())
T5 = json.loads((DATA / 'task5_tail_metrics.json').read_text())
render = T1['render']
align = T1['candidate_alignment']
METHODS = ['Arrival-Hold', 'Capture-Hold', 'One-Euro Anchor', 'EgoAnchor']
SHORT = {'Arrival-Hold':'Arrival', 'Capture-Hold':'Capture', 'One-Euro Anchor':'One-Euro', 'EgoAnchor':'EgoAnchor'}
MARKERS = ['s', 'o', '^', 'D']

# Shared axes for Fig. 2b / Fig. 3b in the paper.
DYN_XLIM = (150, 400)
DYN_YLIM = (0, 21)
DYN_XTICKS = [150, 200, 250, 300, 350, 400]
DYN_YTICKS = [0, 5, 10, 15, 20]

plt.rcParams.update({
    'font.family':'DejaVu Sans', 'font.size':10.2, 'axes.titlesize':12.5,
    'axes.labelsize':10.6, 'xtick.labelsize':9.0, 'ytick.labelsize':9.0,
    'legend.fontsize':8.8, 'axes.linewidth':0.9, 'savefig.dpi':260,
})

def clean(ax, grid='y'):
    if grid:
        ax.grid(axis=grid, linestyle=':', linewidth=0.75, alpha=0.35)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

def save_panel(fig, stem):
    png = OUT / 'figures' / 'panels' / f'{stem}.png'
    pdf = OUT / 'figures' / 'panels' / f'{stem}.pdf'
    fig.savefig(png, bbox_inches='tight', pad_inches=0.06)
    fig.savefig(pdf, bbox_inches='tight', pad_inches=0.06)
    plt.close(fig)
    return png, pdf

def save_generated(fig, stem):
    png = OUT / 'figures' / 'generated' / f'{stem}.png'
    pdf = OUT / 'figures' / 'generated' / f'{stem}.pdf'
    fig.savefig(png, bbox_inches='tight', pad_inches=0.06)
    fig.savefig(pdf, bbox_inches='tight', pad_inches=0.06)
    plt.close(fig)
    return png, pdf

def combine_pdf(srcs, out, cols, gap=8, pad=5):
    docs = [fitz.open(str(p)) for p in srcs]
    rects = [d[0].rect for d in docs]
    rows = math.ceil(len(docs) / cols)
    cw = max(r.width for r in rects)
    ch = max(r.height for r in rects)
    doc = fitz.open()
    page = doc.new_page(width=pad*2 + cols*cw + (cols-1)*gap,
                        height=pad*2 + rows*ch + (rows-1)*gap)
    for i, (src, rect) in enumerate(zip(docs, rects)):
        rr, cc = divmod(i, cols)
        x = pad + cc*(cw+gap) + (cw-rect.width)/2
        y = pad + rr*(ch+gap) + (ch-rect.height)/2
        page.show_pdf_page(fitz.Rect(x, y, x+rect.width, y+rect.height), src, 0)
    doc.save(str(out))
    doc.close()
    for d in docs:
        d.close()

def render_pdf(pdf, png, dpi=220):
    d = fitz.open(str(pdf))
    pix = d[0].get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72), alpha=False)
    pix.save(str(png))
    d.close()

def med_iqr(vals):
    a = np.asarray(vals, float)
    return float(np.median(a)), float(np.quantile(a, .25)), float(np.quantile(a, .75))

def point_panel(data, title, subtitle, ylabel, stem):
    fig, ax = plt.subplots(figsize=(4.55, 3.65))
    xs = np.arange(len(METHODS))
    for i, m in enumerate(METHODS):
        vals = np.asarray(data[m], float)
        offsets = np.linspace(-0.11, 0.11, len(vals))
        sc = ax.scatter(xs[i]+offsets, vals, s=25, alpha=0.46, marker=MARKERS[i])
        color = sc.get_facecolor()[0]
        med, q1, q3 = med_iqr(vals)
        ax.errorbar(xs[i], med, yerr=[[med-q1],[q3-med]], fmt=MARKERS[i],
                    markersize=7.5, capsize=4, linewidth=1.8, color=color)
    ax.set_xticks(xs, [SHORT[m] for m in METHODS], rotation=16, ha='right')
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc='left', fontweight='bold', pad=15)
    ax.text(0, 1.01, subtitle, transform=ax.transAxes, ha='left', va='bottom', fontsize=9.1)
    ax.set_ylim(bottom=0)
    clean(ax)
    fig.tight_layout()
    return save_panel(fig, stem)

# Experiment 1: regenerate all panels to retain exact source consistency.
world = {m:[s['centered_p95_mm'] for s in render[m]['segments']] for m in METHODS}
p1 = point_panel(world, '(a) Head-motion leakage',
                 'Fixed registration offset removed per segment',
                 'Centered translation P95 (mm)', 'exp1a_head_motion_leakage')

fig, ax = plt.subplots(figsize=(4.7, 3.65))
for i, m in enumerate(METHODS):
    pts = np.asarray(T3[m]['lag_residual_segments'], float)
    sc = ax.scatter(pts[:,0], pts[:,1], s=24, alpha=0.28,
                    marker=MARKERS[i], label=SHORT[m])
    color = sc.get_facecolor()[0]
    mx, my = np.median(pts, axis=0)
    x1, x3 = np.quantile(pts[:,0], [.25, .75])
    y1, y3 = np.quantile(pts[:,1], [.25, .75])
    ax.errorbar(mx, my, xerr=[[mx-x1],[x3-mx]], yerr=[[my-y1],[y3-my]],
                fmt=MARKERS[i], markersize=8, capsize=3.5, linewidth=1.7, color=color)
ax.set_xlabel('Effective lag (ms)')
ax.set_ylabel('Lag-aligned translation RMSE (mm)')
ax.set_title('(b) Dynamic translation', loc='left', fontweight='bold', pad=15)
ax.text(0, 1.01, 'Lag and residual are interpreted jointly',
        transform=ax.transAxes, ha='left', va='bottom', fontsize=9.1)
ax.set_xlim(*DYN_XLIM)
ax.set_ylim(*DYN_YLIM)
ax.set_xticks(DYN_XTICKS)
ax.set_yticks(DYN_YTICKS)
ax.annotate('better', xy=(168, 2.2), xytext=(220, 5.4),
            arrowprops={'arrowstyle':'->', 'linewidth':.9})
clean(ax, grid='both')
ax.legend(frameon=False, ncol=2, loc='upper center')
fig.tight_layout()
p2 = save_panel(fig, 'exp1b_dynamic_translation')

occ = {m:[e['translation_p95_mm'] for e in T5[m]['episodes']] for m in METHODS}
p3 = point_panel(occ, '(c) Failure containment',
                 'Episode-level P95 during visual occlusion',
                 'Occlusion translation P95 (mm)', 'exp1c_failure_containment')

exp1_pdf = OUT / 'figures' / 'generated' / 'experiment1_corrected_newdata.pdf'
exp1_png = OUT / 'figures' / 'generated' / 'experiment1_corrected_newdata.png'
combine_pdf([p1[1], p2[1], p3[1]], exp1_pdf, 3)
render_pdf(exp1_pdf, exp1_png)

# Experiment 2 merged.
fig = plt.figure(figsize=(12.3, 3.9))
outer = fig.add_gridspec(1, 2, width_ratios=[1.78, 1.0], wspace=.28)
left = outer[0].subgridspec(1, 3, wspace=.42)

def paired(ax, full, disabled, title, subtitle, ylabel,
           labels=('Enabled','Disabled'), log=False):
    for a, b in zip(full, disabled):
        ax.plot([0,1], [a,b], marker='o', linewidth=.9, alpha=.40, markersize=3.5)
    ax.plot([0,1], [np.median(full),np.median(disabled)],
            marker='D', linewidth=2.35, markersize=6.5)
    ax.set_xticks([0,1], labels)
    ax.set_xlim(-.20,1.20)
    ax.set_ylabel(ylabel)
    if log:
        ax.set_yscale('log')
    else:
        ax.set_ylim(bottom=0)
    ax.set_title(title, fontweight='bold', pad=17, fontsize=10.8)
    ax.text(.5, 1.01, subtitle, transform=ax.transAxes,
            ha='center', va='bottom', fontsize=7.9)
    clean(ax)

arrival = [s['arrival_p95_mm'] for s in align['segments']]
capture = [s['capture_p95_mm'] for s in align['segments']]
ax1 = fig.add_subplot(left[0,0])
paired(ax1, capture, arrival, 'Capture-time alignment',
       'same raw candidates, 4/4 segments improve', 'Candidate P95 (mm)',
       labels=('Capture time','Arrival time'))

full_static = [s['centered_p95_mm'] for s in render['EgoAnchor']['segments']]
no_lock = [s['centered_p95_mm'] for s in render['EgoAnchor w/o StaticLock']['segments']]
ax2 = fig.add_subplot(left[0,1])
paired(ax2, full_static, no_lock, 'StaticLock',
       'removes stationary output fluctuation', 'Centered P95 (mm)')

full_vcd = [e['translation_p95_mm'] for e in T5['EgoAnchor']['episodes']]
no_vcd = [e['translation_p95_mm'] for e in T5['EgoAnchor w/o VCD']['episodes']]
ax3 = fig.add_subplot(left[0,2])
paired(ax3, full_vcd, no_vcd, 'VCD admission',
       '0/9 vs 4/9 catastrophic episodes', 'Occlusion P95 (mm)', log=True)
ax3.axhline(40, linestyle='--', linewidth=1)
ax3.text(.02, 40*1.05, '40-mm failure threshold', fontsize=7.5, va='bottom')

ax4 = fig.add_subplot(outer[0,1])
sf = np.asarray(T3['EgoAnchor']['lag_residual_segments'], float)
sd = np.asarray(T3['EgoAnchor w/o temporal synthesis']['lag_residual_segments'], float)
for f, d in zip(sf, sd):
    ax4.plot([f[0],d[0]], [f[1],d[1]], linewidth=.82, alpha=.26)
ax4.scatter(sf[:,0], sf[:,1], marker='D', s=27, alpha=.42, label='Full')
ax4.scatter(sd[:,0], sd[:,1], marker='X', s=34, alpha=.42, label='Synthesis disabled')
ax4.scatter(*np.median(sf,axis=0), marker='D', s=95)
ax4.scatter(*np.median(sd,axis=0), marker='X', s=110)
ax4.set_xlabel('Effective lag (ms)')
ax4.set_ylabel('Lag-aligned translation RMSE (mm)')
ax4.set_title('(b) Temporal synthesis trade-off', loc='left', fontweight='bold', pad=17)
ax4.text(0, 1.01, 'less delay without synthesis, but substantially larger residual',
         transform=ax4.transAxes, ha='left', va='bottom', fontsize=8.5)
ax4.set_xlim(*DYN_XLIM)
ax4.set_ylim(*DYN_YLIM)
ax4.set_xticks(DYN_XTICKS)
ax4.set_yticks(DYN_YTICKS)
ax4.annotate('better', xy=(168, 2.2), xytext=(220, 5.4),
             arrowprops={'arrowstyle':'->', 'linewidth':.9})
clean(ax4, grid='both')
ax4.legend(frameon=False, loc='upper right')
fig.text(.012, .985, '(a) Targeted component effects', ha='left', va='top',
         fontweight='bold', fontsize=12.5)
fig.subplots_adjust(left=.055, right=.99, top=.80, bottom=.20)
save_generated(fig, 'experiment2_corrected_newdata')

# -----------------------------------------------------------------------------
# Update paper captions and source filenames.
# -----------------------------------------------------------------------------
for kind in ['standalone', 'vgtc']:
    src_tex = OUT / 'paper' / f'EgoAnchor_IEEEVR2027_corrected_newdata_v3_{kind}.tex'
    text = src_tex.read_text(encoding='utf-8')
    text = text.replace(
        '中：持续平移的 fitted-lag--aligned-residual 联合权衡，越靠左下越好；右：遮挡期间的 episode-level P95。',
        '中：持续平移的 fitted-lag--aligned-residual 联合权衡，越靠左下越好；该面板与图~\\ref{fig:exp2-final} 右侧统一采用 150--400~ms 与 0--21~mm 的坐标范围。右：遮挡期间的 episode-level P95。'
    )
    text = text.replace(
        '右侧显示时序合成的 fitted-lag--aligned-residual 权衡。',
        '右侧显示时序合成的 fitted-lag--aligned-residual 权衡，并与图~\\ref{fig:exp1-final} 中间面板统一采用 150--400~ms 与 0--21~mm 的坐标范围，以支持直接视觉比较。'
    )
    text = text.replace('corrected_newdata_v3_', 'corrected_newdata_v4_')
    dst_tex = OUT / 'paper' / f'EgoAnchor_IEEEVR2027_corrected_newdata_v4_{kind}.tex'
    dst_tex.write_text(text, encoding='utf-8')
    src_tex.unlink()

# Update results replacement and README if present.
rep = OUT / 'paper' / 'corrected_results_replacement_v3.tex'
if rep.exists():
    t = rep.read_text(encoding='utf-8')
    t += ('\n% Axis-alignment revision: the dynamic-translation and temporal-synthesis '
          'trade-off panels both use x=[150,400] ms and y=[0,21] mm.\n')
    (OUT / 'paper' / 'corrected_results_replacement_v4.tex').write_text(t, encoding='utf-8')
    rep.unlink()

readme = OUT / 'README.md'
old = readme.read_text(encoding='utf-8') if readme.exists() else ''
old += ('\n\n## v4 axis-alignment revision\n'
        '- The dynamic-translation panel and temporal-synthesis trade-off panel now use identical limits: '
        '150-400 ms on the x-axis and 0-21 mm on the y-axis.\n'
        '- Both panels use identical major ticks, making their visual distances directly comparable.\n')
readme.write_text(old, encoding='utf-8')

# Rename supplement source references are not needed; supplement PDF/data unchanged.

# -----------------------------------------------------------------------------
# Compile v4 standalone source using the existing bibliography output.
# -----------------------------------------------------------------------------
paper = OUT / 'paper'
old_bbl = paper / 'EgoAnchor_IEEEVR2027_corrected_newdata_v3_standalone.bbl'
new_stem = 'EgoAnchor_IEEEVR2027_corrected_newdata_v4_standalone'
if old_bbl.exists():
    shutil.copy2(old_bbl, paper / f'{new_stem}.bbl')

tex_name = f'{new_stem}.tex'
log_chunks = []
for cmd in [
    ['xelatex','-interaction=nonstopmode','-halt-on-error',tex_name],
    ['xelatex','-interaction=nonstopmode','-halt-on-error',tex_name],
    ['xelatex','-interaction=nonstopmode','-halt-on-error',tex_name],
]:
    p = subprocess.run(cmd, cwd=paper, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log_chunks.append('$ ' + ' '.join(cmd) + '\n' + p.stdout)
    if p.returncode != 0:
        (paper / 'build_v4.log').write_text('\n'.join(log_chunks), encoding='utf-8')
        raise RuntimeError(p.stdout[-5000:])
(paper / 'build_v4.log').write_text('\n'.join(log_chunks), encoding='utf-8')

compiled = paper / f'{new_stem}.pdf'
final_pdf = paper / 'EgoAnchor_IEEEVR2027_corrected_newdata_v4.pdf'
shutil.copy2(compiled, final_pdf)
shutil.copy2(final_pdf, ROOT / final_pdf.name)

# Clean stale v3 compilation artifacts and obsolete main PDF names.
for p in paper.glob('EgoAnchor_IEEEVR2027_corrected_newdata_v3_*'):
    p.unlink()
old_main = paper / 'EgoAnchor_IEEEVR2027_corrected_newdata_v3.pdf'
if old_main.exists():
    old_main.unlink()

# Save build script and package.
script_out = OUT / 'scripts' / 'build_v4_axes.py'
shutil.copy2(Path(__file__), script_out)
zip_path = ROOT / 'EgoAnchor_corrected_newdata_v4_package.zip'
if zip_path.exists():
    zip_path.unlink()
shutil.make_archive(str(zip_path.with_suffix('')), 'zip', OUT)
print(final_pdf)
print(zip_path)
