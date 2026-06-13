# EgoAnchor 分阶段可插拔 Anchor Pipeline 架构设计

> 状态：设计文档，待 review。本文不替你做实现决策，而是把「分阶段 + 每阶段可插拔模块」落成一套可编译、可消融、可离线回放的架构，并明确每个设计选择背后的取舍。
>
> 关联：取代 `task_plan.md`（旧 One Euro 单方法重构）的架构层；`补充.md` 的算法选型结论仍有效，作为 `EgoAnchorEstimator` 的内核。

---

## 0. 这份设计要解决的三件事

1. 把「真实 pose → 滤波 → 预测 → 渲染」做成阶段化、可插拔的流水线，每个槽能从列表选模块。
2. 让所有 baseline（raw / low-pass / Kalman / vanilla One Euro）和 ours 走**完全相同的输入与输出契约**，保证论文 RQ2 是 apples-to-apples 对比，而不是「对手没上场」。
3. 核心算法用 plain C# 实现，同一份代码在 Unity 实时、headless smoke、离线回放三处复用。

---

## 1. 关键纠正：阶段顺序与阶段粒度

用户最初设想是「真实 pose → 预测 → 滤波 → 渲染」，四阶段任意插拔。这里有两个必须纠正的点，否则架构会拧着数学走。

### 1.1 顺序：滤波在前，预测在后

预测需要速度/运动模型，速度只能从**已滤过的状态历史**估出。对单个 raw 测量无法预测。因此因果顺序必然是：先用测量更新出干净状态（滤波），再把状态外推到渲染时刻（预测）。

### 1.2 粒度：滤波与预测不能拆成两个独立可选模块

- Kalman 的 predict 与 update 通过协方差 `P` 紧耦合，无法把「KF 的预测」单独拎出来配「One Euro 的滤波」——One Euro 没有协方差。
- One Euro 自带导数估计（`dxHat` 即速度），它的预测天生复用自己的滤波速度，外挂第二个速度估计器是冗余且更差。

结论：**预测是 Estimator 的内禀属性**，跟着它自己的状态走。真正能算法无关、干净分离、任意插拔的阶段是 **Gate（前置门控）** 和 **OutputStage（后置整形）**。Estimator 作为整体单元可插拔，就是 baseline 集合。

### 1.3 真实模型：两个时钟，三个可插拔槽 + 一条正交层

```
测量时钟 (~5Hz, capture-time)
  AnchorSample
    -> [Gate]        剔除/门控（可插拔：Null / ScoreJump）
    -> [Estimator]   滤波/状态融合（可插拔：Raw/LowPass/Kalman/OneEuro/EgoAnchor）
渲染时钟 (~70Hz, render-time)
    -> Estimator.PredictAt(now)   升采样 + 延迟补偿（Estimator 内禀）
    -> [OutputStage] 静止锁 / 限速 / 前推钳制（可插拔：PassThrough / StaticLockRateLimit）
    -> render
  [Recovery] 正交层：只观察状态、发 reacquire command，不碰 pose
```

槽位 = Gate × Estimator × OutputStage，外加 Recovery 开关。每条消融轴 = 换一个槽。

---

## 2. 核心数据类型（plain C#）

放在 `Anchor/Core/`。只依赖 `UnityEngine` 的 `Pose/Vector3/Quaternion` 值类型（smoke csproj 已证明可 headless 引用 `UnityEngine.dll`），**不读 `UnityEngine.Time`**，所有时间由调用方传入。

```csharp
/// <summary>已 frame-aligned 的单帧测量。等价于现有 AnchorObservation 的精简内核。</summary>
public readonly struct AnchorSample {
    public readonly long    FrameId;
    public readonly Pose    WorldPose;     // frame-aligned Unity world pose
    public readonly double  CaptureTime;   // capture-time 时钟（秒），不是到达时刻
    public readonly float   Score;         // reliability [0,1]
    public readonly AnchorSampleKind Kind; // Track / Register / ReRegister / Invalid
    public readonly string[] Flags;        // reliability flags
}

/// <summary>Estimator 在某时刻的状态估计。</summary>
public readonly struct AnchorState {
    public readonly Pose    Pose;
    public readonly Vector3 LinearVelocity;     // m/s
    public readonly Vector3 AngularVelocity;    // rad/s（log-space）
    public readonly double  StateTime;          // 该状态对应的时刻
    public readonly float   Confidence;         // [0,1]，供 OutputStage/Recovery 参考
}

/// <summary>Gate 判定结果。</summary>
public readonly struct GateDecision {
    public readonly GateAction Action;    // Accept / Reject / Hold / Relocalize
    public readonly string     Reason;    // 可统计的固定字符串
}

/// <summary>OutputStage 需要的渲染时刻上下文。</summary>
public readonly struct OutputContext {
    public readonly double LastSampleTime;   // 最近被接受测量的 capture-time
    public readonly double Gap;              // now - LastSampleTime，判 coast/freeze
    public readonly float  LastScore;
}
```

