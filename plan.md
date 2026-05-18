**总体定位**
新架构应围绕论文目标重新定义为：

`Quest realtime sensing -> external 6D pose estimator -> unreliable pose stream -> frame-aligned world pose -> reliability-aware dynamic XR anchor`

也就是说，新版本不只是把旧 `FoundationPose + Unity Transform` 重写一遍，而是把系统拆成两层：

1. **Perception Runtime**：负责从 Quest 图像和标定中产生带诊断信息的相机坐标系 6D pose。
2. **Anchor Runtime**：负责把低频、延迟、噪声、间歇失效的 pose 转换成 Unity 世界中的稳定、可交互、可恢复 dynamic object anchor。

这正好对应 `EgoAnchor-chagpt.md` 中的论文主线：`Pose-to-Anchor / Reliability-Aware Dynamic Object Anchoring for XR`。

---

**1. 通信方案评估**
你计划的方案是合理的：

- **ZMQ 用于 Quest 高频实时视频流**。
- **NATS 用于命令、状态、心跳、pose/status 小消息**。
- **Protobuf 作为 Python/Unity 共享消息协议**。

这比旧架构更清晰，因为旧架构把所有内容都放在 `ZMQ + MessagePack` 里，能跑通，但不利于扩展命令、状态机、ack、实验日志和 schema 演进。

推荐通信分层如下：

| 数据类型 | 方向 | 推荐传输 | 原因 |
|---|---|---|---|
| `QuestStereoFrame` | Unity -> Python | ZMQ PUB/SUB | 高频、大 payload、latest-only，ZMQ 更直接 |
| `QuestCameraInfo` | Unity -> Python | ZMQ PUB/SUB | 低频但和图像同属数据面，保持同一数据入口 |
| `PoseResult` | Python -> Unity | NATS pub/sub | 小消息，便于状态订阅、日志、调试、未来多消费者 |
| `AnchorStatusEvent` | Python -> Unity | NATS pub/sub | 事件流，不应和图像流耦合 |
| `ServerHeartbeat` | Python -> Unity | NATS pub/sub | 运行状态、健康检查 |
| `Reset/Reacquire/Control` | Unity -> Python | NATS request/reply | 需要 ack、request_id、幂等语义 |

当前 `EgoAnchor_Protocol/subjects.v1.json` 已经基本符合这个设计，应继续作为 v2 的唯一 channel 契约来源。

---

**ZMQ 数据面建议**
ZMQ 部分只做两件事：

1. Unity 发布 `egoanchor.v1.quest.stereo`。
2. Unity 发布 `egoanchor.v1.quest.camera_info`。

建议保持：

- PUB/SUB。
- multipart `[topic_utf8, protobuf_payload_bytes]`。
- topic 级 latest-drain。
- stereo `latest_only=true`。
- camera_info 低频但也应 topic 独立缓存。
- 不做业务分片。
- 不恢复旧 `5556/5557` 端口。
- 默认继续使用 `15557` 作为 Unity -> Python 数据面端口。

旧架构中可参考的部分：

- `PayloadSender.cs` 的多 sender entry 设计。
- `PayloadReceiver.cs` 的 topic 级 latest-drain 思路。
- `QuestStereoEncoder.cs` 的双目 texture 采集、JPEG 编码、`frame_id` 递增、`sender_mono_ms`、`unity_frame`。
- `QuestCameraInfoEncoder.cs` 的内参、baseline、lens pose 采集逻辑。
- Python `QuestReceiver` 的 per-topic latest-drain、diagnostics、camera_info version、K remapping 思路。
- Python `PayloadReceiver.recv_all_latest_by_topic()` 的行为模型。

不建议直接迁移的部分：

- MessagePack message class。
- 旧 `QuestStereoMsg` / `QuestCameraInfoMsg` / `PoseMsg` 网络模型。
- 旧 `zmq_utils/payload/decoder` 和 `encoder` 的 MessagePack 编解码层。
- 旧 `object_tracking_server.py` 的“网络、pipeline、debug、状态、发布”混合入口结构。
- Unity 旧 `PayloadEncoder/PayloadDecoder` 如果仍然强绑定 MessagePack，应在 v2 新建 Protobuf 版本，不要复用旧类名造成混淆。

---

