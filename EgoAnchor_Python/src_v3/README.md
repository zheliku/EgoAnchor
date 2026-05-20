# EgoAnchor v3 Python 入口

本目录是 v3 新实现的起点。当前包含两个 Python 入口：

- **通信 demo**：只验证 Quest/Unity -> Python 的双目图像通信与实时显示，不加载模型。
- **tracking server**：接收同一条 ZMQ 数据面，运行 YOLOE-26 + Fast-FoundationStereo + FoundationPose/Cutie，在 Python OpenCV 中显示 debug 结果，并可通过 NATS 向 Unity 发布 camera-space `PoseResult`。

## 当前链路

1. Unity v3 `QuestStreamPublisher` 按 topic 发送 Protobuf bytes。
2. 数据面使用 ZMQ PUB/SUB，消息格式固定为 multipart：`[topic_utf8, protobuf_payload_bytes]`。
3. Python v3 `QuestStreamReceiver` 按 topic 做 latest-only 接收与 Protobuf 解码。
4. 通信 demo 只显示左右 JPEG 拼接图；tracking server 继续运行本地 6DoF pose pipeline。
5. tracking server 将 `PoseObservation` 映射为 Protobuf `PoseResult`，通过 NATS subject `egoanchor.v1.pose.result` 发布给 Unity。
6. Unity v3 `PoseResultReceiver` 在主线程解码 `PoseResult`，`PoseToAnchorRuntime` 按 `frame_id` 回查发送帧 left/right/center camera pose，并根据 Unity 本地 `alignmentReference` 生成 raw/stable world anchor pose；`None` 模式可用于不做 frame 对齐的诊断。

## Topics

- stereo：`egoanchor.v1.quest.stereo`
- camera_info：`egoanchor.v1.quest.camera_info`
- pose_result：`egoanchor.v1.pose.result`

以上名称来自 `EgoAnchor_Protocol/subjects.v1.json`，不要在业务代码里手写新字符串。

## Python 运行：通信 demo

在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python .\src_v3\quest_video_stream_demo.py
```

可选参数：

```powershell
pixi run python .\src_v3\quest_video_stream_demo.py --log DEBUG
pixi run python .\src_v3\quest_video_stream_demo.py --config .\path\to\override.toml
```

默认监听端口是 `15557`，配置在 `src_v3/egoanchor/config/defaults.toml`。

## Python 运行：tracking server / pose debug / NATS 发布

在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python .\src_v3\tracking_server.py
```

可选参数：

```powershell
pixi run python .\src_v3\tracking_server.py --log DEBUG
pixi run python .\src_v3\tracking_server.py --config .\path\to\override.toml
```

默认配置会启用 `[network.message_plane]`，并连接 `nats://127.0.0.1:4222` 发布 `PoseResult`。端到端 Unity anchor 测试前，需要先启动本机或开发机上的 `nats-server`，并确保 Unity `NatsControlClient.natsUrl` 指向同一个地址。若只想做 Python-only debug，可在 override TOML 中设置 `network.message_plane.enabled = false`。

OpenCV 热键：

- `1`：只看输入图像。
- `2`：显示 YOLOE mask 相关 debug。
- `3`：显示深度与 mask/depth 对齐质量。
- `4`：完整 pose register/track 可视化。
- `r`：重置 FoundationPose/Cutie 时序状态，下一帧重新 register。
- `q` 或 `ESC`：退出。

## pose debug 主逻辑

当前主逻辑写在 `egoanchor/perception/quest_pose_pipeline.py` 的 `QuestPosePipeline.process()`：

1. `runtime/tracking_runtime.py` 启动 ZMQ receiver，并在 `start()` 阶段预加载 YOLOE、FFS、FoundationPose 和可选 Cutie。
2. 每轮 `TrackingRuntime.tick()` 只取最新 stereo/camera_info，避免旧帧积压。
3. `QuestPosePipeline.process()` 先用 `camera_info` 更新 K；此时只更新 FoundationPose 适配器的相机矩阵，不重建重模型。
4. 未成功 register 前，使用 YOLOE-26 找 cube mask，再结合 FFS 深度调用 FoundationPose `register()`。
5. register 成功后初始化 Cutie。后续正常帧不再要求 YOLOE 每帧检测成功，而是用 Cutie 传播 2D mask，并继续调用 FoundationPose `track()`。
6. 如果 FoundationPose track 失败或 pose 跳变，才使用当前 Cutie mask 尝试 re-register；如果 Cutie 也失效，则回到等待 YOLOE 重新检测的状态。
7. `diagnostics/debug_view.py` 只负责把 stereo、mask、depth、pose 和 HUD 拼成 OpenCV dashboard。

因此，YOLOE 当前主要负责“首次获取/丢失恢复”，Cutie + FoundationPose 负责“连续跟踪”。HUD 中的 `mask_src=yoloe/cutie` 可以区分当前 mask 来源。

## Unity 场景配置：ZMQ 数据面

在 Unity 场景中新增或绑定以下 v3 组件：

1. `EgoAnchor.V3.Quest.FramePoseHistory`
2. `EgoAnchor.V3.Quest.StereoFrameSource`
3. `EgoAnchor.V3.Quest.CameraInfoSource`
4. `EgoAnchor.V3.Client.QuestStreamPublisher`

Inspector 绑定要求：

