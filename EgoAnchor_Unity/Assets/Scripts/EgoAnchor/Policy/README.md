# EgoAnchor Unity 锚定管线（重构版）

把低频 (~5fps) 的观测 pose 实时升采样成每渲染帧 (72/90fps) 连续平滑的 anchor pose。
重构自离线仿真 `EgoAnchor_Tools3`，根治了旧实现"断断续续 / 阶梯跳变"的问题。

## 为什么旧的不平滑（已修复）

旧 estimator 的 `PredictAt` 把外推时长 `Clamp(now - lastObs, 0, maxPredictAhead≈0.16s)`。
观测每 ~0.2s 才来一次，一旦间隔超过 0.16s，pose 就**冻结**，下一帧观测再**snap** 跳过去
= 阶梯跳变。且完全没有"误差平滑过渡"。新架构：**外推不限幅 + 误差融合/延迟插值**，每帧都有连续输出。

---

## 架构：两个可自由组合的模块（3×2）

一个 anchor runtime = **1 个运动模型 (MotionModel) + 1 个平滑策略 (SmoothingStrategy)**，
挂在同一个 GameObject 上，由 `AnchorPolicyHost` 引用。两个维度正交，自由组合：

```
运动模型 MotionModel (模块 A，去噪+估速+外推)      平滑策略 SmoothingStrategy (模块 B，低频→高频)
├─ ConstantVelocityModel   (CV，差分速度，不去噪)   ├─ BlendStrategy          (B路：零延迟，外推+误差融合)
├─ KalmanModel             (Kalman 去噪+最优速度)    └─ DelayedInterpStrategy  (C路：延迟一周期+样条插值)
└─ OneEuroModel            (One Euro 自适应去噪)
```

**3×2 = 6 种组合**，对应论文实验矩阵：

| | BlendStrategy (B路·零延迟) | DelayedInterpStrategy (C路·延迟插值) |
|---|---|---|
| **ConstantVelocityModel** | cv + blend | cv(原始点) + interp |
| **KalmanModel** | **kalman + blend ★推荐** | kalman + interp |
| **OneEuroModel** | oneeuro + blend | oneeuro + interp |

**正交的第三维：static-lock。** `EgoAnchorStaticLockModule` 与上面 3×2 任意组合正交叠加：
挂上模块并启用 `lockEnabled` = 在该 baseline 之上加 EgoAnchor 静止锚定层；不挂或关闭 = 纯 baseline。
**EgoAnchor 主方法 = `kalman + interp` + `EgoAnchorStaticLockModule`**。

`raw`（什么都不做的参照）= 用任意 model + BlendStrategy 把 decay 设到很小，或单独留一个不平滑 runtime。

模块通过数据契约解耦：MotionModel 提供 `PredictAt(t)`（给 B 路外推）和 `LatestControlPoint`
（给 C 路缓冲插值）。host 每帧调 `strategy.Output(model, now)`。

---

## 场景挂载（真机对比多方法）

沿用 `AnchorRuntimeHub` 一个 pose 流分发给 N 个 runtime，一次跑同时对比所有方法。

**每个对比变体 = 一个 GameObject，挂 4 个组件：**

1. `PoseToAnchorRuntime` —— 帧对齐 + 喂 host（拖入 `framePoseHistory`、`policyHost`）
2. `AnchorPolicyHost` —— 拖入下面两个模块 + 可选静止锁模块
3. **一个 MotionModel 子类**（`KalmanModel` / `OneEuroModel` / `ConstantVelocityModel`）
4. **一个 SmoothingStrategy 子类**（`BlendStrategy` / `DelayedInterpStrategy`）
5. 可选 `EgoAnchorStaticLockModule` —— EgoAnchor 静止锚定层，拖入 host 的 `staticLockModule`
6. `DynamicObjectAnchor` —— 把 host 输出的 pose 应用到要显示的 Transform

然后把所有变体的 `PoseToAnchorRuntime` 拖进场景里 `AnchorRuntimeHub.runtimes` 列表。
`AnchorEvalRecorder` 也拖入这些 runtime → 一次录制拿到所有方法的对比数据。

