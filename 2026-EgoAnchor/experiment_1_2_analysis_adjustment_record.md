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
