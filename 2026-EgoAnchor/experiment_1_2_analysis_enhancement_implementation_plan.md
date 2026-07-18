# 实验一/二分析增强实施计划

## 1. 目的与适用范围

本计划承接 `experiment_1_2_analysis_rebuild_plan.md` 已完成的四阶段基线，并以
`experiment_1_2_analysis_enhancement.md` 的审阅意见为呈现依据。增强工作不改变原始
schema-v2 日志，不回写五个正式 task 目录，也不引入旧分析接口。

本轮只处理三件事：

1. 把实验一从“按已有指标罗列结果”改为面向 MR 锚点行为的系统表征。
2. 把实验二从“只报消融差值”改为完整系统、消融系统和同事件差值的机制归因。
3. 在 Stage 2 增加两个可审阅分析工作簿，方便以后替换正式 task 后按相同命令重跑。

实验一与实验二分别实现、验证、提交和推送。共享基础设施随实验一建立，实验二只在
已经冻结的边界内扩展，不提前混入实验二结果。

## 2. 不变边界

- Stage 1 `preprocess` 只读取 task 目录中的 JSON/JSONL，并发布逐 task 完整 XLSX。
- Stage 2 `analyze` 只读取 Stage 1 XLSX。CSV 与分析 XLSX 来自同一份已定稿表映射。
- Stage 3 `publish` 只读取 Stage 2 CSV。分析 XLSX 是审阅副本，不是后续阶段输入。
- Stage 4 `materialize-paper` 只读取 Stage 3 TeX 中间产物。
- 统计单位仍是 event/segment。frame 只形成事件内轨迹和描述性时间线。
- 五个场景分别报告，不计算跨场景总分、总排名或帧级显著性。
- 误差只表示同一 Quest 平台参考下的相对系统行为，不称外部物理真值。
- 正文、生成器和正式图统一使用 `2026-EgoAnchor/figures/`；不恢复 `figs/`。

## 3. 数据审计结论

五个正式工作簿分别对应一个场景和一条完成 trial。可用事件数为：静止头动 4 个、
起停 6DoF 5 个、持续平移 18 个、持续旋转 3 个、遮挡恢复 7 对。正文必须把这些数据
称为“单 session 长序列中的重复事件”，不能写成每个条件五次独立 trial。

当前 Stage 2 已有静止误差与 HP-RMS、起停响应与沉降、持续运动 effective lag 与
RMSE residual、遮挡误差与恢复、jump、display/output coverage 和 VCD risk-coverage。
现有工作簿还保留 head pose、source frame、anchor state、observation age 等字段，足以
生成描述性时间线和本计划新增指标，无需回读原始 JSONL。

以下限制不可通过离线推断补齐：

- 日志没有保存数值形式的 VCD runtime threshold，因此只能报告“实际接纳子集”工作点，
  不能把接纳样本的最低分反推为运行时阈值。
- Unity 与 Python 单调时钟不能相减，不能增加跨进程网络时延分解。
- head motion 与显示误差可作描述性同步轨迹，不能据此宣称因果泄漏系数。

## 4. 新增指标与冻结参数

所有新增数值参数写入 `analysis_params.toml`，每项保留同行中文注释，并递增参数与指标
契约版本。已有指标保留稳定键；新增量不能靠重命名覆盖旧公式。

| 指标 | 冻结定义 | 用途 |
|---|---|---|
| lag 补偿 P95 residual | 先按现有 0--500 ms、5 ms 步长和 RMSE 目标选择最优 lag；在同一重叠样本上取 residual 的 linear P95 | 实验一持续平移与旋转主质量量 |
| post-stop jitter RMS | 参考实际停止后跳过 1000 ms，在随后固定 3000 ms 公共窗口内，对 `display-reference` 三轴误差减去各轴中位数，再计算向量 RMS | 起停后的静止附着质量 |
| motion hold ratio | 只在同一参考运动窗口内统计连续有效 render pair；位置增量不高于 0.001 mm 且旋转增量不高于 0.001 deg 记为 hold；大时间间隙不跨越 | 时序合成是否退化为零阶保持 |
| reappearance P95 | 从 `target_visible` 开始的固定 1000 ms 公共窗口内计算平移误差 linear P95，不等待各变体自己的 fresh output | 重新可见后的应用可见误差 |
| occlusion output coverage | `occlusion_started` 到 `target_visible` 内 `has_output_pose` 的事件内比例 | 遮挡误差的可用性护栏 |

post-stop 窗口对所有系统使用相同参考时间，不以各系统自己的 settled 时刻起窗。motion
hold ratio 只作为 event-level 比例汇总；分母是合法连续 pair，不把 frame 当作独立样本。