> 提示：6 种组合各建一个 GameObject，分别显示不同颜色的同款 mesh，真机里一眼对比谁最平滑。

---

## 参数详解与推荐配置

### AnchorPolicyHost（每个变体都有）

| 参数 | 含义 | 推荐 |
|---|---|---|
| `motionModel` | 拖入运动模型子类 | 见上矩阵 |
| `smoothingStrategy` | 拖入平滑策略子类 | 见上矩阵 |
| `strategyLabel` | eval 用的名字，空则自动 `<model>_<strategy>` | 留空 |
| **Score Gate（仅 EgoAnchor 方法开）** | | |
| `enableScoreGate` | 是否拒绝低分/跳变坏观测。baseline 关、EgoAnchor 开 | baseline `false` |
| `minScore` | 接受观测的最低可靠分 (0..1)，低于则拒绝 | `0.2` |
| `maxJumpMeters` | 相对预测平移超过此值判为坏跳变拒绝 | `0.8` |
| `maxJumpDegrees` | 相对预测旋转超过此值判为坏跳变拒绝 | `120` |
| **Lifecycle** | | |
| `coastTimeoutSeconds` | 短时无观测仍继续外推/插值的时长 | `0.45` |
| `lostTimeoutSeconds` | 多久无观测后判 Lost 停输出（须 > coast） | `2.0` |
| `staticSpeedThresholdMps` | 运动/静止判定线速度阈值（仅诊断） | `0.015` |
| `staticAngularSpeedThresholdDps` | 运动/静止判定角速度阈值（仅诊断） | `1.5` |
### EgoAnchorStaticLockModule（EgoAnchor 核心方法，仅 EgoAnchor 变体挂载）

| 参数 | 含义 | 默认 |
|---|---|---|
| `lockEnabled` | 是否启用静止锚定稳定器。关闭后透传 baseline 输出 | `true` |
| `enterSpeedMps` | 进入静止判定的观测线速度阈值 (m/s) | `0.05` |
| `enterAngSpeedDps` | 进入静止判定的角速度阈值 (deg/s)，必须高于旋转噪声地板 | `35` |
| `dwellSeconds` | 进入锁定需连续静止+高分的时间 | `0.35` |
| `minScore` | 进入/维持锁定的最低可靠分 | `0.25` |
| `deadbandMeters` | 锁定时位置死区，小于此视为噪声 | `0.008` |
| `deadbandDegrees` | 锁定时旋转死区 | `3` |
| `unlockEvidenceMeters` | CUSUM 位置解锁证据阈值，越大越粘 | `0.08` |
| `unlockEvidenceDegrees` | CUSUM 旋转解锁证据阈值，越大越粘 | `20` |
| `unlockDriftMeters` | 相对锁定原点的平移租绳阈值 | `0.015` |
| `unlockDriftDegrees` | 相对锁定原点的旋转租绳阈值 | `5` |
| `evidenceHalfLifeSeconds` | 解锁证据漏积分半衰期，偶发噪声会衰减掉 | `0.27` |
| `creepHalfLifeSeconds` | 锁定时锁点缓慢贴近高分小位移观测的半衰期 | `2.7` |
| `relockSuppressSeconds` | 解锁后禁止再锁的时间，防频繁翻转 | `1.0` |
| `unlockSpeedFactor` | 速度逃逸倍数，观测速度明显大于静止阈值时触发解锁证据 | `2.5` |
| `unlockMovingSeconds` | 速度逃逸需要连续成立的时间 | `0.4` |
| `seamDecayPerFrame` | 解锁后从锁点回到 smoothing 输出的接缝残差衰减 | `0.85` |
| `refObsIntervalSeconds` | CUSUM 证据累积的观测周期归一基准 | `0.2` |
| `headRotForFullToleranceDps` | 头部角速度达到该值时，头动容忍因子吃满 | `60` |
| `headLinForFullToleranceMps` | 头部线速度达到该值时，头动容忍因子吃满 | `0.3` |
| `headMaxToleranceFactor` | 头动时死区、租绳、速度逃逸阈值最大放大倍数 | `4` |
| `headSettleSeconds` | 头停后冻结解锁判定的沉降时长 | `0.6` |
| `posToleranceRefDistanceMeters` | 距离自适应位置容忍的参考距离，此距离内不放大 | `0.4` |
| `posToleranceDistanceSlope` | 距离超过参考值后，位置容忍随距离增大的斜率 | `1.0` |
| `posToleranceMaxFactor` | 远距离位置容忍放大上限 | `3` |
| `lowScoreReleaseScore` | 锁定时持续低于该分数则释放锁点 | `0.3` |
| `lowScoreReleaseSeconds` | 低分释放需持续的时间 | `0.6` |

