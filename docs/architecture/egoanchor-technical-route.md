# EgoAnchor 技术路线总览（供 gpt-image-2 绘图）

本文档总结 EgoAnchor 当前主线实现的完整技术路线，并在末尾给出可直接喂给 gpt-image-2 的科研风格绘图提示词。可编辑的矢量源图见同目录 `egoanchor-technical-framework.drawio`（可导入 draw.io）；gpt-image-2 的图片产物只作视觉构图参考，正式论文图以 drawio 为准。

本文内容已对照源码核对：感知流水线顺序、可靠性评分公式、三平面通信、Unity 策略层与静止锁机制、评估链路。

---

## 一句话定位

EgoAnchor 面向 passthrough 混合现实，把外部视觉计算设备产生的**异步、低帧率、带噪声的相机坐标系 6DoF 物体位姿流**，转换成头戴端**稳定、世界一致、可恢复**的真实物体锚点。重点不是普通目标跟踪，而是 **pose-to-anchor** 与 **frame-aligned anchoring**（按帧对齐的锚定）。

核心主张：物体位姿估计链路**仅依赖双目视觉 + 物体 3D 模型**（不依赖物体侧的惯性或外部空间定位传感器）；参考相机的世界位姿来自头戴端自身跟踪。仅消费级显卡即可部署（5080 laptop 约 5fps，5090 桌面端约 12fps），框架把低帧率观测平滑升采样到 60fps。

---

## 端到端技术路线（九步）

1. **采集（Unity / Quest 3）**：`StereoFrameSource` 读取左右 passthrough 纹理，`CameraInfoSource` 读取内参与镜头位姿。每个 `frame_id` 在采集时刻被写入 `FramePoseHistory`（frame_id → 采集时刻 left/right/center 相机世界位姿，环形缓存）。
2. **上行传输（ZMQ 数据面）**：`QuestStreamPublisher` 以 ZMQ PUB 发送 `QuestStereoFrame` 和 `QuestCameraInfo`；Python 侧 `QuestStreamReceiver` 做 latest-only drain、protobuf 解码、frame_id / session 去重，旧帧不积压。
3. **标定**：`QuestCalibration` 把网络 `camera_info` 映射到算法处理分辨率下的内参 K（支持中心裁剪 / 线性缩放）。
4. **感知流水线（`QuestPosePipeline`，相机坐标系，纯视觉）**，固定四步顺序：
   - ① 分割：YOLOE-26（默认）或 SAM3（文本提示、异步初始化）输出单目标 mask；
   - ② 双目深度：Fast-FoundationStereo（FFS）；
   - ③ 位姿注册：FoundationPose 用物体 CAD 模型对齐出 6DoF；
   - ④ 位姿跟踪：FoundationPose track + Cutie mask 传播。
   - 输出 `PoseObservation`（相机坐标系 4×4 位姿、phase、frame_id、各类可靠性中间量）。
5. **可靠性评分（`RenderQuality` + `PoseScore`）**：一次渲染后协调颜色重投影、深度对齐、mask 面积调制、连续高质量置信，合成总分。Python **只输出相机坐标系位姿 + 可靠性分**，不输出 Unity 世界锚点。
6. **下行传输（NATS 消息面）**：`TrackingRuntime` 发布 `PoseResult` / `AnchorStatusEvent` / `ServerHeartbeat`（pose 与 heartbeat 为 latest-only，status 为事件流）。
7. **帧对齐（Unity）**：收到 `PoseResult` 后，按 `header.frame_id` 在 `FramePoseHistory` 中**精确回查**采集时刻参考相机世界位姿，`CameraPoseFrameAligner` 把相机坐标系物体位姿刚体组合成 Unity 世界位姿。**这是核心创新路径**——世界锚点只在头戴端由 frame_id 回查得到，禁止用到达时刻 HMD 位姿替代。
8. **策略升采样（`AnchorPolicyHost`）**：把低频不稳定观测转成每渲染帧高频锚点输出。运动模型 = {ConstantVelocity, Kalman, OneEuro}，平滑策略 = {RawPassthrough, Blend, DelayedInterp}，两者自由组合（3×3），外加可选 score gate 与生命周期状态机。
9. **EgoAnchor 方法层（`StaticLockController`）**：在 baseline 之上加 reliability-aware 静止锁——静止时输出 `lockedPose`，用 score 门控的 CUSUM、漂移租绳、速度逃逸、低分释放、头动容忍、头停沉降冻结、接缝残差处理锁定/解锁。挂上模块且启用 = EgoAnchor 方法，不挂 = 纯 baseline，两者正交可对照。

下行还有第 10 条旁路：**命令面（NATS request/reply）**。低分或 track-loss 时 Unity 先本地重置策略；若几何证据也差，由 `AnchorRuntimeHub` 汇总多 runtime 请求，经唯一 command client 向 Python 发 reset / reacquire / control，`request_id` 幂等、快速 ack、runtime 串行执行。

---

## 三平面通信（必须在图中区分）

