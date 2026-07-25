可以。现在把实验 3 明确定位为**跨对象感知评价**，任务只负责让参与者经历论文关心的三种运行时状态，问卷负责测量用户是否感知到锚点在稳定性、运动附着、恢复和可信度上的差异。

这与正文逻辑相符：实验 1、2 已量化头动一致性、静止抖动、起停权衡和遮挡恢复；实验 3 只补充用户是否感知到这些差异。EgoAnchor 的设计目标本身就是世界一致性、持续输出和可预测的失效—恢复行为。 实验 3 在整篇论文中的角色也应当是应用侧感知效用，而不是重复系统性能测量。

下面给出一份可以直接落地到 Unity 和伦理材料中的最终量表方案。

---

# 一、量表总体结构

建议采用三级测量：

| 填写时点                     | 内容                                        |                   数量 |
| ---------------------------- | ------------------------------------------- | ---------------------: |
| 每完成一个物体的三个任务后   | 物体级即时体验：稳定、附着、恢复            |                   3 项 |
| 每完成一种方法下的三个物体后 | CRIQ plausibility、锚点信任、稳定—响应平衡 |                   7 项 |
| 两种方法全部结束后           | 最终选择和开放反馈                          | 1 个选择题＋2 个开放题 |

每位参与者总共填写：

* 物体级即时评分：
  (2\text{ 方法}\times3\text{ 物体}\times3\text{ 项}=18) 项；
* 方法级评分：
  (2\text{ 方法}\times7\text{ 项}=14) 项；
* 最终偏好：1 项；
* 开放题：2 项。

总共 33 个量化评分，分散在整个实验中，不会形成很重的问卷负担。

## 统一评分方式

除 CRIQ 外，所有研究定制条目使用 7 点 Likert：

* 1：完全不同意
* 2：不同意
* 3：比较不同意
* 4：既不同意也不赞同
* 5：比较同意
* 6：同意
* 7：完全同意

不要使用 0–6，也不要在不同任务之间改变刻度。

---

# 二、物体级即时问卷

## 填写时间

参与者对一个物体依次完成：

1. 静止观察；
2. 拿起、移动、放下；
3. 遮挡恢复。

三个阶段全部完成后，虚拟锚定内容暂时隐藏，在 HMD 中立即显示以下三个题目。

不要在每一个任务后都中断填写。三个任务总共约 45–60 秒，结束后再问对应的三项，参与者仍能清楚记得各阶段体验，同时不会频繁破坏实验连续性。

---

## O1：静止稳定性

**条目 ID：`OBJ_STATIC_STABILITY`**

> 在静止观察阶段，虚拟内容在真实物体上的位置保持稳定。

英文可写：

> During static observation, the virtual content remained stable relative to the physical object.

### 对应任务

静止观察，包括：

* 正面观察；
* 左右移动头部；
* 改变观察角度；
* 适当靠近物体。

### 对应论文机制

* capture-time world alignment；
* StaticLock；
* stationary jitter；
* head-motion consistency。

该条目不要写成“系统没有抖动和漂移”，因为“抖动”和“漂移”是两个相近但不完全相同的现象。正文解释时可以同时联系两项系统指标，但问卷条目保持单一判断。

---

## O2：运动附着感

**条目 ID：`OBJ_MOTION_ATTACHMENT`**

> 在拿起、移动和旋转物体时，虚拟内容与真实物体保持一致运动。

英文可写：

> While I picked up, moved, and rotated the object, the virtual content moved consistently with the physical object.

### 对应任务

* 拿起物体；
* 平移约 25–30 cm；
* 旋转约 30–45°；
* 在空中短暂停留；
* 放置到目标区域。

### 对应论文机制

* temporal synthesis；
* motion continuity；
* response lag；
* anchor sliding。

这里使用“保持一致运动”，比“像物体的一部分”更中性。后者带有较强的具身或所有权隐喻。

---

## O3：遮挡恢复可信度

