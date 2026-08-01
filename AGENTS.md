# AGENTS.md

后续 AI 接手本仓库任务时，必须先阅读文件顶部的 **用户手动维护要求**。未阅读前不得修改代码。

<!-- USER-MAINTAINED-REQUIREMENTS:BEGIN -->

## 用户手动维护要求

本区由用户手动维护，放在文件顶部，方便查看和修改。后续 AI 只能读取、遵循和引用，不得自行修改、删减、重排、润色、合并或迁移本区内容。只有用户明确要求修改时，才可以改动本区，并且只改用户指定的内容。

1. Python 侧按包级入口导入，不深层导入到具体模块文件。包内可以使用 `from .image_utils import fit_to_size, stack_stereo` 这类显式 re-export；包外使用 `from egoanchor.algorithms import ...`，不要写成 `from egoanchor.algorithms.xxx import ...`。不要使用包级懒导出。
2. 代码需要有充分的中文说明。`.toml` 配置的每个参数都要在同一行末尾写中文注释；类、成员变量和每个方法也要补充中文说明。
3. 命名保持清楚、克制，不要为了"完整"把名字写得过长。
4. 修改代码前先从项目整体判断影响范围，检查模块配合、引用关系和架构边界。不要只做局部补丁，也不要零散修补。
5. 先读懂项目和计划，再严格按计划实现代码。发现计划与项目事实冲突时，及时指出并说明影响。过程中有任何问题请及时和我讨论交流，如果遇到任何不合理的事情立刻和我报告。
6. 重构时不要兼容已废弃的旧代码、旧接口或旧路径。
7. 使用 Code Simplifier 优化项目代码；处理文档和语言表述时使用 humanizer-zh。
8. 处理复杂或大型任务时，请使用子智能体辅助，加快梳理、审查和验证。
9. 改动时直接在我的这个git分支改动，我能看见改动了哪些。我git有备份没有关系，不用担心
10. 每次操作完后记得更新AGENTS.md
11. 注意论文当前主稿路径是 `2026-EgoAnchor/`，使用 LaTeX 编写；最新中文工作稿为 `egoanchor_cn_ai_v8.tex`，文件名中的 `ai` 表示该版本使用 AI 辅助撰写。该稿目前尚不可用，只供继续修改和内部审阅；`egoanchor_cn_v6.tex`、`egoanchor_cn_v7.tex` 与 `egoanchor_cn_v8.tex` 作为旧稿保留。修改后使用本机 XeLaTeX（推荐 `latexmk -xelatex`）编译检查通过。

<!-- USER-MAINTAINED-REQUIREMENTS:END -->

本文件只记录当前事实、长期约束和已冻结路线。实验过程、旧 session 数字、迁移 hash、调参记录和一次性排障不写入本文件。

## IEEE VR 2027 论文路线

当前中文工作稿定位为系统论文。路线以 `2026-EgoAnchor/egoanchor_cn_ai_v8.tex` 和 `2026-EgoAnchor/plan.md` 的系统论文框架为准；文件名中的 `ai` 表示该版本使用 AI 辅助撰写。该稿目前尚不可用，只供继续修改和内部审阅；`egoanchor_cn_v6.tex`、`egoanchor_cn_v7.tex` 与 `egoanchor_cn_v8.tex` 作为旧稿保留。旧 `IEEEVR2027_RQ12_REFACTOR_PLAN.md` 文件当前不存在，不再作为权威计划引用。

中心论点：开放视觉后端输出的异步 6DoF pose 不是可直接消费的 MR anchor。EgoAnchor 将低频、异步、质量不均的视觉位姿观测，转换为消费级混合现实应用可持续使用的世界系对象锚点。

论文主叙事固定为 `pose estimate != usable MR anchor`：平台原生支持范围只解释外部感知为何必要，零样本视觉感知只说明给定模型的更多刚体为何可被定位。两者不能被写成核心贡献；核心问题是如何为异步视觉观测恢复时间语义、判断是否接纳，并控制持续 MR 锚点的逐帧输出与生命周期。

三项贡献：

1. 感知后端与锚定运行时解耦的端到端对象锚定系统，以及基于 `frame_id` 的采集时刻世界对齐。
2. 观测到锚点运行时：VCD 观测接纳、Kalman 状态估计与 Linear/SLERP 自适应历史合成、显式静止锚定和生命周期管理。
3. 系统实现与分层评估：端到端系统表征、关键组件归因和计划中的跨对象任务层用户研究。

论文外部不再使用 RQ1/RQ2/RQ3 作为顶层结构。当前实验组织为：

- **实验一：端到端系统表征**。在静止目标与主动头动、起停 6DoF、持续平移/旋转、遮挡恢复条件下，比较 *Arrival-Hold*、*Capture-Hold*、*One-Euro Anchor* 与 *EgoAnchor* 的系统行为。
- **实验二：系统设计归因**。在同一日志格式和平台参考下关闭单一设计，归因采集时刻世界对齐、VCD 观测接纳、时序合成和静止锚定的贡献与代价。
- **实验三：日常物体上的跨对象感知评价**。`2 方法 x 3 物体 = 6 区块` 被试内设计，每区块 3 任务 + 13 条目（问卷 v5），只比较 *One-Euro Anchor* 与完整 *EgoAnchor*；**2026-07-25 起改为纯主观评价，不采集任何客观任务数据**。当前只冻结设计，实验一/二完成后再启动正式采集。**唯一权威文件是 `2026-EgoAnchor/experiment_3_questionnaire_design_zh.md`（v5 完整计划：结构+测量+分析+汇报）**；原结构文档 `experiment_3_design_zh.md` 已于 2026-07-26 并入该文件并删除，不得再引用。

VCD 的三个语义层次不得混淆：

- 方法输出 `[0,1]` 连续可靠性评分。
- 运行时以冻结阈值执行 admission。
- 离线按分数诱导候选顺序，使用 risk-coverage/AURC 检验评分的风险判别性。VCD 本身不是排序算法，也不是位姿正确概率。

系统配置命名：

- *Arrival-Hold*：到达时刻复合、接受全部合法候选、零阶保持。
- *Capture-Hold*：采集时刻世界复合、接受全部合法候选、零阶保持，用于隔离 frame alignment。
- *One-Euro Anchor* 是 schema 中保留的稳定 variant ID；新重采的场景显示名为 *One-Euro Interpolation*，使用采集时刻世界复合、VCD 接纳、OneEuroModel、自适应历史目标时刻、位置 Linear / 旋转 SLERP、与完整系统相同的生命周期和逐渲染帧输出，但不使用 StaticLock。
- *EgoAnchor*：采集时刻世界复合、VCD 接纳、Kalman Linear/SLERP 合成、显式静止锚定和生命周期管理。
- 组件消融使用 `EgoAnchor w/o <component>` 风格命名，不再恢复旧 RQ 命名或旧 CLI 兼容层。

IEEE VR 2027 的投稿上限是正文、图和表最多 9 页，参考文献最多另占 2 页。**当前处于撰写阶段，页数不作硬约束**：内容可以适当超出 9 页，先把论述、证据和细节写足，最后统一浓缩到投稿上限。不要为了压页数提前删减实质内容或牺牲论证完整性；也不要因为超页而拒绝补写章节。压缩留到定稿前的专门一轮处理，届时优先压缩公式展开、审计指标叙述和重复的边界说明，而不是删证据或删章节。`egoanchor_cn_v7.tex` 正文占 p1--p8、参考文献起于 p9。上一版 `egoanchor_cn_v8.tex` 在 §5.5 改写为纯主观感知评价后正文占 p1--p10、参考文献起于 p11，超出上限 1 页；最新 `egoanchor_cn_ai_v8.tex` 仍是尚不可用的 AI 辅助工作稿，页数压缩留待内容可用后的定稿轮处理。实验三是已规划的感知效用验证，当前只写冻结设计并占用一张结果表（`tables/exp3_subjective.tex`，数据待回填）；四面板配对图在数据采集完成前保持注释，避免 include 缺失文件导致编译失败。

实验三的完整冻结设计固定在 `2026-EgoAnchor/experiment_3_questionnaire_design_zh.md`（**v5 完整计划书，2026-07-26 起为唯一权威文件**；原结构文档 `experiment_3_design_zh.md` 已并入并删除），`plan.md` 只保留摘要、论文 §5.5 只保留可发表叙述；改动前必须先读该文件，其"版本沿革与决策记录"节列出了被推翻的旧决定，**不得改回**。要点：**实验三是纯主观评价，不采集任何客观任务数据**（无任务时间、无成功率、无行为探针；T3 的四按钮面板行为任务已删除）。条件只有 *One-Euro Anchor* 与完整 *EgoAnchor*，*Arrival-Hold* 只作训练阶段演示、不进入推断统计。交叉核心对象为 `blue_mouse`、`stapler` 与 `gamepad`（覆盖尺寸/纹理/几何三个维度；手柄强制单手握持单侧搬移，使另一手保持握持控制器），`earphone` 作困难样例只由操作员采集并兼作训练物体。**区块结构是物体最外层、两方法嵌套在同一物体内**：物体外层因为 `--object` 只在服务启动时读取、协议无运行时切换动作，且同一物体的两方法由同一次感知会话服务；方法内层是灵敏度选择，同物体相邻 A/B 给出最紧配对。三项任务为静止观察、拿起放下、遮挡恢复，**固定顺序**（对应三个不同运行时状态，非同一构念的三次测量），合计 45--60 s 后统一评分，**不在每项任务后中断**（GPT 曾提议的任务级即时评分已否决）。两类人为探针（读 4 字符码、射线选中小目标）均已评估否决：整体游移不影响可读性、单次注视内抖动仅 0.17 个字高，正确率会撞天花板；小目标选择受追踪补偿影响；两者还要额外花版面解释。**遮挡时长必须使锚点停留在 `FrozenUncertain` 而不进入 `Lost`（0.6--0.9 s 起，预实验校准后冻结）**：`AnchorStateMachine.cs:105-115` 的实际分支是 `<=0.45 s` 滑行、`0.45--1.0 s` 冻结、`>=1.0 s` 丢失，因此 **0.6--0.9 s 落在冻结区间而非滑行区间**（旧文档称"coasting 区间"与 0.45 s 滑行上限自相矛盾，已于 2026-07-25 修正）。更长的遮挡（含旧文档的 2 s 与 2.5 s）会使两方法都进入 `Lost` 并等待同一次服务器 REGISTER（中位数 750.26 ms），使恢复条目主要反映感知后端而非运行时；该区间还须避开 0.45 s 边界，否则计时抖动会把试次随机分到两种生命周期状态。生命周期状态分布与两方法的候选/VCD/接纳率一致性是必须报告的操纵检验。运行时参数不得为实验三修改。日常物体上没有同平台参考位姿，实验三不得报告绝对配准误差，只报主观评价和无需真值的自参考稳定性日志，且不得作中介效应主张；**也不得声称提供任务表现证据**，该边界必须在讨论/局限中明说。Exp3 使用独立的 2 runtime `variant_matrix_id`、独立启动门禁和与 schema-v2 隔离的日志与分析模块，不复用实验一/二的九路矩阵。

