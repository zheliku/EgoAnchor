# EgoAnchor Technical Flow（代码推导版）

> 本文档基于源代码（`.py / .cs / .proto / .toml`）逐行阅读与推导，每处关键技术在正文给出流程与公式，并在文末 **第 16 节《脚本实现位置索引》** 给出对应文件与行号。
> 公式常量来自代码默认值（`defaults.toml` / Inspector 默认）或主线场景覆盖；涉及覆盖时在正文说明。
> `egoanchor_cn_v4.typ` 是当前已确定的论文文本；本文档按论文 v4 的术语记录代码事实，代码类名、字段名和实验标签保留英文。
>
> *最后验证：2026-07-03*

---

## 1. 目标与系统定位

EgoAnchor 旨在为开放消费级混合现实提供稳定的动态真实物体锚定能力。系统的**目标物体位姿估计链路**仅依赖头戴显示器双目 RGB 图像与目标物体三维模型，即可为日常刚性物体提供连续 6DoF 动态锚定输入。参考相机的世界位姿来自头显自身跟踪，视觉推理当前运行在外部消费级 GPU 上，并通过异步通信与头戴端运行时连接；因此本文档中的 open / deployable 指无需物理标签、专用深度硬件或逐物体离线训练，不等于头显端独立运行。

**核心挑战：** 视觉模块输出的是 **异步的相机坐标系位姿观测**，其生成时刻早于结果到达时刻；若使用到达时刻（arrival-time）的设备位姿做坐标变换，将产生系统性动态配准误差，使虚拟内容出现漂移、抖动和跳变。

**解决方案：** EgoAnchor 采用 **对象感知与对象锚定解耦** 的分层架构：

- **对象感知（Python 后端）**：输入 → 目标语义分割 → 双目立体几何重建 → 零样本 6DoF 位姿估计 → **可靠性评分**。输出相机坐标系下的异步位姿观测，**不维护** 世界坐标。
- **对象锚定（Unity 运行时）**：**时空对齐 / 基于采集时刻的帧对齐** → 锚定策略（运动模型 × 平滑策略）→ **静止锚定** → 生命周期管理。依据帧标识恢复 **采集时刻（capture-time）** 的参考相机 world pose，输出稳定的世界坐标锚点。质量评估门控不是独立模块；代码中保留为 `AnchorPolicyHost.enableQualityGate` 控制的内联可选观测拒绝逻辑，论文 RQ2 完整方法变体可打开。

**三条语义边界（贯穿全文）：**

1. Python 只输出 `camera-space object pose + reliability`，不维护世界坐标
2. Unity 必须按 `frame_id` 回查 **capture-time reference camera world pose** 再合成 world anchor
3. arrival-time 的头显姿态 **只用于对照诊断**，不能替代 frame-aligned 对齐

**数据流：** `Unity 采集 → Python 感知 → Python 结果回传 → Unity 帧对齐 → Unity policy 与渲染`

### 1.1 术语写作口径

本文档统一使用 `egoanchor_cn_v4.typ` 的论文术语，同时保留必要的代码标识：

| 论文术语 | 代码定位 |
| --- | --- |
| 动态真实物体锚定 | 系统目标；最终输出为 world-space object anchor |
| 目标语义分割 | `YOLOE-26` 或 `SAM3` 后端，经 `SegmenterResult` 统一进入流水线 |
| 双目立体几何重建 | `Fast-FoundationStereo` 生成米制深度 |
| 可靠性评分 | VCD 综合 `reliability_score` 与 V/C/D 子分 |
| 时空对齐 | `frame_id` 精确回查采集时刻参考相机 world pose |
| 质量评估门控 | `AnchorPolicyHost.enableQualityGate`、`QualityGateDecision`、`quality_gate`；独立门控模块已删，当前是默认关闭的内联可选观测拒绝逻辑 |
| 锚定策略 | `MotionModel × SmoothingStrategy` |
| 静止锚定 | `EgoAnchorStaticLockModule` / `StaticLockController` |
| 生命周期状态机 | `AnchorStateMachine` |

---

## 2. 仓库组成与组件职责

| 组件目录                                                             | 语言/平台       | 职责                                                                         |
| -------------------------------------------------------------------- | --------------- | ---------------------------------------------------------------------------- |
| `EgoAnchor_Python/src/egoanchor/`                                  | Python          | 视觉感知后端（采集接收、分割/深度/位姿、可靠性评分、协议与传输、命令、日志） |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/`                        | C# / Unity      | 对象锚定运行时（采集发布、帧对齐、锚定策略、渲染、命令客户端）               |
| `EgoAnchor_Protocol/`                                              | Protobuf / JSON | 跨端协议契约（`.proto` 消息定义、`subjects.v1.json` 主题清单）           |
| `EgoAnchor_Tools3/`                                                | C# / .NET 8     | 离线预测器仿真基准（回放观测、对比多种预测/平滑策略、产出指标与图）          |
| `EgoAnchor_Python/eval/`                                           | Python          | 定量评估流水线（加载 Python+Unity 日志，计算锚定质量指标，产出表与图）       |
| 第三方模型（`Cutie/ FoundationPose/ Fast-FoundationStereo/ sam3`） | Python          | 上游开源模型；EgoAnchor 通过`algorithms/` 下的 wrapper 集成，不改其内部    |

感知后端的实际整合逻辑集中在 `src/egoanchor/`，第三方模型仅作为被 wrapper 调用的能力单元。

---

## 3. 协议与传输层

### 3.1 双平面传输架构

系统拆分为两条物理传输，按带宽与时延需求分工：

| 平面              | 方向            | 载体                         | 语义                                                           | 端口/地址                 |
| ----------------- | --------------- | ---------------------------- | -------------------------------------------------------------- | ------------------------- |
| **Data**    | Unity → Python | **ZMQ** PUB/SUB        | `QuestStereoFrame`、`QuestCameraInfo`                      | `tcp://*:15557`         |
| **Message** | Python → Unity | **NATS** pub/sub       | `PoseResult`、`AnchorStatusEvent`、`ServerHeartbeat`     | `nats://127.0.0.1:4222` |
| **Command** | Unity → Python | **NATS** request/reply | `reset` / `reacquire` / `control`（回复 `CommandAck`） | 同上                      |

**设计理由：** ZMQ 承载 30+ Hz 双目 JPEG 流（`receive_hwm=20`），配合 latest-only 处理；NATS 提供可靠订阅与请求-应答，承载位姿结果、状态事件与控制命令。

### 3.2 消息头与关键字段

**统一消息头 `MessageHeader`：** `message_id, request_id, session_id, client_id, anchor_id, frame_id, unity_frame, sender_mono_ms, created_unix_ms, schema_version`

- `frame_id`：**帧对齐主键**（单调递增，Unity 分配）
- `session_id`：标识 Unity 采集会话，检测重启
- `request_id`：命令幂等去重键
- `sender_mono_ms` / `created_unix_ms`：**仅用于时序诊断**，不参与位姿计算

**关键消息类型：**

- **`PoseResult`**：`has_pose`、`pose_matrix_cv_camera`（row-major 4×4）、`reliability_score` 与子分（`score_reprojection/score_depth/score_mask`）、`render_quality_*` 诊断、timing 信息
- **`QuestStereoFrame`**：`left_image_jpeg / right_image_jpeg`、宽高、`jpeg_quality`
- **`QuestCameraInfo`**：左右内参、畸变系数、`baseline_m`、分辨率
- **命令消息**：`ResetTrackingRequest`、`ReacquireAnchorRequest`、`AnchorControlRequest`，回复 `CommandAck`

