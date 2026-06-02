# U3/U4 手动测试指南

本文是 Stage U3/U4 必须交付的测试脚本与检查清单。

## 自动化检查

在仓库根目录运行：

```powershell
dotnet run --project EgoAnchor_Tools\eval_writer_smoke\EvalWriterSmoke.csproj
dotnet run --project EgoAnchor_Tools\eval_session_check\EvalSessionCheck.csproj -- --require-python-join
dotnet build EgoAnchor_Unity\EgoAnchorEval.csproj --no-restore
dotnet build EgoAnchor_Unity\Assembly-CSharp.csproj --no-restore
rg -n "\bInput\.|KeyCode|InputLegacy" -g "*.cs" EgoAnchor_Unity\Assets\Scripts\EgoAnchorEval EgoAnchor_Tools\eval_writer_smoke
```

期望结果：前四个命令都以 0 退出。writer smoke 还会检查 `EgoAnchor-Evaluation.unity` 中存在 `EvalRig`、`EvalSessionController`、`EvalSessionHotkeyDriver`，并且 `AnchorEvalRecorder` 使用 `groundTruthTransform` 与每个变体的 `anchorTransform` 字段。session checker 会验证内置 sample session，包括 manifest、capture/output schema、variants、Transform GT 字段，以及 Python `pose_result.frame_id` join。`rg` 命令应无输出并以 1 退出，证明 eval 测试驱动使用的是 Unity 新 Input System，而不是旧输入系统。

## 输出目录与时间格式

新 session 的目录和文件名前缀使用可读时间格式：

```text
EgoAnchor_Python/data/eval/yyyyMMdd_HHmmss_controller_right/
  yyyyMMdd_HHmmss_controller_right_unity_capture.jsonl
  yyyyMMdd_HHmmss_controller_right_unity_output.jsonl
  session_manifest.json
```

例如：

```text
EgoAnchor_Python/data/eval/20260602_153012_controller_right/
```

如果同一秒内重复开始录制，会自动追加 `_02`、`_03` 等后缀，避免覆盖旧数据。

日志同时保留机器分析用时间和人类可读时间：

- `*_mono_ms`：Unity 单调时间，适合算延迟和时间差。
- `*_unix_ms`：Unix 毫秒，适合跨进程对齐。
- `*_utc`：UTC 可读时间，例如 `2026-06-02T07:30:12.345Z`。
- `*_local`：本地时区可读时间，例如 `2026-06-02 15:30:12.345 +08:00`。

## 场景设置

当前 evaluation 场景中已经有 `Server/EvalRig`，包含：

- `AnchorEvalRecorder`
- `EvalSessionController`
- `EvalSessionHotkeyDriver`

进入 Play Mode 前，请确认这些绑定：

1. `AnchorEvalRecorder.groundTruthTransform` 指向本轮作为 GT 的手柄模型 Transform，例如你在 Inspector 中对比的 `OVRControllerPrefab`。
2. `AnchorEvalRecorder.headAnchor`、`stereoSource` 和 `framePoseHistory` 指向 runtime streaming 使用的同一组实例。
3. `AnchorEvalRecorder.recordedRuntimes` 至少包含 `kalman` 或当前 stable 变体，且 `isPrimary=true`；同时包含 `raw`。每个变体都应绑定对应的 `runtime` 和实际显示物体的 `anchorTransform`。
4. `EvalSessionController.recorder` 指向 `EvalRig` 上的 `AnchorEvalRecorder`。
5. `EvalSessionController.objectId` 与 Python 对象一致，例如 `controller_right`。

## Transform GT 行为

eval recorder 只读取 `groundTruthTransform.position/rotation`。每一行 GT 都应该和你在 Unity Inspector 里看到的 `OVRControllerPrefab` Transform 一致：

```text
gt_pose_valid=true
gt_pose_source="transform"
gt_pos=[groundTruthTransform.position]
gt_rot=[groundTruthTransform.rotation xyzw]
gt_euler_deg=[groundTruthTransform.rotation.eulerAngles xyz, 0-360]
```

如果没有绑定 `groundTruthTransform`，该帧会写入：

```text
gt_pose_valid=false
gt_pose_source="none"
gt_pos=null
gt_rot=null
gt_euler_deg=null
```

因此正式录制前必须绑定正确 Transform。若 `OVRControllerPrefab` 静止时自身停止更新，评估日志也会忠实记录这个 Transform 的最后显示状态。

## U3 Session 测试

1. 进入 Play Mode。
2. 按 `F7` 开始一个 session。
3. 分别按 `1`、`2`、`3` 并各保持几秒，切换 `static`、`slow_head` 和 `fast_head`。
4. 按 `O` 标记一个 `occlusion` 事件。
5. 按 `0` 关闭当前 condition，或直接按另一个数字切换 condition。
6. 按 `F8` 停止录制并写出 manifest。

