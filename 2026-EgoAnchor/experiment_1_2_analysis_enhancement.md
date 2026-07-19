# 总体判断

你目前的问题**不是数据不够，也不是系统没有亮点**，而是实验结果仍然按照“采集到了哪些指标”组织，而没有按照“EgoAnchor 为 MR 锚定解决了什么问题”组织。

当前实验一实际上同时混合了四种性质：

* 世界坐标一致性；
* 静止稳定性；
* 动态响应与时延；
* 遮挡期间的失效控制与恢复。

但 Table 2 把不同物理含义、不同单位的指标平铺在一个大表里，Figure 3 又使用近似相同的点线图表达静止、运动和遮挡三类完全不同的行为。结果是读者首先看到“EgoAnchor 运动误差较大、响应较慢”，却不容易理解这是系统主动采用延迟插值换取连续性和稳定性的代价。论文当前也已经承认运动条件下存在明显的误差–时延权衡。

实验二的问题更加明显：当前 Table 3 和 Figure 4 将 mm、deg、ms 等不同量纲的消融差值放在同一个视觉框架中，而且时序合成使用的 P95 跳变指标与该组件真正解决的“零阶保持和逐帧连续输出”并不完全对应。

我的核心建议是：

> **实验一回答完整系统在不同 MR 状态下“表现成什么样”；实验二回答每一个机制“为什么产生这种表现”。**

而不是让两个实验都变成指标汇总。

---

# 一项必须先修正的数据结构问题

五个 XLSX 并不是“每个场景五个独立 trial”，而是：

| 文件   | 场景                   | 独立 trial |     可配对事件 |
| ------ | ---------------------- | ---------: | -------------: |
| task 1 | static head motion     |          1 |              4 |
| task 2 | start–stop 6DoF       |          1 |              5 |
| task 3 | continuous translation |          1 |             18 |
| task 4 | continuous rotation    |          1 |              3 |
| task 5 | occlusion recovery     |          1 | 7 组遮挡–重现 |

每个文件都只有一个 `trial_001`，内部包含多个重复事件。因此正文中“5 个正式 session、5 个场景、每种配置有 5 个完成 trial”的表述容易让审稿人误以为每个场景有五次独立重复。

建议改成：

> We collected five scenario-specific sessions, each consisting of one continuous trial with multiple predefined events. All methods were replayed on the same candidate stream and evaluated using event-level paired summaries.

你在局限部分已经写了“每类定量场景仅由一条包含重复事件的长序列表征”，但它与前面的“5 个完成 trial”存在冲突。

这意味着：

* 不要做帧级显著性检验；
* 不要把 18 个平移 event 描述为 18 个独立实验重复；
* 目前结果主要是**受控系统表征和配对机制证据**，而不是强统计泛化；
* 最好补采若干独立 session，至少让每个核心场景有 3–5 次跨时间重新摆放和重新初始化的重复。

你目前坚持 event-level 而不是 frame-level 统计是正确的。

---

# 1. 实验一应该如何呈现

## 实验一的新问题定义

建议将实验一明确写成：

> **E1: How does EgoAnchor behave as an application-facing MR anchor under head motion, object motion, state transitions, and temporary visual failure?**

它不是单纯的 tracking accuracy benchmark，而是一个**状态化的运行时行为表征**。

实验一可以围绕四种用户可感知属性组织：

1. **World consistency**：头动是否错误地写入物体世界位置。
2. **Rest stability**：物体静止后，虚拟内容是否稳定附着。
3. **Dynamic fidelity**：运动时轨迹有多延迟、多连续、多忠实。
4. **Failure containment**：遮挡和坏观测是否破坏已有锚点。

这比目前按照五个任务逐项罗列指标更符合 IEEE VR 系统论文的表达习惯。

---

## 推荐指标

### A. 静止目标与主动头动

保留两个指标：

* **Translation registration error P95**：世界一致性。
* **Position high-frequency RMS 或 event-centered jitter RMS**：静止视觉稳定性。

注意二者不能混称为“精度”。

你现有结果已经很有力：

* EgoAnchor translation P95：**3.679 mm**
* Arrival-Hold：**22.237 mm**
* One-Euro：**8.273 mm**

即相对 Arrival-Hold 降低约 **83.5%**，相对 One-Euro 降低约 **55.5%**。

但是 `HP-RMS = 0.03 mm` 本质上主要来自 StaticLock 冻结输出。应该称为：

> stationary output jitter

而不要称为 physical tracking accuracy。

还可以增加一个更有 VR 解释力的辅助指标：

