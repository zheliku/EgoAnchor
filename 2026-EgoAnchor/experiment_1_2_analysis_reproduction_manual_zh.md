# 实验一/二离线分析复现手册

这份手册用于在采集新数据后，从五个 schema-v2 task 目录重新生成实验一和实验二的全部离线产物。默认工作目录是 `EgoAnchor_Python`，原始 task 目录只读，不能在里面手工修改 JSON/JSONL。

## 复现边界

分析链路固定为：

```text
五个 raw task 目录
  -> qc / preprocess -> 每个 task 一个完整 XLSX
  -> analyze -> CSV + exp1_analysis.xlsx + exp2_analysis.xlsx
  -> publish -> 两张 PDF/PNG 图 + 四个 TeX 中间文件
  -> materialize-paper -> egoanchor_cn_v6.tex 的受控区块
```

阶段之间是单向契约：

- `qc` 和 `preprocess` 可以读取 raw JSON/JSONL。
- `analyze` 只读取 `task_N_complete.xlsx`，不会打开 raw JSON/JSONL。
- `publish` 只读取 Stage 2 的 CSV，不读取 XLSX。
- `materialize-paper` 只读取四个 Stage 3 TeX，不读取 CSV、XLSX 或 JSON/JSONL。

统计单位是 event/segment。渲染帧只用于形成轨迹，不能当作独立样本；不同场景也不能混池成一个总分。

## 前置检查

在 PowerShell 中执行：

```powershell
Set-Location P:\VSCode-Project\EgoAnchor\EgoAnchor_Python
pixi run python -m egoanchor.eval.cli --help
```

需要看到且只使用这五个命令：`qc`、`preprocess`、`analyze`、`publish`、`materialize-paper`。分析参数唯一来源是 `src/egoanchor/eval/config/analysis_params.toml`；正式结果不要临时修改参数。

每个 raw task 目录应位于 `data/eval/` 下，目录名符合 `task_1_...` 到 `task_5_...`。目录内必须保留以下固定文件：

```text
manifest.json
python_session.json
python_candidates.jsonl
python_events.jsonl
unity_events.jsonl
events.jsonl
unity_reference.jsonl
unity_admission.jsonl
unity_render.jsonl
```

`manifest.session_id`、日志中的主键和跨端 session 配对信息必须来自同一次正式采集。不要把不同 session 的文件拼到同一目录，也不要为了通过检查而补写行数或时间戳。

## 替换新数据

1. 停止 Python、Unity 和 Mutagen 的写入，确认五个 session 已正常停止。
2. 备份当前 `data/eval/task_*` 目录。
3. 用新的五个 task 目录替换 `EgoAnchor_Python/data/eval/` 下对应目录。目录编号必须仍然覆盖 1--5；实际场景、对象、配置哈希和协议由 QC 检查。
4. 不要修改 task 目录内部固定文件名，不要重写 `session_id`、`candidate_id`、`frame_id` 或事件来源行号。
5. 清理本地上一次的派生输出，再从 `qc` 开始执行完整链路。不要只替换一个场景后沿用其他场景的旧 XLSX/CSV。

下面的命令会动态收集五个 task 目录，不依赖当天的 session 时间戳：

```powershell
$evalRoot = (Resolve-Path "data/eval").Path
$taskDirs = @(
    Get-ChildItem -LiteralPath $evalRoot -Directory |
        Where-Object { $_.Name -match '^task_[1-5]_' } |
        Sort-Object { [int]([regex]::Match($_.Name, '^task_(\d+)_').Groups[1].Value) } |
        ForEach-Object { $_.FullName }
)
if ($taskDirs.Count -ne 5) {
    throw "需要恰好五个 task_1 到 task_5 目录，当前找到 $($taskDirs.Count) 个。"
}
$taskDirs | ForEach-Object { "RAW $_" }
```

## 清理派生输出

只删除 `data/analysis/` 下可重建的目录，不要删除 raw task：

