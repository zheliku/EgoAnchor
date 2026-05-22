# EgoAnchor IEEE VR 2027 论文架构规划

日期：2026-05-23  
目标：IEEE VR 2027 papers track  
状态：目标投稿版本蓝图。本文档允许把后续计划实现的可靠性感知控制、恢复实验和任务实验写入论文主线；但最终投稿前，所有“已实现”“已验证”“显著提升”等表述必须由代码、日志、实验数据和图表支撑。

## 1. 投稿约束

IEEE VR 2027 官网已经公布会议时间和地点：2027 年 2 月 27 日至 3 月 3 日，澳大利亚墨尔本。2027 papers CFP 目前尚未公开，因此本规划暂以 IEEE VR 2026 官方 papers CFP 作为最近一届的规则参考；2027 CFP 发布后必须复核。

从 2026 CFP 推导出的写作约束：

- 论文应定位为 AR/MR/XR 技术系统论文，而不是纯 CV pipeline 论文。
- 最终稿应使用英文、双盲、VGTC 模板。
- 近似页数目标：正文、图、表 4 到 9 页，参考文献不超过 2 页。
- 论文必须通过 benchmark、对比、用户研究或等价证据验证贡献。
- 相关工作必须认真覆盖 VR/AR/MR/3DUI 文献；如果主要是 CV 引用，容易被认为不适合 IEEE VR。
- 如果做人类参与者实验，需要提前完成伦理审批、告知同意、人口统计信息与数据处理说明。
- 论文、代码、图像或文字中使用 AI 工具的部分，最终需按 IEEE 规则披露。

时间推断：2026 papers deadline 是 2025 年 9 月，对应 2026 年 3 月会议；因此 2027 截稿大概率在 2026 年 9 月附近，但目前未确认。内部应按 2026 年 8 月完成实验和全文冻结来推进。

后续需复核的官方链接：

- IEEE VR 2027 官网：https://ieeevr.org/2027/
- IEEE VR 2026 papers CFP 参考：https://ieeevr.org/2026/contribute/papers/

## 2. 论文配置记录

| 参数 | 建议值 |
|---|---|
| 主题 | 面向 passthrough MR 的 frame-aligned real-object anchoring |
| 研究问题 | 如何把异步返回的 camera-space 6DoF object pose observation 转化为稳定、世界一致、可恢复的 MR real-object anchor？ |
| 论文类型 | IEEE VR 技术/系统论文，采用 IMRaD + 系统架构混合结构 |
| 学科定位 | VR/AR/MR、3DUI、XR tracking/sensing、XR software systems |
| 目标会议 | IEEE VR 2027 |
| 引用格式 | IEEE/VGTC bibliography style |
| 输出格式 | LaTeX，VGTC 模板 |
| 当前写作语言 | 中文规划和中文初稿；最终转换为英文投稿稿 |
| 已有材料 | v3 代码、v1/v2 历史链路、中文大纲、旧 paper-plan、协议与 AGENTS 记录 |
| 缺失材料 | VR/MR 文献矩阵、定量实验结果、实验日志/脚本、最终图表、supplementary video |
| 当前工作模式 | 论文架构规划 + 实现到证据的路线图 |

## 3. 核心定位

不要把 EgoAnchor 写成：

> 我们把 YOLOE、Fast-FoundationStereo 和 FoundationPose 集成到了 Unity。

应写成：

> 可用的 MR real-object anchor 不会从准确的单帧 camera-space pose 中自然产生。它需要观测帧时间对齐、低时延 latest-only 传输、度量几何观测，以及能抵抗噪声、延迟、间歇丢失和错误更新的 anchor 生命周期控制。

目标论文主张：

> EgoAnchor 说明，异步 6DoF pose stream 可以通过 frame-aligned reprojection 和 reliability-aware anchor update control，被转化为稳定、可恢复、世界一致的 MR object anchor。

保底主张：

> EgoAnchor 说明，外部 6DoF object pose tracking 要在 passthrough MR 中可用，必须按观测帧对应的 capture-time camera pose 完成世界坐标映射，并用 anchor-centric metrics 而不是单帧 pose accuracy 来评价系统。

## 4. 推荐题目

目标题目：