**条目 ID：`OBJ_RECOVERY_CONFIDENCE`**

> 遮挡移除后，虚拟内容恢复到了与真实物体一致的位置。

英文可写：

> After the occlusion was removed, the virtual content recovered to a position consistent with the physical object.

### 对应任务

* 物体完全遮挡约 2.5 秒；
* 移除遮挡；
* 继续观察约 5–7 秒。

### 对应论文机制

* VCD admission；
* lifecycle management；
* frozen/gliding states；
* reacquisition；
* failure containment。

该条目重点是“恢复结果”，不要同时加入“恢复很快”“恢复过程平滑”等内容，否则会成为双重问题。

---

## 物体级问卷的处理方式

这三个条目分别代表三个不同任务阶段，因此：

* 不合并为总分；
* 不计算 Cronbach’s (\alpha)；
* 不称为一个标准量表；
* 分别分析方法和物体的影响。

论文中称为：

> three task-specific single-item ratings

而不是：

> Object Anchoring Questionnaire

这样最诚实。

---

# 三、方法级问卷

## 填写时间

参与者在同一种方法下完成三个物体后，填写一次方法级问卷。

流程是：

```text
方法 A
  物体 1：三个任务 → 3 项即时评分
  物体 2：三个任务 → 3 项即时评分
  物体 3：三个任务 → 3 项即时评分
  方法级问卷：7 项
  休息
方法 B
  重复相同流程
  方法级问卷：7 项
```

方法级问卷要求参与者评价：

> “刚才这种方法在三个物体上的总体体验。”

不能让参与者只根据最后一个物体作答，因此问卷首页应明确写：

> 请综合考虑刚才在三个物体上的全部体验进行评分。

---

# 四、CRIQ plausibility-illusion：3 项

SelfBlending 使用的 CRIQ plausibility-illusion 子量表通过三个问题评价交互是否可信、同步和具有响应性。 这三个方面与 EgoAnchor 的虚实空间一致性和运行时响应较接近。

## CRIQ-P1：总体合理可信度

**条目 ID：`CRIQ_PLAUSIBILITY`**

> 这种虚实交互体验在多大程度上让你觉得合理可信？

英文原意：

> How much did the interaction feel plausible to you?

## CRIQ-P2：同步性

**条目 ID：`CRIQ_SYNCHRONY`**

> 你在多大程度上感觉真实物体与虚拟内容之间的交互是同步的？

英文原意：

> How much did you have the perception of a synchronized interaction between the physical and virtual environments?

## CRIQ-P3：响应性

**条目 ID：`CRIQ_RESPONSIVENESS`**

> 你在多大程度上感觉这一体验会响应你的操作？

英文原意：

> How much did you feel like the experience was responding to you?

## CRIQ 的评分锚点

因为原条目采用“How much”问法，使用：

* 1：完全没有
* 2：非常少
* 3：比较少
* 4：中等程度
* 5：比较强
* 6：很强
* 7：非常强烈

三个条目取平均，得到：

[
CRIQ_}
======

\frac{P1+P2+P3}{3}
]

## 一个重要命名问题

上述中文版本将“physical and virtual environments”具体化为“真实物体与虚拟内容”。因此，严格来说它属于：

> adapted CRIQ plausibility-illusion items

而不是未经修改的原始 CRIQ。

论文中建议写：

> We used three adapted items based on the CRIQ plausibility-illusion subscale, targeting perceived plausibility, synchrony, and responsiveness between the physical object and attached virtual content.

如果你希望直接称为 CRIQ 子量表，应：

1. 找到 CRIQ 原始论文和正式条目；
2. 保留原始措辞；
3. 完成中文翻译—回译；
4. 在补充材料中提供中英文版本。

不要仅根据 SelfBlending 的转述就声称使用了“官方中文版 CRIQ”。

---

# 五、锚点信任与依赖意愿：3 项

这一部分是研究定制的核心量表，测量用户是否相信并愿意依赖锚点。

