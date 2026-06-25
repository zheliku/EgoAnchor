# EgoAnchor Technical Flow

> 代码事实推导版，基于实现与协议整理，不依赖仓库内说明文档。

## 1. 目标

EgoAnchor 的主线不是普通 pose tracking，而是把异步 6DoF object pose 流变成稳定、世界一致、可恢复的 real-object anchor。
核心链路是：

`Unity 采集 -> Python 感知 -> Python 结果回传 -> Unity 帧对齐 -> Unity policy 与渲染`

这里最重要的语义边界是：

- Python 只输出 `camera-space object pose + reliability`。
- Unity 必须按 `frame_id` 回查 capture-time camera pose，再合成 world anchor。
- arrival-time 的头显姿态只可用于对照诊断，不能替代 frame-aligned 对齐。

## 2. 协议与通道

### 2.1 三平面

| 平面 | 方向 | 载体 | 语义 |
| --- | --- | --- | --- |
| Data Plane | Unity -> Python | ZMQ PUB/SUB | `QuestStereoFrame`、`QuestCameraInfo` |
| Message Plane | Python -> Unity | NATS pub/sub | `PoseResult`、`AnchorStatusEvent`、`ServerHeartbeat` |
| Command Plane | Unity -> Python | NATS request/reply | reset / reacquire / control |

### 2.2 头部字段

`MessageHeader` 统一携带：

`message_id, request_id, session_id, client_id, anchor_id, frame_id, unity_frame, sender_mono_ms, created_unix_ms, schema_version`

其中：

- `frame_id` 是正式对齐主键。
- `session_id` 用来识别 Unity 一次采集会话。
- `request_id` 用来做命令幂等去重。
- `sender_mono_ms` 和 `created_unix_ms` 只用于时序诊断。

### 2.3 主要消息

- `QuestStereoFrame`：左右 JPEG 图像 + 尺寸 + 质量。
- `QuestCameraInfo`：左右内参、畸变、基线、传感器/active/current 分辨率、lens pose。
- `PoseResult`：相机坐标系中的对象位姿 + 可靠性 + 渲染质量诊断。
- `AnchorStatusEvent`：状态机/命令/恢复事件流。
- `ServerHeartbeat`：输入是否就绪、最新帧号、版本、吞吐、队列长度、错误信息。
- `CommandAck`：命令是否被接受，不表示命令已执行完成。

## 3. Unity -> Python

### 3.1 会话与帧

Unity 侧每次发布会话都会生成新的 `session_id`。同一会话里：

- stereo 和 camera_info 共用同一个 session。
- `frame_id` 单调递增。
- `QuestCameraInfo.header.frame_id` 不承担图像帧对齐职责，正式图像帧用 `QuestStereoFrame.header.frame_id`。

### 3.2 采集与编码

双目采集流程可抽象为：

1. 读取左右 Passthrough texture。
2. 读取左右相机世界位姿。
3. 计算中心参考相机位姿。
4. 通过短历史缓冲把图像帧绑定到略早的 camera pose，补偿 Passthrough 时间滞后。
5. 将左右图压缩成 JPEG。
6. 以 multipart `[topic_utf8, protobuf_payload_bytes]` 发往 Python。

### 3.3 采集时序

对于第 `f` 帧，Unity 记录：

- 左/右/中心相机采集时刻位姿 `T^w_{c,f}`
- 发送端单调时间 `t_s`
- Unity 帧号 `u`

图像和 pose 的绑定不是 arrival-time，而是 capture-time。

### 3.4 CameraInfo

`QuestCameraInfo` 只负责提供相机参数快照，核心是：

- `K = (fx, fy, cx, cy)`
- `b`，双目基线
- 分辨率与 active array
- lens pose

Python 端主要使用左目内参与基线；畸变和 lens pose 作为协议保留与诊断信息。

## 4. Python 接收与缓存

### 4.1 ZMQ latest-drain

Python 的 ZMQ 接收器按 topic 做 latest-drain：

- socket 里只保留最新消息。
- 同 topic 的旧帧直接丢弃。
- 只接受 multipart `[topic, payload]`。