> EgoAnchor: Frame-Aligned 6DoF Object Pose Tracking and Reliability-Aware Anchor Control for Passthrough Mixed Reality

更完整的描述性题目：

> EgoAnchor: Frame-Aligned 6DoF Object Pose Tracking and Reliability-Aware Anchor Control for World-Consistent Real-Object Anchoring in Passthrough Mixed Reality

如果 reliability-aware controller 没有足够实验支撑，则退回：

> EgoAnchor: Frame-Aligned 6DoF Object Pose Tracking for World-Consistent Real-Object Anchoring in Passthrough Mixed Reality

## 5. 贡献策略

### 目标贡献

这是 IEEE VR 2027 目标投稿版本的贡献组合，默认后续会补齐 controller、恢复机制和消融实验。

1. 提出 passthrough MR 中的 pose-to-anchor 问题表述，说明 camera-space 6DoF pose accuracy 本身不足以保证稳定、世界一致的 real-object anchoring。
2. 提出 frame-aligned、reliability-aware 的动态锚定框架：每个 camera-space pose 通过 capture-time camera frame 映射到世界坐标，并在噪声、延迟和间歇丢失条件下控制 anchor 更新。
3. 实现 EgoAnchor 端到端系统：连接 Quest/Unity 头戴双目采集、Python 外部对象级感知、ZMQ Protobuf 数据面、NATS Protobuf pose/command 消息面，以及 Unity world-anchor 应用。
4. 建立 anchor-centric evaluation：评价 world-space anchor error、head-motion-induced slip、jitter-lag tradeoff、端到端时延、遮挡/出视野恢复，以及可选任务可用性。

### 保底贡献

若 reliability-aware lifecycle controller 最终无法完成，则论文退回到更保守的三条贡献：

1. pose-to-anchor 问题表述与 frame-aligned anchoring 方法。
2. EgoAnchor 端到端 passthrough MR real-object anchoring 系统。
3. 以 world-space anchor quality 为中心的评估协议。

### 贡献门槛

| 主张 | 当前状态 | 投稿前证据 |
|---|---|---|
| frame-aligned pose-to-anchor mapping | Unity v3 已通过 `FramePoseHistory` 和 `CameraPoseFrameAligner` 实现 | fake-pose 单测、Quest 实机日志、可视化视频 |
| ZMQ data plane + NATS message/command plane | v3 skeleton/runtime 已有 | 端到端 smoke log、断连/失败诊断 |
| low-pass/Kalman stable anchor baseline | Unity v3 已有 processors | jitter/lag 定量对比 |
| Python perception reliability score | 内部 scoring 已有，但未进 `PoseResult` proto | 追加 proto 字段、日志验证、Unity 侧消费 |
| reliability-aware anchor lifecycle/state machine | 目标贡献，待实现 | controller、阈值、状态日志、消融实验 |
| task/user benefit | 尚未测量 | 任务 benchmark 或合规 human study |

## 6. 论文结构

目标长度：8.5 到 9 页正文，不含参考文献。当前先写中文大纲，最终转英文。

### Abstract

摘要要直接说明 pose-to-anchor 问题、EgoAnchor 方法、系统机制和核心结果。内部草稿可写入 reliability-aware control；最终投稿必须有对应实验结果。

### 1. Introduction

目的：让 IEEE VR 读者相信“真实物体锚定”是 XR 问题，而不是普通 CV tracking 问题。

关键推进：

- MR 应用消费的是 stable anchor，不是 raw camera-space pose matrix。
- XR spatial anchor 和平台 object tracking 不能完全解决外部 pose stream 驱动的任意真实物体锚定。
- 6DoF pose tracking 文献主要评价 camera-space pose accuracy；MR 需要的是 head motion、delay、failure 下的 world-space anchor quality。
- 提出 gap：异步感知和 MR 渲染之间缺少时间对齐、坐标语义、更新控制和恢复生命周期。
- 给出贡献。

建议图：teaser 展示 Quest passthrough 采集、Python pose service、frame_id camera pose lookup、Unity world anchor。

### 2. Related Work

相关工作必须 VR/MR 优先，再进入 CV。

