# EgoAnchor Unity anchor policy 使用指南

本文档记录当前 Unity 侧 anchor policy 的挂载方式、baseline 组合、离线回放和排查方法。正式路径是每个对比物体一套 `PoseToAnchorRuntime + AnchorPolicyHost + Gate/Estimator/Output module + DynamicObjectAnchor`。

## 当前流程

Python、协议、ZMQ/NATS 和 frame alignment 不变。Unity 收到 `PoseResult` 后仍然先用 `frame_id` 回查采集时刻的 camera pose，再把 Python OpenCV camera-space pose 转成 Unity world pose。

anchor 侧改成两级时钟：

```text
pose 到达时钟:
  PoseToAnchorRuntime -> AnchorPolicyHost.AcceptPose
  -> GateModule.Evaluate
  -> EstimatorModule.Snap / UpdateEstimate

渲染帧时钟:
  PoseToAnchorRuntime.LateUpdate -> AnchorPolicyHost.Advance(now)
  -> EstimatorModule.PredictAt(now)
  -> OutputStageModule.Condition
  -> DynamicObjectAnchor.TryGetStablePose
```

`DynamicObjectAnchor` 现在只读 runtime 的 stable/final pose 并应用 Transform。它没有 Raw/Smoothed 输出模式，也不做滤波、门控、网络或 recovery。

## 模块目录

模块按职责放在四个目录，Unity 侧不再保留 `Policy/Pipeline` 中间层，避免和 Python 感知 pipeline 混名：

```text
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Core
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Gate
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Estimator
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Output
```

共享 DTO 和数学工具在：

```text
Policy/Core
Policy/Estimator/ConstVelocityKalman.cs
```

Inspector 不用 enum 选择策略。`AnchorPolicyHost` 直接引用三个抽象 `MonoBehaviour` 基类字段：

```text
AnchorGateModule
AnchorEstimatorModule
AnchorOutputStageModule
```

具体参数写在模块组件自己的 `[SerializeField]` 字段里。模块内部不得读取 `UnityEngine.Time`；时间只能由 `PoseToAnchorRuntime` / `AnchorPolicyHost` 显式传入。

## 推荐挂载

每个 baseline 或 method 用独立 GameObject，避免共享滤波状态。

```text
AnchorObject_raw_zoh
  PoseToAnchorRuntime
  AnchorPolicyHost
  NullGateModule
  RawEstimatorModule
  PassThroughOutputModule
  DynamicObjectAnchor

AnchorObject_egoanchor_full
  PoseToAnchorRuntime
  AnchorPolicyHost
  ScoreJumpGateModule
  EgoAnchorEstimatorModule
  StaticLockRateLimitOutputModule
  DynamicObjectAnchor
```

场景绑定要点：

1. `AnchorRuntimeHub.runtimes` 绑定全部 runtime，让同一条 `PoseResult` 同时驱动所有策略。
2. 每个 `PoseToAnchorRuntime` 的 `Policy Host` 指向自己的 `AnchorPolicyHost`。
3. 每个 `AnchorPolicyHost` 的 gate、estimator、output 字段拖入同一物体上的对应 module。
4. `DynamicObjectAnchor.runtime` 指向同一个 `PoseToAnchorRuntime`。
5. `AnchorEvalRecorder.recordedRuntimes` 用正式 label 记录每个 runtime 和 Transform。

## 正式策略 label

| label | Gate | Estimator | Output | score |
| --- | --- | --- | --- | --- |
| `raw_zoh` | `NullGateModule` | `RawEstimatorModule` | `PassThroughOutputModule` | 忽略 |
| `lowpass_predict` | `NullGateModule` | `LowPassEstimatorModule` | `PassThroughOutputModule` | 忽略 |
| `kalman_cv` | `NullGateModule` | `KalmanEstimatorModule` | `PassThroughOutputModule` | 忽略 |
| `oneeuro_vanilla` | `NullGateModule` | `OneEuroEstimatorModule` | `PassThroughOutputModule` | 忽略 |
| `egoanchor_no_static` | `ScoreJumpGateModule` | `EgoAnchorEstimatorModule` | `PassThroughOutputModule` | 使用 |
| `egoanchor_full` | `ScoreJumpGateModule` | `EgoAnchorEstimatorModule` | `StaticLockRateLimitOutputModule` | 使用 |

baseline 不读取 reliability score。若以后要做 score-aware Kalman，必须另起 label，例如 `kalman_score_adaptive`，不要覆盖 `kalman_cv`。

## 旋转实现约定

所有 estimator 都必须同时处理 position 和 rotation。

- `KalmanEstimatorModule`：平移是常速度 Kalman；旋转在四元数参考姿态的 Log/Exp 切空间中过滤，状态包含角速度。
- `OneEuroEstimatorModule`：平移按 One Euro 的速度自适应截止频率过滤；旋转同样在四元数切空间中过滤，不使用 Euler 角。
- `LowPassEstimatorModule`、`EgoAnchorEstimatorModule`：预测和输出都同时更新平移与旋转。

实现时核对的公开算法来源：Kalman 原始线性滤波/预测论文，以及 Casiez、Roussel、Vogel 的 One Euro Filter 论文与官方页面。工程里做了 Unity 输入输出适配：world pose 输入、capture/render 时间显式传入、rotation 用 quaternion tangent-space 表达。

