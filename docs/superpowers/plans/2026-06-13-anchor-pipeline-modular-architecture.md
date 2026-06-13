# Anchor Pipeline Modular Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 EgoAnchor 当前的 pose-to-anchor runtime 重构为统一、可插拔、可回放的 anchor pipeline，使 raw / low-pass / Kalman / vanilla One Euro / EgoAnchor score-aware 方法共享同一输入、同一渲染帧输出契约，并能在 Unity Inspector 与离线回放中公平比较。

**Architecture:** 保留现有 Python 感知、Protobuf、NATS/ZMQ、`FramePoseHistory` 与 `CameraPoseFrameAligner` 的 frame-aligned 语义；Unity anchor 侧新增 plain C# pipeline：`Gate -> Estimator -> OutputStage`，其中 `Estimator` 内部负责滤波、状态融合、升采样和预测。`Recovery` 作为正交层单独观察 runtime 状态并发 command，不进入滤波器或网络层。

**Tech Stack:** Unity C#、plain C# policy core、`EgoAnchor_Tools/anchor_policy_smoke`、新增 `EgoAnchor_Tools/anchor_replay`、`dotnet build`、`EgoAnchor_Python/eval` JSONL 指标框架。

---

## 0. 最终判断

这次重构的核心不是“把当前 policy 改成 One Euro”，而是先把所有 baseline 和我们的策略放到同一条可比较的运行契约里。当前代码里有两条路径：

- `PoseToAnchorRuntime.processors`：arrival-time processor chain，只在收到 pose 时更新，`AnchorLowPassPoseProcessor` 和 `AnchorKalmanPoseProcessor` 没有每渲染帧 `Advance(now)`。
- `PoseToAnchorRuntime.policyHost`：每条 pose 只提交测量，`LateUpdate` 每帧 `AdvanceAnchorOutput(now)`，能预测到渲染时刻。

如果保留这个差异，ours 在 latency / lag 指标上会天然占优，但这是因为 baseline 没有拿到同样的升采样/预测机会。主计划必须先消除这个公平性问题。

最终采用的分层：

```text
Python PoseResult
  -> PoseResultReceiver / AnchorRuntimeHub
  -> PoseToAnchorRuntime
  -> CameraPoseFrameAligner(frame_id -> capture-time camera world pose)
  -> AnchorObservation(frame-aligned world pose + score + flags + capture time)

测量时钟：约 4-8Hz
  AnchorPipeline.AcceptPose(observation)
    -> IAnchorGate       接纳、拒绝、hold、snap
    -> IAnchorEstimator  滤波、状态融合、速度估计
    -> AnchorStateMachine 维护 Tracking / Coasting / Frozen / Lost

渲染时钟：约 60-90Hz
  AnchorPipeline.Advance(now)
    -> IAnchorEstimator.PredictAt(now)
    -> IAnchorOutputStage.Condition(...)
    -> AnchorPolicyOutput
    -> DynamicObjectAnchor / AnchorEvalRecorder

正交层
  AnchorRecoveryController 观察 runtime 状态、score、heartbeat，按配置发 reacquire/reset command
```

关键设计原则：

- Kalman 与 One Euro 不串联。Kalman 的 predict/update 与协方差耦合，One Euro 没有协方差语义；串成 `KF -> OEF` 会双重平滑并增加滞后。
- 预测属于 Estimator 内部能力。每个 Estimator 必须实现 `PredictAt(double renderTimeSeconds)`，这样 low-pass、Kalman、One Euro、EgoAnchor 都能在渲染帧输出。
- Score 是 EgoAnchor 的差异化输入。baseline 可以共享 `NullGate` 或普通非 score 策略；EgoAnchor 使用 `ScoreJumpGate` 和 score-adaptive estimator。实验中必须能关掉 gate、关掉 output stage、关掉 recovery 做消融。
- Recovery 不属于滤波 baseline。RQ2 比滤波/同步策略时 recovery 全部关闭或全部共享；RQ3 单独比较 `Off / TimeoutOnly / ScoreAware`。
- 论文主贡献保持保守：pose-to-anchor 问题表述、frame-aligned anchoring、anchor-centric evaluation 是主线；score-aware policy 只有在离线回放和真机数据上赢过强 baseline 后才升级为贡献。

## 1. 文件布局

新增 pipeline 放在现有 `Policy/` 下，保持 namespace `EgoAnchor.Policy`，避免引入新的 Unity assembly 边界。旧 `Processors/` 和旧 `PolicyController` 第一阶段并存，等新 pipeline 和回放验证通过后再清理。

```text
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/
  AnchorEstimate.cs
  GateDecision.cs
  OutputContext.cs
  IAnchorGate.cs
  IAnchorEstimator.cs
  IAnchorOutputStage.cs
  AnchorPipeline.cs

EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Math/
  AnchorMath.cs
  OneEuroFilter.cs
  ConstVelocityKalman.cs

EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Gates/
  NullGate.cs
  ScoreJumpGate.cs

EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Estimators/
  RawAnchorEstimator.cs
  LowPassAnchorEstimator.cs
  KalmanAnchorEstimator.cs
  OneEuroAnchorEstimator.cs
  EgoAnchorEstimator.cs

EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Output/
  PassThroughOutputStage.cs
  StaticLockRateLimitOutputStage.cs

EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/
  AnchorPipelineConfig.cs
  AnchorPipelineHost.cs

EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/
  PoseToAnchorRuntime.cs
  AnchorRecoveryController.cs

EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/
  AnchorEvalRecorder.cs
  AnchorEvalJson.cs
  EvalSessionManifestJson.cs

EgoAnchor_Tools/anchor_policy_smoke/
  Program.cs
  AnchorPolicySmoke.csproj

EgoAnchor_Tools/anchor_replay/
  AnchorReplay.csproj
  Program.cs

EgoAnchor_Python/eval/
  io/schemas.py
  tests/test_log_loader.py
  tests/test_run_eval.py
```

保留但逐步降级为 legacy：

```text
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Processors/AnchorPoseProcessor.cs
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Processors/AnchorLowPassPoseProcessor.cs
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Processors/AnchorKalmanPoseProcessor.cs
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPoseFilter.cs
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/MotionStateClassifier.cs
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs
```

## 2. 核心接口契约

第一阶段复用现有 `AnchorObservation`、`AnchorPolicyDecision`、`AnchorPolicyOutput`、`AnchorState`、`AnchorMotionState`，这样 recorder 和 Python eval schema 不会被迫一起改。新增类型只表示 estimator 内部状态和可插拔模块。

### 2.1 `AnchorEstimate`

文件：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/AnchorEstimate.cs`

```csharp
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Estimator 在指定时间轴上的 pose 估计结果。
    /// </summary>
    public readonly struct AnchorEstimate
    {
        /// <summary>估计出的 Unity world pose。</summary>
        public readonly Pose Pose;

        /// <summary>线速度，单位 m/s，Unity world 坐标。</summary>
        public readonly Vector3 LinearVelocity;

        /// <summary>角速度，单位 rad/s，使用四元数 log-space 表示。</summary>
        public readonly Vector3 AngularVelocityRad;

        /// <summary>该状态对应的单调时间，单位秒。</summary>
        public readonly double TimeSeconds;

        /// <summary>估计置信度，范围 0..1。</summary>
        public readonly float Confidence;

        /// <summary>最近一次参与更新的可靠性分，范围 0..1。</summary>
        public readonly float ReliabilityScore;

        /// <summary>构造估计结果。</summary>
        public AnchorEstimate(
            Pose pose,
            Vector3 linearVelocity,
            Vector3 angularVelocityRad,
            double timeSeconds,
            float confidence,
            float reliabilityScore)
        {
            Pose = pose;
            LinearVelocity = linearVelocity;
            AngularVelocityRad = angularVelocityRad;
            TimeSeconds = timeSeconds;
            Confidence = Mathf.Clamp01(confidence);
            ReliabilityScore = Mathf.Clamp01(reliabilityScore);
        }
    }
}
```

### 2.2 `GateDecision`

文件：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/GateDecision.cs`

