# EgoAnchor 论文写作规划与系统设计笔记

本文档只记录 IEEE VR 2027 投稿阶段的论文定位、实验设计和审稿风险。端到端技术流程、字段名、默认权重和公式细节以
[`../egoanchor_code_derived_technical_flow.md`](../egoanchor_code_derived_technical_flow.md)
为准。

## 术语基准（与 v4.tex 第 3 章对齐）

全文术语原则：**论文概念用中文（首次出现附英文），代码标识保留英文**。本表为权威映射，新增内容一律按此用词；发现旧词残留即改。

| 论文中文术语（概念） | 英文 | 对应代码标识/字段（保留英文） | 已弃用的旧说法 |
| --- | --- | --- | --- |
| 视觉感知后端 | Visual Perception Backend | — | — |
| 对象锚定运行时 | Object Anchoring Runtime | — | — |
| 目标分割 | object segmentation | YOLOE / SAM3 / Cutie | — |
| 立体几何恢复 | stereo geometry recovery | Fast-FoundationStereo | 双目重建 |
| 零样本 6DoF 位姿估计 | zero-shot 6DoF pose estimation | FoundationPose | — |
| 可靠性评分 | reliability score | `reliability_score`、VCD：$R=\text{Gate}\times V\times C^{\alpha}\times D^{\beta}$ | — |
| 时间对齐 | frame-aligned / capture-time alignment | `frame_id` 回查、`CameraPoseFrameAligner` | 帧对齐（可用）、frame-aligned anchoring（作概念时用"时间对齐"） |
| 质量评估门控 | quality / score gate | `GateDecision`、`enableScoreGate` | 可靠性门控、观测门控 |
| 锚定策略 | anchoring policy | `MotionModel × SmoothingStrategy` | 高频时序稳定、时序稳定 |
| 静止优先先验 | static-first prior / static lock | `EgoAnchorStaticLockModule`、`latest_static_locked` | reliability-aware static lock（作概念时用"静止优先先验"）|
| 生命周期状态机 | lifecycle state machine | `AnchorStateMachine` | 生命周期管理 |

> baseline/condition 的标签名（`arrival_time_raw`、`frame_aligned_raw`、`egoanchor`、`kalman_blend` 等）是代码 label，全文保留英文不译。评估指标名（anchor error、jitter、slip、lag、latency、recovery）对应 eval 输出列名，保留英文，必要时附中文。

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

写作分工：三维度是 value-proposition 主线骨架；技术 novelty（时间对齐 frame-aligned anchoring、静止优先先验 reliability-aware static lock、锚点中心评估 anchor-centric evaluation）全部落在维度 3，是研究贡献主体。维度 1、2 扛"可达性/通用性"故事。架构上对象感知（Visual Perception Backend）与对象锚定（Object Anchoring Runtime）解耦呈现；旧"四层协同架构"降级为 Runtime 内部结构（时间对齐 / 质量评估门控 / 锚定策略 / 静止优先先验 / 生命周期状态机），不再当论文顶层骨架。不要把任一单模块写成全新算法；稳妥说法是：已知视觉能力被组织成针对开放消费级 MR 异步感知的系统，并经端到端实现与评估验证有效。

## 建议贡献表述

1. **系统（对应核心信息整体）**：提出 EgoAnchor，面向开放消费级 MR 的动态真实物体锚定系统，仅依赖头显双目图像与物体三维模型，即可对任意日常刚性物体实现连续 6DoF 动态锚定（覆盖维度 1、2；目标物体位姿链路纯视觉，参考相机世界位姿来自头戴端自身跟踪）。
2. **Visual Perception Backend（维度 1、2 的能力来源）**：把目标发现、目标分割、立体几何恢复与零样本 6DoF 位姿估计组织为统一的异步感知流水线，持续产出 camera-space 异步位姿观测；后端可随开放视觉基础模型升级而无需改动运行时。
3. **Object Anchoring Runtime（维度 3，技术主体）**：通过时间对齐（按 `frame_id` 精确回查 capture-time camera pose 合成 world anchor）、质量评估门控、`MotionModel × SmoothingStrategy` 锚定策略与静止优先先验、生命周期状态机，将异步位姿流转换为世界一致、稳定且可恢复的对象锚点。
4. **锚点中心的评估方法**：用 world-space anchor error、jitter/slip、lag、latency、recovery success/time 评价 MR 使用质量，而不是只报告 CV 单帧 pose accuracy。

## 研究问题（RQ）