2.1 AR/MR 中的 spatial anchor、object anchor 与真实物体注册  
讨论 world/spatial anchors、image/object anchors、fiducials、model targets、平台约束、object-centric MR interaction。

2.2 6DoF object pose estimation and tracking  
讨论 model-based pose、RGB-D/stereo pose、register/track/re-register、数据集和 benchmark。FoundationPose 等是 enabling components，不是本文主贡献。

2.3 XR 中的异步感知、时延、稳定性和预测  
讨论 low-latency sensing、distributed perception、asynchronous tracking、prediction/filtering、perceived registration stability。

收束句：已有工作解决了若干局部问题，但尚未把外部异步 6DoF pose stream 到 passthrough MR anchor 的完整 pose-to-anchor 问题作为主对象来评价。

### 3. Problem Definition and Design Goals

目的：清楚定义本文研究对象。

核心变换：

```text
Camera-space observation:  C_T_O(t_capture)
Capture-time camera pose:  W_T_C(t_capture)
World anchor output:       W_T_O(t_capture) = W_T_C(t_capture) * C_T_O(t_capture)
```

明确错误替代方案：

```text
Arrival-time mapping: W_T_C(t_return) * C_T_O(t_capture)
```

设计目标：

- World consistency：使用观测帧对应的 camera pose，而不是结果回包时的 camera pose。
- Stability：减少 jitter，并避免错误 pose jump。
- Recoverability：处理遮挡、目标丢失、reset 和 reacquire。
- Diagnosability：记录 frame id、时间戳、stage、depth/mask quality、pose source 和 anchor state。

### 4. EgoAnchor Method

4.1 Pose observation pipeline  
说明 Quest stereo input、camera info、K remapping、prompt-guided segmentation、stereo depth、model-based pose tracking。措辞要强调系统协同设计，不要宣称提出新的网络结构。

4.2 Frame-aligned anchor mapping  
这是最稳的核心方法。说明 `frame_id`、capture-time left camera world pose history、OpenCV camera coordinates、Unity camera coordinates、world-pose composition。

4.3 Latest-only asynchronous transport  
说明为何高频 stereo/camera_info 走 ZMQ Protobuf data plane，而 pose/status/heartbeat/commands 走 NATS Protobuf message/command plane。把 latest-drain 和 stale-frame avoidance 与 anchor 低时延目标关联起来。

4.4 Reliability-aware anchor control  
这是目标论文中 frame alignment 之后最重要的方法层。controller 根据 pose reliability、frame-history validity、pose innovation、result age、heartbeat/status 等信息，在 Update、Smooth、Coast/Hold、Frozen/Lost、Reacquire 之间切换。raw、low-pass、Kalman 输出保留为 ablation baselines。

4.5 Diagnostics and command lifecycle  
说明 reset/reacquire/control 的 request-reply ack 只代表 accepted/rejected，不代表执行完成；真正结果通过 status/pose events 反映。

### 5. Implementation

实现节要短而具体，不写成项目说明书。

包含：

- Quest/Unity front end：stereo capture、camera_info、frame pose history。
- Python v3 runtime：single-owner perception pipeline、command queue/executor、pose publication。
- Protocol：`subjects.v1.json`、Protobuf、ZMQ data plane、NATS message/command plane。
- Unity anchor runtime：`PoseResultReceiver`、`PoseToAnchorRuntime`、`CameraPoseFrameAligner`、raw/stable processors、后续 policy controller。
- 硬件和软件：Quest 型号、PC GPU、Unity、Python、CUDA、TensorRT 版本。

必须同步：旧稿中出现的 ZMQ + MessagePack 要更新为 v3 的 ZMQ Protobuf + NATS Protobuf。

### 6. Evaluation

评估围绕 RQ 组织，而不是围绕模块列表组织。

RQ1：frame-aligned mapping 是否能在 head motion 和 latency 下提升 world-space anchoring？  
主对比：arrival-time mapping vs frame-aligned mapping。

RQ2：smoothing 和 reliability-aware update policy 如何影响 anchor stability 和 lag？  
主对比：raw frame-aligned vs low-pass vs Kalman vs reliability-aware controller。

RQ3：EgoAnchor 在遮挡、出视野和重新获取条件下如何表现？  
主对比：always-update/no-recovery vs hold/coast/reacquire lifecycle。