**NATS 控制面建议**
NATS 不承载图像，不参与高频帧传输。它只负责：

- Python 发布 `PoseResult`。
- Python 发布 `AnchorStatusEvent`。
- Python 发布 `ServerHeartbeat`。
- Unity 发起 `ResetTrackingRequest`。
- Unity 发起 `ReacquireAnchorRequest`。
- Unity 发起 `AnchorControlRequest`。

这使 v2 更适合论文里的状态机与实验分析，因为状态变化、重定位、失败原因、可靠性评估都能被记录成结构化事件。

建议：

- NATS handler 必须轻量，只 parse/validate/enqueue。
- Python pipeline/GPU 状态只能由单一 `TrackingRuntime` 拥有。
- command ack 只表示“命令已接受/拒绝”，不要等待重定位成功。
- 重定位结果通过后续 `PoseResult` 和 `AnchorStatusEvent` 反馈。
- `request_id` 用于幂等处理。
- Unity 端不要在 MonoBehaviour 回调里直接跑复杂状态逻辑，应该交给 client/service 类。

---

**Protobuf 方案评估**
Protobuf 很适合 v2，因为：

- Python/Unity schema 强一致。
- 字段号可演进。
- 比 MessagePack 更适合作为论文系统中的协议定义。
- 可配合 `subjects.v1.json` 明确 transport、direction、mode、latest-only。

当前 proto 已经覆盖基础链路：

- `MessageHeader`
- `QuestStereoFrame`
- `QuestCameraInfo`
- `PoseResult`
- `AnchorStatusEvent`
- `ServerHeartbeat`
- reset/reacquire/control request

但为了论文目标，后续建议扩展 `PoseResult` 或新增消息时重点补齐：

- `reliability_score`
- `reliability_flags`
- `pose_source`，例如 `register/track/re_register/predict/hold`
- `tracking_state`
- `capture_sender_mono_ms`
- `server_receive_mono_ms`
- `server_publish_mono_ms`
- `depth_in_mask_ratio`
- `mask_area_ratio`
- `jump_rejected`
- `innovation_norm`
- `visible_ratio`
- `failure_reason`

当前先不用马上改 proto，但新架构设计中要为这些字段留出位置。

---

**关键架构判断**
`PoseResult` 是否应该直接包含 Unity world pose？

我的建议是：**Python 仍输出相机坐标系 pose，Unity v2 Anchor Runtime 负责 frame-aligned world transform。**

理由：

- Python 不应依赖 Unity 世界坐标。
- Unity 才有准确的发送帧 camera pose history。
- 旧框架中 `FrameAlignedObjectAnchor` 的核心思想是正确的：用 `frame_id` 回查采集帧相机 pose，而不是用 pose 到达时的 HMD pose。
- 这正是论文里的关键贡献点之一，应该在 v2 中升格为明确模块，而不是隐藏在 decoder/applier 里。

因此 v2 推荐链路是：

1. Unity `QuestStreamPublisher` 调度 `StereoFrameSource` 采集 stereo frame。
2. 同一时刻缓存 `frame_id -> leftCameraWorldPose + sender_mono_ms + unity_frame`。
3. Unity 通过 ZMQ 发 `QuestStereoFrame`。
4. Python 对该 frame 估计 `pose_matrix_cv_camera`。
5. Python 通过 NATS 发 `PoseResult(frame_id, has_pose, diagnostics)`。
6. Unity `PoseResultReceiver` 收到结果。
7. Unity `FramePoseHistory` 用 `frame_id` 找采集时刻 camera world pose。
8. Unity `PoseToAnchorRuntime` 转成 raw world anchor pose。
9. Unity `ReliabilityAwareAnchorController` 进行 gate/filter/predict/state lifecycle。
10. Unity 输出 stable dynamic anchor transform。

---

**2. Python module 结构是否保留**
需要保留，但要重组。

旧 `modules/` 目前承担的是算法组件封装，仍然有价值：

- `yoloe26.py`
- `fast_foundationstereo.py`
- `foundationpose.py`
- `cutie.py`
- `sam3_masker.py`
- `quest_io.py`
- `realsense.py`

但 v2 不应该把所有东西都继续叫 `modules` 然后由一个大 pipeline 随意串起来。建议改成更明确的分层：

