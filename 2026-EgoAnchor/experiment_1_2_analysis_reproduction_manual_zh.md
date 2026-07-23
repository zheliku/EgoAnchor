# 实验一/二数据归档与分析手册

本手册使用唯一入口 `pixi run eval`。命令不接收任意输入、输出路径；日常需要调整的路径、
当前主稿和最终 PDF 名统一写在 `src/egoanchor/eval/config/batch.toml`。

以下命令都在 `EgoAnchor_Python` 目录运行。

## 当前 Kalman 重采边界

当前活动批次是 v3 归档数据，使用旧的 Kalman 过程协方差。它可以继续用于只读诊断和历史
结果核对，但不能作为 CWNA 修正后运行时的正式结果。开始新采前必须确认正式场景中的六个
`KalmanModel` 参数完全一致，配置指纹包含 `q-model:cwna-v1`，并通过 Unity EditMode 测试。

新批次仍按任务 1--5 各采一个正式 session。五项数据没有全部完成并通过 `stage` 前，不切换
活动批次，也不从 v3 单独保留某个表现更好的场景。完成整批 QC 后再使用 `promote` 原子替换，
随后依次运行 `analyze` 和 `latex` 重建图、表、正文数字与稳定 PDF。

## 一、先弄清三类文件

### 1. 新采集 session

Unity 和 Python 同步回来的原始 session 位于：

```text
data/eval/<session_id>/
```

这里是新数据入口，不是论文长期归档。每个正式 session 只能完成一个任务。实验一/二的一批
完整数据由五个不同 session 组成，并且恰好覆盖任务 1--5。

### 2. 当前活动批次

论文分析只读取 `active_root` 指向的批次，默认是：

```text
data/experiments/experiment_1_2/
├─ raw/          # 五项 JSON/JSONL 原始任务
├─ workbooks/    # 五本 Stage 1 XLSX
└─ analysis/     # 指标、绘图数据和分析 provenance
```

`raw/` 中的 JSON/JSONL 是当前批次的只读归档。`workbooks/` 是 JSONL 与论文分析之间的唯一
桥梁。这里常说的“raw XLSX”实际是 Stage 1 完整工作簿，它保留原始行、来源行号、行摘要、
事件、reference、admission 和 render 表，但它仍是预处理产物，不是原始采集文件。

### 3. 论文工程

论文源稿、图和表位于 `2026-EgoAnchor/`。当前版本化源稿是：

```text
egoanchor_cn_v6.tex
```

`v6` 只表示源稿版本。面向阅读和交付的 PDF 使用稳定名称：

```text
pdf/EgoAnchor.pdf
```

以后主稿升级为 v7 时，只需要在 TOML 中把 `manuscript` 改为 `egoanchor_cn_v7.tex`；最终
PDF 仍然叫 `EgoAnchor.pdf`。

## 二、配置文件怎么改

### 1. 操作路径和论文文件：batch.toml

配置文件：

```text
src/egoanchor/eval/config/batch.toml
```

当前内容：

```toml
[paths]
eval_root = "data/eval" # Unity/Python 新采集 session 的本机同步暂存目录。
staging_root = "data/experiments/_staging/experiment_1_2" # 新批次完成 QC 和工作簿发布前的临时目录。
archive_root = "data/experiments/_archive/experiment_1_2" # 退出当前论文的完整旧批次冷归档目录。
active_root = "data/experiments/experiment_1_2" # 当前论文唯一使用的活动批次目录。
paper_root = "../2026-EgoAnchor" # 中文主稿、论文面板、表格和最终 PDF 所在目录。

[paper]
manuscript = "egoanchor_cn_v6.tex" # 当前需要回填和编译的版本化 LaTeX 主稿，相对于 paper_root。
output_pdf = "pdf/EgoAnchor.pdf" # 面向阅读和交付的稳定 PDF 名称，相对于 paper_root，不包含主稿版本号。
```

`[paths]` 的相对路径以 `EgoAnchor_Python` 根目录为基准，不是以 TOML 所在目录为基准。
`[paper]` 的两个路径以 `paper_root` 为基准。

可以修改：

