# Anchor Policy Simplification Implementation Plan

## 对比结论：GPT 的计划在"工程严谨度"上明显更强，我的在"算法选型"上更优

最重要的发现先说： **我之前漏掉了关键基础设施** 。我把搜索局限在 `EgoAnchor_Unity/Assets`，所以没发现你项目里其实已经有一套完整的验证体系，而 GPT 发现了并把它编进了计划:

* ✅  **真实存在的 1417 行 smoke 测试** （`EgoAnchor_Tools/anchor_policy_smoke/Program.cs`），它 compile-include 了所有 policy 文件，离线驱动 `PolicyController`。代码注释里的"可被 smoke 工具驱动"不是空话。
* ✅ **headless 编译路径** `Assembly-CSharp.csproj`。
* ✅  **Python eval 框架** （`eval/metrics` 产出 `anchor_error_summary`、`policy_distribution` 两张表 + 单元测试）。
* ✅ 需要同步的文档 `ANCHOR_CONTROLLER_GUIDE.md` / `AGENTS.md`。

这是我方案的 **真实不足** ：我提议"新写一个 `replay_policy_eval.py`"，但其实你已经有 eval 框架可以复用；我也完全没提 smoke 测试和文档同步。GPT 在这点上做得对。

---

### 逐项对比

| 维度                        | 我的方案                                                     | GPT 方案                                                                               | 取谁                                       |
| --------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------- | ------------------------------------------ |
| **核心滤波算法**      | One-Euro 自适应低通（速度自适应，连续，无离散态）            | 保留"静止锁定 + 运动校正比例"双模式，沿用 `MotionStateClassifier` 离散 Static/Moving | **取我的**                           |
| **测试基础设施**      | 漏了 smoke，提议新写 replay                                  | 正确复用 1417 行 smoke + 改写断言为目标行为门                                          | **取 GPT 的**                        |
| **TDD 流程**          | 无明确"先写测试看失败"流程                                   | 严格 Task1 先写失败测试 → 逐 Task 转绿，每步带 `dotnet build/run` 验证              | **取 GPT 的**                        |
| **自动重注册**        | Lifecycle 内回调，触发条件仅"持续低分"（按你的选择）         | 独立 `AnchorRecoveryController` MonoBehaviour，低分+Lost 都触发                      | **结构取 GPT，触发条件取你的决定**   |
| **文档/AGENTS 同步**  | 提了使用文档，没提 AGENTS                                    | 明确列出 guide + AGENTS 更新且不碰 USER-MAINTAINED 区                                  | **取 GPT 的**                        |
| **延迟分析/前推策略** | 量化了 268ms 延迟、量化静止抖动/运动误差 vs GT，明确前推档位 | 有 evidence 段但**没量化端到端延迟** ，前推沿用旧的 0.15s 没有论证               | **取我的**                           |
| **eval 回归对照**     | 提了用真机数据回归对比新旧                                   | Task10 跑 eval 但**明说"评估的是旧录制数据，不能证明新行为"**                    | **取我的（需补一个真正的回放对比）** |

---

### GPT 方案的"糟粕"（要去掉的）

1. **`MotionStateClassifier` 保留是最大败笔。** GPT 自己在 Evidence 里写了 motion_state 翻转问题的边角，却仍保留离散 Static/Moving 双模式 + 静止锁定/释放阈值。我的数据证明这套**每秒翻转 1.56 次**正是静止晃动的隐患来源。One-Euro 用一个连续的 `cutoff = minCutoff + beta*|速度|` 同时解决静止稳和运动跟手，根本不需要离散态、不需要静止锁、不需要 release 阈值。GPT 的 config 里那 6 个 `static*` 参数全可以消掉。
2. **前推 0.15s 没有依据。** GPT 直接沿用旧值。我量化出实际未补偿延迟 ~156ms，前推策略应该是被论证过的决策（你已选"平衡 ~120-150ms"），不是抄旧值。
3. **Task10 的"验证"是假验证。** GPT 自己承认跑 eval 用的是旧数据，证明不了新算法效果。真正需要的是**用真机 aligned pose 回放喂进新 Tracker**做对照——这正是我方案的回归脚本要干的，但应该接到你现有的 eval 框架里输出 `anchor_error_summary`,而不是另起炉灶。
4. **`positionCorrection/velocityBlend` 这类参数仍偏多且耦合。** 它本质是手搓了一个简化 alpha-beta 滤波器,4 个融合比例参数互相影响,调参体验不会比现在好太多。One-Euro 的 `minCutoff/beta` 物理意义更清晰(截止频率 + 速度响应)。

---

### 融合后的最终方案（取两者精华）

```
算法内核    : One-Euro（我的）—— 删掉 MotionStateClassifier，无离散态
工程流程    : TDD + 复用 smoke（GPT 的）—— 改写 Program.cs 断言为目标行为门
自动重注册  : 独立 AnchorRecoveryController（GPT 结构）+ 仅"持续低分"触发（你的决定）
验证        : 真机 aligned pose 回放接入现有 eval 框架（我的思路 + GPT 的 eval 复用）
文档        : guide + AGENTS 同步，不碰 USER-MAINTAINED（GPT 的）
接口冻结    : AcceptPose/Advance/AnchorPolicyOutput/eval schema 不变（两者一致）
```

具体 Task 编排照搬 GPT 的骨架（Task1 写失败测试 → Task2 config → ... → Task10 验证），但把:

