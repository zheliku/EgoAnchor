# RQ2 重构设计：从"单一主终点"到"四轴权衡刻画"

日期：2026-07-12
主题：推翻旧 RQ2 的"误差容限内有效追踪率作为唯一主终点"框架，改为诚实刻画完整锚定策略相对零阶保持参照的多轴权衡，并以实时轨迹图（realtime trajectory）作为主图承载机制证据。

> 本设计取代 `2026-07-10-rq2-dynamic-tracking-design.md`。旧 spec 保留原"主终点判优"定位，与本次方向冲突，不再参考。

## 一、问题诊断（为什么推翻旧设计）

旧 RQ2 把"当前时刻误差容限内有效追踪率"（`within_tolerance_valid_tracking_rate`）设为唯一主终点。这一选择存在结构性缺陷：

1. **指标对平滑策略系统性不利。** 任何插值/平滑策略以延迟换平滑；*Full* 用 `DelayedInterpStrategy` 输出约 290 ms 前的历史目标时刻位姿，*Raw-ZOH* 只保持最近一次观测（约 223 ms 前）。运动中延迟越大、当前时刻误差越大，因此在"瞬时精度"轴上延迟更小的 ZOH 必然占优。这是指标定义的同义反复，不是关于 EgoAnchor 的发现。
2. **基线方向选反。** *Raw-ZOH* 不加额外延迟，在当前时刻精度上恰是更难打败的一方；把它当作"要被打败的朴素基线"，方向错误。
3. **快速运动下指标饱和。** 快速运动两配置均崩（约 8% vs 11%），指标落在"都失败"区间，无法区分方法价值；此时 RQ2 实际测量的是约 8 Hz 稀疏感知率加处理时延，而非锚定策略。
4. **聚合柱状图隐藏机制。** 现有柱状图把时间行为压成单个 P95 / 率，恰好藏起真正的差异：*Full* 是约 60 Hz 平滑连续曲线，*Raw-ZOH* 是约 8 Hz 阶梯跳变（约 86% 帧为 hold-last）。

**先导数据的双重性质**：每类运动仅一个长 trial，对聚合统计是缺陷（不能算置信区间），但对实时轨迹图恰是优势——需要的正是一段连续轨迹展示阶梯 vs 平滑。因此复用现有先导数据 `20260712_163657_controller_right`，不重新采集。

## 二、新的核心主张（claim）

RQ2 不再评判"谁赢"，而是**刻画完整锚定策略相对零阶保持的四轴权衡**：

> 完整锚定策略以约 66 ms 的额外目标延迟和快速运动下的当前时刻误差，换取约 8× 的显示连续性提升与近乎消除的运动 judder；何者更优取决于任务，由 RQ3 用户研究检验。

这把 RQ2 → RQ3 串成一条线：RQ2 客观刻画权衡，RQ3 主观检验偏好。定位符合 UIST / CHI / IEEE VR 对诚实 trade-off characterization 的偏好。

## 二·五、Baseline 框架与论文术语（正文与内部标签解耦）

**被比较的对象只有两个方法，外加一条真值标尺。** Quest 手柄平台位姿是参考真值（标尺），不是第三个竞争系统。Hero 图语义为 1 条真值线 + 2 条方法线 + 稀疏感知观测点：

- **参考真值** — Quest 手柄平台参考位姿（标尺，非竞争者）
- **完整锚定** — 我们的完整策略（平滑连续、略滞后）
- **零阶保持（ZOH）** — 剥离运动估计/平滑/静止锚定后的同一系统（阶梯跳变）
- **时空对齐感知观测** — 约 8 Hz 稀疏观测点；ZOH 阶梯线正是把这些点保持到下次更新得到的（同源）

**内部标签与正文术语解耦。** 先导数据 manifest 的 `variant_labels=["Full","Raw-ZOH"]`、`config_hash`、代码内部标签一律**不改**（改了读不到数据）。仅在 `paper.py` 导出与正文层做术语映射：

| 内部代号（不改） | 论文正文规范术语 |
|---|---|
| `Full` | *完整锚定*（完整锚定策略）——不直接叫 EgoAnchor，因 ZOH 是剥离策略后的同一系统，一个系统配置 |
| `Raw-ZOH` | 首次出现：*零阶保持*（Zero-Order Hold, ZOH）；此后：*ZOH* |
| aligned raw / raw 误差 / raw source | *时空对齐感知观测* / 感知观测误差 / 感知观测产出率 |

