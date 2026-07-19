# 实验一/二离线分析

当前离线分析以 GPT corrected-newdata-v4 论文包为唯一呈现基线。Stage 1 生成的完整 XLSX 是不可变桥梁；新的 GPT v4 管线只读这五本 XLSX，不回读 raw JSONL，也不修改工作簿。

## 数据流

```text
raw schema-v2 task
  -> qc -> events.jsonl（缺失时安全物化）
  -> preprocess -> task_1..5_complete.xlsx（固定桥梁）
  -> build-paper -> GPT v4 指标、图、表和 egoanchor_cn_v6.tex
```

- `qc` 和 `preprocess` 可以读取 raw task；`events.jsonl` 是两端停止后的本机派生文件，已有总表只验证、不覆盖。
- `preprocess` 在整批 QC 通过后原子发布 `task_N_complete.xlsx`。这些文件是后续唯一输入，不能手工打开后保存。
- `build-paper` 只接受恰好五本 `task_1_complete.xlsx` 到 `task_5_complete.xlsx`，通过只读 XLSX XML reader 计算 GPT v4 指标、写出图表和主稿。
- 统计单位是动作片段或遮挡 episode；渲染帧只用于形成轨迹，不能作为独立样本。

GPT v4 的指标语义固定为：静止头动的中心化泄漏、绝对注册和帧间增量；持续平移/旋转的 fitted lag 与对齐残差；遮挡 `occlusion_started` episode 的平移 P95、40 mm 尾部失败；起停的 250 ms 基线、5 mm 位移和 100 ms 持续响应；组件归因分别使用 raw capture/arrival、中心化 StaticLock、遮挡尾部和持续平移 lag/RMSE。

## 命令

在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src

$workbooks = @(
    "data/analysis/complete/task_1_complete.xlsx"
    "data/analysis/complete/task_2_complete.xlsx"
    "data/analysis/complete/task_3_complete.xlsx"
    "data/analysis/complete/task_4_complete.xlsx"
    "data/analysis/complete/task_5_complete.xlsx"
)

pixi run python -m egoanchor.eval.cli build-paper @workbooks `
    --out data/analysis/gpt_v4 `
    --paper-root ../2026-EgoAnchor
if ($LASTEXITCODE -ne 0) { throw "GPT v4 重建失败，退出码：$LASTEXITCODE" }
```

若从新 raw task 开始，先执行：

```powershell
pixi run python -m egoanchor.eval.cli qc @taskDirs
pixi run python -m egoanchor.eval.cli preprocess @taskDirs `
    --out data/analysis/complete `
    --code-version (git rev-parse --short HEAD)
```

`qc` 或 `preprocess` 失败时不要运行 `build-paper`。退出码 `1` 表示输入或文件系统错误，退出码 `2` 表示 schema/QC/分析契约错误。

## 输出

`build-paper` 的可审计输出位于 `data/analysis/gpt_v4/`：

- `gpt_v4_manifest.json`：五本输入 XLSX 的 SHA-256 与参数文件名；
- `data/experiment1_expanded_summary_v4.csv`：四系统完整表征；
- `data/capture_alignment_candidate_metrics.csv`：同一候选的 capture/arrival 对齐比较；
- `data/runtime_performance_audit_v4.json`：视觉后端性能审计。

论文目录固定写出：

- `figures/generated/experiment1_corrected_newdata.pdf/.png`；
- `figures/generated/experiment2_corrected_newdata.pdf/.png`；
- `tables/experiment1_corrected_newdata_v4.tex`；
- `tables/experiment2_corrected_newdata_v4.tex`；
- `egoanchor_cn_v6.tex`。

GPT 参考包保留在 `2026-EgoAnchor/gpt-web-analysis/EgoAnchor_corrected_newdata_v4_package/`，只作为绘图和论文样式的审计参照，不作为正式数字输入。正式数字始终来自当前五本 XLSX。

## 复现与验收

重建前后比较五本 XLSX 的 SHA-256；它们必须保持不变。重复运行 `build-paper` 时，CSV、表格、PNG/PDF 和主稿应保持科学内容一致；`gpt_v4_manifest.json` 中的输入 hash 必须相同。

论文编译命令：

```powershell
Set-Location ../2026-EgoAnchor
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
```

用 Poppler 渲染 PDF 第 6--8 页检查实验段落、表格、图注和图形；图中不能出现裁切、重叠、旧文件名或未格式化的长小数。主稿不依赖 `generated/exp*.tex`，移走分析输出后仍应能编译。

## 边界

- 初始 XLSX 是 Stage 1 事实桥梁，不能被 GPT 脚本改写或替换为 GPT 包里的汇总 XLSX。
- 新管线不保留旧 `eval/analysis`、`eval/publishing` 或旧 `analyze/publish/materialize-paper` 入口；不要恢复兼容层。
- 新增科学参数只能写入 `src/egoanchor/eval/config/gpt_v4.toml`，每行保留中文注释。
- 论文正文使用 median [Q1, Q3] 和明确的样本数；不同场景不混成一个全局排名。