* Task3「Rewrite MotionStateClassifier」→ 改成「**Delete** MotionStateClassifier」
* Task4「Rewrite AnchorPoseFilter as kinematic predictor」→ 改成「Rewrite as **One-Euro** tracker」
* Task1 的断言去掉所有 `static lock / release` 相关门，换成「静止抖动 ≤ 旧 kalman」「运动连续无阶梯」「One-Euro 运动误差 ≤ raw」
* Task10 增加一步「真机数据回放对照」补上真验证

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Unity anchor policy 从复杂的 reliability-aware 6DoF Kalman/门控组合，重构为更小、更可调的“静止锁定 + 运动预测校正 + 低分/断流重获取”控制器。

**Architecture:** Python 仍只输出低频 camera-space `PoseResult` 和质量评分；Unity 仍由 `PoseToAnchorRuntime` 做 frame-aligned world pose。`PolicyController` 的公开入口保持 `AcceptPose` / `Advance` / `Notify*`，内部改为简单双模式控制：静止时锁定输出并慢速归中，运动时维护线速度/角速度并按 render time 预测输出；自动 reacquire 放在独立 MonoBehaviour，不写进 transport、receiver 或 Transform 应用层。

**Tech Stack:** Unity C#、Google.Protobuf、NATS command API、现有 `EgoAnchor_Tools/anchor_policy_smoke` 离线 smoke、`dotnet build` Unity 编译验证、`EgoAnchor_Python/eval` JSONL 离线评估。

---

## Evidence From Current Project

- 当前真机 session：`EgoAnchor_Python/data/eval/20260613_012345_controller_right`。
- Python 有效 pose 约 5.2Hz：Unity output source frame 变化间隔 P50 0.194s，P90 0.208s。
- Unity render output 约 67Hz：3182 行，47.544s。
- 当前主输出 label 是 `kalman`，但包含 `policy_action=Accept/Hold`、`motion_state` 和 `predict_ahead_ms`，实际是 policy path 的 primary output。
- 当前 policy 能消除 raw 的 5Hz 阶梯：移动段中 policy 有 53/66 个 source gap 内出现逐帧运动，raw 只有 6/66。
- 当前 policy 在这段未标 condition 的 session 中没有降低世界误差：`anchor_error_summary` 中 policy translation RMSE 33.8mm，raw 30.9mm；policy slip RMS 30.1px，raw 27.4px。
- 当前低分只出现一条 source frame，造成 11 个 render frame 的 `Hold/score_hold`；复杂跳变/恢复逻辑在该 session 中基本没有被触发。

## Target Behavior

1. 物体静止时，anchor world pose 稳定，不跟随头显轻微晃动造成的小 residual slip。
2. 物体连续移动时，anchor pose 在 render frame 上连续变化，平移和旋转都不阶梯、不断续。
3. 低分 pose 不拖动 anchor；连续低分、连续 no-pose 或 Lost 后自动请求 Python reacquire/register。
4. 不改 Python pose 语义、不改 protocol、不改 frame alignment，不使用 pose 到达时 HMD pose 替代 capture-time frame pose。
5. raw / processor baseline 继续保留；policy runtime 继续不经过 processor 链。

## File Structure

### Modify

- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyConfig.cs`
  - 精简 Inspector 参数，删除 teleport/soft recovery/chi-square 等当前目标不需要的参数。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs`
  - 保留公开 API，内部改为简单双模式控制器。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPoseFilter.cs`
  - 重写为简单运动学状态：位置、旋转、线速度、角速度、输出 pose、预测/校正/冻结。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/MotionStateClassifier.cs`
  - 保留“测量窗口散布判静止，单帧位移/旋转退出静止”的核心逻辑，移除对 Mahalanobis innovation 的依赖。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`
  - 保留宿主职责，调整诊断属性名和 Tooltip。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
  - 只更新 policy 诊断字段，不改变 frame alignment、baseline processor、server status/heartbeat 逻辑。
- `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`
  - 将 policy smoke 收敛为目标行为门，删除旧 Mahalanobis/teleport/soft recovery 专属断言。
- `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`
  - 删除不再存在的旧 policy 文件 include，加入新增文件 include。
- `ANCHOR_CONTROLLER_GUIDE.md`
  - 同步新控制器使用方式和参数。
- `AGENTS.md`
  - 只更新用户维护区块之外的当前主线事实，描述新 policy；不得修改 `USER-MAINTAINED-REQUIREMENTS`。

### Delete

- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs`
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs.meta`
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs`
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs.meta`

### Create

- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs`
  - 独立 MonoBehaviour，根据 runtime 状态/score/原因触发 `AnchorCommandClient.ReacquireAsync`。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs.meta`
  - Unity meta；如果通过 Unity Editor 生成则保留 Editor 结果，否则用新 GUID。

---

## Task 1: Replace Policy Smoke With Target Behavior Gates

**Files:**

- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] **Step 1: Keep integration smoke, replace policy-specific assertions**

保留 frame alignment、NATS queue、runtime hub、status event、processor skip 等非 policy 内核断言。将 `Main()` 顶部 policy 场景替换为下面这组目标门：

```csharp
// ===== 简单双模式 anchor 控制器场景断言 =====
AssertFirstPoseSnaps();
AssertStaticLockSuppressesHeadMotionSlip();
AssertStaticClassifierUsesWindowDispersion();
AssertStaticReleasesOnRealMotion();
AssertLowRateMotionIsContinuous();
AssertLowRateRotationIsContinuous();
AssertLowScoreHoldsWithoutDragging();
AssertNoPoseCoastsThenFreezesThenLost();
AssertRelocalizeSnap();
AssertStaleMeasurementIgnored();
AssertConfigHotReload();
AssertNotifyChain();
```

删除以下旧场景调用：

```csharp
AssertMovingResponseAndPerFrameOutput();
AssertScoreHysteresis();
AssertLowScoreTrackPoseFailsSoftWhenPlausible();
AssertLowScoreTrackMotionExitsStatic();
AssertLowScoreTrackJumpStillRejected();
AssertTeleportRecovery();
AssertRotationJumpRecoversSoftly();
AssertMediumTranslationRecoversSoftly();
AssertRotationFilterGates();
```

- [ ] **Step 2: Add static head-motion slip gate**

在 `Program.cs` policy 场景区域加入：

```csharp
/// <summary>S2：静止物体 + 小幅头动残差下，输出锁应显著压低显示抖动。</summary>
private static void AssertStaticLockSuppressesHeadMotionSlip()
{
    PolicyController controller = new PolicyController();
    Pose truth = new Pose(new Vector3(0.3f, -0.2f, 1.0f), YawDegrees(30f));
    Lcg rng = new Lcg(20260613);
    const int messageCount = 80;
    const int warmupMessages = 35;

    List<float> inputErrors = new List<float>();
    List<float> outputErrors = new List<float>();
    double firstStaticTime = -1.0;

    for (int i = 0; i < messageCount; i++)
    {
        double t = i * 0.20;
        Pose measured = MakeNoisyPose(truth, 0.003f, 0.45f, ref rng);
        controller.AcceptPose(MakeTrackObservation(i + 1, measured, t, 0.9f, t));
        if (firstStaticTime < 0.0 && controller.MotionState == AnchorMotionState.Static)
        {
            firstStaticTime = t;
        }

        for (double ta = t + FrameDt; ta < t + 0.20; ta += FrameDt)
        {
            AnchorPolicyOutput output = controller.Advance(ta);
            if (i >= warmupMessages)
            {
                inputErrors.Add(Vector3.Distance(measured.position, truth.position));
                outputErrors.Add(Vector3.Distance(output.Pose.position, truth.position));
            }
        }
    }

    Assert(firstStaticTime >= 0.0 && firstStaticTime <= 1.2, $"static mode should engage within 1.2s, got {firstStaticTime:F2}s");
    Assert(Rms(outputErrors) < Rms(inputErrors) * 0.35f, "static output should suppress most measurement jitter");
}
```

- [ ] **Step 3: Add low-rate motion continuity gate**

加入或替换 `AssertLowRateMotionIsInterpolated` 为：

```csharp
/// <summary>S3：5Hz 左右 pose 流下，运动输出应在 source frame 之间持续变化。</summary>
private static void AssertLowRateMotionIsContinuous()
{
    PolicyController controller = new PolicyController();
    Vector3 start = new Vector3(0f, 0f, 1f);
    Vector3 velocity = new Vector3(0.35f, 0f, 0f);
    const double msgDt = 0.20;
    const double latency = 0.18;
    int zeroRun = 0;
    int maxZeroRun = 0;
    int movingSteps = 0;
    Pose previous = Pose.identity;
    bool hasPrevious = false;

    for (int k = 0; k < 35; k++)
    {
        double capture = k * msgDt;
        double arrival = capture + latency;
        Pose measured = new Pose(start + velocity * (float)capture, Quaternion.identity);
        controller.AcceptPose(MakeTrackObservation(k + 1, measured, arrival, 0.9f, capture));

        for (double ta = arrival + FrameDt; ta < arrival + msgDt; ta += FrameDt)
        {
            AnchorPolicyOutput output = controller.Advance(ta);
            if (hasPrevious)
            {
                float step = Vector3.Distance(output.Pose.position, previous.position);
                if (step <= 1e-5f)
                {
                    zeroRun++;
                }
                else
                {
                    movingSteps++;
                    maxZeroRun = Math.Max(maxZeroRun, zeroRun);
                    zeroRun = 0;
                }
            }

            previous = output.Pose;
            hasPrevious = true;
        }
    }

    maxZeroRun = Math.Max(maxZeroRun, zeroRun);
    Assert(movingSteps > 80, "low-rate motion should produce many render-frame movement steps");
    Assert(maxZeroRun <= 4, $"low-rate motion should not have long still runs, got {maxZeroRun}");
}
```

- [ ] **Step 4: Add low score hold gate**

加入：

```csharp
/// <summary>S4：低分测量不应拖动 anchor，输出保持上一稳定 pose。</summary>
private static void AssertLowScoreHoldsWithoutDragging()
{
    PolicyController controller = new PolicyController();
    Pose basePose = new Pose(new Vector3(0.2f, 0f, 1f), Quaternion.identity);
    controller.AcceptPose(MakeTrackObservation(1, basePose, 0.0, 0.9f, 0.0));
    Pose before = controller.Advance(0.05).Pose;

    Pose badPose = new Pose(basePose.position + new Vector3(0.3f, 0f, 0f), YawDegrees(60f));
    AnchorPolicyDecision decision = controller.AcceptPose(MakeTrackObservation(2, badPose, 0.20, 0.05f, 0.20));
    Pose after = controller.Advance(0.25).Pose;

    Assert(decision.Action == AnchorPolicyAction.Hold || decision.Action == AnchorPolicyAction.Reject, "low score should hold or reject");
    Assert(Vector3.Distance(before.position, after.position) < 0.002f, "low score pose should not drag output position");
    Assert(QuaternionAngleDegrees(before.rotation, after.rotation) < 0.2f, "low score pose should not drag output rotation");
}
```

- [ ] **Step 5: Run smoke to confirm tests fail before implementation**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected: FAIL because old `PolicyController` still exposes obsolete behavior and the new smoke references not-yet-implemented simplified semantics.

---

## Task 2: Simplify AnchorPolicyConfig

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyConfig.cs`

