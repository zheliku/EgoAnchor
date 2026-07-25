# 实验一/二数据归档与分析手册

所有命令都在 `EgoAnchor_Python` 目录运行。评估入口固定为 `pixi run eval`；路径从
`src/egoanchor/eval/config/batch.toml` 读取，不接收任意输入或输出路径。主稿编译不属于该 CLI。

## 一、目录和缓存

原始任务、Stage 1 工作簿、任务指标和当前组合相互独立：

```text
data/experiments/
├─ task_data/                     # 唯一原始归档
├─ task_workbooks/                # 每个原始目录唯一对应一本 XLSX
├─ task_analysis/                 # 每本 XLSX 唯一对应一份指标缓存
├─ _staging/experiment_1_2/       # 待提升的 batch.json
├─ _archive/experiment_1_2/       # 旧 batch.json 和旧 analysis
└─ experiment_1_2/
   ├─ batch.json                  # 当前选中的五项任务
   └─ analysis/                   # 当前五项合并后的图、表和 TeX
```

活动目录不再复制 `raw/` 或 `workbooks/`。例如只重采 Task 3 时，只会新增 Task 3 的原始目录、
工作簿缓存和指标缓存；Task 1、2、4、5 继续复用。

`task_data/` 目录名固定为：

```text
task_<1-5>_v<正整数>_<YYYYMMDD_HHMMSS>_<物体>
```

例如：

```text
task_3_v2_20260724_034253_controller_right
```

时间和物体必须与 `manifest.session_id`、`manifest.object_id` 一致。每个目录只完成一项任务。目录
进入 `task_data/` 后视为只读；需要替换内容时新建更高版本，不要覆盖原目录文件。

## 二、配置

当前数据路径配置为：

```toml
[paths]
task_data_root = "data/experiments/task_data" # 人工归档并按 task_任务_v版本_时间_物体 命名的原始日志目录。
task_workbook_root = "data/experiments/task_workbooks" # 每个原始任务目录唯一对应的 Stage 1 工作簿缓存。
task_analysis_root = "data/experiments/task_analysis" # 每本 Stage 1 工作簿唯一对应的论文指标缓存。
staging_root = "data/experiments/_staging/experiment_1_2" # 新组合切换前的轻量暂存目录。
archive_root = "data/experiments/_archive/experiment_1_2" # 旧组合清单和分析产物归档目录。
active_root = "data/experiments/experiment_1_2" # 当前论文唯一使用的活动组合目录。
paper_root = "../2026-EgoAnchor" # 手工发布实验图片和 relay 图片的论文目录。
```

修改后先运行：

```powershell
pixi run eval config
```

确认打印的绝对路径正确再继续。`paper.toml` 只保存论文统计参数；修改它会让逐任务指标缓存失效，
但不会重建 Stage 1 XLSX。

## 三、日常命令

正常流程只有三条：

```powershell
pixi run eval stage --promote
pixi run eval analyze
pixi run eval copy-assets
```

其中 `stage --promote` 自动选择数据、补建变化任务的工作簿，并切换当前五任务组合。`analyze` 只重算
变化任务的指标，然后统一生成完整图表。`copy-assets` 在人工看过结果后发布 PNG/PDF 和三张表格 TeX。

## 四、新数据归档

先停止 Unity session 和远端 Python 服务，确认 `python_session.json` 的状态为 `python_stopped`，
writer 的 `dropped_rows` 与 `log_write_failures` 都是 0。Mutagen 仍在写入时不要移动目录。

确认同步完成后，把 session 从 `data/eval/` 移到 `task_data_root`，按任务独立维护版本。只重采
Task 3 时，不需要改另外四个目录。

查看可选数据：

```powershell
pixi run eval sessions
```

输出会列出任务、版本、采集时间、物体、session ID、完成任务、Python 停止状态和运行时矩阵。
非法目录会显示错误，不会进入自动选择。

## 五、stage：只处理变化任务

默认命令：

```powershell
pixi run eval stage --promote
```

默认对每项任务选择最高版本，再选择该版本时间最新的目录。也可以固定选择：

```powershell
pixi run eval stage --promote --version v2
pixi run eval stage --promote --task-version 3=v2 --task-version 4=v3
pixi run eval stage --promote --object controller_right
```

`--version` 限制五项任务；重复的 `--task-version` 只覆盖指定任务。存在多个完整物体集合时必须用
`--object`，程序不会猜。

`stage` 先读取五个 manifest，检查 Task 1--5 覆盖、session 唯一性、对象、模型、协议、配置哈希、
冻结参数集和 `variant_matrix_id`。随后逐任务处理：

```text
缓存命中 -> 直接复用
缓存缺失或失效 -> events 物化 -> 完整 QC -> 写 XLSX -> 回读验证 -> 发布 cache.json
```

缓存命中判断使用 Stage 1 实现指纹、原始目录文件快照、工作簿存在性和大小。它不重新扫描 JSONL，
也不重新回读 XLSX。完整来源 SHA 和工作簿 SHA 在首次构建时已记录。需要重新深查原始数据时使用
`pixi run eval qc`。

首次处理五个新目录时，JSON 中应显示：