RQ4，可选：更稳定的 anchor 是否改善任务表现或主观稳定感？  
主对比：baseline vs EgoAnchor full，任务可以是 object labeling/alignment 或 object confirmation。

### 7. Results

按论文主张组织结果：

- frame alignment 降低 head-motion-induced anchor slip。
- stable anchor processors 降低 jitter，同时报告 lag tradeoff。
- reliability-aware lifecycle 抑制大幅错误跳变，并改善恢复行为。
- end-to-end latency 可解释且有分模块 breakdown。
- 若有任务/用户实验，展示数值指标之外的实际可用性收益。

### 8. Discussion and Limitations

必须诚实：

- 系统假设目标是已知刚体，并有可用 3D model。
- 外部 GPU inference 带来时延和部署复杂度。
- 静止物体的 hold 策略在物体出视野后被移动时会失效。
- 反光、小物体、纹理贫乏、分割失败、stereo depth 质量低仍是困难场景。
- 多物体锚定和长期持久化锚定是后续工作，除非最终实现。

### 9. Conclusion

回到核心观点：MR object anchoring 的质量取决于 time alignment、coordinate semantics、update policy 和 recoverability，而不只是 pose accuracy。

## 7. 论证蓝图

中心论点：

> EgoAnchor 证明，passthrough MR 中的 world-consistent real-object anchoring 应被视为 pose-to-anchor 系统问题：camera-space pose observation 只有经过 capture-time camera pose 对齐、stale-frame 控制和 anchor-centric evaluation，才可能成为可用的 MR anchor。

| 子论点 | 需要的证据 | 可能反驳 | 回应策略 |
|---|---|---|---|
| per-frame pose accuracy 不足以解释 MR anchoring | head motion 下 arrival-time mapping 误差增大，即使 camera-space pose 相同 | 好的 pose tracker 应该足够 | 证明问题来自 coordinate-time mismatch，而不是 pose 网络本身 |
| frame alignment 是 world consistency 的必要条件 | 对比 `t_capture` 与 `t_return` transform | XR runtime 已有 pose prediction | 外部感知 pose 绑定的是图像采集时刻，不是渲染时刻 |
| latest-only transport 适合实时 anchor | latency 与 stale-frame drop 统计 | 丢帧浪费信息 | 对实时 anchor 而言，过时 pose 往往比缺失 pose 更危险 |
| reliability-aware anchor behavior 提高可用性 | jitter、lag、jump suppression、recovery、任务指标 | filter 会增加延迟或隐藏错误 | 报告 stability-lag tradeoff，并保留 raw baseline |
| EgoAnchor 是 XR 系统贡献，不是 CV 拼装 | 系统闭环、VR/MR 文献、anchor-centric 指标 | 只是组合已有模块 | 贡献在 time/coordinate/update contract 以及 passthrough MR 评价 |

## 8. 实验矩阵

### Baselines

| Baseline | 目的 |
|---|---|
| Arrival-time mapping | 证明使用结果到达时刻 HMD pose 会导致错位 |
| Frame-aligned raw | 隔离 frame alignment 效果，不引入平滑 |
| Frame-aligned + low-pass | 简单稳定性 baseline |
| Frame-aligned + Kalman | 当前 Unity v3 已有的强一点 temporal baseline |
| Frame-aligned + reliability-aware controller | 目标最终方法 |
| No recovery / always update | 展示遮挡和坏 pose 下的失败行为 |

### Conditions

| 条件 | 测试内容 |
|---|---|
| 静态观察 | 基础精度和 jitter floor |
| 慢速自然头动 | 日常 MR 使用 |
| 快速 yaw/translation | head-motion-induced slip |
| 部分遮挡 | 坏观测和缺失观测 |
| 出视野后返回 | hold/coast/reacquire 行为 |
| 光照/材质变化 | perception robustness |
| 多物体，可选 | 单物体之外的泛化 |

### Metrics

