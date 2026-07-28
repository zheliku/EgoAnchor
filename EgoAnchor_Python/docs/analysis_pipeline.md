# EgoAnchor 统一离线评估与论文图表流水线

本文是实验一、实验二和实验三离线分析的唯一完整使用手册。全部人工操作从
`EgoAnchor_Python` 目录执行，入口固定为：

```powershell
cd EgoAnchor_Python
pixi run eval --help
```

正式命令不接受任意输入路径、输出路径或合成数据开关。路径和统计参数只从两份共享 TOML
读取，避免命令历史与正式配置不一致。

## 1. 统一工作模型

三个实验共用四个生命周期动作，实验一/二另有采集批次管理动作：

| 命令 | 作用 | 是否写论文目录 |
|---|---|---|
| `pixi run eval status [all\|exp1-2\|exp3]` | 查看配置、输入进度和最近构建状态；默认 `all` | 否 |
| `pixi run eval validate <all\|exp1-2\|exp3>` | 执行正式分析门禁 | 否 |
| `pixi run eval analyze <all\|exp1-2\|exp3>` | 生成本地统计、XLSX、TeX 和图片 | 否 |
| `pixi run eval publish <all\|exp1-2\|exp3>` | 联合预检后发布指定实验的论文资源 | 是 |
| `pixi run eval data ...` | 管理实验专属原始输入和 Stage 1 缓存 | 否 |

实验三的统计和绘图已经合并进一次 `analyze exp3`。不存在单独的 `plot` 阶段，也不需要在命令之间
手工传递结果路径。

最终论文发布应使用：

```powershell
pixi run eval publish all
```

`publish all` 要求实验一/二和实验三都存在最新、完整、正式来源的构建。采集尚未完成时若只需要更新
实验一/二，必须明确运行 `publish exp1-2`；命令不会自动跳过缺失的实验。

## 2. 工程结构

```text
src/egoanchor/eval/
├─ cli.py                         # 唯一人工命令入口
├─ workflows/
│  ├─ workspace.py               # status/validate/analyze/publish 统一编排
│  ├─ experiment_1_2.py          # 五任务批次、Stage 1 缓存和活动批次
│  └─ experiment_3.py            # 正式问卷工作簿工作流适配层
├─ paper_analysis/
│  ├─ common/                    # 构建清单、摘要和事务性发布
│  ├─ experiment_1_2/            # 实验一/二指标、图表和 TeX
│  └─ experiment_3/              # 计分、Wilcoxon、信度、CLMM、XLSX 和绘图
├─ preprocess/                   # 实验一/二 Stage 1 工作簿
├─ schema_v2/                    # 正式运行时日志 schema
├─ contracts/                    # 工作簿公共契约
└─ config/
   ├─ batch.toml                 # 路径、输入和发布目标
   └─ paper.toml                 # 冻结统计参数和画布参数
```

`workflows` 只组织阶段，不实现统计；`paper_analysis/experiment_1_2` 与
`paper_analysis/experiment_3` 保留各自的数据模型和统计核心。两边只共享生命周期清单、文件摘要和发布器。

## 3. TOML 配置

### 3.1 `config/batch.toml`

配置按所有权分层：

```toml
[shared.paths]

[experiment_1_2.paths]
[experiment_1_2.publish]
[experiment_1_2.publish.tables]
[[experiment_1_2.publish.relay]]

[experiment_3.paths]
[experiment_3.publish]
```

`shared.paths.paper_root` 是唯一论文发布根目录。实验一/二的原始日志、工作簿缓存、指标缓存、暂存批次、
归档批次和活动批次都在 `[experiment_1_2.paths]` 下。实验三的美化来源、正式原始工作簿和本地分析目录
都在 `[experiment_3.paths]` 下。

不要手工编辑活动批次的 `batch.json`，不要让分析输出落入原始日志目录，也不要把论文目录配置到
`EgoAnchor_Python/data` 内。加载器会拒绝越界或互相嵌套的托管路径。