- `perception/`：6D pose 感知 pipeline。
- `algorithms/`：具体模型 wrapper。
- `transport/`：ZMQ/NATS。
- `protocol/`：generated protobuf 与 contract helpers。
- `runtime/`：服务生命周期、命令队列、状态机。
- `anchor/` 或 `reliability/`：可靠性评估、pose quality、状态输出。
- `app/`：组合入口。

Python v2 中 `module` 的价值应从“随便放模型代码”变成“算法适配层”。

推荐职责划分：

| 层级 | 职责 | 示例 |
|---|---|---|
| `transport` | 网络收发，不做算法 | ZMQ data plane receiver, NATS control plane |
| `protocol` | Protobuf 编解码、subject 契约 | generated pb2, subject registry |
| `perception` | 输入 frame -> pose observation | Quest tracking pipeline |
| `algorithms` | 单个模型 wrapper | YOLOE, FFS, FoundationPose, Cutie |
| `reliability` | pose 可信度评估 | mask/depth/innovation/jump checks |
| `runtime` | 单线程拥有 GPU/pipeline 状态 | TrackingRuntime, command queue |
| `app` | 入口组装 | tracking_server.py |
| `diagnostics` | stats/log/debug view | runtime stats, optional OpenCV windows |
| `config` | v2 配置 | runtime_v2.toml/schema |

---

**Python 新目录结构**
建议在 `EgoAnchor_Python/src_v2` 下搭建如下结构：

```text
EgoAnchor_Python/src_v2/
  __init__.py

  app/
    __init__.py
    tracking_server.py
    cli.py

  config/
    __init__.py
    runtime_config.py
    defaults.toml

  protocol/
    __init__.py
    subjects.py
    generated/
      __init__.py
      protocol/
        v1/
          common_pb2.py
          quest_pb2.py
          anchor_pb2.py

  transport/
    __init__.py
    zmq_data_plane.py
    nats_control_plane.py
    message_bus.py

  runtime/
    __init__.py
    tracking_runtime.py
    runtime_state.py
    command_queue.py
    lifecycle.py

  perception/
    __init__.py
    quest_frame.py
    quest_calibration.py
    quest_pose_pipeline.py
    pose_observation.py

  algorithms/
    __init__.py
    yoloe26_segmenter.py
    fast_foundationstereo_depth.py
    foundationpose_estimator.py
    cutie_mask_tracker.py

  reliability/
    __init__.py
    pose_quality.py
    pose_gate.py
    observation_scorer.py

  diagnostics/
    __init__.py
    runtime_stats.py
    debug_view.py
    window.py
    event_log.py

  tests/
    __init__.py
    test_subject_contract.py
    test_proto_roundtrip.py
    test_command_queue.py
    test_frame_store.py
    test_reliability_gate.py
```

当前实现注记：`algorithms/__init__.py` 统一导出 `SegmenterResult`、`MaskTrackResult` 和具体算法适配器；由于每类算法当前只有一个具体实现，已不保留只含 `Protocol` 的空基类文件，外部代码应直接 `from egoanchor.algorithms import ...`。`perception/__init__.py` 统一导出 `PoseObservation`、Quest 标定/帧工具、`QuestPosePipeline` 和 `build_quest_pose_pipeline`；`protocol/__init__.py` 统一导出 subjects 常量、`quest_pb2/common_pb2/anchor_pb2` 和常用 Protobuf 类型；wrapper/runtime/tests 也优先使用包级入口，生成的 `*_pb2.py` 内部 import 例外。OpenCV demo 窗口固定初始尺寸由 `config/defaults.toml` 的 `demo.video`、`demo.pose` 和 `debug` 字段控制，参数说明统一写在同一行末尾注释。

---

**Python 关键入口职责**
`app/tracking_server.py`

- v2 Python 主入口。
- 加载配置。
- 初始化 ZMQ data plane。
- 初始化 NATS control plane。
- 初始化 `TrackingRuntime`。
- 进入主循环。
- 不直接实现模型细节。
- 不直接处理 NATS command 的业务逻辑。

`transport/zmq_data_plane.py`

- 绑定 Unity -> Python data endpoint。
- 订阅 `egoanchor.v1.quest.stereo` 和 `egoanchor.v1.quest.camera_info`。
- multipart topic + protobuf payload。
- 按 topic latest-drain。
- 解码为 Protobuf message。
- 输出 `LatestQuestInputStore` 或简单回调。
- 不引入 OpenCV 模型逻辑。

