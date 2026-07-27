# 实验一/二离线分析

正式数据操作只从 `pixi run eval` 进入。它负责整理 session、生成本地指标和 TeX 片段、发布图表；
不再编译或修改论文主稿。

## 数据流

```text
data/eval/<session_id>                         # 采集与同步中的原始 session
  -> 两端停止后移动并重命名
data/experiments/task_data/task_<N>_v<V>_<YYYYMMDD_HHMMSS>_<object>
  -> stage
  -> task_workbooks/<task-directory>/task_N_complete.xlsx
  -> _staging/<batch_id>/batch.json
  -> promote
  -> experiment_1_2/batch.json
  -> analyze
  -> task_analysis/<task-directory>/task_N_complete_metrics.json
  -> experiment_1_2/analysis/{metrics,plots,figures,tex,provenance}
  -> copy-assets
  -> 2026-EgoAnchor 中的 PNG/PDF 和三张表格 TeX
```

`analyze` 只写活动批次的 `analysis/`，不会改动 `2026-EgoAnchor` 的主稿、表格、图片或 PDF。
`copy-assets` 在审阅后发布图片和三张表格 TeX；图环境 TeX 仍由研究者手工处理。

## 配置

```text
pixi run eval config
```

`batch.toml` 控制数据目录和论文图表发布路径：

- `[paths].task_data_root`：归档后可供 `stage` 自动选择的任务数据目录。
- `[paths].task_workbook_root`：每个原始任务目录唯一对应的 Stage 1 工作簿缓存。
- `[paths].task_analysis_root`：每本 Stage 1 工作簿唯一对应的指标缓存。
- `[paths].active_root`：当前五项任务组合清单和合并后的分析产物。
- `[paths].paper_root`：`copy-assets` 的论文目标根目录。
- `[copy_assets]`：实验面板的目标目录。
- `[copy_assets.tables]`：三张分析表格的论文相对目标路径，键固定，文件名可修改。
- `[[copy_assets.relay]]`：relay PNG/PDF 的明确来源和目标位置。

更换定性 replay 图时，直接修改 `[[copy_assets.relay]]` 的 `source` 与 `destination`。程序不会按修改
时间猜测最新文件。

## 新采集五项任务

```text
pixi run eval sessions
pixi run eval stage --promote
pixi run eval analyze
pixi run eval copy-assets
```

采集和 Mutagen 仍写入 `data/eval/<session_id>`。两端停止且同步完成后，把每个完整 session 移到
`data/experiments/task_data/`，并按以下格式重命名：

```text
task_<任务号>_v<版本>_<YYYYMMDD_HHMMSS>_<物体>
```

例如 `task_1_v1_20260724_005757_controller_right`。时间和物体必须与内部
`manifest.session_id`、`manifest.object_id` 一致。版本是每项任务独立维护的正整数。默认选择时，
各任务先取最高版本，再取该版本中时间最新的目录；不按文件修改时间排序。

需要复现指定版本时使用：

```text
pixi run eval stage --promote --version v1
pixi run eval stage --promote --task-version 3=v2 --task-version 4=v3
pixi run eval stage --promote --object controller_right
```

`--version` 统一限制五项任务，`--task-version` 只覆盖指定任务且可以重复。如果同一目录中有多个物体
都完整覆盖任务 1--5，必须用 `--object` 指定。目录名只负责候选选择；任务身份和配置一致性仍以
`manifest.json` 和固定文件集合为准。

`stage` 不复制 raw。它先检查五个 manifest 的共同身份，再逐项检查缓存。已有缓存直接复用；新目录、
目录内容变化或 Stage 1 实现变化时，只对对应 Task 物化事件、执行完整 QC 并写出 XLSX。首次运行通常
显示五个 `rebuild`，只替换 Task 3 后应显示 Task 1、2、4、5 为 `hit`，Task 3 为 `rebuild`。

`promote` 只核对轻量 `batch.json` 及其引用文件，然后切换活动组合，不重跑 QC，也不回读 XLSX。
正常流程中，`promote` 后直接运行 `analyze`，不需要 `preprocess`。

## analyze 的本地产物

```text
pixi run eval analyze
```

