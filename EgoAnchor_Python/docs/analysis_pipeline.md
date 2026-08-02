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

| 命令                                            | 作用                                          | 是否写论文目录 |
| ----------------------------------------------- | --------------------------------------------- | -------------- |
| `pixi run eval status [all\|exp1-2\|exp3]`      | 查看配置、输入进度和最近构建状态；默认`all` | 否             |
| `pixi run eval validate <all\|exp1-2\|exp3>`    | 执行正式分析门禁                              | 否             |
| `pixi run eval analyze <all\|exp1-2\|exp3>`     | 生成本地统计、XLSX、TeX 和图片                | 否             |
| `pixi run eval copy-assets [all\|exp1-2\|exp3]` | 联合预检后复制指定实验的论文资源              | 是             |
| `pixi run eval data ...`                      | 管理实验专属原始输入和 Stage 1 缓存           | 否             |

实验三的统计和绘图已经合并进一次 `analyze exp3`。不存在单独的 `plot` 阶段，也不需要在命令之间
手工传递结果路径。

两边分析完成后，用以下命令同步论文资源：

```powershell
pixi run eval copy-assets all
```

`copy-assets all` 要求实验一/二和实验三都存在最新、完整、正式来源的构建。采集尚未完成时若只需要更新
实验一/二，运行无参数的 `copy-assets` 或明确运行 `copy-assets exp1-2`；命令不会自动跳过缺失的实验。

## 2. 工程结构

```text
src/egoanchor/eval/
├─ cli.py                         # 唯一人工命令入口
├─ experiments/
│  ├─ common/                    # 构建清单、摘要和事务性资源复制
│  ├─ experiment_1_2/
│  │  ├─ data.py                 # 五任务选择、Stage 1 缓存和活动批次
│  │  ├─ settings.py             # 共享 TOML 中实验一/二拥有的配置
│  │  ├─ workflow.py             # status/validate/analyze/copy-assets 生命周期
│  │  ├─ pipeline.py             # 五本 Stage 1 XLSX 到本地产物
│  │  └─ analysis/               # XLSX reader、指标、缓存、论文图表
│  ├─ experiment_3/
│  │  ├─ data.py                 # 正式空白模板生成
│  │  ├─ settings.py             # 共享 TOML 中实验三拥有的配置
│  │  ├─ workflow.py             # status/validate/analyze/copy-assets 生命周期
│  │  ├─ pipeline.py             # 正式原始工作簿到本地产物
│  │  ├─ template.py             # 采集工作簿结构与实时公式
│  │  └─ analysis/               # reader、计分、推断、结果工作簿与论文图
│  └─ workspace.py               # 跨实验统一编排
├─ preprocess/                   # 实验一/二 Stage 1 工作簿
├─ schema_v2/                    # 正式运行时日志 schema
├─ contracts/                    # 工作簿公共契约
└─ config/
   ├─ batch.toml                 # 路径、输入和资源复制目标
   └─ paper.toml                 # 冻结统计参数和画布参数
```

实验一/二与实验三是并列实验包，都以 `data/settings/workflow/pipeline` 为稳定骨架。实验一和实验二共享
同一套五任务日志、Stage 1 契约和论文结果，因此合并为 `experiment_1_2`，不拆成两个空壳目录。两边的根目录
只负责数据、配置、工作流和构建编排；reader、指标、计分、模型与绘图放在各自 `analysis/` 中。跨实验只共享
构建清单、文件摘要和事务性资源复制。

## 3. TOML 配置

### 3.1 `config/batch.toml`

配置按所有权分层：

```toml
[shared.paths]

[experiment_1_2.paths]
[experiment_1_2.copy_assets]
[experiment_1_2.copy_assets.tables]
[[experiment_1_2.copy_assets.relay]]

[experiment_3.paths]
[experiment_3.copy_assets]
```