**实验三问卷为 v5（2026-07-26 用户批准，推翻 v4 的 9+1 结构；同日 v5.1 增补）**，测量分三层，共 32 个独立条目、每人 108 个评分：（一）**区块级 13 项**，统一七点同意度、单一尺度（v4 的强度尺与切换提示页随 Q4/Q5 退役而取消）——7 项自制条目 Q1 静止稳定/Q2 运动附着/Q9 姿态一致/Q3 恢复一致/Q8 位置正确/Q6 依赖意愿/Q7 稳定--响应平衡（措辞沿用 v4 冻结版，唯 **Q2 于 v5.1 锐化为"始终附着在真实物体上的同一位置"**以与 AQ-IQ3 运动平滑正交；Q1 只承载时间稳定性、Q8 只承载空间正确性、Q9 独立承载旋转通道），加 **Augmentation Quality 的 Embedding Quality 与 Interaction Quality 两个完整子量表 6 项**（Schein et al. 2025, JAMS, doi:10.1007/s11747-025-01108-2，CC BY，EFA/CFA 验证；对象化最小替换，论文须声明）；呈现按体验时间线，Q1 与 Q8 相隔五题；每人 `2 x 3 x 13 = 78` 个区块评分；可选 Q10 放置后稳定默认不启用（启用判据与 AQ 缩减规则见权威文件第八节）。（二）**方法级**：**全部六个区块完成后**，按平衡顺序（S1 先评方法 A、S2 先评方法 B，先评方法 12/12）对两方法分别施测 **adapted TiA 两分量表**（Körber 2019，Reliability/Competence 6 项 + Understanding/Predictability 4 项，官方条目号 1,6,10,13,15,19 与 2,7,11,16，反向项 RC3/RC5/UP2/UP4 计分 6−raw，五点同意度；**英文版验证证据有限，署名只写 adapted，不得写"已验证英文/中文量表"**）与 **adapted S-TIAS 三项**（McGrath, Lack, Tisch & Duenser 2025, Frontiers in AI 8:1582880，doi:10.3389/frai.2025.1582880，CC BY；原文指代 "the AI assistant"，替换为"这种对象锚定方法"；**语料曾误标作者为 Karpus，bib 键为 `mcgrath2025stias`**）。**方法级问卷不得插入第 5/6 区块之间**（会打断第三个物体的相邻 A/B 紧配对并提前启动信任判断框架，2026-07-26 核对修正）。（三）**最终**：2 强制选择（总体偏好 + v5 新增的信任选择）+ 偏好强度与区分信心（v5.1，描述性；强度仅对做出方法选择者施测，"无明显偏好"记 N/A）+ 2 道开放题 + SSQ 衍生安全检查。**v5.1 来自对 GPT 方案（`material/old/gpt-5.6-sol_plan.md`）的复审**：采纳上述四处增补（另含背景字段 +实物 AR/MR 交互经验、预实验 +Q2/AQ-IQ3 判别认知访谈与方法级 A/B 回忆检查、翻译流程明确含认知访谈）；其任务级即时评分、方法级 CRIQ/CIQ 条目、删除 TiA、统计层级倒置与 2.5 s 遮挡**维持否决**，理由已记录在权威文件"v5.1 增补"节，不得复活。**v4 的 Q4/Q5 已退役**（构念由 AQ-EQ/AQ-IQ 接管，CRIQ 署名疑难随之消除）；**任何场合不得以 CRIQ 之名署名条目**——已核查无法确证存在名为 CRIQ 的已验证量表（SelfBlending 归给 Gottsacker et al. ISMAR 2021，但该文标题不含量表名；唯一同名 `CRIq` 是无关的 Cognitive Reserve Index）。自制单项逐项分析、**不得合并总分或报 Cronbach's alpha**；信度只对已发表量表（AQ/TiA/S-TIAS）报告。禁止引入 SUS、完整 NASA-TLX、IPQ/临场感量表、具身量表、UEQ/AttrakDiff（构念在两方法间按设计恒定）。**联网核查结论：不存在测量"虚拟内容在真实物体上的配准质量"的已验证量表**，该结论写入论文测量说明。信任动机文献为 Gottsacker et al. 2024（AR 跟踪偏移/抖动在测试的 0/1/2 度水平内每升高一级伴随信任下降，doi:10.1016/j.cag.2024.104035；**不得表述为任意每度线性下降的连续定律**）。**量表原文核对已于 2026-07-26 完成**（研究者经 GPT 网页端对照原文；结论存档于权威文件〇节"v5.1 核对结果"与采集表 `Verification_Audit` 表）：AQ 官方六条与量尺（1 I do not agree – 7 I fully agree，指代 "The virtual object"）已回填、TiA 6+4 结构与反向项确认（语料 7+3 系误标）、S-TIAS 原文与作者更正、Gottsacker 全书目补全；bib 三条（`schein2025aq` 含全作者与 54:49–69、`mcgrath2025stias`、`gottsacker2024artrust` 含 123:104035）均已完整。**AQ/TiA/S-TIAS 一律以 adapted / 对象化改编署名，信度只表述为当前样本信度；统计家族名为"已发表量表家族"（不再称"已验证工具家族"）**。**剩余采集前置只有两类**：① 预实验（含**确认性**认知访谈——中文措辞已于 2026-07-26 冻结为 v5.1 Final wording：19 条量表条目经"GPT 正向翻译 → GPT 网页端对照原文复核 → 仓库助手逐条语义审计"三次独立通过，审计微调 AQ-IQ2 去"能够"、AQ-EQ2 去"看起来被"；访谈最高优先项为 TIA_RC1/RC4 构念贴合与 Q2/AQ-IQ3 判别，仅在发现理解不良时按"修订—重测—再冻结"改动；论文只写"译为中文并对照原文逐条核对语义等价，预实验中经认知访谈确认理解"，**不得声称执行了独立译者盲法回译**），以及遮挡时长/Q10/AQ 缩减/方法级模态四个预留参数的冻结；② Unity/Python 工程实现。

**顺序平衡已统一为 24 平衡单元**：3 物体的 6 种全排列 × 互补方法序列 S1(A--B, B--A, A--B)/S2(取反) × A/B 标签到方法的映射，N=24 时每单元 1 人、先行方法 12/12；匿名标签在参与者内全程稳定绑定同一方法，否则最终强制选择无从解释。N=18 下限时优先保先行方法与标签映射平衡。旧的"3 拉丁方 × 2 条件顺序 = 6 组"方案已废弃。**统计固定为三物体均值后的参与者内 Wilcoxon + 分层 Holm**：主证实家族 7 项 Q1/Q8/Q2/Q9/Q3/Q6/Q7，已发表量表家族 5 检验 AQ-EQ/AQ-IQ/TiA 两分量表/S-TIAS；TiA 反向项先按 6−raw 换向，Q10 次级，选择、偏好强度、区分信心与开放题只作描述。Wilcoxon 使用含并列中秩的双侧条件精确符号置换：配对差先四舍五入至 12 位小数以恢复理论并列，删除零差，再对全部符号分配求精确 p；不得改回正态近似。“条件精确”只指在给定非零绝对差及其中秩后穷举符号分配，仍要求零假设下非零配对差的符号可交换，通常由配对差分布关于零对称的假设支撑，不得写成无假设检验。2026-08-01 在真实参与者采集前删除自定义 CLMM：其 L-BFGS-B 逆 Hessian 不能作为协方差，Wald 推断无效，数值 Hessian又近奇异；当前不再保留 CLMM 配置、代码、结果页或论文叙述。逐物体结果只作 7 条目 × 3 物体的配对描述，不计算 p 值或星号。

**同步状态（2026-08-01）**：`egoanchor_cn_ai_v8.tex` §5.5、`plan.md` 与实验三权威设计已同步到条件精确 Wilcoxon、其符号可交换/差分布对称假设、逐物体仅描述和不再使用 CLMM 的口径；Figure 4 的计划图注也已冻结为三物体均值后的 Holm p、星号阈值与浅灰配对线。本轮同步后已用本机 `latexmk -xelatex` 编译通过，无未定义引用。`2026-EgoAnchor/material/reference/EgoAnchor_Experiment3_DataCollection_24P_v5_1_Beautified_Checked_VSCodeSafe.xlsx` 仍是只读美化来源。计划中的原始输入路径为 `2026-EgoAnchor/material/EgoAnchor_Experiment3_RawData_24P_v5_1.xlsx`，其 7 张采集表结构不变：`Participants`/`Records` 只保存人工原始值，TiA 换向与其他公式只在 `Derived`/`Analysis`。模板构造器必须显式指定尚不存在的目标并拒绝覆盖。为兼容 WPS，实时四分位继续使用与 `QUARTILE.INC` 同算法的 `QUARTILE`。

**实验三结果工作簿现固定为 6 张中文页**：`说明`、`样本与质控`、`主结果`、`分物体描述`、`量表信度`、`选择结果`。`主结果` 只含冻结的 7 个主条目和 5 个已发表量表；不再输出 AQ 单项探索行、`Participant_Audit`、`Model_CLMM`、`Open_Coding` 或三张 `Scores_*` 派生底表。`分物体描述` 只含 7×3 配对描述，不写 p、Holm、显著性或 `r_rb`。开放题编码必须放在独立、持久且不会被自动重建覆盖的文件。论文只计划一张四面板 Figure 4 和一张 12 结局完整结果表；Figure 4 用浅灰配对线连接同一参与者的 One-Euro 与 EgoAnchor 评分，并在每个面板标三物体均值主检验的 `p_Holm`、对应星号与 `r_rb`。星号只编码每位参与者三物体均值后的 Holm 校正 p，阈值固定为 `*<.05`、`**<.01`、`***<.001`；三个物体只作描述，不分别检验或标星。Figure 5 已退役。分析参数契约为 v2，不兼容旧的 13 页结果簿或 Figure 5。`r_rb_CI_Status=degenerate_at_bound` 时仍只能写"方向完全一致"，不得把 `[1.00, 1.00]` 当置信区间。`Reliability.Measurement_Unit=block_mean` 的 AQ 信度与 `method_single` 的 TiA/S-TIAS 信度不可互比，也不可与原量表发表 α 直接对标。

**当前默认 RawData 未通过来源完整性门禁**：其区块评分、方法级评分和最终问卷核心响应与明确标为 GPT 合成的 `material/reference/GPT-5.6-Thinking_v3_AnalysisFilled_VSCodeSafe.xlsx` 共 4560 个单元格逐格一致，且记录时间为审计日 2026-08-01 之后。当前文件虽写有 `formal-participant-data` 核心属性，也只能用于流程演练，不得作为真实实验数据、论文证据或与真实数据合并。来源门禁固定为正向批准：已知合成响应指纹优先拒绝；其他工作簿除正式契约外，还必须在人工核验来源后把规范化核心响应 SHA-256 加入 `paper.toml [experiment_3.source_gate].approved_response_fingerprints`。批准列表当前为空，分析代码不得自行登记指纹。门禁失败时结果 `说明` 页必须显示警告，构建清单将 `paper_eligible=false`，`copy-assets exp3` 必须拒绝复制；正式采集前要换成来源可核验的原始工作簿并完成指纹批准。**参与者问卷包**仍以 `material/EgoAnchor_Experiment3_Complete_Questionnaire_v5_1_Bilingual.md` 为唯一事实源，同名 docx 由 `material/build_exp3_questionnaire_docx.py` 从 md 确定性生成，先改 md 再重跑脚本，不得手改 docx。历史模板位于 `material/old/`，问卷调研语料位于 `material/old2/`，一律不得用于正式采集。

`material/old/` 下的 **AI 模拟演练数据**仅用于设计与分析流程验证，**不得作为真实实验数据、论文证据或与真实数据合并**：全部按 v5 之前的旧测量结构生成（`EgoAnchor_Experiment3_Simulated_Claude-Fable-5.xlsx` 与 GPT 系文件按已作废的 v3 旧结构；`EgoAnchor_Experiment3_Simulated_Claude-Opus-5.xlsx` 及其报告按 7 条目单层结构，种子 20260726、效应量锚定实验一/二 v4 实测差异、含 24 平衡单元与 TOST 等价操纵检验）。为 v5 做流程演练时只能参考其平衡分配与分析骨架，不得直接复用条目字段。

