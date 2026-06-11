# EgoAnchor Unity 自适应 Anchor 控制器使用指南

本文档说明 Unity 侧 anchor 控制器重构后系统怎么跑、哪里变了、场景怎么挂、参数怎么调。面向的读者是项目维护者本人和后续接手的人。

## 一句话总结

Unity 的 Policy 层重写为一个统一的自适应控制器：消息到达时只做"测量提交"（门控 + 滤波），每个渲染帧由 `Advance` 把滤波状态预测到当前时刻输出。静止时强平滑减抖，运动时低延迟跟随并隐藏管线延迟，感知断流时按 Coasting → FrozenUncertain → Lost 退化。

## 运行步骤（与之前相同）

Python 侧本轮零改动，命令照旧：

```powershell
# EgoAnchor_Python 目录
pixi run python .\src\tracking_server.py
```

NATS server、ZMQ 端口（15557）、`--object` 参数、OpenCV 调试热键全部不变。Unity 侧照常 Play / 部署 Quest，启动顺序也不变（先 nats-server，再 Python，再 Unity）。

唯一的行为差异在 Unity 内部：绑定了 `AnchorPolicyHost` 的 runtime 现在每个渲染帧都会更新 stable pose，而不是等 pose 消息到达。

## 哪里改进了

| 旧行为 | 新行为 |
| --- | --- |
| Policy 输出再过一遍 Kalman + LowPass processor（双重/三重滤波，参数互不知情） | Policy 路径完全不经过 processor 链，门控与滤波在同一个模型里共享协方差 |
| 旋转只有固定速率 Slerp，静止旋转抖动实测 1.27° | 旋转是带角速度的误差态四元数滤波，静止模式下 smoke 实测抖动约 0.07°（合成噪声 σ=0.5°） |
| 滤波强度固定，"稳"和"跟手"只能选一个折中 | 测量噪声按 `reliability_score` 和静止/运动状态自适应：低分帧权重低，静止帧测量噪声放大 100 倍 |
| stable pose 只在消息到达时变化（10-30Hz 阶梯），Python 停发后 anchor 永久冻结 | 每渲染帧 `Advance` 输出预测位姿（72-90Hz 连续运动）；断流时计时照常推进，0.45s 内阻尼外推，2s 后 Lost |
| 测量时间戳用消息到达时刻，80-300ms 管线延迟直接变成显示滞后 | 测量时间戳用该 frame_id 的 Unity 采集时刻（`FramePoseHistory`），输出向渲染时刻前推至多 0.15s，隐藏大部分延迟 |
| 跳变门用固定阈值对比上一输出，快速运动时误拒，物体被挪动后永远拒绝 | 马氏距离门控对比预测位姿，断流后协方差增长、门自动变宽；连续 5 帧高分且互相一致的"跳变"判定为真实瞬移，直接贴合 |
| coast 只外推位置，旋转不动 | coast 同时外推位置和旋转，速度按时间常数阻尼，位移有上界 |
| Inspector 改参数会重建 controller、清空滤波历史 | 参数热更生效，滤波历史保留 |

涉及的核心文件：

- 新增：`Policy/AnchorPolicyConfig.cs`（参数包）、`Policy/AnchorPoseFilter.cs`（6DoF 滤波核）、`Policy/AnchorMeasurementGate.cs`（门控）、`Policy/MotionStateClassifier.cs`（静止/运动分类）、`Policy/AnchorPolicyOutput.cs`（每帧输出）
- 重写：`Policy/PolicyController.cs`、`Policy/AnchorPolicyHost.cs`、`Policy/AnchorObservation.cs`、`Policy/AnchorPolicyDecision.cs`、`Runtime/PoseToAnchorRuntime.cs`、`Runtime/PoseResultPolicyMapper.cs`
- 删除：`AnchorPredictor.cs`、`ReliabilityGate.cs`、`InnovationGate.cs`、`ReliabilityScore.cs`（职责被吸收）
- 不动：`Processors/` 三个 baseline 文件、`AnchorStateMachine.cs`、对齐层、网络层、协议、Python 全部

## Unity 场景怎么挂

### 完整方法（自适应控制器）

1. 给场景里的 anchor 对象（或任意空物体）添加 `AnchorPolicyHost` 组件。
2. 在对应的 `PoseToAnchorRuntime` 的 Inspector 里，把 `Policy Host` 字段拖成这个组件。
3. 把这个 runtime 的 `Processors` 列表清空。绑定 policyHost 后该列表会被忽略（Awake 时打印一条 Info 提醒），留着只会造成误解。主场景 `EgoAnchor.unity` 的 policy runtime 目前挂着 Kalman + LowPass 两个 processor，需要手动清掉。
4. `DynamicObjectAnchor.outputMode` 选 `Smoothed`。

一个 host 只能服务一个 runtime（内部有独占的滤波状态）。多个 policy runtime 就挂多个 host，误共享会在 Console 报 Error。

### Baseline 对照（论文矩阵）

baseline 路径完全没变：