这些参数都参与当前控制逻辑，必须保留 Inspector 调参入口。不要用 `[HideInInspector]` 解决参数过多的问题；后续若要收纳，应做自定义 Inspector foldout、profile 或进一步拆分参数宿主。

### KalmanModel

| 参数 | 含义 | 推荐 |
|---|---|---|
| `positionProcessNoise` | 位置过程噪声 (m²/s)。大→跟得紧但抖，小→平滑但滞后 | `0.2` |
| `positionMeasurementNoise` | 位置测量噪声 (m²)。**小→信任观测、接近过点** | `0.0004` |
| `rotationProcessNoise` | 旋转过程噪声 (rad²/s) | `0.4` |
| `rotationMeasurementNoise` | 旋转测量噪声 (rad²) | `0.0025` |

> 调参口诀：物体抖→调大 measurementNoise（更信滤波）；物体跟不上/滞后→调大 processNoise（更信观测的快速变化）。

### OneEuroModel

| 参数 | 含义 | 推荐 |
|---|---|---|
| `minCutoff` | 最小截止频率 (Hz)。小→更平滑但滞后大 | `1.0` |
| `beta` | 速度自适应系数。大→快动时更跟手、滞后小 | `0.25` |
| `derivativeCutoff` | 速度低通截止 (Hz)，一般不动 | `1.0` |

> 静止抖→调小 minCutoff；快动拖影→调大 beta。

### ConstantVelocityModel
无参数（差分估速）。

### BlendStrategy（B路·零延迟，★主推）

| 参数 | 含义 | 推荐 |
|---|---|---|
| `decayPerFrame` | 每帧残差保留比例（60fps 基准）。**0.9 = 每帧还 10% 的债** | `0.9` |
| `extrapolationLatencyMultiplier` | **外推上限 = 此倍数 × 实测采集-渲染延迟**。自适应、不绑 fps：换快显卡延迟变小，上限自动变小。1.0=只补偿当前延迟 | `1.0` |
| `maxExtrapolationSecondsHardCap` | 外推绝对上限(秒)，与自适应值取小，丢观测时兜底硬保护 | `0.3` |

> `decayPerFrame` 是平滑度关键旋钮（时间常数 ≈158ms）：调大(0.95)更平滑但纠正慢、滞后久；调小(0.7)纠正快但接近闪现。
> `extrapolationLatencyMultiplier` 防止"急停冲过头/飞出去"：真机采集-渲染延迟可达 300ms，外推那么远会过头。
> 设 1.0 = 只外推到刚好补偿当前延迟。物体急停还冲过头→调小到 0.7；觉得跟手不够→调大。**已自适应,换显卡不用改。**

### DelayedInterpStrategy（C路·延迟插值）

| 参数 | 含义 | 推荐 |
|---|---|---|
| `latencySafetyMargin` | **延迟 = 此系数 × 实测采集-渲染延迟**。必须 >1 保证插值不退化成外推(否则锯齿跳变)。自适应、不绑 fps | `1.15` |
| `minDelaySeconds` | 手动延迟下限(秒)，实测未稳定前兜底 | `0.25` |
| `spline` | `Hermite`(用速度切线，配 Kalman/OneEuro 更稳) / `CentripetalCatmullRom`(用相邻点，配原始点直观) | `Hermite` |

