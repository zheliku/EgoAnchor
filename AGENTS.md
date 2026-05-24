# AGENTS.md

本文件是 EgoAnchor 的项目级 AI 接手指南。后续 Agent 进入本仓库时优先阅读并维护本文件；不要再新增分散 handoff 文档。这里只记录长期有效的事实、约定、路线和历史坑，避免流水账、临时调参和已废弃方案。

## 当前状态一句话

EgoAnchor 是面向 passthrough mixed reality 的 **frame-aligned、world-consistent real-object anchoring** 系统。当前仓库已清理为单主线结构：Python 主线位于 `EgoAnchor_Python/src`，Unity 主线位于 `EgoAnchor_Unity/Assets/Scripts/EgoAnchor`，采用 **ZMQ Protobuf 数据面 + NATS Protobuf 消息/命令面 + Unity frame-aligned anchor runtime**。旧 v1/v2、旧计划和早期 NATS 实验目录已移除。

论文目标是 IEEE VR 2027，核心主张必须围绕 **把异步 6DoF object pose stream 转化为稳定、世界一致、可恢复的 MR real-object anchor**，而不是包装成普通 pose tracking 工程。

## 仓库组成

- `EgoAnchor_Python/`：Python 端位姿估计服务和当前主线实现。
- `EgoAnchor_Unity/`：Unity/Quest 工程；采集 Passthrough Camera，发送图像/标定，接收 pose 并转换为 Unity world anchor。
- `EgoAnchor_Protocol/`：共享协议源，包含 `subjects.v1.json`、`proto/protocol/v1/*.proto`、`tools/generate_proto.ps1`。
- `2026-EgoAnchor/`：论文材料；当前源文件包括 `egoanchor_cn_outline.tex`、`egoanchor_cn_v1.tex` 与 `egoanchor_cn_refs.bib`。
- `EgoAnchor_Tools/`：与主系统分离的辅助工具脚本。

## 项目级实现要求

- Python 业务代码优先从包级入口导入，例如 `from egoanchor.algorithms import ...`、`from egoanchor.perception import ...`、`from egoanchor.runtime import ...`、`from egoanchor.protocol import ...`。不要在业务代码里深层导入具体文件。生成的 `*_pb2.py` 内部 import 例外。
- 代码需要详细中文说明。配置 `.toml` 的每个参数都要有同一行末尾中文注释；类、成员变量和每个方法应有中文 docstring 或 XML summary / Tooltip。
- 命名不要过度冗长，能清楚表达职责即可。类名优先写具体职责，不把 `DataPlane`、`ControlPlane` 之类架构词塞进每个文件名。
- 修改代码要按全局架构考虑模块配合、导入关系和协议契约；不要只在局部补补丁。
- 新增行为应先补测试或 smoke 验证。配置、文档、生成代码除外，但仍要有可复现验证命令。
- 不要把尚未实现或尚未实验验证的论文机制写成已完成贡献。

## 当前主线架构

EgoAnchor 固定采用双平面/三语义通道：

| 平面 | 传输 | 方向 | 数据 | 策略 |
|---|---|---|---|---|
| Data Plane | ZMQ PUB/SUB | Unity -> Python | `QuestStereoFrame`、`QuestCameraInfo` | Protobuf bytes，multipart `[topic_utf8, payload]`，topic latest-drain |
| Message Plane | NATS Core pub/sub | Python -> Unity | `PoseResult`；后续 `AnchorStatusEvent`、`ServerHeartbeat` | 小 payload，pose latest-only，status event stream |
| Command Plane | NATS request/reply | Unity -> Python | `ResetTrackingRequest`、`ReacquireAnchorRequest`、`AnchorControlRequest` | `request_id` 幂等，快速 ack，runtime 串行执行 |

当前主线能力：

