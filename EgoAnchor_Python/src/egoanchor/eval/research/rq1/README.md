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

默认报告目录为 `<session_id>/report`，论文图目录为 `2026-EgoAnchor-Typst/figs/rq1`。当前默认使用完整静止序列；需要显式稳态窗口时，通过绘图入口指定窗口，不要修改原始日志。
