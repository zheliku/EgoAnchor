# EgoAnchor v3 通信 Demo

本目录是 v3 新实现的起点。当前只实现 **Quest/Unity -> Python 的双目图像通信与实时显示**，不加载模型、不发布 pose、不接入 NATS。

## 当前链路

1. Unity v3 `QuestStreamPublisher` 按 topic 发送 Protobuf bytes。
2. 数据面使用 ZMQ PUB/SUB，消息格式固定为 multipart：`[topic_utf8, protobuf_payload_bytes]`。
3. Python v3 `QuestStreamReceiver` 按 topic 做 latest-only 接收与 Protobuf 解码。
4. Python OpenCV 窗口实时显示左右 JPEG 拼接图。

## Topics

- stereo：`egoanchor.v1.quest.stereo`
- camera_info：`egoanchor.v1.quest.camera_info`

以上名称来自 `EgoAnchor_Protocol/subjects.v1.json`，不要在业务代码里手写新字符串。

## Python 运行

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

## Unity 场景配置

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

## 验证要点

- Python 窗口显示等待画面：说明接收端已启动但尚未收到 stereo。
- Python 日志出现 `camera_info version=...`：说明标定 topic 已到达。
- Python 窗口出现左右拼接图：说明 stereo topic、Protobuf 和 JPEG 解码均正常。
- 如果 stereo 收不到但 camera_info 能收到，优先检查 Unity `StereoFrameSource` 的左右 camera 是否 `IsPlaying`。

## 设计边界

- `transport` 层不导入 Protobuf、不理解 Quest 业务。
- `runtime` 层解码 Protobuf 并维护 latest-only 输入缓存。
- `diagnostics` 层只负责 OpenCV 显示与 HUD。
- Unity `Quest` 目录只负责采集，`Transport` 目录只负责网络，`Client` 目录负责组合发送。