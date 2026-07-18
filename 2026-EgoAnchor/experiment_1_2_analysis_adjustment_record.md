# 实验一/二离线分析计划调整记录

本文只记录执行过程中由项目事实触发、且会影响后续契约的路线调整。原始四阶段架构、Task 顺序和单向数据边界不变。

## 2026-07-18：Task 7 实验一分析

### 发现

1. 原 `scenario_summary` 只有一个样本数和中心值，无法区分没有发生指标尝试、尝试后成功、以及尝试后因未响应或未恢复而没有可定义数值三种情况。若直接过滤空值，会把失败事件静默排除并抬高结果。
2. Task 7 主指标清单不足以覆盖 `AGENTS.md` 已冻结的系统表征要求。实验一还需要旋转误差、峰值误差、unlock/relock、lag residual、遮挡期更新数和 fresh output 等诊断指标。
3. 直接由 event 汇总到 session 会让 marker 更多的 trial 获得更高权重；起停场景若把所有 marker 都当成转换起点，也会重复计算同一物理过程。

### 调整

1. CSV 契约升级为 breaking `csv-v2`。`scenario_summary` 记录 `attempt_count`、`sample_count`、`success_rate`、median、四分位数、IQR 和范围。指标未成功定义时保留尝试，数值字段写空。
2. 指标目录升级为 breaking `metrics-v3`，补齐实验一所需的旋转、峰值、unlock/relock、lag residual、遮挡期更新数和 fresh output 指标。
3. 汇总链固定为 event → trial → session。每一级只汇总直接下一级，trial 在 session 内等权。
4. 起停 6DoF 只使用 `transition_started` 作为分析事件，其他 marker 只提供相邻窗口边界。遮挡恢复仍按显式角色成对切窗，不根据场景名猜测事件语义。
5. Task 7 保持为纯计算层，只接收已类型化的 trial；工作簿加载、CSV lineage 和原子发布仍由 Task 9 实现。

### 边界影响

- Stage 2 仍只读取 Stage 1 XLSX；Task 7 代码不包含 JSON/JSONL、原始 task 路径或 `schema_v2` reader 依赖。
- 实验一仍只投影 Arrival-Hold、Capture-Hold、One-Euro Anchor 和 EgoAnchor，不混入实验二消融。
- 没有修改 `schema_v2/rows.py`、`schema_v2/writers.py` 或 `schema_v2/paths.py`。

## 2026-07-18：Task 10 CSV 图表发布

### 发现

1. 五个 plot CSV 的冻结主键不含 session/trial；多 session event_id 会碰撞，必须在 plot 行中使用稳定的 session/trial/event 复合键。
2. Stage 3 的 source CSV 必须限制在 `plots/`，并在发布前校验 catalog 行数、源 hash、数值列和 PDF/PNG lineage。

### 调整

1. 新增固定样式、实验一三图、实验二双图和 CSV-only 原子发布 API；空事件数据明确标注为 `No event rows`，不伪造统计值。
2. Stage 2 plot catalog 在所有 plot CSV 写出后回填对应实际 CSV SHA-256；Stage 2 写入后逐表回读契约表头和 hash。
3. `publish` CLI 输出到 `figures/generated`（可用 `--out` 覆盖），禁止输出目录位于 CSV 输入根内；发布 manifest 保留 catalog 与五个源 CSV hash。

### 边界影响

- Stage 3 不打开 XLSX、JSON 或 JSONL；图表只消费 Stage 2 CSV。
- 没有修改 `schema_v2/rows.py`、`schema_v2/writers.py` 或 `schema_v2/paths.py`。

## 2026-07-18：Task 11 TeX 中间产物发布

### 发现

1. 原 `paper/numbers.csv` 只有实验一场景指标，缺少计数和实验二宏；`paper/tables.csv` 只有实验二单列差值，无法生成四个完整 TeX。
2. paper 行的 `source_csv` 已指向 Stage 2 上游 CSV，但原 `source_sha256` 仍是 workbook hash；必须在 CSV writer 已写出上游文件后回填实际二进制 hash。
3. figures 与 TeX 分别替换会在第二侧失败时留下半套 Stage 3 产物，且相同/嵌套输出路径会互相覆盖。

### 调整

1. Stage 2 新增 paper 行投影：实验一固定五场景、每场景两个主指标、四系统矩阵；实验二四组件各保留主效应与 guardrail，并输出配对、VCD AURC 和适用场景 session 计数宏。
2. numbers 宏后缀在 Stage 2 固定为 ASCII 纯字母；Stage 3 保留 CSV 数字文本，转义 display-ready 表格，并对四个 TeX 做文件集合、内容和控制序列回读。
3. `publish` 先在两个 staging 目录完成五张图和四个 TeX，再联合替换正式目录；任一构建失败保留两侧旧产物，并拒绝 CSV 输入、图表输出和 TeX 输出之间的相同或祖先/子孙路径。

### 边界影响

- TeX 生成器只打开 `paper/numbers.csv` 和 `paper/tables.csv`；没有读取 plot CSV、XLSX、JSON 或 JSONL。
- Stage 2 paper 投影不重算 P95、median、IQR、配对差值或 AURC，只格式化已冻结科学结果。
- 没有修改 `schema_v2/rows.py`、`schema_v2/writers.py` 或 `schema_v2/paths.py`。
- 不改变 Task 8 的实验二配对和 VCD 风险覆盖职责，也不提前实现 Task 9 的文件发布。

### 验证依据