**"时空对齐"是唯一正式对齐术语。** 正文不再单造"帧对齐"一词；需强调"基于帧标识校正相机运动错配"这一子机制时，写成"基于帧标识的时空对齐"。删除正文中所有裸 "raw"、`*Frame-aligned*` / `*Arrival-aligned*` 斜体变体标签（后者仅作诊断，不进正文主叙事）。

**论文起点确认**：revert 回 HEAD 后，§RQ2 是一份预注册报告结构（占位图、无数值、含 `*Raw-ZOH*` 与 `*Frame-aligned*` 旧术语），不是带 `#rq2-*` 数值变量的未提交稿。改写以 HEAD 版为起点，填入先导数值并统一术语。

## 三、四轴指标

刻画权衡需要一个 *Full* 明确占优的维度，否则叙事沦为"我们输了但图好看"。四轴各有占优方，互补覆盖：

| 轴 | 指标 | 占优方 | 现状 |
|---|---|---|---|
| **连续性**（Full 占优） | 显示更新率 Hz、hold-last 帧占比、生命周期状态占比 | *Full* ~60 Hz vs *Raw* ~8 Hz；hold 帧 3–26% vs 86% | 已有 |
| **平滑度 / judder**（Full 占优，新增） | **SPARC**（谱弧长，Balasubramanian 2015）为主 + jerk RMS 为直觉辅助 | *Raw-ZOH* 阶梯跳变 → 平滑度极差 | **需新增** |
| **延迟**（Full 付出） | 中位目标延迟、经验响应滞后（互相关，当前 NaN 保留） | *Full* +66 ms | 已有 |
| **当前时刻精度**（Raw 占优，降级为一轴） | 平移/旋转 P95、容限内追踪率 | 快速运动两者都崩；慢速 Raw 略优 | 已有，降级 |

平滑度轴是权衡叙事的正面支柱：judder 破坏 presence，是 *Full* 唯一悬殊占优且感知上高度显著的维度。选 **SPARC** 而非裸 jerk，因其无量纲、抗噪、可引用，更稳健；jerk RMS 仅作直觉辅助同时报告。

**降级而非删除 `within_tolerance_valid_tracking_rate`**：保留计算，定位从"唯一主终点"改为"精度轴的一个指标"。契约层依赖它，降级使代码 churn 最小。

## 四、实时轨迹 Hero 图（替换柱状图为主图）

三面板堆叠，每块承载一类机制证据：

```
(a) 位置分量–t（慢速平移 trial）
    — 参考真值（实线，Quest 手柄平台位姿，标尺）
    — 完整锚定（平滑曲线，略滞后）
    ┅ 零阶保持 ZOH（约 8 Hz 阶梯跳变）
    •  时空对齐感知观测点（约 8 Hz，ZOH 阶梯线的同源来源）
    [放大 inset：阶梯 vs 平滑局部对比]

(b) 旋转角–t（旋转 trial）
    同层：参考真值 / 完整锚定 / ZOH / 感知观测点

(c) 速度或 jerk–t
    完整锚定平滑 vs ZOH 尖峰，把 (a)(b) 的定性差异量化为 judder
```

一眼看清：*ZOH* 阶梯、*完整锚定* 平滑连续；同时**诚实暴露完整锚定的相位滞后**（不藏）。这是聚合柱状图无法提供的机制证据，也是 hero 图的核心价值。

**数据字段确认**（均按 `render_mono_ms` 打时间戳，schema 齐全；内部字段名不改，只在正文/图注映射术语）：
- `variants[].display_pos/display_rot`：完整锚定 / ZOH 的实际显示轨迹
- `variants[0].aligned_raw_pos/aligned_raw_rot`：主变体时空对齐感知观测（约 8 Hz）
- `gt_pos/gt_rot`、`gt_pose_fresh`：动态参考真值
- `gt_linear_speed_m_s/gt_angular_speed_deg_s`、`anchor_state`：速度与生命周期叠加

## 五、保留的辅助图 / 表

- **四轴权衡汇总表**：替代旧"主终点"表述，一表统览连续性 / 平滑度 / 延迟 / 精度四轴。
- **目标时刻诊断**：保留，证明 *Full* 精确重建了延迟轨迹、只是滞后（低速平移 6.9 mm、快速 16.9 mm 中位）。
- **经验运行包络**：降为报告 / 附录级，不进正文推断。
- **`_preliminary` 标识**：全部保留，单会话不给置信区间。