- [ ] **Step 1: Replace config fields**

Rewrite the config class to keep these groups only:

```csharp
[Serializable]
public sealed class AnchorPolicyConfig
{
    [Header("评分门控")]
    [Tooltip("冷启动或重定位后接受第一帧 pose 的最低可靠性分。")]
    [Range(0f, 1f)] public float startScoreMin = 0.35f;

    [Tooltip("已有 anchor 后继续接受普通 TRACK pose 的最低可靠性分。")]
    [Range(0f, 1f)] public float trackScoreMin = 0.20f;

    [Tooltip("低于该分数时本帧只保持输出，不进入运动校正。")]
    [Range(0f, 1f)] public float holdScoreMin = 0.12f;

    [Tooltip("REGISTER/RE_REGISTER pose 的接受下限。")]
    [Range(0f, 1f)] public float relocalizeScoreMin = 0.12f;

    [Header("静止识别")]
    [Tooltip("进入静止判定窗口长度，单位秒。")]
    [Min(0.05f)] public float staticWindowSeconds = 0.60f;

    [Tooltip("进入静止需要的最少 accepted pose 数。")]
    [Min(2)] public int staticMinSamples = 3;

    [Tooltip("窗口内位置散布半径，单位米。")]
    [Min(0.001f)] public float staticRadiusMeters = 0.012f;

    [Tooltip("窗口内旋转散布上限，单位度。")]
    [Min(0.1f)] public float staticRotationDegrees = 2.5f;

    [Tooltip("静止锁释放的位置阈值，单位米。")]
    [Min(0.001f)] public float staticReleaseMeters = 0.020f;

    [Tooltip("静止锁释放的旋转阈值，单位度。")]
    [Min(0.1f)] public float staticReleaseDegrees = 3.0f;

    [Header("运动预测")]
    [Tooltip("位置测量校正比例。越大越跟手，越小越平滑。")]
    [Range(0.01f, 1f)] public float positionCorrection = 0.65f;

    [Tooltip("旋转测量校正比例。越大越跟手，越小越平滑。")]
    [Range(0.01f, 1f)] public float rotationCorrection = 0.55f;

    [Tooltip("线速度估计融合比例。")]
    [Range(0.01f, 1f)] public float velocityBlend = 0.45f;

    [Tooltip("角速度估计融合比例。")]
    [Range(0.01f, 1f)] public float angularVelocityBlend = 0.35f;

    [Tooltip("跟踪状态下预测到渲染时刻的最大时长，单位秒。")]
    [Min(0f)] public float maxPredictAheadSeconds = 0.15f;

    [Tooltip("旋转预测到渲染时刻的最大时长，单位秒。")]
    [Min(0f)] public float maxRotationPredictAheadSeconds = 0.08f;

    [Tooltip("渲染输出追踪目标 pose 的时间常数，单位秒。")]
    [Min(0.001f)] public float outputSmoothingTauSeconds = 0.04f;

    [Tooltip("渲染输出最大线速度，单位米/秒。")]
    [Min(0.01f)] public float maxOutputSpeedMps = 3.0f;

    [Tooltip("渲染输出最大角速度，单位度/秒。")]
    [Min(1f)] public float maxOutputAngularSpeedDps = 720f;

    [Header("断流退化")]
    [Tooltip("正常 pose 消息间隔保护时间，单位秒；约 5Hz pose 流建议不小于 0.25s。")]
    [Min(0.02f)] public float coastGraceSeconds = 0.30f;

    [Tooltip("短时断流可外推的最长时间，单位秒。")]
    [Min(0.05f)] public float maxCoastSeconds = 0.45f;

    [Tooltip("进入 Lost 的无可靠 pose 时长，单位秒。")]
    [Min(0.2f)] public float lostTimeoutSeconds = 2.0f;

    [Tooltip("测量采集时间相对到达时间允许的最大年龄，单位秒。")]
    [Min(0.1f)] public float maxMeasurementAgeSeconds = 1.0f;

    public void Validate()
    {
        startScoreMin = Mathf.Clamp01(startScoreMin);
        trackScoreMin = Mathf.Clamp(trackScoreMin, 0f, startScoreMin);
        holdScoreMin = Mathf.Clamp(holdScoreMin, 0f, trackScoreMin);
        relocalizeScoreMin = Mathf.Clamp01(relocalizeScoreMin);
        staticMinSamples = Mathf.Max(2, staticMinSamples);
        staticReleaseMeters = Mathf.Max(staticReleaseMeters, staticRadiusMeters);
        staticReleaseDegrees = Mathf.Max(staticReleaseDegrees, staticRotationDegrees);
        maxRotationPredictAheadSeconds = Mathf.Clamp(maxRotationPredictAheadSeconds, 0f, maxPredictAheadSeconds);
        maxCoastSeconds = Mathf.Max(maxCoastSeconds, coastGraceSeconds);
        lostTimeoutSeconds = Mathf.Max(lostTimeoutSeconds, maxCoastSeconds);
    }
}
```