`material/` 下的 **v5.1 冻结结构模拟数据**按当前正式 32 条目/108 评分结构生成，同样只用于设计灵敏度与分析流程演练，**不得与真实采集数据合并**：`EgoAnchor_Experiment3_Simulated_24P_v5_1_Claude-Fable-5.xlsx`（`simulate_exp3_claude_fable_5.py`，种子 202607265）与 `EgoAnchor_Experiment3_Simulated_Claude-Opus-5-1M_v5_1_24P.xlsx`（`simulate_exp3_claude_opus_5_1m.py`，种子 20260727），报告分别为 `EgoAnchor_Experiment3_Simulated_Claude-Fable-5_Report_zh.md` 与 `EgoAnchor_Experiment3_Simulated_Claude-Opus-5-1M_Report_zh.md`。两轮结论量级差异很大，**规划灵敏度时以 Opus-5-1M 的保守区间为依据**：Fable-5 报主家族 6/7 显著但 r=1.00、dz=2.12–3.60、量表家族 5/5 全显著，而 dz>2 对七点单项主观评分不现实、且与其 α=0.47–0.77 自相矛盾；Opus-5-1M 报主家族 6/7 显著（dz=0.51–1.60，Q2 为预期零效应 dz=+0.13）、**量表家族仅 2/5 显著**（S-TIAS dz=0.88、TiA-R/C dz=0.64；AQ-EQ/AQ-IQ/TiA-U/P 落在 p≈.066、dz=0.46–0.52，在 N=24 与 α=.05/5 下功效仅 0.31–0.42）。该轮另有三条对正式采集有效的诊断：**28% 区块问卷 >150 s 且 8.4% 区块出现 ≥5 连续同分，§8 的 Q10 否决与 AQ 缩减两条判据都已触发**；AQ-IQ2 单项方向为负（dz=−0.37）如设计预期；**N=18 时只保住 Q1/Q3/Q8，Q6/Q7/Q9 挤到 .038 附近**。经验教训：合成主观数据若缺少方法级共享印象项、区块内分量表共享因子或人×条目随机斜率，会分别产出 r_rb≈1、α 被压到 0.2–0.4、以及配对符号完全由恒正 δ 决定的假象。这里关于随机斜率的结论只用于解释历史模拟器，不能据此恢复已于 2026-08-01 删除的 CLMM。

`material/EgoAnchor_Experiment3_最终数据_Consensus_24P_v5_1.xlsx` 是**三轮模拟的共识合成数据集**（2026-07-27），同属合成数据、边界完全相同，**不得进入论文结果**。流水线为 `extract_exp3_simulations.py` → `adjudicate_exp3_simulations.py` → `derive_exp3_consensus_targets.py` → `build_exp3_final_dataset.py` → `analyze_exp3_final_dataset.py`（种子 20260727），报告为 `EgoAnchor_Experiment3_最终数据_共识合成_实验情况报告.md`。裁决按六条事先定义的自相矛盾判据给权重（Fable-5 1/6→0.10、Opus-5-1M 6/6→0.60、GPT-5.6 3/6→0.30），**位置参数与方差结构用不同权重集**（方差为 0.15/0.70/0.15，因三条方差类判据只有 Opus-5-1M 通过）。**已实测证伪逐格平均**：三份复本逐格平均使 dz 抬高 1.99–3.17 倍、配对差 SD 中位降到 0.389、5/7 条目被推到 r_rb=+1.00，故一律不得用逐格平均合成主观数据。**该数据集是「共识中心估计的一次实现」而非「共识总体的一次随机抽样」**：校准把实得 δ̄ 推到目标上并同时吸收了该组固定抽取的衰减，换 24 个新种子重抽后 13 条目平均 δ̄ 由 +0.510 降到 +0.337（z=+2.33），因此它给出的是中心情形下的可检出性、是一条**乐观边界**，只可用于设计灵敏度评估。结论要点：主家族 Holm 后 5/7 显著（Q1 dz=1.36、Q8 1.05、Q3 1.03、Q7 0.94、Q6 0.71；**Q2 dz=0.20 为设计声明的零效应，Q9 dz=0.48 属检出力不足**——Q9 对应实测比值仅 1.15×，措辞同时承载旋转跟随与静止朝向漂移两个差异悬殊的通道）；量表家族 4/5 显著，**AQ-IQ 不显著且其 α 在两条件下 0.81 vs 0.59，故不宜作单一分数**（AQ-IQ2 反向 dz=−0.49 与 AQ-IQ3 正向 dz=+0.93 内部相消）；五项 TOST 全部等价、142/143 区块停在 FrozenUncertain；四项顺序诊断中先行方法 p=0.043，经角色特征平衡检验（全部 p>0.5）与 40 次换种子重抽（p 中位 0.525、p<.05 占 2/40）确认为抽样波动；**N=18 会丢掉 Q6 与全部四个显著量表，故 N=24 是硬下限、建议采集 26–28**。另记两条一般性教训：**合成偏好判断不能用条目等权均值**（会让天花板项与反向项占去 2/13 决定权，把高敏感度个体推到零附近）；**判断噪声必须是保号乘性噪声而非有符号加性噪声**（后者会把 |raw|=0.05 放大成 0.27，凭随机数制造出反向选择者）。**采集表模板缺陷**：`Analysis!A78:S78`（输出可用率数据行）被误设为合并的分节标题带，程序回填前须先解除合并——建议直接在正式采集工作簿中修正该单元格。

上述 `Analysis!A78:S78` 合并缺陷只属于共识合成数据和旧美化来源；新的正式 `EgoAnchor_Experiment3_RawData_24P_v5_1.xlsx` 已解除该错误合并，Python 不再需要运行时修补。

`material/EgoAnchor_Experiment3_Simulated_Claude-Opus-5-1M_R2_v5_1_24P.xlsx` 是 **Round 2 独立重抽演练**（2026-07-27，种子 202607272、指派种子 90210、400 次换种子重抽），报告为 `EgoAnchor_Experiment3_Simulated_Claude-Opus-5-1M_R2_Report_zh.md`，同属合成数据、边界完全相同。流水线是单一入口 `simulate_exp3_opus5_1m_r2.py`（生成→分析→重抽→写工作簿→公式求值注入→逐格校验），依赖 `sim_r2_personas.py`（手写人物层）、`sim_r2_params.py`、`sim_r2_workbook.py`、`sim_r2_formula_eval.py`、`sim_r2_recalc_verify.py`、`sim_r2_scaffold.json`；另有 `sim_r2_audit_report.py` 把**报告正文数字**与 `_sim_r2_summary.json` 逐条比对（改生成器或报告后必须重跑，否则报告数字会静默过期）。**本轮针对共识数据集的乐观偏置做四处改动**：24 名参与者改为逐人手写人格（含逐通道灵敏度、信任倾向与开放题原文）、**取消事后校准**、追加 400 次换种子重抽报告 Holm 后显著占比、工作簿小分改公式实时计算。**规划正式采集应以本轮的显著占比为基准**（Q1/Q3/Q8 100%、Q6/Q7 99.2%、TiA-R/C 98.0%、S-TIAS 96.8%、TiA-U/P 94.8%、**Q9 仅 69.5%**、AQ-EQ 51.2%、AQ-IQ 34.2%、**Q2 13.8%**），主种子那次落在分布保守一侧（主家族 Holm 后 5/7、dz −0.02…+0.95；量表家族 3/5）。本轮新增五条对正式采集有效的结论：① **手写人物到平衡单元必须做分层随机化**——按书写顺序直接对应会使 `sens` 与先行方法共线（EA 先行位均值 1.058 对 OE 先行位 0.842，相差 26%）并凭空造出顺序效应，且只按 `sens` 分组配物体排列会把共线转移到首个物体（实测 p=0.0056），必须四个顺序因子同时平衡；② **对比锐化必须对称施加**（只放大完整系统等于把对比效应写成方法效应）；②′ **抽随机数时不得迭代 `set`**——`set(SUBSCALE_OF.values())` 的迭代顺序随进程哈希随机化改变，会使两个 AQ 子量表互换所抽到的随机值，同一种子在不同进程间产出不同数据（进程内一致、跨进程不一致，实测 AQ-IQ 检出率 34.2% 与 37.2% 来回跳）；固定顺序列表 `SUBSCALES` 已修正，随机抽取一律按显式列表顺序；③ S1/S2 互补序列使先行方法与区块位置**结构性共线**（EA 先行时平均区块位置 3.33 对 3.67），该不对称在两组间对称抵消；当前只在样本与质控页审计区块位置和对象内先后，不再拟合 CLMM；④ 问卷负担诊断二次独立复现（27.8% 区块 >150 s、13.2% 出现 ≥5 连续同分），**正式采集应执行 §8 的 AQ 缩减规则**（停用 AQ-EQ3 与 AQ-IQ1），这与 AQ-EQ3 天花板拖累子量表的发现互相印证；⑤ N=18 时主家族 5/7 全保住但**三个信任量表全部丢失**（S-TIAS p_Holm=.0501），与共识轮合并后 N=24 是硬下限、建议 26–28。本轮**未拟合次级 CLMM**（环境无支持随机效应的累积链接混合模型，不以代理模型冒充），方向一致性改由逐物体描述承担。另记一条人物层教训：**手写人物的意图不保证实现**——为「偏好 One-Euro」与「权衡型无偏好」专门设定的 P016/P023 实得都选了完整系统，因为偏好判断的稳定类权重远高于响应类，价值取向偏移难以压过知觉显著性；报告必须按实得结果陈述，且本轮**未出现高信心+无偏好个体，故区分信心项识别权衡型无偏好的能力未被验证**。

所有 AI 或模型生成的实验三数据只用于采集表和分析流程演练，必须在文件名、工作簿首屏和报告中明确标为合成，并与正式参与者数据及分析入口隔离；不得进入论文结果、效应量、功效或样本量推断，也不得与真实数据合并。面向 VS Code Office Viewer 的演练工作簿使用与现有 `VSCodeSafe` 模板一致的普通单元格安全子集，不依赖 Excel Table、条件格式、数据验证、合并标题、自动筛选或冻结窗格；统计约束由生成与验证代码执行。**Round 2 演练工作簿和新的正式 `..._RawData_24P_v5_1.xlsx` 都使用公式实时计算问卷小分**；旧美化来源 `..._Beautified_Checked_VSCodeSafe.xlsx` 仍保持无公式，只作为生成来源。`Participants` 与 `Records` 是正式原始输入，TiA 反向项存原始分，反向计分只在派生层做；`Derived` 与 `Analysis` 的 Mdn/IQR、配对差、dz、逐物体均值和各项计数为公式，只有 Wilcoxon W/p、Holm 校正、r_rb 自举区间、信度与启用后的 TOST p 由 Python 结果工作簿写数值。正式分析永远从原始输入独立重算，不读取 Excel 公式缓存。Round 2 演练的缓存注入仍由 `sim_r2_formula_eval.py` 完成，并由 `sim_r2_recalc_verify.py` 从原始评分手写重算后逐格以 1e-9 容差交叉验证；正式空白模板不注入伪缓存，只置 `fullCalcOnLoad="1"` / `forceFullCalc="1"` 让 Excel 打开时重算。**不要依赖本机 Excel COM 重算**：仓库在网络盘 `P:\` 上，Excel 以受保护视图打开，COM 调用被 `RPC_E_CALL_REJECTED` 持续拒绝，且失败会残留 Excel 进程并锁住输出文件。

两次执行边界：Run 1 完成实验一/二采集前全部工程、论文框架、QC、分析骨架和中文采集手册，并保留实验三设计；用户完成功能自检与实验一/二正式采集；Run 2 完成实验一/二分析、图表和论文回填。本轮按用户明确要求，每个 Task 验证后独立提交并推送。

## 诚实边界

- “纯视觉”只修饰物体位姿估计链路；系统仍依赖外部消费级 GPU、局域网和头显平台追踪。
- 系统需要目标三维模型，不得声称适用于任意对象。
- 控制器 pose 是平台参考位姿，不是外部光学真值；它与头显共享追踪系统，会隐藏共模世界漂移。
- frame alignment 只校正相机采集/到达时刻错配，不补偿采集后的物体运动。
- 单操作员、多 session 的帧只表示时间覆盖，不作为独立样本量。
- Meta、Apple 与专用追踪附件只作为论文中的能力定位对象；相关工作、紧凑能力表和讨论必须以官方或同行评审来源说明其对象绑定语义与前提。跨平台数值实验不是实验一/二的必做证据，只有同一对象、统一参考和相同协议均成立且不影响主实验时才可作为描述性上下文，不能支撑核心贡献。

## 主线目录

| 目录 | 职责 |
|---|---|
| `EgoAnchor_Python/src` | 图像接收、感知、VCD、通信、评估分析 |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor` | Quest 采集、时空对齐、公共 admission、四时序策略、显示与录制 |
| `EgoAnchor_Protocol` | Proto 与 subject 唯一来源 |
| `2026-EgoAnchor` | 中文主稿、VGTC 模板、图表、采集手册与当前论文路线 |