| 指标 | 定义 |
|---|---|
| World-space anchor error | estimated world anchor 与 ground truth world object pose 的误差 |
| Head-motion-induced slip | 静止物体在头动时的 apparent overlay displacement |
| World-space jitter | 静止物体下 stable anchor pose 的时间离散度 |
| Lag | 真实物体变化或有效 pose 变化到 stable anchor 响应之间的延迟 |
| End-to-end latency | capture 到 Unity apply 的时延及分模块 breakdown |
| Recovery success rate | 遮挡/出视野后恢复到有效 anchor 的比例 |
| Recovery time | 物体重新出现到 stable accepted anchor 的时间 |
| Rejection/jump suppression | reliability-aware controller 拒绝的大幅错误跳变数量与幅度 |
| Task completion/perceived stability | 可选任务实验指标 |

### Ground Truth 建议

最佳方案：外部 motion capture 或 tracked rigid body，同时获得 object 与 HMD/world 对齐。  
可接受方案：使用只用于评估、不用于 EgoAnchor runtime 的隐藏/临时 fiducial 或外部测量来获得静态物体 ground truth。  
弱方案：只有 overlay 视频和主观观察；不足以支撑 IEEE VR 强论文。

## 9. 图表计划

| 图表 | 要传达的信息 |
|---|---|
| Fig. 1 Teaser | 真实 passthrough 物体、虚拟 anchor overlay 和系统闭环 |
| Fig. 2 Problem diagram | `t_capture`、`t_return`、`t_render`，以及 arrival-time transform 为什么错 |
| Fig. 3 System architecture | Quest/Unity、ZMQ data plane、Python runtime、NATS message/command plane、Unity anchor runtime |
| Fig. 4 Frame alignment math | `frame_id -> capture-time camera pose -> world anchor` |
| Fig. 5 Anchor lifecycle/controller | Update/Smooth/Coast/Frozen/Lost/Reacquire |
| Fig. 6 Experiment setup | 物体、HMD/camera path、ground truth setup |
| Fig. 7 Main results | head motion 下 anchor error/slip |
| Fig. 8 Robustness results | 遮挡/出视野恢复时间线 |
| Table 1 System components | EgoAnchor 相对已有模块的新东西 |
| Table 2 Baselines and ablations | 条件、机制、验证的主张 |
| Table 3 Latency breakdown | capture、encode、network、perception、publish、Unity apply |

Supplementary video 应作为必要材料：展示 arrival-time vs frame-aligned、raw vs stable、occlusion/reacquire 和完整任务 demo。双盲提交前清理身份信息和元数据。

## 10. 文献策略

不要围绕 YOLOE/FFS/FoundationPose 来组织 related work。文献主线必须围绕 VR/MR gap。

搜索主题：

1. XR anchoring and registration：spatial anchors、world anchors、object anchors、model targets、fiducials、AR registration stability。
2. XR tracking/sensing systems：low-latency sensing、distributed perception、asynchronous tracking、prediction/filtering in XR。
3. 6DoF object pose estimation/tracking：model-based pose、RGB-D/stereo pose、register/track/re-register、recovery。
4. Egocentric and passthrough MR datasets/evaluation：head-worn cameras、object interaction、first-person tracking。
5. Stability and user perception：registration error、perceived object attachment、jitter/latency 下的 task performance。
6. Robust filtering and lifecycle control：Kalman、One Euro filter、innovation gating、track management。

示例搜索式：

```text
("mixed reality" OR "augmented reality" OR "passthrough") AND ("object anchoring" OR "object anchor" OR "spatial anchor" OR registration)
("virtual reality" OR "mixed reality" OR XR) AND ("tracking latency" OR "asynchronous sensing" OR "world locked" OR "registration error")
("6D object pose" OR "6DoF object pose") AND (tracking OR "re-registration" OR "RGB-D" OR stereo)
("egocentric" OR "head-mounted") AND ("object pose" OR "object tracking") AND ("mixed reality" OR AR OR XR)
```

纳入规则：每个 related-work 小节都应有 VR/AR/MR 文献或官方平台约束，不能只有 CV paper。CV paper 负责解释感知栈，不负责单独支撑 IEEE VR 相关性。

## 11. 实现路线与论文主张对应

规划假设：最终 IEEE VR 2027 论文可以把 reliability-aware control、恢复实验和可选任务评估作为目标内容写入架构。内部草稿中它们可以是计划中的方法；最终投稿前必须有实现和数据。