## 5. 实验一：应用侧锚点行为

### 5.1 研究问题

实验一回答：EgoAnchor 在头动、对象运动、起停转换和短时视觉失效下，作为应用可消费的
MR 锚点表现如何？结果按世界一致性、静止稳定性、动态保真度和失效约束组织。

### 5.2 主表

主表固定为“行为属性 / 场景 / 指标 / 四个系统”结构，每个系统报告 event-level
median [Q1, Q3]。正文表只保留下列六行：

| 行 | 主指标 | 同行护栏或解释 |
|---|---|---|
| 世界一致性 | 静止头动平移 P95 | 旋转 P95 在正文叙述 |
| 静止稳定性 | 静止头动位置 HP-RMS | 绝对平移误差防止冻结错误位姿 |
| 状态转换 | visible response | post-stop jitter RMS 与 settling |
| 平移保真度 | lag 补偿平移 P95 | effective translation lag |
| 旋转保真度 | lag 补偿角 P95 | effective angular lag，并明确当前限制 |
| 失效约束 | 遮挡窗平移 P95 | occlusion output coverage 与 reappearance P95 |

原有 RMSE lag residual、raw zero-lag P95、jump P95/P99、fresh output 和 durable recovery
继续保留在分析 CSV/XLSX，用于审计或补充材料，不占正文主表行。

### 5.3 一张四面板系统行为图

图名固定为 `exp1_behavior_overview`。四个面板使用统一系统颜色，并以线型和标记重复编码，
保证灰度打印仍可区分。

| 面板 | 叙事任务 | 数据与编码 | 代表事件规则 | 主要注释与护栏 |
|---|---|---|---|---|
| A 头动世界一致性 | 对齐头动与显示误差 | 上轴为 head angular speed，下轴为 Arrival、Capture、EgoAnchor 平移误差时间线 | EgoAnchor 平移 P95 最接近四事件中位数的事件；并列取最早事件 | 标注该轨迹是描述性例子，统计结论来自全部 4 个事件 |
| B 起停行为 | 显示响应与停止后稳定 | 参考位移与四系统显示位移，背景标出参考运动窗和 post-stop 窗 | EgoAnchor 运动窗 P95 最接近五事件中位数的事件；并列取最早事件 | 标注 onset、stop、response 和固定 jitter 窗 |
| C lag--fidelity | 比较动态延迟与轨迹保真度 | 横轴 effective lag，纵轴 lag 补偿 P95；显示 18 个事件点及各系统 median/IQR | 不选代表事件，保留全部 segment | 位置为共同尺度，标题直接说明时延与残差权衡 |
| D 遮挡约束 | 展示遮挡期错误是否被限制 | 四系统平移误差时间线，遮挡区间着色，额外标出 output unavailable | EgoAnchor 遮挡 P95 最接近七事件中位数的事件；并列取最早事件 | display hold 与 output availability 使用不同线型，不把 held display 称为新输出 |

Stage 2 为四个面板发布专用 plot-ready CSV。Stage 3 不重新联接 reference、切窗、选择
代表事件或计算指标，只把 CSV 编码为 PDF/PNG。

### 5.4 结果写法

每段按“回答问题、主结果、机制解释、代价或限制、证据范围”组织。持续旋转若没有优势，
直接作为当前限制报告。视觉推理时延、候选到达时延、更新间隔、capture-to-display age 和
初始化时间必须分开称呼，不能用一个端到端时延数字替代。

## 6. 实验二：机制归因

### 6.1 研究问题与场景边界

实验二回答：哪个 runtime 机制解释了实验一观察到的应用侧行为？四个组件仍按正式采集
设计映射到冻结场景：

| 组件 | 冻结场景 | 主指标 | 护栏 |
|---|---|---|---|
| capture-time alignment | 静止头动 | 平移 P95 | 旋转 P95 |
| StaticLock | 静止头动 | 位置 HP-RMS | 绝对平移误差 |
| temporal synthesis | 起停 6DoF | motion hold ratio | 运动窗 P95、visible response、post-stop jitter |
| VCD admission | 遮挡恢复 | 遮挡窗平移 P95 | occlusion output coverage、实际接纳子集工作点 |

增强建议曾提出把 temporal synthesis 主归因移到持续平移，但这与 `AGENTS.md`、冻结组件
契约和正式采集设计冲突。本轮不做采集后场景迁移。持续平移的完整系统与四基线比较归入
实验一；实验二的时序合成归因继续使用起停 6DoF。

### 6.2 主表与图

