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
11. 注意我们论文路径目前是2026-EgoAnchor-Typst/，写的是typst语言，而不是latex，请你注意语法。写完后使用本机的typst进行编译检查通过。

<!-- USER-MAINTAINED-REQUIREMENTS:END -->

本文件是 EgoAnchor 的项目级接手指南。只记录长期有效的事实、约定、路线和历史坑；不要追加流水账。顶部 `USER-MAINTAINED-REQUIREMENTS` 区块由用户维护，除非用户明确要求，后续 AI 不得改动其中任何文字。

## 当前定位

EgoAnchor 面向开放消费级（passthrough）混合现实，把开放视觉感知能力转换成可直接使用的动态真实物体锚定能力。论文目标 IEEE VR 2027。

核心信息（Core Message）：*EgoAnchor enables open, deployable, and stable dynamic object anchoring for everyday rigid objects in consumer MR.* 全文围绕三个维度叙事：

- **Open & Deployable**：仅依赖头显双目 RGB + 物体三维模型，无需物理标签、专用深度硬件或逐物体离线训练。
- **General-purpose**：面向任意日常刚性物体，而非预定义类别（由"免逐物体训练"直接带来，是因果关系，不是并列）。
- **Stable Dynamic Anchoring**：把异步视觉位姿持续维护为世界一致、可恢复的 6DoF 对象锚点，而不仅是输出位姿。

架构上对象感知（Object Perception）与对象锚定（Object Anchoring）解耦：Visual Perception Backend 持续产出 camera-space 异步位姿观测；Object Anchoring Runtime 做时空对齐（基于采集时刻的 `frame_id` 精确帧对齐）、锚定策略、静止锚定和生命周期管理，输出 world-space object anchor。技术 novelty（frame-aligned anchoring 的 capture-time 对齐、静止锚定、anchor-centric evaluation）全部落在 Stable Dynamic Anchoring 维度里，是技术主体，不是普通 pose tracking 工程；维度 1、2 是可达性/通用性故事。质量评估门控不是独立模块；代码中保留为 `AnchorPolicyHost.enableQualityGate` 控制的内联可选观测拒绝逻辑，论文 RQ2 完整方法变体可打开。

诚实边界（写文必须守）：「纯视觉」只修饰物体位姿估计链路，参考相机世界位姿来自头显自身跟踪；「open / deployable」指无需专用深度/标签/逐物体训练，**不等于头显端独立运行**——当前仍依赖外部消费级 GPU 推理与异步通信，不要把三维叙事滑成"Quest 上即插即用"。

主线结构：

