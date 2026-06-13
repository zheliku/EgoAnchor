# Anchor Policy One Euro Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Unity anchor policy 重构为“静止锁定 + One Euro 自适应滤波 + 有界前推 + 自动重获取”的小控制器，把 Python 约 5Hz 的相机系 pose/score 流扩展成稳定、连续、可恢复的 Unity world anchor pose。

**Architecture:** Python、Protobuf、NATS/ZMQ、frame alignment 和 raw/processor baseline 不改。`PoseToAnchorRuntime` 仍负责把 Python camera-space pose 转为 capture-time frame-aligned world pose；`PolicyController.AcceptPose` 只提交测量，`PolicyController.Advance` 每渲染帧输出稳定 pose。内部删掉马氏门控、Kalman 协方差、teleport/soft recovery，保留 `AnchorStateMachine` 处理 lifecycle，保留简化后的 `MotionStateClassifier` 只负责静止锁定判定；自动 reacquire 放在独立 `AnchorRecoveryController`。

**Tech Stack:** Unity C#、Google.Protobuf、NATS command API、`EgoAnchor_Tools/anchor_policy_smoke`、`dotnet build`、`EgoAnchor_Python/eval` JSONL 只读回放。

---

## 1. 对比结论

Claude 计划里最值得保留的部分：

- One Euro filter。它比当前 6DoF Kalman 更适合这里的输入形态：低频、延迟、有小噪声，且用户感知目标是“静止稳、运动跟手”。
- 先用 `20260613_012345_controller_right` 做离线回放调默认参数，再落 C#。这比凭手感调 Inspector 更可靠。
- 参数大幅收敛。当前 policy 参数太多，很多分支在最新数据中基本没有触发。
- 持续低分触发重获取，并加 cooldown 和 in-flight guard。

Claude 计划里需要丢掉或改写的部分：

- 不删除 `AnchorStateMachine`。现有状态机已经承接 reset/reacquire/pause/resume/server lost/error/coast/lost 语义，删掉会让 runtime 和 server status 的边界变差。
- 不把 `AnchorCommandClient` 直接塞进 `PoseToAnchorRuntime`。重获取是 command bridge，不是 pose-to-anchor runtime 的核心职责，应放在独立 MonoBehaviour。
- 不彻底删除静止分类。One Euro 能降低低速噪声，但不能保证“头显轻微晃动、物体静止时显示绝对不跟着 residual slip 走”。静止锁仍需要一个基于测量窗口散布的判定。
- 不新建 `AnchorTracker.cs` 替换所有既有类型名。为了减少 Unity scene、smoke csproj 和诊断层连锁改动，保留 `AnchorPoseFilter.cs` 文件名，把内部改成 One Euro 核。
- 不关闭 Lost/no-pose 自动重获取。用户需求明确包含断线/丢失后的重新 register；计划里应默认支持，但要有 cooldown，避免刷命令。

本计划合并后的设计是：

```
PoseResult -> frame alignment -> AnchorObservation
                               -> PolicyController.AcceptPose()
                                  score/flag/stale/jump 简单判定
                                  MotionStateClassifier 只判静止锁
                                  AnchorPoseFilter(One Euro) 更新提交态

LateUpdate -> PolicyController.Advance(now)
           -> AnchorPoseFilter.PredictAt(now)
           -> AnchorPoseFilter.AdvanceOutput(...)
           -> stable world pose

AnchorRecoveryController
           -> 观察 PoseToAnchorRuntime 的 state/action/reason/score
           -> 持续低分、no-pose、Lost 后调用 AnchorCommandClient.ReacquireAsync
```

## 2. 不变边界

- 不改 Python 输出语义：`PoseResult.pose_matrix_cv_camera` 仍是左目 OpenCV camera-space object pose。
- 不改协议字段、不重新生成 proto。
- 不改 `CameraPoseFrameAligner` 和 `FramePoseHistory` 的 capture-time frame alignment。
- 不用 pose 到达时 HMD pose 代替采集帧 pose。
- raw / low-pass / Kalman processor baseline 保留，policy runtime 继续不经过 processor 链。
- `PolicyController` 公开入口保留：`AcceptPose`、`Advance`、`NotifyReset`、`NotifyReacquire`、`NotifyPause`、`NotifyResume`、`NotifyError`、`NotifyLost`、`Clear`。
- `AnchorPolicyDecision`、`AnchorPolicyOutput`、`AnchorState`、`AnchorMotionState` 类型保留，避免 eval 和 smoke 大面积断裂。

## 3. 文件结构

### Create

- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/OneEuroFilter.cs`
  - 纯 C# One Euro 数学辅助。包含标量、`Vector3` 和四元数旋转更新需要的函数。不要读取 `Time`，不要依赖 MonoBehaviour。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs`
  - 独立自动重获取组件。观察 `PoseToAnchorRuntime`，通过 `AnchorCommandClient.ReacquireAsync(...)` 请求 Python 重新 register。
- `EgoAnchor_Python/eval/tools/replay_one_euro_policy.py`
  - 只读离线回放脚本。读取现有 session JSONL，用 Python 复刻 One Euro 公式，帮助确认默认参数。

### Modify

- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyConfig.cs`
  - 精简为评分门控、One Euro、静止锁、前推输出、断流退化参数。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPoseFilter.cs`
  - 保留文件名和 `AnchorPredictMode`，内部从 Kalman 改为 One Euro 提交态 + 输出态。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/MotionStateClassifier.cs`
  - 保留 `AnchorMotionState` enum，移除 `InnovationStats` 依赖，改为测量窗口散布 + 预测残差快出。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs`
  - 删掉 `AnchorMeasurementGate`、`AnchorOutputSmoother` 依赖，改为简单 gate + One Euro filter + 状态机。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`
  - 更新 Tooltip 和诊断属性，暴露 residual、score、predict ahead。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
  - 只同步新诊断字段；不接 command client。
- `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`
  - 替换 policy 内核测试，保留 frame alignment、NATS、runtime hub、processor skip 等集成测试。
- `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`
  - 加入 `OneEuroFilter.cs` 和 `AnchorRecoveryController.cs`，删除旧 gate/smoother include。
- `ANCHOR_CONTROLLER_GUIDE.md`
  - 更新使用说明和参数表。
- `AGENTS.md`
  - 只更新用户维护区块之外的当前主线事实。

### Delete

- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs`
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs.meta`
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs`
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs.meta`

不删除：

- `AnchorStateMachine.cs`
- `MotionStateClassifier.cs`
- `AnchorPoseFilter.cs`

## 4. One Euro 设计细节

### 4.1 标量公式

每个标量通道维护：

```csharp
private float rawPrevious;
private float valueHat;
private float derivativeHat;
private double timeSeconds;
private bool hasState;
```

更新公式：

```csharp
float dt = Mathf.Max((float)(timeSeconds - this.timeSeconds), 1e-4f);
float derivative = (raw - rawPrevious) / dt;
derivativeHat = Mathf.Lerp(derivativeHat, derivative, Alpha(derivativeCutoff, dt));

