# Anchor Policy 重构方案（One-Euro 融合版）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> 本方案融合两版计划：算法内核取 **One-Euro 自适应滤波**（删除离散 Static/Moving 双模式），工程流程取 **复用现有 1417 行 smoke + TDD + headless build + Python eval 框架**，自动重注册取 **独立 MonoBehaviour 结构** 但触发条件仅"持续低分"（用户决定）。取代 `2026-06-13-anchor-policy-simplification.md`。

**Goal:** 将 Unity anchor policy 从 8 类 / 40+ 参数的 reliability-aware 6DoF Kalman + 马氏门控 + 多套恢复机制，重构为 **One-Euro 自适应平滑 + 有界前推预测 + 持续低分自动重注册** 的精简控制器（~3 核心类 / ~13 参数），同时不退化静止稳定性、改善运动跟手、保留 baseline 对照与 eval 管线。

**Architecture:** Python 仍只输出低频（实测 5.24Hz）camera-space `PoseResult` + 质量评分；Unity 仍由 `PoseToAnchorRuntime` 做 frame-aligned world pose。`PolicyController` 公开入口保持 `AcceptPose` / `Advance` / `Notify*` 不变；内部由 `AnchorTracker`（异常剔除 + One-Euro 平滑 + 速度估计 + 有界前推）和 `AnchorLifecycle`（4 态生命周期 + 持续低分回调）组成。自动 reacquire 放在独立 `AnchorRecoveryController` MonoBehaviour，不写进 transport/receiver/Transform 层。

**Tech Stack:** Unity C#、Google.Protobuf、NATS command API、现有 `EgoAnchor_Tools/anchor_policy_smoke` 离线 smoke（1417 行，真实存在，compile-include 全部 policy 文件）、`dotnet build EgoAnchor_Unity/Assembly-CSharp.csproj` 编译验证、`EgoAnchor_Python/eval` JSONL 离线评估（产出 `anchor_error_summary` / `policy_distribution` 表）。

---

## Evidence From Current Project（已用真机数据量化）

数据源：`EgoAnchor_Python/data/eval/20260613_012345_controller_right`（unity_output 3182 行 / 47.5s，含 GT、raw aligned、kalman 三路）。

- **Pose 率 5.24Hz**，渲染率 66.9fps —— 必须把低频摊到高帧率。
- **score 中位 0.92、均值 0.90，<0.35 仅 0.3%** —— 分数门控/滞回基本空转。
- **policy_action：Accept 99.7% / Hold 0.3% / Reject 0%** —— 3 套恢复机制（teleport/soft/stuck）本 session 零触发，是死代码。
- **静止抖动：kalman 0.147mm/帧 ≈ raw 0.157mm**（GT 自身 0.75mm）—— 静止已基本达标，重点是别再加复杂度。
- **运动误差：kalman = raw 的 1.06x** —— 当前滤波运动时帮倒忙。
- **端到端延迟 268ms，仅前推补偿 ~150ms**，剩 **~156ms 未补偿** —— 这是"不跟手"主因（5Hz 物理延迟，Unity 端只能部分补偿，根治在 Python 端降延迟，超出本次范围）。
- **motion_state 翻转 1.56 次/秒** —— 离散 Static/Moving 双模式是静止晃动隐患来源，必须消除。

结论：复杂度大多空转，调参却因 40 个耦合参数变成灾难。One-Euro 用单个连续公式 `cutoff = minCutoff + beta·|速度|` 同时满足"静止稳"和"运动跟手"，无需离散态、无需静止锁。

## Target Behavior

1. 物体静止时 anchor world pose 稳定，不跟随头显轻微晃动造成的小 residual slip；**消除 Static/Moving 翻转带来的锁定/释放跳变**。
2. 物体连续移动时 anchor pose 在 render frame 上连续变化，平移和旋转都不阶梯、不断续；通过 One-Euro 速度自适应 + **平衡前推（~120-150ms）** 改善跟手。
3. 低分 pose 不拖动 anchor；**连续低分超过设定时长**后自动请求 Python reacquire/register（带冷却防刷屏）。
4. 不改 Python pose 语义、不改 protocol、不改 frame alignment，**不使用 pose 到达时 HMD pose 替代 capture-time frame pose**（沿用现有异步时间轴对齐）。
5. raw / processor baseline 继续保留；policy runtime 继续不经过 processor 链；eval schema `variants:["kalman","raw"]` 不变。

## 设计决策（已锁定）

- 核心滤波：**One-Euro 自适应低通**（位置 3 轴 + 旋转角度）。
- 前推激进度：**平衡档**，`maxPredictAheadSeconds ≈ 0.13`，可 Inspector 调。
- 自动重注册触发：**仅持续低分**。Lost/断线自动重连**关闭**，留 `enableLostAutoReacquire` 开关 + TODO（彻底无消息通常是更深故障，应暴露而非静默重试）。
- 接口冻结：`AcceptPose`/`Advance`/`Notify*` 签名、`AnchorPolicyOutput`/`AnchorPolicyDecision`/`AnchorState`/`AnchorMotionState` 类型、`PoseResultPolicyMapper`、eval JSONL schema 全部不变。`AnchorMotionState` 字段保留，由 One-Euro 速度阈值做**纯显示映射**，不驱动任何分支。

## File Structure

### Modify
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyConfig.cs` —— 40+ 参数精简到 ~13（见 Task 2）。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs` —— 保留公开 API，内部编排 `AnchorTracker` + `AnchorLifecycle`（496 → ~140 行）。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs` —— 诊断属性名调整（残差/score 取代 innovation/REff）。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs` —— 只更新 policy 诊断字段，不改 frame alignment / baseline / status 逻辑。
- `EgoAnchor_Tools/anchor_policy_smoke/Program.cs` —— 改写 policy 场景断言为 One-Euro 目标行为门，删除旧 Mahalanobis/teleport/soft recovery/static-lock 专属断言。
- `EgoAnchor_Tools/anchor_policy_smoke/AnchorPolicySmoke.csproj` —— 更新 compile include（删除 5 个旧文件，加入 2 个新文件 + AnchorRecoveryController）。
- `ANCHOR_CONTROLLER_GUIDE.md` —— 同步新控制器与参数。
- `AGENTS.md` —— 只更新用户维护区块之外的主线事实；**不得修改 `USER-MAINTAINED-REQUIREMENTS`**。