- Python：`EgoAnchor_Python/src`，负责 Quest stereo/camera_info 接收、目标语义分割、双目立体几何重建（FFS）、FoundationPose/Cutie、可靠性评分、NATS pose/status/heartbeat/command。
- Unity：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor`，负责 Quest 采集、frame pose history、camera-space pose 到 Unity world anchor、policy 输出和可视化运行时。
- Protocol：`EgoAnchor_Protocol`，唯一 proto 和 subject 源；生成脚本同步 Python/Unity 输出。
- Evaluation：`EgoAnchor_Tools3` 是当前主用离线升采样仿真工具；旧 `EgoAnchor_Tools` / `EgoAnchor_Tools2` 的同类项目不再作为主线验证依据。
- Paper：`2026-EgoAnchor-Typst` 放当前 Typst 论文主稿、图像资产和代码事实技术流程文档，写法必须保守，不能把未实现或未验证的机制写成已完成贡献。
- Patent：`EgoAnchor_Invention_Patent/13148-权利要求书-检索结果/01_版本稿/` 采用 `vNN` 版本化工作流；`active/` 只保留当前主稿和对应生成脚本，不覆写代理原稿或历史版本；当前主稿为 `active/v55_透视混合现实视觉帧锚定_申请主稿.md`；当前阶段仅维护版本化 `md` 主稿，`.docx` 由用户自行维护（已于 2026-06-22 批量完成 13148 权利要求书原件与副本的 149 个 LaTeX 公式到 native Word (OMML) 转换，并统一修复了 `clamp01` 与 `resize` 算子的直体样式，实现 0 LaTeX 残留及修订状态的完美保留）。
- Patent：在 v55 版本中，简化并提取了权利要求 11、14、15 的核心公式（删除了不必要的过程状态定义公式，仅保留最终输出、触发条件与核心状态更新方程），大幅提升了专利范围的保护力度。为适配 MS Word 公式编辑器的单字符下标渲染要求，将全部多字符下标简化为单字符（如在数学公式中引入 $s_{s,t}$ 与 $s_{u,t}$ 来替代多字符状态变量）；同时将时钟步长 $\Delta t$ 细分为渲染帧步长 $\Delta t_r$ 与控制点更新周期 $\Delta t_u$ 以消除符号二义性；深度有效信号的布尔逻辑公式修改为乘积求补的容斥表达形式 $\chi_t^{(d)} = \sigma_t^{(d)} [ 1 - (1-\mathbf 1[\upsilon_t^{(d)}>0])(1-\mathbf 1[\varrho_t^{(d)}>0])]$。修复了之前因 Python 字符串转义导致的 LaTeX 符号（如 \theta, \tau, \alpha, \frac 等）变控制字符的格式损坏问题，全稿公式无错。
- Patent：专利主稿中的数学符号不得在命令闭环、状态机、输出策略、静止锚定等不同模块间复用为不同语义；尤其命令平面的请求内容与静止锚定中的时间累计量必须使用不同符号，并在权利要求与具体实施方式两处保持一致。
- Patent：专利主稿中视觉模型链集合、复合算子、控制请求载荷、发送侧引擎帧号、颜色重投影评分信号等跨章节高频记号必须固定为单义符号，不得与命令请求、缓存记录字段或其他局部状态量复用。
- Patent：专利主稿中的“其中”说明必须覆盖公式里实际出现的关键记号；尤其运动模型与输出策略部分，需要显式交代控制点时间戳、末控制点、延迟更新系数、外推目标时刻、插值目标时刻、左极限输出位姿以及位姿残差合成/差分算子，避免出现公式可写出但定义链不闭合的情况。
- Patent：专利主稿中的命令去重、深度有效性和实施方式复述段也要逐项补齐时刻变量、窗口参数、状态有效标志、外推倍率、外推上限、最小插值延迟和渲染步长等记号，不得只在权利要求段定义、却在实施方式段省略。


## 核心架构

EgoAnchor 固定采用双平面/三语义通道：

| 平面          | 传输               | 方向            | 数据                                                       | 策略                                                                   |
| ------------- | ------------------ | --------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------- |
| Data Plane    | ZMQ PUB/SUB        | Unity -> Python | `QuestStereoFrame`、`QuestCameraInfo`                  | Protobuf bytes，multipart`[topic_utf8, payload]`，topic latest-drain |
| Message Plane | NATS Core pub/sub  | Python -> Unity | `PoseResult`、`AnchorStatusEvent`、`ServerHeartbeat` | pose/heartbeat latest-only，status event stream                        |
| Command Plane | NATS request/reply | Unity -> Python | reset / reacquire / control                                | `request_id` 幂等，快速 ack，runtime 串行执行                        |

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
pixi run python .\src\run_server.py
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

- 入口：`EgoAnchor_Python/src/run_server.py` 调 `egoanchor.app.tracking_server`。
- 配置：`src/egoanchor/config/defaults.toml` 和 `objects.toml`；每个 `.toml` 参数必须同行中文注释。
- 分割：默认 `module.segmenter.type="yoloe26"`；SAM3 只能显式配置启用，不能改成默认。
- reliability：`render_quality.enabled=true` 默认只采集颜色重投影、mask 可见比例和深度对齐信号，并写入评分；Python 感知链路不根据低分或位姿跳变自行重新 register。单帧 Cutie mask 丢失输出 no-pose；连续空 mask 达到阈值会清空本地注册状态并等待后续有效输入重新 register。显式目标重获取由 Unity 通过 NATS `reacquire/reset` 命令驱动。
- diagnostics：`debug_view.py` 的主 pose dashboard 和独立 score debug 窗口都使用顶部信息横幅；图像面板必须从横幅下方开始排布，面板标签放在各自图像下方的独立标签条内，避免文字覆盖调试画面。主窗口横幅固定 9 行，评分窗口横幅固定 5 行加 3 条 V/C/D 子分条；不要按实际诊断行数动态改变 banner 高度，长文本按窗口宽度截断。主窗口 depth 面板保留原始深度伪彩色，只画 1px mask 轮廓，不做 mask 内部填充。score debug 窗口保持颜色重投影/深度对齐 2x3 诊断矩阵，上下两行都按观测、渲染、残差从左到右排列；RGB 面板只画 render/Cutie 轮廓，render/depth/残差面板使用中性背景或观测灰度上下文，避免黑底和半透明高亮掩盖原始颜色。残差面板右侧带热力图色标；深度残差图显示 `abs(render_depth - observed_depth)`，蓝色表示残差小、对齐好，红色表示残差大、差异明显，色标高端显示当前帧 p95 残差。`tracking_server` 的 OpenCV 合成显示用 `debug_window_max_fps` 和 `score_window_max_fps` 独立节流，默认主窗口 20Hz、score 窗口 6Hz；score 窗口的 LAB/深度残差矩阵较重，不要恢复成每个 pipeline 帧强制重建。
- logging：两种模式
  - **评估session模式**（`eval_session_enabled=true`，默认）：在 `data/eval/<session_id>/` 创建共享目录，写入Python runtime日志和元数据，供Unity自动配对。`header.session_id` 通过NATS广播给Unity。
  - **普通运行时模式**（`eval_session_enabled=false`）：在 `data/runtime_logs/` 写入独立时间戳日志，用于日常调试，不与Unity配对。
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
- `src/egoanchor/reliability/`：`reprojection.py` 只做交集区域 LAB 颜色重投影；`depth_alignment.py` 只做渲染 depth 与 FFS depth 对齐，采用距离和几何复杂度自适应阈值；`render_quality.py` 负责一次渲染后协调两者；`pose_quality.py` 合成总可靠性分。

Python 细节坑：

- SAM3 异步只异步初始分割。worker 输出必须携带同一帧 left/right RGB 和 mask，主 pipeline 再做 FFS/FoundationPose，避免 RGB/mask 错帧。等待 SAM3 分割期间的调试输出只更新 Quest RGB 预览，不同步跑 FFS depth；SAM3 完成但无 mask 时直接输出 `NO_MASK`，也不跑 FFS，避免未注册阶段的输入画面被深度推理卡住。
- 渲染质量检测只能采集和写分数；不要恢复 Python 内部低分自动重新 register 逻辑。
- `pose_jump_translation_m/pose_jump_rotation_deg` 仍是 TRACK 后的硬异常位姿拒绝阈值，触发时输出 `TRACK_REJECT` no-pose，但不生成可靠性子分，也不自动重新 register；已删除的是 proto/评分里的 `score_jump` 子分。
- `color_reprojection=-1` 表示本帧无有效颜色重投影信号，不是坏 pose。无效原因可能是 warmup、无 Cutie mask、渲染面积太小或 K 缺失。
- VCD 可靠性评分统一解释为 VCD（Visibility-gated Color-Depth）可靠性评分模型：`R = V * G_CD`，其中 `G_CD = exp((w_c ln C + w_d ln D) / (w_c + w_d))`，只对有效 C/D 一致性证据计权；默认 `reproj_weight=0.2`、`depth_weight=0.8`，深度权重高于颜色。论文中不要把 `G_CD` 写成独立于 VCD 的第四个方法名。
- 文献定位上不要把 VCD 单独表述为”首次提出 pose confidence / pose quality scoring”。已有 6D pose 文献包含 render-and-compare、hypothesis scoring、confidence、VSD/visible depth discrepancy 等相近思想；EgoAnchor 的创新边界应写成”面向 passthrough MR object anchoring 的在线、可解释、无 GT runtime reliability signal”，并强调它驱动 frame-aligned anchoring runtime 中的观测接收、静止锚定、状态降级、reacquire 和 anchor 生命周期管理。
- 深度对齐采用绝对-结构联合评估：`D = (1-α)·D_abs + α·D_struct`，其中 `D_abs` 基于逐像素残差统计（核心区域、距离自适应阈值、更宽容的残差容忍度 2.5×），`D_struct` 通过归一化深度图的 ZNCC 评估深度结构的空间对应关系。权重 `α ∈ [0, 0.35]` 根据深度 IQR 自适应调整：平坦表面（IQR < 20mm）回退到纯绝对残差，高频几何（IQR ≥ 20mm）引入结构验证。该机制解决手柄等高频几何物体在特殊角度下”形状正确但有系统性深度噪声”导致的深度分过低问题，实测从 0.406/0.306 提升到 0.9+，避免频繁误触发重定位。
- depth 覆盖不足或渲染深度对齐无信号时 `score_depth=0.5` 是中性显示，不进入几何合取核；`render_quality_status=valid_no_valid_depth_overlap` 这类 `valid_*` 只表示颜色路径有效，不能当作深度有效信号。
- `network.message_plane.enabled=false` 可用于 Python-only debug，避免没有 NATS server 时阻塞模型调试。

## Unity 主线

主要链路：

`QuestStreamPublisher / StereoFrameSource / CameraInfoSource` 采集并发 ZMQ；`FramePoseHistory` 记录 capture-time camera pose；`PoseResultReceiver -> AnchorRuntimeHub -> PoseToAnchorRuntime` 解码并广播 pose；`CameraPoseFrameAligner` 做 OpenCV camera pose 到 Unity world pose；`AnchorPolicyHost` 输出每帧 anchor pose；`DynamicObjectAnchor` 只应用输出 Transform。

Unity policy 当前结构：

- `AnchorPolicyHost` 持有 `MotionModel` + `SmoothingStrategy`，维护生命周期，并保留内联质量评估门控（`enableQualityGate`）。独立门控模块已删除；`enableQualityGate=false` 是源码默认，论文 RQ2 完整方法变体可在场景中开启。开启时只按总可靠性分和测量-预测跳变拒绝观测，eval 字段为 `quality_gate=enabled/disabled`。
- `AnchorObservation.MeasurementTimeSeconds` 是采集时间轴，用于运动模型、平滑和静止锚定；`LifecycleTimeSeconds` 是 Unity 到达时间轴，用于 stale/lost、低分持续时间和生命周期状态。不要用 capture time 刷新生命周期新鲜度，否则 register 推理耗时较长时，高分 pose 到达后会被误判为陈旧并触发 reacquire。
- `Policy/Models`：`ConstantVelocityModel`、`KalmanModel`、`OneEuroModel`。
- `Policy/Smoothing`：`BlendStrategy`、`DelayedInterpStrategy`、`RawPassthroughStrategy`。
  - `DelayedInterpStrategy` 的 Hermite 用控制点 Kalman 速度当切线，运动急停时速度估计滞后（`positionProcessNoise` 衰减不够快）会让两个位置几乎重合的控制点之间挂着非零切线 → 样条鼓出再弹回 = 过冲振铃（用户报告”运动停下后 anchor 来回轻微震荡”）。修复：`hermiteTangentChordRatio`（默认3）把切线模长限到 K×弦长/span（位置、旋转通道各按自己弦长独立限幅）。停下时弦长≈0→切线≈0→不鼓包；真实运动时弦长≈v·span≈切线 ≪ K×弦长→不裁剪、行为不变。`BlendStrategy` 是残差单调衰减，无此问题。
  - `DelayedInterpStrategy` 的延迟自适应增加变化率限制（`MaxDelayChangePerSecond=0.05`），防止Python推理时间波动导致延迟突变影响用户体验。延迟目标按实测采集-渲染延迟×安全系数计算，但通过 `Mathf.MoveTowards` 平滑过渡，最多每秒变化50ms。
- `Policy/Contracts`：`AnchorObservation`、`AnchorPolicyDecision`、`AnchorPolicyOutput`、`QualityGateDecision`。
- `Policy/Lifecycle`：`AnchorStateMachine`、`AnchorPolicyTypes`。
- `Policy/Math`：`AnchorMath`、`ConstVelocityKalman`、`ScalarOneEuro`、`Spline`。
- `EgoAnchorStaticLockModule` 是静止锚定（StaticLock）MonoBehaviour 参数宿主；`StaticLockController` 是纯 C# 控制器。静止锚定与 model × strategy 正交：挂模块并 `lockEnabled=true` 是 EgoAnchor 方法，不挂或关闭是 baseline。

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
- `AnchorViz/AnchorStatusLabel.cs`：只做用户可见状态标签；简化模式对 Static/Tracking -> Uncertain 做短时间显示防抖，吸收低帧率或偶发低分帧造成的标签闪烁，不改变 `AnchorPolicyHost`、静止锚定输出或 eval schema。
- `EgoAnchorEval/AnchorEvalRecorder.cs`：按 capture/render 两条日志写 JSONL；配置摘要通过反射收集 `[SerializeField]` 字段，隐藏字段也会进入 config hash。

静止锚定（StaticLock）命名约定：

- 在 `EgoAnchorStaticLockModule` 内字段名不再重复 `staticLock` 前缀，例如 `unlockDriftMeters`、`headSettleSeconds`、`lowScoreReleaseScore`。
- 不使用 `FormerlySerializedAs` 兼容旧字段名；场景 YAML 直接迁移到新 key。
- 静止锚定所有仍参与控制逻辑的参数应保持可见，便于真机调参和复现实验。不要用 `[HideInInspector]` 把正在生效的调参字段藏起来；若后续要减少 Inspector 压力，应做自定义 Inspector foldout、profile 或进一步拆分参数宿主。
- `LatestStaticLocked`、`motion_model`、`smoothing_strategy`、`quality_gate`、`has_output_pose`、`output_pos`、`output_rot` 是当前 eval/runtime 契约，不要改回旧名。

静止锚定核心机制：

- `OnObservation` 只在 host 接受观测后调用；它更新 obs-to-obs 速度、头动容忍、观测共识、锁定/解锁证据。
- `Stabilize(candidate, dt)` 每渲染帧调用。锁定时返回 `lockedPose`；解锁后用 seam residual 从锁点平滑回到 smoothing 输出；未锁定时透传 candidate。
- 进入锁定看 `enterSpeedMps`、`enterAngSpeedDps`、`dwellSeconds`、`minScore`。角速度阈值 `enterAngSpeedDps=22°/s` 设为观测噪声地板（~15°/s）的约 1.5 倍，在抑制噪声与快速锁定间平衡。线速度和角速度阈值必须高于真实观测噪声地板，尤其角速度阈值太低会永不锁定。
- 解锁证据有三路：速度逃逸、漂移租绳、CUSUM。三路都按真实 dt 处理，不绑定帧率。
- 漂移租绳量的是 `distance(obsConsensus, anchorOrigin)`，不是单帧观测，也不是 creep 后的 `lockedPose`。改回 `lockedPose` 会导致慢速持续移动时永不解锁。
- `obsConsensus` 是死区无关的低增益 EMA，用来平滑单帧噪声/head-slip，同时跟随真实持续位移。
- 头动容忍系数 `headToleranceFactor=1+ratio*(headMaxToleranceFactor-1)`，同比放大死区、租绳和速度逃逸阈值。
- creep 增益乘 `(1 - headMotionRatio)`。头动时不能让系统性 head-slip 偏置被 creep 写进锁点。
- `headSettleSeconds` **只在头已停下、但沉降计时未走完的窗口内**冻结“判物体在动”的证据（速度逃逸/CUSUM/租绳，并清零三者累积）。它修的是“头扫静止物体、头一停就脱离 static”的时序竞速（头停瞬间 `headToleranceFactor` 塌回但 slip 还残留在 `obsConsensus`/速度里）。**头动期间绝不冻结**——那会把头动中物体的大幅真动也锁死；头动时只靠 `headToleranceFactor` 抬高阈值吸收 slip（slip 小幅、真动大幅，靠阈值区分）。计时在 `OnObservation` 维护：`headMotionRatio>0.06` 重置满、否则按 obsDt 递减；冻结判据是 `headMotionRatio<=0.06 && 计时>0`。
- 距离自适应只放大位置通道，不放大旋转通道。远距离双目立体几何重建的深度噪声更大，但旋转噪声不按距离同样变化。
- 低分释放不受 head settle 冻结影响。它表示锁点可靠性差，应该强制释放并交给低分 reacquire 链路。

低分/track-loss 自动 reacquire：`AnchorPolicyHost` 只置 `wantsServerReacquire`；`PoseToAnchorRuntime.ConsumeServerReacquireRequest()` 透传；`AnchorRuntimeHub` 统一 fan-in，并用唯一 `reacquireCommandClient` 发 NATS reacquire。源码默认 `enableLostReacquire=true`、`enableLowScoreReacquire=true`，部分 baseline 场景会关闭低分重获取；持续低总分超过 `lowScoreReacquireThreshold=0.45` 且持续 `0.6s` 后请求 Python 重新 register。`trackingScoreFloor` 源码默认 0.0，EgoAnchor 真机/评估场景可覆盖到 0.5 作为用户可见低质/状态降级提示。颜色/深度一致性加权平均只用于区分 `low_score_track_lost`、`low_score_no_geometry` 或普通 `low_score` 诊断原因，不再阻止 server reacquire。不要让 leaf runtime 或 policy 自持 command client。

Unity/eval 字段契约：

- C# 属性 `MotionModelName` / `SmoothingStrategyName` / `QualityGateMode` 对应 JSONL `motion_model` / `smoothing_strategy` / `quality_gate`。
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
2. RQ1 报告完整系统的锚定质量：精度、稳定性、响应性和鲁棒性。
3. RQ2 做设计权衡消融：简化基线、时空对齐、完整方法（时空对齐 + 质量评估门控 + 静止锚定），并比较静止锚定与运动无关平滑。
4. RQ3 覆盖多类日常刚性物体与典型应用场景。
5. 覆盖静态观察、快速头动、部分遮挡、出视野后重获。
6. 至少 3 个代表性刚体物体。
7. 指标优先 world-space anchor error、jitter/slip、latency、recovery success/time。

论文源文件：`2026-EgoAnchor-Typst/egoanchor_cn_v4.typ` 是当前中文主稿；`egoanchor_cn_v3.typ` 为上一版；`egoanchor_cn_v2.typ` 和 `egoanchor_cn_v1.typ` 为早期 Typst 草稿；参考文献入口为 `2026-EgoAnchor-Typst/egoanchor_cn.bib`。`egoanchor_cn_v4.typ` 是论文相关项目文档的术语基准；`2026-EgoAnchor-Typst/egoanchor_code_derived_technical_flow.md` 按 v4 论文术语记录代码事实、字段名、公式和系统边界。`2026-EgoAnchor-Typst/figs/` 放当前 Typst 图像资产，`2026-EgoAnchor-Typst/pdf/` 是生成产物。
论文写作使用 Typst 语法，不使用 LaTeX/BibTeX 编译链。写完主稿后在仓库根目录运行：`typst compile --root . .\2026-EgoAnchor-Typst\egoanchor_cn_v4.typ .\2026-EgoAnchor-Typst\pdf\egoanchor_cn_v4.pdf`。
`docs/architecture/` 已被完全删除，系统架构、技术路线与绘图提示词后续统一维护在 `2026-EgoAnchor-Typst/egoanchor_code_derived_technical_flow.md` 内。`egoanchor_cn_v4.typ` 是当前已确定论文文本；后续 AI 不要擅自改论文术语。2026-07-03 已将 `paper_planning_notes.md` 和 `egoanchor_code_derived_technical_flow.md` 的论文口径同步到 v4 术语：动态真实物体锚定、目标语义分割、双目立体几何重建、可靠性评分、时空对齐、运动估计与平滑、静止锚定和生命周期管理。RQ 以 v4 为准：RQ1=锚定质量，RQ2=设计权衡，RQ3=泛化能力；时空对齐和静止锚定的消融属于 RQ2。

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
- `2026-EgoAnchor-Typst/.gitignore` 管当前论文目录内 Typst 编译产物和本地实验材料；`EgoAnchor_Unity/.gitignore` 管 Unity 生成目录、IDE 文件和 Unity build/package 产物。

## Python 远端同步

- `EgoAnchor_Python/mutagen.yml` 统一管理 RTX4090、RTX5090 和 RTX5080 Laptop 的 Python 服务器同步。本机是唯一源码源头，三个 `source-*` 会话使用 `one-way-safe` 从本机推到远端；远端源码改动会变成冲突，不会自动回流。Mutagen session 名只能使用合法 name 字符，使用连字符，不要用下划线。
- 远端日志通过独立 `logs-*` 会话拉回本机，统一落在 `EgoAnchor_Python/data/eval`。三台机器若生成同名日志会产生冲突；保持 `one-way-safe`，不要改成会镜像删除本地文件的模式。
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

## 近期优化记录

### 2026-07-04 RQ1 手动标记评估系统实施（进行中）

**背景**：改变 RQ1 数据采集方式，从 Python 自动场景检测改为 Unity 按键手动标记，原因是自动分析总是出错，分不清具体的物体运动状态。

**核心改动**：

1. **Python 侧场景类型对齐论文**（已完成）
   - 更新 `auto_scenario_detection.py` 的 `ScenarioType` 枚举
   - 旧：`STATIC/SLOW_MOTION/FAST_MOTION/ROTATION/OCCLUSION`
   - 新：`STATIC_OBSERVATION/SLOW_TRANSLATION/FAST_MOTION/ROTATION/OCCLUSION_RECOVERY`
   - 严格对齐论文 `egoanchor_cn_v4.typ` 第304行 RQ1 实验条件
   - 更新检测阈值：慢速平移 5-10 cm/s，快速挥动 50+ cm/s

2. **Python Schema 扩展**（已完成）
   - `schemas.py` 添加 `rq1_metric: str` 和 `rq1_metric_duration: float` 字段
   - 添加 `_optional_str()` 辅助函数
   - `OutputRow.to_records()` 包含 RQ1 字段

3. **Unity RQ1 评估组件**（已完成代码，待 Unity Editor 同步）
   - 新增 `Eval/RQ1/` 命名空间和目录
   - `RQ1MetricType.cs`：5种指标枚举 + 扩展方法（对齐论文）
   - `RQ1MetricRecorder.cs`：记录指标类型和持续时间
   - `RQ1InputHandler.cs`：使用新 Input System 处理按键（1-5设置指标，0清除）
   - `RQ1StatusUI.cs`：实时显示面板（录制状态、当前指标、建议时长）

4. **集成到现有评估系统**（已完成）
   - `EvalRecorder.cs`：添加可选 `rq1Recorder` 字段，在 output 行写入 RQ1 字段
   - `EvalJson.cs`：`BuildOutputLine()` 添加 `rq1_metric` 和 `rq1_metric_duration` 参数
   - `EvalSession.cs`：添加 `using EgoAnchor.Eval.RQ1`

**RQ1 实验条件（论文对齐）**：
1. 长时静止（60s）：物体静置桌面，用户头部正常活动
2. 慢速平移（20s）：5-10 cm/s 水平移动
3. 快速挥动（20s）：50+ cm/s 快速运动
4. 旋转运动（20s）：绕多个轴旋转
5. 遮挡恢复（重复10次）：短暂遮挡后恢复

**待完成**：
- Unity Editor 中打开项目，让其检测新文件并重新生成 csproj
- 创建 `EgoAnchor-RQ1.unity` 测试场景（复制 EgoAnchor-Develop）
- 配置 Canvas UI 面板和组件绑定
- 修改 Python 分析脚本优先使用手动标记
- 真机测试完整流程

**技术细节**：
- 按键映射：1=长时静止，2=慢速平移，3=快速挥动，4=旋转运动，5=遮挡恢复，0=清除
- 输出格式：`unity_output.jsonl` 每行添加 `rq1_metric` 和 `rq1_metric_duration`
- 自动检测作为回退：无手动标记时使用自动场景检测
- 使用新 Input System（`UnityEngine.InputSystem`），不使用旧 `Input`

**详细文档**：`RQ1_IMPLEMENTATION_SUMMARY.md`

---

### 2026-07-04 RQ1 评估系统全面重建（2026-07-04 更新）

**Unity 侧（EgoAnchorEval → EgoAnchor.Eval）**：
- 旧 `EgoAnchorEval/` 目录（命名空间混乱、9 个文件）全部删除重建。
- 新目录：`Assets/Scripts/EgoAnchor/Eval/`，属于 `EgoAnchor` 程序集，命名空间 `EgoAnchor.Eval`。
- 4 个核心脚本：
  - `EvalLog.cs`：JSONL 写入器（轻量文件操作）
  - `EvalJson.cs`：capture/output/manifest JSON 行构建，含 `EvalVariantSnapshot`、`EvalVariantConfig` 数据结构
  - `EvalRecorder.cs`：订阅 `StereoFrameSource.FrameCaptured` 写 capture 行；`LateUpdate` 写 output 行（含 GT 线速度/角速度）
  - `EvalSession.cs`：session 开始/停止，`autoStart=true` 时收到第一个 PoseResult 自动开始，写 `session_manifest.json`
  - `EvalHotkeys.cs`：F7/F8 热键（可选，使用内置 Input 系统）
- 日志 schema 不变（Python 侧已有 schema 继续兼容）。

**Python 侧**：
- `eval/io/schemas.py`：`OutputRow` 补充 `gt_linear_speed_m_s`、`gt_angular_speed_deg_s` 字段（Unity 侧已写入）。
- `eval/research/rq1/analyze.py`（新建）：单 session RQ1 分析，自动场景检测 → 指标计算 → CSV + Markdown 输出。
- `eval/research/rq1/run_rq1.py`（重写）：批量分析 CLI，数据完整性检查 → 逐 session 分析 → 跨 session 聚合。
- 删除空目录 `eval/rq1_new/`。

**使用方式**：
```bash
# 单 session 分析
pixi run python -m egoanchor.eval.research.rq1.analyze \
    --session data/eval/20260704_143000_controller_right