实验二主表每个组件一行，固定列为：组件、场景、主指标、Full median [IQR]、Ablated
median [IQR]、配对差值 median [IQR]、方向计数、护栏。差值仍定义为消融减完整系统。

主图固定为 `exp2_mechanism_attribution`：四个小面板分别显示四个组件的同事件 Full 与
Ablated 配对点，灰线连接同一事件。VCD 面板包含 candidate risk-coverage inset，并用独立
符号标出“实际接纳 eligible 子集”的 coverage 和 tail risk；该点不标成数值阈值。

不做 frame-level 显著性检验。正文报告 median [IQR]、配对方向计数和全部配对点；若后续
加入 event bootstrap，只能称序列内事件变异性，不能解释为跨 session 或跨操作者置信区间。

## 7. Stage 2 分析工作簿

`analyze --out <results>` 在同一个 staging 根目录原子发布 CSV 与两个文件：

- `exp1_analysis.xlsx`
- `exp2_analysis.xlsx`

两个工作簿都含 `workbook_info`、`sheet_index`、`inputs`、`analysis_qc`、相关指标目录和
过滤后的 lineage。实验一工作簿收录四层指标、场景汇总、plot-ready 数据和论文投影；
实验二工作簿收录四层指标、配对差值与汇总、VCD 诊断、plot-ready 数据和论文投影。

工作簿不复制完整 frame/candidate 长表，不包含 Excel 内二次科学计算。数值单元格保持
数值类型，缺失值留空，文本防公式注入；表头冻结并启用筛选。XLSX core properties、ZIP
条目顺序和时间戳固定，相同 CSV 表和配置必须产生相同二进制 SHA-256。

任一 CSV 或分析 XLSX 写入、回读、hash、表头、行数或实验过滤检查失败时，整个 Stage 2
返回退出码 2 且不替换旧结果目录。文件系统缺源或写盘失败返回退出码 1。

## 8. 实施顺序

### Task E1：实验一增强

1. 运行 `git status` 和 `rg`，确认影响范围与未提交改动。
2. 先补指标、参数、plot-ready CSV、分析 XLSX、发布图、TeX 和主稿物化测试。
3. 实现新增实验一指标和四面板图数据，不改实验二组件映射。
4. 建立 Stage 2 同源 CSV/XLSX 原子发布基础设施，并只启用 `exp1_analysis.xlsx` 的实验一内容。
5. 重写实验一主表、图注和结果段；用 humanizer-zh 检查表述。
6. 用 Code Simplifier 对本 Task 新增/修改代码做保行为审查。
7. 运行定向测试、全量单测、compileall、mypy、完整四阶段命令和 XeLaTeX。
8. 独立提交并推送，提交信息使用 `Experiment 1: 强化系统行为分析与呈现`。

### Task E2：实验二增强

1. 重新运行 `git status` 和 `rg`。
2. 先补 Full/Ablated/Delta 汇总、实际接纳子集工作点、配对图和实验二工作簿测试。
3. 扩展实验二 CSV、`exp2_analysis.xlsx`、主表和机制归因图，不改变冻结适用场景。
4. 重写实验二结果段，明确收益、代价、空结果和数据范围。
5. 用 humanizer-zh 与 Code Simplifier 分别审查文本和代码。
6. 运行定向测试、全量单测、compileall、mypy、完整四阶段命令和 XeLaTeX。
7. 检查主稿不含活动 `figs/` 引用，PDF 无空图、裁切、重叠和不可读标签。
8. 独立提交并推送，提交信息使用 `Experiment 2: 强化组件归因分析与呈现`。

## 9. 复现与验收

正式命令仍从 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python -m egoanchor.eval.cli qc <五个task目录>
pixi run python -m egoanchor.eval.cli preprocess <五个task目录> --out data/analysis/complete --code-version <commit>
pixi run python -m egoanchor.eval.cli analyze <五个complete.xlsx> --out data/analysis/results --code-version <commit>
pixi run python -m egoanchor.eval.cli publish data/analysis/results --paper-root ../2026-EgoAnchor
pixi run python -m egoanchor.eval.cli materialize-paper --paper-root ../2026-EgoAnchor
```

程序验证：

```powershell
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src
pixi run mypy src/egoanchor/eval
```

论文验证：

```powershell
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
```

每个实验 Task 的最终验收必须同时给出：新增/保留的指标、CSV 与分析 XLSX hash、图和 TeX
hash、主稿编译页数、测试结果、提交 hash 和推送结果。两次完整重跑还要证明科学 CSV、
分析 XLSX、PDF/PNG、TeX 和主稿受控区块均可确定性重建。
