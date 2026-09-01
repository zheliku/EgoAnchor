# EgoAnchor

EgoAnchor 是一套面向透视混合现实（PMR）的零样本动态物体锚定系统。它要解决的问题很具体：开放视觉后端输出的异步 6DoF 位姿，并不等于头显里可以直接绑定的 MR 锚点。视觉位姿低频、到达时刻滞后于画面、质量参差，直接拿去挂虚拟内容，物体就会抖动、漂移或在遮挡后跳位。EgoAnchor 把这些观测转换成消费级 MR 应用可以持续绑定的世界系对象锚点。

系统分两层运行：

- **感知后端**（外部 GPU 工作站，Python）：语义初始化 → 时序分割 → 立体几何重建 → 零样本位姿估计，并为每个输出候选给出逐观测的 VCD 可靠性评分。
- **锚定运行时**（Quest 3 一侧，Unity）：用采集时刻对齐把位姿搬回正确的时间点，再经历史状态查询、静止锚定与分级有效性管理，输出逐帧稳定的锚点位姿。

三个时刻贯穿两层：图像**采集**时刻 `t_f` 决定空间语义，候选**到达**时刻 `t_a` 只说明何时收到，**渲染**时刻 `t_r` 决定何时需要输出锚点。核心机制都围绕"把位姿放回 `t_f`、把输出对齐到 `t_r`"展开。

## 仓库结构

| 目录 | 内容 |
| --- | --- |
| `EgoAnchor_Python/` | 感知后端全部 Python 代码：模型适配、感知流水线、可靠性评分、NATS/ZMQ 传输、离线评估与论文图表生成 |
| `EgoAnchor_Unity/` | Quest 3 头显端 Unity 工程：双目图像采集、帧对齐、四个时序策略、锚定状态机、实验录制 |
| `EgoAnchor_Protocol/` | 两端通信契约的唯一事实源：`.proto` 消息定义、subject 表 `subjects.v1.json`、代码生成脚本 |

每个子目录有自己的 README，写明各自的配置与运行步骤。

## 环境要求

硬件：

- Meta Quest 3 一台（经 Quest Link 连到 PC）。
- 一台带 NVIDIA RTX GPU 的 PC：正式结果取自 RTX 5090；开发期也在 RTX 3090 / 4090 / 5080 Laptop 上跑通过。GPU 同时承担 Unity 渲染与感知推理。
- 局域网连接（如果感知后端单独部署在一台机器上）。

软件：