# 批量 RQ1 分析（自动场景检测 + 聚合）
pixi run python -m egoanchor.eval.research.rq1.run_rq1
pixi run python -m egoanchor.eval.research.rq1.run_rq1 --pattern "*controller_right*"
```

**输出结构**：
```
data/research/rq1/
├── <session_id>/
│   ├── segments.csv          # 自动场景片段
│   ├── anchor_error_*.csv    # 锚定误差
│   ├── jitter_*.csv          # 抖动指标
│   └── summary.md            # 人类可读摘要
├── rq1_summary.csv           # 跨 session 汇总
└── rq1_aggregate.csv         # 跨 session 按场景均值
```

---

### 2026-07-04 Unity评估录制自动启动

**核心改进**：
1. **自动启动录制功能**：Unity收到第一个PoseResult时自动开始录制
   - 新增配置项：`EvalSessionController.autoStartOnFirstPose`（默认true）
   - 无需手动按F7，Python启动后Unity自动配对并开始录制
   - 适合长时间连续数据采集
   
2. **恢复RQ1自动化流程**：
   - 采集：Python启动 → Unity自动录制 → 停止保存
   - 分析：一键运行 `rq1.run_rq1` 从 `data/eval` 读取并输出到 `data/research/rq1`
   
3. **实现细节**：
   - `Start()` 初始化并输出自动启动提示
   - `LateUpdate()` 每帧检查 `runtimeHub.LatestPythonSessionId`
   - 检测到非空session_id时触发 `StartSession()`
   - 使用 `hasReceivedPose` 标志确保只触发一次

**使用方式**：
- 自动模式（推荐）：勾选 `Auto Start On First Pose`，启动Python后Unity自动录制
- 手动模式：取消勾选，使用F7/F8热键控制录制时机

**文档**：`UNITY_AUTO_START_RECORDING.md`

---

### 2026-07-04 Mutagen配置简化

**核心改进**：
1. **只保留RTX5090配置**：注释了RTX4090和RTX5080的同步会话
2. **简化配置文件**：减少不必要的配置，提高可维护性

**修改内容**：
- 保留：`push-5090`（源码同步）和 `logs-5090`（日志拉取）
- 注释：`push-4090`、`logs-4090`、`push-5080`、`logs-5080`

---

### 2026-07-04 数据目录结构优化

**核心改进**：
1. **统一数据管理**：所有数据统一在 `data/` 目录下组织
   - `data/eval/` - 原始session日志（Python和Unity运行时输出）
   - `data/research/` - 研究问题分析结果（RQ1/RQ2/RQ3的分析产物）
   - `data/runtime_logs/` - 普通运行时调试日志
   
2. **目录职责明确**：
   - `data/eval/<session_id>/` - 存储采集的原始日志（Python和Unity配对）
   - `data/research/rq1/`, `rq2/`, `rq3/` - 存储分析结果（CSV表格、PNG图表、汇总报告）
   - 一份eval日志可用于多个RQ分析，避免数据重复
   
3. **修改文件清单**：
   - `EgoAnchor_Python/mutagen.yml` - 同步路径使用 `data/eval`
   - `EgoAnchor_Python/src/egoanchor/runtime/tracking_runtime.py` - 默认回退路径
   - `EgoAnchor_Python/src/egoanchor/config/defaults.toml` - 配置路径和注释优化
   - `EgoAnchor_Unity/.../EvalSessionController.cs` - Unity默认输出路径
   - `EgoAnchor_Unity/.../RecordedAnchorReplaySource.cs` - 注释中的示例路径
   - 文档更新：AGENTS.md, eval/README.md, egoanchor_code_derived_technical_flow.md 等

**验证状态**：
- ✅ Unity编译通过（0错误）
- ✅ 配置文件已更新
- ✅ 文档已同步更新

**工作流程**：
```bash
# 采集：写入 data/eval/
pixi run python src/run_server.py