* **Head-motion leakage gain**：头部位移或角速度变化有多少被泄漏进静止锚点误差。

这个指标能直接解释为什么 capture-time alignment 是 MR 运行时机制，而不只是一个坐标变换技巧。

---

### B. 起停 6DoF

当前只突出：

* 可见响应时间；
* 运动窗 P95 误差。

这会使 EgoAnchor 看起来主要是“慢”。

原始数据中，更符合对象锚定任务价值的是**放置后的稳定性**。我以每个 event 最后 3 秒作为初步静止窗口重新审计，得到：

| 指标，中位数               |   Arrival |   Capture | One-Euro |          EgoAnchor |
| -------------------------- | --------: | --------: | -------: | -----------------: |
| 放置后 jitter RMS          |  1.352 mm |  1.208 mm | 1.116 mm | **0.441 mm** |
| 放置后 frame-increment P95 |  1.471 mm |  0.892 mm | 0.422 mm | **0.062 mm** |
| 放置后 error P95           | 10.371 mm | 10.388 mm | 9.816 mm | **8.327 mm** |

因此推荐报告四个起停阶段指标中的三个：

* **Movement onset response time**：启动代价。
* **Post-stop settling time**：停止后多久重新稳定。
* **Post-settle jitter RMS**：稳定后的附着质量。

峰值过冲可以作为次要指标或补充材料。

这样结果会形成完整叙事：

> EgoAnchor 响应运动较慢，但在物体重新放置后提供显著更稳定的对象附着。

而不是仅仅暴露 751 ms 对 126 ms 的不利数字。

---

### C. 持续平移

这是当前呈现中最需要重构的部分。

当前的 raw P95 error 比较的是：

[
T_{\mathrm{display}}(t)
\quad\text{vs.}\quad
T_{\mathrm{reference}}(t)
]

但 EgoAnchor 本身使用历史目标时刻和延迟插值，所以 raw error 同时包含：

* 时间滞后；
* 空间轨迹误差；
* 估计噪声；
* 平滑偏差。

不能把它单独解释为 tracking quality。

应当把动态表现拆成两个正交维度：

1. **Effective lag**：轨迹迟了多少。
2. **Lag-compensated residual**：时间对齐后，轨迹形状还差多少。

我按照你正文描述的 frozen lag grid 方法，对 task 3 重新计算后得到：

| 配置         | Effective lag | Lag-compensated P95 residual | Raw P95 error |
| ------------ | ------------: | ---------------------------: | ------------: |
| Arrival-Hold |      182.5 ms |                     19.17 mm |      73.36 mm |
| Capture-Hold |      252.5 ms |                     18.37 mm |      98.71 mm |
| One-Euro     |      387.5 ms |                     17.72 mm |     140.03 mm |
| EgoAnchor    |      323.8 ms |            **9.54 mm** |     111.59 mm |

这揭示了当前表格隐藏的核心结论：

> 相比 Arrival-Hold，EgoAnchor 多付出了约 141 ms 的有效时延，但 lag-compensated residual 降低约 50%；相比 One-Euro，它同时减少约 64 ms 时延，并将 residual 降低约 46%。

这才是系统真正的动态价值：

* 不是“当前位置最准确”；
* 而是“输出一条更连续、更接近真实运动形状的延迟轨迹”。

建议把 **lag–residual trade-off** 作为实验一最重要的动态结果。

---

### D. 持续旋转

旋转结果必须诚实处理。

重新计算后：

| 配置         | Effective angular lag | Lag-compensated angular P95 |
| ------------ | --------------------: | --------------------------: |
| Arrival-Hold |                265 ms |                      5.23° |
| Capture-Hold |                265 ms |            **5.18°** |
| One-Euro     |              377.5 ms |                      5.78° |
| EgoAnchor    |                350 ms |                      6.37° |

EgoAnchor 在旋转轨迹上没有表现出与平移相同的 residual 优势。

不要试图用别的指标掩盖它。建议写成明确的边界：

> The translation channel benefited from temporal synthesis after lag compensation, whereas the same improvement did not consistently extend to rotation. This suggests that the current logarithmic-space rotational motion model and interpolation parameters require further refinement.

这个负结果反而会增加可信度，也可以自然引出 future work。

由于旋转只有 3 个 event，建议不要给它占用主图的大面积；放入紧凑表格或补充图即可。

---

### E. 遮挡与恢复

当前最强的结果之一：

