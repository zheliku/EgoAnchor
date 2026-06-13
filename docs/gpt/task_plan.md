# EgoAnchor Anchor Policy One Euro 重构实施计划

> **给后续执行 agent：** 实施本计划前必须使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`，逐个 checkbox 执行。不要跳过 smoke、Unity build 和离线回放验证。

**目标：** 把 Python 约 5Hz 的 camera-space pose + reliability score，稳定扩展成 Unity 每渲染帧连续输出的 world anchor pose。静止物体不跟随头显轻微晃动；连续移动时轨迹平滑、跟手；低分、Lost、no-pose 能触发受控 reacquire。

**架构：** 不改 Python、Protobuf、ZMQ/NATS、frame alignment、raw/processor baseline。Unity policy 内部改为简单 score/jump gate + One Euro 滤波 + 静止输出锁 + 既有 `AnchorStateMachine` 生命周期；自动重获取放到独立 `AnchorRecoveryController`，不塞进网络层或 Transform 输出层。

**技术栈：** Unity C#、plain C# policy core、`EgoAnchor_Tools/anchor_policy_smoke`、`dotnet build`、`EgoAnchor_Python/eval` JSONL 离线回放。

---

## 1. 对 `补充.md` 的判断

结论：大方向合理，但不能照单全收。

采纳的部分：

| 建议                                                 | 处理                                                                                  |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 用 One Euro 作为核心滤波算法                         | 采纳。它比当前 Kalman + 多层 gate 更贴合低频、低噪声、需要跟手的 pose stream。        |
| 先写 smoke gate，再改实现                            | 采纳。现有 `anchor_policy_smoke` 是最重要的回归入口，必须先让旧实现在新目标下失败。 |
| 用 `20260613_012345_controller_right` 做真实回放   | 采纳。默认参数先用这份数据验证，再固化到 Unity。                                      |
| 自动 reacquire 独立成组件                            | 采纳。command bridge 应独立于 policy core。                                           |
| 同步 `ANCHOR_CONTROLLER_GUIDE.md` 和 `AGENTS.md` | 采纳，但不得修改 `USER-MAINTAINED-REQUIREMENTS` 区块。                              |

需要改写或拒绝的部分：

| 建议                                                     | 判断   | 理由                                                                                                                                       |
| -------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 删除 `AnchorStateMachine.cs`                           | 不采纳 | 它已经承接 reset/reacquire/pause/resume/server lost/error/coast/lost。删除会把生命周期逻辑挤回 `PolicyController` 或 runtime，边界更差。 |
| `PoseToAnchorRuntime` 直接持有 `AnchorCommandClient` | 不采纳 | runtime 的职责是 pose-to-anchor，不应直接发 command。自动重获取放到 `AnchorRecoveryController`，通过公开诊断状态观察 runtime。           |
| 完全不要静止锁                                           | 不采纳 | One Euro 能压噪，但不能保证慢速 residual slip 不被逐渐吸收。用户要求“物体静止时尽可能保持静止”，需要一个很小的输出锁。                   |
| 保留旧 `MotionStateClassifier`                         | 不采纳 | 旧分类器依赖 innovation/Kalman 语义，且 Static/Moving 翻转是抖动来源。删除旧文件，改成小型 `AnchorStaticLock`，只管静止输出锁。          |
| 新建 `AnchorTracker.cs` 替换 `AnchorPoseFilter.cs`   | 不采纳 | 保留 `AnchorPoseFilter.cs` 文件名和公开角色，减少 scene、csproj、诊断层连锁改动；内部重写为 One Euro。                                   |

融合后的最终策略：

```text
PoseResult
  -> CameraPoseFrameAligner 采集时刻 world pose（不改）
  -> PolicyController.AcceptPose
       -> score/flag/stale/jump 简单判定
       -> AnchorPoseFilter(One Euro) 提交测量
       -> AnchorStaticLock 只控制静止显示输出
       -> AnchorStateMachine 维护生命周期

LateUpdate
  -> PolicyController.Advance(now)
       -> AnchorPoseFilter.PredictAt(now)
       -> static lock / output speed limit
       -> AnchorPolicyOutput

AnchorRecoveryController
  -> 观察 PoseToAnchorRuntime 公开状态
  -> 持续低分、Lost、no-pose 后通过 AnchorCommandClient.ReacquireAsync 请求 Python register