`shared.paths.paper_root` 是唯一论文资源根目录。实验一/二的原始日志、工作簿缓存、指标缓存、暂存批次、
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
[experiment_3.equivalence]
[experiment_3.figures]
```

修改 `paper.toml` 中任一实验拥有的科学分析参数后，该实验旧构建会因配置摘要不一致而拒绝复制。
`batch.toml` 的路径和复制目标由工作流另行核验；另一实验的配置变化不会使无关缓存失效。

实验三正式采集前必须确认以下冻结项：`aq_mode`、`q10_enabled`、五项 TOST 等价界和问卷施测模态。
当前 `aq_mode = "full"`，而 Round 2 负担诊断记录建议缩减 AQ；是否切到 `reduced`
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
pixi run eval copy-assets exp1-2
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

只有 `copy-assets exp1-2` 会把清单中的面板、三张表格和 TOML 明确列出的 relay 文件写入论文目录。

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

计划中的正式原始工作簿路径由 TOML 固定为：

```text
../2026-EgoAnchor/material/EgoAnchor_Experiment3_RawData_24P_v5_1.xlsx
```

当前该路径下的文件未通过来源完整性门禁：4560 个核心响应与已标为 GPT 合成的参考工作簿逐格一致，
而且记录时间晚于审计日期。它现在只是流程演练输入，不能作为真实参与者数据或论文证据；正式采集前须替换为来源可核验的原始工作簿。

来源门禁采用正向批准。分析会把三段身份和核心响应规范排序后计算 SHA-256：已知合成指纹始终拒绝；
工作簿即使自报为正式来源，未登记的指纹也只能生成带警告的流程演练产物。真实采集完成并核对原始记录、同意与采集来源后，
研究者才把该指纹加入 `paper.toml [experiment_3.source_gate].approved_response_fingerprints`，随后重新运行验证和分析。
批准列表属于受版本控制的发布决定，不能由分析脚本自动学习或根据文件名推断。

正式采集时直接填写通过来源核验的工作簿，不需要反复生成模板。只有需要制作新的审查副本时才运行：

```powershell
pixi run eval data exp3 create-template --output ..\2026-EgoAnchor\material\exp3_template_review.xlsx
```

目标文件必须位于仓库内且尚不存在，命令拒绝覆盖任何已有工作簿。

### 7.1 人工输入

只有 `Participants` 和 `Records` 需要填写。`Participants` 保存 B1--B6 背景、同意、起止时间、
纳入决定和排除原因；`Records` 保存六个区块、两次方法级问卷和最终问卷的原始回答。TiA 反向项仍填原始分，
`6 - raw` 只在派生层执行。不要把任何小分、配对差或 Python 结果粘回这两张表。

纳入正式分析的参与者必须完整填写 B1--B6、签署同意、起止时间、六个有效区块、两条有效方法级记录和完整最终问卷。
已签署同意但标记为不纳入时，`退出/技术问题` 必须选择冻结主原因；补充情况只写 `备注`，不会复制到结果工作簿。
开始分析前，所有已同意者都要明确标记“纳入”或“排除”，已经开始的记录不能缺少同意确认。
年龄只检查是否为合法正整数，不由分析代码擅自设定成人纳入界限。基线不适允许留空；非空时必须使用下拉选项，缺失会在安全汇总中单独报告。

### 7.2 `Derived` 怎样工作

`Derived` 不是实施检查表，也无需人工填写。它是一张只读的 Excel 公式派生表，把每一步计分显式展开：

| 区域 | 一行代表什么               | 作用                                                                                                                    |
| ---- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| D1   | 一个方法×物体区块         | 判断区块是否有效，保留七个自制条目，计算 AQ-EQ/AQ-IQ，标记超时和连续同分，整理运行时审计值                              |
| D2   | 一位参与者对一种方法的问卷 | 分开显示“已作答”和“记录有效”；执行 TiA`6 - raw` 换向，再按各分量表的最少有效条目数计算 TiA-R/C、TiA-U/P 与 S-TIAS |
| D3   | 一位参与者×一种方法       | 区块级结局要求三个物体都有效后取均值；方法级 TiA/S-TIAS 小分直接带入，不再跨物体求均值                                  |
| D4   | 一位参与者                 | 计算`EgoAnchor - One-Euro` 配对差，`Pair_Check` 必须为 `OK`                                                       |
| D5   | 一位参与者                 | 处理偏好强度跳题，检查两项选择、区分信心、两道开放题和结束不适                                                          |
| D6   | 一位参与者                 | 分开派生`Completed_Session` 与 `Analysis_Complete`，并整理人口学、经验、时长、安全、平衡因子和审计状态              |

黄色单元格表示状态或离线统计占位，绿色单元格是公式派生值，其中也包括 ID、类别和标签。`Valid_Block` 与 `Valid_Record` 受
`Participants!纳入分析` 影响；参与者尚未标记为“是”时，相关行显示无效或空白是正常的，不代表原始数据已被删除。

TiA 的“无法回答”是显式响应，不等同于漏填。D2 先保留该响应，再分别应用 TiA-R/C 5/6、TiA-U/P 3/4 和 S-TIAS 3/3 的计分门槛。
因此某个分量表可能缺分，但同一方法的其他分量表仍可计分；正式结果按每个结局自己的配对 N 报告。

D6 的 `Audit_Status` 只描述当前记录状态，不替研究者作纳入决定：

| 状态                        | 含义                                                 |
| --------------------------- | ---------------------------------------------------- |
| `unused_slot`             | 该预分配行还没有人工数据                             |
| `not_consented`           | 行内已有记录，但“签署同意”不是“是”               |
| `pending_review`          | 已同意，但“纳入分析”仍为空                         |
| `included_complete`       | 已标记纳入，六个区块、两次方法级问卷和最终问卷均完整 |
| `included_but_incomplete` | 已标记纳入，但至少一项必要测量未完成                 |
| `excluded`                | 已明确排除，并记录了原因                             |
| `excluded_reason_missing` | 已明确排除，但原因仍为空                             |

`Derived` 和 `Analysis` 已启用无密码工作表保护，用于防止误覆盖公式。不要在其中输入、粘贴或排序。要修正数据时回到 `Participants` 或 `Records`，
公式会自动更新；正式分析仍从这两张原始表独立重算。

### 7.3 `Analysis` 该看什么

`Analysis` 只读取 `Derived`，是现场核对仪表板。首屏把“已完成会话”和“纳入者分析记录完整”分开显示，随后列出论文所需的参与者描述：

- 年龄与会话时长的 N、缺失数、均值、SD、中位数、IQR 和范围；
- 性别、主手、视力、VR/MR 经验和实物 MR 经验的人数及占纳入 N 的比例；
- 基线/结束不适与不适加重人数；安全分母是所有已同意且已开始体验者，不因后续排除而缩小；
- 六种物体排列、S1/S2、A 标签映射和先行方法的实际人数。

后续绿色区可实时显示 Mdn/IQR、配对差均值与 SD、`dz` 和操纵描述。黄色 W、p、Holm、`r_rb` 区间、信度和 TOST 不会回填本工作簿；
它们只出现在 Python 生成的独立结果工作簿中。这样可以避免现场公式和正式推断被误当成同一个计算源。

Office Viewer 和 `openpyxl` 不重算公式，只能显示已有缓存。现场查看实时值时使用能重算公式的 Excel；Python 分析本身不依赖任何公式缓存。

### 7.4 24 个平衡单元的记录边界

当前正式工作簿固定为 24 个参与者行和 24 个平衡单元。已签同意、开始后退出或被技术排除的记录不得覆盖。如需在排除后补招以保持最终 N=24，
必须先冻结可扩展的招募/替补日志和对应平衡单元规则；不得直接复用原 Participant_ID。当前代码不会擅自把被排除者替换掉。

建议每位参与者结束后执行：

```powershell
pixi run eval status exp3
```

每天备份正式原始工作簿，并核对 `included_confirmed`、样本流、区块评分数、方法级评分数和最终问卷完整数。

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
→ 写入并回读六页结果 XLSX
→ 生成 TeX 主表
→ 从同一次分析的内存数据生成正文候选 Figure 4 与 Figure 5 PNG/PDF
→ 校验全部产物并提交 complete 构建清单
```