## 离线分析回放

主力分析回放是 headless dotnet，不启动 Unity Editor。它读取 `offline_data` 的 `aligned_raw`，用同一份 world pose 输入重跑全部策略。

```powershell
dotnet run --project EgoAnchor_Tools\anchor_replay\AnchorReplay.csproj -- --session EgoAnchor_Python\data\eval\offline_data --out EgoAnchor_Python\data\eval\offline_data\anchor_replay
```

输出：

```text
anchor_replay_output.jsonl
anchor_replay_summary.csv
anchor_replay_config.json
```

再接 Python eval：

```powershell
cd EgoAnchor_Python
pixi run python -m eval.run_eval --session-dir .\data\eval\offline_data --output-log .\data\eval\offline_data\anchor_replay\anchor_replay_output.jsonl --report-dir .\data\eval\offline_data\anchor_replay\report --only tables
```

当前 `offline_data` 没有 condition spans，所以第一轮只用于检查字段、时序、公平 baseline 和明显 bug。不要从这一个 fixture 得出论文级结论。

## Unity 回放和视频

Unity 内有两类回放组件，目的不同。

`RecordedAnchorReplaySource` / `RecordedAnchorReplayController`：读取录制日志中的 `aligned_raw`，向指定 `PoseToAnchorRuntime` 注入 replay observation，用于在 Unity 里看 pipeline 行为。定量指标仍以 headless `anchor_replay` 为准。

`AnchorTrajectoryPlayer`：只播放日志里已经录出的 `stable_pos/stable_rot`。这是 supplementary video 的主路径，用来复现已有轨迹，不参与算法评估。

## Recovery

`AnchorRecoveryController` 是正交层，放在 `Runtime/`。它只观察 runtime 诊断并通过 `AnchorCommandClient` / `IAnchorCommandSender` 发送 reacquire command，不参与 Gate/Estimator/Output，也不把 `CommandAck.accepted=true` 当作恢复完成。`IAnchorCommandSender` 是 `AnchorCommandClient.cs` 内的窄测试契约，不单独占文件。

固定触发 reason：

```text
auto_reacquire_low_score
auto_reacquire_lost
auto_reacquire_no_pose
input_not_ready_wait
```

RQ2 比较滤波/同步策略时应关闭 recovery。RQ3 再单独比较 recovery disabled、timeout-only 和 score-aware reacquire。

## RQ1 arrival-time 诊断

默认 anchor 仍使用 capture-time frame alignment。新增的 `arrival_time_raw` 只是诊断字段，用 pose 到达/渲染时刻的 latest camera pose 做对照。

RQ1 只比较：

```text
frame_aligned_raw
arrival_time_raw
```

不要把 filter、score gate 或 recovery 混入 RQ1。

## 常见排查

- runtime 收到 pose 但物体不动：先看 `PoseToAnchorRuntime.policyHost` 是否绑定，再看 host 的 gate/estimator/output 三个 module 字段是否为空。
- `raw_zoh` 不输出：确认它也走 `AnchorPolicyHost + RawEstimatorModule + PassThroughOutputModule`，不要找 Transform 应用层输出模式。
- 多个物体输出完全一样或状态互相影响：检查是否多个 runtime 共用同一个 `AnchorPolicyHost` 或 estimator module。每个 runtime 需要独立模块实例。
- baseline 看起来用到了 score：检查 gate 是否是 `NullGateModule`，estimator 是否是 vanilla baseline module。
- policy 每帧不更新：确认 `PoseToAnchorRuntime.policyHost` 已绑定，且 `AnchorPolicyHost.Advance(now)` 没有因为缺模块抛错。
- arrival-time 诊断为空：检查 `FramePoseHistory.TryGetLatest(...)` 是否有缓存，以及 `AnchorEvalRecorder` 是否记录 primary runtime。

## 验证命令

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
dotnet run --project EgoAnchor_Tools\eval_writer_smoke\EvalWriterSmoke.csproj
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore

cd EgoAnchor_Python
pixi run python -m unittest discover -s eval -p "test_*.py"
```

离线 fixture 验证：

```powershell
dotnet run --project EgoAnchor_Tools\anchor_replay\AnchorReplay.csproj -- --session EgoAnchor_Python\data\eval\offline_data --out EgoAnchor_Python\data\eval\offline_data\anchor_replay

cd EgoAnchor_Python
pixi run python -m eval.run_eval --session-dir .\data\eval\offline_data --output-log .\data\eval\offline_data\anchor_replay\anchor_replay_output.jsonl --report-dir .\data\eval\offline_data\anchor_replay\report --only tables
```

清理检查：

```powershell
rg -n "PoseOutputMode|AnchorPoseSource|RawAnchorPoseSource|StableAnchorPoseSource|Pipeline\\Modules|Pipeline/Modules" EgoAnchor_Unity\Assets\Scripts\EgoAnchor
rg -n "Time\\." EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy
```

第一条不应命中已废弃的输出模式和 PoseSource 包装层；第二条不应命中 policy 模块读取 Unity 时间。
