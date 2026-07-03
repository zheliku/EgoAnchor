# EgoAnchor 论文写作规划与系统设计笔记

本文档只记录 IEEE VR 2027 投稿阶段的论文定位、实验设计、术语基准和审稿风险。端到端技术流程、字段名、默认权重和公式细节以
[`../egoanchor_code_derived_technical_flow.md`](../egoanchor_code_derived_technical_flow.md)
为准。`egoanchor_cn_v4.typ` 是当前已确定的论文版本，也是项目论文相关文档的术语基准。

## 术语基准（与 `egoanchor_cn_v4.typ` 第 3 章对齐）

全文术语原则：**论文概念沿用 `egoanchor_cn_v4.typ` 的中文表述，代码标识保留英文**。后续写作直接使用下列口径。

| 论文中文术语（概念） | 英文 | 对应代码标识/字段（保留英文） | 写作口径 |
| --- | --- | --- | --- |
| 动态真实物体锚定 | dynamic real-object anchoring | EgoAnchor 系统目标 | 标题、摘要、引言和结论使用的主概念 |
| 动态对象锚定 | dynamic object anchoring | object anchor 输出 | 方法与相关工作中描述对象级锚定能力 |
| 对象级空间参考 | object-level spatial reference | world-space object anchor | 解释动态对象锚定为何需要随物体运动更新 |
| 视觉感知后端 | Visual Perception Backend | Python perception pipeline | 输出相机坐标系异步位姿流与可靠性评分 |
| 对象锚定运行时 | Object Anchoring Runtime | Unity anchor runtime | 输出世界坐标系下稳定、连续、可恢复的对象锚点 |
| 目标语义分割 | target semantic segmentation | YOLOE-26、SAM3、`SegmenterResult` | 初始目标掩膜生成；Cutie 单独称为时序掩膜传播 |
| 时序掩膜传播 | temporal mask propagation | Cutie | 注册成功后的目标掩膜连续传播 |
| 双目立体几何重建 | stereo geometry reconstruction | Fast-FoundationStereo | 从双目视差恢复米制深度 |
| 零样本 6DoF 位姿估计 | zero-shot 6DoF pose estimation | FoundationPose | 初始注册与连续追踪 |
| 可靠性评分 | reliability score | `reliability_score`、VCD、`score_reprojection/score_depth/score_mask` | 即时运行时可靠性信号 |
| 颜色投影子分 | color projection score | `score_reprojection`、`color_reprojection=-1` | `-1` 表示本帧无有效颜色证据 |
| 时空对齐 | spatiotemporal alignment | `frame_id` 回查、`CameraPoseFrameAligner` | 方法小节主术语；技术展开时写“基于采集时刻的帧对齐” |
| 质量评估门控 | quality evaluation gate | `enableQualityGate`、`QualityGateDecision`、`quality_gate`、`trackingScoreFloor` | 论文 RQ2 完整方法中的可靠性接收/状态退化机制；代码中独立门控模块已删，保留为 `AnchorPolicyHost` 内联可选逻辑 |
| 锚定策略 | anchoring policy | `MotionModel × SmoothingStrategy` | 运动模型与平滑策略的组合 |
| 静止锚定 | static anchoring | `EgoAnchorStaticLockModule`、`StaticLockController`、`latest_static_locked` | 论文方法名；代码实现定位使用 `StaticLock` 类名即可，不在正文写“静止锁” |
| 生命周期状态机 | lifecycle state machine | `AnchorStateMachine` | 描述 Searching / Tracking / Coasting / Lost 等锚点状态 |

> baseline/condition 的标签名（`arrival_time_raw`、`frame_aligned_raw`、`egoanchor`、`kalman_blend` 等）是代码 label，全文保留英文不译。评估指标名（anchor error、jitter、slip、lag、latency、recovery）对应 eval 输出列名，保留英文，必要时附中文。

### 术语统一性检查