**设计原则**：RQ 一一对应三个技术贡献，不为可替换的工程模块单设 RQ。运动模型与平滑策略（Kalman / OneEuro / Blend / DelayedInterp 等）是可热插拔的模块、不是论文贡献，**默认 Kalman + Blend，不做 filter bake-off**；九变体设计空间对比放补充材料（用于回答"为什么选 Kalman"，不进正文）。真正要比的是稳定化策略的**有无**，而非哪个滤波器更好。

三个 RQ 与贡献的对应：

| RQ | 问题 | 对应贡献 | 轨道 | 物体 / GT |
| --- | --- | --- | --- | --- |
| RQ1 | capture-time 对齐相对 arrival-time 变换能降低多少动态配准误差 | 时间对齐 | 定量 | 手柄 / ✅ SDK GT |
| RQ2 | 稳定化策略（静止优先先验为核心）能否在不牺牲响应性的前提下提升锚定稳定性，各组件各贡献多少 | 静止优先先验 | 定量 | 手柄 / ✅ SDK GT |
| RQ3 | 系统能否在多类日常物体上支撑真实 MR 锚定任务 | 开放/通用系统 | 用户研究 + 免 GT 代理 | 日常物体 / ❌ 无 GT |

要点：

- **RQ1**：隔离时间对齐这一项。核心对比是 `arrival_time_raw` vs `frame_aligned_raw`（两者都 raw、不加策略），干净证明对齐的必要性。
- **RQ2**：用"有无策略"的消融阶梯证明静止优先先验的价值，**并把响应性并入同一 RQ**——因为该先验的设计精髓是"既稳又不牺牲响应"，稳定性（jitter/slip）与响应性（lag/latency/recovery）必须一起报，否则审稿人会质疑稳定是靠加滞后换来的。
- **RQ3**：开放性的泛化证据。日常物体无 GT，靠用户研究（主观可用性）+ 免 GT 客观代理指标（jitter / 失锁率 / 静止优先先验位移）双管齐下。

三个 RQ 合起来：RQ1+RQ2 是手柄定量轨的硬精度证据（证明运行时质量），RQ3 是日常物体轨的泛化证据（证明感知对开放物体可用），两轨闭环（见《评估两轨结构》）。

## Baseline 与消融

**轨道归属**：以下所有对比都需要精确数值，**全部归手柄定量轨**（仅手柄有 SDK GT）。日常物体不跑这些对比，只跑免 GT 代理指标 + 用户研究（见《评估两轨结构》）。`AnchorRuntimeHub` 把同一 `PoseResult` 扇出到多个并行 runtime，保证各变体输入完全一致。

时间对齐对比（对应 RQ1，证明 capture-time 对齐的必要性）：

- `arrival_time_raw`：到达/渲染时刻 latest camera pose 对照，是诊断路径而非正式输出。
- `frame_aligned_raw`：按 `frame_id` 回查 capture-time pose，但不做高阶策略。
- `egoanchor`：完整方法。

稳定化策略消融阶梯（对应 RQ2，正文主体）：固定默认运动模型/平滑策略（Kalman + Blend），只开关策略层组件，证明"策略的有无"而非"哪个滤波器更好"。

- `raw`：裸时序基线（`ConstantVelocityModel + RawPassthroughStrategy`，零阶保持），无任何高阶策略。
- `policy_no_lock`：开质量评估门控 + 平滑，但关静止优先先验（只开关 `EgoAnchorStaticLockModule`，这是最干净的单因素消融）。
- `egoanchor`：完整方法（含静止优先先验）。
- 可选再拆：关质量评估门控（score gate）/ 低分重获取（low-score reacquire），单独看坏观测与恢复链路的贡献。
- 关键：每个阶梯都**同时报稳定性与响应性**（jitter/slip + lag/latency/recovery），证明静止优先先验提升稳定的同时没有牺牲响应。

运动模型 / 平滑策略选择（补充材料，不进正文 RQ）：

- 默认 Kalman + Blend。九变体设计空间（三运动模型 × 三平滑策略）的对比只在补充材料呈现，用于回答"为什么默认选 Kalman"，给 Pareto 或多参数扫描，不用单点结果宣称"优于 One Euro / Kalman"（见《审稿风险》）。
- 理由：这些是可热插拔的工程模块、不是论文贡献，不该占正文 RQ 篇幅。

## 实验条件

最低实验闭环：

1. Quest 真机 + Python real pipeline + Unity anchor runtime 连续运行。
2. 覆盖 `static`、`slow_head`、`fast_head`、`object_motion`、`occlusion`、`out_of_view`、`lighting`。
3. 物体集按"覆盖设计空间"选，而不是凑数量（详见下方《物体选择》）；其中 Quest controller 作为带 SDK GT 的高可信定量评估目标。
4. 对每个正式 session 记录 Unity capture/output、Python runtime log 和 manifest。

定量轨主指标（手柄，需 GT，支撑 RQ1–RQ2）：

