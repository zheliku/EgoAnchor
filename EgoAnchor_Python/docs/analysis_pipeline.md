# 实验一/二离线分析

正式分析只从 `pixi run eval` 进入。命令不接受任意磁盘路径，所有目录均由
`src/egoanchor/eval/config/batch.toml` 统一配置。

这套流程把数据分析与论文写作分开：`analyze` 只写当前活动批次下的 `analysis/`，不会修改
`2026-EgoAnchor` 的主稿、表格、图片或 PDF；确认结果后，才显式执行 `copy-assets` 发布 PNG/PDF。
TeX 表格和图环境始终由研究者手工复制到主稿并审阅。

## 先看配置

```text
pixi run eval config
```

重点检查：

- `[paths].active_root`：当前唯一参与论文分析的五项任务批次。
- `[paper]`：供 `latex` 单独编译的主稿和稳定 PDF 路径。
- `[copy_assets]`：实验一/二面板的论文目标目录，以及指定的 replay/relay PNG、PDF 来源和目标。

不要通过修改命令行路径选择数据。更换定性 replay 图时，只在 `[[copy_assets.relay]]` 中显式改动
`source` 和 `destination`；程序不会按修改时间猜测“最新”图片。

## 完整数据流

```text
data/eval/<session_id>
  -> stage
  -> _staging/<batch_id>/{raw,workbooks}
  -> promote
  -> experiment_1_2/{raw,workbooks}
  -> analyze
  -> experiment_1_2/analysis/{metrics,plots,figures,tex,provenance}
  -> copy-assets
  -> 2026-EgoAnchor 中的 PNG/PDF
  -> 手工审阅并引入 analysis/tex 中的 TeX
  -> latex
  -> 2026-EgoAnchor/pdf/EgoAnchor.pdf
```

`stage`、`promote`、`preprocess` 和长时间的分析步骤会在终端 stderr 显示 `tqdm` 进度条；最终 JSON
结果仍写到 stdout。进度条的总数是当前阶段的工作单元数，不必与状态文字中的“五本工作簿”逐字相同。

## 新采集五项任务

假设五个 session 都已完整同步到 `data/eval/`，按下面顺序执行：

```text
pixi run eval sessions
pixi run eval stage <task-1-directory> <task-2-directory> <task-3-directory> <task-4-directory> <task-5-directory>
pixi run eval promote <stage 返回的 batch_id>
pixi run eval analyze
pixi run eval copy-assets
```

`stage` 参数是 `data/eval/` 下的目录名。目录名可以保留 `task_1_..._v4` 这样的人工标签；是否属于同一
批次、任务号和正式配置由目录内 `manifest.json` 及固定文件集合验证，不以目录名相等为条件。

`stage` 完成整批 QC、复制 raw 并生成、回读五本 `task_N_complete.xlsx`。`promote` 再次复核 raw 与
工作簿来源摘要，随后把旧活动批次归档并原子切换新批次。因此 `promote` 成功后通常直接运行
`analyze`，不需要再运行 `preprocess`。

如果 `stage` 因同名暂存批次存在而失败，直接重跑同一条 `stage` 即可；程序会重建该批次。不要手动合并
暂存目录或 raw 文件。

## 分析结果

```text
pixi run eval analyze
```

输入严格是当前活动批次中的五本 Stage 1 XLSX。命令不读取 raw JSON/JSONL、不改写 XLSX，也不运行
XeLaTeX。为减少重复耗时，它保留批次身份、任务覆盖和运行时矩阵等分析契约检查，但不重复执行已经在
`stage` 和 `promote` 完成的全量工作簿回读。

输出全部位于：

```text
data/experiments/experiment_1_2/analysis/
├─ metrics/                         # 完整精度 CSV、时序策略配对数据和性能统计
├─ plots/figure_plot_data.xlsx      # 图二、图三的审计数据，不是绘图输入
├─ figures/                         # 七个面板，各自的 PNG 和 PDF
├─ tex/
│  ├─ tables/                       # 两张可手工引入的表格 TeX
│  └─ figures/                      # 图二、图三的可手工引入 figure 环境
└─ provenance/                      # 输入摘要、参数 SHA-256 和 build_result.json
```