`egoanchor_cn_v4.typ` 的术语主线是统一的：标题、摘要和结论用“动态真实物体锚定”概括系统目标；方法与相关工作用“动态对象锚定”描述对象级锚定能力；“对象级空间参考”是对该能力的解释性表述。方法章节的显式小节是零样本视觉推理、可靠性评分、时空对齐、运动估计与平滑、静止锚定和生命周期管理；“质量评估门控”只在 RQ2 消融的完整方法中出现，不是单独方法小节。代码中“静止锁”是静止锚定的实现名。

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

写作分工：三维度是 value-proposition 主线骨架；技术 novelty（时空对齐、静止锚定、锚点中心评估）全部落在维度 3，是研究贡献主体。维度 1、2 扛"可达性/通用性"故事。架构上对象感知（Visual Perception Backend）与对象锚定（Object Anchoring Runtime）解耦呈现；Runtime 内部结构按时空对齐、运动估计与平滑、静止锚定和生命周期管理组织。质量评估门控在写作中只作为可靠性评分进入运行时后的观测接收/状态退化机制，出现在完整方法和消融设置里，不单列为顶层贡献。不要把任一单模块写成全新算法；稳妥说法是：已知视觉能力被组织成针对开放消费级 MR 异步感知的系统，并经端到端实现与评估验证有效。

## 建议贡献表述

1. **系统（对应核心信息整体）**：提出 EgoAnchor，面向开放消费级 MR 的动态真实物体锚定系统，仅依赖头显双目图像与物体三维模型，即可对任意日常刚性物体实现连续 6DoF 动态锚定（覆盖维度 1、2；目标物体位姿链路纯视觉，参考相机世界位姿来自头戴端自身跟踪）。
2. **Visual Perception Backend（维度 1、2 的能力来源）**：把目标语义分割、时序掩膜传播、双目立体几何重建与零样本 6DoF 位姿估计组织为统一的异步感知流水线，持续产出 camera-space 异步位姿观测；后端可随开放视觉基础模型升级而无需改动运行时。
3. **Object Anchoring Runtime（维度 3，技术主体）**：通过时空对齐（按 `frame_id` 精确回查 capture-time reference camera pose 合成 world anchor）、可靠性评分驱动的观测接收/状态退化、`MotionModel × SmoothingStrategy` 锚定策略、静止锚定和生命周期状态机，将异步位姿流转换为世界一致、稳定且可恢复的对象锚点。
4. **锚点中心的评估方法**：用 world-space anchor error、jitter/slip、lag、latency、recovery success/time 评价 MR 使用质量，而不是只报告 CV 单帧 pose accuracy。

## 研究问题（RQ）

**设计原则**：RQ 以 `egoanchor_cn_v4.typ` 为准，分别覆盖锚定质量、设计权衡和泛化能力。运动模型与平滑策略（Kalman / OneEuro / Blend / DelayedInterp 等）是可热插拔的实现细节，不单独设置 RQ；当前 EgoAnchor 评估配置采用 `KalmanModel + DelayedInterpStrategy + EgoAnchorStaticLockModule`，但正文不做 filter bake-off。九变体设计空间对比放补充材料，用于回答"为什么选默认组合"，不进正文主 RQ。

三个 RQ 与贡献的对应：

| RQ | 问题 | 对应贡献 | 轨道 | 物体 / GT |
| --- | --- | --- | --- | --- |
| RQ1 | 锚定质量：EgoAnchor 能否满足动态对象锚定的精度、稳定性、响应性和鲁棒性需求 | 整体系统质量 | 定量 | 手柄 / ✅ SDK GT |
| RQ2 | 设计权衡：分层架构与静止锚定如何在稳定性与响应性之间取舍，相对运动无关平滑有何优势 | 时空对齐、质量评估门控、静止锚定的消融 | 定量 | 手柄 / ✅ SDK GT |
| RQ3 | 泛化能力：多类日常刚性物体与典型应用场景中的泛化能力和适用边界 | 开放/通用系统 | 用户研究 + 免 GT 代理 | 日常物体 / ❌ 无 GT |