来源门禁状态为 `approved` 时，正式产物位于：

```text
data/experiments/experiment_3/analysis/
├─ results/experiment3_analysis.xlsx
├─ tex/exp3_subjective.tex
├─ figures/figure4_exp3_primary_outcomes.{png,pdf}
├─ figures/figure5_exp3_published_scales.{png,pdf}
└─ provenance/build_result.json
```

门禁失败时，`provenance/build_result.json` 仍位于分析根目录；结果簿、TeX 和图片进入各自类别下的
`rehearsal_not_paper_evidence/`，文件名附带具体状态。各类文件的路径如下：

```text
results/rehearsal_not_paper_evidence/experiment3_analysis__<status>_rehearsal_not_paper_evidence.xlsx
tex/rehearsal_not_paper_evidence/exp3_subjective__<status>_rehearsal_not_paper_evidence.tex
figures/rehearsal_not_paper_evidence/figure4_exp3_primary_outcomes__<status>_rehearsal_not_paper_evidence.{png,pdf}
figures/rehearsal_not_paper_evidence/figure5_exp3_published_scales__<status>_rehearsal_not_paper_evidence.{png,pdf}
```

其中 `<status>` 只能是 `known_synthetic`、`unapproved_formal` 或 `nonformal`。这些文件用于流程演练，
不是正文候选 Figure，也不能由 `copy-assets exp3` 复制到论文目录。

结果工作簿固定为六张中文页，顺序和职责如下：