旧 RQ1/RQ2 Unity 脚本、场景、Python 分析包和 `EgoAnchor_Tools3` 已删除，不得恢复。正式评估入口只使用实验一/二命名。

## 不可破坏的系统约束

系统使用三条语义平面：

| 平面 | 传输 | 方向 | 内容 |
|---|---|---|---|
| Data | ZMQ PUB/SUB | Unity -> Python | `QuestStereoFrame`、`QuestCameraInfo`，multipart，latest-drain |
| Message | NATS Core pub/sub | Python -> Unity | `PoseResult`、状态、heartbeat |
| Command | NATS request/reply | Unity -> Python | reset、reacquire、control，`request_id` 幂等 |

- Python 只输出 camera-space pose；Unity 用 `frame_id` 回查 image-time proxy camera pose 并合成 world anchor。
- 不得用 PoseResult 到达时的 HMD pose 代替发送帧 pose。
- 业务代码不手写 subject；Python 从 `egoanchor.protocol` 包级入口导入，Unity 使用 `SubjectNames`。
- Proto 字段号不得重排；删除字段时同时 `reserved` 字段号和字段名。
- Unity -> Python ZMQ 端口固定为 `15557`。
- NATS handler 只负责 parse、validate、dedup、enqueue、ack；`TrackingRuntime` 顺序拥有 pipeline/GPU 状态。
- 重获取只有一个中央 owner；四个时序变体不得分别改写共享 Python 感知状态。
- Unity 的正式 session 配对可从 Python `PoseResult`、状态或持续 `ServerHeartbeat` 的 header 获取 `session_id`，不得等待首个 pose；正式采集场景的 NATS 初次连接重试必须开启，使 Python 与 Unity 的启动先后无关。

## 当前运行时架构

正式采集链路：

```text
PoseResult candidate
  -> frame_id-based capture-time alignment
  -> optional VCD admission
  -> Arrival-Hold / Capture-Hold / One-Euro Anchor / EgoAnchor / component ablations / paired strategy candidate
  -> synchronized display and logs
```

- *Arrival-Hold* 用到达时刻复合和零阶保持，作为直接消费异步视觉位姿的朴素系统基线。
- *Capture-Hold* 用采集时刻复合和零阶保持，作为 Arrival-Hold 与 One-Euro Anchor 之间的时间对齐桥接配置。
- *One-Euro Anchor* 的新重采配置使用采集时刻世界复合、VCD 接纳、OneEuroModel 与 `LinearSlerpStrategy`；目标时刻与完整系统采用相同的自适应历史延迟，生命周期和重获取开关与完整系统一致，仅关闭 StaticLock。
- 当前正式场景的 One-Euro 参数按米制位置与约 10 Hz 候选标定为位置 `(minCutoff=0.8, beta=6, derivativeCutoff=2)`、旋转 `(1, 1, 2)`。
- 正式逐帧输出策略统一使用 `Strategy` 后缀：`HoldStrategy`、`LinearSlerpStrategy`、`SmoothedKalmanExtrapolationStrategy` 和 `HermiteStrategy`；运动状态估计统一使用 `Model` 后缀。正式日志字符串分别为 `hold`、`linear_slerp`、`smoothed_kf_extrapolation` 和 `hermite_interpolation`。废弃策略及兼容分支不得恢复。
- *EgoAnchor* 用采集时刻复合、VCD 接纳、Kalman + `LinearSlerpStrategy`、显式静止锚定和生命周期管理。
- 实验二的两路时序策略为 *Smoothed KF Extrapolation* 与 *Hermite Interpolation*。两路共享候选、Kalman、VCD、生命周期、重获取和关闭 StaticLock 的设置，只替换输出策略；180/60 ms 与 Hermite 的 1.15/0.25/3 是 v4 pilot 初值，正式采集前必须冻结。
- 组件归因通过关闭单一设计实现：w/o capture-time alignment、w/o VCD、w/o StaticLock。
- 模型相关 per-variant jump gate 不进入正式比较。

## 当前离线分析架构

实验一/二的 v4 正式采集已完成：活动 `batch.json` 为 `batch_20260724_005757_20260724_054822_20260724_233436_20260724_045132_20260724_035344`，五项 session 均 `run_kind=formal`、`variant_matrix_id=exp12_9_smoothed_hermite_v4`、`config_hash=05e5edecf737bf34`，论文表格与当前分析输出逐字节一致。更早的 v3 数据其 Kalman 与当前运行时不一致，只保留为只读工程诊断。正式 Task 1--5 必须始终作为同一完整批次通过 `data exp1-2 stage` 和 `data exp1-2 promote` 后才成为活动论文输入；人工入口固定为 `pixi run eval`，不再保留要求手工传递任意路径的第二套 CLI：

```text
schema-v2 task directory
  -> validate / data exp1-2 preprocess -> task_workbooks/ 下每个原始目录唯一对应的完整 XLSX
  -> 独立指标缓存 -> task_analysis/ 下每本 XLSX 唯一对应的片段结果
  -> batch.json 选择五项任务 -> analyze exp1-2 合并后生成活动 analysis/ 下的指标、绘图 XLSX、PNG/PDF 和 TeX
  -> copy-assets -> 论文目录中的 PNG/PDF 和表格 TeX
  -> 人工审阅并引入 TeX，并按论文工作流手工编译主稿
```