| 平面 | 传输 | 方向 | 数据 | 语义 |
| --- | --- | --- | --- | --- |
| Data Plane | ZMQ PUB/SUB | Unity → Python | `QuestStereoFrame`、`QuestCameraInfo` | protobuf bytes，topic latest-drain |
| Message Plane | NATS Core | Python → Unity | `PoseResult`、`AnchorStatusEvent`、`ServerHeartbeat` | pose/heartbeat latest-only，status 事件流 |
| Command Plane | NATS request/reply | Unity → Python | reset / reacquire / control | `request_id` 幂等，快速 ack，串行执行 |

`EgoAnchor_Protocol` 是唯一 proto 与 subject 源，同步生成 Python（`*_pb2.py`）与 Unity（`*.cs` + `SubjectNames`）两端代码。

---

## 可靠性评分（不是简单阈值）

最终分采用三层乘积结构：

```
Reliability = Gate × Quality × Confidence
  Gate    = phase × reject                         （门控层：phase 子分 × 近期 track-reject 子分）
  Quality = geomean(reproj, depth ; w=0.5/0.5) × mask_modulation   （质量层：几何核 × mask 调制）
  Confidence = 0.5..1.0 连续高质量帧 warmup ramp（约 10 帧到满）
```

关键约定（图里可作注脚，体现“评分由多信号组合而来”）：
- 颜色重投影 `color_reprojection = -1` 表示本帧无有效颜色信号（纯色/无纹理物体、渲染退化、warmup），此时把颜色项**排除出几何核**而不是惩罚；
- 深度项 `score_depth = 0.5` 为中性值，mask 内有效深度覆盖率需 ≥ `0.10` 才进入深度对齐评分；
- 几何核是对**有效**证据取加权对数几何平均，两路都无信号时保持对当前 pose 的信任（=1）；
- 逐帧跳变子分（旧 `score_jump`）已删除——离线分析证明跳变幅度无法区分坏 pose 与真实快动，坏 pose 的拒绝交给几何核（Python）与 anchor 层 CUSUM（Unity）。

---

## EgoAnchor 静止锁（方法核心，不要画成低通滤波）

- **进入锁定**：线速度 / 角速度低于阈值、连续静止满 `dwell`、可靠分 ≥ `minScore`。
- **锁定输出**：直接输出 `lockedPose`（叠加头动门控的 creep 精修），不是滑动平均。
- **解锁证据三路**：速度逃逸、绝对漂移租绳 `distance(obsConsensus, anchorOrigin)`、CUSUM；三路按真实 dt 处理，不绑帧率。
- **头动感知**：`headToleranceFactor` 头转时同比放大阈值吸收 head-slip；`headSettleSeconds` 仅在头停下而沉降未走完的窗口冻结“判物体在动”的证据（头动期间绝不冻结）。
- **低分释放**：锁点可靠性差时强制释放，交给低分 reacquire。
- **解锁接缝**：解锁瞬间记录 `lockedPose` 相对候选输出的残差，之后在独立接缝阶段按残差衰减平滑回归候选输出。

---

## 评估链路（离线，不要画成线上模块）

- `AnchorEvalRecorder` 按采集 / 渲染两条 JSONL 记录：capture 行（帧位姿、`aligned_raw`），render 行（`output_pos/rot`、`motion_model`、`smoothing_strategy`、`gate`、`has_output_pose`）。
- `EgoAnchor_Tools3` 是离线 latency-aware 60fps 实时仿真器：从 Unity primary 变体的 `aligned_raw` 提取低频观测，按真实采集→渲染延迟重放，对比 RawZoh / Kalman / OneEuro / DeadReckoningSpline / DelayedInterp / ResidualBlending / **EgoAnchorStabilizer** 等预测器。
- `eval/metrics`：世界坐标系锚点误差、jitter / slip、lag、latency、recovery success / time。

---

## 图中必须突出的事实

- Python 不直接输出世界锚点；世界锚点只由 Unity 按 `frame_id` 回查采集时刻相机位姿后刚体组合得到。
- 正式路径必须用采集时刻相机位姿；到达时刻位姿只能作诊断对照。
- 三条语义通道（ZMQ data / NATS message / NATS command）要分别用不同线型标注。
- “纯视觉”只修饰物体位姿估计链路；参考相机世界位姿来自头戴端跟踪。
- 静止锚定是 regime-switching 稳定器，不是滤波器。
- 低分重获取由 Unity hub fan-in，避免多 runtime 同时向 Python 发命令。
- `EgoAnchor_Tools3` 是离线评估仿真工具，不是线上运行模块。

## 负向约束

不要画成“外部 AI 直接输出世界坐标锚点”。不要把 NATS 画成图像流。不要省略 `FramePoseHistory` 与 frame_id 回查箭头。不要把 static lock 画成普通 smoothing filter。不要把 `EgoAnchor_Tools3` 画进线上数据流。

---

## gpt-image-2 提示词（英文，复制即用）