```

## 2. 不变边界

- 不改 Python 输出语义：`PoseResult.pose_matrix_cv_camera` 仍是左目 OpenCV camera-space object pose。
- 不改协议字段，不重新生成 proto。
- 不改 `FramePoseHistory`、`CameraPoseFrameAligner`、`AnchorPoseTransform` 的 frame-aligned 坐标转换。
- 不用 pose 到达时 HMD pose 代替采集帧 camera pose。
- raw、low-pass、Kalman processor baseline 保留，用于论文对照。
- policy 模式继续不经过 processor chain。
- `PolicyController` 公开入口保留：`AcceptPose`、`Advance`、`NotifyReset`、`NotifyReacquire`、`NotifyPause`、`NotifyResume`、`NotifyError`、`NotifyLost`、`Clear`。
- `AnchorPolicyDecision`、`AnchorPolicyOutput`、`AnchorState`、`AnchorMotionState` 对外类型保留。`AnchorMotionState` 移到独立文件，只作为诊断和输出标签。
- `PoseToAnchorRuntime` 不直接发 NATS command，只同步 policy 诊断。

## 3. 文件级变更清单

### 新建

| 文件                                                                             | 职责                                                                                             |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMotionState.cs`         | 保存 `AnchorMotionState` enum，从旧 `MotionStateClassifier.cs` 中拆出。                      |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/OneEuroFilter.cs`             | One Euro 数学工具，包含标量、`Vector3`、四元数 log/exp/最短弧处理。plain C#，不读取 `Time`。 |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorStaticLock.cs`          | 小型静止输出锁。用测量窗口散布慢进静止，用释放阈值快出静止，不依赖 Kalman innovation。           |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs` | 自动 reacquire bridge。观察 runtime 诊断，通过 `AnchorCommandClient` 发 command。              |
| `EgoAnchor_Python/eval/tools/replay_one_euro_policy.py`                        | 离线回放当前 eval session，复刻 Unity One Euro 默认参数，输出 jitter/continuity/GT 误差对比。    |

### 改写

| 文件                                                                        | 改动                                                                                                                                        |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyConfig.cs`   | 删除 Kalman、马氏、teleport、soft recovery、旧 static 参数；保留 score gate、One Euro、static lock、前推、断流、reacquire 参数。            |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPoseFilter.cs`     | 保留文件名，内部改为 One Euro 提交态 + 有界前推 + 输出限速。                                                                                |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs`     | 删除 `AnchorMeasurementGate`、`MotionStateClassifier`、`AnchorOutputSmoother` 依赖，编排 config、filter、static lock、state machine。 |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`     | 更新参数热更与诊断字段：residual、accepted score、predict ahead、static lock 状态。                                                         |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs` | 同步新诊断字段；不接入 command client。                                                                                                     |
| `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`                          | 改成目标行为 gate，保留原有 frame alignment、runtime hub、status、processor skip smoke。                                                    |
| `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`            | 加入新文件，移除旧 gate/smoother/classifier compile include。                                                                               |
| `ANCHOR_CONTROLLER_GUIDE.md`                                              | 更新为 One Euro policy 使用说明和参数表。                                                                                                   |
| `AGENTS.md`                                                               | 只更新用户维护区块之外的当前主线事实。                                                                                                      |

### 删除

| 文件                                                                                      | 删除理由                                                                                    |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs` 和 `.meta` | 马氏 gate、软恢复、瞬移恢复在当前数据里基本不触发，且与 One Euro 目标重复。                 |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs` 和 `.meta`  | 输出平滑并入 `AnchorPoseFilter`，避免两层平滑互相耦合。                                   |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/MotionStateClassifier.cs` 和 `.meta` | 旧 Static/Moving 分类依赖 Kalman innovation，删除后由 `AnchorStaticLock` 承担静止输出锁。 |

保留：

- `AnchorStateMachine.cs`
- `AnchorPoseFilter.cs`
- `AnchorPolicyDecision.cs`
- `AnchorPolicyOutput.cs`
- `AnchorObservation.cs`
- raw/processor baseline 脚本

## 4. 核心算法

### 4.1 One Euro

每个标量通道维护 raw 上一值、滤波值、滤波导数和时间戳。

```csharp
float dt = Mathf.Max((float)(timeSeconds - lastTimeSeconds), 1e-4f);
float derivative = (raw - rawPrevious) / dt;
derivativeHat = Mathf.Lerp(derivativeHat, derivative, Alpha(derivativeCutoff, dt));

