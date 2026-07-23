# EgoAnchor Kalman 预测修正与离线测试报告

## 1. 交付内容

本包包含两个可直接放回 Unity 工程的替换/新增文件：

- `code/KalmanModel.cs`：修正后的常速度 Kalman 状态估计器；
- `code/ContinuousPredictStrategy.cs`：有界预测与校正连续性策略。

同时包含 Python 离线镜像、逐 episode 指标、测试图和完整复现实验结果。

## 2. 修改内容

### 2.1 Kalman 状态估计

旧实现离线回放对应的过程协方差近似为 `I * q * dt`。修正版改为连续白噪声加速度常速度模型：

\[
Q=q_a
\begin{bmatrix}
\Delta t^3/3 & \Delta t^2/2\\
\Delta t^2/2 & \Delta t
\end{bmatrix}.
\]

同时完成以下修改：

- Inspector 参数改为测量标准差，内部再平方为方差，避免单位混淆；
- 使用 Joseph form 更新协方差；
- 对协方差执行对称性和半正定数值保护；
- 拒绝非递增 measurement timestamp；
- 采用 4σ soft innovation gate，通过增大本次测量方差限制异常更新；
- 旋转切空间在每个接受观测后 rebase，避免固定参考在大角度旋转时发生 log-map wrap。

### 2.2 逐帧预测输出

仅修正 Kalman 并不能保证可见轨迹连续。`ContinuousPredictStrategy` 增加：

- 最大预测时域：180 ms；
- 校正残差半衰期：60 ms；
- 新观测校正后，以旧显示轨迹与新预测轨迹的残差保证 C0 连续；
- 位置与旋转残差安全限幅；
- 衰减按真实时间计算，不依赖 60/72/90 Hz 的具体渲染帧率。

冻结的探索性参数为：

| 参数 | 数值 |
|---|---:|
| Position acceleration-noise density | 0.10 m²/s³ |
| Position measurement std | 8 mm |
| Initial velocity std | 0.50 m/s |
| Innovation gate | 4σ |
| Maximum prediction horizon | 180 ms |
| Correction residual half-life | 60 ms |

这些参数是在当前日志上探索性选择的，不能视为独立验证结果。

## 3. 测试设置

真实日志测试固定：

- 同一批 capture-time aligned、VCD accepted candidates；
- 同一 render timeline；
- StaticLock 关闭；
- Buffered-Hermite 使用日志中的 pre-StaticLock 输出；
- Legacy direct 的 Python 镜像与此前离线回放逐帧完全一致，位置差 median/P95/max 均为 0 mm。

此外执行：

- 10,000 次不规则时间步协方差稳定性测试；
- 10 Hz 测量、170 ms 到达延迟、90 Hz 渲染的在线起停合成测试；
- 超过 360° 的旋转切空间 wrap 合成测试。

## 4. 真实日志结果

| 方法 | 静止帧间 P95 (mm) | 平移 Lag / residual (ms/mm) | 到达校正步长 P95 (mm) | Start response (ms) | 遮挡 P95 (mm), >40 | 旋转 Lag / residual (ms/deg) |
|---|---:|---:|---:|---:|---:|---:|
| Legacy direct | 2.619 | 170 / 26.717 | 39.006 | 188.2 | 9.596, 0/9 | 200 / 6.202 |
| Corrected direct | 4.722 | 65 / 17.948 | 27.070 | 167.5 | 52.243, 6/9 | 97.5 / 7.143 |
| **Corrected continuous** | **1.892** | **165 / 14.530** | **6.723** | **242.4** | **6.003, 0/9** | **207.5 / 5.696** |
| Buffered-Hermite | 1.453 | 320 / 4.814 | 6.848 | 284.6 | 5.531, 0/9 | 330 / 2.608 |

### 4.1 相对旧版直接预测

Corrected continuous 相比 Legacy direct：

- 平移 lag-aligned residual：26.717 → 14.530 mm，下降 45.6%；
- 观测到达附近显示步长 P95：39.006 → 6.723 mm，下降 82.8%；
- 静止帧间增量 P95：2.619 → 1.892 mm，下降 27.8%；
- 平移有效时延：170 → 165 ms，基本不变；
- 遮挡 P95：9.596 → 6.003 mm；
- 代价是 start response：188.2 → 242.4 ms。

### 4.2 为什么不能只替换 Q/R 后继续直接显示

Corrected direct 获得了最低的平移时延和更低的平移残差，但：

- 静止帧间增量升至 4.722 mm；
- 观测到达校正步长 P95 仍为 27.070 mm；
- 遮挡时 6/9 episode 超过 40 mm。

这说明 Kalman 数学模型修正后，速度估计更积极，但如果没有预测时域上限和 correction continuity，渲染抖动及遮挡外推仍然存在。状态估计与显示策略必须同时修改。

### 4.3 与 Buffered-Hermite 的关系

Corrected continuous 将平移时延由 Buffered-Hermite 的 320 ms 降至 165 ms，并将起动响应由 284.6 ms 降至 242.4 ms；但 Buffered-Hermite 的平移 residual、静止稳定性和旋转 residual 仍然更好。

因此两种策略代表不同工作点：

- Corrected continuous：响应优先的可部署预测配置；
- Buffered-Hermite：稳定与轨迹保真优先的配置。

## 5. 合成测试

在线起停合成测试的 current-time RMSE：

- Legacy direct：23.13 mm；
- Corrected direct：18.32 mm；
- Corrected continuous：22.15 mm。

Continuous 结果的 current-time RMSE 较 Corrected direct 高，是因为 residual repayment 主动引入短时显示滞后；其主要收益是消除校正跳变，而不是最小化零延迟 current-time RMSE。因此应联合报告 lag、lag-aligned residual 和 correction-step 指标。

旋转合成测试中：

- 固定切空间参考 RMSE：13.81°；
- 每次观测 rebase 后 RMSE：1.47°。

## 6. 建议

1. 工程默认使用 `KalmanModel + ContinuousPredictStrategy`，不要直接使用 `PredictivePassthroughStrategy` 驱动正式显示。
2. `PredictivePassthroughStrategy` 可保留为机制消融，用于展示未经连续性处理的直接外推问题。
3. 论文实验二若要设置强预测 baseline，应增加 Corrected continuous；原始 Predict-to-Now 只能表述为 direct prediction ablation。
4. 在更新论文正式数值前，使用新代码重新采集至少一轮 Task 1–5。当前测试使用旧候选流离线回放，且参数在同一数据上选择。
5. Unity 集成后必须记录：innovation、Kp/Kv、used R、prediction horizon、residual magnitude、timestamp rejection count 和每次 correction 前后显示位姿。

## 7. 限制

当前环境没有 UnityEngine 程序集，因此无法在此直接编译 Unity C# 文件。C# 数学逻辑已由 Python 镜像测试；最终仍需在项目中完成编译和设备运行测试。真实日志的位置与旋转分别完成离线回放，但 rotation rebase 使用独立的 Python SO(3) 镜像，需通过新 Unity 日志再次验证逐帧一致性。
