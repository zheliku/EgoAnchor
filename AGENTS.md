# AGENTS.md

本文件是 EgoAnchor 的项目级 AI 接手指南。后续 Agent 进入本仓库时优先阅读并维护本文件；不要再新增分散 handoff 文档。这里只记录长期有效的事实、约定、路线和历史坑，避免流水账、临时调参和已废弃方案。

## 当前状态一句话

EgoAnchor 是面向 passthrough mixed reality 的 **frame-aligned、world-consistent real-object anchoring** 系统。当前工程状态是：v1 是可回退的旧稳定链路；v2 已作为过渡参考；v3 已成为当前主线，采用 **ZMQ Protobuf 数据面 + NATS Protobuf 消息/命令面 + Unity frame-aligned anchor runtime**，已跑通 Python v3 接收/调试、YOLOE probe、真实 pose pipeline、NATS PoseResult 发布、Unity v3 PoseResult 接收、frame history 对齐、raw/stable anchor 输出和 reset/reacquire/control request-reply 骨架。论文目标是 IEEE VR 2027，核心主张必须围绕 **把异步 6DoF object pose stream 转化为稳定、世界一致、可恢复的 MR real-object anchor**，而不是包装成普通 pose tracking 工程。

## 仓库组成

- `EgoAnchor_Python/`：Python 端位姿估计服务、算法模块、v1 稳定入口、v2 参考实现和 v3 当前主线。
- `EgoAnchor_Unity/`：Unity/Quest 工程；采集 Passthrough Camera，发送图像/标定，接收 pose 并转换为 Unity world anchor。
- `EgoAnchor_Protocol/`：共享协议源，包含 `subjects.v1.json`、`proto/protocol/v1/*.proto`、`tools/generate_proto.ps1`。
- `2026-EgoAnchor/`：论文材料；当前源文件包括 `egoanchor_cn_outline.tex`、`egoanchor_cn_v1.tex` 与 `egoanchor_cn_refs.bib`。
- `plans/` 与 `1779170816026-cosmic-cactus.md`：旧规划参考。当前仓库没有 `plan/` 目录；如用户提到 `plan/`，通常指 `plans/`。
- `nats_example/`：NATS registry/router/dedup 早期实验参考；v3 已吸收其主要结构思想，不作为正式入口。

## 项目级实现要求

- Python 业务代码优先从包级入口导入，例如 `from egoanchor.algorithms import ...`、`from egoanchor.perception import ...`、`from egoanchor.runtime import ...`、`from egoanchor.protocol import ...`。不要在业务代码里深层导入具体文件。生成的 `*_pb2.py` 内部 import 例外。
- 代码需要详细中文说明。配置 `.toml` 的每个参数都要有同一行末尾中文注释；类、成员变量和每个方法应有中文 docstring 或 XML summary / Tooltip。
- 命名不要过度冗长，能清楚表达职责即可。类名优先写具体职责，不把 `DataPlane`、`ControlPlane` 之类架构词塞进每个文件名。
- 修改代码要按全局架构考虑模块配合、导入关系和协议契约；不要只在局部补补丁。
- 新增行为应先补测试或 smoke 验证。配置、文档、生成代码除外，但仍要有可复现验证命令。
- 不要把尚未实现的论文机制写成已完成贡献。特别是 reliability-aware anchor controller、完整 AnchorStateMachine、status/heartbeat 订阅和论文用户实验，目前仍是后续工作。

## 当前主线架构

### v1 稳定链路（保留为回退）

1. Unity/Quest 采集左右 Passthrough Camera 图像和低频 camera info。
2. Unity 用 ZMQ PUB 多 topic 发送 MessagePack：`quest_stereo`、`quest_camera_info`。
3. Python `EgoAnchor_Python/src/object_tracking_server.py` 接收输入，运行 Quest object tracking pipeline。
4. 默认感知组合：YOLOE-26 分割 + Fast-FoundationStereo 深度 + FoundationPose register/track/re-register；Cutie 可选辅助 mask 传播。
5. Python 通过 ZMQ PUB `pose` topic 回传 `PoseMsg`。
6. Unity 用 `frame_id` 回查发送帧左目 camera pose，把相机局部 pose 转成 Unity world anchor pose。

v1 仍是端到端保底链路。v3 修改不得破坏 v1 默认端口、配置和主场景。

### v2 过渡链路（参考，不继续堆新功能）

- v2 完成了 Protobuf、ZMQ 数据面、部分 NATS command、Python 包化、Unity v2 frame history / PoseResult receiver / anchor runtime 等探索。
- v2 不再是主要新增功能位置。后续新能力优先进入 v3；v2 只用于对照、迁移参考或避免破坏旧实验。
- 不要把旧 v2 smoke/demo 写成正式主线，也不要恢复 NATS 图像流、WebRTC 图像传输或旧 smoke server。

### v3 当前主线

v3 固定采用双平面/三语义通道：