### 3.3 路由与背压

- **ZMQ 接收**：`poll_latest()` 抽干队列，每 topic 保留最新；`receive_hwm=20`，`poll_timeout_ms=10`
- **session/frame 去重**：同一 session 内 `frame_id` 不可倒退或重复；session 变化触发输入重置
- **NATS 背压**：`max_pending_futures=32`，超过则丢弃保持 latest-only
- **NATS 路由**：按 subject 查询 → Protobuf 解析 → 派发 handler → 回 `CommandAck`

---

## 4. Unity 采集端

### 4.1 会话与帧标识

- 每次发布生成新 `session_id`
- `frame_id` 在采集端预自增（`++frameId`）单调分配，是帧对齐唯一主键
- `QuestCameraInfo` 低频（默认 1 Hz），`frame_id` 固定为 0

### 4.2 采集流程

1. 读取左右 Passthrough texture 与相机世界位姿
2. **通过延迟缓冲绑定图像到略早的 camera pose**（默认 `cameraPoseDelayFrames=1`），补偿 Passthrough 纹理滞后
3. 记录采集时刻：`sender_mono_ms = Time.realtimeSinceStartupAsDouble × 1000`
4. 压缩左右图为 JPEG，封装 `QuestStereoFrame`
5. 经 ZMQ 多部分消息 `[topic_utf8, protobuf_bytes]` 发往 Python

### 4.3 帧位姿历史（FramePoseHistory）

采集端同时把 `frame_id → 采集时刻 left/right/center 相机世界位姿` 写入环形缓存：

- 数据结构：`Dictionary<frame_id, FramePoseRecord>` + FIFO 队列
- 容量：`capacity=512`（约 17 s @ 30 Hz），超出按最旧淘汰
- 查询：`TryGet(frame_id)` O(1) 精确匹配，**不做时间插值、不做外推、不做最近邻回退**

> 这一"按 frame_id 精确锁定采集时刻相机位姿"的设计，是后续 capture-time 对齐能够成立的前提。

---

## 5. Python 接收与运行时

### 5.1 执行模型

- **ZMQ 轮询**：`TrackingRuntime.tick()` 内调用 `poll_latest()` 抽干 socket，每个 topic 只保留最新 payload
- **Runtime owner 主循环**：顺序执行 `TrackingRuntime.tick()`，独占感知 pipeline 与 GPU 状态
- **异步分割 worker**（可选）：仅后台执行 SAM3 初始分割；完成后主 pipeline 继续使用同一帧左右图、mask、深度和 register
- **NATS 异步客户端**：后台处理发布 future、订阅回调与 request/reply；handler 只校验、去重、入队和 ack

### 5.2 主循环（每 tick）

1. 执行命令队列（至多 `execute_per_tick=8` 条）
2. 轮询最新 stereo / camera_info（`poll_timeout_ms=10`）
3. 若 PAUSE，只发心跳
4. 更新输入就绪状态
5. 按节流条件（`min_process_interval_ms=0`，默认不节流）决定是否运行感知
6. 生成 `PoseResult` 并经 NATS 发布（latest-only）
7. 发布 `AnchorStatusEvent` 与 `ServerHeartbeat`（`interval_s=1.0`）

运行时 FPS 用 EMA 平滑：`fps ← 0.9·fps + 0.1·fps_inst`

---

## 6. Python 感知 Pipeline

### 6.1 总流程

```
解码 JPEG → 统一到处理分辨率 (640×480) → 刷新相机内参 K'
  → 生成/传播目标 mask (YOLOE-26 或 SAM3 初始分割 + Cutie 时序传播)
  → 双目立体几何重建 (FFS) + 有效范围截断
  → mask 像素 + mask 内有效深度比例校验
  → FoundationPose register 或 track
  → 渲染质量回查 (颜色重投影 + 深度对齐)
  → 汇总 PoseObservation (含可靠性评分)
```

`run_stage` 控制运行阶段（1=输入、2=分割、3=深度、4=完整 pose）

### 6.2 标定映射

把 Quest 原始标定映射到算法处理分辨率。中心裁剪模式（`assume_center_crop=true`）：

$$
f_x' = f_x\,s_x,\quad f_y' = f_y\,s_y,\quad c_x' = (c_x - \text{crop}_x)\,s_x,\quad c_y' = (c_y - \text{crop}_y)\,s_y
$$

`network_calib_update=true` 时标定变化触发 FoundationPose 重置。

### 6.3 分割

- **初始分割**：默认 `yoloe26`（开放词表文本分割），可切 `sam3`。参数：`prompt`、`confidence_threshold=0.2`、`max_det=1`、`mask_threshold=0.5`
- **异步分割**（`async_segmentation=true`）：仅用于首次 register。主线提交后立即返回 `WAIT_SEGMENTATION`，后台跑完后在同一帧左右图上继续深度与 register。**关键不变量：第 N 帧的左右图始终与第 N 帧的分割 mask 配对**
- **Cutie 传播**（`module.cutie.enabled=true`）：register 成功后初始化记忆，其后每帧传播 2D mask。连续空 mask 达 `cutie_lost_reset_frames=5` 后清空注册状态

### 6.4 深度估计

Fast-FoundationStereo 输入左右 RGB + `fx` + `baseline`，输出米制深度：

$$
Z = \frac{f_x \cdot s \cdot b}{d},\qquad d = \mathrm{clip}(d,\,10^{-6},\,\infty)
$$

$d$ 为视差，$s$ 为内部缩放，$b$ 为基线。后端优先 TensorRT（`use_trt=true, trt_precision=fp16`），否则 PyTorch（`valid_iters=4, max_disp=192`）。输出后按有效范围清零：$Z<0.1$ 或 $Z>5.0$ m 或非有限值置 0。

### 6.5 位姿估计

- **REGISTER**（未注册）：要求 mask 有像素且 mask 内有效深度比例 `≥ register_min_depth_valid_in_mask=0.15`。调用 `register(K, rgb, depth, ob_mask, iteration=5)`
- **TRACK**（已注册）：调用 `track_one(rgb, depth, K, iteration=2)`，以上一帧为先验
- **对称约束**：`symmetry_mode`（默认 `cube`，可 `none/axis`）

---

## 7. 可靠性评分模型（VCD）

Python 为每个有效 `PoseObservation` 计算 $[0,1]$ 的综合可靠性。采用 **VCD（Visibility-gated Color-Depth）可靠性评分模型**：

$$
\boxed{R = V \times G_\text{CD},\qquad
G_\text{CD}=\exp\!\left(\frac{\sum_{i\in E} w_i\log\max(s_i,\varepsilon)}{\sum_{i\in E}w_i}\right)}
$$

- $V$：可视度因子。实现优先取 `render_quality_area_ratio_score = min(|M_obs|/|M_rnd|, 1)`；缺少渲染面积信号时退回到观测 mask 面积占比的非线性先验
- $G_\text{CD}$：有效 C/D 一致性证据集合 $E\subseteq\{C,D\}$ 的加权对数几何均值
- $C$：颜色投影（Color projection，默认权重 0.2）
- $D$：深度对齐（Depth alignment，默认权重 0.8）
- $\varepsilon$：`geo_floor=0.05`

