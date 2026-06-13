# Anchor Policy Modular Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Unity anchor runtime 重构为可插拔、可并行对比、可离线回放的 anchor policy。所有 baseline 和 EgoAnchor 方法必须共享同一 frame-aligned raw pose 输入、同一 capture/render 时间轴、同一 `Advance(now)` 输出契约。

**Architecture:** Python 感知、Protobuf、ZMQ/NATS、`FramePoseHistory` 和 `CameraPoseFrameAligner` 不改。Unity anchor 侧新增模块化 policy：`GateModule -> EstimatorModule -> OutputStageModule`，其中 `EstimatorModule` 负责滤波、升采样和预测。Inspector 不用 enum 下拉选策略；每个 anchor 的 `AnchorPolicyHost` 引用三类抽象 `MonoBehaviour` 模块基类：`AnchorGateModule`、`AnchorEstimatorModule`、`AnchorOutputStageModule`。具体模块子类自己声明 `[SerializeField]` 参数，这些参数直接显示在 Inspector 上；模块子类直接实现 `Evaluate / Snap / Update / PredictAt / Condition / ResetModule`，不额外封装 config/data 类，也不再额外封装 `AnchorGate`、`AnchorEstimator`、`AnchorOutputStage` 这类 core 类型。模块文件按职责分成 `Policy/Core`、`Policy/Gate`、`Policy/Estimator`、`Policy/Output` 四个目录，不再保留 `Policy/Pipeline` 中间层。

**Tech Stack:** Unity C#、abstract MonoBehaviour module components、plain C# math/DTO helpers、`EgoAnchor_Tools/anchor_policy_smoke`、`EgoAnchor_Tools/anchor_replay`（headless dotnet 策略分析回放，主力）、Unity `AnchorTrajectoryPlayer`（视频回放）+ 可选 batchmode 一致性抽查、`dotnet build`、`EgoAnchor_Python/eval` JSONL 指标框架、真实录制 fixture `EgoAnchor_Python/data/eval/offline_data`。

---

## 0. 这份计划的裁决

这份文件是后续 anchor 同步策略重构的主计划，取代 `docs/claude/1.md`、`docs/claude/补充.md`、`docs/gpt/task_plan.md`、`docs/claude/2026-06-13-anchor-pipeline-modular-architecture.md` 和 `docs/superpowers/plans/2026-06-13-anchor-pipeline-modular-architecture.md` 的执行层。旧文件可以作为讨论记录看，但实施以本文为准。

裁决点如下。

1. 不直接把当前 policy 改成 One Euro。先统一 runtime 契约，让 raw、low-pass、Kalman、vanilla One Euro、EgoAnchor 都能在渲染帧 `Advance(now)`。
2. 不在 Unity Inspector 用 enum 选模块，也不使用 interface 字段。Inspector 侧用抽象 `MonoBehaviour` 基类引用：`AnchorGateModule`、`AnchorEstimatorModule`、`AnchorOutputStageModule`。字段不能写成裸 `MonoBehaviour`，只能接收继承对应抽象基类的模块脚本。
3. module component 本身就是策略实现，不再包一层 core 策略对象。参数字段直接写在具体 module 子类里；算法方法也写在 module 子类里。模块不得在内部读取 `UnityEngine.Time`，时间只能由 `AnchorPolicyHost` 显式传入。
4. `EgoAnchor_Python/data/eval/offline_data` 是阶段 A 默认离线测试输入。它是真实实时数据，不是 toy fixture；用于先回答 baseline 是否公平、旧 `kalman` 是否真的比 raw 好、EgoAnchor 是否值得写成论文贡献。
5. 不保留旧 controller、旧 processor 链或旧 host 兼容路径。`PoseToAnchorRuntime` 只绑定新的 `AnchorPolicyHost`；raw、low-pass、Kalman、One Euro 和 EgoAnchor 都用 Gate/Estimator/Output module 组合表达。

## 1. 当前项目事实

已核对的代码事实：

- `AnchorRuntimeHub` 已经把一条 `PoseResult` 广播给多个 `PoseToAnchorRuntime`。这正好支持同一输入流驱动多个 baseline/method。
- `AnchorEvalRecorder` 已经支持 `recordedRuntimes`，并把每个 runtime 写成 `unity_output.jsonl` 的一个 `variants[]` 元素。每个 variant 有 `label`、`stable_pos`、`stable_rot`、`anchor_state`、`policy_action`、`policy_reason`、`source_capture_mono_ms` 等字段。
- `PoseToAnchorRuntime` 只负责 frame-aligned world pose 输入和 `AnchorPolicyHost` 输出推进；旧 controller/filter/processor 链和旧 Raw/Smoothed 输出模式不再保留。
- 当前 `policyHost` 路径每帧在 `LateUpdate` 调 `AdvanceAnchorOutput(Time.realtimeSinceStartupAsDouble)`。所有 baseline 和 method 在同一 capture/render 时间轴上比较。
- `DynamicObjectAnchor` 只读取 `TryGetStablePose(...)`，raw/stable 差异全部由 `AnchorPolicyHost` module 组合表达。

真实离线数据：

```text
EgoAnchor_Python/data/eval/offline_data/session_manifest.json
EgoAnchor_Python/data/eval/offline_data/python_session.json
EgoAnchor_Python/data/eval/offline_data/20260613_181828_controller_right_python_runtime.jsonl
EgoAnchor_Python/data/eval/offline_data/20260613_181828_controller_right_unity_capture.jsonl
EgoAnchor_Python/data/eval/offline_data/20260613_181828_controller_right_unity_output.jsonl
```

这份 session 的关键情况：

```text
session_id: 20260613_181828_controller_right
object_id: controller_right
duration: 约 48 秒
variant_labels: kalman, raw
capture rows: 1152
output rows after variant flatten: 6414，即 kalman/raw 各 3207
pose_result rows: 460，其中 has_pose=true 约 341
condition_spans: 空，因此当前指标 condition 都是 unlabeled
event_markers: 空，因此 recovery 表为空是正常现象
```

我已用现有 eval 入口验证可读：

```powershell
cd EgoAnchor_Python
pixi run python -m eval.run_eval --session-dir .\data\eval\offline_data --only tables
```

生成了 `data/eval/offline_data/report`。当前报告显示 `raw` 并不比旧 `kalman` 差：

```text
anchor_error_summary:
  kalman translation_rmse_m = 0.04087
  raw    translation_rmse_m = 0.04009

jitter_summary:
  kalman position_jitter_rms_m = 0.03314
  raw    position_jitter_rms_m = 0.03060

latency_summary:
  capture_to_apply_p50_ms = 180.70
  perception_total_p50_ms = 140.23
```

这不说明 raw 一定更好。它说明旧 `kalman` label 不能作为论文里的强 baseline。我们必须用同一份 `aligned_raw` 输入离线重跑 `raw_zoh / lowpass_predict / kalman_cv / oneeuro_vanilla / egoanchor_full`。

## 2. 流程与数学边界

正确流程是两个时钟：

