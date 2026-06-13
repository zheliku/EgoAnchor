# EgoAnchor Unity 侧自适应 Anchor 控制器（论文核心方法）实施计划

## 1. Context（为什么做）

Python 感知侧评分重构已完成：`PoseResult` 携带 `reliability_score = Gate × Quality × Confidence`、七个子分、渲染质量细项与 flags。Unity 侧 anchor 行为层是论文核心方法的另一半，当前存在实测确认的结构性缺陷：

1. **双重/三重滤波**：[PoseToAnchorRuntime.cs:479](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs#L479) 中 policy 的 Accept/Coast 输出再次进入 processor 链（主场景 policy runtime 还同时挂了 Kalman + LowPass 两个 processor）；policy 的 gate/coast 与后级 Kalman 噪声参数互不知情，coast 外推被 Kalman 拖拽。
2. **静止旋转抖动 1.27°**（位置 0.34mm 已合格）：[AnchorKalmanPoseProcessor.cs:73-74](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Processors/AnchorKalmanPoseProcessor.cs#L73-L74) 旋转只是固定速率 8/s 的指数 Slerp，不是滤波器。
3. **滤波强度固定**：测量噪声不随 `reliability_score` 调整，也不区分静止/运动——"稳"与"跟手"只能取一个全局折中。
4. **输出按消息节奏阶梯化**：[PoseToAnchorRuntime.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs) 没有任何 Update/LateUpdate；stablePose 只在 PoseResult 到达时变化（~10-30Hz），渲染 72-90Hz——运动物体可见卡顿，且 Python 停发后 coast/lost 计时永不推进、anchor 永久冻结在最后状态。
5. **Innovation gate 失真**：[InnovationGate.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/InnovationGate.cs) 用固定阈值（0.8m/90°）对比上一 stablePose 而非预测位姿——快速运动时滞后的 stablePose 抬高 innovation 造成误拒；物体真实瞬移（被遮挡时挪动）则永远被拒直到 Python 重注册。
6. **Coast 不外推旋转**：[AnchorPredictor.cs:82](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPredictor.cs#L82) 旋转保持不动；速度只用最近两帧差分（噪声大）。
7. **测量时间戳用到达时间**：[PoseToAnchorRuntime.cs:233](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs#L233) 用 `Time.realtimeSinceStartupAsDouble`（到达时刻），而该 pose 实际描述的是 80-300ms 前 capture 时刻的世界状态。capture 时间其实可得：[FramePoseHistory](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/FramePoseHistory.cs) 按 frame_id 缓存了 `SenderMonoMs = Time.realtimeSinceStartupAsDouble*1000`（[StereoFrameSource.cs:122](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Quest/StereoFrameSource.cs#L122)）。

**目标**：把 Policy 层原地重建为一个**可靠性自适应 + 运动自适应的统一 6DoF anchor 控制器**，回答用户四问——什么时候接收/拒绝 pose（双层门控+瞬移恢复）、平滑逻辑（统一自适应滤波取代两级割裂）、静止减抖（静止检测+ZUPT+噪声放大，目标旋转抖动 <0.5°）、运动快速同步（运动态低噪声+每渲染帧预测到当前时刻的延迟隐藏）。

**范围**：仅 Unity + smoke 工具 + eval 记录字段。**不改 Python、不改 proto、不改 Processors/ 下三个 baseline 文件**（论文对照组冻结）。

---

## 2. 设计总览

### 2.1 核心思想（论文方法叙事）

1. **时间上的 frame-aligned**：空间上已用 capture-time camera pose 对齐（现有机制）；本轮把**时间轴也对齐到 capture**——滤波器的测量时间戳 = 该 frame_id 的 Unity capture 单调时间，输出 = 滤波状态预测到渲染时刻。低频异步 pose 流因此变成 72-90Hz 连续 anchor 运动，且天然完成延迟补偿。
2. **提交态 + 瞬态预测**：滤波器内部状态停留在最后一次测量的 capture 时刻（提交态）；每渲染帧 `PredictAt(t_render)` 只做瞬态前推、不提交。新测量到达时先把提交态 predict 到该测量的 capture 时刻再 update。测量天然"迟到"也被正确处理，无需乱序融合。
3. **单一滤波器吸收 gate/coast**：门控用滤波器自身协方差做马氏距离判跳变（coast 期协方差增长→门自动变宽→恢复更容易）；coast 就是"无测量时继续 predict + 速度阻尼"，不再是独立 predictor。
4. **运动状态显式建模**：Static/Moving 二态（带滞回）。Static：ZUPT（速度/角速度清零）+ 测量噪声放大 → 极低抖动且不外推噪声；Moving：基准噪声 + 速度外推 → 低延迟跟手。
5. **可靠性自适应**：测量噪声 `R_eff = R_base / clamp(score, 0.2, 1)²`——低分测量仍能注入信息但权重低，而不是非黑即白的拒绝。

### 2.2 数据流

```
消息驱动（PoseResultReceiver.Update → Hub → Runtime）
  AcceptPoseResult → TryAlign（不变）
    → framePoseHistory.TryGet(frameId) 取 captureTime = record.SenderMonoMs/1000
    → PoseResultPolicyMapper.FromAlignedPose(+captureTime) → AnchorObservation
    → policyHost.AcceptPose(obs) → AnchorPolicyDecision（只含 Action/State/Reason，更新诊断，不写 stablePose）
        PolicyController.AcceptPose:
          ① 有效性（no aligned pose → 记 miss 事件）
          ② 时序守卫（capture 时间非单调或 age > maxMeasurementAge → 丢弃）
          ③ AnchorMeasurementGate：分数滞回 → relocalize 旁路 → 马氏 innovation（对预测位姿）→ 瞬移恢复
          ④ Accept → AnchorPoseFilter.Correct(pose, t_capture, R_eff)；AcceptSnap → Filter.Snap
          ⑤ MotionStateClassifier 更新
          ⑥ AnchorStateMachine 转移

渲染帧驱动（新增，PoseToAnchorRuntime.LateUpdate，[DefaultExecutionOrder(-50)]）
  policyHost.Advance(now) → AnchorPolicyOutput
        PolicyController.Advance:
          ① coast/lost 计时推进（与消息解耦，Python 停发也正常走 Coasting→Frozen→Lost）
          ② 按状态输出：Tracking+Moving → 外推到 min(now, t_meas+maxPredictAhead)
                         Tracking+Static → 持位（不外推噪声）
                         Coasting → 阻尼速度外推 + 协方差增长
                         Frozen/Lost/Paused → 持位
  → runtime.stablePose / 诊断（DynamicObjectAnchor 在默认 order 0 的 LateUpdate 读取，顺序有保证）

baseline 路径完全不变：policyHost==null 时仍按消息驱动 RunProcessors（raw/lowpass/kalman 论文对照组）。
```

### 2.3 与旧计划（calm-newell）的偏离及理由

| 旧计划 | 本计划 | 理由 |
| --- | --- | --- |
| 新增 `AnchorAdaptive6DofProcessor` 处理器 + `AlreadyFiltered` 决策字段，旧两级 policy 暂留 | **原地重建 Policy 层**，删除 ReliabilityGate/InnovationGate/AnchorPredictor，policy 路径彻底不过 processors | AGENTS.md 用户要求 6"重构不兼容旧代码"；旧两级 policy 从不是论文矩阵变体（矩阵 = raw/lowpass/kalman/full）；`AlreadyFiltered` 旁路是兼容补丁 |
| 复用 `AxisKalman`（从 Kalman processor 提出共享） | Policy/ 内新建独立 `ScalarKalman2` | baseline 文件冻结保证论文对照可比性；新滤波器的 predict-不提交、ZUPT、逐帧自适应 R、协方差增长 API 会使两者实现必然分叉，并非同一组件 |
| 上下文用 `Process(..., in PoseQualityContext)` 重载 | 观测直接扩展 `AnchorObservation`（+capture 时间） | 滤波器不再是 processor，无需迁就 processor 签名 |
| 未含渲染帧预测输出 | **新增 per-frame Advance + 预测到渲染时刻**（地平线截断 0.15s，可配 0 关闭） | 这是"运动时尽快更新同步"的正解，也修复"Python 停发 anchor 永久冻结"缺陷；旧计划的消息驱动 coast 无法覆盖 |
| 旋转двух方案二选一由 smoke 裁决 | 保留该裁决机制（S11 闸门），但只落地一种实现，不留双实现 | 同 AGENTS.md 无兼容要求；替换面封闭在 AnchorPoseFilter 内部 |

### 2.4 v1 信号使用边界（克制）

- **主信号只用 `reliability_score` 总分**。不再单独消费 `score_confidence`：总分已含 Confidence 因子（0.5→1.0 ramp），Unity 再用一次等于双重计权——刚恢复跟踪的帧总分天然 ≤0.5×，正好落在 R 放大区，行为已符合预期。
- flags 只保留硬拒绝（`no_pose`/`invalid_pose` 关键字，现有逻辑）+ 诊断透传。子分继续只进 `RuntimeDiagnostics`/HUD/eval 调参。
- 若真机回放发现 `quality_pending`（无几何证据帧）需要额外 R 膨胀，再加一行 flag→系数，留作 v2。

---

## 3. 文件改动清单

目录前缀：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/`。所有新代码：类/成员/方法中文注释，Inspector 字段中文 `[Tooltip]`；**核心类为 plain C#（非 MonoBehaviour）、所有 API 显式传时间（秒），禁止内部读 `Time.*`**——这是 smoke 工具（离线加载 UnityEngine.dll，icall 不可用）的硬约束，也是现有 PolicyController 的既有模式。

### 3.1 新建（5 个文件）

| 文件 | 职责 |
| --- | --- |
| `Policy/AnchorPolicyConfig.cs` | `[Serializable]` 参数包（§5 全表），含 `Validate()` 归一（τ_stay≤τ_enter、exit>enter 等）。Host 序列化它；smoke 直接 new。 |
| `Policy/AnchorPoseFilter.cs` | 统一 6DoF 自适应滤波核。内含 `private struct ScalarKalman2`（状态 [pos,vel]，2×2 协方差，数学与 AxisKalman 同型，注释注明）。状态：3×ScalarKalman2 + 四元数 q + 角速度 ω(Vector3) + 标量旋转协方差 P_rot。API：`HasState`、`Snap(Pose, t)`（硬置位，v=ω=0，P=P0）、`Correct(Pose, t, rPos, rRot)`（内部先 predict 提交态到 t 再 update）、`PredictAt(t, extrapolate, dampingTau)`（瞬态预测不提交）、`GrowCovariance(dt)`（coast 期协方差增长）、`SetStaticMode(bool)`（ZUPT：Correct 后 v×0.1、ω→0）、`DecayToHold()`（清速度）、只读 `Velocity/AngularVelocity/PositionVariance/RotationVariance`、`Reset()`。自实现 `QuaternionExp/QuaternionLog`（半角公式，短弧 wrap 到 (−π,π]，不依赖可能是 icall 的引擎 API）。 |
| `Policy/AnchorMeasurementGate.cs` | 吸收并取代 ReliabilityGate + InnovationGate。输入：observation + 滤波器预测位姿/协方差 + 是否已初始化。输出 `GateResult { GateAction(Accept/AcceptSnap/Hold/Reject), Reason, REffPos, REffRot, InnovationPosD2, InnovationRotD2 }`。内部状态：分数滞回标志、瞬移恢复计数器与最近被拒 pose 列表。规则顺序见 §4.3。 |
| `Policy/MotionStateClassifier.cs` | `enum AnchorMotionState { Unknown, Static, Moving }` + 滞回分类器（§4.4）。Snap/Reset → Unknown（按 Moving 噪声处理，避免刚重定位就被静止模式压住）。 |
| `Policy/AnchorPolicyOutput.cs` | `readonly struct { bool HasPose; Pose Pose; AnchorState State; AnchorMotionState MotionState; float PredictAheadSeconds; string Reason; }` — `Advance` 的返回值，唯一 pose 输出权威。 |

### 3.2 重写（6 个文件，文件名保留，无旧接口兼容）

| 文件 | 改动 |
| --- | --- |
| `Policy/PolicyController.cs` | 编排器：持有 gate/filter/classifier/stateMachine + config。`AcceptPose(AnchorObservation)` 按 §2.2 流程返回新 Decision；新增 `AnchorPolicyOutput Advance(double now)`（计时推进 + 状态输出）；`ApplyConfig(config)` 热更参数不毁状态；Notify*（Reset/Reacquire/Pause/Resume/Error/Lost/Clear）保留签名，内部改为重置 filter/gate/classifier；删除 `HasStablePose/StablePose`（被 Advance 输出取代）；新增只读诊断 `MotionState/SpeedMps/AngularSpeedDps/LastInnovationPosD2/LastREffPos/PredictAheadSeconds/AcceptedCount/RejectedCount`。 |
| `Policy/AnchorPolicyDecision.cs` | `AnchorPolicyAction` 增 `Snap` 成员（eval policy_distribution 可直接区分重定位接受）；struct 改为 `{ Action, State, Reason }`，删除 `HasOutputPose/OutputPose`。 |
| `Policy/AnchorObservation.cs` | 新增 `double CaptureTimeSeconds`（<0 表示未知）与 `bool HasCaptureTime`；工厂方法加参。`SampleTimeSeconds`（到达时间）保留用于 miss 事件计时与诊断。 |
| `Policy/AnchorPolicyHost.cs` | 字段换为单个 `[SerializeField] AnchorPolicyConfig config`（分组 Header/中文 Tooltip）；`OnValidate` → `config.Validate(); controller?.ApplyConfig(config)`（**不再 Rebuild，修 Play 模式改参清状态问题**）；新增 `Advance(now)` 透传与 `Bind(PoseToAnchorRuntime owner)` 1:1 守卫（重复绑定不同 owner → `EgoAnchorLog` Error 并拒绝，防 Hub 场景误共享）；诊断属性透传。 |
| `Runtime/PoseResultPolicyMapper.cs` | `FromAlignedPose` 增加 `double captureTimeSeconds` 参数透传。 |
| `Runtime/PoseToAnchorRuntime.cs` | ① 类加 `[DefaultExecutionOrder(-50)]`（先于 DynamicObjectAnchor/Recorder 的 LateUpdate）；② policy 分支在 TryAlign 成功后 `framePoseHistory.TryGet(frameId, out record)` 取 capture 时间（对齐成功则记录必然存在；直接注入测试路径传 −1 回退到达时间）；③ `ApplyPolicyDecision` 只写诊断，**删除 RunProcessors 调用与 `ShouldAdvanceProcessors`**；④ 新增 `LateUpdate`：policyHost 非空时 `Advance(Time.realtimeSinceStartupAsDouble)` → stablePose/hasStablePose/诊断；⑤ `Awake` 调 `policyHost?.Bind(this)`；policyHost 与 processors 同时非空 → 一次性 Warning"policy 路径忽略 processors"；⑥ `RuntimeDiagnostics` 新增 `currentMotionState`(string)、`latestSpeedMps`、`latestAngularSpeedDps`、`latestInnovationPosD2`、`latestREffPos`、`latestPredictAheadMs`（中文 Tooltip）。 |

### 3.3 删除（含 .meta，同步 smoke csproj Compile 清单）

- `Policy/AnchorPredictor.cs`（coast 预测由滤波器吸收，且补上旋转外推）
- `Policy/ReliabilityGate.cs`、`Policy/InnovationGate.cs`（合并进 AnchorMeasurementGate）
- `Policy/ReliabilityScore.cs`（ReliabilityLevel 概念被 GateAction 取代）

### 3.4 冻结不动（论文对照组与稳定层）

`Processors/` 全部三文件、`AnchorStateMachine.cs`（状态枚举与转移函数够用，喂法在 controller 改）、`AnchorRuntimeHub`、`DynamicObjectAnchor`、`Alignment/` 全部、`Client/` 全部、协议生成代码、Python 全部。

### 3.5 工具与评估侧

- `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`：**Compile 清单按文件显式列出**（已核验），删 4 个旧文件条目、加 5 个新文件条目。
- `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`：重写 policy 断言段（§7）；现有 `AssertPolicyHoldAndRejectDoNotAdvanceProcessors` 反射依赖将被删除的 `ShouldAdvanceProcessors`，改写为 S12。
- `EgoAnchorEval/AnchorEvalRecorder.cs` + `AnchorEvalJson.cs`：variant 快照增 `motion_state`(string)、`predict_ahead_ms`(double) 两字段。已核验 Python eval loader（`eval/io/schemas.py`）按字段名取值，新增字段对现有 metrics 零破坏，**本轮不改 Python**。

---

## 4. 核心算法（实现可直接照抄）

### 4.1 位置通道（每轴独立 ScalarKalman2）

- **Predict 到 t**（dt = t − t_state）：`pos += vel·dt`；`P00 += dt(P01+P10) + dt²·P11 + q·dt`；`P01 += dt·P11`；`P10 += dt·P11`；`P11 += q·dt`。q 按运动态取 `processNoiseMoving/Static`。
- **Update**：`S = P00 + R_eff`；`k0 = P00/S, k1 = P10/S`；`pos += k0·innov, vel += k1·innov`；协方差更新同现有 AxisKalman 形式。
- **自适应测量噪声**：`R_eff = R_base / clamp(score, scoreNoiseFloor, 1)²`；Static 态 `R_base ×= staticMeasurementNoiseScale`。
- **ZUPT**（Static 态）：每次 Correct 后 `vel ×= 0.1`，P11 上限钳制——静止时速度不积累、预测不外推噪声。

### 4.2 旋转通道（误差态四元数 + 角速度，标量协方差）

- **Predict**：`q ← q ⊗ Exp(ω·dt)`；`P_rot += q_rot·dt`；`ω ×= exp(−dt/τ_ω)`（持续阻尼，防常角速度模型在噪声下漂移——这是 1.27° 问题的反噬风险点）。
- **Update**：`θ = Log(q⁻¹ ⊗ q_meas)`（3 维轴角，rad，wrap 短弧）；`k = P_rot/(P_rot + R_rotEff)`；`q ← q ⊗ Exp(k·θ)`；`ω += clampMagnitude(β·k·θ/dt, ωCorrMax)`；`|ω| ≤ ωMax`；`P_rot ×= (1−k)`。
- **四道保险丝**：β 独立缩小角速度增益、|ω| clamp、τ_ω 持续阻尼、Static 态 ZUPT 清零 ω。
- **裁决机制**：smoke S11 是 go/no-go 闸门（静态旋转抖动必须优于模拟 8/s Slerp 基线、恒速旋转跟踪误差有界）。不达标则本文件内部替换为 One-Euro 四元数实现（速度自适应截止频率，外部 API 不变），注释标注裁决依据。

### 4.3 门控规则（AnchorMeasurementGate，按序短路）

1. **硬拒绝**：flags 含 `no_pose`/`invalid_pose` → Reject。
2. **Relocalize 旁路**：`IsRelocalization`（pose_source/phase 含 REGISTER）且 score ≥ `relocalizeMinScore` → **AcceptSnap**（滤波器硬置位；感知已重定位，与旧状态的连续性是虚构，blend 反而污染 recovery 指标）。
3. **首测量**：滤波器未初始化且 score ≥ `acceptScoreEnter` → AcceptSnap（跳过 innovation）。
4. **分数滞回**：未在接受态需 score ≥ `acceptScoreEnter`(0.35) 进入；已在接受态 score ≥ `acceptScoreStay`(0.25) 维持——防止分数在阈值附近振荡导致接受/拒绝抖动。score < `holdScoreMin`(0.12) → 强 Reject 并计入 lost 计时；介于两者 → Hold（冻结保持）。
5. **马氏 innovation（对预测位姿，位置/旋转分开判）**：
   - `d²_pos = Σ_axis innov_axis² / (P00_axis + R_effPos)`，阈值 `innovationPosChi2Gate`（3 自由度，默认 16 ≈ 99.9%）；
   - `d²_rot = |θ|² / (P_rot + R_effRot)`，阈值 `innovationRotChi2Gate`（默认 11）；
   - 任一超阈 → Reject（Reason 区分 `translation_innovation`/`rotation_innovation`）；绝对兜底 0.8m/90° 保留。
   - coast 期 `GrowCovariance` 使 P 增长 → 门自动变宽 → 重获自然顺滑。
6. **瞬移恢复**（修"物体被挪动后永拒"）：连续 `stuckRecoveryCount`(5) 次 innovation-Reject 且每次 score ≥ `acceptScoreEnter` 且**被拒 pose 互一致**（两两距离 < 0.10m/15°，区分真实瞬移与随机外点串）→ AcceptSnap，Reason=`teleport_recovery`。

### 4.4 运动状态分类（滞回不对称）

- **进 Static**：`|v| < 0.01 m/s` 且 `|ω| < 2°/s` 持续 `0.5s`。
- **出 Static（立即）**：`|v| > 0.03 m/s` 或 `|ω| > 6°/s` 或单帧 `d²_pos > motionSpikeD2`(6.0)。
- Static 生效项：ZUPT、R×`staticMeasurementNoiseScale`、Q 用 `processNoiseStatic`、Advance 输出不外推。

### 4.5 Advance 输出（每渲染帧）

```
gap = now − lastAcceptCaptureTime
gap ≤ coastGrace            → Tracking 输出：PredictAt(min(now, t_meas + maxPredictAhead))
                              Moving 外推（延迟隐藏）；Static 持位
coastGrace < gap ≤ maxCoast → Coasting：阻尼速度外推 pos + vel·τ_d·(1−e^(−h/τ_d))、
                              rot = q ⊗ Exp(ω_damped·h)；每帧 GrowCovariance(dtFrame, clamp dt ≤ 0.25s)
maxCoast < gap < lostTimeout → FrozenUncertain：DecayToHold 后持位
gap ≥ lostTimeout           → Lost：持位输出（HasPose 仍 true，隐藏交由 DynamicObjectAnchor.holdLastPoseWhenMissing）
首测量未到                   → Searching，HasPose=false
Paused                       → 持位，计时不推进状态（恢复后按真实时间差自然走 coast/lost，语义诚实）
```

预测地平线 `maxPredictAheadSeconds` 是延迟隐藏 vs 噪声放大的显式旋钮：全量外推会把速度噪声放大 ~0.1-0.3s 倍，默认截断 0.15s（残余 ~50-150ms 滞后），论文可做消融（0 / 0.10 / 0.15 / 不截断）。

### 4.6 状态机映射（AnchorStateMachine 不改，喂法变）

| 触发 | 调用 | 结果 |
| --- | --- | --- |
| Gate Accept/AcceptSnap | `OnReliablePose` | Tracking |
| Gate Reject（score/innovation） | `OnUncertainPose`；score<holdScoreMin 持续 ≥ lostTimeout → `OnMissingPose(∞)` | FrozenUncertain → Lost |
| Advance 计时 | `OnMissingPose(真实 secondsSinceReliable)` | Coasting / FrozenUncertain / Lost |
| Notify*（Reset/Reacquire/...） | 现有转移函数 | 同现状 |

---

## 5. 参数表（AnchorPolicyConfig 默认值）

**评分门控**：`acceptScoreEnter=0.35`、`acceptScoreStay=0.25`、`holdScoreMin=0.12`、`relocalizeMinScore=0.12`
**跳变门控**：`innovationPosChi2Gate=16`、`innovationRotChi2Gate=11`、`maxTranslationJumpMeters=0.8`、`maxRotationJumpDegrees=90`、`stuckRecoveryCount=5`、`stuckConsistencyMeters=0.10`、`stuckConsistencyDegrees=15`
**位置滤波**：`positionMeasurementNoise=4e-6 m²`（σ≈2mm，对应实测 raw 静态噪声量级）、`staticMeasurementNoiseScale=100`、`scoreNoiseFloor=0.2`、`processNoiseMoving=0.05`、`processNoiseStatic=0.005`
**旋转滤波**：`rotationMeasurementNoise=3e-4 rad²`（σ≈1°）、`rotationProcessNoise=0.02 rad²/s`、`angularVelocityGainBeta=0.3`、`angularVelocityMaxDps=200`、`angularVelocityDampingTau=0.5s`
**运动分类**：`staticEnterSpeed=0.01 / staticExitSpeed=0.03 m/s`、`staticEnterAngular=2 / staticExitAngular=6 °/s`、`staticEnterDuration=0.5s`、`motionSpikeD2=6.0`
**时序续航**：`coastGraceSeconds=0.18`（覆盖 ≥10Hz 消息间隔抖动）、`maxCoastSeconds=0.45`、`lostTimeoutSeconds=2.0`、`maxPredictAheadSeconds=0.15`、`velocityDampingTauSeconds=0.3`、`maxMeasurementAgeSeconds=1.0`

每个字段中文 Tooltip 说明语义+单位+调大调小的效果（仿照现有 AnchorPolicyHost/AnchorKalmanPoseProcessor 风格）。

---

## 6. 边缘情况裁决

- **首 pose**：过分数门即 Snap，跳过 innovation。
- **re-register**：Snap 不 blend（理由见 §4.3-2）。
- **测量"迟到"**：capture 时间单调且 age ≤ 1.0s 即正常 Correct（提交态在过去、输出重预测本来就正确）；乱序/超龄丢弃并记 Reason（`stale_measurement`）。
- **frame_id**：由 Unity 自增（StereoFrameSource），Python 重启不回退；时序守卫兜底一切异常。
- **timeScale/编辑器暂停**：时基统一 `realtimeSinceStartupAsDouble`（capture 与 render 同钟）；长暂停恢复按真实间隔走 coast→lost（数据确实陈旧）；协方差增长单步 dt clamp 0.25s 防数值爆。
- **OnValidate during play**：ApplyConfig 热更，滤波状态保留（S10 断言）。
- **Hub 多 runtime**：每个 policy runtime 配自己的 AnchorPolicyHost；Bind 守卫把误共享变成显式报错。
- **对齐失败/no_pose 消息**：照旧走 `AcceptPose(MissingPose/AlignFailed)` 喂状态机事件（计时推进已由 Advance 负责，消息事件只补充 reason/诊断）。

---

## 7. Smoke 场景与量化断言（Program.cs 重写段）

通用设施：固定种子 LCG 噪声、显式模拟时钟（消息 15Hz / Advance 90Hz）、对照统计用"同序列 raw 输入"与"模拟 8/s Slerp"做**相对断言**（避免绝对界限脆弱）。

| # | 场景 | 量化断言 |
| --- | --- | --- |
| S1 首贴合 | 首条 score=0.9 | Accept(Snap)；输出与测量差 <1e-4m/0.1°；State=Tracking |
| S2 静态抖动（PRIMARY 闸门） | 固定真值 + σ=2mm/0.5° 噪声 ×200 帧 | 后半段输出位置 RMS < 输入×0.3；旋转 RMS < 输入×0.3 **且 < 同序列 8/s Slerp 输出 RMS**（对应实测 1.27° 问题）；1s 内 MotionState=Static；窗口末漂移 <1mm |
| S3 匀速响应 + 延迟隐藏 | 0.5m/s 直线 + 噪声，测量 capture 时间真实、到达延迟 120ms | 输出位置误差 P90 < raw-到达即贴 baseline 的 P90；**无新消息的相邻两次 Advance 输出不同**（渲染帧连续运动的直接断言）；MotionState=Moving |
| S4 分数滞回 | Tracking 中 score=0.30 | 仍 Accept（stay 带）；Reset 后首条 0.30 → 非 Accept |
| S5 低分不拖拽 | score=0.2 且偏移 0.5m | Reject；输出按既有速度继续，与被拒测量距离 >0.4m |
| S6 跳变拒绝 + 瞬移恢复 | 高分 2m 跳变 ×1 → Reject(innovation)；同新位置 ±2cm 高分 ×5 | 第 5 条 AcceptSnap/`teleport_recovery`；输出贴合 <1mm；Tracking |
| S7 全程无消息 coast | 停消息只 Advance | ≤0.18s Tracking；0.18-0.45s Coasting 且位置沿阻尼速度移动、旋转沿 ω 外推；>0.45s 速度归零（两次 Advance 差 <0.1mm）；>2.0s Lost 且 HasPose=true（全程零消息驱动） |
| S8 重定位贴合 | Lost 后 RE_REGISTER、score=0.2、距 1.5m | AcceptSnap；贴合；Tracking |
| S9 时序守卫 | 提交 t=10.0s 后注入 capture=9.8s | 忽略（输出不变，Reason=stale） |
| S10 热更参数 | 运行中 ApplyConfig | 滤波状态保持（输出连续）；新阈值即时生效 |
| S11 ω 稳定性闸门 | (a) 45°/s 恒速偏航：输出角误差 P90 <3°；(b) 静态 2s 后 \|ω\| <1°/s | 任一不达标 → 旋转实现降级 One-Euro（设计内裁决，不留双实现） |
| S12 无双重滤波 | 反射断言 `ShouldAdvanceProcessors` 不存在；构造 runtime+host（沿用现有 MakeUnityObjectNonNull 模式），AcceptWorldPose+Advance 后 `TryGetStablePose` 与 controller Advance 输出逐位相等 |
| S13 Notify 链 | Reset/Reacquire/Pause/Resume 后 filter/gate/classifier 状态正确清空/冻结；Pause 期间 Advance 输出不变 |

---

## 8. 实施阶段（每阶段独立可验证，建议各自 commit）

1. **Phase 1 — 滤波核**：新建 5 个文件（Config/Filter/Classifier/Output + smoke csproj 注册）；smoke 先写 S2/S3/S11（直接驱动 filter，不经 controller）。此阶段不动旧文件，Unity 工程持续可编译。
2. **Phase 2 — 门控与编排**：新建 AnchorMeasurementGate；重写 PolicyController/AnchorPolicyDecision/AnchorObservation；删除 4 个旧文件（同步 csproj）；重写 smoke 其余场景（S1、S4-S10、S13）。`dotnet run` smoke 全绿。
3. **Phase 3 — Host 与 Runtime 集成**：重写 AnchorPolicyHost、PoseResultPolicyMapper、PoseToAnchorRuntime（§3.2-⑥ 全部）；补 S12。`dotnet build Assembly-CSharp` + smoke 全绿。
4. **Phase 4 — Eval 字段与场景接线**：Recorder/Json 加 `motion_state`/`predict_ahead_ms`；Unity Editor 手工步骤（写入文档供执行）：(a) 主场景 `EgoAnchor.unity` policy runtime 的 processors 清空（当前挂着 Kalman+LowPass，是三重滤波来源）；(b) eval 场景 `EgoAnchor-Evaluation.unity` 新增第三个 runtime（label=`controller`，绑定独立 AnchorPolicyHost，processors 空）注册进 Hub 与 Recorder。
5. **Phase 5 — 真机录制与论文证据**（不改代码）：按 condition 录制并跑 `eval/run_eval.py`，见 §9。
6. **收尾（含使用文档）**：
   - 新写仓库根 `ANCHOR_CONTROLLER_GUIDE.md` 使用文档（中文，遵循 humanizer-zh），内容：①系统运行步骤（Python 服务器命令**保持不变**：`pixi run python .\src\tracking_server.py`，本轮零 Python 改动；NATS/ZMQ 启动顺序照旧）；②本轮改进点对照表（改进前/后行为差异：双重滤波、静止抖动、消息间冻结、延迟隐藏、瞬移恢复等）；③Unity 场景挂载指南（AnchorPolicyHost 组件怎么加、PoseToAnchorRuntime.policyHost 怎么绑、policy runtime 的 processors 必须清空、baseline runtime 怎么保留、eval 场景三变体接线步骤、Inspector 参数分组速查与调参建议）；④诊断怎么看（RuntimeDiagnostics 新字段含义、常见现象排查）。
   - 按 AGENTS.md 维护规则更新其"代码地图/Phase B"小节（删除 AnchorPredictor/两 gate 条目，新增 controller 组件描述与新调试字段），不动 USER-MAINTAINED 区块。

---

## 9. 验证与论文证据

### 命令（每阶段）

```powershell
# 仓库根
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
# 录制后
dotnet run --project EgoAnchor_Tools\eval_session_check\EvalSessionCheck.csproj -- --session-dir <dir>
# EgoAnchor_Python 目录
pixi run python -m unittest discover -s eval -p "test_*.py"
python eval\run_eval.py --session-dir <dir>
```

### 真机录制协议（每条 session 同录 raw/kalman/controller 三变体，按 condition 标注）

| condition | 内容 | 证明点 / 指标 |
| --- | --- | --- |
| `static_close` | 物体静置 30s | 静态抖动：jitter_summary 的 rotation RMS，controller 显著 < kalman 的 1.27°（目标 <0.5°），位置不劣于 0.34mm |
| `handheld_slow`/`handheld_fast` | 匀速/快速移动 | 响应：lag、anchor_error，controller < kalman 且无 raw 的消息阶梯；motion_state 切换正确 |
| `occlusion_brief` | 短遮挡 <0.45s | coast：slip/anchor_error 峰值、恢复无瞬移 |
| `out_of_view_return` | 出视野后重获（event marker） | recovery_time、AcceptSnap/`teleport_recovery` 路径出现于 policy_distribution |
| `score_degraded` | 部分遮挡致低分 | gate：Reject/Hold 占比合理且 anchor 不被坏 pose 拖偏 |

### 预期结论（写论文用）

静态旋转抖动 1.27°→<0.5°；运动输出从消息率阶梯变 72-90Hz 连续且滞后下降（maxPredictAhead 消融曲线）；低分/跳变帧被拒但瞬移可恢复；Python 停发时 anchor 按 Coast→Frozen→Lost 退化而非永久冻结。

---

## 10. 风险与回退

- **常角速度旋转滤波是唯一"可能退货"部件**：S11 闸门裁决，退路 One-Euro 封闭在 AnchorPoseFilter 内部，外部 API 不变。
- **延迟隐藏外推放大噪声**：maxPredictAhead 截断 + Static 不外推 + coast 阻尼三重兜底；最坏退化为 `maxPredictAhead=0`（输出仍每帧推进 coast 计时，只是不前推）。
- **smoke csproj 文件清单遗漏**：Phase 1/2 各自跑 `dotnet run` 即暴露。
- **Recorder 与 DynamicObjectAnchor 同为 LateUpdate order 0**：记录可能滞后一帧——既有问题非本次引入，可选给 Recorder 加 `[DefaultExecutionOrder(100)]`，不阻塞本计划。