- Python `src/quest_video_stream_demo.py`：ZMQ/Protobuf 双目通信预览，不加载模型。
- Python `src/yoloe_mask_probe.py`：同一 ZMQ 数据面，只运行 YOLOE-26，实时看 overlay/mask，快速调 prompt/conf/mask threshold。
- Python `src/tracking_server.py`：接收 ZMQ Quest stereo/camera_info，运行 YOLOE-26 + FFS + FoundationPose/Cutie，显示 OpenCV debug，并可通过 NATS 发布 `PoseResult`。
- Python command path：`NatsMessageClient -> NatsRouter -> HandlerRegistry -> CommandDedupStore -> CommandQueue -> TrackingRuntime` 具备 reset/reacquire/control ack/enqueue/execution 骨架。
- Unity `QuestStreamPublisher`：发送 stereo/camera_info Protobuf；支持 PlayerPrefs 注入 Python IP。
- Unity `FramePoseHistory`：记录 `frame_id -> capture-time left/right/center camera world pose`。
- Unity `NatsControlClient`：订阅 PoseResult latest queue，并提供 bytes request/reply。
- Unity `PoseResultReceiver -> PoseResultHub -> PoseToAnchorRuntime`：主线程解码 PoseResult，广播给多个 runtime，支持 raw baseline 与 smoothed runtime 使用同一 pose 输入。
- Unity `CameraPoseFrameAligner`：将 Python OpenCV camera-space pose 按 `frame_id` 回查到 Unity world pose。
- Unity `AnchorLowPassPoseProcessor`、`AnchorKalmanPoseProcessor`：当前 stable baseline。
- Unity `AnchorCommandClient`：公开 reset/reacquire/pause/resume/set stage API；`CommandAck.accepted=true` 只表示 Python 接受命令，不表示重定位完成。

## 常用入口与验证

在 `EgoAnchor_Python` 目录运行：

```powershell
# 当前主线
pixi run python .\src\quest_video_stream_demo.py
pixi run python .\src\yoloe_mask_probe.py
pixi run python .\src\tracking_server.py

# Python 验证
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py"
```

在仓库根目录运行 Unity 编译验证：

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

协议生成在 `EgoAnchor_Python` 目录运行，确保使用 pixi 环境中的 `protoc`：

```powershell
pixi run pwsh -File ..\EgoAnchor_Protocol\tools\generate_proto.ps1
```

`pixi run build` 会构建 FoundationPose C++ 扩展并生成 FFS ONNX/TRT artifacts，耗时且依赖 CUDA/TensorRT 环境；不要把它当轻量验证命令。

论文目录基于 VGTC 模板，但 `2026-EgoAnchor/makefile` 默认仍指向 `template.tex` / `template.bib`。构建 EgoAnchor 论文时必须显式指定主文件和 bib，或先更新 makefile，避免误编译模板。

## 配置与协议契约

### Python 配置

- 默认配置：`EgoAnchor_Python/src/egoanchor/config/defaults.toml`。
- 覆盖配置示例：`EgoAnchor_Python/src/egoanchor/config/mouse.toml`。
- 加载器：`EgoAnchor_Python/src/egoanchor/config/runtime_config.py`。
- 每个 `.toml` 参数必须在同一行末尾写中文注释；新增参数时同步默认值、加载点、使用点和测试。
- 主要分组：`server`、`network.data_plane`、`network.message_plane`、`runtime.commands`、`pipeline.calibration/depth`、`module.segmenter/yoloe/ffs/foundationpose/cutie`、`debug`、`demo.video`、`demo.pose`。
- `network.message_plane.enabled=false` 可用于 Python-only debug，避免没有 NATS server 时阻塞模型调试。

### 共享协议