```text
测量时钟，约 4-8Hz，使用 capture-time：
  AnchorObservation
    -> Gate: 接受、拒绝、hold、snap
    -> Estimator.Update/Snap: 滤波、状态融合、速度估计

渲染时钟，约 60-90Hz，使用 render-time：
  Estimator.PredictAt(now)
    -> OutputStage.Condition(...)
    -> AnchorPolicyOutput
    -> DynamicObjectAnchor / AnchorEvalRecorder
```

几个硬约束：

- 滤波在前，预测在后。速度必须从状态历史估计，不能先对单帧 raw pose 做预测。
- 预测是 Estimator 的内在能力，不拆成独立“预测模块”。Kalman 的 predict/update 和协方差耦合；One Euro 的速度来自导数低通。把 Kalman predict 和 One Euro filter 串起来会变成两层平滑，增加 lag。
- baseline 不使用 EgoAnchor 的 score 特化。普通 `kalman_cv`、`oneeuro_vanilla`、`lowpass_predict` 忽略 score。若以后需要 `kalman_score_adaptive`，它必须作为单独消融 label，不混进 baseline。
- Recovery 是正交层，不属于滤波器。RQ2 比滤波/同步策略时 recovery 关闭；RQ3 再比较 `Off / TimeoutOnly / ScoreAware`。

## 3. 最终架构

### 3.1 共享 DTO 与数学工具

新增共享 DTO 和数学工具放在现有 `Policy/` 边界内，避免引入新的顶层架构目录。这里不定义 `AnchorGate`、`AnchorEstimator`、`AnchorOutputStage`、`AnchorStrategy` 这类二次抽象；策略行为直接写在对应 module component 子类中。

```text
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Core/
  AnchorModuleContracts.cs
  AnchorPolicyTypes.cs

EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Core/
  AnchorMath.cs

EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Estimator/
  ConstVelocityKalman.cs
  OneEuroEstimatorModule.cs 内部私有 OneEuro helper
```

共享 DTO：

```csharp
namespace EgoAnchor.Policy
{
    /// <summary>
    /// EstimatorModule 在指定时间点预测得到的 anchor 状态。
    /// </summary>
    public readonly struct AnchorEstimate
    {
        public readonly Pose Pose;
        public readonly Vector3 LinearVelocity;
        public readonly Vector3 AngularVelocityRad;
        public readonly double TimeSeconds;
        public readonly float ReliabilityScore;
    }
}
```

复用现有对外类型：

```text
AnchorObservation
AnchorPolicyDecision
AnchorPolicyOutput
AnchorState
AnchorMotionState
```

不要新增 `AnchorSample` 作为对外主输入。现有 mapper、recorder、smoke 已围绕 `AnchorObservation` 建立。

### 3.2 Inspector component modules

Inspector 不放 enum，也不使用 interface 字段。新增抽象 `MonoBehaviour` 模块基类，`AnchorPolicyHost` 序列化引用这些基类。参数字段写在具体模块子类里，Unity Inspector 直接显示这些 `[SerializeField]` 字段；不要再封装 `ScoreJumpGateConfig`、`KalmanEstimatorConfig` 这类独立数据段。这样配置仍在 Inspector 上，但只有继承对应抽象基类的模块脚本能被拖进字段：

```text
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Gate/
  AnchorGateModule.cs
  NullGateModule.cs
  ScoreJumpGateModule.cs

EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Estimator/
  AnchorEstimatorModule.cs
  RawEstimatorModule.cs
  LowPassEstimatorModule.cs
  KalmanEstimatorModule.cs
  OneEuroEstimatorModule.cs
  EgoAnchorEstimatorModule.cs

EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Output/
  AnchorOutputStageModule.cs
  PassThroughOutputModule.cs
  StaticLockRateLimitOutputModule.cs
```

模块基类示意：

```csharp
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Gate component 基类。该组件直接实现测量门控逻辑；
    /// 参数显示在 Inspector 中，不读取 Unity Time。
    /// </summary>
    public abstract class AnchorGateModule : MonoBehaviour
    {
        /// <summary>日志和 eval 使用的模块名。</summary>
        public abstract string ModuleName { get; }

        /// <summary>根据当前观测和预测状态决定测量如何进入 estimator。</summary>
        public abstract GateDecision Evaluate(in AnchorObservation observation, in AnchorEstimate predicted, bool hasEstimate);

        /// <summary>清空门控模块内部状态。</summary>
        public abstract void ResetModule();
    }

    /// <summary>
    /// Estimator component 基类。每个 anchor runtime 只引用一个 estimator module。
    /// </summary>
    public abstract class AnchorEstimatorModule : MonoBehaviour
    {
        /// <summary>日志和 eval 使用的模块名。</summary>
        public abstract string ModuleName { get; }

        /// <summary>是否已有可输出估计状态。</summary>
        public abstract bool HasEstimate { get; }

        /// <summary>重定位、首次接受或强校正时直接吸附到测量。</summary>
        public abstract void Snap(in AnchorObservation observation);

        /// <summary>用一帧通过门控的测量更新估计状态。</summary>
        public abstract void UpdateEstimate(in AnchorObservation observation);

        /// <summary>把估计状态预测到指定渲染时间。</summary>
        public abstract AnchorEstimate PredictAt(double renderTimeSeconds);

        /// <summary>清空估计器内部状态。</summary>
        public abstract void ResetModule();
    }

    /// <summary>
    /// OutputStage component 基类。
    /// </summary>
    public abstract class AnchorOutputStageModule : MonoBehaviour
    {
        /// <summary>日志和 eval 使用的模块名。</summary>
        public abstract string ModuleName { get; }

        /// <summary>对 estimator 输出做最后显示整形，例如静止锁、限速或直接透传。</summary>
        public abstract Pose Condition(in AnchorEstimate estimate, double renderTimeSeconds, in OutputContext context);

        /// <summary>清空输出模块内部状态。</summary>
        public abstract void ResetModule();
    }
}
```

具体模块继承对应抽象基类，直接实现算法。需要参数的模块直接在子类里声明字段，例如：

```csharp
namespace EgoAnchor.Policy
{
    /// <summary>
    /// 使用可靠性分数和绝对跳变阈值的门控模块。
    /// </summary>
    public sealed class ScoreJumpGateModule : AnchorGateModule
    {
        [Tooltip("首次接受测量需要达到的最低可靠性分数。")]
        [SerializeField] private float startScoreMin = 0.35f;

        [Tooltip("已有稳定状态后正常更新需要达到的可靠性分数。")]
        [SerializeField] private float trackScoreMin = 0.20f;

        [Tooltip("低于该分数时拒绝测量，避免低质量 pose 拉动 anchor。")]
        [SerializeField] private float holdScoreMin = 0.12f;

        [Tooltip("单帧允许的最大平移跳变，单位米。")]
        [SerializeField] private float maxJumpMeters = 0.80f;

        public override string ModuleName => "score_jump_gate";

        public override GateDecision Evaluate(in AnchorObservation observation, in AnchorEstimate predicted, bool hasEstimate)
        {
            return EvaluateScoreJumpRules(observation, predicted, hasEstimate);
        }

        public override void ResetModule() { }

        private GateDecision EvaluateScoreJumpRules(in AnchorObservation observation, in AnchorEstimate predicted, bool hasEstimate)
        {
            // 这里直接实现 score/jump 门控，不再 new ScoreJumpGate。
            throw new System.NotImplementedException("示意代码：实际实现按 ScoreJumpGateModule 规则填写。");
        }
    }
}
```

