# 引用插入计划

这份计划对应 `egoanchor_cn_ready_v2.tex` 在 2026-08-16 的内容快照。行号会随并行改稿变化，实施时以表中的检索锚点和小节为准。本计划不修改手稿；`egoanchor_cn_refs_verified.bib` 是独立的已核验文献库，实际替换时再将主稿的 `\bibliography{egoanchor_cn_refs}` 改为 `\bibliography{egoanchor_cn_refs_verified}`，或人工合并经选定的条目。

## 核验与格式

- IEEE VR 2027 的论文页为正文、图表 4--9 页，参考文献最多 2 页。来源：<https://ieeevr.org/2027/contribute/papers/>。
- 本地 VGTC 模板要求期刊条目包含作者、题名、期刊、年份、卷期和页码；会议条目包含作者、题名、`Proc.` 形式的会议名、年份、出版社、地点和完整页码。DOI 使用 `doi` 字段，现有手稿采用 `abbrv-doi-hyperref-narrow`。
- 新 Bib 共 66 条，均为正式发表的期刊、会议或会议论文集章节。每一条都有 DOI、年份与页码；`stias2025` 和 `trustar2024` 使用出版社给出的文章号 `1582880`、`104035`，不是缺失页码。
- 代码门禁在 2026-08-16 完成：66/66 条 DOI 在 Crossref 精确记录中均有作者、题名、出版日期以及页码或文章号；66/66 的 `https://doi.org/<DOI>` 初始响应为 301/302/307/308。静态检查结果为 66 条目、66 DOI、66 年份、66 页码字段、0 个重复 DOI、0 个 `arXiv` 文本和 0 个 `@misc`。以本地 `abbrv-doi-hyperref-narrow.bst` 运行 BibTeX 后，66 条全部生成，warning 为 0。

该库的分类如下。这里的条目是经过筛选的候选库，不是要求把所有键都塞进当前论文。

| 类别 | 数量 | 键 |
| --- | ---: | --- |
| PMR、配准与时间语义 | 18 | `apriltag2011`, `aruco2014`, `azuma1994improving`, `casiez2012oneeuro`, `coopimageorientation2024`, `diluca2010latency`, `gradualreality2024`, `harmonize2021`, `jacobs1997latency`, `kalman1960new`, `laviola2003double`, `mrloop2022`, `pvt2023`, `realitycheck2019`, `realitylens2022`, `selfavatar2023`, `selfblending2026`, `vrception2022` |
| 6DoF 位姿与追踪 | 17 | `bundlesdf2023`, `bundletrack2021`, `cosypose2020`, `deepim2018`, `densefusion2019`, `epos2020`, `ffb6d2021`, `foundationpose2024`, `gdrnet2021`, `gen6d2022`, `gigapose2024`, `latentfusion2020`, `onepose2022`, `poserbpf2021`, `pvn3d2020`, `self6d2020`, `zebrapose2022` |
| 开放词表检测与视频对象分割 | 14 | `cutie2024`, `detic2022`, `egmn2020`, `glip2022`, `groundingdino2025`, `mdetr2021`, `owlvit2022`, `regionclip2022`, `stm2019`, `transductivevos2020`, `videoknet2022`, `xmem2022`, `yoloe2025`, `yoloworld2024` |
| 立体、渲染与评分评价 | 13 | `aanet2020`, `crestereo2022`, `dynamicstereo2023`, `focalpose2022`, `foundationstereo2025`, `ganet2019`, `hitnet2021`, `igevstereo2023`, `nvdiffrast2020`, `raftstereo2021`, `stereoanywhere2025`, `riskcontrolled2020`, `ding2020uncertainty` |
| 用户评价量表 | 4 | `aq2026`, `stias2025`, `tia2019`, `trustar2024` |

本地 VGTC 模板的实测结果是：66 条完整引用占 3 个双栏参考文献页，超过两页上限；“主稿优先”列去重后的 34 个键占 2 个双栏参考文献页。建议当前 9 页稿只启用“主稿优先”列中的键，并在扩写相关工作后再从“可选补强”列选取。这里不建议为了达到数字目标而把备选文献全部引用。

## 当前稿的插入点

