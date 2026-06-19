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
10. 每次操作完后记得更新AGENTS.md

<!-- USER-MAINTAINED-REQUIREMENTS:END -->
本文件是 EgoAnchor 的项目级接手指南。只记录长期有效的事实、约定、路线和历史坑；不要追加流水账。顶部 `USER-MAINTAINED-REQUIREMENTS` 区块由用户维护，除非用户明确要求，后续 AI 不得改动其中任何文字。

## 当前定位

EgoAnchor 面向 passthrough mixed reality，把异步 6DoF object pose stream 转成稳定、世界一致、可恢复的 real-object anchor。论文目标是 IEEE VR 2027，叙事核心是 pose-to-anchor / frame-aligned anchoring，不是普通 pose tracking 工程。

主线结构：

- Python：`EgoAnchor_Python/src`，负责 Quest stereo/camera_info 接收、目标分割、FFS/FoundationPose/Cutie、可靠性评分、NATS pose/status/heartbeat/command。
- Unity：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor`，负责 Quest 采集、frame pose history、camera-space pose 到 Unity world anchor、policy 输出和可视化运行时。
- Protocol：`EgoAnchor_Protocol`，唯一 proto 和 subject 源；生成脚本同步 Python/Unity 输出。
- Evaluation：`EgoAnchor_Tools3` 是当前主用离线升采样仿真工具；旧 `EgoAnchor_Tools` / `EgoAnchor_Tools2` 的同类项目不再作为主线验证依据。
- Paper：`2026-EgoAnchor` 放论文材料，写法必须保守，不能把未实现或未验证的机制写成已完成贡献。

## 核心架构

EgoAnchor 固定采用双平面/三语义通道：

| 平面 | 传输 | 方向 | 数据 | 策略 |
| --- | --- | --- | --- | --- |
| Data Plane | ZMQ PUB/SUB | Unity -> Python | `QuestStereoFrame`、`QuestCameraInfo` | Protobuf bytes，multipart `[topic_utf8, payload]`，topic latest-drain |
| Message Plane | NATS Core pub/sub | Python -> Unity | `PoseResult`、`AnchorStatusEvent`、`ServerHeartbeat` | pose/heartbeat latest-only，status event stream |
| Command Plane | NATS request/reply | Unity -> Python | reset / reacquire / control | `request_id` 幂等，快速 ack，runtime 串行执行 |

关键约束：

- Python 不输出 Unity world pose；Unity 必须用 `frame_id` 回查 capture-time camera pose 做 world anchor。
- 不使用 pose 到达时 HMD pose 代替发送帧 pose，这是项目核心历史坑。
- 高频日志保持精简；详细收发、编码、mask/depth 统计必须通过显式 debug 开关启用。
- 业务代码不手写 subject 字符串；Python 从 `egoanchor.protocol` 包级入口导入，Unity 用 `SubjectNames`。
- 共享 proto 字段号不得重排。删除字段必须在 proto 中 `reserved` 字段号和字段名。

## 项目级实现要求

- 生成代码不要手改。Python `*_pb2.py` 内部 import 是协议生成结果，不受“包外只走包级入口”的约束影响。
- Unity 新增 Inspector 字段、网络参数、坐标语义和时间语义时，说明写在 XML summary 或 `[Tooltip]`。参数能少则少，但不要靠 `[HideInInspector]` 隐藏仍在生效、仍需调参的字段来解决 Inspector 过载；需要收纳时应先考虑拆组件、分组、profile 或自定义 Inspector。
- 日志统一走门面：Python 用 `egoanchor.utils.get_logger(...)` 和入口 `configure_logging(...)`；Unity 用 `EgoAnchorLog.For<T>()`。日志消息不要手写 `[ClassName]` 前缀。
- 新增行为先补测试或 smoke 验证。配置、文档、生成代码可以不补测试，但最终必须给出可复现验证命令。
- 重构不做旧接口、旧字段、旧路径兼容。若字段重命名，直接迁移当前场景 YAML 和文档，不加 `FormerlySerializedAs`。
- 修改前先查引用关系和场景序列化影响。Unity 私有 `[SerializeField]` 改名会影响 `.unity` / `.prefab` YAML；Python 配置项改名会影响 `.toml`、加载器、使用点和测试。

## 常用验证

Python 侧在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python .\src\tracking_server.py
pixi run tool-yoloe26-mask
pixi run tool-sam3-mask
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python -m unittest discover -s eval -p "test_*.py"
```

Unity 主线编译在仓库根目录运行：

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

协议生成在 `EgoAnchor_Python` 目录运行，使用 pixi 环境中的 `protoc`：

