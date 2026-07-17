
# EgoAnchor 实验一/二离线分析详细实施计划

**文档版本**: v2.0 - 四阶段重构版
**创建日期**: 2026-07-18
**适用范围**: Run 2 离线分析重构，从 schema-v2 原始数据到论文物化
**执行模式**: 逐 Task 实施，每个 Task 独立验证、提交、推送

---

## 执行前置要求

### 必读文档

1. 仓库根目录 `AGENTS.md` 顶部用户手动维护要求
2. `2026-EgoAnchor/experiment_1_2_analysis_rebuild_plan.md`（用户确认的原始四阶段路线，供参考）
3. 本文档全部内容（详细实施计划）

### 环境准备

- Python 环境：`pixi` 已安装，`EgoAnchor_Python` 环境就绪
- Git 状态：当前分支干净，或用户明确保留的未提交改动
- 原始数据：五个 task 目录只读且完整
  - `data/eval/task_1_20260717_203329_controller_right`
  - `data/eval/task_2_20260717_203749_controller_right`
  - `data/eval/task_3_20260717_204156_controller_right`
  - `data/eval/task_4_20260717_204943_controller_right`
  - `data/eval/task_5_20260717_205539_controller_right`

### 执行纪律

- **一次只完成一个 Task**，不跨 Task 提前实现
- 每个 Task 开始前检查 `git status`、影响范围、引用关系和架构边界
- 先补测试，再改实现
- 验证通过后独立提交并推送，提交信息格式：`Task N: <简要描述>`
- 不要恢复旧分析接口、旧命令或兼容层
- 不要覆盖用户现有未提交改动
- Stage 2 只能读取 Stage 1 XLSX，Stage 3 只能读取 Stage 2 CSV，Stage 4 只能读取 Stage 3 TeX

---

## 总体架构

### 四阶段数据流

```
五个只读 schema-v2 task 目录
  ↓ Stage 1: preprocess (逐task生成完整XLSX)
五个 task_<n>_complete.xlsx (每个task一个完整工作簿，包含所有源文件信息+QC)
  ↓ Stage 2: analyze (批次计算指标)
QC/metric/plot-ready CSV tables (results/ 目录结构化输出)
  ↓ Stage 3: publish (生成论文产物)
PDF/PNG figures + TeX numbers/tables (发布到 2026-EgoAnchor/)
  ↓ Stage 4: materialize-paper (物化到主稿)
egoanchor_cn_v6.tex (自动生成区块，主稿自包含编译)
```

### 单向数据契约（严格执行）

- **原始数据**：五个task目录保留为只读冷归档，Stage 1成功后后续分析不再读取JSONL
- **Stage 1→Stage 2**：Stage 2只能读取Stage 1 XLSX，禁止访问raw task目录
- **Stage 2→Stage 3**：Stage 3只能读取Stage 2 CSV，禁止回读XLSX或raw data
- **Stage 3→Stage 4**：Stage 4只能读取Stage 3 TeX中间产物，禁止直接读CSV
- **审计追溯**：每个阶段输出时记录输入数据的SHA-256，保证lineage可追踪

### 新包结构

```
EgoAnchor_Python/src/egoanchor/eval/
├── __init__.py                    # 包级公开入口
├── cli.py                         # 统一CLI：qc/preprocess/analyze/publish/materialize-paper
├── contracts/                     # 数据契约与版本管理
│   ├── __init__.py
│   ├── workbook.py               # Stage 1 XLSX sheet契约
│   ├── metrics.py                # 指标定义、公式、单位
│   ├── plots.py                  # 绘图数据契约
│   └── versions.py               # 契约版本管理
├── config/                        # 冻结分析参数
│   └── analysis_params.toml      # HP-RMS/阈值/单位，带中文同行注释
├── preprocess/                    # Stage 1: raw → XLSX
│   ├── __init__.py
│   ├── reader.py                 # schema-v2 JSONL流式读取
│   ├── qc.py                     # 完整硬QC
│   ├── workbook.py               # XLSX writer + 回读验证
│   └── provenance.py             # 来源追踪、hash、data dictionary
├── analysis/                      # Stage 2: XLSX → CSV
│   ├── __init__.py
│   ├── loader.py                 # XLSX批次加载与校验
│   ├── pose.py                   # 位姿误差计算原语
│   ├── windows.py                # event/segment窗口提取
│   ├── metrics.py                # 通用指标：HP-RMS/jump/lag/response
│   ├── latency.py                # 时延计算（单调时钟约束）
│   ├── exp1.py                   # 实验一：4系统×5场景
│   ├── exp2.py                   # 实验二：4组件消融
│   ├── vcd.py                    # VCD risk-coverage/AURC
│   └── csv_output.py             # CSV发布+lineage
├── publishing/                    # Stage 3: CSV → figures/TeX
│   ├── __init__.py
│   ├── style.py                  # 固定palette/marker/label
│   ├── figures_exp1.py           # 实验一三联图
│   ├── figures_exp2.py           # 实验二双联图
│   ├── latex.py                  # TeX中间产物生成
│   └── materialize.py            # Stage 4: 主稿物化
├── schema_v2/                     # 保留运行时需要的部分
│   ├── __init__.py
│   ├── rows.py                   # 行契约dataclass（不删，runtime依赖）
│   ├── writers.py                # 运行时writer（不删，runtime依赖）
│   └── paths.py                  # 路径约定（不删，runtime依赖）
└── tests/                         # 单元测试与集成测试
    ├── __init__.py
    ├── test_contracts.py
    ├── test_reader_qc.py
    ├── test_workbook.py
    ├── test_metrics.py
    ├── test_exp1_analysis.py
    ├── test_exp2_analysis.py
    └── fixtures/                 # 最小真实fixture
```

