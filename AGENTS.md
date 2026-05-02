# AGENTS.md

本文件是项目级 AI 记忆仓库与接手指南。后续 AI/Agent 进入本仓库时，优先阅读并维护本文件；不要再新增分散的 handoff 文档。

## 项目目标

本项目实现 Quest/VR 场景中的实时 6D 位姿估计与 Unity 可视化：

1. Unity/Quest 采集左右 Passthrough Camera 图像和静态相机信息。
2. Python 服务端接收双目图与相机信息。
3. Python 执行 YOLOE 2D 分割、Fast-FoundationStereo 双目深度、FoundationPose 6D 位姿估计。
4. Python 通过 ZMQ PUB topic 回传 pose。
5. Unity 解码 pose，按 `frame_id` 对齐发送帧时的参考节点姿态，把物体放回 Unity 世界坐标。

当前主线是结构化链路：Unity 多 topic 发送 -> `Foundationpose_for_VR/src/pose_server.py` -> Quest Pipeline -> `pose` topic 回传 Unity。RealSense pipeline 仅作为本机调试/算法验证链路。

## 工程原则

- 协议变更必须 Python/Unity 双端同步：message、encoder、decoder、topic、字段名都要一致。
- 网络层统一使用 ZMQ PUB/SUB + multipart `[topic, payload]` + MessagePack payload。
- 多 topic 实时流必须按 topic 分别 latest-drain，不能只保留全局最后一条消息。
- 可观测性要保留：stage、phase、检测数、深度有效率、耗时、FPS、收发统计、延迟趋势。
- Unity 事件链优先显式 Inspector 绑定，避免组件内部再自动 Find/自动 AddListener 造成重复订阅或隐藏依赖。
- 高频路径日志默认保持精简；仅保留限频告警和必要统计，详细编码/收发统计应通过显式开关启用。
- 不要恢复旧入口或旧协议：PUSH/PULL、旧 JSON pose、旧 packed 单图协议、旧 TRT legacy 文件名、运行时 `onnx.yaml` 依赖。
- 优先保持链路可运行，再做性能/精度优化。

## 代码布局

### Unity 侧

- `Assets/Scripts/Net/Communicate/PayloadSender.cs`
  - 多 `SenderEntry` PUB 发送器；每个 entry 绑定 `encoder + topic + targetFps`。
  - 默认向 Python Quest 接收端连接，常用端口 `15557`。
- `Assets/Scripts/Net/Communicate/PayloadReceiver.cs`
  - 多 `ReceiverEntry` SUB 接收器；后台线程接收，主线程按 topic 路由 decoder。
  - latest-drain 以 `_latestByTopic` 保存每个 topic 最新 payload。
- `Assets/Scripts/Net/Payload/Encoder/QuestStereoEncoder.cs`
  - 读取左右 PassthroughCameraAccess 纹理，分别 JPEG 编码。
  - 生成 `QuestStereoMsg`，包含 `left_image_jpeg/right_image_jpeg/frame_id/sender_mono_ms/unity_frame`。
  - 成功编码后触发 `OnFrameEncoded(frame_id)`，供 `PoseFollow` 缓存发送时参考姿态。
- `Assets/Scripts/Net/Payload/Encoder/QuestCameraInfoEncoder.cs`
  - 低频发送左右相机内参、分辨率、active array、baseline、lens offset、`sender_mono_ms`。
- `Assets/Scripts/Net/Payload/Decoder/PoseDecoder.cs`
  - 解码 Python `PoseMsg`；默认 `convertFromOpenCvCamera=true`，把 OpenCV 相机坐标转为 Unity 坐标。
- `Assets/Scripts/Pose/PoseFollow.cs`
  - 消费 `PoseDecoder.OnPoseReceived`。
  - 由 Inspector 将 `QuestStereoEncoder.OnFrameEncoded` 显式绑定到 `HandleFrameEncoded(frame_id)`，不在代码中自动查找或自动订阅 encoder。
  - 用 `frame_id` 查找发送帧缓存的 `sourceTarget` 世界姿态。
  - 将相机/参考系下的局部 pose 转成 world raw pose；`Update()` 每帧按 `processors` 列表顺序调用 `PoseProcessor.Process(...)`，应用最终 processed pose，并触发通知事件。
