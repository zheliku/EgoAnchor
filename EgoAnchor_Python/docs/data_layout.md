# 实验数据目录

实验一/二把原始任务、逐任务缓存和当前五任务组合分开保存。替换一个 Task 时，只新增该 Task 的
原始目录、工作簿和指标缓存；其他四项不复制、不重建。

```text
data/
├─ eval/                                      # 新采集和 Mutagen 同步中的 session
└─ experiments/
   ├─ task_data/                              # 唯一原始归档，禁止原地修改
   │  └─ task_3_v2_20260724_034253_controller_right/
   ├─ task_workbooks/                         # 逐任务 Stage 1 缓存
   │  └─ task_3_v2_20260724_034253_controller_right/
   │     ├─ task_3_complete.xlsx
   │     └─ cache.json
   ├─ task_analysis/                          # 逐任务论文指标缓存
   │  └─ task_3_v2_20260724_034253_controller_right/
   │     └─ task_3_complete_metrics.json
   ├─ _staging/experiment_1_2/                # 待提升的轻量组合清单
   │  └─ batch_<task1-time>_..._<task5-time>/
   │     └─ batch.json
   ├─ _archive/experiment_1_2/                # 旧组合清单和对应分析产物
   └─ experiment_1_2/                         # 当前论文活动组合
      ├─ batch.json                           # 当前选中的五个任务缓存
      └─ analysis/
         ├─ metrics/                          # 完整精度 CSV/JSON
         ├─ plots/figure_plot_data.xlsx       # 图 2、图 3 的逐点审计数据
         ├─ figures/                          # 七个实验面板的 PNG/PDF
         ├─ tex/                              # 手工引入主稿的表格和图环境
         └─ provenance/                       # 输入、参数和缓存状态
```

## 原始任务

`data/eval/` 只接收新 session。两端停止并完成同步后，把目录移入 `task_data/`，名称固定为：

```text
task_<1-5>_v<正整数>_<YYYYMMDD_HHMMSS>_<物体>
```

时间和物体必须对应内部 manifest。版本按任务独立递增，局部重采只增加对应任务的版本。默认选择
每项任务的最高版本及该版本最新时间；也可以通过 `--version`、`--task-version` 和 `--object`
固定选择。

`task_data/` 是唯一原始归档。目录进入这里后视为只读；不要在原目录里覆盖 JSON/JSONL。需要修正
或重采时创建新的 `vN` 目录。`stage` 用文件路径、大小和修改时间快速识别原地变化，显式 `qc`
用于需要完整深查的情况。

## 独立缓存

`task_workbooks/` 中每个目录只对应一个 `task_data` 目录。首次生成会执行事件物化、完整 QC、XLSX
写出和回读验证；缓存命中后不重复这些工作。工作簿保留原始行、来源 SHA-256 和 QC 结果，可以只读
查看，不能用 Excel 保存后继续用于正式分析。

`task_analysis/` 保存每本工作簿的片段级指标和性能原始样本。缓存键由工作簿 SHA、`paper.toml`
SHA 和指标实现内容指纹组成。修改论文参数或指标实现时会重算受影响缓存；仅替换 Task 3 时，另外
四项保持命中。最终统计、图、表和 TeX 始终由当前五项缓存合并生成。

## 活动组合

`experiment_1_2/batch.json` 是当前论文数据的唯一选择清单。它按 Task 1--5 引用五个原始目录和五本
工作簿，并冻结 session 身份与工作簿摘要。`promote` 只切换这份清单，不复制 raw，不复制 XLSX，
也不重跑 QC。

替换一个任务后，批次名会变化，但正式分析仍要求五项任务共享对象、协议、配置哈希、冻结参数集和
运行时矩阵。可以局部更新输入，不能按结果好坏从不同采集配置中拼场景。

旧活动组合的 `batch.json` 和 `analysis/` 会进入 `_archive/`。共享的原始目录、工作簿和指标缓存不随
组合重复归档。`_staging/` 和 `_archive/` 都不是默认论文输入。

## 发布边界

`analyze` 只写当前活动组合的 `analysis/`，不会修改论文目录。确认结果后，`pixi run eval copy-assets`
才按 `batch.toml` 的清单复制 PNG/PDF 到 `2026-EgoAnchor`。TeX 由研究者手工纳入主稿。

所有操作路径从 `src/egoanchor/eval/config/batch.toml` 读取。原始数据、工作簿缓存、指标缓存和活动
分析目录均由 `.gitignore` 排除；Git 只跟踪代码、说明、论文源稿和正式图表。
