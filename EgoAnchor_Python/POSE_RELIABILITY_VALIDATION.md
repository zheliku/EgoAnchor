# Python pose 可靠性评分验证指南

本文档说明如何验证 Python 端 pose 可靠性链路：渲染质量检测、几何合取评分、runtime JSONL 诊断，以及离线分布统计。机制细节见 [`POSE_SCORING_MECHANISM.md`](POSE_SCORING_MECHANISM.md)。

## 1. 先跑自动验证

在 `EgoAnchor_Python` 目录执行：

```powershell
pixi run python -m compileall src eval
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python -m unittest discover -s eval -p "test_*.py"
```

重点测试文件：

- `src/egoanchor/tests/test_render_quality.py`：验证重投影颜色分、深度对齐分和渲染质量字段。
- `src/egoanchor/tests/test_pose_quality.py`：验证 `reliability_score` 随 reprojection、depth、mask 和 confidence 变化。
- `src/egoanchor/tests/test_runtime_event_logger.py`：验证 JSONL 中写入 pose score 和渲染质量旁路字段。
- `eval/tests/test_diagnostics.py`：验证离线诊断统计。

## 2. 默认基线运行

当前默认配置会开启 `[reliability.render_quality]`，但模式仍是 `score_only`：

```powershell
pixi run python .\src\run_server.py --object controller_right
```

`score_only` 只计算分数、写 HUD/JSONL，不会因为低重投影分直接触发 re-register。重注册仍要等真机数据确认误报率后，再显式切到 `mode = "re_register"`。

## 3. 确认配置

在 `src/egoanchor/config/defaults.toml` 中确认：

```toml
[reliability.render_quality]
enabled = true # 是否启用渲染质量检测；默认采集重投影、mask 可见比例和深度对齐信号。
mode = "score_only" # score_only=只降分写 flag 不重注册；re_register=确认误报率后再启用连续低重投影分重注册。

[reliability.pose_score]
geo_floor = 0.05 # 几何核单维最低值；避免有效低分在几何平均中变成硬零。
reproj_weight = 0.5 # 重投影颜色分在几何核中的相对权重。
depth_weight = 0.5 # 深度对齐分在几何核中的相对权重。
mask_floor = 0.5 # mask 调制因子下限；遮挡或可见面积少时只温和降权。
```

有效渲染质量信号只会在 TRACK 阶段、已有 Cutie mask、register warmup 结束、K 可用、渲染前景面积足够时出现。以下情况会让 `track_reprojection=-1`：

- 刚 register/re-register 后的 warmup 帧。
- Cutie mask 为空或 Cutie 关闭。
- 渲染前景面积小于 `min_render_area_px`。
- 尚未收到有效 K。
- 渲染过程异常。

`track_reprojection=-1` 不是坏 pose 的直接证据。未满足检测前置条件时，reprojection 不进入几何核；如果本帧按逻辑应该有渲染质量信号但缺失，则会写 `reprojection_missing_expected` 并用低分参与几何核。

## 4. 看 OpenCV HUD

运行时建议保持 debug stage 4。Python OpenCV 热键：

```text
1/2/3/4 切换阶段
r 重置 tracking
q 或 ESC 退出
```

主窗口和 score debug 窗口重点看这些字段：

- `score` / `reliability_score`：最终可靠性分。
- `score_reprojection`：颜色重投影子分；`track_reprojection=-1` 时可能仍显示 1.0 或 0.30，具体取决于是否 expected。
- `score_depth`：深度对齐子分；覆盖不足或缺少渲染深度信号时显示中性 0.5。
- `score_mask`：优先来自 Cutie mask 面积 / 渲染投影面积；没有投影面积信号时退回全图 mask 面积规则。
- `score_confidence`：连续高质量帧 warmup，从 0.5 逐步到 1.0。
- `flags`：例如 `reprojection_low`、`depth_alignment_low`、`depth_coverage_insufficient`、`mask_visible_area_low`。