# 分析：从 data/eval/ 读取，结果写入 data/research/
pixi run python -m egoanchor.eval.research.rq1.run_rq1 \
    --source data/eval \
    --output data/research/rq1
```

### 2026-07-04 输出路径统一到debug目录（已回退）

**核心改进**：
1. **输出路径统一**：Python和Unity的原始日志输出统一到 `debug/` 目录
   - Python：`runtime.logging.eval_output_dir = "debug"`（已在defaults.toml配置）
   - Unity：默认输出路径改为 `EgoAnchor_Python/debug`
   - Mutagen：远端日志同步路径从 `data/eval` 改为 `debug`
   
2. **目录职责明确**：
   - `debug/` - 原始日志存储目录（Python和Unity运行时输出，包含session数据）
   - `eval/rq1/`, `eval/rq2/`, `eval/rq3/` - 分析结果目录（只存储分析产物，不存原始日志）
   - 避免数据重复，一份debug日志可用于多个RQ分析
   
3. **修改文件清单**：
   - `EgoAnchor_Python/mutagen.yml` - 同步路径从 `data/eval` 改为 `debug`
   - `EgoAnchor_Python/src/egoanchor/runtime/tracking_runtime.py` - 默认回退路径
   - `EgoAnchor_Unity/.../EvalSessionController.cs` - Unity默认输出路径
   - `EgoAnchor_Unity/.../RecordedAnchorReplaySource.cs` - 注释中的示例路径
   - 文档更新：AGENTS.md, README.md, egoanchor_code_derived_technical_flow.md 等

**验证状态**：
- ✅ Unity编译通过（0错误，2个无关警告）
- ✅ 配置文件已更新
- ✅ 文档已同步更新

### 2026-07-04 项目重组与RQ自动化评估系统

**核心改进**：
1. **项目结构重组**：数据与分析分离
   - `debug/` 存储所有原始日志（采集时写入，Python和Unity都输出到这里）
   - `eval/rq1/`, `eval/rq2/`, `eval/rq3/` 存储分析结果（分析时生成，只保存分析产物）
   - 避免数据重复，一份日志可用于多个RQ分析
   
2. **全自动评估流程**：
   - 采集时无需按键标记，全程自动录制
   - 事后通过GT速度和anchor状态自动识别场景
   - 一键命令完成场景检测、批量评估、跨场景汇总、报告生成
   
3. **评估工具链**：
   - `eval/batch_eval.py` - 批量评估多个sessions
   - `eval/auto_scenario_detection.py` - 自动场景检测
   - `eval/cross_scenario_analysis.py` - 跨场景汇总分析
   - `eval/rq1/run_rq1.py` - RQ1一键自动化脚本
   
4. **项目清理**：
   - 删除旧评估工具 `EgoAnchor_Tools` 和 `EgoAnchor_Tools2`
   - 删除空目录 `eval/calib`
   - 简化文档结构

**工作流程**：
```bash
# 采集：写入 data/eval/
pixi run python src/run_server.py

