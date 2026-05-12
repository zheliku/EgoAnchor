# AGENTS.md

本文件是项目级 AI 记忆仓库与接手指南。后续 Agent 进入本仓库时优先阅读并维护本文件；不要再新增分散 handoff 文档。

## 项目目标

本项目实现 Quest/VR 场景中的实时 6D 位姿估计与 Unity 可视化：

1. Unity/Quest 采集左右 Passthrough Camera 图像和静态相机信息。
2. Python 服务端接收双目图与相机信息。
3. Python 执行 2D 分割（默认 SAM3，可切 YOLOE）、Fast-FoundationStereo 双目深度、FoundationPose 6D 位姿估计。
4. Python 通过 ZMQ PUB `pose` topic 回传位姿。
5. Unity 解码 pose，按 `frame_id` 对齐发送帧时的左目相机世界姿态，把物体放回 Unity 世界坐标。

当前主线：Unity 多 topic 发送 -> `EgoAnchor_Python/src/pose_server.py` -> Quest Pipeline -> `pose` topic 回传 Unity。RealSense pipeline 仅用于本机算法调试/验证。

## 工程原则

- 协议变更必须 Python/Unity 双端同步：message、encoder、decoder、topic、字段名、契约文件都要一致。
- 网络层统一使用 ZMQ PUB/SUB + multipart `[topic, payload]` + MessagePack payload。
- 多 topic 实时流必须按 topic 分别 latest-drain，不能只保留全局最后一条消息。
- 高频路径日志保持精简，只保留限频告警和必要统计；详细编码/收发统计通过显式开关启用。
- Unity 事件链优先显式 Inspector 绑定，避免组件内部自动 Find/自动 AddListener 导致重复订阅或隐藏依赖。
- Python Quest 主链路运行参数只改 `EgoAnchor_Python/config/runtime.toml`；不要恢复大量 argparse 参数。
- 优先保持端到端链路可运行，再做性能/精度优化。

## 重要入口