### CLI设计

```bash
# Stage 1: 逐task预处理
pixi run python -m egoanchor.eval.cli preprocess \
  data/eval/task_1_20260717_203329_controller_right \
  data/eval/task_2_20260717_203749_controller_right \
  data/eval/task_3_20260717_204156_controller_right \
  data/eval/task_4_20260717_204943_controller_right \
  data/eval/task_5_20260717_205539_controller_right \
  --out data/analysis/complete

# Stage 2: 批次分析
pixi run python -m egoanchor.eval.cli analyze \
  data/analysis/complete/task_*.xlsx \
  --out data/analysis/results

# Stage 3: 发布论文产物
pixi run python -m egoanchor.eval.cli publish \
  data/analysis/results \
  --paper-root ../2026-EgoAnchor

# Stage 4: 物化到主稿
pixi run python -m egoanchor.eval.cli materialize-paper \
  data/analysis/results \
  --paper-root ../2026-EgoAnchor

# 独立QC（不生成XLSX）
pixi run python -m egoanchor.eval.cli qc \
  data/eval/task_1_20260717_203329_controller_right
```

**退出码约定**：

- 0：成功
- 1：文件系统错误或缺少源文件
- 2：schema/QC/分析契约失败

---

## Stage 1：预处理工作簿 (preprocess)

### 目标

从每个schema-v2 task目录生成一个完整、可审计的XLSX工作簿，包含所有源文件信息、QC结果和数据字典。

### 输入与输出

**输入**：一个完整task目录，包含：

- `manifest.json` + `python_session.json`
- `python_candidates.jsonl` + `python_events.jsonl`
- `unity_reference.jsonl` + `unity_admission.jsonl` + `unity_render.jsonl` + `unity_events.jsonl`
- `events.jsonl`（合并后的事件流）

**输出**：

```
data/analysis/complete/
├── task_1_complete.xlsx
├── task_2_complete.xlsx
├── task_3_complete.xlsx
├── task_4_complete.xlsx
└── task_5_complete.xlsx
```

### Sheet契约

| Sheet名称             | 行粒度/主键                                  | 内容说明                                                 |
| --------------------- | -------------------------------------------- | -------------------------------------------------------- |
| `README`            | 文档                                         | 契约版本、单位、空值语义、平台参考诚实边界               |
| `provenance`        | 每workbook 1行                               | session、源目录、schema/config hash、代码版本、生成时间  |
| `source_files`      | 每文件1行                                    | 相对路径、存在性、字节数、行数、SHA-256                  |
| `manifest`          | 每session 1行                                | `manifest.json`与`python_session.json`的稳定标量字段 |
| `metadata_kv`       | `document + json_path`                     | 嵌套、数组或未来扩展字段，禁止静默丢弃                   |
| `variants`          | `session_id + variant_id`                  | 8个runtime的配置与组件开关                               |
| `trial_plan`        | `session_id + task_number`                 | 冻结任务计划                                             |
| `completed_trials`  | 完整trial key                                | 最终完成且未作废的trial                                  |
| `writer_stats`      | `session_id + file_name`                   | rows、drop、failure、pending/stop状态                    |
| `python_candidates` | `session_id + candidate_id`                | candidate全部标量，pose matrix展开为标量列               |
| `candidate_flags`   | `candidate_id + flag_index`                | `reliability_flags`数组                                |
| `candidate_diag`    | `candidate_id + json_path`                 | `render_diagnostics`全量规范化                         |
| `unity_reference`   | `session_id + frame_id`                    | HMD、camera、平台参考pose与时间字段                      |
| `unity_admission`   | `session_id + candidate_id + variant_id`   | 8 runtime的实际admission                                 |
| `unity_render`      | `session_id + render_tick_id + variant_id` | tick × variant长表，所有pose展开为标量列                |
| `python_events`     | `source_file + source_line`                | Python原事件流                                           |
| `unity_events`      | `source_file + source_line`                | Unity原事件流                                            |
| `events`            | `source_file + source_line`                | 确定性合并事件流                                         |
| `event_payload`     | `event_row_id + json_path`                 | payload全量规范化，显式提取`event_role`                |
| `qc_checks`         | `check_id`                                 | pass/fail、观测值、期望值和错误详情                      |
| `data_dictionary`   | `sheet + column`                           | 类型、单位、空值语义、来源JSON path                      |

### Excel精度与容量规则

- **标识符保真**：candidate ID、哈希、session ID按文本写入（避免Excel自动转换）
- **数值时间**：用于分析的时间列保留为数值，但跨表join不依赖Excel浮点推断
- **数组拆分**：数组拆成标量列或子表，不把Python list/JSON字符串塞进一个单元格
- **禁止截断**：超过单sheet行数限制时稳定分片为`_001`、`_002`；任何未声明截断都必须hard fail
- **单元格限制**：单元格超过32,767字符时改写到规范化子表，不能静默截断
- **回读验证**：工作簿写出后必须重新读取，核对每个sheet行数、主键、外键、哈希和数据类型