`transport/nats_control_plane.py`

- 连接 NATS。
- 发布 `PoseResult`、`AnchorStatusEvent`、`ServerHeartbeat`。
- 注册 reset/reacquire/control request handlers。
- handlers 只校验、ack、写 command queue。
- 不直接调用 FoundationPose/GPU。

`runtime/tracking_runtime.py`

- 唯一拥有 perception pipeline 状态。
- 从 ZMQ latest store 取最新 frame/camera_info。
- 执行 pipeline。
- 调用 reliability scorer。
- 生成 `PoseResult`。
- 处理 command queue。
- 发布 heartbeat/status。
- 管理 `Searching/Tracking/Lost/Reacquiring/Paused` 等 server-side 状态。

`perception/quest_pose_pipeline.py`

- 负责 `QuestStereoFrame + QuestCalibration -> PoseObservation`。
- 组合 segmenter/depth/pose estimator/mask tracker。
- 输出相机坐标系 pose 和诊断指标。
- 不知道 NATS/ZMQ。
- 不知道 Unity transform。

`reliability/pose_quality.py`

- 将 pipeline 诊断转换为 reliability score。
- 包含 mask area、depth valid ratio、pose jump、track failure、phase 等。
- v1 可以先简单规则化，后续升级。

---

**Python 可从旧代码迁移的内容**
建议迁移方式是“复制思想，重新落地接口”，不是直接搬旧文件。

可迁移：

- `quest_io.QuestStereoCalibration.scaled_k()` 的 K 映射逻辑。
- `quest_io` 的 per-topic latest drain 设计。
- `quest_object_tracking_pipeline.py` 中 YOLOE + FFS + FoundationPose 的处理顺序。
- `fast_foundationstereo.py` 的 TRT/PyTorch 切换和 engine 匹配逻辑。
- `foundationpose.py` wrapper。
- `yoloe26.py` wrapper。
- `cutie.py` 可选 mask tracker。
- `server/runtime_stats.py` 的统计思想。
- `server/debug_view.py` 的可视化思想。
- `camera_info_cache.py` 的标定缓存策略。

暂不迁移或重写：

- MessagePack payload message/encoder/decoder。
- 旧 `object_tracking_server.py` 单体入口。
- 旧 `quest_io.py` 中绑定 MessagePack 的部分。
- 旧 CLI 参数风格；v2 应继续优先配置文件。
- RealSense pipeline 不进入 v2 主线，只保留为算法调试参考。

---

**3. Unity 新架构设计**
Unity v2 应该更明确地分成：

- `Transport`：ZMQ/NATS。
- `Protocol`：Protobuf 生成代码和 subject 常量。
- `Client`：把 transport 组合成 EgoAnchor client。
- `Quest`：采集 passthrough stereo 和 camera_info。
- `Anchor`：pose-to-anchor 核心逻辑。
- `Reliability`：gate/filter/predict/state。
- `Diagnostics`：HUD/log/stats。
- `Scene_v2`：新测试场景，不影响旧 `Scenes/EgoAnchor.unity`。

---

**Unity 新目录结构**
建议在 `EgoAnchor_Unity/Assets/Scripts_v2` 下搭建：

```text
EgoAnchor_Unity/Assets/Scripts_v2/
  EgoAnchor/
    Protocol/
      Generated/
        Common.cs
        Quest.cs
        Anchor.cs
      ChannelNames.cs
      SubjectNames.cs
      ProtoCodec.cs

    Transport/
      ZmqTopicPublisher.cs
      NatsControlClient.cs
      NatsPoseSubscriber.cs
      TransportSettings.cs

    Quest/
      StereoFrameSource.cs
      CameraInfoSource.cs
      FramePoseHistory.cs
      QuestFrameCapture.cs

    Client/
      EgoAnchorClient.cs
      QuestStreamPublisher.cs
      AnchorCommandClient.cs
      PoseResultReceiver.cs
      ServerHeartbeatReceiver.cs

    Anchor/
      PoseResult.cs
      CameraPoseFrameAligner.cs
      PoseToAnchorRuntime.cs
      DynamicObjectAnchor.cs
      AnchorState.cs
      AnchorStateMachine.cs
      AnchorLifecycleEvent.cs

    Reliability/
      AnchorObservation.cs
      ReliabilityScore.cs
      ReliabilityGate.cs
      AnchorFilter.cs
      OneEuroAnchorFilter.cs
      KalmanAnchorFilter.cs
      AnchorPredictor.cs

    Diagnostics/
      EgoAnchorHud.cs
      LinkStats.cs
      AnchorDebugGizmos.cs
      EventLogPanel.cs

    Config/
      EgoAnchorSettings.cs
```

