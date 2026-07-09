# AGENTS.md

后续 AI 接手本仓库任务时，必须先阅读文件顶部的 **用户手动维护要求**。未阅读前不得修改代码。

<!-- USER-MAINTAINED-REQUIREMENTS:BEGIN -->

## 用户手动维护要求

本区由用户手动维护，放在文件顶部，方便查看和修改。后续 AI 只能读取、遵循和引用，不得自行修改、删减、重排、润色、合并或迁移本区内容。只有用户明确要求修改时，才可以改动本区，并且只改用户指定的内容。

1. Python 侧按包级入口导入，不深层导入到具体模块文件。包内可以使用 `from .image_utils import fit_to_size, stack_stereo` 这类显式 re-export；包外使用 `from egoanchor.algorithms import ...`，不要写成 `from egoanchor.algorithms.xxx import ...`。不要使用包级懒导出。
2. 代码需要有充分的中文说明。`.toml` 配置的每个参数都要在同一行末尾写中文注释；类、成员变量和每个方法也要补充中文说明。
3. 命名保持清楚、克制，不要为了"完整"把名字写得过长。
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

核心信息：*EgoAnchor enables open, deployable, and stable dynamic object anchoring for everyday rigid objects in consumer MR.* 三个叙事维度：

- **Open & Deployable**：仅依赖头显双目 RGB + 物体三维模型，无需物理标签、专用深度硬件或逐物体离线训练。
- **General-purpose**：面向任意日常刚性物体（由"免逐物体训练"直接带来，是因果关系，不是并列）。
- **Stable Dynamic Anchoring**：把异步视觉位姿持续维护为世界一致、可恢复的 6DoF 对象锚点。

架构解耦：Visual Perception Backend 持续产出 camera-space 异步位姿观测；Object Anchoring Runtime 做时空对齐（基于 `frame_id` 精确帧对齐）、锚定策略、静止锚定和生命周期管理，输出 world-space object anchor。

**诚实边界**：「纯视觉」只修饰物体位姿估计链路；「open / deployable」不等于头显端独立运行——当前仍依赖外部消费级 GPU 推理与异步通信。质量评估门控是 `AnchorPolicyHost.enableQualityGate` 控制的内联可选逻辑，论文 RQ2 完整变体可打开。

主线目录：

| 目录 | 职责 |
|------|------|
| `EgoAnchor_Python/src` | Quest 采集接收、分割、FFS 重建、FoundationPose/Cutie、可靠性评分、NATS 通信 |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor` | Quest 采集、帧位姿历史、camera→world 对齐、policy 输出、可视化 |
| `EgoAnchor_Protocol` | 唯一 proto 和 subject 源；生成脚本同步 Python/Unity |
| `EgoAnchor_Tools3` | 当前主用离线升采样仿真工具（旧 Tools/Tools2 不再作为主线验证） |
| `2026-EgoAnchor-Typst` | Typst 论文主稿、图像资产、代码事实技术流程文档 |
| `EgoAnchor_Invention_Patent` | 专利工作区；当前主稿 `active/v55_透视混合现实视觉帧锚定_申请主稿.md` |

## 核心架构

EgoAnchor 固定采用双平面/三语义通道：

| 平面 | 传输 | 方向 | 数据 | 策略 |
|------|------|------|------|------|
| Data Plane | ZMQ PUB/SUB | Unity → Python | `QuestStereoFrame`、`QuestCameraInfo` | multipart `[topic_utf8, payload]`，latest-drain |
| Message Plane | NATS Core pub/sub | Python → Unity | `PoseResult`、`AnchorStatusEvent`、`ServerHeartbeat` | pose/heartbeat latest-only，status event stream |
| Command Plane | NATS request/reply | Unity → Python | reset / reacquire / control | `request_id` 幂等，快速 ack，runtime 串行执行 |

关键约束：

- **Python 不输出 Unity world pose**；Unity 必须用 `frame_id` 回查 capture-time camera pose 做 world anchor。
- **不使用 pose 到达时 HMD pose** 代替发送帧 pose——这是项目核心历史坑。
- 业务代码不手写 subject 字符串；Python 从 `egoanchor.protocol` 包级入口导入，Unity 用 `SubjectNames`。
- 共享 proto 字段号不得重排；删除字段必须在 proto 中 `reserved` 字段号和字段名。
- Unity → Python ZMQ 端口：`15557`（不要恢复旧 `5556/5557`）。

## 项目级实现要求

- 生成代码（`*_pb2.py`、Unity `Protocol/Generated/`、`SubjectNames.cs`）不要手改。
- Unity Inspector 字段、网络参数、坐标语义和时间语义写 XML summary 或 `[Tooltip]`；不要用 `[HideInInspector]` 藏正在生效的调参字段。
- 日志统一走门面：Python 用 `egoanchor.utils.get_logger(...)` 和 `configure_logging(...)`；Unity 用 `EgoAnchorLog.For<T>()`；消息本身不手写 `[ClassName]` 前缀。
- 新增行为先补测试或 smoke 验证；最终必须给出可复现验证命令。
- 重构不做旧接口/旧字段/旧路径兼容；Unity 私有 `[SerializeField]` 改名直接迁移 `.unity`/`.prefab` YAML，不加 `FormerlySerializedAs`。

## 常用验证

Python 侧（在 `EgoAnchor_Python` 目录运行）：

```powershell
pixi run python .\src\run_server.py
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src
```

Unity 主线编译（仓库根目录）：

```powershell
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