```csharp
namespace EgoAnchor.Policy
{
    /// <summary>
    /// Gate 对一帧观测的判定动作。
    /// </summary>
    public enum GateAction
    {
        /// <summary>接受测量并校正 estimator。</summary>
        Accept,

        /// <summary>拒绝测量，保持 estimator 内部状态。</summary>
        Reject,

        /// <summary>不更新 estimator，但允许状态机继续计时。</summary>
        Hold,

        /// <summary>直接把 estimator 重置到该测量，常用于首帧或重定位。</summary>
        Snap,
    }

    /// <summary>
    /// Gate 判定结果，Reason 必须是稳定字符串，便于 JSONL 聚合统计。
    /// </summary>
    public readonly struct GateDecision
    {
        /// <summary>本次 gate 动作。</summary>
        public readonly GateAction Action;

        /// <summary>稳定可统计的原因字符串。</summary>
        public readonly string Reason;

        /// <summary>构造 gate 判定结果。</summary>
        public GateDecision(GateAction action, string reason)
        {
            Action = action;
            Reason = reason ?? string.Empty;
        }
    }
}
```

### 2.3 三个可插拔接口

文件：

- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/IAnchorGate.cs`
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/IAnchorEstimator.cs`
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/IAnchorOutputStage.cs`

```csharp
namespace EgoAnchor.Policy
{
    /// <summary>
    /// 测量进入 estimator 前的判定层。Gate 只看观测、当前预测和状态，不修改 Transform。
    /// </summary>
    public interface IAnchorGate
    {
        /// <summary>评估当前观测是否可用于更新 estimator。</summary>
        GateDecision Evaluate(in AnchorObservation observation, in AnchorEstimate predicted, bool hasEstimate);

        /// <summary>清空 gate 内部历史。</summary>
        void Reset();
    }

    /// <summary>
    /// Anchor estimator，负责低频测量融合、速度估计和渲染时刻预测。
    /// </summary>
    public interface IAnchorEstimator
    {
        /// <summary>用于 Inspector、日志和回放表的稳定名称。</summary>
        string Name { get; }

        /// <summary>是否已有可输出状态。</summary>
        bool HasEstimate { get; }

        /// <summary>直接贴合到一帧测量。</summary>
        void Snap(in AnchorObservation observation);

        /// <summary>用一帧已通过 gate 的测量更新内部状态。</summary>
        void Update(in AnchorObservation observation);

        /// <summary>预测或保持到指定渲染时刻。</summary>
        AnchorEstimate PredictAt(double renderTimeSeconds);

        /// <summary>清空内部状态。</summary>
        void Reset();
    }

    /// <summary>
    /// Estimator 输出后的显示整形层，用于静止锁、限速和统一前推钳制。
    /// </summary>
    public interface IAnchorOutputStage
    {
        /// <summary>根据渲染上下文生成最终输出 pose。</summary>
        Pose Condition(in AnchorEstimate estimate, double renderTimeSeconds, in OutputContext context);

        /// <summary>清空输出层内部历史。</summary>
        void Reset();
    }
}
```

稳定 reason 字符串第一阶段固定为：

```text
first_accept
score_accept
relocalize_accept
no_pose
align_failed
paused
stale_measurement
invalid_pose
score_hold
jump_reject
coast
freeze
lost
no_state
```

## 3. Baseline 与消融矩阵

| Label | Gate | Estimator | OutputStage | Recovery | 目的 |
| --- | --- | --- | --- | --- | --- |
| `raw_zoh` | `NullGate` | `RawAnchorEstimator` | `PassThrough` | Off | 保持上一 pose，暴露低频阶梯感 |
| `lowpass_predict` | `NullGate` | `LowPassAnchorEstimator` | `PassThrough` | Off | 简单平滑 + 自身速度前推 |
| `kalman_cv` | `NullGate` | `KalmanAnchorEstimator` | `PassThrough` | Off | 强 baseline，常速度 Kalman predict-to-render |
| `oneeuro_vanilla` | `NullGate` | `OneEuroAnchorEstimator` | `PassThrough` | Off | 常用交互低通 baseline，不使用 score |
| `egoanchor_no_static` | `ScoreJumpGate` | `EgoAnchorEstimator` | `PassThrough` | Off | 只验证 score-aware gate/filter/prediction |
| `egoanchor_full` | `ScoreJumpGate` | `EgoAnchorEstimator` | `StaticLockRateLimit` | Off | RQ2 主方法，不混入 recovery |
| `egoanchor_recovery_timeout` | `ScoreJumpGate` | `EgoAnchorEstimator` | `StaticLockRateLimit` | TimeoutOnly | RQ3 纯超时 recovery |
| `egoanchor_recovery_score` | `ScoreJumpGate` | `EgoAnchorEstimator` | `StaticLockRateLimit` | ScoreAware | RQ3 score-aware proactive recovery |

预测开关不做成单独 Estimator，而通过配置让所有 Estimator 的 `maxPredictAheadSeconds=0` 或 `predictionScale=0` 实现。这样 “prediction on/off” 是独立消融轴，不和滤波算法混在一起。

RQ1 的 frame-aligned vs arrival-time mapping 不放进 pipeline 内。它发生在 `CameraPoseFrameAligner` 层，是坐标时间映射问题；需要单独实现一个诊断路径，比较 `frame_id` 采集时相机 pose 和 pose 到达/渲染时相机 pose 的差异。

## 4. 实施任务

### Task 0: 建立当前基线和实施保护线

**Files:**

- Read: `AGENTS.md`
- Read: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
- Read: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs`
- Read: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/AnchorEvalRecorder.cs`
- Read: `EgoAnchor_Python/eval/io/schemas.py`

- [ ] Step 0.1: 确认工作区已有用户改动，不回退任何文件。

Run:

```powershell
git status --short
```

Expected:

```text
显示当前 dirty worktree；只记录，不执行 git checkout/reset。
```

- [ ] Step 0.2: 跑现有 Unity policy smoke，确认重构前基线状态。

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
Anchor policy smoke passed.
```

如果失败，先记录失败项和日志。只有失败来自当前 dirty worktree 且会阻塞 pipeline 编译时，才先修复；否则继续实现但在最终报告说明基线 smoke 原本不绿。

- [ ] Step 0.3: 跑 Unity 编译。

Run:

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected:

```text
Build succeeded.
```

- [ ] Step 0.4: 跑 Python eval 单测。

Run:

```powershell
cd EgoAnchor_Python
pixi run python -m unittest discover -s eval -p "test_*.py"
```

Expected:

```text
OK
```

- [ ] Step 0.5: 用现有 `offline_data` 跑一次表格生成。

Run:

```powershell
cd EgoAnchor_Python
pixi run python -m eval.run_eval --session-dir .\data\eval\offline_data --only tables
```

Expected:

```text
生成 EgoAnchor_Python\data\eval\offline_data\report 下的 CSV 表。
```

### Task 1: 新增 pipeline core 类型和接口

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/AnchorEstimate.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/GateDecision.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/OutputContext.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/IAnchorGate.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/IAnchorEstimator.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/IAnchorOutputStage.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] Step 1.1: 新增 `OutputContext`。

Implementation:

```csharp
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 输出层在渲染帧需要的上下文，所有时间均为 Unity 单调秒。
    /// </summary>
    public readonly struct OutputContext
    {
        /// <summary>最近一次被接受测量的采集时间，单位秒。</summary>
        public readonly double LastAcceptedTimeSeconds;

        /// <summary>当前渲染时刻距离最近 accepted 测量的间隔，单位秒。</summary>
        public readonly double GapSeconds;

        /// <summary>最近一次 accepted 测量的 reliability score。</summary>
        public readonly float LastScore;

        /// <summary>当前生命周期状态。</summary>
        public readonly AnchorState State;

        /// <summary>构造输出上下文。</summary>
        public OutputContext(double lastAcceptedTimeSeconds, double gapSeconds, float lastScore, AnchorState state)
        {
            LastAcceptedTimeSeconds = lastAcceptedTimeSeconds;
            GapSeconds = gapSeconds;
            LastScore = Mathf.Clamp01(lastScore);
            State = state;
        }
    }
}
```

- [ ] Step 1.2: 将 2.1、2.2、2.3 中的代码分别写入对应文件。所有类、字段、方法保留中文 XML summary。

- [ ] Step 1.3: 在 `AnchorPolicySmoke.csproj` 加入新文件。

Expected include lines:

```xml
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline\Core\AnchorEstimate.cs" Link="Policy\Pipeline\Core\AnchorEstimate.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline\Core\GateDecision.cs" Link="Policy\Pipeline\Core\GateDecision.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline\Core\OutputContext.cs" Link="Policy\Pipeline\Core\OutputContext.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline\Core\IAnchorGate.cs" Link="Policy\Pipeline\Core\IAnchorGate.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline\Core\IAnchorEstimator.cs" Link="Policy\Pipeline\Core\IAnchorEstimator.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline\Core\IAnchorOutputStage.cs" Link="Policy\Pipeline\Core\IAnchorOutputStage.cs" />
```