| 配置              |  遮挡窗 error P95 |  遮挡窗 drift P95 |
| ----------------- | ----------------: | ----------------: |
| Arrival-Hold      |          35.30 mm |          36.29 mm |
| Capture-Hold      |          34.10 mm |          34.51 mm |
| One-Euro          |          13.00 mm |          13.61 mm |
| EgoAnchor         | **1.82 mm** | **1.21 mm** |
| EgoAnchor w/o VCD |          23.97 mm |          24.89 mm |

EgoAnchor 相对 One-Euro 降低约 **86%** 的遮挡窗 P95 error；相对关闭 VCD 的变体降低约 **92%**。

推荐主指标：

* **Occlusion-window drift P95**：遮挡时锚点被破坏的程度。
* **Error immediately after reappearance**：重新可见后的瞬时错位。
* **Time to stable alignment**：持续满足误差阈值后的恢复时间。
* **Output availability / stale-hold duration**：系统是否始终给出可消费输出。

目前 Table 2 中所有方法的 persistent recovery time 都是完全相同的 207.577 ms。

这说明该指标很可能主要由共享的候选到达或 target-visible 标记决定，而不是方法行为。它不应占据主表的一整行。可以：

* 从主表删除；
* 在正文说明恢复候选的可用时间由共同输入决定；
* 改用真正依赖配置的“time to stable display alignment”。

---

# 推荐的实验一主表

不要再放九到十个彼此无关的指标。建议主表只保留下面这些：

| System property     | Scenario                         | Primary metric                   | Guardrail             |
| ------------------- | -------------------------------- | -------------------------------- | --------------------- |
| World consistency   | Static object + head motion      | Translation P95                  | Rotation P95          |
| Rest stability      | Post-placement stationary window | Jitter RMS                       | Absolute error P95    |
| Dynamic fidelity    | Continuous translation           | Lag-compensated residual         | Effective lag         |
| Rotational fidelity | Continuous rotation              | Lag-compensated angular residual | Effective angular lag |
| Failure containment | Occlusion                        | Occlusion drift P95              | Stable recovery time  |

每个单元格报告 `median [IQR]`。

其他指标放补充材料：

* raw dynamic error；
* P99 jump；
* overshoot；
* anchor-state occupancy；
* observation age；
  -每个事件的完整分布。

---

# 2. 图表应该如何设计

## 主图不要再使用三个相似的小型点图

当前 Figure 3 的三个面板分别显示静止、运动和遮挡事件，但它们没有表现时间过程，也没有揭示状态转换。

推荐将 Figure 3 重构为一个 **behavioral overview figure**：

### Figure 3A：头动下的世界一致性时间线

上下对齐两条时间序列：

* 上：head yaw 或 head linear/angular speed；
* 下：translation registration error。

只画：

* Arrival-Hold；
* Capture-Hold；
* EgoAnchor。

使用阴影标出主动头动区间。

读者会直接看到 Arrival-time 复合如何将头动写入锚点误差。

---

### Figure 3B：起停事件轨迹

选择一个有代表性的“拿起—移动—放下”事件：

* 参考轨迹；
* Arrival-Hold；
* One-Euro；
* EgoAnchor。

标记：

* reference motion onset；
* EgoAnchor unlock；
* reference stop；
* StaticLock reacquisition。

在右侧加一个放大 inset，展示放置后 1–2 秒的抖动。

这比单独报告 751 ms 响应时间更能解释整个状态转换行为。

---

### Figure 3C：动态误差–时延 Pareto 图

* 横轴：effective lag，ms；
* 纵轴：lag-compensated P95 residual，mm；
* 每个 event 一个淡色点；
* 大标记表示中位数和 IQR。

低且靠左越好。

大致位置为：

* Arrival：182.5 ms / 19.17 mm；
* Capture：252.5 ms / 18.37 mm；
* One-Euro：387.5 ms / 17.72 mm；
* EgoAnchor：323.8 ms / 9.54 mm。

这是整篇系统评估中最有价值的一张图。

---

### Figure 3D：遮挡状态机时间线

选择一个严重遮挡事件，绘制：

1. VCD score；
2. accepted/rejected candidate；
3. anchor state；
4. translation error。

对比：

* EgoAnchor；
* EgoAnchor w/o VCD。

用垂直线标出 occlusion start 和 target visible。

这会把“质量门控和生命周期管理”从抽象模块变成可见的运行时行为。

---

## 图形类型选择

适合：

* 配对散点图和配对连线；
* 轨迹时间序列；
* error–lag scatter；
* ECDF 或 risk–coverage；
* 状态时间线；
* median + IQR point-range。

不适合：

