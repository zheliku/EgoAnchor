# Python pose 可靠性评分验证指南

本文档说明如何验证当前 Python 端 pose 可靠性链路。端到端技术流程以
[`../2026-EgoAnchor/egoanchor_code_derived_technical_flow.md`](../2026-EgoAnchor/egoanchor_code_derived_technical_flow.md)
为准。

## 1. 自动验证

在 `EgoAnchor_Python` 目录执行：

```powershell
pixi run python -m compileall src eval
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python -m unittest discover -s eval -p "test_*.py"
```

重点测试：

- `src/egoanchor/tests/test_render_quality.py`：颜色重投影、深度对齐和渲染质量字段。
- `src/egoanchor/tests/test_pose_quality.py`：`reliability_score` 与子分合成。
- `src/egoanchor/tests/test_runtime_event_logger.py`：runtime JSONL 字段。
- `eval/tests/test_diagnostics.py`：离线可靠性分布统计。

## 2. 默认运行方式

当前默认配置开启 `[reliability.render_quality]`，但 `mode="score_only"`。这表示系统只计算分数、写入 HUD/JSONL，不会因为低重投影分直接触发 re-register。

```powershell
pixi run controller_right
```

或直接指定入口：

```powershell
pixi run python src/run_server.py --object controller_right
```

只有在真机日志确认误报率可接受后，才应显式切到 `mode="re_register"`。

## 3. 当前默认配置

在 `src/egoanchor/config/defaults.toml` 中确认：

```toml
[reliability.render_quality]
enabled = true # 是否启用渲染质量检测；默认采集重投影、mask 可见比例和深度对齐信号。
mode = "score_only" # score_only=只降分写 flag 不重注册；re_register=确认误报率后再启用连续低重投影分重注册。

[reliability.pose_score]
geo_floor = 0.05 # 几何核单维最低值；避免有效低分在几何平均中变成硬零。
reproj_weight = 0.2 # 重投影颜色分在几何核中的相对权重；颜色只作为辅助证据。
depth_weight = 0.8 # 深度对齐分在几何核中的相对权重；手柄等低纹理目标优先相信深度。
mask_floor = 0.5 # mask 调制因子下限；遮挡或可见面积少时只温和降权。
```

有效颜色重投影信号只会在 TRACK 阶段、已有 Cutie mask、register warmup 结束、K 可用、渲染前景面积足够时出现。以下情况会让 `color_reprojection=-1`：

- 刚 register/re-register 后的 warmup 帧。
- Cutie mask 为空或 Cutie 关闭。
- 渲染前景面积小于阈值。
- 尚未收到有效 K。
- 渲染过程异常。
- 目标表面颜色方差太低，颜色相关性本身不可用。

`color_reprojection=-1` 表示无有效颜色信号，不是坏 pose。无信号时颜色项不进入几何核。

## 4. 可靠性合成

总分结构：

```text
R = G * Q * C
G = score_phase * score_reject
Q = G_geo * score_mask
```

几何核只纳入有效证据：

```text
G_geo = exp(sum_i w_i * log(max(score_i, eps)) / sum_i w_i)
```

有效证据包括：

- `score_reprojection`：颜色重投影子分。只有 `color_reprojection >= 0` 且逻辑上有效时进入几何核。
- `score_depth`：深度对齐子分。只有渲染深度与 FFS 深度有足够交集和覆盖率时进入几何核。

没有任何有效几何证据时，`G_geo=1`，系统不武断降分。`score_depth=0.5` 常表示深度覆盖不足的中性诊断值，不等于最终分被砍半。

`score_confidence` 是连续高质量帧 warmup，约 10 帧从 0.5 提升到 1.0。

## 5. OpenCV HUD

运行时建议保持 debug stage 4。热键：

```text
1/2/3/4 切换阶段
r 重置 tracking
q 或 ESC 退出
```

重点看：

- `score` / `reliability_score`：最终可靠性分。
- `score_reprojection`：颜色重投影子分。
- `score_depth`：深度对齐子分。
- `score_mask`：mask 面积/可见性调制。
- `score_reject`：近期 track reject 惩罚。
- `score_confidence`：连续高质量帧置信。
- `flags`：例如 `reprojection_low`、`depth_alignment_low`、`depth_coverage_insufficient`、`mask_visible_area_low`。

HUD 显示的是诊断值；最终几何核是否纳入某个子分，要看该证据是否 valid。

## 6. runtime JSONL

启用 eval session 时，Python 日志写在：

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
- `reliability_flags`：降分或无信号原因。
- `score_phase`、`score_reprojection`、`score_depth`、`score_mask`、`score_reject`、`score_confidence`：PoseResult 子分。
- `color_reprojection`：TRACK 阶段颜色重投影分；`-1` 表示本帧无有效颜色信号。
- `render_quality_evaluated`：本帧是否实际运行渲染质量检测。
- `render_quality_status`：如 `valid`、`warmup`、`no_mask`、`render_exception`。
- `render_quality_area_ratio_score`：观测 mask 面积 / 渲染投影面积的比例分。
- `render_quality_depth_inlier`：交集区域深度 inlier 比例。
- `render_quality_depth_alignment`：深度对齐分。
- `render_quality_depth_residual_m`：深度残差中位数。
- `render_quality_ms`：渲染质量检测耗时。

## 7. 离线诊断

对已有 session 运行：

```powershell
pixi run eval --session-dir data/eval/<session_id>
```

报告目录会生成：

```text
report\reliability_diagnostics_summary.csv
report\reliability_score_histogram.csv
report\color_reprojection_histogram.csv
report\policy_distribution.csv
```

重点看：

- `score_unique_count` 和 `score_mode_share`：判断分数是否坍缩到单一值。
- `score_min/p50/p95`：观察可靠性分布。
- `color_reprojection_valid_count`：有效颜色重投影帧数量。
- `color_reprojection_p50/p95`：有效颜色重投影分布。
- `render_quality_ms_p50/p95`：渲染质量开销。
- `policy_distribution.csv`：Unity policy action/reason 分布。

## 8. 谨慎开启 re_register

确认 `score_only` 分布稳定后，才能切换：

```toml
[reliability.render_quality]
mode = "re_register" # score_only=只降分写 flag 不重注册；re_register=确认误报率后再启用连续低重投影分重注册。
```

此模式下，连续低质量颜色重投影会触发软 track-loss 并尝试 re-register。若颜色信号无效，仍只记录无信号状态，不触发重注册。

## 9. 常见排查

- `color_reprojection` 一直是 `-1`：确认已进入 TRACK、Cutie mask 非空、warmup 结束、K 已更新，且渲染面积没有太小。
- `reprojection_low` 很多但肉眼 pose 正常：先保持 `score_only`，检查 mesh 尺度、K 映射、渲染 mask 与观测 mask 方向，以及 LAB 颜色受光照影响的程度。
- `depth_alignment_low` 很多：看 `render_quality_depth_residual_m` 和 `render_quality_depth_inlier`，优先排查 FFS 深度、双目同步、K 映射和 mesh 尺度。
- `depth_coverage_insufficient` 很多：这类帧的 `score_depth=0.5` 多半是中性诊断，先查 mask 内有效深度覆盖率。
- score 分布整体变低：这是几何合取核的预期表现。重投影高但深度有效低分时，最终分会明显下降；Unity 阈值要用新日志分布重新复核。