```powershell
pixi run pwsh -File ..\EgoAnchor_Protocol\tools\generate_proto.ps1
```

离线升采样仿真：

```powershell
dotnet run --project EgoAnchor_Tools3\AnchorUpsampleSim3.csproj -c Release -- --session EgoAnchor_Python\data\eval\<session> --zoom-start 8 --zoom-end 13
```

`pixi run build` 会构建 FoundationPose C++ 扩展并生成 FFS ONNX/TRT artifacts，耗时且依赖 CUDA/TensorRT；不要当作轻量验证命令。

## Python 主线

- 入口：`EgoAnchor_Python/src/tracking_server.py` 调 `egoanchor.app.tracking_server`。
- 配置：`src/egoanchor/config/defaults.toml` 和 `objects.toml`；每个 `.toml` 参数必须同行中文注释。
- 分割：默认 `module.segmenter.type="yoloe26"`；SAM3 只能显式配置启用，不能改成默认。
- reliability：`render_quality.enabled=true` 默认采集信号，但 `mode="score_only"` 保持 shadow mode；无有效 reprojection/depth 信号不得触发重注册。
- logging：`runtime.logging.eval_session_enabled=true` 时创建 `data/eval/<session_id>/`，PoseResult 的 `header.session_id` 供 Unity 本地建同名目录配对。
- 时间：人类可读 session_id 用北京时间 UTC+8；单调钟和 UTC epoch 不受时区影响。
- command path：`NatsMessageClient -> NatsRouter -> HandlerRegistry -> CommandDedupStore/CommandQueue -> TrackingRuntime`。NATS handler 只能 parse/validate/dedup/enqueue/ack，pipeline/GPU 状态由单一 `TrackingRuntime` 顺序拥有。

Python 代码地图：

- `src/egoanchor/config/`：只读 TOML，不导入 ZMQ/OpenCV/模型。新增配置要同步 defaults、objects 覆盖、加载点、使用点和测试。
- `src/egoanchor/protocol/`：subject registry、protobuf registry、包级 Protobuf 入口；运行时 `subjects.v1.json` 副本由协议脚本同步。
- `src/egoanchor/transport/zmq_topic_subscriber.py`：通用 ZMQ SUB，只管 socket、multipart topic bytes、latest-drain。
- `src/egoanchor/transport/nats_client.py`：唯一 NATS transport，负责 asyncio NATS 连接、bytes publish/subscribe/request-reply callback 和限流。
- `src/egoanchor/routing/`：subject -> protobuf parse -> handler -> reply serialize。
- `src/egoanchor/handlers/command_handlers.py`：reset/reacquire/control 只 validate/dedup/enqueue/ack，不碰 pipeline/GPU。
- `src/egoanchor/runtime/quest_stream_receiver.py`：ZMQ bytes -> Quest Protobuf -> latest store，含 per-topic latest cache、frame_id/session 去重、camera_info version 和输入统计。
- `src/egoanchor/runtime/tracking_runtime.py`：唯一 pipeline/GPU 状态 owner；poll Quest stream latest、运行 perception、发布 PoseResult/status/heartbeat，并顺序 pump command。
- `src/egoanchor/runtime/message_factories.py`：`PoseObservation -> PoseResult`、runtime state/command/error -> `AnchorStatusEvent`、input/runtime stats -> `ServerHeartbeat`。
- `src/egoanchor/runtime/runtime_log_writer.py`：集中写 PoseResult/status/heartbeat/command JSONL。
- `src/egoanchor/perception/quest_pose_pipeline.py`：组合 YOLOE-26/SAM3、FFS、FoundationPose/Cutie，输出 camera-space `PoseObservation` 和 debug 图，不依赖 ZMQ/NATS/Unity transform。
- `src/egoanchor/perception/quest_calibration.py`：Quest camera_info 到算法处理分辨率 K 的映射，支持 center-crop 和线性缩放。
- `src/egoanchor/algorithms/`：单模型适配层。`yoloe26_segmenter.py`、`sam3_segmenter.py` 都输出统一 `SegmenterResult`；pipeline 不理解模型内部细节。
- `src/egoanchor/algorithms/foundationpose_estimator.py`：FoundationPose facade，可靠性层只能通过 `render_color_depth_mask(...)`，不要直接访问第三方 estimator 内部对象。
- `src/egoanchor/reliability/`：`reprojection.py` 只做交集区域 LAB 颜色重投影；`depth_alignment.py` 只做渲染 depth 与 FFS depth 对齐；`render_quality.py` 负责一次渲染后协调两者；`pose_quality.py` 合成总可靠性分。

