# AGENTS.md

后续 AI 接手本仓库任务时，必须先阅读文件顶部的 **用户手动维护要求**。未阅读前不得修改代码。

<!-- USER-MAINTAINED-REQUIREMENTS:BEGIN -->

## 用户手动维护要求

本区由用户手动维护，放在文件顶部，方便查看和修改。后续 AI 只能读取、遵循和引用，不得自行修改、删减、重排、润色、合并或迁移本区内容。只有用户明确要求修改时，才可以改动本区，并且只改用户指定的内容。

1. Python 侧按包级入口导入，不深层导入到具体模块文件。包内可以使用 `from .image_utils import fit_to_size, stack_stereo` 这类显式 re-export；包外使用 `from egoanchor.algorithms import ...`，不要写成 `from egoanchor.algorithms.xxx import ...`。不要使用包级懒导出。
2. 代码需要有充分的中文说明。`.toml` 配置的每个参数都要在同一行末尾写中文注释；类、成员变量和每个方法也要补充中文说明。
3. 命名保持清楚、克制，不要为了“完整”把名字写得过长。
4. 修改代码前先从项目整体判断影响范围，检查模块配合、引用关系和架构边界。不要只做局部补丁，也不要零散修补。
5. 先读懂项目和计划，再严格按计划实现代码。发现计划与项目事实冲突时，及时指出并说明影响。过程中有任何问题请及时和我讨论交流，如果遇到任何不合理的事情立刻和我报告。
6. 重构时不要兼容已废弃的旧代码、旧接口或旧路径。
7. 使用 Code Simplifier 优化项目代码；处理文档和语言表述时使用 humanizer-zh。
8. 处理复杂或大型任务时，请使用子智能体辅助，加快梳理、审查和验证。
9. 改动时直接在我的这个git分支改动，我能看见改动了哪些。我git有备份没有关系，不用担心

<!-- USER-MAINTAINED-REQUIREMENTS:END -->

本文件是 EgoAnchor 的项目级 AI 接手指南。后续 Agent 进入本仓库时优先阅读并维护本文件；不要再新增分散 handoff 文档。这里只记录长期有效的事实、约定、路线和历史坑，避免流水账、临时调参和已废弃方案。

## 当前状态一句话

EgoAnchor 是面向 passthrough mixed reality 的 **frame-aligned、world-consistent real-object anchoring** 系统。当前仓库已清理为单主线结构：Python 主线位于 `EgoAnchor_Python/src`，Unity 主线位于 `EgoAnchor_Unity/Assets/Scripts/EgoAnchor`，采用 **ZMQ Protobuf 数据面 + NATS Protobuf 消息/命令面 + Unity frame-aligned anchor runtime**。旧 v1/v2、旧计划和早期 NATS 实验目录已移除。

论文目标是 IEEE VR 2027，核心主张必须围绕 **把异步 6DoF object pose stream 转化为稳定、世界一致、可恢复的 MR real-object anchor**，而不是包装成普通 pose tracking 工程。

## 仓库组成

- `EgoAnchor_Python/`：Python 端位姿估计服务和当前主线实现。
- `EgoAnchor_Unity/`：Unity/Quest 工程；采集 Passthrough Camera，发送图像/标定，接收 pose 并转换为 Unity world anchor。
- `EgoAnchor_Protocol/`：共享协议源，包含 `subjects.v1.json`、`proto/protocol/v1/*.proto`、`tools/generate_proto.ps1`；Python 运行时会读取同步到 `EgoAnchor_Python/src/egoanchor/protocol/subjects.v1.json` 的副本，便于只拷贝 `EgoAnchor_Python` 到 Ubuntu 运行。
- `2026-EgoAnchor/`：论文材料；当前源文件包括 `egoanchor_cn_outline.tex`、`egoanchor_cn_v1.tex` 与 `egoanchor_cn_refs.bib`。
- `EgoAnchor_Tools/`：与主系统分离的辅助工具脚本（部分旧工具 csproj 因 Policy 重构已无法编译）。
- `EgoAnchor_Tools3/`：自包含的离线升采样仿真（不依赖 Unity DLL，自带 Vec3/Quat 数学）。用真机录制的观测离线对比所有平滑策略并出曲线，默认自动复现真机的采集-渲染延迟和渲染帧率，是当前主用离线分析工具。`EgoAnchor_Tools2`、`EgoAnchor_Tools` 内的同类项目由其他 AI 维护。

## 项目级实现要求

本节只保留 EgoAnchor 专属补充约定，不重复文件顶部的用户手动维护要求，也不覆盖顶部要求。

- 生成的 `*_pb2.py` 内部 import 是协议生成结果，不要手改生成代码。
- Unity 端新增 Inspector 字段、网络参数、坐标语义和时间语义时，说明应落在 XML summary 或 `[Tooltip]` 中。
- 日志输出统一走项目门面：Python 使用 `egoanchor.utils.get_logger(...)` 与入口 `configure_logging(...)`，Unity 使用 `EgoAnchorLog.For<T>()`。日志消息本身不要手写 `[ClassName]` 前缀；component、等级、时间和彩色结构前缀由 logger/formatter 统一生成。
- 新增行为应先补测试或 smoke 验证。配置、文档、生成代码除外，但仍要给出可复现的验证命令。
- 论文和文档写法必须保守。不要把尚未实现或尚未实验验证的机制写成已完成贡献。

## 当前主线架构

EgoAnchor 固定采用双平面/三语义通道：

| 平面          | 传输               | 方向            | 数据                                                                           | 策略                                                                    |
| ------------- | ------------------ | --------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| Data Plane    | ZMQ PUB/SUB        | Unity -> Python | `QuestStereoFrame`、`QuestCameraInfo`                                      | Protobuf bytes，multipart `[topic_utf8, payload]`，topic latest-drain |
| Message Plane | NATS Core pub/sub  | Python -> Unity | `PoseResult`、`AnchorStatusEvent`、`ServerHeartbeat`                     | 小 payload，pose/heartbeat latest-only，status event stream             |
| Command Plane | NATS request/reply | Unity -> Python | `ResetTrackingRequest`、`ReacquireAnchorRequest`、`AnchorControlRequest` | `request_id` 幂等，快速 ack，runtime 串行执行                         |

当前主线能力：

