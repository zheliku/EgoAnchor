# EgoAnchor 论文写作规划与系统设计笔记

本文档只记录 IEEE VR 2027 投稿阶段的论文定位、实验设计和审稿风险。端到端技术流程、字段名、默认权重和公式细节以
[`../egoanchor_code_derived_technical_flow.md`](../egoanchor_code_derived_technical_flow.md)
为准。

## 当前定位

EgoAnchor 应写成开放消费级 MR system paper，而不是单一 pose tracking 或单一滤波算法论文。

核心信息（Core Message，全文围绕它展开）：

> EgoAnchor enables **open, deployable, and stable dynamic object anchoring** for everyday rigid objects in consumer MR.
> EgoAnchor 将开放视觉感知能力转换为消费级混合现实中可直接使用的动态真实物体锚定能力。

叙事三维度（摘要/引言/讨论/结论始终围绕这三条，**不要再罗列"五个特点"或"首个填补五维空白矩阵"**）：

1. **开放且易部署（Open & Deployable）**：仅依赖头显双目图像 + 物体三维模型，无需物理标签、专用深度硬件或逐物体离线训练。
2. **面向日常物体（General-purpose）**：支持任意日常刚性物体，而非预定义类别——这是"免逐物体训练"的直接结果，写成因果链，不要硬凑并列。
3. **稳定动态锚定（Stable Dynamic Anchoring）**：把异步视觉位姿持续维护为世界一致、可恢复的对象锚点，而不仅是输出位姿。

支撑该信息的核心研究问题（落在维度 3 里，是技术主体）：

> 如何把低频、异步、带噪、会间歇失效的相机系 6DoF 物体位姿流，转成头戴端高频、世界一致、稳定且可恢复的真实物体锚点？

写作分工：三维度是 value-proposition 主线骨架；技术 novelty（frame-aligned anchoring、reliability-aware static lock、anchor-centric evaluation）全部落在维度 3，是研究贡献主体。维度 1、2 扛"可达性/通用性"故事。架构上对象感知（Visual Perception Backend）与对象锚定（Object Anchoring Runtime）解耦呈现；旧"四层协同架构"降级为 Runtime 内部结构（时间对齐 / 质量门控 / 时序稳定 / 生命周期），不再当论文顶层骨架。不要把任一单模块写成全新算法；稳妥说法是：已知视觉能力被组织成针对开放消费级 MR 异步感知的系统，并经端到端实现与评估验证有效。

## 建议贡献表述

1. **系统（对应核心信息整体）**：提出 EgoAnchor，面向开放消费级 MR 的动态真实物体锚定系统，仅依赖头显双目图像与物体三维模型，即可对任意日常刚性物体实现连续 6DoF 动态锚定（覆盖维度 1、2；目标物体位姿链路纯视觉，参考相机世界位姿来自头戴端自身跟踪）。
2. **Visual Perception Backend（维度 1、2 的能力来源）**：把目标发现、目标分割、双目重建与零样本 6DoF 位姿估计组织为统一的异步感知流水线，持续产出 camera-space 异步位姿观测；后端可随开放视觉基础模型升级而无需改动运行时。
3. **Object Anchoring Runtime（维度 3，技术主体）**：通过 frame-aligned anchoring（按 `frame_id` 精确回查 capture-time camera pose 合成 world anchor）、可靠性门控、`MotionModel × SmoothingStrategy` 高频时序稳定与 reliability-aware static lock、生命周期管理，将异步位姿流转换为世界一致、稳定且可恢复的对象锚点。
4. **锚点中心的评估方法**：用 world-space anchor error、jitter/slip、lag、latency、recovery success/time 评价 MR 使用质量，而不是只报告 CV 单帧 pose accuracy。

## Baseline 与消融

系统级对齐对比：

- `arrival_time_raw`：到达/渲染时刻 latest camera pose 对照，只用于证明 frame alignment 的必要性。
- `frame_aligned_raw`：按 `frame_id` 回查 capture-time pose，但不做高阶策略。
- `egoanchor`：完整方法。

时序输出对比：

