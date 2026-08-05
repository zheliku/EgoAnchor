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
10. 修改论文时，不要防御性表述、不要补丁式修改、注意全文的连贯通顺，以及不要钻牛角尖，不要本末倒置，不要忘记我们论文的核心。
11. 每次操作完后记得更新AGENTS.md

<!-- USER-MAINTAINED-REQUIREMENTS:END -->

本文件只记录当前事实、长期约束和已冻结路线。逐轮评审日志、实验过程、旧 session 数字、迁移 hash、调参记录和一次性排障不写入本文件；事实变化时直接改原条目，不追加相互矛盾的新说明。

## 项目核心

EgoAnchor 是面向透视混合现实（PMR）的**零样本动态真实物体锚定系统**。中心论点：**开放视觉后端输出的异步 6DoF pose 不是可直接消费的 MR anchor**。系统把低频、异步、质量不均的视觉位姿观测，转换为消费级 MR 应用可持续绑定的世界系对象锚点。

主叙事固定为 `pose estimate != usable MR anchor`。平台原生支持范围只解释外部感知为何必要；零样本视觉感知只说明给定三维模型的更多刚体为何可被定位。**两者都不是核心贡献**；核心问题是如何为异步观测恢复时间语义、判断是否接纳，并控制持续锚点的逐帧输出与生命周期。

两层解耦架构：

- **感知后端**（外部 GPU 工作站）：语义初始化 → 时序分割 → 立体几何重建 → 零样本位姿估计，输出 camera-space pose 与 VCD 可靠性评分。
- **锚定运行时**（头显端）：按 `frame_id` 回查采集时刻相机位姿并复合为世界锚点。四项机制为**采集时刻对齐 / 时间索引轨迹取值 / 显式静止锚定 / 分级生命周期**。

三个时刻贯穿两层：采集 $t_f$（定空间语义）、到达 $t_a$（只定何时收到）、渲染 $t_r$（定何时需要输出）。

VCD 的三个语义层次不得混淆：方法输出 `[0,1]` 连续可靠性评分；运行时以冻结阈值执行 admission；离线按分数诱导候选顺序，用 risk-coverage/AURC 检验评分的风险判别性。VCD 本身不是排序算法，也不是位姿正确概率。

## 诚实边界

- 「纯视觉」只修饰物体位姿估计链路；系统仍依赖外部消费级 GPU、局域网与头显平台追踪。
- 系统需要目标三维模型，不得声称适用于任意对象。
- 控制器 pose 是平台参考位姿，不是外部光学真值；它与头显共享追踪系统，会隐藏共模世界漂移。
- 采集时刻对齐只校正相机采集/到达时刻错配，不补偿采集后的物体运动。
- 单操作员、多 session 的帧只表示时间覆盖，不作为独立样本量。
- 实验三只报告主观评价与无需平台真值的自参考稳定性日志，不报绝对配准误差、不主张任务表现证据、不作中介效应主张。
- Meta、Apple 与专用追踪附件只作为能力定位对象，必须以官方或同行评审来源说明其对象绑定语义与前提。跨平台数值只作描述性上下文，不支撑核心贡献。

## 论文宗旨与当前稿件

投稿目标 IEEE VR 2027（正文含图表 9 页 + 参考文献另 2 页）。标题定为**「EgoAnchor：透视混合现实中日常物体的稳定零样本动态锚定」**（*EgoAnchor: Stable Zero-Shot Dynamic Anchoring of Everyday Objects in Passthrough Mixed Reality*）；系统描述位统一为「零样本动态真实物体锚定系统」。

**当前工作稿 `2026-EgoAnchor/egoanchor_cn_final_v1.tex`**：`latexmk -g -xelatex` 通过，11 页、0 undefined、0 overfull；`makefile` 的 `SOURCE` 已切至该文件，直接 `make` 即可，产物为 `2026-EgoAnchor/pdf/egoanchor_cn_final_v1.*`。`egoanchor_cn_v3.tex`、`egoanchor_cn_v2.tex` 及更早稿冻结备查，不再改动，也不得用旧稿覆盖当前章节。

定位为**系统论文，但方法部分按学术标准写**：凝练核心思想、学术化表达，不逐一介绍工程实现。行文精炼、控制篇幅，保持高度学术化。

三项贡献（顺序与短标题已冻结）：

1. **EgoAnchor 系统**：感知后端与锚定运行时解耦的零样本动态真实物体锚定系统，含基于 `frame_id` 的采集时刻对齐。
2. **VCD 位姿验证与状态感知的锚定运行时**：VCD 拒绝物理错误的候选，**因而使遮挡后的重新获取成为可能**；运行时四项机制承担时间语义、轨迹取值、静止锚定与生命周期。VCD 跑在感知后端，**不并入「运行时四项机制」计数**，全文也不得出现「五项机制」。
3. **三层评价**：系统表征、组件归因、跨对象感知评价，各一句。

三个实验（论文外部不再使用 RQ1/RQ2/RQ3 作为顶层结构）：

- **实验一 端到端系统表征**：静止+主动头动 / 起停 6DoF / 持续平移 / 持续旋转 / 遮挡恢复五个场景，比较 *Arrival-Hold*、*Capture-Hold*、*One-Euro Anchor* 与 *EgoAnchor* 的系统行为。
- **实验二 系统设计归因**：同批日志、同平台参考下关闭单一设计，归因采集时刻对齐、VCD 接纳与 StaticLock；时序策略以 Smoothed KF Extrapolation 对关闭 StaticLock 的 Linear/SLERP 为主比较，Hermite Interpolation 仅作审计条件。
- **实验三 日常物体上的跨对象感知评价**：`2 方法 × 3 物体 = 6 区块` 被试内、24 人、纯主观，只比较 *One-Euro Anchor* 与完整 *EgoAnchor*。

当前缺口（未处理，不是待办日志而是稿件现状）：

- **teaser（Figure 1）与 `fig:arch`（Figure 2）仍共用 `figures/pipeline.png`，待用户重绘**，属审稿人可见缺陷。teaser 目标图为 5 个日常物体的锚定拼图，caption 已写明「三个用户研究物体 + 两个仅作定性展示」，重绘后无需再改文字。
- Figure 6 仍排在结论之后（机制见「版面」条）。
- 八条 arXiv-only 参考文献未升级为正式出版信息（`foundationpose2023`、`megapose2022`、`cosypose2020`、`cutie2024`、`bundlesdf2023`、`hodan2020bop`、`posecnn2017`、`densefusion2019`），需联网逐条核实卷期页码，**不得凭记忆填写**。
- 两处 `% TODO(用户核实)`：§4 多 GPU 的 70--130~ms 区间、§5.3 伦理审批编号。

- 实验一/二为单操作员采集，正文未声明操作员数量。当前只报片段级 median [Q1, Q3]、无推断统计，故未违反诚实边界；**一旦加入任何推断统计或声明 N，必须先披露单操作员事实**。

配套文件：`2026-EgoAnchor/plan.md` 为系统论文框架，`2026-EgoAnchor/revision_plan_final_v1.md` 为 final_v1 修改计划书（供用户逐项核对，不是日志）。

**bib 维护坑**：BibTeX **不接受 entry 内 `%` 注释**（IDE 会报缺字段名），投稿前待办只能写成 entry **前**一行的 `%` 注释，不得塞进 `note` 字段——否则会被排版进参考文献（`metaDynamicObjectTracker`、`yoloe2025`、`sam3_2025` 曾出现「recheck before submission」被印出）。

## 论文硬约束（易错，逐条核对后再改稿）

### 术语五层规则（每层只允许一个名字）

| 层次 | 固定名字 | 出现位置 |
| --- | --- | --- |
| 系统级流水线 | 零样本对象感知流水线 | 摘要、§1、§3.2.1 首句 |
| 研究领域能力 | 开放词表检测与分割 / 立体匹配 / 模型驱动的零样本6DoF位姿估计 | §1、§2.1、§2.2 |
| 我们的四个阶段 | 语义初始化 / 时序分割 / 立体几何重建 / 零样本位姿估计 | **仅 §3.2.1** |
| 具体模型名 | —— | **仅 §4** |
| 运行时四项机制 | 采集时刻对齐 / 时间索引轨迹取值 / 显式静止锚定 / 分级生命周期 | 摘要、贡献 2、§3.3、§8 |