- world-space translation / rotation anchor error（RQ1：对齐收益；RQ2：策略阶梯精度）。
- static jitter（RQ2 稳定性）。
- head-motion-induced slip（RQ1/RQ2）。
- lag / latency（RQ2 响应性，与稳定性同表呈现）。
- recovery success/time（RQ2 响应性）。

定量轨辅助指标（手柄，诊断用）：

- Python reliability 分布、颜色重投影有效率、深度对齐分布。
- 推理耗时和端到端 capture-to-apply 延迟。

日常物体轨免 GT 代理指标（无 GT，支撑 RQ3 的泛化证据，细节见《评估两轨结构》）：

- 静止 jitter / 屏幕空间抖动、reliability 分布、失锁帧占比与重注册触发率、静止优先先验位移。

## 物体选择

现有资产（`EgoAnchor_Python/data/model/`）：`earphone.glb`、`blue_mouse.glb`、`pink_mouse.glb`、`MetaQuestTouchPlus_Left/Right.glb`、`cube.stl`。即当前实测目标是耳机 + 鼠标，手柄作 GT 参照。

问题：耳机和鼠标在视觉/几何维度上高度同质，**都落在"小件 + 弱纹理 + 光面"这一侧**，恰好是本系统最擅长、也最依赖深度的工况（`depth_weight=0.8` 就是为低纹理目标设计）。只测这一类 = 在自己的舒适区自证，撑不起摘要"跨多类日常刚性物体"的开放性主张，也让颜色重投影子分 `s_rep` 形同虚设、无从验证。

物体集应横跨三个轴、每轴都取两端，让"general-purpose"站得住：

| 物体 | 尺寸 | 纹理 | 几何/对称 | 角色 |
| --- | --- | --- | --- | --- |
| 鼠标（保留） | 小 | 弱、光面 | 近似对称 | 近物精细交互 |
| 耳机（保留，注意半刚性） | 中 | 弱 | 不规则 | 头梁可弯→违反刚性假设，写成 limitation |
| ➕ 带按键/接口的小设备（路由器/桌面打印机等） | 中 | 中 | 规则+局部细节 | 撑起"虚拟说明书附着"任务（最该补） |
| ➕ 书 / 盒装品 | 中 | **强、平面** | 规则 | 验证颜色子分 `s_rep` 真有用 |
| ➕ 马克杯 / 水瓶（可选） | 中 | 弱~中、可反光 | **回转体、部分对称** | 测对称约束，经典 6DoF 难例 |

要点：

- "虚拟说明书附着"任务现在没有合适载体——鼠标和耳机都不需要说明书。必须补一个有操作复杂度的设备，否则正文声称的任务与物体集对不上。
- 强纹理物体是验证 `s_rep` 分支的唯一途径；缺它，颜色重投影在论文里无法自证有效。
- 日常物体只需要一个三维模型（可用 Image-to-3D 现生成），**不需要 GT**，所以物体选择是自由的，没有理由不补。
- 耳机的半刚性（头梁可弯）会让 mesh 对不齐，明确写进 limitations，不要假装它是理想刚体。

## 评估两轨结构（GT 用手柄，日常物体免 GT）

GT 方案定调：**只用 Quest 手柄经官方 SDK 取 6DoF 作为 GT**，不给日常物体硬凑 GT。理由：给日常物体绑手柄会引入"物体↔手柄外参"标定误差（现报告 `pose_offset` 旋转常偏 ≈ -1°、`rotation_offset_std` 7–13° 有一部分就是这类残差），且日常物体中心位置难确定。手柄 SDK pose 零额外标定、精度最高，是干净选择。

由此评估自然分两轨，这个划分要在正文里**显式讲清楚**，化缺口为卖点：

| 轨道 | 物体 | GT | 度量 |
| --- | --- | --- | --- |
| 定量评估 | 仅 Quest 手柄 | ✅ 官方 6DoF | anchor error、jitter、slip、lag、latency、recovery、RQ1（capture vs arrival） |
| 用户研究 + 免 GT 代理 | 耳机、鼠标、补充设备… | ❌ | 任务可用性、主观量表 **+ 免 GT 客观代理指标** |

审稿人必问的缺口：定量精度只在"手柄"这一个物体上验证，而手柄是被追踪设备、mesh 完美、纹理特定，**它证明的是"锚定运行时"好，没证明"感知"能泛化到日常物体**。

补救（强烈建议，最便宜有效）：给日常物体补一组**不需要 6DoF GT 的质量代理指标**，现有 eval 流水线已能产出：