要点：

- **RQ1**：报告完整 EgoAnchor 在静止、头动、物体运动、遮挡和出视野后的整体锚定质量。anchor error、jitter/slip、lag、latency、recovery 都服务于这个问题。
- **RQ2**：通过消融解释设计选择，而不是把 RQ2 写成单一模块胜负。消融阶梯为简化基线、时空对齐、完整方法（时空对齐 + 质量评估门控 + 静止锚定），并额外比较静止锚定与更强平滑的稳定性/响应性权衡。
- **RQ3**：开放性的泛化证据。日常物体无 GT，靠用户研究（主观可用性）+ 免 GT 客观代理指标（jitter / 失锁率 / 静止锚定期间输出位移）双管齐下。

三个 RQ 合起来：RQ1 给整体锚定质量，RQ2 解释这些质量来自哪些运行时设计，RQ3 补上日常物体和应用场景的泛化证据。两条实验轨道分别提供带 GT 的硬指标和无 GT 的应用证据（见《评估两轨结构》）。

## Baseline 与消融

**轨道归属**：以下所有对比都需要精确数值，**全部归手柄定量轨**（仅手柄有 SDK GT）。日常物体不跑这些对比，只跑免 GT 代理指标 + 用户研究（见《评估两轨结构》）。`AnchorRuntimeHub` 把同一 `PoseResult` 扇出到多个并行 runtime，保证各变体输入完全一致。

时空对齐对比（归入 RQ2 消融，证明 capture-time alignment 的必要性）：

- `arrival_time_raw`：到达/渲染时刻 latest camera pose 对照，是诊断路径而非正式输出。
- `frame_aligned_raw`：按 `frame_id` 回查 capture-time pose，但不做高阶策略。
- `egoanchor`：完整方法。

设计权衡消融阶梯（对应 RQ2，正文主体）：固定当前 EgoAnchor 评估配置（Kalman + DelayedInterp），逐步启用运行时设计，证明"设计组合的作用"而非"哪个滤波器更好"。

- `raw`：裸时序基线（`ConstantVelocityModel + RawPassthroughStrategy`，零阶保持），无任何高阶策略。
- `policy_no_lock`：开运动模型 + 平滑，可按论文完整方法设置打开 `enableQualityGate`，但关静止锚定（只开关 `EgoAnchorStaticLockModule`，这是最干净的单因素消融）。
- `egoanchor`：完整方法（时空对齐 + 质量评估门控 + 静止锚定）。
- 可选再拆：关 `enableQualityGate` / 低分重获取（low-score reacquire），单独看坏观测与恢复链路的贡献。
- 关键：每个阶梯都**同时报稳定性与响应性**（jitter/slip + lag/latency/recovery），证明静止锚定提升稳定的同时没有牺牲响应。

运动模型 / 平滑策略选择（补充材料，不进正文 RQ）：

- 当前 EgoAnchor 评估配置为 Kalman + DelayedInterp。九变体设计空间（三运动模型 × 三平滑策略）的对比只在补充材料呈现，用于回答"为什么选当前默认组合"，给 Pareto 或多参数扫描，不用单点结果宣称"优于 One Euro / Kalman"（见《审稿风险》）。
- 理由：这些是可热插拔的工程模块、不是论文贡献，不该占正文 RQ 篇幅。

## 实验条件

最低实验闭环：

1. Quest 真机 + Python real pipeline + Unity anchor runtime 连续运行。
2. 覆盖 `static`、`slow_head`、`fast_head`、`object_motion`、`occlusion`、`out_of_view`、`lighting`。
3. 物体集按"覆盖设计空间"选，而不是凑数量（详见下方《物体选择》）；其中 Quest controller 作为带 SDK GT 的高可信定量评估目标。
4. 对每个正式 session 记录 Unity capture/output、Python runtime log 和 manifest。