### Create
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorTracker.cs`（+ `.meta`）—— One-Euro 平滑器 + 异常剔除 + 速度估计 + 有界前推。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorLifecycle.cs`（+ `.meta`）—— 4 态生命周期 + 持续低分 `OnNeedReacquire` 回调；并入旧 `AnchorStateMachine` 职责。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs`（+ `.meta`）—— 独立 MonoBehaviour，观察 runtime 持续低分后触发 `AnchorCommandClient.ReacquireAsync`。
- `EgoAnchor_Python/eval/tools/replay_oneeuro.py` —— 真机回放对照脚本（喂历史 aligned pose 进 One-Euro Python 复现，对比新/旧 kalman/raw vs GT）。

### Delete（+ 对应 `.meta`）
- `Policy/AnchorMeasurementGate.cs` —— 马氏门 + 3 套恢复，零触发。
- `Policy/AnchorPoseFilter.cs` —— KF/ZUPT/冻结封账，被 One-Euro 取代。
- `Policy/MotionStateClassifier.cs` —— Static/Moving 翻转根源，One-Euro 不需要离散态。
- `Policy/AnchorOutputSmoother.cs` —— 静止锁/归中，One-Euro 不需要。
- `Policy/AnchorStateMachine.cs` —— 9 态机，逻辑并入 `AnchorLifecycle`。

---

## Task 1: 用 One-Euro 目标行为门替换 policy smoke 断言

**Files:** Modify `EgoAnchor_Tools/anchor_policy_smoke/Program.cs`

> 复用现有 smoke 的 `Main()`、`Assert`、`MakeTrackObservation(frameId, pose, sampleTime, score, captureTime=NaN)`、`MakeNoisyPose(truth, posSigma, rotSigmaDeg, ref rng)`、`Rms`、`Lcg`、`YawDegrees`、`QuaternionAngleDegrees`、`const double FrameDt = 1.0/90.0` 等既有辅助。保留所有非 policy 集成断言（frame-align 数学、heartbeat/status 判定、Hub/NATS/队列、`AssertPolicyPathSkipsProcessors` 等）。

- [ ] **Step 1: 替换 `Main()` 顶部 policy 场景调用**

将 `Main()` 第 26-48 行的「统一自适应控制器场景断言」块替换为：

```csharp
// ===== One-Euro anchor 控制器场景断言 =====
AssertFirstPoseSnaps();
AssertStaticJitterSuppression();            // 保留：静止抖动 PRIMARY 闸门
AssertStaticDoesNotFollowHeadSlip();        // 新：头动残差不拖动静止 anchor
AssertLowRateMotionIsContinuous();          // 改：5Hz 下运动逐帧连续、无长静止段
AssertLowRateRotationIsContinuous();        // 新：旋转同样连续
AssertMotionTracksWithBoundedPredict();     // 新：运动跟手且前推有界、不过冲发散
AssertLowScoreDoesNotDrag();                // 保留：低分不拖动
AssertOutlierJumpRejected();                // 改：单一绝对跳变门剔除外点
AssertCoastWithoutMessages();               // 保留：断流外推退化
AssertRelocalizeSnap();                     // 保留：重定位贴合
AssertStaleMeasurementIgnored();            // 保留：乱序/超龄丢弃
AssertConfigHotReload();                    // 保留：热更不清状态
AssertLowScoreReacquireSignal();            // 新：持续低分触发 OnNeedReacquire 回调
AssertNotifyChain();                        // 保留：Notify* 链
```

删除以下旧场景调用（连同其方法定义）：

```csharp
AssertStaticClassifierUsesWindowDispersion();
AssertStaticOutputLockSuppressesSmallSlip();
AssertMovingOutputDoesNotLockBeforeClassifierStatic();
AssertMovingResponseAndPerFrameOutput();
AssertLowRateMotionIsInterpolated();
AssertScoreHysteresis();
AssertLowScoreTrackPoseFailsSoftWhenPlausible();
AssertLowScoreTrackMotionExitsStatic();
AssertLowScoreTrackJumpStillRejected();
AssertTeleportRecovery();
AssertRotationJumpRecoversSoftly();
AssertStaticRotationStartsMoving();
AssertMediumTranslationRecoversSoftly();
AssertRotationFilterGates();
```

- [ ] **Step 2: 静止抖动 + 头动残差门**

`AssertStaticJitterSuppression` 保留语义但用 One-Euro 阈值；新增 `AssertStaticDoesNotFollowHeadSlip`：

```csharp
/// <summary>静止物体 + 测量噪声下，One-Euro 输出抖动必须显著低于输入（不退化于旧 kalman）。</summary>
private static void AssertStaticJitterSuppression()
{
    PolicyController controller = new PolicyController();
    Pose truth = new Pose(new Vector3(0.3f, -0.2f, 1.0f), YawDegrees(30f));
    Lcg rng = new Lcg(20260613);
    List<float> inErr = new List<float>();
    List<float> outErr = new List<float>();
    const int warmup = 35;
    for (int i = 0; i < 80; i++)
    {
        double t = i * 0.20;
        Pose measured = MakeNoisyPose(truth, 0.003f, 0.45f, ref rng);
        controller.AcceptPose(MakeTrackObservation(i + 1, measured, t, 0.9f, t));
        for (double ta = t + FrameDt; ta < t + 0.20; ta += FrameDt)
        {
            AnchorPolicyOutput o = controller.Advance(ta);
            if (i >= warmup)
            {
                inErr.Add(Vector3.Distance(measured.position, truth.position));
                outErr.Add(Vector3.Distance(o.Pose.position, truth.position));
            }
        }
    }
    Assert(Rms(outErr) < Rms(inErr) * 0.5f, "static One-Euro output should suppress most measurement jitter");
}
```

```csharp
/// <summary>静止后注入持续小幅头动残差（< 跳变门），输出不得显著漂移。</summary>
private static void AssertStaticDoesNotFollowHeadSlip()
{
    PolicyController controller = new PolicyController();
    Pose truth = new Pose(new Vector3(0.2f, 0f, 1f), Quaternion.identity);
    for (int i = 0; i < 60; i++)
    {
        double t = i * 0.20;
        controller.AcceptPose(MakeTrackObservation(i + 1, truth, t, 0.9f, t));
        controller.Advance(t + 0.05);
    }
    Pose locked = controller.Advance(60 * 0.20).Pose;
    Lcg rng = new Lcg(7);
    for (int i = 60; i < 90; i++)
    {
        double t = i * 0.20;
        Pose slip = MakeNoisyPose(truth, 0.004f, 0.3f, ref rng); // residual head slip
        controller.AcceptPose(MakeTrackObservation(i + 1, slip, t, 0.9f, t));
        controller.Advance(t + 0.05);
    }
    Pose after = controller.Advance(90 * 0.20).Pose;
    Assert(Vector3.Distance(locked.position, after.position) < 0.01f, "static anchor should not drift under residual head slip");
}
```

- [ ] **Step 3: 低频运动连续性门（位置 + 旋转）**

```csharp
/// <summary>5Hz pose 流 + 延迟下，运动输出应在 source frame 之间逐帧连续，无长静止段。</summary>
private static void AssertLowRateMotionIsContinuous()
{
    PolicyController controller = new PolicyController();
    Vector3 start = new Vector3(0f, 0f, 1f);
    Vector3 vel = new Vector3(0.35f, 0f, 0f);
    const double msgDt = 0.20, latency = 0.18;
    int movingSteps = 0, zeroRun = 0, maxZeroRun = 0;
    Pose prev = Pose.identity; bool hasPrev = false;
    for (int k = 0; k < 35; k++)
    {
        double capture = k * msgDt, arrival = capture + latency;
        Pose measured = new Pose(start + vel * (float)capture, Quaternion.identity);
        controller.AcceptPose(MakeTrackObservation(k + 1, measured, arrival, 0.9f, capture));
        for (double ta = arrival + FrameDt; ta < arrival + msgDt; ta += FrameDt)
        {
            AnchorPolicyOutput o = controller.Advance(ta);
            if (hasPrev)
            {
                float step = Vector3.Distance(o.Pose.position, prev.position);
                if (step <= 1e-5f) zeroRun++;
                else { movingSteps++; maxZeroRun = Math.Max(maxZeroRun, zeroRun); zeroRun = 0; }
            }
            prev = o.Pose; hasPrev = true;
        }
    }
    maxZeroRun = Math.Max(maxZeroRun, zeroRun);
    Assert(movingSteps > 80, "low-rate motion should produce many render-frame movement steps");
    Assert(maxZeroRun <= 4, $"low-rate motion should not have long still runs, got {maxZeroRun}");
}
```

`AssertLowRateRotationIsContinuous` 同构，用 `YawDegrees` 线性增角的测量序列，断言旋转步进连续（`QuaternionAngleDegrees(prev, cur) > 0` 的帧数占多数、无长零段）。

- [ ] **Step 4: 跟手 + 前推有界门**

```csharp
/// <summary>匀速运动下，前推后的输出误差应小于"无前推零阶保持"的误差，且前推时长不超过配置上限、不发散。</summary>
private static void AssertMotionTracksWithBoundedPredict()
{
    PolicyController controller = new PolicyController();
    Vector3 start = new Vector3(0f, 0f, 1f);
    Vector3 vel = new Vector3(0.4f, 0f, 0f);
    const double msgDt = 0.20, latency = 0.18;
    List<float> predErr = new List<float>();
    List<float> holdErr = new List<float>();
    for (int k = 0; k < 30; k++)
    {
        double capture = k * msgDt, arrival = capture + latency;
        Pose measured = new Pose(start + vel * (float)capture, Quaternion.identity);
        controller.AcceptPose(MakeTrackObservation(k + 1, measured, arrival, 0.9f, capture));
        double tRender = arrival + 0.05;
        AnchorPolicyOutput o = controller.Advance(tRender);
        Vector3 gtNow = start + vel * (float)tRender;        // 真值在渲染时刻的位置
        Vector3 lastMeasured = measured.position;            // 零阶保持基线
        if (k >= 10)
        {
            predErr.Add(Vector3.Distance(o.Pose.position, gtNow));
            holdErr.Add(Vector3.Distance(lastMeasured, gtNow));
            Assert(o.PredictAheadSeconds <= 0.2f + 1e-3f, "predict-ahead must stay bounded");
        }
    }
    Assert(Rms(predErr) < Rms(holdErr), "bounded predict should beat zero-order hold during steady motion");
}
```

- [ ] **Step 5: 外点剔除 + 低分不拖动 + 持续低分信号**

```csharp
/// <summary>单帧超过绝对跳变门的高分外点应被拒绝，输出不跟随。</summary>
private static void AssertOutlierJumpRejected()
{
    PolicyController controller = new PolicyController();
    Pose basePose = new Pose(new Vector3(0.2f, 0f, 1f), Quaternion.identity);
    controller.AcceptPose(MakeTrackObservation(1, basePose, 0.0, 0.9f, 0.0));
    Pose before = controller.Advance(0.05).Pose;
    Pose outlier = new Pose(basePose.position + new Vector3(1.2f, 0f, 0f), Quaternion.identity); // > maxJumpMeters
    AnchorPolicyDecision d = controller.AcceptPose(MakeTrackObservation(2, outlier, 0.20, 0.9f, 0.20));
    Pose after = controller.Advance(0.25).Pose;
    Assert(d.Action == AnchorPolicyAction.Reject, "absolute jump outlier should be rejected");
    Assert(Vector3.Distance(before.position, after.position) < 0.05f, "rejected outlier should not drag output");
}
```

`AssertLowScoreDoesNotDrag` 保留（低分 → Hold/Reject，输出位置/旋转不被拖动）。

```csharp
/// <summary>连续低分超过 lowScoreReacquireSeconds 应触发 OnNeedReacquire 回调一次（受冷却约束）。</summary>
private static void AssertLowScoreReacquireSignal()
{
    AnchorPolicyConfig cfg = new AnchorPolicyConfig { lowScoreThreshold = 0.25f, lowScoreReacquireSeconds = 0.8f, reacquireCooldownSeconds = 3f };
    PolicyController controller = new PolicyController(cfg);
    int fired = 0;
    controller.OnNeedReacquire += _ => fired++;
    controller.AcceptPose(MakeTrackObservation(1, new Pose(Vector3.forward, Quaternion.identity), 0.0, 0.9f, 0.0));
    for (int i = 1; i <= 12; i++)
    {
        double t = i * 0.20;
        controller.AcceptPose(MakeTrackObservation(i + 1, new Pose(Vector3.forward, Quaternion.identity), t, 0.05f, t));
        controller.Advance(t);
    }
    Assert(fired >= 1, "sustained low score should raise reacquire signal");
    Assert(fired <= 2, "cooldown should prevent reacquire spam");
}
```

- [ ] **Step 6: 运行 smoke 确认实现前失败**

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected: FAIL —— 旧 `PolicyController` 没有 `OnNeedReacquire`、新断言引用未实现的 One-Euro 语义，编译/断言失败。

---

## Task 2: 精简 AnchorPolicyConfig

**Files:** Modify `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyConfig.cs`

- [ ] **Step 1: 替换字段为 ~13 参数**

```csharp
[Serializable]
public sealed class AnchorPolicyConfig
{
    [Header("One-Euro 平滑")]
    [Tooltip("位置最小截止频率 Hz：越小静止越稳、运动越滞后。")]
    [Min(0.01f)] public float positionMinCutoff = 1.0f;
    [Tooltip("位置速度系数 beta：越大运动越跟手、抖动越多。")]
    [Min(0f)] public float positionBeta = 0.5f;
    [Tooltip("旋转最小截止频率 Hz。")]
    [Min(0.01f)] public float rotationMinCutoff = 1.0f;
    [Tooltip("旋转速度系数 beta。")]
    [Min(0f)] public float rotationBeta = 0.5f;
    [Tooltip("速度估计的导数低通截止频率 Hz（One-Euro dcutoff）。")]
    [Min(0.01f)] public float derivativeCutoff = 1.0f;