输入由活动 `batch.json` 指向五本 Stage 1 XLSX。命令不读取 raw JSON/JSONL、不改写 XLSX，也不调用
XeLaTeX。每本 XLSX 的指标独立缓存；缓存命中时不打开工作簿，只有变化的 Task 会重新扫描。之后仍将
五项结果合并，再统一生成完整图表和 TeX。

```text
data/experiments/experiment_1_2/analysis/
├─ metrics/                         # 完整精度 CSV、时序策略配对数据和性能统计
├─ plots/figure_plot_data.xlsx      # 图二、图三审计数据，不是绘图输入
├─ figures/                         # 八个面板，各自的 PNG 和 PDF
├─ tex/
│  ├─ tables/                       # 三张由 copy-assets 显式发布的表格 TeX
│  └─ figures/                      # 图二、图三的 figure 环境 TeX
└─ provenance/                      # 输入摘要、参数 SHA-256 和 build_result.json
```

实验一图二按静止平移、静止旋转、动态平移、动态旋转排列为一行四个双纵轴面板；左轴是误差，右轴是抖动。
静止误差采用中心化 P95，动态误差采用最佳时延对齐后的 RMSE，动态抖动采用同一最佳时延下残差帧增量 P95，
避免把真实运动直接计为抖动。动态表另报告不补偿时延的 current-time RMSE，用于披露包含相位差的当前配准误差。
未对齐显示位姿的原始帧间增量包含目标真实运动，不作为 perceived jitter。图 3(d) 的主比较是 *Smoothed KF Extrapolation* 与关闭 StaticLock 的
*Linear/SLERP*；*Hermite Interpolation* 是补充条件。完整数值仍保留在 `metrics/` 和
`figure_plot_data.xlsx`。

首次分析的主要耗时仍是 XLSX ZIP/XML 读取和 Python 分组统计。后续只替换一个 Task 时，耗时主要来自
该 Task 的 XLSX；另外四项直接读取小型 JSON 指标缓存。

## 发布图片与表格 TeX

```text
pixi run eval copy-assets
```

该命令先校验 `analysis/provenance/build_result.json` 的 batch ID，再严格按本次 `figure_paths` 复制八组实验
PNG/PDF，按 `artifact_paths` 和 `[copy_assets.tables]` 发布三张表格 TeX，并复制 TOML 中逐项声明的 relay
PNG/PDF。所有来源在写入前统一校验，分析目录中的旧面板和旧表不会被推断发布；命令不修改主稿。

表格默认发布为：

```text
2026-EgoAnchor/tables/exp1_static.tex
2026-EgoAnchor/tables/exp1_dynamic.tex
2026-EgoAnchor/tables/exp2_design.tex
```

图环境 TeX 位于 `analysis/tex/figures/`，仍需研究者审阅后手工纳入论文。

工作稿与 PDF 的编译不属于 `pixi run eval`。最新中文工作稿为 `2026-EgoAnchor/egoanchor_cn_ai_v8.tex`，其中 `ai` 表示该版本使用 AI 辅助撰写；该稿目前尚不可用，只供继续修改和内部审阅。完成手工引入后，
在 `2026-EgoAnchor/` 下运行：

```powershell
latexmk -xelatex -synctex=1 -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_ai_v8.tex
```

PDF 和辅助文件都使用工作稿 basename `egoanchor_cn_ai_v8`，写入 `2026-EgoAnchor/pdf/`。
工作区的 LaTeX Workshop 输出目录也指向 `%DIR%/pdf`，可以直接按 TeX 文件名打开 PDF。

## 诊断与重建

```text
pixi run eval qc
pixi run eval preprocess
pixi run eval rebuild
```

- `qc`：显式深查活动清单引用的五个原始目录；日常增量流程不需要运行。
- `preprocess`：补建当前组合中缺失或失效的任务工作簿，已有缓存不重做。
- `rebuild`：显式强制重建五本工作簿和全部指标缓存，不切换批次、不发布图表。

工作簿只能只读查看，不要用 Excel 保存后继续正式分析。`figure_plot_data.xlsx` 是审计输出，手工修改它不会
重绘图片。

## 常用完整命令