**已归零、不得复活的旧名**：采集时刻配准、采集时刻世界配准、采集时刻世界对齐、双目深度估计、双目重建、延迟插值、时序合成、开放词表分割（漏检测阶段）、观测轴/渲染轴/跨轴、两条通路/两条并发更新通路/两个事件源、锚点交付（GPT 造词）、易部署/广适用/稳锚定三标签、G1/G2/G3 标签、$\mathcal{V}_f$、漂移**租**绳（正确为漂移**系**绳）、RTX 5070（从未跑过）。

其余术语口径：正文统一「感知后端」（不写「视觉感知后端」/「视觉后端」）；**方法名全文一律短名 Arrival / Capture / One-Euro**，`variant_matrix_id` 里的 *Arrival-Hold* / *Capture-Hold* / *One-Euro Anchor* 只是数据管线 ID，不回填正文；「冻结」只保留运行时含义（冻结保持、冻结解锁判据），实验设计与分析口径一律写「预先固定」；「端到端」保留且**不加防守性限定语**，两层部署是贡献 1 本身而非局限；§4「运动估计采用常速度卡尔曼滤波」保留——该处指实现手段，不是机制名。

### §3 结构与符号

四个子节及其 label（**label 不改，改 label 只增加引用风险、零读者收益**）：`sec:obs-update` **观测处理**（采集时刻对齐 / 观测准入 / 状态更新）、`sec:frame-output` **锚点合成**（查询时刻 / 轨迹取值 / 输出模式）、`sec:staticlock` **静止锚定**、`sec:lifecycle` **生命周期管理**；§3.4 `sec:runtime-alg` 为运行时算法。散文中「逐帧输出策略」「观测更新率」指策略与频率，仍可用。

- `eq:staticlock` 属 §3.3.2（**静止锚定是锚点合成的一部分**），故 §3.3.2 产出 $\widetilde{T}_o^w(t_r)$；§3.3.3 作用域收窄为 $\mathsf{Locked}$ 分支的入锁/锁内/解锁。生命周期保持独立子节：StaticLock 决定输出**在哪**，生命周期决定它**以何种可信度交付**。
- 运行时是**帧内串行两步**，不是并发：`Update()` 排空 NATS（`MaxMessagesPerFrame` 默认 1）先于 `LateUpdate()` 的 `Advance`，同帧同线程。真正成立的是速率不对称（候选约 9.5~Hz 对刷新 72/90~Hz），多数帧只执行锚点合成。不变量：**轨迹只在观测处理中追加，锚点合成不外推**，每帧输出只依赖已到达的观测。
- 每个子节以一句框架句开场再进 `\textbf{}` 段，是全章体例，不得为省版面删除。
- **符号层级**：$T_o^w$（单次观测直接复合）→ $\widehat{T}_o^w$（状态估计平滑后）→ $\widetilde{T}_o^w$（提交给应用的锚点）。$j$ 标记被接纳观测的到达次序（控制点与被接纳观测一一对应）；$k$ 为 VCD 模态下标，有效模态集为 $\mathcal{K}_f$；漂移偏移 $d_{\mathrm{org},j}$（归入距离族）；运动持续时间 $t_j^{\mathrm{mov}}$/$t^{\mathrm{mov}}_{\max}$（归入 $t$ 族）；深度分量 $S_f^{D,\mathrm{abs}}$/$S_f^{D,\mathrm{str}}$；最新控制点采集时刻 $t_{\mathrm{latest}}$；锁定位姿 $T_{\mathrm{lock}}^w$（不写四段下标 $T_{o,\mathrm{lock}}^w$）。$f_x$ 与帧标识 $f$ 共用字母保留（标准记法且已注明「校正后的像素焦距」）。
- $\mathrm{SE}(3)$ 只写「由旋转与平移构成的位姿变换，多个变换按矩阵乘法顺序复合」，**不引入群论措辞、不使用 $\circ$**（`eq:capture-alignment` 已改矩阵并置）。
- 已删且不得复活：`eq:temporal-alignment`/`eq:spatial-alignment`（合并为 `eq:capture-alignment`）、`eq:admission` 集合式与 $\mathcal{O}^{+}$（改行内条件）、`eq:unlock`（改四分点列表：证据触顶/漂移系绳/速度逃逸/可靠性失效）、`eq:deadband`、集合记号 $A_j$、§1 论文组织段、§3.1 三性质标签段、「逐帧流程」散文段。
- 算法 1 为 12 行、标题「运行时算法」、`\Statex` 标注「候选到达时 / 每个渲染帧」，注释只引用公式号或小节号之一，不混用。

### 数字口径

- **2.69× 与 17.06× 是逐片段配对中位数，不得用表 1 相除重算**（表 1 无 *EgoAnchor w/o StaticLock* 对照臂）。每个比值须在同句内自带 on/off 数对与对照臂配置。17.06× 必须写「中心化静止**平移**误差」，旋转证据指向图 2(b)。摘要不写「降低 N 倍」，固定为「降至……的 1/N」。
- **当前时刻代价只对平移成立**：平移 RMSE Arrival 84.74 → EgoAnchor 125.83（最差），旋转 One-Euro 34.10 → EgoAnchor 31.88（EgoAnchor 更好）。全文统一「更大的当前时刻**平移**误差」。
- **不得写「均优于三个对照配置」而不带范围限定**：`tables/exp1_performance.tex` 显示 EgoAnchor 在 Start-transition、有效时延（平移与旋转）、当前时刻 RMSE（平移与旋转）共 5 行落后，必须写「在**静止、遮挡与时延对齐后的运动误差**上均优于三个对照」。
- **不得写「四组已发表量表」**：TiA-R/C 与 TiA-U/P 是同一量表的两个子量表，正确写法是「四项已发表量表**结局**」（横跨 AQ / TiA / S-TIAS 三种工具）。
- 阴性口径全文统一「**未检测到显著差异**」，不写「用户无法区分」也不写「未出现差异」。两项阴性（运动附着、姿态一致）点名与稳定优先代价句是**摘要强制项**，不因对齐参考论文风格而删。
- 必须披露 **AQ-IQ 的 α：One-Euro .504 / EgoAnchor .892**（AQ-IQ 恰是唯一不显著的已发表量表结局，p=.446），TiA-U/P 的 .565/.769 同步内联；只陈述数值，不加防守性从句。
- 候选率：§4 用活动批次的 **9.52~Hz**（配套 75.44 / 88.47 / 105.07），并预先说明「在第 6 节的日常物体条件下约为 12.9~Hz」；§6.3 实验三为 12.85/12.86~Hz。已归档批次的 9.37 等旧数不得回填。
- 不使用笼统的「毫米级精度」：中心化静止可达亚毫米，绝对注册 6.60~mm，持续运动当前时刻误差约 126~mm，§7.1 与讨论节须显式界定口径。

### 部署与平台口径

`unity_run_mode = editor_link` 的事实：`EvalSession.ResolveRunMode()` 为 `Application.isEditor ? "editor_link" : "player_<platform>"`；`EgoAnchor_Python/data/eval/` 下 33 个带该字段的 manifest **全部为 `editor_link`**，无 `player_android`（`EgoAnchor_Unity/Build/` 有 16 个 APK，即 on-device 路径真实存在但未用于正式评测）。故运行时 C# 在 PC 的 Unity Editor 进程内执行，Quest 3 提供 passthrough 图像与头部追踪并显示。定稿口径（2026-08-05 用户裁定，推翻其 2026-08-03 的旧裁定）：

- §4：「对象锚定运行时运行于头显端……实验中头显端运行时经 Meta Quest Link 部署于一台配备 Intel Core i9-14900K CPU 与 32~GB 内存的主机，Meta Quest 3 承担双目图像采集、设备位姿追踪与显示」。
- §1 用「运行于**头显端**」——层的角色词，不指定执行硬件。
- 摘要「我们在 Meta Quest 3 上实现 EgoAnchor」**保留**：陈述实现平台而非执行位置。
- §3.1 与 `fig:arch` caption 只说「两层」、不提硬件，无需改动。
- 有效时延**不含** Link 串流往返：它由 `unity_render.jsonl` 与 `unity_reference.jsonl` 在同一 Unity 时钟上对齐求得，两者都在显示之前记录。

