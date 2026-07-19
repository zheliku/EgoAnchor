# 实验一/二论文呈现指南

本文档是当前系统论文的结果呈现约束。它回答三件事：主文保留哪些指标，图表承担什么叙事，结果段落如何在不夸大证据的前提下解释系统行为。完整 event/trial/session 数字仍以 Stage 2 CSV 和两个审阅 XLSX 为准；主稿数字由 `materialize-paper` 自动写入，不能手工抄录。

## 论文定位

EgoAnchor 的评价对象是“可被 MR 应用持续消费的对象锚点”，不是单独的 VCD 分数、FoundationPose 位姿或滤波器。主线按三层证据组织：

1. 实验一回答完整系统在头动、起停、持续运动和遮挡下表现成什么样。
2. 实验二回答哪些运行时机制解释这些应用侧行为。
3. 实验三（尚未采集）回答锚点质量是否转化为对象附着型 MR 任务收益。

实验一和实验二使用同一 Quest、同一视觉候选流、同一渲染时间线和同一平台参考。平台控制器 pose 是配对参考，不是外部光学真值。

## 实验一主表

主表使用行为属性行，不按原始日志字段堆叠指标。每个单元格是 event/segment-level `median [Q1, Q3]`，括号内的 `n` 是事件或片段数；五个场景分开报告。

| 行 | 场景 | 主指标 | 解释边界 |
|---|---|---|---|
| 世界一致性 | 静止头动 | 平移误差 event-P95 | 说明头动是否写入静止锚点；不是外部真值精度 |
| 静止稳定性 | 静止头动 | 位置 HP-RMS | 说明静止输出抖动；冻结错误位姿仍可能有低 jitter |
| 起停转换 | 起停 6DoF | 可见响应时间 | 报告运动开始的响应代价；停止后 jitter/沉降放在正文或补充 |
| 平移保真度 | 持续平移 | lag 补偿平移 P95 | 与 effective lag 成对解释，不把 raw error 单独称为精度 |
| 旋转保真度 | 持续旋转 | lag 补偿角 P95 | 当前为限制项，不能用平移结果替代 |
| 失效约束 | 遮挡恢复 | 遮挡窗平移 P95 | 与 output coverage 和重新可见后的误差一起解释 |

不把跨场景平均、全局排名、帧级显著性或“5 个独立 trial”写入主文。当前数据是五个场景各一条长 trial，事件是同一时间线内的配对观察。

## 实验一主图

`exp1_behavior_overview` 采用四面板，每个面板回答一个不同的系统问题：

- A：头动速度与显示误差时间线，解释 arrival-time world composition 的误差泄漏。
- B：起停参考和四系统显示轨迹，解释响应、停止和重新稳定的过程。
- C：effective lag--lag-compensated residual 散点，解释延迟换轨迹保真的权衡；低时延和低残差同时更好。
- D：遮挡前后误差和 output unavailable 标记，解释系统是如何限制有害更新的。

图中的代表轨迹只用于说明行为，所有定量结论来自全部 event/segment。不要在图中加入所有内部状态、所有指标或八个 runtime。

## 实验二主表

实验二每个组件只在其冻结适用场景内配对完整 EgoAnchor 与对应消融。差值固定为 `Ablated - Full`；正值表示消融后的误差或代价更大，具体方向仍以指标定义为准。

| 组件 | 场景 | 主指标 | 护栏 |
|---|---|---|---|
| Capture-time alignment | 静止头动 | 平移 event-P95 | 旋转 event-P95 |
| VCD admission | 遮挡恢复 | 遮挡窗平移 P95 | output coverage、实际接纳 eligible 工作点 |
| Temporal synthesis | 起停 6DoF | motion hold ratio | 运动窗平移 P95、停止后 jitter、visible response |
| StaticLock | 静止头动 | 位置 HP-RMS | 绝对平移误差 |

