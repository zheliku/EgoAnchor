from __future__ import annotations
import csv, json, re, shutil, subprocess, textwrap, zipfile
from pathlib import Path

ROOT=Path('/mnt/data')
SRC=ROOT/'EgoAnchor_corrected_newdata'
OUT=ROOT/'EgoAnchor_corrected_newdata_v2'
if OUT.exists(): shutil.rmtree(OUT)
for sub in ['paper','figures/generated','figures/panels','tables','data','scripts','documentation']:
    (OUT/sub).mkdir(parents=True,exist_ok=True)

# Copy support materials.
shutil.copy2(SRC/'paper'/'egoanchor_cn_refs.bib',OUT/'paper'/'egoanchor_cn_refs.bib')
shutil.copy2(ROOT/'_corrected_compile'/'figures'/'pipeline.png',OUT/'figures'/'pipeline.png')
for p in (SRC/'figures'/'generated').glob('*'):
    shutil.copy2(p,OUT/'figures'/'generated'/p.name)
for p in (SRC/'figures'/'panels').glob('*'):
    shutil.copy2(p,OUT/'figures'/'panels'/p.name)
for p in (SRC/'data').glob('*'):
    if p.is_file(): shutil.copy2(p,OUT/'data'/p.name)
shutil.copy2(SRC/'tables'/'experiment2_corrected_newdata.tex',OUT/'tables'/'experiment2_corrected_newdata_v2.tex')
shutil.copy2('/tmp/compute_v2_metrics.py',OUT/'scripts'/'compute_v2_metrics.py')

# Load summary data.
rows=list(csv.DictReader((SRC/'data'/'experiment1_expanded_summary_v2.csv').open(encoding='utf-8')))
by={r['method']:r for r in rows}
trans=json.loads((SRC/'data'/'task2_transition_summary_v2.json').read_text())
rot=json.loads((SRC/'data'/'task4_rotation_summary_v2.json').read_text())
perf=json.loads((SRC/'data'/'runtime_performance_audit_v2.json').read_text())

methods=['Arrival-Hold','Capture-Hold','One-Euro Anchor','EgoAnchor']

def f3(x): return f'{float(x):.3f}'
def f1(x): return f'{float(x):.1f}'

def fail_text(r): return f"{int(float(r['catastrophic_failures_gt40']))}/{int(float(r['occlusion_episodes']))}"

# Expanded table 1.
table1=r'''\begin{table*}[t]
\centering
\caption{新采集数据上的完整系统表征。数值为重复动作片段或遮挡过程的 median。粗体仅标记各能力块的主指标最优值；绝对注册是护栏，平移与旋转的 lag / aligned RMSE 必须成对解释，Start-transition 是稳定优先策略的转换代价。}
\label{tab:exp1-final}
\scriptsize
\setlength{\tabcolsep}{2.8pt}
\resizebox{\textwidth}{!}{%
\begin{tabular}{lcccccccc}
\toprule
& \multicolumn{2}{c}{世界一致性} & 静止稳定性 & \multicolumn{2}{c}{动态保真度} & \multicolumn{2}{c}{失效控制} & 转换代价 \\
\cmidrule(lr){2-3}\cmidrule(lr){4-4}\cmidrule(lr){5-6}\cmidrule(lr){7-8}\cmidrule(lr){9-9}
方法 & 头动泄漏 P95 $\downarrow$ & 绝对注册 P95 $\downarrow$ & 帧间增量 P95 $\downarrow$ & 平移 Lag / RMSE & 旋转 Lag / RMSE & 遮挡 P95 $\downarrow$ & $>40$~mm $\downarrow$ & Start-transition $\downarrow$ \\
& (mm) & (mm) & (mm) & (ms / mm) & (ms / deg) & (mm) & (次数) & (ms) \\
\midrule
'''
for m in methods:
    r=by[m]
    leak=f3(r['head_motion_leakage_p95_mm']); absreg=f3(r['absolute_registration_p95_mm']); jitter=f3(r['stationary_frame_increment_p95_mm'])
    tl=f1(r['translation_lag_ms']); tr=f3(r['translation_aligned_rmse_mm'])
    rl=f1(r['rotation_lag_ms']); rr=f3(r['rotation_aligned_rmse_deg'])
    occ=f3(r['occlusion_p95_mm']); fail=fail_text(r); start=f1(r['start_transition_response_ms'])
    if m=='EgoAnchor':
        leak='\\textbf{'+leak+'}'; absreg='\\textbf{'+absreg+'}'; jitter='\\textbf{'+jitter+'}'; tr='\\textbf{'+tr+'}'; occ='\\textbf{'+occ+'}'
    # Catastrophic failure has a tie; bold both zero-failure methods.
    if int(float(r['catastrophic_failures_gt40']))==0: fail='\\textbf{'+fail+'}'
    table1 += f'{m} & {leak} & {absreg} & {jitter} & {tl} / {tr} & {rl} / {rr} & {occ} & {fail} & {start} \\\\\n'