**关键设计：** 某证据无效时从 $E$ 中排除，而非按低分惩罚；两路都无效时 $G_\text{CD}=1$，总分退化为只看可见度 $V$。

### 7.1 颜色投影（C）

取渲染 mask 与观测 mask 交集核心区域（椭圆腐蚀），转 LAB，亮度通道按 `color_l_weight=0.3` 降权，做零均值归一化互相关 ZNCC：

$$
C = \mathrm{clamp}_{[0,1]}\!\Big(\tfrac{\text{ZNCC}+1}{2}\Big)
$$

无纹理/纯色 → 标记无效并排除 C 证据（评分合成阶段设置 valid=false，当前占位值不进入几何核；`PoseObservation.color_reprojection=-1`），避免冤枉正确 pose。`color_reprojection=-1` 表示无有效颜色证据，不是低质量颜色分。

### 7.2 深度对齐（D）

mask 内有效深度覆盖率 $< 0.10$ → 返回 0.5 且无效。否则采用 **绝对-结构联合评估**：

$$
\boxed{D = (1-\alpha)\,D_\text{abs} + \alpha\,D_\text{struct}}
$$

**绝对残差分量** $D_\text{abs}$：在核心区域（3×3 腐蚀 mask 排除边缘噪声）内，采用距离自适应阈值：

$$
\tau(p) = \max(\tau_\text{min},\ \rho_z\,D_\text{rnd}(p)),\qquad \rho_z=0.02,\ \tau_\text{min}=5\,\text{mm}
$$

联合评估内点比例与归一化残差中位数：

$$
D_\text{abs} = \lambda\,\rho_\text{inlier} + (1-\lambda)\,S_\text{med},\qquad \lambda=0.6
$$

$$
\rho_\text{inlier} = \tfrac{1}{|\Omega|}\sum_{p\in\Omega}\mathbb{1}[e(p)<\tau(p)],\qquad S_\text{med} = 1 - \mathrm{median}\Big(\min\big(\tfrac{e(p)}{s\cdot\tau(p)},1\big)\Big),\qquad s=2.5
$$

其中 $s=2.5$ 为残差容忍倍数，鲁棒应对双目立体几何重建中的系统性深度偏差。

**相对结构分量** $D_\text{struct}$：对渲染深度和观测深度分别减去各自中位数并除以四分位距（IQR）归一化后，计算零均值互相关（ZNCC）并映射到 $[0,1]$。该机制识别深度形状完全对齐的正确位姿，即使存在全局偏移或局部系统噪声。

**自适应融合权重**：

$$
\alpha = \begin{cases}
0, & \text{IQR} < 20\,\text{mm} \quad\text{(平坦表面，回退绝对残差)}\\
\alpha_\text{max}, & \text{IQR} \ge 20\,\text{mm} \quad\text{(高频几何，引入结构验证)}
\end{cases}
$$

其中 $\alpha_\text{max}=0.35$。该机制解决手柄等高频几何物体在特殊角度下"形状正确但有系统性深度噪声"导致的深度分过低问题（实测从 0.306/0.406 提升到 0.9+）。

**配置参数**：`[reliability.render_quality]` 新增 `depth_residual_scale`、`depth_enable_structural`、`depth_structural_max_weight`、`depth_structural_iqr_thresh`、`depth_core_erode_kernel`。

---

## 8. Python → Unity（结果回传）

`pose_matrix_cv_camera` 是 row-major 展平 4×4：平移在索引 `[3,7,11]`，forward 列在 `[2,6,10]`，up 列在 `[1,5,9]`。Unity 用 `Quaternion.LookRotation(forward, up)` 重建为 OpenCV 相机系下的 object pose。

`frame_id` 原样穿透回传（对齐主键）；`server_receive_mono_ms`、`server_publish_mono_ms`、`timing.*` 仅作诊断，不参与位姿计算。

---

## 9. Unity 时空对齐（基于采集时刻的帧对齐，核心贡献）

### 9.1 问题

Python 返回的位姿基于较早采集时刻的图像（frame N），具体滞后由感知推理、传输和调度延迟共同决定；结果到达 Unity 时头显可能已移动到 frame N+k。若用 **到达时刻** 的相机位姿做坐标变换，会引入系统性动态配准误差。

### 9.2 接收→对齐→输出流程

```
NATS PoseResult 到达 (latest-only)
  → 主线程解析
  → 读 pose_matrix_cv_camera → OpenCV camera-local pose
  → 按 header.frame_id 回查 FramePoseHistory（采集时刻相机世界位姿）
  → 命中: 合成 world anchor；未命中: 判 AlignFailed
  → 打包 AnchorObservation 交给锚定策略
```

### 9.3 核心对齐数学

设 frame $f$ 采集时刻参考相机的世界位姿为 $T^{w}_{c,f}$（从历史回查得到），Python 输出经轴翻转后的 Unity 相机本地 object pose 为 $T^{c}_{o}(f)$，则世界锚点：

$$
\boxed{\,T^{w}_{o}(f) = T^{w}_{c,f}\cdot T^{c}_{o}(f)\,}
$$

具体到位置与旋转：

$$
p^{w}_{o} = p^{w}_{c,f} + R^{w}_{c,f}\,p^{c}_{o},\qquad R^{w}_{o} = R^{w}_{c,f}\,R^{c}_{o}
$$

**OpenCV→Unity 相机本地轴翻转**（OpenCV：x 右、y 下、z 前；Unity：x 右、y 上、z 前）：

$$
R_u = S\,R_\text{cv}\,S,\qquad S = \mathrm{diag}(1,-1,1)
$$

实现用 forward/up 重建四元数（`flipY=true`），规避 handedness 陷阱。

### 9.4 对齐失败与诊断

- **未命中**（frame_id 已淘汰、或位姿矩阵非法、或 has_pose=false）→ 返回 `AlignFailed`，由锚定策略进入保持/失锁逻辑。**不外推、不近邻回退**
- **arrival-time raw 对照**：另有用"最新相机位姿"对齐的诊断路径（`TryAlignWithLatestCameraPose`），**仅用于评估**，绝不作为正式 anchor

---

## 10. Unity 锚定策略

锚定策略把已对齐的、低频且含噪的 world pose 流转成每帧稳定输出。组成：

`AnchorPolicy = MotionModel + SmoothingStrategy + 静止锚定 + lifecycle`，可选叠加 `enableQualityGate` 观测拒绝。

三种 MotionModel × 三种 SmoothingStrategy 可任意组合（9 变体）。时间语义分为两条轴：`MeasurementTimeSeconds`（优先 capture time）用于运动模型、平滑策略和静止锚定；`LifecycleTimeSeconds`（Unity 到达时间）用于 stale/lost 判断和低分持续时间。

### 10.1 锚定状态机

`Uninitialized / Searching / Tracking / Coasting / FrozenUncertain / Lost / Relocalizing / Paused / Error`

- 短 gap（$\le$ `coastTimeoutSeconds=0.45`）→ Coasting（输出预测）
- 长 gap（源码默认 `lostTimeoutSeconds=1.0`，主线场景可覆盖 2.0 s）→ Lost（不输出）
- `trackingScoreFloor` 源码默认 0，场景可覆盖 0.5 作状态提示；重 register 使用更低的 `lowScoreReacquireThreshold=0.45`，且需持续 `0.6 s`

