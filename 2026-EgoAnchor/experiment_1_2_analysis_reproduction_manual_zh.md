# 实验一/二数据归档与手动分析手册

这套流程只需要 `pixi` 命令。路径、任务目录名、工作簿名和论文位置都由 Python 读取
`src/egoanchor/eval/config/batch.toml`，不需要 PowerShell 变量，也不需要手动拼接五组路径。

以下命令都在 `EgoAnchor_Python` 目录执行。先用文件管理器或编辑器终端进入该目录即可。

## 1. 目录和配置

新采集先进入：

```text
data/eval/<session_id>/
```

当前论文只读取：

```text
data/experiments/experiment_1_2/
├─ raw/          # 五项只读 JSON/JSONL
├─ workbooks/    # 五本 Stage 1 XLSX
└─ analysis/     # 指标、绘图数据和 provenance
```

批次切换还会使用：

```text
data/experiments/_staging/experiment_1_2/  # 新批次通过检查前的暂存区
data/experiments/_archive/experiment_1_2/  # 旧活动批次的冷归档
```

默认路径写在 `src/egoanchor/eval/config/batch.toml`：

```toml
[paths]
eval_root = "data/eval" # 新采集 session 的同步入口。
staging_root = "data/experiments/_staging/experiment_1_2" # 待提升批次的暂存父目录。
archive_root = "data/experiments/_archive/experiment_1_2" # 旧活动批次的冷归档父目录。
active_root = "data/experiments/experiment_1_2" # 当前论文唯一使用的数据批次。
paper_root = "../2026-EgoAnchor" # 中文主稿、图表和最终 PDF 的目录。
```

一般不需要修改。如果项目整体搬家，相对路径仍然有效。只有目录结构确实改变时才改这里；
四个数据目录必须位于 `EgoAnchor_Python/data/` 内且不能互相嵌套，论文目录必须位于本仓库内。

## 2. 新采集完成后的同步

先停止 Unity session 和远端 Python 服务，确认两端 writer 已关闭。然后刷新并查看日志同步：

```text
pixi run mutagen sync flush logs-5090
pixi run mutagen sync list logs-5090
```

只有同步没有 conflict、文件数量稳定后才能继续。准备整理批次前终止同步项目：

```text
pixi run mutagen project terminate
```

不要在 writer 仍运行或 Mutagen 仍同步时移动、重命名或删除 `data/eval/<session_id>`。

## 3. 查看并暂存五个 session

先列出 `data/eval` 中可用的 session：

```text
pixi run eval sessions
```

输出会显示目录名、`completed_tasks`、`config_hash`、Python 停止状态和运行时矩阵。每次正式
session 只完成一项任务，因此下一批必须选择五个不同 session，并恰好覆盖任务 1--5。

把五个实际 session ID 依次写在命令后。顺序不限，程序会根据 manifest 自动映射任务：

```text
pixi run eval stage 20260722_120001_controller_right 20260722_120002_controller_right 20260722_120003_controller_right 20260722_120004_controller_right 20260722_120005_controller_right
```

`stage` 会一次完成这些工作：

1. 检查五个 session 的任务映射、正式状态、九路矩阵和公共配置。
2. 物化并验证 `events.jsonl`，对五项原始数据执行整批硬 QC。
3. 把原始目录复制到暂存批次，复制前后复核来源 SHA-256，保留 `data/eval` 原件。
4. 自动生成 `task_1_complete.xlsx` 到 `task_5_complete.xlsx` 并独立回读验证。

任一步失败都不会替换当前论文数据。成功后会输出自动批次名，例如
`batch_20260722_120001_a575a3813af3b6a1`，以及下一条 `promote` 命令。

## 4. 切换当前正式批次

如果暂存区只有一个完整批次：

```text
pixi run eval promote
```

如果暂存区有多个批次，明确指定刚才输出的批次名：

```text
pixi run eval promote batch_20260722_120001_a575a3813af3b6a1
```