- [ ] Step 1.4: 编译 smoke。

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
现有 smoke 仍通过；新增 core 文件不改变行为。
```

### Task 2: 新增 pipeline 配置和模块枚举

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPipelineConfig.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] Step 2.1: 新增模式枚举。

Implementation:

```csharp
using System;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>Anchor pipeline 的前置 gate 选择。</summary>
    public enum AnchorGateMode
    {
        /// <summary>不使用 score/jump gate，仅做必要时序与有效性检查。</summary>
        None,

        /// <summary>使用 reliability score、flags、绝对 jump 的 EgoAnchor gate。</summary>
        ScoreJump,
    }

    /// <summary>Anchor pipeline 的 estimator 选择。</summary>
    public enum AnchorEstimatorMode
    {
        /// <summary>Zero-order hold raw baseline。</summary>
        Raw,

        /// <summary>指数低通 baseline。</summary>
        LowPass,

        /// <summary>常速度 Kalman baseline。</summary>
        Kalman,

        /// <summary>不使用 score 的 vanilla One Euro baseline。</summary>
        OneEuro,

        /// <summary>使用 score-aware 更新和有界前推的 EgoAnchor 方法。</summary>
        EgoAnchor,
    }

    /// <summary>Estimator 输出后的整形层选择。</summary>
    public enum AnchorOutputStageMode
    {
        /// <summary>直接输出 estimator 预测结果。</summary>
        PassThrough,

        /// <summary>使用静止锁、输出限速和前推钳制。</summary>
        StaticLockRateLimit,
    }

    /// <summary>自动重获取策略选择；只由 AnchorRecoveryController 使用。</summary>
    public enum AnchorRecoveryMode
    {
        /// <summary>不自动发 command。</summary>
        Off,

        /// <summary>仅基于 no-pose、Lost、heartbeat 超时触发。</summary>
        TimeoutOnly,

        /// <summary>在超时基础上加入持续低 score 的主动 reacquire。</summary>
        ScoreAware,
    }
}
```

- [ ] Step 2.2: 新增 `AnchorPipelineConfig`。字段先覆盖模块选择、score gate、滤波、预测、静止锁、生命周期，避免继续扩大旧 `AnchorPolicyConfig`。

Required fields:

```csharp
/// <summary>前置 gate 模式。</summary>
[Tooltip("前置 gate 模式：None 用于普通 baseline，ScoreJump 用于 EgoAnchor score-aware 方法。")]
public AnchorGateMode gateMode = AnchorGateMode.None;

/// <summary>Estimator 模式。</summary>
[Tooltip("Estimator 模式：决定滤波、升采样和预测策略。")]
public AnchorEstimatorMode estimatorMode = AnchorEstimatorMode.Raw;

/// <summary>输出整形模式。</summary>
[Tooltip("输出整形模式：PassThrough 直接输出，StaticLockRateLimit 会加入静止锁和限速。")]
public AnchorOutputStageMode outputStageMode = AnchorOutputStageMode.PassThrough;

/// <summary>日志和 Inspector 使用的策略标签。</summary>
[Tooltip("日志和 Inspector 使用的策略标签；为空时自动使用 gate/estimator/output 组合名。")]
public string strategyLabel = "";

/// <summary>首帧开始 tracking 的最低可靠性分。</summary>
[Tooltip("首帧开始 tracking 的最低可靠性分。仅 ScoreJump gate 使用。")]
[Range(0f, 1f)] public float startScoreMin = 0.35f;

/// <summary>已有状态时接受普通 TRACK 的最低可靠性分。</summary>
[Tooltip("已有状态时接受普通 TRACK 的最低可靠性分。仅 ScoreJump gate 使用。")]
[Range(0f, 1f)] public float trackScoreMin = 0.20f;

/// <summary>低于该分值时只 hold，不更新 estimator。</summary>
[Tooltip("低于该分值时只 hold，不更新 estimator。仅 ScoreJump gate 使用。")]
[Range(0f, 1f)] public float holdScoreMin = 0.12f;

/// <summary>register/re-register 观测 snap 接受下限。</summary>
[Tooltip("register/re-register 观测 snap 接受下限。")]
[Range(0f, 1f)] public float relocalizeScoreMin = 0.12f;

/// <summary>绝对位置跳变拒绝阈值，单位米。</summary>
[Tooltip("绝对位置跳变拒绝阈值，单位米。")]
public float maxJumpMeters = 0.80f;

/// <summary>绝对旋转跳变拒绝阈值，单位度。</summary>
[Tooltip("绝对旋转跳变拒绝阈值，单位度。")]
public float maxJumpDegrees = 120f;

/// <summary>通用最大前推时长，单位秒。</summary>
[Tooltip("通用最大前推时长，单位秒；设为 0 可做 prediction off 消融。")]
public float maxPredictAheadSeconds = 0.14f;

/// <summary>预测强度缩放，0 表示关闭前推，1 表示使用 estimator 默认前推。</summary>
[Tooltip("预测强度缩放，0 表示关闭前推，1 表示使用 estimator 默认前推。")]
[Range(0f, 1f)] public float predictionScale = 1.0f;

/// <summary>短时断流保护窗口，单位秒。</summary>
[Tooltip("短时断流保护窗口，单位秒；窗口内保持 Tracking。")]
public float coastGraceSeconds = 0.30f;

/// <summary>可续航外推的最大时长，单位秒。</summary>
[Tooltip("可续航外推的最大时长，单位秒；超过后冻结输出。")]
public float maxCoastSeconds = 0.45f;

/// <summary>无可靠 pose 后进入 Lost 的时长，单位秒。</summary>
[Tooltip("无可靠 pose 后进入 Lost 的时长，单位秒。")]
public float lostTimeoutSeconds = 2.0f;
```

One Euro fields:

```csharp
public float positionMinCutoff = 1.0f;
public float positionBeta = 0.65f;
public float rotationMinCutoff = 1.0f;
public float rotationBeta = 0.55f;
public float derivativeCutoff = 1.0f;
public float minScoreWeight = 0.25f;
```

Kalman fields:

```csharp
public float kalmanPositionProcessNoise = 0.08f;
public float kalmanPositionMeasurementNoise = 0.015f;
public float kalmanRotationProcessNoise = 0.12f;
public float kalmanRotationMeasurementNoise = 0.025f;
```

Static lock fields:

```csharp
public float staticWindowSeconds = 0.60f;
public int staticMinSamples = 3;
public float staticRadiusMeters = 0.012f;
public float staticRotationDegrees = 2.5f;
public float staticSpeedMetersPerSecond = 0.025f;
public float staticAngularSpeedDegreesPerSecond = 8.0f;
public float staticReleaseMeters = 0.020f;
public float staticReleaseDegrees = 3.0f;
public float staticCenterTauSeconds = 0.35f;
public float maxOutputSpeedMps = 3.0f;
public float maxOutputAngularSpeedDps = 720f;
```

- [ ] Step 2.3: 实现 `Validate()`，只做 clamp 和必要关系约束。

Required rules:

```text
0 <= holdScoreMin <= trackScoreMin <= startScoreMin <= 1
0 <= relocalizeScoreMin <= 1
maxJumpMeters >= 0.001
maxJumpDegrees >= 1
0 <= predictionScale <= 1
maxPredictAheadSeconds >= 0
lostTimeoutSeconds >= maxCoastSeconds >= coastGraceSeconds >= 0
staticReleaseMeters >= staticRadiusMeters
staticReleaseDegrees >= staticRotationDegrees
staticMinSamples >= 1
cutoff、tau、noise 字段均大于 0
```

- [ ] Step 2.4: smoke csproj 加入 `AnchorPipelineConfig.cs`。

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
现有 smoke 仍通过；新增配置不改变行为。
```

### Task 3: 新增数学工具

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Math/AnchorMath.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Math/OneEuroFilter.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Math/ConstVelocityKalman.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] Step 3.1: 实现 `AnchorMath`。

Required methods:

```csharp
public static Quaternion Normalize(Quaternion q);
public static Quaternion AlignHemisphere(Quaternion reference, Quaternion value);
public static Quaternion Inverse(Quaternion q);
public static Vector3 Log(Quaternion q);
public static Quaternion Exp(Vector3 log);
public static float AngleDegrees(Quaternion a, Quaternion b);
public static Pose Integrate(Pose pose, Vector3 linearVelocity, Vector3 angularVelocityRad, float dt);
public static Pose ClampPoseDelta(Pose previous, Pose target, float maxLinearStep, float maxAngularStepDegrees);
```

Smoke assertions:

```csharp
AssertQuaternionLogExpRoundTrips();
AssertQuaternionHemisphereAlignmentUsesShortestArc();
AssertPoseDeltaClampLimitsLinearAndAngularSteps();
```

- [ ] Step 3.2: 实现 `OneEuroFilter`，包含 `OneEuroFloat`、`OneEuroVector3`、`OneEuroRotation`。

Required behavior:

```text
Alpha(cutoff, dt) = 1 / (1 + tau / dt)
tau = 1 / (2π * cutoff)
derivative 使用 derivativeCutoff 低通
cutoff = minCutoff + beta * abs(derivativeHat)
rotation 使用 Quaternion log/exp，不使用 Euler 角
所有 Update/Snap 方法都显式接收 timeSeconds，不读取 UnityEngine.Time
```

Smoke assertions:

```csharp
AssertOneEuroStaticNoiseIsSmoothed();
AssertOneEuroFastMotionReducesLag();
AssertOneEuroRotationUsesShortestArc();
```

- [ ] Step 3.3: 实现 `ConstVelocityKalman`。

Required behavior:

```text
状态为 position + velocity 的 1D 常速度 Kalman。
Predict(dt) 可在没有测量时独立调用。
Correct(measurement, measurementNoise) 只校正位置观测。
Reset(position, velocity) 清空协方差为合理初值。
dt clamp 到 [1e-4, 1.0]，避免长断流数值发散。
```

Smoke assertions:

```csharp
AssertConstVelocityKalmanPredictsBetweenSamples();
AssertConstVelocityKalmanIgnoresNoisyMeasurementWhenRIsLarge();
```

- [ ] Step 3.4: 确认 pipeline 数学层没有隐式读取 Unity 时间。

Run:

```powershell
rg -n "Time\\." EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline
```

Expected:

```text
无输出。
```

### Task 4: 实现 Gate 模块

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Gates/NullGate.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Gates/ScoreJumpGate.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] Step 4.1: 实现 `NullGate`。

Rules:

```text
HasAlignedPose=false 且 HasServerPose=false -> Hold / no_pose
HasAlignedPose=false 且 HasServerPose=true -> Hold / align_failed
observation.HasCaptureTime=false -> Accept 或 Snap，但 reason 加 capture_time_missing 不作为拒绝条件
hasEstimate=false 且 HasAlignedPose=true -> Snap / first_accept
observation.IsRelocalization 且 HasAlignedPose=true -> Snap / relocalize_accept
其它 HasAlignedPose=true -> Accept / score_accept
```

- [ ] Step 4.2: 实现 `ScoreJumpGate`。

Rules:

```text
ReliabilityFlags 包含 invalid_pose 或 reject -> Reject / invalid_pose
无 aligned pose -> 与 NullGate 一致
重定位观测且 score >= relocalizeScoreMin -> Snap / relocalize_accept
无 estimator state 且 score >= startScoreMin -> Snap / first_accept
无 estimator state 且 score < startScoreMin -> Reject / score_hold
已有 state 且 score < holdScoreMin -> Reject / score_hold
已有 state 且 holdScoreMin <= score < trackScoreMin -> Hold / score_hold
已有 state 且与 predicted 的位置差 > maxJumpMeters -> Reject / jump_reject
已有 state 且与 predicted 的旋转差 > maxJumpDegrees -> Reject / jump_reject
其它 -> Accept / score_accept
```

- [ ] Step 4.3: 新增 gate smoke。

Required assertions:

```csharp
AssertNullGateAcceptsReliableTrackWithoutScore();
AssertScoreGateRejectsInvalidFlag();
AssertScoreGateHoldsLowScoreWithoutUpdating();
AssertScoreGateRejectsAbsoluteJump();
AssertScoreGateSnapsRelocalizationWhenScorePasses();
```

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
新增 gate smoke 通过，旧 smoke 仍通过。
```

### Task 5: 实现五个 Estimator

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Estimators/RawAnchorEstimator.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Estimators/LowPassAnchorEstimator.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Estimators/KalmanAnchorEstimator.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Estimators/OneEuroAnchorEstimator.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Estimators/EgoAnchorEstimator.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] Step 5.1: `RawAnchorEstimator`。

Behavior:

```text
Snap/Update 直接保存 observation.WorldPose。
PredictAt 始终返回最近一次 pose，不做插值或外推。
LinearVelocity 和 AngularVelocityRad 可由相邻测量估计，但不用于输出。
Name = "raw_zoh"。
```

- [ ] Step 5.2: `LowPassAnchorEstimator`。

Behavior:

```text
位置使用 EMA：filtered = lerp(filtered, measurement, alpha)。
旋转使用 Slerp(filtered, measurement, alpha)。
velocity = (filtered - previousFiltered) / dt。
PredictAt 使用 velocity * clamp(now - stateTime, 0, maxPredictAheadSeconds * predictionScale)。
Name = "lowpass_predict"。
```

- [ ] Step 5.3: `KalmanAnchorEstimator`。

Behavior:

```text
位置：x/y/z 三个 ConstVelocityKalman。
旋转：用 Quaternion residual log 转成三轴角向量，三轴 ConstVelocityKalman 估计 log-space angular state。
Update 先 Predict 到 observation measurement time，再 Correct。
PredictAt 调用 Kalman predict 到 render time，但不永久推进提交态；需要 Copy/PeekPredict 或内部非破坏性预测。
score 不参与 vanilla Kalman baseline；score-aware Kalman 只有在后续实验需要时另加新 label。
Name = "kalman_cv"。
```

- [ ] Step 5.4: `OneEuroAnchorEstimator`。

Behavior:

```text
使用 OneEuroVector3 + OneEuroRotation。
scoreWeight 固定为 1，不读取 reliability score。
PredictAt 使用 One Euro 导数前推，受 maxPredictAheadSeconds 和 predictionScale 限制。
Name = "oneeuro_vanilla"。
```

- [ ] Step 5.5: `EgoAnchorEstimator`。

Behavior:

```text
使用 OneEuroVector3 + OneEuroRotation。
scoreWeight = lerp(minScoreWeight, 1, normalizedScore)，normalizedScore 根据 trackScoreMin..1 映射。
低 score 时降低 Update alpha，并缩短 PredictAt 的 effective predictAhead。
effectivePredictAhead = rawPredictAhead * predictionScale * scoreFactor * uncertaintyFactor。
uncertaintyFactor 在连续 coast、低 score 或高角速度时下降，最小不小于 0。
Name = "egoanchor"。
```

- [ ] Step 5.6: 新增 estimator contract smoke。

Required assertions:

```csharp
AssertAllEstimatorsSnapThenOutputPose();
AssertRawEstimatorIsZeroOrderHold();
AssertLowPassEstimatorMovesBetweenSamplesWhenPredictionEnabled();
AssertKalmanEstimatorPredictsConstantVelocityBetweenSamples();
AssertOneEuroEstimatorProducesContinuousRenderOutput();
AssertEgoAnchorEstimatorDampsPredictionWhenScoreDrops();
AssertEstimatorsResetClearsState();
```

For continuous motion tests:

```text
输入测量间隔 0.2s，渲染间隔 1/72s，匀速 0.35m/s。
除 Raw 外，continuous estimators 的 maxZeroRun <= 4。
Raw 的 maxZeroRun > 4，作为 ZOH baseline 预期行为。
```

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
新增 estimator smoke 通过。
```

### Task 6: 实现 OutputStage

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Output/PassThroughOutputStage.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Output/StaticLockRateLimitOutputStage.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] Step 6.1: `PassThroughOutputStage`。

Behavior:

```text
Condition 直接返回 estimate.Pose。
Reset 无状态。
```

- [ ] Step 6.2: `StaticLockRateLimitOutputStage`。

Behavior:

```text
维护 accepted estimate 滑动窗口。
进入静止需要同时满足：
  窗口时长 >= staticWindowSeconds
  样本数 >= staticMinSamples
  position spread <= staticRadiusMeters
  rotation spread <= staticRotationDegrees
  linear speed <= staticSpeedMetersPerSecond
  angular speed <= staticAngularSpeedDegreesPerSecond
静止时关闭前推，输出 lock pose 或按 staticCenterTauSeconds 慢速归中。
position residual > staticReleaseMeters 或 rotation residual > staticReleaseDegrees 立即释放。
所有输出经过 maxOutputSpeedMps / maxOutputAngularSpeedDps 单帧限速。
```

- [ ] Step 6.3: 新增 output smoke。

Required assertions:

```csharp
AssertStaticOutputStageLocksSmallResidualSlip();
AssertStaticOutputStageReleasesOnRealMotion();
AssertRateLimitPreventsSingleFrameJump();
AssertPassThroughDoesNotModifyPose();
```

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
新增 output smoke 通过。
```

### Task 7: 实现 `AnchorPipeline`

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Pipeline/Core/AnchorPipeline.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] Step 7.1: 实现 pipeline 编排器。

Required public API:

```csharp
public sealed class AnchorPipeline
{
    public AnchorState State { get; }
    public AnchorMotionState MotionState { get; }
    public string LatestAction { get; }
    public string LatestReason { get; }
    public float LastAcceptedScore { get; }
    public float LastPredictAheadSeconds { get; }
    public float SpeedMps { get; }
    public float AngularSpeedDps { get; }

    public AnchorPipeline(
        AnchorPipelineConfig config,
        IAnchorGate gate,
        IAnchorEstimator estimator,
        IAnchorOutputStage outputStage);

    public AnchorPolicyDecision AcceptPose(AnchorObservation observation);
    public AnchorPolicyOutput Advance(double nowSeconds);
    public void ApplyConfig(AnchorPipelineConfig newConfig);
    public void NotifyReset(double nowSeconds, string reason);
    public void NotifyReacquire(double nowSeconds, string reason);
    public void NotifyPause(double nowSeconds, string reason);
    public void NotifyResume(double nowSeconds, string reason);
    public void NotifyError(double nowSeconds, string reason);
    public void NotifyLost(double nowSeconds, string reason);
    public void Clear(double nowSeconds, string reason);
}
```

State handling:

```text
AcceptPose:
  Paused/Error -> Hold / paused 或 Hold / error
  Missing/align failed -> 不更新 estimator，stateMachine.OnMissingPose
  Gate Snap -> estimator.Snap，stateMachine.OnPoseAccepted
  Gate Accept -> estimator.Update，stateMachine.OnPoseAccepted
  Gate Hold/Reject -> estimator 不动，stateMachine 只更新诊断，不把 reject 当 accepted

Advance:
  !HasEstimate -> AnchorPolicyOutput.None(state, "no_state")
  gap <= coastGraceSeconds -> Tracking / estimate PredictAt(now)
  coastGraceSeconds < gap <= maxCoastSeconds -> Coasting / estimate PredictAt(now)
  maxCoastSeconds < gap < lostTimeoutSeconds -> FrozenUncertain / output freeze
  gap >= lostTimeoutSeconds -> Lost / output None 或 frozen pose，按现有 AnchorStateMachine 语义保持
```

- [ ] Step 7.2: 新增 pipeline smoke。

Required assertions:

```csharp
AssertPipelineMapsGateActionsToPolicyDecision();
AssertPipelineAdvancesEveryRenderFrame();
AssertPipelineCoastsThenFreezesThenLost();
AssertPipelinePauseResumePreservesPose();
AssertPipelineRelocalizeSnapsEstimator();
AssertPipelineClearRemovesState();
```

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
所有 pipeline smoke 通过。
```

### Task 8: 新增 `AnchorPipelineHost`

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPipelineHost.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] Step 8.1: 实现 MonoBehaviour host。

Responsibilities:

```text
持有 AnchorPipelineConfig。
Awake/OnEnable 时构造 gate、estimator、outputStage、AnchorPipeline。
Bind(PoseToAnchorRuntime owner) 采用 1:1 bind guard，和 AnchorPolicyHost 一样防止多个 runtime 绑定同一 host。
AcceptPose / Advance / Notify* / Clear 直接委托给 AnchorPipeline。
OnValidate 调用 config.Validate()。
Inspector 字段全部有中文 Tooltip。
```

Required factory mapping:

```text
AnchorGateMode.None -> NullGate
AnchorGateMode.ScoreJump -> ScoreJumpGate
AnchorEstimatorMode.Raw -> RawAnchorEstimator
AnchorEstimatorMode.LowPass -> LowPassAnchorEstimator
AnchorEstimatorMode.Kalman -> KalmanAnchorEstimator
AnchorEstimatorMode.OneEuro -> OneEuroAnchorEstimator
AnchorEstimatorMode.EgoAnchor -> EgoAnchorEstimator
AnchorOutputStageMode.PassThrough -> PassThroughOutputStage
AnchorOutputStageMode.StaticLockRateLimit -> StaticLockRateLimitOutputStage
```

- [ ] Step 8.2: 新增 host smoke。

Required assertions:

```csharp
AssertAnchorPipelineHostBindsOnce();
AssertAnchorPipelineHostBuildsRequestedStrategy();
AssertAnchorPipelineHostLabelDefaultsToGateEstimatorOutput();
AssertAnchorPipelineHostConfigHotReloadDoesNotClearPose();
```

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
host smoke 通过。
```

### Task 9: 接入 `PoseToAnchorRuntime`

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] Step 9.1: 新增字段，短期和旧 `policyHost` 并存。

Required field:

```csharp
/// <summary>可选模块化 anchor pipeline 宿主。绑定后优先于旧 policyHost 与 processors。</summary>
[Tooltip("可选模块化 anchor pipeline 宿主。绑定后优先于旧 policyHost 与 processors，用于公平 baseline/ours 对比。")]
[SerializeField] private AnchorPipelineHost pipelineHost;
```

Priority:

```text
pipelineHost != null -> 使用新 pipeline
pipelineHost == null && policyHost != null -> 使用旧 policy 路径
pipelineHost == null && policyHost == null -> 使用 processors legacy baseline
```

- [ ] Step 9.2: 抽出内部 helper，减少条件分支重复。

Required helpers:

```csharp
private bool HasRenderFrameController => pipelineHost != null || policyHost != null;
private AnchorPolicyDecision AcceptControllerPose(AnchorObservation observation);
private AnchorPolicyOutput AdvanceController(double nowSeconds);
private AnchorState CurrentControllerState { get; }
```

- [ ] Step 9.3: `LateUpdate` 调整。

Behavior:

```text
只有 pipelineHost 或 policyHost 存在时每帧 AdvanceAnchorOutput。
processors legacy 路径仍只在 pose 到达时 RunProcessors；这条路径保留作旧对照，但论文公平对比使用 pipelineHost。
```

- [ ] Step 9.4: 所有 `NotifyReset/Reacquire/Pause/Resume/Error/Lost/Clear` 同时支持 pipelineHost。

Rules:

```text
pipelineHost 存在时只通知 pipelineHost。
否则通知 policyHost。
不把通知发给 processors。
```

- [ ] Step 9.5: 更新 diagnostics 映射。

Required mapping:

```text
LatestPolicyAction / LatestPolicyReason 来自 pipelineHost 或 policyHost。
CurrentAnchorState 来自 pipelineHost 或 policyHost。
CurrentMotionStateName 来自 pipelineHost 或 policyHost。
LatestPredictAheadMs 来自最新 AnchorPolicyOutput。
旧 latestInnovationPosD2/latestEffectiveMeasurementNoise 对 pipelineHost 写 NaN。
```

- [ ] Step 9.6: 新增 runtime smoke。

Required assertions:

```csharp
AssertPipelinePathSkipsProcessors();
AssertPipelinePathAdvancesInLateUpdateContract();
AssertPipelineHostTakesPriorityOverLegacyPolicyHost();
AssertLegacyPolicyPathStillWorksWhenPipelineMissing();
AssertProcessorPathStillWorksWhenNoHostBound();
```

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected:

```text
smoke PASS；Unity build PASS。
```

### Task 10: Unity Inspector 多变体对比配置

**Files:**

- Modify only by scene/prefab task after code passes; do not edit scene automatically during code task if user has active scene changes.
- Read: `EgoAnchor_Unity/Assets/Scene/` scene files during execution.
- Read: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/AnchorEvalRecorder.cs`

- [ ] Step 10.1: 在 Unity 场景中建立多 runtime 对比结构。

Required scene pattern:

```text
同一个 PoseResultReceiver
  -> AnchorRuntimeHub
     -> PoseToAnchorRuntime raw_zoh + AnchorPipelineHost(Raw/PassThrough)
     -> PoseToAnchorRuntime lowpass_predict + AnchorPipelineHost(LowPass/PassThrough)
     -> PoseToAnchorRuntime kalman_cv + AnchorPipelineHost(Kalman/PassThrough)
     -> PoseToAnchorRuntime oneeuro_vanilla + AnchorPipelineHost(OneEuro/PassThrough)
     -> PoseToAnchorRuntime egoanchor_full + AnchorPipelineHost(EgoAnchor/StaticLockRateLimit)
```

Each runtime:

```text
framePoseHistory 指向同一个 FramePoseHistory。
cameraPoseAligner 配置一致。
alignmentReference 默认 Left。
processors 列表清空。
policyHost 为空。
pipelineHost 绑定对应 AnchorPipelineHost。
DynamicObjectAnchor outputMode 使用 Smoothed。
```

- [ ] Step 10.2: `AnchorEvalRecorder.recordedRuntimes` 记录全部变体。

Labels:

```text
raw_zoh
lowpass_predict
kalman_cv
oneeuro_vanilla
egoanchor_full
```

Primary:

```text
将 egoanchor_full 或 raw_zoh 标为 isPrimary=true。
如果目标是离线回放同一输入，推荐 raw_zoh primary，因为它额外写 aligned_raw_pos/rot 和 reliability_score。
```

- [ ] Step 10.3: 手动真机 smoke。

Checklist:

```text
所有变体的 LatestAlignedFrameId 同步增长。
raw_zoh 能看到阶梯输出。
kalman_cv / oneeuro_vanilla / egoanchor_full 在两帧 pose 之间有连续输出。
egoanchor_full 低分时不被异常 pose 拖走。
AnchorEvalRecorder 输出 variants 中包含所有 label。
```

### Task 11: 增强评估日志元数据

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/AnchorEvalRecorder.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/AnchorEvalJson.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/EvalSessionManifestJson.cs`
- Modify: `EgoAnchor_Python/eval/io/schemas.py`
- Modify: `EgoAnchor_Python/eval/tests/test_log_loader.py`

- [ ] Step 11.1: 扩展 `RecordedVariantSnapshot`。

Add fields:

```csharp
public readonly string StrategyLabel;
public readonly string GateMode;
public readonly string EstimatorMode;
public readonly string OutputStageMode;
public readonly string ConfigHash;
```

Rules:

```text
pipelineHost 存在时从 AnchorPipelineHost 暴露属性读取。
legacy policyHost 时 StrategyLabel="legacy_policy"，其余模式为空字符串。
processor legacy 时 StrategyLabel="legacy_processor"，其余模式为空字符串。
```

- [ ] Step 11.2: `AppendVariant` 写入可选元数据字段。

Fields:

```json
"strategy_label": "egoanchor_full",
"gate_mode": "ScoreJump",
"estimator_mode": "EgoAnchor",
"output_stage_mode": "StaticLockRateLimit",
"config_hash": "..."
```

- [ ] Step 11.3: Python schema 只做可选读取，不破坏旧日志。

Add optional columns in `VariantRow.to_record()`:

```python
"strategy_label": str(self.raw.get("strategy_label", "")),
"gate_mode": str(self.raw.get("gate_mode", "")),
"estimator_mode": str(self.raw.get("estimator_mode", "")),
"output_stage_mode": str(self.raw.get("output_stage_mode", "")),
"config_hash": str(self.raw.get("config_hash", "")),
```

- [ ] Step 11.4: Manifest 写策略摘要。

Add `variant_configs` array:

```json
[
  {
    "label": "egoanchor_full",
    "gate_mode": "ScoreJump",
    "estimator_mode": "EgoAnchor",
    "output_stage_mode": "StaticLockRateLimit",
    "config_hash": "..."
  }
]
```

Python `Manifest` 保持 `raw=dict(row)`，不需要强制 dataclass 字段。

- [ ] Step 11.5: 验证旧日志仍可读，新日志字段可读。

Run:

```powershell
cd EgoAnchor_Python
pixi run python -m unittest discover -s eval -p "test_*.py"
```

Expected:

```text
OK
```

### Task 12: 新增 headless C# replay

**Files:**

- Create: `EgoAnchor_Tools/anchor_replay/AnchorReplay.csproj`
- Create: `EgoAnchor_Tools/anchor_replay/Program.cs`
- Modify: `EgoAnchor_Python/eval/tests/test_run_eval.py`

- [ ] Step 12.1: 创建 csproj，复用 smoke 的 UnityEngine 引用和 compile include。

Required includes:

```xml
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorObservation.cs" Link="Policy\AnchorObservation.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorPolicyDecision.cs" Link="Policy\AnchorPolicyDecision.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorPolicyOutput.cs" Link="Policy\AnchorPolicyOutput.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorLifecycleEvent.cs" Link="Policy\AnchorLifecycleEvent.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorStateMachine.cs" Link="Policy\AnchorStateMachine.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorPipelineConfig.cs" Link="Policy\AnchorPipelineConfig.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline\Core\*.cs" LinkBase="Policy\Pipeline\Core" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline\Math\*.cs" LinkBase="Policy\Pipeline\Math" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline\Gates\*.cs" LinkBase="Policy\Pipeline\Gates" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline\Estimators\*.cs" LinkBase="Policy\Pipeline\Estimators" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline\Output\*.cs" LinkBase="Policy\Pipeline\Output" />
```

- [ ] Step 12.2: Program 输入参数。

Required CLI:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_replay\AnchorReplay.csproj -- --session EgoAnchor_Python\data\eval\offline_data --out EgoAnchor_Python\data\eval\offline_data\anchor_replay
```

Supported arguments:

```text
--session <directory>  包含 session_manifest.json、*_unity_output.jsonl、*_unity_capture.jsonl 的目录
--out <directory>      replay 输出目录
--render-hz <float>    不传时复用 unity_output 的 render_mono_ms；传入时生成固定渲染网格
--strategies <csv>     不传时跑 raw_zoh,lowpass_predict,kalman_cv,oneeuro_vanilla,egoanchor_full
```

- [ ] Step 12.3: Replay 输入构造。

Rules:

```text
从 unity_output.variants 中寻找 is_primary=true 且 has_aligned_raw=true 的 variant。
读取 aligned_raw_pos/aligned_raw_rot 作为所有策略共享测量输入。
读取 source_frame_id、source_capture_mono_ms、reliability_score、latest_phase、latest_failure。
render tick 使用 unity_output.render_mono_ms 和 GT pose。
每个新 source_frame_id 只 AcceptPose 一次，避免同一测量在多个渲染 tick 重复提交。
```

- [ ] Step 12.4: Replay 输出。

Files:

```text
anchor_replay_output.jsonl
anchor_replay_summary.csv
anchor_replay_config.json
```

`anchor_replay_output.jsonl` 采用 `unity_output` 兼容结构：

```json
{
  "event": "unity_output",
  "render_mono_ms": 1234.0,
  "render_unix_ms": 0.0,
  "render_unity_frame": 10,
  "source_frame_id": 200,
  "head_pos": [0,0,0],
  "head_rot": [0,0,0,1],
  "gt_pos": [0,0,0],
  "gt_rot": [0,0,0,1],
  "gt_pose_valid": true,
  "gt_pose_source": "transform",
  "variants": []
}
```

Each replay variant includes:

```json
"label": "kalman_cv",
"has_stable": true,
"stable_pos": [0,0,0],
"stable_rot": [0,0,0,1],
"anchor_state": "Tracking",
"policy_action": "Accept",
"policy_reason": "score_accept",
"has_source_capture_timing": true,
"source_capture_mono_ms": 1000.0,
"has_aligned_raw": true,
"aligned_raw_pos": [0,0,0],
"aligned_raw_rot": [0,0,0,1],
"reliability_score": 0.9,
"strategy_label": "kalman_cv",
"gate_mode": "None",
"estimator_mode": "Kalman",
"output_stage_mode": "PassThrough"
```

- [ ] Step 12.5: Summary 指标。

`anchor_replay_summary.csv` columns:

```text
label
render_rows
measurement_rows
valid_gt_rows
static_jitter_pos_mm
static_jitter_rot_deg
moving_rmse_pos_mm
moving_rmse_rot_deg
lag_ms
max_zero_run
jump_reject_count
hold_count
lost_count
```