### 10.2 可靠性消费与可选观测门控

可靠性评分在 Unity 端有三类消费路径：

1. 生命周期状态：`trackingScoreFloor` 决定是否刷新可靠观测时间戳，低分会让 gap 累积并推动 Coasting / FrozenUncertain / Lost。
2. 低分重获取：`lowScoreReacquireThreshold` 持续满足后请求 Python 重新 register。
3. 静止锚定：进入锁定、低分释放和解锁证据都会使用可靠性评分。

质量评估门控对应 `enableQualityGate`。它不是独立模块，源码默认关闭；打开后，可靠性总分 $<$ 阈值或 $|$测量−预测$|$ 超跳变阈值 → Reject，不更新运动模型。论文 RQ2 的 *Full* 与 *Raw-ZOH* 使用相同的门控配置，比较完整锚定策略与零阶保持参照的整体权衡，不把质量门控作为独立消融因素；eval 字段为 `quality_gate=enabled/disabled`。

### 10.3 运动模型

**ConstantVelocity（基线）：**

$$
p(t)=p_n+v(t-t_n),\quad q(t)=q_n\otimes\exp\!\big(\omega(t-t_n)\big),\quad v=\tfrac{p_n-p_{n-1}}{\Delta t},\ \omega=\tfrac{\log(q_{n-1}^{-1}q_n)}{\Delta t}
$$

**Kalman（CV，去噪 + 最优速度）：** 位置 x/y/z 三路 1D CV Kalman，旋转在切空间三路 CV。单轴状态 $\mathbf{x}=[p,v]^\top$：

$$
\mathbf{F}=\begin{bmatrix}1&\Delta t\\0&1\end{bmatrix},\quad \mathbf{H}=[1\ 0],\quad \mathbf{P}\leftarrow\mathbf{FPF}^\top+\mathbf{Q},\quad K=\tfrac{\mathbf{PH}^\top}{\mathbf{HPH}^\top+r},\quad \mathbf{x}\leftarrow\mathbf{x}+K(z-p)
$$

默认：位置过程噪声 $0.20$、位置测量噪声 $0.0004$、旋转过程噪声 $0.40$、旋转测量噪声 $0.0025$。**Unity 版无 maxPredictAhead 限幅**。

**One Euro（自适应低通）：** 每轴两级低通：

$$
f_c = f_\text{min} + \beta\,|\hat{\dot x}|,\qquad \alpha(\Delta t,f_c)=\frac{1}{1+\tau/\Delta t},\quad \tau=\frac{1}{2\pi f_c},\qquad \hat x\leftarrow\hat x+\alpha(z-\hat x)
$$

默认：`minCutoff=1.0 Hz, beta=0.25, derivativeCutoff=1.0 Hz`

### 10.4 平滑策略

**RawPassthrough**：零阶保持，不外推不插值。

**Blend（零延迟外推 + 残差融合）：** 预测到当前时间，再把残差逐帧指数还掉：

$$
y_t = \text{predict}(t)\oplus \text{residual}_t,\qquad \text{residual}\leftarrow \text{residual}\cdot d^{\,\Delta t_\text{render}\cdot 60}
$$

默认 `decayPerFrame=0.9`（半衰期≈158 ms）。外推时域自适应：$L=\min(\hat\tau\cdot m,\ L_\text{max})$，`extrapolationLatencyMultiplier=1.0`、硬上限 `maxExtrapolationSecondsHardCap=0.3`。

**DelayedInterp（主动延迟 + 真插值）：** 渲染目标取 $t-\Delta$，落在两个已到控制点间做插值（非外推），保证精确过点：

$$
\Delta = \max(\hat\tau\cdot s,\ \Delta_\text{min}),\qquad s=\text{latencySafetyMargin}=1.15,\ \Delta_\text{min}=0.25\text{s}
$$

可选 Cubic Hermite（速度切线，按 `hermiteTangentChordRatio=3.0` 限幅）或 Centripetal Catmull-Rom（$\alpha=0.5$）。

### 10.5 静止锚定（EgoAnchor 核心增强）

**"静止即锚、默认锁定、证据解锁"** 的先验层，叠加在 `MotionModel×Smoothing` 之上。多数 MR 物体长期静止，头动与观测噪声主导其表观抖动。

**进入锁定：** 观测线速度 $\le$ `enterSpeedMps=0.05`、角速度 $\le$ `enterAngSpeedDps=35`、score $\ge$ `minScore=0.25`，持续 `dwellSeconds=0.35` s

**多路解锁证据（任一触发）：**

| 机制             | 含义                                                             | 关键默认                                 |
| ---------------- | ---------------------------------------------------------------- | ---------------------------------------- |
| 可靠性加权 CUSUM | 超死区位移按 score 加权累积、半衰期衰减                          | 阈值`0.08 m / 20°`，半衰期 `0.27 s` |
| 绝对漂移租绳     | 观测共识相对锚原点的绝对位移                                     | `0.015 m / 5°`                        |
| 速度逃逸         | 观测速度$>$ 进入阈值×`unlockSpeedFactor=2.5` 持续 `0.4 s` | —                                       |
| 低分释放         | score$<$ `0.3` 持续 `0.6 s`                                | —                                       |

**死区**（位置 `0.008 m`、旋转 `3°`）内视为噪声不累积；**漏积分蠕变**（半衰期 `2.7 s`、score 加权、头动门控）把锁点缓慢精修到共识中心；**解锁接缝** 用残差衰减（`seamDecayPerFrame=0.85`）平滑过渡；**重锁抑制** `1.0 s` 防抖振。

**头动感知与距离自适应：**

- 头动 **放宽** 位置/旋转阈值（`headMaxToleranceFactor` 至 4×）并抑制蠕变；头停后 `headSettleSeconds=0.6` s 内冻结解锁证据，待共识消化头动残差
- 距离自适应：位置容差随物体距离放大（补偿双目立体几何重建的深度噪声 $\propto z$），`refDist=0.4 m, slope=1.0, maxFactor=3.0`；**仅放大位置，不改旋转**

---

## 11. Unity 渲染应用层

`DynamicObjectAnchor` 是最薄一层：只读 `PoseToAnchorRuntime` 的最终输出并写到目标 Transform；无网络、无滤波、无状态机。`AnchorRuntimeHub` 负责把同一 `PoseResult` 扇出给多个并行 runtime（用于策略对比研究）。

---

## 12. 命令与生命周期

### 12.1 命令类型

Unity → Python：`reset`、`reacquire`（NEXT_VALID_FRAME / LATEST_FRAME_IF_AVAILABLE / FORCE_DETECT）、`control`（SET_STAGE / PAUSE / RESUME）。在 Python 当前实现中，`reset` 与 `reacquire` 都会清空 pipeline tracking state。

handler 层：类型校验 → 参数校验 → `request_id` 去重（TTL `60000 ms`）→ 入队（`max_queue_size=128`）→ 立即回 `CommandAck`。**真正执行在 runtime owner 线程的 tick 边界**（每 tick 至多 8 条）。

`CommandAck.accepted=true` 只表示"已接受"，不表示"已执行完成"；实际完成通过 `AnchorStatusEvent` 与 `ServerHeartbeat` 回馈。