硬件与版本（已核实，改前先核对 `ServerEndpointConfig` 三处 preset `selected: 2` → `RTX5090 = 172.24.247.32`）：感知工作站远程 **RTX 5090 / 32~GB 显存**；Link 主机 **i9-14900K / 32~GB**；Python 3.14.6、PyTorch 2.12.1+cu130、CUDA 13.2 (V13.2.78)、TensorRT 11.1.0.106、OpenCV 4.13.0、**Unity 6000.3.11f1**（不写「Unity 6」）、Meta XR SDK 203.0.0。感知后端另在 RTX 3090 / 4090 / 5080 Laptop 上运行过，处理时间约 70--130~ms（描述性上下文，正式结果全部取自 RTX 5090）。

相关工作平台口径（2026-08-04 联网核实）：Meta Dynamic Object Tracker **只支持键盘**、一次一个、Quest 3/3S + OS v72+、需用户显式启用；Apple 对象追踪已在 **visionOS 27** 扩展至运动中与手持物体（WWDC26 Session 283），但**仍要求逐物体提供三维模型并用 Create ML 在设备外离线训练**。故固定口径：**平台动态对象追踪正在扩展，但仍以逐物体离线准备或系统支持的对象集合为前提**，EgoAnchor 的「无需逐物体训练」差异点不失效。bib：`appleObjectTracking2026` 已增，`appleObjectAnchor` 与 `metaDynamicObjectTracker` 的 year 更新为 2026、访问日期 2026-08-04。

### 版面（浮动体机制，三次独立确认）

**页数由浮动体数目对可用页顶数决定，不由正文长度决定。压缩正文可能使总页数增加**——腾出的空间反而让浮动体有条件迁到下一个页顶（实测：三处压缩后表 2 由 p7 迁至 p8，总页数 10 → 11）。抢页不要靠削正文。

- 附录表 3 独占末页的机制已查明：`\appendix` 前有 `\clearpage`，且表 3 是 `[t]`-only，末页页顶已被参考文献续页占据，浮动体只能顺延。删 `\clearpage` + 改 `[!htbp]` 实测可压到 10 页，**但用户裁定「附录让它独占一页」，定稿 11 页，不要再以省页为由改动这两处**。
- Figure 6 同属「页顶排队」问题：**动 `\clearpage` 与浮动体放行参数比压正文有效**（曾误诊为「压缩正文约半栏即可」，实测证伪——压缩会把参考文献起始位置一起左移，Figure 6 同步前移）。
- **拒绝 `\FloatBarrier`**：放在 §4 前虽让算法 1 不打断 §4 首段，但**表 1 被挤出第 6 页**、离开它在 §6.1 的讨论。表 1 贴着讨论更重要。
- `tables/` 由分析流水线生成，**不改其中的浮动体参数**。前言放宽了 `\dbltopfraction` 等参数以容纳 4 图 + 1 宽表，调整该组参数前先确认浮动体总面积没有增加。

### 写作风格（已冻结）

- **正面定义作用域，不用否定句预先防守**；边界集中在 §6.2，不在正文中途插免责从句；不在已有定义处再补否定。
- **不给公式补边界情形、不给修正挂防御尾句**。判据：修事实错误时先问「能不能只改一个词」；给公式加话前先问「审稿人真会问这个吗」。
- 原文既有的「这一取舍是有意的」「被拒候选不写入轨迹」「符号可交换」「而非外部光学系统给出的物理真值」是用户自己的表述，**不属清理范围，不要顺手清理**。
- **必须逐字存活的强制句**：§6.1 「两者均不等价于零时延的当前时刻配准误差，帧对齐也不是对物体运动时延的补偿」；§5.2 「对齐残差描述移除相位差后的轨迹保真度，current-time RMSE 描述同一渲染时刻的实际配准误差，前者不能替代后者」；§6.2 的平台参考非真值、共模漂移不可观测、日常物体无平台参考、实验三不主张感知效用四项。改写不得改变段落在论证中的功能，也不得删除任何强制项。
- **§7.1 实验三的作用域声明保留**（两个条件都启用采集时刻对齐与 VCD，只在运动模型与 StaticLock 上不同，故它检验的是稳定优先输出策略的感知效用，而非整个系统的有效性）。这是准确的范围陈述，不是防御性写作。不得把「采集时刻对齐 → 位置正确性提升」直接连线，那是越界归因。
- 参考论文为 VRGaussianAvatar（`reference/`，原文 `tmp/vrga_raw.txt`）：§4 Experiments / §5 Results 两分、附录在参考文献之后、结论零数字零阴性。对齐其文风时保留本文自身的强制项。

## 论文所依赖的代码事实（曾被写错，不得凭旧说行事）

- **`weighted_geometric_mean` 无有效模态时返回 `1.0`，不是 `0.0`**：`reliability/pose_quality.py` 的 `_geometry_core`（L168--182）在 `weight_sum <= 0.0` 时 `return 1.0`，即 $\mathcal{K}_f=\varnothing$ 给出 $R_f = V_f$（docstring：两路都无信号时保持当前 pose 信任）。`_mask_factor`（L192--215）在无投影面积信号时回落到 `mask_area_ratio` 启发式，故除零路径同样不可达。**结论仍是正文不写退化情形**，但理由必须是上述实测；`\mathcal{K}_f=\varnothing \Rightarrow R_f=0` 方向相反，已否决。
- **三个同尺度阈值互不相同，不得混用**：准入 `minQualityScore=0.2` / 低分重新注册 `0.45` / 追踪新鲜度 `trackingScoreFloor=0.5`。正文只出现 $R_{\min}$ 与 $R_{\mathrm{live}}$ 两个记号，0.45 只留在附录。
- **生命周期边界**（`AnchorStateMachine.cs:105-115`）：gap ≤ 0.45~s → Coasting，0.45--1.0~s → FrozenUncertain，≥ 1.0~s → Lost。故 450~ms 是**缓冲保持时长**，不是「进入缓冲保持」的门槛（无可靠观测时立刻进缓冲保持）。
- **VCD 拒绝提前 return、不刷新时间戳**（`AnchorPolicyHost.cs:333-339` 对 `:374-378`），即被拒候选**不**计入新鲜度，gap 与无候选同路累积。若写成「也计入」，因果就反了（持续坏观测会永停 Coasting）。
- **`OnUncertainPose` 置的 `FrozenUncertain` 是瞬态**：`Advance:404-413` 每帧按 `lifecycleGap` 重算并覆盖状态。只读 `AcceptPose` 会得出相反结论。
- **区分「拒绝坏观测」与「长时间无观测」的真实载体是 `TryLowScoreReacquire`**（`:326`，在 VCD 门控**之前**、对 raw observation 判定），阈值 0.45、持续 600~ms、冷却 3~s。算法 1 因此把「可靠性持续过低则请求重新注册」放在准入判断**之前**。
- **有效时延搜索区间 `[0, 600]`~ms、步长 5~ms**（`paper.toml` 的 `minimum_ms/maximum_ms/step_ms`，`metrics.py` 的 `query_times = times - lag_ms` 为正向滞后）。旧稿的 `[-500, 0]` 上下界与符号全错。
- **$\widehat{\tau}$ 由快升慢降的非对称 EMA 给出**（`AnchorMath.UpdateAsymmetricEma`，上行 0.5 / 下行 0.05），**不是滑动中位数**；`MaxDelayChangePerSecond = 0.05` 属实现细节，不写入正文。「端到端时延」这一命名保留：`HistoricalInterpolationStrategy.cs:95` 的 `observedLatency = nowSeconds - latest.TimeSeconds` 确实度量采集到渲染。
- **不得写「所有阈值随头动强度自适应放大」**：随头动因子缩放的只有运动判据（入锁速度、速度逃逸、漂移系绳、死区）；`staticEnterMinScore`、CUSUM 上限、低分释放均不缩放，蠕变增益随头动**削弱**。正文口径固定为「运动判据随头动强度放宽，可靠性判据不随之放松」。
- **`staticSpeedThresholdMps=0.015` / `staticAngularSpeedThresholdDps=1.5` 是诊断用运动分类阈值，不是入锁门槛**，不得写进论文的入锁条件。
- **控制器外参无标定流程**：`AnchorPoseTransform.cs` 为 Inspector 配置量，`EgoAnchor-Experiment12.unity:498` 实测只有 `cameraLocalPositionOffset.z = -0.016` 与 `anchorLocalRotationOffsetEuler.z = 180`。正文写「该补偿量在全部序列中保持不变、不做逐次标定，其残余误差包含在所报告的注册误差中」，**不写「实验前标定」**。补偿量是**相机系**轴向平移，其世界系方向随头动旋转，故在「静止目标+主动头动」场景残差不是常量，**不得写「残差是常量，因此不影响中心化指标」**。这解释了 6.60~mm 绝对注册与 0.82~mm 中心化泄漏的量级差。
- `eq:vcd` 按代码写「仅对有效模态取加权几何平均并重归一化权重」，故无纹理模型退化为 $R = V \cdot S_D$；**不得写成 SSIM，也不得写成对深度残差取指数**。颜色分为 LAB 三通道加权 ZNCC（L 权重 0.3）并映射 `(rho+1)/2`。
- 第 4 节参数值一律以代码为准（`StaticLockController.cs`、`HistoricalInterpolationStrategy.cs`、`pose_quality.py`、`depth_alignment.py`；19 项 StaticLock 参数已逐项核对一致）。

