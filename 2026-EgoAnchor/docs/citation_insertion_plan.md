# v3 引用插入记录

适用手稿：`2026-EgoAnchor/egoanchor_cn_ready_v3.tex`。本文件记录当前已落地的引用，而不是待执行计划；修改正文时以小节和检索锚点定位，不依赖行号。

## 交付状态

- 主稿只使用 `\bibliography{egoanchor_cn_refs_verified}`；不要与旧的 `egoanchor_cn_refs.bib` 合并。两库存在同名键，合并可能重新引入 arXiv 或字段不完整的旧记录。
- 已插入 `56` 个唯一引用键；`egoanchor_cn_refs_verified.bib` 的 `56` 个条目均被主稿引用，生成的 BBL 与之对应。
- 2026-08-16，Crossref `works/<DOI>` 对 `55/55` DOI 返回正式记录。TrueCite 对全部题名完成核验；`realitycheck2019` 的副标题已补全为 ``situated physical reality``。MegaPose 的正式 CoRL 版本由 PMLR 收录于 *Proceedings of Machine Learning Research* 205:715--725（2023），但 PMLR、Crossref 与 DataCite 均未登记该出版版本的 DOI；其条目因此保留出版社正式页面的 `url`，不使用指向预印本的 `10.48550/arXiv.2212.06870`。BibTeX 编译记录为 `warning$ -- 0`。
- `vgtc` 的 `abbrv-doi-hyperref-narrow` 样式负责最终 IEEE 型参考文献排版。DOI 使用 BibTeX 的 `doi` 字段，MegaPose 使用 PMLR 的 `url` 字段；不把 DOI、URL 或核验说明写入 `note`。

## 正文插入位置

| 小节与检索锚点 | 已插入的引用 | 支撑范围 |
| --- | --- | --- |
| §1，`动态物体锚定是以物体为中心` | `selfblending2026, gradualreality2024` | PMR 中与真实物体交互的应用动机。 |
| §1，`开放词表检测与分割、立体匹配` | `groundingdino2025, cutie2024, foundationstereo2025, foundationpose2024, gigapose2024` | 视觉能力扩大可定位对象范围，不支撑锚定运行时贡献。 |
| §2.1，`AprilTag、ArUco` | `apriltag2011, aruco2014` | 物理标记式对象位姿。 |
| §2.1，`学术原型在头显相机` | `farasin2020hololens, fan2021assettracking, haxthausen2021hololens, gbot2024` | 头显上的对象级估计与装配引导。 |
| §2.1，`物理场景混合、对象可见性` | `realitycheck2019, realitylens2022, gradualreality2024, selfblending2026, externalcalib2024` | 物理场景混合、对象可见性与外部追踪配置。 |
| §2.2，`针对已知实例` | `densefusion2019, gdrnet2021, epos2020, self6d2020` | 已知对象的 RGB-D、几何回归、对称性与自监督路线。 |
| §2.2，`参考图像或三维模型` | `gen6d2022, megapose2022, gigapose2024, foundationpose2024` | 未见实例的参考图像或模型驱动位姿估计。 |
| §2.2，`时间滤波和多视图约束` | `poserbpf2021, bundletrack2021` | 跨帧 6DoF 状态维护。 |
| §2.2，`渲染--观测比较` | `deepim2018, latentfusion2020` | 候选位姿的渲染比较与细化。 |
| §2.2，`语言--视觉检测` | `glip2022, owlvit2022, groundingdino2025, yoloe2025` | 文本条件语义初始化。 |
| §2.2，`视频对象分割` | `stm2019, xmem2022, cutie2024` | 跨帧对象身份维持。 |
| §2.2，`双目几何侧` | `raftstereo2021, igevstereo2023, dynamicstereo2023, foundationstereo2025, stereoanywhere2025` | 米制几何恢复的技术脉络。 |
| §2.3，`端到端测量、采样补偿` | `diluca2010latency, mrloop2022, stauffert2020mtp, dixit2024predatw` | 时延及其抖动的测量与补偿。 |
| §2.3，`预测式追踪` | `azuma1994improving, laviola2003double, pvt2023, yoon2022headmotion` | 将状态推进到当前或预期显示时刻。 |
| §2.3，`Jacobs等` | `jacobs1997latency, externalcalib2024` | 带时间戳数据流的协调与同步。 |
| §2.3，`世界锁定内容的抖动` | `jitterhmd2022, worldlockedjitter2023` | 抖动的感知后果。 |
| §3.2.1，`开放词表检测器` / `视频对象分割器` / `模型驱动位姿估计器` | `yoloe2025, cutie2024, foundationpose2024` | 实际使用的已发表组件。 |
| §3.2.2，`VCD限制此类候选` | `deepim2018, latentfusion2020, focalpose2022` | 渲染--观测比较范式，不替代 VCD 的运行时角色。 |
| §3.3.1，`常速度卡尔曼滤波` | `kalman1960new` | 状态更新实现。 |
| §4，`YOLOE-26` / `Cutie` / `FoundationPose` / `nvdiffrast` | `yoloe2025, cutie2024, foundationpose2024, nvdiffrast2020` | 已发表组件与渲染实现。 |
| §5.1，`One-Euro作为主要运行时平滑基线` | `casiez2012oneeuro` | 基线方法出处。 |
| §5.2，`风险--覆盖率曲线下面积` | `riskcontrolled2020, ding2020uncertainty` | AURC 的评分排序评价。 |
| §5.3，`增强现实中的追踪因素` | `trustar2024` | 对象锚定条目设计的参考。 |
| §5.3，`AQ` | `aq2026` | 增强质量量表。 |
| §5.3，`TiA与S-TIAS` | `tia2019, stias2025` | 信任量表。 |

## 脚注而非参考文献

以下是官方平台、规范或项目页，保持为紧邻主张的 URL 脚注，不进入 Bib：Azure Object Anchors、Vuforia Model Targets、Apple ObjectAnchor/WWDC26 Object Tracking、Meta Dynamic Object Tracker、OpenXR 1.1 specification，以及实际使用的 Fast-FoundationStereo 项目页。

官方 VGTC 模板在 XeLaTeX 2025 与 `xdvipdfmx` 下需要额外兼容设置：`\vgtcinsertpkg` 后的 `\hypersetup{nesting=false}`。它仅恢复 Hyperref 的受支持默认值，避免 `nesting=true` 吞掉脚注正文；不要修改 `template.tex` 或 `vgtc.cls`。

## 页面预算

当前 55 个实引的 v3 于 2026-08-16 编译为 11 页：正文和图表位于 p1--p9，参考文献位于 p10--p11，满足 9 页正文加 2 页参考文献的限制。页数或浮动体变动后仍须重新核验 `.aux` 页码与逐页 PNG。

## 构建核对

在 `2026-EgoAnchor` 目录执行：

```text
latexmk -g -xelatex -synctex=1 -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_ready_v3.tex
```

产物固定为 `2026-EgoAnchor/pdf/egoanchor_cn_ready_v3.pdf`。参考文献 DOI 后的页码数字来自官方 `vgtc.cls` 启用的 `pagebackref`，表示该文献在正文中被引用的页码，不是 Bib 字段或 DOI 的一部分。
