# RQ1 分析入口

原始日志位于 `EgoAnchor_Python/data/eval/<session_id>/`。RQ1 采集按键、遮挡恢复标记规则和面板字段说明见：

```text
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/README.md
```

在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python -m egoanchor.eval.research.rq1.analyze `
  --session-dir data/eval/<session_id>
```

默认报告目录为 `<session_id>/report`，论文图目录为 `2026-EgoAnchor/figs/rq1`。论文图从 `static_observation` 中选择首个 *Full* 已锁定、两变体与平台参考均有效的连续 180 个 Unity 渲染帧；该规则不读取误差大小。位置与旋转分别输出三轴时间线，遮挡恢复只保留总体指标，不单独绘图。