- 原始 task 目录保留为只读冷归档；Stage 1 成功后，后续阶段不得再读取 JSON/JSONL。
- **Stage 1（`data exp1-2 preprocess`）** 只读取缓存缺失或失效 task 的 JSON/JSONL，执行完整 QC 并逐 task 原子发布 XLSX；每个版本化原始目录唯一对应一个共享工作簿缓存，命中时不得重复 QC 或回读 XLSX。不得把 XLSX 之前的任何中间文件作为后续输入。
- Stage 1 的 schema-v2 reader 按固定文件集合流式解析 JSONL，保留来源行号与行 SHA-256；只读硬 QC 只接受 `variant_matrix_id=exp12_9_smoothed_hermite_v4` 的当前九 runtime 矩阵，并检查主外键、生命周期、事件合并、warmup reference、平滑外推诊断和两端 writer 停止态统计；未消费 candidate 仅作为 latest-only 警告。
- `analyze exp1-2` 按工作簿 SHA、`paper.toml` SHA 和指标实现指纹复用逐 task JSON 指标缓存，只扫描缓存失效的 Stage 1 XLSX；随后合并五项结果，并在活动批次 `analysis/` 发布八个独立 PDF/PNG 面板、三张 TeX 表和图环境 TeX。它不得回读 raw JSON/JSONL、改写 XLSX、修改 `2026-EgoAnchor` 下的主稿、图片、表格或 PDF。
- VCD 连续分数的风险判别性只在最终有效的 `occlusion_started` event 内计算：仅使用完整 EgoAnchor 的 capture-time aligned raw pose 与同 frame 有效平台参考，按分数降序且同分候选整组进入，以保留候选的平均平移误差为 selective risk，并用右连续阶梯积分得到 event AURC。不得按 admission 决策过滤低分候选，不得跨 event 混池候选；论文汇总 event AURC 的 median [Q1, Q3]，并与冻结阈值的 VCD admission 尾部效果分开报告。
- 旧 Stage 2/3、v2 replay、`egoanchor.eval.workflows` 与 `egoanchor.eval.paper_analysis` 已删除。正式实现统一位于 `egoanchor.eval.experiments`：`experiment_1_2` 与 `experiment_3` 是同级实验包，都使用 `data.py`、`settings.py`、`workflow.py`、`pipeline.py` 四层，实验专属 reader、指标、计分、模型和绘图位于各自 `analysis/` 子包；跨实验编排在 `experiments/workspace.py`，构建清单和事务性资源复制在 `experiments/common`。实验一和实验二共享五任务日志、Stage 1 契约和结果模型，因此保留 `experiment_1_2`，不拆成两个空壳目录，也不保留旧路径兼容层。
- `pixi run eval` 顶层只保留 `status`、`validate`、`analyze`、`copy-assets` 和 `data`，稳定目标为 `all`、`exp1-2` 与 `exp3`；实验三统计和绘图必须由一次 `analyze exp3` 完成，不再保留单独 `plot`。没有独立 `experiment3.toml`：共享路径及两个实验的路径/资源复制位置分层存于现有 `batch.toml`，统计参数分层存于现有 `paper.toml`；构建配置摘要只覆盖所属实验的 `paper.toml` 科学参数，路径、输入和复制目标由工作流独立核验。文件系统或工具错误返回 1，批次、schema、QC 或论文输入契约失败返回 2。
- 统计单位固定为 event/segment，不是 frame；先在 session/trial/event/variant 内计算，再做同 event/segment 配对和 session 汇总。
- 每个场景单独报告，禁止跨场景混池计算全局总分或总排名。
- 实验一发布一行四个 LaTeX 子图，依次为静止平移、静止旋转、动态平移和动态旋转的误差--抖动双纵轴面板；实验二发布一行四个 LaTeX 子图。图内不重复小标题，图内最小字号固定为 7 pt。
- 实验一图二以四方法为横轴，左移实心圆表示左轴误差，右移空心菱形表示右轴抖动；静止误差使用中心化 P95，动态左轴必须明确标为 lag-aligned RMSE，动态抖动必须使用同一最佳时延下残差轨迹的帧间增量 P95，不得把真实运动计为抖动。动态表另报告不补偿时延的 current-time RMSE，用于披露当前渲染时刻包含相位差的实际配准误差；不得把原始显示位姿的帧间运动量命名为感知抖动。图 3(c) 只显示 event median 与 IQR，横轴为按 VCD 分数从高到低保留候选的比例，纵轴按有效风险范围收紧；图 3(d) 使用 `Smoothed KF`、`Linear/SLERP`、`Hermite` 的紧凑左上图例，图例背景和边框均保持透明，左侧锚点略向 Y 轴靠拢且不得遮挡刻度文字或原始点。
- `egoanchor.eval.contracts` 的 workbook 契约继续作为 Stage 1 Excel 的唯一结构来源，完整保留对齐原始位姿、时间、reference、render 和事件字段；论文参数唯一入口是 `egoanchor/eval/config/paper.toml`，正式 CLI 不提供覆盖参数，分析 provenance 必须记录该文件的 SHA-256；每个参数同行保留中文注释。
- Stage 1 workbook writer 先执行全量硬 QC，再在目标目录写临时 XLSX；写出后独立回读检查分片、表头、行数、类型、主外键、来源集合摘要和超长值，并在替换前复算输入来源哈希，全部通过才原子替换正式文件。单 sheet 超限时使用 `_001`、`_002` 分片；未知 JSONL 字段进入 `row_kv`，超长值进入 `large_values`，不得截断或静默丢弃。内部大值 marker 必须精确绑定来源分片；经过转义的同形原始文本仍按字面量回读。每个物理 sheet 冻结首行，并按列语义写入稳定列宽。Windows 下删除临时文件和原子替换遇到短暂共享锁时有界重试，重试耗尽仍保留旧正式文件并返回文件系统错误。
- `data exp1-2 preprocess` 先按活动 `batch.json` 解析五个独立任务缓存，只对缓存缺失或失效项检查固定源文件、执行 QC 并发布；一个 task 失败不得改写其他 task 的既有缓存。正式工作簿使用 `task_N_complete.xlsx`，代码版本自动读取当前 Git commit 用于审计，但普通 Git 提交本身不作为缓存失效条件。
- `analyze` 只在各自活动分析目录生成结果，不回填主稿；每次构建开始即把统一 `build_result.json` 置为 `building`，只有输入、配置、实现与全部产物摘要冻结后才提交 `complete`。`copy-assets` 只接受 `complete + formal + paper_eligible`，先让目标实验构造只读资源计划，再联合校验全部来源、配置/实现/输入/产物 SHA、后缀与目标冲突，全部通过后暂存并以可回滚事务复制。`copy-assets all` 要求两个实验都就绪，不得静默跳过；无参数时默认实验一/二，也可显式指定 `exp3` 或 `all`。实验一/二表格默认复制为 `tables/exp1_static.tex`、`tables/exp1_dynamic.tex` 和 `tables/exp2_design.tex`；正式实验三只复制 `figures/panels/figure4_exp3_paired.{png,pdf}` 与 `tables/exp3_subjective.tex`，合成来源或来源门禁失败的构建不得复制。图环境 TeX 仍由研究者审阅后手工纳入。主稿编译不属于 `pixi run eval`，当前工作稿编译产物为 `2026-EgoAnchor/pdf/egoanchor_cn_ai_v8.pdf`，仅供内部审阅，不是稳定交付版本。
- 当前中文主稿及自动发布图统一使用 `2026-EgoAnchor/figures/`，不得恢复或新增活动的 `2026-EgoAnchor/figs/` 依赖；面板 PDF 不写入构建时间元数据，确保相同输入重复构建时字节稳定。
- `data/eval/` 只作为新采集和 Mutagen 同步入口；两端停止后，完整 session 移入可配置的 `task_data/`，并按 `task_<1-5>_v<正整数>_<YYYYMMDD_HHMMSS>_<物体>` 命名且视为不可原地修改。`task_workbooks/` 保存逐原始目录的 Stage 1 缓存，`task_analysis/` 保存逐工作簿指标缓存；活动 `experiment_1_2/` 只保存当前五任务 `batch.json` 和合并后的 `analysis/`。目录规则见 `EgoAnchor_Python/docs/data_layout.md`。旧 `data/eval/`、活动 `raw/`/`workbooks/` 快照与 `data/analysis/` 重复归档不得恢复为论文输入路径。
- `audit_samples/` 是可选审计样本目录：没有真实审计文件时不得在新 session 中预创建；Stage 1 暂存会跳过遗留的空目录，但一旦存在真实文件则必须完整复制并纳入来源摘要。
- 统一命令、配置、批次归档、实验三采集、退出码和故障排查的唯一完整手册是 `EgoAnchor_Python/docs/analysis_pipeline.md`；新采集批次通过 `pixi run eval data exp1-2 stage --promote` 选择每项任务最高版本中的最新时间，只为缓存失效任务执行 QC 和工作簿生成，再原子切换轻量组合清单；随后运行增量 `analyze exp1-2` 和 `copy-assets exp1-2`。`--version` 固定全局版本，重复的 `--task-version TASK=VERSION` 覆盖单项任务，`--object` 处理多个完整对象集合。`validate exp1-2` 作显式深查，`data exp1-2 preprocess` 补建失效缓存，`analyze exp1-2 --rebuild` 才强制重建五项任务且不复制论文资源；论文 PDF 由论文工作流手工编译。
- 论文六行连续轨迹图使用独立 `egoanchor.qualitative_replay` 包和 `pixi run replay` 入口；它只读取 `data/replay_capture/` 下的 `egoanchor_qualitative_replay` v1 capture，不得读取或写入正式 `data/eval/`、实验一/二工作簿和 schema-v2 产物。采集方式固定为 Quest Link 串流下的 Unity Editor Play Mode，完整操作说明固定在 `EgoAnchor_Python/docs/qualitative_replay.md`。离线 silhouette 必须按三角面并集生成，不能把整组重叠三角形交给 OpenCV 奇偶填充。
- 正式论文数据不得按场景或指标择优拼接。局部重采可以只替换对应任务，但活动 `batch.json` 中五项任务必须共享对象、协议、配置 hash、冻结参数集和运行时矩阵；未变化任务复用已有工作簿和指标缓存。逐场景仍报告 event 数、缺失率、median[IQR] 与护栏；技术 QC 通过不能替代参数 provenance 和关键场景覆盖门槛。
- 读者表格中的连续数值统一固定显示两位小数，计数和样本量保持整数，完整精度保存在 `analysis/metrics/`；图中可见数据点统一写入 `analysis/plots/figure_plot_data.xlsx`。实验一按系统报告七项行为属性，表内方法短名称固定为 `Arrival`、`Capture`、`One-Euro` 和 `EgoAnchor`；实验二按组件报告启用、关闭和配对效应。
- One-Euro Interpolation 固定为 `OneEuroModel + LinearSlerpStrategy`；三个组件对照与完整系统同样使用 Linear/SLERP，确保只关闭目标组件。图 3(d) 的时序策略主比较是 Smoothed KF Extrapolation 与关闭 StaticLock 的 Linear/SLERP；Hermite Interpolation 是共享关闭 StaticLock、候选、Kalman、VCD 和生命周期设置的补充条件。图 3(d) 必须绘制全部片段原始点，纵轴按当前完整数据自动向上扩展，不得为了阅读尺度隐藏范围外数据。
- 同一批五项物理任务同时驱动实验一四配置、实验二三个消融与两路时序策略；原始 trial/event 上保留共享物理任务的 `exp1_system_characterization` 上下文，实验二由 variant/component 投影得到，不按 `experiment_id` 单独过滤。
- 旋转控制点的 `AngularVelocityRad` 统一表示控制点姿态下的 body-local 角速度。Kalman/One-Euro 每次校正后重置旋转切空间，并用 SO(3) 右雅可比保存物理角速度；不得把不同参考姿态下的旋转向量导数直接混用。
- 正式场景中完整 EgoAnchor 及保留 StaticLock 的两个消融统一使用 `enterAngSpeedDps=22` 和 `unlockDriftDegrees=12`；单项消融不得残留不同 StaticLock 数值。旋转证据必须独立报告，不能用平移收益替代。
- 当前 `KalmanModel` 使用连续白噪声加速度 CV 模型，离散过程协方差为 `q_a [[dt^3/3, dt^2/2], [dt^2/2, dt]]`。冻结参数为位置 `q_a=0.002 m^2/s^3`、`R=0.000004 m^2`，旋转 `q_a=0.2 rad^2/s^3`、`R=0.0004 rad^2`；首帧位置/角速度方差均为 `1`，配置指纹必须包含 `q-model:cwna-v1` 及这些数值。协方差校正使用 Joseph 形式；共享 admission 入口拒绝非有限或非递增的 measurement time，不能把乱序控制点交给模型、时序合成或 StaticLock。VCD 只控制 admission，论文不得声称测量噪声随 VCD 分数在线自适应。
- 当前五本 Stage 1 工作簿已是 CWNA 运行时下的 v4 正式采集结果（`variant_matrix_id=exp12_9_smoothed_hermite_v4`、`config_hash=05e5edecf737bf34`、`run_kind=formal`），可作为论文正式证据。更早的 `q*dt` 协方差工作簿只保留为 v3 归档与只读工程诊断输入。任何后续替换或补采仍须用同一冻结代码完整重采五项任务后整批替换；不得把 v3 数字写成当前运行时的证据，也不得从不同批次按场景拼接。

## Python 关键约束

入口：`EgoAnchor_Python/src/run_server.py` -> `egoanchor.app.tracking_server`。配置位于 `src/egoanchor/config/defaults.toml` 与 `objects.toml`。

- 默认分割器是 `yoloe26`；SAM3 只能显式启用。
- 评估模式写 `data/eval/<session_id>/` 并通过 header 与 Unity 配对；普通模式写 `data/runtime_logs/`。
- VCD 目标公式为 `R = V * G_CD`，其中 `V = |M_obs intersection M_rnd| / |M_rnd|`。正式采集前必须确保公式、代码和日志一致；当前面积比旧实现不得进入正式结果。
- `color_reprojection < 0` 表示颜色信号不可用，应从几何核排除，而不是视作坏 pose。
- 深度评分保留绝对与结构分量 `D = (1-alpha) D_abs + alpha D_struct`；Run 1 日志必须暴露消融所需分量。
- Python 评估模式的 `RuntimeLogWriter` 已将候选行映射为严格 `PythonCandidateRow`，颜色不可用写入 `null` 并保留解释 flag；runtime 事件与候选行分写固定 schema-v2 文件。
- Python candidate ID 使用 `session_id:frame_id:frame_local_seq`；`RuntimeLogWriter` 关闭时把 candidate/event 的真实 `rows_written`、`dropped_rows` 和 `log_write_failures` 写回 `python_session.json`，供最终 manifest 汇总，Unity 不得伪造 Python 丢行统计。
- `egoanchor.eval` 包级入口只导出 schema-v2、QC 和 Stage 1 workbook 基础设施；论文分析必须从 `egoanchor.eval.experiments.experiment_1_2`、`egoanchor.eval.experiments.experiment_3` 的包级入口或离线 CLI 显式进入，运行时服务不得因论文绘图依赖加载失败。
- `CutieMaskTracker` 不直接导入 `torchvision.transforms.functional.to_tensor`，避免 Windows 图像 DLL 冲突。
- FFS 必须在 server 启动阶段按固定 `pipeline.calibration.process_width/process_height` 完成一次中性立体图完整预热；TRT engine 的尺寸匹配、CUDA 上下文和首次前向不得推迟到 Unity 首帧，预热结果不得进入跟踪状态或日志候选。
- Python OpenCV debug 窗口按 `S` 时从当前诊断数据重新生成并无损保存 pose 与 VCD 两张高分辨率 PNG，默认写入 `data/debug/snapshots/`，尺寸分别为 `2560x1280` 与 `1920x1240`；保存分辨率独立于实时窗口尺寸。VCD 的 render RGB 与 render projected depth 都只在渲染 mask 内显示数据，mask 外统一使用中性棋盘背景。
- 生成代码、`*_pb2.py` 和协议副本不手改。

关键 ownership：`config/` 不导入模型/网络；`transport/` 只管传输；`routing/handlers` 不碰 GPU；`runtime/tracking_runtime.py` 是 pipeline owner；`perception/quest_pose_pipeline.py` 组合视觉模块；`reliability/` 计算 VCD；新 `eval/` 只处理 schema-v2、QC、实验一/二/三和论文产物。

## Unity 关键约束