table1 += r'''\bottomrule
\end{tabular}%
}
\end{table*}'''
(OUT/'tables'/'experiment1_expanded_corrected_v2.tex').write_text(table1,encoding='utf-8')

# New Experiment 1 block.
exp1 = r'''\subsection{实验一：应用侧锚点行为}

实验一围绕五项应用可感知属性组织：\emph{world consistency} 衡量主动头动是否被错误写入静止物体的世界位置；\emph{rest stability} 衡量静止锚点的逐帧显示抖动；\emph{dynamic fidelity} 将持续运动中的有效时延与时延对齐后的轨迹残差作为不可拆分的权衡；\emph{failure containment} 衡量遮挡和坏观测是否破坏已建立锚点；\emph{transition cost} 衡量稳定优先策略从静止锁定切换到可见运动跟随的代价。静止头动场景中，绝对 display--reference 误差还包含一次 session 特有的固定注册偏置，因此我们将每个重复动作片段的误差向量减去该片段的中位误差向量，并以中心化残差 P95 作为头动泄漏主指标；绝对注册 P95 仅作为护栏报告。

'''+table1+r'''

\textbf{头动下的世界一致性与静止稳定性。}
移除每个动作片段的固定注册偏置后，EgoAnchor 的中心化平移 P95 为 1.631~mm，而 Arrival-Hold、Capture-Hold 与 One-Euro Anchor 分别为 20.690、10.833 与 8.329~mm。相对 Arrival-Hold，头动泄漏降低 92.1\%；相对 One-Euro Anchor 降低 80.4\%。EgoAnchor 的绝对注册 P95 亦为四种方法最低的 6.894~mm。静止显示的帧间位置增量 P95 为 0.098~mm，低于 Arrival-Hold 的 3.760~mm、Capture-Hold 的 2.380~mm 和 One-Euro Anchor 的 1.065~mm。头动泄漏和帧间增量分别刻画低频世界坐标泄漏与逐帧显示抖动，不能由同一个绝对误差指标替代。

\textbf{持续运动中的时延--轨迹质量权衡。}
持续平移中，EgoAnchor 的有效时延 / lag-aligned RMSE 为 320~ms / 4.960~mm；Arrival-Hold 为 182.5~ms / 10.087~mm，One-Euro Anchor 为 385~ms / 9.559~mm。相对 Arrival-Hold，EgoAnchor 付出额外拟合时延，但 residual 降低 50.8\%；相对 One-Euro Anchor，它同时减少 65~ms 的拟合时延并将 residual 降低 48.1\%。因此，平移结果支持稳定优先的连续轨迹合成，而不是最低时延主张。

该优势没有一致延伸至旋转。Capture-Hold 的有效角时延 / lag-aligned angular RMSE 为 260~ms / 3.281$^\circ$，EgoAnchor 为 372.5~ms / 4.691$^\circ$。因此，表~\ref{tab:exp1-final} 将旋转作为动态护栏保留，而不宣称当前旋转速度估计与对数空间合成优于保持式基线。

\textbf{遮挡期间的失效控制。}
九次遮挡过程中，EgoAnchor 的 episode-level 平移 P95 中位数为 1.980~mm，而 Arrival-Hold、Capture-Hold 与 One-Euro Anchor 分别为 25.553、25.479 与 11.710~mm。Arrival-Hold 与 Capture-Hold 各有 2/9 次过程超过 40~mm，One-Euro Anchor 与 EgoAnchor 均为 0/9；但 EgoAnchor 的最大 episode P95 仅为 3.252~mm，显著低于 One-Euro Anchor 的 27.922~mm。中位数、阈值超限率和最大值共同表明完整运行时不仅改善典型遮挡行为，也压缩了上尾风险。

\textbf{起停转换代价。}
我们将 Start-transition response 定义为：相对于各动作片段前 250~ms 的基线，参考物体与显示锚点首次持续 100~ms 超过 5~mm 位移阈值的时刻差。Arrival-Hold、Capture-Hold、One-Euro Anchor 与 EgoAnchor 的片段中位数分别为 167.5、208.8、284.4 与 591.1~ms。该量包含 StaticLock 解锁证据、候选更新和延迟合成时间线，不是网络或视觉推理的原始时延；它诚实刻画了静止稳定性收益所伴随的启动成本。

\begin{figure*}[t]
  \centering
  \includegraphics[width=0.99\textwidth]{../figures/generated/experiment1_corrected_newdata.pdf}
  \caption{新数据上的三项核心分布性结果。小标记表示重复动作片段或遮挡过程，大标记与误差棒表示 median--IQR。左：在每个片段内移除固定注册偏置后的头动泄漏；中：持续平移的 fitted-lag--aligned-residual 联合权衡，越靠左下越好；右：遮挡期间的 episode-level P95。静止帧间抖动、旋转护栏、灾难性失效率与起停转换代价在表~\ref{tab:exp1-final} 中完整报告。}
  \label{fig:exp1-final}
\end{figure*}
'''

