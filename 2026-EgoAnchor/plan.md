是的，**EgoAnchor 完全可以写成系统论文**。但我需要修正上一轮建议中的一个倾向：如果把整篇论文主要组织成“VCD 评分是否有效”和“StaticLock 是否优于若干滤波器”，论文会逐渐变成一篇**位姿可靠性与时序滤波方法论文**，而不是你想要的 **MR system paper**。

看完你给的两篇论文后，我认为 EgoAnchor 应更接近 **VRGaussianAvatar 的技术系统路线**，同时吸收 **SelfBlending 的用户任务评估方式**。

---

# 一、这两篇论文为什么属于系统论文？

## 1. SelfBlending：交互系统型论文

SelfBlending 的主要贡献不是一个新的目标检测算法。它使用手部追踪、物体标注、YOLO 检测、视频混合等已有组件，构建了一个完整的“注册物体—识别物体—选择性透视—真实交互”框架。

它的贡献写成：

1. 一种通过手势注册真实物体的方法；
2. 一种根据用户意图选择性显示真实物体的 contextual blending interface。

其核心评价也不是“YOLO 精度是否超过另一个网络”，而是比较三种**完整交互条件**：

* 摘下头显；
* 默认全局透视；
* SelfBlending 的条件式透视。

随后用用户研究回答存在感、工作负荷、交互时间、跨现实连续性和偏好等问题。

甚至论文明确说明：

> 该实验并不评估系统配置过程本身，而是评估 SelfBlending 框架在用户沉浸于 VR 时支持真实物体交互的有效性。

也就是说，它把整个系统提供的**交互能力**作为实验对象，而不是把内部算法逐个拿出来竞争。

这是一种典型的：

> **Application / Interaction System Paper**

---

## 2. VRGaussianAvatar：技术系统型论文

VRGaussianAvatar 更接近你的情况。它同样大量使用现有模块：

* 现成的单图像 Gaussian Avatar 重建模型；
* 现成的 IK solver；
* 商用 HMD 的头手追踪。

但它构建了一个完整的：

> VR Frontend → 姿态与双目参数传输 → GA Backend → 立体 3DGS 渲染

系统，并提出一个系统关键技术 **Binocular Batching**。

作者非常明确地说，系统建立在 off-the-shelf IK 和现有单图像重建模型上，主要贡献是：

* VR 流式集成系统；
* Binocular Batching；
* 定量评估与 VR 感知用户研究。

它的评价也分成两层：

### 系统与技术层

* 图像/视频 mesh avatar 与 Gaussian avatar 的视觉质量比较；
* 有无 Binocular Batching 的消融；
* 不同分辨率下的渲染时间和 FPS；
* 重建时间和运行配置。

例如它直接报告了双目批处理前后的渲染时间和 FPS，而不是只讨论理论复杂度。

### 用户层

它把最终完整头像系统与两种功能相近的 mesh avatar 系统比较，评估外观相似度、具身感和 plausibility。

这是一种典型的：

> **Technical System Paper**

EgoAnchor 与它非常相似：

| VRGaussianAvatar                     | EgoAnchor                                            |
| ------------------------------------ | ---------------------------------------------------- |
| 使用现成重建模型和 IK                | 使用现成分割、立体深度与 FoundationPose              |
| 构建 VR Frontend + GA Backend        | 构建视觉后端 + Object Anchoring Runtime              |
| 解决 3DGS 无法直接进入 VR 的系统障碍 | 解决异步 6DoF pose 无法直接成为 MR anchor 的系统障碍 |
| Binocular Batching                   | Capture-time alignment、VCD、regime-aware anchoring  |
| 系统性能 + 用户研究                  | 锚定性能 + 用户任务研究                              |

所以你的工作**不是简单的 CV 模型接入 Unity**。只要论证得当，它就是一个很清楚的 MR technical system。

---

# 二、当前计划为什么让你感觉“不像系统论文”？

你右侧计划目前把论文集中到：

* RQ1：VCD 是否是好的可靠性分数；
* RQ2：ZOH、One Euro、NoLock、Full 如何比较；
* RQ3：多对象覆盖。

其中 RQ1 大量使用 risk–coverage、AURC、matched coverage；RQ2 又像一篇滤波器比较论文。计划中的系统图和运行时仍然存在，但**评价单元变成了 VCD 与 StaticLock 两个算法模块**。