    [Header("前推预测（延迟补偿）")]
    [Tooltip("位置前推到渲染时刻的最大时长，单位秒。平衡档约 0.13；越大越跟手但转向越易过冲。")]
    [Min(0f)] public float maxPredictAheadSeconds = 0.13f;
    [Tooltip("旋转前推最大时长，单位秒。旋转外推风险更高，默认短于位置。")]
    [Min(0f)] public float maxRotationPredictAheadSeconds = 0.07f;

    [Header("异常剔除")]
    [Tooltip("单帧测量相对当前平滑态的位置跳变上限，单位米。超过直接拒绝。")]
    [Min(0.01f)] public float maxJumpMeters = 0.8f;
    [Tooltip("单帧测量相对当前平滑态的旋转跳变上限，单位度。超过直接拒绝。")]
    [Min(1f)] public float maxJumpDegrees = 90f;

    [Header("评分与重注册")]
    [Tooltip("冷启动/重定位接受第一帧的最低分；普通帧低于该值不更新平滑器。")]
    [Range(0f, 1f)] public float acceptScoreMin = 0.3f;
    [Tooltip("REGISTER/RE_REGISTER pose 的接受下限。")]
    [Range(0f, 1f)] public float relocalizeScoreMin = 0.12f;
    [Tooltip("低于该分判为低分；持续低分会触发自动重注册。")]
    [Range(0f, 1f)] public float lowScoreThreshold = 0.25f;
    [Tooltip("连续低分累计多久触发 OnNeedReacquire，单位秒。")]
    [Min(0.1f)] public float lowScoreReacquireSeconds = 0.8f;
    [Tooltip("两次自动重注册的最小间隔，单位秒，防刷屏。")]
    [Min(0.5f)] public float reacquireCooldownSeconds = 3.0f;