- `eval_root`：新 session 同步到了其他 `data/` 子目录时修改。
- `staging_root`、`archive_root`：需要调整暂存和冷归档位置时修改。
- `active_root`：需要维护另一套完整实验批次时修改。
- `paper_root`：论文工程目录改变时修改。
- `manuscript`：主稿升级版本时修改，例如改为 `egoanchor_cn_v7.tex`。
- `output_pdf`：修改最终交付 PDF 的路径或名称。建议保持 `pdf/EgoAnchor.pdf`。

这些路径有硬限制：四个数据目录必须位于 `EgoAnchor_Python/data/` 内，彼此不能相同或互相
嵌套；论文目录必须位于当前仓库内；主稿和 PDF 必须位于 `paper_root` 内，扩展名分别是
`.tex` 和 `.pdf`。最终 PDF 的文件名只使用 ASCII 字母、数字、点、下划线和连字符，避免
latexmk 的 `jobname` 在不同系统上产生不一致结果。

修改 TOML 只会改变下一条命令读取和写入的位置，不会自动搬迁旧数据。改完先运行：

```text
pixi run eval config
```

它会打印全部绝对路径，并列出所有 `pixi run eval` 子命令的实际输入、输出。路径不符合
预期时不要继续。

### 2. 论文统计参数：paper.toml

科学参数位于：

```text
src/egoanchor/eval/config/paper.toml
```

这里控制有效时延搜索范围和步长、最小样本数、起停判定阈值、遮挡灾难性失效阈值。它不
控制目录、文件名、颜色或字体。

修改 `paper.toml` 会改变正式结果。分析 provenance 会记录该文件的 SHA-256，因此正式采集
完成后不能为了得到更好看的数字反复调参。确需修改时，应先说明原因、冻结新参数，再对五项
任务完整重建，不能只重算某一个场景。

绘图风格目前由 `egoanchor.eval.paper_analysis` 的绘图代码控制，没有命令行或 TOML 覆盖项。
`figure_plot_data.xlsx` 是审计输出，手工修改它不会改变图片。

## 三、命令总表

| 命令                                   | 主要输入                | 主要输出或写入                                   | 是否改当前活动批次 |
| -------------------------------------- | ----------------------- | ------------------------------------------------ | ------------------ |
| `pixi run eval config`               | `batch.toml`          | 终端 JSON                                        | 否                 |
| `pixi run eval sessions`             | `eval_root`           | session 清单 JSON                                | 否                 |
| `pixi run eval stage <5 IDs>`        | 五个新 session          | `staging_root/<batch_id>/raw` 和 `workbooks` | 否                 |
| `pixi run eval promote [batch_id]`   | 一个完整暂存批次        | 新`active_root`，旧批次进入 `archive_root`   | 是                 |
| `pixi run eval qc`                   | `active_root/raw`     | QC JSON；必要时生成`events.jsonl`              | 否                 |
| `pixi run eval preprocess`           | `active_root/raw`     | 五本 Stage 1 XLSX                                | 否                 |
| `pixi run eval analyze --skip-latex` | 五本 Stage 1 XLSX       | 指标、绘图数据、面板、表格、主稿回填             | 否                 |
| `pixi run eval latex`                | 配置指定的`.tex` 主稿 | 配置指定的最终 PDF                               | 否                 |
| `pixi run eval analyze`              | 五本 Stage 1 XLSX       | `analyze --skip-latex` 的全部输出，再编译 PDF  | 否                 |
| `pixi run eval rebuild`              | `active_root/raw`     | preprocess + analyze + latex 的全部输出          | 否                 |

只有 `promote` 会替换当前活动批次。`preprocess`、`analyze` 和 `rebuild` 会更新活动批次内的
派生产物，但不会把另一个批次切换进来。

## 四、新数据如何进入下一批

### 阶段 0：等待两端停止和同步完成

先停止 Unity session 和远端 Python 服务，确认 `python_session.json` 已写入
`python_stopped`，两端 writer 的 `dropped_rows` 和 `log_write_failures` 都是 0。

刷新并查看 Mutagen：

```text
pixi run mutagen sync flush logs-5090
pixi run mutagen sync list logs-5090
```

确认没有 conflict，文件数量和大小不再变化，然后停止同步项目：

```text
pixi run mutagen project terminate
```

writer 或 Mutagen 仍在写入时，不要执行 `stage`，也不要移动、重命名或删除 session。

### 阶段 1：sessions，只查看候选 session

命令：

