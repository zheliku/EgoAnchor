# goAnchor 论文写作规划与系统设计笔记 (Paper Planning Notes)

**日期**：2026-06-22
**定位**：IEEE VR 2027 Papers Track (Technology / System Paper)
**当前状态**：最终版主稿 `egoanchor_final.tex` 已建立（摘要+引言完整撰写，相关工作→结论为带写作指引的占位骨架），编译产物在 `pdf/egoanchor_final.pdf`。下方 §5 记录 2026-06-22 文献核实与定位决策。

---

## 1. 学术定位与论文核心主张

### 1.1 核心研究问题 (Research Question)

> 如何在**头显持续运动**、**感知模型计算异步延迟**、**通信低频带噪**以及**间歇性失效**的条件下，将相机坐标系 6DoF 位姿观测流稳定映射并转化为混合现实（MR）应用层真正可用的**世界一致且稳定的真实物体锚点**？

### 1.2 论文核心主张 (Core Claims)

1. **“位姿精度不等于锚点质量”**：计算机视觉算法输出的单帧 camera-space pose 精度，并不自然保证混合现实应用层世界锚点的可用性。
2. **解耦时空语义（帧对齐）**：通过在时间上将异步外部感知延迟与头显运动解耦（`Frame-Aligned`），是保证真实物体在头显运动下“零打滑”的物理前提。
3. **可靠性门控与静止锁定是吸收抖动与异常的关键**：无需复杂的动态预测模型，在帧对齐之上引入多维可靠性门控、卡尔曼自适应状态估计（默认时序平滑）、静止状态锁定（Static Lock）和断连恢复自愈（Reacquire），即可用极低的计算开销实现高稳定、抗遮挡的物体锚定。

---

## 2. 系统核心机制与公式定义

### 2.1 帧对齐配准 (Frame-Aligned Mapping)

为了消除异步感知带来的头动滑移（Head-Motion-Induced Slip），系统摒弃传统的到达时刻对齐（Arrival-Time Mapping），采用基于 `frame_id` 回查的机制：

* **输入观测**：采集时刻 $t_{\text{capture}}$ 的相机空间物体位姿观测 ${}^{C}\mathbf{T}_{O}(t_{\text{capture}})$
* **回查位姿**：头显环形缓存中 $t_{\text{capture}}$ 时刻对应的相机世界位姿 ${}^{W}\mathbf{T}_{C}(t_{\text{capture}})$
* **帧对齐世界空间位姿**：
  \[
  {}^{W}\mathbf{T}_{O}(t_{\text{capture}}) = {}^{W}\mathbf{T}_{C}(t_{\text{capture}}) \cdot {}^{C}\mathbf{T}_{O}(t_{\text{capture}})
  \]
* **对比项（到达时刻配准错误公式）**：
  \[
  {}^{W}\hat{\mathbf{T}}_{O} = {}^{W}\mathbf{T}_{C}(t_{\text{return}}) \cdot {}^{C}\mathbf{T}_{O}(t_{\text{capture}})
  \]
  其中 $t_{\text{return}}$ 为外部计算返回时间。由于 ${}^{W}\mathbf{T}_{C}(t_{\text{return}}) \neq {}^{W}\mathbf{T}_{C}(t_{\text{capture}})$，两者在头部运动时的偏差将导致巨大的视觉滑动。

### 2.2 可靠性评估指标

感知后端计算的多维可靠性分值：

1. **重投影颜色误差 ($score_{reproj}$)**：渲染三维模型与当前双目透视图像在 LAB 色彩空间下的相似度，若未初始化或缺失记为 $-1$。
2. **渲染深度有效性 ($score_{depth}$)**：在遮罩区域内有效立体渲染深度的覆盖比例，中性值（有效深度覆盖不足时）为 $0.5$，深度有效覆盖阈值应与当前 Unity/Python 真实实现一致，即 `depth_valid_in_mask >= 0.10`。
3. **几何对数平均分 ($S_t$)**：
   \[
   S_t = \exp \left( w_c \ln(score_{reproj}) + w_d \ln(score_{depth}) \right)
   \]

### 2.3 静止锁定控制器 (Static Lock Controller)

在物体或头显相对静止时，锁定输出以完全抑制噪声：