### Stage 1 QC门禁（硬约束）

必须覆盖并保留现有schema-v2的硬约束：

- ✅ schema为2，固定文件齐全，session ID一致
- ✅ Python已停止；writer实际行数与冻结统计一致；drop/failure全为0
- ✅ candidate/reference主键唯一，admission外键有效
- ✅ 每个Unity实际消费的candidate恰有8个variant；每个render tick恰有8个variant
- ✅ 8个variant开关矩阵和整体FNV-1a config hash正确
- ✅ trial生命周期唯一、顺序合法，最终完成集合与manifest一致
- ✅ 遮挡事件严格交替闭合；其他marker只保留真实角色，不根据场景名猜语义
- ✅ pose数值有限、四元数可归一化、VCD与各分量在合法范围内
- ✅ 输出XLSX的事实行数与源文件逐项相等

**任何硬错误都禁止发布对应预处理工作簿；只输出独立QC诊断并返回退出码2。**

---

## Stage 2：指标计算与CSV发布 (analyze)

### 唯一输入原则

Stage 2**只接受**五个Stage 1工作簿，**禁止回读原始JSONL**。此时XLSX已经在工作流中替代原task文件夹。

开始计算前先检查：

- 五个场景齐全，session ID不重复
- object、protocol、run kind、config hash、冻结参数集和variant定义一致
- 输入workbook的SHA-256与批次输入清单一致
- 所有Stage 1 QC均通过

### 输出目录结构

```
data/analysis/results/
├── audit/                    # 输入、QC、定义和lineage
│   ├── analysis_run.csv
│   ├── inputs.csv
│   ├── metric_catalog.csv
│   ├── filter_catalog.csv
│   ├── analysis_qc.csv
│   ├── lineage.csv
│   └── sensitivity.csv
├── common/                   # 公共逐帧、candidate和窗口数据
│   ├── trial_windows.csv
│   ├── frame_metrics.csv
│   └── candidate_metrics.csv
├── exp1/                     # 实验一event/trial/session指标
│   ├── event_metrics.csv
│   ├── trial_metrics.csv
│   ├── session_metrics.csv
│   └── scenario_summary.csv
├── exp2/                     # 实验二配对差值与VCD诊断
│   ├── event_metrics.csv
│   ├── trial_metrics.csv
│   ├── session_metrics.csv
│   ├── paired_deltas.csv
│   ├── vcd_risk_points.csv
│   ├── vcd_curve.csv
│   └── vcd_aurc.csv
├── plots/                    # Stage 3唯一允许读取的窄表
│   ├── plot_catalog.csv
│   ├── exp1_static_timeline.csv
│   ├── exp1_motion_events.csv
│   ├── exp1_occlusion_events.csv
│   ├── exp2_component_deltas.csv
│   └── exp2_vcd_curve.csv
└── paper/                    # 论文数字和表格单元
    ├── numbers.csv
    └── tables.csv
```

### 基础位姿与时间公式

**平移和旋转误差**：

```python
translation_error_mm = 1000 * ||p_display - p_reference||_2
rotation_error_deg = 2 * acos(clamp(abs(dot(q_display_norm, q_reference_norm)), 0, 1)) * 180/pi
```

**关键约束**：

- 显示误差使用`display_*`和`has_display_pose`
- 输出可用性使用`has_output_pose`（不能用hold-last的显示覆盖率代替）
- candidate arrival只在Unity单调时钟内计算：`unity_pose_handle_mono_ms - source_capture_mono_ms`
- Python processing只在Python单调时钟内计算：`server_publish_mono_ms - server_receive_mono_ms`
- 平台控制器pose只能称平台参考，不称外部真值

### 实验一：端到端系统表征

**比较配置**（4个）：

1. **Arrival-Hold**：到达时刻复合、接受全部合法候选、零阶保持
2. **Capture-Hold**：采集时刻世界复合、接受全部合法候选、零阶保持
3. **One-Euro Anchor**：采集时刻世界复合、基本有效性检查、One Euro自适应滤波
4. **EgoAnchor**：采集时刻世界复合、VCD接纳、Kalman-Hermite合成、显式静止锚定

**场景与主指标**：

| 场景              | 正文主指标                                         | 必要guardrail/次指标                               |
| ----------------- | -------------------------------------------------- | -------------------------------------------------- |
| 静止目标+主动头动 | event-P95平移误差；位置HP-RMS                      | event-P95旋转误差、绝对误差中位数、drift           |
| 起停6DoF          | visible response；settling time；运动窗平移P95     | 旋转P95、jump P95、unlock/relock诊断               |
| 持续平移          | 平移event-P95；effective lag                       | lag-compensated residual仅作诊断、jump P95         |
| 持续旋转          | 旋转event-P95；effective angular lag               | lag-compensated angular residual、angular jump P95 |
| 遮挡恢复          | 遮挡窗平移event-P95；durable recovery time/success | 旋转P95、jump P95、错误更新、fresh output time     |

