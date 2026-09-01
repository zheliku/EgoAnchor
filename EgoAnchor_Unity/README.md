# EgoAnchor_Unity

EgoAnchor 的头显端 Unity 工程：Quest 3 双目采集、采集时刻对齐、锚定策略与实验录制。感知推理全部在外部 Python 后端完成，本工程只负责发帧、收位姿、合成锚点和显示。

## 环境要求

- Unity **6000.3.11f1**（URP；打开工程时用这个精确版本）。
- 已安装 Meta Quest 3 并能通过 Quest Link 连接到本机。
- 包依赖在 `Packages/manifest.json`：Meta XR SDK 203.0.0 全家、OpenXR、Input System、Burst、NuGetForUnity，以及两个 git 源 UPM 包（`com.zheliku.unityplugins`、`com.coplaydev.unity-mcp`；后者是编辑器调试工具，不影响运行时）。

## 克隆后的准备步骤

1. 用 Unity Hub 打开本目录，等待 UPM 包解析完成。
2. 菜单 **NuGet → Manage NuGet Packages → Restore**：还原 `Assets/packages.config` 里的 NuGet 依赖（NetMQ、NATS.Net、Google.Protobuf 等，DLL 落在 `Assets/Packages/`）。
3. 打开场景 `Assets/Scene/EgoAnchor.unity`，确认 Console 无编译错误。
4. Quest Link 连接后进 Play。

## 场景

| 场景 | 用途 |
| --- | --- |
| `Assets/Scene/EgoAnchor.unity` | 主开发场景：完整链路 + 评估录制 + 轨迹渲染 |
| `Assets/Scene/EgoAnchor-Experiment12.unity` | 实验一/二正式采集（9 个 runtime 对照矩阵，启动前有硬校验） |
| `Assets/Scene/EgoAnchor-Experiment3.unity` | 实验三主观评价（2 方法 × 3 物体） |
| `Assets/Scene/EgoAnchor-ReplayCapture.unity` | 定性轨迹图素材采集（Quest Link + Play Mode） |

## 连接配置

场景中的 `ServerEndpointConfig` 组件（执行序 -1000）是唯一的 IP 入口：Inspector 上选预设或填自定义 IP，启动时自动把裸 IP 下发给 ZMQ 数据面（端口 15557）与 NATS 消息/命令面（端口 4222）。默认预设指向本机与实验室两台 GPU 服务器，克隆后改成你自己的后端地址即可。

评估数据默认写到 `<仓库>/../EgoAnchor_Python/data/eval/`，可在 `EvalSession` 组件的 `outputRoot` 上覆盖。

## 代码结构

```
Assets/Scripts/EgoAnchor/
├── Client/        # QuestStreamPublisher(ZMQ 发帧)、NATS 收发、ServerEndpointConfig
├── Runtime/       # AnchorRuntimeHub、PoseToAnchorRuntime、DynamicObjectAnchor、轨迹渲染
├── Alignment/     # 采集时刻帧对齐、相机位姿历史、坐标补偿
├── Policy/        # 锚定策略：状态机、运动模型(Kalman/One-Euro/CV)、平滑策略、StaticLock
├── Eval/          # EvalSession/EvalRecorder、实验任务选择、状态板
├── Quest/         # 双目纹理 Blit/读回/JPEG 编码、相机内参来源
├── QualitativeReplay/  # 定性回放采集器
├── Transport/     # NATS bytes 客户端、ZMQ publisher 封装
└── Protocol/Generated/  # protobuf 生成代码与 SubjectNames（勿手改）
```

测试在 `Assets/Tests/EditMode/`（5 个文件、102 个用例），从 Unity Test Runner 或命令行运行：

```bash
dotnet build "EgoAnchor.Tests.csproj" --no-restore
dotnet build "EgoAnchor.csproj" --no-restore
```

## 约定

- `Protocol/Generated/` 与 `SubjectNames.cs` 由 `EgoAnchor_Protocol/tools/generate_proto.ps1` 生成，不要手改。
- Inspector 参数写中文 XML summary 或 `[Tooltip]`；不隐藏生效参数。
- 运行日志统一走 `EgoAnchorLog` 门面（分级、带通道与调用位置）。
- 实验采集的按键映射与状态板契约见中文采集手册（`2026-EgoAnchor/docs/experiment_1_2_collection_manual_zh.md`）。

## 许可注意

工程内含若干 Asset Store 商业插件（HighlightPlus、Proxima、vTools 系列），随本仓库分发前请确认你持有相应授权并遵守其再分发条款，详见仓库根目录 [OPEN_SOURCE_CHECKLIST.md](../OPEN_SOURCE_CHECKLIST.md)。`Runtime/LineRenderer3D.cs` 改编自 survivorr9049/LineRenderer3D（MIT），出处保留在文件头。