没有参数的模块可以只有 `ModuleName`、核心方法和 `ResetModule()`。有参数的 gate、estimator、output module 都按上面方式写字段，不另外做参数包，也不创建对应 core 对象。

`AnchorPolicyHost` 负责组装：

```text
EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs
```

字段：

```csharp
[SerializeField] private AnchorGateModule gateModule;
[SerializeField] private AnchorEstimatorModule estimatorModule;
[SerializeField] private AnchorOutputStageModule outputModule;
[SerializeField] private string strategyLabel = "";
```

行为：

```text
Awake/Bind 时检查三类 module 引用。
AcceptPose 时调用 gateModule.Evaluate(...)，再按决策调用 estimatorModule.Snap(...) 或 estimatorModule.UpdateEstimate(...)。
Advance 时调用 estimatorModule.PredictAt(now)，再调用 outputModule.Condition(...) 得到 stable pose。
NotifyReset/NotifyReacquire/NotifyPause/NotifyResume/NotifyLost/NotifyError/Clear 由 Host 统一转发到三个 module 的 ResetModule 或状态入口。
记录 StrategyLabel、GateModuleName、EstimatorModuleName、OutputModuleName，供 Runtime 和 Recorder 写日志。
不自动 Find，不自动 AddComponent。缺模块时明确报错并进入 no_state。
```

一个 anchor 物体的推荐挂载方式：

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

切换方法是在同一个 GameObject 上挂对应模块组件，并在 `AnchorPolicyHost` 的三个抽象基类字段中拖拽引用；不用 enum，也不用 interface 字段。

### 3.3 DynamicObjectAnchor 输出契约

`DynamicObjectAnchor` 当前有 `PoseOutputMode Raw/Smoothed` enum。该 enum 属于旧 raw/stable 双路输出错误，应删除，不再用 `AnchorPoseSource`、`RawAnchorPoseSource`、`StableAnchorPoseSource` 继续包装它。

新契约：

```text
DynamicObjectAnchor
  -> PoseToAnchorRuntime.TryGetStablePose(...)
```

所有策略，包括 `raw_zoh`，都必须通过 `AnchorPolicyHost` 产生 stable/final pose。`raw_zoh` 的 stable pose 等于 frame-aligned 原始 Python pose 的 ZOH 输出；不再通过 `DynamicObjectAnchor` 选择 Raw/Smoothed。这样 scene 上每个对比 object 都有一个 `PoseToAnchorRuntime + AnchorPolicyHost + Gate/Estimator/Output module + DynamicObjectAnchor`，差异只来自 pipeline 模块组合。

## 4. Baseline 与模块组合

正式 label 和模块组合：

| label | Gate module | Estimator module | Output module | score 用法 | 作用 |
| --- | --- | --- | --- | --- | --- |
| `raw_zoh` | `NullGateModule` | `RawEstimatorModule` | `PassThroughOutputModule` | 忽略 | 低频 ZOH baseline |
| `lowpass_predict` | `NullGateModule` | `LowPassEstimatorModule` | `PassThroughOutputModule` | 忽略 | 简单平滑 + 速度前推 |
| `kalman_cv` | `NullGateModule` | `KalmanEstimatorModule` | `PassThroughOutputModule` | 忽略 | 常速度 Kalman 强 baseline |
| `oneeuro_vanilla` | `NullGateModule` | `OneEuroEstimatorModule` | `PassThroughOutputModule` | 忽略 | 常用交互低通 baseline |
| `egoanchor_no_static` | `ScoreJumpGateModule` | `EgoAnchorEstimatorModule` | `PassThroughOutputModule` | 使用 | gate/filter/prediction 消融 |
| `egoanchor_full` | `ScoreJumpGateModule` | `EgoAnchorEstimatorModule` | `StaticLockRateLimitOutputModule` | 使用 | RQ2 主方法 |

如果以后需要 score-aware Kalman，label 必须是 `kalman_score_adaptive`，不能覆盖 `kalman_cv`。用户当前要求是“baseline 不支持 score”，所以第一批 baseline 不用 score。

## 5. 离线数据如何使用

`offline_data` 分两层使用。

第一层：现有 eval 直接评估已录出的 `kalman/raw`：

```powershell
cd EgoAnchor_Python
pixi run python -m eval.run_eval --session-dir .\data\eval\offline_data --only tables
```

这只是 sanity，不证明新方法。报告可参考，但 replay 输入必须来自原始 JSONL，不用 `report/`。

第二层：新增 Unity offline replay 重跑所有策略。因为策略实现就在 `MonoBehaviour` module 子类中，replay 也要实例化同一套 module component，而不是另写 dotnet 版策略内核。

replay observation 构造规则：

```text
FrameId:
  unity_output.variants[].source_frame_id

WorldPose:
  首选 primary variant 的 aligned_raw_pos/aligned_raw_rot
  如果 primary 缺 aligned_raw，则用 label=="raw" 的 stable_pos/stable_rot

CaptureTimeSeconds:
  source_capture_mono_ms / 1000

SampleTimeSeconds:
  该 source_frame_id 第一次出现在 unity_output 中的 render_mono_ms / 1000

ReliabilityScore:
  首选 primary variant reliability_score
  缺失时按 frame_id join python_runtime pose_result.pose_score

ReliabilityFlags:
  按 frame_id join python_runtime pose_result.reliability_flags

Phase:
  latest_phase，缺失时按 frame_id join python_runtime pose_result.phase

PoseSource:
  按 frame_id join python_runtime pose_result.pose_source，缺失时用 TRACK
```

不要从 `pose_matrix_cv_camera` 直接重建 world pose。那会要求离线复刻 Unity 当时的 `CameraPoseFrameAligner`、`AnchorPoseTransform` 和 scene offset，日志未完整记录所有 Inspector 参数。`aligned_raw_*` 已经是 frame-aligned Unity world pose，是正确 replay 输入。

## 6. 实施任务

### Task 0: 基线验证和工作区保护

**Files:**

- Read: `AGENTS.md`
- Read: `docs/claude/2026-06-13-FINAL-anchor-architecture-plan.md`
- Read: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
- Read: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/DynamicObjectAnchor.cs`
- Read: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/AnchorEvalRecorder.cs`
- Read: `EgoAnchor_Python/eval/io/schemas.py`

- [ ] Step 0.1: 查看 dirty worktree，只记录，不回退。

Run:

```powershell
git status --short
```

Expected:

```text
显示现有用户改动；不执行 git reset、git checkout 或删除未跟踪数据。
```