协议生成（在 `EgoAnchor_Python` 目录）：

```powershell
pixi run pwsh -File ..\EgoAnchor_Protocol\tools\generate_proto.ps1
```

离线升采样仿真：

```powershell
dotnet run --project EgoAnchor_Tools3\AnchorUpsampleSim3.csproj -c Release -- --session EgoAnchor_Python\data\eval\<session> --zoom-start 8 --zoom-end 13
```

论文编译（仓库根目录）：

```powershell
typst compile --root . .\2026-EgoAnchor-Typst\egoanchor_cn_v4.typ .\2026-EgoAnchor-Typst\pdf\egoanchor_cn_v4.pdf
```

> `pixi run build` 会安装或检查 nvdiffrast、构建 FoundationPose C++ 扩展并生成 FFS ONNX/TRT artifacts，耗时且依赖 CUDA/TensorRT，不要当作轻量验证命令。

Fast-FoundationStereo ONNX/TRT 构建坑：

- PyTorch 2.12 + onnxscript 导出 external data 时，Windows 下直接覆盖已有 `*.onnx.data` 可能报 `PermissionError: [Errno 13] Permission denied`。`Fast-FoundationStereo/scripts/make_onnx.py` 在每次导出前会删除目标 `.onnx` 和同名 `.onnx.data` sidecar，不要移除这一步。

Windows 上 nvdiffrast / FoundationPose C++ 扩展构建坑（`pixi install` / `pixi clean cache` 后一次过不了）：

- nvdiffrast **不放 `[pypi-dependencies]`**：`pixi install` 的 PyPI 源码构建上下文不能可靠安装或刷新系统 MSVC，清缓存后容易在 CUDA 扩展编译阶段找不到可用 `cl.exe`。改由 `pixi run` 下的 `_build-nvdiffrast` 任务安装，已挂进 `build`。缓存里有 wheel 时不重编，所以问题只在 `pixi clean cache` 后暴露。
- Pixi 0.72.1 实测 `depends-on` task 之间**不会重新执行 workspace activation**：activation 在 task 图启动前捕获一次，前置 task 安装 VS Build Tools 后，后续 task 不会自动刷新 `cl.exe` / `INCLUDE` / `LIB`。因此 Windows `_build-nvdiffrast` 在 `pixi.toml` task 内联 PowerShell 中重新初始化 VS2026/MSVC/CUDA 环境；FoundationPose C++ 扩展的 Windows 构建逻辑放在 `FoundationPose/mycpp/build_msvc.py`。
- Windows `[target.win-64.activation.env]` 只放运行时变量，不放 `CL` / `INCLUDE` / `PATH` / `CC` / `CXX` 这类构建变量。Pixi 0.72.1 的 PowerShell `pixi shell` 会把 `CL=/I"%CONDA_PREFIX%\..."` 展开成非法字符串，直接触发 `ParserError`；构建关键变量必须在对应 Windows task 或 `FoundationPose/mycpp/build_msvc.py` 内重新设置。
- Windows task 不要再内联复杂 `cmd /c "call ""%CONDA_PREFIX%\..."" ..."`：远端路径如 `D:\Project\EgoAnchor_Python (2)` 含空格和括号时会被 `cmd.exe` 拆坏，报 `'D:\Project\EgoAnchor_Python' is not recognized`。当前做法是运行时生成临时 `.cmd` 捕获 `vcvars64.bat` 产生的环境，再执行实际构建命令；仓库不要恢复 `scripts/run_msvc2026.cmd` 这类持久外置环境脚本。
- `vs2026_compiler_vars.bat` 不要作为唯一 MSVC 激活入口：当前 conda-forge 脚本不会静态查 `Microsoft Visual Studio\18\BuildTools`，且可能继承错误的 `VSINSTALLDIR=C:\Program Files (x86)\Microsoft Visual Studio\2026\Enterprise\`。Windows `_build-nvdiffrast` 和 `FoundationPose/mycpp/build_msvc.py` 都必须先清理 `VSINSTALLDIR/VCINSTALLDIR/VCToolsInstallDir/VCToolsVersion/VSCMD_*` 等变量，再直接调用已定位的 `vcvars64.bat`。
- CUDA 13 的 `cuda_fp16.h` 会包含 `nv/target`；Windows 下必须把 `%CONDA_PREFIX%\Library\include\targets\x64` 和 `...\cccl` 同时加入构建进程的 `CL` 与 `INCLUDE`。这些变量只在 `_build-nvdiffrast` 和 `FoundationPose/mycpp/build_msvc.py` 内设置；`CL` 里的 `/I` 路径必须写成 `/I"%CONDA_PREFIX%\..."`，否则远端 `D:\Project\EgoAnchor_Python (2)` 这类含空格路径会被 MSVC 拆断，表现为 `fatal error C1083: 无法打开包括文件: "nv/target"`。
- `_ensure-msvc-buildtools` 现在内联在 `pixi.toml`：通过 `vswhere` 和常见安装路径检查 VS2026/18 C++ Build Tools，缺失时调用 `winget install Microsoft.VisualStudio.BuildTools`，由系统弹出管理员确认。VS2026 BuildTools 当前落点可能是 `C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools`，不要误改回只查 `2026` 目录。
- `_build-nvdiffrast` 不注入 `NVCC_PREPEND_FLAGS=--compiler-bindir`：VS2026/MSVC 激活后 `cl.exe` 已在 PATH，torch 构建自带 `--use-local-env` 会让 nvcc 用 PATH 的 `cl.exe`。nvcc 会校验 `-ccbin` 与 PATH cl.exe 是否同一路径，8.3 短路径 vs 长路径字符串不一致会触发 `nvcc fatal: cl.exe in PATH is different than -ccbin`。
- 单独重装：设置 `EGOANCHOR_NVDIFRAST_FORCE=1` 后运行 `pixi run _build-nvdiffrast`；未设置时已安装 `nvdiffrast==0.4.0` 会直接跳过。
- Windows 数值栈固定 `libblas=*openblas`，`scipy` 和 `scikit-learn` 走 PyPI wheel，避免 conda MKL/LLVM OpenMP 与 PyTorch wheel 的 `libiomp5md.dll` 混用触发 `OMP: Error #15`。