Python 细节坑：

- SAM3 异步只异步初始分割。worker 输出必须携带同一帧 left/right RGB 和 mask，主 pipeline 再做 FFS/FoundationPose，避免 RGB/mask 错帧。
- `render_quality.mode="score_only"` 时只能采集和写分数；不要在没有足够证据前切到 `re_register`。
- `color_reprojection=-1` 表示本帧无有效颜色重投影信号，不是坏 pose。无效原因可能是 warmup、无 Cutie mask、渲染面积太小或 K 缺失。
- depth 覆盖不足时 `score_depth=0.5` 是中性显示，不进入几何合取核。
- `network.message_plane.enabled=false` 可用于 Python-only debug，避免没有 NATS server 时阻塞模型调试。

## Unity 主线

主要链路：

`QuestStreamPublisher / StereoFrameSource / CameraInfoSource` 采集并发 ZMQ；`FramePoseHistory` 记录 capture-time camera pose；`PoseResultReceiver -> AnchorRuntimeHub -> PoseToAnchorRuntime` 解码并广播 pose；`CameraPoseFrameAligner` 做 OpenCV camera pose 到 Unity world pose；`AnchorPolicyHost` 输出每帧 anchor pose；`DynamicObjectAnchor` 只应用输出 Transform。

Unity policy 当前结构：

- `AnchorPolicyHost` 持有 `MotionModel` + `SmoothingStrategy`，维护生命周期和可选 score gate。
- `Policy/Models`：`ConstantVelocityModel`、`KalmanModel`、`OneEuroModel`。
- `Policy/Smoothing`：`BlendStrategy`、`DelayedInterpStrategy`、`RawPassthroughStrategy`。
- `Policy/Contracts`：`AnchorObservation`、`AnchorPolicyDecision`、`AnchorPolicyOutput`、`GateDecision`。
- `Policy/Lifecycle`：`AnchorStateMachine`、`AnchorPolicyTypes`。
- `Policy/Math`：`AnchorMath`、`ConstVelocityKalman`、`ScalarOneEuro`、`Spline`。
- `EgoAnchorStaticLockModule` 是静止锁 MonoBehaviour 参数宿主；`StaticLockController` 是纯 C# 控制器。静止锁与 model × strategy 正交：挂模块并 `lockEnabled=true` 是 EgoAnchor 方法，不挂或关闭是 baseline。

Unity 代码地图：

- `Protocol/Generated/` 和 `SubjectNames.cs`：协议生成输出，不要手改。
- `Transport/ZmqTopicPublisher.cs`：只管理 NetMQ PUB socket，发送 `[topic_utf8, protobuf_payload_bytes]`。
- `Client/NatsControlClient.cs`：NATS 消息面客户端，订阅 PoseResult latest queue、AnchorStatusEvent event queue、ServerHeartbeat latest queue，并提供 bytes request/reply；后台回调不改 Transform。
- `Quest/StereoFrameSource.cs`：读取左右 Passthrough texture，记录 left/right/center camera pose，JPEG 编码，构造 `QuestStereoFrame`。
- `Quest/CameraInfoSource.cs`：读取 Quest intrinsics/lens pose 并构造 `QuestCameraInfo`。
- `Alignment/FramePoseHistory.cs`：`frame_id -> capture-time left/right/center camera world pose` 环形缓存，是 frame-aligned anchor 的关键。
- `Alignment/CameraReference.cs`：Python 当前 pose 语义默认左目 OpenCV camera；Right/Center/None 只用于本地诊断、对照或补偿实验。
- `Alignment/CameraPoseFrameAligner.cs`：OpenCV camera pose + frame history -> Unity world pose，包含轴翻转和 offset 配置。
- `Client/PoseResultReceiver.cs`：主线程 latest-drain，解析 PoseResult，交给 `AnchorRuntimeHub`。
- `Runtime/AnchorRuntimeHub.cs`：pose/status/heartbeat fan-out 给多个 runtime；低分 reacquire fan-in 也在这里合并发出。
- `Runtime/PoseToAnchorRuntime.cs`：把 camera-space pose 对齐为 Unity world pose，提交给 policy，每帧 `LateUpdate(-50)` 推进输出。
- `Runtime/DynamicObjectAnchor.cs`：只读 `TryGetOutputPose` 并应用 Transform，不承载滤波、状态机、网络或 recovery。
- `EgoAnchorEval/AnchorEvalRecorder.cs`：按 capture/render 两条日志写 JSONL；配置摘要通过反射收集 `[SerializeField]` 字段，隐藏字段也会进入 config hash。

静止锁命名约定：