- [ ] **Step 2: Run build to expose compile errors**

Run:

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: FAIL because old policy classes still reference removed config fields.

---

## Task 3: Rewrite MotionStateClassifier Without InnovationStats

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/MotionStateClassifier.cs`

- [ ] **Step 1: Change public API**

Replace `Observe(Pose measuredPose, in InnovationStats innovation, double timeSeconds)` with:

```csharp
public void Observe(Pose measuredPose, Pose predictedPose, double timeSeconds)
```

The method should:

- if currently Static and `Vector3.Distance(measuredPose.position, predictedPose.position) > config.staticReleaseMeters`, switch to Moving and reset window;
- if currently Static and `Quaternion.Angle(measuredPose.rotation, predictedPose.rotation) > config.staticReleaseDegrees`, switch to Moving and reset window;
- otherwise add the measurement to the sliding window and enter Static only when `staticWindowSeconds`, `staticMinSamples`, `staticRadiusMeters`, and `staticRotationDegrees` all pass.

- [ ] **Step 2: Keep Chinese summaries**

Every class, member, and public method must keep Chinese XML summary. The class summary should explicitly state:

```csharp
/// 静止/运动状态分类器。
/// 只根据最近 accepted 测量在 world 空间的散布和当前预测残差判断静止/运动，
/// 不依赖滤波器协方差或马氏距离，便于按真机日志解释和调参。
```

- [ ] **Step 3: Run smoke compile**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected: FAIL until `PolicyController` and `AnchorPoseFilter` are rewritten to call the new API.

---

## Task 4: Rewrite AnchorPoseFilter As Kinematic Predictor

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPoseFilter.cs`

- [ ] **Step 1: Remove Kalman-specific types**

Delete `InnovationStats`, `ScalarKalman2`, covariance fields, measurement noise fields, and `EvaluateInnovation`.

- [ ] **Step 2: Keep `AnchorPredictMode`**

Keep the enum values `Hold`, `Track`, and `Coast` so `AnchorPolicyOutput` and smoke terminology remain stable.

- [ ] **Step 3: Implement state fields**

Use these fields:

```csharp
private AnchorPolicyConfig config;
private Pose statePose = Pose.identity;
private Pose outputPose = Pose.identity;
private Vector3 velocity;
private Vector3 angularVelocityRad;
private double stateTimeSeconds;
private double outputTimeSeconds = -1.0;
private bool hasState;
private bool hasOutput;
```

- [ ] **Step 4: Implement methods**

Provide these public methods:

```csharp
public bool HasState => hasState;
public double StateTimeSeconds => stateTimeSeconds;
public Pose StatePose => statePose;
public Vector3 Velocity => velocity;
public Vector3 AngularVelocityRad => angularVelocityRad;
public float AngularSpeedDps => angularVelocityRad.magnitude * Mathf.Rad2Deg;

public void ApplyConfig(AnchorPolicyConfig newConfig)
public void Reset()
public void Snap(Pose pose, double timeSeconds)
public Pose PredictAt(double timeSeconds, AnchorPredictMode mode)
public Pose Correct(Pose measured, double timeSeconds, float score, bool staticMode)
public Pose AdvanceOutput(Pose target, AnchorPredictMode mode, bool staticMode, double nowSeconds)
public void Freeze(double nowSeconds)
```

`Correct` should:

- predict current state to `timeSeconds`;
- compute position residual and rotation residual;
- if `staticMode`, keep `statePose` close to previous/mean, zero velocities, and only allow slow centering;
- if moving, apply `positionCorrection * score` and `rotationCorrection * score`;
- estimate `velocity` from residual / dt using `velocityBlend * score`;
- estimate `angularVelocityRad` from quaternion log residual / dt using `angularVelocityBlend * score`;
- clamp non-finite dt to 0.001s minimum.

`AdvanceOutput` should:

- initialize output on first call;
- in Hold mode, return current output unchanged;
- in Track/Coast, move output toward target using exponential smoothing and `maxOutputSpeedMps` / `maxOutputAngularSpeedDps`;
- in Static mode, keep output locked while target remains within release thresholds, otherwise release and follow.

- [ ] **Step 5: Run build**

Run:

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: FAIL until `PolicyController` is rewritten for the new filter methods.

---