## Python 主线

入口：`EgoAnchor_Python/src/run_server.py` → `egoanchor.app.tracking_server`。
配置：`src/egoanchor/config/defaults.toml` 和 `objects.toml`；每个 `.toml` 参数必须同行中文注释。

核心约定：

- 分割默认 `yoloe26`；SAM3 只能显式配置启用，不能改成默认。
- Python 感知链路不根据低分或位姿跳变自动重新 register；显式重获取由 Unity 通过 NATS `reacquire/reset` 命令驱动。
- `pose_jump_translation_m/pose_jump_rotation_deg` 是 TRACK 后硬异常拒绝阈值，触发输出 `TRACK_REJECT` no-pose，不生成可靠性子分，不自动 register。
- command path：`NatsMessageClient → NatsRouter → HandlerRegistry → CommandDedupStore/CommandQueue → TrackingRuntime`；NATS handler 只 parse/validate/dedup/enqueue/ack，pipeline/GPU 状态由单一 `TrackingRuntime` 顺序拥有。
- `network.message_plane.enabled=false` 可用于无 NATS server 的 Python-only debug。
- `CutieMaskTracker` 不直接导入 `torchvision.transforms.functional.to_tensor`；Windows 下 PyPI `torchvision` 自带的图像 DLL 会与 conda Pillow 的同名 DLL 冲突，先导入 `torchvision` 再导入 `PIL.Image` 可能触发 `_imaging` 加载失败。项目内用本地 numpy→torch 张量转换即可。

logging 两种模式：
- **评估 session 模式**（`eval_session_enabled=true`，默认）：在 `data/eval/<session_id>/` 创建共享目录，`header.session_id` 通过 NATS 广播给 Unity 自动配对。
- **普通运行时模式**（`eval_session_enabled=false`）：在 `data/runtime_logs/` 写独立时间戳日志，不与 Unity 配对。

VCD 可靠性评分：`R = V * G_CD`，`G_CD = exp((w_c ln C + w_d ln D) / (w_c + w_d))`；默认 `reproj_weight=0.2`、`depth_weight=0.8`。`color_reprojection=-1` 表示本帧无有效颜色重投影信号，不是坏 pose。`score_depth=0.5` 是 depth 覆盖不足时的中性显示。深度对齐采用绝对-结构联合评估 `D = (1-α)·D_abs + α·D_struct`，`α` 按深度 IQR 自适应（平坦表面回退到纯绝对残差）。

Python 代码地图（关键模块）：

| 路径 | 职责 |
|------|------|
| `config/` | 只读 TOML，不导入 ZMQ/OpenCV/模型 |
| `protocol/` | subject registry、protobuf registry、包级入口 |
| `transport/zmq_topic_subscriber.py` | 通用 ZMQ SUB，只管 socket/multipart/latest-drain |
| `transport/nats_client.py` | 唯一 NATS transport，asyncio 连接/pub/sub/request-reply |
| `routing/` | subject → protobuf parse → handler → reply serialize |
| `handlers/command_handlers.py` | reset/reacquire/control：只 validate/dedup/enqueue/ack |
| `runtime/quest_stream_receiver.py` | ZMQ bytes → Quest Protobuf → latest store |
| `runtime/tracking_runtime.py` | 唯一 pipeline/GPU 状态 owner |
| `runtime/message_factories.py` | PoseObservation → PoseResult；state/command → AnchorStatusEvent |
| `runtime/runtime_log_writer.py` | 集中写 JSONL |
| `perception/quest_pose_pipeline.py` | 组合分割/FFS/FoundationPose/Cutie，输出 camera-space PoseObservation |
| `algorithms/` | 单模型适配层；yoloe26/sam3 都输出统一 `SegmenterResult` |
| `reliability/` | `reprojection.py`（LAB 颜色重投影）+ `depth_alignment.py`（自适应阈值）+ `render_quality.py`（协调渲染）+ `pose_quality.py`（合成总分） |

