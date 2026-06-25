# EgoAnchor Python 离线评估使用说明

本文档记录当前 Python `eval/` 的用法。它只评估 Unity 已经写出的世界坐标系日志，不再做旧版 hand-eye P2 标定。

## 1. 当前评估语义

Unity recorder 写两条 JSONL：

```text
<session_id>_unity_capture.jsonl  # capture-time head/camera/GT pose
<session_id>_unity_output.jsonl   # render-time anchor variants
```

Python runtime 写：

```text
<session_id>_python_runtime.jsonl # PoseResult/status/heartbeat/command 摘要
```

当前正式 anchor 输出字段是：

```text
has_output_pose
output_pos
output_rot
anchor_pose_source
motion_model
smoothing_strategy
gate
latest_static_locked
```

不要再写入或依赖旧的 `has_stable / stable_pos / stable_rot`。报告里的 `stable_rows` 只是 sanity 汇总名，表示某个 variant 中 `has_output_pose=true` 的行数。

GT、head、camera、anchor 都已经是 Unity 世界系 Transform pose。离线指标直接比较：

```text
gt_pos/gt_rot  <->  output_pos/output_rot
```

继续做旧 hand-eye 会把真实 tracking/filter 误差吸收到离线标定偏置里，反而削弱评估。

## 2. 录制 session

先在 `EgoAnchor_Python` 目录启动 Python：

```powershell
pixi run controller_right
```

Unity 进入 Play 前检查：

1. `AnchorEvalRecorder.groundTruthTransform` 绑定真实 GT Transform，例如控制器可视模型。
2. `recordedRuntimes[*].runtime` 绑定待评估 runtime。
3. `recordedRuntimes[*].anchorTransform` 绑定实际显示输出的 anchor Transform。
4. `headAnchor`、`stereoSource`、`framePoseHistory` 与主链路共用同一组实例。
5. `EvalSessionController.objectId` 与 Python `--object` 一致。

热键：

| 热键 | 动作 |
| --- | --- |
| F7 | 开始 session |
| F8 | 停止 session 并写 manifest |
| 0 | 结束当前 condition |
| 1 | `static` |
| 2 | `slow_head` |
| 3 | `fast_head` |
| 4 | `object_motion` |
| 5 | `occlusion` |
| 6 | `out_of_view` |
| 7 | `lighting` |
| O | `occlusion` marker |
| V | `out_of_view` marker |
| R | `recovery` marker |

推荐正式协议：

```text
static -> slow_head -> fast_head -> object_motion -> occlusion -> out_of_view -> lighting
```

短 smoke 可以只录 `static + slow_head + fast_head`。

## 3. 运行评估

在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run eval --session-dir data/eval/<session_id>
```

只导出指标表：

```powershell
pixi run eval-metrics --session-dir data/eval/<session_id>
```

只导出图表：

```powershell
pixi run eval-figures --session-dir data/eval/<session_id>
```

如果旧 session 的 manifest 没有 `python_log_filename`，可以显式指定：

```powershell
pixi run eval --session-dir data/eval/<session_id> --python-log data/eval/<session_id>/<python_runtime>.jsonl
```

## 4. Report 产物

报告写入：

```text
data/eval/<session_id>/report/
```

主要文件：

```text
gt_anchor_sanity.json
summary.md
anchor_error_summary.csv
pose_offset_summary.csv
rq1_raw_mapping_error_summary.csv
rq1_raw_mapping_slip_summary.csv
latency_summary.csv
jitter_summary.csv
slip_summary.csv
lag_summary.csv
jump_suppression_summary.csv
recovery_summary.csv
reliability_diagnostics_summary.csv
color_reprojection_histogram.csv
```

`gt_anchor_sanity.json` 是第一眼要看的文件：

- `gt_source` 应为 `transform`。
- `gt_transform` 应是本轮真实 GT Transform。
- `variants.<label>.stable_rows` 应大于 0。
- `anchor_pose_source_counts` 应主要是 `transform`。
- `aligned_raw_error` 只诊断主变体 raw 输入质量，不等于最终 anchor 精度。

## 5. 指标怎么读

- `anchor_error_summary.csv`：世界系 anchor 平移/旋转误差，主表。
- `pose_offset_summary.csv`：`output - gt` 的固定偏移诊断。
- `rq1_raw_mapping_*`：frame-aligned raw 与 arrival-time raw 的 RQ1 对照。
- `jitter_summary.csv`：静止窗口抖动。
- `slip_summary.csv`：头动时屏幕空间/投影滑移。
- `lag_summary.csv`：物体运动条件下的滞后。
- `latency_summary.csv`：capture -> render apply 以及 Python 模块耗时。
- `recovery_summary.csv`：marker 后恢复时间，需要 O/V/R 事件。
- `reliability_diagnostics_summary.csv`：Python pose score 和渲染质量分布。

## 6. 常见问题

- `ModuleNotFoundError: No module named 'eval'`：从 `EgoAnchor_Python` 目录运行 `pixi run eval ...`。
- `anchor_error_summary.csv` 只有表头：检查 `gt_anchor_sanity.json` 的 `stable_rows`，通常是 `anchorTransform` 未绑定或 runtime 没有输出。
- `gt_source=none`：`groundTruthTransform` 未绑定。
- `manifest.python_log_filename` 为空：Unity 没复用 Python session；先启动 Python，再按 F7。
- 图里显示 `insufficient_data`：链路正常，但缺少对应实验条件，例如 lag 没有 `object_motion`，recovery 没有 marker。

## 7. 开发验证

```powershell
pixi run python -m compileall src eval
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python -m unittest discover -s eval -p "test_*.py"
```