    [Header("时序与续航")]
    [Tooltip("正常 pose 间隔保护时间，单位秒；5Hz 流建议 ≥ 0.25s。超过进入 Coasting。")]
    [Min(0.02f)] public float coastSeconds = 0.4f;
    [Tooltip("连续无可靠 pose 超过该时长进入 Lost，单位秒。")]
    [Min(0.2f)] public float lostSeconds = 2.0f;
    [Tooltip("测量采集时间相对到达时间允许的最大年龄，单位秒。")]
    [Min(0.1f)] public float maxMeasurementAgeSeconds = 1.0f;
    [Tooltip("速度模长低于该值（米/秒）时显示为 Static，仅用于诊断映射，不驱动逻辑。")]
    [Min(0.0001f)] public float staticDisplaySpeedMps = 0.02f;

    [Header("自动重连开关")]
    [Tooltip("进入 Lost 是否也自动重注册。默认关闭：彻底无消息通常是更深故障，应暴露而非静默重试。")]
    public bool enableLostAutoReacquire = false; // TODO: 如需开启 Lost 自动重连，将此置 true 并在 AnchorRecoveryController 接线 Lost 计时。

    public void Validate()
    {
        positionMinCutoff = Mathf.Max(positionMinCutoff, 0.01f);
        rotationMinCutoff = Mathf.Max(rotationMinCutoff, 0.01f);
        derivativeCutoff = Mathf.Max(derivativeCutoff, 0.01f);
        maxRotationPredictAheadSeconds = Mathf.Clamp(maxRotationPredictAheadSeconds, 0f, maxPredictAheadSeconds);
        acceptScoreMin = Mathf.Clamp01(acceptScoreMin);
        relocalizeScoreMin = Mathf.Clamp01(relocalizeScoreMin);
        lowScoreThreshold = Mathf.Clamp(lowScoreThreshold, 0f, acceptScoreMin);
        lostSeconds = Mathf.Max(lostSeconds, coastSeconds);
    }
}
```

- [ ] **Step 2: 运行 build 暴露编译错误**

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: FAIL —— 旧 policy 类仍引用被删字段。

---

## Task 3: 新建 AnchorTracker（One-Euro 内核）

**Files:** Create `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorTracker.cs`（纯 C#，不依赖 Unity 生命周期/Time，可被 smoke 离线驱动）

- [ ] **Step 1: 状态与接口**

```csharp
private AnchorPolicyConfig config;
private OneEuro1D x, y, z;            // 位置三轴 One-Euro（含速度估计）
private Quaternion orientation;       // 平滑后朝向
private Vector3 angularVelocityRad;   // 估计角速度
private double stateTimeSeconds;      // 平滑态对应 capture 时刻
private bool hasState;