- `MeasurementTimeSeconds` 属于采集时间轴，用于运动估计与静止锚定；生命周期 freshness 使用到达/生命周期时间轴。不得用 capture time 刷新 stale/lost。
- `has_output_pose` 表示 runtime 是否有输出；`has_display_pose` 表示用户实际看到的 Transform，包括 hold-last。显示误差使用 display pose，输出覆盖率使用 output pose。
- hold-last 显示行从 `DynamicObjectAnchor.LastAppliedFrameId` 保留实际来源帧；只有从未应用或已隐藏的显示才允许 `source_frame_id=-1`。
- 平台控制器参考 pose 只从 `EvalRecorder.groundTruth` 绑定的 Transform 读取。`controller_right` 必须绑定 `OVRCameraRig/OVRInteractionComprehensive/OVRControllerVisualRight/OVRControllerPrefab`，对应 `OVRControllerHelper.m_controller=RTouch` 和 `EvalRecorder.gtController=RTouch`；不得绑定名称相似但不会更新的静态节点。参考对象激活且平台报告可追踪时更新 world pose；失活或隐藏时无限期保持最后一次激活 pose，重新激活后继续更新。激活状态只写入 `reference_pose_fresh/reference_pose_keep_alive` 并在实时板显示 `ACTIVE/HELD`，不得把 OVR 状态当作另一套 pose 来源，也不得因失活停止计算实时差异或让正式日志参考失效。正式 session 启动前必须观察到参考对象至少 1 cm 平移或 5 度旋转；manifest 写入参考 Transform 路径、控制器类型和预检结果，未通过时禁止启动。
- StaticLock tether 计算 `obsConsensus -> anchorOrigin`，不得改成单帧观测或 `lockedPose`。
- 头动期间不冻结真实运动证据；`headSettleSeconds` 只覆盖头停后的沉降窗口。
- 距离自适应只放大位置通道；旋转 tether 必须高于旋转噪声地板。
- `EvalLog` 使用有界后台队列；正式 session 的所有日志 `dropped_rows` 必须为 0。
- Unity manifest 的 `log_files` 与 `EvalSession`/`EvalRecorder` 已固定覆盖 `manifest.json`、`unity_reference.jsonl`、`unity_admission.jsonl`、`unity_render.jsonl` 和本机独占的 `unity_events.jsonl`；render 为 tick×variant 长表，admission 由每个 runtime 的实际处理结果产生。Python 远端独占写入 `python_events.jsonl`。Mutagen 同步完成后，`qc`/`preprocess` 的 Stage 1 事件物化入口在总表缺失时确定性发布 `events.jsonl`；已有总表只验证，不覆盖。两端不再通过跨机器 `.lock` 共同追加同名文件。
- Unity admission 与 event 行已覆盖 schema-v2 必填时间、策略、上下文和 payload 字段；candidate ID 使用 `session_id:frame_id:frame_local_seq`，同一 `PoseResult` 的多 runtime 回调共用标识。
- Unity manifest 将 `run_kind` 固定写为 `formal`，不再暴露运行类型选择；同时写出自动配置哈希、对象、版本、无时长上下界的实验/场景计划、`completed_tasks` 和真实 Unity writer 统计。每个 variant 还必须写出非空 `configuration_fingerprint`，覆盖坐标补偿、运动模型、输出策略、接纳/生命周期/重获取及 StaticLock 的全部生效数值；`config_hash` 必须绑定该指纹，Python QC 同时核对模型、策略、门控、开关和 FNV-1a 哈希。`completed_tasks` 按任务编号记录本 session 最终未作废的 trial，schema-v2 QC 必须与 lifecycle events 重新推导的完成集合核对。`frozen_parameter_set_id` 自动复用整体 `config_hash`，`operator_id` 固定为匿名单操作员，run mode 与 protocol 由代码生成，Git commit 为可选审计字段。Formal 启动不要求现场填写元数据，仍严格要求 Python session 配对和非空变体配置哈希。Python candidate 及跨端 events 总统计在 Unity 停止时明确标为 pending，必须在 Python 停止并同步 `python_session.json` 后完成合并，禁止把 pending 当作 0。
- Unity 正式采集场景维护五项可任意选择的共享物理任务；每项任务同时记录四个实验一系统配置、三个实验二组件消融和 Smoothed KF Extrapolation/Hermite Interpolation 两路策略，不再重复采集任务 6--9。Task 2 的 marker 必须按 `transition_started` / `transition_stopped` 严格交替闭合，用于停止过冲、反向回动和 settling time。`ExperimentInputHandler` 直接在 Inspector 序列化内联 `InputAction`，不使用 binding 字符串、`InputActionAsset` 或 `InputActionReference`；右手摇杆与键盘方向键共用 3×3 九宫格导航，主键盘数字行与小键盘 `1`--`5` 只负责直接选中任务，A/主键盘 Enter/小键盘 Enter 开始，右扳机/小键盘 `+`/`M` 标记，快速短按 B/小键盘 `0`/`E` 结束任务，摇杆按下/`Space` 只作废当前或选中任务，长按 B 1.5 秒/`F` 可随时停止 session。小键盘主流程固定为 `1`--`5` 选任务、`Enter` 开始、`+` 标记、`0` 结束。进入场景后保持未录制的任务选择状态并默认选中任务 1；方向键、右手摇杆或数字键只改变选中项。正式场景的 `EvalSession.autoStart` 固定关闭；A、主 Enter 或小键盘 Enter 的一次新按下必须在同一回调内启动 session 与当前选中 trial，不得要求第二次确认，启动失败时保留选择且不得写 `trial_started`。右手 B 的结束绑定固定为 `Tap(duration=0.5)`，停止绑定固定为 `Hold(duration=1.5)`，防止长按停止前先误结束 trial。停止 session 时活动 trial 先写 `trial_rejected`，已经完成的任务保持不变。数字行路径必须写 `<Keyboard>/1`--`5`，小键盘路径写 `<Keyboard>/numpad1`--`numpad5`，marker 与结束路径分别写 `<Keyboard>/numpadPlus` 和 `<Keyboard>/numpad0`；不得使用无法解析的 `<Keyboard>/digitN`。运行中禁止切场；任务和 session 均无持续时间门禁，实际 trial 时长只记录不判定成败。已完成任务选中后可按开始动作重录，旧 trial 先写 `trial_rejected`；单独作废仍只影响选中任务。状态板只显示 `NEXT`、九宫格、`CURRENT`、直白 `STATE`、单一实际 trial 计时和固定按键图例，不暴露分析内部的 phase/event role；未录制时任务 1 保持黄色选中，一次显式开始动作后才显示绿色运行并启动 trial 计时；蓝色表示完成、灰色表示待执行，已完成任务被选中时保持蓝色并以箭头和粗体区分；Canvas 保持场景根节点静止。`EgoAnchor-Develop.unity` 只用于工程调试，不承担正式采集契约。
- 头显状态板运行时文本统一使用英文 ASCII，因为当前 TextMesh Pro 字体资产不保证 CJK 字形；中文只用于代码注释、Inspector Tooltip、控制台日志和采集手册，不得把中文动态状态字符串传给 `ExperimentStatusUI`。
- 正式采集场景的根 Canvas 固定包含两个同级面板：左侧任务状态板和右侧 `EvalLiveStats` 实时诊断板。实时板以 10 Hz 显示 HMD/佩戴/VR focus/输入 focus、output/display/reference、相对平台控制器的位姿差异、观测年龄、同 Unity 时钟 E2E arrival、Python server processing、smoothing delay、pose rate、VCD、平滑外推校正残差、实际 prediction horizon、continuity reset、frame step 与锚点状态。一般系统信号与显示差异读取唯一主变体 `EgoAnchor`；外推诊断按稳定标签读取 `Smoothed KF Extrapolation`，不得误读主变体的 Linear/SLERP 诊断。缺少该变体时诊断显示为空；已废弃的通用 `latest_residual_*` 字段不得恢复。平台参考差异不是外部真值，实时板不得用于挑选低误差起始时刻；正式指标仍以 schema-v2 离线分析为准。
- marker 成功后状态板显示 2 秒绿色 `MARKER SAVED #N` 和事件角色，非法时显示红色 `MARKER IGNORED`。反馈只属于 UI，不得额外写成实验事件；成功 marker 仍只写既有 `event_marker`。
- `QuestStreamPublisher` 订阅 Meta VR focus：focus 丢失时暂停双目 GPU 读回和 JPEG 编码，恢复后自动继续；录制期间的 `xr_focus_lost/acquired` 写入 Unity events。出现 `HMDUnmounted`、`VrFocusLost` 或 `InputFocusLost` 的活动 trial 应作废重采。
- 正式 `EgoAnchor-Experiment12.unity` 场景使用 9 个唯一 runtime：实验一四配置、实验二三个单组件消融和 Smoothed KF Extrapolation/Hermite Interpolation 两路策略，完整 EgoAnchor 只保留一个共享 runtime；场景契约测试冻结组件矩阵与层级；manifest 写入 `variant_matrix_id=exp12_9_smoothed_hermite_v4`，并记录 VCD、时序合成、StaticLock、低分重获取、服务器重获取开关及整体 `config_hash`。
- `EgoAnchor-Experiment12.unity` 启动正式 session 前由 `EvalRecorder.TryValidateFormalVariantMatrix` 硬校验九路数量、顺序、模型、输出策略、门控、对齐、六个能力开关、runtime 唯一性、显示绑定和唯一主变体；校验失败不得开始录制。两路时序策略的参数仍是 pilot 初值，冻结前不把整体数值 hash 硬编码到启动门禁。
- `EgoAnchor-ReplayCapture.unity` 是 Quest Link 定性图专用场景，只保留实验一四个 runtime 和 `ReplayCaptureRecorder`，不得挂载 `EvalSession`/`EvalRecorder` 或实验二 runtime。采集器复用 `QuestStreamPublisher` 已编码的只读左目 JPEG，不增加 GPU 读回和编码；`captureFps=0` 保存发布器产生的全部帧，按 `ImageUnityFrame` 回查左目相机、四路实际 display pose 和 Quest 官方右手柄参考，直接写入仓库电脑的 `EgoAnchor_Python/data/replay_capture/`。右手柄参考固定读取 `OVRCameraRig/OVRInteractionComprehensive/OVRControllerVisualRight/OVRControllerPrefab` 的 Transform；平台追踪有效时刷新，静止失活时无限期保持最近一次有效 pose，不得写成 null 或切换另一套 pose 来源。后台队列不得阻塞追踪，完整 capture 必须记录真实丢帧、缺 pose、缺标定、参考 fresh/held 和写入失败统计。
- Inspector 参数、坐标语义和时间语义写 XML summary 或 `[Tooltip]`；不隐藏生效参数。
- Unity 生成协议代码和 `SubjectNames.cs` 不手改。

## Schema-v2 与评估原则

Run 1 将原始日志固定为 `manifest.json`、`python_candidates.jsonl`、`python_events.jsonl`、`unity_reference.jsonl`、`unity_admission.jsonl`、`unity_render.jsonl`、`unity_events.jsonl` 和合并后的 `events.jsonl`。`audit_samples/` 是可选目录，只能在实际写入审计样本时按需创建，不得为每个 session 预创建空目录。旧共享事件文件格式不兼容。