```powershell
pixi run eval stage --promote
pixi run eval analyze
pixi run eval copy-assets
```

内部批次名由任务 1--5 的 manifest 时间按任务号组成。它确定地表示整组输入，局部重采任一任务都会
得到新批次名；`--promote` 会在变化任务的缓存发布成功后自动切换活动组合，因此无需手工输入该名称。

## 实验三：问卷原始数据与分析

实验三的正式输入和实验一/二的 Stage 1 XLSX 完全隔离。它只接受 24 个平衡单元的问卷原始工作簿，
不读取 schema-v2 事件、不会把问卷答案写回 Unity，也不会用日常物体场景生成没有平台真值的绝对配准误差。
实验三的结论边界是跨对象的主观感知评价和无需真值的自参考运行时日志；它不提供客观任务表现证据。

### 文件与数据流

实验三没有单独的 TOML。三个实验共用现有的 `batch.toml` 和 `paper.toml`：前者保存输入、分析输出和论文发布
路径，后者保存统计契约与图尺寸。实验一/二只读取自己的配置节，实验三只读取 `[experiment_3.*]`，两边的参数
摘要互不污染。每项配置都带行内中文说明；正式采集开始后不要临时修改计分、缺失值、检验或多重校正规则。

分析代码同样按实验并列，不把实验三挂在旧模块旁边：

```text
src/egoanchor/eval/paper_analysis/
├─ common/                 # 两条流水线共享的资源发布契约
├─ experiment_1_2/         # 实验一/二指标、图表、工作簿和流水线
└─ experiment_3/           # 实验三读取、计分、推断、CLMM、图表和流水线
```

`paper_analysis` 顶层不重导出两边的业务接口。CLI 分别从两个实验包的包级入口导入，再在 `copy-assets` 阶段合并
发布计划。

```text
2026-EgoAnchor/material/
  EgoAnchor_Experiment3_DataCollection_24P_v5_1_Beautified_Checked_VSCodeSafe.xlsx
  -> pixi run eval experiment3 build-template --destination <尚不存在的新文件.xlsx>
  EgoAnchor_Experiment3_RawData_24P_v5_1.xlsx
  -> 人工填写 Participants 与 Records；Derived/Analysis 只读
  -> pixi run eval experiment3 validate --complete
  -> pixi run eval experiment3 analyze
  data/experiments/experiment_3/analysis/
  ├─ results/experiment3_analysis.xlsx
  ├─ tex/exp3_subjective.tex
  └─ provenance/build_result.json
  -> pixi run eval experiment3 plot
  └─ figures/figure4_exp3_paired.{png,pdf}, figure5_exp3_scales.{png,pdf}
  -> pixi run eval copy-assets
  2026-EgoAnchor/figures/panels/ 与 tables/exp3_subjective.tex
```

`EgoAnchor_Experiment3_RawData_24P_v5_1.xlsx` 是已经生成并验证的默认正式输入。生成命令从美化定稿复制设计映射、
对象顺序和方法盲法映射，清空年龄、状态、原始评分、运行时审计、最终选择和开放题；不会复制模拟作答、
模型标语或历史推断结果。`build-template` 强制要求 `--destination`，目标已经存在时直接拒绝，不能覆盖正在填写
的正式数据。日常采集和分析不需要重新生成模板；只有审查模板构造时才生成另一个新文件。

```powershell
pixi run eval experiment3 config
pixi run eval experiment3 build-template --destination ..\2026-EgoAnchor\material\exp3_template_review.xlsx
```

### 填写正式原始模板

只有 `Participants` 和 `Records` 可以人工填写。`Questionnaire` 是条目字典，`Derived` 与 `Analysis` 是公式
审计面板，不能在其中粘贴数值或修改公式。工作簿打开时强制完整重算；若 Excel 显示旧值，先启用自动计算并
等待状态栏完成计算，再关闭并重新打开确认。

`Participants` 的 A--K 列是预设平衡单元，不可改动。填写 L--X 的背景、同意、起止时间、纳入状态和备注。
只有 `纳入分析=是` 的参与者会进入实时小分、离线统计和图表；被排除者保留在原始表中以便审计，但不会进入 N。

`Records` 由三段组成：