### 3.2 `config/paper.toml`

统计参数同样按实验分层：

```toml
[experiment_1_2.contract]
[experiment_1_2.lag]
[experiment_1_2.transition]
[experiment_1_2.occlusion]

[experiment_3.contract]
[experiment_3.analysis]
[experiment_3.missing]
[experiment_3.clmm]
[experiment_3.equivalence]
[experiment_3.figures]
```

修改任一实验拥有的参数后，该实验旧构建会因配置摘要不一致而拒绝发布。另一实验的参数变化不会使
无关缓存失效。

实验三正式采集前必须确认以下冻结项：`aq_mode`、`q10_enabled`、五项 TOST 等价界、CLMM 开关和
问卷施测模态。当前 `aq_mode = "full"`，而 Round 2 负担诊断记录建议缩减 AQ；是否切到 `reduced`
必须依据权威计划规定的预实验冻结过程明确决定，不能在采集中途改变。

## 4. 状态与门禁

查看整个工作区：

```powershell
pixi run eval status
```

只看单个实验：

```powershell
pixi run eval status exp1-2
pixi run eval status exp3
```

`status` 是只读状态命令。输入尚未采完、尚无构建或旧构建清单失效时，命令仍返回退出码 0，并在 JSON
中给出 `missing`、`invalid` 或 `unavailable` 原因。

正式分析前运行：

```powershell
pixi run eval validate exp1-2
pixi run eval validate exp3
pixi run eval validate all
```

`validate exp1-2` 对活动清单引用的五份原始任务执行完整硬 QC。`validate exp3` 总是执行正式来源和完整性
门禁，不再提供弱校验选项；采集未完成时用 `status exp3` 看填表进度。`validate all` 会分别运行两边门禁，
即使一边失败也保留另一边的诊断。

## 5. 实验一/二日常重分析

已有正确活动批次时，不需要重复 `stage` 或 `preprocess`：

```powershell
pixi run eval status exp1-2
pixi run eval validate exp1-2
pixi run eval analyze exp1-2
pixi run eval publish exp1-2
```

`analyze exp1-2` 读取活动 `batch.json` 指向的五本 Stage 1 XLSX。逐任务指标缓存按工作簿摘要、实验一/二
参数摘要和指标实现摘要命中，只重算失效任务；随后统一生成八个 PNG/PDF 面板、三张主表、指标文件、
绘图数据和 TeX 片段。

本地产物位于：

```text
data/experiments/experiment_1_2/analysis/
├─ figures/
├─ metrics/
├─ plots/
├─ tex/
└─ provenance/build_result.json
```

只有 `publish exp1-2` 会把清单中的面板、三张表格和 TOML 明确列出的 relay 文件写入论文目录。

## 6. 实验一/二新增或局部重采

先把五项任务目录放入 `data/experiments/task_data/`，目录名必须为：

```text
task_<1..5>_v<正整数>_<YYYYMMDD_HHMMSS>_<object>
```

列出可选数据：

```powershell
pixi run eval data exp1-2 sessions
```

默认按每项任务选择最高数值版本，并在同版本内选择最新时间：

```powershell
pixi run eval data exp1-2 stage
```

常用选择方式：

```powershell
pixi run eval data exp1-2 stage --version v2
pixi run eval data exp1-2 stage --task-version 3=v5 --task-version 4=v4
pixi run eval data exp1-2 stage --object controller_right
pixi run eval data exp1-2 stage --promote
```

不带 `--promote` 时，命令只在 `_staging/experiment_1_2/<batch_id>/` 写轻量组合清单。核对 JSON 中的
`selected_task_data`、`cache_hits` 和 `rebuilt_tasks` 后再切换：

```powershell
pixi run eval data exp1-2 promote <batch_id>
```