```text
pixi run eval sessions
```

输入：`batch.toml` 的 `eval_root`。

输出：终端 JSON，包含目录名、`session_id`、`completed_tasks`、`config_hash`、
`python_state` 和 `variant_matrix_id`。该命令不修改任何日志。

你能控制的内容：不能通过命令改路径；需要改入口目录时修改 `batch.toml` 的 `eval_root`。

成功判据：找得到准备归档的五个 session；每个 session 的 `python_state` 是
`python_stopped`，五项任务编号没有重复。

### 阶段 2：stage，复制新批次并生成工作簿

命令：

```text
pixi run eval stage <session-dir-1> <session-dir-2> <session-dir-3> <session-dir-4> <session-dir-5>
```

例如：

```text
pixi run eval stage task_1_20260722_120001_controller_right_v4 task_2_20260722_120002_controller_right_v4 task_3_20260722_120003_controller_right_v4 task_4_20260722_120004_controller_right_v4 task_5_20260722_120005_controller_right_v4
```

输入：五个 `eval_root/<session-directory>` 目录。目录名可保留 `task_N_..._v4` 这类
人工标签，不要求与 manifest 的 `session_id` 相同。输入顺序不限，程序根据 manifest 的
`completed_tasks` 自动映射任务 1--5，批次身份始终使用 manifest 的 `session_id`。

检查内容：

- 五个 session ID 唯一，每个 session 只完成一项任务，整批恰好覆盖任务 1--5。
- `run_kind` 为 `formal`，九路矩阵为 `exp12_9_smoothed_hermite_v4`。
- 五个 session 的配置哈希、冻结参数、对象、模型和协议一致。
- Task 2 的 `transition_started` / `transition_stopped` 严格交替闭合；Smoothed KF Extrapolation 的实际时域不超过配置指纹中的上限，校正残差有限，异常连续性重置计数单调不减。
- 固定 JSON/JSONL 文件齐全，生命周期、事件、主外键和九路 admission/render 矩阵通过 QC。
- 复制期间来源文件没有继续变化。

写入：

```text
staging_root/batch_YYYYMMDD_HHMMSS_<config-hash>/
├─ raw/
│  ├─ task_1_static_head_motion/
│  ├─ task_2_start_stop_6dof/
│  ├─ task_3_continuous_translation/
│  ├─ task_4_continuous_rotation/
│  └─ task_5_occlusion_recovery/
└─ workbooks/
   ├─ task_1_complete.xlsx
   ├─ task_2_complete.xlsx
   ├─ task_3_complete.xlsx
   ├─ task_4_complete.xlsx
   └─ task_5_complete.xlsx
```

需要特别注意：如果 session 中缺少派生的 `events.jsonl`，`stage` 会先根据
`python_events.jsonl` 和 `unity_events.jsonl` 在原 session 内确定性生成它。因此
`data/eval` 原件不会被重命名或删除，但并非绝对零写入。

你能控制的内容：五个 session ID；暂存根目录由 `batch.toml` 控制。批次名自动生成，不能
手写，避免同名覆盖和无法追溯。

成功判据：返回 `"passed": true`、`batch_id`、五本工作簿 SHA-256，以及下一条
`promote` 命令。失败时当前活动批次完全不变，修正原 session 后重新运行整条 `stage`。

### 阶段 3：promote，切换当前论文批次

暂存区只有一个批次时：

```text
pixi run eval promote
```

暂存区有多个批次时：

```text
pixi run eval promote <batch_id>
```

输入：一个 `staging_root/<batch_id>`。提升前会重新执行 QC、回读五本工作簿，并核对每本
工作簿记录的来源摘要是否与对应 raw 一致。

写入和移动：旧 `active_root` 整体移动到 `archive_root/<old_batch_id>`，新暂存批次整体移动
到 `active_root`。第二次移动失败时会回滚旧活动批次。

你能控制的内容：多个暂存批次并存时必须明确给出 `batch_id`；活动和归档路径由 TOML
控制。命令不允许覆盖已经存在的冷归档。

成功判据：返回新的 `active_root` 和旧批次 `archived_root`。新活动批次此时只有 `raw/` 和
`workbooks/`；还要执行 `analyze` 才会得到这一批对应的图表和论文结果。

