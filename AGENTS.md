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

EgoAnchor 面向开放消费级（passthrough）混合现实，把开放视觉感知能力转换成可直接使用的动态真实物体锚定能力。论文目标 IEEE VR 2027。

核心信息（Core Message）：*EgoAnchor enables open, deployable, and stable dynamic object anchoring for everyday rigid objects in consumer MR.* 全文围绕三个维度叙事，**不再罗列"五个特点"或"五维能力空白矩阵"**：

- **Open & Deployable**：仅依赖头显双目 RGB + 物体三维模型，无需物理标签、专用深度硬件或逐物体离线训练。
- **General-purpose**：面向任意日常刚性物体，而非预定义类别（由"免逐物体训练"直接带来，是因果关系，不是并列）。
- **Stable Dynamic Anchoring**：把异步视觉位姿持续维护为世界一致、可恢复的 6DoF 对象锚点，而不仅是输出位姿。

架构上对象感知（Object Perception）与对象锚定（Object Anchoring）解耦：Visual Perception Backend 持续产出 camera-space 异步位姿观测；Object Anchoring Runtime 做帧对齐、质量门控、时序稳定与生命周期管理，输出 world-space object anchor。技术 novelty（frame-aligned anchoring 的 capture-time 对齐、reliability-aware static lock、anchor-centric evaluation）全部落在 Stable Dynamic Anchoring 维度里，是技术主体，不是普通 pose tracking 工程；维度 1、2 是可达性/通用性故事。旧"四层协同架构"降级为 Runtime 内部结构，不再当顶层骨架。

诚实边界（写文必须守）：「纯视觉」只修饰物体位姿估计链路，参考相机世界位姿来自头显自身跟踪；「open / deployable」指无需专用深度/标签/逐物体训练，**不等于头显端独立运行**——当前仍依赖外部消费级 GPU 推理与异步通信，不要把三维叙事滑成"Quest 上即插即用"。

主线结构：