## 主线目录

| 目录 | 职责 |
| --- | --- |
| `EgoAnchor_Python/src` | 图像接收、感知、VCD、通信、评估分析 |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor` | Quest 采集、时空对齐、公共 admission、四时序策略、显示与录制 |
| `EgoAnchor_Protocol` | Proto 与 subject 唯一来源 |
| `2026-EgoAnchor` | 中文主稿、VGTC 模板、图表、采集手册与论文路线 |

旧 RQ1/RQ2 Unity 脚本、场景、Python 分析包和 `EgoAnchor_Tools3` 已删除，不得恢复。正式评估入口只使用实验一/二命名。

## 不可破坏的系统约束

系统使用三条语义平面：

| 平面 | 传输 | 方向 | 内容 |
| --- | --- | --- | --- |
| Data | ZMQ PUB/SUB | Unity -> Python | `QuestStereoFrame`、`QuestCameraInfo`，multipart，latest-drain |
| Message | NATS Core pub/sub | Python -> Unity | `PoseResult`、状态、heartbeat |
| Command | NATS request/reply | Unity -> Python | reset、reacquire、control，`request_id` 幂等 |

- Python 只输出 camera-space pose；Unity 用 `frame_id` 回查 image-time proxy camera pose 并合成 world anchor。
- 不得用 PoseResult 到达时的 HMD pose 代替发送帧 pose。
- 业务代码不手写 subject；Python 从 `egoanchor.protocol` 包级入口导入，Unity 使用 `SubjectNames`。
- Proto 字段号不得重排；删除字段时同时 `reserved` 字段号和字段名。
- Unity -> Python ZMQ 端口固定为 `15557`。
- NATS handler 只负责 parse、validate、dedup、enqueue、ack；`TrackingRuntime` 顺序拥有 pipeline/GPU 状态。
- **重获取只有一个中央 owner**；四个时序变体不得分别改写共享 Python 感知状态。
- Unity 正式 session 配对可从 `PoseResult`、状态或持续 `ServerHeartbeat` 的 header 获取 `session_id`，不得等待首个 pose；正式采集场景的 NATS 初次连接重试必须开启，使两端启动先后无关。

## 当前运行时架构

```text
PoseResult candidate
  -> frame_id-based capture-time alignment
  -> optional VCD admission
  -> Arrival-Hold / Capture-Hold / One-Euro Anchor / EgoAnchor / component ablations / paired strategy candidate
  -> synchronized display and logs
```

- *Arrival-Hold*：到达时刻复合 + 零阶保持，直接消费异步位姿的朴素基线。
- *Capture-Hold*：采集时刻世界复合 + 零阶保持，隔离 frame alignment。
- *One-Euro Anchor*（schema 保留 ID，场景显示名 *One-Euro Interpolation*）：采集时刻世界复合、VCD 接纳、`OneEuroModel` + `LinearSlerpStrategy`、与完整系统相同的自适应历史目标时刻/生命周期/重获取，**仅关闭 StaticLock**。当前参数按米制位置与约 10~Hz 候选标定为位置 `(minCutoff=0.8, beta=6, derivativeCutoff=2)`、旋转 `(1, 1, 2)`。
- *EgoAnchor*：采集时刻复合、VCD 接纳、Kalman + `LinearSlerpStrategy`、显式静止锚定与生命周期管理。
- 组件消融按 `EgoAnchor w/o <component>` 命名，三项为 w/o capture-time alignment、w/o VCD、w/o StaticLock。
- 实验二两路时序策略 *Smoothed KF Extrapolation* 与 *Hermite Interpolation* 共享候选、Kalman、VCD、生命周期、重获取并关闭 StaticLock，只替换输出策略。
- 正式输出策略统一 `Strategy` 后缀（`HoldStrategy`、`LinearSlerpStrategy`、`SmoothedKalmanExtrapolationStrategy`、`HermiteStrategy`），运动模型统一 `Model` 后缀；日志字符串为 `hold`、`linear_slerp`、`smoothed_kf_extrapolation`、`hermite_interpolation`。废弃策略与兼容分支不得恢复。
- 模型相关 per-variant jump gate 不进入正式比较。
- `KalmanModel` 为连续白噪声加速度 CV 模型，离散过程协方差 `q_a [[dt^3/3, dt^2/2], [dt^2/2, dt]]`；冻结参数位置 `q_a=0.002 m^2/s^3`、`R=0.000004 m^2`，旋转 `q_a=0.2 rad^2/s^3`、`R=0.0004 rad^2`，首帧方差均为 `1`，配置指纹必须含 `q-model:cwna-v1` 及这些数值。协方差校正用 Joseph 形式；共享 admission 拒绝非有限或非递增 measurement time。**VCD 只控制 admission，不得声称测量噪声随 VCD 分数在线自适应**。
- 旋转控制点的 `AngularVelocityRad` 表示控制点姿态下的 body-local 角速度；Kalman/One-Euro 每次校正后重置旋转切空间，并用 SO(3) 右雅可比保存物理角速度，不得混用不同参考姿态下的旋转向量导数。
- 完整 EgoAnchor 及保留 StaticLock 的两个消融统一使用 `enterAngSpeedDps=22`、`unlockDriftDegrees=12`；单项消融不得残留不同 StaticLock 数值。旋转证据必须独立报告，不能用平移收益替代。

## 离线分析与论文产物契约

实验一/二的 v4 正式采集已完成。活动 `batch.json` 为 `batch_20260724_005757_20260724_054822_20260724_233436_20260724_045132_20260724_035344`，五项 session 均 `run_kind=formal`、`variant_matrix_id=exp12_9_smoothed_hermite_v4`、`config_hash=05e5edecf737bf34`，论文表格与当前分析输出逐字节一致。更早的 v3（`q*dt` 协方差）数据只保留为只读工程诊断，不得写成当前运行时的证据。

```text
schema-v2 task directory
  -> validate / data exp1-2 preprocess -> task_workbooks/ 下每个原始目录唯一对应的完整 XLSX
  -> 独立指标缓存 -> task_analysis/ 下每本 XLSX 唯一对应的片段结果
  -> batch.json 选择五项任务 -> analyze exp1-2 合并后生成活动 analysis/ 下的指标、绘图 XLSX、PNG/PDF 和 TeX
  -> copy-assets -> 论文目录中的 PNG/PDF 和表格 TeX
  -> 人工审阅并引入 TeX，按论文工作流手工编译主稿