```powershell
$analysisRoot = (Resolve-Path "data/analysis").Path
$targets = @(
    (Join-Path $analysisRoot "complete"),
    (Join-Path $analysisRoot "results")
)
foreach ($target in $targets) {
    if (Test-Path -LiteralPath $target) {
        $resolved = (Resolve-Path -LiteralPath $target).Path
        if (-not $resolved.StartsWith($analysisRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "拒绝删除分析目录之外的路径：$resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
New-Item -ItemType Directory -Force -Path (Join-Path $analysisRoot "complete") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $analysisRoot "results") | Out-Null
```

如果需要保留旧结果，先复制整个 `data/analysis/`，不要把旧结果目录直接混入新批次。

## 一键执行四阶段

先记录代码版本。工作树有未提交改动时，使用明确的审计标签，不要把 `HEAD` 误写成完整源码版本：

```powershell
$codeVersion = (git rev-parse --short HEAD).Trim()
if (git status --porcelain) {
    $codeVersion = "manual-dirty-$codeVersion"
    Write-Warning "当前工作树有未提交改动，分析 provenance 将使用 $codeVersion"
}
$completeDir = (Resolve-Path "data/analysis/complete").Path
$resultDir = (Resolve-Path "data/analysis/results").Path
$workbooks = @(1..5 | ForEach-Object {
    Join-Path $completeDir ("task_{0}_complete.xlsx" -f $_)
})
```

### 1. QC raw task

```powershell
pixi run python -m egoanchor.eval.cli qc @taskDirs
if ($LASTEXITCODE -ne 0) { throw "QC 失败，停止后续阶段。退出码：$LASTEXITCODE" }
```

QC 失败时不要运行 `preprocess`。退出码 `2` 表示 schema/QC 错误，退出码 `1` 表示文件系统或输入路径错误。

### 2. 发布完整原始 XLSX

```powershell
pixi run python -m egoanchor.eval.cli preprocess @taskDirs `
    --out $completeDir `
    --code-version $codeVersion
if ($LASTEXITCODE -ne 0) { throw "preprocess 失败，停止后续阶段。退出码：$LASTEXITCODE" }
```

每个 task 必须得到一个确定性文件：

```text
data/analysis/complete/task_1_complete.xlsx
data/analysis/complete/task_2_complete.xlsx
data/analysis/complete/task_3_complete.xlsx
data/analysis/complete/task_4_complete.xlsx
data/analysis/complete/task_5_complete.xlsx
```

快速检查文件数量和 hash：

```powershell
Get-ChildItem -LiteralPath $completeDir -Filter "task_*_complete.xlsx" -File |
    Sort-Object Name |
    Select-Object Name, Length,
        @{Name="SHA256"; Expression={(Get-FileHash $_.FullName -Algorithm SHA256).Hash}}
```

这些 XLSX 是 raw 数据的完整、带 QC 的审阅副本，包含来源文件、来源行号、行 hash、数据字典和 QC 结果。不要手工打开后保存，否则可能改变确定性 ZIP 内容；需要阅读时使用只读方式。

### 3. 只从 XLSX 生成分析 CSV 和审阅 XLSX

```powershell
pixi run python -m egoanchor.eval.cli analyze @workbooks `
    --out $resultDir `
    --code-version $codeVersion
if ($LASTEXITCODE -ne 0) { throw "analyze 失败，停止后续阶段。退出码：$LASTEXITCODE" }
```

Stage 2 的主要输出是：

```text
data/analysis/results/
  common/       共享窗口、候选和帧级审计 CSV
  exp1/         实验一 event/trial/session CSV
  exp2/         实验二配对、VCD 和 session CSV
  plots/        绘图专用 CSV 与 plot_catalog.csv
  paper/        numbers.csv、tables.csv
  audit/        QC、指标目录、参数和 lineage
  exp1_analysis.xlsx
  exp2_analysis.xlsx
```

`exp1_analysis.xlsx` 和 `exp2_analysis.xlsx` 只用于人工审阅和复核；Stage 3 不读取它们。`audit/lineage.csv` 记录每个输出 CSV 对应的输入 workbook SHA-256。

### 4. 只从 CSV 发布图和 TeX

```powershell
pixi run python -m egoanchor.eval.cli publish $resultDir `
    --paper-root ..\2026-EgoAnchor