在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python .\src\pose_server.py
pixi run python .\src\pose_server.py --config .\config\runtime.toml
pixi run python .\src\pose_server.py --print_config
```

Quest pipeline 单独调试（不回传 Unity）：

```powershell
pixi run python .\src\pipeline\quest_pipeline.py
```

RealSense 本机调试：

```powershell
pixi run python .\src\pipeline\realsense_pipeline.py
```

常用验证：

```powershell
pixi run python -m compileall src/config src/pipeline/quest_pipeline.py src/server/debug_view.py src/pose_server.py src/modules/fast_foundationstereo.py
pixi run python -m unittest src.test.test_runtime_config src.test.test_protocol_contract src.test.test_sam3_masker
dotnet build "Assembly-CSharp.csproj" --no-restore
```

## 运行配置

统一配置文件：`EgoAnchor_Python/config/runtime.toml`。该文件已使用中文行内注释，调参优先直接看此文件。

`pose_server.py` 和 `quest_pipeline.py` CLI 只保留：

- `--config`
- `--print_config`

不要恢复 `--sam3_*`、`--ffs_*`、`--run_stage`、`--local_debug` 等旧运行参数。

当前 TOML 分组：

- `server`：启动 stage、无 pose 状态包、自动 reset。
- `network.receiver`：Unity -> Python 的 stereo/camera_info 接收地址、端口、HWM、timeout。
- `network.sender`：Python -> Unity 的 pose 发布地址、端口、topic、HWM。
- `pipeline.calibration` / `pipeline.depth`：标定缓存、K 映射、处理分辨率、有效深度范围。
- `module.segmenter` / `module.sam3` / `module.yoloe` / `module.ffs` / `module.foundationpose` / `module.cutie`：各算法模块参数。
- `debug`：本地 OpenCV 调试、键盘热键、统计间隔、延迟 EMA、等待日志间隔、mask 快照窗口。

配置加载：

- `EgoAnchor_Python/src/config/runtime_config.py` 使用 stdlib `tomllib`。
- 配置对象为 `SimpleNamespace`，例如 `cfg.module.ffs.use_trt`。
- `CONFIG_SCHEMA` 做嵌套未知 key 校验；新增/移动字段时必须同步：`runtime.toml`、`runtime_config.py`、使用点、`src/test/test_runtime_config.py`。
- 路径字段统一解析为 `EgoAnchor_Python` 项目相对路径。

## Unity 侧关键模块

- `Assets/Scripts/Net/Communicate/PayloadSender.cs`
  - 多 `SenderEntry` PUB 发送器；每个 entry 绑定 `encoder + topic + targetFps`。
  - 默认连接 Python Quest 接收端 `15557`。
- `Assets/Scripts/Net/Communicate/PayloadReceiver.cs`
  - 多 `ReceiverEntry` SUB 接收器；后台线程接收，主线程按 topic 路由 decoder。
  - 以 `_latestByTopic` 做 topic 级 latest-drain。
- `Assets/Scripts/Net/Payload/Encoder/QuestStereoEncoder.cs`
  - 读取左右 PassthroughCameraAccess texture，分别 JPEG 编码。
  - 生成 `QuestStereoMsg`，字段含 `left_image_jpeg/right_image_jpeg/frame_id/sender_mono_ms/unity_frame`。
  - 成功编码后触发 `OnFrameEncoded(frame_id, cameraPose)`，必须在 Inspector 绑定到 `PoseFollow.HandleFrameEncoded(long, Pose)`。
- `Assets/Scripts/Net/Payload/Encoder/QuestCameraInfoEncoder.cs`
  - 低频发送左右相机内参、分辨率、active array、baseline、lens offset、`sender_mono_ms`。
- `Assets/Scripts/Net/Payload/Decoder/PoseDecoder.cs`
  - 解码 Python `PoseMsg`；默认 `convertFromOpenCvCamera=true`，把 OpenCV 相机坐标转 Unity 坐标。
- `Assets/Scripts/Pose/PoseFollow.cs`
  - 缓存发送帧的左 Passthrough camera 世界 pose；用 Python 回包的 `frame_id` 回找该 pose。
  - 不再使用 `sourceTarget` 或运行时 LensOffset 近似相机位姿。
  - `Update()` 中按 `processors` 顺序处理 raw world pose，再应用到 Transform。
- `Assets/Scripts/Pose/PoseProcessor.cs`
  - `Pose` 是 struct，处理器必须返回处理后的 `Pose`，不能依赖 UnityEvent 参数原地修改。

## Python 侧关键模块

- `EgoAnchor_Python/src/pose_server.py`
  - Quest 端到端服务入口：接收 `quest_stereo`、`quest_camera_info`，运行 pipeline，发布 `pose`。
  - 保存/备份 `Calibration/cache/camera_info_latest.json`。
  - 本地 OpenCV debug、键盘控制、延迟/发布统计由 `src/server/` 辅助模块处理。
- `EgoAnchor_Python/src/pipeline/quest_pipeline.py`
  - Quest pipeline：输入 -> 2D 分割 -> FFS 深度 -> FoundationPose register/track。
  - 默认可用 SAM3 异步种子 + Cutie 当前帧传播；YOLOE-26 可作为 fallback/对比。
  - FoundationPose/Cutie 输入使用 RGB；OpenCV/YOLO/debug 显示保留 BGR。
  - register 前检查 mask 内有效深度比例，避免明显 mask/depth 错位时初始化。
  - track 失败或 pose 跳变时，可用当前稳定 2D mask 自动 re-register。
  - `debug.show_mask_snapshot=true` 时，检测到有效 mask 会显示一张单帧 RGB/mask/overlay 对齐快照；按 `r` 或切 stage 后可再次显示。
- `EgoAnchor_Python/src/modules/quest_io.py`
  - Quest 多 topic 接收；公开 `get_stereo_frames()`、`get_camera_info()`、`get_calibration()`、`get_input_state()`。
  - `QuestStereoCalibration.scaled_k()` 负责把 Quest 标定 K 映射到算法处理分辨率。
- `EgoAnchor_Python/src/modules/sam3_masker.py`
  - 同步/异步 SAM3 封装；异步版本后台线程持有 CUDA 模型，忙时丢帧且只保留最新完成结果。
- `EgoAnchor_Python/src/modules/yoloe26.py`
  - YOLOE-26 语义分割 fallback。
- `EgoAnchor_Python/src/modules/fast_foundationstereo.py`
  - FFS 实时深度；支持 PyTorch 与 TensorRT。
- `EgoAnchor_Python/src/modules/foundationpose.py`
  - FoundationPose register、track、visualize 封装。
- `EgoAnchor_Python/src/modules/cutie.py`
  - 可选 2D mask tracker，用于当前帧 mask 传播和可选 bbox 中心辅助修正。
- `EgoAnchor_Python/src/zmq_utils/payload/protocol_contract.json`
  - Python/Unity 协议契约；改 topic、字段或坐标约定时必须同步更新。

## 网络协议

统一约定：

- ZMQ PUB/SUB。
- multipart 固定 `[topic_utf8, payload_bytes]`。
- payload 为单帧 MessagePack bytes。
- 不使用 PUSH/PULL，不使用业务分片，不使用 JSON pose。

Topic：

- `quest_stereo`：Unity -> Python，高频双目 JPEG，`QuestStereoMsg`。
- `quest_camera_info`：Unity -> Python，低频相机静态信息，`QuestCameraInfoMsg`。
- `pose`：Python -> Unity，位姿和状态，`PoseMsg`。

默认端口：

- Unity `PayloadSender` connect -> Python `QuestReceiver` bind：`15557`。
- Python `pose_server.py` bind -> Unity `PayloadReceiver` connect：`15556`。
- 旧端口 `5556/5557` 在 Windows 上可能被 QQ/QQMusic 等占用；不要恢复旧默认端口，也不要添加 Unity legacy PlayerPrefs 自动迁移逻辑。

HWM 经验：

- Quest stereo 帧较大，Python 接收端 HWM 默认 20，避免模型初始化期间队列过小导致 stereo 流断掉。
- Unity stereo 发送端 HWM 不宜过大，过大会增加排队延迟。
- pose 发布端 HWM 可低（默认 1），Unity 只消费最新 pose。

## MessagePack 字段要点

`QuestStereoMsg`：

- `left_image_jpeg`
- `right_image_jpeg`
- `frame_id`
- `sender_mono_ms`
- `unity_frame`

`QuestCameraInfoMsg`：

- `is_supported`
- 左右目 `fx/fy/cx/cy`
- 左右 `distortion`
- `baseline_m`
- `sensor_width/sensor_height`
- `active_left/top/right/bottom`
- 左右 `requested_width/requested_height`
- `current_width/current_height`
- `max_framerate`
- 左右 `lens_offset` position/quaternion
- `sender_mono_ms`

`PoseMsg`：

- `timestamp_ms`
- `frame_id`
- `stage`
- `phase`
- `det_count`
- `depth_valid_ratio`
- `fps`
- `has_pose`
- `pose_matrix_flat`：4x4 行优先展平；无 pose 时为 null/空。
- `yolo_ms/depth_ms/cutie_ms/pose_ms`：兼容字段名；默认 SAM3 路径中 `yolo_ms` 表示 2D segmentation/最新 SAM3 推理耗时。

`server.send_when_no_pose=true` 时，无有效 pose 也发送状态包；Unity `PoseDecoder` 应忽略 `has_pose=false` 的 pose 应用。

## 标定、K 映射与深度

- `pose_server.py` 将收到的 `quest_camera_info` 保存到 `EgoAnchor_Python/Calibration/cache/camera_info_latest.json`。
- 若新旧核心标定不同，旧 latest 备份为 `camera_info_<timestamp>.json`。
- 核心比较排除 `_received_at` 与 `sender_mono_ms`。
- `pipeline.calibration.camera_source="network" + preload_camera_cache=true`：先用缓存预初始化，收到网络标定后校验/刷新。
- `pipeline.calibration.preload_camera_cache=false`：严格等待本次网络 camera_info。
- `pipeline.calibration.assume_center_crop=true`：K 映射使用中心裁剪+缩放；false 为仅线性缩放。
- `quest_pipeline._preprocess_stereo_pair()` 只缩放实际接收图像，不会先扩回 active array 再裁剪。
- 若 pose/深度在图像边缘明显偏，优先对比 `assume_center_crop=true/false`。

FFS/TensorRT：

- TRT artifact tag：`h{height}-w{width}-it{valid_iters}-md{max_disp}`。
- Engine 匹配顺序：显式路径 -> `{runner}-{tag}.{platform}.{precision}.engine` -> `{runner}-{tag}.{platform}.engine` -> `{runner}-{tag}.engine`。
- `module.ffs.trt_strict=true` 时 TRT 不可用直接报错；默认 false 时回退 PyTorch。
- `predict_depth(return_timing=True)` 的 `infer_ms/depth_ms` 是预处理 + forward + 后处理总耗时，不等于纯模型 forward。

## 坐标与位姿应用

Python FoundationPose 输出 OpenCV 相机坐标：

- x 向右。
- y 向下。
- z 向前。

Unity `PoseDecoder.convertFromOpenCvCamera=true` 后转换为 Unity 口径：

- x 向右。
- y 向上。
- z 向前。

Unity 位姿应用链路：

1. `QuestStereoEncoder` 获取左目 texture 后立即读取左目 `GetCameraPose()`。
2. 递增 `frame_id`，触发 `OnFrameEncoded(frame_id, cameraPose)`。
3. Inspector 显式绑定到 `PoseFollow.HandleFrameEncoded(long, Pose)`，缓存发送帧左相机世界 pose。
4. Python 回包携带同一 `frame_id`。
5. `PoseFollow.FollowTarget(pose, frame_id)` 用缓存相机 pose 将相机局部 pose 转 world raw pose。
6. `PoseFollow.Update()` 按 processors 列表处理 raw pose 并应用。

若 Unity 日志出现“未命中发送帧 camera pose 缓存”：检查 Inspector 绑定、`sourceCameraAccess` 是否为左目 PassthroughCameraAccess、`cameraPoseCacheSize` 是否过小、Python 回包 `frame_id` 是否正确透传。

## 调试与排查

OpenCV 热键：

- `1/2/3/4`：切换 stage。
- `r`：重置跟踪状态，下一次有效 mask 可重新 register，并重新显示 mask snapshot。
- `q` / `ESC`：退出。

建议调试顺序：stage 1 看输入 -> stage 2 看 mask -> stage 3 看 depth/mask 对齐 -> stage 4 看 register/track。

关键 HUD/日志字段：

- `stage` / `phase`
- `det` / `det_count`
- `depth_valid` / `depth_valid_ratio`
- `depth_in_mask` / `median` / `iqr`
- `track_reject`
- `sender_est` 看网络延迟趋势；`sender_raw` 是跨进程/设备单调时钟差，不可直接当真实延迟。

常见问题：

- stereo 收不到但 camera_info 能收到：检查 Unity `PayloadSender` 是否有 `quest_stereo` entry、左右 camera 是否 `IsPlaying`、Python `network.receiver.hwm` 是否太小。
- camera_info 收不到：检查 Unity `quest_camera_info` topic、`QuestCameraInfoEncoder` 左右相机引用、Python 订阅 topic。
- Unity 物体位置/朝向错：检查 `PoseDecoder.convertFromOpenCvCamera`、左目 camera pose 缓存命中、`frame_id` 透传、Quest K 映射策略。
- mask 不稳定：调 `module.segmenter.prompt`、`module.segmenter.mask_threshold`、`module.segmenter.max_det`；YOLOE 再调 `module.yoloe.conf`。
- YOLOE 误检/背景 mask：`module.yoloe.conf` 不宜过低；可用 `debug.show_mask_snapshot=true` 查看实际下游 mask。
- depth_in_mask 低：优先查 K 映射、左右图同步/基线、FFS 权重/TRT engine。
- register 失败：先确认 mask 与 depth 对齐，再查 mesh 路径、尺度、对称设置、refine iter。
- 快速移动后 track 丢失：依赖 `module.foundationpose.re_register_on_track_lost=true`；若 2D 辅助带来抖动，可设 `module.cutie.adjust_pose=false`。
- SAM3 异步仍卡顿：后台 SAM3 仍占用同一 GPU；调大 `module.sam3.interval_sec`，并保持 `refresh_when_tracking=false`。

## 环境

Python 环境由 `EgoAnchor_Python/pixi.toml` 管理：

- Python 3.12
- CUDA 12.8
- PyTorch 2.7.x cu128
- TensorRT cu12
- pyrealsense2
- ultralytics/YOLOE
- msgpack、onnx、pillow
- Cutie 以本地 editable path 引入

Windows 注意：若重建 `.pixi/envs/default` 失败，先关闭 VS Code Python LSP、Black Formatter、残留 Python 进程，避免文件占用。

FoundationPose C++ 扩展由 `pixi run build` 中 `_build-fp` 构建；若 FoundationPose 导入报 C++ 扩展缺失，先确认构建成功。

## 关键历史修复与约束

保留这些经验，后续不要回退：

- Unity payload 抽象统一为 `PayloadEncoder.TryEncode(out byte[] payload)` / `PayloadDecoder.HandlePayload(RawPayload payload)`。
- Python payload 抽象统一为 `PayloadEncoder` / `PayloadDecoder`，协议契约记录在 `protocol_contract.json`。
- Unity `QuestStereoMsg` / `QuestCameraInfoMsg` / `PoseMsg` 源码属性可用 PascalCase，但 `[Key("snake_case")]` 是网络协议字段，必须与 Python 和契约一致。
- `QuestReceiver` 提供 `get_input_state()` 等公开诊断接口，上层不要直接访问 `_latest_stereo` 等私有字段。
- `zmq_utils/communicate/sender.py` / `receiver.py` 使用 logging，不要在通用传输层分散 print。
- `has_pose=false` 且 `pose_matrix_flat=None/null` 是合法状态包，不是解码失败。
- SAM3 本地 patch：`sam3/sam3/model/geometry_encoders.py` 应显式创建 CPU tensor 再 `pin_memory()`，避免 FoundationPose 全局 `torch.set_default_tensor_type('torch.cuda.FloatTensor')` 污染导致 bug。
- `Sam3MaskResult.source_image_bgr` 用于保证异步 SAM3 mask 与初始化 Cutie 的 RGB 帧一致，避免 async mask/RGB 错配。
- `AsyncSam3Masker.reset_runtime(min_frame_id=...)` 会清理 stale latest/pending，并拒绝 reset 前 in-flight 旧帧结果；按 `r` 重置后不要用旧 mask register。
- 端口已迁移到 `15557/15556`，不要恢复旧默认 `5556/5557`。
- `.gitignore` 应忽略 `.dotnet/`、Python `__pycache__/`、`*.py[cod]`、`EgoAnchor_Python/Calibration/cache/camera_info_latest.json` 和 `camera_info_*.json`。

## 不要恢复的旧内容

- `src/pose_tracker_api.py`
- `src/vpt_cli.py`
- `src/VOT.py`
- `src/zmq_utils/timing.py`
- `src/zmq_utils/latency.py`
- `src/modules/quest_stereo.py`
- `src/modules/quest_receiver.py`
- `src/quest_stereo_pose_pipeline.py`
- Unity 旧 `StaticStereoEncoder.cs`
- ZMQ PUSH/PULL 模式
- Python `PayloadSender` default topic
- 旧 packed_image_jpeg_legacy 单图协议
- Pose JSON 传输路径
- TRT legacy alias / legacy fallback 文件名
- 运行时 `onnx.yaml` 依赖
- 旧默认端口 `5556/5557`
- Unity `LegacyQuestReceiverPort` / `LegacyPoseServerPort` 兼容迁移逻辑

## 文档维护规则

- 本文件是长期项目记忆入口，保持“核心事实 + 关键历史坑 + 当前约定”。
- 大改后更新入口、模块职责、协议字段、标定策略、坐标、调试统计、常见排查。
- 不要追加流水账式日期日志；若有关键 bug 修复，只保留对后续 Agent 有指导意义的结论。