`AnchorSampleKind`、`GateAction`、以及对外保留的 `AnchorState`（生命周期 enum，与上面状态 struct 不同名，注意区分）、`AnchorMotionState` 都从现有 `Policy/` 类型迁移，保证 eval JSONL schema 不破。

> 命名冲突提醒：现有代码里 `AnchorState` 是**生命周期 enum**（Tracking/Coasting/Lost…）。本设计里状态估计 struct 暂用 `AnchorState`，实现时改名为 `AnchorEstimate` 以免撞名。下文沿用 `AnchorEstimate`。

---

## 3. 三个可插拔接口 + 编排器

```csharp
/// <summary>前置门控。算法无关，可单独开关（RQ：门控 on/off）。</summary>
public interface IAnchorGate {
    GateDecision Evaluate(in AnchorSample s, in AnchorEstimate predicted, bool hasState);
    void Reset();
}

/// <summary>估计器 = baseline 集。整体可插拔；内部含滤波 + 自己的预测。</summary>
public interface IAnchorEstimator {
    string Name { get; }
    bool   HasState { get; }
    void   Snap(in AnchorSample s);            // 首帧/重定位直接贴合
    void   Update(in AnchorSample s);          // 测量时刻：滤波/状态融合
    AnchorEstimate PredictAt(double renderTime);// 渲染时刻：升采样 + 延迟补偿
    void   Reset();
}

/// <summary>后置整形。算法无关，可单独开关（RQ：静止锁 on/off、预测 on/off）。</summary>
public interface IAnchorOutputStage {
    Pose Condition(in AnchorEstimate predicted, double renderTime, in OutputContext ctx);
    void Reset();
}
```

编排器 `AnchorPipeline`（plain C#），对外两个入口与现有 `PolicyController.AcceptPose` / `Advance` 同接缝：

```csharp
public sealed class AnchorPipeline {
    private readonly IAnchorGate        gate;
    private readonly IAnchorEstimator   estimator;
    private readonly IAnchorOutputStage output;

    public AnchorPipeline(IAnchorGate g, IAnchorEstimator e, IAnchorOutputStage o) {
        gate = g; estimator = e; output = o;
    }

    // 测量时钟（~5Hz）
    public AnchorPolicyDecision AcceptSample(in AnchorSample s) {
        AnchorEstimate predicted = estimator.HasState
            ? estimator.PredictAt(s.CaptureTime)
            : default;
        GateDecision d = gate.Evaluate(s, predicted, estimator.HasState);
        switch (d.Action) {
            case GateAction.Relocalize:
            case GateAction.Accept when !estimator.HasState:
                estimator.Snap(s); break;
            case GateAction.Accept:
                estimator.Update(s); break;
            // Reject / Hold：不动状态
        }
        return MapDecision(d);   // 转成现有 AnchorPolicyDecision，保 eval schema
    }

    // 渲染时钟（~70Hz）
    public AnchorPolicyOutput Advance(double renderTime) {
        if (!estimator.HasState)
            return AnchorPolicyOutput.None(/*lifecycle*/, "no_state");
        AnchorEstimate est = estimator.PredictAt(renderTime);
        Pose pose = output.Condition(est, renderTime, BuildContext(renderTime));
        return new AnchorPolicyOutput(true, pose, /*lifecycle*/, /*motion*/,
                                      (float)(renderTime - est.StateTime), "advance");
    }
}
```

生命周期状态机（现有 `AnchorStateMachine`）和 Recovery 保留在 `AnchorPipeline` 之外或作为薄成员，**不混进 Gate/Estimator/OutputStage**——它们是正交关注点。

---

## 4. Estimator 动物园（baseline 集）

每个一个文件，全部实现 `IAnchorEstimator`。这是论文 RQ2 的对比对象。

| Estimator | 滤波 | 预测（PredictAt） | 角色 |
| --- | --- | --- | --- |
| `RawEstimator` | 无 | ZOH（保持上一测量） | jitter floor + 阶梯感基线 |
| `LowPassEstimator` | 位置/旋转 EMA | 有限差分速度 → 线性外推（可关） | 简单稳定性 baseline |
| `KalmanEstimator` | const-velocity KF（位置+log 旋转） | **KF predict 步**，R 由 score 驱动 | 强基线：原理化「升采样+预测」对手 |
| `OneEuroEstimator` | vanilla One Euro | 复用 OEF 速度，ZOH 或简单外推（声明清楚） | 交互系统常用低通 baseline |
| `EgoAnchorEstimator` | score-adaptive One Euro | **有界前推 + score×motion 阻尼** | ours |