float cutoff = minCutoff + beta * Mathf.Abs(derivativeHat);
float alpha = Alpha(cutoff, dt) * scoreWeight;
valueHat = Mathf.Lerp(valueHat, raw, Mathf.Clamp01(alpha));
rawPrevious = raw;
lastTimeSeconds = timeSeconds;
```

`Alpha`：

```csharp
float tau = 1f / (2f * Mathf.PI * Mathf.Max(cutoff, 1e-4f));
return 1f / (1f + tau / Mathf.Max(dt, 1e-4f));
```

位置：3 个标量 One Euro，导数就是线速度。

旋转：不用欧拉角。用四元数最短弧：

1. 将新测量四元数与上一 raw 或 filtered 四元数对齐到同一半球。
2. `Log(Inverse(rawPrevious) * raw) / dt` 得到 raw angular velocity。
3. 对 angular velocity 向量低通。
4. `cutoff = rotationMinCutoff + rotationBeta * angularVelocityHat.magnitude`。
5. `residual = Log(Inverse(rotationHat) * raw)`。
6. `rotationHat = rotationHat * Exp(residual * alpha * scoreWeight)`。

### 4.2 简单 gate

`PolicyController.AcceptPose` 只保留必要判断：

1. Paused：`Hold/paused`。
2. `HasAlignedPose=false`：`Hold/no_pose` 或 `Hold/align_failed`。
3. 测量时间乱序或超龄：`Reject/stale_measurement`。
4. `flags` 含 `invalid_pose`：`Reject/invalid_pose`。
5. 重定位 pose 且 score >= `relocalizeScoreMin`：`Snap/relocalize_accept`。
6. 首帧 score >= `startScoreMin`：`Snap/first_accept`。
7. 已有 state 且 score < `holdScoreMin`：`Hold/score_hold`。
8. 已有 state 且 score < `trackScoreMin`：`Hold/score_hold`。
9. 与当前预测 pose 的位置/旋转残差超过 `maxJumpMeters/maxJumpDegrees`：`Reject/jump_reject`。
10. 其它 accepted：`Accept/score_accept`，更新 One Euro。

不再保留马氏距离、协方差、soft recovery、teleport recovery、stuck recovery。

### 4.3 静止输出锁

静止锁只处理显示输出，不污染 One Euro 提交态。

进入静止：

- 最近 `staticWindowSeconds` 内 accepted pose 数量 >= `staticMinSamples`。
- 窗口位置散布 <= `staticRadiusMeters`。
- 窗口旋转散布 <= `staticRotationDegrees`。
- 当前速度 <= `staticSpeedMetersPerSecond`，角速度 <= `staticAngularSpeedDegreesPerSecond`。

静止时输出：

- 关闭前推。
- 输出保持进入静止时的 lock pose。
- 如果滤波均值和 lock pose 的偏差仍在释放阈值内，只用 `staticCenterTauSeconds` 很慢地归中。

退出静止：

- 位置残差 > `staticReleaseMeters`，或旋转残差 > `staticReleaseDegrees`。
- 退出后立刻按运动模式输出，避免真移动时拖尾。

`AnchorMotionState.Static/Moving/Unknown` 只用于 `AnchorPolicyOutput`、Inspector 和 eval 诊断，不再作为旧式多分支控制器。

### 4.4 有界前推

`Advance(now)` 使用 capture-time 测量时间轴和 render-time 输出时间轴：

```text
predictAhead = clamp(now - stateTimeSeconds, 0, maxPredictAheadSeconds)
predictedPos = filteredPos + velocity * predictAhead
predictedRot = filteredRot * Exp(angularVelocity * rotationPredictAhead)
```

约束：

- 静止锁开启时前推为 0。
- 旋转前推使用独立上限 `maxRotationPredictAheadSeconds`，默认小于位置前推。
- Coasting 只短时前推；超过 `maxCoastSeconds` 后冻结输出，状态机进入 `FrozenUncertain` 或 `Lost`。
- 输出层用 `maxOutputSpeedMps` 和 `maxOutputAngularSpeedDps` 限制单帧变化，避免一帧跳到远处。

### 4.5 自动 reacquire

`AnchorRecoveryController` 是 MonoBehaviour，字段默认：

| 参数                    | 默认 | 说明                                                                    |
| ----------------------- | ---: | ----------------------------------------------------------------------- |
| `autoReacquire`       | true | 总开关。                                                                |
| `reacquireOnLowScore` | true | 持续低分触发。                                                          |
| `reacquireOnLost`     | true | Unity anchor 进入 Lost 后触发。                                         |
| `reacquireOnNoPose`   | true | 持续 no-pose/align_failed 后触发，但 `input_not_ready` 只计时不发送。 |
| `lowScoreThreshold`   | 0.25 | 自动重获取的低分阈值。                                                  |
| `lowScoreSeconds`     |  0.8 | 连续低分时长。                                                          |
| `lostSeconds`         |  0.3 | Lost 后等待时长。                                                       |
| `noPoseSeconds`       |  1.0 | no-pose 后等待时长。                                                    |
| `cooldownSeconds`     |  3.0 | 两次 command 的最短间隔。                                               |
| `clearTrackingFirst`  | true | 默认让 Python 清掉旧 tracking 再重新检测。                              |

触发时调用：

```csharp
await commandClient.ReacquireAsync(
    ReacquireAnchorRequest.Types.ReacquireMode.ForceDetect,
    clearTrackingFirst,
    string.Empty,
    0.0,
    reason,
    destroyCts.Token);