- `Assets/Scripts/Pose/PoseProcessor.cs`
  - 位姿处理器基类。因为 `Pose` 是 struct，处理器必须显式返回处理后的 `Pose`，不能依赖 UnityEvent 参数被原地修改。
- `Assets/Scripts/Pose/PoseSmoother.cs`
  - `PoseProcessor` 派生的指数平滑处理器；放入 `PoseFollow.processors` 列表后按 Unity `Update()` 频率运行。
- `Assets/Scripts/Pose/PoseKalmanFilter.cs`
  - `PoseProcessor` 派生的卡尔曼滤波处理器；放入 `PoseFollow.processors` 列表后用于抑制静止物体 pose 估计噪声。
- `Assets/Scripts/PcaApiInfoDumper.cs`
  - PassthroughCameraAccess API/相机信息导出与排查工具。
- `Assets/Scripts/CameraViewerManager.cs`
  - 本地 UI 显示左右 Passthrough 相机纹理。

### Python 侧

- `Foundationpose_for_VR/src/pose_server.py`
  - Quest 端到端服务主入口。
  - 接收 `quest_stereo`、`quest_camera_info`，运行 Quest Pipeline，发布 `pose`。
  - 管理 `Calibration/cache/camera_info_latest.json` 缓存与备份。
  - 提供本地 OpenCV 调试窗口、键盘控制、延迟/发布统计。
- `Foundationpose_for_VR/src/pipeline/quest_pipeline.py`
  - Quest 输入完整 pipeline：输入 -> YOLOE -> FFS -> FoundationPose。
  - `camera_source=network` 默认先尝试预加载 camera_info 缓存，再等待网络标定校验/刷新。
  - FoundationPose/Cutie 输入使用 RGB；OpenCV/YOLO/debug 显示保留 BGR。
  - register 前会检查 mask 内有效深度比例，避免 mask/depth 明显错位时直接初始化。
  - FoundationPose track 失败或单帧 pose 跳变时，可用当前稳定 2D mask 自动 re-register（`--re_register_on_track_lost` 默认开启）。
- `Foundationpose_for_VR/src/pipeline/realsense_pipeline.py`
  - RealSense 左右红外本机调试链路。
- `Foundationpose_for_VR/src/modules/quest_io.py`
  - Quest 多 topic 接收模块；对外提供 `QuestReceiver.get_stereo_frames()`、`get_camera_info()`、`get_calibration()`。
  - `QuestStereoCalibration.scaled_k()` 负责把 Quest 标定 K 映射到算法处理分辨率。
- `Foundationpose_for_VR/src/modules/yoloe26.py`
  - YOLOE-26 语义分割封装。
- `Foundationpose_for_VR/src/modules/fast_foundationstereo.py`
  - Fast-FoundationStereo 实时深度封装；支持 PyTorch 与 TensorRT 后端。
- `Foundationpose_for_VR/src/modules/foundationpose.py`
  - FoundationPose 封装；提供 register、track、visualize 等能力。
- `Foundationpose_for_VR/src/modules/cutie.py`
  - 可选 2D mask tracker，辅助后续帧跟踪。
- `Foundationpose_for_VR/src/zmq_utils/communicate/{sender,receiver}.py`
  - 通用 ZMQ PUB/SUB 传输层。
- `Foundationpose_for_VR/src/zmq_utils/payload/message/*.py`
  - MessagePack 消息定义：`QuestStereoMsg`、`QuestCameraInfoMsg`、`PoseMsg`。
- `Foundationpose_for_VR/src/zmq_utils/payload/encoder/*.py` / `decoder/*.py`
  - 业务对象与 MessagePack payload 的转换层。

## 常用入口

在 `Foundationpose_for_VR` 目录运行：