- [ ] Step 12.6: 验证 replay 可跑。

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_replay\AnchorReplay.csproj -- --session EgoAnchor_Python\data\eval\offline_data --out EgoAnchor_Python\data\eval\offline_data\anchor_replay
```

Expected:

```text
写出 anchor_replay_output.jsonl、anchor_replay_summary.csv、anchor_replay_config.json。
summary 至少包含 raw_zoh、lowpass_predict、kalman_cv、oneeuro_vanilla、egoanchor_full 五行。
```

### Task 13: 将 replay 输出接回 Python eval

**Files:**

- Modify: `EgoAnchor_Python/eval/io/log_loader.py`
- Modify: `EgoAnchor_Python/eval/tests/test_run_eval.py`

- [ ] Step 13.1: 支持 replay report 目录读取。

Rule:

```text
如果 session 目录下存在 anchor_replay/anchor_replay_output.jsonl，允许 eval.run_eval 通过 --output-log 参数指定该文件。
默认行为仍读取原始 *_unity_output.jsonl。
```

CLI:

```powershell
cd EgoAnchor_Python
pixi run python -m eval.run_eval --session-dir .\data\eval\offline_data --output-log .\data\eval\offline_data\anchor_replay\anchor_replay_output.jsonl --report-dir .\data\eval\offline_data\anchor_replay\report --only tables
```

Expected:

```text
anchor_error_summary.csv、jitter.csv、lag.csv、latency.csv、policy_distribution.csv 均生成。
```

- [ ] Step 13.2: 新增单测，构造一个 replay output 文件并确认 loader 能展开 strategy metadata。

Assertions:

```python
self.assertIn("strategy_label", logs.output.columns)
self.assertEqual(set(logs.output["label"]), {"raw_zoh", "egoanchor_full"})
self.assertTrue((report_dir / "anchor_error_summary.csv").is_file())
```

### Task 14: Unity 录制回放源，用于视频复现

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/RecordedAnchorReplaySource.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/RecordedAnchorReplayController.cs`

- [ ] Step 14.1: `RecordedAnchorReplaySource` 读取 JSONL 中的 aligned raw 输入。

Behavior:

```text
Inspector 输入 sessionDirectory。
读取 *_unity_output.jsonl。
选择 primary variant 的 aligned_raw_pos/rot、source_frame_id、source_capture_mono_ms、reliability_score。
按录制时间或用户设置的 playbackSpeed 在 Unity 中重放。
```

- [ ] Step 14.2: 重放时不走 NATS，不启动 Python。

Integration:

```text
直接调用 AnchorRuntimeHub 或指定 PoseToAnchorRuntime 的测试入口。
需要新增 PoseToAnchorRuntime.AcceptAlignedWorldPoseForReplay(...)，只接收 Unity world pose、frame_id、captureTime、score、phase。
该入口仅用于 eval/replay，summary 写清楚不解码 PoseResult、不改坐标变换。
```

- [ ] Step 14.3: Replay controller 支持暂停、单步、循环。

Inspector fields:

```text
playOnStart
playbackSpeed
loop
startMonoMs
endMonoMs
targetRuntimes
```

- [ ] Step 14.4: 手动验证。

Checklist:

```text
Unity 未连接 Python/NATS 时能复现轨迹。
所有 pipeline variants 输出与 headless replay 同一趋势。
可录制 supplementary video。
```

### Task 15: 实现 Recovery 正交层

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] Step 15.1: 新增 controller。

Inspector fields:

```csharp
[SerializeField] private PoseToAnchorRuntime runtime;
[SerializeField] private AnchorCommandClient commandClient;
[SerializeField] private AnchorRecoveryMode recoveryMode = AnchorRecoveryMode.Off;
[SerializeField] private float lowScoreThreshold = 0.25f;
[SerializeField] private float lowScoreSeconds = 0.8f;
[SerializeField] private float lostSeconds = 0.3f;
[SerializeField] private float noPoseSeconds = 1.0f;
[SerializeField] private float cooldownSeconds = 3.0f;
[SerializeField] private bool clearTrackingFirst = true;
```

Behavior:

```text
Off: 不发送 command。
TimeoutOnly: Lost、no_pose、align_failed 持续超过阈值后发送 reacquire。
ScoreAware: TimeoutOnly + reliability_score 连续低于 lowScoreThreshold 超过 lowScoreSeconds 后发送 reacquire。
command in-flight 时不重复发送。
cooldown 未结束时不重复发送。
runtime LatestHeartbeatInputReady=false 时不发送 command，只记录等待原因。
组件不修改 Transform，不解码 PoseResult，不直接清 Python 模型状态。
```

- [ ] Step 15.2: smoke 用 reflection 检查字段和非阻塞触发逻辑。

Required assertions:

```csharp
AssertRecoveryControllerDoesNothingWhenOff();
AssertRecoveryControllerTriggersOnLostInTimeoutMode();
AssertRecoveryControllerTriggersOnLowScoreOnlyInScoreAwareMode();
AssertRecoveryControllerHonorsCooldownAndInFlight();
AssertRecoveryControllerWaitsWhenInputNotReady();
```

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
recovery smoke 通过。
```

### Task 16: RQ1 frame-aligned vs arrival-time mapping 诊断路径

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/CameraPoseFrameAligner.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/AnchorEvalRecorder.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/AnchorEvalJson.cs`
- Modify: `EgoAnchor_Python/eval/metrics/slip.py`
- Modify: `EgoAnchor_Python/eval/tests/test_run_eval.py`

- [ ] Step 16.1: 增加 arrival-time baseline 但不改变默认 anchor。

Implementation rule:

```text
默认仍使用 frame_id -> capture-time camera pose。
新增诊断方法只为记录 arrival_time_aligned_raw，不驱动主 method。
arrival-time pose 使用 pose 到达或渲染时刻的当前参考 camera world pose，与同一 PoseResult camera-space pose 组合。
```

- [ ] Step 16.2: 记录额外 variant 或额外字段。

Recommended label:

```text
arrival_time_raw
frame_aligned_raw
```

Metrics:

```text
快速头动条件下比较 world-space slip、anchor error、head-motion-induced drift。
RQ1 图表只使用 raw mapping，不混入 filter/policy。
```

- [ ] Step 16.3: 验证默认行为不变。

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected:

```text
smoke/build 通过；没有任何默认场景从 capture-time mapping 回退到 arrival-time mapping。
```

### Task 17: 清理 legacy policy 与 processors

**Files:**

- Modify or delete after user confirms scene migration:
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Processors/AnchorPoseProcessor.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Processors/AnchorLowPassPoseProcessor.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Processors/AnchorKalmanPoseProcessor.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPoseFilter.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/MotionStateClassifier.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs`

- [ ] Step 17.1: 先冻结 legacy，不立即删除。

Rule:

```text
在 AnchorPipelineHost 通过 smoke、Unity build、headless replay、至少一次真机录制前，不删除旧文件。
```

- [ ] Step 17.2: scene 全部迁移到 pipelineHost 后，删除 legacy 入口。

Deletion condition:

```text
rg "policyHost|processors" EgoAnchor_Unity\Assets\Scene EgoAnchor_Unity\Assets\Scripts\EgoAnchor
只剩文档说明或 legacy 删除提交中的预期引用。
```

- [ ] Step 17.3: 删除旧 `Processors/` 或将其标记为非论文 legacy。

Decision:

```text
如果所有 baseline 已由 Pipeline Estimator 覆盖，则删除 Processors。
如果还需要旧 scene 临时对照，则保留但文档明确“不用于论文公平对比”。
```

### Task 18: 文档同步

**Files:**

- Modify: `ANCHOR_CONTROLLER_GUIDE.md`
- Modify: `AGENTS.md`
- Modify: `2026-EgoAnchor/egoanchor_cn_outline.tex`
- Modify: `2026-EgoAnchor/egoanchor_cn_v1.tex`

- [ ] Step 18.1: 更新 `ANCHOR_CONTROLLER_GUIDE.md`。

Required content:

```text
AnchorPipelineHost 使用方式。
Gate / Estimator / OutputStage 参数表。
五个 baseline label 的含义。
如何在 AnchorEvalRecorder 中设置 recordedRuntimes。
如何运行 anchor_replay。
recovery 为独立组件，不属于滤波器。
```

- [ ] Step 18.2: 更新 `AGENTS.md` 用户维护区块之外的事实。

Rules:

```text
不得修改 USER-MAINTAINED-REQUIREMENTS 区块。
只更新当前 Unity Policy/Runtime/Eval 事实。
删除与已移除 legacy 矛盾的描述。
```

- [ ] Step 18.3: 论文只写已验证事实。

Conservative wording:

```text
未完成实验前：写成 “we implement a modular anchor synchronization pipeline and evaluate policy choices”。
只有 replay/真机数据证明 egoanchor_full 优于 Kalman/OneEuro 后：写成 “score-aware anchor synchronization improves jitter-lag trade-off under unreliable pose streams”。
不要把 FoundationPose 的任意物体能力写成本文核心方法贡献。
```

### Task 19: 完整验证门

**Files:** no planned edits.

- [ ] Step 19.1: Unity smoke。

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
Anchor policy smoke passed.
```