定量轨主指标（手柄，需 GT，支撑 RQ1 的整体质量与 RQ2 的设计消融）：

- world-space translation / rotation anchor error（RQ1：整体锚定精度；RQ2：设计阶梯差异）。
- static jitter（RQ2 稳定性）。
- head-motion-induced slip（RQ1/RQ2）。
- lag / latency（RQ2 响应性，与稳定性同表呈现）。
- recovery success/time（RQ2 响应性）。

定量轨辅助指标（手柄，诊断用）：

- Python reliability 分布、颜色重投影有效率、深度对齐分布。
- 推理耗时和端到端 capture-to-apply 延迟。

日常物体轨免 GT 代理指标（无 GT，支撑 RQ3 的泛化证据，细节见《评估两轨结构》）：

- 静止 jitter / 屏幕空间抖动、reliability 分布、失锁帧占比与自动/手动重获取触发率、静止锚定期间输出位移。

## 物体选择

现有资产与配置（`EgoAnchor_Python/src/egoanchor/config/defaults.toml` 的 `[objects.*]` 与 `EgoAnchor_Python/data/model/`）：`earphone.glb`、`blue_mouse.glb`、`pink_mouse.glb`、`MetaQuestTouchPlus_Left/Right.glb`、`cube.stl`。当前已接入目标是耳机充电盒、蓝/粉鼠标、Quest Touch Plus 左/右手柄和立方体；手柄作带 SDK GT 的定量参照。

问题：耳机和鼠标在视觉/几何维度上高度同质，**都落在"小件 + 弱纹理 + 光面"这一侧**，恰好是本系统最擅长、也最依赖深度的工况（`depth_weight=0.8` 就是为低纹理目标设计）。只测这一类 = 在自己的舒适区自证，撑不起摘要"跨多类日常刚性物体"的开放性主张，也让颜色投影子分 C / `score_reprojection` 形同虚设、无从验证。

物体集应横跨三个轴、每轴都取两端，让"general-purpose"站得住：

| 物体 | 尺寸 | 纹理 | 几何/对称 | 角色 |
| --- | --- | --- | --- | --- |
| 鼠标（保留） | 小 | 弱、光面 | 近似对称 | 近物精细交互 |
| 耳机（保留，注意半刚性） | 中 | 弱 | 不规则 | 头梁可弯→违反刚性假设，写成 limitation |
| ➕ 带按键/接口的小设备（路由器/桌面打印机等） | 中 | 中 | 规则+局部细节 | 撑起"虚拟说明书附着"任务（最该补） |
| ➕ 书 / 盒装品 | 中 | **强、平面** | 规则 | 验证颜色投影子分 C 真有用 |
| ➕ 马克杯 / 水瓶（可选） | 中 | 弱~中、可反光 | **回转体、部分对称** | 测对称约束，经典 6DoF 难例 |

要点：

- "虚拟说明书附着"任务现在没有合适载体——鼠标和耳机都不需要说明书。必须补一个有操作复杂度的设备，否则正文声称的任务与物体集对不上。
- 强纹理物体是验证颜色投影分支的唯一途径；缺它，颜色重投影在论文里无法自证有效。
- 日常物体只需要一个三维模型（可用 Image-to-3D 现生成），**不需要 GT**，所以物体选择是自由的，没有理由不补。
- 耳机的半刚性（头梁可弯）会让 mesh 对不齐，明确写进 limitations，不要假装它是理想刚体。

## 评估两轨结构（GT 用手柄，日常物体免 GT）

GT 方案定调：**只用 Quest 手柄经官方 SDK 取 6DoF 作为 GT**，不给日常物体硬凑 GT。理由：给日常物体绑手柄会引入"物体↔手柄外参"标定误差（现报告 `pose_offset` 旋转常偏 ≈ -1°、`rotation_offset_std` 7–13° 有一部分就是这类残差），且日常物体中心位置难确定。手柄 SDK pose 零额外标定、精度最高，是干净选择。