```

限制：

- command in-flight 时不重复发送。
- 冷却未结束时不重复发送。
- `LatestHeartbeatInputReady=false` 时不发 reacquire，只记录 `input_not_ready_wait`，因为 Python 没有有效相机输入时 register 没意义。
- 组件只观察 `PoseToAnchorRuntime`，不改 Transform、不解码 PoseResult、不直接重置 Python 模型。

## 5. 新参数表

`AnchorPolicyConfig` 保留以下字段。Unity 字段必须有中文 XML summary 和 `[Tooltip]`。

| 分组     | 参数                                   |  默认 | 说明                                     |
| -------- | -------------------------------------- | ----: | ---------------------------------------- |
| 评分     | `startScoreMin`                      |  0.35 | 冷启动第一帧接受下限。                   |
| 评分     | `trackScoreMin`                      |  0.20 | 已有 anchor 后接受普通 TRACK 的下限。    |
| 评分     | `holdScoreMin`                       |  0.12 | 低于该值只 hold/reject，不更新滤波器。   |
| 评分     | `relocalizeScoreMin`                 |  0.12 | REGISTER/RE_REGISTER snap 接受下限。     |
| One Euro | `positionMinCutoff`                  |   1.0 | 静止位置平滑强度，越小越稳。             |
| One Euro | `positionBeta`                       |  0.65 | 位置速度响应，越大越跟手。               |
| One Euro | `rotationMinCutoff`                  |   1.0 | 静止旋转平滑强度。                       |
| One Euro | `rotationBeta`                       |  0.55 | 旋转速度响应。                           |
| One Euro | `derivativeCutoff`                   |   1.0 | 速度估计低通 cutoff。                    |
| One Euro | `minScoreWeight`                     |  0.25 | 已通过 gate 的测量参与滤波时的最低权重。 |
| 静止锁   | `staticWindowSeconds`                |  0.60 | 判静止的测量窗口时长。                   |
| 静止锁   | `staticMinSamples`                   |     3 | 判静止最少 accepted pose 数。            |
| 静止锁   | `staticRadiusMeters`                 | 0.012 | 窗口位置散布上限。                       |
| 静止锁   | `staticRotationDegrees`              |   2.5 | 窗口旋转散布上限。                       |
| 静止锁   | `staticSpeedMetersPerSecond`         | 0.025 | 进入静止的速度上限。                     |
| 静止锁   | `staticAngularSpeedDegreesPerSecond` |   8.0 | 进入静止的角速度上限。                   |
| 静止锁   | `staticReleaseMeters`                | 0.020 | 静止锁释放位置阈值。                     |
| 静止锁   | `staticReleaseDegrees`               |   3.0 | 静止锁释放旋转阈值。                     |
| 静止锁   | `staticCenterTauSeconds`             |  0.35 | 静止时向滤波均值慢速归中时间常数。       |
| 输出     | `maxPredictAheadSeconds`             |  0.14 | 位置前推上限。                           |
| 输出     | `maxRotationPredictAheadSeconds`     |  0.08 | 旋转前推上限。                           |
| 输出     | `movingOutputTauSeconds`             | 0.035 | 运动输出追踪时间常数。                   |
| 输出     | `maxOutputSpeedMps`                  |   3.0 | 输出最大线速度。                         |
| 输出     | `maxOutputAngularSpeedDps`           |   720 | 输出最大角速度。                         |
| 跳变     | `maxJumpMeters`                      |  0.80 | 位置外点绝对门。                         |
| 跳变     | `maxJumpDegrees`                     |   120 | 旋转外点绝对门。                         |
| 断流     | `coastGraceSeconds`                  |  0.30 | 正常消息间隔保护。                       |
| 断流     | `maxCoastSeconds`                    |  0.45 | 短时断流外推上限。                       |
| 断流     | `lostTimeoutSeconds`                 |   2.0 | 无可靠 pose 进入 Lost 的时长。           |
| 断流     | `maxMeasurementAgeSeconds`           |   1.0 | 可接受测量最大年龄。                     |

`Validate()` 只做 clamp 和少量关系约束：

- score 阈值限制到 0..1。
- `holdScoreMin <= trackScoreMin <= startScoreMin`。
- cutoff、tau、timeout 必须大于 0。
- `staticReleaseMeters >= staticRadiusMeters`。
- `staticReleaseDegrees >= staticRotationDegrees`。
- `maxRotationPredictAheadSeconds <= maxPredictAheadSeconds`。
- `lostTimeoutSeconds >= maxCoastSeconds >= coastGraceSeconds`。

## 6. 实施任务

### Task 1：先改 smoke，定义目标行为

**Files**

- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] 保留现有 frame alignment、NATS、runtime hub、status event、processor skip 相关 smoke。
- [ ] 删除或改写旧 Mahalanobis、soft recovery、teleport recovery 专属断言。
- [ ] 新增 `AssertOneEuroStaticJitterSuppression()`：5Hz 小噪声输入，渲染帧推进，warmup 后输出 RMS <= 输入 RMS 的 0.4。
- [ ] 新增 `AssertStaticLockSuppressesResidualSlip()`：输入 1 到 2cm 的慢速 residual slip，静止锁期间 stable pose 不应跟随漂走。
- [ ] 新增 `AssertStaticLockReleasesOnRealMotion()`：超过 `staticReleaseMeters/staticReleaseDegrees` 后 2 到 3 帧内退出静止并跟随。
- [ ] 新增 `AssertLowRateMotionIsContinuous()`：0.2s 一帧、0.35m/s 匀速平移，渲染帧输出不能出现长时间零增量，`maxZeroRun <= 4`。
- [ ] 新增 `AssertLowRateRotationIsContinuous()`：0.2s 一帧、45deg/s yaw，渲染帧输出连续旋转，`maxZeroRun <= 4`。
- [ ] 新增 `AssertLowScoreHoldsWithoutDragging()`：低分测量不更新滤波器、不拖动输出。
- [ ] 新增 `AssertAbsoluteJumpRejected()`：高分但超过 `maxJumpMeters/maxJumpDegrees` 的单帧外点被 reject。
- [ ] 新增 `AssertNoPoseCoastsThenFreezesThenLost()`：短断流 coast，超过上限 freeze，超过 `lostTimeoutSeconds` Lost。
- [ ] 新增 `AssertRecoveryControllerTypeExists()`：reflection 确认 `AnchorRecoveryController` 有 `runtime`、`commandClient`、cooldown/in-flight 字段。
- [ ] 运行：

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected：FAIL。失败应来自新目标或待新增类型，不应来自旧集成 smoke 崩坏。

### Task 2：写离线 One Euro 回放

**Files**

- Create: `EgoAnchor_Python/eval/tools/replay_one_euro_policy.py`

- [ ] 新建 `EgoAnchor_Python/eval/tools` 目录。
- [ ] 脚本只读 eval session，不导入 Unity、不导入 runtime、不启动模型。
- [ ] 用 numpy 实现 `alpha`、四元数 normalize/mul/inv/log/exp/sign-align。
- [ ] 从 `data/eval/20260613_012345_controller_right` 读取 Unity 输出 JSONL，提取 aligned raw pose、score、frame/capture/render 时间、旧 stable pose、可用 GT。
- [ ] 用与 Unity 同名参数复刻 One Euro + static lock + predict ahead。
- [ ] 输出：

```text
one_euro_replay_summary
measurements=...
render_rows=...
raw_jitter_mm=...
old_policy_jitter_mm=...
one_euro_jitter_mm=...
raw_rmse_mm=...
old_policy_rmse_mm=...
one_euro_rmse_mm=...
one_euro_max_zero_run=...
```

- [ ] 运行：

```powershell
cd EgoAnchor_Python
pixi run python .\eval\tools\replay_one_euro_policy.py --session .\data\eval\20260613_012345_controller_right
```

Expected：脚本跑完。若 `one_euro_rmse_mm > raw_rmse_mm * 1.05` 或 `one_euro_max_zero_run > 4`，先调默认参数，再写 Unity 实现。

### Task 3：精简 `AnchorPolicyConfig`

**Files**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyConfig.cs`