**汇总顺序**：

```
frame/candidate
  -> session × scenario × trial × event/segment × variant 内计算
  -> 同一event/segment内方法配对
  -> 报event-level median [IQR]、范围和配对方向
```

**关键原则**：

- P95必须先在每个event/segment内计算，再对event-level P95做median[IQR]
- 禁止把不同持续时间的所有帧混池后计算一个P95
- 不做frame-level p值、置信区间或显著性检验
- 统计单位是event/segment，不是frame

### 实验二：组件归因

**消融配置**（4个）：

1. **EgoAnchor w/o capture-time alignment** → 适用场景：`static_head_motion`
2. **EgoAnchor w/o VCD** → 适用场景：`occlusion_recovery`
3. **EgoAnchor w/o temporal synthesis** → 适用场景：`start_stop_6dof`
4. **EgoAnchor w/o StaticLock** → 适用场景：`static_head_motion`

**组件归因表**：

| 组件                   | 场景               | 主要效应                            | 代价/guardrail                                   |
| ---------------------- | ------------------ | ----------------------------------- | ------------------------------------------------ |
| capture-time alignment | static head motion | 配对窗口的平移P95差值               | 旋转P95；误差随HMD线/角速度变化                  |
| VCD admission          | occlusion recovery | 配对遮挡事件的平移P95与jump P95差值 | durable recovery；risk-coverage/AURC仅作评分诊断 |
| temporal synthesis     | start-stop 6DoF    | jump P95/P99或逐帧连续性            | visible response、运动P95、额外lag               |
| StaticLock             | static head motion | 位置HP-RMS差值                      | 绝对误差与drift，防止冻结错误pose虚胜            |

**VCD risk-coverage固定契约**：

- 只使用完整EgoAnchor的candidate
- 使用capture-time aligned raw pose
- risk是相对同一`frame_id`平台参考的平移误差，单位mm
- 按VCD分数降序诱导候选顺序；VCD本身不是排序算法或正确概率
- 并列分数按同一阈值整组纳入
- 明确coverage分母、无pose/无reference/未到达Unity candidate的排除规则

---

## Stage 3：论文产物发布 (publish)

### 数据接口

Stage 3**只能读取**`plots/plot_catalog.csv`、其中声明的`plots/<plot_id>.csv`，以及`paper/*.csv`。

`plot_catalog.csv`至少包含：

```
plot_id, panel_id, source_csv, x, y, hue, row_facet, col_facet,
filter_rule_id, order, unit, scale, target_width, output_basename,
expected_rows, data_sha256
```

**关键约束**：绘图阶段可以改颜色、线型、布局、字号和图型，但**不能重新筛选trial、连接reference、重算误差或改变指标定义**。

### 正文版面决策

IEEE VR正文只有9页，实验一/二完成后还要为实验三保留空间。建议正文只保留：

1. **系统配置表**：说明4个实验一系统和4个消融的组件差异
2. **实验一跨栏汇总表**：5个场景，每个场景1-2个主指标，4系统并列；数字为event-level汇总，不跨场景平均
3. **实验一三联图**：静止头动、起停、遮挡恢复的代表性时间线或配对事件图；持续平移/旋转的error-lag数字放汇总表
4. **实验二四行消融表**：每行一个组件，给主要差值和代价/guardrail
5. **实验二双联图**：VCD event-level配对效果 + risk-coverage曲线

### 图形规范

**颜色方案**（确保灰度可辨）：

```python
COLORS = {
    'Arrival-Hold': '#6B6B6B',      # 灰色（基线）
    'Capture-Hold': '#0072B2',      # 蓝色（隔离frame alignment）
    'One-Euro': '#E69F00',          # 橙色（标准滤波基线）
    'EgoAnchor': '#009E73',         # 绿色（完整系统）
}
ABLATION_COLOR = '#D55E00'  # 红橙色（强调差值）
```

**线型与标记**：

- Arrival-Hold: `'--'` + `'s'` (square)
- Capture-Hold: `'-.'` + `'o'` (circle)
- One-Euro: `':'` + `'^'` (triangle)
- EgoAnchor: `'-'` (solid, linewidth=2) + `'D'` (diamond)

**技术规范**：

- 低样本量场景禁用bar/violin，优先使用全部事件点、同事件配对线、median[IQR]和原始时间线
- 时间线只说明系统行为和事件关系，图注明确"统计单位是event/segment，不是frame"
- 四系统颜色和顺序固定，同时使用线型和marker保证灰度可辨
- 双栏图按最终物理宽度设计，正文最小字号不低于7 pt
- PDF使用嵌入字体和矢量元素，另导出PNG供快速审查
- 不统一加粗"最好值"（论文的真实结论是稳定性和遮挡尾部收益换取持续运动lag）

### 论文产物

Stage 3同时从`paper/numbers.csv`和`paper/tables.csv`生成：

```
2026-EgoAnchor/generated/
├── exp1_numbers.tex
├── exp1_tables.tex
├── exp2_numbers.tex
└── exp2_tables.tex

2026-EgoAnchor/figures/generated/
├── exp1_static_timeline.pdf
├── exp1_motion_events.pdf
├── exp1_occlusion_events.pdf
├── exp2_component_deltas.pdf
└── exp2_vcd_curve.pdf
```