省略 `<batch_id>` 时，暂存区必须恰好只有一个批次。切换不同组合会把旧活动清单和旧分析归档到
`_archive/experiment_1_2/`，不会复制数百 MB 原始日志和工作簿。

只补建缺失或失效工作簿：

```powershell
pixi run eval data exp1-2 preprocess
```

明确要求五本工作簿全部重建：

```powershell
pixi run eval data exp1-2 preprocess --force
```

也可以在分析时一次完成强制重建：

```powershell
pixi run eval analyze exp1-2 --rebuild
```

局部重采必须创建新的 `vN` 目录。禁止原地修改已进入清单的版本目录；来源快照变化会使提升和分析失败。

## 7. 实验三原始模板与采集

正式原始工作簿已由 TOML 固定为：

```text
../2026-EgoAnchor/material/EgoAnchor_Experiment3_RawData_24P_v5_1.xlsx
```

日常采集直接填写该文件，不需要反复生成模板。只有需要制作新的审查副本时才运行：

```powershell
pixi run eval data exp3 create-template --output ..\2026-EgoAnchor\material\exp3_template_review.xlsx
```

目标文件必须位于仓库内且尚不存在，命令拒绝覆盖任何已有工作簿。

原始评分只写入 `Participants` 和 `Records` 规定区域；TiA 反向项仍存原始分，`6 - raw` 只在派生层计算。
不要用计算结果覆盖原始评分。工作簿中的绿色区和 `Derived`/`Analysis` 公式用于现场核对可实时计算的小分，
Python 会从原始值独立重算全部统计。

建议每位参与者结束后执行：

```powershell
pixi run eval status exp3
```

每天备份正式原始工作簿，并核对 `included_confirmed`、区块评分数、方法级评分数和最终选择数。Office Viewer
和 `openpyxl` 不计算公式；它们只显示工作簿已有缓存。现场最终核对应使用能重算公式的 Excel，Python 分析本身
不依赖这些缓存值。

## 8. 实验三完成分析

采集完成后：

```powershell
pixi run eval validate exp3
pixi run eval analyze exp3
```

`analyze exp3` 内部顺序固定为：

```text
读取并验证正式原始工作簿
→ 从原始评分计算区块、量表和参与者配对分
→ Wilcoxon、分层 Holm、效应量、信度和操纵检查
→ 逐条目 CLMM
→ 写入并回读结果 XLSX
→ 生成 TeX 主表
→ 只从结果 XLSX 回读绘图数据并生成 PNG/PDF
→ 校验全部产物并提交 complete 构建清单
```

结果位于：

```text
data/experiments/experiment_3/analysis/
├─ results/experiment3_analysis.xlsx
├─ tex/exp3_subjective.tex
├─ figures/figure4_exp3_paired.{png,pdf}
├─ figures/figure5_exp3_scales.{png,pdf}
└─ provenance/build_result.json
```

重点审阅结果工作簿中的纳入人数、warnings、主家族和已发表量表家族的 Holm 校正、CLMM 收敛数、操纵
检查及信度。不能手工修改结果 XLSX 后把它当作正式绘图源；原始工作簿、TOML 或分析代码变化后，直接重新
运行 `analyze exp3`。

合成和模拟工作簿只能通过 Python 包级 API 或独立模拟脚本调用 `allow_synthetic=True`。正式 CLI 没有该
选项，合成构建即使完整也会被 `publish` 拒绝。

## 9. 联合分析和最终发布

两边正式数据都准备好后：

```powershell
pixi run eval validate all
pixi run eval analyze all
pixi run eval publish all
```

`analyze all` 先运行联合门禁；任一实验未通过时，两条分析都不会开始。门禁通过后先分析实验一/二，再分析
实验三，避免两个统计任务并行争用 CPU。需要同时强制重建实验一/二 Stage 1 时使用：

```powershell
pixi run eval analyze all --rebuild-exp1-2
```