- 在 `EgoAnchorStaticLockModule` 内字段名不再重复 `staticLock` 前缀，例如 `unlockDriftMeters`、`headSettleSeconds`、`lowScoreReleaseScore`。
- 不使用 `FormerlySerializedAs` 兼容旧字段名；场景 YAML 直接迁移到新 key。
- 静止锁所有仍参与控制逻辑的参数应保持可见，便于真机调参和复现实验。不要用 `[HideInInspector]` 把正在生效的调参字段藏起来；若后续要减少 Inspector 压力，应做自定义 Inspector foldout、profile 或进一步拆分参数宿主。
- `LatestStaticLocked`、`motion_model`、`smoothing_strategy`、`gate`、`has_output_pose`、`output_pos`、`output_rot` 是当前 eval/runtime 契约，不要改回旧名。

静止锁核心机制：

- `OnObservation` 只在 host 接受观测后调用；它更新 obs-to-obs 速度、头动容忍、观测共识、锁定/解锁证据。
- `Stabilize(candidate, dt)` 每渲染帧调用。锁定时返回 `lockedPose`；解锁后用 seam residual 从锁点平滑回到 smoothing 输出；未锁定时透传 candidate。
- 进入锁定看 `enterSpeedMps`、`enterAngSpeedDps`、`dwellSeconds`、`minScore`。这些阈值必须高于真实观测噪声地板，尤其角速度阈值太低会永不锁定。
- 解锁证据有三路：速度逃逸、漂移租绳、CUSUM。三路都按真实 dt 处理，不绑定帧率。
- 漂移租绳量的是 `distance(obsConsensus, anchorOrigin)`，不是单帧观测，也不是 creep 后的 `lockedPose`。改回 `lockedPose` 会导致慢速持续移动时永不解锁。
- `obsConsensus` 是死区无关的低增益 EMA，用来平滑单帧噪声/head-slip，同时跟随真实持续位移。
- 头动容忍系数 `headToleranceFactor=1+ratio*(headMaxToleranceFactor-1)`，同比放大死区、租绳和速度逃逸阈值。
- creep 增益乘 `(1 - headMotionRatio)`。头动时不能让系统性 head-slip 偏置被 creep 写进锁点。
- `headSettleSeconds` **只在头已停下、但沉降计时未走完的窗口内**冻结“判物体在动”的证据（速度逃逸/CUSUM/租绳，并清零三者累积）。它修的是“头扫静止物体、头一停就脱离 static”的时序竞速（头停瞬间 `headToleranceFactor` 塌回但 slip 还残留在 `obsConsensus`/速度里）。**头动期间绝不冻结**——那会把头动中物体的大幅真动也锁死；头动时只靠 `headToleranceFactor` 抬高阈值吸收 slip（slip 小幅、真动大幅，靠阈值区分）。计时在 `OnObservation` 维护：`headMotionRatio>0.06` 重置满、否则按 obsDt 递减；冻结判据是 `headMotionRatio<=0.06 && 计时>0`。
- 距离自适应只放大位置通道，不放大旋转通道。远距离立体深度噪声更大，但旋转噪声不按距离同样变化。
- 低分释放不受 head settle 冻结影响。它表示锁点可靠性差，应该强制释放并交给低分 reacquire 链路。

低分/track-loss 自动 reacquire：`AnchorPolicyHost` 只置 `wantsServerReacquire`；`PoseToAnchorRuntime.ConsumeServerReacquireRequest()` 透传；`AnchorRuntimeHub` 统一 fan-in，并用唯一 `reacquireCommandClient` 发 NATS reacquire。不要让 leaf runtime 或 policy 自持 command client。

Unity/eval 字段契约：

- C# 属性 `MotionModelName` / `SmoothingStrategyName` / `GateName` 对应 JSONL `motion_model` / `smoothing_strategy` / `gate`。
- 每帧输出字段是 `has_output_pose` / `output_pos` / `output_rot`。不要恢复旧 `has_stable` / `stable_pos` / `stable_rot`。
- `PoseResult` proto 当前字段名是 `color_reprojection` 和 `render_quality_evaluated`。不要恢复旧 `track_reprojection` / `render_quality_expected`。
- `score_phase`、`score_reprojection`、`score_depth`、`score_mask`、`score_reject`、`score_confidence` 保持原名；这是和一组 score 子分一致的命名，不是错名。
- `AnchorTrajectoryPlayer` 和离线分析依赖当前 JSONL key；改 schema 必须同步 Unity writer、reader、Python eval 工具和 AGENTS。

Unity 场景/序列化注意事项：