```powershell
pixi run python .\src\pose_server.py
```

常用 Quest 端到端调试：

```powershell
pixi run python .\src\pose_server.py --run_stage 4 --camera_source network --local_debug 1
```

Quest pipeline 示例（不负责 pose 回传 Unity）：

```powershell
pixi run python .\src\pipeline\quest_pipeline.py
```

RealSense 本机调试：

```powershell
pixi run python .\src\pipeline\realsense_pipeline.py
```

pixi 任务：

- `pixi run build`：构建 FoundationPose C++ 扩展、导出 ONNX、构建 TRT engine。
- `pixi run demo-yoloe`：运行 RealSense pipeline 测试 YOLOE/主链路。
- `pixi run demo-pipeline`：运行 `src/pipeline/quest_pipeline.py`。

## Pipeline 阶段与热键

Quest/RealSense pipeline 使用 4 个阶段：

1. stage 1：仅输入图像。
2. stage 2：输入 + YOLOE 2D 分割。
3. stage 3：输入 + YOLOE + Fast-FoundationStereo 深度。
4. stage 4：完整链路，包含 FoundationPose register/track。

OpenCV 调试窗口热键：

- `1/2/3/4`：切换阶段。
- `r`：重置跟踪状态，下一次有效 mask 重新 register。
- `q` 或 `ESC`：退出。

建议调试顺序：先 stage 1 看图像，再 stage 2 看 mask，再 stage 3 看 depth_valid/深度范围，最后 stage 4 看 register/track。

## 网络协议

统一约定：

- ZMQ PUB/SUB。
- multipart 固定为 `[topic_utf8, payload_bytes]`。
- payload 是单帧 MessagePack bytes。
- 不使用 PUSH/PULL，不使用业务分片，不使用 JSON pose。

Topic：

- `quest_stereo`：Unity -> Python，高频双目 JPEG，消息 `QuestStereoMsg`。
- `quest_camera_info`：Unity -> Python，低频相机静态信息，消息 `QuestCameraInfoMsg`。
- `pose`：Python -> Unity，位姿和调试状态，消息 `PoseMsg`。

默认端口/方向：

- Unity `PayloadSender` connect -> Python `QuestReceiver` bind：`15557`。
- Python `pose_server.py` bind -> Unity `PayloadReceiver` connect：`15556`。
- `5556/5557` 是旧默认端口，容易与本机应用冲突；不要恢复为默认值，也不要在 Unity `PayloadSender` / `PayloadReceiver` 中添加 `LegacyQuestReceiverPort`、`LegacyPoseServerPort` 或自动 PlayerPrefs 迁移逻辑。若本地 PlayerPrefs 仍保存旧端口，手动在 Inspector 改为 `15557/15556` 后 `Save Config`。

HWM 经验：

- Quest stereo 帧较大，Python 接收端 `recv_hwm` 默认 20，避免初始化 TRT/FoundationPose 期间队列过小导致 stereo 流断掉。
- Unity stereo 发送端 HWM 不宜过大，过大会增加排队延迟。
- pose 发布端 HWM 可低（默认 1），Unity 只消费最新 pose。

## MessagePack 字段

### `QuestStereoMsg`

Python 定义在 `src/zmq_utils/payload/message/quest_stereo_msg.py`，Unity 定义在 `Assets/Scripts/Net/Payload/Message/QuestStereoMsg.cs`。

字段：

- `left_image_jpeg`: 左目 JPEG bytes。
- `right_image_jpeg`: 右目 JPEG bytes。
- `frame_id`: Unity 发送端递增帧号。
- `sender_mono_ms`: Unity 单调时钟毫秒。
- `unity_frame`: Unity `Time.frameCount`。

### `QuestCameraInfoMsg`

字段包括：