- `capture_mono_ms` 是 image-time proxy，不得称曝光真值。
- 平台参考轨迹用于同一 Quest、同一时间线下的配对系统行为分析，不得称外部物理真值。
- 实验一比较 *Arrival-Hold*、*Capture-Hold*、*One-Euro Anchor* 与 *EgoAnchor* 的端到端系统行为。
- 实验二通过三个单组件关闭归因采集时刻世界对齐、VCD 接纳和 StaticLock；时序策略以 Smoothed KF Extrapolation 与关闭 StaticLock 的 Linear/SLERP 为主配对比较，Hermite Interpolation 作为同设置补充条件。
- 静止指标同时报告 HP-RMS、绝对误差和漂移，避免“冻结错误位姿”获得虚假优势。
- 转换指标至少包括 visible response、unlock/relock、peak error 与 settling time。
- 分析先在 `session x trial/event x variant` 内计算，再做 trial/event 配对和 session 汇总；不做 frame-level 推断。
- 正式参数在系统实现完成时随配置固定；所有记录的实验 session 均为 formal，采集后不得调参。
- 图表和 LaTeX 数字由 `egoanchor.eval` 自动生成，主稿不手抄结果。
- 由顺序录制的 Quest 投屏视频生成的轮廓极值叠加图，只能标为二维物体稳像后的定性示意；必须说明各方法片段并非同一候选流，不得把图像像素分离或人工挑选的极端帧写成正式配对指标，也不得替代 schema-v2 工作簿生成的定量证据。
- 新定性 replay 的四种方法来自同一候选流和同一物理采集。离线图默认 6 列、可配置为 2--20 列，默认六行标题为 `Passthrough`、两行显示的 `Quest Reference`、`Arrival`、`Capture`、`One-Euro` 和 `EgoAnchor`，允许从中选择显示行；列必须按连续已保存样本的固定间隔 `N` 选择，显式 sample ID 同样必须按 capture 顺序严格递增且等距，不按误差或每种方法各自的极值挑帧。每列显示行共用同一真实左目背景、相机、时间点和裁剪框；自动裁剪跨列尺寸固定并以平台参考居中，也可显式指定所有列共用的原图裁剪框。默认坐标原点位于第一列第一行图像的左上角，顶部横轴向右显示相对首列的 `Δt (s)`，时间刻度与列中心对齐；纵轴从同一原点向下延伸，六个行中心刻度依次对应显示行。轴线、刻度和横轴相对最后一列图像实际右边缘的精确延伸长度由 TOML 的 `[timeline]` 管理。参考的 fresh 与 held 状态都可用，但图片不显示状态角标，来源只保留在 sidecar JSON。定性出图参数统一由 `egoanchor/qualitative_replay/config/qualitative_replay.toml` 管理，可用自定义 TOML 和显式 CLI 参数逐层覆盖；四方法轮廓色默认严格复用全文共享配色：Arrival `#4C78A8`、Capture `#F28E2B`、One-Euro `#59A14F`、EgoAnchor `#E15759`（唯一定义在 `egoanchor/visuals/__init__.py`，`qualitative_replay.toml` 的 `method_colors_hex` 必须与其逐项一致）。定性 replay 只画轮廓，不使用配对线；实验三 Figure 4 另以浅灰色线连接同一参与者的 One-Euro 与 EgoAnchor 评分。**已知可访问性缺陷**：该绿/红对在绿色盲（deutan）模拟下几乎无法区分，实验三两种方法在图中依靠位置、点形、填充和图例区分而非仅靠色相；若要修正必须全文一次性换成同一套色盲安全配色（Okabe-Ito：One-Euro `#0072B2`、EgoAnchor `#E69F00`、Arrival `#009E73`、Capture `#CC79A7`）并同步重跑实验一/二论文图与定性 replay grid，不得只改实验三而让同一方法在不同图里换色。GLB 的 unlit base-color 纹理默认保留；纹理优先使用与 VCD 一致的 nvdiffrast CUDA 栅格化，`auto` 不可用时才回退 CPU，微小组件过滤和纹理预滤波均由 TOML 显式控制。sidecar 必须保留默认和自定义 TOML、实际 mesh、严格校验模式、最终生效配置及其统一 SHA-256，并记录最终行列、字体、相对首列的 `delta-t`、二维坐标轴原点和刻度、纹理后端、半透明模型、独立参考/方法轮廓、XYZ 轴和裁剪配置。离线投影必须从 runtime 配置指纹恢复 OpenCV GLB 到 Unity 实际 renderer 的对象局部基，不能把已含 anchor-local 补偿的显示根节点 pose 直接作用到原始 GLB；模型轮廓和 XYZ 轴必须共用 `K * P * C` 投影链，同一 capture 中投影相关的 runtime 补偿必须保持一致，该局部矩阵写入 sidecar JSON。该图仍然只是二维定性示意，不得把像素偏移写成正式配对指标或替代 schema-v2 定量证据。首次使用某个对象模型时必须先用 `replay frame` 做实际像素贴合检查。
- 定性窗口的六列必须体现持续差异，不能依赖单列峰值；启动阶段或重获取期间四种方法共同错位的区段必须排除，不能解释为某个基线的抖动。窗口筛选可用平台参考做同一 Quest 时间线内的诊断，但不得称为外部真值或按该诊断发布正式定量结论。
- 定性窗口筛选优先依据最终投影轮廓的可见差异，而非仅凭 pose 数值。需要展示姿态范围时，在轮廓可读的前提下优先覆盖正面、侧转和倾斜视角；论文定性图必须保留物体局部 XYZ 轴、顶部时间轴和纵向方法轴。
- `replay grid` 默认在 PNG 和 sidecar JSON 同目录输出单页 `replay_grid.pdf`，供 LaTeX 直接导入；PDF 只改变封装格式，不改变固定间隔选择、裁剪、纹理或坐标轴。
- 定性图顶部横轴默认显示相对时间；使用 `frame-sequence` 模式时显示可直接用于 `--start-sample-id` 的保存帧序号，二者都不改变固定间隔选择。`[selection].start_sample_id` 为空时自动寻找首段完整序列，填写固定十进制数字序号可作为默认首列，命令行显式起点优先覆盖；该字段受 TOML 契约校验并记录在最终生效配置中。
 - 定性 replay 的 `[selection].row_keys` 选择数据源和顺序，等长的 `[selection].rows` 是按原样显示的左侧标题，不再使用独立的 `layout.row_titles` 映射；两项必须逐项对应。临时改写数据行顺序使用 `--row-keys`。`start_sample_id=""` 明确表示自动寻找完整起点，默认末行标题为两行的 `EgoAnchor (Ours)`。
- **同步状态（2026-07-29）**：论文定性 replay 已按 6 列正式发布，来源为 `EgoAnchor_Python/data/replay_capture/20260723_125041_569_controller_right/rendered/grid/replay_grid.{png,pdf,json}`，论文目录目标为 `2026-EgoAnchor/figures/replay_grid.{png,pdf}`；当前窗口使用 `start_sample_id=000000365`、`frame_step=30`、六列样本 `000000365,000000395,000000425,000000455,000000485,000000515`，四方法可见轮廓色为 Arrival `#4C78A8`、Capture `#F28E2B`、One-Euro `#59A14F`、EgoAnchor `#E15759`，横轴右延伸为 20 px，纹理后端解析为 nvdiffrast。该图已随 `copy-assets exp1-2` 发布并用 `latexmk -g -xelatex` 编译通过。
- schema-v2 reader 按 dataclass 契约严格检查固定字段和跨表稳定键，并把 `python_session.json` 的停止态 writer 统计、Python host/version 合并到内存 manifest。CLI 事件物化入口只有在 `python_stopped`、两个事件分片 schema 合法、实际行数分别匹配 writer 统计且无丢行/写入失败时，才用冻结全序原子发布可重建的 `events.jsonl`；已有文件交给只读 QC 逐字节验证。半同步、pending、错配或非法 fragment 不得留下部分派生文件，也不得进入正式分析；Mutagen 完成同步后允许对同一目录直接重试。
- schema-v2 QC 依据 `variant_matrix_id=exp12_9_smoothed_hermite_v4` 固定要求 9 个唯一 runtime，并冻结完整系统、三个组件对照和两路时序策略。Smoothed KF Extrapolation 的 render 行单独记录 `prediction_horizon_ms`、位置/旋转校正残差和 session 内单调不减的 `continuity_reset_count`；其他策略的前三项必须为 null、计数必须为 0。缺少矩阵标识、配置指纹、任意 variant 或出现名称/方法错配均硬失败。QC 还检查 writer 行数/丢行/失败、candidate/reference 主键、Unity 已消费 candidate×variant 与 tick×variant 矩阵；事实表为空时硬失败。latest-only 未消费 candidate 只统计并警告，Unity admission 指向未知 Python candidate 仍是硬错误。
- Formal schema-v2 QC 按 `trial_started -> trial_ended` 的 Unity 单调时间核对每个最终完成 trial；开始/结束事件必须唯一且顺序合法。实际持续时间作为描述性审计指标记录，不设上下界，也不决定 QC 成败。
- Unity `source_frame_id` 必须来自最近被 policy 接受并实际显示的 frame；被拒候选只能更新诊断用 latest aligned frame，不能覆盖 hold-last 或当前输出的来源。Smoothed KF Extrapolation 的校正残差按观测到达时间衰减，且异步 capture time 晚于渲染 tick 时不得把输出时刻强推到未来观测。
- 中性指标统一按 `session_id × experiment_id × scenario_id × trial_id × event_id × condition_id × variant_id` 组内计算；显示误差使用 `reference_*` 与 `display_*`，output availability 只使用 `has_output_pose`。
- candidate arrival 使用 Unity 同一单调时钟的 `source_capture_mono_ms -> unity_pose_handle_mono_ms`；Python processing 使用 `server_receive_mono_ms -> server_publish_mono_ms`，不得跨进程相减单调时钟。
- 人工事件角色写入 `events.payload.event_role`。五个正式物理任务的完成 trial 都必须至少包含一个 marker；起停 6DoF 必须从 `transition_started` 开始，与 `transition_stopped` 严格交替并成对闭合；遮挡恢复必须从 `occlusion_started` 开始，与 `target_visible` 严格交替并成对闭合。转换与恢复指标按角色切窗，不得根据场景名猜测事件含义；任一实验二消融缺少其冻结关键指标时禁止发布 CSV/PDF/TeX 正式产物。
- schema-v2 基础 QC 始终检查全部原始行；实验一/二正式 QC、指标和 VCD risk-coverage 只投影已有 `trial_ended` 且没有后续 `trial_rejected` 的 trial。被作废和未完成的尝试保留审计记录，但不得进入论文结果。
- 历史离线分析路径和旧 schema 测试已删除；正式分析只从 `EvalSessionV2` 和后续 `egoanchor.eval.cli` 进入。
- 旧命名扫描按语义判定：Unity/Python runtime、writer、namespace 和 CLI 不得依赖或输出旧 RQ/schema 名称；`schema_v2/readers.py`、`schema_v2/qc.py` 及其测试可保留旧文件名和字段名，仅用于显式拒绝旧输入，不得把这些 reject-only guard 当作兼容层删除。
- 实验一分析先对完整 session 执行 schema-v2 基础 QC，再投影 *Arrival-Hold*、*Capture-Hold*、*One-Euro Anchor* 与 *EgoAnchor*；消融和两路时序策略不得混入实验一的 VCD、时延、图表或 LaTeX 数字。
- 实验一单 session QC 只检查实际完成任务的 reference coverage 和 tick×variant 完整性；批次 QC 按已完成 trial 的场景并集要求任务 1--5 全部覆盖。失败时只写 session/trial/批次 QC 审计表并停止，禁止生成正式指标、PDF 和 LaTeX。
- 实验二复用实验一任务 1--5 的同一批 schema-v2 session。采集时刻对齐和 StaticLock 使用静止头动任务，VCD 使用遮挡恢复任务，三项时序策略使用起停、持续运动与遮挡任务；批次仍要求五项物理任务全部覆盖。完整系统的三个归因组件必须全开，每个消融名称必须且只能关闭对应组件；图 3(d) 主比较 Smoothed KF Extrapolation 与 Linear/SLERP，并以 Hermite Interpolation 补充展示。分析同时报告校正边界显示步长、停止前向过冲、反向回动和 settling time。
- 同一分析批次不得包含重复 `session_id`，且 formal run kind、对象、对象模型、协议、整体配置哈希、冻结参数集和 runtime 定义必须一致。`data exp1-2 stage` 只扫描 `task_data_root` 直接子目录，目录名用于任务、版本、时间和对象选择，选中后核对 manifest 的任务、时间、对象和共同身份；批次目录固定为任务 1--5 session 时间组成的 `batch_<task1-time>_..._<task5-time>`。每个原始目录在 `task_workbooks/` 中只有一个缓存，命中时只检查实现指纹、来源内容快照（文件路径加行尾归一摘要，忽略修改时间与 CRLF/LF 差异）、存在性和大小；新建或失效任务才执行完整 workbook-v2 构建与回读。`data exp1-2 promote` 只切换 `batch.json`，`analyze exp1-2` 命中逐 task 指标缓存时不打开 XLSX 大表。Mutagen `logs-5090` 启用期间不得移动或重命名 `data/eval` 原始目录，也不得修改内部固定文件名和 manifest `session_id`。
- 实验二只在组件对应场景内按 `session_id × scenario_id × trial_id × event_id` 配对完整系统与消融。VCD risk-coverage 仅使用完整 *EgoAnchor* 的 capture-time aligned raw 相对同帧平台 reference 的平移误差，单位为毫米；不得用 VCD 或几何评分分量代替 risk，并列分数按同一阈值整体纳入。
- 人工分析只使用 `pixi run eval` 的固定路径工作流；旧顶层 `config/sessions/stage/promote/qc/preprocess/rebuild/copy-assets/experiment3`、旧任意路径 `build-paper` 和 `batch_cli.py` 均已删除，不保留别名或兼容层。
- `data exp1-2 stage`、`data exp1-2 preprocess` 和 `analyze exp1-2 --rebuild` 新写工作簿时，`code_version` 自动读取当前 Git commit，不提供人工覆盖入口；缓存失效使用 Stage 1 相关源码内容指纹，不因无关提交重建。论文分析的 temporal provenance 使用 `temporal_strategy_comparison`。耗时 CLI 阶段使用 `tqdm` 在 stderr 显示任务命中/重建和实验三分析阶段，最终 JSON 只写 stdout。
- `data exp1-2 preprocess` 将失效 task 原子写成完整 XLSX；`analyze exp1-2` 合并五份逐 task 指标结果，并在 `analysis/figures/` 生成八个独立 PDF/PNG 面板、在 `analysis/tex/` 生成三张 TeX 表和图环境；统一构建清单的 `outputs` 冻结全部本地产物路径与摘要，`copy-assets` 只从该清单和 TOML 资源目标构造计划。所有来源必须在写入前统一校验，不得从分析目录残留文件推断资源清单，主稿由研究者手工编辑。
- 自动生成的 LaTeX 控制序列不得含阿拉伯数字；分位数等后缀使用字母拼写（如 `PFifty`、`PNinetyFive`），避免 TeX 在数字处截断命令名。
- 论文发布层的表格和图表必须将内部 `scenario_id`、指标键映射为读者可读的标签；CSV 与 QC 审计文件保留稳定机器字段，二者不得互相替代。
- 分析 reader 对启动阶段的参考时间窗有明确边界：只有 render 内嵌参考有效、`source_capture_mono_ms` 早于首条 `unity_reference` 且 `source_frame_id` 位于首帧之前的 warmup 行可被保留；其余未知 frame-id 仍必须硬失败。指标层同样排除没有右表参考基线的 warmup candidate。
- Run 1 中文采集手册固定为 `2026-EgoAnchor/experiment_1_2_collection_manual_zh.md`；它规定 NATS/Python/Unity 启动、跨端 session 配对、pilot 与参数冻结、实验一/二事件操作、随时停止、QC、失败重采和 formal 参数固定边界。Pilot 不启动 `EvalSession`，不进入正式 raw，也不用于论文回填。
- 中文主稿从 `tables/` 引入由 `copy-assets` 显式复制的指标表；图环境 TeX 由研究者从当前 `analysis/tex/figures/` 审阅后手工纳入。图只从 `figures/panels/` 加载由 `copy-assets` 复制的独立 PDF，并由 LaTeX subfigure 排版。正式分析产物不存在时不得写占位数字或占用图表版面。