这样容易给审稿人留下三个印象：

1. 视觉管线只是若干现有模型的拼接；
2. 主要创新是一个 hand-crafted score 和一个状态机；
3. 论文在证明内部模块，而没有充分证明“EgoAnchor 作为一个系统到底提供了什么新能力”。

这并不代表这些实验不该做，而是它们应该从“顶层 RQ”降为：

> **系统设计的 component analysis / ablation。**

换句话说：

* VCD 不是整篇论文的研究主题；
* StaticLock 也不是整篇论文的研究主题；
* **动态真实物体锚定系统**才是研究主题。

---

# 三、EgoAnchor 应该采用什么系统论文定位？

我建议将中心论点改成：

> **EgoAnchor is an end-to-end system that turns delayed and intermittent visual pose observations into persistent, world-consistent, and application-ready dynamic object anchors on consumer mixed-reality devices.**

中文可以写成：

> EgoAnchor 是一套端到端动态真实物体锚定系统，它将低频、异步、质量不均的视觉位姿观测，转换为消费级混合现实应用可持续使用的世界系对象锚点。

关键词是：

* end-to-end system；
* application-ready anchor；
* consumer MR；
* model-available everyday objects；
* no marker、no per-object training、no dedicated tracking hardware。

而不是把标题和摘要中心放在：

* reliability score；
* regime-aware filter；
* risk–coverage。

这些是系统的关键设计，但不是系统存在的最终目的。

---

# 四、系统论文应该证明什么？

我建议把证据分成三层。

## 第一层：系统能力

这是论文最重要的一层：

> EgoAnchor 是否真正实现了对多类真实物体的动态、连续、世界一致和可恢复锚定？

这里不需要先讨论 VCD，也不需要先讨论哪个滤波器好。

应该直接评价完整系统在以下条件下的表现：

* 静止物体、头部运动；
* 物体平移和旋转；
* 起动与停止；
* 部分遮挡；
* 追踪丢失和重新出现；
* 不同尺寸、纹理、几何和对称性的物体。

核心指标：

* translation / rotation error；
* static jitter；
* response latency；
* output availability；
* tracking loss rate；
* recovery success rate 和 recovery time；
* end-to-end latency；
* perception FPS 与 render FPS。

这相当于 VRGaussianAvatar 先证明自己的系统能达到交互式运行、能在 VR 中提供高质量头像。

## 第二层：为什么系统有效

这一层才放 component analysis：

* Capture-time vs arrival-time alignment；
* VCD vs no gate / visibility / depth-only；
* Full vs NoLock；
* EgoAnchor temporal runtime vs One Euro；
* 有无延迟插值；
* 有无 StaticLock。

目标不是分别把 VCD 和 StaticLock包装成两篇独立算法，而是回答：

> EgoAnchor 的关键设计各自对最终锚点质量贡献了什么？

这相当于 VRGaussianAvatar 的 Binocular Batching 消融：它并没有把整篇论文写成“批处理算法论文”，而是证明这个设计让系统能够达到实时双目 VR 渲染。

## 第三层：系统是否对 MR 应用有意义

这是用户实验承担的角色：

> 相较于直接消费视觉位姿的常规实现，EgoAnchor 是否改善了真实 MR 任务中的操作表现和虚实附着体验？

这一层非常适合你原本打算做的用户实验。

---

# 五、我建议的最终论文结构

## 1. Introduction

1. MR 应用需要附着在可移动真实物体上的内容；
2. 现有平台、marker、专用 tracker 和视觉 pose estimator 的限制；
3. 视觉 pose stream 不能直接作为 application-ready anchor；
4. EgoAnchor 的端到端系统与关键设计；
5. 系统贡献和评价概览。

这里不要把三个“语义缺口”写得过于抽象。它们可以作为设计动机，但引言必须尽快让审稿人看见：

> 你做出了什么完整系统、它可以做什么、现有方案为什么做不到。

## 2. Related Work

* Dynamic object tracking and anchoring in XR
* Model-based and zero-shot 6DoF perception
* Temporal stabilization and pose reliability
* Platform-level object tracking

平台表可以保留，但不要占太多空间。

## 3. Design Goals and System Overview