- `is_supported`。
- 左右目 `fx/fy/cx/cy`。
- 左右 `distortion` 数组（Quest 通常为空）。
- `baseline_m`。
- `sensor_width/sensor_height`。
- `active_left/top/right/bottom`。
- 左右 `requested_width/requested_height`。
- `current_width/current_height`。
- `max_framerate`。
- 左右 `lens_offset` 的 position 与 quaternion。
- `sender_mono_ms`。

### `PoseMsg`

字段：

- `timestamp_ms`
- `frame_id`
- `stage`
- `phase`
- `det_count`
- `depth_valid_ratio`
- `fps`
- `has_pose`
- `pose_matrix_flat`：4x4 矩阵行优先展平，16 个数；无 pose 时为 null/空。
- `yolo_ms/depth_ms/cutie_ms/pose_ms`

`pose_server.py --send_when_no_pose 1` 时，无有效位姿也会发送状态包；Unity `PoseDecoder` 会忽略 `has_pose=false` 的包。

## 标定与缓存

- `pose_server.py` 将收到的 `quest_camera_info` 保存到 `Foundationpose_for_VR/Calibration/cache/camera_info_latest.json`。
- 若新旧核心标定不同，旧 latest 会备份为 `camera_info_<timestamp>.json`。
- 比较核心内容时排除 `_received_at` 与 `sender_mono_ms`，因为它们每次接收/发送都会变。
- `QuestReceiver.get_camera_info_version()` 每成功解码一次 camera_info 递增；上层用它判断是否收到新标定。

启动策略：

- `camera_source=network + preload_camera_cache=1`（默认）：先用本地 `camera_info_latest.json` 预初始化 K/FoundationPose，收到网络 camera_info 后校验；若不同且 `network_calib_update=1`，刷新 K/PoseEstimator 并重置跟踪。
- `camera_source=network + preload_camera_cache=0`：严格等待本次网络 camera_info。
- `camera_source=local`：优先读本地缓存；失败后仍等待网络。

K 映射：

- Quest 标定可能来自 sensor/active array 分辨率，算法通常处理 640x480。
- `QuestStereoCalibration.scaled_k(width,height,assume_center_crop=True)` 默认使用中心裁剪 + 缩放映射。
- `--calib_assume_center_crop 0` 改为仅线性缩放。
- `quest_pipeline._preprocess_stereo_pair()` 只缩放实际接收图像，不会先扩回 active array 再裁剪。

## 深度与 TensorRT

`FastFoundationStereoRealtime` 支持：

- PyTorch 后端：加载 `.pth`。
- TensorRT 后端：按输入尺寸、迭代次数、最大视差、平台、精度匹配 engine。

Quest 默认 FFS 权重：`Fast-FoundationStereo/weights/23-36-37/model_best_bp2_serialize.pth`。
RealSense 调试默认权重通常为 `20-30-48/model_best_bp2_serialize.pth`。

TRT artifact 命名：

- tag：`h{height}-w{width}-it{valid_iters}-md{max_disp}`。
- ONNX：`feature_runner-{tag}.onnx`、`post_runner-{tag}.onnx`。
- Engine：`feature_runner-{tag}.{platform}.{precision}.engine`、`post_runner-{tag}.{platform}.{precision}.engine`。

运行时 engine 匹配顺序：

1. 显式传入 engine path。
2. `{runner}-{tag}.{platform}.{precision}.engine`。
3. `{runner}-{tag}.{platform}.engine`。
4. `{runner}-{tag}.engine`。

`--ffs_trt_strict 1` 时 TRT 不可用直接报错；默认 `0` 时缺 engine/初始化失败会回退 PyTorch。

`predict_depth(return_timing=True)` 的 `infer_ms/depth_ms` 是预处理 + forward + 后处理总耗时，不等于纯模型 forward 时间。

## 坐标与位姿应用

Python FoundationPose 输出 OpenCV 相机坐标：

- x 向右。
- y 向下。
- z 向前。

Unity `PoseDecoder.convertFromOpenCvCamera=true` 时转换为 Unity 常用口径：

- x 向右。
- y 向上。
- z 向前。

Unity 不直接把 Python pose 设置到物体，而是：