| 页面 | 内容 | 论文用法 |
| ---- | ---- | -------- |
| `说明` | 来源指纹、是否可用于论文、统计规则、参数摘要、警告和页面索引 | 先确认分析来源与发布资格 |
| `样本与质控` | 样本流、人口学、经验、安全、设计平衡和运行时操纵描述 | 样本、流程和操纵检查段 |
| `主结果` | 7 个主条目和已发表量表家族 5 项结局的描述统计、精确 Wilcoxon、家族内 Holm 与 `r_rb` | 论文完整结果表的唯一数字源 |
| `分物体描述` | 7 个主条目在三个物体上的两方法描述统计与配对差 | 方向一致性核查；不作逐物体推断 |
| `量表信度` | 已发表量表家族各结局按方法计算的当前样本 α、ω、Spearman--Brown 与测量单位 | 量表信度脚注或补充材料 |
| `选择结果` | 偏好、信任选择、偏好强度、区分信心及偏好×信任交叉 | 最终选择的描述性汇报 |

人口学只做描述，不事后拆成年龄、性别或经验亚组寻找显著性。会话时长和不适只作流程与安全审计，
不解释为方法表现。开放题原文及人工编码另存于不会被自动重建覆盖的独立文件，避免分析重跑覆盖人工工作。

确证结论只看 `主结果` 的“Holm 校正 p”：主证实家族 m=7，已发表量表家族 m=5。七个自制条目逐项分析，
不合并总分；AQ-EQ/AQ-IQ 先按冻结模式计算区块内子量表均值，再与七个自制条目一起在三个物体上取均值。
TiA 四个反向项按 `6 - raw` 换向，R/C 至少有 5/6 项、U/P 至少有 3/4 项有效时取有效条目均值；S-TIAS 三项均有效时取均值。
TiA 两个分量表与 S-TIAS 三项均分来自每种方法一次的方法级施测，不跨物体汇总。随后运行含并列中秩的双侧条件精确
Wilcoxon 符号置换，删除零配对差并另报非零配对数；两个家族分别做 Holm 校正。
“条件精确”只表示在给定非零绝对差及其中秩后枚举零假设下的等概率符号分配。该检验仍要求非零配对差的符号在零假设下
可交换，通常由配对差分布关于零对称的假设支撑，不能写成无假设检验；若正式数据明显偏离该条件，应在论文中列为解释限制。
`分物体描述` 不含 p 值或星号，不能被读成逐物体显著性结论。

两处必须按标注解读、不能照抄数字的列：

- **“r_rb 区间”**：匹配秩双列相关是有界统计量。若一项结局的全部非零配对差同向，`r_rb` 会取到 ±1，参与者级重采样也只能得到同一边界值。工作簿此时显示“不报告（方向完全一致）”；论文照此叙述，**不得把退化的 `[1.00, 1.00]` 当作置信区间**。其他行显示可解释的区间；若显示“不可估计”，先核对非零配对数和评分完整性。
- **“测量单位”**：AQ-EQ/AQ-IQ 显示“三物体均值”，因为其条目先在三个物体上取均值，α/ω 描述的是该分析单位的内部一致性，不是单个物体区块的信度。TiA 与 S-TIAS 显示“方法级单次施测”，对应每种方法完成一次的方法级问卷。两类信度不可互比，也不可与原量表发表的 α 直接对标。

CLMM 不进入冻结分析、结果工作簿或论文。被删除的自定义实现把 L-BFGS-B 的迭代近似逆 Hessian 当作协方差，
其标准误、Wald p 值和区间没有统计依据；数值 Hessian 又近奇异，不能安全替换。若后续要回答物体异质性问题，
应先冻结新的假设，再使用经过验证的序数混合模型实现，不能恢复这套旧代码。

两张正文候选 Figure 都是箱线图。`figure4_exp3_primary_outcomes` 上排 4 个、下排 3 个面板，展示 7 个主条目；`figure5_exp3_published_scales` 单行展示
AQ-EQ、AQ-IQ、TiA-R/C、TiA-U/P 与 S-TIAS。各面板使用与主分析一致的参与者级得分：区块级结局先在三个物体上取均值，
TiA 两个分量表与 S-TIAS 三项均分使用方法级单次施测得分；图中叠加半透明参与者级得分点和浅灰配对线。若所属家族内 Holm 校正后的 p<.05，
则在两个箱体上方显示括号和星号（`* p_Holm < .05`、
`** p_Holm < .01`、`*** p_Holm < .001`）。TiA 使用 1--5 理论量尺，其余面板使用 1--7。逐物体数据只检查方向，
不分别检验或添加星号。