**TeX命名规则**：

- 前缀：`\EAExpOne` / `\EAExpTwo`
- 变体名：驼峰式（如`EgoAnchor`, `ArrivalHold`）
- 指标名：描述性（如`TranslationMedianMm`）
- 分位数：字母拼写（如`PNinetyFive`不用`P95`）

---

## Stage 4：主稿数据物化 (materialize-paper)

### 目标

将Stage 3生成的四个`.tex`文件的内容写入`egoanchor_cn_v6.tex`中固定的自动生成区块，使最终中文主稿**不再依赖**`generated/exp{1,2}_*.tex`才能编译。

### 主稿自动生成区块

主稿使用稳定边界标记，例如：

```latex
% EGOANCHOR-EXP-DATA:BEGIN
% 由egoanchor.eval发布工具生成，请勿手工修改本区块。
...宏定义...
% EGOANCHOR-EXP-DATA:END
```

表格不能全部堆在导言区。每张实验表在正文原位置设置单独的自动生成区块，Stage 4只替换区块内部，不用字符串查找任意LaTeX片段，也不重排人工撰写正文。

### Stage 4规则

- 删除主稿中对四个生成`.tex`的`\IfFileExists` / `\input`依赖
- 宏定义写入导言区数据块；表格代码写入实验章节对应表格块
- 每个数据块首行记录源CSV hash、Stage 3 TeX hash和生成器版本
- 物化后再次解析主稿，确认所有预期宏定义唯一、所有表格块唯一、没有旧include残留
- 最终仍依赖外部PDF图文件，这是LaTeX图像的正常依赖
- `generated/*.tex`可以保留为审计产物，但主稿编译不能依赖它们

**验证**：删除`generated/exp{1,2}_*.tex`后，主稿仍应通过XeLaTeX编译。

---

## 13个Task详细实施步骤

---

## Task 0：确认路线并更新仓库约束

### 目标

将新的四阶段分析路线写入 AGENTS.md，作为 Run 2 的冻结执行入口。

### 改动文件

- AGENTS.md（非手动维护区）

### 具体操作

在 AGENTS.md 的 Run 2 离线分析架构章节，更新为四阶段描述，明确：

- 原始task目录为只读冷归档
- Stage 1成功后不再读取JSONL
- 统一CLI为 qc/preprocess/analyze/publish/materialize-paper
- 统计单位是event/segment，不是frame
- 不跨场景混池

### 验收标准

- 顶部 USER-MAINTAINED-REQUIREMENTS 区块逐字不变
- 新四阶段路线清晰记录
- 旧命令名不再出现
- Git diff 确认只修改了非手动维护区

### 提交信息

Task 0: 更新AGENTS.md冻结四阶段分析路线

---

## Task 1：依赖审计和旧实现删除

### 目标

删除旧离线分析代码和产物，建立新包骨架，确保运行时不受影响。

### 步骤

1. 审计依赖：确认只有 schema_v2 的 rows/writers/paths 被运行时引用
2. 删除旧代码：experiments/metrics/paper/figure_style/excel/旧cli
3. 建立新骨架：创建 contracts/config/preprocess/analysis/publishing 目录
4. 创建最小CLI骨架

### 验收标准

- 旧代码已删除，runtime不受影响
- pixi run python -m compileall src 通过
- pixi run python -m egoanchor.eval.cli 显示帮助

### 提交信息

Task 1: 删除旧离线分析代码，建立新包骨架

---

## Task 2：冻结workbook、CSV与metric契约

### 目标

定义Stage 1 XLSX、Stage 2 CSV和指标的完整数据契约，带版本管理和中文文档。

### 创建文件

- contracts/versions.py: 契约版本号和变更日志
- contracts/workbook.py: sheet名称、列名、主键、外键、数据类型
- contracts/metrics.py: 指标公式、单位、方向、适用场景
- config/analysis_params.toml: 冻结分析参数，带中文同行注释

### 验收标准

- 契约可序列化
- TeX命名扫描不含阿拉伯数字
- 所有类、成员、方法有中文文档字符串
- 单元测试验证契约结构

### 提交信息

Task 2: 冻结workbook、CSV与metric契约

## Task 3：实现schema-v2只读解析与Stage 1 QC

### 目标

实现流式JSONL读取、嵌套字段规范化、完整硬QC、来源行号与行hash。

### 创建文件

- preprocess/reader.py: 流式读取所有schema-v2文件
- preprocess/qc.py: 完整硬QC检查（8个variant、trial生命周期、事件配对等）
- tests/test_reader_qc.py: 真实最小fixture测试

### 关键QC检查项

- schema为2，固定文件齐全
- Python已停止，writer统计一致，drop/failure为0
- candidate/reference主键唯一，admission外键有效
- 8个variant矩阵正确，config hash正确
- trial生命周期合法，遮挡事件严格交替

### 验收标准

- 五个task逐个只读QC通过
- 错误fixture能稳定返回退出码2
- 不写工作簿（这一步只做QC）

### 提交信息

Task 3: 实现schema-v2只读解析与Stage 1 QC

---

## Task 4：实现Stage 1 workbook writer

### 目标

生成五个同构workbook、类型控制、分片规则、data dictionary、source hash、原子写出。