- 唯一 channel 契约：`EgoAnchor_Protocol/subjects.v1.json`。
- Proto 源：`EgoAnchor_Protocol/proto/protocol/v1/common.proto`、`quest.proto`、`anchor.proto`。
- 默认生成输出：
  - Python：`EgoAnchor_Python/src/egoanchor/protocol/v1/*_pb2.py`
  - Unity：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/Generated/*.cs`
  - Unity subject 常量：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/SubjectNames.cs`
- 字段号进入共享 proto 后不得重排。删除字段必须在 proto 中 `reserved` 字段号和字段名。
- 业务代码不手写 subject 字符串；Python 从 `egoanchor.protocol` 包级入口导入常量，Unity 从 `SubjectNames` 使用常量。

主线逻辑 channels：

| Channel | 方向 | 传输 | Protobuf | 说明 |
|---|---|---|---|---|
| `egoanchor.v1.quest.stereo` | Unity -> Python | ZMQ | `QuestStereoFrame` | 高频双目 JPEG，latest-only |
| `egoanchor.v1.quest.camera_info` | Unity -> Python | ZMQ | `QuestCameraInfo` | 低频标定，独立 latest cache |
| `egoanchor.v1.pose.result` | Python -> Unity | NATS | `PoseResult` | 小型 pose 结果，latest-only |
| `egoanchor.v1.anchor.status` | Python -> Unity | NATS | `AnchorStatusEvent` | 状态事件流，协议已存在，当前待接入 |
| `egoanchor.v1.server.heartbeat` | Python -> Unity | NATS | `ServerHeartbeat` | 健康状态，协议已存在，当前待接入 |
| `egoanchor.v1.cmd.anchor.reset` | Unity -> Python | NATS request/reply | `ResetTrackingRequest -> CommandAck` | ack 只表示接受/拒绝 |
| `egoanchor.v1.cmd.anchor.reacquire` | Unity -> Python | NATS request/reply | `ReacquireAnchorRequest -> CommandAck` | 重定位结果靠后续事件/pose |
| `egoanchor.v1.cmd.anchor.control` | Unity -> Python | NATS request/reply | `AnchorControlRequest -> CommandAck` | stage/pause/resume 等控制 |

## 代码地图

### Python

- `src/tracking_server.py`：当前主入口 wrapper，调用 `egoanchor.app.tracking_server`。
- `src/quest_video_stream_demo.py`：ZMQ/Protobuf 双目实时预览 demo。
- `src/yoloe_mask_probe.py`：YOLOE mask 调参入口。
- `src/egoanchor/config/`：轻量配置。配置层只读 TOML，不导入 ZMQ/OpenCV/模型。
- `src/egoanchor/protocol/`：subject registry、protobuf registry、包级 Protobuf 入口。
- `src/egoanchor/transport/zmq_topic_subscriber.py`：通用 ZMQ SUB；只负责 socket、multipart topic bytes、topic latest-drain，不导入 Protobuf/OpenCV/模型。
- `src/egoanchor/transport/nats_client.py`：唯一 NATS transport 文件；负责后台 asyncio NATS 连接、bytes publish/subscribe/request-reply callback 和 publish 限流，不理解 perception 或 Unity anchor。
- `src/egoanchor/routing/`：`HandlerRegistry`、`NatsRouter`、`iter_nats_request_specs`；负责 subject -> protobuf parse -> handler -> reply serialize。
- `src/egoanchor/handlers/command_handlers.py`：reset/reacquire/control request handler；只 validate/dedup/enqueue/ack，不直接碰 pipeline/GPU。
- `src/egoanchor/runtime/latest_quest_input_store.py`：topic independent latest cache、frame_id/session 去重、camera_info version 和输入统计。
- `src/egoanchor/runtime/quest_stream_receiver.py`：ZMQ bytes -> Quest Protobuf -> latest store。
- `src/egoanchor/runtime/command_queue.py`、`command_dedup.py`、`command_executor.py`：命令队列、request_id TTL 幂等、runtime 内解释命令。
- `src/egoanchor/runtime/tracking_runtime.py`：唯一 pipeline/GPU 状态 owner；poll Quest stream latest、运行 perception pipeline、发布 PoseResult、顺序消费 commands。
- `src/egoanchor/runtime/pose_result_factory.py`：`PoseObservation -> PoseResult` 映射。
- `src/egoanchor/perception/quest_pose_pipeline.py`：Quest pose pipeline；组合 YOLOE-26、FFS、FoundationPose/Cutie，输出 camera-space `PoseObservation` 与 debug 图像，不依赖 ZMQ/NATS/Unity transform。
- `src/egoanchor/perception/quest_calibration.py`：Quest camera_info 到算法处理分辨率 K 的映射，支持 center-crop 与线性缩放。
- `src/egoanchor/algorithms/`：单模型适配层。
- `src/egoanchor/reliability/pose_quality.py`：轻量感知可靠性评分，目前主要用于 HUD 和内部诊断。
- `src/egoanchor/diagnostics/`：OpenCV HUD、depth/mask/pose dashboard、窗口工具。
- `src/egoanchor/tests/test_command_flow.py`：当前 command request/reply、dedup、executor 轻量测试。

### Unity

- `Assets/Scripts/EgoAnchor/Protocol/Generated/`：C# Protobuf 生成代码。
- `Assets/Scripts/EgoAnchor/Protocol/SubjectNames.cs`：由协议脚本生成的 subject 常量，不要手改。
- `Assets/Scripts/EgoAnchor/Transport/ZmqTopicPublisher.cs`：只管理 NetMQ PUB socket，发送 `[topic_utf8, protobuf_payload_bytes]`。
- `Assets/Scripts/EgoAnchor/Transport/NatsControlClient.cs`：NATS 消息面客户端；订阅 PoseResult latest queue，提供 bytes request/reply；后台回调不改 Transform。
- `Assets/Scripts/EgoAnchor/Quest/StereoFrameSource.cs`：读取左右 Passthrough texture、记录 left/right/center camera pose、JPEG 编码、构造 `QuestStereoFrame`。
- `Assets/Scripts/EgoAnchor/Quest/CameraInfoSource.cs`：读取 Quest intrinsics/lens pose 并构造 `QuestCameraInfo`。
- `Assets/Scripts/EgoAnchor/Quest/FramePoseHistory.cs`：`frame_id -> capture-time left/right/center camera world pose` 环形缓存，是 frame-aligned anchor 的关键。
- `Assets/Scripts/EgoAnchor/Quest/AnchorPoseReference.cs`：Unity 本地对齐参考枚举。Python 当前语义仍是左目 OpenCV camera pose；Right/Center/None 只用于本地诊断、对照或小量补偿实验。
- `Assets/Scripts/EgoAnchor/Client/QuestStreamPublisher.cs`：场景级 ZMQ 数据面发送组件；支持 PlayerPrefs 配置 Python IP。
- `Assets/Scripts/EgoAnchor/Client/PoseResultReceiver.cs`：主线程 latest-drain、解析 PoseResult、交给 `PoseResultHub`。
- `Assets/Scripts/EgoAnchor/Client/AnchorCommandClient.cs`：Unity command API，发送 reset/reacquire/control request 并解析 `CommandAck`。
- `Assets/Scripts/EgoAnchor/Anchor/PoseResultHub.cs`：将同一条 PoseResult 广播给多个 `PoseToAnchorRuntime`，用于 raw vs smoothed 对照。
- `Assets/Scripts/EgoAnchor/Anchor/CameraPoseFrameAligner.cs`：OpenCV camera pose + frame history -> Unity world pose；包含 `AnchorPoseTransform` 轴翻转和固定 offset 配置。
- `Assets/Scripts/EgoAnchor/Anchor/PoseToAnchorRuntime.cs`：pose-to-anchor 组合点；保留 raw pose，并按 processor chain 生成 stable pose。
- `Assets/Scripts/EgoAnchor/Anchor/AnchorPoseProcessor.cs`、`AnchorKalmanPoseProcessor.cs`、`AnchorLowPassPoseProcessor.cs`：可插拔处理器与当前 baseline。
- `Assets/Scripts/EgoAnchor/Anchor/DynamicObjectAnchor.cs`：只读取 runtime raw/stable pose 并应用 Transform，不承载滤波、状态机或网络逻辑。
- `Assets/Scene/`：当前主线测试场景工作区。

Unity 命名/目录规则：

- `Quest/` 放 Quest 数据提供者/source 和采集期缓存。
- `Transport/` 放网络 socket/client，不理解 Quest 或 anchor 语义。
- `Client/` 放把 source、transport、runtime 组合成场景组件的客户端脚本。
- `Anchor/` 放 frame alignment、processor chain、pose hub、Transform 输出和未来 anchor policy/state。
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
- 关键 HUD/日志：`stage`、`phase`、`mask_src`、`pose_source`、`det_count`、`depth_valid_ratio`、`depth_in_mask`、`median/iqr`、`track_reject`、`reliability_score`、`sender_est`。`sender_raw` 是跨进程/设备单调时钟差，不可直接当真实延迟。
- stereo 收不到但 camera_info 能收到：查 Unity stereo source、左右 camera `IsPlaying`、ZMQ publisher、Python 接收 HWM。
- camera_info 收不到：查 topic、`CameraInfoSource` 引用、Python 订阅。
- Unity 物体位姿错：查 OpenCV->Unity 坐标转换、frame pose cache 命中、`frame_id` 透传、K 映射策略、`AnchorPoseTransform` 轴翻转和 offset。
- Unity `PoseResultReceiver` decoded 增加但 aligned 为 0：查 `PoseResultHub` runtime 列表、`PoseToAnchorRuntime.framePoseHistory` 是否与 `StereoFrameSource` 共用、`alignmentReference` 是否正确、Python 是否原样透传 frame_id。
- raw 物体正常但 smoothed 不动：查 `PoseToAnchorRuntime.processors`、processor 是否启用、`DynamicObjectAnchor.outputMode` 是否为 `Smoothed`。
- YOLOE mask 不稳：调 prompt、conf、mask threshold、max_det，并用 `debug.show_mask_snapshot=true` 或 `yoloe_mask_probe.py` 看真实下游 mask。
- `depth_in_mask` 低：优先查 K 映射、左右图同步/基线、FFS 权重或 TRT engine。
- register 失败：先确认 mask/depth 对齐，再查 mesh 路径、尺度、对称设置、refine iter。
- track 丢失：依赖 `module.foundationpose.re_register_on_track_lost=true`；若 2D 辅助引入抖动，可设 `module.cutie.adjust_pose=false`。
- NATS 命令无 ack：查 `nats-server` 是否启动、Unity/Python NATS URL 是否指向同一地址、防火墙 4222、Python `network.message_plane.enabled`。

## 后续实现规划

近期目标不是继续重写目录，而是把主线推进到论文级系统。建议按以下顺序推进，每阶段都保留可验证 smoke。

### Phase A：Quest 真机 smoke 与日志回放

- Quest 真机 + Python real pipeline + Unity raw/stable anchor 连续运行。
- 记录每帧：frame_id、capture/send/receive/publish/apply 时间、phase、score、flags、raw pose、stable pose、anchor state、align result。
- 导出 CSV/JSONL，按 session 分目录保存，不写进高频日志。
- 做 fake replay 或 recorded session 入口，用同一输入离线比较多种 anchor policy。

### Phase B：Unity reliability-aware anchor controller

- 输入：`PoseResult` 可靠性字段、frame history 命中、pose innovation、回包年龄、连续 no-pose 时间、heartbeat 状态。
- 输出：`Accept`、`Smooth`、`Hold`、`Coast`、`Reject`、`Lost`、`Relocalizing` 等 anchor 行为。
- 保留 raw、low-pass、Kalman baseline，full method 单独作为 reliability-aware runtime 或 processor/policy 链。
- 不要把 controller 写进 `NatsControlClient`、`PoseResultReceiver` 或 `DynamicObjectAnchor`；它应在 anchor runtime/policy 层。

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
- 可强调机制：`frame_id` 对齐、capture-time camera pose 回查、per-topic latest-drain、Quest K remapping、YOLOE-26 + FFS + FoundationPose/Cutie re-register、NATS command ack/enqueue、状态/时延/mask-depth 诊断。
- 实验主指标优先用 anchor 指标：world-space anchor error、head-motion-induced slip、world-space jitter/drift、recovery success/time、P50/P90 latency。ADD/ADD-S、translation/rotation pose error 只能作为支持性底层感知指标。
- 如果做用户/任务实验，需提前确认伦理/IRB 要求。

## 环境

- Python 环境由 `EgoAnchor_Python/pixi.toml` 管理：Python 3.12、CUDA 12.8、PyTorch 2.7 cu128、TensorRT cu12、pyrealsense2、ultralytics/YOLOE、onnx、pillow、protobuf、nats-py、Cutie editable path。
- Windows 重建 `.pixi/envs/default` 失败时，先关闭 VS Code Python LSP、Black Formatter、残留 Python 进程，避免文件占用。
- FoundationPose C++ 扩展由 `pixi run build` 中 `_build-fp` 构建；FFS ONNX/TRT artifact 也由 build task 生成。
- Unity 依赖由 `EgoAnchor_Unity/Packages/manifest.json` 管理；主线依赖 Google.Protobuf、NATS.Net、NetMQ 等。

## 关键历史约束：不要回退

- 不恢复旧 v1/v2 目录、MessagePack 链路、旧计划目录或早期 NATS 实验目录。
- 不恢复旧默认端口 `5556/5557`；保持 Unity -> Python `15557`。
- 不恢复 ZMQ PUSH/PULL、业务分片、JSON pose、单图 `packed_image_jpeg_legacy`。
- 不恢复旧入口/文件：`src/pose_tracker_api.py`、`src/vpt_cli.py`、`src/VOT.py`、`src/quest_stereo_pose_pipeline.py`、`src/modules/quest_stereo.py`、`src/modules/quest_receiver.py`、`src/zmq_utils/timing.py`、`src/zmq_utils/latency.py`、Unity 旧 `StaticStereoEncoder.cs`。
- 不恢复 Python `PayloadSender` default topic、TRT legacy alias/fallback 文件名、运行时 `onnx.yaml` 依赖。
- 不添加 Unity legacy port 自动迁移逻辑。
- 不把异步 SAM3 + Cutie 种子刷新写回默认主线。
- 不恢复 WebRTC 图像传输方案、NATS 图像流 smoke server。
- 高频路径日志保持精简；详细收发/编码统计只通过显式 debug 开关启用。
- Unity 事件链优先显式 Inspector 绑定，避免组件内部自动 Find/AddListener 造成重复订阅或隐藏依赖。
- NATS handler 只能 parse/validate/dedup/enqueue/ack；pipeline/GPU 状态必须由单一 `TrackingRuntime` 顺序拥有。
- Python 不输出 Unity world pose；Unity 用 capture-time frame pose 做 world anchor。
- 不使用 pose 到达时 HMD pose 代替发送帧 pose。这个是项目核心历史坑。

## AGENTS.md 维护规则

- 本文件保持“当前事实 + 核心约定 + 后续路线 + 历史坑”，不要追加日期日志。
- 大改后同步入口、模块职责、协议字段、标定策略、坐标、调试统计、论文定位、实验目标和排查结论。
- 若事实被代码或协议更新推翻，直接改旧条目，不要在后面追加相互矛盾的新条目。