## Unity 主线

主要链路：

`QuestStreamPublisher / StereoFrameSource / CameraInfoSource` 采集并发 ZMQ → `FramePoseHistory` 记录 capture-time camera pose → `PoseResultReceiver → AnchorRuntimeHub → PoseToAnchorRuntime` 解码并广播 pose → `CameraPoseFrameAligner` 做 OpenCV camera pose 到 Unity world pose → `AnchorPolicyHost` 输出每帧 anchor pose → `DynamicObjectAnchor` 只应用输出 Transform。

Policy 结构：

- `AnchorPolicyHost` 持有 `MotionModel` + `SmoothingStrategy`，维护生命周期，保留内联质量门控（`enableQualityGate`，源码默认 false）。
- `AnchorObservation.MeasurementTimeSeconds`：采集时间轴，用于运动模型/平滑/静止锚定。`LifecycleTimeSeconds`：Unity 到达时间轴，用于 stale/lost 和生命周期状态。**不要用 capture time 刷新生命周期新鲜度**，否则推理耗时较长时高分 pose 到达后会被误判为陈旧触发 reacquire。
- `Policy/Models`：`ConstantVelocityModel`、`KalmanModel`、`OneEuroModel`。
- `Policy/Smoothing`：`BlendStrategy`、`DelayedInterpStrategy`、`RawPassthroughStrategy`。
- `DelayedInterpStrategy` Hermite 切线用 `hermiteTangentChordRatio`（默认 3）限幅，防止急停后样条过冲振铃。延迟目标通过 `Mathf.MoveTowards` 平滑过渡（`MaxDelayChangePerSecond=0.05`），防止 GPU 波动导致延迟突变。

静止锚定（StaticLock）关键坑：

- `EgoAnchorStaticLockModule` 是参数宿主；`StaticLockController` 是纯 C# 控制器，与 model × strategy 正交。挂模块并 `lockEnabled=true` 是 EgoAnchor 方法，不挂或关闭是 baseline。
- 进入锁定看 `enterSpeedMps`、`enterAngSpeedDps`（设为噪声地板约 1.5 倍，当前 22°/s）、`dwellSeconds`、`minScore`。线/角速度阈值必须高于真实噪声地板，太低会永不锁定。
- 漂移租绳量的是 `distance(obsConsensus, anchorOrigin)`，不是单帧观测也不是 `lockedPose`——改成 `lockedPose` 会导致慢速持续移动时永不解锁。
- **旋转解锁租绳 `unlockDriftDegrees` 必须高于物体旋转估计噪声地板，否则静止时噪声顶破租绳 → 反复误解锁（锁不稳）**。实测 controller 静止+头静止时，一个锁生命周期内 obsConsensus 旋转摆幅 p50 5.3°/p90 9.8°，故租绳从 5° 抬到 12°（贴合代码注释里已知 ~13° 旋转噪声，仍低于 CUSUM 天花板 `unlockEvidenceDegrees=20°`，真慢转仍能解锁）。位置租绳 `unlockDriftMeters=0.015` 实测正常，不动。定位手法：把 `StaticLockController` 逻辑离线重放在采集的观测流上，统计每次解锁走哪条分支（drift_rot/drift_pos/cusum/speed/lowscore）。
- `headSettleSeconds` 只在头已停下但沉降计时未完成的窗口内冻结"判物体在动"的证据；头动期间绝不冻结——那会把真动也锁死。
- 距离自适应只放大位置通道，不放大旋转通道。
- `LatestStaticLocked`、`motion_model`、`smoothing_strategy`、`quality_gate`、`has_output_pose`、`output_pos`、`output_rot` 是当前 eval/runtime 契约，不要改回旧名。

低分/track-loss 自动 reacquire：

- `AnchorPolicyHost` 只置 `wantsServerReacquire`；`PoseToAnchorRuntime` 透传；`AnchorRuntimeHub` 统一 fan-in，用唯一 `reacquireCommandClient` 发 NATS reacquire。
- 源码默认 `enableLostReacquire=true`、`enableLowScoreReacquire=true`；持续低总分超过 `lowScoreReacquireThreshold=0.45` 且持续 `0.6s` 后请求 Python 重新 register。
- 不要让 leaf runtime 或 policy 自持 command client。

eval 字段契约（改 schema 必须同步 Unity writer、reader、Python eval 工具和 AGENTS）：

- JSONL 字段：`motion_model` / `smoothing_strategy` / `quality_gate` / `has_output_pose` / `output_pos` / `output_rot`。
- proto 当前字段名：`color_reprojection`、`render_quality_evaluated`。
- `score_reprojection`、`score_depth`、`score_mask` 保持当前名；`score_phase`、`score_jump`、`score_reject`、`score_confidence` 已 reserved，不要恢复。
- `LatestResidualMeters/Degrees` 当前返回 NaN 是为保留 eval schema，不要因此删除 public API。

Unity 代码地图（关键模块）：

