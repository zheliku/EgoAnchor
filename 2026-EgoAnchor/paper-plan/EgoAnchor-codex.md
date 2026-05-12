论文定位

我会把论文核心问题定成一句话：

How can we turn asynchronous 6DoF object pose tracking into stable, world-consistent real-object anchoring in passthrough MR?

中文就是：

如何在异步感知、外部推理和头显持续运动条件下，把 6DoF 物体姿态跟踪变成稳定、世界一致的真实物体 MR 锚定？

这个问题比“怎么做 tracking”更像 IEEE VR。

推荐题目

我最建议这一版：

EgoAnchor: Frame-Aligned 6DoF Object Pose Tracking and Adaptive Anchor Control for World-Consistent Object Anchoring in Passthrough Mixed Reality

如果想更保守一点，可以先去掉 Adaptive：

EgoAnchor: Frame-Aligned 6DoF Object Pose Tracking for World-Consistent Object Anchoring in Passthrough Mixed Reality

我建议的论文贡献，最后收敛成 3 条就够

一种面向 passthrough MR 的 frame-aligned 真实物体锚定框架，把异步 6DoF pose tracking 映射为世界一致的 object anchoring。
一个 reliability- and motion-aware adaptive anchor controller，决定何时更新、平滑、保持或重连 anchor。
一个开放的端到端系统与系统性实验，覆盖精度、时延、鲁棒性和任务可用性。
论文大纲，我建议这样写

Introduction
问题、挑战、贡献。这里重点讲“usable anchor does not emerge from per-frame pose accuracy alone”。

Related Work
6DoF pose tracking、MR object anchoring、low-latency XR sensing、tracking recovery。

System Overview
Quest stereo capture -> Python perception -> pose return -> Unity world anchoring。

Method
frame_id 对齐、K remapping、2D segmentation、depth、register/track/re-register、adaptive anchor controller。

Adaptive Anchor Control
输入：motion level、reliability score
输出：Update / Smooth / Hold / Reacquire
这是你论文最该新加的一节。

Evaluation
精度、时延、鲁棒性、ablation、任务实验。

Discussion and Limitations
多物体、遮挡、材质、强反光、依赖外部 GPU 等。

Conclusion

之后的目标，我会分成“必须完成”和“加分项”

必须完成：

做出最小版 adaptive controller
搭建 ground-truth pose evaluation
做 4 组关键 ablation
no frame alignment vs frame alignment
always update vs adaptive controller
no recovery vs recovery
static vs head motion vs occlusion
把对象从单个 cube 扩到一组代表性物体
加分项：

一个小型任务实验
更系统的 latency breakdown
多对象或更复杂场景
如果只做一件最值的事

就是你自己也判断到的那条：

在现有系统上增加一个简洁的 confidence/motion-aware anchoring controller，并做强实验。

这件事收益最高，因为它能把你现在已有的工程优势，真正变成论文贡献。

如果你愿意，我下一步可以直接帮你写两样很具体的东西：

一个可以放进论文初稿里的 abstract + contributions + figure caption。
一个 adaptive controller 的最小设计草案，包括输入信号、状态机和消融方案。
参考：

IEEE VR 2026 CFP: https://ieeevr.org/2026/contribute/papers/
IEEE VR 2025 Papers Program: https://ieeevr.org/2025/program/papers/