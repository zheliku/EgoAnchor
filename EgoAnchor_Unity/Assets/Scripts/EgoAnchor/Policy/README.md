# EgoAnchor Unity 锚定策略

本目录把低频、异步的世界系位姿观测转换为逐渲染帧对象锚点。正式链路由运动模型、
输出策略、VCD 接纳、生命周期和可选 StaticLock 组成，各模块使用同一观测时间语义。

## 模块边界

一个 `AnchorPolicyHost` 绑定一个 `MotionModel` 和一个 `SmoothingStrategy`：

```text
MotionModel                          SmoothingStrategy
|- ConstantVelocityModel            |- HoldStrategy
|- OneEuroModel                     |- LinearSlerpStrategy
`- KalmanModel                      |- SmoothedKalmanExtrapolationStrategy
                                    `- HermiteStrategy
```

- `MotionModel` 估计位置、姿态、线速度和 body-local 角速度。
- `SmoothingStrategy` 生成逐渲染帧输出。
- `AnchorPolicyHost` 负责 VCD 接纳、生命周期、重获取和模块顺序。
- `EgoAnchorStaticLockModule` 负责静止锚定与解锁。
- `PoseToAnchorRuntime` 负责 `frame_id` 采集时刻对齐和坐标补偿。

稳定日志名为 `hold`、`linear_slerp`、`smoothed_kf_extrapolation` 和
`hermite_interpolation`。废弃策略不保留兼容入口。

## 输出策略

### HoldStrategy

锁存最近控制点并零阶保持，不外推、不插值。Arrival-Hold 和 Capture-Hold 只在世界系
复合时刻上不同。

### LinearSlerpStrategy

目标时刻为 `t_render - delay(t)`。自适应延迟由采集至渲染观测年龄的非对称 EMA、安全系数
和延迟下限决定，变化速度限制为每秒 50 ms。相邻控制点之间的位置用 Linear，旋转用最短弧
SLERP；目标时刻晚于最新控制点时保持最新值。

One-Euro Anchor 和完整 EgoAnchor 使用相同的目标时间线。前者使用 `OneEuroModel` 且关闭
StaticLock，后者使用 `KalmanModel` 并开启 StaticLock。

### SmoothedKalmanExtrapolationStrategy

每帧查询当前时刻的 Kalman 状态，但外推不超过最近观测后的固定上限。新观测校正模型后，
策略保存旧显示轨迹与新模型轨迹的位姿残差，并按真实时间半衰期衰减，因此校正边界保持
C0 连续。该策略不读取未来控制点，也不修改 Kalman 测量噪声。

当前 pilot 初值为 `maxPredictionHorizonSeconds=0.18`、
`correctionHalfLifeSeconds=0.06`。正式采集前需通过起停、遮挡、旋转和刷新率检查后冻结。
render 日志记录实际预测时域、位置/旋转校正残差与连续性重置计数；其他策略对应的浮点
诊断写 `null`，重置计数写 `0`。

### HermiteStrategy

它与 `LinearSlerpStrategy` 共用历史目标时间线，在相邻 Kalman 控制点之间执行 6DoF Hermite
插值。位置切线来自世界系线速度；旋转在 SO(3) Log 切空间插值，并用右雅可比统一第二端点
的 body-local 角速度。端点切线模长限制为弦长的固定倍数，目标时刻晚于最新控制点时保持
最新值，不执行末段外推。

当前 pilot 初值为 `latencySafetyMargin=1.15`、`minDelaySeconds=0.25` 和
`tangentChordRatio=3`。

## 正式九路矩阵

| Variant | Alignment | Admission | Model | Strategy | StaticLock |
|---|---|---|---|---|---|
| Arrival-Hold | Arrival time | 合法性 | ConstantVelocity | Hold | 关 |
| Capture-Hold | Capture time | 合法性 | ConstantVelocity | Hold | 关 |
| One-Euro Anchor | Capture time | VCD | OneEuro | LinearSlerp | 关 |
| EgoAnchor | Capture time | VCD | Kalman | LinearSlerp | 开 |
| EgoAnchor w/o capture-time alignment | Arrival time | VCD | Kalman | LinearSlerp | 开 |
| EgoAnchor w/o VCD | Capture time | 合法性 | Kalman | LinearSlerp | 开 |
| Smoothed KF Extrapolation | Capture time | VCD | Kalman | SmoothedKalmanExtrapolation | 关 |
| EgoAnchor w/o StaticLock | Capture time | VCD | Kalman | LinearSlerp | 关 |
| Hermite Interpolation | Capture time | VCD | Kalman | Hermite | 关 |

实验一使用前四个系统配置。实验二包含三个单组件消融和
`Smoothed KF Extrapolation vs. Hermite Interpolation` 配对比较。两路时序策略共享
采集时刻对齐、VCD、Kalman、生命周期、重获取、候选序列和关闭 StaticLock 的配置，只改变
逐帧输出策略。完整 EgoAnchor 仍是 Kalman + Linear/SLERP + StaticLock。

## 冻结模型参数

One-Euro 参数：

| 通道 | minCutoff | beta | derivativeCutoff |
|---|---:|---:|---:|
| 位置 | 0.8 Hz | 6 | 2 Hz |
| 旋转 | 1 Hz | 1 | 2 Hz |

Kalman 参数：

| 参数 | 值 |
|---|---:|
| `positionAccelerationNoise` | 0.002 m²/s³ |
| `positionMeasurementNoise` | 0.000004 m² |
| `rotationAccelerationNoise` | 0.2 rad²/s³ |
| `rotationMeasurementNoise` | 0.0004 rad² |

过程噪声使用连续白噪声加速度离散化：
`Q = q_a [[dt^3/3, dt^2/2], [dt^2/2, dt]]`。VCD 只控制接纳，不在线修改测量噪声。

完整 EgoAnchor 及保留 StaticLock 的两个组件消融共享同一组 StaticLock 参数，其中
`enterAngSpeedDps=22`、`unlockDriftDegrees=12`。头动只影响头停后的沉降窗和位置容忍，
不能冻结真实物体运动证据。

## 场景与验证

正式场景 `EgoAnchor-Experiment12.unity` 使用九个唯一 runtime，由一个 `AnchorRuntimeHub`
分发同一候选流。manifest 写入 `variant_matrix_id=exp12_9_smoothed_hermite_v4`，并为每个
variant 记录模型、策略、门控、能力开关、完整配置指纹和 FNV-1a 哈希。Python Stage 1 QC
按相同顺序复算哈希并拒绝名称、组件或配置不一致的数据。

验证命令：

```powershell
dotnet build EgoAnchor_Unity/EgoAnchor.Tests.csproj --no-restore
dotnet build EgoAnchor_Unity/EgoAnchor.csproj --no-restore
```

Unity Editor 还需运行 `EgoAnchor.Tests` EditMode 测试。完成 Quest 上的 pilot 并冻结两路
时序策略参数后，才能开始 v4 正式 Task 1--5 采集。