| 文件 | 职责 |
|------|------|
| `Transport/ZmqTopicPublisher.cs` | NetMQ PUB socket，发 `[topic_utf8, payload]` |
| `Client/NatsControlClient.cs` | NATS 客户端，sub PoseResult/StatusEvent/Heartbeat |
| `Quest/StereoFrameSource.cs` | 左右 Passthrough 采集、JPEG 编码、构造 QuestStereoFrame |
| `Alignment/FramePoseHistory.cs` | `frame_id → capture-time camera pose` 环形缓存（frame-aligned anchor 关键） |
| `Alignment/CameraPoseFrameAligner.cs` | OpenCV camera pose + frame history → Unity world pose |
| `Client/PoseResultReceiver.cs` | 主线程 latest-drain，解析 PoseResult |
| `Runtime/AnchorRuntimeHub.cs` | pose/status/heartbeat fan-out；low-score reacquire fan-in |
| `Runtime/PoseToAnchorRuntime.cs` | camera-space pose → world pose，提交 policy，LateUpdate(-50) 推进 |
| `Runtime/DynamicObjectAnchor.cs` | 只读 `TryGetOutputPose` 并应用 Transform |
| `EgoAnchorEval/AnchorEvalRecorder.cs` | capture/render 两条 JSONL；config 摘要通过反射收集 |

## 协议与生成输出

协议源（唯一真理）：

- `EgoAnchor_Protocol/subjects.v1.json`
- `EgoAnchor_Protocol/proto/protocol/v1/{common,quest,anchor}.proto`

生成输出（不要手改）：

