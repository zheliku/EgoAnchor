# 实验一/二离线分析

人工入口只有一个：

```text
pixi run eval
```

旧的任意路径 `qc / preprocess / build-paper` CLI 已删除。底层能力保留为包内函数，人工操作
统一读取 `src/egoanchor/eval/config/batch.toml`，避免命令行路径与论文实际输入不一致。

## 配置

`batch.toml` 控制新 session、暂存、冷归档、当前活动批次、论文根目录、当前版本化主稿和稳定
PDF 名。相对数据路径以 `EgoAnchor_Python` 根目录为基准；论文文件以 `paper_root` 为基准。

当前主稿是 `egoanchor_cn_v6.tex`，最终交付文件是 `pdf/EgoAnchor.pdf`。版本升级时只修改
`[paper].manuscript`，不用修改 Python。

`src/egoanchor/eval/config/paper.toml` 只保存论文统计参数。它的 SHA-256 会进入分析
provenance，不用于配置目录或文件名。

查看解析后的绝对路径和每个阶段的输入、输出：

```text
pixi run eval config
```

## 数据流

```text
data/eval/<session_id>
  -> stage
  -> staging/<batch_id>/{raw,workbooks}
  -> promote
  -> experiment_1_2/{raw,workbooks}
  -> analyze
  -> analysis + figures + tables + manuscript
  -> latex
  -> pdf/EgoAnchor.pdf
```

逐阶段命令：

```text
pixi run eval sessions
pixi run eval stage <session-dir-1> <session-dir-2> <session-dir-3> <session-dir-4> <session-dir-5>
pixi run eval promote <batch_id>
pixi run eval qc
pixi run eval preprocess
pixi run eval analyze --skip-latex
pixi run eval latex
```

`stage` 会对新 session 执行整批 QC、复制来源并生成暂存工作簿。`promote` 才会切换当前
活动批次。`qc` 和 `preprocess` 读取当前 raw；缺少 `events.jsonl` 时会从两个事件分片确定性
生成。`analyze` 只读取五本 Stage 1 XLSX，但会更新指标、绘图数据、论文面板、TeX 表和配置
指定的主稿。`latex` 只编译主稿，不重新分析数据。

`stage` 参数是 `data/eval` 下的目录名，不要求它与 `manifest.session_id` 同名。目录可保留
`task_1_..._v4` 这类人工标签；批次身份始终取 manifest 内不可改写的 `session_id`。
同一批目录重复执行 `stage` 时，程序会重新构建五本 XLSX。新批次完整通过后替换同名暂存批次；
重建失败时保留旧暂存批次。

耗时命令会在终端 stderr 显示 `tqdm` 任务进度条和当前阶段；最终 JSON 结果仍写入 stdout，
可继续用于脚本处理。

## Stage 成功后

`stage` 返回 `"passed": true` 后，终端会给出 `batch_id` 和下一条 `promote` 命令。此时五份
原始 session 已完成 QC，并复制为一个独立批次；五本 `task_N_complete.xlsx` 也已经生成和回读。

下一步直接运行：

```text
pixi run eval promote <batch_id>
```

`promote` 会再次检查暂存 raw、五本工作簿和来源摘要，然后做两次目录移动：现有活动批次进入
`_archive/`，刚刚通过检查的暂存批次进入 `data/experiments/experiment_1_2/`。原始
`data/eval/` session 不会被移动、改名或覆盖。

成功时 JSON 中应有：

```text
"passed": true
"active_batch": "batch_..."
"active_root": ".../data/experiments/experiment_1_2"
"next_command": "pixi run eval analyze"
```

如果 `promote` 失败，活动批次不会切换，暂存批次仍保留在 `_staging/`。修复报错原因后，重复同一条
`promote` 命令即可；不需要重新采集，也通常不需要重新执行 `stage`。

`stage` 已经写好了当前批次的五本工作簿，因此正常流程中不再运行 `preprocess`。下面两条命令只在
需要时使用：

- `pixi run eval qc`：查看当前活动批次的 raw QC 报告，不改写工作簿。
- `pixi run eval preprocess`：从当前活动 raw 重新生成五本工作簿。它适用于明确要重建 Stage 1
  产物的情况，不是 `stage` 成功后的必经步骤。

## 生成分析结果

`promote` 成功后，直接运行：

```text
pixi run eval analyze
```

这条命令只读取当前活动批次的五本 XLSX。它依次验证工作簿、计算指标、生成七个图表面板、写入两张
LaTeX 表、回填中文主稿，并编译最终 PDF。不要手工编辑分析生成的 CSV、图、表或主稿结果段；下次
`analyze` 会覆盖它们。

想把分析和 LaTeX 编译分开排查时，使用：

```text
pixi run eval analyze --skip-latex
pixi run eval latex
```

`analyze` 成功后的主要输出：

| 位置 | 内容 |
| --- | --- |
| `data/experiments/experiment_1_2/analysis/metrics/` | 完整精度的 CSV、时序策略候选数据和运行性能统计。 |
| `data/experiments/experiment_1_2/analysis/plots/figure_plot_data.xlsx` | 图二、图三的可见数据点审计表。 |
| `data/experiments/experiment_1_2/analysis/provenance/build_result.json` | 五本 XLSX、统计参数和生成结果的溯源信息。 |
| `../2026-EgoAnchor/figures/panels/` | 七个论文面板的 PDF 和 PNG。 |
| `../2026-EgoAnchor/tables/` | 实验一和实验二的自动生成 LaTeX 表。 |
| `../2026-EgoAnchor/egoanchor_cn_v6.tex` | 已回填实验一、实验二结果的中文主稿。 |
| `../2026-EgoAnchor/pdf/EgoAnchor.pdf` | 最终编译 PDF。 |

如果 `analyze` 在指标或绘图阶段失败，先阅读终端中的具体契约错误，不使用局部生成结果。修复数据或
配置问题后重新运行 `analyze`。如果只有 LaTeX 失败，先运行 `analyze --skip-latex` 保留分析结果，
再用 `pixi run eval latex` 单独处理编译问题。

从当前 raw 一次重建：

```text
pixi run eval rebuild
```

## 输出边界

```text
data/experiments/experiment_1_2/analysis/
├─ metrics/
├─ plots/figure_plot_data.xlsx
└─ provenance/

../2026-EgoAnchor/figures/panels/
../2026-EgoAnchor/tables/
../2026-EgoAnchor/egoanchor_cn_v6.tex
../2026-EgoAnchor/pdf/EgoAnchor.pdf
```

`figure_plot_data.xlsx` 是审计输出，不是绘图输入。PNG/PDF 面板与它来自同一份分析结果。
手工修改 plot XLSX 不会改变图片，下次 `analyze` 还会覆盖它。

五本工作簿分别原子发布，但五本文件不是一个跨文件事务。`analyze` 的全部输出也不是单一
事务。任一阶段失败后，不使用局部新产物；排除文件锁、输入或配置问题后重新运行完整阶段。

详细输入、输出、可控项和失败处理见
`2026-EgoAnchor/experiment_1_2_analysis_reproduction_manual_zh.md`。

## 验证

```text
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src
pixi run eval config
pixi run eval qc
pixi run eval latex
```