| 平面 | 传输 | 方向 | 数据 | 策略 |
|---|---|---|---|---|
| Data Plane | ZMQ PUB/SUB | Unity -> Python | `QuestStereoFrame`、`QuestCameraInfo` | Protobuf bytes，multipart `[topic_utf8, payload]`，topic latest-drain |
| Message Plane | NATS Core pub/sub | Python -> Unity | `PoseResult`，后续 `AnchorStatusEvent`、`ServerHeartbeat` | 小 payload，pose latest-only，status event stream |
| Command Plane | NATS request/reply | Unity -> Python | `ResetTrackingRequest`、`ReacquireAnchorRequest`、`AnchorControlRequest` | `request_id` 幂等，快速 ack，runtime 串行执行 |

当前 v3 能力：

- Python v3 `src_v3/quest_video_stream_demo.py`：ZMQ/Protobuf 双目通信预览，不加载模型。
- Python v3 `src_v3/yoloe_mask_probe.py`：同一 ZMQ 数据面，只运行 YOLOE-26，实时看 overlay/mask，快速调 prompt/conf/mask threshold。
- Python v3 `src_v3/tracking_server.py`：接收 ZMQ Quest stereo/camera_info，运行 YOLOE-26 + FFS + FoundationPose/Cutie，显示 OpenCV debug，并可通过 NATS 发布 `PoseResult`。
- Python v3 command path：`NatsMessageClient -> NatsRouter -> HandlerRegistry -> CommandDedupStore -> CommandQueue -> TrackingRuntime` 已具备 reset/reacquire/control ack/enqueue/execution 骨架。
- Unity v3 `QuestStreamPublisher`：发送 stereo/camera_info Protobuf；支持 PlayerPrefs 注入 Python IP。
- Unity v3 `FramePoseHistory`：记录 `frame_id -> capture-time left/right/center camera world pose`。
- Unity v3 `NatsControlClient`：订阅 PoseResult latest queue，并提供 bytes request/reply。
- Unity v3 `PoseResultReceiver -> PoseResultHub -> PoseToAnchorRuntime`：主线程解码 PoseResult，广播给多个 runtime，支持 raw baseline 与 smoothed runtime 使用同一 pose 输入。
- Unity v3 `CameraPoseFrameAligner`：将 Python OpenCV camera-space pose 按 `frame_id` 回查到 Unity world pose。
- Unity v3 `AnchorLowPassPoseProcessor`、`AnchorKalmanPoseProcessor`：当前 stable baseline。它们不是最终 reliability-aware controller。
- Unity v3 `AnchorCommandClient`：公开 reset/reacquire/pause/resume/set stage API；`CommandAck.accepted=true` 只表示 Python 接受命令，不表示重定位完成。

当前 v3 缺口：

- `PoseResult` proto 尚未携带 `reliability_score`、`reliability_flags`、`depth_valid_in_mask`、`mask_area_ratio`、`pose_source` 等字段；这些只存在于 Python 内部 `PoseObservation` 和 HUD。
- `AnchorStatusEvent`、`ServerHeartbeat` proto 已存在，但 Python v3 尚未正式发布，Unity v3 尚未接收/显示。
- Unity v3 还没有完整 `AnchorStateMachine` 和 reliability-aware anchor controller；`has_pose=false`、frame history miss 或低置信度时目前主要保持上一帧输出并记录诊断。
- 论文中的 adaptive/reliability-aware anchor controller 还不能写成已完成贡献。
- 论文实现章节仍有旧 v1 表述（例如 ZMQ + MessagePack），写论文时必须同步为 v3 的 ZMQ Protobuf + NATS 架构。

## 常用入口与验证

在 `EgoAnchor_Python` 目录运行：

```powershell
# v1 端到端服务
pixi run python .\src\object_tracking_server.py
pixi run python .\src\object_tracking_server.py --config .\config\runtime.toml
pixi run python .\src\object_tracking_server.py --print_config

# v1 pipeline 单独调试
pixi run python .\src\pipeline\quest_object_tracking_pipeline.py
pixi run python .\src\pipeline\realsense_object_tracking_pipeline.py

# v2 参考 smoke/demo
pixi run python .\src_v2\tracking_server.py
pixi run python .\src_v2\quest_video_stream_demo.py
pixi run python .\src_v2\quest_pose_debug_demo.py
pixi run python .\src_v2\anchor_link_smoke.py
pixi run python .\src_v2\send_fake_quest_stream.py

# v3 当前主线
pixi run python .\src_v3\quest_video_stream_demo.py
pixi run python .\src_v3\yoloe_mask_probe.py
pixi run python .\src_v3\tracking_server.py

# Python 验证
pixi run python -m compileall src src_v2 src_v3
pixi run python -m unittest src.test.test_runtime_config src.test.test_protocol_contract src.test.test_sam3_masker
pixi run python -m unittest discover -s src_v2 -p "test_*.py"
pixi run python -m unittest discover -s src_v3 -p "test_*.py"
```