自动重获取与手动重获取走同一条 NATS command path，但触发源不同：自动重获取由 `AnchorPolicyHost` 在持续低分或 Lost 状态下置位 `wantsServerReacquire`，经 `PoseToAnchorRuntime` 透传、`AnchorRuntimeHub` 汇总后由唯一 command client 发送；手动重获取来自用户或调试入口。Python handler 不直接触碰 GPU/pipeline 状态，只把已去重命令排入队列，由 runtime owner 在 tick 边界串行执行。

### 12.2 评估会话协同

`runtime.logging.eval_session_enabled=true` 时，Python 在 `data/eval/<session_id>/` 创建共享目录并写 `python_session.json` 元数据；Unity 据此自动配对两侧 JSONL 日志，供离线评估使用。

---

## 13. 离线预测仿真（EgoAnchor_Tools3）

`AnchorUpsampleSim3`（.NET 8 控制台）是离线基准：回放录制的低频观测，通过多种预测/平滑策略产出渲染频率轨迹并计算指标，用于在真机部署前 **离线验证与调参**，其预测器与 Unity 锚定策略一一对应。默认会从 `*_unity_output.jsonl` 实测渲染帧率与采集-渲染延迟；若日志缺少必要字段或用户显式指定参数，则回退到 60 Hz、300 ms latency 与 ±60 ms jitter。

### 13.1 仿真流程

1. 从 `*_unity_output.jsonl` 加载观测（`aligned_raw_pos/rot` + `reliability_score` + 可选子分/flags/头部 pose）。
2. `RealtimeSimulator` 以固定渲染时钟推进；**关键：观测按 `capture_time + latency + jitter` 延迟投递**，而非采集即到。默认优先从录制日志实测 render Hz 与 latency；测不到时用 60 Hz、300 ms latency、±60 ms jitter。早期"采集即到"会导致"离线平滑、真机抖动"的失配。
3. 每渲染帧：投递到期观测 → `OnObservation` → `PredictAt(now)` → 记录样本。
4. 计算指标、导出每策略轨迹 JSONL 与对比图。所有"随机"均为确定性 hash，可复现。

### 13.2 预测器与 Unity 对应

| Tools3 预测器                                  | 数学要点                                                                | Unity 对应            |
| ---------------------------------------------- | ----------------------------------------------------------------------- | --------------------- |
| `RawZohPredictor`                            | 零阶保持                                                                | RawPassthrough        |
| `DeadReckoningSplinePredictor`               | 死推 + C¹ Hermite 修正窗（零延迟，工业游戏引擎做法）                   | —（基线对照）        |
| `KalmanPredictor`(+`ScalarCvKalman`)       | 同 §10.3 CV Kalman，**有** `maxPredictAhead=0.18` 限幅         | KalmanModel           |
| `OneEuroPredictor`(+`ScalarOneEuro`)       | 同 §10.3 1€，限幅`0.12`                                             | OneEuroModel          |
| `ResidualBlendingPredictor`                  | 外推+残差指数衰减（`decayPerFrame=0.9`），可插 CV/Kalman/1€ 运动模型 | BlendStrategy         |
| `DelayedInterpolationPredictor`(+`Spline`) | 延迟插值，Hermite / Centripetal Catmull-Rom                             | DelayedInterpStrategy |
| `EgoAnchorStabilizerPredictor`               | 装饰器：静止锚定 + 多路解锁 + 头动/距离自适应（同 §10.5，~25 参数）      | `StaticLockController` |

> 注意区别：Tools3 独立预测器保留 `maxPredictAhead` 限幅；Unity 运动模型 **取消限幅**，把外推边界交给 smoothing。两者参数（Q/R、minCutoff/beta、decay、静止锚定阈值）保持一致以保证离线结论可迁移到真机。

### 13.3 鲁棒性注入与指标

- `BadPoseInjector`：周期性跳变尖刺（`jumpPeriod=23` 帧、`0.15 m / 35°`、低分 `0.15`）、噪声爆发段（`0.02 m`）、低分段（`0.2`），均确定性可复现。
- `MetricsCalculator`：平滑度（相邻帧步进 RMS，mm/deg）、时延（互相关估计 lag）、对齐精度（按 lag 补偿后误差）、直通精度（不补偿）、起步时延 onset-lag（静→动的响应延迟，量化静止锚定代价）。

---

## 14. 定量评估流水线（EgoAnchor_Python/eval）

离线从录制日志计算锚定体验质量指标。

### 14.1 总流程与日志对齐

`run_eval.py` 加载三类 JSONL：Unity capture（含 GT 物体位姿 `gt_pos/gt_rot` + 相机/头部位姿）、Unity output（每渲染 tick 的各变体锚点位姿 + 诊断）、Python runtime（每帧 `pose_result`，含各阶段耗时）。**以 `frame_id` 为主键** 左连接 capture 与 Python 日志；output 表展开为"每变体每 tick 一行"长表，按 manifest 的 `condition_spans` 打条件标签。

### 14.2 指标定义（要点）

| 指标             | 度量                       | 关键公式/方法                                                                                       | 单位              |
| ---------------- | -------------------------- | --------------------------------------------------------------------------------------------------- | ----------------- |
| Anchor Error     | 锚点 vs GT 的 SE(3) 误差   | $E=(T^w_\text{GT})^{-1}T^w_\text{anchor}$，平移 $\lVert E_{:3,3}\rVert$，旋转 $2\arccos|q_w | $ |                   |
| Pose Offset      | 有符号位姿偏置（标定诊断） | $\text{offset}=p_\text{out}-p_\text{gt}$，相对四元数转欧拉                                        | m / deg           |
| Jitter           | 静止窗内高频抖动           | GT 静止窗（$\lVert v\rVert\le0.03$ m/s）内 1 Hz 高通后位置 RMS                                    | m / deg           |
| Lag              | 锚点滞后真实运动           | 沿最大方差轴速度互相关峰（±500 ms 内，30 Hz 重采样）                                               | ms                |
| Latency          | 端到端/分阶段时延          | `render_mono_ms − source_capture_mono_ms`，及 yolo/depth/cutie/pose 分项                         | ms（p50/p90/p95） |
| Jump Suppression | 异常抑制有效性             | 误差$>0.05$ m 的尖刺计数 vs policy reject 计数                                                    | 计数              |
| Slip             | 屏幕空间漂移               | 锚点与 GT 原点投影到像平面的像素距离                                                                | px（RMS/peak）    |
| Recovery         | 遮挡/丢失后恢复时间        | 事件后首个误差$\le0.05$ m 且维持 `hold_ms=200` ms 的时刻                                        | ms                |
| Diagnostics      | 分数健康 + 渲染开销        | score 众数占比、尖刺漏检率、render_quality 耗时分位                                                 | —                |

产出：各指标 CSV + `summary.md` + 一组 PNG/PDF 图（误差时间线、时延堆叠、jitter-lag 散点、slip 时间线、recovery 柱状）。`plot_recorded_strategies.py` 还能把同一会话下不同平滑/预测策略的 6 通道（XYZ + RotVec XYZ）轨迹叠加对比。

> 共享指标引擎按各指标语义过滤有效样本。RQ2 不使用统一的“GT 有效且有输出”过滤：显示误差保留 Lost 后 hold-last，主终点则把 runtime 无输出计为失败。*Frame-aligned* / *Arrival-aligned* 仅诊断相机位姿取样时刻错配，不进入物体运动时延主模型，也不作为 RQ2 的核心消融。

### 14.3 RQ2 专用动态分析

