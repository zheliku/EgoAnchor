> 状态说明：本文档是早期讨论记录，保留用于追溯。当前主线以 `IEEEVR2027-paper-architecture.md` 和 `EgoAnchor-Evaluation-Plan.md` 为准；论文方法已从复杂 adaptive controller 收敛为 frame-aligned anchoring + reliability-gated One Euro controller，并要求同时对比 raw、low-pass、Kalman、vanilla One Euro 与改进 One Euro。下文关于较重 adaptive controller 的表述不再作为默认论文计划。

先给结论：
这个项目不应再包装成“VR pose tracking 工程”。  
更合适的定位是：
面向 Passthrough Mixed Reality 的低时延、世界一致的真实物体 6DoF 感知与锚定系统
- 技术内核用 pose / tracking
- VR/MR 论文叙事用 anchoring
- 场景表述尽量用 passthrough MR / mixed reality，不要只写 VR
因为你做的不是纯虚拟场景里的 tracking，而是真实物体在头显透视场景中的稳定对齐与附着。这在 IEEE VR 语境里，anchor 比单纯 pose 更“对口”，但不能只用 anchor，因为你的核心算法仍然是 6DoF object pose tracking。

一个会根据感知可靠性、运动状态和时延情况，自适应决定“是否更新 anchor、如何更新 anchor、何时重连”的 MR anchoring controller。

---
1. 在 VR/MR 论文里，pose / tracking / anchor 到底怎么区分
这三个词不是互斥的，而是三个层级。
词
含义
你的项目里对应什么
论文里怎么用
Pose
某一时刻物体的 6DoF 位姿
Python 估计出的 4x4 pose
方法和指标里用
Tracking
连续时间上的位姿估计与更新
register / track / re-register / Cutie
方法名、实验名里用
Anchor / Anchoring
把虚拟内容稳定附着到真实世界对象/位置
Unity 世界坐标下稳定显示物体相关内容
标题、引言、应用价值里用
最准确的说法
你的系统本质上是：
6DoF object pose tracking  
that enables  
world-consistent object anchoring in passthrough MR
这句话最适合做全文主线。
在 AR/MR/XR 里，anchor 通常指：
- spatial anchor：把虚拟内容固定在真实世界某个位置
- world anchor：强调与世界坐标稳定绑定
- object anchoring：把内容固定在某个真实物体上
你的项目虽然不是平台官方“Anchor API”本身，但你做的是：
- 估计真实物体 pose
- 把这个 pose 对齐到 Unity 世界
- 让虚拟内容稳定跟随真实物体
这完全可以叫：
- object anchoring
- world-consistent object anchoring
- pose-driven object anchoring
要注意一点：
- 不要把 anchor 当成底层估计算法名词
- 要把 anchor 当成 XR 结果和体验层名词
所以标题里最好同时出现：
- pose tracking 或 6DoF
- anchoring
- passthrough MR

---
2. 论文定位
推荐定位：一种面向头戴式透视 MR 的真实物体稳定锚定系统
核心问题不是“我估出了 pose”，而是：
1. 头显在动
2. 双目透视图在变
3. 推理在异步
4. 网络有延迟
5. 但虚拟内容仍然要稳定附着在真实物体上
这就是 IEEE VR 最容易买账的叙事。
3. 推荐的项目名和论文标题
推荐系统名：EgoAnchor
这是我最推荐的。
为什么好
- Ego：强调 egocentric / head-worn / first-person
- Anchor：强调 XR 里的稳定附着
- 比 “VR-Pose-Tracking” 强很多
- 比 “QuestPose” 更泛化，不被平台绑定
- 比 “PoseTracker” 更有论文感
适合的论文标题
EgoAnchor: Frame-Aligned 6DoF Object Pose Tracking for World-Consistent Object Anchoring in Passthrough Mixed Reality
这版我认为最平衡。
它同时覆盖了：
- Frame-aligned：你的关键技术点
- 6DoF Object Pose Tracking：CV/感知内核
- World-Consistent Object Anchoring：VR/MR 应用价值
- Passthrough Mixed Reality：准确场景

---
4. 贡献组合
Contribution 1
A frame-aligned and reliability-aware anchoring method that couples 6DoF object pose tracking with adaptive anchor update control under asynchronous perception.
中文：
一种帧对齐、可靠性感知的锚定方法，在异步感知条件下将 6DoF 物体姿态跟踪与自适应 anchor 更新控制耦合起来。
这条是你的方法贡献。
如果你把 adaptive controller 做出来，这条会明显变强。
Contribution 2
An open end-to-end system for world-consistent 6DoF real-object anchoring in passthrough MR, from head-worn stereo capture to Unity deployment.
中文：
一套开放的、端到端的透视式 MR 真实物体世界一致 6DoF 锚定系统，从头戴双目采集到 Unity 部署完整闭环。
这条解决“第一个做这个”的系统定位。

