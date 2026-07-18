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