- Python：`EgoAnchor_Python/src`，负责 Quest stereo/camera_info 接收、目标分割、FFS/FoundationPose/Cutie、可靠性评分、NATS pose/status/heartbeat/command。
- Unity：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor`，负责 Quest 采集、frame pose history、camera-space pose 到 Unity world anchor、policy 输出和可视化运行时。
- Protocol：`EgoAnchor_Protocol`，唯一 proto 和 subject 源；生成脚本同步 Python/Unity 输出。
- Evaluation：`EgoAnchor_Tools3` 是当前主用离线升采样仿真工具；旧 `EgoAnchor_Tools` / `EgoAnchor_Tools2` 的同类项目不再作为主线验证依据。
- Paper：`2026-EgoAnchor` 放论文材料，写法必须保守，不能把未实现或未验证的机制写成已完成贡献。
- Patent：`EgoAnchor_Invention_Patent/13148-权利要求书-检索结果/01_版本稿/` 采用 `vNN` 版本化工作流；`active/` 只保留当前主稿和对应生成脚本，不覆写代理原稿或历史版本；当前主稿为 `active/v55_透视混合现实视觉帧锚定_申请主稿.md`；当前阶段仅维护版本化 `md` 主稿，`.docx` 由用户自行维护（已于 2026-06-22 批量完成 13148 权利要求书原件与副本的 149 个 LaTeX 公式到 native Word (OMML) 转换，并统一修复了 `clamp01` 与 `resize` 算子的直体样式，实现 0 LaTeX 残留及修订状态的完美保留）。
- Patent：在 v55 版本中，简化并提取了权利要求 11、14、15 的核心公式（删除了不必要的过程状态定义公式，仅保留最终输出、触发条件与核心状态更新方程），大幅提升了专利范围的保护力度。为适配 MS Word 公式编辑器的单字符下标渲染要求，将全部多字符下标简化为单字符（如在数学公式中引入 $s_{s,t}$ 与 $s_{u,t}$ 来替代多字符状态变量）；同时将时钟步长 $\Delta t$ 细分为渲染帧步长 $\Delta t_r$ 与控制点更新周期 $\Delta t_u$ 以消除符号二义性；深度有效信号的布尔逻辑公式修改为乘积求补的容斥表达形式 $\chi_t^{(d)} = \sigma_t^{(d)} [ 1 - (1-\mathbf 1[\upsilon_t^{(d)}>0])(1-\mathbf 1[\varrho_t^{(d)}>0])]$。修复了之前因 Python 字符串转义导致的 LaTeX 符号（如 \theta, \tau, \alpha, \frac 等）变控制字符的格式损坏问题，全稿公式无错。
- Patent：专利主稿中的数学符号不得在命令闭环、状态机、输出策略、静止锚定等不同模块间复用为不同语义；尤其命令平面的请求内容与静止锚定中的时间累计量必须使用不同符号，并在权利要求与具体实施方式两处保持一致。
- Patent：专利主稿中视觉模型链集合、复合算子、控制请求载荷、发送侧引擎帧号、颜色重投影评分信号等跨章节高频记号必须固定为单义符号，不得与命令请求、缓存记录字段或其他局部状态量复用。
- Patent：专利主稿中的“其中”说明必须覆盖公式里实际出现的关键记号；尤其运动模型与输出策略部分，需要显式交代控制点时间戳、末控制点、延迟更新系数、外推目标时刻、插值目标时刻、左极限输出位姿以及位姿残差合成/差分算子，避免出现公式可写出但定义链不闭合的情况。
- Patent：专利主稿中的命令去重、深度有效性和实施方式复述段也要逐项补齐时刻变量、窗口参数、状态有效标志、外推倍率、外推上限、最小插值延迟和渲染步长等记号，不得只在权利要求段定义、却在实施方式段省略。


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
- reliability：`render_quality.enabled=true` 默认只采集颜色重投影、mask 可见比例和深度对齐信号，并写入评分；Python 感知链路不根据低分、mask 丢失或位姿跳变自行重新 register，目标重获取由 Unity 通过 NATS `reacquire/reset` 命令驱动。
- diagnostics：`debug_view.py` 的主 pose dashboard 和独立 score debug 窗口都使用顶部信息横幅；图像面板必须从横幅下方开始排布，面板标签放在各自图像下方的独立标签条内，避免文字覆盖调试画面。主窗口横幅固定 9 行，评分窗口横幅固定 5 行加 3 条 V/C/D 子分条；不要按实际诊断行数动态改变 banner 高度，长文本按窗口宽度截断。主窗口 depth 面板保留原始深度伪彩色，只画 1px mask 轮廓，不做 mask 内部填充。score debug 窗口保持颜色重投影/深度对齐 2x3 诊断矩阵，上下两行都按观测、渲染、残差从左到右排列；RGB 面板只画 render/Cutie 轮廓，render/depth/残差面板使用中性背景或观测灰度上下文，避免黑底和半透明高亮掩盖原始颜色。残差面板右侧带热力图色标；深度残差图显示 `abs(render_depth - observed_depth)`，蓝色表示残差小、对齐好，红色表示残差大、差异明显，色标高端显示当前帧 p95 残差。`tracking_server` 的 OpenCV 合成显示用 `debug_window_max_fps` 和 `score_window_max_fps` 独立节流，默认主窗口 20Hz、score 窗口 6Hz；score 窗口的 LAB/深度残差矩阵较重，不要恢复成每个 pipeline 帧强制重建。
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

- SAM3 异步只异步初始分割。worker 输出必须携带同一帧 left/right RGB 和 mask，主 pipeline 再做 FFS/FoundationPose，避免 RGB/mask 错帧。等待 SAM3 分割期间的调试输出只更新 Quest RGB 预览，不同步跑 FFS depth；SAM3 完成但无 mask 时直接输出 `NO_MASK`，也不跑 FFS，避免未注册阶段的输入画面被深度推理卡住。
- 渲染质量检测只能采集和写分数；不要恢复 Python 内部低分自动重新 register 逻辑。
- `color_reprojection=-1` 表示本帧无有效颜色重投影信号，不是坏 pose。无效原因可能是 warmup、无 Cutie mask、渲染面积太小或 K 缺失。
- VCD 可靠性评分为 `R = V * exp((w_c ln C + w_d ln D) / (w_c + w_d))`，只对有效几何证据计权；默认 `reproj_weight=0.2`、`depth_weight=0.8`，深度权重高于颜色。
- depth 覆盖不足或渲染深度对齐无信号时 `score_depth=0.5` 是中性显示，不进入几何合取核；`render_quality_status=valid_no_valid_depth_overlap` 这类 `valid_*` 只表示颜色路径有效，不能当作深度有效信号。
- `network.message_plane.enabled=false` 可用于 Python-only debug，避免没有 NATS server 时阻塞模型调试。

## Unity 主线

主要链路：

`QuestStreamPublisher / StereoFrameSource / CameraInfoSource` 采集并发 ZMQ；`FramePoseHistory` 记录 capture-time camera pose；`PoseResultReceiver -> AnchorRuntimeHub -> PoseToAnchorRuntime` 解码并广播 pose；`CameraPoseFrameAligner` 做 OpenCV camera pose 到 Unity world pose；`AnchorPolicyHost` 输出每帧 anchor pose；`DynamicObjectAnchor` 只应用输出 Transform。

Unity policy 当前结构：

- `AnchorPolicyHost` 持有 `MotionModel` + `SmoothingStrategy`，维护生命周期和可选 score gate。
- `AnchorObservation.MeasurementTimeSeconds` 是采集时间轴，用于运动模型、平滑和静止锁；`LifecycleTimeSeconds` 是 Unity 到达时间轴，用于 stale/lost、低分持续时间和生命周期状态。不要用 capture time 刷新生命周期新鲜度，否则 register 推理耗时较长时，高分 pose 到达后会被误判为陈旧并触发 reacquire。
- `Policy/Models`：`ConstantVelocityModel`、`KalmanModel`、`OneEuroModel`。
- `Policy/Smoothing`：`BlendStrategy`、`DelayedInterpStrategy`、`RawPassthroughStrategy`。
  - `DelayedInterpStrategy` 的 Hermite 用控制点 Kalman 速度当切线，运动急停时速度估计滞后（`positionProcessNoise` 衰减不够快）会让两个位置几乎重合的控制点之间挂着非零切线 → 样条鼓出再弹回 = 过冲振铃（用户报告“运动停下后 anchor 来回轻微震荡”）。修复：`hermiteTangentChordRatio`（默认3）把切线模长限到 K×弦长/span（位置、旋转通道各按自己弦长独立限幅）。停下时弦长≈0→切线≈0→不鼓包；真实运动时弦长≈v·span≈切线 ≪ K×弦长→不裁剪、行为不变。`BlendStrategy` 是残差单调衰减，无此问题。
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
- `Runtime/AnchorRuntimeHub.cs`：pose/status/heartbeat fan-out 给多个 runtime；低分 reacquire fan-in 也在这里合并发出。hub 在 PoseResult 分发后和 `LateUpdate` 都会消费 runtime 的 server reacquire 标志，避免 Lost/断流时因为没有下一条 PoseResult 而卡住不发命令。
- `Runtime/PoseToAnchorRuntime.cs`：把 camera-space pose 对齐为 Unity world pose，提交给 policy，每帧 `LateUpdate(-50)` 推进输出。
- `Runtime/DynamicObjectAnchor.cs`：只读 `TryGetOutputPose` 并应用 Transform，不承载滤波、状态机、网络或 recovery。
- `AnchorViz/AnchorStatusLabel.cs`：只做用户可见状态标签；简化模式对 Static/Tracking -> Uncertain 做短时间显示防抖，吸收低帧率或偶发低分帧造成的标签闪烁，不改变 `AnchorPolicyHost`、静止锁输出或 eval schema。
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

低分/track-loss 自动 reacquire：`AnchorPolicyHost` 只置 `wantsServerReacquire`；`PoseToAnchorRuntime.ConsumeServerReacquireRequest()` 透传；`AnchorRuntimeHub` 统一 fan-in，并用唯一 `reacquireCommandClient` 发 NATS reacquire。持续低总分超过 `lowScoreReacquireThreshold/Seconds` 后应请求 Python 重新 register；当前默认用 `trackingScoreFloor=0.5` 做用户可见低质/状态降级提示，用 `lowScoreReacquireThreshold=0.45` 且持续 `0.6s` 作为真正 server reacquire 触发，避免轻微遮挡刚低于 0.5 就反复 register。深度/颜色几何加权平均只用于区分 `low_score_track_lost`、`low_score_no_geometry` 或普通 `low_score` 诊断原因，不再阻止 server reacquire。不要让 leaf runtime 或 policy 自持 command client。

Unity/eval 字段契约：

- C# 属性 `MotionModelName` / `SmoothingStrategyName` / `GateName` 对应 JSONL `motion_model` / `smoothing_strategy` / `gate`。
- 每帧输出字段是 `has_output_pose` / `output_pos` / `output_rot`。不要恢复旧 `has_stable` / `stable_pos` / `stable_rot`。
- `PoseResult` proto 当前字段名是 `color_reprojection` 和 `render_quality_evaluated`。不要恢复旧 `track_reprojection` / `render_quality_expected`。
- `score_reprojection`、`score_depth`、`score_mask` 保持当前字段名；`score_phase`、`score_jump`、`score_reject`、`score_confidence` 已在 proto 中 reserved，不要恢复。
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

论文源文件：`2026-EgoAnchor/egoanchor_cn_v5.tex` 是当前最新中文主稿。历史草稿 `egoanchor_cn_v2.tex`、`egoanchor_cn_v1.tex`、`egoanchor_cn_outline.tex` 保留备查，参考文献入口为 `egoanchor_cn_refs.bib`。`2026-EgoAnchor/egoanchor_code_derived_technical_flow.md` 是当前按代码事实梳理的技术流程文档，论文实现细节、公式和系统边界优先以该文档和代码为准；`2026-EgoAnchor/paper-plan/paper_planning_notes.md` 只记录投稿叙事、实验设计和风险规划，不作为实现事实源。`2026-EgoAnchor/pdf/` 是生成产物。
当前部分 LaTeX 草稿文件在早期写作阶段可能先保留 `\bibliography{...}` 而尚未加入正文 `\cite{...}`；若需要临时消除 BibTeX 的 `I found no \citation commands` 提示，可显式加入 `\nocite{*}`，待正文引用补齐后再按需要移除。
系统架构图文档当前放在 `docs/architecture/`，用于维护主线 Python / Unity / Protocol / Evaluation 与三平面通信关系。其中 `egoanchor-system-architecture.drawio`（+ `.spec.yaml` / `.svg`）是系统级总览；`egoanchor-technical-framework.drawio` 是更详细的科研风格技术框架图（感知四步链、三层可靠性评分公式、静止锁机制、生命周期 FSM、评估链路），配套 `egoanchor-technical-route.md` 给出端到端技术路线说明与 gpt-image-2 绘图提示词。论文用中文架构图初稿在 `2026-EgoAnchor/figures/egoanchor_architecture_cn.svg`，可编辑源为同名 `.drawio`，后续英文投稿版可在此基础上翻译标签。

专利工作区：`EgoAnchor_Invention_Patent/`。专利文稿中的技术描述必须严格贴合当前主线实现：帧姿态历史正式路径只允许按 `frame_id` 精确命中，不得杜撰 latest-match、最近有效缓存回退、候选评分回查或“降级对齐”机制；静止锁相关公式要覆盖 `headToleranceFactor`、`posDistanceFactor`、`headSettleSeconds`、`lowScoreReleaseScore/Seconds` 等当前真实机制，不得退回成只写 deadband + CUSUM 的简化版本；同时要突出纯视觉链路、AI 模型链、异步通信、帧对齐、可靠性评分与整套 anchor 策略。这里“纯视觉”只适用于目标物体位姿估计链路，不得把参考相机世界位姿的来源写成“完全不依赖惯性传感器或外部空间定位传感器”的绝对方案。
在进行专利初稿 `.docx` 的检查与确认时，需重点防范由格式转换引起的数学公式损坏：Word (OMML) 转换过程中指示函数 \(\mathbf 1[\cdot]\) 极易退化为普通数字 `1` 导致逻辑关系彻底失效；递推公式中的接缝残差等变量容易发生同名混淆（如将 \(\tilde{r}_t\) 误写为 \(r_t\)）；大括号分段函数易丢失且易残留 LaTeX 格式代码（如 `[6pt]`、`[4pt]`）。此外，Word 草稿在同步主稿时容易缺失较多控制公式及系统细化从属权利要求，且极易因模板残留引入无关技术文本（如“专家网络”等多模态无关内容），后续检查需以最新 `vNN` 主稿 `md` 文件为唯一绝对真理源进行全文核对与重构。

## 环境与依赖

- Python 环境由 `EgoAnchor_Python/pixi.toml` 管理：Python 3.12、CUDA 12.8、PyTorch 2.7 cu128、TensorRT cu12、pyrealsense2、ultralytics/YOLOE、nats-py、Cutie、SAM3 等。
- Windows 重建 `.pixi/envs/default` 失败时，先关闭 VS Code Python LSP、Black Formatter 和残留 Python 进程，避免文件占用。
- Unity 依赖由 `EgoAnchor_Unity/Packages/manifest.json` 管理，主线依赖 Google.Protobuf、NATS.Net、NetMQ 等。
- 日志门面：Python 使用 `egoanchor.utils.get_logger(...)` 与入口 `configure_logging(...)`；Unity 使用 `EgoAnchorLog.For<T>()`。日志消息本身不要手写 `[ClassName]` 前缀。

## Git 忽略规则

- `.gitignore` 按目录分层维护：父级只管理本层和没有下级 `.gitignore` 接管的直属目录；一旦子目录有自己的 `.gitignore`，权重、缓存、构建输出和运行日志都交给该子目录管理。
- 仓库根 `.gitignore` 只管根层编辑器状态、根层临时 Python 缓存、`EgoAnchor_Blender` 本地模型/插件/Blender 工作文件和本地专利工作区；不要在根层写 Python、Unity、论文目录内部产物。
- `EgoAnchor_Python/.gitignore` 只管一方 Python 环境、根权重、runtime/eval 日志、Mutagen lock 和一方代码缓存；`Cutie`、`Fast-FoundationStereo`、`FoundationPose`、`sam3` 的 checkpoint、权重、ONNX/TensorRT engine、debug/output/build 产物由各自子目录 `.gitignore` 接管。
- `2026-EgoAnchor/.gitignore` 管论文目录内 LaTeX 编译产物和本地实验材料；`EgoAnchor_Unity/.gitignore` 管 Unity 生成目录、IDE 文件和 Unity build/package 产物。

## Python 远端同步

- `EgoAnchor_Python/mutagen.yml` 统一管理 RTX4090、RTX5090 和 RTX5080 Laptop 的 Python 服务器同步。本机是唯一源码源头，三个 `source-*` 会话使用 `one-way-safe` 从本机推到远端；远端源码改动会变成冲突，不会自动回流。Mutagen session 名只能使用合法 name 字符，使用连字符，不要用下划线。
- 远端日志通过独立 `eval-logs-*` 和 `runtime-logs-*` 会话拉回本机，统一落在 `EgoAnchor_Python/data/eval`。三台机器若生成同名日志会产生冲突；保持 `one-way-safe`，不要改成会镜像删除本地文件的模式。
- 源码同步忽略 `.pixi`、权重、ONNX/TRT engine、runtime 日志、eval 日志、debug 输出和平台相关 build 产物。权重和 TensorRT engine 按机器本地维护；RTX5080 Laptop 是 Windows 原生路径 `D:/Projects/EgoAnchor_Python`。
- 当前本机 SSH 默认公钥是 `C:\Users\zheliku\.ssh\id_ed25519.pub`，指纹 `SHA256:/pWd7s01iijezRD+YVju7yJdrKNMQIMPKwdo64HZLz8`；RTX4090、RTX5090 和 RTX5080 Laptop 已验证可免密登录。若 Codex 沙箱里 `ssh` 被 `.sbx-denybin` 覆盖，直接调用 `C:\Windows\System32\OpenSSH\ssh.exe`。
- RTX5080 Laptop 的 `gjw` 属于 Windows 管理员组，Windows OpenSSH 会读取 `C:\ProgramData\ssh\administrators_authorized_keys`，不是普通用户的 `C:\Users\gjw\.ssh\authorized_keys`。必须在 RTX5080 本机用管理员 PowerShell 写入公钥、设置 ACL，并重启 `sshd`；不要在 SSH 会话里启动 `notepad`。RTX5080 的 Windows SSH 默认 `cmd.exe` 代码页已通过 `HKCU\Software\Microsoft\Command Processor\AutoRun = chcp 65001 >NUL` 切到 UTF-8，否则 Mutagen 可能报 `remote did not return UTF-8 output`。
- 首次 `mutagen project start` 前，先确保远端项目目录、`data/eval` 和 `data/runtime_logs` 已存在。缺少日志源目录会让对应拉回会话启动失败。

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
- 本机 Codex 已在用户配置中启用 `superpowers@openai-curated`；后续 AI 若会话暴露该插件技能，应先读/调用 `using-superpowers` 再处理任务。