---
Contribution 
An open end-to-end system for world-consistent 6DoF real-object anchoring in passthrough MR, from head-worn stereo capture to Unity deployment.
中文：
一套开放的、端到端的透视式 MR 真实物体世界一致 6DoF 锚定系统，从头戴双目采集到 Unity 部署完整闭环。
这条解决“第一个做这个”的系统定位。

---
5. 论文定位
A usable MR anchor does not emerge from per-frame pose accuracy alone; it emerges from the joint compatibility of semantic localization, metric geometry, recoverable object pose tracking, and temporally aligned anchor application.
EgoAnchor studies how to turn 6DoF object pose tracking into usable real-object anchoring in passthrough MR through frame-aligned reprojection, adaptive anchor control, and perception-stack co-design.
推荐系统名：EgoAnchor
推荐标题：
EgoAnchor: Frame-Aligned 6DoF Object Pose Tracking and Adaptive Anchor Control for World-Consistent Object Anchoring in Passthrough Mixed Reality
这版最平衡。
一个“开放、端到端、面向 Passthrough MR 的 6DoF Real-Object Anchoring System”，外加一套“协同设计原则 + 自适应锚定控制策略”
EgoAnchor is the first open end-to-end system that performs world-consistent 6DoF real-object anchoring in passthrough MR from head-worn stereo input to Unity deployment.
这里有四个限定词，非常关键：
- open
- end-to-end
- world-consistent
- from head-worn stereo input to Unity deployment
这样“firstness”才更容易 defend。

6. 你真正能强调的技术性，不是“用了哪些模块”，而是“为什么这些模块能组成一个可用系统”
这是一个非常重要的升维。
不是：
- YOLOE26 很好
- FFS 很好
- FoundationPose 很好
而是：
在 Passthrough MR 的异步外部推理场景里，一个可用系统需要模块满足这些属性：
属性 1：语义可指向性
系统必须知道“要跟踪哪个物体”。
- YOLOE26 的价值不只是分割
- 而是它支持 prompt 驱动、低延迟、适合在线初始化
属性 2：度量几何性
系统必须给出真实尺度和深度几何，否则 Unity 世界锚定不稳。
- 这就是 stereo + FFS 的价值
- 不是“多一个 depth 模块”，而是“提供 metric 3D consistency”
属性 3：对象级姿态可恢复性
系统必须在丢失后重新建立物体姿态。
- 这就是 FoundationPose register/track 分离结构的价值
- 对 MR 来说，recoverability 比单帧精度更重要
属性 4：时间兼容性
系统必须适配：
- 外部推理
- 网络回传
- 头显持续运动
- 这就是 frame-aligned 和 adaptive anchoring 的价值

---
1. 所以模块组合能不能成为贡献？
最准确的答案：
“模块组合”本身不是贡献
“面向 Passthrough MR 约束的模块协同设计原则 + 实证验证”可以成为贡献
这是你后面写论文时最该坚持的表述。

第一优先级：定义论文核心问题
把问题改成：
如何在异步、外部推理、头显持续运动的条件下，实现稳定、可用的真实物体 MR anchoring？
而不是：
如何做实时 pose tracking？

---
第二优先级：实现一个最小可发表的 adaptive controller
最小版本就够：
输入
- motion level
- reliability score
输出模式
- Update
- Smooth
- Hold
- Reacquire
论文亮点
- “错误更新比短暂停住更糟”
- “静态/动态场景策略不同”
- “系统应根据可靠性决定 anchor 更新方式”

---
第三优先级：做关键实验
至少做这四组：
1.1 No frame alignment vs frame alignment
1.2 Always update vs adaptive controller
1.3 No recovery vs adaptive recovery
1.4 Static scene vs dynamic head motion vs occlusion
这四组足以让论文立起来。

---
第四优先级：做用户或任务实验
哪怕样本不大，也非常有帮助。
例如：
- 真实物体高亮/标签附着
- 头动时判断哪种系统更稳
- 完成简单对齐/指认任务

---
2. 现实上，哪条路线最值
如果你的目标是“提高论文质量和接收概率”，我建议的路线按收益/风险排序是：
路线 1：最推荐
在现有系统上增加一个简洁的 confidence/motion-aware anchoring controller，并做强实验。
收益高，风险可控。

---