public bool HasState => hasState;
public double StateTimeSeconds => stateTimeSeconds;
public Vector3 Position { get; }      // 当前平滑位置
public Quaternion Orientation => orientation;
public Vector3 Velocity { get; }      // x/y/z One-Euro 平滑导数组成
public float SpeedMps => Velocity.magnitude;
public float AngularSpeedDps => angularVelocityRad.magnitude * Mathf.Rad2Deg;
public float LastResidualMeters { get; private set; }
public float LastResidualDegrees { get; private set; }

public void ApplyConfig(AnchorPolicyConfig c);   // 热更，不清状态
public void Reset();                              // 清空全部状态
public void Snap(Pose pose, double t);            // 首测量/重定位/外点恢复：直接置位，速度清零
public bool IsOutlier(Pose measured);             // 相对当前平滑态超过 maxJumpMeters/Degrees
public void Correct(Pose measured, double t);     // One-Euro 融合一帧测量；更新残差与速度
public Pose PredictAt(double nowSeconds);         // 有界前推到渲染时刻（只读，不提交）
```

- [ ] **Step 2: One-Euro 核心**

```csharp
// alpha = 1 / (1 + tau/dt), tau = 1/(2π·cutoff)
private static float Alpha(float cutoff, float dt)
{
    float tau = 1f / (2f * Mathf.PI * Mathf.Max(cutoff, 1e-4f));
    return 1f / (1f + tau / Mathf.Max(dt, 1e-4f));
}
// 每轴：先平滑导数得速度，再用速度自适应 cutoff 平滑位置
//   dxHat += Alpha(derivativeCutoff, dt) * ((x - xPrev)/dt - dxHat)
//   cutoff = minCutoff + beta * |dxHat|
//   xHat   += Alpha(cutoff, dt) * (x - xHat)
```

`OneEuro1D` 为内嵌 struct，持有 `xHat, dxHat, xPrev, hasPrev`，提供 `Filter(x, dt, minCutoff, beta, dCutoff)`、`SnapTo(x)`、`Value`、`Velocity`。

- [ ] **Step 3: 旋转 One-Euro**

旋转用最短弧误差角做标量 One-Euro：测量与当前 `orientation` 的 `QuaternionLog(conj(orientation)·measured)` 得误差向量 `θ`（rad），角速率 `|θ|/dt` 经导数低通 → 自适应 cutoff → 对 `θ` 取 alpha 比例，沿测地线 `orientation = orientation · Exp(alpha·θ)`。`angularVelocityRad` 取平滑后的 `alpha·θ/dt`。复用旧 `AnchorPoseFilter` 已验证的 `QuaternionExp/Log/Multiply/Conjugate/Normalize/AlignSign` 纯 C# 实现（迁移过来，删除 Kalman 部分）。

- [ ] **Step 4: 有界前推**

```csharp
// 位置：Position + Velocity * min(now - stateTime, maxPredictAheadSeconds)
// 旋转：orientation · Exp(angularVelocityRad * min(now - stateTime, maxRotationPredictAheadSeconds))
// PredictAheadSeconds 实际用量由 PolicyController 读取写入 AnchorPolicyOutput
```

- [ ] **Step 5: 编译**

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Expected: 仍 FAIL（PolicyController 未改），但 AnchorTracker 自身无语法错误。

---

## Task 4: 新建 AnchorLifecycle（4 态 + 重注册回调）

**Files:** Create `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorLifecycle.cs`

- [ ] **Step 1: 状态与转移**

并入旧 `AnchorStateMachine` 职责，但状态收敛为核心 4 态 + 外部命令态：

```csharp
// 复用既有 AnchorState enum（不改）：核心路径只用 Searching/Tracking/Coasting/Lost；
// Paused/Error/Relocalizing 保留为外部命令入口（Python status 驱动）。
public AnchorState State { get; }
public AnchorLifecycleEvent LastEvent { get; }   // 复用既有类型

public AnchorState OnReliablePose(double t, string reason);   // → Tracking, 刷新 lastPoseTime
public AnchorState OnGap(double now, double gap, string reason); // gap>coast→Coasting; gap>lost→Lost
public AnchorState OnUncertain(double t, string reason);      // 低分/无 pose
public AnchorState OnReset/OnReacquire/OnPause/OnResume/OnError/Clear(...); // 同旧语义
```

- [ ] **Step 2: 持续低分计时 + 回调**

```csharp
public event Action<string> OnNeedReacquire;   // 由 PolicyController 透传

// 内部：score<lowScoreThreshold 连续累计 ≥ lowScoreReacquireSeconds
//        且 now - lastReacquireTime ≥ reacquireCooldownSeconds
//        → OnNeedReacquire?.Invoke(reason); 重置计时器与冷却
// （Lost 触发仅在 enableLostAutoReacquire 时启用，本版默认关闭）
public void ObserveScore(float score, double now);
```

- [ ] **Step 3: 编译** —— 同 Task 3，预期 PolicyController 未改仍 FAIL。

---

## Task 5: 改写 PolicyController 编排 Tracker + Lifecycle

**Files:** Modify `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs`

- [ ] **Step 1: 字段收敛**

```csharp
private AnchorPolicyConfig config;
private readonly AnchorTracker tracker;
private AnchorLifecycle lifecycle;
private double lastAcceptSampleTime = -1.0;
private double lastMeasurementCaptureTime = -1.0;
private float lastPredictAheadSeconds;
private long acceptedCount, rejectedCount;