在仓库根目录运行 Unity 编译验证：

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

协议生成在仓库根目录运行：

```powershell
.\EgoAnchor_Protocol\tools\generate_proto.ps1
.\EgoAnchor_Protocol\tools\generate_proto.ps1 -GenerateV2
```

`pixi run build` 会构建 FoundationPose C++ 扩展并生成 FFS ONNX/TRT artifacts，耗时且依赖 CUDA/TensorRT 环境；不要把它当轻量验证命令。

论文目录基于 VGTC 模板，但 `2026-EgoAnchor/makefile` 默认仍指向 `template.tex` / `template.bib`。构建 EgoAnchor 论文时必须显式指定主文件和 bib，或先更新 makefile，避免误编译模板。

## 配置与协议契约

### v1 配置

- 统一运行配置：`EgoAnchor_Python/config/runtime.toml`。
- 加载器：`EgoAnchor_Python/src/config/runtime_config.py`，使用 stdlib `tomllib`，返回 `SimpleNamespace`。
- 主要分组：`server`、`network.receiver`、`network.sender`、`pipeline.calibration`、`pipeline.depth`、`module.segmenter/yoloe/sam3/ffs/foundationpose/cutie`、`debug`。
- 新增/移动配置字段时同步：`runtime.toml`、`runtime_config.py`、使用点、`src/test/test_runtime_config.py`。
- 路径字段按 `EgoAnchor_Python` 项目相对路径解析。
- 当前默认分割后端是 `module.segmenter.type = "yoloe26"`；`sam3`/`AsyncSam3Masker` 保留为历史/可选路径，不是默认主线。

### v3 配置

- v3 默认配置：`EgoAnchor_Python/src_v3/egoanchor/config/defaults.toml`。
- 覆盖配置示例：`EgoAnchor_Python/src_v3/egoanchor/config/mouse.toml`。
- 加载器：`EgoAnchor_Python/src_v3/egoanchor/config/runtime_config.py`。
- 每个 `.toml` 参数必须在同一行末尾写中文注释；新增参数时同步默认值、加载点、使用点和测试。
- 主要分组：`server`、`network.data_plane`、`network.message_plane`、`runtime.commands`、`pipeline.calibration/depth`、`module.segmenter/yoloe/ffs/foundationpose/cutie`、`debug`、`demo.video`、`demo.pose`。
- `network.message_plane.enabled=false` 可用于 Python-only debug，避免没有 NATS server 时阻塞模型调试。

### v1 网络协议

- 传输：ZMQ PUB/SUB + multipart `[topic_utf8, payload_bytes]` + MessagePack。
- Topics：`quest_stereo`、`quest_camera_info`、`pose`。
- 端口：Unity -> Python 默认 `15557`；Python -> Unity 默认 `15556`。不要恢复旧默认 `5556/5557`。
- 契约：`EgoAnchor_Python/src/zmq_utils/payload/protocol_contract.json`。
- `PoseMsg.has_pose=false` 且 `pose_matrix_flat=null/空` 是合法状态包；Unity 应忽略其 pose 应用。

### v3 协议

- 唯一 channel 契约：`EgoAnchor_Protocol/subjects.v1.json`。
- Proto 源：`EgoAnchor_Protocol/proto/protocol/v1/common.proto`、`quest.proto`、`anchor.proto`。
- 默认生成输出：
  - Python v3：`EgoAnchor_Python/src_v3/egoanchor/protocol/v1/*_pb2.py`
  - Unity v3：`EgoAnchor_Unity/Assets/Scripts_v3/EgoAnchor/Protocol/Generated/*.cs`
  - Unity v3 subject 常量：`EgoAnchor_Unity/Assets/Scripts_v3/EgoAnchor/Protocol/SubjectNames.cs`
- 加 `-GenerateV2` 时同步刷新 v2 输出；默认不再写 v2。
- v3 字段号进入共享 proto 后不得重排。删除字段必须在 proto 中 `reserved` 字段号和字段名。
- 业务代码不手写 subject 字符串；Python 从 `egoanchor.protocol` 包级入口导入常量，Unity 从 `SubjectNames` 使用常量。

v3 逻辑 channels：

| Channel | 方向 | 传输 | Protobuf | 说明 |
|---|---|---|---|---|
| `egoanchor.v1.quest.stereo` | Unity -> Python | ZMQ | `QuestStereoFrame` | 高频双目 JPEG，latest-only |
| `egoanchor.v1.quest.camera_info` | Unity -> Python | ZMQ | `QuestCameraInfo` | 低频标定，独立 latest cache |
| `egoanchor.v1.pose.result` | Python -> Unity | NATS | `PoseResult` | 小型 pose 结果，latest-only |
| `egoanchor.v1.anchor.status` | Python -> Unity | NATS | `AnchorStatusEvent` | 状态事件流，当前待接入 |
| `egoanchor.v1.server.heartbeat` | Python -> Unity | NATS | `ServerHeartbeat` | 健康状态，当前待接入 |
| `egoanchor.v1.cmd.anchor.reset` | Unity -> Python | NATS request/reply | `ResetTrackingRequest -> CommandAck` | ack 只表示接受/拒绝 |
| `egoanchor.v1.cmd.anchor.reacquire` | Unity -> Python | NATS request/reply | `ReacquireAnchorRequest -> CommandAck` | 重定位结果靠后续事件/pose |
| `egoanchor.v1.cmd.anchor.control` | Unity -> Python | NATS request/reply | `AnchorControlRequest -> CommandAck` | stage/pause/resume 等控制 |