metrics = r'''\subsection{评价指标与汇总契约}

所有误差均由 display pose 相对于同一 Quest 平台参考计算。静止头动场景同时报告绝对注册误差、片段中心化头动泄漏和帧间位置增量：中心化指标在片段内减去中位误差向量，用于隔离头动相关的世界坐标泄漏；帧间增量则量化相邻显示帧的静止抖动。采集时刻对齐另在 candidate 层面对同一原始观测的 capture-time 与 arrival-time 世界复合进行直接比较。遮挡场景同时报告 episode-level P95、超过 40~mm 的灾难性失效率和最大值，避免中位数掩盖稀疏重尾失效。

持续运动的\emph{有效时延}在每个连续动作片段内通过冻结 lag 网格搜索得到：平移通道最小化 $\mathrm{display}(t)$ 与 $\mathrm{reference}(t-\mathrm{lag})$ 的位置 RMSE，旋转通道使用四元数球面插值并最小化角 RMSE。Start-transition response 使用冻结的 5~mm 位移阈值、250~ms 片段初始基线和 100~ms 持续条件，计算参考运动与显示响应之间的时刻差。上述量均是相对于平台参考轨迹的描述性行为指标；有效时延和转换响应不等于网络到达时延，也不等于单次视觉推理时间。

本文以 median [IQR] 和同一动作片段内的配对差值为主，不进行渲染帧级显著性推断。所有参数、动作片段边界和指标契约在正式数据分析前冻结；完整片段级表、图源数据和流式解析脚本随分析包提供。
'''

# Performance paragraph replacement.
performance = (f"正式采集日志中，TRACK 阶段候选的服务器端处理时间中位数为 {perf['track_total_ms_median']:.1f}~ms，"
               f"P95 为 {perf['track_total_ms_p95']:.1f}~ms（$n={perf['track_n']}$）；"
               f"有效位姿候选的发布时间间隔中位数为 {perf['pose_publish_interval_ms_median']:.1f}~ms，"
               f"对应约 {perf['pose_publish_rate_hz_from_median']:.1f}~Hz。初始 REGISTER 阶段中位数为 {perf['register_total_ms_median']:.1f}~ms（$n={perf['register_n']}$）。"
               "这些日志量仅覆盖服务器端候选处理或候选发布间隔，不包含图像采集、跨端网络传输、Unity 接收与显示策略，因此不应直接解释为端到端交互时延。")

