# EgoAnchor：IEEE VR 2027 论文重构方案与初稿说明

## 1. 结论先行：论文应被定义为什么

这篇论文不应被包装成“一个更准的 6DoF 位姿估计算法”，也不应被写成“把若干视觉模型串起来的工程 pipeline”。最有竞争力、也最符合现有证据的定位是：

> **EgoAnchor 是一个 observation-to-anchor runtime：它把异步、低频、质量不均、属于历史采集时刻的相机系 6DoF 位姿，转换为 MR 应用可持续消费的世界系动态物体锚点。**

建议标题：

**EgoAnchor: From Asynchronous 6-DoF Pose Estimates to Stable Dynamic Object Anchors in Consumer Mixed Reality**

可选更短标题：

**EgoAnchor: A Runtime for Stable Dynamic Object Anchoring in Consumer Mixed Reality**

核心句必须在摘要、引言第三段、贡献列表、讨论第一段和结论中重复出现，但每次承担不同功能：

- 摘要：定义问题和系统结果。
- 引言：指出“pose estimate is not yet an MR anchor”。
- 贡献：强调运行时契约，而非视觉基础模型本身。
- 讨论：说明为何同候选流的运行时比较比跨平台黑盒比较更能支撑机制主张。
- 结论：回到“动态锚定是一项完整运行时行为，而非离散位姿快照”。

## 2. 当前稿件的主要问题

### 2.1 贡献中心不稳定

当前文稿同时强调视觉 pipeline、VCD 评分、Kalman、插值、StaticLock、生命周期、跨端通信和用户信任。每项都写得较重，导致审稿人可能得出“组件很多，但单项创新有限”的判断。

重构后应形成主从关系：

1. **主贡献：observation-to-anchor runtime contract。**
2. **关键机制：capture-time alignment、admission、temporal synthesis、StaticLock/lifecycle。**
3. **感知后端：可替换的 observation producer，不作为主要算法贡献。**
4. **VCD：运行时 admission signal，不声称为概率校准器或新的通用 pose metric。**

### 2.2 方法过长，评价证据被淹没

VCD 的颜色、深度、IQR 自适应、全部阈值，以及 StaticLock 四路释放机制目前占用过多主文篇幅。对 9 页上限的 IEEE VR 系统论文，这会直接挤压评价和讨论。

主文保留：

- 一条 VCD 总公式和三个分量的语义。
- capture-time world transform 公式。
- delayed Linear/SLERP 的目标时间定义。
- StaticLock 的进入、退出原则和状态图。
- lifecycle 的状态语义。

移入补充材料：

- 所有具体阈值及调参过程。
- VCD 通道级公式、腐蚀、IQR 和容差细节。
- Kalman 的逐轴矩阵和异常重置规则。
- StaticLock 的 CUSUM 完整公式和所有自适应参数。
- 网络消息定义、完整软件版本、额外工程审计。

### 2.3 “毫米级精度”必须更审慎

现有受控评价使用 Quest 控制器 SDK 参考，而非独立光学真值。最安全、最准确的表述是：

- **platform-relative millimeter-scale behavior**；
- **0.82 mm median centered static translation leakage**；
- **9.12 mm median lag-aligned dynamic translation RMSE**。

不建议直接写：

- “达到 Quest 3 毫米级真值精度”；
- “绝对毫米级跟踪”；
- “消除了动态配准误差”。

原因是平台参考具有内部预测、滤波和共同漂移；lag-aligned RMSE 还移除了相位差，不能替代 current-time registration error。

### 2.4 当前稿件混用了“已完成结果”和“计划书语态”

实验三段落中仍存在“结果待回填”“计划招募 24 人”等表述，后文却已经报告完整结果。必须全部改为过去时，并删除协议阶段的冗长辩护。主文只需呈现：设计、任务、测量、分析、结果和解释边界。

## 3. 最强叙事链

整篇论文应围绕四个连续问题展开：

### 问题 A：为什么位姿估计不等于锚点

异步视觉位姿存在三个缺口：

1. **时间语义错误**：位姿属于采集时刻，而非到达时刻。
2. **更新风险**：形式合法的候选仍可能是有害更新。
3. **输出语义缺失**：观察之间、静止期、遮挡期和恢复期没有定义。