- Windows 10/11 或 Linux（x86_64）。Windows 是主力开发与采集环境。
- [pixi](https://pixi.sh)（Python 环境与任务管理）。
- NVIDIA 驱动 + CUDA 13.x 运行时；首次构建需要 MSVC/CUDA 编译工具链（pixi 任务会自动准备 Windows 侧的 VS Build Tools）。
- [nats-server](https://nats.io)（消息面通信）。
- Unity **6000.3.11f1**（含 Meta XR SDK 203.0.0）。

## 快速开始

按顺序做三件事：起 NATS、起 Python 感知后端、在 Unity 里进 Play。

### 0. 准备第三方依赖

本仓库只包含我们自己的代码。感知链路依赖的几个开源项目与模型权重需要自行获取（详见 `EgoAnchor_Python/README.md` 的"第三方依赖"一节）：

- `Cutie`（视频目标分割，MIT）——`pixi install` 时作为 editable 依赖，必须先放到 `EgoAnchor_Python/Cutie/`。
- `Fast-FoundationStereo`、`FoundationPose`、`sam3`——按各自上游仓库获取，放到 `EgoAnchor_Python/` 同名目录（sam3 为可选模块，默认不启用）。
- 模型权重放入 `EgoAnchor_Python/weights/`（YOLOE-26 分割权重等）。
- 目标物体的三维模型已经在仓库里：`EgoAnchor_Python/data/model/`。

### 1. 启动 NATS

仓库根目录的 `egoanchor.conf` 是本地开发配置（只监听 127.0.0.1，payload 上限放宽到 8 MB 以容纳双目 JPEG）：

```bash
nats-server -c egoanchor.conf
```

### 2. 启动 Python 感知后端

```bash
cd EgoAnchor_Python
pixi run default          # 用默认物体（cube）启动
pixi run blue_mouse       # 或指定任一已注册物体
```

首次运行会自动创建 conda/pixi 环境；第一次跑通前还需要 `pixi run build` 编译 nvdiffrast、FoundationPose C++ 扩展并生成 TensorRT 引擎（见 `EgoAnchor_Python/README.md`）。启动后会出现 OpenCV 调试窗口，按键 `1/2/3/4` 切阶段、`r` 重置、`s` 保存快照、`v` 录制视频、`q` 退出。

### 3. Unity 头显端

1. 用 Unity 6000.3.11f1 打开 `EgoAnchor_Unity/`，等待编译。
2. 通过 NuGetForUnity 还原 NuGet 包（Unity 菜单 NuGet → Manage NuGet Packages → Restore）。
3. 打开场景 `Assets/Scene/EgoAnchor.unity`。
4. 在场景中的 `ServerEndpointConfig` 组件上选择感知后端所在机器的 IP 预设（或勾选 Custom 填 IP）。
5. 连上 Quest 3（Quest Link），进 Play。

此时头显里应当能看到被追踪物体上的锚点与坐标轴；Python 侧的调试窗口同步显示分割、深度与位姿结果。

## 端口与消息

| 平面 | 通道 | 方向 | 内容 |
| --- | --- | --- | --- |
| Data | ZMQ PUB/SUB，端口 `15557` | Unity → Python | 双目 JPEG 帧、相机内参，latest-only |
| Message | NATS Core pub/sub | Python → Unity | `PoseResult`、锚点状态、心跳 |
| Command | NATS request/reply | Unity → Python | reset / reacquire / control，`request_id` 幂等 |

Python 只输出 camera-space 位姿；Unity 用 `frame_id` 回查采集时刻的相机位姿并复合成世界系锚点。协议细节见 `EgoAnchor_Protocol/README.md`。

## 物体注册

新增一个可锚定物体需要两步：

1. 把物体三维模型（GLB/STL）放入 `EgoAnchor_Python/data/model/`。
2. 在 `EgoAnchor_Python/src/egoanchor/config/defaults.toml` 增加一段 `[objects.<name>.*]`，至少给出 `mesh_path` 与分割器参数；每个参数行末的中文注释说明了取值含义。

之后就能用 `pixi run python src/run_server.py --object <name>` 启动。

## 离线评估

实验数据采集（Unity 侧 `EvalSession`）与论文图表生成都从 `EgoAnchor_Python` 的统一入口进入：

```bash
pixi run eval status        # 查看数据与批次状态
pixi run eval validate all  # schema-v2 校验
pixi run eval analyze all   # 生成指标、图与 LaTeX 表
pixi run replay --help      # 定性轨迹图（独立采集源）
```

完整流水线说明在 `EgoAnchor_Python/docs/analysis_pipeline.md`，目录契约在 `docs/data_layout.md`，定性回放手册在 `docs/qualitative_replay.md`。

## 协议再生成

改了 `.proto` 或 `subjects.v1.json` 之后，在仓库根目录执行：

```bash
pixi run pwsh -File EgoAnchor_Protocol/tools/generate_proto.ps1
```

脚本要求 PATH 里有 `protoc`，会同时生成 Python 侧 `*_pb2.py` 与 Unity 侧 `Generated/*.cs`、`SubjectNames.cs`。生成产物不要手改。

## 测试

```bash
# Python（在 EgoAnchor_Python 下）
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src

# Unity（在仓库根目录）
dotnet build "EgoAnchor_Unity/EgoAnchor.Tests.csproj" --no-restore
dotnet build "EgoAnchor_Unity/EgoAnchor.csproj" --no-restore
```

Unity 内的 EditMode 测试也可以从 Test Runner 运行。

## 边界与前提

- 系统需要目标物体的三维模型；"零样本"指不需要为每个物体训练或标定，不是适用于任意对象。
- "纯视觉"只修饰物体位姿估计链路；整套系统仍依赖外部 GPU、局域网与头显平台自身的头部追踪。
- 实验中的控制器位姿是平台参考位姿，与头显共享追踪系统，不是外部光学真值。

## 第三方组件

感知链路的上游项目各自带着自己的许可，随获取方式分发，不在本仓库内再分发：Cutie（MIT）、Fast-FoundationStereo 与 FoundationPose（NVIDIA 自有条款）、SAM3（Meta SAM License）。Unity 工程使用了若干 Asset Store 插件（HighlightPlus、Proxima 等），再分发需遵守其授权条款；`Runtime/LineRenderer3D.cs` 改编自 survivorr9049/LineRenderer3D（MIT），出处保留在文件头。发布前的完整清单见 [OPEN_SOURCE_CHECKLIST.md](OPEN_SOURCE_CHECKLIST.md)。

## 引用

本仓库是论文 EgoAnchor（IEEE VR 2027 投稿）的配套代码。论文定稿后会在这里补上引用条目；代码计划随论文发表开源。