- [ ] Step 0.2: 跑当前 Unity smoke。

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
Anchor policy smoke passed.
```

- [ ] Step 0.3: 跑 Unity build。

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

- [ ] Step 0.5: 验证 `offline_data` 可读，并确认 join 规模。

Run:

```powershell
cd EgoAnchor_Python
pixi run python -c "from pathlib import Path; from eval.io import load_session, join_by_frame; logs=load_session(Path('data/eval/offline_data')); joined=join_by_frame(logs); print(logs.capture.shape, logs.output.shape, logs.pose.shape, joined.shape); print(int(joined['pose_has_pose'].sum()))"
```

Expected:

```text
capture/output/pose 均非空；pose_has_pose 命中数量大于 0。
```

### Task 1: 新增共享 DTO 和数学辅助边界

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Core/AnchorModuleContracts.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Core/AnchorPolicyTypes.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] Step 1.1: 写 `AnchorEstimate`，字段为 `Pose`、`LinearVelocity`、`AngularVelocityRad`、`TimeSeconds`、`Confidence`、`ReliabilityScore`。不要命名为 `AnchorState`。
- [ ] Step 1.2: 写 `GateAction` 和 `GateDecision`，reason 必须是稳定字符串。
- [ ] Step 1.3: 写 `OutputContext`，包含 `LastAcceptedTimeSeconds`、`GapSeconds`、`LastScore`、`AnchorState State`。
- [ ] Step 1.4: 不创建 `AnchorGate`、`AnchorEstimator`、`AnchorOutputStage`、`AnchorStrategy`。这些职责全部落在 module component 抽象基类和具体子类上。
- [ ] Step 1.5: smoke csproj include 新文件。
- [ ] Step 1.6: 验证 pipeline 目录不读 Unity 时间。

Run:

```powershell
rg -n "Time\\." EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
rg 无输出；现有 smoke 仍通过。
```

### Task 2: 新增模块 component 基类

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Gate/AnchorGateModule.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Estimator/AnchorEstimatorModule.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Output/AnchorOutputStageModule.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] Step 2.1: 写三类抽象 `MonoBehaviour` 基类，字段和方法都加中文 summary。基类直接暴露运行时方法：`Evaluate`、`Snap/UpdateEstimate/PredictAt`、`Condition`、`ResetModule`，不暴露 `Create...()`。
- [ ] Step 2.2: 不定义 Inspector enum。不要在 module 基类里写 `public enum Mode`。
- [ ] Step 2.3: 参数字段必须写在具体 `MonoBehaviour` module 子类里，例如 `ScoreJumpGateModule.startScoreMin`、`KalmanEstimatorModule.processNoise`。不要新增独立 `Config`、`Options`、`Settings` 数据类。
- [ ] Step 2.3b（headless 可测试约定，硬性）: 所有算法状态必须由 `ResetModule()` 完整初始化；**禁止在 `Awake/Start` 做算法状态初始化**（`Awake` 只做引用检查/日志）。因为 headless 分析回放（Task 10）用 `RuntimeHelpers.GetUninitializedObject` 实例化 module，不会跑 `Awake`，调用方拿到实例后立即 `ResetModule()` 即得到与实时一致的干净状态。module 内任何"首帧懒初始化"必须以 `HasEstimate==false` 显式表达，不依赖构造/Awake 副作用。
- [ ] Step 2.4: smoke 加 reflection 断言：

```text
AssertAnchorModulesAreMonoBehaviours()
AssertAnchorModulesDoNotExposeModeEnums()
AssertAnchorModulesDoNotExposeCreateFactories()
AssertAnchorModulesImplementRuntimeMethodsDirectly()
AssertAnchorModulesKeepParametersOnMonoBehaviourFields()
AssertAnchorModulesInitializeStateInResetNotAwake()
```

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
新断言先失败，直到具体 module 和 host 补齐。
```

### Task 3: 数学工具

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Core/AnchorMath.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Estimator/ConstVelocityKalman.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Estimator/OneEuroEstimatorModule.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] Step 3.1: `AnchorMath` 提供 `Normalize`、`AlignHemisphere`、`Inverse`、`Log`、`Exp`、`AngleDegrees`、`Integrate`、`ClampPoseDelta`。
- [ ] Step 3.1b: 平移和旋转必须一起实现。旋转统一用四元数同半球对齐 + log/exp 切空间，不允许只实现平移或用 Euler 角滤波代替旋转滤波。
- [ ] Step 3.2: `OneEuroEstimatorModule` 内部私有实现 `OneEuroFloat`、`OneEuroVector3`、`OneEuroRotation`，不要再暴露独立 One Euro helper 文件。实现参考 Casiez/Roussel/Vogel 的 One Euro Filter 原始公式：`cutoff = min_cutoff + beta * |dx_hat|`，`alpha = 1 / (1 + tau / dt)`，`tau = 1 / (2π cutoff)`；旋转版本在四元数 log/exp 切空间中过滤，不用 Euler。
- [ ] Step 3.3: `ConstVelocityKalman` 是一维位置+速度常速度 Kalman。`Predict(dt)` 和 `Correct(measurement, r)` 分开；位置 estimator 用 3 个轴向 Kalman，旋转 estimator 用四元数误差状态和角速度估计适配同一 `PredictAt(renderTime)` 契约，不允许只更新位置。
- [ ] Step 3.4: 增加 smoke：