## Task 5: Rewrite PolicyController Around Two Modes

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs`

- [ ] **Step 1: Remove old collaborators**

Remove fields:

```csharp
private readonly AnchorMeasurementGate gate;
private readonly AnchorOutputSmoother outputSmoother;
private InnovationStats lastInnovation;
private float lastREffPos;
private bool outputFrozen;
```

Keep:

```csharp
private AnchorPolicyConfig config;
private readonly AnchorPoseFilter filter;
private readonly MotionStateClassifier classifier;
private AnchorStateMachine stateMachine;
```

- [ ] **Step 2: Add simple diagnostics**

Add:

```csharp
private float lastResidualMeters;
private float lastResidualDegrees;
private float lastAcceptedScore;
private float lastPredictAheadSeconds;
```

Expose:

```csharp
public float LastResidualMeters => lastResidualMeters;
public float LastResidualDegrees => lastResidualDegrees;
public float LastAcceptedScore => lastAcceptedScore;
```

- [ ] **Step 3: Implement `AcceptPose`**

The method flow should be:

1. Paused -> `Hold/paused`.
2. Missing pose -> `HandleMissing`.
3. Stale/over-age measurement -> `Reject/stale_measurement`.
4. Hard flags `no_pose` or `invalid_pose` -> `Hold/flag_hold`.
5. Relocalization and score >= `relocalizeScoreMin` -> `Snap/relocalize_accept`.
6. No filter state and score >= `startScoreMin` -> `Snap/first_accept`.
7. No filter state and score below threshold -> `Reject/score_reject`.
8. Existing state and score < `holdScoreMin` -> `Hold/score_hold`.
9. Existing state and score < `trackScoreMin` -> `Hold/score_hold`.
10. Existing state and score accepted -> predict to measurement time, update classifier, correct filter, state Tracking.

Decision reasons should be limited to:

- `first_accept`
- `score_accept`
- `motion_start`
- `static_lock`
- `score_hold`
- `flag_hold`
- `stale_measurement`
- `relocalize_accept`
- `no_pose`
- `align_failed`

- [ ] **Step 4: Implement `Advance`**

`Advance(nowSeconds)` should:

- return `None` if no filter state;
- compute gap from `lastAcceptSampleTime`;
- if gap <= `coastGraceSeconds`, mode `Track`;
- else if gap <= `maxCoastSeconds`, mode `Coast`;
- else call `filter.Freeze(nowSeconds)` and mode `Hold`;
- use `AnchorStateMachine` to enter `Tracking`, `Coasting`, `FrozenUncertain`, or `Lost`;
- call `filter.PredictAt(nowSeconds, mode)` then `filter.AdvanceOutput(...)`.

- [ ] **Step 5: Preserve Notify APIs**

Keep `NotifyReset`, `NotifyReacquire`, `NotifyPause`, `NotifyResume`, `NotifyError`, `NotifyLost`, and `Clear`. They should reset the simplified filter/classifier and drive `AnchorStateMachine` exactly as today.

- [ ] **Step 6: Run smoke**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected: policy smoke should now compile and fail only on behavioral thresholds. Tune config defaults inside `AnchorPolicyConfig` until the new target gates pass.

---

## Task 6: Delete Obsolete Policy Files And Update Smoke Project

**Files:**

- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorMeasurementGate.cs.meta`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorOutputSmoother.cs.meta`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`

- [ ] **Step 1: Delete obsolete files**

Use `apply_patch` delete hunks for the four obsolete files.

- [ ] **Step 2: Remove compile includes**

Remove these lines from `AnchorPolicySmoke.csproj`:

```xml
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorOutputSmoother.cs" Link="Policy\AnchorOutputSmoother.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorMeasurementGate.cs" Link="Policy\AnchorMeasurementGate.cs" />
```

- [ ] **Step 3: Run smoke and Unity build**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: smoke PASS, build PASS with no new errors. Existing third-party/sample warnings may remain.

---

## Task 7: Update Runtime Diagnostics For Simplified Policy

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`

- [ ] **Step 1: Update host diagnostics**

In `AnchorPolicyHost`, replace old properties:

```csharp
public float LastInnovationPosD2 => Controller.LastInnovationPosD2;
public float LastREffPos => Controller.LastREffPos;
```

with:

```csharp
/// <summary>最近一次 accepted 测量的位置残差，单位米。</summary>
public float LastResidualMeters => Controller.LastResidualMeters;

/// <summary>最近一次 accepted 测量的旋转残差，单位度。</summary>
public float LastResidualDegrees => Controller.LastResidualDegrees;

/// <summary>最近一次 accepted 测量的可靠性分。</summary>
public float LastAcceptedScore => Controller.LastAcceptedScore;
```

- [ ] **Step 2: Update runtime diagnostic fields**

In `RuntimeDiagnostics`, replace:

```csharp
public float latestInnovationPosD2;
public float latestEffectiveMeasurementNoise;
```

with:

```csharp
[Tooltip("最近一次 accepted 测量与预测位姿的位置残差，单位米。仅 policy 模式下更新。")]
public float latestResidualMeters;

[Tooltip("最近一次 accepted 测量与预测位姿的旋转残差，单位度。仅 policy 模式下更新。")]
public float latestResidualDegrees;

[Tooltip("最近一次 accepted 测量的 reliability score。仅 policy 模式下更新。")]
public float latestAcceptedScore;
```

- [ ] **Step 3: Update `ApplyPolicyDecision`**

Replace old sync:

```csharp
diagnostics.latestInnovationPosD2 = policyHost.LastInnovationPosD2;
diagnostics.latestEffectiveMeasurementNoise = policyHost.LastREffPos;
```

with:

```csharp
diagnostics.latestResidualMeters = policyHost.LastResidualMeters;
diagnostics.latestResidualDegrees = policyHost.LastResidualDegrees;
diagnostics.latestAcceptedScore = policyHost.LastAcceptedScore;
```

- [ ] **Step 4: Run build**

Run:

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: PASS.

---

## Task 8: Add AnchorRecoveryController For Automatic Reacquire

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs.meta`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj`
- Modify: `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

- [ ] **Step 1: Add class**

