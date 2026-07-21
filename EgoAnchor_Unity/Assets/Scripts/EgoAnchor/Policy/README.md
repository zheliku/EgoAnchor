# EgoAnchor Unity 锚定策略

本目录把低频、异步的世界系位姿观测转换为逐渲染帧对象锚点。运行时由运动状态估计、逐帧输出策略、观测接纳、生命周期和可选 StaticLock 组成；这些模块的时间语义不能混用。

## 模块边界

一个 `AnchorPolicyHost` 绑定一个 `MotionModel` 和一个 `SmoothingStrategy`：

```text
MotionModel                          SmoothingStrategy
|- ConstantVelocityModel            |- HoldStrategy
|- OneEuroModel                     |- PredictToNowStrategy
`- KalmanModel                      |- LinearSlerpStrategy
                                    `- HermiteStrategy
```

- `MotionModel` 负责状态、线速度和 body-local 角速度估计。
- `SmoothingStrategy` 负责输出所对应的目标时刻和逐渲染帧合成。
- `AnchorPolicyHost` 负责 VCD admission、生命周期、重获取和模块顺序。
- `EgoAnchorStaticLockModule` 只负责静止锚定、解锁证据和接缝恢复。
- `PoseToAnchorRuntime` 负责 `frame_id` 采集时刻对齐和坐标补偿，不参与滤波调参。

正式策略统一使用 `Strategy` 后缀，状态估计统一使用 `Model` 后缀。日志名固定为 `hold`、`predict_to_now`、`linear_slerp` 和 `hermite`。

## 四种输出策略

### HoldStrategy

锁存最近控制点并执行零阶保持，不外推、不插值。Arrival-Hold 和 Capture-Hold 都使用该策略，两者只改变世界系复合时刻。

### PredictToNowStrategy

每个渲染帧调用 `MotionModel.PredictAt(now)`，输出语义时刻等于当前渲染时刻。新重采的 `EgoAnchor w/o temporal synthesis` 使用 `KalmanModel + PredictToNowStrategy`，只关闭历史时序合成，不更换状态估计器。

### LinearSlerpStrategy

缓存运动模型输出的控制点，目标时刻为：

```text
t_target = t_render - delay(t)
```

`delay(t)` 由采集至渲染观测年龄的非对称 EMA、自适应安全系数和延迟下限决定，并限制每秒变化速度。相邻控制点之间的位置使用 Linear，旋转使用最短弧 SLERP；不使用 One-Euro 内部导数作为样条切线。

新重采的场景显示名为 One-Euro Interpolation，schema 中稳定 variant ID 仍为 `One-Euro Anchor`。该配置开启采集时刻对齐和 VCD，使用与完整系统相同的生命周期与重获取开关，只关闭 StaticLock。

### HermiteStrategy

使用与 Linear/SLERP 相同的自适应历史目标时间。位置在相邻 Kalman 控制点之间做 Hermite；旋转在 `Log(q1^-1 q)` 切空间做 Quaternion Hermite。端点切线按弦长限制，避免急停时速度滞后造成过冲。

`AngularVelocityRad` 始终表示控制点姿态下的 body-local 角速度。Kalman/One-Euro 重置旋转切空间时使用 SO(3) 右雅可比保存物理角速度；Hermite 在第二端使用右雅可比逆把 body 角速度转换为 Log 向量导数。不得直接混用不同参考姿态下的旋转向量导数。

## 正式实验组合

| Variant | Alignment | Admission | Model | Strategy | StaticLock | Lifecycle / reacquire |
|---|---|---|---|---|---|---|
| Arrival-Hold | Arrival time | 合法性 | ConstantVelocity | Hold | 关 | 基线 |
| Capture-Hold | Capture time | 合法性 | ConstantVelocity | Hold | 关 | 基线 |
| One-Euro Anchor | Capture time | VCD | OneEuro | LinearSlerp | 关 | 与完整系统相同 |
| EgoAnchor | Capture time | VCD | Kalman | Hermite | 开 | 完整 |
| EgoAnchor Linear/SLERP | Capture time | VCD | Kalman | LinearSlerp | 开 | 完整；配对策略候选 |
| EgoAnchor w/o capture-time alignment | Arrival time | VCD | Kalman | Hermite | 开 | 完整 |
| EgoAnchor w/o VCD | Capture time | 合法性 | Kalman | Hermite | 开 | 仅关闭 VCD 相关低分重获取 |
| EgoAnchor w/o temporal synthesis | Capture time | VCD | Kalman | PredictToNow | 开 | 完整 |
| EgoAnchor w/o StaticLock | Capture time | VCD | Kalman | Hermite | 关 | 完整 |