## 代码地图

### Python v1

- `src/object_tracking_server.py`：旧稳定 Quest 端到端服务入口；接收 `quest_stereo/camera_info`，运行 pipeline，发布 `pose`；保存/备份 `Calibration/cache/camera_info_latest.json`。
- `src/pipeline/quest_object_tracking_pipeline.py`：Quest 主 pipeline。输入 -> YOLOE-26 mask -> FFS depth -> FoundationPose register/track/re-register。FoundationPose/Cutie 输入使用 RGB；OpenCV/YOLO/debug 显示可保留 BGR。
- `src/modules/quest_io.py`：Quest 多 topic 接收和标定缓存访问；公开 `get_stereo_frames()`、`get_camera_info()`、`get_calibration()`、`get_input_state()`。
- `src/modules/yoloe26.py`：默认单目标 prompt segmentation；按置信度选单个 mask，避免多误检 union 污染 pose。
- `src/modules/fast_foundationstereo.py`：FFS 深度，支持 PyTorch/TensorRT；TRT engine 匹配失败按 `trt_strict` 决定报错或回退。
- `src/modules/foundationpose.py`：FoundationPose register/track/visualize 封装。
- `src/modules/cutie.py`：可选 2D mask tracker 与 bbox 中心辅助修正。
- `src/modules/sam3_masker.py`：历史/可选 SAM3 封装；重新启用前必须重验 GPU 抢占、旧帧 mask、Cutie 初始化帧一致性。
- `src/server/`：debug view、键盘控制、运行统计、camera_info cache 等服务辅助。

### Python v3

- `src_v3/tracking_server.py`：当前 v3 主入口 wrapper，调用 `egoanchor.app.tracking_server`。
- `src_v3/quest_video_stream_demo.py`：ZMQ/Protobuf 双目实时预览 demo。
- `src_v3/yoloe_mask_probe.py`：YOLOE mask 调参入口。
- `src_v3/egoanchor/config/`：v3 轻量配置。配置层只读 TOML，不导入 ZMQ/OpenCV/模型。
- `src_v3/egoanchor/protocol/`：subject registry、protobuf registry、包级 Protobuf 入口。业务代码从这里导入 `quest_pb2/common_pb2/anchor_pb2`、常用消息类型和 subject 常量。
- `src_v3/egoanchor/transport/zmq_topic_subscriber.py`：通用 ZMQ SUB；只负责 socket、multipart topic bytes、topic latest-drain，不导入 Protobuf/OpenCV/模型。
- `src_v3/egoanchor/transport/nats_client.py`：唯一 NATS transport 文件；负责后台 asyncio NATS 连接、bytes publish/subscribe/request-reply callback 和 publish 限流，不理解 perception 或 Unity anchor。
- `src_v3/egoanchor/routing/`：`HandlerRegistry`、`NatsRouter`、`iter_nats_request_specs`；负责 subject -> protobuf parse -> handler -> reply serialize。
- `src_v3/egoanchor/handlers/command_handlers.py`：reset/reacquire/control request handler；只 validate/dedup/enqueue/ack，不直接碰 pipeline/GPU。
- `src_v3/egoanchor/runtime/latest_quest_input_store.py`：topic independent latest cache、frame_id/session 去重、camera_info version 和输入统计。
- `src_v3/egoanchor/runtime/quest_stream_receiver.py`：ZMQ bytes -> Quest Protobuf -> latest store。
- `src_v3/egoanchor/runtime/command_queue.py`、`command_dedup.py`、`command_executor.py`：命令队列、request_id TTL 幂等、runtime 内解释命令。
- `src_v3/egoanchor/runtime/tracking_runtime.py`：唯一 pipeline/GPU 状态 owner；poll Quest stream latest、运行 perception pipeline、发布 PoseResult、顺序消费 commands。
- `src_v3/egoanchor/runtime/pose_result_factory.py`：`PoseObservation -> PoseResult` 映射；当前尚未写出 reliability 相关 proto 字段。
- `src_v3/egoanchor/perception/quest_pose_pipeline.py`：Quest v3 pose pipeline；组合 YOLOE-26、FFS、FoundationPose/Cutie，输出 camera-space `PoseObservation` 与 debug 图像，不依赖 ZMQ/NATS/Unity transform。
- `src_v3/egoanchor/perception/quest_calibration.py`：Quest camera_info 到算法处理分辨率 K 的映射，支持 center-crop 与线性缩放。
- `src_v3/egoanchor/algorithms/`：单模型适配层。外部从 `egoanchor.algorithms` 包级入口导入 `SegmenterResult`、`MaskTrackResult`、`Yoloe26Segmenter`、`FastFoundationStereoDepth`、`FoundationPoseObjectEstimator`、`CutieMaskTracker`。
- `src_v3/egoanchor/reliability/pose_quality.py`：轻量感知可靠性评分，目前主要用于 HUD 和内部诊断，不等于最终 adaptive anchor controller。
- `src_v3/egoanchor/diagnostics/`：OpenCV HUD、depth/mask/pose dashboard、窗口工具。
- `src_v3/egoanchor/tests/test_command_flow.py`：当前 v3 command request/reply、dedup、executor 轻量测试。

