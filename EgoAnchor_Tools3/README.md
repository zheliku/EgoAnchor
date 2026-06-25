# EgoAnchor_Tools3 — 离线实时升采样仿真

把真实录制的 **~5fps 观测 pose** 当作实时输入，用多种**实时预测/外推**算法生成 **~60fps 连续渲染轨迹**，
并画出对比曲线。完全自包含（不依赖 Unity DLL，自带 Vec3/Quat 数学）。

> 核心：**这不是插值**。每个渲染时刻只用「该时刻之前已经到达的观测」做外推，输出当前最新 pose——
> 和真机上 Unity 每帧要干的事一致。两次观测之间那 ~200ms 由算法实时填出一条连续平滑曲线。

---

## 怎么跑

```bash
dotnet run --project EgoAnchor_Tools3/AnchorUpsampleSim3.csproj -c Release -- \
  --session <session_dir> \
  [--out <output_dir>] \
  [--render-hz 60] \
  [--latency-ms 300 | --no-latency] [--latency-jitter-ms 60] \
  [--zoom-start 72.8 --zoom-end 75.7]
```

- `--session`：eval session 目录（里面要有 `*_unity_output.jsonl`）
- `--out`：输出目录，默认 `<session>/tools3_upsample_sim`
- `--render-hz`：渲染帧率。**不指定则自动从录制实测**（取 `render_mono_ms` 间隔中位数）
- `--latency-ms`：采集-渲染延迟（ms）。**不指定则自动从录制实测**（见下）。`--no-latency` 还原零延迟
- `--latency-jitter-ms`：延迟抖动幅度（确定性，默认 60ms），模拟真机延迟非恒定
- `--zoom-start/--zoom-end`：额外输出一个时间窗的放大图（看平滑细节，强烈建议用）

---

## ⚠️ 采集-渲染延迟（必读，否则离线结果不可信）

**这是本工具最重要的一点。** 真机上一帧观测从被拍下（capture）到能用于渲染，要经过
Python 推理（~159ms）+ 网络传输 + 排队，实测**采集-渲染延迟中位 ~300ms**，比观测周期（~208ms）还大。

早期仿真在 capture 时刻就立即交付观测（零延迟），导致**「离线平滑、真机抖」**：
离线 `now - 最近观测` 只有一帧（16ms），真机却有 300ms。C 路延迟插值尤其会被坑——
离线看着完美，真机锯齿跳变。

现在 `RealtimeSimulator` 把观测的**交付时刻**推迟到 `capture + 延迟(+抖动)`，而观测自带的时间戳
仍是 capture 时间（与真机 `source_capture_mono_ms` 语义一致）。**默认自动从录制实测延迟和渲染帧率**
（`render_mono_ms - source_capture_mono_ms` 中位数），让离线时序对齐该 session 真机。

**所以：** 离线对比策略时**不要加 `--no-latency`**（那是旧的不可信行为）。默认即复现真机延迟。
要专门看「无延迟理想情况」才用 `--no-latency`。

已验证数据集：
- `EgoAnchor_Python/data/eval/20260614_130324_controller_right`（464 帧观测，~4.65fps，99.7s）
- `EgoAnchor_Python/data/eval/offline_data`（253 帧观测，~5.28fps，47.9s）

产出：每算法一张 6 子图 PNG + 一张总对比 PNG（含 zoom 版）+ 每算法 `render_*.jsonl` + `observations.jsonl`。

---

## 数据来源（关键约定）

观测 pose **不是** `python_runtime.jsonl` 里的 `pose_result`（那里只有分数/耗时，没有坐标）。
真正的 ~5fps 观测 pose = `*_unity_output.jsonl` 里 **primary 变体**（egoanchor，`is_primary:true`）的
**`aligned_raw_pos` / `aligned_raw_rot`**，按 `source_frame_id` **去重**，时间戳用 `source_capture_mono_ms`。
（详见 `Data/ObservationLoader.cs`。）

---

## 仿真驱动（`Sim/RealtimeSimulator.cs`）

维护一个固定步长（60fps = 16.67ms）的渲染时钟，从第一帧观测时间跑到最后一帧之后一个观测周期。每个渲染 tick：

1. 若时钟越过了下一帧观测的 capture 时间 → 先把该观测交给预测器（`OnObservation`）；
2. 调 `PredictAt(now)` 取这一时刻的渲染 pose，记录。

预测器接口 `IPredictor`（`Sim/IPredictor.cs`）只有两个核心方法：
- `OnObservation(obs)`：新观测到达时更新内部状态；
- `PredictAt(t)`：外推到渲染时刻 t（只用已到达观测）。

旋转统一在「相对参考四元数的切空间」里处理（Log → 滤波/外推 → Exp），等价于估计姿态 + 角速度，无 gimbal lock。

---

## 四个 baseline 算法