float scoreWeight = Mathf.Clamp(score, minScoreWeight, 1f);
float cutoff = minCutoff + beta * Mathf.Abs(derivativeHat);
float alpha = Alpha(cutoff, dt) * scoreWeight;
valueHat = Mathf.Lerp(valueHat, raw, Mathf.Clamp01(alpha));
rawPrevious = raw;
this.timeSeconds = timeSeconds;
```

`Alpha`：

```csharp
private static float Alpha(float cutoff, float dt)
{
    float safeCutoff = Mathf.Max(cutoff, 1e-4f);
    float tau = 1f / (2f * Mathf.PI * safeCutoff);
    return 1f / (1f + tau / Mathf.Max(dt, 1e-4f));
}
```

### 4.2 位置

位置用 3 个标量 One Euro。线速度直接来自每轴 `derivativeHat`，用于前推。

### 4.3 旋转

旋转不按欧拉角滤波。维护 `rotationHat`、`rawRotationPrevious`、`angularVelocityHatRad`：

1. 把新测量四元数归一化，并与上一 raw 或当前 filtered 四元数对齐到同一半球。
2. 用 `Log(Inverse(rawPrevious) * raw)` / `dt` 得到 raw angular velocity。
3. 对 angular velocity 向量做低通，得到 `angularVelocityHatRad`。
4. 用 `cutoff = rotationMinCutoff + rotationBeta * angularVelocityHatRad.magnitude` 计算 alpha。
5. 用 `Log(Inverse(rotationHat) * raw)` 得到 filtered 到 raw 的最短弧残差。
6. `rotationHat = rotationHat * Exp(residual * alpha * scoreWeight)`。

这比“对 Quaternion.Angle 标量做 One Euro 再 Slerp”更完整，因为它保留了旋转轴，可以自然支持 6DoF 姿态。

### 4.4 静止锁和输出态

One Euro 负责滤波提交态，静止锁负责显示态。

- `MotionStateClassifier` 判定 Static 后，`AnchorPoseFilter` 的预测前推关闭，线速度/角速度清零。
- 输出 pose 锁在进入静止时的 pose。
- 如果目标 pose 与锁定 pose 的偏差低于 `staticReleaseMeters/staticReleaseDegrees`，输出不跟随小 residual slip，只用很慢的 `staticCenterTauSeconds` 向滤波均值归中。
- 如果超过释放阈值，认为物体真的动了，退出锁定，输出按运动模式追踪 One Euro 目标。

## 5. 新参数表

`AnchorPolicyConfig` 保留以下字段。所有字段继续有中文 XML summary 和 `[Tooltip]`。

| 分组 | 参数 | 默认 | 说明 |
| --- | --- | ---: | --- |
| 评分门控 | `startScoreMin` | 0.35 | 冷启动第一帧接受下限 |
| 评分门控 | `trackScoreMin` | 0.20 | 已有 anchor 后普通 TRACK 接受下限 |
| 评分门控 | `holdScoreMin` | 0.12 | 低于该值只 hold/reject，不更新滤波器 |
| 评分门控 | `relocalizeScoreMin` | 0.12 | REGISTER/RE_REGISTER snap 接受下限 |
| One Euro | `positionMinCutoff` | 1.0 | 静止位置平滑强度，越小越稳 |
| One Euro | `positionBeta` | 0.65 | 位置速度响应，越大越跟手 |
| One Euro | `rotationMinCutoff` | 1.0 | 静止旋转平滑强度 |
| One Euro | `rotationBeta` | 0.55 | 旋转速度响应 |
| One Euro | `derivativeCutoff` | 1.0 | 速度估计低通 cutoff |
| One Euro | `minScoreWeight` | 0.25 | 已接受测量参与滤波时的最低权重 |
| 静止锁 | `staticWindowSeconds` | 0.60 | 判静止的测量窗口时长 |
| 静止锁 | `staticMinSamples` | 3 | 判静止最少 accepted pose 数 |
| 静止锁 | `staticRadiusMeters` | 0.012 | 窗口位置散布上限 |
| 静止锁 | `staticRotationDegrees` | 2.5 | 窗口旋转散布上限 |
| 静止锁 | `staticReleaseMeters` | 0.020 | 静止锁释放位置阈值 |
| 静止锁 | `staticReleaseDegrees` | 3.0 | 静止锁释放旋转阈值 |
| 静止锁 | `staticCenterTauSeconds` | 0.35 | 静止锁慢速归中时间常数 |
| 输出 | `maxPredictAheadSeconds` | 0.14 | 位置前推上限 |
| 输出 | `maxRotationPredictAheadSeconds` | 0.08 | 旋转前推上限 |
| 输出 | `movingOutputTauSeconds` | 0.035 | 运动输出追踪时间常数 |
| 输出 | `maxOutputSpeedMps` | 3.0 | 输出最大线速度 |
| 输出 | `maxOutputAngularSpeedDps` | 720 | 输出最大角速度 |
| 跳变 | `maxJumpMeters` | 0.80 | 绝对位置外点门 |
| 跳变 | `maxJumpDegrees` | 120 | 绝对旋转外点门 |
| 断流 | `coastGraceSeconds` | 0.30 | 正常消息间隔保护 |
| 断流 | `maxCoastSeconds` | 0.45 | 短时断流外推上限 |
| 断流 | `lostTimeoutSeconds` | 2.0 | 进入 Lost 的无可靠 pose 时长 |
| 断流 | `maxMeasurementAgeSeconds` | 1.0 | 测量最大年龄 |

`Validate()` 只做 clamp 和简单关系约束，不再保留旧参数迁移。

## 6. Task 1: Add Offline One Euro Replay

**Files:**
- Create: `EgoAnchor_Python/eval/tools/replay_one_euro_policy.py`

- [ ] **Step 1: 创建 eval tools 目录**

如果 `EgoAnchor_Python/eval/tools` 不存在，创建该目录。该目录是 eval 工具脚本，不导入 Unity 或 `egoanchor.runtime`。

- [ ] **Step 2: 写入 Python One Euro 参考实现**

脚本包含以下结构：

```python
"""离线回放 Unity aligned raw pose，评估 One Euro anchor policy 默认参数。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from eval.io import load_session


@dataclass
class OneEuroParams:
    """One Euro 与前推参数，默认值应与 Unity AnchorPolicyConfig 保持一致。"""

    position_min_cutoff: float = 1.0
    position_beta: float = 0.65
    rotation_min_cutoff: float = 1.0
    rotation_beta: float = 0.55
    derivative_cutoff: float = 1.0
    min_score_weight: float = 0.25
    max_predict_ahead_seconds: float = 0.14
    max_rotation_predict_ahead_seconds: float = 0.08
```

实现 `alpha(cutoff, dt)`、`quat_normalize`、`quat_mul`、`quat_inv`、`quat_log`、`quat_exp`、`quat_align_sign`。这些函数只用 numpy，不引入 scipy。

- [ ] **Step 3: 从 session 提取测量流和渲染流**

从 `logs.output` 读取：

- 测量流：按 `source_frame_id` 去重，取第一行 `has_aligned_raw=true` 的 `aligned_raw_pos`、`aligned_raw_rot`、`reliability_score`、`source_capture_mono_ms`。
- 渲染流：保留 `render_mono_ms`、GT pose、旧 variant stable pose，用来对比 raw/current policy/One Euro。
- 时间统一转秒，第一帧时间归零。

- [ ] **Step 4: 输出指标**

脚本打印：

```text
one_euro_replay_summary
rows_rendered=...
measurements=...
raw_rmse_mm=...
old_policy_rmse_mm=...
one_euro_rmse_mm=...
raw_jitter_mm=...
old_policy_jitter_mm=...
one_euro_jitter_mm=...
one_euro_max_zero_run=...
```

通过标准暂定：

- 静止段未标注时，先用全局 jitter 和 no-GT continuity 作为 smoke。
- `one_euro_max_zero_run <= 4`。
- 有 GT 行时，`one_euro_rmse_mm <= raw_rmse_mm * 1.05`。第一次回放不强行要求优于 raw，因为当前 session 没明确 condition，目标是避免明显退化。

- [ ] **Step 5: 运行回放**

Run:

```powershell
pixi run python .\eval\tools\replay_one_euro_policy.py --session .\data\eval\20260613_012345_controller_right
```

Expected: 脚本能跑完并打印 summary。根据结果微调默认 `positionBeta`、`rotationBeta`、`maxPredictAheadSeconds`，再进入 Unity 实现。

## 7. Task 2: Replace Policy Smoke With Target Behavior Gates

**Files:**
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] **Step 1: 保留集成 smoke，替换 policy 内核断言列表**

保留 frame alignment、NATS、runtime hub、status event、processor skip 相关测试。将开头 policy 场景收敛为：

```csharp
AssertFirstPoseSnaps();
AssertOneEuroStaticJitterSuppression();
AssertStaticLockSuppressesHeadMotionSlip();
AssertStaticClassifierUsesWindowDispersion();
AssertStaticReleasesOnRealMotion();
AssertLowRateMotionIsContinuous();
AssertLowRateRotationIsContinuous();
AssertLowScoreHoldsWithoutDragging();
AssertAbsoluteJumpRejected();
AssertNoPoseCoastsThenFreezesThenLost();
AssertRelocalizeSnap();
AssertStaleMeasurementIgnored();
AssertConfigHotReload();
AssertNotifyChain();
AssertAnchorRecoveryControllerExists();
```

删除旧的马氏、teleport、soft recovery 专属断言调用。

- [ ] **Step 2: 添加静止防抖断言**

新增 `AssertOneEuroStaticJitterSuppression()`：用 5Hz 左右噪声输入喂 80 帧，warmup 后要求输出位置 RMS 小于输入 RMS 的 0.4 倍，旋转 RMS 小于输入 RMS 的 0.4 倍。

- [ ] **Step 3: 添加低频运动连续断言**

新增 `AssertLowRateMotionIsContinuous()`：输入 0.20s 一帧、0.35m/s 匀速平移，渲染帧间隔用 `FrameDt`。要求：

```csharp
Assert(movingSteps > 80, "low-rate motion should produce render-frame movement");
Assert(maxZeroRun <= 4, $"low-rate motion should not have long still runs, got {maxZeroRun}");
```

- [ ] **Step 4: 添加低频旋转连续断言**

新增 `AssertLowRateRotationIsContinuous()`：输入 0.20s 一帧、45deg/s yaw，要求渲染帧之间有连续旋转，`maxZeroRun <= 4`。

- [ ] **Step 5: 添加低分 hold 和绝对跳变断言**

低分 pose 不应拖动输出；高分但超过 `maxJumpMeters/maxJumpDegrees` 的单帧外点应 `Reject/jump_reject`，输出保持上一 pose。

- [ ] **Step 6: 先运行 smoke，确认旧实现不满足新目标**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected: FAIL。失败原因应来自新 policy 目标或待新增类型，不应来自 frame alignment/NATS 集成测试。

## 8. Task 3: Simplify AnchorPolicyConfig

**Files:**
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyConfig.cs`

- [ ] **Step 1: 替换字段**

按第 5 节参数表重写字段。删除以下旧字段族：

- `innovationPosChi2Gate`
- `innovationRotChi2Gate`
- `trustedMotionTranslationMeters`
- `trustedMotionRotationDegrees`
- `softRecovery*`
- `stuckRecovery*`
- `positionMeasurementNoise`
- `processNoise*`
- `rotationMeasurementNoise`
- `rotationProcessNoise*`
- `angularVelocityGainBeta`
- `angularVelocityDampingTau`
- `motionSpikeD2`
- `staticOutput*` 旧命名

- [ ] **Step 2: 保留中文说明**

每个字段保留 XML summary 和 `[Tooltip]`。Tooltip 说明单位和调参方向。

- [ ] **Step 3: 实现 Validate**

`Validate()` 做以下约束：

```csharp
startScoreMin = Mathf.Clamp01(startScoreMin);
trackScoreMin = Mathf.Clamp(trackScoreMin, 0f, startScoreMin);
holdScoreMin = Mathf.Clamp(holdScoreMin, 0f, trackScoreMin);
relocalizeScoreMin = Mathf.Clamp01(relocalizeScoreMin);
positionMinCutoff = Mathf.Max(positionMinCutoff, 0.001f);
rotationMinCutoff = Mathf.Max(rotationMinCutoff, 0.001f);
derivativeCutoff = Mathf.Max(derivativeCutoff, 0.001f);
minScoreWeight = Mathf.Clamp(minScoreWeight, 0.01f, 1f);
staticMinSamples = Mathf.Max(2, staticMinSamples);
staticReleaseMeters = Mathf.Max(staticReleaseMeters, staticRadiusMeters);
staticReleaseDegrees = Mathf.Max(staticReleaseDegrees, staticRotationDegrees);
maxRotationPredictAheadSeconds = Mathf.Clamp(maxRotationPredictAheadSeconds, 0f, maxPredictAheadSeconds);
maxCoastSeconds = Mathf.Max(maxCoastSeconds, coastGraceSeconds);
lostTimeoutSeconds = Mathf.Max(lostTimeoutSeconds, maxCoastSeconds);
```

- [ ] **Step 4: 编译确认旧引用暴露**

Run:

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: FAIL，旧类引用已删除字段。下一任务修复。

## 9. Task 4: Add OneEuroFilter Helper

**Files:**
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/OneEuroFilter.cs`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] **Step 1: 新增 helper 文件**

文件包含：

```csharp
namespace EgoAnchor.Policy
{
    /// <summary>One Euro 滤波数学工具，供 anchor policy 的位置和旋转通道复用。</summary>
    internal static class OneEuroMath
    {
        public static float Alpha(float cutoff, float dt) { ... }
        public static Quaternion Normalize(Quaternion q) { ... }
        public static Quaternion AlignSign(Quaternion reference, Quaternion value) { ... }
        public static Quaternion Multiply(Quaternion a, Quaternion b) { ... }
        public static Quaternion Inverse(Quaternion q) { ... }
        public static Vector3 Log(Quaternion q) { ... }
        public static Quaternion Exp(Vector3 rotationVector) { ... }
    }

    /// <summary>单轴 One Euro 滤波器。</summary>
    internal struct OneEuroFloat
    {
        public bool HasState { get; }
        public float Value { get; }
        public float Derivative { get; }
        public void Reset();
        public void Snap(float value, double timeSeconds);
        public float Update(float raw, double timeSeconds, float minCutoff, float beta, float derivativeCutoff, float scoreWeight);
    }

    /// <summary>三轴位置 One Euro 滤波器。</summary>
    internal struct OneEuroVector3
    {
        public Vector3 Value { get; }
        public Vector3 Velocity { get; }
        public void Reset();
        public void Snap(Vector3 value, double timeSeconds);
        public Vector3 Update(Vector3 raw, double timeSeconds, AnchorPolicyConfig config, float score);
    }

    /// <summary>四元数旋转 One Euro 滤波器。</summary>
    internal struct OneEuroRotation
    {
        public Quaternion Value { get; }
        public Vector3 AngularVelocityRad { get; }
        public void Reset();
        public void Snap(Quaternion value, double timeSeconds);
        public Quaternion Update(Quaternion raw, double timeSeconds, AnchorPolicyConfig config, float score);
    }
}
```

实现时不要使用 LINQ，不分配临时集合。所有方法保留中文 summary。

- [ ] **Step 2: 加入 smoke csproj**

在 `AnchorPolicySmoke.csproj` 加入：

```xml
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\OneEuroFilter.cs" Link="Policy\OneEuroFilter.cs" />
```

- [ ] **Step 3: 运行 smoke 编译**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected: 仍 FAIL，但 `OneEuroFilter.cs` 自身应无编译错误。

## 10. Task 5: Rewrite MotionStateClassifier

**Files:**
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/MotionStateClassifier.cs`

- [ ] **Step 1: 改 API**

将：

```csharp
public void Observe(Pose measuredPose, in InnovationStats innovation, double timeSeconds)
```

改为：

```csharp
public void Observe(Pose measuredPose, Pose predictedPose, double timeSeconds)
```

- [ ] **Step 2: 改进入静止逻辑**

进入静止只看最近 accepted 测量窗口：

- 时间覆盖 `staticWindowSeconds`
- 样本数不少于 `staticMinSamples`
- 所有位置距离窗口均值不超过 `staticRadiusMeters`
- 所有旋转距离窗口均值不超过 `staticRotationDegrees`

- [ ] **Step 3: 改退出静止逻辑**

如果当前是 Static，只要本帧测量相对预测 pose：

- 位置残差大于 `staticReleaseMeters`，或
- 旋转残差大于 `staticReleaseDegrees`

立即切到 Moving，并用当前测量重置窗口。

- [ ] **Step 4: 编译确认调用点待修**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected: FAIL，`PolicyController` 仍调用旧 API。

## 11. Task 6: Rewrite AnchorPoseFilter As One Euro Core

**Files:**
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPoseFilter.cs`

- [ ] **Step 1: 删除 Kalman 类型**

删除：

- `InnovationStats`
- `ScalarKalman2`
- `EvaluateInnovation`
- covariance/measurement noise/process noise 相关字段

保留：

- `AnchorPredictMode`
- `HasState`
- `StateTimeSeconds`
- `Velocity`
- `AngularVelocityRad`
- `AngularSpeedDps`

- [ ] **Step 2: 新状态字段**

使用：

```csharp
private AnchorPolicyConfig config;
private OneEuroVector3 positionFilter;
private OneEuroRotation rotationFilter;
private Pose statePose = Pose.identity;
private Pose outputPose = Pose.identity;
private Pose staticLockPose = Pose.identity;
private double stateTimeSeconds;
private double outputTimeSeconds = -1.0;
private bool hasState;
private bool hasOutput;
private bool staticLocked;
```

- [ ] **Step 3: 实现 public 方法**

提供：

```csharp
public bool HasState => hasState;
public double StateTimeSeconds => stateTimeSeconds;
public Pose StatePose => statePose;
public Vector3 Velocity => positionFilter.Velocity;
public Vector3 AngularVelocityRad => rotationFilter.AngularVelocityRad;
public float AngularSpeedDps => AngularVelocityRad.magnitude * Mathf.Rad2Deg;

public void ApplyConfig(AnchorPolicyConfig newConfig);
public void Reset();
public void Snap(Pose pose, double timeSeconds);
public Pose PredictAt(double timeSeconds, AnchorPredictMode mode, bool staticMode);
public Pose Correct(Pose measured, double timeSeconds, float score, bool staticMode);
public Pose AdvanceOutput(Pose target, AnchorPredictMode mode, bool staticMode, double nowSeconds);
public void Freeze(double nowSeconds);
```

- [ ] **Step 4: Correct 语义**

`Correct` 行为：

- 无状态时 `Snap`。
- staticMode=true 时仍更新 One Euro 的低通均值，但输出锁由 `AdvanceOutput` 控制；同时不让速度参与前推。
- staticMode=false 时正常 One Euro 更新。
- score 只在已经通过 gate 的测量中作为滤波权重，不再做复杂噪声模型。

- [ ] **Step 5: PredictAt 语义**

`Track`：

- 非静止时位置按 `Velocity * min(gap, maxPredictAheadSeconds)` 前推。
- 非静止时旋转按 `AngularVelocityRad * min(gap, maxRotationPredictAheadSeconds)` 前推。
- 静止时不前推。

`Coast`：

- 位置继续短时前推，但前推时长不超过 `maxCoastSeconds`，并可沿用 `maxPredictAheadSeconds` 作为有效上限。
- 旋转默认只用较短上限，避免低频旋转外推发散。

`Hold`：

- 返回提交态或输出态，不继续前推。

- [ ] **Step 6: AdvanceOutput 语义**

- 第一次输出直接 snap 到 target。
- `Hold` 返回上一输出。
- 静止模式下进入 static lock；偏差小于 release 阈值时只慢速归中。
- 运动模式下按 `movingOutputTauSeconds` 追踪 target，并用 `maxOutputSpeedMps/maxOutputAngularSpeedDps` 限速。

- [ ] **Step 7: 运行 build**

Run:

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: FAIL，`PolicyController` 仍引用旧 filter/gate。

## 12. Task 7: Rewrite PolicyController

**Files:**
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs`

- [ ] **Step 1: 删除旧 collaborator**

删除字段：

```csharp
private readonly AnchorMeasurementGate gate;
private readonly AnchorOutputSmoother outputSmoother;
private InnovationStats lastInnovation;
private float lastREffPos;
```

保留：

```csharp
private AnchorPolicyConfig config;
private readonly AnchorPoseFilter filter;
private readonly MotionStateClassifier classifier;
private AnchorStateMachine stateMachine;
```

- [ ] **Step 2: 新诊断字段**

加入：

```csharp
private float lastResidualMeters;
private float lastResidualDegrees;
private float lastAcceptedScore;
private float lastPredictAheadSeconds;
```

暴露：

```csharp
public float LastResidualMeters => lastResidualMeters;
public float LastResidualDegrees => lastResidualDegrees;
public float LastAcceptedScore => lastAcceptedScore;
public float PredictAheadSeconds => lastPredictAheadSeconds;
```

- [ ] **Step 3: AcceptPose 流程**

按顺序实现：

1. Paused -> `Hold/paused`。
2. `HasAlignedPose=false` -> `HandleMissing`。
3. 测量时间超龄或乱序 -> `Reject/stale_measurement`。
4. flags 含 `no_pose` 或 `invalid_pose` -> `Hold/flag_hold`。
5. `IsRelocalization` 且 score >= `relocalizeScoreMin` -> `Snap/relocalize_accept`。
6. 无 filter state 且 score >= `startScoreMin` -> `Snap/first_accept`。
7. 无 filter state 且 score 不足 -> `Reject/score_reject`。
8. 已有 state 且 score < `holdScoreMin` -> `Hold/score_hold`。
9. 已有 state 且 score < `trackScoreMin` -> `Hold/score_hold`。
10. 绝对跳变超过 `maxJumpMeters/maxJumpDegrees` -> `Reject/jump_reject`。
11. 正常 accepted：先 `PredictAt(measurementTime, Track, staticMode:false)` 得到预测 pose，更新 classifier，再 `Correct`。

接受类 reason 限制为：

- `first_accept`
- `score_accept`
- `static_lock`
- `motion_start`
- `relocalize_accept`

拒绝/保持类 reason 限制为：

- `score_hold`
- `score_reject`
- `flag_hold`
- `jump_reject`
- `stale_measurement`
- `no_pose`
- `align_failed`
- `paused`

- [ ] **Step 4: Advance 流程**

`Advance(nowSeconds)`：

- 无 filter state -> `AnchorPolicyOutput.None(...)`。
- `gap <= coastGraceSeconds` -> `Track`。
- `gap <= maxCoastSeconds` -> `Coast`。
- `gap > maxCoastSeconds` -> `Freeze` + `Hold`，状态由 `AnchorStateMachine` 推到 `FrozenUncertain` 或 `Lost`。
- 调用 `filter.PredictAt(nowSeconds, mode, classifier.IsStatic)`。
- 调用 `filter.AdvanceOutput(target, mode, classifier.IsStatic, nowSeconds)`。

- [ ] **Step 5: 保留 Notify APIs**

所有 `Notify*` 和 `Clear` 保留。reset/reacquire/lost/error 仍清空或冻结 filter/classifier，并驱动 `AnchorStateMachine`。

- [ ] **Step 6: 运行 smoke**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected: 编译通过后可能有行为阈值失败。只调第 5 节默认参数，不恢复旧 gate。

## 13. Task 8: Delete Obsolete Gate/Smoother

**Files:**
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs.meta`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs.meta`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] **Step 1: 删除旧文件**

使用 `apply_patch` 删除上述四个文件。

- [ ] **Step 2: 更新 smoke csproj**

删除：

```xml
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorOutputSmoother.cs" Link="Policy\AnchorOutputSmoother.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorMeasurementGate.cs" Link="Policy\AnchorMeasurementGate.cs" />
```

保留 `AnchorStateMachine.cs`、`MotionStateClassifier.cs`、`AnchorPoseFilter.cs`。

- [ ] **Step 3: 运行 smoke 和 Unity build**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: smoke PASS，Unity build PASS。已有第三方 warnings 可以保留，不应出现新的 EgoAnchor policy/runtime errors。

## 14. Task 9: Update Diagnostics

**Files:**
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`

- [ ] **Step 1: 更新 AnchorPolicyHost 诊断**

替换旧属性：

```csharp
public float LastInnovationPosD2 => Controller.LastInnovationPosD2;
public float LastREffPos => Controller.LastREffPos;
```

为：

```csharp
/// <summary>最近一次 accepted 测量与预测位姿的位置残差，单位米。</summary>
public float LastResidualMeters => Controller.LastResidualMeters;

/// <summary>最近一次 accepted 测量与预测位姿的旋转残差，单位度。</summary>
public float LastResidualDegrees => Controller.LastResidualDegrees;

/// <summary>最近一次 accepted 测量的可靠性分。</summary>
public float LastAcceptedScore => Controller.LastAcceptedScore;
```

- [ ] **Step 2: 更新 RuntimeDiagnostics 字段**

替换：

```csharp
public float latestInnovationPosD2;
public float latestEffectiveMeasurementNoise;
```

为：

```csharp
[Tooltip("最近一次 accepted 测量与预测位姿的位置残差，单位米。仅 policy 模式下更新。")]
public float latestResidualMeters;

[Tooltip("最近一次 accepted 测量与预测位姿的旋转残差，单位度。仅 policy 模式下更新。")]
public float latestResidualDegrees;

[Tooltip("最近一次 accepted 测量的 reliability score。仅 policy 模式下更新。")]
public float latestAcceptedScore;
```

- [ ] **Step 3: 更新 ApplyPolicyDecision**

同步新字段：

```csharp
diagnostics.latestResidualMeters = policyHost.LastResidualMeters;
diagnostics.latestResidualDegrees = policyHost.LastResidualDegrees;
diagnostics.latestAcceptedScore = policyHost.LastAcceptedScore;
```

- [ ] **Step 4: 运行 build**

Run:

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: PASS。

## 15. Task 10: Add AnchorRecoveryController

**Files:**
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs.meta`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] **Step 1: 新增组件**

`AnchorRecoveryController` 字段：

```csharp
[SerializeField] private PoseToAnchorRuntime runtime;
[SerializeField] private AnchorCommandClient commandClient;
[SerializeField] private bool autoReacquire = true;
[SerializeField] private bool reacquireOnLowScore = true;
[SerializeField] private bool reacquireOnLost = true;
[SerializeField] private bool reacquireOnNoPose = true;
[SerializeField] private float lowScoreSeconds = 0.8f;
[SerializeField] private float lostSeconds = 0.3f;
[SerializeField] private float noPoseSeconds = 1.0f;
[SerializeField] private float cooldownSeconds = 3.0f;
[SerializeField] private bool clearTrackingFirst = true;
```

行为：

- `score_hold`、`score_reject`、`flag_hold` 连续超过 `lowScoreSeconds` -> reacquire。
- `CurrentAnchorState == Lost` 连续超过 `lostSeconds` -> reacquire。
- `LatestPolicyReason` 为 `no_pose`、`align_failed` 或 `input_not_ready` 连续超过 `noPoseSeconds` -> reacquire；`input_not_ready` 可只计时不立刻发命令，避免 Python 未收到相机输入时重复请求。
- `commandInFlight` 时不重复发。
- 距上次命令不足 `cooldownSeconds` 时不重复发。
- 调用：

```csharp
await commandClient.ReacquireAsync(
    ReacquireAnchorRequest.Types.ReacquireMode.ForceDetect,
    clearTrackingFirst,
    string.Empty,
    0.0,
    "auto_reacquire_low_score_no_pose_or_lost",
    destroyCts.Token);
```

- [ ] **Step 2: 添加中文说明**

类 summary 明确：

```csharp
/// 本组件只观察 Unity runtime 状态并发送 command。
/// 它不解码 PoseResult，不修改 Transform，不直接重置 Python 模型状态。
```

- [ ] **Step 3: 加入 smoke**

`AnchorPolicySmoke.csproj` 加入：

```xml
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Runtime\AnchorRecoveryController.cs" Link="Runtime\AnchorRecoveryController.cs" />
```

`Program.cs` 加入 reflection smoke：

```csharp
private static void AssertAnchorRecoveryControllerExists()
{
    Type type = typeof(AnchorRecoveryController);
    Assert(type.GetMethod("Update", BindingFlags.Instance | BindingFlags.NonPublic) != null, "AnchorRecoveryController should tick in Update");
}
```

- [ ] **Step 4: 不改 scene**

当前 `EgoAnchor_Unity/Assets/Scene/EgoAnchor-Evaluation.unity` 已有用户改动，本计划不直接改 scene。代码完成后，再单独检查 scene diff 并绑定：

- policy runtime 的 `PoseToAnchorRuntime`
- 同一 NATS message plane 下的 `AnchorCommandClient`

## 16. Task 11: Documentation

**Files:**
- Modify: `ANCHOR_CONTROLLER_GUIDE.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: 更新 guide 总述**

写成：

```markdown
Unity Policy 层现在是 One Euro anchor controller。Python 仍输出低频 camera-space pose 和 score；Unity 先按 frame_id 对齐到 capture-time world pose，再用 One Euro 滤波和有界前推生成每渲染帧 stable anchor。静止时，测量窗口确认物体未动后锁定输出，吸收头显轻微晃动造成的 residual slip；运动时，One Euro 根据速度自动提高 cutoff，输出连续跟手。持续低分、no-pose 或 Lost 由 AnchorRecoveryController 请求 Python reacquire/register。
```

- [ ] **Step 2: 更新参数表**

只保留第 5 节字段。删除 Mahalanobis、Kalman covariance、teleport recovery、soft recovery 文案。

- [ ] **Step 3: 更新 AGENTS.md**

只改 `USER-MAINTAINED-REQUIREMENTS` 区块之外的当前事实：

- `PolicyController` = score/jump 简单 gate + One Euro + 静止锁 + lifecycle。
- `AnchorPoseFilter` = One Euro 提交态、渲染输出态、有界前推。
- `MotionStateClassifier` = 静止窗口判定，不依赖协方差。
- `AnchorRecoveryController` = 自动 reacquire bridge。

- [ ] **Step 4: 搜索过期术语**

Run:

```powershell
rg "马氏|Mahalanobis|teleport_recovery|softRecovery|soft recovery|6DoF Kalman|AnchorMeasurementGate|AnchorOutputSmoother" ANCHOR_CONTROLLER_GUIDE.md AGENTS.md EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy
```

Expected: 无输出，或只在“已删除机制”的说明中出现。推荐无输出。

## 17. Task 12: Full Verification

**Files:**
- No additional edits unless verification exposes failures.

- [ ] **Step 1: Unity policy smoke**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected:

```text
Anchor policy smoke passed.
```

- [ ] **Step 2: Unity build**

Run:

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: build succeeds. Existing package/sample warnings may remain; no new EgoAnchor policy/runtime errors.

- [ ] **Step 3: Python eval tests**

Run in `EgoAnchor_Python`:

```powershell
pixi run python -m unittest discover -s eval -p "test_*.py"
```

Expected: all eval tests pass.

- [ ] **Step 4: One Euro replay**

Run in `EgoAnchor_Python`:

```powershell
pixi run python .\eval\tools\replay_one_euro_policy.py --session .\data\eval\20260613_012345_controller_right
```

Expected: replay summary prints without schema errors. If One Euro replay is worse than raw by more than 5% on GT RMSE, tune only the defaults in `AnchorPolicyConfig` and Python replay params together.

- [ ] **Step 5: Existing metrics still load**

Run in `EgoAnchor_Python`:

```powershell
pixi run python -c "from pathlib import Path; from eval.io import load_session; from eval.metrics import compute_all_metrics; logs=load_session(Path('data/eval/20260613_012345_controller_right')); result=compute_all_metrics(logs); print(result.tables['anchor_error_summary'].to_string(index=False)); print(result.tables['policy_distribution'].to_string(index=False))"
```

Expected: command runs without schema errors. It evaluates old recorded data, so it is a schema regression check, not proof of new runtime behavior.

- [ ] **Step 6: Report simplification metrics**

Run from repo root:

```powershell
@'
from pathlib import Path
files = [
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyConfig.cs',
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/OneEuroFilter.cs',
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPoseFilter.cs',
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/MotionStateClassifier.cs',
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs',
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs',
]
for f in files:
    p = Path(f)
    if p.exists():
        print(f, len(p.read_text(encoding='utf-8').splitlines()))
'@ | python -
```

Expected: policy core lines materially lower than current baseline:

- `AnchorPolicyConfig.cs`: 251 lines before.
- `PolicyController.cs`: 496 lines before.
- `AnchorPoseFilter.cs`: 659 lines before.
- `AnchorMeasurementGate.cs`: 533 lines before, deleted.
- `AnchorOutputSmoother.cs`: 234 lines before, deleted.
- `MotionStateClassifier.cs`: 272 lines before, simplified.

## 18. Acceptance Criteria

- 静止物体：smoke 中输出位置/旋转 RMS 明显低于输入噪声；静止锁能压住 1-2cm 级 residual slip。
- 连续运动：5Hz pose 输入下，Unity 渲染帧输出连续移动/旋转，source frame 之间无长时间零增量。
- 低分：低分测量不拖动 anchor；持续低分会触发 reacquire，且有 cooldown。
- 断流：短时 no-pose 先 coast，再 freeze，超过阈值进入 Lost；Lost 可触发 reacquire。
- 边界：frame alignment、raw baseline、processor baseline、NATS transport、Protobuf 不改。
- 代码：旧 Mahalanobis/Kalman/teleport/soft recovery 代码删除，不保留兼容旧参数。

## 19. Implementation Notes

- 不要在 `Policy/` plain C# 类中读取 `UnityEngine.Time`；时间必须由调用者传入。
- 不要在 `NatsControlClient`、`PoseResultReceiver`、`DynamicObjectAnchor` 中加入 policy 逻辑。
- 不要把自动 reacquire 写成 `PolicyController` 内的 async command。policy 内核保持可 smoke 驱动，command bridge 放在 MonoBehaviour。
- Unity 新 Inspector 字段必须有中文 `[Tooltip]`；新增类、成员变量、方法必须有中文 summary。
- 不迁移旧 Inspector 字段值。旧参数正是本次要删除的复杂度来源。

## 20. Self-Review

- Spec coverage: 覆盖静止稳定、连续运动、低分 hold、断流退化、自动 reacquire、One Euro、离线回放、baseline 保留、文档和验证。
- Placeholder scan: 无 `TBD`、无未指定路径、无“以后实现”占位。
- Type consistency: 保留现有公开 DTO；新增 `OneEuroFilter.cs` 和 `AnchorRecoveryController.cs`；删除的文件只在 smoke csproj 和文档中同步清理。
- Main risk: One Euro 默认参数需要离线回放和真机微调。计划先做 Python replay，再做 C#，避免直接把未经验证的默认值固化进 Unity。
