# EgoAnchor figures/tables redraw v2

本版本用于视觉审阅，尚未自动回填论文正文。

## Figure 1: Experiment 1
- 误差棒仍表示事件级 IQR。
- 每个方法叠加真实事件散点：静止头动 4 个事件、持续平移 18 个事件、遮挡 7 个 episode。
- 持续平移面板同时展示 effective lag 与 lag-aligned translation RMSE，左下更好。

## Figure 2: Experiment 2
- 不再使用难以理解的 `ablated - full` 单点差值图。
- Capture alignment、StaticLock、VCD 使用 full-vs-ablated 的逐事件配对线。
- Temporal synthesis 使用 lag-RMSE 二维配对图，直接显示“降低时延但增大轨迹残差”的代价。

## Tables
- 方法/变体作为行，指标作为列。
- 指标名使用下降箭头表示越小越好。
- 每列数值最优项加粗。
- 主表只放事件级中位数；IQR 和逐事件分布由图及补充材料承担，以控制正文宽度。

## Data handling
原始 25-39 MB XLSX 通过 ZIP/XML 流式读取，只提取分析所需列，没有整表载入内存。