有一个容易误读的点：HUD/JSONL 中的子分保留诊断值，但几何核只纳入 valid 的 reprojection/depth。比如 `score_depth=0.5` 可能只是"没有可靠 depth 信号"，不一定会把最终分砍半。

## 5. 查看 runtime JSONL

默认启用 eval session 时，Python 日志会写在：

```text
EgoAnchor_Python\data\eval\<session_id>\<session_id>_python_runtime.jsonl
```

快速查看 pose 行：

```powershell
Get-Content .\data\eval\<session_id>\<session_id>_python_runtime.jsonl |
  Select-String '"event": "pose_result"' |
  Select-Object -First 5
```

关键字段：

- `pose_score`：最终可靠性分，0..1。
- `reliability_flags`：解释降分或无信号原因。
- `score_phase`、`score_reprojection`、`score_depth`、`score_mask`、`score_reject`、`score_confidence`：PoseResult 子分。
- `track_reprojection`：TRACK 阶段颜色重投影分；`-1` 表示本帧无有效重投影信号。
- `render_quality_status`：渲染质量状态，如 `valid`、`warmup`、`no_mask`、`render_exception`。
- `render_quality_area_ratio_score`：观测 mask 面积 / 渲染投影面积的比例分。
- `render_quality_depth_inlier`：交集区域深度 inlier 比例。
- `render_quality_depth_alignment`：深度对齐分。
- `render_quality_depth_residual_m`：深度残差中位数。
- `render_quality_ms`：渲染质量检测耗时。

## 6. 跑离线诊断

对已有 session 运行：

```powershell
pixi run python .\eval\run_eval.py --session-dir .\data\eval\<session_id>
```

报告目录会生成：

```text
report\reliability_diagnostics_summary.csv
report\reliability_score_histogram.csv
report\track_reprojection_histogram.csv
report\policy_distribution.csv
```

重点看：

- `score_unique_count` 和 `score_mode_share`：判断分数是否仍坍缩到单一值。
- `score_min/p50/p95`：观察新评分公式的整体分布。
- `track_reprojection_valid_count`：有效颜色重投影帧数量；长期为 0 时先查 Cutie mask、warmup、K 和渲染异常。
- `track_reprojection_p50/p95`：重投影分布。
- `render_quality_ms_p50/p95`：渲染质量开销；过高时先调大 `downscale`。
- `policy_distribution.csv`：Unity policy action/reason 分布；后续复核 Unity 阈值时会用到。

## 7. 谨慎开启 re_register

只有在 `score_only` 分布确认误报率可接受后，再把模式切到：

```toml
[reliability.render_quality]
mode = "re_register" # score_only=只降分写 flag 不重注册；re_register=确认误报率后再启用连续低重投影分重注册。
```

此模式下，连续 `min_track_frames` 帧 `track_reprojection < re_register_threshold` 会触发软 track-loss，并尝试用当前 mask 进行 `RE_REGISTER`。如果重投影信号无效，仍只记录无信号状态，不触发重注册。

## 8. 常见排查

- `track_reprojection` 一直是 `-1`：确认已经进入 TRACK、Cutie mask 非空、warmup 已结束、K 已更新，且渲染面积没有太小。
- `reprojection_low` 很多但肉眼 pose 正常：先保持 `score_only`，检查 mesh 尺度、K 映射、渲染 mask 与观测 mask 方向，以及 LAB 颜色是否受光照影响过大。
- `depth_alignment_low` 很多：看 `render_quality_depth_residual_m` 和 `render_quality_depth_inlier`，优先排查 FFS 深度、双目同步、K 映射和 mesh 尺度。
- `depth_coverage_insufficient` 很多：这类帧的 `score_depth=0.5` 不进入几何核，先查 mask 内有效深度覆盖率。
- score 分布整体变低：这是几何合取核的预期结果之一。重投影高但深度有效低分时，最终分会明显下降；Unity `ReliabilityGate` 阈值需要用新日志分布重新复核。