推荐在 `EgoAnchor_Unity/Assets/Scene_v2` 下：

```text
EgoAnchor_Unity/Assets/Scene_v2/
  EgoAnchor_v2.unity
  EgoAnchor_v2.unity.meta
  Prefabs/
    EgoAnchorClient.prefab
    DynamicObjectAnchor.prefab
    DiagnosticsHud.prefab
```

如果暂时不想创建 prefab，也可以先只设计脚本目录，之后逐步搭建 scene。

当前 Unity v2 目录/命名约定：

- 协议文件统一放在 `Assets/Scripts_v2/EgoAnchor/Protocol/`；`Generated/*.cs` 与 `ChannelNames.cs` 都由 `EgoAnchor_Protocol/tools/generate_proto.ps1` 生成。旧外层 `Assets/Scripts_v2/Protocol/` 不再使用，避免和业务侧 `EgoAnchor/Protocol` 重名。
- `data plane` 是架构术语，表示 ZMQ 上的高频 stereo/camera_info 数据面；`control plane` 表示 NATS 上的低频 pose/status/heartbeat/command 控制面。术语可以在文档中保留，但类名优先表达具体职责。
- 因此旧 `QuestDataPlanePublisher` 改为 `QuestStreamPublisher`，旧 `ZmqDataPlanePublisher` 改为 `ZmqTopicPublisher`。
- `Quest/` 目录用于 Quest 数据提供者/source 和采集期缓存；`Client/` 目录用于组合 source、transport、anchor runtime 的场景级组件；`Transport/` 目录只做网络，不理解 Quest/anchor 语义。
- `EgoAnchor.V2.Quest` 命名空间内的类可省略重复 `Quest` 前缀：`StereoFrameSource`、`CameraInfoSource`；共享协议消息名仍保留 `QuestStereoFrame`、`QuestCameraInfo`。
- Unity v2 新脚本要添加中文 `<summary>`；所有 Inspector 暴露参数要添加 `[Tooltip]`，说明单位、默认值、实时性/坐标/时间语义和不要回退的历史约束。

---

**Unity 关键类职责**
`Quest/StereoFrameSource.cs`

- 读取左右 `PassthroughCameraAccess` texture。
- JPEG 编码。
- 生成 `QuestStereoFrame` Protobuf。
- 写入 `MessageHeader.frame_id`、`unity_frame`、`sender_mono_ms`。
- 同步记录左目 camera pose 到 `FramePoseHistory`。
- 不负责 ZMQ socket。

`Quest/CameraInfoSource.cs`

- 读取左右 PCA intrinsics。
- 生成 `QuestCameraInfo` Protobuf。
- 低频发布。
- 不负责 ZMQ socket。

`Quest/FramePoseHistory.cs`

- `frame_id -> Pose + sender_mono_ms + unity_frame` 环形缓存。
- v2 论文关键模块之一。
- 后续可扩展记录 capture timestamp、camera velocity、HMD pose。

`Transport/ZmqTopicPublisher.cs`

- 管理 ZMQ PUB socket。
- 发送 multipart `[topic, protobuf_bytes]`。
- 不知道 camera/anchor 语义。

`Client/QuestStreamPublisher.cs`

- MonoBehaviour。
- 持有 `StereoFrameSource`、`CameraInfoSource`、`ZmqTopicPublisher`。
- 按 target fps 调度 stereo/camera_info 发送。
- 对外暴露 link stats。

`Transport/NatsControlClient.cs`

- 管理 NATS 连接。
- request/reply。
- pub/sub。
- 不直接修改 Transform。

`Client/PoseResultReceiver.cs`

- 订阅 `egoanchor.v1.pose.result`。
- 解码 `PoseResult`。
- 主线程派发给 `PoseToAnchorRuntime`。
- 忽略 `has_pose=false` 的 transform 应用，但仍把状态交给 state machine。

