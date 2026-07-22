# EgoAnchor Unity 锚定策略

本目录把低频、异步的世界系位姿观测转换为逐渲染帧对象锚点。运行时由运动状态估计、逐帧输出策略、观测接纳、生命周期和可选 StaticLock 组成；这些模块的时间语义不能混用。

## 模块边界

一个 `AnchorPolicyHost` 绑定一个 `MotionModel` 和一个 `SmoothingStrategy`：

```text
MotionModel                          SmoothingStrategy
|- ConstantVelocityModel            |- HoldStrategy
|- OneEuroModel                     |- PredictToNowStrategy
`- KalmanModel                      |- CausalPredictionStrategy
                                    `- LinearSlerpStrategy
```

- `MotionModel` 负责状态、线速度和 body-local 角速度估计。
- `SmoothingStrategy` 负责输出所对应的目标时刻和逐渲染帧合成。
- `AnchorPolicyHost` 负责 VCD admission、生命周期、重获取和模块顺序。
- `EgoAnchorStaticLockModule` 只负责静止锚定、解锁证据和接缝恢复。
- `PoseToAnchorRuntime` 负责 `frame_id` 采集时刻对齐和坐标补偿，不参与滤波调参。

正式策略统一使用 `Strategy` 后缀，状态估计统一使用 `Model` 后缀。日志名固定为 `hold`、`predict_to_now`、`causal_prediction` 和 `linear_slerp`。

## 四种输出策略

### HoldStrategy

锁存最近控制点并执行零阶保持，不外推、不插值。Arrival-Hold 和 Capture-Hold 都使用该策略，两者只改变世界系复合时刻。

### PredictToNowStrategy

每个渲染帧调用 `MotionModel.PredictAt(now)`，输出语义时刻等于当前渲染时刻。新重采的 `EgoAnchor w/o temporal synthesis` 使用 `KalmanModel + PredictToNowStrategy`，只关闭历史时序合成，不更换状态估计器。

### CausalPredictionStrategy

每个渲染帧请求当前时刻的 Kalman 预测，但将实际预测时域限制在最近观测后的固定上限内。新观测校正模型后，策略保存旧显示轨迹与新预测轨迹之间的完整位置和旋转残差，并按真实经过时间指数衰减。该残差融合保持校正边界连续，不使用未来观测，也不修改 Kalman 的测量噪声。

当前场景的 pilot 初值是 `maxPredictionHorizonSeconds=0.18` 和 `correctionHalfLifeSeconds=0.06`。这两个参数必须在 v4 正式采集前依据起停、回动、遮挡和帧率无关性测试冻结；配置指纹完整记录其生效值。

正式 render 日志使用独立字段记录 `prediction_horizon_ms`、位置/旋转校正残差和 `continuity_reset_count`。它们不复用观测年龄、`predict_ahead_ms` 或通用 residual；非因果策略的三个浮点字段写 `null`，异常重置计数写 `0`。

### LinearSlerpStrategy

缓存运动模型输出的控制点，目标时刻为：

```text
t_target = t_render - delay(t)
```

`delay(t)` 由采集至渲染观测年龄的非对称 EMA、自适应安全系数和延迟下限决定，并限制每秒变化速度。相邻控制点之间的位置使用 Linear，旋转使用最短弧 SLERP；不使用 One-Euro 内部导数作为样条切线。

新重采的场景显示名为 One-Euro Interpolation，schema 中稳定 variant ID 仍为 `One-Euro Anchor`。该配置开启采集时刻对齐和 VCD，使用与完整系统相同的生命周期与重获取开关，只关闭 StaticLock。

## 正式实验组合