public event Action<string> OnNeedReacquire;   // 透传 lifecycle.OnNeedReacquire
public float LastResidualMeters => tracker.LastResidualMeters;
public float LastResidualDegrees => tracker.LastResidualDegrees;
public float SpeedMps => tracker.SpeedMps;
public float AngularSpeedDps => tracker.AngularSpeedDps;
public float PredictAheadSeconds => lastPredictAheadSeconds;
// 保留 State / MotionState / AcceptedCount / RejectedCount / ApplyConfig
```

`MotionState` 由 `tracker.SpeedMps < config.staticDisplaySpeedMps ? Static : Moving` 纯映射。

- [ ] **Step 2: `AcceptPose` 流程**

1. Paused → `Hold/paused`。
2. `!HasAlignedPose` → `HandleMissing`（驱动 lifecycle gap，不动 tracker）。
3. 超龄/乱序（capture ≤ lastCaptureTime）→ `Reject/stale_measurement`。
4. 硬 flag（`no_pose`/`invalid_pose`，复用旧 `HasHardRejectFlag` 逻辑迁移为静态辅助）→ `Hold/flag_hold`。
5. 重定位且 score ≥ `relocalizeScoreMin` → `tracker.Snap`，`Snap/relocalize_accept`。
6. 无 tracker 状态：score ≥ `acceptScoreMin` → `Snap/first_accept`；否则 `Reject/score_reject`。
7. 有状态且 score < `lowScoreThreshold` → `lifecycle.ObserveScore`，`Hold/score_hold`（不更新 tracker，不拖动）。
8. 有状态且 `tracker.IsOutlier(measured)` → `Reject/outlier_jump`。
9. 否则 `tracker.Correct(measured, captureTime)`，`lifecycle.OnReliablePose`，`Accept/score_accept`；刷新 `lastAcceptSampleTime/lastMeasurementCaptureTime`，`lifecycle.ObserveScore(score, now)` 清低分计时。

决策 reason 限定集合：`first_accept / score_accept / motion_start / score_hold / flag_hold / outlier_jump / stale_measurement / relocalize_accept / no_pose / align_failed`。

- [ ] **Step 3: `Advance` 流程**

```csharp
// 无 tracker 状态 → AnchorPolicyOutput.None
// gap = now - lastAcceptSampleTime
// gap <= coastSeconds       → state = lifecycle.State (Tracking), 正常前推
// gap <= lostSeconds        → lifecycle.OnGap → Coasting, 前推（速度随 One-Euro 自然衰减或按 gap 截断）
// gap >  lostSeconds        → lifecycle.OnGap → Lost, 冻结保持（前推置 0）
// pose = tracker.PredictAt(now); lastPredictAheadSeconds = min(now-stateTime, maxPredictAhead)
// 返回 AnchorPolicyOutput(true, pose, state, MotionState, lastPredictAheadSeconds, reason)
```

- [ ] **Step 4: 保留 Notify* + 构造透传回调**

构造函数中 `lifecycle.OnNeedReacquire += r => OnNeedReacquire?.Invoke(r);`。`NotifyReset/Reacquire/Pause/Resume/Error/Lost/Clear` 保持公开签名，内部 reset tracker + 驱动 lifecycle，与现状语义一致。

- [ ] **Step 5: 运行 smoke 调默认参数**

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```

Expected: 编译通过，仅行为阈值可能未过。在 `AnchorPolicyConfig` 默认值内调 `positionMinCutoff/positionBeta/maxPredictAheadSeconds` 直到目标门全绿。

---

## Task 6: 删除废弃文件并更新 smoke 工程

**Files:** Delete 5 个 `.cs` + `.meta`；Modify `AnchorPolicySmoke.csproj`

- [ ] **Step 1: 删除**
`AnchorMeasurementGate.cs(.meta)`、`AnchorPoseFilter.cs(.meta)`、`MotionStateClassifier.cs(.meta)`、`AnchorOutputSmoother.cs(.meta)`、`AnchorStateMachine.cs(.meta)`。

- [ ] **Step 2: 更新 csproj compile include**

移除：
```xml
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorStateMachine.cs" Link="Policy\AnchorStateMachine.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorPoseFilter.cs" Link="Policy\AnchorPoseFilter.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorOutputSmoother.cs" Link="Policy\AnchorOutputSmoother.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorMeasurementGate.cs" Link="Policy\AnchorMeasurementGate.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\MotionStateClassifier.cs" Link="Policy\MotionStateClassifier.cs" />
```
加入：
```xml
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorTracker.cs" Link="Policy\AnchorTracker.cs" />
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy\AnchorLifecycle.cs" Link="Policy\AnchorLifecycle.cs" />
```
（`AnchorLifecycleEvent.cs` 保留，仍被 include。）

- [ ] **Step 3: smoke + build**

```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```
Expected: smoke PASS，build PASS（第三方/Sample 既有 warning 可保留，无新 EgoAnchor policy/runtime error）。

---

## Task 7: 更新 Runtime / Host 诊断字段

**Files:** Modify `PoseToAnchorRuntime.cs`、`AnchorPolicyHost.cs`

- [ ] **Step 1: Host 属性**

删除 `LastInnovationPosD2 / LastREffPos`，新增：
```csharp
/// <summary>最近一次 accepted 测量的位置残差，单位米。</summary>
public float LastResidualMeters => Controller.LastResidualMeters;
/// <summary>最近一次 accepted 测量的旋转残差，单位度。</summary>
public float LastResidualDegrees => Controller.LastResidualDegrees;
```
并新增转发 `public event Action<string> OnNeedReacquire { add => Controller.OnNeedReacquire += value; remove => Controller.OnNeedReacquire -= value; }`（供 AnchorRecoveryController 直接订阅，可选，与轮询二选一；见 Task 8 注）。