```text
AssertQuaternionLogExpRoundTrips()
AssertQuaternionHemisphereAlignmentUsesShortestArc()
AssertEstimatorRotationsPredictBetweenSamples()
```

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
数学 smoke 通过；pipeline 目录仍无 Time. 读取。
```

### Task 4: Gate modules

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Gate/NullGateModule.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Gate/ScoreJumpGateModule.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] Step 4.1: `NullGateModule.Evaluate(...)` 只做必要有效性检查，不使用 score。

Rules:

```text
HasAlignedPose=false 且 HasServerPose=false -> Hold / no_pose
HasAlignedPose=false 且 HasServerPose=true -> Hold / align_failed
hasEstimate=false 且 HasAlignedPose=true -> Snap / first_accept
observation.IsRelocalization 且 HasAlignedPose=true -> Snap / relocalize_accept
其它 HasAlignedPose=true -> Accept / score_accept
```

- [ ] Step 4.2: `ScoreJumpGateModule.Evaluate(...)` 使用 score、flags、绝对 jump。规则直接写在 module 子类中，不再委托给 `ScoreJumpGate` core 类。

Rules:

```text
invalid_pose/reject flag -> Reject / invalid_pose
无 aligned pose -> NullGate 同语义
重定位且 score >= relocalizeScoreMin -> Snap / relocalize_accept
无 state 且 score >= startScoreMin -> Snap / first_accept
无 state 且 score < startScoreMin -> Reject / score_hold
已有 state 且 score < holdScoreMin -> Reject / score_hold
已有 state 且 holdScoreMin <= score < trackScoreMin -> Hold / score_hold
位置残差 > maxJumpMeters -> Reject / jump_reject
旋转残差 > maxJumpDegrees -> Reject / jump_reject
其它 -> Accept / score_accept
```

- [ ] Step 4.3: module component 直接暴露 Inspector 参数，不包含处理逻辑，也不转交给独立 config/data 类。

`ScoreJumpGateModule` fields:

```text
startScoreMin = 0.35
trackScoreMin = 0.20
holdScoreMin = 0.12
relocalizeScoreMin = 0.12
maxJumpMeters = 0.80
maxJumpDegrees = 120
maxMeasurementAgeSeconds = 1.0
```

- [ ] Step 4.4: smoke：

```text
AssertNullGateIgnoresScore()
AssertScoreGateRejectsInvalidFlag()
AssertScoreGateHoldsLowScore()
AssertScoreGateRejectsAbsoluteJump()
AssertScoreGateModuleEvaluatesDirectly()
```

### Task 5: Estimator modules

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Estimator/RawEstimatorModule.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Estimator/LowPassEstimatorModule.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Estimator/KalmanEstimatorModule.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Estimator/OneEuroEstimatorModule.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Estimator/EgoAnchorEstimatorModule.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] Step 5.1: `RawEstimatorModule`：`PredictAt` 直接返回最近测量，label `raw_zoh`。
- [ ] Step 5.2: `LowPassEstimatorModule`：位置 EMA、旋转 Slerp、有限差分速度，`PredictAt` 可线性外推。
- [ ] Step 5.3: `KalmanEstimatorModule`：常速度 Kalman，第一批 `kalman_cv` 不用 score 改 R。位置用 3 个 `ConstVelocityKalman`；旋转用四元数误差状态 + 角速度，`PredictAt` 同时预测位置和旋转。若实现 score-aware 版本，另起 label。
- [ ] Step 5.4: `OneEuroEstimatorModule`：vanilla One Euro，`scoreWeight=1`。位置用 `OneEuroVector3`；旋转用 `OneEuroRotation`，四元数 log/exp，不用 Euler。
- [ ] Step 5.5: `EgoAnchorEstimatorModule`：score-adaptive One Euro + 有界前推。低 score 同时降低 update weight 和缩短 effective predict ahead；平移和旋转都要受同一 score-aware 策略约束。
- [ ] Step 5.6: estimator module component 各自直接暴露专属 Inspector 参数。不要共用一个巨型 config，也不要为每个 estimator 再建单独 data/config 类。
- [ ] Step 5.7: smoke：

```text
AssertAllEstimatorsSnapThenOutputPose()
AssertRawEstimatorIsZeroOrderHold()
AssertLowPassEstimatorMovesBetweenSamplesWhenPredictionEnabled()
AssertKalmanEstimatorPredictsConstantVelocityBetweenSamples()
AssertKalmanEstimatorPredictsRotationBetweenSamples()
AssertOneEuroEstimatorProducesContinuousRenderOutput()
AssertOneEuroEstimatorSmoothsRotationWithoutEulerArtifacts()
AssertEgoAnchorEstimatorModuleDampsPredictionWhenScoreDrops()
AssertBaselineEstimatorsIgnoreReliabilityScore()
AssertEstimatorModulesCreateExpectedEstimatorNames()
```

Continuous motion test rule:

```text
输入 0.2s 一帧，渲染 1/72s，匀速 0.35m/s。
Raw 的 maxZeroRun 应明显大于 4。
LowPass/Kalman/OneEuro/EgoAnchor 在 prediction enabled 时 maxZeroRun <= 4。
```

### Task 6: OutputStage modules

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Output/PassThroughOutputModule.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Output/StaticLockRateLimitOutputModule.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] Step 6.1: `PassThroughOutputModule.Condition(...)` 直接返回 `estimate.Pose`。
- [ ] Step 6.2: `StaticLockRateLimitOutputModule` 的静止锁、释放、限速参数直接写成该 `MonoBehaviour` 子类的 `[SerializeField]` 字段，不新增单独配置类。
- [ ] Step 6.3: `StaticLockRateLimitOutputModule.Condition(...)` 只整形显示输出，不回写 estimator 状态。
- [ ] Step 6.4: 静止锁进入条件：

```text
窗口时长 >= staticWindowSeconds
样本数 >= staticMinSamples
position spread <= staticRadiusMeters
rotation spread <= staticRotationDegrees
linear speed <= staticSpeedMetersPerSecond
angular speed <= staticAngularSpeedDegreesPerSecond
```

- [ ] Step 6.5: 静止锁释放条件：

```text
position residual > staticReleaseMeters
rotation residual > staticReleaseDegrees
```

- [ ] Step 6.6: smoke：

```text
AssertStaticOutputStageLocksSmallResidualSlip()
AssertStaticOutputStageReleasesOnRealMotion()
AssertRateLimitPreventsSingleFrameJump()
AssertPassThroughDoesNotModifyPose()
```

### Task 7: AnchorPolicyHost 编排模块

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] Step 7.1: `AnchorPolicyHost` 直接组合 `AnchorGateModule`、`AnchorEstimatorModule`、`AnchorOutputStageModule` 和 `AnchorStateMachine`。不创建 `AnchorPipeline` 或 `AnchorStrategy` core 类。
- [ ] Step 7.2: `AcceptMeasurement` 只提交测量，不输出 stable pose：先调用 `gateModule.Evaluate(...)`，再根据 gate action 调 `estimatorModule.Snap(...)` 或 `estimatorModule.UpdateEstimate(...)`。
- [ ] Step 7.3: `Advance(now)` 是唯一 stable pose 输出入口：调用 `estimatorModule.PredictAt(now)`，再调用 `outputModule.Condition(...)`。
- [ ] Step 7.4: `AnchorPolicyHost` 引用三个 module component，并实现 `Bind(PoseToAnchorRuntime owner)` 1:1 守卫。
- [ ] Step 7.5: host 暴露诊断：

```text
StrategyLabel
GateModuleName
EstimatorModuleName
OutputModuleName
State
LatestAction
LatestReason
MotionState
LastAcceptedScore
LastPredictAheadMs
SpeedMps
AngularSpeedDps
```

- [ ] Step 7.6: smoke：

```text
AssertPolicyHostMapsGateActionsToPolicyDecision()
AssertPolicyHostAdvancesEveryRenderFrame()
AssertPolicyHostCoastsThenFreezesThenLost()
AssertPolicyHostRequiresExplicitModules()
AssertPolicyHostDoesNotUseEnumSelection()
AssertPolicyHostMapsGateActionsToPolicyDecision()
AssertPolicyHostAdvancesEveryRenderFrame()
AssertPolicyHostCoastsThenFreezesThenLost()
AssertPolicyHostRequiresExplicitModules()
AssertPolicyHostDoesNotUseEnumSelection()
```

### Task 8: 接入 PoseToAnchorRuntime 和 DynamicObjectAnchor

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/DynamicObjectAnchor.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] Step 8.1: `PoseToAnchorRuntime` 只保留新的 `AnchorPolicyHost` 引用：

```csharp
/// <summary>Unity 侧 anchor policy 宿主。</summary>
[Tooltip("Unity 侧 anchor policy 宿主。所有 baseline 和 EgoAnchor 方法都通过该 host 的 Gate/Estimator/Output 模块表达。")]
[SerializeField] private AnchorPolicyHost policyHost;
```

- [ ] Step 8.2: 不再保留旧优先级链：

```text
policyHost != null -> AnchorPolicyHost module path
policyHost == null -> 不输出 stable pose，并记录 policy_host_required
```

- [ ] Step 8.3: `LateUpdate` 在 `policyHost` 存在时调用 `AdvanceAnchorOutput(now)`。
- [ ] Step 8.4: `NotifyReset/Reacquire/Pause/Resume/Lost/Error/Clear` 只通知 `policyHost`。
- [ ] Step 8.5: `PoseToAnchorRuntime` 直接暴露 strategy metadata：

```text
strategyLabel
gateModuleName
estimatorModuleName
outputModuleName
latestResidualMeters
latestResidualDegrees
latestAcceptedScore
latestStaticLocked
```

- [ ] Step 8.6: `DynamicObjectAnchor` 删除 `PoseOutputMode Raw/Smoothed`，也不新增 `AnchorPoseSource` 包装层。它只引用 `PoseToAnchorRuntime runtime` 并读取 `TryGetStablePose(...)`；`raw_zoh` 通过 policy module 输出 stable pose，因此不需要 Transform 应用层再选择 Raw。
- [ ] Step 8.7: smoke：

```text
AssertPolicyRuntimeUsesPolicyHostOnly()
AssertPoseToAnchorRuntimeUsesPolicyHostField()
AssertDynamicObjectAnchorReadsRuntimeStablePoseOnly()
AssertDynamicObjectAnchorHasNoRawSmoothedEnum()
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

