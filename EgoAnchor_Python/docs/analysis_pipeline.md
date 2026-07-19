# 实验一/二离线分析

本文说明如何从五个只读 schema-v2 task 目录重建实验一/二结果。正式入口只有 `egoanchor.eval.cli`，科学参数的唯一入口是 `src/egoanchor/eval/config/analysis_params.toml`。

面向采集新数据的逐步操作手册见 [`2026-EgoAnchor/experiment_1_2_analysis_reproduction_manual_zh.md`](../../2026-EgoAnchor/experiment_1_2_analysis_reproduction_manual_zh.md)。本文保留阶段契约、开发者验收和扩展说明。

## 数据流与边界

```text
raw JSON/JSONL
  -> preprocess -> 每个 task 一个完整 XLSX
  -> analyze -> 审计、指标、绘图和论文 CSV + 实验审阅 XLSX
  -> publish -> PDF/PNG 与四个 TeX 审计文件
  -> materialize-paper -> egoanchor_cn_v6.tex 受控区块
```

- Stage 1 `preprocess` 只读 raw task 目录。任一 task 的 QC 失败时返回 2，整批不发布 XLSX。
- Stage 2 `analyze` 只读 Stage 1 XLSX，不得打开 raw JSON 或 JSONL。它同时发布正式 CSV 和便于人工检查的 `exp1_analysis.xlsx`、`exp2_analysis.xlsx`；审阅工作簿只重排同批已定稿行，不增加科学计算层，也不作为 Stage 3 输入。
- Stage 3 `publish` 只读 Stage 2 CSV，不重新联接 reference、切事件窗或计算科学指标。
- Stage 4 `materialize-paper` 的实验数据只来自 Stage 3 的四个固定 TeX，同时读取主稿作为写入目标；它不读取 CSV、XLSX 或 JSON/JSONL，也不接受 CSV 根目录。
- 主稿已内联数字和表格，不依赖四个生成 TeX 才能编译；实验一行为总览和实验二机制归因两张正式 PDF 图仍是外部论文资源。

统计单位是 event/segment，不是 frame。系统指标先在 event 内计算，再按 trial、session 汇总；VCD risk-coverage 保持 candidate-level，独立于 event 汇总。所有结果按场景分别报告，不计算跨场景总分或总排名。

## 完整重建

以下命令在仓库的 `EgoAnchor_Python` 目录运行。复现新批次时优先使用中文操作手册中的动态 task 目录收集片段；这里仍列出当前五个正式目录，便于审计和 CI 复现。

```powershell
$codeVersion = (git rev-parse HEAD).Trim()
$taskDirs = @(
    "data/eval/task_1_20260717_203329_controller_right"
    "data/eval/task_2_20260717_203749_controller_right"
    "data/eval/task_3_20260717_204156_controller_right"
    "data/eval/task_4_20260717_204943_controller_right"
    "data/eval/task_5_20260717_205539_controller_right"
)
$workbooks = @(
    "data/analysis/complete/task_1_complete.xlsx"
    "data/analysis/complete/task_2_complete.xlsx"
    "data/analysis/complete/task_3_complete.xlsx"
    "data/analysis/complete/task_4_complete.xlsx"
    "data/analysis/complete/task_5_complete.xlsx"
)

pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src
pixi run python -m egoanchor.eval.cli qc $taskDirs
pixi run python -m egoanchor.eval.cli preprocess $taskDirs --out data/analysis/complete --code-version $codeVersion
pixi run python -m egoanchor.eval.cli analyze $workbooks --out data/analysis/results --code-version $codeVersion
pixi run python -m egoanchor.eval.cli publish data/analysis/results --paper-root ../2026-EgoAnchor
pixi run python -m egoanchor.eval.cli materialize-paper --paper-root ../2026-EgoAnchor
```

最后在论文目录编译：

```powershell
cd ../2026-EgoAnchor
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
```

如果工作树有未提交分析代码，不应把当前 `HEAD` 冒充为完整代码版本；应改用明确的审计标签，并在复现记录中说明 dirty 状态。Task 13 的验证使用 `task13-e2e` 作为这样的审计标签。

默认输出如下：

- XLSX：`data/analysis/complete/`
- CSV 与审阅 XLSX：`data/analysis/results/`；Stage 3 只消费其中的 CSV
- PDF/PNG：`../2026-EgoAnchor/figures/generated/`
- TeX 中间产物：`../2026-EgoAnchor/generated/`
- 主稿：`../2026-EgoAnchor/egoanchor_cn_v6.tex`

`publish` 可用 `--out` 和 `--tex-out` 覆盖两个发布目录。`materialize-paper` 可用 `--tex-root` 和 `--manuscript` 覆盖测试路径，但实验数据仍只能来自 TeX。

## 退出码

- `0`：命令完整成功。
- `1`：文件系统错误，或发布所需的上一阶段产物缺失。
- `2`：schema、QC 或分析契约失败。

退出码 2 表示数据不能进入下一阶段。不要绕过失败检查，也不要从后续阶段回读更早的数据源补数据；应修正当前阶段的输入，重新执行该阶段。

## 可复现性检查