### 问题 B：EgoAnchor 如何填补这些缺口

- Capture-time alignment：恢复历史观测的世界坐标语义。
- VCD admission：避免明显错误观测污染状态。
- Kalman + delayed Linear/SLERP：在已到达控制点之间生成连续轨迹。
- StaticLock + lifecycle：显式定义静止、运动开始、遮挡、冻结和恢复行为。

### 问题 C：每个机制贡献了什么，代价是什么

- Capture-time alignment 显著降低头动泄漏。
- StaticLock 把静止中心化误差从 13.73 mm 降至 0.82 mm，但有起动转换成本。
- 历史插值在约 360 ms 有效滞后下得到 8.93 mm 中位 lag-aligned RMSE；平滑外推把滞后降至约 305 ms，却把误差推高到 45.64 mm。
- VCD 的 risk--coverage 曲线支持其作为排序和接纳信号，但不等价于正确概率。

### 问题 D：这些系统差异是否抵达用户

用户研究必须给出有边界的结论：

- 显著改善：静止稳定、位置正确、恢复一致、依赖意愿、稳定--响应平衡。
- 未检出差异：运动附着、姿态一致、AQ 交互质量。
- 15/24 总体偏好 EgoAnchor；18/24 更信任其标注。
- 7 名参与者的偏好与信任选择不一致，说明“喜欢使用”和“愿意依赖空间标注”不是同一构念。

这条叙事比“所有指标全面优于基线”更可信，也更符合顶会审稿人的预期。

## 4. 推荐的 9 页分配

IEEE VR 2027 主文允许 4--9 页正文、图表和附录，不含参考文献；参考文献最多 2 页。建议直接按 9 页设计。

| 部分 | 页数目标 | 内容 |
|---|---:|---|
| 标题、摘要、Teaser、引言 | 1.15 | 问题、缺口、系统一句话、三层评价、贡献 |
| 相关工作 | 0.75 | 平台对象锚定、6DoF pose、XR latency/filtering |
| 系统概览与感知契约 | 0.85 | pipeline、observation tuple、VCD 一条公式 |
| 锚定运行时 | 1.25 | alignment、admission/state、temporal synthesis、StaticLock/lifecycle |
| 实现 | 0.35 | Quest 3 + workstation + communication，禁止堆版本号 |
| 实验 1 | 1.45 | 设置、指标、主结果图、紧凑表、trade-off |
| 实验 2 | 0.95 | 四项归因图、关键倍率和边界 |
| 实验 3 | 1.45 | 设计、主要量表、结果、选择；细节放补充 |
| 讨论、局限、结论 | 0.80 | 系统启示、适用任务、reference 限制、部署限制 |
| **合计** | **9.00** | 参考文献另计 |

方法不能“过少”，但必须只保留足以支撑新颖性、可复现性和后续实验解释的内容。本文的证据优势在评价，因此方法约 2.1 页、评价约 3.8 页是合理比例。

## 5. 三个实验的角色必须严格分离

### 实验 1：完整系统行为

回答：应用实际看到的锚点怎样表现？

主指标：

- static world consistency；
- rest stability；
- dynamic fidelity；
- effective lag / current-time error；
- transition cost；
- occlusion behavior。

重要写法：把 lag、lag-aligned residual 和 current-time error 分开。禁止用 lag-aligned RMSE 单独宣称实时跟随更准确。

### 实验 2：机制归因

回答：实验 1 中的行为由什么造成？

四项足够：

1. capture-time vs arrival-time；
2. StaticLock on/off；
3. VCD risk--coverage；
4. Linear/SLERP vs extrapolation（Hermite 作为次要对照）。

不要再增加大量小消融，否则会稀释核心信息。

### 实验 3：感知效用和信任

回答：实验 1 的稳定性、恢复和响应权衡是否能被用户感知，并影响依赖意愿？

主文只保留七项定制结局及五项量表结果的概要。完整题目、翻译、反向计分、缺失规则、精确 Wilcoxon 细节、全部信度和分物体描述移至补充材料。

## 6. 图表重构方案

### Figure 1：Teaser

推荐横向三段式：