## 六、代码改动范围（最小化）

新增：
- `EgoAnchor_Python/src/egoanchor/eval/research/rq2/smoothness.py`：SPARC + jerk RMS，作用于 `display_pos/rot` 与 `aligned_raw` 轨迹，按 `condition × label` 聚合。
- `rq2/plot.py` 新增实时轨迹 hero 图函数（三面板 a/b/c，含 inset）。

修改：
- `rq2/pipeline.py`：挂接 smoothness 计算与 hero 图导出。
- `rq2/paper.py`：导出新指标（SPARC、jerk、四轴汇总）到 `generated/rq2_results.typ`。
- `rq2/__init__.py`：re-export smoothness 包级 API。
- `AGENTS.md` RQ2 段：把"主终点"改为"四轴权衡"，记录 SPARC 新指标与 hero 图。
- `2026-EgoAnchor-Typst/egoanchor_cn_v6.typ`：§动态实验设计 + §RQ2 结果两段重写。

保留不动：
- 契约层（Unity `EvalRecorder`/`EvalJson`/`EvalSession` ↔ Python `eval/io`）。
- `trajectory.py` / `source.py` / `lag.py` / `qc.py` / `contract.py` / `model.py` / `paired.py`。
- 先导数据 `data/eval/rq2_data`（gitignore 保护，绝不删）。

## 七、论文正文重写

- **§RQ2 研究问题**：主张从"当前时刻配准质量随运动变化 + 权衡"细化为明确的四轴权衡刻画，加 RQ2 → RQ3 桥接句。
- **§动态实验设计**：把"误差容限内有效追踪率为主终点"改为"四轴权衡刻画"；说明先导数据用于机制展示而非总体推断。
- **§RQ2 结果**：以 hero 图导读为主线，四轴顺序叙述（连续性 → 平滑度 → 延迟 → 精度），删除"主终点失败"负面框架。
- **篇幅控制**：行文精炼、高度学术化，为其他章节留版面。
- **术语**：配置用斜体 *Full* / *Raw-ZOH*；用"系统配置/变体"，不用"条件"。

## 八、执行顺序（含破坏性 git 操作）

1. 写完本 design doc（当前步骤）→ 提交。
2. **外科手术式清理上一版 RQ2 工作**（不用宽范围 `git clean -fd`，它会误删 Blender/data/docs 等无关目录）：
   - `git checkout` 恢复上一版改动的 tracked 文件（typ / AGENTS.md / rq2 各 .py / README / 字体 asset）。
   - 逐个删除上一版新增的 untracked RQ2 文件（`paper.py` / `screen.py` / `screening.py` / `figs/rq2/` / `generated/` / `Rq2BlendPilotSceneTests.cs`）。
   - 先导数据、Blender、data、docs 等无关未跟踪内容一律保留。
3. 按新 spec 重新实现代码 → 分析数据 → 改论文。

## 九、验证

- Python 全量单测：`pixi run python -m unittest discover -s src -p "test_*.py" -t src`（`KMP_DUPLICATE_LIB_OK=TRUE`）。
- 新增 `smoothness.py` 单测：SPARC 对阶梯 vs 平滑信号的区分、jerk RMS、退化输入返回 NaN。
- RQ2 分析 CLI 复跑：`pixi run python -m egoanchor.eval.research.rq2.analyze --session-dir data/eval/rq2_data`。
- Typst 编译：`typst compile --root . 2026-EgoAnchor-Typst/egoanchor_cn_v6.typ 2026-EgoAnchor-Typst/pdf/egoanchor_cn_v6.pdf`。

## 十、开放风险

- **单会话上限**：hero 图强、聚合弱；正文必须始终以 `_preliminary` 呈现，不写总体结论。审稿人可能仍要求正式采集——本设计把叙事重心放在机制展示，降低对样本量的依赖，但不能完全消除该风险。
- **SPARC 参数**：谱弧长对截止频率与幅度阈值敏感，需在单测中固定参数并在图注 / 正文说明取值来源。
- **RQ2 → RQ3 桥接**：主张成立依赖 RQ3 后续检验主观偏好；若 RQ3 未落地，RQ2 结论停在"刻画权衡"，不预写偏好结论。