- [ ] 按第 5 节字段表替换旧字段。
- [ ] 删除 Kalman/协方差字段、马氏 gate 字段、soft recovery、teleport recovery、stuck recovery、旧 output smoother 参数。
- [ ] 每个字段补中文 XML summary 和中文 `[Tooltip]`，写清单位和调参方向。
- [ ] 实现新的 `Validate()` clamp。
- [ ] 运行：

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected：FAIL，暴露旧引用。下一任务开始修复。

### Task 4：新增 One Euro 数学工具和运动状态 enum

**Files**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMotionState.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/OneEuroFilter.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] 从 `MotionStateClassifier.cs` 拆出 `AnchorMotionState` enum 到独立文件，保留 `Unknown/Static/Moving`。
- [ ] 新增 `OneEuroMath`：`Alpha`、`Normalize`、`AlignSign`、`Multiply`、`Inverse`、`Log`、`Exp`。
- [ ] 新增 `OneEuroFloat`：`Reset`、`Snap`、`Update`、`Value`、`Derivative`。
- [ ] 新增 `OneEuroVector3`：内部 3 个 `OneEuroFloat`，暴露 `Value`、`Velocity`。
- [ ] 新增 `OneEuroRotation`：维护 `Rotation`、`AngularVelocityRad`，使用四元数 log/exp 更新。
- [ ] `OneEuroFilter.cs` 内所有类写中文 summary；不访问 `UnityEngine.Time`。
- [ ] smoke csproj 加入新文件 include。
- [ ] 运行：

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected：仍 FAIL，但新 helper 自身不应有编译错误。