这意味着 Python 侧天然是实时链路，而不是历史补帧链路。

### 4.2 session / frame 去重

Python 对 stereo 还有两层保护：

- 同一 session 内，`frame_id` 不能倒退或重复。
- session 变化会触发输入缓存重置。

这避免 Unity 重启后旧帧混入新会话。

### 4.3 runtime 主循环

Python 主循环顺序可概括为：

1. 执行已入队命令。
2. 轮询最新 stereo / camera_info。
3. 若暂停则只发心跳。
4. 更新输入就绪状态。
5. 按节流条件决定是否运行感知 pipeline。
6. 生成 `PoseResult` 并发布。
7. 发布状态事件与心跳。

命令处理、pipeline 和 GPU 状态都由单一 runtime owner 顺序管理。

## 5. Python 感知 pipeline

### 5.1 总流程

单帧处理可抽象为：

1. 解码 stereo JPEG。
2. 将左右图统一到算法处理分辨率。
3. 更新相机内参映射 `K'`。
4. 生成/跟踪目标 mask。
5. 估计双目深度。
6. 对目标做 register 或 track。
7. 必要时做渲染质量回查。
8. 汇总成 `PoseObservation`。

### 5.2 标定映射

若将 Quest 原始标定坐标系映射到处理分辨率，中心裁剪模式下可写成：

`fx' = fx * s_x, fy' = fy * s_y`

`cx' = (cx - crop_x) * s_x, cy' = (cy - crop_y) * s_y`

纯缩放模式则直接对内参按比例缩放。

### 5.3 深度估计

FFS 的米制深度可写成：

`Z = (fx * s * b) / d`

其中 `d` 是视差，`s` 是缩放比例，`b` 是双目基线。

深度会再被截断到有效范围外清零。

### 5.4 分割

初始分割后端可以是 YOLOE-26 或显式启用的 SAM3。
分割只负责给出目标 mask，不负责位姿。

已注册后，系统会优先用 Cutie 传播 mask；如果 mask 持续丢失，会回到 detect / re-register 路径。

### 5.5 Register / Track

感知链路分两种核心模式：

- `REGISTER`：在有 mask 和足够深度证据时，FoundationPose 从头注册。
- `TRACK`：已有注册状态后，使用新 RGB-D 继续跟踪。

Track 后会做跳变检查：

- 平移增量超过阈值则视为异常。
- 旋转增量超过阈值则视为异常。

异常后会清空当前注册态，并在具备 mask 时尝试重新注册。

### 5.6 渲染质量回查

TRACK 后可再做一次渲染质量检查，用于软重注册判定。
它分成两部分：

- 颜色重投影
- 深度对齐

颜色和深度不是简单相加，而是分别打分、再进入可靠性合成。

## 6. 可靠性模型

### 6.1 总分结构

Python 的最终可靠性可抽象为：

`R = G * Q * C`

其中：

- `G` 是 gate
- `Q` 是 quality
- `C` 是 confidence

### 6.2 Gate

`G = S_phase * S_reject`

其中：

- `S_phase`：TRACK / REGISTER / RE_REGISTER 取 1，其它阶段偏低
- `S_reject`：近期 track reject 越多，门控越低

### 6.3 Quality

Quality 由几何核心和有界调制组成：

`Q = G_geo * M_mask`

有界 mask 调制可写成：

`M_mask = m_f + (1 - m_f) * S_mask`

其中 `m_f` 是 mask floor。

### 6.4 几何核心

有效几何证据只来自两路：

- 颜色重投影 `S_rep`
- 深度对齐 `S_dep`

几何核心是有效子分的加权对数几何平均：

`G_geo = exp( sum_i w_i log(max(s_i, ε)) / sum_i w_i )`

没有任何有效几何证据时，`G_geo = 1`，不武断降分。

### 6.5 颜色重投影

颜色重投影不是全图比较，而是：

1. 在渲染 mask 与观测 mask 的交集上取核心区域。
2. 变到 LAB。
3. 做零均值归一化相关。
4. 将 `[-1, 1]` 映射到 `[0, 1]`。

若核心区域没有颜色方差，则颜色项视为无效，不惩罚。
纯色 / 无纹理目标会走这个分支。

