# Python pose 检测与可靠性评分验证指南

本文档说明如何验证本轮新增的 Python 端可靠性评分功能：渲染-重投影一致性检测、非恒定 reliability score、runtime JSONL 旁路诊断，以及离线分布统计。

## 1. 先跑自动验证

在 `EgoAnchor_Python` 目录执行：

```powershell
pixi run python -m compileall src eval
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python -m unittest discover -s eval -p "test_*.py"
```

重点测试文件：

- `src/egoanchor/tests/test_render_consistency.py`：验证渲染 mask/depth 与观测 mask/depth 的纯数学评分。
- `src/egoanchor/tests/test_pose_quality.py`：验证 `reliability_score` 会随一致性、depth、jump 展开，不再恒为 1。
- `src/egoanchor/tests/test_runtime_event_logger.py`：验证 JSONL 中写入一致性旁路字段。
- `eval/tests/test_diagnostics.py`：验证离线诊断统计。

## 2. 默认基线运行

默认配置仍关闭渲染一致性检测，用于确认主线行为未改变：

```powershell
pixi run python .\src\tracking_server.py --object controller_right
```

此时 `PoseResult.reliability_score` 仍由新评分函数计算，但 `track_consistency=-1`，可靠性 flags 中会出现 `no_consistency_signal`。这表示本帧没有渲染一致性信号，不表示 pose 一定坏。

## 3. 开启 score_only shadow mode

第一轮真机验证请先使用 `score_only`，只降分和写日志，不触发重注册：

在 `src/egoanchor/config/defaults.toml` 中确认：

```toml
[reliability.consistency]
enabled = true # 是否启用渲染一致性检测；真机联调稳定后再设为 true。
mode = "score_only" # score_only=只降分写 flag 不重注册；re_register=确认误报率后再启用连续低一致性重注册。
```

然后运行：

```powershell
pixi run python .\src\tracking_server.py --object controller_right
```

运行时建议保持 debug stage 4。Python OpenCV 窗口热键仍是：

```text
1/2/3/4 切换阶段
r 重置 tracking
q 或 ESC 退出
```

有效一致性信号只会在 TRACK 阶段、已有 Cutie mask、depth in mask 足够、且 register warmup 结束后出现。以下情况会保持 `track_consistency=-1`，且不会触发重注册：

- 刚 register/re-register 后的 warmup 帧。
- Cutie mask 为空或 Cutie 关闭。
- mask 内有效深度比例过低。
- 渲染前景面积小于 `min_render_area_px`。
- 尚未收到有效 K。

OpenCV HUD 左上角可以直接看当前分数：

- `score=...`：最终 `PoseObservation.reliability_score`。
- `depth(mask)=...`：mask 内有效深度比例，越低越说明深度/分割/标定不可靠。
- `depth(all)=...`：全图有效深度比例，用于区分全局深度坏掉还是目标区域坏掉。
- `depthScore=...`：由 `depth(mask)` 和 `depth(all)` 映射出的深度质量子分，范围 0..1。
- `flags=...`：例如 `depth_in_mask_low`、`depth_in_mask_mid`、`no_consistency_signal`。

## 4. 查看 runtime JSONL

默认启用 eval session 时，Python 日志会写在：

```text
EgoAnchor_Python\data\eval\<session_id>\<session_id>_python_runtime.jsonl
```

可用 PowerShell 快速查看 pose 行：

```powershell
Get-Content .\data\eval\<session_id>\<session_id>_python_runtime.jsonl |
  Select-String '"event": "pose_result"' |
  Select-Object -First 5
```

新增关键字段：

- `pose_score`：最终可靠性分，0..1。
- `reliability_flags`：例如 `no_consistency_signal`、`consistency_low`、`depth_in_mask_low`、`near_jump_limit`。
- `depth_quality_score`：深度质量子分，0..1；这是 HUD 中 `depthScore` 的日志版本。
- `track_consistency`：渲染一致性分；`-1` 表示本帧无信号。
- `consistency_mask_iou`：渲染 mask 与观测 mask 的 IoU。
- `consistency_depth_inlier`：交集区域深度残差小于阈值的比例。
- `consistency_depth_residual_m`：深度残差中位数。
- `consistency_ms`：一致性检测耗时。

## 5. 跑离线诊断

对已有 session 运行：

```powershell
pixi run python .\eval\run_eval.py --session-dir .\data\eval\<session_id>
```

报告目录会新增：

```text
report\reliability_diagnostics_summary.csv
report\reliability_score_histogram.csv
report\track_consistency_histogram.csv
report\policy_distribution.csv
```

重点看：

- `score_unique_count` 和 `score_mode_share`：如果 mode share 仍接近 1，说明评分仍坍缩。
- `consistency_valid_count`：有效一致性帧数量；长期为 0 时先查 Cutie mask、depth、warmup、K。
- `consistency_ms_p50/p95`：一致性检测开销；若 p95 过高，调大 `downscale`。
- `track_consistency_histogram.csv`：低一致性是否集中出现在可疑坏 pose 帧。
- `policy_distribution.csv`：Unity policy action/reason 分布；本轮 Python 可先看分布，Unity C/D 后再用于完整闭环。

## 6. 谨慎开启 re_register

只有在 `score_only` 分布确认误报率可接受后，再运行：

在 `src/egoanchor/config/defaults.toml` 中只把模式切到：

```toml
[reliability.consistency]
enabled = true # 是否启用渲染一致性检测；真机联调稳定后再设为 true。
mode = "re_register" # score_only=只降分写 flag 不重注册；re_register=确认误报率后再启用连续低一致性重注册。
```

然后运行：

```powershell
pixi run python .\src\tracking_server.py --object controller_right
```

此模式下，连续 `min_track_frames` 帧 `track_consistency < re_register_threshold` 会触发软 track-loss，并尝试用当前 mask 进行 `RE_REGISTER`。如果信号无效，仍只会记录 `no_consistency_signal`，不会重注册。

## 7. 常见排查

- `track_consistency` 一直是 `-1`：先确认 Cutie 开启且 TRACK 阶段有 mask，再看 `depth_valid_in_mask` 是否足够。
- `consistency_ms` 太高：把 `downscale` 从 2 调到 3 或 4。
- `consistency_low` 很多但肉眼 pose 正常：先不要开 `re_register`，检查 mesh 尺度、K 映射、mask/depth 方向是否一致。
- score 仍接近全 1：看 `reliability_score_histogram.csv` 和 runtime flags，确认是否没有有效一致性信号，或场景里 depth/jump 都很稳定。