### 4.1 关于「Kalman 预测 + One Euro 滤波 + score 融合」的判断

用户问到要不要把 KF 预测和 OEF 滤波串起来。结论：**串联（KF→OEF）不要做**，那是双重平滑，两层互相打架、叠加滞后、协方差语义被破坏（项目历史删 `AnchorOutputSmoother` 正因两层平滑耦合）。

只有两条自洽的路，**score 的融合方式完全不同**，分别落成 `KalmanEstimator` 和 `EgoAnchorEstimator`：

- **方案 A — score-adaptive Kalman**：score → 测量噪声 `R`（低分→大 R→少信任）。原理化、教科书做法，审稿人尊重；KF 的 predict 步天然完成升采样+延迟补偿。
- **方案 B — score-adaptive One Euro + 有界预测**：score → 调 alpha 权重 + 调预测时长；OEF 自带速度，外推有界。参数物理意义清楚。

**不在文档里二选一**——两个都实现成 Estimator，用离线回放让数据决定哪个赢。真正的技术增量不在 KF vs OEF，而在两者共有的 **「被 score×motion 约束的预测」**：低分 / 低数据率 / 高不确定时缩短或关闭外推。这是 MR 特定、有数据背书（见 memory：4.4Hz 激进外推导致 37° 摆动）的非平凡机制，比「我们用了 One Euro」强得多。

### 4.2 预测必须公平

现有 `RunProcessors` 的 Kalman/lowpass baseline **只在收到测量时算一次，没有 render-time 预测**；而 policy 路径每帧 Advance 做前推。若保持现状，ours 在 lag 指标上必赢，但这是对手没上场，审稿人一眼看穿。本架构强制所有 Estimator 都实现 `PredictAt(renderTime)`，从而：

- RQ2 滤波对比：固定 Gate=Null、OutputStage 共享，只换 Estimator。
- 预测 on/off 作为**独立消融轴**：通过 OutputStage 把前推钳制为 0，或 Estimator 预测时长设 0。

---

## 5. 文件布局

```
Anchor/Core/                         (plain C#, 不读 UnityEngine.Time)
  AnchorSample.cs  AnchorEstimate.cs  GateDecision.cs  OutputContext.cs
  IAnchorGate.cs  IAnchorEstimator.cs  IAnchorOutputStage.cs
  AnchorPipeline.cs
  Math/  OneEuro.cs  QuaternionLog.cs  ConstVelKalman.cs

Anchor/Gates/
  NullGate.cs
  ScoreJumpGate.cs              (score + flag + jump + stale，迁移自 AnchorMeasurementGate 精简)

Anchor/Estimators/
  RawEstimator.cs  LowPassEstimator.cs  KalmanEstimator.cs
  OneEuroEstimator.cs  EgoAnchorEstimator.cs

Anchor/Output/
  PassThroughOutput.cs
  StaticLockRateLimitOutput.cs  (静止锁 + 限速 + 前推钳制，吸收 AnchorStaticLock/OutputSmoother)

Anchor/Recovery/
  AnchorRecoveryController.cs   (正交层，沿用 task_plan 设计)

Runtime/  (Unity 薄层，尽量不动)
  AnchorPipelineHost.cs         (MonoBehaviour：enum 选 Gate/Estimator/Output，热更参数，配 AnchorPipeline)
  PoseToAnchorRuntime.cs        (基本不变；把 policyHost 换成 pipelineHost，调 AcceptSample/Advance)
  DynamicObjectAnchor.cs        (不变；仍读 TryGetStablePose)

EgoAnchor_Tools/anchor_replay/  (新 dotnet 工程，照搬 anchor_policy_smoke 的引用方式)
  AnchorReplay.csproj           (Reference UnityEngine.dll + Compile Include Anchor/Core 全部源文件)
  Program.cs                    (读一份 eval session，对同一输入跑全部 Gate×Estimator×Output 组合，出统一指标表)
```

迁移策略：现有 `Policy/` 与 `Processors/` 不立即删，先并存。`AnchorPipelineHost` 跑通、回放对比确认无回归后，再按 task_plan 的删除清单清掉旧 `PolicyController/AnchorMeasurementGate/AnchorOutputSmoother/MotionStateClassifier`。对外类型 `AnchorPolicyDecision/AnchorPolicyOutput/AnchorMotionState` 和 eval schema 全程保留。

---