### 6.6 深度对齐

深度对齐只在有效覆盖率足够时生效。
自适应阈值：

`τ_z = max(τ_min, ρ * ||t||)`

其中 `||t||` 是物体到相机的距离。

在渲染深度与观测深度的交集上：

`S_inlier = mean(|Z_r - Z_o| < τ_z)`

`S_med = clamp(1 - median(|Z_r - Z_o|) / (3 τ_z), 0, 1)`

`S_dep = 0.5 * S_inlier + 0.5 * S_med`

### 6.7 Confidence

confidence 是连续高质量帧的 warmup：

- 连续质量好时逐帧累积
- 质量差时回退
- 没有几何证据时保持不动

可写成一个离散计数器 `n`，再映射成：

`C = 0.5 + 0.5 * n / N`

其中 `N = 10`。

## 7. Python -> Unity

### 7.1 PoseResult

`PoseResult` 里最重要的是：

- `has_pose`
- `pose_matrix_cv_camera`
- `phase`
- `pose_source`
- `reliability_score`
- `score_phase / score_reprojection / score_depth / score_mask / score_reject / score_confidence`
- `render_quality_*`
- `server_receive_mono_ms`
- `server_publish_mono_ms`

其中 `pose_matrix_cv_camera` 是 row-major 4x4。

### 7.2 Matrix 约定

Python 输出的 row-major 4x4 中：

- 平移在 `[3, 7, 11]`
- forward 在 `[2, 6, 10]`
- up 在 `[1, 5, 9]`

Unity 端再把它恢复成 OpenCV 相机坐标系下的 object pose。

### 7.3 状态与心跳

Python 还会发布：

- `AnchorStatusEvent`：状态迁移、reset、reacquire、pause、resume、错误
- `ServerHeartbeat`：输入是否就绪、最新 stereo frame_id、camera_info 版本、runtime FPS、队列长度、最后错误

`AnchorStatusEvent` 是事件流，不应像 pose 一样只保留最新一条。

## 8. Unity 接收与处理

### 8.1 NATS 订阅

Unity 侧把消息分成两类：

- `PoseResult` / `ServerHeartbeat`：latest-only
- `AnchorStatusEvent`：事件队列

后台线程只做收包和排队，主线程负责 Protobuf 解析与状态更新。

### 8.2 frame-aligned 对齐

Unity 端的正式锚定必须按 `frame_id` 回查历史相机 pose：

`T^w_o(f) = T^w_{c,f} * T^c_o(f)`

其中 `T^c_o(f)` 是从 OpenCV camera pose 转成 Unity camera-local pose 后的结果。

OpenCV 到 Unity 的相机本地轴变换可以写成：

`R_u = S * R_cv * S,  S = diag(1, -1, 1)`

平移则做对应的 y 轴翻转。

这一步是项目的核心语义边界：

- **正式锚定** 用 capture-time pose
- **arrival-time raw** 只用于诊断对照

### 8.3 诊断与对照

Unity 还会尝试构造 arrival-time raw pose，但它不作为正式 anchor 输出。
它的唯一作用是帮助观察“如果直接用最新头显位姿会发生什么”。

### 8.4 policy 输入

对齐后的 world pose 会被打包为 `AnchorObservation`。
它携带：

- `MeasurementTimeSeconds`：优先 capture time
- `ReliabilityScore`
- `ScoreDepth / ScoreReprojection / ScoreConfidence`
- `DepthValid / ReprojValid`
- 采集时刻头部 pose

这保证后续 motion model、smoothing、static lock 都共享同一个测量时间轴。

## 9. Unity policy

### 9.1 总结构

Unity policy = `MotionModel + SmoothingStrategy + optional score gate + optional static lock`

它只负责把已经对齐好的 world pose 变成每帧稳定输出，不再处理网络或 Protobuf。

### 9.2 MotionModel

三种模型：

- `ConstantVelocityModel`
- `KalmanModel`
- `OneEuroModel`

共同点是都按 `MeasurementTimeSeconds` 驱动，而不是按到达时间。

#### ConstantVelocity

`p_t = p_{t-1} + v Δt`