* **锁定进入**：当连续观测速度和角速度低于预设的极低门槛（如 `enterSpeedMps`、`enterAngSpeedDps`），且时间累积达到 $headSettleSeconds$。锁定一旦进入，直接输出锁定时的世界位姿 $lockedPose$。
* **累积解锁**：解锁证据有三路：
  1. **速度逃逸**：自适应低通速度超出阈值；
  2. **漂移绳索**：观测共识点 $obsConsensus$ 与锁定进入时的锚定起点 $anchorOrigin$ 的绝对距离超过阈值（不能对比当前已漂移的 $lockedPose$，否则慢速持续移动将永远无法解锁）；
  3. **CUSUM 偏差累积**：观测点相对于 $lockedPose$ 的残差累积值超出死区。
* **接缝消除**：解锁瞬间，记录当前 $lockedPose$ 相对当前最新候选输出的接缝残差（Seam Residual），并在后续的独立接缝阶段将其向 $0$ 平滑衰减，平滑回归到普通滤波更新状态。

---

## 3. 实验设计与对比矩阵 (Evaluation)

### 3.1 对比 Baselines 组合 (系统级基线与模块化消融)

我们将实验对比设计为“系统级对齐对比”和“时序/策略模块消融”两个层次，以全面展现 EgoAnchor 系统的整体优势及其内部设计的合理性：

#### 3.1.1 系统级对齐基线

* **Arrival-Time Mapping**：无帧对齐，包到达时刻配准，直接与 HMD 最新位姿结合。用于证明 Frame-Alignment 是消除打滑的物理基础。
* **Frame-Aligned Raw**：使用帧对齐，但无任何时序滤波与门控策略。用于量化纯视觉姿态跟踪的原始噪声与空间抖动。
* **EgoAnchor (Default configuration)**：完整方法。使用帧对齐 + 默认卡尔曼滤波 + 可靠性门控 + 静止锁定控制器。

#### 3.1.2 模块化消融与设计空间比较

* **时序平滑模块消融 (Filter Module comparison)**：在保持帧对齐和其它组件不变的前提下，对比不同时序平滑器的表现，生成 **抖动-延迟折衷曲线 (Jitter-Lag Tradeoff Curves)**。
  * **Low-Pass Filter (LP)**：简单低通平滑，展示常规滤波带来的严重延迟响应。
  * **One Euro Filter**：常用于 VR 交互的自适应滤波，作为对比。
  * **Kalman Filter (Default)**：系统默认采用的 ConstVelocity 状态估计，对平移和四元数对数空间旋转进行跟踪。
* **静止锁定模块消融 (Static Lock Ablation)**：
  * 对比 **EgoAnchor (默认 Kalman + 启用静止锁)** vs **EgoAnchor (仅 Kalman，不启用静止锁)**。量化 Static Lock 机制在吸收微小系统噪声（如传感器漂移或视觉微抖）中的绝对效益。
* **可靠性门控消融 (Gating Ablation)**：
  * 对比 **EgoAnchor (启用多维可靠性门控)** vs **EgoAnchor (完全信任所有外部返回位姿)**。主要通过追踪丢失、光照剧变或手动遮挡等干扰场景，量化门控在抑制位姿跃变（Pose Jump）和触发重定位（Reacquire）自愈中的保护作用。

### 3.2 测量指标定义

1. **World-space Anchor Error**：应用层虚拟 Overlay 在世界空间中的 6DoF 坐标与物体真实 Ground Truth（真值）之间的误差（分为平移误差 $\text{RMSE}_t$ 和旋转误差 $\text{RMSE}_R$）。
2. **Head-motion-induced Slip**：在头显处于正弦或圆周头动时，虚拟 Overlay 相对于真实物体的视觉“滑动”位移。
3. **World-space Jitter**：物体静止、头显也静止时，虚拟 Overlay 在世界坐标系中的标准差（SD）。
4. **Lag / Latency**：物体运动时，虚拟 Overlay 的追踪响应延迟（使用交叉相关分析计算时滞）。
5. **Recovery Time**：在物体被手完全遮挡或移出视野后，重新出现到系统重新成功锚定并恢复稳定输出（状态机回到 Tracking）所需的时间。

### 3.3 Ground Truth (真值) 获取实验设计