这一节非常重要，也是当前计划缺少“系统味”的地方。

明确四个设计目标：

* **Extensibility**：给定三维模型即可添加物体，无需逐物体训练；
* **World consistency**：用户头动不能破坏静止对象的世界关系；
* **Continuous anchoring**：低频观测之间仍有逐帧锚点；
* **Robust lifecycle**：坏观测、遮挡和重获取不应造成无控制跳变。

随后展示完整系统架构和数据流。

## 4. EgoAnchor System

### 4.1 Egocentric perception backend

说明模块组合、输入输出和为什么需要双目米制深度。不要声称 YOLOE、FoundationStereo 或 FoundationPose 是你的算法贡献。

### 4.2 Asynchronous observation transport

* frame ID；
* capture timestamp；
* camera calibration；
* pose stream；
* network and queue policy。

这部分是系统设计，不只是公式。

### 4.3 Capture-time world alignment

说明历史设备位姿如何恢复观测的世界语义。

### 4.4 Reliability-aware observation admission

介绍 VCD，但压缩大量 ZNCC 和阈值细节。

### 4.5 Regime-aware anchor synthesis

介绍 Kalman 状态估计、Linear/SLERP 自适应历史合成、StaticLock、unlock 和 rendering output；Hermite 仅作为配对插值器对照。

### 4.6 Lifecycle and recovery

明确：

* uninitialized；
* tracking；
* temporarily unavailable；
* locked；
* reacquiring；
* recovered。

“持续对象锚点”必须有清楚的生命周期定义，这是非常系统性的贡献。

## 5. Implementation

像 VRGaussianAvatar 一样，坦率列出：

* Quest 3；
* 外部 GPU；
* Unity/Python；
* 图像频率；
* 每模块耗时；
* 网络传输；
* 总时延；
* 模型准备时间；
* 运行资源占用。

你当前系统在 RTX 3090 上约 7 FPS、4090 约 10 FPS、5090 约 14 FPS，这种信息应该进入系统评价，而不仅是实现描述。

## 6. Evaluation

### 6.1 End-to-End System Characterization

系统跨对象、跨运动、跨遮挡的总体表现。

### 6.2 Component Analysis

frame alignment、VCD、temporal runtime 和 StaticLock 的消融。

### 6.3 User Study

完整 EgoAnchor 与一个合理完整 baseline 的任务级比较。

## 7. Discussion and Limitations

## 8. Conclusion

---

# 六、baseline 也应该改成“系统 baseline + 组件消融”

之前的四个时序配置可以保留，但不能让它们成为论文里唯一显眼的 baseline。

## 1. 顶层系统 baseline

建议定义三个完整系统配置：

### Direct Pose Anchoring

一个开发者最容易实现的朴素方案：

* 使用返回的最新 pose；
* 在结果到达时转换到世界系；
* ZOH 保持到下一次观测；
* 不进行可靠性门控；
* 不进行显式生命周期处理。

它回答：

> 为什么 FoundationPose 输出不能直接驱动 MR 内容？

### Conventional Filtered Anchoring

一个较强的标准工程方案：

* capture-time alignment；
* 基本有效性检查；
* One Euro filtering；
* 最新滤波结果保持；
* 简单 lost/hold 机制。

它回答：

> 正确时间对齐加标准时序滤波是否已经足够？

### EgoAnchor

* capture-time alignment；
* VCD admission；
* Kalman Linear/SLERP synthesis；
* StaticLock；
* lifecycle and recovery。

这三个是**系统级对照**。

## 2. 组件消融

为了归因，再做：

* EgoAnchor w/o capture-time alignment；
* EgoAnchor w/o VCD；
* EgoAnchor w/o StaticLock；
* EgoAnchor w/o temporal synthesis（Kalman Predict-to-Now）。

这样既能体现系统，又能证明技术设计。

比起把 ZOH、One Euro、NoLock、Full 直接列成四个平级“算法”，这种结构会更像 VRGaussianAvatar：

* 系统与外部功能 baseline 比；
* 内部创新通过消融验证。

---

# 七、用户实验应该保留，而且它会增强“系统论文”身份

上一轮我说用户实验不是绝对必需，这在规则上没错，但结合你明确想写系统论文、以及这两篇参考论文，我现在建议：