if ($LASTEXITCODE -ne 0) { throw "publish 失败，停止后续阶段。退出码：$LASTEXITCODE" }
```

默认会原子发布：

```text
2026-EgoAnchor/figures/generated/exp1_behavior_overview.pdf
2026-EgoAnchor/figures/generated/exp1_behavior_overview.png
2026-EgoAnchor/figures/generated/exp2_mechanism_attribution.pdf
2026-EgoAnchor/figures/generated/exp2_mechanism_attribution.png
2026-EgoAnchor/figures/generated/figure_manifest.json
2026-EgoAnchor/generated/exp1_numbers.tex
2026-EgoAnchor/generated/exp1_tables.tex
2026-EgoAnchor/generated/exp2_numbers.tex
2026-EgoAnchor/generated/exp2_tables.tex
```

`plots/exp2_vcd_curve.csv` 是实验二 VCD risk--coverage 与实际接纳工作点的 Stage 2 审计输入；当前主图只展示四个组件的 `Ablated - Full` 差值，不再对应一张独立的 VCD PDF。

### 5. 只从 TeX 物化主稿并编译

```powershell
pixi run python -m egoanchor.eval.cli materialize-paper `
    --paper-root ..\2026-EgoAnchor
if ($LASTEXITCODE -ne 0) { throw "materialize-paper 失败，退出码：$LASTEXITCODE" }

Set-Location ..\2026-EgoAnchor
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
if ($LASTEXITCODE -ne 0) { throw "XeLaTeX 编译失败，检查 pdf/egoanchor_cn_v6.log" }
```

主稿中的实验数字和表格来自三个稳定受控区块；四个生成 TeX 只是审计中间产物。图仍从 `figures/generated/` 加载。

## 复现验收

至少检查：

```powershell
Get-ChildItem -LiteralPath "..\2026-EgoAnchor\figures\generated" -File |
    Sort-Object Name |
    Select-Object Name, Length,
        @{Name="SHA256"; Expression={(Get-FileHash $_.FullName -Algorithm SHA256).Hash}}

Get-ChildItem -LiteralPath $resultDir -File -Recurse |
    Where-Object { $_.FullName -notlike "*\audit\analysis_run.csv" } |
    Sort-Object FullName |
    ForEach-Object {
        "{0} {1}" -f $_.FullName, (Get-FileHash $_.FullName -Algorithm SHA256).Hash
    }
```

要验证确定性，在相同源码、参数、五个 raw task 和输出路径下再执行一次 `preprocess` 与 `analyze`。比较：

- 五个 `task_N_complete.xlsx` 的 SHA-256；
- `common/`、`exp1/`、`exp2/`、`plots/`、`paper/` 中全部 CSV 的 SHA-256；
- 两个审阅 XLSX 的 SHA-256；
- `figure_manifest.json` 中的输入 CSV 和 PDF/PNG hash；
- 四个生成 TeX 和主稿三个受控区块。

`audit/analysis_run.csv` 的 `created_at_utc` 每次会变化，不纳入科学结果 hash。若两次结果不同，先检查源码版本、`analysis_params.toml` 原始字节、输入 workbook hash 和输出目录是否混入旧文件。

## 常见失败处理

| 现象                             | 处理                                                                                                    |
| -------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `qc` 返回 2                    | 查看输出中的`source_file`、`source_line` 和错误说明；修复采集日志，不要绕过 QC。                    |
| `preprocess` 没有生成完整 XLSX | 确认五个目录和固定文件集合完整；任一 task 失败时整批不会发布。                                          |
| `analyze` 返回 2               | 确认传入的是五个完整 XLSX，不能传 raw 目录；检查 session、配置 hash、runtime 矩阵和关键事件是否一致。   |
| `publish` 返回 1               | 检查`data/analysis/results/` 是否完整，尤其是 `plots/plot_catalog.csv`、plot CSV 和两个 paper CSV。 |
| `materialize-paper` 返回 2     | 确认四个 TeX 都来自当前 Stage 3，且主稿三个受控区块边界未被手工改写。                                   |
| PDF 页数或图片不对               | 先看`pdf/egoanchor_cn_v6.log` 的首个错误，再确认图位于 `figures/generated/`。                       |

任何阶段失败都应停在当前阶段。不要让 Stage 2 回读 raw、让 Stage 3 回读 XLSX，或从旧结果目录补一张缺失图；修复当前输入后重新执行该阶段。