1. `QuestStereoEncoder` 成功编码 stereo 后递增 `frame_id` 并触发 `OnFrameEncoded(frame_id)`。
2. Inspector 中把 `OnFrameEncoded(frame_id)` 绑定到 `PoseFollow.HandleFrameEncoded(frame_id)`，缓存此时 `sourceTarget` 的世界 pose。
3. Python 回包带同一个 `frame_id`。
4. `PoseFollow.FollowTarget(pose, frame_id)` 查找发送帧参考 pose。
5. 可选组合左相机 `Intrinsics.LensOffset`，再使用参考 pose 将相机局部 pose 转到 world raw pose。
6. `Update()` 每帧先触发 `OnBeforePoseApply` 通知，再按 `PoseFollow.processors` 列表顺序处理 raw pose（例如 `PoseSmoother` 或 `PoseKalmanFilter`），随后应用 processed pose 并触发 `OnAfterPoseApply`。

若 Unity 日志出现“未命中发送帧缓存”：检查 `QuestStereoEncoder.OnFrameEncoded` 是否已在 Inspector 绑定到 `PoseFollow.HandleFrameEncoded`、`sourceTarget` 是否为空、`sourceTargetCacheSize` 是否过小、Python 回包 `frame_id` 是否正确传递。

## 调试统计口径

Pipeline HUD/日志常见字段：

- `fps` / `rt_fps` / `window_fps`：实时或窗口 FPS。
- `stage` / `phase`。
- `det` / `det_count`。
- `depth_valid` / `depth_valid_ratio`。
- `yolo/depth/cutie/pose` 分阶段耗时。
- `mask` / `depth_in_mask` / `median` / `iqr`：FoundationPose 输入对齐诊断，在 `PoseServer Debug` 的 depth+mask 面板中查看。
- `track_reject`：FoundationPose track 被非法 pose/跳变过滤拒绝的连续计数；若随快速运动上升但 mask/depth 仍稳定，说明 6D track 丢失后依赖 re-register 恢复。

Quest 接收统计还包括：

- `recv`
- `decode_fail`
- `sender_fps`
- `sender_est`
- `sender_raw`
- `sender_gap`

`sender_raw` 是跨进程/跨设备单调时钟差，不能直接解释为真实网络延迟；优先看 `sender_est` 与趋势。

`pose_server.py` 额外统计：

- `quest_rx->unity_tx`：从 Quest 帧接收到 Python 发出 pose 的估计总耗时。
- `run`：一次 pipeline.run 总耗时。
- `wait`：粗略等待/取帧耗时。
- `proc`：算法耗时合计。
- `send`：ZMQ 发送耗时。
- `pose_ratio`：有效 pose 输出比例。
- `drop`：pose 发布失败比例。

`pose_server.py --local_debug 1` 显示两个窗口：`PoseServer Debug`（pose/2D box + depth+mask，启动后置顶）与 `PoseServer Stereo`（保持左右拼接比例的 stereo），并叠加 FPS、阶段耗时、mask/depth 质量和发布延迟摘要。

稳定性排查建议：

- 若 `depth_in_mask` 很低或 dashboard 的 depth+mask 面板中 mask 覆盖区域深度明显错位，优先检查 Quest K 映射、双目 rectification/左右图同步与 FFS 深度。
- 若初始 mask 框住了多个目标或背景，优先调 `--yolo_prompt`、`--yolo_conf`、`--yolo_mask_threshold`，并保持 `--yolo_max_det 1` 或确认单目标选择策略。
- `--cutie_adjust_pose` 默认启用（默认值 `1`）；若确认 Cutie bbox 中心抖动会注入 FoundationPose 的 tx/ty，可显式传 `--cutie_adjust_pose 0` 关闭。
- 快速移动后若 mask/Cutie bbox 仍稳定但 pose 丢失，可先保留 `--cutie_adjust_pose 1` 并依赖 `--re_register_on_track_lost 1` 用当前 mask 恢复；若 2D 辅助带来明显抖动，再改用 `--cutie_adjust_pose 0`，必要时调大 `--pose_jump_translation_m`、`--pose_jump_rotation_deg` 或提高 `--track_refine_iter`。