RQ2 使用 `eval/research/rq2/` 下的专用分析包，不复用静态场景的聚合口径：

| 模块 | 职责 |
|---|---|
| `contract.py` | 预注册阈值、正式重复次数与稳定输出列 |
| `trajectory.py` | 新鲜参考轨迹、有效运动区间和图像前局部运动拟合 |
| `source.py` | 每个 source 首现的 raw 误差与有符号时延残差 |
| `lag.py` | 连续段互相关与峰值可辨识性诊断 |
| `qc.py` | 会话、trial 和正式设计三级审计 |
| `paired.py` | *Full* 与 *Raw-ZOH* 的试次级配对差值 |
| `model.py` | 等 trial 权重的运动—时延探索性关联 |
| `pipeline.py` | 多会话编排、经验运行包络、表格和图形导出 |

Unity 按键仅界定粗 trial 包络。Python 从控制器平台参考轨迹计算平滑线速度与角速度，桥接短暂低速间隙并删除过短运动段，形成 `active_motion`。正式 trial 至少包含 8 s 有效运动；每个录制会话的三类运动各需 8 个合格 trial，联合分析至少包含 3 个独立会话。

动态主终点是误差容限内有效追踪率：有效运动帧同时满足 runtime 有输出、显示平移误差不超过 50 mm、显示旋转误差不超过 10° 才记为成功。分母包含 runtime 丢失帧，因此不会因只统计成功输出而产生幸存者偏差。显示误差仍使用 `display_*`，保留用户实际看到的 hold-last；可用率只使用 `has_output_pose`。

图像时刻 raw 误差与渲染时刻显示误差属于不同诊断层，不能解释为同一位姿的“补偿前后”。运动—时延分析只在图像时间代理之前 400 ms 的参考轨迹局部稳态且运动轴一致时纳入样本；`v·τ` / `ω·τ` 只作为探索性解释变量，不作感知时延的因果验证。轨迹 lag 仅在样本长度、动态激励、峰值相关、峰值突出度和非边界峰均通过时报告；不再对自相关帧计算 Pearson p 值或 Bonferroni 显著性。

统计先在试次内计算 *Full* − *Raw-ZOH*，再以录制会话为最高层、trial 为次层执行层级 bootstrap。经验运行包络按实测线速度或角速度分箱，并让每个 trial 具有相同总权重；未采样区间不外推为物理性能边界。

正式分析输出 source、motion-delay、trial、paired、operating-envelope、latency、model、lag-diagnostics 八类结果表，以及 session/trial/design 三类审计表。后台日志队列只要出现丢行、动态参考位姿使用 keep-alive、双变体声明不完整或 trial 参考覆盖不足，该会话或 trial 就不会进入正式配对与关联统计。

---

## 15. 关键参数总表（按子系统）