### 创建文件

- preprocess/workbook.py: XLSX writer，实现所有sheet契约
- preprocess/provenance.py: 来源追踪、文件hash、行号
- tests/test_workbook.py: 回读验证测试

### 关键实现

- 标识符按文本写入（避免Excel自动转换）
- 数组拆成标量列或子表
- 超过行数限制时分片为 _001, _002
- 单元格超过32767字符改写到规范化子表
- 写出后回读验证：行数、主键、外键、hash

### 验收标准

- 无截断
- 每个事实sheet行数与JSONL一致
- 主外键和hash回读通过

### 提交信息

Task 4: 实现Stage 1 workbook writer

---

## Task 5：生成并审计五个正式预处理工作簿

### 目标

执行完整的Stage 1 preprocess，生成五个正式XLSX，并进行人工+程序化审计。

### 执行命令

```bash
pixi run python -m egoanchor.eval.cli preprocess \
  data/eval/task_1_20260717_203329_controller_right \
  data/eval/task_2_20260717_203749_controller_right \
  data/eval/task_3_20260717_204156_controller_right \
  data/eval/task_4_20260717_204943_controller_right \
  data/eval/task_5_20260717_205539_controller_right \
  --out data/analysis/complete
```

### 审计检查

- 逐workbook视觉检查：README/表头/冻结行/列宽
- 程序化验证：行数、类型、唯一键、hash、QC checks sheet全通过
- 对比原始JSONL行数

### 验收标准

- 五个 task_N_complete.xlsx 生成成功
- 所有QC checks为pass
- 人工抽查确认数据正确性

### 提交信息

Task 5: 生成并审计五个正式预处理工作簿

## Task 6：实现公共指标原语与窗口提取

### 目标

实现pose误差计算、event/segment窗口提取、HP-RMS、drift、response、settling、lag、jump、recovery等基础指标。

### 创建文件

- analysis/pose.py: 平移/旋转误差计算，四元数归一化
- analysis/windows.py: event/segment窗口提取，marker角色解析
- analysis/metrics.py: HP-RMS、jump P95/P99、settling time、visible response
- analysis/latency.py: 时延计算（严格单调时钟约束）
- tests/test_metrics.py: 合成轨迹验证

### 关键公式

```python
translation_error_mm = 1000 * ||p_display - p_reference||_2
rotation_error_deg = 2 * acos(clamp(abs(dot(q_display_norm, q_reference_norm)), 0, 1)) * 180/pi
```

### 关键约束

- 显示误差使用 display_* 和 has_display_pose
- 输出可用性使用 has_output_pose
- candidate arrival只在Unity单调时钟内计算
- Python processing只在Python单调时钟内计算
- 禁止跨进程相减单调时钟

### 验收标准

- 合成轨迹有解析期望值
- 先event后汇总的P95测试通过
- 跨单调时钟相减测试必须失败

### 提交信息

Task 6: 实现公共指标原语与窗口提取

---

## Task 7：实现实验一分析

### 目标

只投影4个系统配置，按五场景冻结指标，生成event/trial/scenario长表和论文候选表。

### 创建文件

- analysis/exp1.py: 实验一主分析逻辑
- tests/test_exp1_analysis.py: 实验一分析测试

### 关键逻辑

1. 从XLSX加载5个session
2. 投影4个实验一variant（Arrival-Hold, Capture-Hold, One-Euro, EgoAnchor）
3. 按scenario分组（static_head_motion, start_stop_6dof, continuous_translation, continuous_rotation, occlusion_recovery）
4. 在每个trial/event内计算指标
5. 汇总到session级别
6. 输出event_metrics.csv, trial_metrics.csv, session_metrics.csv, scenario_summary.csv

### 场景主指标

- 静止头动: event-P95平移误差, 位置HP-RMS
- 起停6DoF: visible response, settling time, 运动窗平移P95
- 持续平移: 平移event-P95, effective lag
- 持续旋转: 旋转event-P95, effective angular lag
- 遮挡恢复: 遮挡窗平移event-P95, durable recovery time

### 验收标准

- 不混入消融variant
- 不跨场景混池
- 低n时保留全部配对点和范围
- P95先在event内计算，再对event-level P95做median[IQR]

### 提交信息

Task 7: 实现实验一分析

---

## Task 8：实现实验二分析与VCD诊断

### 目标

四组件适用场景、event-level paired delta、mean-risk AURC、P95 tail-risk curve、tie group、随机参考和敏感性表。

### 创建文件

- analysis/exp2.py: 实验二主分析逻辑
- analysis/vcd.py: VCD risk-coverage/AURC计算
- tests/test_exp2_analysis.py: 实验二分析测试

### 关键逻辑

1. 按组件适用场景筛选：
   - capture-time alignment: static_head_motion
   - VCD admission: occlusion_recovery
   - temporal synthesis: start_stop_6dof
   - StaticLock: static_head_motion
2. 在相同trial内配对完整EgoAnchor vs 消融
3. 计算差值（ablation - full）
4. VCD risk-coverage使用capture-time aligned raw pose

### VCD契约

- 只使用完整EgoAnchor的candidate
- risk是相对同frame_id平台参考的平移误差（mm）
- 按VCD分数降序诱导候选顺序
- 并列分数按同一阈值整组纳入
- 明确coverage分母和排除规则

