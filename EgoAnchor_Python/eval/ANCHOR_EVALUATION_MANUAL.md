# EgoAnchor anchor 评测手册

这份手册面向正式实验录制和论文指标解读。更短的命令说明见 [`README.md`](README.md)。

## 1. 评估边界

当前评估直接比较 Unity 世界坐标系中的 GT 与 anchor 输出：

```text
gt_pos/gt_rot  <->  output_pos/output_rot
```

这里的 `output_pos/output_rot` 来自 Unity render 日志中的每个 variant。当前评估只接受 `has_output_pose / output_pos / output_rot` 这组 schema。

`gt_anchor_sanity.json` 里的 `stable_rows` 是汇总统计名，含义是该 variant 中 `has_output_pose=true` 的行数。

## 2. 录制前检查

Unity 场景中找到 `EvalRig`，逐项检查：

1. `AnchorEvalRecorder.groundTruthTransform` 指向真实 GT Transform，例如 `OVRControllerPrefab`。
2. `AnchorEvalRecorder.headAnchor` 指向 `CenterEyeAnchor`。
3. `stereoSource` 和 `framePoseHistory` 指向 runtime streaming 使用的同一组实例。
4. `recordedRuntimes` 至少包含一个主方法和一个 raw 参照。
5. 每个 `recordedRuntimes[*].anchorTransform` 指向实际显示的输出物体，不要指向 runtime 宿主空物体。
6. `EvalSessionController.objectId` 与 Python 对象一致。

GT 是答案，anchor 是被评估对象。不要把 `groundTruthTransform` 绑定到 `AnchorObject`、runtime 输出物体或头显相机。

## 3. 推荐变体

正式论文建议至少记录：

| label | 说明 |
| --- | --- |
| `raw` | `ConstantVelocityModel + RawPassthroughStrategy`，原始低频观测零阶保持 |
| `kalman_blend` | `KalmanModel + BlendStrategy`，零延迟平滑 baseline |
| `oneeuro_blend` | `OneEuroModel + BlendStrategy`，常用交互滤波 baseline |
| `kalman_interp` | `KalmanModel + DelayedInterpStrategy`，延迟插值 baseline |
| `egoanchor` | 与选定 baseline 相同，启用静止锚定；论文 RQ2 完整方法变体可额外开启 `enableQualityGate` |

`rq2_alignment_ablation_*` 用于 RQ2 的时空对齐消融，比较 frame-aligned raw 与 arrival-time raw。不要把滤波器混进这组对照。

## 4. 条件与热键

| 热键 | condition / marker | 建议时长 | 目的 |
| --- | --- | ---: | --- |
| F7 | 开始 session | - | 开始录制 |
| 1 | `static` | 30s | 静态误差与 jitter |
| 2 | `slow_head` | 30s | 慢速头动 world consistency |
| 3 | `fast_head` | 20s | 快速头动 slip 与时延影响 |
| 4 | `object_motion` | 30s | 运动误差与 lag |
| 5 / O / R | `occlusion` / marker | 20s | 遮挡、hold/recovery |
| 6 / V / R | `out_of_view` / marker | 5 次 | 出视野后重获 |
| 7 | `lighting` | 20s | 光照和背景变化 |
| F8 | 停止 session | - | 写 manifest |

一次完整录制可以按：

```text
F7 -> 1 -> 2 -> 3 -> 4 -> 5/O/R -> 6/V/R... -> 7 -> F8
```

只排查 frame alignment 和基础 pose 精度时，最小录制：

```text
F7 -> 1 static 30s -> 2 slow_head 30s -> 3 fast_head 20s -> F8
```

## 5. 运行评估

```powershell
cd P:\VSCode-Project\EgoAnchor\EgoAnchor_Python
pixi run eval --session-dir data/eval/<session_id>
```

输出目录：

```text
data/eval/<session_id>/report/
```

先打开：

```text
gt_anchor_sanity.json
```

合格 session 至少满足：

```text
gt_source = transform
capture_rows > 0
pose_rows > 0
output_rows > 0
variants.<label>.stable_rows > 0
anchor_pose_source_counts 里 transform > 0
condition_spans 覆盖主要实验条件
```

## 6. 主指标阅读顺序

第一看 `anchor_error_summary.csv`：

```text
translation_median_m
translation_p95_m
rotation_median_deg
rotation_p95_deg
```

第二看 `pose_offset_summary.csv`：

```text
position_offset_median_x/y/z_m
position_offset_median_norm_m
position_residual_after_median_p50/p95_m
rotation_offset_median_euler_x/y/z_deg
rotation_offset_median_deg
```

固定偏移的判断：

- median offset 稳定，且 residual p95 很小：可能是模型原点、GT Transform 或固定补偿问题。
- static 好、slow/fast head 变差：优先查 frame alignment、latency 或 head-motion-induced slip。
- raw 好但方法差：查 policy、滤波器或输出 Transform 绑定。

第三看时间线图和 detail 表：

```text
error_timeline.png
anchor_error_detail.csv
```

detail 表可定位到具体 `source_frame_id`、condition、policy action 和误差尖峰。

## 7. 其它指标

- `jitter_summary.csv`：静止条件下的微抖，适合证明静止锚定。
- `slip_summary.csv`：头动时的屏幕空间滑移，适合证明 frame-aligned anchoring。
- `lag_summary.csv`：物体运动时的滞后，适合比较滤波器。
- `jump_suppression_summary.csv`：raw 与方法输出都有有效 pose 时才有意义。
- `recovery_summary.csv`：需要 O/V/R marker。
- `latency_summary.csv`：解释延迟来源，不直接代表精度。
- `reliability_diagnostics_summary.csv`：检查 Python score 分布和渲染质量信号覆盖。

## 8. 旋转误差接近 180 度

如果平移误差小，但 `rotation_median_deg` 长期接近 180 度，通常不是滤波器问题。优先检查：

1. GT Transform 的局部轴。
2. anchor mesh / CAD 模型前向轴。
3. OpenCV camera pose 到 Unity world pose 的固定轴转换。
4. 控制器或目标物体的近似对称性。

这不是恢复旧 hand-eye P2 的理由。应在 Unity 绑定、模型 offset 或评估语义中明确固定局部轴差异。

## 9. 常见问题

- `stable_rows=0`：检查 runtime 是否输出、`anchorTransform` 是否绑定实际显示物体。
- `gt_source=none`：`groundTruthTransform` 未绑定。
- `python_pose_frame_matches=0`：检查 Unity 是否复用 Python session，以及 `frame_id` 是否从采集一路透传到 Python runtime 日志。
- 只有 `unlabeled` condition：录制时没有按数字键切 condition。
- recovery 表为空：没有 marker，或 marker 后没有持续低误差恢复段。

## 10. 实验检查清单

```text
[ ] Python 先启动并创建 eval session
[ ] Unity F7 后复用同一个 session_id
[ ] GT Transform 绑定正确
[ ] 每个 variant 有 runtime 和 anchorTransform
[ ] static/slow_head/fast_head/object_motion 至少覆盖
[ ] gt_anchor_sanity.json 中 stable_rows > 0
[ ] anchor_pose_source_counts 主要为 transform
[ ] report 中 anchor_error_summary 和 pose_offset_summary 非空
```