在 `EgoAnchor_Python` 目录、相同代码、参数、输入和输出路径下连续运行两次，比较以下内容：

- 五个 XLSX 的二进制 SHA-256；工作簿已经固定 ZIP 条目顺序、时间戳和 core properties。
- `common/`、`exp1/`、`exp2/`、`plots/`、`paper/` 下全部 CSV 的 SHA-256。
- `figures/generated/figure_manifest.json` 中的输入 CSV 和图文件 SHA-256。
- `generated/exp1_numbers.tex`、`exp1_tables.tex`、`exp2_numbers.tex`、`exp2_tables.tex`。
- 主稿三个自动生成区块。

`audit/analysis_run.csv` 的 `created_at_utc` 记录真实执行时间，重复运行时预期变化，不属于科学结果哈希门禁。论文编译 PDF 也可能含工具链构建元数据，验收重点是源 TeX、受控区块、正式图 hash 和编译成功。

PowerShell 可用以下命令查看目录内文件哈希（命令在 `EgoAnchor_Python` 目录执行）：

```powershell
Get-ChildItem data/analysis/complete -File -Recurse |
    Sort-Object FullName |
    ForEach-Object { "{0} {1}" -f $_.FullName, (Get-FileHash $_.FullName -Algorithm SHA256).Hash }
```

## 添加新指标

1. 先在 `src/egoanchor/eval/tests/` 增加公式、边界、聚合顺序、缺失值和场景适用性测试。
2. 在 `contracts/metrics.py` 登记指标键、单位、方向、公式、适用场景、聚合语义和纯字母 TeX 后缀。
3. 新阈值或算法选择写入 `config/analysis_params.toml`，每个参数同行写中文注释；语义变化时同步递增 `contracts/versions.py` 的契约版本。
4. 在 `analysis/metrics.py` 实现可复用纯计算，在 `analysis/exp1.py` 或 `analysis/exp2.py` 完成 event 到 trial/session 的投影。统计推断不得使用 frame 作为样本。
5. 若 CSV 列结构变化，同步修改 `contracts/workbook.py`、CSV 回读测试和 breaking changelog。只增加新的指标行通常不需要改表头。
6. 若指标进入图表或论文，再更新 `analysis/plot_rows.py`、`analysis/paper.py` 及对应测试。
7. 对包外调用只从 `egoanchor.eval` 导入公开符号，并在 `egoanchor/eval/__init__.py` 显式 re-export；不要增加懒导出或深层导入。

## 添加新图表

1. 先增加 plot-row 选择测试和发布测试，冻结场景、指标、主键、行数、单位和图尺寸。
2. 在 Stage 2 的 `analysis/plot_rows.py` 生成 plot-ready 行，并在 `cli.py` 的 `plot_catalog` 增加固定声明。绘图层不得重新计算科学指标。
3. 在 `publishing/figures_exp1.py` 或 `figures_exp2.py` 增加绘制函数，复用 `publishing/style.py` 的颜色、标签、字号和原子保存工具。
4. 在 `publishing/__init__.py` 更新固定图集合，并验证 PDF、PNG、输入 CSV hash 和图文件 hash 都进入 manifest。
5. 在主稿中只引用 `figures/generated/` 下的正式 PDF，并按最终插入尺寸检查最小 7 pt 字号、图例遮挡和双栏可读性。

## 故障排查

### `preprocess` 返回 2

先单独运行 `qc`，根据 JSON 中的 `errors`、`source_file` 和 `source_line` 定位 raw 数据。未进入 Unity 的 Python candidate 只会以 latest-only 警告出现；未知 candidate 外键、writer 丢行、矩阵不完整、非法生命周期或 reference 缺失是硬错误。

### `analyze` 返回 2

确认输入是五个完整 XLSX，session 不重复，formal run kind、对象、协议、配置 hash、参数集和八 runtime 定义一致。不要把 raw task 目录传给 `analyze`。实验一/二共用五场景批次，缺少任一冻结关键指标都禁止发布。

### `publish` 返回 1 或 2

确认 `data/analysis/results/plots/plot_catalog.csv`、其中声明的 plot CSV 和 `paper/` 两个 CSV 都存在，且 catalog 中的行数与 SHA-256 没有被手改。输出目录不得位于 CSV 输入目录内，也不得让图目录和 TeX 目录互相嵌套。

### `materialize-paper` 返回 1 或 2

确认 `generated/` 下四个固定 TeX 都来自当前 Stage 3，并保留 CSV hash、生成器和实验归属头。该命令不接受 `data/analysis/results` 位置参数。主稿必须保留三个完整的 `EGOANCHOR-...:BEGIN/END` 受控边界。

### LaTeX 编译失败

先查看 `pdf/egoanchor_cn_v6.log` 中的首个错误，确认字体、模板、图片和受控区块语法，再确认两张正式 PDF 位于 `2026-EgoAnchor/figures/generated/`。从 `2026-EgoAnchor` 目录运行 XeLaTeX；四个生成 TeX 只是审计中间产物，移走后主稿仍应编译。若扫描发现主稿重新引入 `generated/exp*.tex`，才说明出现了外部数字依赖。
