# 实验一/二离线分析

正式链路只有 qc、preprocess 和 build-paper 三个命令。数据目录及各层职责见
docs/data_layout.md。

~~~text
raw task
  -> qc
  -> preprocess
  -> task_1_complete.xlsx ... task_5_complete.xlsx
  -> build-paper
  -> 指标、绘图 XLSX、LaTeX 表格、面板图和中文主稿
~~~

qc 和 preprocess 可以读取 raw JSON/JSONL。build-paper 只读取五本 Stage 1 XLSX，
不回读 raw，也不修改工作簿。统计单位是动作片段或遮挡 episode，渲染帧不作为独立样本。

## 当前输入

~~~powershell
Set-Location P:\VSCode-Project\EgoAnchor\EgoAnchor_Python

$rawRoot = (Resolve-Path "data/experiments/experiment_1_2/raw").Path
$taskDirs = @(
    "task_1_static_head_motion"
    "task_2_start_stop_6dof"
    "task_3_continuous_translation"
    "task_4_continuous_rotation"
    "task_5_occlusion_recovery"
) | ForEach-Object { Join-Path $rawRoot $_ }
~~~

五个 task 必须使用 variant_matrix_id=exp12_9_linear_v2，并完整记录九个 runtime。QC 不再
接受缺少矩阵标识的历史八路数据。

## 从 raw 重建

~~~powershell
$codeVersion = (git rev-parse --short HEAD).Trim()
pixi run python -m egoanchor.eval.cli qc @taskDirs
if ($LASTEXITCODE -ne 0) { throw "QC 失败。" }

pixi run python -m egoanchor.eval.cli preprocess @taskDirs --out data/experiments/experiment_1_2/workbooks --code-version $codeVersion
if ($LASTEXITCODE -ne 0) { throw "preprocess 失败。" }
~~~

preprocess 必须原子生成 task_1_complete.xlsx 到 task_5_complete.xlsx。任一 task 的硬 QC
失败时，整批不开始发布。

## 重建论文

~~~powershell
$workbookRoot = (Resolve-Path "data/experiments/experiment_1_2/workbooks").Path
$workbooks = 1..5 | ForEach-Object {
    Join-Path $workbookRoot ("task_{0}_complete.xlsx" -f $_)
}

pixi run python -m egoanchor.eval.cli build-paper @workbooks --out data/experiments/experiment_1_2/analysis --paper-root ..\2026-EgoAnchor
if ($LASTEXITCODE -ne 0) { throw "论文分析失败。" }
~~~

冻结科学参数位于 src/egoanchor/eval/config/paper.toml。分析代码位于
egoanchor.eval.paper_analysis，不保留旧分析包或 CLI 兼容入口。

## 输出

本地分析目录：

~~~text
data/experiments/experiment_1_2/analysis/
├─ metrics/
│  ├─ experiment1_summary.csv
│  ├─ capture_alignment.csv
│  ├─ runtime_performance.json
│  ├─ strategy_comparison_segments.csv
│  └─ strategy_comparison_summary.csv
├─ plots/
│  └─ figure_plot_data.xlsx
└─ provenance/
   ├─ analysis_manifest.json
   └─ build_result.json
~~~

论文目录：

~~~text
2026-EgoAnchor/figures/panels/figure2a_...pdf 到 figure3d_...pdf
2026-EgoAnchor/tables/experiment1_system_characterization.tex
2026-EgoAnchor/tables/experiment2_design_attribution.tex
2026-EgoAnchor/egoanchor_cn_v6.tex
~~~

图 2 和图 3 都由 LaTeX subfigure 排成一行。图内不重复小标题；图 2(b) 不连接跨方法折线。

## 验证

~~~powershell
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src

Set-Location ..\2026-EgoAnchor
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
~~~

重建前后应核对五本 Stage 1 XLSX 的 SHA-256。图表、CSV 和主稿可以重建，但 raw、
工作簿与 strategy_label_migration.json 不能由分析阶段改写。