- A 段 144 行：每人六个方法×物体区块。13 个正式七点评分必须完整；Q10 是默认关闭的可选项。填写任务、
  问卷和区块有效状态，并保留运行时审计值和技术说明。`区块有效=是` 是是否纳入区块统计的明确裁决，技术说明
  可以记录非排除性现象。
- B 段 48 行：每人两条方法级记录。TiA 可填 `无法回答`，但 R/C 至少五项、U/P 至少三项才形成分量表；
  S-TIAS 三项必须完整。尺度切换确认、A/B 归属回忆确认和方法级记录有效都必须填“是”。TiA 反向项只会在
  `Derived` 中按 `6-原始分` 计分，原始分永远保留。
- C 段 24 行：填写标签层的偏好和信任选择、区分信心、开放题和不适。没有明显偏好时，偏好强度填 `N/A` 或
  留空；做出偏好时必须填写 1--7。

下拉和整数校验会阻止常见的输入错误。不要删除记录行、增加参与者、重排 ID 或解除 A/B 映射，因为 reader
会严格要求 `24 / 144 / 48 / 24` 的身份结构。日常保存前可做只读结构检查：

```powershell
pixi run eval experiment3 validate
```

正式分析前必须完成严格检查：

```powershell
pixi run eval experiment3 validate --complete
```

该检查拒绝模拟输入、少于 18 个明确纳入者、未完成的有效区块、无效的方法级审核、非法量尺、最终选择缺失和
被修改的平衡映射。少于 24 人但不少于 18 人会产生警告，并按实际配对 N 报告。

### 实时面板与离线统计

模板的绿色单元格是 Excel 即时审计，不是第二套统计实现。`Derived` 先按参与者纳入状态和区块有效状态形成
AQ 小分、TiA 换向小分、三个物体上的参与者×方法均值和 `EgoAnchor - One-Euro` 配对差。`Analysis` 由此显示：

- 纳入人数、有效区块和方法级记录、最终问卷完成度、过长问卷与连续同分诊断；
- 主证实七项和五个已发表量表的 N、两种方法的 Q1/中位数/Q3、配对差中位数、均值、SD 与 `dz`；
- 候选率、VCD、接纳率、输出可用率和遮挡时长的参与者级描述值；
- 偏好强度与区分信心的纳入者级描述值。

黄色单元格特意不在 Excel 中伪造：Wilcoxon W、精确 p、Holm 校正、匹配秩双列相关及其自举区间、信度、
CLMM 和 TOST 都只由 Python 写入结果工作簿。Python 不读取任何公式缓存，而是从 `Participants` 与 `Records`
的原始值重新计分，因此绿色定义与离线结果共享同一纳入、三物体均值和差值方向契约。

### 生成结果与论文图

```powershell
pixi run eval experiment3 analyze
pixi run eval experiment3 plot
```

`analyze` 在 stderr 显示 `tqdm` 进度，stdout 只输出可存档的 JSON。它写入
`results/experiment3_analysis.xlsx`，其中有来源与参数摘要、主结果、量表、次级条目、当前样本信度、逐物体描述、
操纵检验、选择、开放题双编码工作区、CLMM 系数/对象内对比和两张图的逐行输入数据。结果文件每张表均可直接
筛选、冻结表头和审计；`README` 记录输入与参数 SHA-256，避免拿到旧分析结果后误写论文。

冻结的统计规则如下：

- 单位是参与者；先在三个对象取均值，再形成 `EgoAnchor - One-Euro` 完整配对。
- 主证实顺序固定为 Q1、Q8、Q2、Q9、Q3、Q6、Q7，双侧 Wilcoxon、删除零差、平均并列秩的精确符号置换 p，
  并在该七项家族内 Holm 校正。
- 已发表量表家族顺序固定为 AQ-EQ、AQ-IQ、TiA-R/C、TiA-U/P、S-TIAS，独立执行 Holm。AQ 默认完整三条目；
  只有预实验作出明确冻结决定时才把 `aq_mode` 改成 `reduced` 并重新分析。
- `r_rb` 以参与者级固定种子自举 10,000 次给出 95% 百分位区间；分位数采用与 Excel `QUARTILE.INC` 一致的
  type-7 规则，`dz` 使用配对差的样本 SD（`ddof=1`）。