* 只有 3–7 个事件时使用 violin plot；
* 将不同单位的 delta 放在同一纵轴；
* 对渲染帧绘制大型箱线图，让样本量看起来非常大；
* 雷达图；
* 将所有四个方法、八个消融和所有指标塞进一张图。

---

# 3. 实验二应该如何重构

## 新问题定义

建议改成：

> **E2: Which runtime mechanism is responsible for each application-facing anchoring behavior?**

每个组件只使用与其设计目标直接对应的场景和指标。

---

## 推荐的组件—场景—指标对应关系

| 组件                   | 场景                        | 主指标                                                | 代价或护栏                  |
| ---------------------- | --------------------------- | ----------------------------------------------------- | --------------------------- |
| Capture-time alignment | Static object + head motion | Translation P95                                       | Rotation P95                |
| StaticLock             | Static / post-placement     | HP-RMS 或 jitter RMS                                  | Absolute error              |
| Temporal synthesis     | Continuous translation      | Hold ratio、frame increment、lag-compensated residual | Effective lag               |
| VCD admission          | Occlusion                   | Occlusion drift/error P95                             | Accepted coverage、recovery |

---

## Capture-time alignment

使用四个 head-motion event 的配对点：

* Full EgoAnchor；
* w/o capture-time alignment。

目前配对差值方向一致，正文报告的 translation P95 配对中位差为 +5.585 mm。

图用四条配对连线即可，不需要柱状图。

---

## StaticLock

只展示静止期指标：

* HP-RMS；
* drift；
* absolute error guardrail。

不要把起动响应时间算进 StaticLock 消融的主要结论，因为它同时受到 motion detection、dwell、synthesis delay 等多个机制影响。

当前结果表明关闭 StaticLock 后 HP-RMS 配对增加 1.592 mm。

建议增加一个直观时间片段：

* Full 输出近似冻结；
* w/o StaticLock 输出持续围绕参考振荡。

---

## Temporal synthesis

这是当前消融最需要更换指标的部分。

现有分析在起停任务中得到 P95 和 P99 方向相反，于是难以得出结论。

原因不是时序合成没有效果，而是指标没有测量它的核心目标。

在 continuous translation 数据中，我得到：

| 指标，中位数                      |       Full EgoAnchor | w/o temporal synthesis |
| --------------------------------- | -------------------: | ---------------------: |
| Effective lag                     |             323.8 ms |               253.8 ms |
| Lag-compensated P95 residual      |    **9.54 mm** |               18.55 mm |
| Frame increment P95               |    **7.95 mm** |               27.15 mm |
| P95 acceleration                  | **10.8 m/s²** |            194.1 m/s² |
| Exact/near-exact hold-frame ratio |              接近 0% |                 约 86% |

这形成了清晰的组件结论：

> Temporal synthesis adds roughly 70 ms of fitted lag, but removes the zero-order-hold behavior between asynchronous observations and substantially improves trajectory continuity and lag-compensated spatial fidelity.

建议将“hold-frame ratio”作为最直接的主指标，因为它对应“低频候选流转逐帧渲染输出”的系统目标。

---

## VCD admission

保留两种互补证据：

1. **系统级配对结果**：Full vs w/o VCD 的遮挡窗误差。
2. **候选级诊断**：risk–coverage。

当前：

* Full：1.822 mm；
* w/o VCD：23.970 mm；
* 配对差值中位数：+21.857 mm；
* VCD mean-risk AURC：2.384 mm；
* random ordering：4.081 mm。

risk–coverage 图上还应标出实际运行阈值对应的 operating point：

* coverage；
* mean risk；
* P95 tail risk。

这样审稿人能判断实际阈值是否位于合理位置，而不是只看到完整排序曲线。

---

# 推荐的实验二表格

将当前只列 delta 的表改成：

| Component         | Scenario    | Metric             |     Full |   Ablated | Paired Δ [IQR] | Guardrail         |
| ----------------- | ----------- | ------------------ | -------: | --------: | --------------: | ----------------- |
| Capture alignment | Head motion | Translation P95    | 3.679 mm |  8.730 mm |       +5.585 mm | Rotation P95      |
| StaticLock        | Static      | HP-RMS             | 0.030 mm |        — |       +1.592 mm | Median error      |
| Synthesis         | Translation | Lag-comp. residual | 9.540 mm | 18.552 mm |    paired value | +70 ms lag        |
| VCD               | Occlusion   | Error P95          | 1.822 mm | 23.970 mm |      +21.857 mm | Recovery/coverage |

这里的 `Full` 和 `Ablated` 能让读者理解实际量级；`Δ` 才负责归因。当前表格只给 delta，读者无法判断基线水平。

---