## 协议与生成输出

唯一协议源：

- `EgoAnchor_Protocol/subjects.v1.json`
- `EgoAnchor_Protocol/proto/protocol/v1/{common,quest,anchor}.proto`

生成输出：

- Python：`EgoAnchor_Python/src/egoanchor/protocol/v1/*_pb2.py`
- Unity：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/Generated/*.cs`、`SubjectNames.cs`

## 常用验证

Python（`EgoAnchor_Python`）：

```powershell
pixi run python .\src\run_server.py
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src
```

Unity（仓库根目录）：

```powershell
dotnet build "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore
dotnet build "EgoAnchor_Unity\EgoAnchor.csproj" --no-restore
```

协议生成（`EgoAnchor_Python`）：

```powershell
pixi run pwsh -File ..\EgoAnchor_Protocol\tools\generate_proto.ps1
```

论文（`2026-EgoAnchor`，在审阅并纳入图环境 TeX 后）：

```text
latexmk -xelatex -synctex=1 -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_ai_v8.tex
```

## 环境与远端关键坑

- `pixi run build` 会构建 nvdiffrast、FoundationPose 扩展和 FFS artifacts，不作为轻量验证。
- FFS 覆盖导出前必须删除旧 `.onnx` 与 `.onnx.data` sidecar，避免 Windows `PermissionError`。
- nvdiffrast 不放 `[pypi-dependencies]`；使用 `_build-nvdiffrast`。Windows 构建任务内部清理并重建 MSVC/CUDA 环境，`CL/INCLUDE/PATH` 不放 Pixi activation；CUDA 13 同时加入 `targets/x64` 与 `cccl` include。
- Windows 数值栈保持 OpenBLAS；SciPy/scikit-learn 使用 PyPI wheel。OpenCV 只保留 `opencv-python`，避免 DLL/OpenMP 冲突。
- 完整 Windows 环境说明在 `EgoAnchor_Python/docs/windows-prerequisites.md`。
- `EgoAnchor_Python/mutagen.yml` 以本机为唯一源码源，source 使用 `one-way-replica`，日志回传使用 `one-way-safe`；远端 `data/eval/` 与 `data/runtime_logs/` 必须先存在。
- Windows 远端 Mutagen 要求 OpenSSH `DefaultShell=cmd.exe` 且系统代码页为 UTF-8；PowerShell DefaultShell 会使相对 agent 命令失败。

## 项目级实现要求

- 日志统一走门面：Python 使用 `egoanchor.utils`，Unity 使用 `EgoAnchorLog`。
- 新行为先补测试或工程功能自检；最终提供可复现验证命令。
- AI 或自动化工具修改 Unity 文件、保存场景、刷新 AssetDatabase 或触发编译前，必须先确认 Editor 不在 Play Mode。正式采集从进入 Play Mode 到退出期间禁止任何代码写入和 Unity MCP 状态变更。
- 不恢复旧端口、旧 MessagePack/JSON pose、旧 NATS 图像流、旧 Python/Unity 入口或旧 eval schema。
- 不添加 `FormerlySerializedAs`、旧字段、旧路径、旧标签或旧 CLI 兼容层。
- 改 schema 时同步 writer、reader、分析、论文接口和本文件。

## 当前离线分析事实

- Stage 1 workbook-v2 契约、XLSX writer 和回读验证保持不变；活动 `batch.json` 引用的 `task_1_complete.xlsx` 到 `task_5_complete.xlsx` 是论文分析的唯一正式输入。
- `experiments/experiment_1_2/analysis` 的只读 XLSX reader 直接解析 ZIP/XML 和逻辑分片 sheet；每本 XLSX 的指标独立缓存为严格 JSON，非有限浮点显式编码，性能统计保存可跨 task 合并的原始样本。缓存键绑定 workbook SHA、`paper.toml` SHA 和 `analysis/metrics.py`、`analysis/xlsx.py` 内容指纹。
- 实验一图固定为静止平移、静止旋转、动态平移和动态旋转四个误差--抖动双纵轴 LaTeX 子图同占一行，每个子图使用 `0.245\textwidth`；实验二固定为 capture-time alignment、StaticLock、VCD 和 temporal strategy 四个 LaTeX 子图同占一行，其中时序面板展示 Smoothed KF Extrapolation、Linear/SLERP 与 Hermite Interpolation。实验一原始片段点、中位数和 IQR 均保留，左右指标以错位 marker、轴颜色和明确单位共同区分；缺失或重复键必须拒绝绘图，图内最终字号不得小于 7 pt。图 3(a)--(c) 的原生宽度应与 `0.18\textwidth` 目标宽度一致，图 3(d) 的原生宽高比与 `0.40\textwidth` 目标严格匹配；四张面板保留固定等高 PDF 画布和相同坐标轴上下边界，二元开关横轴使用不重叠的 `On`/`Off` 标签。图二、图三的可见点统一导出到 `analysis/plots/figure_plot_data.xlsx`。
- 论文构建使用 `egoanchor_cn_ai_v8` basename（`makefile` 的 `SOURCE` 已同步）；PDF 与辅助产物写入 `2026-EgoAnchor/pdf/`，当前编译产物为 `pdf/egoanchor_cn_ai_v8.pdf`，仅供内部审阅。工作区的 LaTeX Workshop 输出目录同步设为 `%DIR%/pdf`，不得再固定为无关的 `EgoAnchor` jobname。
- 实验一正文拆为静止与遮挡稳定性、动态 6DoF 保真度两张表。表一依次报告中心化泄漏、绝对注册、静止帧间增量、遮挡平移 P95，并把 Start-transition 放在最右列；表二只报告平移/旋转 effective lag、lag-aligned RMSE 和 current-time RMSE。实验二归因表固定为采集时刻对齐、StaticLock、VCD 判别性和时序策略四行；VCD admission、停止护栏与 Hermite 补充只保留在完整指标、图或审计输出中，不进入主表。
- capture-time alignment 直接比较完整 EgoAnchor 同一 raw candidate 的 capture-time 与 arrival-time 世界复合 P95；StaticLock 使用中心化静止 P95；VCD 判别性比较 `occlusion_started` event 的排序 AURC 与全覆盖风险；时序策略比较同样关闭 StaticLock 的 Linear/SLERP 与 Smoothed KF 的平移、旋转 lag-aligned RMSE。
- 正式数字必须由当前五本 Stage 1 XLSX 计算，不保留或读取历史 GPT 结果包。
- 当前 Stage 1 不拆分多任务 session，也不合并多个 session；正式组合使用五个不同 session，每个
  session 只完成对应的一项任务。新组合清单先进入 `data/experiments/_staging/`，旧清单和旧分析进入
  `data/experiments/_archive/`；共享 `task_data/`、`task_workbooks/` 和 `task_analysis/` 不随组合重复复制。
- `batch.json` 中的每条任务记录必须与对应 `task_workbooks/<source>/cache.json` 逐字段一致；活动切换拒绝符号链接、同名归档覆盖和没有清单的旧活动快照。`promote` 只从旧活动清单读取 `batch_id` 用于归档命名，不复核它引用的任务缓存：旧清单的 schema 过期或缓存失效不得阻塞一个已完整验证的新批次，但清单存在而读不出合法 `batch_id` 时仍必须显式失败，禁止静默覆盖。
- 提升任务缓存 schema 会使全部五项缓存同时失效，且 `validate`、`analyze` 和 `data exp1-2 preprocess` 都按活动清单严格加载，无法自行修复；唯一恢复路径是重新 `stage` 后 `promote`。重新 stage 必须用 `--task-version` 逐项固定当前活动版本，否则默认选最高版本会静默改变批次身份和论文输入。重建只改 `code_version` 与工作簿 SHA，不改论文数字。论文指标缓存另保存结果正文 SHA-256，正文被修改时自动失效并重算；这些检查只读取小型清单，不恢复五本 XLSX 的重复扫描。
- `figure_plot_data.xlsx` 是与 PNG/PDF 面板共享同一分析结果的审计导出，不是绘图输入；正式流程
  没有独立的 plot XLSX 转图片命令。
- 复现命令、批次归档、退出码和故障排查统一见 `EgoAnchor_Python/docs/analysis_pipeline.md` 与中文复现手册。

## AGENTS.md 维护规则

- 不修改顶部 `USER-MAINTAINED-REQUIREMENTS` 区块。
- 只写当前事实、长期约束、已冻结路线和会直接导致失败的历史坑。
- 不记录 session 数字、迁移 hash、调参过程、旧图窗或一次性排障过程。
- 事实变化时直接改原条目，不追加相互矛盾的新说明。