- `StereoFrameSource`：绑定左右 `PassthroughCameraAccess`，并绑定 `FramePoseHistory`。
- `CameraInfoSource`：绑定左右 `PassthroughCameraAccess`。
- `QuestStreamPublisher`：绑定 `StereoFrameSource` 和 `CameraInfoSource`。
- `QuestStreamPublisher.serverIp`：填运行 Python demo 的开发机 IP；也可通过 `PlayerPrefs` key `EgoAnchor.V3.DataPlaneServerIp` 持久化。
- `QuestStreamPublisher.serverPort`：保持 `15557`。

## Unity 场景配置：NATS PoseResult 与 anchor 显示

在同一场景中继续新增或绑定以下 v3 组件：

1. `EgoAnchor.V3.Transport.NatsControlClient`
2. `EgoAnchor.V3.Anchor.PoseToAnchorRuntime`
3. `EgoAnchor.V3.Client.PoseResultReceiver`
4. 一个或多个 `EgoAnchor.V3.Anchor.DynamicObjectAnchor`
5. 可选：`EgoAnchor.V3.Anchor.AnchorKalmanPoseProcessor` 或 `EgoAnchor.V3.Anchor.AnchorLowPassPoseProcessor`

Inspector 绑定要求：

- `NatsControlClient.natsUrl`：填 `nats-server` 地址，例如开发机本地 `nats://127.0.0.1:4222`，Quest 真机应填开发机局域网 IP；也可通过 `PlayerPrefs` key `EgoAnchor.V3.NatsUrl` 持久化。
- `PoseToAnchorRuntime.framePoseHistory`：必须绑定与 `StereoFrameSource` 相同的 `FramePoseHistory`，否则无法按 `frame_id` 对齐。
- `PoseToAnchorRuntime.processors`：挂入一个或多个 processor。论文对照时，建议 stable 链路挂 `AnchorKalmanPoseProcessor`，raw 链路不挂处理器或由 `DynamicObjectAnchor` 选择 Raw 输出。
- `PoseResultReceiver.natsClient`：绑定 `NatsControlClient`。
- `PoseResultReceiver.anchorRuntime`：绑定 `PoseToAnchorRuntime`。
- `DynamicObjectAnchor.runtime`：绑定 `PoseToAnchorRuntime`。
- `DynamicObjectAnchor.outputMode`：一个物体选 `Raw` 作为不平滑 baseline，另一个物体选 `Smoothed` 作为处理器链输出，用于实时对照。

当前阶段不实现 anchor 状态机：`has_pose=false`、pose 矩阵非法或 `frame_id` 查不到时，只更新诊断并保持上一帧有效 Transform，不触发 Lost/Reacquire 状态。

## 验证要点

- Python 窗口显示等待画面：说明接收端已启动但尚未收到 stereo。
- Python 日志出现 `camera_info version=...`：说明标定 topic 已到达。
- Python 窗口出现左右拼接图：说明 stereo topic、Protobuf 和 JPEG 解码均正常。
- 如果 stereo 收不到但 camera_info 能收到，优先检查 Unity `StereoFrameSource` 的左右 camera 是否 `IsPlaying`。
- pose debug 首次启动会加载 YOLOE、FFS、FoundationPose/Cutie，耗时明显长于通信 demo。
- 若 Unity `NatsControlClient` 没有 connected 日志，先确认 `nats-server` 已启动、URL/IP 可达、防火墙未拦截 4222。
- 若 Unity `PoseResultReceiver` 有 decoded 但 aligned 为 0，优先检查 `PoseToAnchorRuntime.framePoseHistory` 是否与 `StereoFrameSource` 共用同一个实例、`frame_id` 是否被 Python 原样透传，以及 Unity 本地 `alignmentReference/latestUsedReference` 是否需要历史 frame pose。
- 当前 v3 Python 感知 pipeline 使用左目图像、左目 K 和左目 mask/depth，因此 `PoseResult.pose_matrix_cv_camera` 语义上仍是左目 OpenCV camera pose。`PoseToAnchorRuntime.alignmentReference` 是 Unity 本地对齐/诊断策略，不写入通信协议，也不需要服务器知道；Right/Center 可用于本地对照或外参补偿实验，必要时配合 `applyLocalOffset` 做小量残差补偿。
- 若 raw 物体正常但 smoothed 物体不动，检查 `PoseToAnchorRuntime.processors` 中 processor 是否禁用，或 stable `DynamicObjectAnchor.outputMode` 是否选择了 `Smoothed`。
- 如果 dashboard 显示 `WAIT_CALIBRATION`，说明 stereo 已到但 camera_info 尚未到达或未成功解析。
- 如果显示 `NO_MASK`，优先调整 `module.segmenter.prompt/conf/mask_threshold`。
- 如果显示 `REJECT_DEPTH`，优先检查 K 映射、双目同步、baseline、FFS 权重或 TRT engine。

## 设计边界

- `transport` 层不导入 Protobuf、不理解 Quest 业务。
- `runtime` 层解码 Protobuf 并维护 latest-only 输入缓存。
- `diagnostics` 层只负责 OpenCV 显示与 HUD。
- `perception` 层只输出 OpenCV camera 坐标系下的 `PoseObservation`，不做 Unity world transform。
- `algorithms` 层只封装单模型适配器，不直接处理网络或 runtime 命令。
- Python `transport/nats_client.py` 是唯一 NATS transport 文件，只负责 bytes publish/subscribe，不导入 OpenCV 或 perception 重模型。
- Unity `Quest` 目录只负责采集，`Transport` 目录只负责网络，`Client` 目录负责 Protobuf decode 和 runtime 调用，`Anchor` 目录负责 frame alignment、processor chain 和 Transform 输出。