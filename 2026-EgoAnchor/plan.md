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
3. Kalman 状态估计；
4. 自适应历史目标时刻上的位置 Linear 与旋转 SLERP；
5. StaticLock；
6. 与重获取协同的生命周期管理。

EgoAnchor Hermite 使用相同输入、Kalman、VCD、目标时刻、StaticLock 和生命周期，只替换
插值器。它保留为图 3(d) 的配对对照，不是正式主方法。

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

图 3(d) 另外保留 Predict-to-Now、Hermite 和 Linear/SLERP 的实际 runtime 对比。

实验一/二当前使用五项正式 task，经 schema-v2 QC、Stage 1 XLSX 和 paper_analysis 管线
生成论文数字。原始数据与复现步骤见 experiment_1_2_analysis_reproduction_manual_zh.md。

### 实验三：跨对象用户研究

实验三暂不采集。后续只比较 One-Euro Interpolation 与完整 EgoAnchor，考察真实物体上的
虚拟标签阅读和对象附着交互。正式启动前需完成：

1. 冻结目标对象、三维模型准备流程和任务材料；
2. 完成伦理审批、样本量与排除规则；
3. 通过跨对象功能试验确认两种方法都能稳定运行；
4. 冻结主客观指标、随机化与统计方案；
5. 为正文预留不超过约 0.6 页的结果空间。

## 当前交付边界

中文主稿是 egoanchor_cn_v6.tex。实验一/二图、表和正文由 build-paper 从五本 Stage 1
工作簿重建。图 2 为一行三个 LaTeX 子图，图 3 为一行四个 LaTeX 子图。正文、图和表不超过
9 页；实验三启动前不把计划性描述写成已完成证据。

## 诚实边界

- 控制器 pose 是同一 Quest 平台参考，不是外部光学真值。
- frame alignment 修正采集/到达时刻错配，不补偿采集后的物体运动。
- 系统需要目标三维模型，纯视觉只修饰物体位姿估计链路。
- 单操作员、多 session 的帧不是独立样本；统计单位是 event 或 segment。
- 当前结果只描述当前对象、设备、参数和任务条件，不能外推为跨对象结论。
