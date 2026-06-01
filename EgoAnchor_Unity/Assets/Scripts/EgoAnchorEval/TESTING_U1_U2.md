# U1/U2 手动测试指南

本文是 Stage U1/U2 必须交付的测试脚本与检查清单。

## 自动化检查

在仓库根目录运行：

```powershell
dotnet run --project EgoAnchor_Tools\eval_writer_smoke\EvalWriterSmoke.csproj
dotnet build EgoAnchor_Unity\EgoAnchorEval.csproj --no-restore
dotnet build EgoAnchor_Unity\Assembly-CSharp.csproj --no-restore
```

期望结果：三个命令都以 0 退出。smoke 命令会写入一行临时 JSONL，并检查精确 JSON 字节、capture/output JSON 字段以及评估场景挂载状态。

## 场景设置

1. 在 Unity evaluation 场景中创建或选择 `EvalRig`。
2. 给 `EvalRig` 添加这些组件：
   - `ControllerGroundTruthProvider`
   - `AnchorEvalRecorder`
   - `EvalManualSmokeDriver`
3. 将 `ControllerGroundTruthProvider.cameraRig` 绑定到场景里的 `OVRCameraRig`。
4. 将 `ControllerGroundTruthProvider.controller` 设置为本轮测试的手柄。
5. 将 `AnchorEvalRecorder.gt` 绑定到 `EvalRig` 上的 provider。
6. 将 `AnchorEvalRecorder.headAnchor` 绑定到 `OVRCameraRig/TrackingSpace/CenterEyeAnchor`。
7. 将 `AnchorEvalRecorder.alignmentReference` 设置为 `Left`。
8. 将 `AnchorEvalRecorder.stereoSource` 和 `framePoseHistory` 绑定到 runtime streaming 使用的同一组场景实例。
9. 至少添加两个 `recordedRuntimes`：
   - 主稳定变体 runtime，label 填 `kalman` 或当前 stable label，`isPrimary=true`
   - raw runtime，label 填 `raw`，`isPrimary=false`
10. 将 `EvalManualSmokeDriver.gt` 和 `recorder` 绑定到同一组组件。

## U1 GT 测试

1. 保持 Quest Link 可用并进入 Play Mode。
2. 按 `F6` 切换 GT 日志，或使用组件 context menu：`EgoAnchor Eval/Log Ground Truth Once`。
3. 移动被选中的手柄。
4. 确认 Console 日志类似：

```text
[EgoAnchorEval][U1] controller=RTouch has_pose=True tracked=True pos=(...) rot_xyzw=(...)
```

期望结果：position 会随手柄移动而变化。手柄可见且被追踪时 `tracked=true`；追踪丢失时 `tracked=false`。

## U2 Recorder 测试

1. 在 Play Mode 中按 `F7`，或使用 context menu：`EgoAnchor Eval/Begin U1 U2 Smoke Recording`。
2. 移动头部和手柄 5-10 秒。
3. 按 `F8`，或使用 context menu：`EgoAnchor Eval/Stop U1 U2 Smoke Recording`。
4. 查看 Console 打印的 session 目录。默认根目录为：

```text
EgoAnchor_Python/data/eval/manual_smoke/<session_id>/
```

期望文件：

```text
<session_id>_unity_capture.jsonl
<session_id>_unity_output.jsonl
```

期望内容：

- capture 行包含递增的 `frame_id`、`capture_mono_ms`、`head_pos`、`cam_pos`、`gt_pos` 和 `gt_tracked`。
- output 行包含 `render_mono_ms`、`source_frame_id`、`gt_pos` 和 `variants` 数组。
- 主变体包含 `aligned_raw_pos`、`aligned_raw_rot` 和 `reliability_score`。
- output 行数应高于 capture 行数。