# 4. 数据分析与统计方式

## 统计单位

坚持：

* 每个 event 先计算指标；
* 再在事件之间汇总；
* 渲染帧只用于形成轨迹；
* 不把帧当作独立样本。

你当前的方法说明在这一点上是正确的。

---

## 当前数据不建议做强显著性检验

由于每个场景只有一个连续 trial，事件可能具有：

* 相同操作者；
* 相同摆放；
* 相同光照；
* 时间相邻；
* 相同初始化；
* 自相关。

建议主文报告：

* median [IQR]；
* paired event delta；
* 改善方向的事件数，例如 4/4、7/7；
* event-level bootstrap interval，但明确其只量化该序列内事件波动；
* 所有配对点。

避免写：

* statistically significant；
* generalizes across environments；
* proves robustness；
* across trials，除非真的补采独立 trial。

---

## 动态指标必须预先冻结定义

在论文和分析代码中明确：

* motion speed threshold；
* 最短有效运动区间；
* lag search range 和步长；
* interpolation method；
* reference overlap requirement；
* post-stop window；
* stable recovery 的误差阈值与持续时间；
* hold frame 的数值容差。

否则审稿人容易怀疑是看到结果后选择指标。

---

# 5. 结果段落应该如何写

每个结果段落使用相同结构：

1. **先回答系统问题。**
2. 给主结果。
3. 给机制解释。
4. 给代价或失败边界。
5. 限定证据范围。

例如：

### 静止与头动

> Capture-time alignment prevented delayed camera observations from being compounded with the current headset pose. Across four head-motion events, EgoAnchor reduced translation P95 from 22.24 mm with Arrival-Hold to 3.68 mm. StaticLock further suppressed stationary output fluctuations. These results characterize world consistency and displayed-anchor stability relative to the Quest reference; they should not be interpreted as external physical accuracy.

### 持续平移

> EgoAnchor intentionally traded latency for trajectory fidelity. Relative to Arrival-Hold, its fitted lag increased from 182.5 to 323.8 ms, while the lag-compensated P95 residual decreased from 19.17 to 9.54 mm. Thus, the higher zero-lag registration error primarily reflects a delayed output timeline rather than a proportionally less faithful motion trajectory.

### 持续旋转

> This benefit did not consistently extend to rotation. EgoAnchor exhibited a 350 ms fitted angular lag and a 6.37° lag-compensated P95 residual, compared with 265 ms and 5.18° for Capture-Hold. We therefore treat rotational synthesis as a current limitation rather than claiming a uniform dynamic improvement.

### 遮挡

> VCD admission contained harmful updates during occlusion. Disabling VCD increased the median occlusion-window P95 error from 1.82 to 23.97 mm, while output coverage remained unchanged. The benefit therefore arose from rejecting damaging candidates rather than suppressing output altogether.

这种写法比连续罗列数字更像高水平系统论文：**收益、机制、成本和边界同时出现。**

---

# 6. 还需要立即核对的日志一致性问题

论文实现部分目前写的是完整视觉流水线约 140 ms、约 7 fps。

但五个工作簿中的 `python_candidates` 日志显示：

* TRACK 阶段 `total_ms` 中位数约 **74.3 ms**；
* P95 约 **86.9 ms**；
* REGISTER 阶段中位数约 **751 ms**。

这可能是因为：

* 140 ms 包含了未记录的图像传输或排队；
* `total_ms` 只统计服务器模型执行；
* 论文数字来自另一次硬件测试；
* “fps”受最新帧策略、无掩膜帧和注册阶段共同影响。

投稿前必须明确区分：

* inference latency；
* capture-to-candidate latency；
* candidate update interval；
* capture-to-display observation age；
* initialization latency。

否则审稿人很容易从日志或图中发现 74 ms 与 140 ms 不一致。

---

# 最终建议的篇幅分配

对于 IEEE VR 系统论文：

* 实验一：约 1.0–1.25 页；
* 实验二：约 0.6–0.8 页；
* 用户实验：约 1.25–1.5 页；
* 一张核心系统行为图；
* 一张消融图；
* 两张紧凑表；
* 其余完整指标放 supplementary material。

你现在不需要增加更多指标，而是需要删掉不回答系统问题的指标，并将最有价值的三个结果推到叙事中心：

1. **头动下的世界一致性与静止附着稳定性；**
2. **连续运动中的 lag–fidelity trade-off；**
3. **遮挡期间 VCD 对有害更新的 containment。**

下一步应直接按照这套结构重算并生成新版 **Table 2、Figure 3、Table 3 和 Figure 4**。