### Unity v1

- `Assets/Scripts/Net/Communicate/PayloadSender.cs`：多 `SenderEntry` PUB 发送器，每个 entry 绑定 `encoder + topic + targetFps`。
- `Assets/Scripts/Net/Communicate/PayloadReceiver.cs`：多 `ReceiverEntry` SUB 接收器，后台线程收包，主线程按 topic 路由；用 `_latestByTopic` 做 topic 级 latest-drain。
- `Assets/Scripts/Net/Payload/Encoder/QuestStereoEncoder.cs`：左右 Passthrough texture JPEG 编码，生成 `QuestStereoMsg`；成功编码后触发 `OnFrameEncoded(frame_id, cameraPose)`，需 Inspector 显式绑定到 `FrameAlignedObjectAnchor.HandleFrameEncoded(long, Pose)`。
- `Assets/Scripts/Net/Payload/Encoder/QuestCameraInfoEncoder.cs`：低频发送左右相机内参、active array、baseline、lens offset、`sender_mono_ms`。
- `Assets/Scripts/Net/Payload/Decoder/PoseDecoder.cs`：解码 `PoseMsg`；默认 `convertFromOpenCvCamera=true`，把 OpenCV 相机坐标转 Unity 坐标。
- `Assets/Scripts/Anchor/FrameAlignedObjectAnchor.cs`：按 `frame_id` 回查左目相机 world pose，将相机局部 object pose 映射到 Unity world raw anchor pose，并按 processors 输出稳定 Transform。
- `Assets/Scripts/Anchor/AnchorProcessor.cs`：`Pose` 是 struct，处理器必须返回处理后的 `Pose`，不能依赖 UnityEvent 参数原地修改。

### Unity v3

- `Assets/Scripts_v3/EgoAnchor/Protocol/Generated/`：C# Protobuf 生成代码。
- `Assets/Scripts_v3/EgoAnchor/Protocol/SubjectNames.cs`：由协议脚本生成的 subject 常量，不要手改。
- `Assets/Scripts_v3/EgoAnchor/Transport/ZmqTopicPublisher.cs`：只管理 NetMQ PUB socket，发送 `[topic_utf8, protobuf_payload_bytes]`。
- `Assets/Scripts_v3/EgoAnchor/Transport/NatsControlClient.cs`：NATS 消息面客户端；订阅 PoseResult latest queue，提供 bytes request/reply；后台回调不改 Transform。
- `Assets/Scripts_v3/EgoAnchor/Quest/StereoFrameSource.cs`：读取左右 Passthrough texture、记录 left/right/center camera pose、JPEG 编码、构造 `QuestStereoFrame`。
- `Assets/Scripts_v3/EgoAnchor/Quest/CameraInfoSource.cs`：读取 Quest intrinsics/lens pose 并构造 `QuestCameraInfo`。
- `Assets/Scripts_v3/EgoAnchor/Quest/FramePoseHistory.cs`：`frame_id -> capture-time left/right/center camera world pose` 环形缓存，是 frame-aligned anchor 的关键。
- `Assets/Scripts_v3/EgoAnchor/Quest/AnchorPoseReference.cs`：Unity 本地对齐参考枚举。Python 当前语义仍是左目 OpenCV camera pose；Right/Center/None 只用于本地对照/补偿/诊断。
- `Assets/Scripts_v3/EgoAnchor/Client/QuestStreamPublisher.cs`：场景级 ZMQ 数据面发送组件；支持 PlayerPrefs 配置 Python IP。
- `Assets/Scripts_v3/EgoAnchor/Client/PoseResultReceiver.cs`：主线程 latest-drain、解析 PoseResult、交给 `PoseResultHub`。
- `Assets/Scripts_v3/EgoAnchor/Client/AnchorCommandClient.cs`：Unity command API，发送 reset/reacquire/control request 并解析 `CommandAck`。
- `Assets/Scripts_v3/EgoAnchor/Anchor/PoseResultHub.cs`：将同一条 PoseResult 广播给多个 `PoseToAnchorRuntime`，用于 raw vs smoothed 对照。
- `Assets/Scripts_v3/EgoAnchor/Anchor/CameraPoseFrameAligner.cs`：OpenCV camera pose + frame history -> Unity world pose；包含 `AnchorPoseTransform` 轴翻转和固定 offset 配置。
- `Assets/Scripts_v3/EgoAnchor/Anchor/PoseToAnchorRuntime.cs`：v3 pose-to-anchor 组合点；保留 raw pose，并按 processor chain 生成 stable pose。当前没有完整状态机。
- `Assets/Scripts_v3/EgoAnchor/Anchor/AnchorPoseProcessor.cs`、`AnchorKalmanPoseProcessor.cs`、`AnchorLowPassPoseProcessor.cs`：可插拔处理器与当前 baseline。
- `Assets/Scripts_v3/EgoAnchor/Anchor/DynamicObjectAnchor.cs`：只读取 runtime raw/stable pose 并应用 Transform，不承载滤波、状态机或网络逻辑。