# Audit note text.
audit_note = '''# Full-text audit and changes in corrected v2

## Restored Experiment 1 coverage
- Rest stability restored as stationary frame-increment P95.
- Continuous rotation restored as a lag / angular-RMSE guardrail.
- Failure containment now includes both median occlusion P95 and >40 mm episode counts.
- Start-transition response restored using an explicit frozen operational definition.

## Corrected or removed stale content
- Removed the obsolete auto-generated macro block containing the previous dataset's values.
- Replaced the ambiguous cross-GPU timing paragraph with timing values directly audited from the five new workbooks.
- The Experiment 1 introduction now names five application-facing properties rather than three.
- The metric-contract section now defines centered leakage, frame increment, catastrophic failure, angular lag fitting, and start-transition response separately.
- Figure 1 caption explicitly states which guardrail and cost metrics are reported only in the table.
- Replaced remaining reader-facing “event” terminology with action segment / occlusion episode where applicable.

## Metrics intentionally not ranked as primary wins
- Absolute registration is a guardrail because it includes session-specific fixed bias.
- Translation and rotation lag are not independently bolded; they must be interpreted with aligned residual.
- Start-transition is a policy cost and is not included in the primary-benefit ranking.
- Rotation is retained despite being unfavorable to EgoAnchor, preventing selective reporting.
'''
(OUT/'documentation'/'FULL_TEXT_AUDIT.md').write_text(audit_note,encoding='utf-8')

# Patch TeX files.
for kind in ['standalone','vgtc']:
    src=SRC/'paper'/f'EgoAnchor_IEEEVR2027_corrected_newdata_{kind}.tex'
    text=src.read_text(encoding='utf-8')
    # Remove obsolete generated data macro block.
    text=re.sub(r'% EGOANCHOR-EXP-DATA:BEGIN.*?% EGOANCHOR-EXP-DATA:END\s*','',text,flags=re.S)
    # Abstract: add rest stability and transition cost while keeping core results.
    old_abs='静止头动时，移除片段固定注册偏置后的 EgoAnchor 平移 P95 为 1.631~mm，而 Arrival-Hold 为 20.690~mm；持续平移时，其有效时延为 320~ms，但 lag-aligned residual 为 4.960~mm，低于 Arrival-Hold 的 10.087~mm；遮挡窗内，其 episode-level 平移 P95 为 1.980~mm，而 One-Euro Anchor 为 11.710~mm。结果表明，EgoAnchor 明显改善静止附着与失效控制，同时以可测量的运动时延换取连续轨迹质量。'
    new_abs='静止头动时，移除片段固定注册偏置后的 EgoAnchor 平移 P95 为 1.631~mm，而 Arrival-Hold 为 20.690~mm；其静止帧间增量 P95 为 0.098~mm，而 One-Euro Anchor 为 1.065~mm。持续平移时，其有效时延为 320~ms，但 lag-aligned residual 为 4.960~mm，低于 Arrival-Hold 的 10.087~mm；遮挡窗内，其 episode-level 平移 P95 为 1.980~mm。上述收益伴随 591.1~ms 的起停转换响应，揭示了稳定性与响应性的明确权衡。'
    text=text.replace(old_abs,new_abs)
    # Replace old cross-GPU performance paragraph.
    text=re.sub(r'在 RTX 3090 平台上，完整的视觉推理流水线平均每帧耗时约 140 ms（约 7 fps）。为评估系统在不同算力条件下的性能表现，我们在 RTX 4090 与 RTX 5090 平台上进行了对照测试：RTX 4090 平台的平均推理时间降至约 100 ms（约 10 fps），RTX 5090 平台进一步降至约 70 ms（约 14 fps）。',performance,text)
    # Replace Experiment 1 block.
    text=re.sub(r'\\subsection\{实验一：应用侧锚点行为\}.*?(?=\\subsection\{实验二：组件归因\})',lambda m:exp1+'\n',text,flags=re.S)
    # Replace metrics contract.
    text=re.sub(r'\\subsection\{评价指标与汇总契约\}.*?(?=\\subsection\{实验三：跨对象用户研究计划\})',lambda m:metrics+'\n',text,flags=re.S)
    # Add discussion paragraph after time consistency boundary.
    marker='\\textbf{时间一致性的边界。} 帧对齐可避免将历史相机系观测与到达时刻相机位姿错误复合，但不能恢复目标物体在采集之后的当前位姿。动态场景仍受感知处理时间、观测更新率和平滑策略引入的插值延迟共同影响。因此，动态表征以渲染时刻误差描述应用实际获得的配准质量，不把帧对齐表述为对物体运动时延的补偿。'
    addition=marker+'\n\n\\textbf{稳定性与响应性的边界。} StaticLock 和历史时序合成显著降低静止抖动与平移轨迹残差，但新数据中的 Start-transition response 为 591.1~ms，且旋转通道未获得与平移相同的 residual 优势。这两项负结果被保留在主表中：前者限定快速抓取和直接操控任务，后者表明当前旋转速度估计和插值仍需独立优化。'
    text=text.replace(marker,addition)
    # Remove remaining '重复事件' phrasing if any.
    text=text.replace('一条包含重复事件的长序列','一条包含重复动作片段的长序列')
    out=OUT/'paper'/f'EgoAnchor_IEEEVR2027_corrected_newdata_v2_{kind}.tex'
    out.write_text(text,encoding='utf-8')

