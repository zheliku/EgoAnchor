# 实验一/二离线分析

科学分析契约仍由 `egoanchor.eval.cli` 的 `qc`、`preprocess` 和 `build-paper` 三个命令实现。
人工操作统一通过 `pixi run eval` 的固定路径包装入口完成，不需要在命令行传五组路径。

```text
raw JSON/JSONL
  -> qc
  -> preprocess
  -> task_1_complete.xlsx ... task_5_complete.xlsx
  -> analyze（内部调用 build-paper）
  -> 指标、绘图 XLSX、LaTeX 表格、面板图和中文主稿
  -> latex
  -> egoanchor_cn_v6.pdf
```

`qc` 和 `preprocess` 可以读取 raw JSON/JSONL。`analyze` 只读取五本 Stage 1 XLSX，不回读
raw，也不修改工作簿。统计单位是动作片段或遮挡 episode，渲染帧不作为独立样本。

## 路径配置

操作路径位于 `src/egoanchor/eval/config/batch.toml`，默认指向当前仓库的数据与论文目录。
论文统计参数位于 `src/egoanchor/eval/config/paper.toml`。路径配置不改变科学参数，正式 CLI
也不提供统计参数覆盖入口。

当前预处理要求一项任务对应一个独立 session，不拆分多任务 session，也不合并多个
session。五项任务必须使用 `variant_matrix_id=exp12_9_linear_v2` 并完整记录九个 runtime。

## 新批次归档

```text
pixi run eval sessions
pixi run eval stage <session-1> <session-2> <session-3> <session-4> <session-5>
pixi run eval promote <stage 输出的 batch_id>
```

五个 session 的输入顺序不限，程序按 `completed_tasks` 自动映射任务 1--5。`stage` 会执行
整批 QC、复制来源和生成五本工作簿；`promote` 会复核 raw/XLSX 来源摘要，并整体归档旧批次。

## 逐阶段重建

```text
pixi run eval qc
pixi run eval preprocess
pixi run eval analyze --skip-latex
pixi run eval latex
```

对应关系如下：

| 命令 | 输入 | 主要输出 |
|---|---|---|
| `pixi run eval qc` | 当前 `raw/` | QC JSON，不发布论文产物 |
| `pixi run eval preprocess` | 当前 `raw/` | `workbooks/task_1_complete.xlsx` 到 `task_5_complete.xlsx` |
| `pixi run eval analyze --skip-latex` | 当前五本 XLSX | 指标、绘图 XLSX、PNG/PDF 面板、TeX 表和中文主稿 |
| `pixi run eval latex` | 当前中文主稿 | `2026-EgoAnchor/pdf/egoanchor_cn_v6.pdf` |

从 raw 一次完成全部阶段使用：

```text
pixi run eval rebuild
```

工作簿已经存在时，从 XLSX 开始并同时编译论文使用：

```text
pixi run eval analyze
```

## 输出

```text
data/experiments/experiment_1_2/analysis/
├─ metrics/
├─ plots/
│  └─ figure_plot_data.xlsx
└─ provenance/

../2026-EgoAnchor/figures/panels/figure2a_...png/.pdf 到 figure3d_...png/.pdf
../2026-EgoAnchor/tables/experiment1_system_characterization.tex
../2026-EgoAnchor/tables/experiment2_design_attribution.tex
../2026-EgoAnchor/egoanchor_cn_v6.tex
../2026-EgoAnchor/pdf/egoanchor_cn_v6.pdf
```

`figure_plot_data.xlsx` 与面板共享同一分析结果，只用于审计和人工查看，不是绘图输入。没有
独立的 plot-XLSX-to-figure 阶段；重新生成 PNG/PDF 时再次运行 `pixi run eval analyze`。

图 2 和图 3 都由 LaTeX subfigure 排成一行。图内不重复小标题；图 2(b) 不连接跨方法折线。
raw、工作簿和 `strategy_label_migration.json` 不得由分析阶段改写。

## 代码验证

```text
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src
```