- raw：`policyHost` 为空，`processors` 为空
- kalman：`policyHost` 为空，`processors` 里放 `AnchorKalmanPoseProcessor`
- lowpass：`policyHost` 为空，`processors` 里放 `AnchorLowPassPoseProcessor`
- controller（完整方法）：`policyHost` 绑定，`processors` 为空

### Eval 录制场景（三变体同录）

在 `EgoAnchor-Evaluation.unity` 中：

1. 复制现有 kalman runtime 节点，命名 controller，绑定独立的 `AnchorPolicyHost`，清空 processors，配一个自己的 anchor 物体（`DynamicObjectAnchor` 指向新 runtime）。
2. 把新 runtime 注册进 `AnchorRuntimeHub` 的 runtime 列表。
3. 在 `AnchorEvalRecorder` 的 `Recorded Runtimes` 里加一项：label 填 `controller`，runtime 和 anchorTransform 指向新节点。建议把 `isPrimary` 移到 controller 变体上。
4. 录制输出的 JSONL 中，controller 变体会多两个字段：`motion_state`（Unknown/Static/Moving）和 `predict_ahead_ms`（本帧前推时长）。Python eval 按字段名取值，新字段不影响现有指标。

## Inspector 参数速查

参数都在 `AnchorPolicyHost` 的 config 里，分六组。运行中修改即时生效，不清滤波历史。每个字段的 Tooltip 写了单位和调整方向，这里只列最常动的：

| 参数 | 默认 | 什么时候动它 |
| --- | --- | --- |
| acceptScoreEnter / acceptScoreStay | 0.35 / 0.25 | Python 评分分布变化后重标。enter 是冷启动门槛，stay 是已跟踪时的滞回下限 |
| positionMeasurementNoise | 4e-6 m²（σ≈2mm） | 感知位置噪声明显不同时改成实测 σ² |
| rotationMeasurementNoise | 3e-4 rad²（σ≈1°） | 同上，旋转通道 |
| staticMeasurementNoiseScale | 100 | 静止还嫌抖就加大；静止后小幅修正跟不上就减小 |
| staticEnterRadius / staticEnterDuration | 12mm / 0.5s | 半径要 ≥ 位置噪声 σ 的 4 倍，否则噪声会反复打断静止判定 |
| maxPredictAheadSeconds | 0.15s | 延迟隐藏量。设 0 关闭前推（仍每帧推进计时）；运动时输出发飘就调小 |
| coastGraceSeconds | 0.18s | 要大于 pose 消息间隔（10Hz 流 ≥0.1s），否则消息间隙会被误判断流 |
| maxCoastSeconds / lostTimeoutSeconds | 0.45s / 2.0s | 断流外推上限 / 进 Lost 的时长 |

## 诊断怎么看

`PoseToAnchorRuntime` 的 Inspector 诊断区新增了几个字段：

- `currentMotionState`：Static 说明静止模式生效（强平滑、不外推）。物体明明在动却显示 Static，查 staticExit 阈值。
- `latestSpeedMps` / `latestAngularSpeedDps`：滤波估计的速度。静止时应趋近 0。
- `latestInnovationPosD2`：测量门控的马氏距离平方。持续超过 16 说明测量和预测严重不符（真实瞬移或感知锁错）。
- `latestEffectiveMeasurementNoise`：本帧实际用的测量噪声。低分帧和静止帧会明显变大。
- `latestPredictAheadMs`：本帧前推时长。跟踪态约等于管线延迟（封顶 150ms），coast 态等于断流时长。
- `latestPolicyAction`：新增 `Snap` 动作，表示贴合接受（首测量、重定位、瞬移恢复），原因看 `latestPolicyReason`（`first_accept` / `relocalize_accept` / `teleport_recovery`）。

常见现象排查：

- anchor 不动、状态 FrozenUncertain：看 `latestPolicyReason`。`score_hold`/`score_reject` 是分数不够（查 Python 评分），`stale_measurement` 是时序异常（查 FramePoseHistory 容量是否被打满）。
- 物体被挪动后 anchor 卡在原地：正常情况下连续 5 帧高分测量后会出现 `teleport_recovery` 并贴合。一直没恢复说明分数不到 acceptScoreEnter。
- 运动时输出超前或回弹：调小 maxPredictAheadSeconds。
- 静止时偶尔轻微滑动后回位：是静止窗口被噪声打断、短暂回到运动模式。加大 staticEnterRadius。

## 验证命令

```powershell
# 仓库根：行为断言（13 个场景：静抖、响应、滞回、瞬移恢复、断流退化、热更……）
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj

# 仓库根：编译
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore

# 录制后的会话检查与离线指标
dotnet run --project EgoAnchor_Tools\eval_session_check\EvalSessionCheck.csproj -- --session-dir <dir>
python eval\run_eval.py --session-dir <dir>    # EgoAnchor_Python 目录
```

真机录制建议每条 session 同录 raw / kalman / controller 三变体，按 condition 标注：静置 30 秒（看 jitter）、慢速和快速手持移动（看 lag 和阶梯消失）、短遮挡（看 coast）、出视野再回来（看 recovery 和 teleport_recovery 路径）、部分遮挡致低分（看 Reject/Hold 占比和输出是否被坏 pose 拖偏）。