由此评估自然分两轨，这个划分要在正文里**显式讲清楚**，化缺口为卖点：

| 轨道 | 物体 | GT | 度量 |
| --- | --- | --- | --- |
| 定量评估 | 仅 Quest 手柄 | ✅ 官方 6DoF | RQ1 整体锚定质量；RQ2 时空对齐、完整方法和静止锚定消融 |
| 用户研究 + 免 GT 代理 | 耳机、鼠标、补充设备… | ❌ | 任务可用性、主观量表 **+ 免 GT 客观代理指标** |

审稿人必问的缺口：定量精度只在"手柄"这一个物体上验证，而手柄是被追踪设备、mesh 完美、纹理特定，**它证明的是"锚定运行时"好，没证明"感知"能泛化到日常物体**。

补救（强烈建议，最便宜有效）：给日常物体补一组**不需要 6DoF GT 的质量代理指标**，现有 eval 流水线已能产出：

- **静止 jitter / 屏幕空间抖动**：让被试"拿稳别动"几秒，直接测输出方差，无需 GT 位姿。
- **可靠性分分布**（`reliability_score`）：纯系统输出。
- **跟踪连续性**：失锁帧占比、Unity `reacquire/reset` 命令触发率。
- **静止锚定有效性**：静止段输出位移，静止锚定应将其压到近零。

这样"手柄上的硬精度 GT + 日常物体上的免 GT 稳定性代理"两轨合起来，泛化故事才闭环：既证明运行时质量，又证明感知对开放物体可用。

## 方法与代码同步口径

本节记录项目文档采用的统一口径。论文术语以 `egoanchor_cn_v4.typ` 为准，代码实现名只在需要精确定位文件、字段或实验条件时保留。

| 论文术语 | 项目文档同步写法 |
| --- | --- |
| 目标语义分割 | 默认目标语义分割后端为 `YOLOE-26`，`SAM3` 是可切换后端，二者通过 `SegmenterResult` 进入统一感知流水线。 |
| 时序掩膜传播 | `Cutie` 只描述为时序掩膜传播模块，不并入初始目标语义分割概念。 |
| 双目立体几何重建 | `Fast-FoundationStereo` 输出米制深度，为三维对齐和深度一致性评估提供尺度约束。 |
| 可靠性评分 | VCD 是即时运行时可靠性评分；C/D 只融合有效证据，`color_reprojection=-1` 表示本帧没有有效颜色证据。 |
| 时空对齐 | 正式机制是按 `frame_id` 精确回查采集时刻参考相机位姿；arrival-time 只作为评估对照。 |
| 质量评估门控 | 论文中作为 RQ2 完整方法的组成项；代码中独立门控模块已删除，当前是 `AnchorPolicyHost.enableQualityGate` 控制的内联观测拒绝逻辑。源码默认关，评估完整方法变体可在场景中打开。`quality_gate` 是当前 eval 字段，取值 `enabled/disabled`。生命周期状态、低分重获取和静止锚定也会消费可靠性评分，但不等同于这个开关。 |
| 锚定策略 | 用 `MotionModel × SmoothingStrategy` 描述运动模型和平滑策略组合；正文不把具体滤波器写成独立贡献。 |
| 静止锚定 | 论文方法名使用“静止锚定”；代码定位可写 `EgoAnchorStaticLockModule`、`StaticLockController` 或 `latest_static_locked`。 |
| 生命周期状态机 | 描述对象锚点从 Searching / Tracking / Coasting / FrozenUncertain / Lost 到 Relocalizing 的状态演化和重获取闭环。 |