`publish all` 在写任何论文目标前完成两条构建的来源、配置、实现、输入、输出摘要和目标冲突检查。发布过程
先暂存全部文件，再替换目标；中途失败会恢复所有已有目标，避免论文目录出现跨构建的新旧混合版本。

发布只更新 TOML 声明的 PNG、PDF 和表格 TeX，不修改主稿，也不自动编译论文。发布成功后在
`2026-EgoAnchor` 目录运行项目规定的 XeLaTeX/`latexmk -xelatex` 检查。

## 10. 构建清单与失效规则

每条分析在 `provenance/build_result.json` 写统一清单，关键字段包括：

| 字段 | 含义 |
|---|---|
| `schema` | 构建清单契约版本 |
| `owner` | `experiment_1_2` 或 `experiment_3` |
| `build_id` | 输入、配置和实现共同决定的构建身份 |
| `status` | `building` 或 `complete` |
| `source_kind` | `formal` 或 `synthetic` |
| `inputs` | 每个输入的绝对路径和 SHA-256 |
| `config_sha256` | 该实验拥有的 TOML 参数摘要 |
| `implementation_sha256` | 该实验分析源码树摘要 |
| `outputs` | 每个本地产物的路径、类型和 SHA-256 |
| `warnings` / `details` | 诊断、批次和模型摘要 |

新分析一开始就把清单切换为 `building`。只有 XLSX、TeX、PNG、PDF 和其他声明产物全部成功并完成摘要后，
才原子提交 `complete`。因此失败重跑不会留下仍可发布的旧完成状态。

以下任一变化都会阻止复用旧构建：

- 原始工作簿或 Stage 1 XLSX 变化；
- 活动 batch 改变；
- 该实验拥有的 TOML 参数变化；
- 分析源码变化；
- 任一声明产物缺失或被手工修改；
- 实验三来源标记为 synthetic。

## 11. 输出、进度和退出码

机器可读结果始终是 stdout 上的一份 JSON。耗时阶段的 `tqdm` 进度只写 stderr，不会污染 JSON。

| 退出码 | 含义 |
|---:|---|
| `0` | 命令成功；`status` 中尚未采完不算错误 |
| `1` | 文件系统、Git 或外部工具错误 |
| `2` | 数据、schema、QC、统计配置或发布契约错误 |

脚本自动化应同时检查退出码和 JSON 的 `passed` 字段，不要只搜索控制台文本。

## 12. 常见问题

### `status` 显示 `build.status = invalid`

通常是旧清单版本、配置变化或源码变化。重新运行对应的 `analyze exp1-2` 或 `analyze exp3`，不要手工修清单。

### `validate exp3` 报参与者不足或评分不完整

正式验证要求达到冻结的最小纳入人数和完整评分结构。采集期间用 `status exp3` 查看进度；不要为了临时运行
分析而降低 TOML 中的正式门槛。

### CLMM 未全部收敛

先看结果工作簿中的完整模型与约简模型状态和 warnings。不要用普通有序回归冒充随机效应模型，也不要删除
不收敛记录。确认原始评分与配置后，再决定是否按论文统计计划报告约简结果。

### `publish` 报输入、配置、实现或产物摘要变化

说明本地产物不再能证明来自当前正式输入。重新运行对应 `analyze`；不要复制文件绕过摘要门禁。

### Excel 中公式为空或未更新

Office Viewer 与 `openpyxl` 不负责重算公式。用 Excel 打开并重算可恢复现场显示；Python 正式分析始终从原始值
重算，不读取绿色区缓存作为统计输入。

### 想回到实验一/二旧版本批次

通过 `data exp1-2 stage --version ...` 或逐任务 `--task-version` 重新构造并提升组合。不要复制旧
`raw/workbooks` 快照，也不要手改活动 `batch.json`。

### 只想发布一个实验

显式使用 `publish exp1-2` 或 `publish exp3`。最终论文同步仍必须使用 `publish all`，这样才能确认两边资源来自
各自最新的完整构建。