`q_t = q_{t-1} ⊗ Exp(ω Δt)`

速度直接由相邻观测差分得到，不额外去噪。

#### Kalman

位置与旋转都用常速度 Kalman。
位置是三路 1D CV Kalman，旋转在切空间里做三路 CV Kalman。

#### One Euro

One Euro 的核心是自适应低通：

`dx_hat` 先低通；

`f_c = f_min + β |dx_hat|`

再用 `f_c` 过滤信号本身。

### 9.3 SmoothingStrategy

三种策略：

- `RawPassthroughStrategy`
- `BlendStrategy`
- `DelayedInterpStrategy`

#### RawPassthrough

零阶保持，不外推不插值。它就是 raw baseline。

#### Blend

零延迟外推 + 残差融合：

`y_t = predict(now) ⊕ residual_t`

新观测到来时不硬跳，而是把旧输出和新预测之间的残差慢慢还掉。

#### DelayedInterp

主动引入一段延迟 `Δ`，渲染目标取 `now - Δ`。
当目标落在两个控制点之间时做真实插值。

Hermite 版本会把切线模长限到弦长倍数，防止急停时的过冲振铃。

### 9.4 score gate

score gate 是可选的，只建议方法型变体开启。

典型门限是：

- 最低可靠性分
- 最大平移跳变
- 最大旋转跳变

它的定位是“拒绝坏观测”，不是“修平滑”。

### 9.5 static lock

static lock 是 EgoAnchor 方法的核心增强层，不是另一个滤波器。

它做的事很简单：

- 静止时冻结输出
- 运动时交回 smoothing 输出
- 通过多路证据决定何时解锁

锁定进入条件可概括为：

`v <= v0`
`ω <= ω0`
`score >= s0`
并且持续 `dwellSeconds`

解锁证据主要有：

- 持续低分
- 速度逃逸
- 观测共识的绝对漂移租绳
- score 加权 CUSUM

其中头动只会放宽位置/旋转阈值，不会改变几何语义。
远距离只放大位置通道，不放大旋转通道。

### 9.6 measurement time

policy 全部用 `MeasurementTimeSeconds`。
它优先等于 capture time，若 capture time 不可用才退化成到达时间。

这一步能避免“消息到达了但观测时间不是那一刻”的系统性偏差。

## 10. Unity 渲染

`DynamicObjectAnchor` 是最薄的一层：

- 只读 `PoseToAnchorRuntime` 的最终输出
- 只把 pose 应用到目标 Transform
- 没有网络、没有滤波、没有状态机

当没有有效 pose 时，可选择：

- 保持上一帧
- 或隐藏渲染器

## 11. 命令与恢复

### 11.1 命令类型

Unity -> Python 的命令包括：

- `reset`
- `reacquire`
- `control`

### 11.2 命令语义

handler 层只做：

- 类型校验
- 参数校验
- `request_id` 去重
- 入队
- 立即返回 `CommandAck`

真正执行发生在 Python runtime owner 线程的 tick 边界。

因此：

- `CommandAck.accepted=true` 只表示 Python 接受了命令
- 不表示 reset/reacquire 已经完成

### 11.3 回复状态

命令实际完成后，会通过 `AnchorStatusEvent` 和 `ServerHeartbeat` 再反馈回 Unity。

## 12. 一条完整链路

一个典型帧的完整链路可以概括为：

1. Unity 采集左右图和相机位姿。
2. Unity 记录 `frame_id` 对应的 capture-time camera pose。
3. Unity 发送 `QuestStereoFrame` 与 `QuestCameraInfo`。
4. Python latest-drain 接收最新输入。
5. Python 解码、分割、估深、register/track。
6. Python 计算可靠性并发布 `PoseResult`。
7. Unity 解析 `PoseResult`，按 `frame_id` 回查历史 camera pose。
8. Unity 合成 world anchor，再喂给 policy。
9. policy 做 smoothing / static lock。
10. `DynamicObjectAnchor` 将最终 pose 应用到场景物体。

这条链路的关键不是“更快地发 pose”，而是“在正确的时间轴上把 pose 锚到正确的世界参考上”。