合成和模拟工作簿只能通过 Python 包级 API 或独立模拟脚本调用 `allow_synthetic=True`。正式 CLI 没有该
选项，合成构建即使完整也会被 `copy-assets` 拒绝。

## 9. 联合分析和最终资源复制

两边正式数据都准备好后：

```powershell
pixi run eval validate all
pixi run eval analyze all
pixi run eval copy-assets all
```

`analyze all` 先运行联合门禁；任一实验未通过时，两条分析都不会开始。门禁通过后先分析实验一/二，再分析
实验三，避免两个统计任务并行争用 CPU。需要同时强制重建实验一/二 Stage 1 时使用：

```powershell
pixi run eval analyze all --rebuild-exp1-2
```

`copy-assets all` 在写任何论文目标前完成两条构建的来源、配置、实现、输入、输出摘要和目标冲突检查。复制过程
先暂存全部文件，再替换目标；中途失败会恢复所有已有目标，避免论文目录出现跨构建的新旧混合版本。

该命令只更新 TOML 声明的 PNG、PDF 和表格 TeX，不修改主稿，也不自动编译论文。复制成功后在
`2026-EgoAnchor` 目录运行项目规定的 XeLaTeX/`latexmk -xelatex` 检查。

## 10. 构建清单与失效规则

每条分析在 `provenance/build_result.json` 写统一清单，关键字段包括：

| 字段                       | 含义                                    |
| -------------------------- | --------------------------------------- |
| `schema`                 | 构建清单契约版本                        |
| `owner`                  | `experiment_1_2` 或 `experiment_3`  |
| `build_id`               | 输入、配置和实现共同决定的构建身份      |
| `status`                 | `building` 或 `complete`            |
| `source_kind`            | `formal` 或 `synthetic`             |
| `inputs`                 | 每个输入的绝对路径和 SHA-256            |
| `config_sha256`          | 该实验在`paper.toml` 中的科学参数摘要 |
| `implementation_sha256`  | 该实验分析源码树摘要                    |
| `outputs`                | 每个本地产物的路径、类型和 SHA-256      |
| `warnings` / `details` | 诊断、批次和模型摘要                    |

新分析一开始就把清单切换为 `building`。只有 XLSX、TeX、PNG、PDF 和其他声明产物全部成功并完成摘要后，
才原子提交 `complete`。因此失败重跑不会留下仍可复制的旧完成状态。

以下任一变化都会阻止复用旧构建：

- 原始工作簿或 Stage 1 XLSX 变化；
- 活动 batch 改变；
- 该实验拥有的 TOML 参数变化；
- 分析源码变化；
- 任一声明产物缺失或被手工修改；
- 实验三来源标记为 synthetic。

## 11. 输出、进度和退出码

机器可读结果始终是 stdout 上的一份 JSON。耗时阶段的 `tqdm` 进度只写 stderr，不会污染 JSON。

| 退出码 | 含义                                         |
| -----: | -------------------------------------------- |
|  `0` | 命令成功；`status` 中尚未采完不算错误      |
|  `1` | 文件系统、Git 或外部工具错误                 |
|  `2` | 数据、schema、QC、统计配置或资源复制契约错误 |

脚本自动化应同时检查退出码和 JSON 的 `passed` 字段，不要只搜索控制台文本。

## 12. 常见问题

### `status` 显示 `build.status = invalid`

通常是旧清单版本、配置变化或源码变化。重新运行对应的 `analyze exp1-2` 或 `analyze exp3`，不要手工修清单。

### `validate exp3` 报参与者不足或评分不完整

正式验证要求达到冻结的最小纳入人数和完整评分结构。采集期间用 `status exp3` 查看进度；不要为了临时运行
分析而降低 TOML 中的正式门槛。

### `copy-assets` 报输入、配置、实现或产物摘要变化

说明本地产物不再能证明来自当前正式输入。重新运行对应 `analyze`；不要复制文件绕过摘要门禁。

### Excel 中公式为空或未更新

Office Viewer 与 `openpyxl` 不负责重算公式。用 Excel 打开并重算可恢复现场显示；Python 正式分析始终从原始值
重算，不读取绿色区缓存作为统计输入。

### 想回到实验一/二旧版本批次

通过 `data exp1-2 stage --version ...` 或逐任务 `--task-version` 重新构造并提升组合。不要复制旧
`raw/workbooks` 快照，也不要手改活动 `batch.json`。

### 只想复制一个实验的论文资源

使用 `copy-assets exp1-2` 或 `copy-assets exp3`。最终论文同步使用 `copy-assets all`，这样才能确认两边资源来自
各自最新的完整构建。