## 环境

Python 环境由 `Foundationpose_for_VR/pixi.toml` 管理：

- Python 3.12。
- CUDA 12.8。
- PyTorch 2.7.x cu128。
- TensorRT cu12。
- pyrealsense2。
- ultralytics/YOLOE。
- msgpack、onnx、pillow。
- Cutie 以本地 editable path 引入。

Windows 注意：若重建 `.pixi/envs/default` 失败，先关闭 VS Code Python LSP、Black Formatter、残留 Python 进程，避免文件占用。

FoundationPose C++ 扩展由 `pixi run build` 中 `_build-fp` 构建；若 FoundationPose 导入报 C++ 扩展缺失，先确认该构建成功。

## 常见排查

- stereo 收不到但 camera_info 能收到：检查 Unity `PayloadSender` 是否有 `quest_stereo` entry；`QuestStereoEncoder` 左右相机是否 `IsPlaying`；Python `recv_hwm` 是否太小。
- camera_info 收不到：检查 Unity `quest_camera_info` topic；`QuestCameraInfoEncoder` 左右相机引用；Python 订阅 topics。
- Unity 物体位置/朝向明显错：检查 `PoseDecoder.convertFromOpenCvCamera`、`PoseFollow.sourceTarget`、`frame_id` 缓存命中、Quest K 映射策略。
- stage 2 mask 不稳定：优先调 `--yolo_prompt`、`--yolo_conf`、`--yolo_max_det`、光照/目标可见性。
- stage 3 depth_valid 低：检查左右图同步/基线/内参映射、`min_depth/max_depth`、FFS 权重与 TRT engine 是否匹配。
- stage 4 register 失败：先确认 mask 与 depth 正确，再看 mesh 路径、对称设置、FoundationPose refine iter。
- TRT 不生效：检查 engine 文件名是否带完整 tag、平台、精度；必要时用 `--ffs_trt_strict 1` 强制暴露错误。
- 启动后长时间无 pose：确认 `camera_info_latest.json` 是否存在或加 `--preload_camera_cache 0` 验证网络标定；观察 stage/phase、det、depth_valid。

## 不要恢复的旧内容

以下旧入口或旧协议路径不要恢复：

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

- 本文件是长期项目记忆入口。
- 大改后至少更新：入口、模块职责、协议字段、标定策略、位姿坐标、调试统计、常见排查。
- 删除或迁移旧文档后，不要再引用旧 handoff 文件。

## 2026-04 架构收敛更新

- Unity payload 抽象命名已统一为 `PayloadEncoder` / `PayloadDecoder`：
  - Encoder 方法为 `TryEncode(out byte[] payload)`。
  - Decoder 方法为 `HandlePayload(RawPayload payload)`。
  - `PayloadSender` / `PayloadReceiver` 的 Inspector 配置方式不变，`VInspector`、`RuntimeInspector`、`Proxima` 调试按钮继续保留。
- Python payload 抽象命名已统一：
  - `zmq_utils/payload/encoder/payload_encoder.py` 定义 `PayloadEncoder`。
  - `zmq_utils/payload/decoder/payload_decoder.py` 定义 `PayloadDecoder`。
- 协议契约新增到 `Foundationpose_for_VR/src/zmq_utils/payload/protocol_contract.json`，用于记录 topic、端口方向、MessagePack 字段与坐标约定。
- Unity `QuestStereoMsg` / `QuestCameraInfoMsg` / `PoseMsg` 源码成员使用 C# PascalCase 属性；`[Key("snake_case")]` 中的字段名才是网络协议字段，必须继续与 Python message 和 `protocol_contract.json` 保持一致。
- `pose_server.py` 保持主入口职责，辅助逻辑拆到 `Foundationpose_for_VR/src/server/`：
  - `camera_info_cache.py`：camera_info latest 保存、核心字段比较、旧版本备份。
  - `debug_view.py`：OpenCV debug 窗口、等待占位图、HUD 文本绘制。
  - `runtime_stats.py`：发布计数、pose/drop 比例、EMA 延迟统计。
  - `keyboard_control.py`：本地调试热键处理。