建议命名为：

> Anchor Trust and Reliance

或中文：

> 锚点信任与依赖意愿

不能将其称为已经验证的标准量表。

---

## AT1：位置可信度

**条目 ID：`TRUST_POSITION`**

> 我相信该方法显示的虚拟内容位于真实物体上的正确位置。

英文：

> I trusted that the virtual content displayed by this method was located at the correct position relative to the physical object.

这是最直接的锚点信任条目。

---

## AT2：恢复后信任

**条目 ID：`TRUST_AFTER_RECOVERY`**

> 短暂遮挡后，我仍然相信恢复后的锚点位置是可靠的。

英文：

> After a temporary occlusion, I still trusted the recovered anchor position.

这直接对应论文的生命周期和重新获取贡献。

---

## AT3：实际依赖意愿

**条目 ID：`TRUST_RELIANCE`**

> 在需要虚拟内容准确附着于真实物体的混合现实应用中，我愿意依赖这种锚定方法。

英文：

> I would be willing to rely on this anchoring method in an MR application that requires virtual content to be accurately attached to a physical object.

这是最重要的应用层条目。它不是泛泛地问“喜欢不喜欢”，而是问参与者是否愿意基于该锚点完成实际应用。

---

## 信任量表的计分

若内部一致性可以接受，则计算：

[
AnchorTrust
===========

\frac{AT1+AT2+AT3}{3}
]

报告：

* Cronbach’s (\alpha)，或 McDonald’s (\omega)；
* 每种方法的中位数和 IQR；
* 配对差；
* 效应量和置信区间。

由于样本预计只有 18 人，内部一致性结果只能用于描述，不能声称完成了量表验证。

如果内部一致性很低，例如 (\alpha<0.70)，不要强行报告总分，应分别报告三个条目。

---

# 六、稳定性—响应性平衡：1 项

**条目 ID：`STABILITY_RESPONSIVENESS_BALANCE`**

> 总体而言，该方法在锚点稳定性与响应及时性之间取得了合适的平衡。

英文：

> Overall, this method achieved an appropriate balance between anchor stability and responsiveness.

使用标准 1–7 同意度量尺。

该题单独报告，不加入 CRIQ 或信任量表。

它对整篇论文很重要，因为 EgoAnchor 并不追求单独最小化时延，而是处理稳定性、连续性、转换和恢复之间的系统权衡。正文也明确要求时延和轨迹质量成对解释。

这一题可以揭示一种很有价值的结果：

* EgoAnchor 的稳定性、恢复信任评分更高；
* One-Euro 的即时响应感可能相近或更高；
* 但参与者仍认为 EgoAnchor 的总体权衡更合适。

这会与实验 1 的结果形成闭环。

---

# 七、两种方法完成后的最终问卷

两种方法全部完成后，参与者摘下头显，在平板或纸质问卷上完成最终比较。

## F1：实际选择

**条目 ID：`FINAL_METHOD_CHOICE`**

> 如果需要在实际混合现实应用中使用一个对象锚定方法，你会选择哪一种？

选项：

* 方法 A
* 方法 B
* 无明显偏好

这比问“哪一种更好”更具体，因为它对应实际使用意愿。

不要向参与者透露哪一个是 EgoAnchor。

---

## F2：感知差异

**条目 ID：`OPEN_DIFFERENCE`**

> 你认为两种锚定方法之间最明显的区别是什么？

用于识别：

* 微小抖动；
* 头动漂移；
* 运动打滑；
* 放下后的迟滞；
* 遮挡后跳变；
* 无明显差异。

---

## F3：信任破坏因素

**条目 ID：`OPEN_DISTRUST`**

> 在使用附着于真实物体的虚拟内容时，什么现象最容易使你不再信任这个锚点？

这是整个开放访谈中最有价值的问题。它能够让参与者自然指出什么运行时行为真正破坏信任，而不是只复述问卷中的术语。

---

# 八、完整流程中的填写时点