- `raw`：`ConstantVelocityModel + RawPassthroughStrategy`，零阶保持。
- `kalman_blend`：`KalmanModel + BlendStrategy`。
- `oneeuro_blend`：`OneEuroModel + BlendStrategy`。
- `kalman_interp`：`KalmanModel + DelayedInterpStrategy`。

方法消融：

- 关闭 static lock：评估静态 jitter 与锁定机制贡献。
- 关闭 score gate / low-score reacquire：评估坏观测和恢复链路贡献。
- 固定同一 baseline，只开关 `EgoAnchorStaticLockModule`，这是 static lock 最干净的消融。

## 实验条件

最低实验闭环：

1. Quest 真机 + Python real pipeline + Unity anchor runtime 连续运行。
2. 覆盖 `static`、`slow_head`、`fast_head`、`object_motion`、`occlusion`、`out_of_view`、`lighting`。
3. 至少 3 个代表性刚体物体；其中 Quest controller 可作为带 SDK GT 的高可信评估目标。
4. 对每个正式 session 记录 Unity capture/output、Python runtime log 和 manifest。

主指标：

- world-space translation / rotation anchor error。
- static jitter。
- head-motion-induced slip。
- lag / latency。
- recovery success/time。

辅助指标：

- Python reliability 分布、颜色重投影有效率、深度对齐分布。
- 推理耗时和端到端 capture-to-apply 延迟。

## 写作注意

- 三维主线（open / deployable / general-purpose / stable）是 value proposition，不是能力勾选表。不要回退到"五维能力矩阵 + 首个全 ✓"的写法——那种断言会被任一次平台 SDK 更新击穿，也容易被指 cherry-pick。需要对照时，写成沿三维度的 design-space 取舍讨论。
- “open / deployable”范围必须收窄：指无需物理标签、专用深度硬件、逐物体离线训练；**不等于头显端独立运行**。当前感知跑在外部消费级 GPU（5080 ~5fps / 5090 ~12fps）并经 ZMQ/NATS 异步通信，limitations 必须保留"外部算力依赖"，不要让读者误读成"Quest 即插即用"。
- “纯视觉”只修饰目标物体位姿估计链路。不要写成整个系统完全不依赖头显 SLAM、IMU 或平台追踪。
- Python 不输出 world pose；world anchor 只在 Unity 端通过 `frame_id` 回查得到。
- arrival-time mapping 是诊断对照，不是正式路径。
- static lock 是 regime-switching 稳定器，不是普通低通滤波。
- 当前代码没有 `score_jump` 子分，也没有旧 Gate/Estimator/Output 三模块结构。
- 当前 JSONL 输出字段是 `has_output_pose/output_pos/output_rot`，静止锁状态字段是 `latest_static_locked`；report 里的 `stable_rows` 只是统计名。

## 审稿风险

- 与平台能力的对比必须投稿前重新联网核实。不要依赖旧说法，例如“平台完全不支持动态物体”这类容易被新 SDK 击穿的断言。
- 与 Vision Pro / Meta / Vuforia / Azure 等系统对比时，优先做能力维度和系统假设对比；跨设备定量比较只能谨慎呈现。
- 如果使用 controller SDK pose 作为 GT，要说明它与头显共享追踪系，只能隔离视觉 pose-to-anchor 栈，不能暴露头显 SLAM 的共模误差。
- 过滤器对比最好给 Pareto 或多参数扫描，不要用单点结果宣称“优于 One Euro / Kalman”。
- 用户实验需要事先明确任务、样本量依据、主观量表和统计检验方式。

## 投稿前清单

- [ ] 把正文从"四层协同架构 / 五维能力空白"骨架收口到三维主线：旧四层降级为 Object Anchoring Runtime 内部结构，旧五维矩阵改写成沿三维度的 design-space 对照（v3.tex 的系统设计、相关工作、讨论、结论章节待改）。
- [ ] 按代码事实文档更新方法章节公式和字段名。
- [ ] 完成至少一轮正式真机 session，并生成 report。
- [ ] 核对相关工作和平台能力的最新状态。
- [ ] 补齐正文引用，移除临时 `\nocite{*}`。
- [ ] 准备 supplementary video：frame-aligned vs arrival-time、static lock、遮挡/出视野恢复、baseline 对比。