> **只要时间和伦理审批允许，保留一个聚焦的用户实验。**

SelfBlending 几乎完全依赖用户实验来证明系统价值；VRGaussianAvatar 则用定量技术实验证明系统可运行，再用用户实验证明用户能够感知到系统带来的价值。

EgoAnchor 更适合第二种路线。

## 用户实验不应比较 Full vs ZOH

因为 ZOH 太弱，容易成为 strawman。

建议：

* **Conventional Filtered Anchoring**
* **EgoAnchor**

即标准 One Euro / 普通平滑锚定，与完整系统比较。

## 用户任务建议缩成两个

### Task A：Object-attached inspection

真实物体上附着虚拟标签、说明或方向提示。参与者需要：

* 拿起物体；
* 旋转检查；
* 放下；
* 阅读或寻找指定信息。

主要测量：

* 完成时间；
* 阅读/识别错误；
* 重复调整物体次数；
* perceived stability；
* workload。

### Task B：Object-attached interaction

真实物体上附着按钮、控制面板或装配引导。物体经历：

* 移动；
* 停止；
* 短暂遮挡；
* 恢复。

主要测量：

* 点击或选择错误；
* 任务完成时间；
* 因错位导致的重试；
* perceived alignment；
* trust / preference。

这两个任务分别代表：

* 静止稳定与 stop-go；
* 动态连续、遮挡和恢复。

任务不要太多，否则每个构念都测不干净。

---

# 八、还要不要显式写 RQ1–RQ3？

结合两篇参考论文，可以看到：

* SelfBlending 因为主要是用户研究，所以列了四个明确的用户研究 RQ；
* VRGaussianAvatar 没有在引言中列 RQ，而是直接写贡献、系统结构、定量实验和用户研究。

因此：

> **系统论文不要求必须写 RQ。**

对于 EgoAnchor，我现在更推荐**不在引言中列 RQ1–RQ3**，而是在 Evaluation 开头写三个 evaluation goals：

### G1. End-to-end capability

EgoAnchor 在不同对象、运动和遮挡条件下，能否提供准确、稳定、连续且可恢复的动态锚点？

### G2. System design attribution

Capture-time alignment、VCD admission 和 regime-aware anchoring 各自对系统性能有什么贡献和代价？

### G3. Application utility

相较于 conventional filtered anchoring，EgoAnchor 是否改善对象附着型 MR 任务中的表现和用户体验？

这比当前的 RQ1“VCD 是否有好 AURC”、RQ2“几个滤波器差多少”、RQ3“覆盖几个对象”更像一个完整系统论文的证据结构。

RQ 可以保留在实验设计内部，但不要让三个算法问题统治引言和贡献。

---

# 九、最终推荐的贡献表述

我建议将贡献改成下面三项：

### C1. EgoAnchor system

一套端到端、模型可扩展的消费级 MR 动态真实物体锚定系统，仅使用头显双目图像和目标三维模型，将异步视觉位姿转换为持续世界系对象锚点。

### C2. Observation-to-anchor runtime

一套面向异步视觉感知的锚定运行时，通过 capture-time world alignment、可靠性接纳和区制感知时序合成，处理时间错配、坏观测、静止抖动、运动连续性以及遮挡恢复。

### C3. System evaluation

一套覆盖端到端锚定质量、系统组件贡献、多对象适用范围和用户任务效用的评估，证明系统在消费级 MR 场景中的能力与边界。

其中 VCD 和 StaticLock 是 C2 中的关键技术设计，不必分别升级为整篇论文级贡献。

---

## 结论

**EgoAnchor 应该写成系统论文，而且它具备比 SelfBlending 更强的技术系统深度。**

最合适的参考模板不是完全照搬 SelfBlending，而是：

> **VRGaussianAvatar 的系统架构与技术评估方式**
> ＋
> **SelfBlending 的用户任务价值验证方式**

当前计划最需要的不是增加更多算法 baseline，而是重新确定评价层级：

1. 首先证明完整 EgoAnchor 系统能够实现动态对象锚定；
2. 再通过消融解释系统为什么有效；
3. 最后通过用户实验说明这种锚点能力对 MR 应用确实有价值。

这样，VCD、frame alignment 和 StaticLock 都服务于 EgoAnchor，而不是让 EgoAnchor 退化成它们的实验载体。