# 分析：从 data/eval/ 读取，结果写入 data/research/
pixi run python -m egoanchor.eval.research.rq1.run_rq1 \
    --source data/eval \
    --output data/research/rq1
```

**核心文档**：
- `data/DATA_ORGANIZATION.md` - 数据组织规范（简化版）
- `eval/rq1/README.md` - RQ1分析说明

### 2025-01-XX Unity 实现优化

**关键修改**：
1. 静止锚定角速度阈值从 35°/s 优化到 22°/s（噪声地板的 1.5 倍），平衡抑制噪声与快速锁定
2. 论文延迟描述从"固定 100-150ms"改为"自适应 100-350ms"，与代码实现一致
3. DelayedInterpStrategy 增加延迟变化率限制（50ms/s），防止 GPU 波动导致的突变

**详细文档**：
- `OPTIMIZATION_SUMMARY.md` - 完整优化总结和后续行动建议
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/OPTIMIZATION_LOG.md` - 技术细节

**验证状态**：
- ✅ Unity 编译通过（0 错误）
- ✅ 论文编译通过（无语法错误）
- ⏳ 待真机测试验证效果

## 性能统计

- Python pose pipeline 主调试窗口 HUD 显示 6 行固定高度横幅（`POSE_HUD_LINE_COUNT=10`），第 5 行显示后端各阶段耗时（yolo/depth/cutie/pose/rq/total），第 6 行显示调试窗口渲染耗时（ui_render debug/score）。
- `PipelineStepTiming` 包含 `render_quality_ms`；`FrameDiagnostics` 包含 `debug_render_ms` 和 `score_render_ms`。
- `_check_render_quality` 方法签名包含 `timing` 参数，将渲染质量耗时同时写入 `diagnostics.render_quality_ms` 和 `timing.render_quality_ms`。
- `tracking_server.py` 在渲染新帧前先将上一帧渲染耗时写入当前帧 diagnostics（避免时序悖论），渲染完成后测量新帧耗时。
- 真实帧时间 = `total_ms` + `debug_render_ms` + `score_render_ms`；调试窗口跳帧时渲染耗时不会每帧更新。