### 验收标准

- 每个消融只关闭一个组件
- risk来自aligned raw同帧平台参考
- 未到达Unity candidate不伪造admission

### 提交信息

Task 8: 实现实验二分析与VCD诊断

## Task 9：实现Stage 2 CSV发布和lineage

### 目标

完整Stage 2 CSV契约、trial/event/session长表、plot-ready窄表、paper numbers/tables、input/output hash和原子目录发布。

### 创建文件

- analysis/loader.py: XLSX批次加载与校验
- analysis/csv_output.py: CSV发布+lineage追踪

### 输出目录结构

```
data/analysis/results/
├── audit/ (analysis_run, inputs, metric_catalog, filter_catalog, lineage, sensitivity)
├── common/ (trial_windows, frame_metrics, candidate_metrics)
├── exp1/ (event_metrics, trial_metrics, session_metrics, scenario_summary)
├── exp2/ (event_metrics, trial_metrics, paired_deltas, vcd_risk_points, vcd_curve, vcd_aurc)
├── plots/ (plot_catalog, exp1_*.csv, exp2_*.csv)
└── paper/ (numbers.csv, tables.csv)
```

### 关键约束

- 分析器只打开Stage 1 XLSX，禁止访问raw task路径
- 所有CSV使用UTF-8，缺失值为空字段，布尔值为true/false
- 每个输出记录输入XLSX的SHA-256
- 关键汇总可追溯到event和源行

### 验收标准

- 回读所有CSV成功
- lineage.csv可追溯每个结果到源XLSX
- Stage 2不读raw data

### 提交信息

Task 9: 实现Stage 2 CSV发布和lineage

---

## Task 10：实现论文绘图

### 目标

固定palette/marker/label、实验一三联图、实验二双联图、PDF/PNG、数据hash检查。

### 创建文件

- publishing/style.py: 固定颜色、线型、标记、字号
- publishing/figures_exp1.py: 实验一图表（静止时间线、运动事件、遮挡恢复）
- publishing/figures_exp2.py: 实验二图表（组件差值、VCD曲线）

### 图表清单

1. exp1_static_timeline.pdf: 静止头动时间线（4系统叠加，标注marker）
2. exp1_motion_events.pdf: 起停6DoF配对事件点图
3. exp1_occlusion_events.pdf: 遮挡恢复配对CCDF曲线
4. exp2_component_deltas.pdf: 4组件配对差值
5. exp2_vcd_curve.pdf: VCD risk-coverage曲线

### 颜色方案

```python
COLORS = {
    'Arrival-Hold': '#6B6B6B',
    'Capture-Hold': '#0072B2',
    'One-Euro': '#E69F00',
    'EgoAnchor': '#009E73',
}
ABLATION_COLOR = '#D55E00'
```

### 技术规范

- 低样本量禁用bar/violin，使用全部事件点+配对线
- 双栏图88mm，单栏180mm，最小字号7pt
- PDF使用嵌入字体和矢量元素
- 同时导出PNG供快速审查

### 验收标准

