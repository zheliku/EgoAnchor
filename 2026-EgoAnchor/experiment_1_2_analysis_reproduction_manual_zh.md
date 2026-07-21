# 实验一/二分析复现手册

本手册从五项正式 raw task 重建 Stage 1 工作簿、论文指标、图表和中文主稿。当前数据目录
说明见 EgoAnchor_Python/docs/data_layout.md，分析代码说明见
EgoAnchor_Python/docs/analysis_pipeline.md。

## 1. 固定输入

~~~text
EgoAnchor_Python/data/experiments/experiment_1_2/raw/
├─ task_1_static_head_motion/
├─ task_2_start_stop_6dof/
├─ task_3_continuous_translation/
├─ task_4_continuous_rotation/
└─ task_5_occlusion_recovery/
~~~

每项任务都必须包含 manifest、python_session、六个源 JSONL 和已物化的 events.jsonl。
五个 manifest 使用同一个配置 hash 和 variant_matrix_id=exp12_9_linear_v2。正式
EgoAnchor 采用 Kalman Linear/SLERP；EgoAnchor Hermite 只作为图 3(d) 的插值器对照。

## 2. QC 与 Stage 1

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

pixi run python -m egoanchor.eval.cli qc @taskDirs
if ($LASTEXITCODE -ne 0) { throw "QC 失败，停止重建。" }

$codeVersion = (git rev-parse --short HEAD).Trim()
pixi run python -m egoanchor.eval.cli preprocess @taskDirs --out data/experiments/experiment_1_2/workbooks --code-version $codeVersion
if ($LASTEXITCODE -ne 0) { throw "preprocess 失败，停止重建。" }
~~~

必须得到 task_1_complete.xlsx 到 task_5_complete.xlsx。工作簿是后续唯一输入；可以只读
查看，不能在 Excel 中保存。

## 3. 论文分析

~~~powershell
$workbookRoot = (Resolve-Path "data/experiments/experiment_1_2/workbooks").Path
$workbooks = 1..5 | ForEach-Object {
    Join-Path $workbookRoot ("task_{0}_complete.xlsx" -f $_)
}

pixi run python -m egoanchor.eval.cli build-paper @workbooks --out data/experiments/experiment_1_2/analysis --paper-root ..\2026-EgoAnchor
if ($LASTEXITCODE -ne 0) { throw "build-paper 失败，停止编译。" }
~~~

绘图数据统一写入
data/experiments/experiment_1_2/analysis/plots/figure_plot_data.xlsx。Figure2 sheet 有图 2
的三个面板，Figure3 sheet 有图 3 的四个面板；同一 session_id、trial_id 和 segment_id
表示严格配对。完整精度指标位于 analysis/metrics/。

## 4. XeLaTeX

~~~powershell
Set-Location ..\2026-EgoAnchor
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
if ($LASTEXITCODE -ne 0) { throw "XeLaTeX 编译失败。" }
~~~

最终检查：

1. 图 1 只出现一次，架构文字在双栏全宽下可读。
2. 图 2 是一行三个 LaTeX 子图，小标题来自 subcaption；图 2(b) 没有跨方法折线。
3. 图 3 是一行四个 LaTeX 子图，图 3(d) 保留 Predict-to-Now、Hermite 和 Linear/SLERP。
4. 图内 tick、坐标轴和图例不小于约 7 pt，没有裁切或重叠。
5. 表格与正文数字来自当前五本工作簿，主稿不含旧结果包、旧 CLI 或旧文件名。

任一阶段失败都停在该阶段。不要手工补行、从历史目录复制数字，或把不同批次的场景拼成
同一份论文结果。