历史 v2 的 One-Euro 是 `OneEuroModel + RawPassthroughStrategy`，历史 w/o temporal synthesis 是 `ConstantVelocityModel + RawPassthroughStrategy`。旧名只用于解释既有数据 provenance，不得恢复为当前 Unity 类，也不得与新重采数据混合。

## 冻结参数

### OneEuroModel

| 通道 | minCutoff | beta | derivativeCutoff |
|---|---:|---:|---:|
| 位置 | 0.8 Hz | 6 | 2 Hz |
| 旋转 | 1 Hz | 1 | 2 Hz |

### KalmanModel

| 参数 | 值 |
|---|---:|
| `positionProcessNoise` | 0.2 |
| `positionMeasurementNoise` | 0.0004 |
| `rotationProcessNoise` | 0.4 |
| `rotationMeasurementNoise` | 0.0025 |

测量噪声是冻结参数。VCD 只控制 admission，不根据分数在线修改 Kalman 噪声。

### 历史目标时刻

`LinearSlerpStrategy` 与 `HermiteStrategy` 都使用 `latencySafetyMargin=1.15`、`minDelaySeconds=0.25`，延迟变化上限为每秒 50 ms。两种方法的公平性来自相同接纳候选、相同目标时间和相同渲染时间线，不要求 One-Euro 使用 Hermite 端点速度。

### StaticLock

正式场景中，完整 EgoAnchor、Linear/SLERP 配对候选以及保留 StaticLock 的三个消融必须使用同一组序列化参数。当前旋转相关冻结值包括：

- `enterAngSpeedDps=22`
- `unlockDriftDegrees=12`
- `deadbandDegrees=3`
- `unlockEvidenceDegrees=20`
- `headSettleSeconds=0.6`

头动只影响头停后的沉降窗和位置容忍；真实物体运动证据不能在头动期间被冻结。距离自适应只放大位置通道，旋转阈值保持不变。

## 场景与日志

正式场景 `EgoAnchor-Experiment12.unity` 使用九个唯一 runtime，由一个 `AnchorRuntimeHub` 分发同一候选流：四个实验一配置、四个实验二单组件消融，以及一个 `EgoAnchor Linear/SLERP` 配对策略候选。实验一和实验二共享完整 EgoAnchor runtime，避免同一方法出现两套内部状态。

每个 variant 的 manifest 配置必须包含：

- `motion_model`、`smoothing_strategy` 和 `quality_gate`
- alignment、VCD、temporal synthesis、StaticLock 和重获取开关
- 覆盖坐标补偿、模型、策略、生命周期和 StaticLock 数值的 `configuration_fingerprint`
- 绑定完整指纹的 per-variant `config_hash`

Python Stage 1 QC 会按 Unity 的 FNV-1a 顺序重算哈希。当前场景验证带 `variant_matrix_id=exp12_9_strategy_v1` 的九路组件矩阵，并强制完整参数指纹；无该标识的已发布 v2 八路归档按其历史方法字符串和旧哈希字段顺序复现。当前数据缺失指纹、字符串布尔值、名称与组件错配或任意缺项都会阻止正式发布。

## 验证

```powershell
dotnet build EgoAnchor_Unity/EgoAnchor.Tests.csproj --no-restore
dotnet build EgoAnchor_Unity/Assembly-CSharp.csproj --no-restore
```

Unity Editor 还必须运行 `EgoAnchor.Tests` EditMode 测试。场景契约测试会读取 YAML，核对九个 runtime、层级、模型、策略、门控、重获取和 StaticLock 绑定。