```

- 人工入口固定为 `pixi run eval`，顶层只有 `status`、`validate`、`analyze`、`copy-assets`、`data`，目标为 `all`/`exp1-2`/`exp3`。旧顶层命令、旧任意路径 `build-paper` 和 `batch_cli.py` 已删除，不保留别名或兼容层。文件系统/工具错误返回 1，批次/schema/QC/论文输入契约失败返回 2。
- 原始 task 目录为只读冷归档；Stage 1 成功后不得再读 JSON/JSONL，也不得把 XLSX 之前的中间文件作为后续输入。
- Stage 1 只对缓存缺失或失效的 task 执行完整 QC 并原子发布 XLSX（写后独立回读校验分片、表头、行数、类型、主外键、来源摘要与超长值，替换前复算来源哈希）；一个 task 失败不得改写其他 task 的缓存。正式工作簿为 `task_N_complete.xlsx`。
- 缓存键绑定 workbook SHA、`paper.toml` SHA 与指标实现内容指纹；`code_version` 自动读当前 Git commit（仅审计，普通提交不触发失效）。论文指标缓存另绑定结果正文 SHA-256。共享样式 `egoanchor.visuals/style.py` 必须纳入实现指纹。
- **提升任务缓存 schema 会使五项缓存同时失效**，唯一恢复路径是重新 `stage` 后 `promote`；重新 stage 必须用 `--task-version` 逐项固定当前活动版本，否则默认选最高版本会静默改变批次身份与论文输入。
- 同一批次不得含重复 `session_id`；五项任务必须共享对象、协议、`config_hash`、冻结参数集与 runtime 矩阵。不得按场景或指标择优拼接。
- `analyze` 只在活动分析目录生成结果，不回填主稿；构建开始即把 `build_result.json` 置 `building`，全部产物摘要冻结后才 `complete`。`copy-assets` 只接受完整且摘要一致的构建，以可回滚事务复制；`copy-assets all` 要求两实验都就绪，不得静默跳过。主稿图环境由研究者维护，主稿编译不属于 `pixi run eval`。
- 统计单位固定为 **event/segment，不是 frame**：先在 `session × experiment × scenario × trial × event × condition × variant` 组内计算，再做同 event/segment 配对与 session 汇总，不做 frame-level 推断。每个场景单独报告，禁止跨场景混池算全局总分或排名。
- 显示误差使用 `reference_*` 与 `display_*`；output availability 只用 `has_output_pose`。candidate arrival 用 Unity 同一单调时钟的 `source_capture_mono_ms -> unity_pose_handle_mono_ms`；Python processing 用 `server_receive_mono_ms -> server_publish_mono_ms`，**不得跨进程相减单调时钟**。
- `capture_mono_ms` 是 image-time proxy，不得称曝光真值。平台参考轨迹只用于同一 Quest、同一时间线下的配对分析，不得称外部物理真值。
- 静止指标同时报告 HP-RMS、绝对误差与漂移，避免「冻结错误位姿」获得虚假优势；转换指标至少含 visible response、unlock/relock、peak error 与 settling time。
- 图二以四方法为横轴，左移实心圆为误差、右移空心菱形为抖动；静止误差用中心化 P95，动态误差用 lag-aligned RMSE，动态抖动必须用同一最佳时延下残差轨迹的帧间增量 P95（**不得把真实运动计为抖动**）。合并表另报不补偿时延的 current-time RMSE。图 3(c) 保留 event 风险曲线、median 与 IQR，横轴为按 VCD 分数从高到低保留候选的比例。图 3(d) 只展示 Smoothed KF 与 Linear/SLERP，**不展示 Hermite**。
- VCD risk-coverage 只在最终有效的 `occlusion_started` event 内计算：仅用完整 EgoAnchor 的 capture-time aligned raw pose 相对同帧有效平台参考的平移误差（mm），按分数降序、同分整组进入，以保留候选的平均平移误差为 selective risk，右连续阶梯积分得 event AURC。不得按 admission 过滤低分候选，不得跨 event 混池，不得用 VCD 分量代替 risk。
- 正文图为分析器原生生成的两张 `1×4` 双栏组合 PDF `figure2_exp1_behavior` 与 `figure3_exp2_attribution`，加实验三 `figure4_exp3_subjective_outcomes`；基础字号 7.4~pt、子图标题 7.2~pt 加粗、画布宽 7.15~in。八个独立子图 PNG/PDF 只作审计，正文不引用。缺失、重复键或非有限值必须拒绝绘图。图中可见点统一导出到 `analysis/plots/figure_plot_data.xlsx`（**审计导出，不是绘图输入**）。不恢复 `figures/make_paper_figures.py`、`panels_v9` 或 LaTeX subfigure 拼图路线。
- 实验一表格为单栏 `tables/exp1_performance.tex`（方法作列、指标作行，不显示 `n=` 或 `[Q1,Q3]`，`\normalsize` + `\columnwidth`）；实验二归因表不进正文，关键数值由图与结果文字承担。读者表格连续数值固定两位小数，完整精度留在 `analysis/metrics/`；发布层必须把内部 `scenario_id` 与指标键映射为可读标签，CSV/QC 审计文件保留稳定机器字段。
- 自动生成的 LaTeX 控制序列**不得含阿拉伯数字**（分位数后缀写 `PFifty`、`PNinetyFive`），否则 TeX 在数字处截断命令名。
- 图表和 LaTeX 数字由 `egoanchor.eval` 自动生成，主稿不手抄结果；正式产物不存在时不得写占位数字或占用图表版面。正式数字必须由当前五本 Stage 1 XLSX 计算，不读历史 GPT 结果包。
- 主稿图片统一用 `2026-EgoAnchor/figures/`（组合图在 `figures/panels/`，表格在 `tables/`），不恢复 `2026-EgoAnchor/figs/`；面板 PDF 不写构建时间元数据以保证字节稳定。
- 正式实现位于 `egoanchor.eval.experiments`：`experiment_1_2` 与 `experiment_3` 同级，各含 `data.py`/`settings.py`/`workflow.py`/`pipeline.py` 四层，专属 reader、指标、计分、模型与绘图在各自 `analysis/` 子包；跨实验编排在 `experiments/workspace.py`，构建清单与事务性复制在 `experiments/common`。旧 Stage 2/3、v2 replay、`eval.workflows`、`eval.paper_analysis` 与历史 schema 测试已删除。
- 旧命名扫描按语义判定：runtime、writer、namespace 和 CLI 不得依赖或输出旧 RQ/schema 名称；`schema_v2/readers.py`、`schema_v2/qc.py` 及其测试保留旧字段名**仅用于显式拒绝旧输入**，不得当作兼容层删除。
- 没有独立 `experiment3.toml`：共享路径与资源目标分层存于 `batch.toml`，统计参数分层存于 `paper.toml`（唯一论文参数入口，正式 CLI 不提供覆盖，provenance 必须记录其 SHA-256，每个参数同行保留中文注释）。
- 完整命令、批次归档、退出码与故障排查见 `EgoAnchor_Python/docs/analysis_pipeline.md`、目录规则见 `docs/data_layout.md`、中文采集手册为 `2026-EgoAnchor/experiment_1_2_collection_manual_zh.md`（Pilot 不启动 `EvalSession`、不进正式 raw、不用于论文回填）。
- Mutagen `logs-5090` 启用期间不得移动或重命名 `data/eval` 原始目录，也不得修改内部固定文件名和 manifest `session_id`。

### Schema-v2 与 QC

Run 1 原始日志固定为 `manifest.json`、`python_candidates.jsonl`、`python_events.jsonl`、`unity_reference.jsonl`、`unity_admission.jsonl`、`unity_render.jsonl`、`unity_events.jsonl` 与合并后的 `events.jsonl`。旧共享事件文件格式不兼容。`audit_samples/` 是可选目录：**没有真实审计文件时不得为每个 session 预创建**，Stage 1 暂存会跳过遗留的空目录，但一旦存在真实文件则必须完整复制并纳入来源摘要。

- 事件物化只在 `python_stopped`、两个分片 schema 合法、行数匹配 writer 统计且无丢行/写入失败时，以冻结全序原子发布 `events.jsonl`；已有总表只逐字节验证、不覆盖。半同步、pending 或非法 fragment 不得留下部分派生文件。**两端不再通过跨机器 `.lock` 共同追加同名文件**。
- Python writer 统计在 Unity 停止时标为 pending，必须在同步 `python_session.json` 后合并，**禁止把 pending 当作 0**。
- QC 按 `variant_matrix_id=exp12_9_smoothed_hermite_v4` 固定要求 9 个唯一 runtime（实验一四配置 + 实验二三消融 + 两路时序策略，完整 EgoAnchor 只一个共享 runtime）。Smoothed KF 的 render 行单独记录 `prediction_horizon_ms`、位置/旋转校正残差与 session 内单调不减的 `continuity_reset_count`，其他策略前三项必须为 null、计数为 0。缺矩阵标识、配置指纹、任意 variant 或名称/方法错配均硬失败。
- 每个 variant 必须写出非空 `configuration_fingerprint`（覆盖坐标补偿、运动模型、输出策略、接纳/生命周期/重获取及 StaticLock 全部生效数值），`config_hash` 绑定该指纹，QC 核对模型、策略、门控、开关与 FNV-1a 哈希。`frozen_parameter_set_id` 复用整体 `config_hash`，`operator_id` 固定匿名单操作员。
- candidate ID 为 `session_id:frame_id:frame_local_seq`，同一 `PoseResult` 的多 runtime 回调共用标识。Unity admission 指向未知 Python candidate 是硬错误；latest-only 未消费 candidate 只警告。
- Formal QC 按 `trial_started -> trial_ended` 的 Unity 单调时间核对每个完成 trial（事件唯一且顺序合法）；实际时长只作描述性审计，不设上下界、不决定成败。
- 人工事件角色写入 `events.payload.event_role`。五个正式任务的完成 trial 都必须至少含一个 marker；起停 6DoF 必须 `transition_started` 与 `transition_stopped` 严格交替闭合，遮挡恢复必须 `occlusion_started` 与 `target_visible` 严格交替闭合。**指标按角色切窗，不得根据场景名猜测事件含义**；任一消融缺其冻结关键指标时禁止发布正式产物。
- 基础 QC 检查全部原始行；正式指标与 VCD risk-coverage 只投影**已有 `trial_ended` 且无后续 `trial_rejected`** 的 trial。被作废与未完成的尝试保留审计记录但不进论文。
- `source_frame_id` 必须来自最近被 policy 接受并实际显示的 frame；被拒候选只更新诊断用 latest aligned frame，不得覆盖 hold-last 或当前输出来源。
- 分析 reader 对启动阶段只保留「render 内嵌参考有效 + `source_capture_mono_ms` 早于首条 `unity_reference` + `source_frame_id` 在首帧之前」的 warmup 行，其余未知 frame-id 硬失败；指标层排除无右表参考基线的 warmup candidate。
- 单 session QC 只检查实际完成任务的 reference coverage 与 tick×variant 完整性；批次 QC 按已完成 trial 的场景并集要求任务 1--5 全覆盖。失败时只写 QC 审计表并停止。
- 实验二复用实验一同一批 session，只在组件对应场景内按 `session_id × scenario_id × trial_id × event_id` 配对完整系统与消融；采集时刻对齐与 StaticLock 用静止头动任务，VCD 用遮挡恢复任务，时序策略用起停/持续运动/遮挡任务。完整系统三个归因组件必须全开，每个消融只关闭对应组件。消融与时序策略不得混入实验一的 VCD、时延、图表或 LaTeX 数字。
- 正式参数随实现固定，所有记录的 session 均为 formal，采集后不得调参。

### 定性回放（qualitative replay）

独立 `egoanchor.qualitative_replay` 包与 `pixi run replay` 入口，只读 `data/replay_capture/` 下的 v1 capture，不得读写正式 `data/eval/`、工作簿与 schema-v2 产物。采集方式固定为 Quest Link 下的 Unity Editor Play Mode，完整说明在 `EgoAnchor_Python/docs/qualitative_replay.md`，出图参数统一由 `egoanchor/qualitative_replay/config/qualitative_replay.toml` 管理。

- **四种方法来自同一候选流、同一物理采集**；列必须按连续已保存样本的**固定间隔**选择（显式 sample ID 也须按 capture 顺序严格递增且等距），**不按误差或各方法极值挑帧**。每列显示行共用同一真实左目背景、相机、时间点与裁剪框。
- 窗口必须体现持续差异，不能依赖单列峰值；启动阶段或重获取期间四方法共同错位的区段必须排除，不能解释为某个基线的抖动。窗口筛选可用平台参考作同时间线内诊断，但不得称外部真值。
- 论文图必须保留物体局部 XYZ 轴、顶部时间轴与纵向方法轴。离线投影必须从 runtime 配置指纹恢复 OpenCV GLB 到 Unity renderer 的对象局部基，不能把已含 anchor-local 补偿的显示根节点 pose 直接作用到原始 GLB；轮廓与 XYZ 轴必须共用 `K * P * C` 投影链。轮廓按三角面并集生成，不能交给 OpenCV 奇偶填充。首次使用某对象模型必须先用 `replay frame` 做像素贴合检查。
- sidecar 必须保留默认与自定义 TOML、实际 mesh、严格校验模式、最终生效配置及其 SHA-256，以及最终行列、字体、`delta-t`、坐标轴、纹理后端与裁剪配置。
- **该图只是二维定性示意**，必须显式标注，不得把像素偏移写成正式配对指标或替代 schema-v2 定量证据。
- 论文当前用图：6 列，源 `replay_capture/20260722_203752_143_controller_right`（**独立的定性回放采集**，`editor_link`、`delayed_image_time_proxy` 图像时刻、平台参考含 683 个 held 样本，与实验一/二的正式批次**不同源**），目标 `2026-EgoAnchor/figures/replay_grid.{png,pdf}`。
- **配色（全文共享，唯一定义在 `egoanchor/visuals/__init__.py`，`qualitative_replay.toml` 的 `method_colors_hex` 必须逐项一致）**：Arrival `#4C78A8`、Capture `#F28E2B`、One-Euro `#59A14F`、EgoAnchor `#E15759`。**已知可访问性缺陷**：该绿/红对在绿色盲（deutan）模拟下几乎无法区分；实验三图中两方法依靠固定位置、点形、箱体边框和图例区分而非仅靠色相。若要修正必须**全文一次性**换成同一套色盲安全配色（Okabe-Ito：One-Euro `#0072B2`、EgoAnchor `#E69F00`、Arrival `#009E73`、Capture `#CC79A7`）并同步重跑实验一/二论文图与定性 grid，**不得只改实验三**而让同一方法在不同图里换色。