- **静止 jitter / 屏幕空间抖动**：让被试"拿稳别动"几秒，直接测输出方差，无需 GT 位姿。
- **可靠性分分布**（`reliability_score`）：纯系统输出。
- **跟踪连续性**：失锁帧占比、Unity `reacquire/reset` 命令触发率。
- **静止优先先验有效性**：静止段输出位移，静止优先先验应将其压到近零。

这样"手柄上的硬精度 GT + 日常物体上的免 GT 稳定性代理"两轨合起来，泛化故事才闭环：既证明运行时质量，又证明感知对开放物体可用。

- 三维主线（open / deployable / general-purpose / stable）是 value proposition，不是能力勾选表。不要回退到"五维能力矩阵 + 首个全 ✓"的写法——那种断言会被任一次平台 SDK 更新击穿，也容易被指 cherry-pick。需要对照时，写成沿三维度的 design-space 取舍讨论。
- “open / deployable”范围必须收窄：指无需物理标签、专用深度硬件、逐物体离线训练；**不等于头显端独立运行**。当前感知跑在外部消费级 GPU（5080 ~5fps / 5090 ~12fps）并经 ZMQ/NATS 异步通信，limitations 必须保留"外部算力依赖"，不要让读者误读成"Quest 即插即用"。
- “纯视觉”只修饰目标物体位姿估计链路。不要写成整个系统完全不依赖头显 SLAM、IMU 或平台追踪。
- Python 不输出 world pose；world anchor 只在 Unity 端通过 `frame_id` 回查得到。
- arrival-time mapping 是诊断对照，不是正式路径。
- 静止优先先验（static lock）是 regime-switching 稳定器，不是普通低通滤波。
- 当前代码没有逐帧跳变、阶段或近期拒绝子分，也没有旧 Gate/Estimator/Output 三模块结构。
- 当前 JSONL 输出字段是 `has_output_pose/output_pos/output_rot`，静止锁状态字段是 `latest_static_locked`；report 里的 `stable_rows` 只是统计名。

## 审稿风险

- 与平台能力的对比必须投稿前重新联网核实。不要依赖旧说法，例如“平台完全不支持动态物体”这类容易被新 SDK 击穿的断言。
- 与 Vision Pro / Meta / Vuforia / Azure 等系统对比时，优先做能力维度和系统假设对比；跨设备定量比较只能谨慎呈现。
- 如果使用 controller SDK pose 作为 GT，要说明它与头显共享追踪系，只能隔离视觉 pose-to-anchor 栈，不能暴露头显 SLAM 的共模误差。
- 定量精度只在手柄单物体上有 GT，而手柄是被追踪设备、mesh 完美、纹理特定。必须用日常物体的免 GT 代理指标（见《评估两轨结构》）补上感知泛化证据，否则"跨多类日常物体"的开放性主张缺乏定量支撑。
- 过滤器对比最好给 Pareto 或多参数扫描，不要用单点结果宣称“优于 One Euro / Kalman”。
- 用户实验需要事先明确任务、样本量依据、主观量表和统计检验方式。

## 投稿前清单

- [x] 把正文从"四层协同架构 / 五维能力空白"骨架收口到三维主线：旧四层降级为 Object Anchoring Runtime 内部结构。（已完成：v4.tex 第 3 章「系统流程」按对象感知/对象锚定两段式重构，Runtime 内部结构为时间对齐/质量评估门控/锚定策略/静止优先先验/生命周期状态机。讨论、结论章已对齐三维主线。）
- [x] 按代码事实文档更新方法章节公式和字段名。（已完成：v4.tex 第 3 章含 15 个编号公式，术语与字段已与代码事实文档和本文术语基准表对齐。）
- [ ] 完成至少一轮正式真机 session，并生成 report。
- [ ] 核对相关工作和平台能力的最新状态。
- [x] 补齐正文引用，移除临时 `\nocite{*}`。（已完成：v4.tex 相关工作前两小节补全 15 处引用，移除 `\nocite{*}`，参考文献从 46 收敛到正文实引的 30 条。）
- [ ] 扩展物体集到覆盖矩阵：补 1 个带操作复杂度的设备（撑"虚拟说明书附着"）+ 1 个强纹理物体（验证 `s_rep`）；缺模型的用 Image-to-3D 生成。
- [ ] 给日常物体跑免 GT 代理指标（jitter / reliability 分布 / 失锁率 / 静止优先先验位移），与手柄定量轨配套。
- [ ] 在评估章显式写出"手柄定量 + 日常物体定性与代理"的两轨结构，把单物体 GT 缺口讲成设计选择。
- [ ] 准备 supplementary video：时间对齐 vs 到达时刻对照（`frame_aligned_raw` vs `arrival_time_raw`）、静止优先先验、遮挡/出视野恢复、baseline 对比。
