# EgoAnchor 评估输出脚本同步规范

本轮附件中未包含项目的 `paper.py` 或 Figure 6 绘图脚本，因此没有对不存在的源文件做猜测性修改。
请在项目脚本中同步以下“输出契约”，避免下一次自动生成覆盖论文中的定稿表格。

## 1. 实验一表格生成

输出三个单栏表，均使用模板默认字号，不使用 `\small`、`\footnotesize`、`\scriptsize` 或 `\resizebox`。

- `tables/exp1_static.tex`
  - 指标：头动泄漏 P95、绝对注册 P95、静止抖动 P95
  - 单元格：平移 / 旋转中位数
- `tables/exp1_dynamic.tex`
  - 指标：有效时延、时延对齐 RMSE、当前时刻 RMSE、残余抖动 P95
  - 单元格：平移 / 旋转中位数
- `tables/exp1_recovery.tex`
  - 指标：遮挡误差 P95（平移 / 旋转）、起动转换时延

列名中使用 `\downarrow` 标记越低越好；粗体仅标每个通道的最优中位数。

## 2. 实验三表格生成 (`paper.py`)

目标输出为五列：

`结局 | Mdn↑ (One-Euro / EgoAnchor) | W | p_adj | r_rb [95% CI]`

要求：
- 保留 `W`、Holm 校正后的 `p_adj` 和 `r_rb`；
- 不在主表逐行输出非零差 `n`；
- 不改变论文模板字号；
- 不输出 McDonald's omega；
- 按四组插入分组行：
  1. 阶段性锚点质量：静止稳定、运动附着、姿态一致、恢复一致
  2. 整体锚定判断：位置正确、依赖意愿、稳定--响应平衡
  3. 增强质量：AQ-EQ、AQ-IQ
  4. 信任：TiA R/C、TiA U/P、S-TIAS
- 全部 24 组完整配对与零差处理规则只在 caption 中说明一次；
- TiA 可靠性/能力的 `r_rb=1.00` 使用 dagger 标记，不伪造 bootstrap CI。

## 3. 用户研究图（Figure 6）建议重排

当前七个对象锚定条目集中在同一面板，视觉密度较高。建议绘图脚本改为四个逻辑面板：

- (a) 阶段性锚点质量：Stability / Attachment / Orientation / Recovery
- (b) 整体锚定判断：Position / Reliance / Balance
- (c) 七点评分的已发表量表：AQ-EQ / AQ-IQ / S-TIAS
- (d) 五点评分 TiA：R/C / U/P

建议布局为 2×2 或上 2 下 2 的紧凑排布；四个面板继续使用参与者内连线、IQR、median 和 Holm 校正显著性。
不要把不同量尺（TiA 1--5 与其余 1--7）强行放在同一纵轴。

完成重绘后，应同步更新主稿 Figure 6 caption；本轮主稿仍保留当前图的 caption，以免在绘图脚本尚未更新时出现图文不一致。