* **最佳定量基准：Touch Controller 作为标靶**
  * *做法*：使用 Meta Quest 3 头显的官方 Controller。Controller 的 CAD 模型已知，且其精确 of 6DoF 世界坐标可由 Meta SDK 接口原生获取。
  * *原理*：对 Controller 进行 3D 重建并将 CAD 输入 EgoAnchor 系统。在运行中，EgoAnchor 仅使用 Passthrough 图像对 Controller 进行视觉追踪；而 Meta SDK 输出的数据作为绝对 Ground Truth，用于超高精度计算 World-space Anchor Error 和 Head-motion-induced Slip。
* **日常物体真值设计：隐藏的 Fiducial 标记**
  * *做法*：对于键盘、鼠标等日常物体，在物体隐蔽处粘贴 ArUco 标记。
  * *原理*：ArUco 标记仅供实验评估用的独立相机/标定链路离线解算真值，EgoAnchor 的运行时分割与追踪算法对该标记不可见，实现非仪器化下的真值对比。

### 3.4 用户可用性实验设计 (Human Study)

* **设计**：Within-Subject（被试内）设计，招募 12-15 名参与者。
* **自变量**：控制条件包括 Baseline (仅时序状态估计如 Kalman) 与 EgoAnchor (默认 Kalman + 启用静止锁定 + 可靠性门控的完整配置)。
* **因变量/任务**：
  1. *精细对齐任务*：要求参与者在不同的头部转动速度下，使用射线或手部对附着在物理实体上的虚拟按键进行点击，测量完成时间与失误率。
  2. *快速遮挡任务*：在交互中用书本遮挡物体，随后移开，测量参与者恢复交互信心的时间。
* **主观量表**： Likert scale 问卷评估以下维度：
  * **Jitter (抖动感)**：虚拟物体是否有微小的漂移或抖动。
  * **Lag (延迟感)**：移动物体或转头时，虚拟菜单是否滞后。
  * **Attachment (附着感)**：虚拟内容是否像“焊接”在实体上。
  * **Trust (信任度)**：用户对锚点长时稳定不丢失的心理信任度。

---

## 4. 相关工作推荐文献检索矩阵

后续写作 Related Work 时，必须优先搜索和引用 VR/AR/MR 领域的文献，控制 CV 论文的比例：

1. **Late Latching & Time Alignment in XR**：
   * 检索 *“Late Latching”*, *“Asynchronous TimeWarp”*, *“Motion-to-Photon Latency in AR”*（IEEE VR / ISMAR 经典文献，如 Azuma 的早期关于 AR 延迟配准误差的奠基性文章）。
2. **Spatial Anchors & Dynamic Tracking**：
   * 检索 *“world anchors”*, *“spatial attachment in mixed reality”*, *“interactive real-object tracking”*，对比 Apple Object Tracking 与 Meta Dynamic Object Tracker 的技术规范。
3. **One Euro & Filtering in 3DUI**：
   * 检索 Casiez 2012 年发表的关于 *“1€ Filter”* 的经典论文，以及 Kalman 滤波在空间 3D 输入设备中的滞后分析工作。

---

## 5. 文献核实与最终定位决策（2026-06-22，三专家团 + 联网核实）

本节是本轮关键产出。三个并行研究团核实了平台landscape、CV/XR文献谱系与评估方法学，结论已落入 `egoanchor_final.tex` 与 `egoanchor_cn_refs.bib`。

### 5.1 新颖性定位（关键修正）

* **旧表述已过时、勿再用**：「只有苹果做静态、没人做动态物体追踪」是错的。**Apple visionOS 27（WWDC 2026）已正式支持手持/运动物体追踪**（`appleVisionOS27ObjectTracking`）。若沿用旧表述会被审稿人当场击穿。
* **新的、可辩护的定位 = 五维空白**：没有任何现有系统同时满足以下五个维度，EgoAnchor 是首个：
  1. **免主动深度**（仅双目相机，无 LiDAR/结构光）—— visionOS、HoloLens/Azure 都依赖主动深度；
  2. **任意日常物体**（非固定类别）—— Meta「动态物体追踪」实测仅稳定支持键盘等极少数预定义类；
  3. **允许运动**（动态）—— Vuforia Model Targets、visionOS 2 均为静态物体；
  4. **CAD 可由手机照片低成本生成**—— visionOS 需数小时 Create ML 训练；
  5. **开放 + 消费级硬件**—— 平台方案全封闭；Azure Object Anchors 已于 2023 年底停服。