### Task 5：新增 `AnchorStaticLock`

**Files**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorStaticLock.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] 实现 accepted pose 滑动窗口，保存 pose 和时间。
- [ ] `ObserveAccepted(Pose measured, Pose filtered, Vector3 velocity, Vector3 angularVelocityRad, double timeSeconds)` 更新窗口和锁状态。
- [ ] `IsStatic`、`MotionState`、`LockedPose`、`PositionSpreadMeters`、`RotationSpreadDegrees` 暴露诊断。
- [ ] 静止慢进：窗口时长、样本数、位置散布、旋转散布、速度、角速度都满足才锁定。
- [ ] 静止快出：filtered/measured 相对 lock pose 超过释放阈值立即释放。
- [ ] `Advance(Pose target, double nowSeconds)` 在锁定时返回 lock pose 或慢速归中 pose。
- [ ] `Reset()` 清空窗口和锁。
- [ ] 加入 smoke csproj。

Expected：静止锁逻辑可以被 smoke 直接驱动，不依赖 `PolicyController`。

### Task 6：重写 `AnchorPoseFilter`

**Files**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPoseFilter.cs`

- [ ] 删除 `InnovationStats`、`ScalarKalman2`、协方差、measurement/process noise、ZUPT、freeze coast 旧实现。
- [ ] 保留 `AnchorPredictMode`、`HasState`、`StateTimeSeconds`、`StatePose`、`Velocity`、`AngularVelocityRad`、`AngularSpeedDps`。
- [ ] 新状态字段使用 `OneEuroVector3`、`OneEuroRotation`、`AnchorStaticLock`。
- [ ] 实现：

```csharp
public void ApplyConfig(AnchorPolicyConfig newConfig);
public void Reset();
public void Snap(Pose pose, double timeSeconds);
public Pose Correct(Pose measured, double timeSeconds, float score);
public Pose PredictAt(double timeSeconds, AnchorPredictMode mode);
public Pose AdvanceOutput(Pose target, AnchorPredictMode mode, double nowSeconds);
public void Freeze(double nowSeconds);
```

- [ ] `Correct` 中 score 只作为已接受测量的滤波权重，不再做噪声模型。
- [ ] `PredictAt` 中静止锁开启时前推为 0；Track/Coast 使用不同前推上限。
- [ ] `AdvanceOutput` 负责静止锁、运动输出 tau、最大速度/角速度限幅。
- [ ] 运行：

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected：可能 FAIL，因为 `PolicyController` 仍引用旧 API。

### Task 7：重写 `PolicyController`

**Files**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs`

- [ ] 删除字段：`AnchorMeasurementGate gate`、`MotionStateClassifier classifier`、`AnchorOutputSmoother outputSmoother`、`InnovationStats lastInnovation`、`lastREffPos`。
- [ ] 保留字段：`AnchorPolicyConfig config`、`AnchorPoseFilter filter`、`AnchorStateMachine stateMachine`。
- [ ] 新增诊断：`LastResidualMeters`、`LastResidualDegrees`、`LastAcceptedScore`、`LastPredictAheadSeconds`、`MotionState`、`SpeedMps`、`AngularSpeedDps`。
- [ ] `AcceptPose` 按第 4.2 节流程实现。
- [ ] `Advance(nowSeconds)`：
  - 无 filter state：`AnchorPolicyOutput.None(...)`。
  - gap <= `coastGraceSeconds`：Track。
  - gap <= `maxCoastSeconds`：Coast。
  - gap > `maxCoastSeconds`：Freeze/Hold，并让 `AnchorStateMachine.OnMissingPose` 推进到 `FrozenUncertain` 或 `Lost`。