```json
"cache_hits": [],
"rebuilt_tasks": [1, 2, 3, 4, 5]
```

只替换 Task 3 后应显示：

```json
"cache_hits": [1, 2, 4, 5],
"rebuilt_tasks": [3]
```

暂存批次只包含 `batch.json`，不会复制 raw 或 XLSX。`--promote` 随后直接切换这份组合清单。批次名
由五个 session 时间按任务号组成，所以任一任务变化都会产生新的确定名称。

如果不带 `--promote`，命令返回 `batch_id`。之后可运行：

```powershell
pixi run eval promote <batch_id>
```

省略 ID 时，暂存区必须恰好只有一个批次。`promote` 不重跑 QC，也不打开五本 XLSX；它只确认
清单引用仍存在，并把旧 `batch.json` 和旧 `analysis/` 移入归档。

## 六、analyze：只重算变化任务

```powershell
pixi run eval analyze
```

输入由活动 `batch.json` 指向。分析缓存键包含三部分：

```text
Stage 1 workbook SHA-256
paper.toml SHA-256
metrics.py + xlsx.py 实现指纹
```

缓存命中时不打开 XLSX。缓存缺失或键变化时，只对对应工作簿计算 SHA、核对 `batch.json` 摘要并读取
其大表。Task 3 更新后，正常进度应为四个“使用指标缓存”和一个“重建指标缓存”。

五项 `TaskResults` 合并后才计算全批性能统计并生成八个面板、三张表和 TeX。性能缓存保存原始
TRACK、REGISTER 和 pose publish interval 样本，不会错误合并各 Task 的中位数。

输出目录：

```text
data/experiments/experiment_1_2/analysis/
├─ metrics/                         # 完整精度指标
├─ plots/figure_plot_data.xlsx      # 图中可见数据点
├─ figures/                         # 八个 PNG/PDF 面板
├─ tex/                             # 待发布的表格和待审阅的图环境
└─ provenance/build_result.json     # batch、输入、参数、实现指纹和缓存状态
```

成功后检查 JSON 中 `task_cache`。第一次分析应全部为 `rebuilt`；原样再次运行应全部为 `hit`；局部
重采后只有相应任务为 `rebuilt`。

`analyze` 不读取原始 JSON/JSONL，不改写 XLSX，不修改论文目录，也不调用 XeLaTeX。

## 七、发布图表

```powershell
pixi run eval copy-assets
```

命令先确认 `analysis/provenance/build_result.json` 的 batch ID 与活动清单一致，防止新组合误发布旧图表。
通过后，复制本次清单中的实验 PNG/PDF、`batch.toml` 明确列出的 relay PNG/PDF，以及
`[copy_assets.tables]` 配置的三张表格 TeX。所有来源在写入论文目录前统一校验，主稿不会自动修改。

表格默认发布到：

```text
2026-EgoAnchor/tables/exp1_static.tex
2026-EgoAnchor/tables/exp1_dynamic.tex
2026-EgoAnchor/tables/exp2_design.tex
```

图环境仍位于 `analysis/tex/figures/`，审阅后手工纳入 `2026-EgoAnchor/egoanchor_cn_v7.tex`，
再按论文工程单独编译。

## 八、诊断和强制重建

```powershell
pixi run eval qc
pixi run eval preprocess
pixi run eval rebuild
```

- `qc`：对活动组合引用的五个原始目录执行完整硬 QC。它会读取全部 JSON/JSONL，耗时较长。
- `preprocess`：检查五项 Stage 1 缓存，只补建缺失或失效项。
- `rebuild`：明确强制重建五本 XLSX 和五份指标缓存，再生成合并产物。日常局部重采不要用它。

修改工作簿契约、reader 或 QC 实现时，Stage 1 实现指纹会变化，对应缓存会重建。修改论文指标或 XLSX
分析 reader 时，只会使指标缓存失效。普通 Git 提交不会单独让缓存失效。

## 九、常见问题

### stage 为什么仍要求五项任务？

因为 `batch.json` 表示一组可进入论文的完整输入，需要检查共同配置和 Task 1--5 覆盖。但这只是选择
和身份检查，不代表重做五项数据。真正耗时的 QC 和 XLSX 写出只发生在变化任务上。

### promote 为什么很快？

它只切换组合清单。原始数据和工作簿已在共享缓存中，不需要复制，也不需要再验证一遍重型内容。

### analyze 为什么仍会重新生成所有图？

图和表代表当前五项组合，必须统一发布。重画本身很快；耗时的 XLSX 解析和片段统计已按 Task 缓存。

### 能否修改旧 task_data 目录？

不要。创建新 `vN` 目录。版本化不可变目录是快速缓存成立的前提，也是原始数据可审计的边界。

### 已有旧 active/raw 和 active/workbooks 怎么办？

新代码不会读取它们。第一次运行 `stage --promote` 会写入新的 `batch.json`，之后 `analyze` 只按清单
读取共享缓存。确认新流程结果后，可人工归档旧副本；工具不自动删除已有实验数据。

## 十、验证命令

```powershell
pixi run python -m compileall src/egoanchor/eval
pixi run python -m unittest discover -s src/egoanchor/eval/tests -t src -p test_*.py
pixi run eval config
pixi run eval sessions
```