期望 Console：

```text
[EgoAnchorEval][U3] Session started: ...
[EgoAnchorEval][U3] Condition started: static
[EgoAnchorEval][U3] Event marked: occlusion
[EgoAnchorEval][U3] Manifest written: ...\session_manifest.json
```

期望文件位于 `EgoAnchor_Python/data/eval/<session_id>/`：

```text
<session_id>_unity_capture.jsonl
<session_id>_unity_output.jsonl
session_manifest.json
```

期望 manifest 字段：

- `session_id` 与目录名一致。
- `object_id` 与 `EvalSessionController.objectId` 一致。
- `gt_source` 为 `transform`，并且 `gt_transform` 是绑定的 Transform 名称。
- `session_start_utc/local` 与 `session_stop_utc/local` 记录本次录制开始/结束的可读时间。
- `condition_spans` 有序且不重叠。
- `event_markers` 包含刚才标记的事件。
- `variant_labels` 包含 `raw` 和主稳定变体 label。

## session_manifest.json 的作用

`session_manifest.json` 是这次实验的“目录卡片”。它不记录每帧 pose，而是记录离线分析必须知道的元数据：

- 这次 session 叫什么：`session_id`。
- 这次追踪哪个对象：`object_id`。
- GT 来自哪个 Transform：`gt_source` / `gt_transform`。
- Unity 单调时间和真实墙钟时间如何换算：`mono_to_unix_offset_ms`。
- 本次录制开始/结束时间：`session_start_*` / `session_stop_*`。
- 你在录制时按数字键切出来的实验条件区间：`condition_spans`。
- 你按 `O/V/R` 标记的瞬时事件：`event_markers`。
- 本次输出了哪些 anchor 变体：`variant_labels`。
- Python runtime log 文件名：`python_log_filename`。默认由 Unity 从同目录 `python_session.json` 自动写入。

后续 P1-P4 分析会用 manifest 自动给每一帧打上 condition 标签，并知道该和哪份 Python log 做 `frame_id` join。

## U4 Unity 端到端测试

1. 使用匹配的 object 启动 Python，例如：

```powershell
cd EgoAnchor_Python
pixi run controller_right
```

2. 确认 Python 已创建 `EgoAnchor_Python/data/eval/<session_id>/python_session.json`。
3. 在 Unity Editor + Quest Link 中进入 Play Mode。
4. 按 `F7`，Unity Console 应提示复用 Python eval session；移动头部和手柄录制约 20 秒，然后按 `F8`。
5. 打开 Console 打印的 session 目录。
6. 从 `<session_id>_unity_capture.jsonl` 中任选一个 `frame_id`。
7. 在同目录 `<session_id>_python_runtime.jsonl` 的 `pose_result` 行中找到相同的 `frame_id`。
8. 运行 validator：

```powershell
dotnet run --project EgoAnchor_Tools\eval_session_check\EvalSessionCheck.csproj -- --session-dir EgoAnchor_Python\data\eval\<session_id> --require-python-join
```

期望输出检查：

- `*_unity_capture.jsonl`、`*_unity_output.jsonl` 和 `session_manifest.json` 都存在。
- capture 行包含递增的 `frame_id`、`capture_utc/local`、`gt_pose_source`、`gt_pose_valid`、`gt_pos`、`gt_rot` 和 `[0,360)` 的 `gt_euler_deg`。
- output 行包含 `variants`，其中有 `raw` 和主稳定变体。
- output 行包含 `render_utc/local`。
- 每个变体包含 `anchor_pose_source`、`source_capture_mono_ms`、`source_capture_unity_frame` 和 `[0,360)` 的 `stable_euler_deg`，可直接计算 `render_mono_ms - source_capture_mono_ms`。
- 主变体包含 `aligned_raw_pos`、`aligned_raw_rot`、`aligned_raw_euler_deg` 和 `reliability_score`。
- `gt_pose_source` 应为 `transform`；如果出现 `none`，说明本轮没有绑定 `groundTruthTransform`。
- validator 打印非零的 `capture_rows`、`output_rows`、包含 `raw` 的 `variant_labels`，以及 `python_pose_frame_matches`。

自动 smoke 的临时产物可以在验证后删除，包括 `EgoAnchor_Python/data/eval/unity_eval_smoke`、`EgoAnchor_Tools/eval_writer_smoke/bin`、`obj`、`EgoAnchor_Tools/eval_session_check/bin`、`obj`。如果真实 manual session 后续会用于 P1-P4 分析，请保留对应 session 目录。
