# EgoAnchor Unity anchor policy 使用指南

本文档只记录当前 Unity 侧 anchor runtime 的挂载、对比组合和验证命令。更完整的端到端技术流程见
[`2026-EgoAnchor/egoanchor_code_derived_technical_flow.md`](2026-EgoAnchor/egoanchor_code_derived_technical_flow.md)。

## 当前流程

Unity 收到 Python 的 `PoseResult` 后，先按 `frame_id` 在 `FramePoseHistory` 中精确回查采集时刻的相机世界位姿，再把 Python 的 OpenCV camera-space object pose 转成 Unity world pose。anchor policy 只处理已经对齐好的 world pose，不接触网络、Protobuf 或相机坐标变换。

运行时有两个时钟：

```text
pose 到达时钟:
  PoseToAnchorRuntime -> CameraPoseFrameAligner -> AnchorPolicyHost.AcceptPose

渲染帧时钟:
  PoseToAnchorRuntime.LateUpdate -> AnchorPolicyHost.Advance
  -> MotionModel + SmoothingStrategy + optional StaticLock
  -> DynamicObjectAnchor 应用 Transform
```

`DynamicObjectAnchor` 是薄应用层：只读取 runtime 的最终输出 pose 并写入 Transform；它不做滤波、门控、网络收发或 recovery。

## 当前 policy 结构

每个对比变体由一个 `PoseToAnchorRuntime` 和一个 `AnchorPolicyHost` 驱动。`AnchorPolicyHost` 组合：

- 一个 `MotionModel`：`ConstantVelocityModel`、`KalmanModel` 或 `OneEuroModel`。
- 一个 `SmoothingStrategy`：`RawPassthroughStrategy`、`BlendStrategy` 或 `DelayedInterpStrategy`。
- 可选 score gate：用于拒绝低可靠分或过大跳变的坏观测。
- 可选 `EgoAnchorStaticLockModule`：EgoAnchor 静止锚定层，挂载并启用才算完整方法。

baseline 与 EgoAnchor 的区别不是旧式模块三分法，而是同一组 `MotionModel × SmoothingStrategy` 上是否叠加 score gate 和 static lock。

## 推荐挂载

每个方法或 baseline 用独立 GameObject，避免共享滤波状态。

```text
AnchorObject_raw
  PoseToAnchorRuntime
  AnchorPolicyHost
  ConstantVelocityModel
  RawPassthroughStrategy
  DynamicObjectAnchor

AnchorObject_kalman_blend
  PoseToAnchorRuntime
  AnchorPolicyHost
  KalmanModel
  BlendStrategy
  DynamicObjectAnchor

AnchorObject_egoanchor
  PoseToAnchorRuntime
  AnchorPolicyHost
  KalmanModel 或 OneEuroModel
  BlendStrategy 或 DelayedInterpStrategy
  EgoAnchorStaticLockModule
  DynamicObjectAnchor
```

场景绑定要点：

1. `AnchorRuntimeHub.runtimes` 绑定所有需要同时比较的 `PoseToAnchorRuntime`。
2. 每个 `PoseToAnchorRuntime.policyHost` 指向自己的 `AnchorPolicyHost`。
3. 每个 `AnchorPolicyHost.motionModel` 和 `smoothingStrategy` 指向同一物体上的对应组件。
4. 若使用 EgoAnchor 静止锁，将 `EgoAnchorStaticLockModule` 拖入 `staticLockModule`，并保持 `lockEnabled=true`。
5. `DynamicObjectAnchor.runtime` 指向同一个 `PoseToAnchorRuntime`。
6. `AnchorEvalRecorder.recordedRuntimes` 同时绑定 runtime 和实际显示输出的 `anchorTransform`。

## 对比组合

建议论文实验至少保留这些标签：

| label | MotionModel | SmoothingStrategy | static lock | 目的 |
| --- | --- | --- | --- | --- |
| `raw` | `ConstantVelocityModel` | `RawPassthroughStrategy` | 关 | 原始低频观测零阶保持 |
| `kalman_blend` | `KalmanModel` | `BlendStrategy` | 关 | 零延迟平滑 baseline |
| `oneeuro_blend` | `OneEuroModel` | `BlendStrategy` | 关 | 常用交互滤波 baseline |
| `kalman_interp` | `KalmanModel` | `DelayedInterpStrategy` | 关 | 延迟插值 baseline |
| `egoanchor` | 与选定 baseline 相同 | 与选定 baseline 相同 | 开 | EgoAnchor 静止锚定方法 |

RQ1 的 arrival-time 对照应只比较 `frame_aligned_raw` 和 `arrival_time_raw`，不要混入滤波、score gate 或 recovery。

## 关键语义

- `MeasurementTimeSeconds` 优先使用采集时刻时间。policy 不能把消息到达时间当观测时间。
- baseline 默认不使用 reliability score；需要 score-aware 版本时应另起 label。
- `RawPassthroughStrategy` 是真正 raw：不外推、不插值，只输出最近一帧观测。
- `BlendStrategy` 做零延迟外推和残差融合。
- `DelayedInterpStrategy` 使用延迟目标时刻和控制点插值；Hermite 切线有弦长限幅，避免急停过冲。
- static lock 是 regime-switching 稳定器，不是低通滤波器。锁定时输出 `lockedPose`，解锁后用接缝残差平滑回到 smoothing 输出。

## Eval 字段

Unity render 日志当前字段是：

```text
has_output_pose
output_pos
output_rot
motion_model
smoothing_strategy
gate
anchor_pose_source
```

不要恢复旧的 `has_stable / stable_pos / stable_rot` 字段。Python eval report 中的 `stable_rows` 只是汇总表里“有可评估输出 pose 的行数”这一统计名，不是 JSONL 输入字段。

## Recovery

低分或 track-loss 自动 reacquire 由 `AnchorRuntimeHub` 统一 fan-in。leaf runtime 或 policy 只暴露请求意图，不自持 command client。`CommandAck.accepted=true` 只表示 Python 接受命令，不表示已经完成 reset/reacquire。

RQ2 比较滤波和静止锁时应关闭 recovery；RQ3 再单独比较 recovery disabled、timeout-only 和 score-aware reacquire。

## 常见排查

- runtime 收到 pose 但物体不动：先查 `PoseToAnchorRuntime.policyHost`，再查 host 的 `motionModel`、`smoothingStrategy` 和 `DynamicObjectAnchor.runtime`。
- 评估输出为空：检查 `AnchorEvalRecorder.recordedRuntimes[*].anchorTransform` 是否绑定实际显示物体。
- 多个变体状态互相影响：确认每个 runtime 使用独立的 `AnchorPolicyHost` 和模型/策略组件实例。
- baseline 看起来用了 score：确认 `enableScoreGate=false`，且没有挂启用状态的 `EgoAnchorStaticLockModule`。
- arrival-time 对照为空：检查 `FramePoseHistory` 是否有 latest camera pose，以及 recorder 是否记录 primary runtime。

## 验证命令

Unity 主线编译：

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

离线升采样仿真：

```powershell
dotnet run --project EgoAnchor_Tools3\AnchorUpsampleSim3.csproj -c Release -- --session EgoAnchor_Python\data\eval\<session> --zoom-start 8 --zoom-end 13
```

Python eval 单测：

```powershell
cd EgoAnchor_Python
pixi run python -m unittest discover -s eval -p "test_*.py"
```