`motion_hold_ratio` 是比例，Full/Ablated 水平按百分比显示，二者差值按百分点 `pp` 显示。它衡量参考运动窗口内连续有效 render pair 是否近似保持不变，直接对应低频候选流是否退化为零阶保持。跳变 P95/P99 仍保留在 CSV/XLSX，用于审计和补充材料，但不作为时序合成唯一主证据。

## 实验二主图

`exp2_mechanism_attribution` 使用四个独立单位的小面板。灰线连接同一 event 的 Full/Ablated 值，面板内显示 Stage 2 已计算的差值中位数；不得把不同单位重新放到同一纵轴。VCD 面板右侧保留 candidate-level P95 tail-risk 曲线，并以星标表示日志中实际 `admission_decision=accepted` 的 eligible 子集。

这个星标是 operating point 描述，不是运行时数值阈值。正式日志没有保存可重建的数值阈值时，不能从接纳样本的最低 VCD 分数反推阈值。

## 结果段落模板

每个结果段落按同一顺序写：先回答系统问题，再给主结果，随后解释机制，最后说明代价和证据范围。

### 世界一致性与静止稳定性

先报告 Arrival-Hold、Capture-Hold、One-Euro Anchor 与 EgoAnchor 的静止头动平移 P95，再用 HP-RMS 说明静止输出是否稳定。明确 Capture-time alignment 解决的是采集时刻与到达时刻的世界复合错配，StaticLock 解决的是静止输出抖动；不要把 HP-RMS 写成物理精度。

### 动态平移与旋转

同时报告 effective lag 和 lag-compensated residual。推荐句式是“系统以更高/更低的拟合时延换取更低/更高的时间对齐后残差”，而不是只比较 raw zero-lag error。旋转只有少量 event 时，直接报告当前限制，不写成普遍动态优势。

### 遮挡与恢复

把遮挡窗误差、output coverage 和重新可见后的误差放在同一逻辑中。若 EgoAnchor 通过暂时不输出而限制有害更新，应明确这是 failure containment 的取舍，不声称覆盖率更高。

### 组件归因

先说明完整系统和消融共享同一 event，再报告 paired median [IQR] 与正/零/负方向计数。对时序合成，优先解释 hold ratio 以及运动误差护栏；对 VCD，同时说明完整系统误差、消融误差和实际接纳候选的 risk--coverage 位置。

## 统计与措辞边界

- event 内先计算指标，再做 trial/session 汇总；不把 render frame 当作样本。
- 当前每个场景只有一条长 trial，结果是受控系统表征和配对机制证据，不支持跨操作者、跨环境泛化结论。
- 可以报告 median [IQR]、paired delta、方向计数和完整配对点；不要写 `statistically significant`、`proves robustness` 或 `generalizes`。
- 任何 bootstrap 若未来加入，只能描述这组事件序列的变异性，不能当作独立 session 的置信区间。
- `capture-time alignment` 只校正历史观测与相机世界复合的时间语义，不能补偿采集之后的物体运动。
- 视觉推理耗时、candidate arrival、candidate update interval、capture-to-display observation age 和初始化耗时必须分开命名，不能用一个“端到端延迟”数字混合它们。

## 篇幅和补充材料

正文保留一张实验一系统行为图、一张实验二机制图、两张紧凑主表。完整 event 点、raw dynamic error、P99 jump、状态占用、observation age、VCD sensitivity 和审计 lineage 放在 CSV/XLSX 或补充材料。实验三用户研究开始后，再为任务表现和体验结果预留约 1.25--1.5 页。

## 发布前检查

1. `paper/numbers.csv` 与 `paper/tables.csv` 的每个主稿数字都有直接 Stage 2 source CSV 和 SHA-256。
2. 主稿只加载 `figures/generated/` 下的正式 PDF，不使用 `figs/` 或生成 TeX 的 `\input`。
3. 表格的指标、单位和样本数与当前冻结 `analysis_params.toml` 一致。
4. 主稿结果段没有把平台参考称为外部真值，没有把单 session 事件称为独立重复。
5. 重新运行 `materialize-paper` 和 XeLaTeX 后，页数、图例、表格和受控区块均通过视觉检查。