确认新批次的工作簿、图表和 PDF 都正确后，才可以清理 `data/eval` 中对应的五个 session。
继续采集前重新启动同步：

```text
pixi run mutagen project start
```

## 五、当前活动批次如何逐阶段分析

### 阶段 4：qc，只检查当前 raw

命令：

```text
pixi run eval qc
```

输入：`active_root/raw/` 下五个固定任务目录。

输出：终端 QC JSON，包含每个 session 的错误、警告和计数；QC 不通过时同样返回完整报告，
并使用退出码 2。若某个 task 缺少
`events.jsonl`，命令会在该 raw task 内确定性生成它；除此之外不生成工作簿、图或论文。

你能控制的内容：输入位置只由 `active_root` 控制。QC 规则和九路矩阵属于正式数据契约，
不能通过命令关闭。

成功判据：退出码为 0，顶层 `"passed": true`，五项 task 都没有 error。latest-only 导致的
`python_candidates_not_consumed` 可以是警告；Unity admission 指向未知 candidate、丢行、
writer 失败或任务不完整都属于硬错误。

失败处理：根据 JSON 中的 error code 定位问题。不要修改 JSONL 补行，也不要从别的批次复制局部文件。先修复同步或选择正确批次，
然后重新运行 QC。

### 阶段 5：preprocess，JSON/JSONL 转五本 Stage 1 XLSX

命令：

```text
pixi run eval preprocess
```

输入：`active_root/raw/`。命令先对五项任务重新做整批 QC。

输出：

```text
active_root/workbooks/
├─ task_1_complete.xlsx
├─ task_2_complete.xlsx
├─ task_3_complete.xlsx
├─ task_4_complete.xlsx
└─ task_5_complete.xlsx
```

每本工作簿记录当前 Git commit、来源文件摘要、原始行和 QC 结果，写出后还会独立回读验证。
单本工作簿采用临时文件加原子替换，不会留下半本 XLSX。五本工作簿不是一个跨文件事务；
如果第 N 本因文件锁失败，前面成功的工作簿可能已经更新。关闭 Excel、修复问题后，重新运行
整条 `preprocess` 即可，不要只手工补某一本。

你能控制的内容：raw 和 workbooks 根目录由 `active_root` 决定，文件名固定。正式命令不允许
覆盖代码版本或跳过 QC。

成功判据：返回五个 `workbook_sha256`。工作簿可以只读查看，但不要在 Excel 中保存后继续
用于正式分析；Excel 保存会改变文件内容和摘要。

### 阶段 6：analyze，从五本 XLSX 生成指标、绘图数据和论文内容

只分析、不编译最终论文：

```text
pixi run eval analyze --skip-latex
```

输入：

```text
active_root/workbooks/task_1_complete.xlsx
...
active_root/workbooks/task_5_complete.xlsx
```

该阶段不回读 raw JSON/JSONL，也不修改五本工作簿。

输出：

```text
active_root/analysis/
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

paper_root/figures/panels/
├─ figure2a_head_motion.png/.pdf
├─ figure2b_translation.png/.pdf
├─ figure2c_occlusion.png/.pdf
├─ figure3a_capture_alignment.png/.pdf
├─ figure3b_static_lock.png/.pdf
├─ figure3c_vcd.png/.pdf
└─ figure3d_temporal_strategies.png/.pdf

paper_root/tables/
├─ experiment1_system_characterization.tex
└─ experiment2_design_attribution.tex

paper_root/<manuscript>
```

重要写入行为：`analyze` 会原地更新 TOML 指定主稿中的实验一/二自动生成区域，并更新输入
工作簿 provenance。它不是单纯的“画图”命令。如果你刚刚手改了实验一/二生成区，再运行
`analyze` 会用当前数据重新覆盖这些区域。只修改普通正文、暂时不想重算结果时，应直接运行
`latex`，不要运行 `analyze`。

`figure_plot_data.xlsx` 与 PNG/PDF 面板来自同一份内存分析结果。它用于核对图中可见点，不是
后续绘图输入。手改它不会改变图片，下次分析还会覆盖它。

你能控制的内容：

- 输入、分析输出和论文根目录由 `batch.toml` 控制。
- 当前被回填的主稿由 `[paper].manuscript` 控制。
- 指标算法参数由 `paper.toml` 控制，但正式采集后不能临时调参。
- `--skip-latex` 只跳过最终 XeLaTeX，不跳过指标、图片、表格或主稿回填。