- Python 协议测试新增 `Foundationpose_for_VR/src/test/test_protocol_contract.py`，覆盖 message 字段契约、PoseEncoder/PoseDecoder 回环和 receiver 多 topic latest-drain。

## 2026-04 可读性与提交卫生更新

- `QuestReceiver` 提供公开诊断接口：
  - `has_stereo_frame()`：判断是否已成功解码过 stereo 帧。
  - `get_input_state()`：返回 `QuestInputState` 快照，用于 `pose_server.py` 等待阶段输出 camera_info/stereo/解码计数等诊断。
  - 上层不应再直接访问 `pipeline.camera._latest_stereo` 等私有缓存字段。
- `server/keyboard_control.py` 使用 `KeyboardControllablePipeline` Protocol 描述热键所需的最小 pipeline 能力，避免用 `object` 隐藏依赖。
- `zmq_utils/communicate/sender.py` 与 `receiver.py` 的连接/关闭输出改为 `logging.info/debug`，不再在通用传输层分散使用 `print`。
- Unity `PayloadSender` / `PayloadReceiver` 注释补充了传输层边界、PUB/SUB multipart 协议、HWM 延迟取舍、latest-drain 策略、后台收包线程到主线程 decoder 分发的线程模型。
- Unity `PayloadEncoder` / `PayloadDecoder` 注释说明了与 Python `PayloadEncoder` / `PayloadDecoder` 的对称关系。
- `PoseEncoder` / `PoseDecoder` 注释明确：
  - `frame_id` 必须从 `QuestStereoMsg` 传递到 `PoseMsg`，用于 Unity 回找发送帧参考姿态。
  - `has_pose=false` 且 `pose_matrix_flat=None/null` 是合法状态包，不是解码失败。
- `Foundationpose_for_VR/src/zmq_utils/payload/README.md` 记录 `protocol_contract.json` 的维护规则，因为 JSON 本身不支持注释。
- `.gitignore` 补充运行/验证产物规则：
  - `.dotnet/` 为外部 dotnet 验证生成的临时目录，不应提交。
  - Python `__pycache__/`、`*.py[cod]` 不应提交。
  - `Foundationpose_for_VR/Calibration/cache/camera_info_latest.json` 和 `camera_info_*.json` 属于运行时标定缓存/备份，默认不作为源码改动提交。
- 本轮验证命令：
  - `pixi run python -m compileall src/pose_server.py src/server src/zmq_utils/payload src/modules/quest_io.py`
  - `pixi run python -m unittest src.test.test_protocol_contract`

## 2026-05 端口避让更新

- Python/Unity 主链路默认端口已从 `5557/5556` 迁移到 `15557/15556`：
  - Unity `PayloadSender` -> Python `QuestReceiver`：`15557`。
  - Python `pose_server.py` -> Unity `PayloadReceiver`：`15556`。
- 旧端口 `5556/5557` 在 Windows 本机上可能被 QQ/QQMusic 等本地 IPC 占用，导致 ZMQ `Address in use`。
- Unity 侧不保留旧端口兼容：`PayloadSender` / `PayloadReceiver` 只保留当前默认端口常量，不再维护 `LegacyQuestReceiverPort`、`LegacyPoseServerPort` 或自动 PlayerPrefs 迁移。
- 若 Unity PlayerPrefs 曾保存旧端口，后续 Agent 不要通过兼容代码修复；应在 Inspector 或运行时调试面板中手动设置新端口并执行 `Save Config`。
- 端口协议变更必须同步更新 `pose_server.py`、`quest_pipeline.py` / `quest_io.py`、Unity Sender/Receiver 默认值、场景序列化端口、`protocol_contract.json` 和本文件。