`Anchor/CameraPoseFrameAligner.cs`

- 输入 `PoseResult.pose_matrix_cv_camera + frame_id`。
- 从 `FramePoseHistory` 找对应 camera pose。
- 完成 OpenCV camera pose -> Unity camera-local pose -> Unity world raw anchor pose。
- 这是旧 `PoseDecoder + FrameAlignedObjectAnchor` 的 v2 正式化拆分。

`Anchor/PoseToAnchorRuntime.cs`

- 输入 pose observation。
- 调用 `ReliabilityGate`。
- 调用 `AnchorStateMachine`。
- 调用 filter/predictor。
- 输出 stable anchor pose。
- 不负责网络。

`Anchor/DynamicObjectAnchor.cs`

- MonoBehaviour。
- 把 `PoseToAnchorRuntime` 输出应用到 Transform。
- 提供交互系统挂载点。
- 不直接订阅 NATS，不直接解码 Protobuf。

`Reliability/AnchorStateMachine.cs`

- 管理论文中的核心状态：
  - `Uninitialized`
  - `Searching`
  - `Tracking`
  - `Coasting`
  - `FrozenUncertain`
  - `Lost`
  - `Relocalizing`
  - `Paused`
- 定义状态转移和事件。
- 后续实验中可对比 raw pose、simple smoothing、reliability-aware anchoring。

`Reliability/AnchorFilter.cs`

- 先实现简单 low-pass/slerp 或 One Euro。
- 后续替换/扩展 Kalman。
- 不耦合网络。

---

**Unity 可从旧代码迁移的内容**
可参考或迁移：

- `QuestStereoEncoder.cs` 的 texture capture、JPEG 编码、buffer 复用。
- `QuestCameraInfoEncoder.cs` 的 PCA intrinsics 采集。
- `FrameAlignedObjectAnchor.cs` 的 `frame_id -> camera pose` 对齐思想。
- `PoseDecoder.cs` 的 OpenCV camera coordinate 到 Unity coordinate 转换。
- `AnchorProcessor.cs` 的 processor 链思路。
- `AnchorSmoother.cs` 和 `AnchorKalmanFilter.cs` 的滤波思路。
- `PayloadSender.cs` 的多 entry target fps 调度思想。
- `PayloadReceiver.cs` 的主线程派发思想。
- `PcaApiInfoDumper.cs` 作为 diagnostics 工具可继续保留在旧目录或后续复制到 v2 diagnostics。

不建议直接迁移：

- 旧 MessagePack `Msg` 类。
- 旧 `PayloadEncoder/PayloadDecoder` 命名和接口，如果它们暗含 MessagePack。
- 旧 scene 中的 Inspector 绑定。
- 旧 `FrameAlignedObjectAnchor` 作为最终 v2 anchor 类，因为它同时承担了 frame alignment、processor、Transform apply，v2 应拆开以支撑论文状态机。

---

**建议的系统运行图**
v2 推荐架构如下：

```text
Unity Quest
  PassthroughCameraAccess L/R
    |
    v
  StereoFrameSource ----------> FramePoseHistory
    |                               ^
    v                               |
  ZmqTopicPublisher                 |
    |                               |
    | egoanchor.v1.quest.stereo     |
    v                               |
Python ZmqDataPlaneReceiver          |
    |                               |
    v                               |
  TrackingRuntime                   |
    |                               |
    v                               |
  QuestPosePipeline                 |
    |                               |
    v                               |
  PoseObservation + Reliability ----|
    |
    v
  NatsControlPlane
    |
    | egoanchor.v1.pose.result
    v
Unity PoseResultReceiver
    |
    v
  CameraPoseFrameAligner
    |
    v
  PoseToAnchorRuntime
    |
    v
  ReliabilityGate + Filter + StateMachine
    |
    v
  DynamicObjectAnchor Transform
```

---

**迁移策略**
推荐分 6 个阶段推进，保证旧系统不被破坏。

**阶段 0：冻结旧主线**

- `EgoAnchor_Python/src` 只读参考。
- `EgoAnchor_Unity/Assets/Scripts` 只读参考。
- `EgoAnchor_Unity/Assets/Scenes/EgoAnchor.unity` 不动。
- 所有 v2 工作只进入：
  - `EgoAnchor_Python/src_v2`
  - `EgoAnchor_Unity/Assets/Scripts_v2`
  - `EgoAnchor_Unity/Assets/Scene_v2`

