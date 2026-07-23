# EgoAnchor 论文与实验路线

## 论文定位

EgoAnchor 研究如何把开放视觉后端输出的低频、异步、质量不均的相机系 6DoF 位姿，
转换为混合现实应用可持续使用的世界系对象锚点。平台能力和零样本感知只作为系统背景；
论文主线是 observation-to-anchor runtime。

## 主方法

完整 EgoAnchor 固定使用：

1. 基于 `frame_id` 的采集时刻世界对齐；
2. VCD 接纳；
3. 连续白噪声加速度 Kalman 状态估计；
4. 自适应历史目标时刻上的位置 Linear / 旋转 SLERP；
5. StaticLock；
6. 与重获取协同的生命周期管理。

实验二另比较两种关闭 StaticLock 的逐帧输出策略：

- `Smoothed KF Extrapolation`：有限 180 ms 外推，并以 60 ms 真实时间半衰期平滑
  Kalman 校正残差；
- `Hermite Interpolation`：在相同历史目标时间线上使用 Kalman 速度切线做 6DoF Hermite
  插值，不在最新控制点之后外推。

180/60 ms 与 Hermite 的 `1.15 / 0.25 / 3` 目前是 pilot 初值，正式 v4 采集前冻结。
两路策略共享采集时刻对齐、VCD、Kalman、生命周期、重获取、候选序列、渲染时间线和关闭
StaticLock 的配置，只改变输出策略。这个比较不改变完整 EgoAnchor 的主方法定义。

## 实验组织

### 实验一：端到端系统表征

比较 Arrival-Hold、Capture-Hold、One-Euro Anchor 和 EgoAnchor。五项任务覆盖静止头动、
起停 6DoF、持续平移、持续旋转和遮挡恢复。每个场景分别报告世界一致性、静止稳定性、
lag--fidelity、失效控制和转换代价，不汇总成全局排名。

### 实验二：系统设计归因与时序策略比较

三个单组件消融为：

- EgoAnchor w/o capture-time alignment；
- EgoAnchor w/o VCD；
- EgoAnchor w/o StaticLock。

图 3(d) 和对应表格比较 `Smoothed KF Extrapolation vs. Hermite Interpolation`。
除 lag--residual 外，还报告候选生效边界步长、静止帧间增量、起动响应、停止前向过冲、
反向回动、settling time、旋转误差和遮挡超限。候选生效边界步长按 `source_frame_id`
改变前后相邻 render pose 的差计算，只作为同一时间线上的配对显示护栏，不称为 Kalman
innovation。

Task 2 每轮使用成对 marker：拿起前记录 `transition_started`，完全停止后记录
`transition_stopped`。QC 要求两者严格交替闭合。

旧 v3 数据来自旧 Kalman 过程协方差和旧矩阵，只用于只读工程诊断。v4 必须在同一冻结代码
和参数下完整重采 Task 1--5，不得按场景拼接批次。

### 实验三：跨对象用户研究

实验三暂不采集。后续比较 One-Euro Interpolation 与完整 EgoAnchor，正式启动前需完成伦理、
样本量、对象与任务材料、排除规则和统计方案冻结。

## v4 启动条件

正式采集前完成一次不启动 recorder 的 Quest 功能 pilot：

- 72/90/120 Hz 下残差半衰期行为一致；
- 实际外推时域不超过配置上限；
- 平移和旋转起停无异常跳变、持续回动或非有限输出；
- Hermite 不在最新控制点之后外推；
- 遮挡恢复、VCD、生命周期与九路日志正常；
- 正式场景矩阵门禁和 EditMode 测试通过。

pilot 冻结参数后不再根据 v4 正式结果调参。

## 数据与论文交付

现有活动工作簿仍是 v3 归档证据，新的分析契约只接受
`variant_matrix_id=exp12_9_smoothed_hermite_v4`。五项 v4 session 完成并停止 Python 后，
依次运行：

```text
pixi run eval stage <5 session IDs>
pixi run eval promote <batch_id>
pixi run eval analyze
```

中文主稿是 `egoanchor_cn_v6.tex`，稳定 PDF 为 `pdf/EgoAnchor.pdf`。分析管线从五本 Stage 1
XLSX 回填实验一/二，不读取 raw JSON/JSONL。正文、图和表最多 9 页，实验三仍需预留空间。

## 诚实边界

- 控制器 pose 是同一 Quest 平台参考，不是外部光学真值。
- frame alignment 只修正采集/到达时刻错配，不补偿采集后的物体运动。
- 系统需要目标三维模型；“纯视觉”只修饰物体位姿估计链路。
- 单操作员、多 session 的帧不是独立样本，统计单位是 event 或 segment。
- 正式结论只描述当前对象、设备、参数和任务条件。