- [ ] **Step 2: RuntimeDiagnostics 字段**

`latestInnovationPosD2 / latestEffectiveMeasurementNoise` 替换为 `latestResidualMeters / latestResidualDegrees`（带中文 Tooltip）。`ApplyPolicyDecision` 内同步改为读取新属性。其余诊断（state/motion/predictAhead/speed）不变。

- [ ] **Step 3: build**
```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```
Expected: PASS。

---

## Task 8: 新建 AnchorRecoveryController（自动重注册）

**Files:** Create `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs`（+ `.meta`）；Modify `AnchorPolicySmoke.csproj`、`Program.cs`

> 结构取 GPT 版独立 MonoBehaviour，但**触发条件仅"持续低分"**，不接 Lost 计时（除非 `enableLostAutoReacquire`）。低分判定优先订阅 `PolicyController.OnNeedReacquire`（已带计时+冷却逻辑），MonoBehaviour 只负责把回调转成 `ReacquireAsync` 调用 + in-flight 去重。这样计时/冷却逻辑集中在可被 smoke 测试的 PolicyController，MonoBehaviour 保持薄。

- [ ] **Step 1: 类实现**

```csharp
using System.Threading;
using System.Threading.Tasks;
using EgoAnchor.Client;
using EgoAnchor.Protocol.Generated;
using UnityEngine;

namespace EgoAnchor.Runtime
{
    /// <summary>
    /// Anchor 自动重获取桥接。
    /// 订阅 policy 的"持续低分需要重注册"信号，通过 AnchorCommandClient 请求 Python 重新 register。
    /// 不解码 PoseResult、不修改 Transform、不直接重置 Python 模型；冷却与计时逻辑在 PolicyController 内。
    /// </summary>
    public sealed class AnchorRecoveryController : MonoBehaviour
    {
        [Tooltip("提供 OnNeedReacquire 信号的 anchor policy host。")]
        [SerializeField] private Policy.AnchorPolicyHost policyHost;
        [Tooltip("发送 reacquire command 的客户端，必须与 runtime 共用同一 NATS。")]
        [SerializeField] private AnchorCommandClient commandClient;
        [Tooltip("是否启用自动重获取。关闭后只保留手动按钮。")]
        [SerializeField] private bool autoReacquire = true;
        [Tooltip("触发 reacquire 时是否让 Python 先清空旧 tracking 状态。")]
        [SerializeField] private bool clearTrackingFirst = true;

        private bool commandInFlight;
        private CancellationTokenSource destroyCts;

        private void Awake()
        {
            destroyCts = new CancellationTokenSource();
            if (policyHost != null) policyHost.OnNeedReacquire += HandleNeedReacquire;
        }

        private void OnDestroy()
        {
            if (policyHost != null) policyHost.OnNeedReacquire -= HandleNeedReacquire;
            destroyCts?.Cancel(); destroyCts?.Dispose();
        }

        private void HandleNeedReacquire(string reason)
        {
            if (!autoReacquire || commandClient == null || commandInFlight) return;
            _ = RequestReacquireAsync(reason);
        }

        private async Task RequestReacquireAsync(string reason)
        {
            commandInFlight = true;
            try
            {
                await commandClient.ReacquireAsync(
                    ReacquireAnchorRequest.Types.ReacquireMode.ForceDetect,
                    clearTrackingFirst, string.Empty, 0.0,
                    reason ?? "auto_reacquire_low_score", destroyCts.Token);
            }
            finally { commandInFlight = false; }
        }
    }
}
```

> 注：`OnNeedReacquire` 在 Unity 主线程外的回调安全性——`PolicyController.AcceptPose` 由 PoseResultReceiver 投递到主线程消费（现有架构），故回调在主线程，`ReacquireAsync` 可安全发起。实现时确认投递点，必要时加主线程 marshaling。

- [ ] **Step 2: smoke 静态检查**

```csharp
private static void AssertAnchorRecoveryControllerWiring()
{
    Type t = typeof(EgoAnchor.Runtime.AnchorRecoveryController);
    Assert(t.GetMethod("HandleNeedReacquire", BindingFlags.Instance | BindingFlags.NonPublic) != null,
        "AnchorRecoveryController should handle reacquire signal");
}
```
在 `Main()` 集成断言区调用。

- [ ] **Step 3: csproj include**

```xml
<Compile Include="..\..\EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Runtime\AnchorRecoveryController.cs" Link="Runtime\AnchorRecoveryController.cs" />
```

- [ ] **Step 4: smoke + build**
```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```
Expected: PASS。

---

## Task 9: 真机数据回放对照（真验证，非旧数据复跑）

**Files:** Create `EgoAnchor_Python/eval/tools/replay_oneeuro.py`

> 目的：GPT 版 Task10 自认"跑 eval 用旧录制数据，不能证明新行为"。本 Task 用真机 **aligned raw pose** 回放喂进 Python 复现的 One-Euro，与旧 kalman 输出、raw、GT 三方对照，**实现前先用它选定默认参数**，实现后回归确认不退化。

- [ ] **Step 1: 脚本**

读取 `data/eval/20260613_012345_controller_right` 的 unity_output：提取每帧 `aligned_raw_pos/rot`（One-Euro 输入）、`source_capture_mono_ms`（capture 时间轴）、`reliability_score`、`gt_pos/rot`、旧 `stable_pos/rot`（kalman 基线）。用与 C# 完全一致的 One-Euro 公式（位置 3 轴 + 旋转角度）逐 source-frame 推进，渲染时刻按 unity_output 行的 `render_mono_ms` 取前推输出。

- [ ] **Step 2: 输出对照表**

打印三方对比：
- 静止段（GT 帧间位移 < 1mm）每渲染帧抖动（mm）：One-Euro / 旧 kalman / raw。
- 运动段（GT 帧间 > 3mm）位置误差 vs GT（mm，p50/p90）：三方。
- 等效延迟：输出与 GT 最佳时移相关（ms）：One-Euro vs 旧 kalman。