成功判据：退出码为 0，`build_result.json` 中 `"passed": true`，七组面板、两张 TeX 表和
配置指定的主稿都存在。分析输出不是跨全部文件的单一事务；中途失败时不要使用局部新产物，
修复问题后重新运行完整 `analyze --skip-latex`。

### 阶段 7：latex，只编译当前主稿

命令：

```text
pixi run eval latex
```

输入：`batch.toml` 的 `[paper].manuscript`，以及主稿引用的 bibliography、图和表。

输出：`[paper].output_pdf`。当前配置为：

```text
2026-EgoAnchor/pdf/EgoAnchor.pdf
```

命令使用本机 `latexmk -xelatex`，通过 `jobname` 将版本化源稿编译为稳定 PDF 名。它不读取
raw，不重新计算指标，不重画图片，也不改写主稿正文。

你能控制的内容：主稿和 PDF 文件名在 `batch.toml` 中修改。切换到 v7 时改
`manuscript = "egoanchor_cn_v7.tex"`；通常保留 `output_pdf = "pdf/EgoAnchor.pdf"`。

成功判据：退出码为 0，命令返回的 `paper_pdf` 指向 `EgoAnchor.pdf`。LaTeX warning 可以单独
评估；缺图、缺表、未定义命令或 XeLaTeX 非零退出会使命令失败。

## 六、组合命令怎么选

### 当前 raw 全部重建

```text
pixi run eval rebuild
```

等价于依次执行：

```text
pixi run eval preprocess
pixi run eval analyze
```

它不执行 `stage` 或 `promote`，不会切换数据批次。

### 当前 raw 全部分析，但暂不编译 PDF

```text
pixi run eval rebuild --skip-latex
```

### 工作簿已经确认，只重算指标和图

```text
pixi run eval analyze --skip-latex
```

### 只改了普通 LaTeX 正文

```text
pixi run eval latex
```

不要为了编译正文运行 `analyze`，因为它会重新回填实验一/二生成区。

### 新采集五个 session 的完整顺序

```text
pixi run eval config
pixi run eval sessions
pixi run eval stage <session-dir-1> <session-dir-2> <session-dir-3> <session-dir-4> <session-dir-5>
pixi run eval promote <batch_id>
pixi run eval analyze
```

`stage` 已经为暂存批次生成工作簿，提升后通常直接 `analyze`，不必再次 preprocess。

## 七、哪些东西不能手工改

- 不要补写、删行或拼接 raw JSON/JSONL。
- 不要在 Excel 中保存后把修改过的 Stage 1 工作簿用于正式分析。
- 不要把 `figure_plot_data.xlsx` 当成绘图输入。
- 不要从不同采集批次挑选更好的场景或指标拼成论文结果。
- 不要在 writer 或 Mutagen 仍运行时执行归档切换。
- 不要恢复要求手工输入五组路径的旧 Python CLI。人工入口只有 `pixi run eval`。

主稿的普通正文可以手工编辑。实验一/二自动生成区域应由 `analyze` 维护；如果确需修改生成
逻辑，应修改分析代码和模板生成函数，然后对五本工作簿完整重建。

## 八、退出码和排错

| 退出码 | 含义                                        | 处理方式                         |
| ------ | ------------------------------------------- | -------------------------------- |
| `0`  | 命令成功                                    | 检查返回 JSON 中的路径和摘要     |
| `1`  | 目录、固定文件、Git、latexmk 或文件系统错误 | 检查同步、路径、文件锁和工具安装 |
| `2`  | 批次、schema、QC 或论文输入契约错误         | 修复数据或配置后整阶段重跑       |

排错顺序：

1. 运行 `pixi run eval config`，确认实际输入和输出。
2. 运行 `pixi run eval qc`，先排除当前 raw 问题。
3. 检查 Excel 是否打开了工作簿，LaTeX 是否缺少图表或参考文献。
4. 修复后重跑失败的完整阶段，不手工拼补局部产物。

日常使用不需要设置 `PYTHONPATH`，也不需要手工导入 Python 模块。需要写自己的只读检查
脚本时，使用包级入口：

```python
from egoanchor.eval import describe_workflow, list_eval_sessions, qc_current
```