- 三维主线（open / deployable / general-purpose / stable）是 value proposition，不是能力勾选表。不要回退到"五维能力矩阵 + 首个全 ✓"的写法——那种断言会被任一次平台 SDK 更新击穿，也容易被指 cherry-pick。需要对照时，写成沿三维度的 design-space 取舍讨论。
- “open / deployable”范围必须收窄：指无需物理标签、专用深度硬件、逐物体离线训练；**不等于头显端独立运行**。当前感知跑在外部消费级 GPU 并经 ZMQ/NATS 异步通信，开发记录中的端到端视觉推理约为 RTX 3090 140 ms / 7 fps、RTX 4090 100 ms / 10 fps、RTX 5090 65 ms / 15 fps；limitations 必须保留"外部算力依赖"，不要让读者误读成"Quest 即插即用"。
- “纯视觉”只修饰目标物体位姿估计链路。不要写成整个系统完全不依赖头显 SLAM、IMU 或平台追踪。
- Python 不输出 world pose；world anchor 只在 Unity 端通过 `frame_id` 回查得到。
- arrival-time mapping 是诊断对照，不是正式路径。
- 静止锚定是 regime-switching 稳定器，不是普通低通滤波。
- VCD 只负责可靠性评分；质量评估门控是 `AnchorPolicyHost` 的可选内联观测接收逻辑，不属于 VCD 公式，也不是独立模块。
- 当前 JSONL 输出字段是 `has_output_pose/output_pos/output_rot`，静止锚定状态字段是 `latest_static_locked`；report 里的 `stable_rows` 只是统计名。

## 审稿风险

- 与平台能力的对比必须投稿前重新联网核实。避免使用“平台完全不支持动态物体”这类容易被新 SDK 击穿的断言。
- 与 Vision Pro / Meta / Vuforia / Azure 等系统对比时，优先做能力维度和系统假设对比；跨设备定量比较只能谨慎呈现。
- 如果使用 controller SDK pose 作为 GT，要说明它与头显共享追踪系，只能隔离视觉 pose-to-anchor 栈，不能暴露头显 SLAM 的共模误差。
- 定量精度只在手柄单物体上有 GT，而手柄是被追踪设备、mesh 完美、纹理特定。必须用日常物体的免 GT 代理指标（见《评估两轨结构》）补上感知泛化证据，否则"跨多类日常物体"的开放性主张缺乏定量支撑。
- 过滤器对比最好给 Pareto 或多参数扫描，不要用单点结果宣称“优于 One Euro / Kalman”。
- 用户实验需要事先明确任务、样本量依据、主观量表和统计检验方式。

## 投稿前清单

- [x] 正文已收口到三维主线：`egoanchor_cn_v4.typ` 第 3 章按对象感知/对象锚定两段式重构，方法小节为可靠性评分、时空对齐、运动估计与平滑、静止锚定和生命周期管理；质量评估门控只作为 RQ2 完整方法消融项保留。
- [x] 论文术语与项目文档口径已同步到本文“术语基准”和“方法与代码同步口径”。
- [ ] 完成至少一轮正式真机 session，并生成 report。
- [ ] 核对相关工作和平台能力的最新状态。
- [x] 补齐正文引用，移除临时全量引用，仅保留正文实际引用的 bibliography entries。（已完成：`egoanchor_cn_v4.typ` 相关工作前两小节补全引用，参考文献收敛到正文实引条目。）
- [ ] 扩展物体集到覆盖矩阵：补 1 个带操作复杂度的设备（撑"虚拟说明书附着"）+ 1 个强纹理物体（验证颜色投影子分 C）；缺模型的用 Image-to-3D 生成。
- [ ] 给日常物体跑免 GT 代理指标（jitter / reliability 分布 / 失锁率 / 静止锚定期间输出位移），与手柄定量轨配套。
- [ ] 在评估章显式写出"手柄定量 + 日常物体定性与代理"的两轨结构，把单物体 GT 缺口讲成设计选择。
- [ ] 准备 supplementary video：时空对齐 vs 到达时刻对照（`frame_aligned_raw` vs `arrival_time_raw`）、静止锚定、遮挡/出视野恢复、baseline 对比。