- Python `tools/sam3/sam3_mask.py`：RealSense + SAM3 文本 prompt 实时 mask 调试工具，用于不接 Quest 时快速比较耳机盒等目标描述。
- Python `src/tracking_server.py`：接收 ZMQ Quest stereo/camera_info，运行可切换 YOLOE-26/SAM3 mask backend + FFS + FoundationPose/Cutie，显示 OpenCV debug，并可通过 NATS 发布 `PoseResult`、`AnchorStatusEvent`、`ServerHeartbeat`；默认仍是 YOLOE-26，显式配置 `module.segmenter.type="sam3"` 才加载 SAM3。SAM3 在初始 detect/register 前可通过 `module.sam3.async_segmentation=true` 后台异步分割，完成后用同一帧的 left/right RGB 与 mask 继续交给 FFS/FoundationPose，避免 RGB/mask 错帧。
- Python reliability：TRACK 阶段默认启用 `defaults.toml` 的 `[reliability.render_quality]` 渲染质量检测，当前保持 `mode="score_only"` shadow mode；通过 FoundationPose 适配器 facade 一次渲染 color/depth/mask，再由 `ReprojectionChecker` 只在 Cutie mask 与投影 mask 交集区域计算 LAB 颜色重投影分，由 `DepthAlignmentChecker` 只在同一交集区域计算渲染深度与 FFS 深度对齐分；Cutie mask 面积 / 渲染投影面积作为独立 `score_mask` 连续信号，写入 `render_quality_area_ratio_score`、`color_reprojection`、IoU、depth inlier、depth alignment、render/observed coverage、`render_quality_ms` 等 JSONL 字段；pose 可靠性分采用 `Gate(phase/reject) × Quality × Confidence`，其中 `Quality = geometry_core(reprojection, depth) × bounded_mod(mask, jump)`，只有有效几何信号进入几何合取核，mask/jump 只做有下限的温和调制；`PoseResult` 追加携带 `phase/reprojection/depth/jump/mask/reject/confidence` 评分子分和渲染质量细项，Unity 可用于 Inspector/HUD/policy 调参。
- Python command path：`NatsMessageClient -> NatsRouter -> HandlerRegistry -> CommandDedupStore/CommandQueue -> TrackingRuntime` 具备 reset/reacquire/control ack/enqueue/execution 骨架；runtime command 类型、幂等、队列、执行器和 pump 统一在 `egoanchor.runtime.commands`。
- Unity `QuestStreamPublisher`：发送 stereo/camera_info Protobuf；服务器 IP 由 `ServerEndpointConfig` 单点下发（`SetServerIp`，无 PlayerPrefs）。
- Unity `FramePoseHistory`：记录 `frame_id -> capture-time left/right/center camera world pose`。
- Unity `NatsControlClient`：订阅 PoseResult latest queue、ServerHeartbeat latest queue 和 AnchorStatusEvent event queue，并提供 bytes request/reply。
- Unity `PoseResultReceiver -> AnchorRuntimeHub -> PoseToAnchorRuntime`：主线程解码 PoseResult，广播给多个 runtime，支持多个 pipeline label 使用同一 frame-aligned raw pose 输入。
- Unity `CameraPoseFrameAligner`：将 Python OpenCV camera-space pose 按 `frame_id` 回查到 Unity world pose。
- Unity `Policy/` 模块化 anchor policy（已重构为两模块自由组合 3×2）：`AnchorPolicyHost` 持有一个 `MotionModel`（运动模型）+ 一个 `SmoothingStrategy`（平滑策略），二者正交、可任意组合。`MotionModel` 子类在 `Policy/Models`：`ConstantVelocityModel`（CV 差分）/`KalmanModel`/`OneEuroModel`，对外提供 `PredictAt(t)`（**不限幅外推**，给 B 路）和 `LatestControlPoint`（给 C 路插值）。`SmoothingStrategy` 子类在 `Policy/Smoothing`：`BlendStrategy`（B 路：高频外推+误差融合，零延迟）/`DelayedInterpStrategy`（C 路：延迟一周期+Hermite/向心 Catmull-Rom 插值）/`RawPassthroughStrategy`（纯零阶保持，真 raw 对照）。数据契约 DTO（`AnchorObservation`/`AnchorPolicyDecision`/`AnchorPolicyOutput`/`GateDecision`）在 `Policy/Contracts`，生命周期状态机与枚举（`AnchorStateMachine`/`AnchorPolicyTypes`）在 `Policy/Lifecycle`，纯数学（`AnchorMath`/`ConstVelocityKalman`/`ScalarOneEuro`/`Spline`）在 `Policy/Math`。消息入口 `AcceptPose` 只提交测量（可选内联 score 门控，只 EgoAnchor 方法开），渲染帧入口 `Advance(now)` 调 `strategy.Output(model, now)` 输出每帧 anchor pose。eval 字段名：C# 属性 `MotionModelName`/`SmoothingStrategyName`/`GateName`，对应 JSONL wire key `motion_model`/`smoothing_strategy`/`gate`（旧名 `estimator_module`/`output_module`/`gate_module` 已废弃，历史录制已迁移到新键，读写两端都不留兼容层）；变体每帧输出 pose 的 wire key 是 `has_output_pose`/`output_pos`/`output_rot`（旧名 `has_stable`/`stable_pos`/`stable_rot`，对应 `AnchorEvalJson.RecordedVariantSnapshot.HasOutputPose`/`OutputPose`、runtime API `PoseToAnchorRuntime.TryGetOutputPose`）；`PoseResult` proto 字段 `color_reprojection`（旧名 `track_reprojection`）和 `render_quality_evaluated`（旧名 `render_quality_expected`）也已改名（proto 字段号不变、二进制 wire 兼容，重新生成 `anchor_pb2.py`+`Anchor.cs`）。`score_phase` 等 `score_*` 子分保持原名（与 6 个兄弟字段一致，不是错名）。模块不读 Unity `Time`，时间由 runtime 显式传入。**旧的 Gate/Estimator/Output 三模块拆分（含 `raw_zoh`/`lowpass_predict`/`kalman_cv`/`oneeuro_vanilla`/`egoanchor_*` estimator/gate/output 类）已全部删除，不再兼容。**
  关键修复（真机延迟自适应）：真机采集-渲染延迟实测中位 ~300ms（Python 推理 159ms + 传输 + 陈旧）>> 观测周期 ~208ms。C 路延迟必须 = **实测采集-渲染延迟**（`DelayedInterpStrategy` 每帧测 `now-最新控制点时间` 的 EMA × 1.15），不是观测周期，否则插值目标比最新点还新 → 退化外推 → 锯齿跳变。B 路外推上限 = **实测延迟 × 倍数**（`BlendStrategy` 自适应），防急停冲过头。两者都不绑 fps，换更快显卡延迟自动变小、上限自动跟着减小。
- Unity `AnchorCommandClient`：公开 reset/reacquire/pause/resume/set stage API；`CommandAck.accepted=true` 只表示 Python 接受命令，不表示重定位完成。
- 低分/track-loss 自动 reacquire（上行 fan-in，无 leaf 持 client）：`AnchorPolicyHost` 持续低分(0.25/0.8s)→本地 `NotifyReacquire`；若几何子分也差(`HasGeometryConcern`，depth+reproj 都低=判定 track 丢)→置 `wantsServerReacquire` 标志（host **不持** client）。`PoseToAnchorRuntime.ConsumeServerReacquireRequest()` 透传，`AnchorRuntimeHub` 在 Publish 循环 fan-in 收集所有 runtime 的标志，用它持有的**唯一** `reacquireCommandClient` 发一次 NATS reacquire（冷却 3s + in-flight，server 级合并）。旧的独立 `AnchorRecoveryController` 已删除。`ServerEndpointConfig`（`Client/`，`[DefaultExecutionOrder(-1000)]`）单点配 IP：一个 `List<ServerPreset>`(RTX3090/RTX5090) 下拉，Awake 下发 `QuestStreamPublisher.SetServerIp` + `NatsControlClient.SetNatsUrl`，无 PlayerPrefs。