实验二图 3(d) 的主比较是 *Smoothed KF Extrapolation* 与关闭 StaticLock 的 *Linear/SLERP*；
*Hermite Interpolation* 是同一设置下的补充条件。图 2(b) 和图 3(d) 对超出阅读范围的原始点使用图顶
空心上三角标记；所有真实数值仍完整保留在 `metrics/` 和 `figure_plot_data.xlsx`，不会因排版被删除或
修改统计结果。

这一步不适合 GPU 加速：主要时间来自 XLSX ZIP/XML 读取、校验和 Python 端分组统计，而不是可批量并行的
数值计算。关闭不必要的重复工作簿回读、合并 render 扫描后，保持现有 CPU 流程更可靠。

## 发布图片并手工纳入 TeX

确认 `analysis/` 中的图和数值后，运行：

```text
pixi run eval copy-assets
```

该命令只复制：

- 当前活动批次 `analysis/figures/` 的七个实验面板 PNG/PDF；
- `batch.toml` 中逐项声明的 replay/relay PNG/PDF。

它不会复制 TeX，不会修改主稿正文或表格，也不会编译 PDF。之后从以下目录手工选择并复制经过审阅的
TeX 片段到 `2026-EgoAnchor/egoanchor_cn_v6.tex`：

```text
data/experiments/experiment_1_2/analysis/tex/tables/
data/experiments/experiment_1_2/analysis/tex/figures/
```

图片默认发布到 `2026-EgoAnchor/figures/panels/`，relay 文件的目标位置以 `batch.toml` 为准。此操作是
显式覆盖同名 PNG/PDF；源主稿和 TeX 文件不受影响。

## 编译论文

完成手工 TeX 引入并保存主稿后：

```text
pixi run eval latex
```

`latex` 只调用本机 `latexmk -xelatex` 编译 `[paper].manuscript`，输出 `[paper].output_pdf`。它不分析数据、
不生成图，也不改写 LaTeX 源码。缺图、缺表或未定义控制序列需要在主稿中修复，再重新运行此命令。

## 诊断与重建

```text
pixi run eval qc
pixi run eval preprocess
pixi run eval rebuild
```

- `qc`：只检查当前活动批次 raw 和事件物化状态，不生成工作簿。
- `preprocess`：从当前活动 raw 重新生成五本工作簿。只有明确需要重建 Stage 1 时使用。
- `rebuild`：等价于当前活动批次的 `preprocess` 加 `analyze`；不切换批次、不复制论文图片、不编译 PDF。

工作簿在 Excel 中只读查看，不要保存后继续用于正式分析。`figure_plot_data.xlsx` 是审计结果，手工修改它
不会重绘图片，也不应作为论文数据来源。

## 本轮五项 v4 的命令

新 Task 1 替换旧 Task 1 后，先执行：

```text
pixi run eval stage task_1_20260724_005757_controller_right_v4_2 task_2_20260723_215645_controller_right_v4 task_3_20260723_215941_controller_right_v4 task_4_20260723_223641_controller_right_v4_2 task_5_20260723_223421_controller_right_v4
```

命令返回新的 `batch_id` 后依次执行：

```text
pixi run eval promote <新的 batch_id>
pixi run eval analyze
pixi run eval copy-assets
```

审阅 `analysis/` 和复制到论文目录的 PNG/PDF 后，再手工引入所需 TeX 并运行 `pixi run eval latex`。

## 代码验证

```text
pixi run python -m compileall src/egoanchor/eval
pixi run python -m unittest egoanchor.eval.tests.test_batch egoanchor.eval.tests.test_paper_pipeline
pixi run eval config
```

更完整的阶段边界和故障处理见
`2026-EgoAnchor/experiment_1_2_analysis_reproduction_manual_zh.md`。