Unity v3 命名/目录规则：

- `Quest/` 放 Quest 数据提供者/source 和采集期缓存。
- `Transport/` 放网络 socket/client，不理解 Quest 或 anchor 语义。
- `Client/` 放把 source、transport、runtime 组合成场景组件的客户端脚本。
- `Anchor/` 放 frame alignment、processor chain、pose hub、Transform 输出和未来 anchor policy/state。
- 新增脚本应写清中文 `<summary>` 和 Inspector 参数 `[Tooltip]`，尤其是端口、帧率、HWM、缓存容量、坐标/时间语义。

主场景是 `EgoAnchor_Unity/Assets/Scenes/EgoAnchor.unity`；v3 场景工作区应在 `Assets/Scene_v3/`，用于并行测试，不得替换或破坏旧主场景。

## 标定、深度与坐标约定

- Python FoundationPose 输出 OpenCV camera 坐标：x 右、y 下、z 前。
- Unity camera-local 坐标约定：x 右、y 上、z 前。v1 由 `PoseDecoder` 转换；v3 由 `CameraPoseFrameAligner` / `AnchorPoseTransform` 转换。
- v3 Python 感知 pipeline 当前使用左目图像、左目 K、左目 mask/depth，因此 `PoseResult.pose_matrix_cv_camera` 语义仍是左目 OpenCV camera pose。
- Unity 必须使用“采集该 `frame_id` 时”的参考 camera world pose，而不是 pose 到达时的 HMD pose。
- v3 `FramePoseHistory` 同时缓存 left/right/center pose；Left 是默认语义，Right/Center/None 只用于本地诊断、对照或小量补偿实验。
- `object_tracking_server.py` 保存最新 v1 `quest_camera_info` 到 `EgoAnchor_Python/Calibration/cache/camera_info_latest.json`；v3 当前依赖网络 camera_info latest store。
- v1 `pipeline.calibration.assume_center_crop=true` 与 v3 `pipeline.calibration.assume_center_crop=true` 都表示 K 映射使用中心裁剪 + 缩放；`false` 为线性缩放。若边缘 pose/depth 偏差明显，优先对比该开关。
- v1 `quest_object_tracking_pipeline._preprocess_stereo_pair()` 和 v3 `preprocess_stereo_pair()` 都只缩放实际接收图像，不先扩回 active array 再裁剪。

## 调试与排查

- Python OpenCV 热键：`1/2/3/4` 切 stage；`r` reset；`q`/`ESC` 退出。
- 调试顺序：stage 1 看输入 -> stage 2 看 mask -> stage 3 看 depth/mask 对齐 -> stage 4 看 register/track。
- 关键 HUD/日志：`stage`、`phase`、`mask_src`、`pose_source`、`det_count`、`depth_valid_ratio`、`depth_in_mask`、`median/iqr`、`track_reject`、`reliability_score`、`sender_est`。`sender_raw` 是跨进程/设备单调时钟差，不可直接当真实延迟。
- stereo 收不到但 camera_info 能收到：查 Unity stereo source、左右 camera `IsPlaying`、ZMQ publisher、Python 接收 HWM。
- camera_info 收不到：查 topic、v1 `QuestCameraInfoEncoder` 或 v3 `CameraInfoSource` 引用、Python 订阅。
- Unity 物体位姿错：查 OpenCV->Unity 坐标转换、frame pose cache 命中、`frame_id` 透传、K 映射策略、`AnchorPoseTransform` 轴翻转和 offset。
- Unity `PoseResultReceiver` decoded 增加但 aligned 为 0：查 `PoseResultHub` runtime 列表、`PoseToAnchorRuntime.framePoseHistory` 是否与 `StereoFrameSource` 共用、`alignmentReference` 是否正确、Python 是否原样透传 frame_id。
- raw 物体正常但 smoothed 不动：查 `PoseToAnchorRuntime.processors`、processor 是否启用、`DynamicObjectAnchor.outputMode` 是否为 `Smoothed`。
- YOLOE mask 不稳：调 prompt、conf、mask threshold、max_det，并用 `debug.show_mask_snapshot=true` 或 `yoloe_mask_probe.py` 看真实下游 mask。
- `depth_in_mask` 低：优先查 K 映射、左右图同步/基线、FFS 权重或 TRT engine。
- register 失败：先确认 mask/depth 对齐，再查 mesh 路径、尺度、对称设置、refine iter。
- track 丢失：依赖 `module.foundationpose.re_register_on_track_lost=true`；若 2D 辅助引入抖动，可设 `module.cutie.adjust_pose=false`。
- NATS 命令无 ack：查 `nats-server` 是否启动、Unity/Python NATS URL 是否指向同一地址、防火墙 4222、Python `network.message_plane.enabled`。