- 绘图器只打开plots/*.csv
- 修改plot CSV会改变图，修改XLSX或raw data不会被绘图器读取
- PDF字体和版面检查通过

### 提交信息

Task 10: 实现论文绘图

---

## Task 11：实现TeX中间产物发布

### 目标

只从paper/numbers.csv、paper/tables.csv生成四个TeX文件；不直接修改主稿。

### 创建文件

- publishing/latex.py: TeX生成器

### 输出文件

```
2026-EgoAnchor/generated/
├── exp1_numbers.tex
├── exp1_tables.tex
├── exp2_numbers.tex
└── exp2_tables.tex
```

### TeX命名规则

- 前缀: \EAExpOne / \EAExpTwo
- 变体名: 驼峰式（EgoAnchor, ArrivalHold）
- 指标名: 描述性（TranslationMedianMm）
- 分位数: 字母拼写（PNinetyFive 不用 P95）

### 示例输出

```latex
\newcommand{\EAExpOneSessionCount}{5}
\newcommand{\EAExpOneEgoAnchorDisplayCoveragePct}{98.5}
\newcommand{\EAExpOneEgoAnchorTranslationMedianMm}{12.3}
```

### 验收标准

- 宏和表格数字与CSV一致
- 没有手抄数值
- 控制序列不含阿拉伯数字

### 提交信息

Task 11: 实现TeX中间产物发布

## Task 12：实现主稿数据物化

### 目标

加入唯一的自动生成宏区块和表格区块；从Task 11的TeX中间产物替换区块内容；删除四个生成TeX的\IfFileExists/\input依赖；同步修订实验结果措辞和版面。

### 创建文件

- publishing/materialize.py: 主稿物化工具

### 修改文件

- 2026-EgoAnchor/egoanchor_cn_v6.tex

### 主稿区块标记

```latex
% EGOANCHOR-EXP-DATA:BEGIN
% 由egoanchor.eval发布工具生成，请勿手工修改本区块。
% 源: exp1_numbers.tex hash=abc123, 生成器版本=1.0.0
\newcommand{\EAExpOneSessionCount}{5}
...
% EGOANCHOR-EXP-DATA:END
```

### 关键操作

1. 删除主稿中的 \IfFileExists{generated/exp1_numbers.tex}{\input{...}}{}
2. 在导言区添加宏定义自动生成区块
3. 在实验章节添加表格自动生成区块
4. 从generated/*.tex读取内容，写入对应区块
5. 每个区块首行记录源hash和生成器版本

### 验收标准

- 区块外人工正文不变
- 重复物化得到零diff
- 临时移走generated/exp{1,2}_*.tex后主稿仍可编译
- 没有frame-level显著性表述

### 提交信息

Task 12: 实现主稿数据物化

---

## Task 13：端到端复现与审查

### 目标

从五个raw task重建五个完整XLSX、全部指标/绘图CSV、正式图、TeX中间产物和自包含主稿；使用Code Simplifier审查新代码；补使用文档。

### 端到端验证命令

```bash
cd EgoAnchor_Python

# 编译检查
pixi run python -m compileall src

# 单元测试
pixi run python -m unittest discover -s src -p "test_*.py" -t src

# Stage 1: 预处理
pixi run python -m egoanchor.eval.cli preprocess \
  data/eval/task_*_controller_right \
  --out data/analysis/complete

# Stage 2: 分析
pixi run python -m egoanchor.eval.cli analyze \
  data/analysis/complete/*.xlsx \
  --out data/analysis/results

# Stage 3: 发布
pixi run python -m egoanchor.eval.cli publish \
  data/analysis/results \
  --paper-root ../2026-EgoAnchor

# Stage 4: 物化
pixi run python -m egoanchor.eval.cli materialize-paper \
  data/analysis/results \
  --paper-root ../2026-EgoAnchor

# 论文编译
cd ../2026-EgoAnchor
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
```

### 可重现性检查

同一代码、配置和输入重复运行后，以下内容的hash必须一致：

- 事实sheet（除生成时间字段外）
- 指标CSV
- plot CSV
- TeX数字
- 主稿自动生成区块

### 使用Code Simplifier审查

审查新eval包代码，但不改变功能或架构，重点检查：

- 命名清晰度
- 中文文档字符串完整性
- 包级导入规范（不深层导入）
- 死代码和冗余逻辑

### 补充文档

创建 `EgoAnchor_Python/docs/analysis_pipeline.md`，说明：

- 四阶段数据流
- CLI使用示例
- 如何添加新指标
- 如何添加新图表
- 故障排查

### 验收标准

- 端到端命令执行成功
- 重复运行hash一致
- 所有单元测试通过
- Code Simplifier审查无重大问题
- 使用文档完整

### 提交信息

Task 13: 端到端复现与Code Simplifier审查

---

## 完成标准

完成全部13个Task后，应该达到：

1. ✅ 旧离线分析脚本和正式旧产物已删除，运行时schema writer与原始数据未受影响
2. ✅ 五个task各有一个完整、无截断、可回溯到源文件和源行的Stage 1 workbook
3. ✅ Stage 2输出完整的trial/event/session CSV、配对差值、VCD诊断、plot-ready data和lineage
4. ✅ Stage 2、Stage 3和Stage 4都无法绕过上一阶段读取更早的数据源
5. ✅ 正文只报告场景条件化指标，不跨场景总排名，不把frame当样本
6. ✅ 主文采用一张实验一汇总表、一张实验一三联图、一张实验二消融表和一张实验二双联图
7. ✅ 主稿不依赖四个生成.tex才能编译，宏与表格内容由受控自动生成区块承载
8. ✅ 所有workbook、CSV、PDF、PNG、TeX中间产物和主稿区块通过程序化回读、视觉检查、内容hash和论文编译验证

---

## GPT启动提示词

用户确认本计划后，在新的GPT会话中使用：

```
请先完整阅读仓库根目录 AGENTS.md 顶部用户手动维护要求，以及
2026-EgoAnchor/data_analysis_refactor_plan.md。

严格从 Task 0 开始实施，一次只完成一个 Task。每个 Task 开始前先检查 git status、
影响范围、引用关系和架构边界；先补测试，再改实现。验证通过后独立提交并推送，
然后报告变更、验证命令和下一 Task，不要跨 Task 提前实现。

原始 data/eval/task_* 目录只读，gpt-web-analysis 只作参考。不要恢复旧分析接口、
旧命令或兼容层，不要覆盖用户现有未提交改动。Stage 2 只能读取 Stage 1 XLSX，
Stage 3 只能读取 Stage 2 CSV，Stage 4 只能读取 Stage 3 TeX；任何 QC 失败都不得发布正式结果。
```

---

## 注意事项

1. **单向数据流严格执行**：每个阶段只能读取上一阶段的输出，禁止跨阶段回读
2. **统计单位明确**：event/segment是统计单位，不是frame；论文中必须明确说明
3. **不跨场景混池**：EgoAnchor的优势是场景条件化的，不计算全局总分
4. **QC失败即停止**：任何QC检查失败都不得生成论文产物
5. **可重现性**：同一输入和代码重复运行，事实数据hash必须一致
6. **审计追踪**：每个输出记录输入hash，保证完整lineage
7. **契约版本管理**：任何契约变更都需要递增版本号
8. **中文文档**：所有类、方法、参数都需要中文文档字符串