## 阶段 0：实验开始前

填写：

* 年龄；
* 性别；
* 主手；
* 正常或矫正视力；
* VR/MR 使用经验；
* 可选的当前不适程度。

这些是参与者信息，不属于实验 3 的因变量。

不要在实验前向参与者讲解：

* StaticLock；
* VCD；
* One-Euro；
* Kalman；
* 哪个条件是完整系统。

只说明：

> 你将体验两种不同的对象锚定方法，并评价虚拟内容与真实物体之间的空间关系。

这样可以减少需求特征。

---

## 阶段 1：训练

使用粉色耳机盒完成：

1. 静止观察；
2. 拿起放下；
3. 遮挡恢复；
4. 演示如何使用 1–7 评分。

训练数据不进入正式分析。

训练结束后只问：

> 是否理解任务和评分方式？

不填写正式量表。

---

## 阶段 2：方法 A、物体 1

### 任务顺序

1. 静止观察；
2. 拿起放下；
3. 遮挡恢复。

### 任务结束后

隐藏虚拟内容，出现三道物体级问题：

1. `OBJ_STATIC_STABILITY`
2. `OBJ_MOTION_ATTACHMENT`
3. `OBJ_RECOVERY_CONFIDENCE`

每题单独一页，选择后进入下一题。

填写时间约 20–30 秒。

---

## 阶段 3：方法 A、物体 2 和物体 3

重复完全相同流程。

三个物体结束后，进入方法 A 的方法级问卷。

---

## 阶段 4：方法 A 方法级问卷

填写顺序建议：

### 第一页：CRIQ

1. `CRIQ_PLAUSIBILITY`
2. `CRIQ_SYNCHRONY`
3. `CRIQ_RESPONSIVENESS`

### 第二页：锚点信任

4. `TRUST_POSITION`
5. `TRUST_AFTER_RECOVERY`
6. `TRUST_RELIANCE`

### 第三页：系统权衡

7. `STABILITY_RESPONSIVENESS_BALANCE`

总填写时间约 60–90 秒。

完成后：

* 摘下或抬起头显；
* 休息约 2 分钟；
* 不向参与者反馈其评分；
* 不讨论两种方法差异。

---

## 阶段 5：方法 B

完整重复：

* 三个物体；
* 每物体三个即时评分；
* 方法级七项问卷。

方法顺序在参与者之间平衡。

---

## 阶段 6：最终问卷

摘下头显后填写：

1. `FINAL_METHOD_CHOICE`
2. `OPEN_DIFFERENCE`
3. `OPEN_DISTRUST`
4. 可选的结束不适检查。

---

# 九、Unity 中如何呈现问卷

建议全部使用 head-locked UI，而不是把问卷附着在物体上。

## 物体级三项

界面标题：

> 请根据刚才操作的这个物体作答

界面显示：

```text
在静止观察阶段，虚拟内容在真实物体上的位置保持稳定。

1   2   3   4   5   6   7
完全不同意                 完全同意
```

要求：

* 每次只显示一个条目；
* 使用控制器射线选择；
* 选择后需要按“确认”；
* 不显示前一方法的回答；
* 不允许实验员代填；
* 不显示方法真实名称。

## 方法级问卷

界面标题：

> 请综合考虑刚才在三个物体上的全部体验

CRIQ 与同意度题使用不同的端点文字，避免评分语义混淆。

## 建议记录字段

```text
participant_id
method_id
method_order
object_id
object_order
questionnaire_level
item_id
response
timestamp
```

其中：

* 物体级条目记录具体 `object_id`；
* 方法级条目将 `object_id` 留空；
* 最终偏好单独记录。

即使不采集任务客观数据，也应记录：

* 当前方法；
* 当前物体；
* 任务是否正常完成；
* 是否发生系统崩溃或人工重初始化。

这些只是数据审计信息，不作为客观因变量。

---

# 十、最终分析和论文汇报

## 10.1 三个主要感知结果

正文优先报告：