Create `AnchorRecoveryController.cs`:

```csharp
using System.Threading;
using EgoAnchor.Client;
using EgoAnchor.Protocol.Generated;
using UnityEngine;

namespace EgoAnchor.Runtime
{
    /// <summary>
    /// Anchor 自动重获取控制器。
    /// 本组件只观察 PoseToAnchorRuntime 的本地状态和最近 policy 诊断，
    /// 在连续低分、连续无 pose 或 Lost 后通过 AnchorCommandClient 请求 Python 重新 register。
    /// 它不解码 PoseResult、不修改 Transform、不直接重置 Python 模型状态。
    /// </summary>
    public sealed class AnchorRecoveryController : MonoBehaviour
    {
        /// <summary>要观察的 anchor runtime。</summary>
        [Tooltip("要观察的 anchor runtime。通常指向 policy 变体的 PoseToAnchorRuntime。")]
        [SerializeField] private PoseToAnchorRuntime runtime;

        /// <summary>发送 reacquire command 的客户端。</summary>
        [Tooltip("发送 reacquire command 的 AnchorCommandClient。必须与 runtime 使用同一个 NATS message plane。")]
        [SerializeField] private AnchorCommandClient commandClient;

        /// <summary>是否启用自动重获取。</summary>
        [Tooltip("是否启用自动重获取。关闭后只保留手动按钮命令。")]
        [SerializeField] private bool autoReacquire = true;

        /// <summary>连续低分/保持多久后触发 reacquire，单位秒。</summary>
        [Tooltip("连续 score_hold、score_reject 或 flag_hold 达到该时长后触发 reacquire，单位秒。")]
        [Min(0.1f)]
        [SerializeField] private float lowScoreSeconds = 0.8f;

        /// <summary>进入 Lost 后多久触发 reacquire，单位秒。</summary>
        [Tooltip("本地 anchor state 进入 Lost 后达到该时长触发 reacquire，单位秒。")]
        [Min(0.1f)]
        [SerializeField] private float lostSeconds = 0.2f;

        /// <summary>两次自动 reacquire 的最小间隔，单位秒。</summary>
        [Tooltip("两次自动 reacquire 的最小间隔，单位秒，避免低分期间重复刷命令。")]
        [Min(0.5f)]
        [SerializeField] private float cooldownSeconds = 3.0f;

        /// <summary>触发时是否先清空 Python tracking 状态。</summary>
        [Tooltip("触发 reacquire 时是否让 Python 先清空旧 tracking 状态。低分重定位建议开启。")]
        [SerializeField] private bool clearTrackingFirst = true;

        /// <summary>当前低分/保持累计起点。</summary>
        private double lowScoreStartSeconds = -1.0;

        /// <summary>Lost 状态累计起点。</summary>
        private double lostStartSeconds = -1.0;

        /// <summary>最近一次自动发命令时间。</summary>
        private double lastCommandSeconds = -999.0;

        /// <summary>当前是否已有自动命令在等待 ack。</summary>
        private bool commandInFlight;

        /// <summary>组件销毁取消源。</summary>
        private CancellationTokenSource destroyCts;

        private void Awake()
        {
            if (runtime == null)
            {
                runtime = GetComponent<PoseToAnchorRuntime>();
            }

            if (commandClient == null)
            {
                commandClient = GetComponent<AnchorCommandClient>();
            }

            destroyCts = new CancellationTokenSource();
        }

        private void Update()
        {
            if (!autoReacquire || runtime == null || commandClient == null)
            {
                return;
            }

            double now = Time.realtimeSinceStartupAsDouble;
            UpdateLowScoreTimer(now);
            UpdateLostTimer(now);

            bool shouldReacquire = IsTimerExpired(lowScoreStartSeconds, now, lowScoreSeconds)
                || IsTimerExpired(lostStartSeconds, now, lostSeconds);
            if (shouldReacquire && !commandInFlight && now - lastCommandSeconds >= cooldownSeconds)
            {
                _ = RequestReacquireAsync(now);
            }
        }

        private void UpdateLowScoreTimer(double now)
        {
            string reason = runtime.LatestPolicyReason ?? string.Empty;
            bool lowScore = reason == "score_hold" || reason == "score_reject" || reason == "flag_hold";
            if (lowScore)
            {
                if (lowScoreStartSeconds < 0.0)
                {
                    lowScoreStartSeconds = now;
                }
            }
            else
            {
                lowScoreStartSeconds = -1.0;
            }
        }

        private void UpdateLostTimer(double now)
        {
            if (runtime.CurrentAnchorState == Policy.AnchorState.Lost)
            {
                if (lostStartSeconds < 0.0)
                {
                    lostStartSeconds = now;
                }
            }
            else
            {
                lostStartSeconds = -1.0;
            }
        }

        private async System.Threading.Tasks.Task RequestReacquireAsync(double now)
        {
            commandInFlight = true;
            lastCommandSeconds = now;
            try
            {
                await commandClient.ReacquireAsync(
                    ReacquireAnchorRequest.Types.ReacquireMode.ForceDetect,
                    clearTrackingFirst,
                    string.Empty,
                    0.0,
                    "auto_reacquire_low_score_or_lost",
                    destroyCts.Token);
            }
            finally
            {
                commandInFlight = false;
            }
        }

        private static bool IsTimerExpired(double start, double now, float seconds)
        {
            return start >= 0.0 && now - start >= seconds;
        }

        private void OnDestroy()
        {
            destroyCts?.Cancel();
            destroyCts?.Dispose();
        }
    }
}
```