- 单元测试覆盖五场景、四系统投影、event-first P95、低样本范围、失败尝试保留、trial 等权 session 汇总和显式事件角色。
- 五个正式 Stage 1 工作簿的只读烟雾测试用于核对真实字段、窗口和汇总规模；该测试不访问原始 JSON/JSONL，也不写后续产物。

## 2026-07-18：Task 8 实验二分析与 VCD 诊断

### 发现

1. `paired_deltas` 原主键没有 component。静止头动同时用于 capture-time alignment 和 StaticLock，两个消融共享部分指标时会发生主键冲突。
2. 原 VCD 曲线和 AURC 表只能保存一个 risk 值，无法同时表示 mean/P95 和 VCD/random。risk point 也没有排除原因，不能审计无 aligned raw 或缺 reference 的候选。
3. `analysis_params-v2` 没有定义 coverage 分母、tie 相等规则、AURC 积分、随机参考和敏感性 cohort。把这些规则写死在函数里会破坏唯一参数入口。
4. 原组件表提到 HMD 速度条件效应和额外 lag，但现有指标目录没有公式，Task 7 类型也不含 head pose 序列。

### 调整

1. CSV 契约升级为 breaking `csv-v3`。配对主键加入 `component_id`，结果保存 `pair_status`，并增加 `paired_summary`。VCD risk point、曲线、AURC 和 sensitivity 表补齐审计列与稳定主键。
2. 指标目录升级为 breaking `metrics-v4`，冻结 VCD mean-risk AURC、P95 tail-risk 曲线和 cohort 敏感性。参数契约升级为 breaking `analysis_params-v3`。
3. 组件配对使用双边 exact join。缺行、重复行或 event 错配立即失败；两侧行都存在但数值未定义时保留尝试，delta 写空。差值始终是 `ablation - full`。
4. VCD 只取完整 EgoAnchor 且实际到达 Unity 的 admission，不根据 accepted/rejected 过滤。risk 使用 aligned raw 与同 session、同 frame reference 的平移距离。无 aligned raw、缺 reference、无效 reference 和非有限 pose 分原因排除；未到 Unity 的候选不生成 risk row。
5. tie 按解析后的有限浮点分数精确分组。mean-risk AURC 使用右连续经验阶梯积分，首个非零 coverage 区间从零起计。P95 使用 linear 分位数，只作为 tail-risk 曲线。
6. 随机参考使用无放回随机排序的有限总体精确期望。敏感性比较 completed-trial 主 cohort 与 marker-covered、occlusion-only 两个替代 cohort。
7. 没有公式和输入类型支持的 HMD 速度条件效应、额外 lag 不进入 Task 8；后续若需要，必须先升级前置工作簿和指标契约。

### 边界影响

- Task 8 是纯计算层，不打开 XLSX、JSON 或 JSONL。Task 9 负责从 Stage 1 XLSX 构造类型化 trial、variant 和 VCD candidate/reference 联接。
- 没有修改 `schema_v2/rows.py`、`schema_v2/writers.py` 或 `schema_v2/paths.py`。
- Task 9 只序列化 Task 8 已计算的 event、trial、paired、curve、AURC 和 sensitivity 结果，不重新切窗或计算科学指标。

### 正式工作簿核对

- 四组件结果包含 156 条 event 指标、31 条 trial 指标、31 条 session 指标、72 个 event 配对和 14 条配对汇总；所有冻结主指标都有有限配对。
- 遮挡 trial 有 787 个实际到达 Unity 的完整 EgoAnchor candidate。211 个因无 aligned raw 排除，2 个因缺同 frame reference 排除，coverage 分母为 574。
- 574 个 eligible candidate 形成 542 个精确分数 tie group。VCD mean-risk AURC 为 2.3843 mm，精确随机参考为 4.0806 mm；最终 coverage 为 1。

## 2026-07-18：Task 9 XLSX loader 与 CSV 发布

### 发现

1. 正式 render sheet 同时包含实验一四配置和实验二四消融；实验一 trial 类型必须保留完整八 runtime，以便后续实验二复用，但实验一指标投影只能选择四个冻结系统。
2. 同一 candidate 会被八个 runtime 各写一条 admission。科学层 VCD 只使用完整 EgoAnchor，common candidate 窄表的主键则要求每个 session/candidate 一行。
3. 实验二组件只适用于静止头动、遮挡恢复和起停 6DoF；连续平移/旋转 trial 必须保留在实验一批次而不能进入组件映射。

### 调整

1. loader 保留所有八条 render 序列和 admission 审计，`Exp1Trial` 只硬要求四个实验一配置存在；analyze 层通过 `EXP2_VARIANT_ORDER` 和组件场景投影消融。
2. `candidate_metrics.csv` 发布时按 `(session_id, candidate_id)` 去重并优先完整 EgoAnchor 行；`candidate_rows` 内存审计仍保留所有 runtime admission，VCD risk points 不受此窄表去重影响。
3. `analyze_exp2_components` 在完整五场景批次中仅投影组件定义声明的场景，连续平移/旋转只进入实验一结果。

### 边界影响

- Stage 2 loader 只打开完整 XLSX，按 `sheet_index` 读取物理分片，并在 typed trial/candidate 上保留输入 workbook SHA-256；没有 raw task 或 JSONL 路径依赖。
- CSV writer 固定写 UTF-8、空字段和小写布尔值，先在临时目录完成全部表与 lineage，再原子替换正式目录。
- 没有修改 `schema_v2/rows.py`、`schema_v2/writers.py` 或 `schema_v2/paths.py`。
