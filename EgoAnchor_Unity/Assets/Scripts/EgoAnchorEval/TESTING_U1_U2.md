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
   - `AnchorEvalRecorder`
   - `EvalSessionController`
   - `EvalSessionHotkeyDriver`
3. 将 `AnchorEvalRecorder.groundTruthTransform` 绑定到本轮作为 GT 的手柄模型 Transform，例如你在 Inspector 中对比的 `OVRControllerPrefab`。
4. 将 `AnchorEvalRecorder.headAnchor` 绑定到 `OVRCameraRig/TrackingSpace/CenterEyeAnchor`。
5. 将 `AnchorEvalRecorder.alignmentReference` 设置为 `Left`。
6. 将 `AnchorEvalRecorder.stereoSource` 和 `framePoseHistory` 绑定到 runtime streaming 使用的同一组场景实例。
7. 至少添加两个 `recordedRuntimes`：
   - 主稳定变体：label 填 `kalman` 或当前 stable label，`runtime` 绑定主 runtime，`anchorTransform` 绑定实际显示的 `AnchorObject` Transform，`isPrimary=true`
   - raw 变体：label 填 `raw`，`runtime` 绑定 raw runtime，`anchorTransform` 绑定 raw 显示物体 Transform，`isPrimary=false`
8. 将 `EvalSessionController.recorder` 绑定到同一个 `AnchorEvalRecorder`。
9. 将 `EvalSessionHotkeyDriver.controller` 绑定到同一个 `EvalSessionController`。

## U1 GT 测试

1. 保持 Quest Link 可用并进入 Play Mode。
2. 按 `F7` 开始录制，移动被选中的手柄 2-3 秒，再按 `F8` 停止。
3. 打开 Console 打印的 session 目录中的 `<session_id>_unity_capture.jsonl`。
4. 任取一行，确认 `gt_pose_source="transform"`，并把 `gt_pos/gt_rot` 与 `AnchorEvalRecorder.groundTruthTransform` 在 Inspector 中看到的 Transform 对比；同时确认 `gt_euler_deg` 是 `[0,360)` 区间的 xyz 欧拉角。

期望结果：`gt_pos/gt_rot` 与绑定的 GT Transform 一致，并随手柄模型移动而变化；`gt_euler_deg` 只用于人工阅读，正式离线计算仍使用 `gt_rot` 四元数。

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

- capture 行包含递增的 `frame_id`、`capture_mono_ms`、`capture_unity_frame`、`head_pos/head_euler_deg`、`cam_pos/cam_euler_deg`、`gt_pos/gt_euler_deg`、`gt_pose_valid` 和 `gt_pose_source`。
- output 行包含 `render_mono_ms`、`render_unity_frame`、`source_frame_id`、`gt_pos` 和 `variants` 数组。
- 每个变体包含 `stable_pos/stable_rot/stable_euler_deg`、`anchor_pose_source`、`source_capture_mono_ms` 和 `source_capture_unity_frame`。
- 主变体包含 `aligned_raw_pos`、`aligned_raw_rot`、`aligned_raw_euler_deg` 和 `reliability_score`。
- output 行数应高于 capture 行数。