| 子系统         | 参数                                               | 默认值                                          | 含义                      |
| -------------- | -------------------------------------------------- | ----------------------------------------------- | ------------------------- |
| 传输           | ZMQ 端口 / receive_hwm / poll                      | 15557 / 20 / 10 ms                              | 数据面                    |
| 传输           | NATS url / max_pending_futures                     | 127.0.0.1:4222 / 32                             | 消息面背压                |
| 命令           | max_queue_size / dedup_ttl_ms / execute_per_tick   | 128 / 60000 ms / 8                              | 命令队列                  |
| 采集           | FramePoseHistory capacity / cameraPoseDelayFrames  | 512 / 1                                         | 帧位姿历史                |
| 标定           | process_width × height / assume_center_crop       | 640×480 / true                                 | 处理分辨率                |
| 深度           | min_depth / max_depth / valid_iters / max_disp     | 0.1 / 5.0 m / 4 / 192                           | FFS                       |
| 分割           | confidence_threshold / max_det / mask_threshold    | 0.2 / 1 / 0.5                                   | YOLOE-26/SAM3 共用        |
| Cutie          | seg_threshold / erosion_size                       | 0.1 / 5                                         | mask 传播                 |
| FoundationPose | est_refine_iter / track_refine_iter                | 5 / 2                                           | register/track 迭代       |
| FoundationPose | register_min_depth_valid_in_mask                   | 0.15                                            | 注册深度门限              |
| 可靠性         | geo_floor / reproj_weight / depth_weight           | 0.05 /**0.2** / **0.8**             | C/D 一致性核（toml 覆盖） |
| 可靠性         | depth_distance_ratio / depth_min_inlier_thresh_m   | 0.02 / 0.005 m                                  | 深度对齐阈值              |
| 可靠性         | color_l_weight / downscale / min_render_area_px    | 0.3 / 2 / 50                                    | 颜色投影                  |
| 可靠性         | warmup_frames                                      | 3                                               | register 后评分预热       |
| 状态机         | coastTimeoutSeconds / lostTimeoutSeconds           | 0.45 / 1.0 s（源码默认；场景可覆盖 2.0 s）      | gap 升级                  |
| 状态机         | trackingScoreFloor / lowScoreReacquire             | 0.0 源码默认（场景可覆盖 0.5）/ 0.45 持续 0.6 s | 状态提示 / 重注册         |
| Kalman         | pos proc/meas noise                                | 0.20 / 0.0004                                   | 位置                      |
| Kalman         | rot proc/meas noise                                | 0.40 / 0.0025                                   | 旋转切空间                |
| OneEuro        | minCutoff / beta / dCutoff                         | 1.0 / 0.25 / 1.0                                | 自适应低通                |
| Blend          | decayPerFrame / latencyMult / maxExtrap            | 0.9 / 1.0 / 0.3 s                               | 残差融合                  |
| DelayedInterp  | safetyMargin / minDelay / tangentChordRatio        | 1.15 / 0.25 s / 3.0                             | 延迟插值                  |
| 静止锚定       | enterSpeed / enterAngSpeed / dwell / minScore      | 0.05 m·s⁻¹ / 35°·s⁻¹ / 0.35 s / 0.25     | 进入锁定                  |
| 静止锚定       | deadband pos/rot                                   | 0.008 m / 3°                                   | 噪声死区                  |
| 静止锚定       | CUSUM 阈值 pos/rot / 半衰期                        | 0.08 m / 20° / 0.27 s                          | 解锁证据                  |
| 静止锚定       | drift leash pos/rot                                | 0.015 m / 5°                                   | 漂移租绳                  |
| 静止锚定       | headMaxToleranceFactor / headSettle / posMaxFactor | 4.0 / 0.6 s / 3.0                               | 头动/距离自适应           |
| Tools3         | renderHz / latency / jitter                        | 默认自动实测；回退 60 / 300 / 60 ms             | 仿真投递                  |
| Eval           | jitter 静止阈 / lag 窗 / 尖刺阈 / recovery hold    | 0.03 m·s⁻¹ / ±500 ms / 0.05 m / 200 ms      | 指标参数                  |

---

## 16. 脚本实现位置索引（traceability）

> 每条对应正文技术点的实现位置，路径相对仓库根。行号为分析时刻的近似定位，便于检索。

### 16.1 协议与传输

- 协议定义：[EgoAnchor_Protocol/proto/protocol/v1/common.proto](EgoAnchor_Protocol/proto/protocol/v1/common.proto)、[quest.proto](EgoAnchor_Protocol/proto/protocol/v1/quest.proto)、[anchor.proto](EgoAnchor_Protocol/proto/protocol/v1/anchor.proto)
- 主题清单：[EgoAnchor_Protocol/subjects.v1.json](EgoAnchor_Protocol/subjects.v1.json)、[src/egoanchor/protocol/subjects.v1.json](EgoAnchor_Python/src/egoanchor/protocol/subjects.v1.json)
- 主题常量：[src/egoanchor/protocol/subjects.py:11](EgoAnchor_Python/src/egoanchor/protocol/subjects.py#L11)
- Protobuf 注册/解析：[src/egoanchor/protocol/protobuf_registry.py:14](EgoAnchor_Python/src/egoanchor/protocol/protobuf_registry.py#L14)
- 头部工具：[src/egoanchor/protocol/header_utils.py](EgoAnchor_Python/src/egoanchor/protocol/header_utils.py)
- NATS 路由：[src/egoanchor/routing/nats_router.py:22](EgoAnchor_Python/src/egoanchor/routing/nats_router.py#L22)
- ZMQ 接收（latest-drain）：[src/egoanchor/transport/zmq_topic_subscriber.py:111](EgoAnchor_Python/src/egoanchor/transport/zmq_topic_subscriber.py#L111)
- NATS 客户端（背压/重连）：[src/egoanchor/transport/nats_client.py:31](EgoAnchor_Python/src/egoanchor/transport/nats_client.py#L31)
- Unity ZMQ 发布：[Assets/Scripts/EgoAnchor/Transport/ZmqTopicPublisher.cs:16](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Transport/ZmqTopicPublisher.cs#L16)
- Unity NATS 收发：[Transport/NatsBytesClient.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Transport/NatsBytesClient.cs)、[Client/NatsControlClient.cs:26](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Client/NatsControlClient.cs#L26)
- Unity 主题名：[Assets/Scripts/EgoAnchor/Protocol/SubjectNames.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/SubjectNames.cs)

### 16.2 Unity 采集端

- 双目采集 + frame_id 自增：[Assets/Scripts/EgoAnchor/Quest/StereoFrameSource.cs:131](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Quest/StereoFrameSource.cs#L131)
- 相机内参/基线：[Quest/CameraInfoSource.cs:40](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Quest/CameraInfoSource.cs#L40)
- 帧位姿历史（环形缓存）：[Alignment/FramePoseHistory.cs:44](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/FramePoseHistory.cs#L44)（`TryGet` 见 [:77](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/FramePoseHistory.cs#L77)）
- 采集发布：[Client/QuestStreamPublisher.cs:184](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Client/QuestStreamPublisher.cs#L184)、[Quest/QuestStreamSession.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Quest/QuestStreamSession.cs)

### 16.3 Python 运行时与感知

- 入口：[src/run_server.py](EgoAnchor_Python/src/run_server.py)、[app/tracking_server.py](EgoAnchor_Python/src/egoanchor/app/tracking_server.py)
- 主循环 tick：[runtime/tracking_runtime.py:220](EgoAnchor_Python/src/egoanchor/runtime/tracking_runtime.py#L220)
- 输入接收/去重：[runtime/quest_stream_receiver.py:80](EgoAnchor_Python/src/egoanchor/runtime/quest_stream_receiver.py#L80)
- 运行时状态：[runtime/runtime_state.py](EgoAnchor_Python/src/egoanchor/runtime/runtime_state.py)
- 感知主流程：[perception/quest_pose_pipeline.py:255](EgoAnchor_Python/src/egoanchor/perception/quest_pose_pipeline.py#L255)
- 标定映射：[perception/quest_calibration.py:104](EgoAnchor_Python/src/egoanchor/perception/quest_calibration.py#L104)
- 异步分割：[perception/async_segmenter.py:86](EgoAnchor_Python/src/egoanchor/perception/async_segmenter.py#L86)
- 配置：[config/defaults.toml](EgoAnchor_Python/src/egoanchor/config/defaults.toml)、[config/runtime_config.py](EgoAnchor_Python/src/egoanchor/config/runtime_config.py)

### 16.4 算法 wrapper

- 分割（YOLOE-26 或 SAM3，同一接口）：[algorithms/yoloe26_segmenter.py](EgoAnchor_Python/src/egoanchor/algorithms/yoloe26_segmenter.py)、[algorithms/sam3_segmenter.py](EgoAnchor_Python/src/egoanchor/algorithms/sam3_segmenter.py)、[algorithms/segmenter_utils.py:29](EgoAnchor_Python/src/egoanchor/algorithms/segmenter_utils.py#L29)
- Cutie mask 传播：[algorithms/cutie_mask_tracker.py:102](EgoAnchor_Python/src/egoanchor/algorithms/cutie_mask_tracker.py#L102)
- 双目立体几何重建（深度公式）：[algorithms/fast_foundationstereo_depth.py:453](EgoAnchor_Python/src/egoanchor/algorithms/fast_foundationstereo_depth.py#L453)
- 6DoF 位姿（register/track）：[algorithms/foundationpose_estimator.py:337](EgoAnchor_Python/src/egoanchor/algorithms/foundationpose_estimator.py#L337)

### 16.5 可靠性评估

- VCD 综合评分 $R=V\times G_\text{CD}$：[reliability/pose_quality.py:122](EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L122)
- C/D 一致性核（加权对数几何平均）：[reliability/pose_quality.py:247](EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py#L247)
- 颜色投影（Color projection，LAB ZNCC）：[reliability/reprojection.py:245](EgoAnchor_Python/src/egoanchor/reliability/reprojection.py#L245)
- 深度对齐：[reliability/depth_alignment.py:101](EgoAnchor_Python/src/egoanchor/reliability/depth_alignment.py#L101)
- 渲染质量编排：[reliability/render_quality.py](EgoAnchor_Python/src/egoanchor/reliability/render_quality.py)

### 16.6 Unity 帧对齐

- 核心对齐合成 $T^w_o=T^w_{c,f}T^c_o$：[Alignment/CameraPoseFrameAligner.cs:167](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/CameraPoseFrameAligner.cs#L167)
- 矩阵读取约定：[Alignment/CameraPoseFrameAligner.cs:219](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/CameraPoseFrameAligner.cs#L219)
- 轴翻转 $S R S$：[Alignment/AnchorPoseTransform.cs:131](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/AnchorPoseTransform.cs#L131)
- 接收→对齐→策略：[Runtime/PoseToAnchorRuntime.cs:270](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs#L270)
- 扇出 hub：[Runtime/AnchorRuntimeHub.cs:160](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRuntimeHub.cs#L160)

### 16.7 Unity 锚定策略

- 编排：[Policy/AnchorPolicyHost.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs)
- 状态机：[Policy/Lifecycle/AnchorStateMachine.cs:32](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Lifecycle/AnchorStateMachine.cs#L32)
- 质量评估门控（`enableQualityGate` 内联可选观测拒绝）：[Policy/Contracts/QualityGateDecision.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Contracts/QualityGateDecision.cs)、低分重获取诊断用观测几何加权 [Contracts/AnchorObservation.cs:75](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Contracts/AnchorObservation.cs#L75)
- 四元数 Log/Exp/slerp/积分：[Policy/Math/AnchorMath.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Math/AnchorMath.cs)
- CV Kalman：[Policy/Math/ConstVelocityKalman.cs:71](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Math/ConstVelocityKalman.cs#L71)、[Models/KalmanModel.cs:16](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Models/KalmanModel.cs#L16)
- 1€ 滤波：[Policy/Math/ScalarOneEuro.cs:61](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Math/ScalarOneEuro.cs#L61)、[Models/OneEuroModel.cs:14](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Models/OneEuroModel.cs#L14)
- 常速度模型：[Models/ConstantVelocityModel.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Models/ConstantVelocityModel.cs)
- 平滑策略：[Smoothing/BlendStrategy.cs:72](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Smoothing/BlendStrategy.cs#L72)、[Smoothing/DelayedInterpStrategy.cs:99](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Smoothing/DelayedInterpStrategy.cs#L99)、[Smoothing/RawPassthroughStrategy.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Smoothing/RawPassthroughStrategy.cs)、样条 [Policy/Math/Spline.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Math/Spline.cs)
- 静止锚定（`StaticLockController` 实现）：[Policy/StaticLockController.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/StaticLockController.cs)、[Policy/EgoAnchorStaticLockModule.cs:21](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/EgoAnchorStaticLockModule.cs#L21)
- 渲染应用：[Runtime/DynamicObjectAnchor.cs:81](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/DynamicObjectAnchor.cs#L81)

### 16.8 命令与会话

- Python 命令 handler：[handlers/command_handlers.py:100](EgoAnchor_Python/src/egoanchor/handlers/command_handlers.py#L100)
- 命令执行：[runtime/commands.py:319](EgoAnchor_Python/src/egoanchor/runtime/commands.py#L319)
- 评估会话协同：[runtime/eval_session.py:39](EgoAnchor_Python/src/egoanchor/runtime/eval_session.py#L39)
- 运行时日志：[runtime/runtime_log_writer.py](EgoAnchor_Python/src/egoanchor/runtime/runtime_log_writer.py)
- Unity 命令客户端：[Client/AnchorCommandClient.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Client/AnchorCommandClient.cs)

### 16.9 离线仿真（Tools3）

- 入口/仿真器：[EgoAnchor_Tools3/Program.cs:32](EgoAnchor_Tools3/Program.cs#L32)、[Sim/RealtimeSimulator.cs:54](EgoAnchor_Tools3/Sim/RealtimeSimulator.cs#L54)
- 观测加载：[Data/ObservationLoader.cs:91](EgoAnchor_Tools3/Data/ObservationLoader.cs#L91)
- 预测器：[Predictors/KalmanPredictor.cs](EgoAnchor_Tools3/Predictors/KalmanPredictor.cs)、[Predictors/OneEuroPredictor.cs](EgoAnchor_Tools3/Predictors/OneEuroPredictor.cs)、[Predictors/ResidualBlendingPredictor.cs:28](EgoAnchor_Tools3/Predictors/ResidualBlendingPredictor.cs#L28)、[Predictors/Interp/DelayedInterpolationPredictor.cs:30](EgoAnchor_Tools3/Predictors/Interp/DelayedInterpolationPredictor.cs#L30)、[Predictors/DeadReckoningSplinePredictor.cs:29](EgoAnchor_Tools3/Predictors/DeadReckoningSplinePredictor.cs#L29)、[Predictors/EgoAnchorStabilizerPredictor.cs:43](EgoAnchor_Tools3/Predictors/EgoAnchorStabilizerPredictor.cs#L43)
- 注入与指标：[Eval/BadPoseInjector.cs:47](EgoAnchor_Tools3/Eval/BadPoseInjector.cs#L47)、[Eval/MetricsCalculator.cs:26](EgoAnchor_Tools3/Eval/MetricsCalculator.cs#L26)
- 旋转/数学：[Core/Rotation.cs](EgoAnchor_Tools3/Core/Rotation.cs)、[Core/Math.cs](EgoAnchor_Tools3/Core/Math.cs)

### 16.10 定量评估（eval）

- 入口：[eval/run_eval.py](EgoAnchor_Python/eval/run_eval.py)
- 日志加载/schema：[eval/io/log_loader.py](EgoAnchor_Python/eval/io/log_loader.py)、[eval/io/schemas.py](EgoAnchor_Python/eval/io/schemas.py)
- 指标：[eval/metrics/anchor_error.py:79](EgoAnchor_Python/eval/metrics/anchor_error.py#L79)、[jitter.py:26](EgoAnchor_Python/eval/metrics/jitter.py#L26)、[lag.py:16](EgoAnchor_Python/eval/metrics/lag.py#L16)、[latency.py:46](EgoAnchor_Python/eval/metrics/latency.py#L46)、[jump_suppression.py:23](EgoAnchor_Python/eval/metrics/jump_suppression.py#L23)、[slip.py:18](EgoAnchor_Python/eval/metrics/slip.py#L18)、[recovery.py:22](EgoAnchor_Python/eval/metrics/recovery.py#L22)、[diagnostics.py:31](EgoAnchor_Python/eval/metrics/diagnostics.py#L31)、[common.py](EgoAnchor_Python/eval/metrics/common.py)
- 报表/图：[eval/report/tables.py](EgoAnchor_Python/eval/report/tables.py)、[eval/report/figures.py](EgoAnchor_Python/eval/report/figures.py)、[eval/plot_recorded_strategies.py:40](EgoAnchor_Python/eval/plot_recorded_strategies.py#L40)

---

## 17. 一条完整链路（端到端回顾）

1. **Unity 采集**：读左右图与左/右/中心相机世界位姿；按 `cameraPoseDelayFrames` 绑定略早的相机位姿。
2. **记录历史**：把 `frame_id → 采集时刻相机位姿` 写入 FramePoseHistory（容量 512）。
3. **发送**：`QuestStereoFrame`（JPEG）与 `QuestCameraInfo` 经 ZMQ 发往 Python。
4. **Python 接收**：latest-drain 取最新输入，session/frame 去重。
5. **感知**：解码 → 统一分辨率 → 刷新 $K'$ → 分割（YOLOE-26 或 SAM3 初始分割 + Cutie 传播）→ 深度（$Z=f_x s b/d$）→ FoundationPose register/track → 渲染质量回查。
6. **可靠性**：$R=V\cdot G_\text{CD}$，打包 `PoseResult`（camera-space 4×4 + V/C/D 质量子分与诊断 flags）经 NATS 发布。
7. **Unity 对齐**：按 `frame_id` 回查采集时刻相机位姿，$T^w_o=T^w_{c,f}\,T^c_o$，合成 world anchor。
8. **锚定策略**：MotionModel（CV/Kalman/1€）+ Smoothing（Raw/Blend/DelayedInterp）+ 静止锚定 + 生命周期管理；完整方法可打开 `enableQualityGate` 做质量评估门控。运动模型、平滑和静止锚定使用 capture-time measurement axis；生命周期 stale/lost 与低分持续时间使用 Unity arrival/sample time。
9. **渲染**：`DynamicObjectAnchor` 把最终 pose 写到目标 Transform。
10. **命令/恢复**：reset/reacquire/control 经 NATS 入队、tick 边界执行，状态经 `AnchorStatusEvent`/`ServerHeartbeat` 回馈。
11. **离线闭环**：Tools3 离线对比预测策略、eval 流水线从日志计算锚定质量指标，反哺参数与设计。

这条链路的关键不是"更快地发 pose"，而是 **"在正确的时间轴上，把 pose 锚到正确的世界参考上，并在低频含噪输入下保持稳定连续。"**
