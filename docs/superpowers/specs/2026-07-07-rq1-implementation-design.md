# RQ1 实现设计

日期：2026-07-07
主题：RQ1「静态锚定质量」采集脚本、分析脚本与论文更新

## 目标

按 2026-07-07 定稿的 RQ 结构实现 RQ1（静态锚定质量）的完整评估链路：

- **RQ1 只评估静止场景**：长时静止观察、遮挡恢复。
- **消融**：*Full*（含静止锚定）vs *No-StaticLock*（关静止锚定），仅在静止观察场景下对比。
- 慢速平移 / 快速挥动 / 旋转已移交 RQ2，不在 RQ1 采集。

产出三块：Unity 采集脚本 + 实时面板、Python 分析脚本、采集后论文更新与绘图。

## 背景约束（不可回退）

契约层（Unity `EvalRecorder`/`EvalJson`/`EvalSession`/`EvalLog` ↔ Python `eval/io`）与共享分析引擎（`eval/core/run_eval.py` + `eval/metrics` + `eval/report`）已通过测试、能干净录制 13k 帧，且编码了三个已修复的历史坑：帧对齐（`frame_id → capture-time pose`）、GT keep-alive（手柄 sleep 复用上次有效 pose）、时延补偿对齐。**保留不改**。

已废弃的 `eval/research/rq1/*`（`data_loader`/`gt_alignment`/`metrics`/`plot_*`/`run_analysis`/`run_rq1`）是对共享引擎的**重复造轮子**，是本次要清除的陈旧层。

## 范围

### 删除（陈旧层）

- Python：整个 `EgoAnchor_Python/src/egoanchor/eval/research/rq1/` 下除 `__init__.py` 外的旧实现文件（`data_loader.py`、`gt_alignment.py`、`metrics.py`、`plot_compact.py`、`plot_comprehensive.py`、`run_analysis.py`、`run_rq1.py`）及其 `__pycache__`。
- 根散落文档（违反 CLAUDE.md #2）：`EgoAnchor_Python/RQ1_ANALYSIS_DESIGN.md`、`RQ1_COMPLETE_REPORT.md`、`RQ1_PAPER_UPDATE.md`、`analyze_rq1_data_quality.py`。
- 旧图（旧数据、旧 5 场景）：`2026-EgoAnchor-Typst/figs/rq1/fig_rq1_compact.{pdf,png}`、`fig_rq1_comprehensive.{pdf,png}`。

### 保留不动

- 契约层全部。
- 共享引擎 `eval/core`/`eval/metrics`/`eval/report`/`eval/io`。
- Unity `RQ1LiveStats`（实时性遥测面板，新代码）、`RQ1StatusUI`（录制/标注状态）、`RQ1MetricSelector`、`RQ1InputHandler`、`EvalSession` 会话边界事件机制。

### 改造（语义对齐 07-07 拆分）

- **Unity `RQ1MetricType`**：5 场景 → 2 场景。
  - `None = 0`
  - `StaticObservation = 1`（静止观察，长时静置桌面 + 正常头动）
  - `OcclusionRecovery = 2`（遮挡恢复）
  - 删除 `SlowTranslation`/`FastMotion`/`Rotation`（移交 RQ2）。
  - 同步 `ToLogString`/`GetDisplayName`/`GetDescription`/`GetSuggestedDuration`。
- **Unity `RQ1InputHandler`**：按键收窄——1=静止观察、2=遮挡恢复、0=清除、F7=开始、F8=停止。删除 3/4/5 的 action 字段与回调。
- **Unity `RQ1StatusUI`**：按键对照表只列 2 场景。
- **Unity 场景 `EgoAnchor-RQ1.unity`**：新增第二个 `PoseToAnchorRuntime`（baseline），配置与 Full 完全相同（同 motion model × smoothing strategy），仅关闭 `EgoAnchorStaticLockModule`（`lockEnabled=false` 或不挂模块）。接入 `EvalRecorder.variants[1]`，`label="No-StaticLock"`；Full 为 `variants[0]`、`isPrimary=true`、`label="Full"`。

### 新建

- **Python `eval/research/rq1/analyze.py`**：薄封装脚本，不重算任何指标。
  - `load_session` 加载 → `compute_all_metrics`（共享引擎）→ 从结果 tables 中筛 RQ1 关注的 `condition ∈ {static_observation, occlusion_recovery}` × `label ∈ {Full, No-StaticLock}` 切片 → 复用 `eval/report` 出 CSV/表/图。
  - 精度、抖动（`jitter_summary`）、屏幕漂移（`slip_summary`）、恢复时间（`recovery_summary`）、时延（`latency_summary`）全部取自共享引擎产出，不复制计算逻辑。
  - 提供 CLI：`--session-dir`，产出写 session `report/`，RQ1 论文图另存 `2026-EgoAnchor-Typst/figs/rq1/`。
  - 为 RQ2/RQ3 铺路：analyze 只做「场景过滤 + 论文视图组织」，通用能力留在 `eval/core|metrics|report`，RQ2/RQ3 各自建同构薄封装即可复用。