提升前，程序会重新检查 raw、五本 XLSX 及二者的来源摘要。当前活动批次会整体进入冷归档，
新批次再整体切换到 `data/experiments/experiment_1_2/`；中途失败会恢复原活动批次。不要按
task 手动覆盖，也不要从不同采集批次挑选场景或指标。

确认新批次图表和论文均正常后，才可清理 `data/eval` 中对应的五个原始 session。继续采集前
重新启动同步：

```text
pixi run mutagen project start
```

## 5. 当前 raw 的逐阶段分析

下面四条命令分别对应用户最常用的四个阶段。

### 5.1 只检查 JSON/JSONL

```text
pixi run eval qc
```

它读取 `active_root/raw/` 的五个固定任务目录，检查 schema、事件、主外键、writer 统计、任务
覆盖和九路矩阵。成功输出包含 `"passed": true`；失败时不会生成正式分析结果。

### 5.2 JSON/JSONL 转为 raw XLSX

```text
pixi run eval preprocess
```

输出固定在：

```text
data/experiments/experiment_1_2/workbooks/
├─ task_1_complete.xlsx
├─ task_2_complete.xlsx
├─ task_3_complete.xlsx
├─ task_4_complete.xlsx
└─ task_5_complete.xlsx
```

命令会先重新做整批 QC，再用当前 Git commit 记录代码版本。工作簿可以只读查看，但不要在
Excel 中保存后继续用于正式分析，因为保存会改变文件内容和 SHA-256。

### 5.3 raw XLSX 转为绘图数据、PNG、PDF 和主稿

```text
pixi run eval analyze --skip-latex
```

这一步只读取五本 Stage 1 XLSX，不回读 JSON/JSONL，也不修改工作簿。输出包括：

```text
data/experiments/experiment_1_2/analysis/
├─ metrics/                         # 完整精度 CSV/JSON
├─ plots/figure_plot_data.xlsx      # 图 2、图 3 的可见逐点数据
└─ provenance/                      # 输入和参数摘要

../2026-EgoAnchor/figures/panels/   # 七组 PNG/PDF 面板
../2026-EgoAnchor/tables/           # 两张自动生成的 TeX 表
../2026-EgoAnchor/egoanchor_cn_v6.tex
```

`figure_plot_data.xlsx` 是审计导出，不是绘图输入。分析代码从同一份内存结果同时生成该工作簿
和 PNG/PDF，因此不存在“手工把 plot XLSX 转图片”的正式阶段。需要重画时再次运行
`pixi run eval analyze --skip-latex`；修改图形样式应修改绘图代码，不能手改正式数据。

### 5.4 只编译最终论文 PDF

```text
pixi run eval latex
```

该命令不重新分析数据，只用本机 `latexmk -xelatex` 编译当前中文主稿。最终文件是：

```text
../2026-EgoAnchor/pdf/egoanchor_cn_v6.pdf
```

## 6. 常用组合命令

从当前 raw 开始全部重建，包括工作簿、分析、图表、主稿和最终 PDF：

```text
pixi run eval rebuild
```

从当前 raw 完整重建，但暂不编译最终论文：

```text
pixi run eval rebuild --skip-latex
```

五本工作簿已经存在，只重建分析、图表、主稿和最终 PDF：

```text
pixi run eval analyze
```

## 7. 参数和 Python 导入

操作路径只从 `src/egoanchor/eval/config/batch.toml` 读取；论文统计参数只从
`src/egoanchor/eval/config/paper.toml` 读取。两者职责不同，不要把路径写入 `paper.toml`，也
不要用命令行覆盖正式统计参数。

日常使用不需要手动导入 Python 包，也不需要设置 `PYTHONPATH`。如果要写自己的检查脚本，
按包级入口导入：

```python
from egoanchor.eval import list_eval_sessions, qc_current
```

不要从 `egoanchor.eval.batch` 等具体模块深层导入。

退出码含义：`0` 表示成功，`1` 表示目录、文件或外部工具错误，`2` 表示批次、schema、QC
或论文输入契约失败。任一阶段失败都应先解决原因，不要手工补日志行、修改工作簿或从冷归档
复制局部结果。