| Variant | Alignment | Admission | Model | Strategy | StaticLock | Lifecycle / reacquire |
|---|---|---|---|---|---|---|
| Arrival-Hold | Arrival time | 合法性 | ConstantVelocity | Hold | 关 | 基线 |
| Capture-Hold | Capture time | 合法性 | ConstantVelocity | Hold | 关 | 基线 |
| One-Euro Anchor | Capture time | VCD | OneEuro | LinearSlerp | 关 | 与完整系统相同 |
| EgoAnchor | Capture time | VCD | Kalman | LinearSlerp | 开 | 完整 |
| EgoAnchor w/o capture-time alignment | Arrival time | VCD | Kalman | LinearSlerp | 开 | 完整 |
| EgoAnchor w/o VCD | Capture time | 合法性 | Kalman | LinearSlerp | 开 | 仅关闭 VCD 相关低分重获取 |
| EgoAnchor w/o temporal synthesis | Capture time | VCD | Kalman | PredictToNow | 开 | 完整 |
| EgoAnchor w/o StaticLock | Capture time | VCD | Kalman | LinearSlerp | 关 | 完整 |
| EgoAnchor Causal Prediction | Capture time | VCD | Kalman | CausalPrediction | 关 | 与 w/o StaticLock 配对 |

## 冻结参数

### OneEuroModel

| 通道 | minCutoff | beta | derivativeCutoff |
|---|---:|---:|---:|
| 位置 | 0.8 Hz | 6 | 2 Hz |
| 旋转 | 1 Hz | 1 | 2 Hz |

### KalmanModel

| 参数 | 值 |
|---|---:|
| `positionAccelerationNoise` | 0.002 m²/s³ |
| `positionMeasurementNoise` | 0.000004 m² |
| `rotationAccelerationNoise` | 0.2 rad²/s³ |
| `rotationMeasurementNoise` | 0.0004 rad² |

过程噪声采用连续白噪声加速度离散化：`Q = q_a [[dt^3/3, dt^2/2], [dt^2/2, dt]]`。测量噪声是冻结参数；VCD 只控制 admission，不根据分数在线修改 Kalman 噪声。上述参数由 v3 工作簿的只读工程诊断冻结，修改后的运行时必须完整重采五项任务，不能与 v3 论文结果混用。

### 历史目标时刻

`LinearSlerpStrategy` 使用 `latencySafetyMargin=1.15`、`minDelaySeconds=0.25`，延迟变化上限为每秒 50 ms。One-Euro Anchor 与完整 EgoAnchor 共享这组历史目标时刻语义。

### StaticLock

正式场景中，完整 EgoAnchor 以及保留 StaticLock 的三个消融必须使用同一组序列化参数。当前旋转相关冻结值包括：

- `enterAngSpeedDps=22`
- `unlockDriftDegrees=12`
- `deadbandDegrees=3`
- `unlockEvidenceDegrees=20`
- `headSettleSeconds=0.6`

头动只影响头停后的沉降窗和位置容忍；真实物体运动证据不能在头动期间被冻结。距离自适应只放大位置通道，旋转阈值保持不变。

## 场景与日志

正式场景 `EgoAnchor-Experiment12.unity` 使用九个唯一 runtime，由一个 `AnchorRuntimeHub` 分发同一候选流：四个实验一配置、四个实验二单组件消融，以及一个 `EgoAnchor Causal Prediction` 配对策略对照。实验一和实验二共享采用 Linear/SLERP 的完整 EgoAnchor runtime，避免同一方法出现两套内部状态。

每个 variant 的 manifest 配置必须包含：

- `motion_model`、`smoothing_strategy` 和 `quality_gate`
- alignment、VCD、temporal synthesis、StaticLock 和重获取开关
- 覆盖坐标补偿、模型、策略、生命周期和 StaticLock 数值的 `configuration_fingerprint`
- 绑定完整指纹的 per-variant `config_hash`

Python Stage 1 QC 会按 Unity 的 FNV-1a 顺序重算哈希。当前场景和正式批次使用 `variant_matrix_id=exp12_9_causal_v3`：完整系统及三个组件对照采用 Linear/SLERP，因果预测作为关闭 StaticLock 的独立策略对照。配置缺失指纹、字符串布尔值、名称与组件错配或任意缺项都会阻止正式发布。

## 验证

```powershell
dotnet build EgoAnchor_Unity/EgoAnchor.Tests.csproj --no-restore
dotnet build EgoAnchor_Unity/Assembly-CSharp.csproj --no-restore
```

Unity Editor 还必须运行 `EgoAnchor.Tests` EditMode 测试。场景契约测试会读取 YAML，核对九个 runtime、层级、模型、策略、门控、重获取和 StaticLock 绑定。