* **最近邻各破一维**：Vuforia（相机+CAD 但静态、封闭）；visionOS 27（动态+model-based 但需深度设备+多小时训练+封闭，高帧率路径也仅 ~30Hz）；Meta（相机+动态但仅键盘类）。
* 与 Vision Pro 的对比口径：**只做定性平价对照，不争输赢**（它有 LiDAR、生态封闭、API 语义不同）。

### 5.2 帧对齐锚定的理论定位（已写入引言）

* 框定为渲染管线 **late latching / 异步时间扭曲（ATW）原理在「异步感知融合层」的对偶**：ATW 把渲染结果对齐到「当前」最新头显位姿；帧对齐锚定把外部感知结果对齐回其「采集时刻」头显位姿。
* 与**预测式跟踪**（Azuma & Bishop 1994）区分：预测是「猜未来」，帧对齐是「用已记录的过去」，**精确消除而非估计** slip。
* 文献核实结论：这一「按 frame_id 回查采集时刻位姿、作为应用层 late latching」的明确框定**在已核实的先验工作中不存在**，可作为新颖系统贡献（迁移已知图形管线原理到新层），honest 且 reviewer-defensible。
* 父原理引用：Azuma 1997「时延×运动 = 动态配准误差首要来源」，pose-to-anchor 是其在感知融合阶段的具体实例化。

### 5.3 评估方法学审稿风险（必须在正文预先回应）

1. **手柄真值与锚点共用 Quest 跟踪系** → 只能隔离锚定/滤波栈，无法暴露与头显 SLAM 同源的共模误差。须明说此点。
2. **单标记近正对存在旋转翻转歧义（IPPE flip）** → 改用多标记板/cube，并报告真值静态重复性作为噪声地板，只在噪声地板之上断言误差。
3. **滤波器对比须画 Pareto 前沿**（扫描 fcmin/beta、Q、cutoff），标注实际部署工作点；单点比较「优于 One Euro」不可辩护。
4. **N=12–15 须配先验功效分析（G*Power）**，不能只靠惯例；「信任/附着」须标注为自定义改编构念；Likert 用 Friedman+Wilcoxon（Holm 校正）+ 报告效应量。
5. **恢复时间须报告随阈值变化的曲线**，非单一数值。
6. **互相关时延**对非线性滤波会有偏差，须在子集上用独立 motion-to-photon 方法交叉验证。

### 5.4 已核实并加入 bib 的关键文献

* CV 谱系：FoundationPose(CVPR24)、Cutie(CVPR24)、SAM/SAM2/SAM3、YOLOE(ICCV25)、FoundationStereo(CVPR25)；ADD→Hinterstoisser ACCV12、ADD-S→PoseCNN(RSS18)、BOP(ECCV18)。
* XR 谱系：Azuma 1997 survey、Azuma&Bishop 1994 预测跟踪、Mark 1997 后渲染 warp、van Waveren 2016 ATW、One Euro(CHI12)、Holloway 1997 配准误差。
* 平台：visionOS 27(WWDC26)、Meta Dynamic Object Tracker、Vuforia Model Targets、Azure Object Anchors(已停服)。
* 评估工具：ArUco/AprilTag、Di Luca 2010 互相关时延、NASA-TLX、Gonzalez-Franco 2018 具身问卷。

### 5.5 投稿前 checklist（待办）

* [ ] 核对 SAM3 / YOLOE / FoundationStereo 最终发表 venue 与完整作者列表（目前为 preprint 占位）。
* [ ] teaser 图：一眼对照「到达时刻打滑」vs「帧对齐贴合」。
* [ ] 补齐正文 `\cite` 后移除 `\nocite{*}`。
* [X] 决定主文标题用 Kalman 还是 One Euro 作默认时序模块：**已确认用 Kalman**（恒速卡尔曼，与代码 `ConstVelocityModel`/`KalmanModel` 默认及 v1 一致）。One Euro 仅作为滤波器消融对比中的一条基线，用于画抖动-延迟 Pareto 曲线，不是默认方法。