1. 左：用户在 Quest 3 passthrough 中操作鼠标/订书机/手柄。
2. 中：同一动作三个关键时刻，显示 Arrival、One-Euro、EgoAnchor 轮廓相对真实物体的差异。
3. 右：三条 headline result：0.82 mm static leakage；9.12 mm lag-aligned dynamic RMSE；18/24 trust EgoAnchor。

Teaser 不要重复 pipeline。它的任务是让审稿人在 10 秒内理解“问题是什么、系统做什么、结果是否重要”。

### Figure 2：Pipeline

必须显式画出三个时间点：

- image capture $t_f$；
- candidate arrival $t_a$；
- render query $t_r$。

推荐两层泳道：perception backend 和 headset runtime。把 `frame_id` 与历史设备轨迹缓存画在层间边界，这是本文真正的系统接口。

### Figure 3：系统主结果

现有四面板数据可以保留，但应遵循：

- raw episode points + median/IQR；
- error 和 residual jitter 的定义写在 caption；
- 不把真实运动的帧间位移叫 jitter；
- 在正文中明确双纵轴只是排版压缩，不能直接比较左右轴数值。

已生成四个独立 panel，可由 LaTeX 组合。

### Figure 4：组件归因

四面板：alignment、StaticLock、VCD risk--coverage、temporal strategy。

重要改动：时序策略图不得静默裁掉大于 32 mm 的片段。建议用 log y 轴显示全部点，直观看到 extrapolation 的低 lag / 高 error 权衡。已生成的重构图采用该方式。

### Figure 5：用户研究

最终稿优先使用 participant-level paired dot/slope 或 raincloud，而不是柱状图。当前上传工作簿只有汇总结果，因此包内先生成 median paired difference + IQR 的 provisional forest plot。拿到原始参与者级得分后，应替换为：

- 左：七项主要结局的 participant-level paired differences；
- 右：五项已发表量表；
- 视觉上区分显著与未显著，不用星号堆叠替代效应量。

### Replay grid

当前 replay grid 已能清楚展示 Passthrough、Quest Reference、Arrival、Capture、One-Euro、EgoAnchor，并使用六个等间隔采样时刻。它适合补充材料或视频缩略图。主文若空间紧张，建议只保留 3 个关键时刻并放入 teaser，而不是再占用一幅完整单栏图。

## 7. 数据审计：当前 Tex 中必须修正的具体错误

以下不是语言偏好，而是当前稿件与上传分析工作簿之间的实质不一致。

| 项目 | 当前 Tex | 分析工作簿 | 处理 |
|---|---|---|---|
| 性别 | 女 9、男 15 | 女 12、男 12 | 改为 12/12 |
| 年龄 | 24.8 ± 3.1 | 27.083 ± 4.452 | 改为 27.08 ± 4.45 |
| VR/MR 经验 | 3/12/9 三档 | 6/10/4/2/2 五档 | 按原类别报告或压缩时说明合并规则 |
| 实物 AR/MR 经验 | 8/11/5 | 12/6/4/2 | 改正 |
| 候选率 | 9.31 vs 9.28 Hz | 12.853 vs 12.861 Hz | 改正；区分实验协议和服务器内部发布率 |
| VCD 接纳率 | 94.2% vs 94.5% | 88.611% vs 88.201% | 改正 |
| 输出可用率 | 97.8% vs 98.1% | 99.099% vs 99.057% | 改正 |
| StaticLock | 激活率 31.7% | 212 次进入/72 区块，无激活率 | 删除“31.7%”并报告事件计数或重新从原始日志定义比例 |
| 遮挡状态 | 在 Coasting/Frozen 间过渡 | 72/72 均 FrozenUncertain；0 Coasting、0 Lost | 改正 |
| 总体偏好 | 18 EgoAnchor / 4 One-Euro / 2 无偏好 | 15 / 4 / 5 | 改正 |
| 信任选择 | 19 / 3 / 2 | 18 / 1 / 5 | 改正 |
| 偏好强度 | 5.00 [4,6] | 4.00 [3,5]，N=19 | 改正 |
| AQ-EQ alpha | 0.89 | 0.768 / 0.769 | 按方法报告或移至补充 |
| AQ-IQ alpha | 0.88 | 0.504 / 0.892 | 不能概括为高信度；讨论适配量表稳定性 |
| TiA alpha | 0.91 / 0.87 | 0.792/0.751 和 0.565/0.769 | 改正；同时报告 omega |
| S-TIAS alpha | 0.92 | 0.672 / 0.697 | 改正 |
| 实验语态 | “计划招募”“结果待回填” | 数据已经完成 | 全部改为过去时 |