- [ ] **Step 2: Add smoke static checks**

In `Program.cs`, add a reflection smoke:

```csharp
private static void AssertAnchorRecoveryControllerExists()
{
    Type type = typeof(AnchorRecoveryController);
    Assert(type.GetMethod("Update", BindingFlags.Instance | BindingFlags.NonPublic) != null, "AnchorRecoveryController should tick in Update");
}
```

Call it near the existing runtime integration smoke checks.

- [ ] **Step 3: Add csproj include**

Add:

```xml
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Runtime\AnchorRecoveryController.cs" Link="Runtime\AnchorRecoveryController.cs" />
```

- [ ] **Step 4: Run smoke and build**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: PASS.

---

## Task 9: Update Documentation

**Files:**

- Modify: `ANCHOR_CONTROLLER_GUIDE.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update guide summary**

Replace the guide’s current “统一自适应控制器 / 6DoF Kalman / 马氏门控” description with:

```markdown
Unity 的 Policy 层现在是一个简单双模式 anchor 控制器：消息到达时只提交测量，渲染帧按 capture-time 时间轴输出连续 world pose。静止模式用测量窗口识别真实静止并锁定输出，运动模式用线速度/角速度预测和受限校正把约 5Hz pose 流扩展成连续运动；连续低分或 Lost 由独立 AnchorRecoveryController 请求 Python reacquire/register。
```

- [ ] **Step 2: Update parameter table**

Only document current config fields from Task 2. Remove teleport recovery、soft recovery、Mahalanobis、Kalman covariance references.

- [ ] **Step 3: Update AGENTS current-mainline facts**

In `AGENTS.md`, outside `USER-MAINTAINED-REQUIREMENTS`, update the Unity `Policy/` bullets to state:

- `PolicyController` = static lock + moving kinematic prediction + score hold;
- `AnchorRecoveryController` = auto reacquire bridge;
- no Mahalanobis gate, no teleport recovery, no 6DoF Kalman claim.

- [ ] **Step 4: Verify no stale terms remain**

Run:

```powershell
rg "马氏|Mahalanobis|teleport_recovery|softRecovery|soft recovery|6DoF Kalman|AnchorMeasurementGate|AnchorOutputSmoother" ANCHOR_CONTROLLER_GUIDE.md AGENTS.md EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy
```

Expected: no stale references, except acceptable historical comments if deliberately retained in a “removed” context. Prefer no output.

---

## Task 10: Full Verification

**Files:**

- No additional edits unless verification exposes failures.

- [ ] **Step 1: Run anchor policy smoke**

Run:

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected: `Anchor policy smoke passed.`

- [ ] **Step 2: Run Unity build**

Run:

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: build succeeds. Existing warnings from third-party plugins / Net Samples may remain; no new EgoAnchor policy/runtime errors.

- [ ] **Step 3: Run Python eval tests**

Run in `EgoAnchor_Python`:

```powershell
pixi run python -m unittest discover -s eval -p "test_*.py"
```

Expected: all eval tests pass. This ensures output schema changes did not break loaders.

- [ ] **Step 4: Run read-only current session metric check**

Run in `EgoAnchor_Python`:

```powershell
pixi run python -c "from pathlib import Path; from eval.io import load_session; from eval.metrics import compute_all_metrics; logs=load_session(Path('data/eval/20260613_012345_controller_right')); result=compute_all_metrics(logs); print(result.tables['anchor_error_summary'].to_string(index=False)); print(result.tables['policy_distribution'].to_string(index=False))"
```

Expected: command runs without schema errors. It still evaluates old recorded data, so it is not expected to prove new runtime behavior.

- [ ] **Step 5: Report simplification metrics**

Use:

```powershell
@'
from pathlib import Path
files = [
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyConfig.cs',
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs',
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPoseFilter.cs',
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/MotionStateClassifier.cs',
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs',
    'EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs',
]
for f in files:
    p = Path(f)
    if p.exists():
        print(f, len(p.read_text(encoding='utf-8').splitlines()))
'@ | python -
```

Expected: policy core line count is materially lower than the pre-refactor baseline:

- `AnchorPolicyConfig.cs`: 251 lines before.
- `PolicyController.cs`: 496 lines before.
- `AnchorPoseFilter.cs`: 659 lines before.
- `AnchorMeasurementGate.cs`: 533 lines before, deleted.
- `AnchorOutputSmoother.cs`: 234 lines before, deleted.
- `MotionStateClassifier.cs`: 272 lines before.

---

## Self-Review

- Spec coverage: covers static stability, moving continuity, low score hold, no-pose/lost degradation, automatic reacquire, frame alignment boundary, baseline preservation, docs, and verification.
- Placeholder scan: no unresolved placeholder markers or unspecified file paths.
- Type consistency: uses existing public DTOs (`AnchorObservation`, `AnchorPolicyDecision`, `AnchorPolicyOutput`, `AnchorState`, `AnchorMotionState`) and adds only `AnchorRecoveryController`; updates host/runtime diagnostics consistently.
- Risk: Unity scene wiring for `AnchorRecoveryController` is not edited in this plan because current scene files already have user changes. After code lands, bind it explicitly in Unity Inspector or make a separate scene-only change after reviewing current dirty scene diffs.