### 实验三（冻结设计，改前必读权威文件）

**唯一权威文件是 `2026-EgoAnchor/experiment_3_questionnaire_design_zh.md`**（v5 完整计划：结构+测量+分析+汇报）。其「版本沿革与决策记录」节列出被推翻的旧决定，**不得改回**；原 `experiment_3_design_zh.md` 已并入并删除，不得再引用。下列为最易写错、且会直接导致论文表述错误的边界：

- **纯主观评价，不采集任何客观任务数据**（无任务时间、无成功率、无行为探针）。条件只有 *One-Euro Anchor* 与完整 *EgoAnchor*，*Arrival-Hold* 只作训练演示、不进推断统计。核心物体 `blue_mouse` / `stapler` / `gamepad`，`earphone` 作困难样例与训练物体。
- **区块结构是物体最外层、两方法嵌套在同一物体内**（`--object` 只在服务启动时读取，协议无运行时切换；同物体相邻 A/B 给出最紧配对）。三项任务为静止观察、拿起放下、遮挡恢复，**固定顺序**、合计 45--60~s 后统一评分，**不在每项任务后中断**。方法级问卷必须在**全部六个区块完成后**施测，不得插入第 5/6 区块之间。
- **遮挡时长必须使锚点停留在 `FrozenUncertain` 而不进入 `Lost`（0.6--0.9~s）**：`AnchorStateMachine.cs:105-115` 的实际分支是 ≤0.45~s 滑行、0.45--1.0~s 冻结、≥1.0~s 丢失，故 0.6--0.9~s 落在**冻结**区间。更长的遮挡会使两方法都进 `Lost` 并等同一次服务器 REGISTER（中位数 750.26~ms），使恢复条目主要反映感知后端而非运行时。运行时参数不得为实验三修改。
- 题序固定 `Q1--Q7 → AQ_EQ1--3 → AQ_IQ1--3`（Q1 静止稳定、Q2 运动附着、Q3 姿态一致、Q4 恢复一致、Q5 位置正确、Q6 依赖意愿、Q7 稳定--响应平衡；Q10 已删除）。区块级 13 项统一七点同意度，每人 `2×3×13 = 78` 个区块评分。
- **顺序平衡为 24 平衡单元**（3 物体全排列 × 互补方法序列 S1/S2 × A/B 标签到方法的映射），N=24 时每单元 1 人、先行方法 12/12；匿名标签在参与者内全程稳定绑定同一方法，否则最终强制选择无从解释。
- **统计固定为参与者内 Wilcoxon + 分层 Holm**：七个自制条目逐项分析、**不合并总分、不报 Cronbach's α**（信度只对已发表量表报告）。AQ-EQ/AQ-IQ 先算区块内子量表均值再在三物体取均值；TiA 反向项按 6−raw 换向后分别算 TiA-R/C 与 TiA-U/P；S-TIAS 取三项均值。主证实家族含 Q1--Q7，已发表量表家族含 AQ-EQ/AQ-IQ/TiA-R/C/TiA-U/P/S-TIAS；选择、偏好强度、区分信心与开放题只作描述。Wilcoxon 为含并列中秩的双侧条件精确符号置换（配对差四舍五入至 12 位小数以恢复理论并列、删零差、穷举符号分配），**不得改回正态近似**，也不得写成无假设检验（仍需符号可交换假设）。**自定义 CLMM 已删除**（逆 Hessian 不能作协方差、Wald 推断无效），不保留配置、代码、结果页或论文叙述。逐物体结果只作 7×3 配对描述，不算 p 值或星号。
- **署名边界**：AQ / TiA / S-TIAS 一律以 **adapted / 对象化改编**署名，信度只表述为当前样本信度，统计家族名为「已发表量表家族」（不称「已验证工具家族」）。TiA 为 Körber 2019 的 R/C 6 项 + U/P 4 项、反向项 RC3/RC5/UP2/UP4、五点；**英文版验证证据有限，不得写「已验证英文/中文量表」**。S-TIAS 为 McGrath, Lack, Tisch & Duenser 2025（bib 键 `mcgrath2025stias`；语料曾误标作者为 Karpus）。**任何场合不得以 CRIQ 之名署名条目**（已核查无法确证存在该量表）。
- **联网核查结论：不存在测量「虚拟内容在真实物体上的配准质量」的已验证量表**，该结论写入论文测量说明。信任动机文献为 Gottsacker et al. 2024（AR 跟踪偏移/抖动在测试的 0/1/2 度水平内每升高一级伴随信任下降），**不得表述为任意每度线性下降的连续定律**。
- 禁止引入 SUS、完整 NASA-TLX、IPQ/临场感量表、具身量表、UEQ/AttrakDiff（构念在两方法间按设计恒定）。
- **版本边界**：`material/EgoAnchor_Experiment3_RawData.xlsx` 是已完成 24 人的 **v5.2** 正式数据；后续采集用 `EgoAnchor_Experiment3_RawData_Template_v5_3.xlsx` 与 v5.3 问卷包，**两版不得合并分析**。v5.3 才启用 AQ-EQ2、TiA-RC1/RC4/UP1 的情境化措辞与互斥 B5 累计次数选项，四处改写须先经认知访谈确认。v5.3 问卷包以 `material/EgoAnchor_Experiment3_Complete_Questionnaire_v5_3_Bilingual.md` 为唯一事实源，同名 docx 由 `material/build_exp3_questionnaire_docx.py` 从 md 确定性生成（先改 md 再重跑脚本，不得手改 docx）。不要依赖本机 Excel COM 重算：仓库在网络盘 `P:\`，受保护视图可能拒绝 COM 并残留锁文件。
- **分析参数契约 v5、图产物契约 v7**：只生成 `figure4_exp3_subjective_outcomes.{png,pdf}` 与 `tables/exp3_subjective.tex`。复合图上排七个等宽槽依次 Stability / Attachment / Orientation / Recovery / Position / Reliance / Balance（内部键 Q1--Q7，纵轴 1--7 原始分，不显示问卷编号）；下排五项已发表量表整体居中，AQ-EQ、AQ-IQ、S-TIAS 共用 1--7 左轴，TiA R/C 与 U/P 共用 1--5 右轴，两分区留窄缝、不归一化。显著性括号仅编码所属冻结家族内 Holm 校正后的 p，绘图入口从参与者配对分重算精确 Wilcoxon 与分家族 Holm，拒绝与结果表不一致的显著性数据。旧对象展开图、独立 Figure 5、森林图、Figure S1 已退役。
- 结果工作簿固定为 6 张中文页：`说明`、`样本与质控`、`主结果`、`分物体描述`、`量表信度`、`选择结果`。`分物体描述` 不写 p、Holm、显著性或 `r_rb`。开放题编码必须放在独立、持久、不会被自动重建覆盖的文件。`r_rb_CI_Status=degenerate_at_bound` 时只能写「方向完全一致」，不得把 `[1.00, 1.00]` 当置信区间。`Measurement_Unit=block_mean` 的 AQ 信度与 `method_single` 的 TiA/S-TIAS 信度不可互比，也不可与原量表发表 α 直接对标。
- Exp3 使用独立的 2 runtime `variant_matrix_id`、独立启动门禁和与 schema-v2 隔离的日志与分析模块，不复用九路矩阵。`analyze exp3` 先在 staging 生成并验证全部产物再整目录切换发布，失败时保留上一轮活动结果；`validate exp3` 是可选诊断，不是前置门禁。

## Python 关键约束

入口 `EgoAnchor_Python/src/run_server.py` -> `egoanchor.app.tracking_server`；配置在 `src/egoanchor/config/defaults.toml` 与 `objects.toml`。

- 默认分割器 `yoloe26`；SAM3 只能显式启用。
- 评估模式写 `data/eval/<session_id>/` 并通过 header 与 Unity 配对；普通模式写 `data/runtime_logs/`。
- VCD 目标公式 `R = V * G_CD`，其中 `V = |M_obs ∩ M_rnd| / |M_rnd|`；旧面积比实现不得进入正式结果。`color_reprojection < 0` 表示颜色信号不可用，应从几何核排除，**不是坏 pose**。深度评分保留绝对与结构分量 `D = (1-alpha) D_abs + alpha D_struct`，日志必须暴露消融所需分量。
- `RuntimeLogWriter` 把候选行映射为严格 `PythonCandidateRow`（颜色不可用写 `null` 并保留解释 flag），runtime 事件与候选行分写固定 schema-v2 文件；关闭时把真实 `rows_written`、`dropped_rows`、`log_write_failures` 写回 `python_session.json`，**Unity 不得伪造 Python 丢行统计**。
- `egoanchor.eval` 包级入口只导出 schema-v2、QC 与 Stage 1 基础设施；论文分析必须从 `experiments.experiment_1_2` / `experiments.experiment_3` 包级入口或离线 CLI 进入，运行时服务不得因绘图依赖加载失败。
- `CutieMaskTracker` 不直接导入 `torchvision.transforms.functional.to_tensor`（避免 Windows 图像 DLL 冲突）。
- FFS 必须在 server 启动阶段按固定 `pipeline.calibration.process_width/process_height` 完成一次中性立体图完整预热（TRT 尺寸匹配、CUDA 上下文与首次前向不得推迟到 Unity 首帧），预热结果不得进入跟踪状态或日志候选。
- OpenCV debug 窗口按 `S` 从当前诊断数据重新生成并无损保存 pose 与 VCD 两张 PNG（`2560x1280` 与 `1920x1240`，默认写 `data/debug/snapshots/`），保存分辨率独立于实时窗口；VCD 的 render RGB 与 projected depth 只在渲染 mask 内显示数据。
- 生成代码、`*_pb2.py` 与协议副本不手改。
- 关键 ownership：`config/` 不导入模型/网络；`transport/` 只管传输；`routing/handlers` 不碰 GPU；`runtime/tracking_runtime.py` 是 pipeline owner；`perception/quest_pose_pipeline.py` 组合视觉模块；`reliability/` 计算 VCD；`eval/` 只处理 schema-v2、QC、三个实验与论文产物。

## Unity 关键约束

- `MeasurementTimeSeconds` 属采集时间轴，用于运动估计与静止锚定；生命周期 freshness 使用到达/生命周期时间轴。**不得用 capture time 刷新 stale/lost**。
- `has_output_pose` 表示 runtime 是否有输出，`has_display_pose` 表示用户实际看到的 Transform（含 hold-last）。hold-last 显示行从 `DynamicObjectAnchor.LastAppliedFrameId` 保留实际来源帧；只有从未应用或已隐藏的显示才允许 `source_frame_id=-1`。
- 平台控制器参考 pose 只从 `EvalRecorder.groundTruth` 绑定的 Transform 读取；`controller_right` 必须绑定 `OVRCameraRig/OVRInteractionComprehensive/OVRControllerVisualRight/OVRControllerPrefab`（对应 `m_controller=RTouch`、`gtController=RTouch`），**不得绑定名称相似但不会更新的静态节点**。失活或隐藏时无限期保持最后一次激活 pose，激活状态只写入 `reference_pose_fresh/reference_pose_keep_alive`，不得当作另一套 pose 来源。正式 session 启动前必须观察到参考对象至少 1~cm 平移或 5 度旋转，未通过时禁止启动。
- StaticLock tether 计算 `obsConsensus -> anchorOrigin`，**不得改成单帧观测或 `lockedPose`**。头动期间不冻结真实运动证据，`headSettleSeconds` 只覆盖头停后的沉降窗口。距离自适应只放大位置通道，旋转 tether 必须高于旋转噪声地板。
- `EvalLog` 使用有界后台队列；正式 session 所有日志 `dropped_rows` 必须为 0。Unity 独占写 `manifest.json`、`unity_reference.jsonl`、`unity_admission.jsonl`、`unity_render.jsonl`、`unity_events.jsonl`（render 为 tick×variant 长表，admission 由每个 runtime 的实际处理结果产生）；Python 远端独占写 `python_events.jsonl`。
- manifest 的 `run_kind` 固定 `formal`，不暴露运行类型选择；Formal 启动不要求现场填元数据，但严格要求 Python session 配对与非空变体配置哈希。`completed_tasks` 按任务编号记录最终未作废的 trial，QC 必须与 lifecycle events 重新推导的完成集合核对。
- 正式场景 `EgoAnchor-Experiment12.unity` 使用 **9 个唯一 runtime**，完整 EgoAnchor 只保留一个共享 runtime；`variant_matrix_id=exp12_9_smoothed_hermite_v4`。启动正式 session 前由 `EvalRecorder.TryValidateFormalVariantMatrix` 硬校验数量、顺序、模型、输出策略、门控、对齐、六个能力开关、runtime 唯一性、显示绑定与唯一主变体，**校验失败不得开始录制**。场景契约测试冻结组件矩阵与层级。`EgoAnchor-Develop.unity` 只用于工程调试，不承担正式采集契约。
- 五项共享物理任务可任意选择；每项同时记录实验一四配置、实验二三消融与两路时序策略，不重复采集任务 6--9。运行中禁止切场；任务与 session 均无时长门禁，实际 trial 时长只记录不判定成败。已完成任务可重录（旧 trial 先写 `trial_rejected`）。完整按键映射与状态板契约见中文采集手册；`ExperimentInputHandler` 直接在 Inspector 序列化内联 `InputAction`，不使用 binding 字符串、`InputActionAsset` 或 `InputActionReference`，数字行路径写 `<Keyboard>/1`--`5`、小键盘写 `<Keyboard>/numpad1`--`numpad5`（**不得使用无法解析的 `<Keyboard>/digitN`**），B 键结束绑定固定 `Tap(duration=0.5)`、停止绑定固定 `Hold(duration=1.5)`。
- **头显状态板运行时文本统一英文 ASCII**（当前 TextMesh Pro 字体资产不保证 CJK 字形）；中文只用于代码注释、Tooltip、控制台日志与采集手册，不得把中文动态状态字符串传给 `ExperimentStatusUI`。状态板不暴露分析内部的 phase/event role；marker 反馈只属 UI，不得额外写成实验事件。
- 实时诊断板 `EvalLiveStats` 以 10~Hz 显示系统信号：一般信号读唯一主变体 `EgoAnchor`，外推诊断按稳定标签读 `Smoothed KF Extrapolation`（**不得误读主变体的 Linear/SLERP 诊断**），已废弃的通用 `latest_residual_*` 字段不得恢复。**平台参考差异不是外部真值，实时板不得用于挑选低误差起始时刻**。
- `QuestStreamPublisher` 订阅 Meta VR focus：focus 丢失时暂停双目 GPU 读回与 JPEG 编码，恢复后自动继续；出现 `HMDUnmounted`、`VrFocusLost` 或 `InputFocusLost` 的活动 trial 应作废重采。
- `EgoAnchor-ReplayCapture.unity` 是 Quest Link 定性图专用场景，只保留实验一四个 runtime 与 `ReplayCaptureRecorder`，**不得挂载 `EvalSession`/`EvalRecorder` 或实验二 runtime**。采集器复用 `QuestStreamPublisher` 已编码的只读左目 JPEG，不增加 GPU 读回与编码；右手柄参考固定读取 `OVRControllerPrefab` 的 Transform，静止失活时无限期保持最近一次有效 pose，**不得写成 null 或切换另一套来源**。后台队列不得阻塞追踪，必须记录真实丢帧、缺 pose、缺标定、参考 fresh/held 与写入失败统计。
- Inspector 参数、坐标语义与时间语义写 XML summary 或 `[Tooltip]`，不隐藏生效参数。生成协议代码与 `SubjectNames.cs` 不手改。

## 协议与生成输出

唯一协议源：`EgoAnchor_Protocol/subjects.v1.json`、`EgoAnchor_Protocol/proto/protocol/v1/{common,quest,anchor}.proto`。

生成输出：Python `EgoAnchor_Python/src/egoanchor/protocol/v1/*_pb2.py`；Unity `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/Generated/*.cs` 与 `SubjectNames.cs`。

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

论文（`2026-EgoAnchor`，审阅已复制的组合图与表格后；`-g` 强制标志是必需的）：

```text
latexmk -g -xelatex -synctex=1 -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_final_v1.tex
```

## 环境与远端关键坑

- `pixi run build` 会构建 nvdiffrast、FoundationPose 扩展与 FFS artifacts，不作为轻量验证。
- FFS 覆盖导出前必须删除旧 `.onnx` 与 `.onnx.data` sidecar，避免 Windows `PermissionError`。
- nvdiffrast 不放 `[pypi-dependencies]`，使用 `_build-nvdiffrast`；Windows 构建任务内部清理并重建 MSVC/CUDA 环境，`CL/INCLUDE/PATH` 不放 Pixi activation；CUDA 13 同时加入 `targets/x64` 与 `cccl` include。
- Windows 数值栈保持 OpenBLAS；SciPy/scikit-learn 用 PyPI wheel；OpenCV 只保留 `opencv-python`（避免 DLL/OpenMP 冲突）。完整说明见 `EgoAnchor_Python/docs/windows-prerequisites.md`。
- `EgoAnchor_Python/mutagen.yml` 以本机为唯一源码源，source 用 `one-way-replica`、日志回传用 `one-way-safe`；远端 `data/eval/` 与 `data/runtime_logs/` 必须先存在。
- Windows 远端 Mutagen 要求 OpenSSH `DefaultShell=cmd.exe` 且系统代码页为 UTF-8；PowerShell DefaultShell 会使相对 agent 命令失败。
- 论文渲染截图、样式预览与一次性几何检查统一放根目录 `tmp/` 或 `2026-EgoAnchor/tmp/`，临时 XeLaTeX 包装文件用 `2026-EgoAnchor/pdftest/`；这些路径均被 `.gitignore` 排除，不得作为论文资源提交。图表参考资料只保留 `2026-EgoAnchor/gpt-web/`，早期输出包不能作为主稿或分析产物来源。

## 项目级实现要求

- 日志统一走门面：Python 用 `egoanchor.utils`，Unity 用 `EgoAnchorLog`。
- 新行为先补测试或工程自检；最终提供可复现验证命令。
- **AI 或自动化工具修改 Unity 文件、保存场景、刷新 AssetDatabase 或触发编译前，必须先确认 Editor 不在 Play Mode**；正式采集从进入到退出 Play Mode 期间禁止任何代码写入和 Unity MCP 状态变更。
- 不恢复旧端口、旧 MessagePack/JSON pose、旧 NATS 图像流、旧 Python/Unity 入口或旧 eval schema；不添加 `FormerlySerializedAs`、旧字段、旧路径、旧标签或旧 CLI 兼容层。
- 改 schema 时同步 writer、reader、分析、论文接口和本文件。

## AGENTS.md 维护规则

- 不修改顶部 `USER-MAINTAINED-REQUIREMENTS` 区块（内容、位置、分隔符均不动）。
- 只写当前事实、长期约束、已冻结路线和会直接导致失败的历史坑。**不写逐轮评审日志**：不记录 session 数字、迁移 hash、调参过程、旧图窗、一次性排障过程，也不为每轮改稿新增一节。
- 事实变化时直接改原条目，不追加相互矛盾的新说明，也不保留划除线的旧文本。
- **「冻结」不是硬约束**：新证据推翻理由后可以改，但改前必须先读懂原理由，并在本文件写清推翻它的证据。不得以「冻结」为由拒绝修正事实错误，也不得不留记录地悄悄推翻。
- 本文件已于 2026-08-05 按用户要求整体重构：删除历次 GPT 复审的逐条采纳/否决日志（约 240 行），其中仍然生效的裁定已按主题合并进「论文硬约束」「论文所依赖的代码事实」两节。**不要按旧格式重新添加按轮次组织的变更记录。**
