# EgoAnchor 论文与实验路线

## 论文定位

EgoAnchor 是动态真实物体锚定系统。中心问题不是如何再次估计 6DoF pose，而是如何把开放
视觉后端输出的低频、异步、质量不均的相机系位姿，转换为混合现实应用可持续使用的世界系
对象锚点。

论文只把平台能力和零样本感知作为系统背景。主要贡献是采集时刻世界对齐、统一候选接纳、
逐帧时序合成、静止锚定和生命周期管理组成的 observation-to-anchor runtime。

## 当前方法

正式 EgoAnchor 使用：

1. 基于 frame_id 的采集时刻世界对齐；
2. VCD admission；
3. 使用连续白噪声加速度过程模型的 Kalman 状态估计；
4. 自适应历史目标时刻上的位置 Linear 与旋转 SLERP；
5. StaticLock；
6. 与重获取协同的生命周期管理。

第九路配置改为 EgoAnchor Causal Prediction。它与 `w/o StaticLock` 共享采集时刻对齐、
VCD、Kalman、生命周期和关闭 StaticLock 的设置，只将 Linear/SLERP 历史合成替换为
有限时域因果预测。该策略预测到当前渲染时刻，但将外推限制在最新观测之后的冻结时域内；
新观测校正造成的显示残差按真实时间半衰期衰减，以免候选到达时直接跳到新的 Kalman
轨迹。它不使用未来观测，也不属于四个单组件消融。

原 EgoAnchor Hermite 不再进入新矩阵。正式主方法仍是 Kalman + Linear/SLERP +
StaticLock；`w/o temporal synthesis` 仍是 Kalman + Predict-to-Now，不用 Causal Prediction
替代。

## 实验组织

### 实验一：端到端系统表征

比较 Arrival-Hold、Capture-Hold、One-Euro Anchor 和 EgoAnchor。五项物理任务分别覆盖
静止头动、起停 6DoF、持续平移、持续旋转和遮挡恢复。报告世界一致性、静止稳定性、
lag--fidelity、失效控制和转换代价，不跨场景汇总成单一总分。

### 实验二：系统设计归因

在同一候选流、参考轨迹和渲染时间线上关闭单一组件：

- w/o capture-time alignment；
- w/o VCD；
- w/o temporal synthesis，即 Kalman Predict-to-Now；
- w/o StaticLock。

图 3(d) 比较 Direct Predict-to-Now、Causal Prediction 和 Buffered Linear/SLERP。
其中完整 EgoAnchor 与 `w/o temporal synthesis` 用于回答关闭历史时序合成的影响；
Causal Prediction 与 `w/o StaticLock` 都关闭 StaticLock，只改变逐帧输出策略，是严格的
因果预测与缓冲合成配对比较。Direct 条件保留 StaticLock，因此三路图不能被解释为单一因素
的三水平实验。

Causal Prediction 的预测上限、校正残差半衰期和异常重置规则先通过工程 pilot 冻结。
pilot 必须覆盖 72/90/120 Hz、平移与旋转起停、静止头动和遮挡恢复，并报告校正边界跳变、
停止前向过冲、反向回动、settling time、静止帧间增量及遮挡超限。网页回放只用于选择
初始搜索范围，不进入正式结果。

候选生效边界步长按 `source_frame_id` 改变前后相邻 render pose 的差计算。它包含相邻渲染帧
之间的真实运动，只作为 Causal 与 Buffered 的配对显示护栏，不称为 Kalman innovation。

Task 2 的每轮动作使用成对 marker：拿起前记录 `transition_started`，物体完全停止后记录
`transition_stopped`。QC 要求两者严格交替并闭合，分析只在明确的开始和停止边界上计算
起动响应、停止过冲、反向回动与 settling time。

现有五项正式 task 与 Stage 1 XLSX 属于 v3 归档批次，其中 Kalman 过程协方差仍使用旧实现，
旧第九路为 Hermite。
这些数据可用于只读工程诊断，但不能证明修正后的运行时效果。当前 CWNA 模型和参数完成验证后，
实验一/二必须完整重采五项任务，再经 schema-v2 QC、Stage 1 XLSX 和 paper_analysis 管线替换
正式论文数字。不得按场景混用 v3 与新批次。原始数据与复现步骤见
experiment_1_2_analysis_reproduction_manual_zh.md。

### 实验三：跨对象用户研究

实验三暂不采集。后续只比较 One-Euro Interpolation 与完整 EgoAnchor，考察真实物体上的
虚拟标签阅读和对象附着交互。正式启动前需完成：

1. 冻结目标对象、三维模型准备流程和任务材料；
2. 完成伦理审批、样本量与排除规则；
3. 通过跨对象功能试验确认两种方法都能稳定运行；
4. 冻结主客观指标、随机化与统计方案；
5. 为正文预留不超过约 0.6 页的结果空间。

## 当前交付边界

当前版本化中文主稿是 egoanchor_cn_v6.tex，稳定交付文件是 pdf/EgoAnchor.pdf。磁盘上的既有
分析产物属于 v3 归档批次；主稿中的实验数值和面板暂以 v4 待自动回填标记代替，不能解释为
当前运行时结果。新批次通过 `pixi run eval analyze` 从五本 Stage 1 工作簿完整重建。图 2 为
一行三个 LaTeX 子图，图 3 为一行四个 LaTeX 子图。正文、图和表不超过 9 页；实验三启动前
不把计划性描述写成已完成证据。

## 诚实边界

- 控制器 pose 是同一 Quest 平台参考，不是外部光学真值。
- frame alignment 修正采集/到达时刻错配，不补偿采集后的物体运动。
- 系统需要目标三维模型，纯视觉只修饰物体位姿估计链路。
- 单操作员、多 session 的帧不是独立样本；统计单位是 event 或 segment。
- 当前结果只描述当前对象、设备、参数和任务条件，不能外推为跨对象结论。