- `AnchorRuntimeHub.runtimes`、`PoseResultReceiver.runtimeHub`、`PoseToAnchorRuntime.framePoseHistory/policyHost`、`AnchorEvalRecorder.recordedRuntimes` 都是场景关键绑定。改字段名必须同步 `.unity`，否则运行时会“收到消息但无人消费”或 eval 为空。
- `AnchorEvalRecorder.RecordedRuntime.anchorTransform` 是 `output_pos/output_rot` 的采样来源，不是直接读 runtime output pose。删它会让评估轨迹为空。
- `LatestResidualMeters/Degrees` 目前返回 NaN 是为了保留 eval schema；不要因为“恒为 NaN”就删 public API。
- `SmoothingStrategy.NominalLatencySeconds`、`AnchorMath.ClampPoseDelta`、`AnchorPolicyAction.Coast` 这类 public API 即使当前少用，也不要随手删，除非同步确认所有程序集和工具。

## 协议与生成输出

协议源：

- `EgoAnchor_Protocol/subjects.v1.json`
- `EgoAnchor_Protocol/proto/protocol/v1/common.proto`
- `EgoAnchor_Protocol/proto/protocol/v1/quest.proto`
- `EgoAnchor_Protocol/proto/protocol/v1/anchor.proto`

生成输出：

- Python：`EgoAnchor_Python/src/egoanchor/protocol/v1/*_pb2.py` 和 `subjects.v1.json` 副本。
- Unity：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/Generated/*.cs`。
- Unity subject 常量：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/SubjectNames.cs`。

生成代码不要手改。Python `*_pb2.py` 内部 import 是协议生成结果，不受包级导入约束影响。

## 论文与评估

论文问题表述：

> How can asynchronous 6DoF object pose tracking be transformed into stable, world-consistent, recoverable real-object anchoring in passthrough MR?

最低实验闭环：

1. Quest 真机 + Python real pipeline + Unity anchor runtime 连续运行。
2. 对比 arrival-time anchoring vs frame-aligned anchoring。
3. 对比 raw / low-pass 或 OneEuro / Kalman / reliability-aware static lock。
4. 覆盖静态观察、快速头动、部分遮挡、出视野后重获。
5. 至少 3 个代表性刚体物体。
6. 指标优先 world-space anchor error、jitter/slip、latency、recovery success/time。

论文源文件：`2026-EgoAnchor/egoanchor_cn_outline.tex`、`egoanchor_cn_v1.tex`、`egoanchor_cn_refs.bib`。`2026-EgoAnchor/pdf/` 是生成产物。

## 环境与依赖

- Python 环境由 `EgoAnchor_Python/pixi.toml` 管理：Python 3.12、CUDA 12.8、PyTorch 2.7 cu128、TensorRT cu12、pyrealsense2、ultralytics/YOLOE、nats-py、Cutie、SAM3 等。
- Windows 重建 `.pixi/envs/default` 失败时，先关闭 VS Code Python LSP、Black Formatter 和残留 Python 进程，避免文件占用。
- Unity 依赖由 `EgoAnchor_Unity/Packages/manifest.json` 管理，主线依赖 Google.Protobuf、NATS.Net、NetMQ 等。
- 日志门面：Python 使用 `egoanchor.utils.get_logger(...)` 与入口 `configure_logging(...)`；Unity 使用 `EgoAnchorLog.For<T>()`。日志消息本身不要手写 `[ClassName]` 前缀。

## 不要回退

- 不恢复旧 v1/v2 目录、MessagePack 链路、旧计划目录或早期 NATS 图像流实验。
- 不恢复旧默认端口 `5556/5557`；保持 Unity -> Python `15557`。
- 不恢复 ZMQ PUSH/PULL、JSON pose、业务分片、单图 legacy payload。
- 不恢复旧 Python 入口和旧 Unity `StaticStereoEncoder.cs`。
- 不恢复 Unity legacy port 自动迁移逻辑。
- 不把 SAM3 设为默认分割后端。
- 不恢复旧 Gate/Estimator/Output 三模块拆分或旧 `has_stable/stable_pos/stable_rot`、`estimator_module/output_module/gate_module` 字段。
- 不添加旧字段/旧路径兼容层；重构时直接迁移当前主线代码和场景。

## AGENTS.md 维护规则

- 保持本文件短，只写当前事实、核心约定、后续路线和历史坑。
- 不要修改 `USER-MAINTAINED-REQUIREMENTS` 区块。
- 大改后同步入口、模块职责、协议字段、配置名、验证命令和关键坑。
- 若代码事实推翻旧描述，直接改旧条目，不要追加相互矛盾的新条目。