| 位置与检索锚点 | 处理 | 主稿优先 | 可选补强与边界 |
| --- | --- | --- | --- |
| §1，`PMR正在将虚拟内容附着`（约 L59） | 在应用动机段末加入 2--3 篇 PMR 物理物体交互文献。 | `selfblending2026, gradualreality2024, realitylens2022` | `vrception2022, realitycheck2019` 仅在段落保留跨现实原型或虚实混合的表述时加入。它们只支撑应用动机，不支撑 EgoAnchor 的运行时贡献。 |
| §1，`平台原生对象追踪通常`（约 L62） | 删除平台网页的 `\cite{...}` 组，分别用官方脚注支撑能力范围、模型准备与平台限制。视觉方法句改用正式论文。 | `foundationpose2024, gigapose2024` | 对“开放词表检测与分割、立体匹配”这一概括，若需加证据，采用 `groundingdino2025, cutie2024, foundationstereo2025`。不要把 `foundationstereo2025` 说成当前 Fast-FoundationStereo 的正式论文。 |
| §2.1，`通过AprilTag、ArUco`（约 L85） | 用两个带 DOI 的标记系统替换原有包含无 DOI 条目的三键集合。 | `apriltag2011, aruco2014` | 删除 `kato1999artoolkit`，不以无完整页码的历史条目占用参考文献。 |
| §2.1，`HoloLens 2的Azure Object Anchors`（约 L87） | 该段所有平台能力都改官方脚注，不进入 Bib。平台名称不应用同行评审文献替代。 | 见“脚注” | 若保留 `HTC Tracker` 示例，也只加其官方产品页脚注。 |
| §2.2，`大量深度学习方法针对特定物体`（约 L93） | 将“实例训练”“新物体/模型驱动”“渲染匹配”“检测/分割/立体”拆成四个紧凑引用组。原句中的 `megapose2022` 不保留。 | 实例级：`densefusion2019, gdrnet2021`；新物体与模型驱动：`gen6d2022, gigapose2024, foundationpose2024`；渲染匹配：`deepim2018, cosypose2020, latentfusion2020`；基础模块：`groundingdino2025, cutie2024, foundationstereo2025` | 位姿历史可选 `pvn3d2020, ffb6d2021, epos2020, self6d2020, zebrapose2022, onepose2022`；检测可选 `yoloworld2024, yoloe2025, glip2022, detic2022, owlvit2022, regionclip2022, mdetr2021`；分割可选 `xmem2022, stm2019, egmn2020, transductivevos2020, videoknet2022`；立体可选 `raftstereo2021, igevstereo2023, crestereo2022, stereoanywhere2025`。不要把 CosyPose 写成未知物体零样本方法，也不要用这些论文暗示已解决对象锚定。 |
| §2.3，`预测式追踪` 与 `历史状态查询`（约 L99） | 保留预测和历史查询的对比结构。预测式追踪句增加近年的延迟感知视觉追踪；历史状态段添加时间戳/缓冲/动态对象取值的已发表先例。OpenXR 保持脚注。 | 预测：`azuma1994improving, laviola2003double, pvt2023`；历史查询：`jacobs1997latency, harmonize2021, selfavatar2023, coopimageorientation2024` | `mrloop2022` 可在需要工业仿真延迟补偿的跨领域比较时引用。不要在本节加入 `casiez2012oneeuro`、ATW 或 EgoAnchor；这与现有章节边界不符。 |
| §3.2.1，`开放词表检测器`（约 L136） | 直接引用已正式发表的实际初始化器。 | `yoloe2025` | `yoloworld2024` 仅作相关工作，不替代 YOLOE 的实现出处。 |
| §3.2.1，`视频对象分割器`（约 L143） | 保留一个实现出处即可。 | `cutie2024` | `xmem2022, stm2019` 只在 §2.2 的方法脉络中使用，不堆到实现段。 |
| §3.2.1，`Fast-FoundationStereo`（约 L150） | 这是实际依赖，但尚无可核验的正式 DOI/页码。这里加官方项目页脚注；不将它写入新 Bib。 | 见“脚注” | `foundationstereo2025` 可在 §2.2 作为前代零样本立体工作，不是 Fast-FoundationStereo 的替身。 |
| §3.2.1，`模型驱动位姿估计器`（约 L157） | 替换旧 arXiv 键。 | `foundationpose2024` | 无需同时堆叠多篇位姿论文；这里是实现出处。 |
| §3.2.2，`VCD沿用渲染匹配范式`（约 L170） | 以渲染--观测比较的正式工作支撑范式，不声称前人没有候选评分。 | `deepim2018, cosypose2020, latentfusion2020, focalpose2022` | 该组只支持 render-and-compare。VCD 的新意仍应写为最终候选的显式可靠性、轨迹准入、失效判定与重新获取依据。 |
| §3.3.1，`常速度卡尔曼滤波`（约 L232） | 为标准滤波器实现补一个经典出处即可。 | `kalman1960new` | 不新增额外预测论文；相关工作已经给出时间语义脉络。 |
| §4，`YOLOE-26用于`（约 L322） | 对已发表组件引用正式论文；Fast-FoundationStereo 用脚注。 | `yoloe2025, cutie2024, foundationpose2024, nvdiffrast2020` | `foundationstereo2025` 仅在“前代/背景”句中出现。不要用 `nvdiffrast2020` 证明 VCD 的方法论，它只对应渲染实现。 |
| §5.2，`风险--覆盖率曲线下面积`（约 L371） | 首次定义 AURC 时加两篇方法学引用，结果段不重复。 | `riskcontrolled2020, ding2020uncertainty` | 前者对应连续误差的选择性预测，后者讨论不确定性评分的风险--覆盖率评估。它们不意味着 VCD 是回归分类器，也不授权将 AURC 与全覆盖风险直接作优劣比较。 |
| §5.1，`One-Euro作为主要运行时平滑基线`（约 L334） | 现有引用保留并换用新 Bib 中的同键。 | `casiez2012oneeuro` | 不移动到 §2.3。 |
| §5.3，`配准误差与用户信任`、`AQ`、`TiA`、`S-TIAS`（约 L389、L414、L417） | 逐个替换为完整正式记录。 | `trustar2024`; `aq2026`; `tia2019, stias2025` | 不在结果和讨论段重复同一组量表出处。 |