**通过标准**：One-Euro 静止抖动 ≤ 旧 kalman（≤0.15mm 量级）；运动误差 ≤ raw（即不再 1.06x 帮倒忙）；等效延迟 < 旧 kalman 补偿后水平。

- [ ] **Step 3: 调参定档**
不达标先在脚本里扫 `positionMinCutoff ∈ [0.5,2]`、`positionBeta ∈ [0.2,1.0]`、`maxPredictAhead ∈ [0.08,0.15]`，选最优写回 `AnchorPolicyConfig` 默认值与 Task 5 调参。

```powershell
pixi run python eval/tools/replay_oneeuro.py --session-dir data/eval/20260613_012345_controller_right
```

---

## Task 10: 文档同步

**Files:** Modify `ANCHOR_CONTROLLER_GUIDE.md`、`AGENTS.md`

- [ ] **Step 1: guide 概述**
替换"统一自适应 / 6DoF Kalman / 马氏门控"为：One-Euro 自适应平滑（静止稳、运动跟手，无离散态）+ 有界前推（延迟补偿）+ 持续低分自动重注册；列新参数表（Task 2 的 13 项），删除 teleport/soft/Mahalanobis/Kalman 协方差/static-lock 相关条目。补充挂载说明（`AnchorRecoveryController` 需在场景拖 `policyHost` + `commandClient`）。

- [ ] **Step 2: AGENTS 主线事实**
`USER-MAINTAINED-REQUIREMENTS` 区块**不动**。其余 `Policy/` 描述更新为：`PolicyController` = One-Euro tracker + 4 态 lifecycle + 持续低分重注册；`AnchorTracker`/`AnchorLifecycle`/`AnchorRecoveryController` 职责；明确无 Mahalanobis 门、无 teleport recovery、无 6DoF Kalman。

- [ ] **Step 3: 陈词扫描**
```powershell
rg "马氏|Mahalanobis|teleport|softRecovery|soft recovery|6DoF Kalman|AnchorMeasurementGate|AnchorOutputSmoother|MotionStateClassifier|AnchorPoseFilter|AnchorStateMachine" ANCHOR_CONTROLLER_GUIDE.md AGENTS.md EgoAnchor_Unity\Assets\Scripts\EgoAnchor\Policy
```
Expected: 无残留（被删类名不再出现于文档与现存代码）。

---

## Task 11: 完整验证

- [ ] **Step 1: smoke**
```powershell
dotnet run --project EgoAnchor_Tools\anchor_policy_smoke\AnchorPolicySmoke.csproj
```
Expected: `Anchor policy smoke passed.`

- [ ] **Step 2: Unity 编译**
```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```
Expected: 成功，无新 EgoAnchor policy/runtime error。

- [ ] **Step 3: Python eval 单测**（确认 schema 未破坏 loader）
```powershell
cd EgoAnchor_Python; pixi run python -m unittest discover -s eval/tests -p "test_*.py"
```
Expected: 全过。

- [ ] **Step 4: 真机回放对照**（Task 9 脚本，确认行为达标）
```powershell
cd EgoAnchor_Python; pixi run python eval/tools/replay_oneeuro.py --session-dir data/eval/20260613_012345_controller_right
```
Expected: One-Euro 静止抖动 ≤ 旧 kalman、运动误差 ≤ raw、等效延迟更低。

- [ ] **Step 5: 行数对比报告**
```powershell
@'
from pathlib import Path
files = [
 "EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyConfig.cs",
 "EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/PolicyController.cs",
 "EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorTracker.cs",
 "EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorLifecycle.cs",
 "EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRecoveryController.cs",
]
for f in files:
    p=Path(f); print(f, len(p.read_text(encoding="utf-8").splitlines()) if p.exists() else "MISSING")
'@ | python -
```
重构前基线：`AnchorPolicyConfig` 251、`PolicyController` 496、`AnchorPoseFilter` 659（删）、`AnchorMeasurementGate` 533（删）、`AnchorOutputSmoother` 234（删）、`MotionStateClassifier` 272（删）、`AnchorStateMachine` 209（删）。预期净删 ~1500 行、参数 40+→13。

- [ ] **Step 6: 场景接线提示**
代码落地后，在 Unity Editor 把 `AnchorRecoveryController` 的 `policyHost` 与 `commandClient` 拖好（当前 `EgoAnchor-Evaluation.unity` 已有用户改动，单独作为 scene-only 改动处理，先 review dirty scene diff）。未接线时自动重注册静默禁用，仅手动按钮可用。

---

## Self-Review

- **Spec 覆盖**：静止稳定（One-Euro 低 cutoff + 头动残差门）、运动连续与跟手（速度自适应 + 有界前推）、低分不拖动、外点剔除、断流退化、持续低分自动重注册、frame-align 边界保持、baseline 保留、文档、真机回放验证。
- **取舍记录**：删 `MotionStateClassifier`（离散态翻转，实测 1.56/s）；前推 0.13s 由真机 268ms 延迟量化得出，非沿用旧值；自动重连仅"持续低分"（用户决定），Lost/断线留开关。
- **类型一致**：复用既有 DTO（`AnchorObservation/AnchorPolicyDecision/AnchorPolicyOutput/AnchorState/AnchorMotionState/AnchorLifecycleEvent`），新增 `AnchorTracker/AnchorLifecycle/AnchorRecoveryController` 与 `OnNeedReacquire` 事件；Host/Runtime 诊断一致更新。
- **风险**：(1) `OnNeedReacquire` 回调线程归属需在实现时确认（PoseResultReceiver 主线程投递）。(2) 删 5 个 `.cs` 会丢失场景中 `AnchorPolicyHost` 旧序列化参数——新默认值即 Task 2 表，旧 40 参数无法迁移（也无必要，正是它们调不出效果）。(3) One-Euro 旋转角度做法对接近 180° 大旋转需依赖最短弧，已由迁移的 `AlignSign` 保证。
- **接口冻结确认**：`AcceptPose/Advance/Notify*` 签名、`AnchorPolicyOutput/Decision` 结构、eval `variants:["kalman","raw"]` schema 均不变，eval loader 与论文对照不受影响。