## 关键设计点

### 消融同步性

两个 runtime 订阅同一 pose 流，同一渲染 tick 写进同一 `unity_output` 行的 `variants` 数组。Python 侧 `label_conditions` 用 `rq1_metric` 做 `condition`，`groupby(["condition","label"])` 天然产出 Full vs No-StaticLock 逐场景对比。无需任何时间对齐——同帧同源。

### 遮挡恢复的事件标记（真实缺口，必须处理）

`compute_recovery` 依赖 `manifest.event_markers`（含 `mono_ms`），但当前 `EvalJson.BuildManifest` 恒写 `event_markers: []`。为让遮挡恢复恢复时间可算，采用：

- **方案（选定）**：analyze.py 从 `rq1_metric == "occlusion_recovery"` 段的**起始时刻**在内存里合成 event marker（每个连续 occlusion_recovery 段一个 marker，`mono_ms` = 段首 `render_mono_ms`），构造临时 manifest 传给 `compute_recovery`。这样无需改契约层 Unity 代码，遮挡事件由用户按键 2 的时刻界定。
- 恢复时间 = 段内锚点平移误差首次持续（hold 200ms）低于阈值（默认 0.05m）的时刻减去段首时刻。

> 备选（不选）：改 Unity 写真实 event marker。会动契约层且需要额外的「遮挡开始」输入信号，超出本次范围。

### 数据过滤

沿用共享引擎既有约定：`valid = gt_pose_valid & has_output_pose`；接受 Coasting/FrozenUncertain 状态（追踪连续性设计的一部分）；jitter 只在 GT 低速窗口（默认 0.03 m/s）内算。不引入新的速度启发式剔除（会和 GT keep-alive 打架）。

## 采集工作流（用户执行）

1. 启动 Python server（`eval_session_enabled=true`，`--object controller_right`）。
2. Unity 进入 `EgoAnchor-RQ1.unity`，`autoStart` 收到首个 PoseResult 自动开始录制并复用 Python session_id。
3. 用户按 **1** 标注静止观察段（控制器静置、正常头动，约 60–80s），期间实时面板显示时延/误差/抖动/状态。
4. 用户按 **2** 标注遮挡恢复段：按 2 后用手遮挡目标再移开，重复若干次。
5. F8 停止，写 manifest。数据落 `EgoAnchor_Python/data/eval/<session_id>/`。

## 分析工作流（采集后）

```powershell
cd EgoAnchor_Python
pixi run python -m egoanchor.eval.research.rq1.analyze --session-dir data/eval/<session_id>
```

产出：session `report/` 下 CSV/summary + `figs/rq1/` 下论文图。

## 论文更新（拿到实测数据后）

- §6.1 RQ1 结果（`egoanchor_cn_v5.typ` 第 337–357 行）：用实测值替换 X/Y/Z/W 占位符（精度中位数/P95、抖动 RMS、屏幕漂移、恢复时间、Full vs No-StaticLock 对比）。
- `<fig:rq1-static>` placeholder → 真实图：(A) 长期稳定性误差时间线、(B) Full vs No-StaticLock 抖动+屏幕漂移对比、(C) 遮挡恢复误差曲线。
- 本机 `typst compile --root . 2026-EgoAnchor-Typst/egoanchor_cn_v5.typ ...` 编译验证通过。

## 验证策略

- Unity：`dotnet build EgoAnchor_Unity\Assembly-CSharp.csproj --no-restore` 编译通过；用 Unity MCP 检查 `EgoAnchor-RQ1.unity` 两个 runtime + recorder variants 接线；进入 Play 观察实时面板与双变体输出。
- Python：`pixi run python -m compileall src`；`pixi run python -m unittest discover -s src -p "test_*.py" -t src`（含 eval 测试）；用现有 `20260706_163825` session（若含 static/occlusion 段）跑 analyze 冒烟。
- 采集后：analyze 全链路跑通 + typst 编译。

## RQ2/RQ3 铺路

- 场景标签、双变体、时延补偿、slip、recovery、latency 全在共享引擎，RQ2/RQ3 直接复用。
- RQ2 已有 `rq2_alignment_ablation_*` 表（时空对齐消融）在引擎内产出，RQ2 薄封装可直接取用。
- 每个 RQ 一个 `eval/research/rqN/analyze.py` 薄封装，只做该 RQ 的场景过滤与论文视图组织，模式统一。
