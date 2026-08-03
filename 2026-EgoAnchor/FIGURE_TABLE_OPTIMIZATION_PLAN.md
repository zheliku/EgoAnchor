# EgoAnchor 图表优化计划

更新日期：2026-08-03

## 范围与边界

- 当前主稿是 `egoanchor_cn_v2.tex`，makefile 的 `SOURCE` 已指向该文件。
- v2 第 3 章由 Claude 重写，本轮不修改、回退或覆盖该章。
- 实验一/二使用正式 v4 分析结果。实验三工作簿的来源尚未人工确认，因此只完成绘图与产物契约，不把其数据图表复制进 v2。

## 统一视觉规范

- 双栏图原生宽度为 7.15 in，直接按最终物理尺寸导出。
- 基础字号为 7.4 pt，实验一/二子图标题为 7.2 pt 加粗。不用超过正文的大标题。
- 配色固定为 Arrival `#4C78A8`、Capture `#F28E2B`、One-Euro `#59A14F`、EgoAnchor `#E15759`。
- 分布图使用方法色边框、透明填充的箱线图：箱体表示 IQR，箱内横线表示中位数，彩色圆点表示均值，须线采用 1.5 倍 IQR 规则。原始样本用浅色小点，配对数据用浅灰线连接。
- 坐标轴使用近黑文字、浅色点状横网格，隐藏上、右边框。图例每张图只保留一份。
- PNG 以 300 dpi 导出，PDF 嵌入 TrueType 字体。正文图和独立审计子图由同一绘图实现生成。

## 实验一

### Figure 2：端到端系统行为

- 使用一张 `1 x 4` 双栏组合图 `figure2_exp1_behavior.{pdf,png}`。
- 四个面板依次为静止平移、静止旋转、动态平移和动态旋转。
- 各面板的误差与残差抖动单位相同，共用一个线性纵轴。不使用双 Y 轴或对数轴。
- 实线箱体与实心圆表示中心化 P95 或 lag-aligned RMSE，虚线箱体与空心菱形表示残差帧间增量 P95。两项指标均保留全部片段值，并在透明箱体上叠加均值点。
- 正文只引用组合 PDF。`figure2a`--`figure2d` 的 PNG/PDF 保留在子图目录，仅作审计。

### Table 1：系统行为合并表

- 静止、遮挡和动态指标合并为一张单栏表 `tables/exp1_performance.tex`。
- 方法作列，指标作行。方法表头 Arrival / Capture / One-Euro / EgoAnchor 保持单行。
- 不显示 `n=` 或 `[Q1,Q3]`。只对“静止帧间增量”和“当前时刻 RMSE”等长指标名换行。
- 使用 `\normalsize`、`\columnwidth` 和 booktabs；每行只加粗最优值。

## 实验二

### Figure 3：系统设计归因

- 使用一张 `1 x 4` 双栏组合图 `figure3_exp2_attribution.{pdf,png}`。
- 四个面板依次为 capture-time alignment、StaticLock、VCD risk-coverage 和 temporal strategy。
- Figure 3(d) 只显示 Smoothed KF Extrapolation 与 Linear/SLERP；Hermite 不进入正文图和 caption。
- 面板间距保持紧凑，子图标题单行显示。`figure3a`--`figure3d` 的独立资源只作审计。

### 归因表

- 实验二原归因表不进入 v2 正文。
- 采集时刻对齐、StaticLock、VCD 和时序策略的关键数值由 Figure 3 和结果文字承担。

## 实验三

### Figure 4：十二项主观结局复合图

- 只发布一张双栏宽的双排复合图 `figure4_exp3_subjective_outcomes.{pdf,png}`，全图共享一个方法图例。
- 上排 `(a)` 填满七个等宽槽，依次显示 `Stability / Attachment / Recovery / Reliance / Balance / Position / Orientation`，不显示不连续的问卷编号。内部仍以 Q1/Q2/Q3/Q6/Q7/Q8/Q9 作为稳定分析键，纵轴保留原始 1--7 分。
- 下排沿用上排的物理槽宽，五项已发表量表整体居中。左侧 `(b)` 三个槽展示 AQ-EQ、AQ-IQ 与 S-TIAS，共用 1--7 轴；右侧 `(c)` 两个槽展示 TiA R/C 与 TiA U/P，共用 1--5 右轴。两个量尺分区之间留窄缝，不归一化也不共用纵轴。
- 每项结局并列 One-Euro 和 EgoAnchor。One-Euro 使用绿色菱形，EgoAnchor 使用红色方形；固定左右位置、点形和箱体边框共同区分方法。
- 浅色点是参与者级得分，浅灰线连接同一参与者。透明箱体表示 IQR，箱内横线表示中位数，圆点表示均值，须线采用 1.5 倍 IQR 规则。
- 显著性括号按所属冻结家族分别计算：上排使用主证实家族的 Holm 校正结果，下排使用已发表量表家族的 Holm 校正结果。绘图入口必须从配对分重算精确 Wilcoxon 与 Holm。

### 完整结果表

- `tables/exp3_subjective.tex` 保留七个主结局和五个已发表量表结局，包括不显著项。
- 表中报告配对差中位数、家族内 Holm 校正 p 和 $r_{rb}$ [95% CI]；不再展开两方法的 `[Q1,Q3]`。
- 数据来源经研究团队人工确认前，该表与 Figure 4 都不进入 v2。

## 产物与实现契约

- 实验一/二组合图由 `experiment_1_2/analysis/figures.py` 生成，不恢复独立 `make_paper_figures.py`、`panels_v9` 或 LaTeX 拼图路线。
- 实验三图产物契约为 v7，只包含复合 Figure 4 的 PNG/PDF；旧 v4/v5/v6 构建清单均不兼容。
- 共享样式位于 `egoanchor.visuals/style.py`，必须同时纳入实验一/二和实验三的实现指纹。
- `analyze` 在 staging 目录生成全部产物并验证后，再以可回滚的整目录切换发布。

## 验收

1. 运行实验一/二和实验三的分析、绘图与资源契约测试。
2. 对修改的 Python 文件运行 mypy，再运行 `egoanchor.eval.tests` 全量测试。
3. 运行 `git diff --check`。
4. 使用 `latexmk -xelatex -synctex=1 -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v2.tex` 编译主稿。
5. 渲染含 Figure 2、Figure 3 和 Table 1 的页面，检查字号、重叠、边距、表格越界和浮动体空白。
6. 比对编译前后 v2 第 3 章的内容摘要，确认本轮没有覆盖 Claude 的修改。