- Python：`EgoAnchor_Python/src/egoanchor/protocol/v1/*_pb2.py` + `subjects.v1.json` 副本
- Unity：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/Generated/*.cs` + `SubjectNames.cs`

## 论文与评估

论文源：`2026-EgoAnchor-Typst/egoanchor_cn_v5.typ`（当前中文主稿 v5）；参考文献：`egoanchor_cn.bib`；代码事实文档：`egoanchor_code_derived_technical_flow.md`。`docs/architecture/` 已完全删除，系统架构统一维护在 `egoanchor_code_derived_technical_flow.md`。

论文术语基准（后续 AI 不要擅自改）：动态真实物体锚定、目标语义分割、双目立体几何重建、可靠性评分、时空对齐、运动估计与平滑、静止锚定、生命周期管理。

**论文 RQ 结构**（2026-07-07 定稿）：
- RQ1：静态锚定质量——评估静止场景（长时静止观察、遮挡恢复）下的精度、稳定性、鲁棒性；消融静止锚定机制（Full vs. No-StaticLock，仅在静止观察场景下对比）
- RQ2：动态追踪能力——评估动态场景（慢速平移、快速挥动、旋转）下的追踪精度、时延影响量化（验证 Δe = v·τ 线性模型）、响应延迟分解
- RQ3：应用泛化能力——覆盖多类日常刚性物体与典型 MR 任务（至少 3 个代表性刚体），实验在典型室内光照条件下进行

**实验表述规范**（2026-07-07）：
- 消融实验配置用斜体标签：*Full*、*No-StaticLock*、*Frame-aligned*、*Arrival-aligned*
- 不使用"条件"描述实验配置，用"系统配置"或"变体"
- 不用"+"罗列组件（如"运动估计+时序平滑+静止锚定"），改为"包含运动估计、时序平滑与静止锚定"
- RQ2 不验证"时空对齐是否有效"（太显然），而是验证时延-误差线性关系模型（Δe = v·τ）
- 避免冗余表述："进行"、"通过"、"该实验旨在"等啰嗦句式应简化或删除
- RQ1的消融实验只在静止场景下进行，不涉及动态场景

评估数据目录：`data/eval/<session_id>/`（原始日志，Python/Unity 配对）；`data/research/rq1|rq2|rq3/`（分析产物，已废弃）。

### RQ1 分析框架（2026-07-07 重构完成）

**RQ1 只评估两个静止场景**：`static_observation`（长时静止观察）、`occlusion_recovery`（遮挡恢复）。slow_translation / fast_motion / rotation 已移交 RQ2，不在 RQ1 采集或分析。消融为 *Full* vs *No-StaticLock* 双变体同帧录制。

**架构原则**：保留已验证的契约层（Unity `EvalRecorder`/`EvalJson`/`EvalSession` ↔ Python `eval/io`）与共享分析引擎（`eval/core`/`eval/metrics`/`eval/report`）。RQ1 只做「场景语义收窄 + 论文视图组织」，不重算任何指标。

**双变体录制**：`EvalRecorder.variants` 两项——`variants[0]` label=`Full` isPrimary=true（Kalman + DelayedInterp + StaticLock 开），`variants[1]` label=`No-StaticLock` isPrimary=false（与 Full 逐项相同，仅 `EgoAnchorStaticLockModule.lockEnabled=false`）。两变体订阅同一 pose 流（同 `AnchorRuntimeHub.runtimes`）、同一渲染 tick，写进同一 `unity_output` 行的 `variants` 数组——完美同步，无需时间对齐。场景 `EgoAnchor-RQ1.unity` 的 No-StaticLock 分支（GameObject `AnchorObject - NoStaticLock`，fileID 段 700000001–010）是直接编辑场景 YAML 添加的（Unity MCP 不能持久化保存、也不能写 `List<EvalVariant>`/`List<runtime>` 引用字段）。

**分析代码**：`src/egoanchor/eval/research/rq1/analyze.py`（薄封装，复用共享引擎；旧 `data_loader/gt_alignment/metrics/plot_compact/plot_comprehensive/run_analysis/run_rq1` 已全部删除）。核心 API：
- `RQ1_CONDITIONS = ("static_observation", "occlusion_recovery")`
- `synthesize_occlusion_markers(output)` - 从 `rq1_metric=="occlusion_recovery"` 连续段起点在内存合成 `event_markers`（Unity 契约层恒写空数组，此处不改契约层地补齐恢复时间输入）
- `filter_rq1_tables(tables)` - 每张含 `condition` 列的 summary 表过滤到 RQ1 两场景
- `run_rq1_analysis(session_dir, *, report_dir=None, figs_dir=None)` - 全链路：load → 注入合成 marker → `compute_all_metrics` → 写表/图 → 返回过滤后的 tables
- `main(argv)` - CLI

**运行命令**：
```bash
cd EgoAnchor_Python
pixi run python -m egoanchor.eval.research.rq1.analyze --session-dir data/eval/<session_id>
```
默认 `report_dir=<session_dir>/report`、`figs_dir=2026-EgoAnchor-Typst/figs/rq1`。

**测试**：`src/egoanchor/eval/tests/test_rq1_analyze.py`（marker 合成 + 场景过滤，依赖 metrics 引擎）；`src/egoanchor/eval/tests/test_rq1_plot.py`（纯绘图层，无 cv2，含"默认完整序列不裁剪"用例）。`analyze.py` 直跑时 bootstrap 用 `Path(__file__).resolve().parents[4]`（=`src`）加入 `sys.path`。

**误差口径：实时逐帧对比，不做回溯时延对齐**。误差取渲染时刻锚点输出（`unity_output` 的 `variants[].output_pos/rot`）与同一 tick 采样的控制器真值（`ResolveGtPose(monoMs)` 在 `LateUpdate` 里取）逐帧比较——Unity 侧就是实时同刻采样，Python `eval/metrics/anchor_error.py` 也不做任何时间平移。这样误差如实包含端到端时延影响，与 RQ2 的时延分析口径一致。不要在 RQ1 引入「按 frame_id 回溯到采集时刻真值」的补偿对齐（那会抹掉时延效应，也与代码事实不符）。

**static 图与正文取稳态窗口**。整段 static_observation 含启动沉降（前 ~10s 偏高）与偶发的一次性头动尖峰（~38s 冲到 17mm）。`analyze.write_rq1_figure` 用 `STATIC_STEADY_WINDOW_S`（当前 `(50.0, 75.0)`，相对该场景起点）只裁 static 列（遮挡列完整保留，其尖峰正是 No-StaticLock 缺陷的展示）；论文正文 static 数字与图口径一致，也取该窗口统计。改窗口须图文同步。图重生成绕开 cv2：直接读 `report/anchor_error_detail.csv` 复刻绘图逻辑即可（`egoanchor` 包导入链带 cv2）。

**论文更新**：§6.1 RQ1 结果用实测值替换占位符，图 `<fig:rq1-static>` 换成 `figs/rq1/*.pdf`；配置用斜体 *Full* / *No-StaticLock* 与「系统配置/变体」表述，不用「条件」；正文措辞为「实时逐帧对比」，不用「时延补偿对齐」。当前实测 session：`20260707_141751_controller_right`（静止约 70s、遮挡约 64s，全程不裁窗）。static_observation（全程）：*Full* 平移中位 5.8 mm / P95 6.6 mm、旋转中位 2.1° / P95 2.9°；抖动 *Full* 0.04 mm vs *No-StaticLock* 0.71 mm 约 18×、旋转抖动 1.71° vs 2.80°。occlusion_recovery（全段）：*Full* 平移中位 5.6 mm / P95 6.7 mm、旋转 P95 4.6°；*No-StaticLock* 平移 P95 19.3 mm 约 2.9×、旋转 P95 17.2°、屏幕漂移 1.6 vs 7.2 px 约 4.5×；生命周期 Coasting 48% / Searching 32% / Frozen 15% / Lost 5%。历史 session `20260707_122900`（曾取 50–75s 稳态窗）已弃用。

RQ1 分析链路：`eval/research/rq1/analyze.py` → `eval/core` + `eval/metrics` + `eval/report`。关键约定和历史坑：

- **GT 有效性只信任 Unity 写的 `gt_pose_valid`**。Unity `EvalRecorder` 已用 keep-alive 处理手柄 sleep（静止休眠时复用上次有效 pose 并保持 `gt_pose_valid=true`）；`eval/core/gt_filter.py` 因此不再做「速度≈0 判休眠剔除」或「首次运动前自动砍开头」这类速度启发式——那会和 keep-alive 正面打架，把合法长时静止帧误删。不要恢复旧的 `_detect_frozen`/`suggest_startup_cutoff`/`frozen_window_s`。
- **RQ1 场景分组走 `rq1_metric` 手动标注**。`io/log_loader.py::label_conditions` 优先用 manifest `condition_spans`；当 `condition_spans` 为空（RQ1 当前采集就是空）则回退到 Unity 按键标注的 `rq1_metric` 作为 `condition`，使各场景各成一行。RQ1 只标注 static_observation / occlusion_recovery 两种；`analyze.filter_rq1_tables` 再把 summary 表过滤到这两种。所有 metric 模块统一按 `condition × label` 聚合（`label` 即变体 Full / No-StaticLock）。
- **occlusion_recovery 段不需要 GT**（遮挡期本就无 GT 语义），恢复时间靠 manifest `event_markers` 驱动 `metrics/recovery.py`，不靠 GT 误差。
- `eval/core/run_eval.py` 已从包根迁到 `core/`，脚本直跑时 bootstrap 把 `parents[3]`（=`src`）加入 `sys.path` 才能解析 `egoanchor` 包。
- **录制状态单一真理是 `EvalSession`**。`EvalSession._recording` 是唯一录制开关；UI（`RQ1StatusUI`）和 `EvalRecorder` 都读它。`EvalSession` 有序列化的 `sessionStarted`/`sessionStopped`（`UnityEvent`，Inspector 可视化挂接），在 `StartSession`/`StopSession` 触发，供 RQ1/RQ2/RQ3 在会话边界做副作用（如清空指标标记）。
- **`RQ1MetricSelector`（原 `RQ1MetricRecorder`，已更名去混淆）只持有「当前指标」，不拥有录制状态、不写文件**。它只暴露 `CurrentMetric`/`CurrentMetricDuration`/`SetMetric`/`ClearMetric`；`SetMetric` 无任何门槛，按 1/2 永远直接生效。`EvalRecorder`（唯一真正写 JSONL 的）每帧直接读 `CurrentMetric`（未按键即 `none`），字段名 `rq1Selector`。历史坑：该组件曾叫 `RQ1MetricRecorder` 且自持独立 `_recording`，只在 F7 回调里 `StartRecording`，而 `autoStart`（收到首个 PoseResult 自动录制）只翻转 `EvalSession._recording`，导致 UI 显示 Recording 但按键 1/2 报「未录制状态下无法设置指标」，必须手按 F7 才生效。已彻底删除该重复状态——不要恢复 `IsRecording`/`StartRecording`/`StopRecording`，也不要因为「两个都叫 Recorder」把 `RQ1MetricSelector` 当成 `EvalRecorder` 的重复而删除（它是 Python 端按场景分组的唯一标签来源）。
- `RQ1InputHandler` 只做 1/2/0/F7/F8 输入映射：1 调 `SetMetric(StaticObservation)`、2 调 `SetMetric(OcclusionRecovery)`、0 调 `ClearMetric`、F7/F8 调 `EvalSession.StartSession`/`StopSession`。旧的 3/4/5 键（slow/fast/rotation，已移交 RQ2）已删除。旧的一键搭场景编辑器脚本 `RQ1/Editor/RQ1SceneBuilder.cs` 已删除（构建的中文面板与运行时英文文本漂移），场景直接编辑 `.unity` YAML / Unity MCP 搭建。
- 验证：`pixi run python -m unittest discover -s src -p "test_*.py" -t src`（eval 测试需 `-t src` 才能解析包）。

## 环境与依赖

- Python：`EgoAnchor_Python/pixi.toml`，Python 3.14、CUDA 13.2 conda 组件、PyTorch 2.12.1 cu130、TensorRT 11、ultralytics/YOLOE、nats-py、Cutie、SAM3 等；CUDA 13.2 不在 `workspace.platforms` 内联，Windows 用精确 conda 组件声明，Linux 用 `cuda-toolkit`。4090 Linux 当前 Pixi 仍不接受 `platforms = [{ platform = "linux-64", glibc = "2.35" }]` 这种 inline table，新 Pixi 0.72+ 又会对 `[system-requirements]` 报弃用 warning；为兼容两台当前机器，`pixi.toml` 暂时保留 `platforms = ["win-64", "linux-64"]` 和 `[system-requirements] libc = { family = "glibc", version = "2.35" }`。只有确认 4090/5090 都升级到支持 rich platform entry 的 Pixi 后，才把 glibc 迁回 `platforms`。Pixi 0.72+ 下 `nvdiffrast` 不放进 `[pypi-dependencies]`，必须由 `pixi run _build-nvdiffrast` 在激活环境内以 `--no-build-isolation --no-deps` 编译安装，从而复用当前环境的 torch/CUDA/MSVC。Windows 使用 `vs2026_win-64` 提供 `vswhere` 和 MSVC activate.d 脚本；`_ensure-msvc-buildtools` 的 winget 检查/安装逻辑直接内联在 `pixi.toml`，`_build-nvdiffrast` 在 `pixi.toml` 内联 PowerShell 中刷新 VS2026/MSVC/CUDA，`_build-fp` 调用 `FoundationPose/mycpp/build_msvc.py`；不要把这些构建变量放进 activation，否则会破坏 `pixi shell`。OpenCV Python 绑定统一使用 PyPI `opencv-python`，不要同时加入 conda `opencv/libopencv` 或 PyPI `opencv-contrib-python`，避免 Pixi 0.72+ 的覆盖警告。Windows 重建 `.pixi/envs/default` 失败时先关闭 VS Code Python LSP 和残留 Python 进程，避免文件占用。
- 环境配置和跨平台安装步骤统一写在 `EgoAnchor_Python/docs/windows-prerequisites.md`；后续若再改 Python / CUDA / Torch / TensorRT / MSVC / build task，同步更新这份文档。
- Unity：`EgoAnchor_Unity/Packages/manifest.json`，主线依赖 Google.Protobuf、NATS.Net、NetMQ。

## Git 忽略规则

`.gitignore` 按目录分层维护：父级只管本层；子目录有自己 `.gitignore` 时权重/缓存/构建/日志由子目录接管。根层只管根层编辑器状态、Blender 本地文件和本地专利工作区，不写 Python/Unity/论文目录内部产物。

## Python 远端同步

- `EgoAnchor_Python/mutagen.yml` 管理远端同步；RTX5090 当前是 Windows 11 远端，账号 `BNU@172.24.247.32`，项目目录 `D:/Project/EgoAnchor_Python (2)`。本机是唯一源码源头，source push 使用 `one-way-replica`，远端日志拉回使用 `one-way-safe`，远端改动不回流。
- 远端日志通过 `logs-5090` 拉回 `data/eval/`；三台机器同名日志会冲突，保持 `one-way-safe`。
- 首次 `mutagen project start` 前确保远端 `data/eval/` 和 `data/runtime_logs/` 已存在，否则日志拉回会话启动失败。
- 本机 SSH 默认公钥 `C:\Users\zheliku\.ssh\id_ed25519.pub`；若沙箱里 `ssh` 被覆盖，直接调用 `C:\Windows\System32\OpenSSH\ssh.exe`。Windows 远端必须启用 OpenSSH Server。
- **Windows 中文（GBK/936）远端 Mutagen 握手坑（2026-07-09 实测定位，5090 迁 Win11）**：`remote did not return UTF-8 output` 是**二次错误**——真正的失败是 agent 引导失败，Mutagen 去读远端 stderr 解释原因，发现 stderr 是 GBK 非 UTF-8 才抛这句（源码 `pkg/agent/dial.go` 用 `utf8.Valid` 校验首行）。两个独立病根，必须同时修：
  1. **`HKLM\SOFTWARE\OpenSSH\DefaultShell` 必须设为 `cmd.exe`，不能是 PowerShell**。Mutagen 的 Windows agent 引导用相对路径命令 `.mutagen/agents/<ver>/mutagen-agent synchronizer`，cmd.exe 直接当相对路径可执行文件跑，PowerShell 不认相对路径命令（会报 `is not recognized as ... cmdlet`）→ agent 永远起不来。对应 GitHub issue #251/#252，社区收敛结论就是换回 cmd.exe。改完 `Restart-Service sshd` 即可（无需重启机器）。
  2. **系统级开启 UTF-8**（设置→语言→管理语言设置→勾 "Beta: 使用 Unicode UTF-8"，需重启），把系统代码页从 936 变 65001。否则任何 GBK 输出仍会污染 Mutagen 读取的首行。
  - 反例（已作废的旧结论）：早期给 5080 记的"cmd.exe 不行、要改 PowerShell"是错的，正好写反，曾把 5090 迁移排查带偏。PowerShell 作为 DefaultShell 才是 agent 引导失败的直接原因。
  - PowerShell profile 强制 `[Console]::OutputEncoding=UTF8` 这条路不可靠：BNU 执行策略 `Restricted`/`Undefined` 会拒绝加载 profile，且拒绝时抛的 GBK 报错本身就是首行污染源。

## 不要回退

- 不恢复旧 v1/v2 目录、MessagePack 链路、旧计划目录或早期 NATS 图像流实验。
- 不恢复旧默认端口 `5556/5557`；保持 Unity → Python `15557`。
- 不恢复 ZMQ PUSH/PULL、JSON pose、业务分片、单图 legacy payload。
- 不恢复旧 Python 入口和旧 Unity `StaticStereoEncoder.cs`。
- 不把 SAM3 设为默认分割后端。
- 不恢复旧 Gate/Estimator/Output 三模块拆分或旧 `has_stable/stable_pos/stable_rot`、`estimator_module/output_module/gate_module` 字段。
- 不添加旧字段/旧路径兼容层；重构时直接迁移当前主线代码和场景。

## AGENTS.md 维护规则

- 只写当前事实、核心约定、后续路线和历史坑；不追加流水账或 changelog。
- 不修改 `USER-MAINTAINED-REQUIREMENTS` 区块。
- 大改后同步入口、模块职责、协议字段、配置名、验证命令和关键坑。
- 若代码事实推翻旧描述，直接改旧条目，不追加相互矛盾的新条目。
- 本机已启用 `superpowers@openai-curated`；后续 AI 若会话暴露该插件技能，应先调用 `using-superpowers` 再处理任务。