此外，当前 Tex 将“服务器 TRACK 时间、候选发布率”和“用户研究日志中的候选率”混在同一叙事中。二者测量区间不同，不能择一覆盖。建议只在主文报告端到端应用可见的时间分解；服务器内部 profile 放补充材料。

## 8. 需要保留的统计优点

当前分析有几项做法值得保留：

- 区块级结局先在参与者内跨三个物体取均值，再作配对推断。
- 定制条目不强行合成总分。
- 七项主结局与五项量表结局分两个 Holm 家族。
- exact conditional Wilcoxon 明确删除零差、处理中秩，并说明“exact”不是无假设。
- 分物体结果只作描述，不做 21 次额外显著性检验。
- 报告 matched rank-biserial correlation 及区间。

主文无需解释所有计算细节，但必须保留分析单位、家族定义、效应量和“未显著不等于等价”的边界。

## 9. 最可能的审稿人质疑与回答策略

### “只是把现有模型拼起来”

回答：视觉模型不是贡献；贡献是时间语义、接纳、连续输出和生命周期构成的 observation-to-anchor contract，并通过同候选流消融证明运行时机制的因果作用。

### “为什么不与 Meta/Apple/Vuforia 做数值比较”

回答：不同平台支持对象、内部观测、预测、过滤和坐标语义不一致，无法在同一目标、同一候选、同一参考下做机制归因。平台方案应在相关工作中定位；核心比较采用同 Quest、同候选流、同时间线。

### “StaticLock 只是冻结，当然抖动小”

回答：因此同时报告中心化稳定、绝对注册护栏、起动转换和动态/current-time 指标；用户研究也把“稳定”和“位置正确”分开，避免冻结错误位姿获得虚假优势。

### “lag-aligned RMSE 掩盖了高延迟”

回答：有效 lag、lag-aligned residual 和 current-time error 分开报告，明确结果是稳定性--响应性权衡，不将相位对齐后的误差解释为实时配准误差。

### “用户研究指标过多、量表适配过度”

回答：主文以七项预先冻结的应用侧结局为主，已发表量表作为独立家族；定制条目不计算内部一致性。低信度适配量表如实报告，不进行强构念主张。

## 10. 提交前的硬性事项

- 使用 double-blind VGTC 模板；删除作者、单位、路径、项目页、可识别视频信息。
- 主文严格控制在 9 页，参考文献不超过 2 页。
- 摘要需在正式论文截止前一周提交。
- 人体实验的 ethics/IRB 状态必须与 PCS 和文稿一致；若应审批而未审批，存在 desk rejection 风险。
- IEEE VR 2027 要求披露 AI 生成内容。披露必须准确说明工具、涉及部分及使用程度，同时避免在双盲稿中泄露作者身份。
- 补充材料建议包括：完整阈值、状态机、参数表、全部 episode 数据、current-time RMSE、起停过冲、量表条目与翻译、全部信度、分物体描述、视频。

## 11. 本包内文件

- `egoanchor_ieeevr2027_draft_v1.tex`：英文初稿，已按上述主线重写并修正实验三关键数据。
- `figures/figure2*.pdf`：实验 1 四个独立面板。
- `figures/figure3*.pdf`：实验 2 四个独立面板。
- `figures/figure4_exp3_primary_effects.pdf`：实验 3 主结局暂用汇总效应图。
- `figures/figure5_exp3_scale_effects.pdf`：实验 3 量表暂用汇总效应图。
- `make_figures.py`：从两个上传工作簿复现上述图的脚本。

该初稿是“可继续迭代的英文论文骨架”，不是可直接提交版本。提交前还需要补齐：正式 pipeline、teaser、实验场景图、伦理声明、独立 bibliography、参与者级用户研究图、端到端 latency decomposition 和匿名化审计。