> **⚠️ 关键修复（2026-06-16）**：延迟必须 = **实测采集-渲染延迟**（推理+传输+陈旧，真机 ~300ms），
> 不是观测周期(~200ms)。否则插值目标 `now-Δ` 比最新控制点还新 → 退化成外推 → **锯齿抖动**（旧版 bug）。
> 现已改为每帧实测延迟自适应。C 路严格过点、无 overshoot，但有 ~一个延迟周期的滞后。
> VR 实时场景慎用（延迟敏感），适合回放/录制。**换快显卡后延迟自动变小，不用调参。**

### RawPassthroughStrategy（纯 raw 参照·不升采样）

无参数。零阶保持(ZOH)：渲染时永远输出最近一帧观测，不外推不插值，下一帧观测到才跳变。
配 `ConstantVelocityModel` = **真正的"原样保持原始观测帧率"对照通道**（5fps 卡顿感），
用来对比升采样到底带来多少改善。**注意：之前录的 `raw` 其实是 cv+blend，不是真 raw——用这个才是真 raw。**

---

## 推荐起步配置

**先验证平滑（主推）**：`KalmanModel`(默认参数) + `BlendStrategy`(decay=0.9)，门控关。
这是离线仿真里效果最好的组合，零延迟、零跳变、跟手。

**做消融对比**：6 个 GameObject 各一种组合 + 一个 raw 参照，全拖进 `AnchorRuntimeHub`，
一次录制用 `AnchorEvalRecorder` 拿全部数据，离线 `eval/` 出指标对比图。

**EgoAnchor 方法（带 score + 静止锁定）**：`KalmanModel` + `DelayedInterpStrategy`(你满意的 interp) +
挂 `EgoAnchorStaticLockModule` 且 `lockEnabled=true`（核心）+ 可选 `enableScoreGate=true`。

> **EgoAnchor 不是"又一个滤波器"，而是建立在任意 baseline (model×strategy) 之上的 score-gated 分区静止锚定控制层。**
> 被锚定的真实物体绝大多数时间静止（动的是头显，噪的是观测）。所有 baseline 都是 motion-agnostic 滤波器，
> 静止时残留抖动；EgoAnchor 用静止锁定把小抖动当噪声吸收 → 抖动≈0（"看上去一动不动"），运动时交回 interp。
> 同一 `Kalman+interp` 组合，挂/关 `EgoAnchorStaticLockModule` = baseline ↔ EgoAnchor，这是最干净的消融。
> 离线仿真验证（EgoAnchor_Tools3）：静止段 P50 位置步长 0.115mm→0.000mm、冻结帧 9%→63%，运动跟踪不退化
> （lag 不变），代价是运动起始响应中位 +~110ms。

---

## 代码结构

```
Assets/Scripts/EgoAnchor/Policy/
├─ AnchorPolicyHost.cs          # 持两模块 + 生命周期 + 可选 score 门控 + 每帧输出
├─ EgoAnchorStaticLockModule.cs # 静止锁 MonoBehaviour 参数宿主
├─ StaticLockController.cs      # 静止锁纯 C# 控制器
├─ Contracts/                   # 模块接缝数据契约：AnchorObservation / AnchorPolicyDecision / AnchorPolicyOutput / GateDecision
├─ Lifecycle/                   # AnchorStateMachine + AnchorPolicyTypes (状态/运动状态/生命周期事件枚举)
├─ Math/                        # AnchorMath (四元数/向量基元) + ConstVelocityKalman / ScalarOneEuro / Spline
├─ Models/                      # MotionModel 基类 + CV / Kalman / OneEuro
└─ Smoothing/                   # SmoothingStrategy 基类 + Blend / DelayedInterp / RawPassthrough
```

运行时链路（都在 LateUpdate，执行序正确）：
`Hub.Publish → PoseToAnchorRuntime.AcceptPoseResult`(帧对齐)`→ host.AcceptPose`(喂模型) ；
`PoseToAnchorRuntime.LateUpdate(-50) → host.Advance(now) → strategy.Output → stablePose`；
`DynamicObjectAnchor.LateUpdate(0) → 读 stablePose → 应用 Transform`。

时间戳：观测的 `CaptureTimeSeconds` 和渲染 `now` 都用 `Time.realtimeSinceStartupAsDouble`
（同一单调时钟，见 StereoFrameSource），所以外推/插值的时间差是真实物理时间，平滑正确。