1. 静止稳定性：`OBJ_STATIC_STABILITY`
2. 运动附着感：`OBJ_MOTION_ATTACHMENT`
3. 遮挡恢复可信度：`OBJ_RECOVERY_CONFIDENCE`

因为这三项一一对应三种标准化任务，也直接连接实验 1 的系统表征。

对每一项分析：

[

Rating \sim Method \times Object
]

重点报告：

* Method 主效应；
* 三个物体上的方向是否一致；
* Method × Object 仅作为探索性结果。

---

## 10.2 方法级结果

正文报告：

* CRIQ plausibility-illusion 平均分；
* Anchor Trust and Reliance 平均分；
* stability–responsiveness balance 单项；
* 最终方法选择。

对 CRIQ 和 Anchor Trust 报告内部一致性。

---

## 10.3 开放反馈

对两道开放题进行轻量主题分析。

建议预设初始编码框架：

* stationary jitter；
* viewpoint-dependent drift；
* motion lag；
* motion sliding；
* post-placement settling；
* recovery jump；
* wrong recovery；
* predictability；
* no noticeable difference。

同时允许出现新的归纳主题。

正文只报告最主要的 3–4 个主题和少量短引语，完整编码放补充材料。

---

# 十一、正文中建议展示的结果

## 图

一张四面板配对图：

* (a) Static stability
* (b) Motion attachment
* (c) Recovery confidence
* (d) Anchor trust

每位参与者显示配对点和连接线，不用柱状图。

三个物体的分项结果可使用：

* 小型 heatmap；
* 或 supplement 中的分面图。

## 表

| Measure                           | One-Euro | EgoAnchor | Effect | 95% CI | (p_{\mathrm{adj}}) |
| --------------------------------- | -------: | --------: | -----: | -----: | -----------------: |
| Static stability                  |          |           |        |        |                    |
| Motion attachment                 |          |           |        |        |                    |
| Recovery confidence               |          |           |        |        |                    |
| CRIQ plausibility                 |          |           |        |        |                    |
| Anchor trust                      |          |           |        |        |                    |
| Stability–responsiveness balance |          |           |        |        |                    |

最终方法选择用一句话报告：

> X/18 participants preferred EgoAnchor, Y/18 preferred One-Euro, and Z/18 reported no clear preference.

---

# 十二、最终量表清单

## 每个物体后，重复 6 次

1. **静止稳定性**
   在静止观察阶段，虚拟内容在真实物体上的位置保持稳定。
2. **运动附着感**
   在拿起、移动和旋转物体时，虚拟内容与真实物体保持一致运动。
3. **恢复可信度**
   遮挡移除后，虚拟内容恢复到了与真实物体一致的位置。

## 每种方法后，重复 2 次

4. **CRIQ 合理可信度**
   这种虚实交互体验在多大程度上让你觉得合理可信？
5. **CRIQ 同步性**
   你在多大程度上感觉真实物体与虚拟内容之间的交互是同步的？
6. **CRIQ 响应性**
   你在多大程度上感觉这一体验会响应你的操作？
7. **位置信任**
   我相信该方法显示的虚拟内容位于真实物体上的正确位置。
8. **恢复后信任**
   短暂遮挡后，我仍然相信恢复后的锚点位置是可靠的。
9. **依赖意愿**
   在需要虚拟内容准确附着于真实物体的混合现实应用中，我愿意依赖这种锚定方法。
10. **稳定—响应平衡**
    总体而言，该方法在锚点稳定性与响应及时性之间取得了合适的平衡。

## 全部实验结束后

11. 实际应用中会选择方法 A、方法 B，还是无明显偏好？
12. 两种方法最明显的区别是什么？
13. 什么现象最容易使你不再信任一个真实物体锚点？

这套结构已经足够支持实验 3。它不会把实验扩展成复杂的 HCI 量表研究，同时能够完整覆盖正文最重要的四个应用侧构念：**稳定、附着、恢复和信任**。