- [ ] Step 19.2: Unity build。

Run:

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected:

```text
Build succeeded.
```

- [ ] Step 19.3: Python eval tests。

Run:

```powershell
cd EgoAnchor_Python
pixi run python -m unittest discover -s eval -p "test_*.py"
```

Expected:

```text
OK
```

- [ ] Step 19.4: Headless replay。

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_replay\AnchorReplay.csproj -- --session EgoAnchor_Python\data\eval\offline_data --out EgoAnchor_Python\data\eval\offline_data\anchor_replay
```

Expected:

```text
anchor_replay_summary.csv 包含 raw_zoh、lowpass_predict、kalman_cv、oneeuro_vanilla、egoanchor_full。
raw_zoh 的 max_zero_run 高于连续 estimator。
kalman_cv 与 oneeuro_vanilla 有逐渲染帧输出。
egoanchor_full 不因低分 outlier 产生大跳。
```

- [ ] Step 19.5: Python eval 读取 replay 输出。

Run:

```powershell
cd EgoAnchor_Python
pixi run python -m eval.run_eval --session-dir .\data\eval\offline_data --output-log .\data\eval\offline_data\anchor_replay\anchor_replay_output.jsonl --report-dir .\data\eval\offline_data\anchor_replay\report --only tables
```

Expected:

```text
report 目录生成 anchor_error_summary.csv、jitter.csv、lag.csv、latency.csv、policy_distribution.csv。
```

- [ ] Step 19.6: 代码搜索。

Run:

```powershell
rg -n "Time\\." EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\Pipeline
rg -n "policyHost|processors" EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Runtime\PoseToAnchorRuntime.cs
```

Expected:

```text
第一条无输出。
第二条只剩兼容期的明确优先级分支；legacy cleanup 完成后应无输出。
```

## 5. 实验路线

### RQ1: Frame-aligned anchoring 是否必要

变量：

```text
frame_aligned_raw
arrival_time_raw
```

固定：

```text
不使用 filter，不使用 score gate，不使用 recovery。
```

条件：

```text
static object + slow head motion
static object + fast head motion
object motion with moderate head motion
```

指标：

```text
world-space anchor error
head-motion-induced slip
jitter under static GT
capture_to_apply latency
```

预期论点：

```text
异步 pose 到达时 HMD 已经移动，arrival-time mapping 会把相机时序误差转换成 world anchor slip；frame_id capture-time 回查是 EgoAnchor 的系统核心。
```

### RQ2: Anchor synchronization policy 的 jitter-lag 权衡

变量：

```text
raw_zoh
lowpass_predict
kalman_cv
oneeuro_vanilla
egoanchor_no_static
egoanchor_full
```

固定：

```text
同一份 frame-aligned raw pose 输入。
同一份 render_mono_ms 网格。
recovery=Off。
```

指标：

```text
static_jitter_pos_mm
moving_rmse_pos_mm
lag_ms
max_zero_run
jump_reject_count
policy_distribution
```

解释规则：

```text
如果 egoanchor_full 赢过 kalman_cv 和 oneeuro_vanilla，policy 可以作为论文贡献的一部分。
如果 egoanchor_full 只接近强 baseline，则 policy 写成系统实现选择，论文主贡献回到 frame-aligned pose-to-anchor。
如果 kalman_cv 明显赢，保留 Kalman 作为默认强方法，score-aware gate/recovery 作为附加机制。
```

### RQ3: Recovery 是否改善可恢复 anchor 行为

变量：

```text
egoanchor_full + Recovery Off
egoanchor_full + TimeoutOnly
egoanchor_full + ScoreAware
```

条件：

```text
短遮挡
长遮挡
出视野再进入
低分但未彻底丢 pose
```

指标：

```text
recovery_success_rate
recovery_time_ms
false_reacquire_count
anchor_error_after_recovery
command_count
```

## 6. 验收标准

工程验收：

- 所有 pipeline module 是 plain C#，不读取 `UnityEngine.Time`。
- `PoseToAnchorRuntime` 的 frame-aligned 坐标转换默认不变。
- `DynamicObjectAnchor` 不承载滤波、状态机、网络或 recovery 逻辑。
- Unity Inspector 可以为多个 anchor runtime 选择不同 `Gate / Estimator / OutputStage`。
- `AnchorEvalRecorder` 可以在一份 session 中记录多个策略变体。
- `anchor_replay` 可以用同一份 recorded aligned raw 输入复现全部策略。
- Python eval 能读取 replay 输出并生成同一套表。

论文验收：

- RQ1 和 RQ2 分开，不把 frame alignment 与 filter policy 混为一个变量。
- RQ2 的所有策略共享同一输入和渲染时钟。
- Recovery 只在 RQ3 出现，不混入滤波 baseline 对比。
- 论文不声称未验证的机制已经提升效果。

## 7. 风险与处理

| 风险 | 处理 |
| --- | --- |
| 新 pipeline 与旧 policy 并存造成 Inspector 混乱 | `PoseToAnchorRuntime` 明确优先级：`pipelineHost > policyHost > processors`，并在绑定时输出一次日志。 |
| C# replay 与 Unity 实时行为不一致 | replay 直接 compile include Unity pipeline 源文件，不重写算法。 |
| One Euro 默认参数不稳 | 通过 replay 先调默认值；参数不达标时不把 One Euro 写成贡献。 |
| Kalman 强 baseline 赢过 ours | 论文保守处理：系统贡献仍成立，policy 贡献降级，Kalman 作为默认 estimator 候选。 |
| JSONL schema 破坏旧数据 | 新字段全作为 optional metadata；`VariantRow.raw` 保留原始字段，旧 required 字段不改名。 |
| Scene 有用户改动 | 代码阶段不自动改 scene；多变体 scene 绑定单独执行，执行前读 `git status --short`。 |
| Recovery 误触发频繁 | `cooldown + in-flight guard + input_ready guard` 三层限制，并单独统计 command_count。 |

## 8. 执行顺序建议

第一批必须一起完成，才能回答 baseline 公平性：

```text
Task 0 -> Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5 -> Task 6 -> Task 7 -> Task 8 -> Task 9 -> Task 12 -> Task 13
```

第二批用于真机展示与论文视频：

```text
Task 10 -> Task 11 -> Task 14
```

第三批用于 RQ3 和论文收尾：

```text
Task 15 -> Task 16 -> Task 17 -> Task 18 -> Task 19
```

每个批次结束都要提交一次独立 commit。推荐 commit 粒度：

```text
feat(anchor): add modular pipeline interfaces
feat(anchor): add estimator baselines
feat(anchor): integrate pipeline host with runtime
feat(eval): add anchor replay runner
feat(eval): record pipeline strategy metadata
feat(anchor): add recovery controller
docs(anchor): document modular pipeline workflow
```

## 9. 给执行 agent 的注意事项

- 修改代码前再次阅读 `AGENTS.md` 顶部用户手动维护要求。
- Python 侧新增 eval import 必须走包级入口，不做深层业务导入。
- 新增 Unity 类、字段、方法必须有中文 XML summary；Inspector 字段必须有中文 `[Tooltip]`。
- 不手改 Protobuf 生成代码和 `SubjectNames.cs`。
- 不把 policy 逻辑放进 `NatsControlClient`、`PoseResultReceiver`、`DynamicObjectAnchor`。
- 不使用 pose 到达时 HMD pose 替代 capture-time frame pose。
- 不在第一阶段删除旧 policy/processor 文件；等 pipeline 真机与 replay 验证完成再清理。
- 不把尚未通过 replay/真机实验的 policy 效果写成论文贡献。