Priority 0：论文源文件卫生

- 将 v1/v2 表述更新为 v3：ZMQ Protobuf data plane + NATS Protobuf message/command plane。
- 修正 `2026-EgoAnchor/makefile` 当前仍默认编译 `template.tex` 的问题。
- 用已验证的 VR/MR 与 pose-tracking 文献替换 placeholder bibliography。

Priority 1：证据基础设施

- 加 experiment logging/replay：frame id、timestamps、pose result、anchor raw/stable、frame history hit/miss、processor/controller state。
- 加分析脚本：anchor error、jitter、slip、latency percentiles、recovery time。
- 建立 deterministic fake-pose/fake-frame replay，用于回归测试和生成图。

Priority 2：论文指标所需协议字段

- 给 `PoseResult` 非破坏性增加：`reliability_score`、`reliability_flags`、`depth_valid_in_mask`、`mask_area_ratio`、`pose_source`、`server_receive_mono_ms`、`server_publish_mono_ms`。
- 如评估需要，给 heartbeat/status 增加 camera_info readiness、dropped stale frames、queue length、generation 等字段。

Priority 3：Unity anchor policy

- 实现显式 anchor state machine 或 policy controller。
- raw、low-pass、Kalman、policy 输出必须可切换，以支持 ablation。
- 记录 accept/reject/hold/reacquire 原因。

Priority 4：技术实验

- 先跑 frame-alignment ablation，这是最核心证据，不依赖完整 reliability controller。
- 再跑 stability/filtering ablation。
- 再跑 occlusion/out-of-view recovery。

Priority 5：可选任务实验

- 只有在伦理要求满足后才收集 human data。
- 任务保持简单：在真实物体上对齐/确认标签或 bounding overlay，并加入头动和遮挡。
- 如果伦理审批赶不上，用 recorded trace benchmark 代替弱 informal user study。

## 12. Desk-reject 风险清单

| 风险 | 严重度 | 缓解 |
|---|---:|---|
| 论文读起来像 CV 模块拼装 | 高 | 以 pose-to-anchor、frame alignment、anchor metrics 和 VR/MR 文献开篇 |
| 宣称 reliability-aware control 但没有证据 | 高 | 内部架构可以写，投稿稿必须有 controller、ablation 和 log |
| 没有定量 ground truth | 高 | 建立可测量 object/HMD ground-truth setup |
| VR/MR 文献薄弱 | 高 | related work 必须覆盖 anchor、latency、registration、user experience |
| 双盲泄露 | 高 | 清理论文、视频、metadata、repo/path/ack 信息 |
| 人类实验没有伦理审批 | 高 | 先审批再招募；否则删除 human-study claims |
| 实现细节太多、论证太少 | 中 | 主文 claim-driven，代码细节放 supplementary |
| 过度使用 first claim | 中 | 文献验证前尽量避免 first，或用保守措辞 |
| 当前 bib placeholder 太多 | 中 | 投稿前必须换成可验证公开文献 |

## 13. 近期行动

1. 以 reliability-aware anchor-control paper 作为目标方案，frame-aligned system paper 作为 fallback。
2. 把 LaTeX 大纲更新为 v3 术语和目标论文结构。
3. 实现 logging/replay，并优先跑 frame-alignment ablation。
4. 明确 Unity controller 要消费哪些 reliability 指标，再追加 proto 字段。
5. 写 introduction 前先建立 related-work matrix。

建议内部里程碑：

| 时间窗口 | 里程碑 |
|---|---|
| 2026-05-23 到 2026-06-07 | 固定 claims、metrics、ground-truth setup、source matrix |
| 2026-06-08 到 2026-06-30 | 实现 logging、reliability fields、policy-controller MVP |
| 2026-07-01 到 2026-07-20 | 跑 frame-alignment、filtering、latency、recovery 实验 |
| 2026-07-21 到 2026-08-05 | 可选任务/用户实验或 recorded-trace benchmark |
| 2026-08-06 到 2026-08-25 | 写英文完整稿、生成图、制作 supplementary video |
| 2026-08-26 之后 | 内部 review、匿名化审查、citation audit、准备 rebuttal appendix |
