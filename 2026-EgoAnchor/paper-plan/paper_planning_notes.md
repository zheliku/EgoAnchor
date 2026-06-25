# EgoAnchor 论文写作规划与系统设计笔记

本文档只记录 IEEE VR 2027 投稿阶段的论文定位、实验设计和审稿风险。端到端技术流程、字段名、默认权重和公式细节以
[`../egoanchor_code_derived_technical_flow.md`](../egoanchor_code_derived_technical_flow.md)
为准。

## 当前定位

EgoAnchor 应写成 MR system paper，而不是单一 pose tracking 或单一滤波算法论文。核心问题是：

> 如何把低频、异步、带噪、会间歇失效的外部 6DoF 物体位姿流，转成头戴端高频、世界一致、稳定且可恢复的真实物体锚点？

论文叙事应突出完整系统，而不是把某个单点技术写成全部贡献。帧对齐、可靠性评分、时序输出、静止锁和重获取要作为一套协同架构来写。

## 建议贡献表述

1. 一个开放硬件上的端到端 MR real-object anchoring 系统：目标物体位姿链路只依赖双目视觉、物体 3D 模型和初始分割提示；参考相机世界位姿来自头戴端自身跟踪。
2. 面向异步外部感知的 frame-aligned anchoring：Python 只返回 camera-space object pose，Unity 按 `frame_id` 精确回查 capture-time camera pose 合成 world anchor。
3. 面向 anchor 质量的可靠性与输出策略：Python 多信号可靠性评分，Unity `MotionModel × SmoothingStrategy` 输出高频 pose，并在 EgoAnchor 方法中叠加 reliability-aware static lock。
4. 锚点中心的评估方法：用 world-space anchor error、jitter/slip、lag、latency、recovery success/time 评价 MR 使用质量，而不是只报告 CV pose accuracy。

写作时不要声称单个模块本身是全新算法。更稳妥的说法是：已知技术被组合到一个针对 passthrough MR 异步感知的系统中，并通过端到端实现和评估证明有效。

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

- [ ] 按代码事实文档更新方法章节公式和字段名。
- [ ] 完成至少一轮正式真机 session，并生成 report。
- [ ] 核对相关工作和平台能力的最新状态。
- [ ] 补齐正文引用，移除临时 `\nocite{*}`。
- [ ] 准备 supplementary video：frame-aligned vs arrival-time、static lock、遮挡/出视野恢复、baseline 对比。