## 脚注而非参考文献

以下对象是平台接口、规范或尚未具有正式出版元数据的项目页。它们应写成紧邻能力主张的脚注，包含 URL 与访问日期；下表链接统一按 `accessed 2026-08-16` 标注，不进入 `egoanchor_cn_refs_verified.bib`。

| 使用处 | 建议脚注来源 |
| --- | --- |
| Apple `ObjectAnchor` 与对象追踪能力 | <https://developer.apple.com/documentation/arkit/objectanchor>；若保留运动/手持物体的更新，另加 <https://developer.apple.com/videos/play/wwdc2026/283/> |
| Azure Object Anchors | <https://learn.microsoft.com/en-us/azure/object-anchors/overview> |
| Vuforia Model Targets | <https://library.vuforia.com/objects/model-targets> |
| Meta Dynamic Object Tracker | <https://developers.meta.com/horizon/documentation/native/android/mobile-dynamic-object-tracker/> |
| OpenXR 的历史状态查询语义 | <https://registry.khronos.org/OpenXR/specs/1.1-khr/html/xrspec.html> |
| 实际使用的 Fast-FoundationStereo | <https://nvlabs.github.io/Fast-FoundationStereo/> |

## 旧键的处理

| 当前键 | 处理 |
| --- | --- |
| `foundationpose2023` | 改为 `foundationpose2024`。新条目为 CVPR 2024，DOI `10.1109/cvpr52733.2024.01692`，页码 17868--17879。 |
| `cosypose2020` | 键可保留，但引用源必须替换为新 Bib 中的正式 ECCV 记录。正确 DOI 为 `10.1007/978-3-030-58520-4_34`，页码 574--591。 |
| `cutie2024`、`yoloe2025` | 键可保留，替换为新 Bib 中的 CVPR 2024 和 ICCV 2025 正式记录。 |
| `megapose2022` | 不纳入 DOI 强制的 Bib。MegaPose 有 PMLR 正式论文，但没有可核验 DOI；原有叙述可改引 `gigapose2024`，并按需要加 `deepim2018, latentfusion2020`。 |
| `kato1999artoolkit`、`olson2011apriltag`、`garridojurado2014aruco` | 标记段改为 `apriltag2011, aruco2014`。 |
| `appleObjectAnchor`、`appleObjectTracking2026`、`azureObjectAnchors`、`vuforiaModelTargets`、`metaDynamicObjectTracker`、`openxr2026spec` | 全部改为上表的官方脚注。 |
| `gottsacker2024artrust`、`schein2025aq`、`koerber2019tia`、`mcgrath2025stias` | 分别改为 `trustar2024`、`aq2026`、`tia2019`、`stias2025`。 |

`Fast-FoundationStereo: Real-Time Zero-Shot Stereo Matching` 在本地 README 中标为 CVPR 2026 accepted，但联网核验时 Crossref 尚无正式 DOI 与页码。它保持项目页脚注，不能用 `foundationstereo2025` 冒充当前实现，也不能以 arXiv 条目填补这一空缺。