## 6. 消融轴 → 配置对照

| RQ / 轴 | Gate | Estimator | OutputStage | Recovery |
| --- | --- | --- | --- | --- |
| RQ1 frame-align（独立轴，见下） | — | — | — | — |
| RQ2 滤波对比 | Null | 五选一 | 共享同款 | off |
| 预测 on/off | Null | 同一个 | 前推钳制 0 ↔ 正常 | off |
| 门控 on/off | Null ↔ ScoreJump | EgoAnchor | 共享 | off |
| 静止锁 on/off | 固定 | EgoAnchor | PassThrough ↔ StaticLockRateLimit | off |
| RQ3 恢复 | 固定 | EgoAnchor | 固定 | off ↔ 纯超时 ↔ score-aware |

> RQ1（arrival-time vs frame-aligned mapping）是**坐标-时间映射轴**，发生在 `CameraPoseFrameAligner` 层，不在本 pipeline 内，保持现有实现，单独对比。别和滤波轴混。

---

## 7. 离线回放 harness（实验主力）

为什么实验主力放离线、Unity 只做 demo/video：保证所有组合吃**完全相同输入**，无 run-to-run 抖动，对比公平、图可复现。

- 新建 `EgoAnchor_Tools/anchor_replay`，照搬 `anchor_policy_smoke` 的 `<Reference UnityEngine.dll>` + `<Compile Include>` 方式，直接编译 `Anchor/Core` 与全部 Estimator 源文件 → **论文数字 == Unity 实时行为**（同一份 C#）。
- 输入：一份 eval session（如 `data/eval/20260613_012345_controller_right`）的 frame-aligned raw pose + score + capture/render 时间 + 可用 GT。
- 流程：对同一输入序列，循环 `{Null,ScoreJump} × {Raw,LowPass,Kalman,OneEuro,EgoAnchor} × {PassThrough,StaticLockRateLimit}`，按真实 capture 时间喂 `AcceptSample`、按渲染时间网格调 `Advance`。
- 输出统一指标表：static jitter（mm）、moving RMSE vs GT（mm）、等效 lag（ms）、maxZeroRun（连续零增量帧，查阶梯感）、jump rejection 数。
- 通过门槛（沿用 task_plan）：ours 在有 GT 段不比 raw 差 >5%；连续运动段 `maxZeroRun <= 4`；且**回答「KF 还是 OEF 赢、policy 算不算贡献」**。

---

## 8. 落地顺序

1. **Core 接口 + AnchorPipeline + 五个 Estimator + 回放 harness**：一步就能用数据回答 policy 是否成立、A/B 谁赢。后续所有论文写作分支依赖此结果。
2. Unity 薄层 `AnchorPipelineHost`（enum 选模块、热更参数），接进 `PoseToAnchorRuntime`，录 supplementary video。
3. Recovery 独立层 + score-aware proactive reacquire（RQ3 卖点）。
4. 数据确认 ours 成立 → 按 task_plan 删旧 `Policy/Processors` 冗余文件；不成立 → 论文走「保底贡献」，policy 降级为实现细节。

---

## 9. 与现有计划的关系

- `task_plan.md`（One Euro 重构）：其 One Euro 数学、static lock、recovery、smoke/回放验证**仍然有效**，作为本架构里 `EgoAnchorEstimator` + `StaticLockRateLimitOutput` + `AnchorRecoveryController` 的内核。本文在其之上补了**可比 baseline 集**这一缺失维度。
- `补充.md`：算法选型（One Euro 优于多层 Kalman+gate）结论保留；但「删 Kalman」改为「Kalman 升级为 const-velocity predict 版作为强 baseline」——对比需要它。

---

## 10. 待确认 / 风险

| 项 | 说明 |
| --- | --- |
| `AnchorEstimate` vs 生命周期 `AnchorState` 撞名 | 实现时状态估计 struct 用 `AnchorEstimate`，生命周期 enum 保持 `AnchorState`。 |
| KF log-space 旋转协方差 | const-velocity KF 在四元数 log-space 做旋转状态，需小心半球对齐；`Math/QuaternionLog.cs` 统一处理。 |
| 回放 GT 来源 | 当前 eval session 是否含可用 GT 决定 moving RMSE 能否算；无 GT 时只能比 jitter/lag/连续性，需在论文如实说明。 |
| 旧参数迁移 | Inspector 旧 40+ 参数不迁移，新默认值由回放标定，与 task_plan 一致。 |
| Unity 值类型依赖 | Core 用 `Pose/Vector3/Quaternion`，靠引用 `UnityEngine.dll` 编译；若日后要纯 .NET 化需自带数学类型，当前不必。 |