### 1. `raw_zoh` —— 什么都不处理（零阶保持）
**逻辑**：收到观测就存下，渲染时永远输出最近一帧，直到下一帧才**硬跳变**。
**效果**：阶梯状轨迹，每 ~200ms 一次跳，完全不平滑。作为对照基线。
文件：`Predictors/RawZohPredictor.cs`

### 2. `kalman_cv` —— 卡尔曼滤波 + 预测
**逻辑**：把轨迹建模为状态 `[位置, 速度]`（常速度模型）。
- 平移：x/y/z 三路独立的一维 CV Kalman（`Predict` 外推协方差 + `Correct` 用测量校正）；
- 旋转：在四元数切空间里同样跑三路 CV Kalman（估计姿态 + 角速度）；
- 渲染：用状态方程 `pos + vel*ahead` 外推到任意时刻，`ahead` 限幅 0.18s。

测量噪声 R 设得很小（0.0004）→ 高度信任观测，近似过点，同时滤抖。
**效果**：能跟、能滤噪，但 `ahead` 用完后会保持，仍有可见的「平段+跳变」。
文件：`Predictors/KalmanPredictor.cs`, `Predictors/ScalarCvKalman.cs`
（与 Unity 侧 `KalmanModel` 的常速度状态估计结构对应。）

### 3. `deadreckoning_spline` —— 航位推测 + 样条修正
**逻辑**（网络游戏经典方案，专为「零延迟 + 平滑无跳」设计）：
- **航位推测**：两帧之间用上一帧位置 + 估计速度一阶外推 `x = x0 + v0*Δt`；
- **样条修正**：新观测到达时，不硬跳，而是构造一段**三次 Hermite** 曲线，在一个修正窗口
  （默认 200ms ≈ 一个观测周期）内，从「当前渲染 pose + 当前渲染速度」平滑过渡到
  「新观测 pose + 新观测速度」。Hermite 同时匹配两端**位置和速度** → **C¹ 连续**：
  位置不跳、速度不跳，窗口末端命中新观测。

整条轨迹 = 一段段首尾速度连续的 Hermite 拼接，视觉上最连续。
**效果**：四者中**最平滑**（step jitter 最小）。代价：方向突变时有轻微 overshoot，快速运动时有轻微 lag——
这是 DR「近似过点」的固有特性。
文件：`Predictors/DeadReckoningSplinePredictor.cs`

### 4. `oneeuro_predict` —— One Euro Filter + 预测
**逻辑**：One Euro 是自适应低通——截止频率 `fc = minCutoff + beta*|平滑速度|`，
信号慢时更平滑、信号快时更跟手。在平滑值之上叠加一阶外推 `xHat + dxHat*ahead`（`ahead` 限幅 0.12s）抵消滞后。
位置 x/y/z 各一路标量 One Euro，旋转在切空间三路。
**效果**：平滑、抗抖好，但快速运动时**滞后明显**（峰值被削、转角变圆）。
文件：`Predictors/OneEuroPredictor.cs`
（与 Unity 侧 `OneEuroModel` 对应。）

---

## 平滑度指标

控制台打印相邻 render 帧的步长 RMS（位置 mm / 旋转 deg）——**越小越平滑、越无跳变**。
两个数据集上排名一致：`deadreckoning_spline` < `oneeuro_predict` ≲ `kalman_cv` < `raw_zoh`。

示例（20260614 数据集）：

| 算法 | posStepRMS (mm) | rotStepRMS (deg) |
|---|---|---|
| raw_zoh | 4.01 | 1.50 |
| kalman_cv | 3.98 | 1.26 |
| oneeuro_predict | 2.60 | 0.98 |
| **deadreckoning_spline** | **1.30** | **0.48** |

> 注意：step RMS 只衡量「相邻帧平滑度」，不衡量「准确度/滞后」。要看准不准、滞后多少，看 zoom 图。

---

## 旋转曲线为什么用「旋转向量」而不是欧拉角

录制文件里的 `*_euler_deg` 用的是 Unity 内部 ZXY 提取，手工复现有几度误差，且欧拉角本身有 gimbal-lock 跳变，
不适合判断「旋转是否平滑」。所以图里旋转画的是 **旋转向量 RotVec**（= 轴 × 角度，度）：与四元数一一对应（±180° 内），
无 gimbal lock，平滑当且仅当旋转平滑，正是各 estimator 在切空间里操作的量。（`Core/Rotation.cs` 另提供 ZXY 欧拉角作参考。）

---

## 下一步：接入 EgoAnchor 的 posescore

baseline 已就绪。后续在某个 baseline（最可能是 Kalman 或 DR+spline）之上，用观测自带的
`reliability_score`（已在 `Observation.Score` 里读入）做：
- 低分时减小修正幅度 / 增大测量噪声（少信任坏观测）；
- 低分时缩短外推 ahead（别基于坏速度乱飞）；
- 静止检测 + 锁定。

新算法只要实现 `IPredictor` 加进 `Program.cs` 的列表即可，自动出图、出指标、可对比。
