# EgoAnchor Unity 命令控制接线说明

`AnchorCommandClient` 是 Unity 侧控制 Python pose 估计流程的 API 组件。它通过 `NatsControlClient` 发送 NATS request/reply 命令：

- `ResetTracking()`：请求 Python 在 runtime 主循环边界重置 FoundationPose/Cutie 跟踪状态。
- `ForceReacquire()`：请求 Python 清空旧 tracking，并在后续帧重新检测/register。
- `ReacquireNextValidFrame()`：请求 Python 从下一帧有效输入重新获取目标。
- `PauseTracking()` / `ResumeTracking()`：暂停或恢复 Python pipeline。
- `SetStage1()` / `SetStage2()` / `SetStage3()` / `SetStage4()`：远程切换 Python debug stage。

## 场景接线

1. 在已有 NATS GameObject 上保留 `NatsControlClient` 和 `PoseResultReceiver`。
2. 给同一个 GameObject 添加 `AnchorCommandClient`。
3. 将 `AnchorCommandClient.natsClient` 指向同一个 `NatsControlClient`。
4. 如需 reset 后同步清理 Unity 本地滤波/pose，把 `PoseToAnchorRuntime` 拖入 `localAnchorRuntimes`。
5. UI Button 的 `OnClick()` 直接绑定 `AnchorCommandClient.ResetTracking()`、`ForceReacquire()`、`PauseTracking()` 等公开方法。

`CommandAck.accepted=true` 只表示 Python 已接受命令；reset/reacquire 的实际完成状态仍应以后续 `PoseResult` 或状态事件为准。
