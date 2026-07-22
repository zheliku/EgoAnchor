# 实验一/二数据归档与手动分析手册

本手册覆盖新数据从 `data/eval/` 进入正式归档，直到生成工作簿、论文图表和最终 PDF 的
完整流程。目录约定见 `EgoAnchor_Python/docs/data_layout.md`，CLI 契约见
`EgoAnchor_Python/docs/analysis_pipeline.md`。

## 1. 先分清四层数据

~~~text
data/eval/<session_id>/
  -> qc
data/experiments/experiment_1_2/raw/task_N_<scenario>/
  -> preprocess
data/experiments/experiment_1_2/workbooks/task_N_complete.xlsx
  -> build-paper
data/experiments/experiment_1_2/analysis/plots/figure_plot_data.xlsx
2026-EgoAnchor/figures/panels/*.png + *.pdf
2026-EgoAnchor/tables/*.tex
2026-EgoAnchor/egoanchor_cn_v6.tex
  -> latexmk
2026-EgoAnchor/pdf/egoanchor_cn_v6.pdf
~~~

三个 Python 命令的职责不同：

| 命令 | 输入 | 主要输出 |
|---|---|---|
| `qc` | 一个或多个扁平 task/session 目录中的 JSON、JSONL | QC JSON；缺少时安全生成 `events.jsonl` |
| `preprocess` | 五个 `task_N_*` raw 目录 | `task_1_complete.xlsx` 到 `task_5_complete.xlsx` |
| `build-paper` | 五本 Stage 1 工作簿 | 指标、绘图工作簿、PNG/PDF 面板、TeX 表和中文主稿 |

`preprocess` 生成的不是另一套“raw XLSX”，而是完整的 Stage 1 工作簿。它们是后续分析的
唯一输入。

## 2. 当前采集批次的硬约束

当前 CLI 不会拆分一个包含多个任务的 session，也不会把多个 session 自动合并成一个 task。
新采集必须使用下面的稳定做法：

1. 任务 1--5 各录一个独立 session，共五个 session。
2. 每个被选中的 session 只有一个最终完成、未作废的任务。
3. 五个 session 使用同一个 `config_hash`、`frozen_parameter_set_id`、对象、协议和
   `variant_matrix_id=exp12_9_linear_v2`。
4. 不得把同一个多任务 session 复制五份。这样会重复数据和 `session_id`，不能作为正式输入。

当前正式数据就是“一项任务一个 session”。Unity 可以在同一 session 中切换任务，但在离线
拆分/合并功能实现前，不要用这个能力采正式批次。

## 3. 从 `data/eval` 整理下一批数据

### 3.1 等待两端停止和同步完成

先停止 Unity session 和远端 Python 服务，确认 `python_session.json` 已写入停止态统计。然后在
`EgoAnchor_Python` 目录检查 Mutagen：

~~~powershell
Set-Location P:\VSCode-Project\EgoAnchor\EgoAnchor_Python

mutagen sync flush logs-5090
mutagen sync list logs-5090
~~~

只有 `logs-5090` 没有 conflict、两侧文件数量稳定后才能继续。准备移动目录前终止同步项目：

~~~powershell
mutagen project terminate
~~~

同步和两端 writer 停止前，不得移动或重命名 `data/eval/<session_id>`。

### 3.2 先在暂存区逐 session 做 QC

把下面五个占位符替换为实际目录名：

~~~powershell
$evalRoot = (Resolve-Path "data/eval").Path
$sessionByTask = [ordered]@{
    "task_1_static_head_motion"     = "<task-1-session-id>"
    "task_2_start_stop_6dof"        = "<task-2-session-id>"
    "task_3_continuous_translation" = "<task-3-session-id>"
    "task_4_continuous_rotation"    = "<task-4-session-id>"
    "task_5_occlusion_recovery"     = "<task-5-session-id>"
}

foreach ($entry in $sessionByTask.GetEnumerator()) {
    $sessionPath = Join-Path $evalRoot $entry.Value
    pixi run python -m egoanchor.eval.cli qc $sessionPath
    if ($LASTEXITCODE -ne 0) {
        throw "QC 失败：$($entry.Key) <- $($entry.Value)"
    }
}
~~~

`qc` 可能在 session 根目录生成 `events.jsonl`。它由 `python_events.jsonl` 和
`unity_events.jsonl` 确定性物化，不是人工补写文件。返回码为 `0` 且输出包含
`"passed": true` 才能继续。

再检查任务映射。外层 session 目录名和 manifest 的 `session_id` 必须一致，每个 session 只完成
映射到的一个任务：

~~~powershell
$manifests = foreach ($entry in $sessionByTask.GetEnumerator()) {
    $manifestPath = Join-Path (Join-Path $evalRoot $entry.Value) "manifest.json"
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    $taskNumber = [int]([regex]::Match($entry.Key, '^task_(\d+)_').Groups[1].Value)
    $completed = @($manifest.completed_tasks | ForEach-Object { [int]$_.task_number })

    if ($manifest.session_id -ne $entry.Value) {
        throw "目录名与 manifest.session_id 不一致：$($entry.Value)"
    }
    if ($completed.Count -ne 1 -or $completed[0] -ne $taskNumber) {
        throw "$($entry.Value) 的 completed_tasks 与 $($entry.Key) 不一致。"
    }

    [pscustomobject]@{
        Task = $entry.Key
        SessionId = $manifest.session_id
        ConfigHash = $manifest.config_hash
        FrozenSet = $manifest.frozen_parameter_set_id
        ObjectId = $manifest.object_id
        ObjectModel = $manifest.object_model_id
        Protocol = $manifest.protocol_version
        RunKind = $manifest.run_kind
        Matrix = $manifest.variant_matrix_id
    }
}

$manifests | Format-Table -AutoSize
if (($manifests.SessionId | Sort-Object -Unique).Count -ne 5) {
    throw "五个 task 必须来自五个不同 session。"
}
if (($manifests.ConfigHash | Sort-Object -Unique).Count -ne 1) {
    throw "五个 session 的 config_hash 不一致。"
}
foreach ($field in @("FrozenSet", "ObjectId", "ObjectModel", "Protocol", "RunKind")) {
    if (($manifests.$field | Sort-Object -Unique).Count -ne 1) {
        throw "五个 session 的 $field 不一致。"
    }
}
if (($manifests.Matrix | Sort-Object -Unique) -ne "exp12_9_linear_v2") {
    throw "variant_matrix_id 不正确。"
}
~~~

### 3.3 批次命名和复制

正式活动目录不使用 `v3`、`v4` 之类的名字。批次身份来自 manifest、session ID、工作簿
SHA-256 和 provenance。为方便人工管理，暂存和旧批次冷归档使用
`batch_YYYYMMDD_<config-hash前16位>`，例如：

~~~text
batch_20260722_a575a3813af3b6a1
~~~

先复制，不要直接从 `data/eval` 移走。这样即使后续批次 QC 失败，原始同步结果仍然在：

~~~powershell
$configHash = [string]$manifests[0].ConfigHash
$configToken = $configHash.Substring(0, [Math]::Min(16, $configHash.Length))
$batchId = "batch_{0}_{1}" -f (Get-Date -Format "yyyyMMdd"), $configToken
$stagingRoot = Join-Path "data/experiments/_staging/experiment_1_2" $batchId
$stagingRaw = Join-Path $stagingRoot "raw"
if (Test-Path -LiteralPath $stagingRoot) {
    throw "批次暂存目录已存在，拒绝合并：$stagingRoot"
}
New-Item -ItemType Directory -Path $stagingRaw -Force | Out-Null

foreach ($entry in $sessionByTask.GetEnumerator()) {
    $source = Join-Path $evalRoot $entry.Value
    $destination = Join-Path $stagingRaw $entry.Key
    if (Test-Path -LiteralPath $destination) {
        throw "目标已存在，拒绝合并或覆盖：$destination"
    }
    Copy-Item -LiteralPath $source -Destination $destination -Recurse
}
~~~

复制后的 `task_N_*` 必须是扁平数据根。`manifest.json` 和各 JSONL 直接位于 task 目录中，
不能再多套一层 `<session_id>/`。只能修改外层副本目录名；内部固定文件名、
`manifest.session_id` 和 JSONL 内容保持不变。

## 4. 从 JSONL 生成五本 Stage 1 工作簿

先对复制后的五项任务做整批 QC，再生成工作簿：

~~~powershell
$rawRoot = (Resolve-Path $stagingRaw).Path
$taskDirs = @(
    "task_1_static_head_motion"
    "task_2_start_stop_6dof"
    "task_3_continuous_translation"
    "task_4_continuous_rotation"
    "task_5_occlusion_recovery"
) | ForEach-Object { Join-Path $rawRoot $_ }

pixi run python -m egoanchor.eval.cli qc @taskDirs
if ($LASTEXITCODE -ne 0) { throw "批次 QC 失败，停止发布工作簿。" }

$codeVersion = (git rev-parse --short HEAD).Trim()
$stagingWorkbooks = Join-Path $stagingRoot "workbooks"
pixi run python -m egoanchor.eval.cli preprocess @taskDirs --out $stagingWorkbooks --code-version $codeVersion
if ($LASTEXITCODE -ne 0) { throw "preprocess 失败，停止分析。" }

Get-ChildItem -LiteralPath $stagingWorkbooks -Filter "task_*_complete.xlsx" |
    Sort-Object Name |
    Get-FileHash -Algorithm SHA256 |
    Format-Table Path, Hash -AutoSize
~~~

必须恰好得到：

~~~text
task_1_complete.xlsx
task_2_complete.xlsx
task_3_complete.xlsx
task_4_complete.xlsx
task_5_complete.xlsx
~~~

工作簿可以只读查看，但不要在 Excel 中保存后再把它用于正式分析。Excel 保存会改变文件内容
和 SHA-256。

## 5. 将新批次设为当前正式批次

`data/experiments/experiment_1_2/` 始终表示当前论文使用的唯一活动批次。确认新批次整批 QC 和
`preprocess` 都成功后，再一次性切换；不要逐 task 覆盖，也不要混用新旧批次。

先给当前活动批次设置一个旧批次 ID，然后把它整体移入冷归档，再把新暂存批次移到活动路径：

~~~powershell
$experimentsRoot = (Resolve-Path "data/experiments").Path
$activeRoot = Join-Path $experimentsRoot "experiment_1_2"
$archiveParent = Join-Path $experimentsRoot "_archive/experiment_1_2"
$oldManifestPath = Join-Path $activeRoot "raw/task_1_static_head_motion/manifest.json"
$oldManifest = Get-Content -Raw -LiteralPath $oldManifestPath | ConvertFrom-Json
$oldConfigHash = [string]$oldManifest.config_hash
$oldConfigToken = $oldConfigHash.Substring(0, [Math]::Min(16, $oldConfigHash.Length))
$oldBatchId = "batch_{0}_{1}" -f $oldManifest.session_id.Substring(0, 8), $oldConfigToken
$oldArchive = Join-Path $archiveParent $oldBatchId

New-Item -ItemType Directory -Path $archiveParent -Force | Out-Null
if (Test-Path -LiteralPath $oldArchive) {
    throw "旧批次归档目标已存在：$oldArchive"
}
if (-not (Test-Path -LiteralPath $activeRoot -PathType Container)) {
    throw "当前活动批次不存在：$activeRoot"
}
if (-not (Test-Path -LiteralPath $stagingRoot -PathType Container)) {
    throw "新暂存批次不存在：$stagingRoot"
}

Move-Item -LiteralPath $activeRoot -Destination $oldArchive
Move-Item -LiteralPath $stagingRoot -Destination $activeRoot
~~~

这一步只在 Mutagen 已停止、Excel 没有打开工作簿时执行。切换后，活动目录包含新批次的
`raw/` 和 `workbooks/`；`analysis/` 会在下一步重新生成。确认新批次全部产物和最终 PDF 正常后，
才清理 `data/eval` 中对应的五个 session。冷归档批次默认只读，不参与当前论文分析。

需要继续采集时，回到 `EgoAnchor_Python` 目录重新执行 `mutagen project start`。

如果你只是重建当前批次，不需要执行第 3 节和第 5 节，直接从当前 `raw/` 或 `workbooks/`
开始即可。

## 6. 从五本工作簿生成指标、绘图数据和图片

在活动目录上运行：

~~~powershell
Set-Location P:\VSCode-Project\EgoAnchor\EgoAnchor_Python

$workbookRoot = (Resolve-Path "data/experiments/experiment_1_2/workbooks").Path
$workbooks = 1..5 | ForEach-Object {
    Join-Path $workbookRoot ("task_{0}_complete.xlsx" -f $_)
}

pixi run python -m egoanchor.eval.cli build-paper @workbooks `
    --out data/experiments/experiment_1_2/analysis `
    --paper-root ..\2026-EgoAnchor
if ($LASTEXITCODE -ne 0) { throw "build-paper 失败，停止编译。" }
~~~

这条命令一次生成以下内容：

~~~text
EgoAnchor_Python/data/experiments/experiment_1_2/analysis/
├─ metrics/                         # 完整精度 CSV/JSON
├─ plots/
│  └─ figure_plot_data.xlsx         # 图 2、图 3 的可见逐点数据
└─ provenance/                      # 输入 hash、参数 hash 和构建结果

2026-EgoAnchor/figures/panels/
├─ figure2a_head_motion.png/.pdf
├─ figure2b_translation.png/.pdf
├─ figure2c_occlusion.png/.pdf
├─ figure3a_capture_alignment.png/.pdf
├─ figure3b_static_lock.png/.pdf
├─ figure3c_vcd.png/.pdf
└─ figure3d_temporal_strategies.png/.pdf

2026-EgoAnchor/tables/
├─ experiment1_system_characterization.tex
└─ experiment2_design_attribution.tex

2026-EgoAnchor/egoanchor_cn_v6.tex
~~~

`build-paper` 会直接更新中文主稿中的实验一/二结果段落、两张表和论文面板，不只是写
`analysis/`。正式参数固定从 `src/egoanchor/eval/config/paper.toml` 读取，CLI 没有参数覆盖入口。

## 7. `figure_plot_data.xlsx` 如何变成 PNG/PDF

当前没有单独的“plot XLSX 转图片”命令。`build-paper` 从五本 Stage 1 工作簿计算一次
`PaperResults`，同一份结果同时写入 `figure_plot_data.xlsx` 和七组 PNG/PDF。因此：

- `figure_plot_data.xlsx` 是审计和人工查看用的导出，不是绘图输入；
- 手工修改它不会改变图片，下次运行 `build-paper` 还会覆盖它；
- 需要重画时，重新运行 `build-paper`；
- 修改图形样式应改 `egoanchor.eval.paper_analysis` 的绘图代码，不能在 Excel 中改正式数据；
- LaTeX 使用 PDF 面板，PNG 主要用于快速预览和文档检查。

工作簿中有 `README`、`Figure2` 和 `Figure3` 三个 sheet。Figure2 保存图 2 三个面板的可见点，
Figure3 保存图 3 四个面板的可见点；严格配对由 `session_id`、`trial_id` 和 `segment_id` 等
稳定键标识。

## 8. 编译最终论文 PDF

~~~powershell
Set-Location P:\VSCode-Project\EgoAnchor\2026-EgoAnchor

latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
if ($LASTEXITCODE -ne 0) { throw "XeLaTeX 编译失败。" }
~~~

最终文件是 `2026-EgoAnchor/pdf/egoanchor_cn_v6.pdf`。建议检查：

1. 图 2 是一行三个子图，图 2(b) 没有跨方法折线。
2. 图 3 是一行四个子图，图 3(d) 有 Predict-to-Now、Hermite 和 Linear/SLERP。
3. 图内文字没有裁切或重叠，最终字号不小于约 7 pt。
4. `analysis_manifest.json` 中的五个工作簿 hash 与当前文件一致。
5. 表格和正文数字来自当前批次，没有从冷归档或历史结果包拼接。

## 9. 是否需要手动导入 Python

不需要。只要从 `EgoAnchor_Python` 目录运行 `pixi run python -m egoanchor.eval.cli ...`，Pixi 会
按当前项目环境加载 `src/egoanchor`。你不需要设置 `PYTHONPATH`，也不需要在脚本中深层导入
分析模块。

CLI 的路径参数都是显式的，所以它既能读取暂存批次，也能读取当前活动批次。正式发布仍以
`data/experiments/experiment_1_2/` 为唯一活动路径。

退出码含义：`0` 表示成功，`1` 表示目录或固定输入文件缺失，`2` 表示 schema、QC 或论文输入
契约失败。任一阶段非零都应立即停止，不要手工补行、改工作簿或从其他批次复制结果。
