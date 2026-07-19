# 实验一/二离线分析复现手册

本手册从五个 schema-v2 task 目录重建 GPT corrected-newdata-v4 论文结果。原始 task 目录只读；Stage 1 完整 XLSX 是固定、不可变的分析桥梁。

## 固定链路

```text
raw task 目录
  -> qc（必要时物化 events.jsonl）
  -> preprocess（五本完整 XLSX）
  -> build-paper（GPT v4 图、表、主稿）
  -> XeLaTeX
```

`qc` 与 `preprocess` 可读取 raw JSON/JSONL。`build-paper` 只读取 `task_N_complete.xlsx`，不会回读 raw，也不会改写 XLSX。渲染帧只用于形成动作片段轨迹；论文统计单位是片段或遮挡 episode。

## 前置检查

```powershell
Set-Location P:\VSCode-Project\EgoAnchor\EgoAnchor_Python
pixi run python -m egoanchor.eval.cli --help
```

当前只应看到三个命令：`qc`、`preprocess`、`build-paper`。GPT v4 参数唯一来源是 `src/egoanchor/eval/config/gpt_v4.toml`。

每个 raw task 目录必须包含：

```text
manifest.json
python_session.json
python_candidates.jsonl
python_events.jsonl
unity_events.jsonl
unity_reference.jsonl
unity_admission.jsonl
unity_render.jsonl
```

`events.jsonl` 是本机派生文件，不要求采集端预先写出。缺失时 `qc` 会检查两端 fragment、停止态和 writer 统计，然后原子生成；已有文件只验证，不覆盖。

## 替换新数据

1. 停止 Python、Unity 和 Mutagen 的写入，确认五个 session 正常停止。
2. 备份当前 `data/eval/`，再用新 task 目录替换对应的 `task_1_...` 到 `task_5_...`。
3. 不要修改 `session_id`、`candidate_id`、`frame_id`、固定文件名或事件来源行号。
4. 不要只替换单个场景后沿用旧 XLSX；五个 task 必须作为一个批次完整重建。

可用下面的代码动态收集五个目录：

```powershell
$evalRoot = (Resolve-Path "data/eval").Path
$taskDirs = @(Get-ChildItem -LiteralPath $evalRoot -Directory |
    Where-Object { $_.Name -match '^task_[1-5]_' } |
    Sort-Object { [int]([regex]::Match($_.Name, '^task_(\d+)_').Groups[1].Value) } |
    ForEach-Object { $_.FullName })
if ($taskDirs.Count -ne 5) { throw "需要恰好五个 task_1 到 task_5 目录。" }
```

## 运行 Stage 1

```powershell
$codeVersion = (git rev-parse --short HEAD).Trim()
pixi run python -m egoanchor.eval.cli qc @taskDirs
if ($LASTEXITCODE -ne 0) { throw "QC 失败，停止后续步骤。" }

pixi run python -m egoanchor.eval.cli preprocess @taskDirs `
    --out data/analysis/complete `
    --code-version $codeVersion
if ($LASTEXITCODE -ne 0) { throw "preprocess 失败，停止后续步骤。" }
```

必须得到：

```text
data/analysis/complete/task_1_complete.xlsx
data/analysis/complete/task_2_complete.xlsx
data/analysis/complete/task_3_complete.xlsx
data/analysis/complete/task_4_complete.xlsx
data/analysis/complete/task_5_complete.xlsx
```

这些文件是后续唯一输入。只读审阅可以使用 `load_workbook(..., read_only=True)`；不要在 Excel 中保存。

## 运行 GPT v4 重建

```powershell
$completeDir = (Resolve-Path "data/analysis/complete").Path
$workbooks = @(1..5 | ForEach-Object {
    Join-Path $completeDir ("task_{0}_complete.xlsx" -f $_)
})

pixi run python -m egoanchor.eval.cli build-paper @workbooks `
    --out data/analysis/gpt_v4 `
    --paper-root ..\2026-EgoAnchor
if ($LASTEXITCODE -ne 0) { throw "GPT v4 重建失败，停止编译。" }
```

该命令只读 XLSX，计算 GPT v4 的三联实验一和组件归因实验二，并写出：

```text
2026-EgoAnchor/figures/generated/experiment1_corrected_newdata.pdf
2026-EgoAnchor/figures/generated/experiment2_corrected_newdata.pdf
2026-EgoAnchor/tables/experiment1_corrected_newdata_v4.tex
2026-EgoAnchor/tables/experiment2_corrected_newdata_v4.tex
2026-EgoAnchor/egoanchor_cn_v6.tex
```

同时在 `data/analysis/gpt_v4/` 保存输入 hash、表格 CSV 和性能审计。GPT 参考包不作为正式数字输入。

## 编译与视觉验收

```powershell
Set-Location ..\2026-EgoAnchor
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
if ($LASTEXITCODE -ne 0) { throw "XeLaTeX 编译失败。" }
```

检查 PDF 页数、实验页面和图表：

- 表格中的 RMSE、P95 和毫秒数应为短格式，不出现十几位小数；
- 图 3 为三面板：头动泄漏、动态平移 lag/RMSE、遮挡 P95；
- 图 4 左侧为 capture-time、StaticLock、VCD，右侧为 temporal synthesis lag/RMSE；
- VCD 只统计 `occlusion_started` episode，40 mm 阈值和 `0/9 vs 4/9` 必须与表格一致；
- 主稿不应出现旧的 `exp1_final_v2`、`exp2_merged_final_v2` 或旧 CLI 名称。

用 `pdftoppm` 渲染第 6--8 页检查裁切、重叠和字号；临时 PNG 放在 `2026-EgoAnchor/tmp/pdfs/`，验收后删除。

## 失败处理

- `qc` 返回 `1`：检查 task 目录或固定文件是否缺失。
- `qc` 或 `preprocess` 返回 `2`：修复 schema、生命周期、writer 统计或矩阵问题，不要手工补行。
- `build-paper` 返回 `1`：检查五本 XLSX 是否可读以及输出目录权限。
- `build-paper` 返回 `2`：检查 XLSX 命名、五个 task 是否齐全、事件角色和组件配对是否完整。
- XeLaTeX 失败：先查看 `pdf/egoanchor_cn_v6.log` 的首个错误，并确认两张正式 PDF 位于 `figures/generated/`。

任何阶段失败都应停在当前阶段。不要从 GPT 包复制数字、不要把 raw 目录传给 `build-paper`，也不要从旧结果目录补数据。