- 信度仅是当前样本的 raw Cronbach alpha、单因子 omega total；缩减 AQ 两条目时 omega 留空并报告
  Spearman--Brown。它不构成对象化改编量表的验证声明。
- 逐条目 CLMM 是次级稳健性分析：`response ~ method*object + object_position + within_object_order + (1|participant)`，
  使用 Gauss--Hermite 求积的真实随机截距累积 logit。每个模型输出收敛状态、迭代数、梯度、随机截距 SD 和
  交互 LRT；只有交互显著才对三个对象内方法对比作条件 Holm。
- TOST 默认关闭。所有正等价界必须在预实验冻结后同时写入 TOML 并把 `equivalence.enabled` 设为 `true`；
  不得把“不显著”解释为等价。

`plot` 只读 `experiment3_analysis.xlsx` 的 `Plot_Paired`、`Plot_Scales` 和结果表，绝不回读原始工作簿。它输出两张
论文级 PNG/PDF：图 4 的四面板展示 Q1、Q8、Q3、Q6 在三个对象上的参与者内配对、箱体分布、均值标记和
Holm 校正结果；图 5 用紧凑小多图展示 Q6/Q7 与五个已发表量表分数，七点和五点量尺各用自己的纵轴。版式参考
SelfBlending 的紧凑分组统计图和 VRGaussianAvatar 的箱体、均值标记与顶部显著性括号，同时保留实验三权威设计
冻结的配对线，而不是改成柱状图。修改结果 XLSX 后，来源摘要校验会失败；应重新运行 `analyze`，再运行 `plot`。

若只在审查副本上工作，可显式覆盖输入或本地输出位置；输出仍必须位于 `EgoAnchor_Python/data/`：

```powershell
pixi run eval experiment3 validate --input .\data\review\raw.xlsx
pixi run eval experiment3 analyze --input .\data\review\raw.xlsx --output-root .\data\review\experiment3
pixi run eval experiment3 plot --output-root .\data\review\experiment3
```

### 发布到论文目录

```powershell
pixi run eval copy-assets
```

统一发布命令先分别构造实验一/二与实验三的只读发布计划，再联合检查全部来源、摘要、后缀和目标冲突。只有联合
预检全部通过才开始复制。实验三还要求构建完整、输入为正式工作簿，并且输入 SHA、配置 SHA、结果 SHA 和四个
图摘要一致。默认发布文件为：

```text
2026-EgoAnchor/figures/panels/figure4_exp3_paired.png
2026-EgoAnchor/figures/panels/figure4_exp3_paired.pdf
2026-EgoAnchor/figures/panels/figure5_exp3_scales.png
2026-EgoAnchor/figures/panels/figure5_exp3_scales.pdf
2026-EgoAnchor/tables/exp3_subjective.tex
```

模拟或演练输入永远不能发布。若实验一/二活动批次尚未准备好，`copy-assets` 可以只发布通过校验的正式实验三
资源，并在 JSON 中明确标记实验一/二为跳过；两条发布链都就绪时则作为同一份联合计划发布。任一已就绪计划的
来源或摘要失效都会让命令在写入前失败。主稿的图环境仍由研究者审阅后手工纳入，该命令不会编译或改写主稿。

### 实验三验证

```powershell
pixi run python -m unittest egoanchor.eval.tests.test_artifacts egoanchor.eval.tests.test_experiment3
pixi run eval experiment3 config
pixi run eval experiment3 validate
```

正式采集完成后的最短路径是：`validate --complete`、`analyze`、`plot`、审阅结果工作簿与 PNG/PDF、最后
`copy-assets`。任何原始数据、TOML 或分析源码的变化都应从 `analyze` 重新开始，不能复用旧的图或 TeX。

## 验证

```text
pixi run python -m compileall src/egoanchor/eval
pixi run python -m unittest egoanchor.eval.tests.test_batch egoanchor.eval.tests.test_paper_pipeline
pixi run eval config
```

阶段边界和异常处理见 `2026-EgoAnchor/experiment_1_2_analysis_reproduction_manual_zh.md`。