- [ ] `NotifyReset/Reacquire/Pause/Resume/Error/Lost/Clear` 保留，并重置 filter/static lock。
- [ ] `ApplyConfig` 热更参数但不隐式清空稳定 pose，除非字段逻辑必须重建状态机时只重建 lifecycle timeout。
- [ ] 运行：

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected：编译通过后可能有阈值失败。只调默认参数，不恢复旧 gate。

### Task 8：删除旧 gate/smoother/classifier

**Files**

- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs.meta`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs.meta`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/MotionStateClassifier.cs`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/MotionStateClassifier.cs.meta`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] 用 `apply_patch` 删除上述文件。
- [ ] 从 csproj 删除旧 compile include。
- [ ] 确认 `AnchorMotionState.cs` 已被 include。
- [ ] 运行：

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected：smoke PASS，Unity build PASS。允许已有第三方 warning，不允许新增 EgoAnchor policy/runtime error。

### Task 9：更新 policy 诊断

**Files**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`

- [ ] `AnchorPolicyHost` 移除 `LastInnovationPosD2`、`LastREffPos` 等旧诊断。
- [ ] 新增：

```csharp
public float LastResidualMeters => Controller.LastResidualMeters;
public float LastResidualDegrees => Controller.LastResidualDegrees;
public float LastAcceptedScore => Controller.LastAcceptedScore;
public bool StaticLocked => Controller.MotionState == AnchorMotionState.Static;
```

- [ ] `RuntimeDiagnostics` 替换旧字段：

```csharp
public float latestResidualMeters;
public float latestResidualDegrees;
public float latestAcceptedScore;
public bool latestStaticLocked;
```

- [ ] 同步 `latestSpeedMps`、`latestAngularSpeedDps`、`latestPredictAheadMs` 保持可用。
- [ ] 运行：

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected：PASS。

### Task 10：新增 `AnchorRecoveryController`

**Files**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] 新增 SerializeField：

```csharp
[SerializeField] private PoseToAnchorRuntime runtime;
[SerializeField] private AnchorCommandClient commandClient;
[SerializeField] private bool autoReacquire = true;
[SerializeField] private bool reacquireOnLowScore = true;
[SerializeField] private bool reacquireOnLost = true;
[SerializeField] private bool reacquireOnNoPose = true;
[SerializeField] private float lowScoreThreshold = 0.25f;
[SerializeField] private float lowScoreSeconds = 0.8f;
[SerializeField] private float lostSeconds = 0.3f;
[SerializeField] private float noPoseSeconds = 1.0f;
[SerializeField] private float cooldownSeconds = 3.0f;
[SerializeField] private bool clearTrackingFirst = true;
```

- [ ] 类 summary 写清：本组件只观察 Unity runtime 状态并发送 command，不解码 PoseResult，不修改 Transform。
- [ ] `Update()` 只做计时和触发，不阻塞主线程；异步 request 使用 destroy CTS。
- [ ] 触发 reason 固定可统计，例如：
  - `auto_reacquire_low_score`
  - `auto_reacquire_lost`
  - `auto_reacquire_no_pose`
- [ ] `input_not_ready` 不发送 command，只刷新等待状态。
- [ ] smoke 加 reflection 检查类型和字段。
- [ ] 不修改 `EgoAnchor-Evaluation.unity`，因为场景当前已有用户改动。实现完成后再由人或单独任务绑定组件引用。

### Task 11：文档同步

**Files**

- Modify: `ANCHOR_CONTROLLER_GUIDE.md`
- Modify: `AGENTS.md`

- [ ] guide 总述改为 One Euro anchor controller。
- [ ] 参数表只保留第 5 节字段。
- [ ] 删除 Mahalanobis、Kalman covariance、teleport recovery、soft recovery、old smoother 文案。
- [ ] `AGENTS.md` 只改 `USER-MAINTAINED-REQUIREMENTS` 区块之外的事实：
  - `PolicyController` = simple score/jump gate + One Euro + static lock + state machine。
  - `AnchorPoseFilter` = One Euro 提交态、输出态、有界前推。
  - `AnchorStaticLock` = 静止输出锁。
  - `AnchorRecoveryController` = 自动 reacquire bridge。
- [ ] 搜索过期术语：

```powershell
rg "马氏|Mahalanobis|teleport_recovery|softRecovery|soft recovery|6DoF Kalman|AnchorMeasurementGate|AnchorOutputSmoother|MotionStateClassifier" ANCHOR_CONTROLLER_GUIDE.md AGENTS.md EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy
```

Expected：无输出，或只在“旧机制已删除”的说明中出现。推荐无输出。

### Task 12：完整验证

**Files**

- No additional edits unless verification exposes failures.

- [ ] Unity policy smoke：

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected：

```text
Anchor policy smoke passed.
```

- [ ] Unity build：

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected：build succeeds。已有 package/sample warning 可保留，不应有新的 EgoAnchor policy/runtime error。

- [ ] Python eval tests：

```powershell
cd EgoAnchor_Python
pixi run python -m unittest discover -s eval -p "test_*.py"
```

Expected：all eval tests pass。

- [ ] One Euro replay：

```powershell
cd EgoAnchor_Python
pixi run python .\eval\tools\replay_one_euro_policy.py --session .\data\eval\20260613_012345_controller_right
```

Expected：无 schema error。One Euro 在有 GT 的段落不应比 raw 差超过 5%；连续运动段 `maxZeroRun <= 4`。

- [ ] 现有 metrics schema 不断：

```powershell
cd EgoAnchor_Python
pixi run python -c "from pathlib import Path; from eval.io import load_session; from eval.metrics import compute_all_metrics; logs=load_session(Path('data/eval/20260613_012345_controller_right')); result=compute_all_metrics(logs); print(result.tables['anchor_error_summary'].to_string(index=False)); print(result.tables['policy_distribution'].to_string(index=False))"
```

Expected：命令跑完。它验证旧记录仍能被 eval 读取，不证明新 runtime 行为。

## 7. 验收标准

- 静止物体：smoke 中 stable 输出 RMS 明显低于 raw 输入噪声；1 到 2cm 级 residual slip 不会让 anchor 缓慢漂走。
- 连续运动：5Hz pose 输入下，Unity 渲染帧 stable pose 连续移动/旋转，source frame 之间没有长时间停顿。
- 低分：低分测量不拖动输出；持续低分触发 reacquire，且有 cooldown 和 in-flight guard。
- 断流：短时 no-pose 先 coast，再 freeze，超过阈值进入 Lost；Lost 触发 reacquire。
- 边界：frame alignment、raw baseline、processor baseline、NATS transport、Protobuf 不改。
- 代码：旧 Mahalanobis/Kalman covariance/teleport/soft recovery 代码删除，不保留旧参数兼容。
- 文档：guide 和 AGENTS 当前事实与代码一致，用户维护区块不动。

## 8. 实施注意

- 不要在 `Policy/` plain C# 类中读取 `UnityEngine.Time`；所有时间由调用者传入。
- 不要在 `NatsControlClient`、`PoseResultReceiver`、`DynamicObjectAnchor` 中加入 policy 逻辑。
- 不要把自动 reacquire 写进 `PolicyController`。policy core 必须保持可 headless smoke 驱动。
- Unity 新 Inspector 字段必须有中文 `[Tooltip]`；新增类、成员变量、方法必须有中文 summary。
- 不迁移旧 Inspector 参数。旧参数正是本次要删除的复杂度来源。
- 不直接修改当前有用户改动的 scene。代码完成后，再单独绑定 `AnchorRecoveryController`。
- 如果离线回放显示 One Euro 默认参数不如 raw，先调默认参数，不要把旧 Kalman/gate 重新加回来。

## 9. 本计划的风险

| 风险                                  | 处理                                                                                                                               |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| One Euro 默认参数不适合所有物体       | 先用当前 session 回放定一版，再用 controller_right、mouse、earphone 分别录制校准。                                                 |
| 静止锁过强导致真移动起步慢            | release 阈值和速度阈值要由 smoke 覆盖，真移动必须快出。                                                                            |
| 自动 reacquire 过于频繁               | cooldown、in-flight guard、input_ready guard 三层限制。                                                                            |
| 删除旧文件导致 csproj 或 scene 引用断 | smoke csproj 和 Unity build 是硬门；scene 不自动改，避免覆盖用户修改。                                                             |
| eval 新旧字段不兼容                   | `AnchorPolicyDecision`、`AnchorPolicyOutput`、`AnchorState`、`AnchorMotionState` 对外类型保留，metrics schema 作为验证项。 |