### Task 9: AnchorEvalRecorder 记录模块元数据

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/AnchorEvalRecorder.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/AnchorEvalJson.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/EvalSessionManifestJson.cs`
- Modify: `EgoAnchor_Python/eval/io/schemas.py`
- Modify: `EgoAnchor_Python/eval/tests/test_log_loader.py`

- [ ] Step 9.1: `RecordedVariantSnapshot` 增加：

```text
strategy_label
gate_module
estimator_module
output_module
config_hash
```

`config_hash` 只对三个 module component 上的 `[SerializeField]` 字段做稳定摘要，用来追踪本次录制的 Inspector 参数；不要为此新增运行时 config/data 对象。

- [ ] Step 9.1b（参数可复现，配合 Task 10 回放）: manifest 的 `variant_configs[]` 除 `config_hash` 外，必须把每个 module 的 `[SerializeField]` 字段以 `name->value` 明文键值对一并写出（反射枚举字段，纯标量/向量）。Task 10 headless 回放据此**反射逐字段注入**到对应 module 实例，精确复现该次录制的参数。`config_hash` 仅作快速比对，注入靠明文键值；两者都来自同一次反射枚举，保证一致。

- [ ] Step 9.2: 未绑定 `AnchorPolicyHost` 的 runtime 不写旧兼容 label；模块字段为空并通过 smoke/build 暴露绑定问题。
- [ ] Step 9.3: Python schema 只做可选读取，不破坏旧日志。`VariantRow.raw` 继续保留原字段。
- [ ] Step 9.4: Manifest 增加 `variant_configs` 数组，记录每个 label 的模块组合和 Inspector 字段摘要。这里是日志 schema 名称，不是 Unity 运行时配置类。
- [ ] Step 9.5: eval 单测验证新旧日志都可读。

Run:

```powershell
cd EgoAnchor_Python
pixi run python -m unittest discover -s eval -p "test_*.py"
```

Expected:

```text
OK
```

### Task 10: 离线策略回放（headless dotnet 主力，给 AI 直接跑 offline_data 分析）

> **回放分两种，环境不同，本 Task 是“分析回放”：** AI 写完代码后**直接 `dotnet run` 跑 `offline_data` 做真实场景模拟**，秒级出指标、可频繁调参、不依赖 Unity Editor/license/图形栈。**视频回放**（Unity 内复现场景录 supplementary video）是另一回事，见 Task 12 `AnchorTrajectoryPlayer`。
>
> **可行性已核实：** 现有 `anchor_policy_smoke` 已用 `RuntimeHelpers.GetUninitializedObject(typeof(PoseToAnchorRuntime))` + 反射在纯 dotnet 中实例化并驱动 MonoBehaviour（见 `Program.cs` 的 `CreatePoseRuntimeForSmoke`）。module 是 MonoBehaviour 但算法 headless-safe（不读 `Time`、不碰 GameObject API），因此可在 dotnet 里同样实例化、反射注入参数、驱动 `AcceptMeasurement/Advance`。**不需要起 Unity 跑分析。**

**Files:**

- Create: `EgoAnchor_Tools/anchor_replay/AnchorReplay.csproj`
- Create: `EgoAnchor_Tools/anchor_replay/Program.cs`
- Modify: `EgoAnchor_Python/eval/tests/test_run_eval.py`

- [ ] Step 10.1: 新建 `anchor_replay` dotnet 工程，照搬 `anchor_policy_smoke` 的 `<Reference UnityEngine.dll>` + `<Compile Include>` 方式，include `Policy/Core|Gate|Estimator|Output` + 复用的 `AnchorObservation/AnchorPolicyDecision/AnchorPolicyOutput/AnchorStateMachine/CameraPoseFrameAligner` 等源。
- [ ] Step 10.2: replay runner 用 `GetUninitializedObject` 实例化所需 module component，反射逐字段注入该策略参数（见 Task 9 的参数注入约定），构建 `AnchorPolicyHost` 等价编排（或直接调用 host 的 headless 构造路径），按 `offline_data` 的 capture 时间喂 `AcceptMeasurement`、按 `render_mono_ms` 网格调 `Advance`。
- [ ] Step 10.2b（可选一致性抽查）: 另留 Unity batchmode 入口 `AnchorOfflineReplayCli.Run`，偶尔比对 dotnet 回放与 Unity 实例化行为是否一致（防 headless 反射路径漂移）。**这不是主力分析路径，CI/日常调参用 10.2 的 dotnet。**

```powershell
dotnet run --project EgoAnchor_Tools\anchor_replay\AnchorReplay.csproj -- --session EgoAnchor_Python\data\eval\offline_data --out EgoAnchor_Python\data\eval\offline_data\anchor_replay
```

- [ ] Step 10.3: 默认 strategies：

```text
raw_zoh
lowpass_predict
kalman_cv
oneeuro_vanilla
egoanchor_no_static
egoanchor_full
```

- [ ] Step 10.4: 输出：

```text
anchor_replay_output.jsonl
anchor_replay_summary.csv
anchor_replay_config.json
```

- [ ] Step 10.5: `anchor_replay_summary.csv` 至少包含：

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

- [ ] Step 10.6: replay output 采用现有 `unity_output` 兼容结构，让 Python eval 可直接读。
- [ ] Step 10.7: 实现完成后必须先用 `offline_data` 跑一次真实 replay，再接 Python eval，避免只通过 toy smoke 但真实日志字段或时序有 bug。

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_replay\AnchorReplay.csproj -- --session EgoAnchor_Python\data\eval\offline_data --out EgoAnchor_Python\data\eval\offline_data\anchor_replay
```