## 后续实现规划

近期目标不是继续重写目录，而是把 v3 从可运行 debug 链路推进到论文级系统。建议按以下顺序推进，每阶段都保留可验证 smoke。

### Phase A：协议诊断字段补强

目标：让 Unity anchor policy 能消费 Python 感知可靠性，而不只能看 `has_pose/phase`。

- 非破坏性追加 `PoseResult` 字段：`reliability_score`、`reliability_flags`、`depth_valid_in_mask`、`mask_area_ratio`、`pose_source`、`server_receive_mono_ms`、`server_publish_mono_ms`。
- 必要时追加 `AnchorStatusEvent.generation`，用于 reset/reacquire 后防止旧 pose 污染。
- 同步更新：proto、生成脚本、Python `PoseResultFactory`、Unity generated、Unity receiver/runtime、v3 proto roundtrip 测试。
- 不重排已有字段号；旧字段语义保持兼容。

### Phase B：status / heartbeat 正式接入

目标：让系统具备论文级可观测性，而不是只靠 OpenCV HUD。

- Python 添加 `StatusEventPublisher`、`HeartbeatPublisher` 或等价轻量 factory/publisher。
- `TrackingRuntime` 在 WAIT_STREAM、WAIT_CALIBRATION、NO_MASK、REJECT_DEPTH、REGISTER、TRACK、TRACK_REJECT、RESET_APPLIED、REACQUIRE_REQUESTED 等关键状态发布事件。
- Unity 添加 `AnchorStatusReceiver`、`ServerHeartbeatReceiver`，后台只入队，主线程消费。
- Heartbeat 应包含 input ready、latest frame id、camera_info version、runtime fps、publish stats、command queue length、last error。

### Phase C：Unity reliability-aware anchor controller

目标：完成论文核心方法，不把错误 pose 直接应用为 anchor。

- 新增 Unity `Reliability/` 或 `Anchor/Policy` 模块，先实现规则式最小 controller。
- 输入：`PoseResult` 可靠性字段、frame history 命中、pose innovation、回包年龄、连续 no-pose 时间、heartbeat 状态。
- 输出：`Accept`、`Smooth`、`Hold`、`Coast`、`Reject`、`Lost`、`Relocalizing` 等 anchor 行为。
- 保留 raw、low-pass、Kalman baseline，full method 单独作为 reliability-aware runtime 或 processor/policy 链。
- 不要把 controller 写进 `NatsControlClient`、`PoseResultReceiver` 或 `DynamicObjectAnchor`；它应在 anchor runtime/policy 层。

建议状态：

| 状态 | 含义 |
|---|---|
| `Uninitialized` | 尚无有效 pose 或缺少必要绑定 |
| `Searching` | Python 正在检测/注册，Unity 暂无稳定 anchor |
| `Tracking` | 持续收到可靠 pose，正常更新 |
| `Coasting` | 短时无 pose 或低频延迟，用 predictor/last velocity 续航 |
| `FrozenUncertain` | pose 不可靠但不立刻清空，冻结显示并标注不确定 |
| `Lost` | 长时间无可靠 pose，停止更新或隐藏/提示 |
| `Relocalizing` | 用户或系统主动 reacquire 中 |
| `Paused` | 用户暂停 anchor 更新 |
| `Error` | 协议/对齐/runtime 错误 |

### Phase D：实验与日志基础设施

目标：把 demo 变成可采集论文数据的系统。

- 记录每帧：frame_id、capture/send/receive/publish/apply 时间、phase、score、flags、raw pose、stable pose、anchor state、align result。
- 导出 CSV/JSONL，按 session 分目录保存，不写进高频日志。
- 支持 raw / arrival-time / frame-aligned / low-pass / Kalman / reliability-aware 条件切换。
- 做 fake replay 或 recorded session 入口，用同一输入离线比较多种 anchor policy。
- 为 Unity 侧输出添加轻量实验面板或文件日志，避免只靠 Inspector。

### Phase E：端到端与论文实验

最低论文闭环：

1. Quest 真机 + Python v3 real pipeline + Unity v3 raw/stable anchor 连续运行。
2. 对比 arrival-time anchoring vs frame-aligned anchoring。
3. 对比 always update / raw、low-pass、Kalman、reliability-aware policy。
4. 覆盖静态观察、快速头动、部分遮挡、出视野后重获。
5. 至少 3 个代表性刚体物体，避免只用 cube/pink mouse 导致泛化叙事太弱。
6. 输出端到端延迟、world-space anchor error/jitter、recovery success/time、failure taxonomy。

