# 实验一/二离线分析

正式数据操作只从 `pixi run eval` 进入。它负责整理 session、生成本地指标和 TeX 片段、发布图片；
不再编译或修改论文主稿。

## 数据流

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
```

`analyze` 只写活动批次的 `analysis/`，不会改动 `2026-EgoAnchor` 的主稿、表格、图片或 PDF。
表格 TeX 和图环境 TeX 与图片一起生成在本地，之后由你手工复制到主稿。

## 配置

```text
pixi run eval config
```

`batch.toml` 只控制数据目录、论文图片发布目录和 relay 资源：

- `[paths].active_root`：唯一参与论文分析的五项任务批次。
- `[paths].paper_root`：`copy-assets` 的图片目标根目录。
- `[copy_assets]`：实验面板和 relay PNG/PDF 的明确来源、目标位置。

更换定性 replay 图时，直接修改 `[[copy_assets.relay]]` 的 `source` 与 `destination`。程序不会按修改
时间猜测最新文件。

## 新采集五项任务

```text
pixi run eval sessions
pixi run eval stage <task-1-directory> <task-2-directory> <task-3-directory> <task-4-directory> <task-5-directory>
pixi run eval promote <stage 返回的 batch_id>
pixi run eval analyze
pixi run eval copy-assets
```

`stage` 参数是 `data/eval/` 下的目录名。目录可保留 `task_1_..._v4` 这类标签；任务编号、批次身份和
配置一致性以目录内 `manifest.json` 和固定文件集合为准。

`stage` 会完整 QC、复制 raw 并生成五本 `task_N_complete.xlsx`。`promote` 再次复核 raw 与工作簿来源
摘要，然后原子切换活动批次。正常流程中，`promote` 后直接运行 `analyze`，不需要 `preprocess`。

## analyze 的本地产物

```text
pixi run eval analyze
```

输入是当前活动批次的五本 Stage 1 XLSX。命令不读取 raw JSON/JSONL、不改写 XLSX，也不调用 XeLaTeX。
它保留批次身份、任务覆盖和运行时矩阵检查，但不重复 `stage` 和 `promote` 已完成的全量工作簿回读。

```text
data/experiments/experiment_1_2/analysis/
├─ metrics/                         # 完整精度 CSV、时序策略配对数据和性能统计
├─ plots/figure_plot_data.xlsx      # 图二、图三审计数据，不是绘图输入
├─ figures/                         # 七个面板，各自的 PNG 和 PDF
├─ tex/
│  ├─ tables/                       # 两张可手工引入的表格 TeX
│  └─ figures/                      # 图二、图三的 figure 环境 TeX
└─ provenance/                      # 输入摘要、参数 SHA-256 和 build_result.json
```

图 3(d) 的主比较是 *Smoothed KF Extrapolation* 与关闭 StaticLock 的 *Linear/SLERP*；
*Hermite Interpolation* 是补充条件。图 2(b) 和图 3(d) 对超出阅读范围的点使用图顶空心上三角，
完整数值仍保留在 `metrics/` 和 `figure_plot_data.xlsx`。

分析主要耗时在 XLSX ZIP/XML 读取、校验与 Python 分组统计，不适合 GPU。现有流程已经避免重复的完整
工作簿回读，并把校正步长计算合并进同一次 render 扫描。

## 发布图片与手工引入 TeX

```text
pixi run eval copy-assets
```

该命令只复制当前 `analysis/figures/` 的七组实验 PNG/PDF，以及 `batch.toml` 中逐项声明的 relay PNG/PDF。
它不会复制 TeX，也不会修改主稿。

从以下目录手工选择、审阅并复制 TeX 到主稿：

```text
data/experiments/experiment_1_2/analysis/tex/tables/
data/experiments/experiment_1_2/analysis/tex/figures/
```

主稿与 PDF 的编译不属于 `pixi run eval`。完成手工引入后，按论文工程既有方式运行本机 LaTeX 工具链。

## 诊断与重建

```text
pixi run eval qc
pixi run eval preprocess
pixi run eval rebuild
```

- `qc`：检查当前活动批次 raw 和事件物化状态，不生成工作簿。
- `preprocess`：从当前 raw 重新生成五本工作簿。
- `rebuild`：依次执行 `preprocess` 与 `analyze`，不切换批次、不发布图片。

工作簿只能只读查看，不要用 Excel 保存后继续正式分析。`figure_plot_data.xlsx` 是审计输出，手工修改它不会
重绘图片。

## 当前五项 v4 命令

```powershell
pixi run eval stage --promote task_1_20260724_005757_controller_right_v4_2 task_2_20260723_215645_controller_right_v4 task_3_20260723_215941_controller_right_v4 task_4_20260723_223641_controller_right_v4_2 task_5_20260723_223421_controller_right_v4 && pixi run eval analyze && pixi run eval copy-assets
```

内部批次名由任务 1--5 的 manifest 时间按任务号组成。它确定地表示整组输入，局部重采任一任务都会
得到新批次名；`--promote` 会在 QC 和工作簿发布成功后自动切换活动批次，因此无需手工输入该名称。

## 验证

```text
pixi run python -m compileall src/egoanchor/eval
pixi run python -m unittest egoanchor.eval.tests.test_batch egoanchor.eval.tests.test_paper_pipeline
pixi run eval config
```

阶段边界和异常处理见 `2026-EgoAnchor/experiment_1_2_analysis_reproduction_manual_zh.md`。