Expected:

```text
秒级跑完，不启动 Unity Editor。
summary 至少有六个策略 label。
raw_zoh 的 max_zero_run 明显高于带预测 estimator。
baseline strategies 不读取 score。
egoanchor_full 在低分 outlier 上 reject/hold 数大于 vanilla baseline。
```

### Task 11: replay 输出接回 Python eval

**Files:**

- Modify: `EgoAnchor_Python/eval/io/log_loader.py`
- Modify: `EgoAnchor_Python/eval/run_eval.py`
- Modify: `EgoAnchor_Python/eval/tests/test_run_eval.py`

- [ ] Step 11.1: `run_eval.py` 增加 `--output-log` 可选参数。默认仍读 session 里的 `*_unity_output.jsonl`。
- [ ] Step 11.2: 用 replay output 生成 report：

```powershell
cd EgoAnchor_Python
pixi run python -m eval.run_eval --session-dir .\data\eval\offline_data --output-log .\data\eval\offline_data\anchor_replay\anchor_replay_output.jsonl --report-dir .\data\eval\offline_data\anchor_replay\report --only tables
```

Expected:

```text
anchor_error_summary.csv
jitter_summary.csv
lag_summary.csv
latency_summary.csv
policy_distribution.csv
```

- [ ] Step 11.3: 单测构造 replay output，验证 `strategy_label/gate_module/estimator_module/output_module` 展开到 DataFrame。

### Task 12: Unity 回放，两种用途分开

> **回放环境分工（已与用户确认）：** **分析回放**走 headless dotnet（Task 10），给 AI 直接跑 `offline_data` 出指标。**视频回放**走 Unity（本 Task），因为投稿 supplementary video 需要渲染画面——Unity 内记录位置/旋转，跑回放场景复现当时录制的场景并录屏。两者各取所长，不混。

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/RecordedAnchorReplaySource.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/RecordedAnchorReplayController.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/AnchorTrajectoryPlayer.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`

- [ ] Step 12.1: `RecordedAnchorReplaySource` 用 `aligned_raw` 在 Unity 内重跑 runtime/strategy（定性验证用，可看实时渲染；定量指标以 Task 10 dotnet 为准）。

Behavior:

```text
读取 unity_output.jsonl。
取 primary variant 的 aligned_raw_pos/rot、source_frame_id、source_capture_mono_ms、reliability_score。
按录制时间向指定 PoseToAnchorRuntime 注入 AnchorObservation。
不连接 NATS，不启动 Python。
用于 Unity 内验证 pipeline，与离线表格趋势一致。
```

- [ ] Step 12.2: `AnchorTrajectoryPlayer` 只播放已录出的 stable 轨迹 —— **这是投稿视频的主路径**。

Behavior:

```text
读取指定 variant label 的 stable_pos/stable_rot（可同时播多个 label 做并排对比）。
按 render_mono_ms 驱动 Transform，可附 GT Transform 一同复现。
用于复现当时录制的场景、录 supplementary video，不参与算法评估。
```

- [ ] Step 12.3: `PoseToAnchorRuntime` 新增 replay-only 入口：

```text
AcceptAlignedWorldPoseForReplay(frameId, worldPose, captureTimeSeconds, reliabilityScore, reliabilityFlags, phase, poseSource, sampleTimeSeconds)
```

该入口不解码 Protobuf，不做 camera-space 到 world-space 转换。

### Task 13: Recovery 正交层

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] Step 13.1: 新增 component，字段用 bool/float 和 component 引用，不用 enum。

Fields:

```text
runtime
commandClient
enableAutoReacquire
enableLowScoreReacquire
enableLostReacquire
enableNoPoseReacquire
lowScoreThreshold = 0.25
lowScoreSeconds = 0.8
lostSeconds = 0.3
noPoseSeconds = 1.0
cooldownSeconds = 3.0
clearTrackingFirst = true
```

- [ ] Step 13.2: 触发 reason 固定：

```text
auto_reacquire_low_score
auto_reacquire_lost
auto_reacquire_no_pose
input_not_ready_wait
```

- [ ] Step 13.3: in-flight、cooldown、`LatestHeartbeatInputReady` 三层 guard。
- [ ] Step 13.4: smoke：

```text
AssertRecoveryControllerDoesNothingWhenDisabled()
AssertRecoveryControllerTriggersOnLostWhenEnabled()
AssertRecoveryControllerTriggersOnLowScoreOnlyWhenEnabled()
AssertRecoveryControllerHonorsCooldownAndInFlight()
AssertRecoveryControllerWaitsWhenInputNotReady()
```

### Task 14: RQ1 arrival-time mapping 诊断

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/CameraPoseFrameAligner.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/AnchorEvalRecorder.cs`
- Modify: `EgoAnchor_Python/eval/metrics/slip.py`
- Modify: `EgoAnchor_Python/eval/tests/test_run_eval.py`

- [ ] Step 14.1: 默认 anchor 仍使用 capture-time frame alignment。
- [ ] Step 14.2: 增加诊断输出 `arrival_time_raw`，使用 pose 到达/渲染时刻的 camera pose 做对照。
- [ ] Step 14.3: RQ1 只比较：

```text
frame_aligned_raw
arrival_time_raw
```

不混入 filter、score gate、recovery。

### Task 15: Unity scene 迁移和 Inspector 对比

**Files:**

- Scene files under `EgoAnchor_Unity/Assets/Scene/`，执行前必须读 `git status --short`。

- [ ] Step 15.1: 不在代码阶段自动改 scene。等 Task 8-11 通过后再单独迁移。
- [ ] Step 15.2: 搭五个 runtime object：

```text
raw_zoh
lowpass_predict
kalman_cv
oneeuro_vanilla
egoanchor_full
```

每个 object 有：

```text
PoseToAnchorRuntime
AnchorPolicyHost
对应 GateModule
对应 EstimatorModule
对应 OutputStageModule
DynamicObjectAnchor
```

- [ ] Step 15.3: `AnchorRuntimeHub.runtimes` 绑定全部 runtime。
- [ ] Step 15.4: `AnchorEvalRecorder.recordedRuntimes` 绑定全部 runtime 和对应 Transform，label 与策略一致。
- [ ] Step 15.5: 手动真机 smoke：

```text
所有 runtime LatestAlignedFrameId 同步增长。
raw_zoh 有明显 ZOH 阶梯。
kalman_cv/oneeuro_vanilla/egoanchor_full 在两测量间有连续输出。
recorder 写出的 variants 包含全部 label。
DynamicObjectAnchor 不包含 Raw/Smoothed 输出模式选择。
```

### Task 16: 文档同步和旧路径审计

**Files:**

- Modify: `ANCHOR_CONTROLLER_GUIDE.md`
- Modify: `AGENTS.md`
- Modify: `2026-EgoAnchor/egoanchor_cn_outline.tex`
- Modify: `2026-EgoAnchor/egoanchor_cn_v1.tex`
- Delete: old policy helper files and processor directory if any stale copy reappears.

