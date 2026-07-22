# 实验数据目录

实验一/二的数据固定放在 EgoAnchor_Python/data/experiments/experiment_1_2/。目录不再带
v1、v2、v3 或分析实现版本号；数据身份由 manifest、工作簿 SHA-256 和 provenance
文件确定。

~~~text
data/
├─ eval/                              # 新采集 session 的暂存区
└─ experiments/
   ├─ _staging/experiment_1_2/        # 新批次通过整批 QC 前的临时位置
   ├─ _archive/experiment_1_2/        # 已退出当前论文的只读冷归档
   └─ experiment_1_2/                 # 当前论文唯一活动批次
      ├─ raw/
      │  ├─ task_1_static_head_motion/
      │  ├─ task_2_start_stop_6dof/
      │  ├─ task_3_continuous_translation/
      │  ├─ task_4_continuous_rotation/
      │  └─ task_5_occlusion_recovery/
      ├─ workbooks/
      │  ├─ task_1_complete.xlsx
      │  ├─ ...
      │  └─ task_5_complete.xlsx
      ├─ analysis/
      │  ├─ metrics/                  # 完整精度 CSV/JSON
      │  ├─ plots/
      │  │  └─ figure_plot_data.xlsx # 图 2、图 3 的逐点数据
      │  └─ provenance/               # 输入 hash 与构建结果
      └─ provenance/
         └─ strategy_label_migration.json
~~~

## 各层职责

data/eval/ 只接收 Unity/Python 新生成的 session 目录。Mutagen 同步、两端停止和 QC
完成前，不移动或重命名其中的 session。

当前 Stage 1 不拆分多任务 session，也不合并多个 session。正式批次使用五个不同 session，
每个 session 只完成一个 task。`pixi run eval stage` 会先执行整批 QC，再复制到
experiments/_staging/experiment_1_2/batch_YYYYMMDD_HHMMSS_<config-hash>/raw/，并把外层副本
命名为固定 task 名；内部 session_id 和固定文件内容不变。

raw/ 是当前论文数据的只读归档。五个目录按物理任务命名，内部仍保留原始 session_id、
来源行号和固定 JSON/JSONL 文件名。替换正式批次时必须一次替换五项任务，不能按场景挑选
不同批次。

_archive/ 只保存已经退出当前论文的完整旧批次，批次名使用日期和配置 hash，不使用 v1、
v2、v3。_staging/ 与 _archive/ 都不是默认论文输入；正式发布只使用无版本后缀的活动目录。

workbooks/ 是 Stage 1 输出，也是 build-paper 的唯一输入。工作簿完整保留 raw 行、来源
SHA-256 和 QC 结果。可以只读查看，不能在 Excel 中保存后继续用于正式分析。

analysis/metrics/ 保存完整精度指标，供审计和复算使用。analysis/plots/figure_plot_data.xlsx
只整理图中实际显示的数据点，含 README、Figure2 和 Figure3 三个 sheet；它不是新的统计
输入，也没有独立的 plot XLSX 到图片转换命令。build-paper 从五本工作簿同时生成该文件和
PNG/PDF 面板。

以上操作路径统一从 `src/egoanchor/eval/config/batch.toml` 读取。人工归档和分析使用
`pixi run eval`，不需要设置 shell 环境变量或在命令行逐项传入路径。

provenance/strategy_label_migration.json 保存当前批次完成策略身份统一时的文件摘要。该文件
属于数据来源记录，不能作为可删除的普通中间产物处理。

## 发布边界

论文图和表发布到 2026-EgoAnchor/figures/panels/ 与 2026-EgoAnchor/tables/。这些文件由
分析代码生成，不从历史结果包复制。原始数据、Stage 1 工作簿和本地分析目录均由
.gitignore 排除；Git 只跟踪代码、目录说明、论文源稿和正式图表。