```text
Create a clean, publication-quality system architecture figure for an IEEE VR research paper. White background, muted grayscale-safe colors, thin orthogonal connectors, no gradients, no 3D, no icons, no marketing style. Serif labels (Times-like). Title at top: "EgoAnchor: Frame-Aligned Real-Object Anchoring in Passthrough MR".

Layout: three tall vertical bands left-to-right, plus a wide support band along the bottom.

BAND 1 (left) "Quest 3 HMD / Unity Capture":
- StereoFrameSource: left/right passthrough textures + capture-time L/R/C camera poses
- CameraInfoSource: intrinsics + lens pose
- FramePoseHistory (draw as a database cylinder): frame_id -> capture-time L/R/C camera world pose, ring buffer
- QuestStreamPublisher: ZMQ PUB, latest-only
- small note: "reference camera world pose comes from HMD tracking; only the object-pose chain is vision-only"

BAND 2 (center) "External Visual Compute / Python (vision-only object pose)":
- QuestStreamReceiver: ZMQ latest-drain, protobuf decode, frame_id/session dedup
- QuestCalibration: camera_info -> processing-resolution K
- A dashed sub-box "QuestPosePipeline" containing a vertical 4-step chain: (1) Segmentation YOLOE-26 default / SAM3 async text-prompt, (2) Stereo Depth Fast-FoundationStereo, (3) Pose Register FoundationPose with CAD model, (4) Pose Track + Cutie mask propagation; output label "PoseObservation: camera-space 4x4 pose, phase, frame_id"
- A dashed sub-box "RenderQuality + PoseScore" with: color reprojection (LAB), depth alignment (render vs FFS), mask-area modulation, confidence ramp; and a highlighted formula box "Reliability = Gate x Quality x Confidence; Quality = geomean(reproj, depth) x mask; color=-1 no-signal, depth=0.5 neutral, depth-valid>=0.10"
- TrackingRuntime: owns pipeline/GPU, publishes PoseResult/status/heartbeat, serial command pump

BAND 3 (right) "Unity Anchor Runtime":
- NatsControlClient + PoseResultReceiver: latest pose queue, status event stream (main-thread drain)
- AnchorRuntimeHub: multi-runtime fan-out, low-score reacquire fan-in
- CameraPoseFrameAligner: OpenCV camera pose COMBINED WITH FramePoseHistory(frame_id) -> Unity world pose
- A dashed sub-box "AnchorPolicyHost (MotionModel x SmoothingStrategy)" containing: Motion Models {ConstantVelocity, Kalman, OneEuro}; Smoothing {RawPassthrough, Blend, DelayedInterp}; optional Score gate; Lifecycle FSM {Searching, Tracking, Coasting, FrozenUncertain, Lost, Relocalizing}
- A solid emphasized sub-box "StaticLockController - EgoAnchor stabilizer (score-gated regime switch)" containing: Enter lock (low speed/ang-speed, dwell, score>=min); Locked output = lockedPose (+ head-gated creep); Unlock evidence = speed escape OR drift leash OR CUSUM; Head-aware (tolerance factor, settle freeze); low-score release + seam-residual decay
- PoseToAnchorRuntime: LateUpdate(-50)
- DynamicObjectAnchor: applies world Transform (rounded terminal box)

BOTTOM BAND "Protocol & Evaluation":
- EgoAnchor_Protocol (document shape): proto + subjects.v1.json -> single source generating Python *_pb2.py and Unity *.cs + SubjectNames
- AnchorEvalRecorder (document shape): capture JSONL (frame poses, aligned_raw) + render JSONL (output_pos/rot, model, strategy, gate)
- EgoAnchor_Tools3: offline latency-aware 60 fps simulator; predictors RawZoh, Kalman, OneEuro, DeadReckoningSpline, DelayedInterp, ResidualBlending, EgoAnchorStabilizer
- Metrics: world-space anchor error, jitter/slip, lag, latency, recovery success/time

ARROWS (label each, distinct line styles):
- Quest -> Python, thick dashed: "ZMQ data plane: QuestStereoFrame / QuestCameraInfo, latest-only"
- Python -> Unity, thick dashed (different color): "NATS message plane: PoseResult / AnchorStatusEvent / ServerHeartbeat"
- Unity -> Python, dash-dot: "NATS command plane: reset / reacquire / control, request_id idempotent ack"
- A THICK ORANGE emphasized arrow from FramePoseHistory to CameraPoseFrameAligner labeled "exact frame_id lookup -> world anchor" (this is the core idea, make it visually prominent)
- dotted gray arrows from EgoAnchor_Protocol to publisher, runtime, and Unity client (generated code dependency)
- dotted gray arrows from PoseToAnchorRuntime and TrackingRuntime into AnchorEvalRecorder / Tools3, then solid into Metrics

A small caption box near the center-top, highlighted: "Key idea: the external compute node emits camera-space object pose only; the headset reconstructs the world anchor by exact frame_id lookup of the capture-time reference camera pose."

Style: short labels not sentences, orthogonal arrowheads, print-safe muted palette (soft blue / green / amber bands), no decorative elements. Make the frame_id lookup arrow and the camera-space-pose-only constraint visually obvious.
```