- [ ] Step 16.1: 更新 guide，说明 component 挂载方式、五个 baseline、offline replay、Unity replay。
- [ ] Step 16.2: 更新 `AGENTS.md` 用户维护区块之外的事实。不得改 `USER-MAINTAINED-REQUIREMENTS`。
- [ ] Step 16.3: 论文只写已验证事实。`egoanchor_full` 没打赢 `kalman_cv/oneeuro_vanilla` 前，不把 score-aware policy 写成贡献。
- [ ] Step 16.4: 搜索确认旧代码没有回流：

```powershell
rg "legacy processor|old policy controller|Pipeline\\Modules" EgoAnchor_Unity\Assets\Scripts\EgoAnchor EgoAnchor_Tools\anchor_policy_smoke ANCHOR_CONTROLLER_GUIDE.md AGENTS.md
```

预期：

```text
代码、smoke、guide 和 AGENTS 都不再引用旧 host、旧 controller 或旧 processor 类。
```

## 7. 完整验证门

必须通过：

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Python：

```powershell
cd EgoAnchor_Python
pixi run python -m unittest discover -s eval -p "test_*.py"
pixi run python -m eval.run_eval --session-dir .\data\eval\offline_data --only tables
```

离线策略分析回放（headless dotnet，主力）：

```powershell
dotnet run --project EgoAnchor_Tools\anchor_replay\AnchorReplay.csproj -- --session EgoAnchor_Python\data\eval\offline_data --out EgoAnchor_Python\data\eval\offline_data\anchor_replay
```

视频回放（Unity，投稿用，非 CI 门）：在 Unity 内用 `AnchorTrajectoryPlayer` 复现已录轨迹录屏；可选 `AnchorOfflineReplayCli` batchmode 抽查与 dotnet 回放行为一致。

Replay 接 Python eval：

```powershell
cd EgoAnchor_Python
pixi run python -m eval.run_eval --session-dir .\data\eval\offline_data --output-log .\data\eval\offline_data\anchor_replay\anchor_replay_output.jsonl --report-dir .\data\eval\offline_data\anchor_replay\report --only tables
```

代码搜索：

```powershell
rg -n "Time\\." EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy
rg -n "enum .*Mode|AnchorGateMode|AnchorEstimatorMode|AnchorOutputStageMode" EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Runtime
```

Expected:

```text
第一条无输出。
第二条不应出现新的 Inspector module selection enum，也不应保留 DynamicObjectAnchor 的 Raw/Smoothed 输出 enum。
```

## 8. 论文实验映射

RQ1：frame-aligned 是否必要。

```text
frame_aligned_raw vs arrival_time_raw
不使用 filter、score gate、recovery
指标：world-space anchor error、head-motion-induced slip、static jitter、capture_to_apply latency
```

RQ2：同步策略的 jitter-lag 权衡。

```text
raw_zoh
lowpass_predict
kalman_cv
oneeuro_vanilla
egoanchor_no_static
egoanchor_full

固定同一份 aligned_raw 输入、同一 render_mono_ms 网格、recovery off。
指标：static jitter、moving RMSE、lag、maxZeroRun、jump reject/hold 分布。
```

RQ3：Recovery 是否改善可恢复 anchor 行为。

```text
egoanchor_full + recovery disabled
egoanchor_full + no_pose/lost timeout reacquire
egoanchor_full + score-aware reacquire

指标：recovery success/time、false reacquire count、command count、recovery 后 anchor error。
```

## 9. 验收标准

工程验收：

- Unity Inspector 不通过 enum 选择 gate/estimator/output；通过挂载并拖拽 module component 指定。
- 所有 estimator 都实现 `PredictAt(renderTime)`。
- baseline 不使用 score；EgoAnchor 的 score 特化只在 `ScoreJumpGateModule` 和 `EgoAnchorEstimatorModule`。
- `PoseToAnchorRuntime` 默认仍使用 frame_id capture-time 对齐。
- `DynamicObjectAnchor` 不包含滤波、状态机、网络、recovery 逻辑，也不包含 Raw/Smoothed 输出模式选择；它只应用 `PoseToAnchorRuntime` 的 final/stable pose。
- `AnchorEvalRecorder` 能记录多 strategy variant 和模块元数据。
- Unity offline replay 能用 `offline_data` 同一份 aligned raw 输入重跑所有策略。
- Python eval 能读取 replay output 并生成同一套表。

论文验收：

- RQ1 和 RQ2 分开，不把 frame alignment 与 filter policy 混成一个变量。
- RQ2 的所有策略共享同一输入和渲染时钟。
- Recovery 只在 RQ3 出现。
- 若 `egoanchor_full` 未赢过 `kalman_cv` 或 `oneeuro_vanilla`，论文不把 policy 写成主要贡献。

## 10. 风险与处理

| 风险 | 处理 |
| --- | --- |
| Unity 不能序列化 interface 字段 | Inspector 字段使用抽象 `MonoBehaviour` module 基类；模块子类直接实现行为，不使用 `IAnchor*` interface，也不新增 `AnchorGate/AnchorEstimator/AnchorOutputStage` core 类型。 |
| scene 仍绑定旧脚本 GUID | 不保留代码兼容层；scene 迁移单独执行，把每个 variant 明确绑定 `PoseToAnchorRuntime + AnchorPolicyHost + modules + DynamicObjectAnchor`。 |
| baseline 偷用 score 影响论文公平性 | 第一批 `kalman_cv/oneeuro_vanilla/lowpass_predict/raw_zoh` 明确忽略 score；score-aware Kalman 单独 label。 |
| replay 与 Unity 实时行为漂移 | offline replay 在 Unity 内实例化同一套 module component，不维护第二套策略实现。 |
| `offline_data` 没有 condition spans | 第一批分析 condition 为 `unlabeled`，只做 baseline 行为和参数筛选；正式论文数据需要重新录 condition spans。 |
| 旧 scene 引用 enum/outputMode | 不再保留兼容层；代码删除 Raw/Smoothed 输出 enum。scene 迁移单独执行，所有 baseline 通过独立 runtime + pipeline label 表达。 |
| EgoAnchor 打不过 Kalman | 这不是失败；论文主贡献回到 frame-aligned pose-to-anchor，policy 降级为实现细节。 |

## 11. 执行顺序

第一批先完成公平 baseline 和真实数据离线验证：

```text
Task 0 -> Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5 -> Task 6 -> Task 7 -> Task 10 -> Task 11
```

第二批接 Unity 实时和录制：

```text
Task 8 -> Task 9 -> Task 12 -> Task 15
```

第三批接 recovery、RQ1 和清理：

```text
Task 13 -> Task 14 -> Task 16
```

每批结束建议提交：

```text
feat(anchor): add component-driven anchor pipeline core
feat(anchor): add estimator baselines and output stages
feat(eval): add offline anchor replay on recorded data
feat(anchor): integrate pipeline host with runtime
feat(eval): record module metadata and replay trajectories
feat(anchor): add recovery controller
docs(anchor): document final modular anchor workflow
```