## 常用入口与验证

在 `EgoAnchor_Python` 目录运行：

```powershell
# 当前主线
pixi run python .\src\tracking_server.py
pixi run tool-yoloe26-mask
pixi run tool-sam3-mask

# Python 验证
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python -m unittest discover -s eval -p "test_*.py"
```

在仓库根目录运行 Unity 编译验证：

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

Unity anchor 离线升采样仿真（`EgoAnchor_Tools3`，自包含、不依赖 Unity DLL，是当前主用离线工具）：

```powershell
# 用真机录制 session 离线对比所有升采样策略，并出曲线 PNG。
# 默认自动从录制实测"采集-渲染延迟"和"渲染帧率"，复现真机时序（关键：零延迟会"离线平滑、真机抖"）。
dotnet run --project EgoAnchor_Tools3\AnchorUpsampleSim3.csproj -c Release -- --session EgoAnchor_Python\data\eval\<session> --zoom-start 8 --zoom-end 13
# --no-latency 还原旧的零延迟行为；--latency-ms / --render-hz 手动覆盖
```

注意：`EgoAnchor_Tools/anchor_policy_smoke`、`anchor_replay` 等旧工具的 csproj 仍 glob 已删除的 `Policy/Gate|Estimator|Output` 目录，重构后无法编译；它们属于早期辅助工具，未随新两模块架构更新。Unity 主线编译验证仍用上面的 `Assembly-CSharp.csproj`。

协议生成在 `EgoAnchor_Python` 目录运行，确保使用 pixi 环境中的 `protoc`：

```powershell
pixi run pwsh -File ..\EgoAnchor_Protocol\tools\generate_proto.ps1
```

`pixi run build` 会构建 FoundationPose C++ 扩展并生成 FFS ONNX/TRT artifacts，耗时且依赖 CUDA/TensorRT 环境；不要把它当轻量验证命令。

论文目录基于 VGTC 模板，但 `2026-EgoAnchor/makefile` 默认仍指向 `template.tex` / `template.bib`。构建 EgoAnchor 论文时必须显式指定主文件和 bib，或先更新 makefile，避免误编译模板。

## 配置与协议契约

### Python 配置

- 默认配置：`EgoAnchor_Python/src/egoanchor/config/defaults.toml`。
- 目标物体覆盖配置：`EgoAnchor_Python/src/egoanchor/config/objects.toml`，入口通过 `--object blue_mouse` / `pink_mouse` / `earphone` / `controller_right` / `controller_left` 选择；显式 `--config` 仍可在对象配置之后做临时覆盖。
- 加载器：`EgoAnchor_Python/src/egoanchor/config/runtime_config.py`。
- 每个 `.toml` 参数必须在同一行末尾写中文注释；新增参数时同步默认值、加载点、使用点和测试。
- 主要分组：`server`、`network.data_plane`、`network.message_plane`、`runtime.commands`、`pipeline.calibration/depth`、`reliability.render_quality`、`reliability.pose_score`、`module.segmenter/yoloe/sam3/ffs/foundationpose/cutie`、`debug`、`demo.video`、`demo.pose`。
- `module.segmenter.type` 支持 `yoloe26` 和 `sam3`；默认必须保持 `yoloe26`，耳机盒等覆盖配置可显式切到 `sam3`。`module.segmenter.confidence_threshold` 和 `module.segmenter.mask_threshold` 是 YOLOE/SAM3 共用阈值；后端专属配置只保留权重、输入尺寸、设备、异步等参数。SAM3 本地仓库和 checkpoint 默认位于 `EgoAnchor_Python/sam3` 与 `sam3/assets/sam3_ckpt/sam3.pt`；`module.sam3.async_segmentation=true` 只异步初始分割，不把 FoundationPose/Cutie 移出 `TrackingRuntime` owner 线程。
- `reliability.render_quality.enabled=true` 是默认值；真机联调已验证可默认采集渲染质量信号，但仍保持 `mode="score_only"`，只有确认误报率后再切 `mode="re_register"`。无效重投影信号（warmup、无 Cutie mask、渲染面积太小或 K 缺失）只写 `no_reprojection_signal` 或对应 status，不得触发重注册；depth 覆盖不足只让 `score_depth=0.5` 中性显示，并且不进入几何合取核。
- `reliability.pose_score` 控制 pose 可靠性合成：`geo_floor`、`reproj_weight`、`depth_weight` 用于 reprojection/depth 几何核，`mask_floor` 用于 mask 有界调制。HUD/JSONL 中的子分仍保持原始诊断语义，valid 标志只影响 `quality_score` 合成。（jump 子分已删除：逐帧跳变幅度无法区分坏 pose 和真实快动，坏 pose 拒绝交给几何核 + Unity anchor 层。）
- `runtime.logging.eval_session_enabled=true` 时，Python 启动会创建 `data/eval/<yyyyMMdd_HHmmss_object_id>/`，runtime JSONL 默认写入同目录 `<session_id>_python_runtime.jsonl`，并把该 `session_id` 写进每条 PoseResult 的 `header.session_id` 经 NATS 广播。Unity eval 录制按收到的 session_id 在本地建同名目录（不依赖共享文件系统），实现 Python 在远程服务器、Unity 在本地的跨机器配对；录完把服务器侧 `<session_id>_python_runtime.jsonl` 拷到本地同名目录即自动合并。
- 时区约定：所有人类可读时间和 session_id 统一用北京时间 (UTC+8)，与运行机器系统时区无关。Python 经 `src/egoanchor/utils/timezone.py` 的 `beijing_now()`（session_id、event log 文件名），Unity 经 `EvalSessionManifestJson.FormatLocal` / `EvalSessionController.BuildReadableSessionId` 的固定 +8 偏移。**机器对齐基准不碰**：单调钟 `mono_ms`（pose 时序/平滑插值基准）和 `created_unix_ms` / `*_utc`（UTC epoch，跨端对齐基准）与时区无关，保持原样。
- `network.message_plane.enabled=false` 可用于 Python-only debug，避免没有 NATS server 时阻塞模型调试。

### 共享协议