# Results replacement standalone snippet.
(OUT/'paper'/'corrected_results_replacement_v2.tex').write_text(exp1+'\n\n% Experiment 2 remains the corrected targeted-attribution block in the full paper.\n\n'+metrics,encoding='utf-8')

# Save expanded table CSV copy and summary README.
readme=f'''# EgoAnchor corrected new-data revision v2

This package supersedes `EgoAnchor_corrected_newdata_package.zip`.

## Main reporting changes
- Experiment 1 Table 1 is restored to cover world consistency, rest stability, translation and rotation fidelity, failure containment, and start-transition cost.
- The main table now includes stationary frame-increment P95, angular lag / RMSE, catastrophic occlusion counts, and the newly recomputed start-transition response.
- Rotation remains in the table as an unfavorable guardrail rather than being omitted.
- The paper now uses a frozen transition definition: 5 mm sustained displacement, 250 ms pre-motion baseline, and 100 ms persistence.
- The obsolete numerical macro block from the previous dataset was removed.
- Runtime-performance wording is now grounded in the new workbooks: TRACK {perf['track_total_ms_median']:.1f} ms median / {perf['track_total_ms_p95']:.1f} ms P95; candidate interval {perf['pose_publish_interval_ms_median']:.1f} ms median (~{perf['pose_publish_rate_hz_from_median']:.1f} Hz).

## Key expanded-table values for EgoAnchor
- Head-motion leakage P95: 1.631 mm
- Absolute registration P95: 6.894 mm
- Stationary frame-increment P95: 0.098 mm
- Translation lag / aligned RMSE: 320.0 ms / 4.960 mm
- Rotation lag / aligned RMSE: 372.5 ms / 4.691 deg
- Occlusion P95: 1.980 mm
- Catastrophic occlusion episodes (>40 mm): 0/9
- Start-transition response: 591.1 ms

See `documentation/FULL_TEXT_AUDIT.md` for the full audit.
'''
(OUT/'README.md').write_text(readme,encoding='utf-8')

# Compile standalone.
work=OUT/'paper'
tex='EgoAnchor_IEEEVR2027_corrected_newdata_v2_standalone.tex'
shutil.copy2(SRC/'paper'/'EgoAnchor_IEEEVR2027_corrected_newdata_standalone.bbl', work/(Path(tex).stem+'.bbl'))
commands=[['xelatex','-interaction=nonstopmode','-halt-on-error',tex],['xelatex','-interaction=nonstopmode','-halt-on-error',tex],['xelatex','-interaction=nonstopmode','-halt-on-error',tex]]
log=[]
for cmd in commands:
    proc=subprocess.run(cmd,cwd=work,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    log.append(proc.stdout)
    if proc.returncode!=0:
        (OUT/'documentation'/'compile_failure.log').write_text('\n'.join(log),encoding='utf-8')
        raise SystemExit(f'compile failed: {cmd}\n{proc.stdout[-4000:]}')
pdf=work/(Path(tex).stem+'.pdf')
shutil.copy2(pdf,work/'EgoAnchor_IEEEVR2027_corrected_newdata_v2.pdf')

# Save build script itself.
shutil.copy2('/tmp/build_egoanchor_corrected_v2.py',OUT/'scripts'/'build_corrected_v2.py')

# Package.
zip_path=ROOT/'EgoAnchor_corrected_newdata_v2_package.zip'
if zip_path.exists():zip_path.unlink()
shutil.make_archive(str(zip_path.with_suffix('')),'zip',OUT)
print(pdf)
print(zip_path)
