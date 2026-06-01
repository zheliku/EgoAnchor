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

期望结果：前四个命令都以 0 退出。writer smoke 还会检查 `EgoAnchor-Evaluation.unity` 中存在 `EvalRig`、`EvalSessionController`、`EvalSessionHotkeyDriver`，并且启用了 hold-last GT。session checker 会验证内置 sample session，包括 manifest、capture/output schema、variants、hold-last GT 字段，以及 Python `pose_result.frame_id` join。`rg` 命令应无输出并以 1 退出，证明 eval 测试驱动使用的是 Unity 新 Input System，而不是旧输入系统。

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

- `ControllerGroundTruthProvider`
- `AnchorEvalRecorder`
- `EvalSessionController`
- `EvalSessionHotkeyDriver`
- 可选的 `EvalManualSmokeDriver`，用于 U1/U2 检查

进入 Play Mode 前，请确认这些绑定：

1. `ControllerGroundTruthProvider.cameraRig` 指向 `OVRCameraRig`。
2. `ControllerGroundTruthProvider.controller` 与本轮测试一致；`controller_right` 通常使用 `RTouch`。
3. `ControllerGroundTruthProvider.holdLastPoseWhenUntracked` 已启用。
4. `AnchorEvalRecorder.gt`、`headAnchor`、`stereoSource` 和 `framePoseHistory` 指向 runtime streaming 使用的同一组实例。
5. `AnchorEvalRecorder.recordedRuntimes` 至少包含 `kalman` 或当前 stable 变体，且 `isPrimary=true`；同时包含 `raw`。
6. `EvalSessionController.recorder` 和 `gt` 指向 `EvalRig` 上的组件。
7. `EvalSessionController.objectId` 与 Python 对象一致，例如 `controller_right`。

## 手柄静止休眠行为

Meta 手柄静止一段时间后可能为了省电而报告 `tracked=false`。eval GT provider 不会伪装 live tracking；它会继续输出最后一次 live tracked pose，并写入：

```text
gt_tracked=false
gt_pose_valid=true
gt_pose_source="hold_last"
gt_hold_age_ms=<age>
```

当手柄恢复 live tracking 后，日志行会回到：

```text
gt_tracked=true
gt_pose_source="live_tracked"
```

这样静态段仍可用于评估，同时保留 live SDK tracking 和 held GT 的区别。

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
- `gt_source` 为 `ovr_rtouch` 或 `ovr_ltouch`，并且与 provider 一致。
- `session_start_utc/local` 与 `session_stop_utc/local` 记录本次录制开始/结束的可读时间。
- `condition_spans` 有序且不重叠。
- `event_markers` 包含刚才标记的事件。
- `variant_labels` 包含 `raw` 和主稳定变体 label。
- `gt_hold_policy` 为 `hold_last_pose_when_untracked`。

## session_manifest.json 的作用

`session_manifest.json` 是这次实验的“目录卡片”。它不记录每帧 pose，而是记录离线分析必须知道的元数据：

- 这次 session 叫什么：`session_id`。
- 这次追踪哪个对象：`object_id`。
- GT 来自哪个手柄：`gt_source` / `gt_controller`。
- Unity 单调时间和真实墙钟时间如何换算：`mono_to_unix_offset_ms`。
- 本次录制开始/结束时间：`session_start_*` / `session_stop_*`。
- 你在录制时按数字键切出来的实验条件区间：`condition_spans`。
- 你按 `O/V/R` 标记的瞬时事件：`event_markers`。
- 本次输出了哪些 anchor 变体：`variant_labels`。
- Python runtime log 文件名：`python_log_filename`，后续可手填或由分析脚本传入。

后续 P1-P4 分析会用 manifest 自动给每一帧打上 condition 标签，并知道该和哪份 Python log 做 `frame_id` join。

## U4 Unity 端到端测试

1. 使用匹配的 object 启动 Python，例如：

```powershell
cd EgoAnchor_Python
pixi run controller_right
```

2. 在 Unity Editor + Quest Link 中进入 Play Mode。
3. 按 `F7`，移动头部和手柄录制约 20 秒，然后按 `F8`。
4. 打开 Console 打印的 session 目录。
5. 从 `<session_id>_unity_capture.jsonl` 中任选一个 `frame_id`。
6. 在本轮 Python runtime log 的 `pose_result` 行中找到相同的 `frame_id`。
7. 运行 validator：

```powershell
dotnet run --project EgoAnchor_Tools\eval_session_check\EvalSessionCheck.csproj -- --session-dir EgoAnchor_Python\data\eval\<session_id> --python-log <path-to-python-runtime-log.jsonl> --require-python-join
```

期望输出检查：

- `*_unity_capture.jsonl`、`*_unity_output.jsonl` 和 `session_manifest.json` 都存在。
- capture 行包含递增的 `frame_id`、`capture_utc/local`、`gt_pose_source`、`gt_pose_valid` 和 `gt_hold_age_ms`。
- output 行包含 `variants`，其中有 `raw` 和主稳定变体。
- output 行包含 `render_utc/local`。
- 主变体包含 `aligned_raw_pos`、`aligned_raw_rot` 和 `reliability_score`。
- 手柄静止休眠时，行里可能出现 `hold_last`；这是预期行为，不要把它改成 `tracked=true`。
- validator 打印非零的 `capture_rows`、`output_rows`、包含 `raw` 的 `variant_labels`，以及 `python_pose_frame_matches`。

自动 smoke 的临时产物可以在验证后删除，包括 `EgoAnchor_Python/data/eval/unity_eval_smoke`、`EgoAnchor_Tools/eval_writer_smoke/bin`、`obj`、`EgoAnchor_Tools/eval_session_check/bin`、`obj`。如果真实 manual session 后续会用于 P1-P4 分析，请保留对应 session 目录。