- 唯一 channel 源契约：`EgoAnchor_Protocol/subjects.v1.json`；Python 运行时副本位于 `EgoAnchor_Python/src/egoanchor/protocol/subjects.v1.json`，由协议生成脚本同步。
- Proto 源：`EgoAnchor_Protocol/proto/protocol/v1/common.proto`、`quest.proto`、`anchor.proto`。
- 默认生成输出：
  - Python：`EgoAnchor_Python/src/egoanchor/protocol/v1/*_pb2.py` 与 `EgoAnchor_Python/src/egoanchor/protocol/subjects.v1.json`
  - Unity：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/Generated/*.cs`
  - Unity subject 常量：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/SubjectNames.cs`
- 字段号进入共享 proto 后不得重排。删除字段必须在 proto 中 `reserved` 字段号和字段名。
- 业务代码不手写 subject 字符串；Python 从 `egoanchor.protocol` 包级入口导入常量，Unity 从 `SubjectNames` 使用常量。

主线逻辑 channels：

| Channel                               | 方向            | 传输               | Protobuf                                 | 说明                                                                     |
| ------------------------------------- | --------------- | ------------------ | ---------------------------------------- | ------------------------------------------------------------------------ |
| `egoanchor.v1.quest.stereo`         | Unity -> Python | ZMQ                | `QuestStereoFrame`                     | 高频双目 JPEG，latest-only                                               |
| `egoanchor.v1.quest.camera_info`    | Unity -> Python | ZMQ                | `QuestCameraInfo`                      | 低频标定，独立 latest cache                                              |
| `egoanchor.v1.pose.result`          | Python -> Unity | NATS               | `PoseResult`                           | 小型 pose 结果，latest-only；携带总分、flags、七个评分子分和渲染质量细项 |
| `egoanchor.v1.anchor.status`        | Python -> Unity | NATS               | `AnchorStatusEvent`                    | 状态事件流，reset/reacquire/pause/resume/state/error 闭环                |
| `egoanchor.v1.server.heartbeat`     | Python -> Unity | NATS               | `ServerHeartbeat`                      | 低频服务与输入健康状态，latest-only                                      |
| `egoanchor.v1.cmd.anchor.reset`     | Unity -> Python | NATS request/reply | `ResetTrackingRequest -> CommandAck`   | ack 只表示接受/拒绝                                                      |
| `egoanchor.v1.cmd.anchor.reacquire` | Unity -> Python | NATS request/reply | `ReacquireAnchorRequest -> CommandAck` | 重定位结果靠后续事件/pose                                                |
| `egoanchor.v1.cmd.anchor.control`   | Unity -> Python | NATS request/reply | `AnchorControlRequest -> CommandAck`   | stage/pause/resume 等控制                                                |

## 代码地图

### Python

- `src/tracking_server.py`：当前主入口 wrapper，调用 `egoanchor.app.tracking_server`。
- `tools/sam3/sam3_mask.py`：RealSense + SAM3 prompt mask 调参入口；顶部常量配置 prompt、置信度、分辨率和相机参数。
- `src/egoanchor/config/`：轻量配置。配置层只读 TOML，不导入 ZMQ/OpenCV/模型。
- `src/egoanchor/protocol/`：subject registry、protobuf registry、包级 Protobuf 入口；内含运行时 `subjects.v1.json` 副本，协议生成脚本会从 `EgoAnchor_Protocol/subjects.v1.json` 同步更新。
- `src/egoanchor/transport/zmq_topic_subscriber.py`：通用 ZMQ SUB；只负责 socket、multipart topic bytes、topic latest-drain，不导入 Protobuf/OpenCV/模型。
- `src/egoanchor/transport/nats_client.py`：唯一 NATS transport 文件；负责后台 asyncio NATS 连接、bytes publish/subscribe/request-reply callback 和 publish 限流，不理解 perception 或 Unity anchor。
- `src/egoanchor/routing/`：`HandlerRegistry`、`NatsRouter`、`iter_nats_request_specs`；负责 subject -> protobuf parse -> handler -> reply serialize。
- `src/egoanchor/handlers/command_handlers.py`：reset/reacquire/control request handler；只 validate/dedup/enqueue/ack，不直接碰 pipeline/GPU。
- `src/egoanchor/runtime/quest_stream_receiver.py`：ZMQ bytes -> Quest Protobuf -> latest store；内部包含 topic independent latest cache、frame_id/session 去重、camera_info version 和输入统计。
- `src/egoanchor/runtime/commands.py`：命令模型、命令队列、request_id TTL 幂等、runtime 内解释命令，以及在 `TrackingRuntime` owner 线程顺序解释并应用已 ack/enqueue command 的 pump。
- `src/egoanchor/runtime/tracking_runtime.py`：唯一 pipeline/GPU 状态 owner；poll Quest stream latest、运行 perception pipeline、发布 PoseResult/status/heartbeat，并把 command/logging 细节委托给 runtime helper。
- `src/egoanchor/runtime/message_factories.py`：`PoseObservation -> PoseResult`、Python runtime state/command/error -> `AnchorStatusEvent`、input stats/runtime stats -> `ServerHeartbeat` 映射；PoseResult 必须透传 `score_phase/score_reprojection/score_depth/score_mask/score_reject/score_confidence` 与渲染质量细项，其中 `score_reprojection` 当前语义是交集区域颜色重投影分。
- `src/egoanchor/runtime/eval_session.py`：Python 启动时创建评估 session 目录，并把 `session_id` 经 PoseResult `header.session_id` 经 NATS 广播给 Unity；Unity 据此在本地建同名目录配对（见上文 `runtime.logging.eval_session_enabled`）。仍会写 `python_session.json` 留作服务器侧自查，但 Unity 不再读它。
- `src/egoanchor/runtime/runtime_log_writer.py`：集中写入 PoseResult/status/heartbeat/command JSONL 结构化事件；eval session 启用时写入 `data/eval/<session_id>/<session_id>_python_runtime.jsonl`，否则回退到 `runtime_logs`。
- `src/egoanchor/perception/quest_pose_pipeline.py`：Quest pose pipeline；组合可切换 YOLOE-26/SAM3 mask backend、FFS、FoundationPose/Cutie，输出 camera-space `PoseObservation` 与 debug 图像，不依赖 ZMQ/NATS/Unity transform。SAM3 异步模式只把分割模型放入 latest-only worker；worker 输出携带原始 decoded frame/left/right 图，主 pipeline 线程消费后再做 depth/register。
- `src/egoanchor/perception/quest_calibration.py`：Quest camera_info 到算法处理分辨率 K 的映射，支持 center-crop 与线性缩放。
- `src/egoanchor/algorithms/`：单模型适配层；`yoloe26_segmenter.py` 和 `sam3_segmenter.py` 都输出统一 `SegmenterResult`，pipeline 不理解模型内部细节。
- `src/egoanchor/algorithms/foundationpose_estimator.py`：FoundationPose 适配器；公开 `render_color_depth_mask(...)` facade 给 reliability 层使用，reliability 代码不得直接访问第三方 estimator 内部 `glctx/mesh_tensors`。
- `src/egoanchor/reliability/reprojection.py`：重投影评分器；只消费渲染 color/mask 与观测 RGB/mask，重投影分只来自交集区域 LAB 颜色相似度，IoU、覆盖率和面积比仅作为诊断与 `score_mask` 来源。
- `src/egoanchor/reliability/depth_alignment.py`：深度对齐评分器；只消费渲染 depth、观测 depth 和交集 mask，按物体距离自适应 depth inlier 阈值，覆盖不足时给中性分。
- `src/egoanchor/reliability/render_quality.py`：一次渲染后协调 `ReprojectionChecker` 与 `DepthAlignmentChecker`，保持性能不变但拆清重投影和 depth 职责。
- `src/egoanchor/reliability/pose_quality.py`：感知可靠性评分，采用 `Gate(phase/reject) × Quality × Confidence`；`Quality` 由 reprojection/depth 有效几何信号的加权几何平均乘以 mask/jump 有界调制得到，输出 `reliability_score`、flags 和 `phase/reprojection/depth/jump/mask/reject/confidence` 子分。
- `src/egoanchor/diagnostics/`：OpenCV HUD、depth/mask/pose dashboard 等诊断工具；窗口创建辅助由 app 层就近维护。
- `eval/metrics/diagnostics.py`：离线轻量诊断，输出 score/color_reprojection 直方图、policy action/reason 分布、spike 漏检和 render_quality 开销统计；不导入 runtime 或模型。
- `src/egoanchor/tests/test_command_flow.py`：当前 command request/reply、dedup、executor 轻量测试。

### Unity

- `Assets/Scripts/EgoAnchor/Protocol/Generated/`：C# Protobuf 生成代码。
- `Assets/Scripts/EgoAnchor/Protocol/SubjectNames.cs`：由协议脚本生成的 subject 常量，不要手改。
- `Assets/Scripts/EgoAnchor/EgoAnchor.asmdef`：唯一手写 EgoAnchor 程序集；`Assets/Scripts/EgoAnchor` 下所有非生成手写脚本都归入该程序集。
- `Assets/Scripts/EgoAnchor/Transport/ZmqTopicPublisher.cs`：只管理 NetMQ PUB socket，发送 `[topic_utf8, protobuf_payload_bytes]`。
- `Assets/Scripts/EgoAnchor/Client/NatsControlClient.cs`：NATS 消息面客户端；订阅 PoseResult latest queue、AnchorStatusEvent event queue、ServerHeartbeat latest queue，提供 bytes request/reply；后台回调不改 Transform。
- `Assets/Scripts/EgoAnchor/Quest/StereoFrameSource.cs`：读取左右 Passthrough texture、记录 left/right/center camera pose、JPEG 编码、构造 `QuestStereoFrame`。
- `Assets/Scripts/EgoAnchor/Quest/CameraInfoSource.cs`：读取 Quest intrinsics/lens pose 并构造 `QuestCameraInfo`。
- `Assets/Scripts/EgoAnchor/Alignment/FramePoseHistory.cs`：`frame_id -> capture-time left/right/center camera world pose` 环形缓存，是 frame-aligned anchor 的关键。
- `Assets/Scripts/EgoAnchor/Alignment/CameraReference.cs`：Unity 本地对齐参考枚举。Python 当前语义仍是左目 OpenCV camera pose；Right/Center/None 只用于本地诊断、对照或小量补偿实验。
- `Assets/Scripts/EgoAnchor/Alignment/CameraPoseFrameAligner.cs`：OpenCV camera pose + frame history -> Unity world pose；包含 `AnchorPoseTransform` 轴翻转和固定 offset 配置。
- `Assets/Scripts/EgoAnchor/Client/QuestStreamPublisher.cs`：场景级 ZMQ 数据面发送组件；Python IP 由 `ServerEndpointConfig` 单点下发（无 PlayerPrefs）。
- `Assets/Scripts/EgoAnchor/Client/NatsTypedReceiver.cs`：PoseResult、AnchorStatusEvent、ServerHeartbeat 三类 Protobuf receiver 的主线程解码基类。
- `Assets/Scripts/EgoAnchor/Client/PoseResultReceiver.cs`：主线程 latest-drain、解析 PoseResult、交给 `AnchorRuntimeHub`。
- `Assets/Scripts/EgoAnchor/Client/AnchorStatusReceiver.cs`：主线程按事件顺序解析 `AnchorStatusEvent`，转交 `PoseToAnchorRuntime` 更新本地 lifecycle，不修改 Transform。
- `Assets/Scripts/EgoAnchor/Client/ServerHeartbeatReceiver.cs`：主线程 latest-drain、解析 `ServerHeartbeat`，转交 `PoseToAnchorRuntime` 更新链路健康诊断。
- `Assets/Scripts/EgoAnchor/Client/AnchorCommandClient.cs`：Unity command API，发送 reset/reacquire/control request 并解析 `CommandAck`。
- `Assets/Scripts/EgoAnchor/Runtime/AnchorRuntimeHub.cs`：将同一条 PoseResult/status/heartbeat 广播给多个 `PoseToAnchorRuntime`，用于多 pipeline label 公平对照；同时记录最近一条 PoseResult 的 `header.session_id`（`LatestPythonSessionId`），供 `EvalSessionController` 跨机器命名 eval 目录。
- `Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`：pose-to-anchor 组合点；默认用 capture-time frame alignment 生成 aligned raw world pose，再提交给 `policyHost`（新 `AnchorPolicyHost`）。每帧 `LateUpdate` 调 `AdvanceAnchorOutput` 输出预测位姿（`[DefaultExecutionOrder(-50)]` 保证先于 DynamicObjectAnchor/recorder）。该文件还生成 `arrival_time_raw` 诊断，只用于 RQ1 对照，不改变默认 anchor 输出。
- `Assets/Scripts/EgoAnchor/Policy/`：anchor policy 实现。主线是 `AnchorPolicyHost` + 两个可自由组合的模块基类：`Policy/Models/MotionModel`（CV/Kalman/OneEuro）和 `Policy/Smoothing/SmoothingStrategy`（Blend/DelayedInterp/RawPassthrough）。数据契约 DTO 在 `Policy/Contracts`，生命周期状态机/枚举在 `Policy/Lifecycle`，纯数学在 `Policy/Math`。运动模型的 `PredictAt(renderTime)` 同时处理平移和旋转，且**不限幅外推**（平滑交给策略）。`AnchorMotionState` 在 `Policy/Lifecycle/AnchorPolicyTypes.cs`。旧 Gate/Estimator/Output 三模块目录、旧 controller/filter/gate/smoother/config/processor 目录已删除。参数说明与场景挂载见 `Policy/README.md`。
- `Assets/Scripts/EgoAnchor/Runtime/DynamicObjectAnchor.cs`：只读取 runtime 每帧 anchor 输出 pose（`TryGetOutputPose`）并应用 Transform，不承载滤波、状态机、网络、recovery，也不再提供 Raw/Smoothed 输出模式。
- `Assets/Scripts/EgoAnchor/Runtime/AnchorRuntimeHub.cs`：pose/status/heartbeat fan-out 给多 runtime；同时 fan-in 收集各 runtime 的 `ConsumeServerReacquireRequest()`，用其持有的唯一 `reacquireCommandClient` 发一次 server reacquire（冷却+in-flight）。低分/track-loss 自动 reacquire 的命令出口（leaf 不持 client）。
- `Assets/Scripts/EgoAnchor/Client/ServerEndpointConfig.cs`：单点服务器端点配置，一个 `List<ServerPreset>` 下拉（RTX3090/RTX5090），Awake 顺链路下发 IP 给 publisher/nats client，无 PlayerPrefs 持久化。
- `Assets/Scripts/EgoAnchorEval/RecordedAnchorReplaySource.cs`、`RecordedAnchorReplayController.cs`、`AnchorTrajectoryPlayer.cs`：Unity 内 replay 组件。前两者用 `aligned_raw` 注入 runtime 做定性验证；`AnchorTrajectoryPlayer` 播放已录的 anchor 输出轨迹（`output_pos`/`output_rot`），用于视频复现。
- `Assets/Scene/`：当前主线测试场景工作区。

Unity 命名/目录规则：

- `Quest/` 放 Quest 数据提供者/source。
- `Alignment/` 放 frame pose history、camera reference 与 frame-aligned world pose 转换。
- `Transport/` 放纯网络 socket/bytes client，不理解 Quest 或 anchor 语义。
- `Client/` 放把 source、transport、runtime 组合成场景组件的客户端脚本。
- `Runtime/` 放 pose hub、PoseToAnchorRuntime、Transform 输出和 server notification 映射。
- `Policy/` 放 anchor policy 实现、observation/decision DTO、state machine 和两类可组合模块。数据契约 DTO 放 `Policy/Contracts`，生命周期状态机/枚举放 `Policy/Lifecycle`，纯数学放 `Policy/Math`，运动模型放 `Policy/Models`（继承 `MotionModel`），平滑策略放 `Policy/Smoothing`（继承 `SmoothingStrategy`）；不要再建 `Pipeline`、`Pipeline/Modules`、旧 `Gate`/`Estimator`/`Output`/`processor` 目录，也不要再用已删除的 `Policy/Core` 杂物目录。
- 新增脚本应写清中文 `<summary>` 和 Inspector 参数 `[Tooltip]`，尤其是端口、帧率、HWM、缓存容量、坐标/时间语义。

## 标定、深度与坐标约定

- Python FoundationPose 输出 OpenCV camera 坐标：x 右、y 下、z 前。
- Unity camera-local 坐标约定：x 右、y 上、z 前；Unity 由 `CameraPoseFrameAligner` / `AnchorPoseTransform` 转换。
- Python 感知 pipeline 当前使用左目图像、左目 K、左目 mask/depth，因此 `PoseResult.pose_matrix_cv_camera` 语义仍是左目 OpenCV camera pose。
- Unity 必须使用“采集该 `frame_id` 时”的参考 camera world pose，而不是 pose 到达时的 HMD pose。
- `FramePoseHistory` 同时缓存 left/right/center pose；Left 是默认语义，Right/Center/None 只用于本地诊断、对照或小量补偿实验。
- `pipeline.calibration.assume_center_crop=true` 表示 K 映射使用中心裁剪 + 缩放；`false` 为线性缩放。若边缘 pose/depth 偏差明显，优先对比该开关。

## 调试与排查

- Python OpenCV 热键：`1/2/3/4` 切 stage；`r` reset；`q`/`ESC` 退出。
- 调试顺序：stage 1 看输入 -> stage 2 看 mask -> stage 3 看 depth/mask 对齐 -> stage 4 看 register/track。
- 关键 HUD/日志：`stage`、`phase`、`mask_src`、`pose_source`、`det_count`、`depth_valid_ratio`、`depth_in_mask`、HUD `depthScore`、HUD `depthAlign`、`score_phase/score_reprojection/score_depth/score_mask/score_reject/score_confidence`、`median/iqr`、`track_reject`、`reliability_score`、`reliability_flags`、`color_reprojection`、`render_quality_area_ratio_score`、`render_quality_mask_iou`、`render_quality_depth_inlier`、`render_quality_depth_alignment`、`render_quality_render_visible_ratio`、`render_quality_observed_visible_ratio`、`render_quality_depth_residual_m`、`render_quality_ms`、`yolo/depth/cutie/pose/total_ms`、`seg_async done/submitted/drop`、`sender_est`。`score_reprojection` 和 `color_reprojection` 当前语义是交集区域颜色重投影分（`color_reprojection` 旧名 `track_reprojection`），`score_depth` 是 pose 评分里的 depth 子分，`score_mask` 当前优先来自 Cutie mask 面积 / 渲染投影面积。`sender_raw` 是跨进程/设备单调时钟差，不可直接当真实延迟。
- stereo 收不到但 camera_info 能收到：查 Unity stereo source、左右 camera `IsPlaying`、ZMQ publisher、Python 接收 HWM。
- camera_info 收不到：查 topic、`CameraInfoSource` 引用、Python 订阅。
- Unity 物体位姿错：查 OpenCV->Unity 坐标转换、frame pose cache 命中、`frame_id` 透传、K 映射策略、`AnchorPoseTransform` 轴翻转和 offset。
- Unity `PoseResultReceiver` decoded 增加但 aligned 为 0：查 `AnchorRuntimeHub` runtime 列表、`PoseToAnchorRuntime.framePoseHistory` 是否与 `StereoFrameSource` 共用、`alignmentReference` 是否正确、Python 是否原样透传 frame_id。
- runtime 收到 pose 但物体不动：先查 `PoseToAnchorRuntime.policyHost`、`AnchorPolicyHost` 的 `motionModel` 和 `smoothingStrategy` 两个 module 是否显式绑定；再看 `latestPolicyAction/Reason`、`currentMotionState`、`LatestAlignedFrameId`。`DynamicObjectAnchor` 已无 Raw/Smoothed 输出模式，真 raw 用 `ConstantVelocityModel + RawPassthroughStrategy` 组合。
- 锚点抖动/卡顿排查：先看真机采集-渲染延迟（`render_mono_ms - source_capture_mono_ms` 中位 ~300ms）。C 路 interp 锯齿跳变=延迟设成观测周期而非实测延迟（已修为自适应）；B 路 blend 急停冲过头=外推上限太大（已改自适应）。离线复现要用 `EgoAnchor_Tools3` 带 `--latency-ms`（默认自动从录制实测），否则零延迟会"离线平滑、真机抖"。
- mask 不稳：调 `module.segmenter.prompt`、`module.segmenter.confidence_threshold`、`module.segmenter.mask_threshold`、`module.segmenter.max_det`，并用 `debug.show_mask_snapshot=true`、`pixi run tool-yoloe26-mask` 或 `pixi run tool-sam3-mask` 看真实下游 mask；若 YOLOE 语义误检仍高，可显式切 `module.segmenter.type="sam3"`。
- `depth_in_mask` 低：优先查 K 映射、左右图同步/基线、FFS 权重或 TRT engine。
- register 失败：先确认 mask/depth 对齐，再查 mesh 路径、尺度、对称设置、refine iter。
- track 丢失：依赖 `module.foundationpose.re_register_on_track_lost=true`；若 2D 辅助引入抖动，可设 `module.cutie.adjust_pose=false`。
- `color_reprojection=-1`：表示本帧无有效重投影信号，不是坏 pose；查是否启用 `reliability.render_quality.enabled`、是否在 TRACK 且 Cutie mask 非空、渲染面积是否过小、warmup 是否结束、K 是否已更新。
- `reprojection_low` 误报多：先保持 `mode="score_only"`，检查 mesh 尺度、K 映射、渲染 mask 与观测 mask 方向是否一致，再看 LAB 颜色是否因纹理/光照差异过大；`depth_alignment_low` 则看 `depthAlign/depthRes` 判断是否是深度不对；遮挡或可见面积过小优先看 `render_quality_area_ratio_score`/`score_mask`，`renderCov/obsCov` 只作为投影与观测 mask 相对位置诊断；最后才考虑调 `downscale`、`depth_distance_ratio` 或阈值。
- NATS 命令无 ack：查 `nats-server` 是否启动、Unity/Python NATS URL 是否指向同一地址、防火墙 4222、Python `network.message_plane.enabled`。

## 后续实现规划

近期目标不是继续重写目录，而是把主线推进到论文级系统。建议按以下顺序推进，每阶段都保留可验证 smoke。

### Phase A：Quest 真机 smoke 与日志回放

- Quest 真机 + Python real pipeline + Unity raw/stable anchor 连续运行。
- 记录每帧：frame_id、capture/send/receive/publish/apply 时间、phase、score、flags、raw pose、stable pose、anchor state、align result。
- 导出 CSV/JSONL，按 session 分目录保存，不写进高频日志。
- 做 fake replay 或 recorded session 入口，用同一输入离线比较多种 anchor policy。

### Phase B：Unity modular anchor policy

- 模块化 policy 已进入主线并重构为两模块自由组合（3×2）：`AnchorPolicyHost` 持有 `MotionModel`（CV/Kalman/OneEuro）+ `SmoothingStrategy`（Blend/DelayedInterp/RawPassthrough），所有组合共享同一 aligned raw pose 输入、capture/render 时间轴和 `Advance(now)` 输出契约。
- 方法矩阵：B 路（外推+误差融合，零延迟）= `{cv,kalman,oneeuro}+blend`；C 路（延迟一周期+插值）= `{cv原始点,kalman,oneeuro}+interp`；真 raw 对照 = `cv+RawPassthrough`。baseline 不读 score，EgoAnchor 方法才在 host 内联开 score 门控。
- **EgoAnchor 主方法 = score-gated 分区静止锚定稳定器**（不是又一个滤波器，是 baseline 之上的锚定控制层）。已从 host 剥离为独立 `EgoAnchorStaticLockModule`（MonoBehaviour，`Policy/EgoAnchorStaticLockModule.cs`，内含纯 C# `StaticLockController`），与 model×strategy 矩阵**正交**：挂模块并 enabled = 在任意组合上加静止锁定；留空/不启用 = 纯 baseline。机制：死区吸收抖动 + score 加权 CUSUM 解锁 + 速度逃逸（堵慢运动 false-lock）+ 漏锁 creep + 反 chatter 禁锁窗 + 解锁接缝残差融合 + **绝对漂移租绳**（`unlockDriftMeters/Degrees`，修 creep 掩盖极慢平移导致永不解锁）+ **头动感知**（用采集时刻 head pose 差分头速，头动时按比例放宽 static 容忍阈值，吸收 head-motion-induced slip，头部 pose 复用 `FramePoseHistory.CenterCameraPose` 不重复绑定）+ **低分释放**（持续低分强制解锁）。所有时间量纲为帧率无关（dwell/decay/escape/suppress → 秒/半衰期，CUSUM 按 dt 归一），可在 5090@12fps 标定后自动适配 3090@5fps。位置/旋转独立证据通道。`LatestStaticLocked` 经 `PoseToAnchorRuntime`→`AnchorEvalRecorder` 写入 JSONL `latest_static_locked`。主方法 = `Kalman+interp+静止锁模块`，启停模块 = baseline↔EgoAnchor（最干净消融）。离线 PoC（Tools3 `EgoAnchorStabilizerPredictor`）验证有效。angular 静止阈值必须设在旋转噪声地板之上否则永不锁（5090@12fps ~15°/s）。pose score 子分（depth/reprojection/confidence）已经 `PoseResultPolicyMapper` 透传进 `AnchorObservation`，用于区分坏 pose（几何差→该重 register）vs 真实快动（几何好→别重）。
- `EgoAnchor_Tools3` 是当前默认离线分析入口：对真机 session 重跑所有策略并出曲线 PNG，默认自动从录制实测延迟+渲染帧率以复现真机时序。旧 `EgoAnchor_Tools/anchor_replay` 因 glob 已删目录无法编译。
- Unity replay 分两类：`RecordedAnchorReplaySource` 用 `aligned_raw` 注入 runtime 做定性验证；`AnchorTrajectoryPlayer` 播放已录 stable 轨迹用于 supplementary video。
- Recovery（低分/track-loss 自动 reacquire）走上行 fan-in：host 置标志 → runtime 透传 → `AnchorRuntimeHub` 用唯一 command client 发一次 NATS reacquire（详见组件清单）。旧独立 `AnchorRecoveryController` 已删。RQ2 可关（hub 不绑 client = 只本地重置），RQ3 再单独比较 recovery 策略。
- 下一步：迁移 Unity scene 到多 runtime pipeline 绑定（每个变体一个 GameObject 挂 1 model + 1 strategy + runtime + anchor，全注册到 `AnchorRuntimeHub`），真机按 condition 录制多策略变体，再用 `EgoAnchor_Tools3` 和 `eval/run_eval.py` 出 jitter/lag/slip/recovery 证据。

### Phase C：端到端与论文实验

最低论文闭环：

1. Quest 真机 + Python real pipeline + Unity raw/stable anchor 连续运行。
2. 对比 arrival-time anchoring vs frame-aligned anchoring。
3. 对比 always update / raw、low-pass、Kalman、reliability-aware policy。
4. 覆盖静态观察、快速头动、部分遮挡、出视野后重获。
5. 至少 3 个代表性刚体物体，避免只用 cube/pink mouse 导致泛化叙事太弱。
6. 输出端到端延迟、world-space anchor error/jitter、recovery success/time、failure taxonomy。

## 论文维护与目标

IEEE VR 2027 论文定位：

> How can asynchronous 6DoF object pose tracking be transformed into stable, world-consistent, recoverable real-object anchoring in passthrough MR?

中文表述：

> 如何在外部异步感知、头显持续运动、pose 低频/延迟/间歇失效的条件下，把 6DoF object pose stream 转化为稳定、世界一致、可恢复、可交互的真实物体 MR anchor？

推荐标题方向：

- `EgoAnchor: Frame-Aligned 6DoF Object Pose Tracking for World-Consistent Object Anchoring in Passthrough Mixed Reality`
- 如果 reliability-aware controller 完成并有实验证据，再使用 `... and Reliability-Aware Anchor Control ...` 或 `... Adaptive Anchor Control ...`。

贡献写法必须保守、可由代码和实验支撑：

1. 一个面向 passthrough MR 的 pose-to-anchor 问题表述与 frame-aligned anchoring 方法。
2. 一个开放、端到端的 EgoAnchor 系统，从头戴双目透视采集到外部对象级感知，再到 Unity world anchor。
3. 一套面向 MR real-object anchoring 的评估协议，重点评估 world-space anchor error、jitter/slip、latency、recovery，而不是只报相机坐标 pose accuracy。

若 reliability-aware controller 完成并验证，可作为第 2 或第 3 条贡献的一部分；未完成前只能写为 planned/future work 或 current baseline limitation。

论文源文件：

- 当前主要中文大纲：`2026-EgoAnchor/egoanchor_cn_outline.tex`。
- 另一个较完整草稿：`2026-EgoAnchor/egoanchor_cn_v1.tex`。
- 参考文献：`2026-EgoAnchor/egoanchor_cn_refs.bib`。
- `2026-EgoAnchor/pdf/` 是生成产物，不当作源文件维护。

写作注意：

- 不要写成“VR pose tracking 工程堆模块”。核心是 pose-to-anchor 和 world-consistent anchoring。
- 不要夸大“first”除非限定清楚：open、end-to-end、head-worn stereo input、external asynchronous 6DoF pose stream、Unity deployment、world-consistent real-object anchoring。
- 可强调机制：`frame_id` 对齐、capture-time camera pose 回查、per-topic latest-drain、Quest K remapping、可切换 YOLOE-26/SAM3 mask backend + FFS + FoundationPose/Cutie re-register、NATS command ack/enqueue、状态/时延/mask-depth 诊断。
- 实验主指标优先用 anchor 指标：world-space anchor error、head-motion-induced slip、world-space jitter/drift、recovery success/time、P50/P90 latency。ADD/ADD-S、translation/rotation pose error 只能作为支持性底层感知指标。
- 如果做用户/任务实验，需提前确认伦理/IRB 要求。

## 环境

- Python 环境由 `EgoAnchor_Python/pixi.toml` 管理：Python 3.12、CUDA 12.8、PyTorch 2.7 cu128、TensorRT cu12、pyrealsense2、ultralytics/YOLOE、onnx、pillow、protobuf、nats-py、Cutie editable path；SAM3 代码当前作为项目内 `EgoAnchor_Python/sam3` 仓库使用，默认从本地 checkpoint 加载。
- Windows 重建 `.pixi/envs/default` 失败时，先关闭 VS Code Python LSP、Black Formatter、残留 Python 进程，避免文件占用。
- FoundationPose C++ 扩展由 `pixi run build` 中 `_build-fp` 构建；FFS ONNX/TRT artifact 也由 build task 生成。
- Unity 依赖由 `EgoAnchor_Unity/Packages/manifest.json` 管理；主线依赖 Google.Protobuf、NATS.Net、NetMQ 等。
- Pixi activation 与 VSCode `python.analysis.extraPaths` 负责暴露 `EgoAnchor_Python`、`src`、`Fast-FoundationStereo`、`Cutie`、`sam3` 等本地算法包根；`src/egoanchor/algorithms` 适配器不得再手动修改 `sys.path`。第三方库 console 输出由 `egoanchor.utils` 包级入口下的第三方日志工具统一接管，适配器只从 `module.foundationpose/cutie/ffs/sam3.enable_logging` 传入开关，默认关闭。

## 关键历史约束：不要回退

- 不恢复旧 v1/v2 目录、MessagePack 链路、旧计划目录或早期 NATS 实验目录。
- 不恢复旧默认端口 `5556/5557`；保持 Unity -> Python `15557`。
- 不恢复 ZMQ PUSH/PULL、业务分片、JSON pose、单图 `packed_image_jpeg_legacy`。
- 不恢复旧入口/文件：`src/pose_tracker_api.py`、`src/vpt_cli.py`、`src/VOT.py`、`src/quest_stereo_pose_pipeline.py`、`src/modules/quest_stereo.py`、`src/modules/quest_receiver.py`、`src/zmq_utils/timing.py`、`src/zmq_utils/latency.py`、Unity 旧 `StaticStereoEncoder.cs`。
- 不恢复 Python `PayloadSender` default topic、TRT legacy alias/fallback 文件名、运行时 `onnx.yaml` 依赖。
- 不添加 Unity legacy port 自动迁移逻辑。
- 不把 SAM3 设为默认分割后端；默认主线保持 YOLOE-26。SAM3 异步分割可以作为显式配置路径，但 FoundationPose/Cutie 状态仍必须由单一 `TrackingRuntime` 顺序拥有，不能放进分割 worker。
- 不恢复 WebRTC 图像传输方案、NATS 图像流 smoke server。
- 高频路径日志保持精简；详细收发/编码统计只通过显式 debug 开关启用。
- Unity 事件链优先显式 Inspector 绑定，避免组件内部自动 Find/AddListener 造成重复订阅或隐藏依赖。
- NATS handler 只能 parse/validate/dedup/enqueue/ack；pipeline/GPU 状态必须由单一 `TrackingRuntime` 顺序拥有。
- Python 不输出 Unity world pose；Unity 用 capture-time frame pose 做 world anchor。
- 不使用 pose 到达时 HMD pose 代替发送帧 pose。这个是项目核心历史坑。

## AGENTS.md 维护规则

- 本文件保持“当前事实 + 核心约定 + 后续路线 + 历史坑”，不要追加日期日志。
- 不要修改 `USER-MAINTAINED-REQUIREMENTS` 区块。除非用户明确要求修改该区块，否则后续 AI 不得因润色、去重、同步文档或整理结构而改动其中任何文字。
- 大改后同步入口、模块职责、协议字段、标定策略、坐标、调试统计、论文定位、实验目标和排查结论。
- 若事实被代码或协议更新推翻，直接改旧条目，不要在后面追加相互矛盾的新条目。