加分项：

- 轻量任务实验：真实物体标签/边框附着、遮挡后指认/确认、主观稳定性/信任评分。
- 更完整 latency breakdown。
- 多对象或更复杂场景，但不要在单目标稳定前扩展。

## 论文维护与目标

IEEE VR 2027 论文定位：

> How can asynchronous 6DoF object pose tracking be transformed into stable, world-consistent, recoverable real-object anchoring in passthrough MR?

中文表述：

> 如何在外部异步感知、头显持续运动、pose 低频/延迟/间歇失效的条件下，把 6DoF object pose stream 转化为稳定、世界一致、可恢复、可交互的真实物体 MR anchor？

推荐标题方向：

- `EgoAnchor: Frame-Aligned 6DoF Object Pose Tracking for World-Consistent Object Anchoring in Passthrough Mixed Reality`
- 如果 Phase C 完成并有实验证据，再使用 `... and Reliability-Aware Anchor Control ...` 或 `... Adaptive Anchor Control ...`。

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
- 现有论文草稿中“ZMQ + MessagePack”属于 v1 实现描述；v3 主线论文应改为 ZMQ Protobuf 数据面 + NATS Protobuf 消息/命令面。
- 实验主指标优先用 anchor 指标：world-space anchor error、head-motion-induced slip、world-space jitter/drift、recovery success/time、P50/P90 latency。ADD/ADD-S、translation/rotation pose error 只能作为支持性底层感知指标。
- 如果做用户/任务实验，需提前确认伦理/IRB 要求。

## 环境

- Python 环境由 `EgoAnchor_Python/pixi.toml` 管理：Python 3.12、CUDA 12.8、PyTorch 2.7 cu128、TensorRT cu12、pyrealsense2、ultralytics/YOLOE、msgpack、onnx、pillow、protobuf、nats-py、Cutie editable path。
- Windows 重建 `.pixi/envs/default` 失败时，先关闭 VS Code Python LSP、Black Formatter、残留 Python 进程，避免文件占用。
- FoundationPose C++ 扩展由 `pixi run build` 中 `_build-fp` 构建；FFS ONNX/TRT artifact 也由 build task 生成。
- Unity 依赖由 `EgoAnchor_Unity/Packages/manifest.json` 管理；旧链路依赖 MessagePack C#，v2/v3 依赖 Google.Protobuf、NATS.Net、NetMQ 等。

## 关键历史约束：不要回退

- 不恢复旧默认端口 `5556/5557`；保持 Unity -> Python `15557`，v1 Python -> Unity `15556`。
- 不恢复 ZMQ PUSH/PULL、业务分片、JSON pose、单图 `packed_image_jpeg_legacy`。
- 不恢复旧入口/文件：`src/pose_tracker_api.py`、`src/vpt_cli.py`、`src/VOT.py`、`src/quest_stereo_pose_pipeline.py`、`src/modules/quest_stereo.py`、`src/modules/quest_receiver.py`、`src/zmq_utils/timing.py`、`src/zmq_utils/latency.py`、Unity 旧 `StaticStereoEncoder.cs`。
- 不恢复 Python `PayloadSender` default topic、TRT legacy alias/fallback 文件名、运行时 `onnx.yaml` 依赖。
- 不添加 Unity `LegacyQuestReceiverPort` / `LegacyPoseServerPort` 自动迁移逻辑。
- 不把异步 SAM3 + Cutie 种子刷新写回默认主线。
- 不恢复 WebRTC 图像传输方案、`try_webrtc/`、Unity `Assets/Scripts_v2/EgoAnchor/WebRtc/`、NATS 图像流 smoke server。
- 高频路径日志保持精简；详细收发/编码统计只通过显式 debug 开关启用。
- Unity 事件链优先显式 Inspector 绑定，避免组件内部自动 Find/AddListener 造成重复订阅或隐藏依赖。
- NATS handler 只能 parse/validate/dedup/enqueue/ack；pipeline/GPU 状态必须由单一 `TrackingRuntime` 顺序拥有。
- Python 不输出 Unity world pose；Unity 用 capture-time frame pose 做 world anchor。
- 不使用 pose 到达时 HMD pose 代替发送帧 pose。这个是项目核心历史坑。
- 不把 v3 尚未实现的 reliability controller、status/heartbeat、用户实验写成已完成。

## AGENTS.md 维护规则

- 本文件保持“当前事实 + 核心约定 + 后续路线 + 历史坑”，不要追加日期日志。
- 大改后同步入口、模块职责、协议字段、标定策略、坐标、调试统计、论文定位、实验目标和排查结论。
- 若事实被代码或协议更新推翻，直接改旧条目，不要在后面追加相互矛盾的新条目。