**阶段 1：协议与目录骨架**

- 确认 `subjects.v1.json` 是唯一契约。
- 生成 Python/C# Protobuf。
- 建立 v2 目录结构。
- 建立空入口和配置骨架。
- 不实现 demo 算法。

**阶段 2：通信 smoke test**

- Unity v2 发 fake/small `QuestCameraInfo`。
- Python v2 收并打印 subject/protobuf header。
- Python v2 发 heartbeat。
- Unity v2 收 heartbeat。
- 只验证 ZMQ/NATS/Protobuf，不接模型。

**阶段 3：Quest 数据面接入**

- Unity v2 接入 PCA stereo/camera_info。
- Python v2 解码 stereo/camera_info。
- 验证 per-topic latest-drain、frame_id、sender_mono_ms、camera_info version。
- 不跑 FoundationPose。

**阶段 4：Perception Runtime 接入**

- Python v2 迁移 YOLOE/FFS/FoundationPose wrapper。
- 输出 `PoseResult`。
- 不在 Unity 直接裸应用，先只显示 diagnostics。

**阶段 5：Unity Pose-to-Anchor Runtime**

- 实现 `FramePoseHistory`。
- 实现 `CameraPoseFrameAligner`。
- 实现 raw world anchor 输出。
- 加入 basic reliability gate。
- 加入 filter/predictor。
- 加入 anchor state machine。

**阶段 6：实验与替换**

- 对比旧 raw pose、v2 raw pose、v2 filtered anchor、v2 reliability-aware anchor。
- 场景和脚本稳定后，再逐步替换旧主线。
- 替换前保留旧端到端链路作为 fallback。

---

**推荐最小 v2 骨架范围**
你当前说“先不要实现 demo 功能”，因此第一步只需要建立这些概念骨架即可：

Python：

```text
src_v2/app/tracking_server.py
src_v2/config/runtime_config.py
src_v2/protocol/subjects.py
src_v2/transport/zmq_data_plane.py
src_v2/transport/nats_control_plane.py
src_v2/runtime/tracking_runtime.py
src_v2/runtime/command_queue.py
src_v2/perception/quest_pose_pipeline.py
src_v2/perception/pose_observation.py
src_v2/reliability/pose_quality.py
```

Unity：

```text
Assets/Scripts_v2/EgoAnchor/Protocol/SubjectNames.cs
Assets/Scripts_v2/EgoAnchor/Transport/ZmqTopicPublisher.cs
Assets/Scripts_v2/EgoAnchor/Transport/NatsControlClient.cs
Assets/Scripts_v2/EgoAnchor/Quest/FramePoseHistory.cs
Assets/Scripts_v2/EgoAnchor/Quest/StereoFrameSource.cs
Assets/Scripts_v2/EgoAnchor/Quest/CameraInfoSource.cs
Assets/Scripts_v2/EgoAnchor/Client/QuestStreamPublisher.cs
Assets/Scripts_v2/EgoAnchor/Client/PoseResultReceiver.cs
Assets/Scripts_v2/EgoAnchor/Anchor/CameraPoseFrameAligner.cs
Assets/Scripts_v2/EgoAnchor/Anchor/PoseToAnchorRuntime.cs
Assets/Scripts_v2/EgoAnchor/Anchor/DynamicObjectAnchor.cs
Assets/Scripts_v2/EgoAnchor/Anchor/AnchorStateMachine.cs
```

Scene：

```text
Assets/Scene_v2/EgoAnchor_v2.unity
```

---

**最重要的设计原则**
v2 不应把“pose 能传回来并显示”作为最终架构中心。真正的中心应是：

- `frame_id` 对齐。
- capture-time camera pose 回查。
- 相机坐标 pose 到 Unity world anchor 的严格转换。
- reliability score / gate。
- low-rate pose 到 high-rate render 的 filter/predict。
- anchor lifecycle state machine。
- diagnostics 和实验可记录性。

这样重构后，旧系统里的算法能力仍能复用，但论文贡献会落在更有价值的 `Pose-to-Anchor` 系统层，而不是“把几个现成模型接起来”。