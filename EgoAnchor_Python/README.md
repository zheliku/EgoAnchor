# EgoAnchor_Python

EgoAnchor 的感知后端与离线评估代码。运行时侧负责接收 Quest 双目流、执行零样本位姿估计、输出带可靠性评分的候选位姿；离线侧负责把两端日志整理成实验指标、论文图表与 LaTeX 表格。

环境与快速启动见仓库根目录 [README](../README.md)，本文件只展开 Python 侧细节。

## 代码结构

```
src/
├── run_server.py            # 运行入口（薄壳，转调 egoanchor.app）
└── egoanchor/
    ├── algorithms/          # 各上游模型的适配器：YOLOE-26、SAM3、Cutie、Fast-FoundationStereo、FoundationPose
    ├── perception/          # Quest 双目解码/标定、QuestPosePipeline 组合、异步分割 worker
    ├── reliability/         # VCD 评分：渲染质量、深度对齐、重投影、加权几何均值
    ├── runtime/             # TrackingRuntime 状态机、候选日志、eval session 配对、命令队列
    ├── app/                 # 主循环与 OpenCV 调试窗口
    ├── transport/           # ZMQ 订阅、NATS 客户端与 Protobuf 发布器
    ├── protocol/            # subject 契约与 protobuf 生成代码（勿手改）
    ├── routing/ handlers/   # NATS 路由与命令处理（parse/validate/dedup/enqueue/ack）
    ├── config/              # defaults.toml 全部运行参数（每行带中文注释）
    ├── diagnostics/         # 调试视图、图像工具、运行时事件日志
    ├── eval/                # 离线评估：schema-v2、QC、实验一/二/三分析与论文产物
    ├── qualitative_replay/  # 定性轨迹图离线管线
    └── utils/ visuals/      # 日志门面、数学工具、论文配色
```

分层约束：`config/` 不导入模型与网络代码；`transport/` 只管传输；`routing/`、`handlers/` 不碰 GPU；`runtime/tracking_runtime.py` 是流水线的唯一 owner；`eval/` 与运行时服务互不依赖（运行时不会因绘图库缺失而失败）。

导入规范：包外一律走包级入口（`from egoanchor.algorithms import ...`），不深入到具体模块文件；包内部用显式 re-export。

## 第三方依赖

仓库只包含我们自己的代码，以下组件需要自行获取。`pixi.toml` 顶部与 `docs/windows-prerequisites.md` 有更完整的环境说明。

| 组件                                                                    | 放置位置                                    | 说明                                                                                        |
| ----------------------------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------- |
| [Cutie](https://github.com/dvlab-research/Cutie)                         | `EgoAnchor_Python/Cutie/`                 | **必需**。`pixi.toml` 里以 editable path 依赖声明，缺失则 `pixi install` 直接失败 |
| [Fast-FoundationStereo](https://github.com/NVlabs/Fast-FoundationStereo) | `EgoAnchor_Python/Fast-FoundationStereo/` | 双目深度主链路；需要其权重`weights/23-36-37/model_best_bp2_serialize.pth`                 |
| [FoundationPose](https://github.com/NVlabs/FoundationPose)               | `EgoAnchor_Python/FoundationPose/`        | 零样本 6DoF 位姿估计                                                                        |
| [SAM3](https://github.com/facebookresearch/sam3)                         | `EgoAnchor_Python/sam3/`                  | 可选分割器，默认不启用（`defaults.toml` 的 `type = "sam3"` 行被注释）                   |
| nvdiffrast                                                              | 由`pixi run build` 自动从 GitHub 安装     | VCD 渲染依赖的 CUDA 扩展                                                                    |
| YOLOE-26 权重                                                           | `EgoAnchor_Python/weights/`               | `yoloe-26{m,l}-seg.pt` 等；按 `defaults.toml` 中 `model_path` 的名字放置              |

## 环境搭建

```bash
pixi install        # 解析 pixi.lock 并创建 conda/pixi 环境（需要 Cutie 就位）
pixi run build      # 首次运行：安装 nvdiffrast、编译 FoundationPose C++ 扩展、生成 TRT 引擎
```

Windows 侧 `pixi run build` 会先检查 VS 2026 Build Tools（缺失时经 winget 自动安装），再在 MSVC/CUDA 环境里编译。这些步骤只在环境变化后需要重跑。

## 运行

```bash
pixi run default              # 默认物体（cube）
pixi run blue_mouse           # 任一已注册物体（pixi.toml 中每物体一个任务）
pixi run python src/run_server.py --object stapler --log DEBUG
```

CLI 参数：`--config` 指定 TOML 覆盖（默认用包内 `defaults.toml`）、`--object` 选择目标物体、`--log`/`--log-color` 控制日志。

两种数据落点：普通调试运行写 `data/runtime_logs/`；当 Unity 侧 `EvalSession` 发起正式会话并通过 header 配对后，写 `data/eval/<session_id>/`（schema-v2 固定文件集）。

调试窗口按键：`1/2/3/4` 切换运行阶段，`r` 重置注册，`s` 保存当前 pose/VCD 快照 PNG，`v` 开关 12 路异步 MP4 录制，`q`/ESC 退出。

## 配置

`src/egoanchor/config/defaults.toml` 是唯一的运行参数入口，198 个参数每行末尾都有中文注释。物体差异不单独建文件：`--object <name>` 会把 `[objects.<name>.*]` 子树合并到默认配置之上（mesh 路径、分割器参数等），合并后该子树从命名空间剔除。

## 离线评估

```bash
pixi run eval status            # 数据、缓存与批次状态
pixi run eval validate <target> # schema-v2 校验
pixi run eval analyze <target>  # 生成指标、图、LaTeX 表（target: all / exp1-2 / exp3）
pixi run eval copy-assets <target>  # 事务性复制到论文目录
pixi run eval data <target>     # 预处理/工作簿子命令
```

退出码约定：文件系统/工具错误为 1，批次、schema、QC 或论文输入契约失败为 2。完整手册：[docs/analysis_pipeline.md](docs/analysis_pipeline.md)；目录契约：[docs/data_layout.md](docs/data_layout.md)。

定性轨迹图（独立采集源，不读正式评估数据）：

```bash
pixi run replay --help
```

手册：[docs/qualitative_replay.md](docs/qualitative_replay.md)。

## 测试

```bash
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src   # 运行时与评估侧全部测试
pixi run python -m pytest tests -q                                  # 根目录深度对齐测试（tests/ 无 __init__.py，走 pytest）
```

## 约定

- 日志统一走 `egoanchor.utils` 门面，不直接配置 logger。
- 每个 TOML 参数行末写中文注释；类、成员与方法写中文 docstring。
- `protocol/v1/*_pb2.py` 与 `subjects.v1.json` 副本是生成产物，改动请走 `EgoAnchor_Protocol/tools/generate_proto.ps1`。
