# EgoAnchor 代码架构优化工程报告

## Context

EgoAnchor 已在 `AGENTS.md` 中固化主线（Python `src/egoanchor` + Unity `Assets/Scripts/EgoAnchor` + ZMQ/NATS 双平面 + Protobuf 协议），架构骨架基本稳定。但代码体量已达到 **Python 8590 行 / Unity 5740 行**，部分单文件（`quest_pose_pipeline.py` 1153、`tracking_runtime.py` 653、`PoseToAnchorRuntime.cs` 749、`NatsControlClient.cs` 659、`AnchorCommandClient.cs` 569、`CameraPoseFrameAligner.cs` 365、`AnchorPolicyController.cs` 330）已经偏厚，并出现：

- 同一种"接收 → 解码 → 分发"的样板在 ZMQ/NATS 链与 Unity 三个 Receiver 中各写了一遍
- 多份 latest-only 缓存 / generation 计数 / 四元数转换 / 图像缩放与拼接 重复实现
- `PoseToAnchorRuntime` 同时承担 frame align、processor chain、reliability policy、状态机驱动、诊断字段五件事
- 多份 override `.toml`（blue_mouse / pink_mouse / earphone / controller）几乎只差 `prompt` 与 `mesh_path` 两个字段
- Unity 全部脚本仍在单一 `Assembly-CSharp` 里编译，没有 asmdef 分层

本报告目标：**在不改变主线架构契约（双平面 / Protobuf / frame-aligned anchor / 单 owner runtime）和已写明的"不要回退"清单的前提下**，列出可执行的精简、合并、重构与冗余删除项，并给出分阶段实施顺序与验证手段，便于后续按阶段推进。

---

## 1. 全局判断

整体分层是健康的：`config / protocol / transport / routing / handlers / runtime / perception / algorithms / reliability / diagnostics / app` 层次清晰，依赖方向基本单向；Unity 端 `Quest / Transport / Client / Anchor / Reliability / Diagnostics` 也基本对应。**主要问题不是架构走偏，而是接口过细 + 样板未抽 + 单文件膨胀**。优化方向应当是"收敛同形样板、拆分巨型文件、精简配置和 Inspector 字段"，而不是再做一次跨层重构。

按价值/风险分布，工程优先级：

| 优先级 | 类别 | 代表项 |
|---|---|---|
| P0（高价值低风险） | 抽公共模板 / 删冗余 | Unity 三个 Receiver、Python latest-only 缓存、override `.toml` 字段、空 dead handler |
| P1（高价值中风险） | 拆巨型文件 | `quest_pose_pipeline.py`、`PoseToAnchorRuntime.cs`、`tracking_runtime.py` |
| P2（结构性） | asmdef 分层 + Inspector sub-config | Unity 编译速度 + Inspector 折叠 |
| P3（防回退） | 测试补强 | transport resilience、config merge、status_handlers 补齐或删除 |

---

## 2. Python 侧优化项

### 2.1 `perception/quest_pose_pipeline.py` 拆分（P1，最重要）

**事实**：单文件 1153 行，包含 `PipelineStepTiming / SegmenterBackend / AsyncSegmenterJob / AsyncSegmenterWorker / QuestPosePipeline` 五个核心类，并在 `QuestPosePipeline` 内同时维护：异步 SAM3 worker 状态、generation 计数、Cutie ready、track reject 计数、tracked mask lost 计数、register 状态、debug 帧 timing；主处理函数 `_process_prepared_frame` ~102 行覆盖 5 个 stage。

**优化建议**：
- 把 `AsyncSegmenterJob / AsyncSegmenterWorker` 拆到 `perception/async_segmenter.py`（独立测试 SAM3 异步分割单线程行为），`QuestPosePipeline` 只保留消费 worker 输出的接口。
- 把 generation/has_registered/cutie_ready/track_reject_count/tracked_mask_lost_count 等离散布尔与计数收敛进 `@dataclass(slots=True) PipelineTrackingState`，所有 `reset_tracking_state` / `_refresh_calibration` / `__init__` 三个递增点改成调用 `state.bump_generation()`，避免 generation 同步逻辑分散在 `quest_pose_pipeline.py:498/516/667/807/1070` 多处。
- 把 `_process_prepared_frame` 拆为 `_run_detect_stage / _run_depth_stage / _run_register_stage / _run_track_stage` 四个职责清晰的小方法，主函数只做 stage 路由。
- 将所有 `mask_source` 字符串（`"none"/"yoloe"/"sam3"/"cutie"`，散落在 `quest_pose_pipeline.py:280/711/729/924/929`）替换为 `class MaskSource(StrEnum)`，并在 diagnostics HUD 中复用同一枚举。
- 把多处 `timing.total_ms = (time.perf_counter() - t_total) * 1000.0`（行 715/721/733/743/756/777）抽为 `PipelineStepTiming.finalize(t_total)` 方法，避免遗漏。
- 对 `quest_pose_pipeline.py:244/1015` 等 `except Exception: pass` 改为 `LOGGER.warning("…", exc_info=True)`，保持与同模块内其他 warning 一致的可观测性。

### 2.2 `runtime/tracking_runtime.py` 收缩（P1）

**事实**：653 行，混入了 `_pose_log_fields`（42 行四元数 + 调试字段构造）和 `_rotation_matrix_to_quaternion`（35 行纯数学）。runtime 的本职是"poll latest input → drive pipeline → publish PoseResult/Status/Heartbeat → 顺序消费 commands"。

**优化建议**：
- 把四元数与日志字段构造迁出 runtime：`_rotation_matrix_to_quaternion` → `egoanchor/utils/math.py`（新建轻量 utils 包）；`_pose_log_fields` 拆为 `pose_result_factory` 旁的 `pose_log_factory.py`，跟随 PoseResult 一起出。
- 把 `_extract_frame_id / _extract_session_id / _extract_client_id` 提到 `protocol/header_utils.py`，让 `LatestQuestInputStore`（`latest_quest_input_store.py:129-150`）和 `quest_pose_pipeline.py:786-791` 都共享同一份实现。

### 2.3 三类小样板合并（P0）

| 重复项 | 现状证据 | 建议 |
|---|---|---|
| latest-only 缓存 | `LatestQuestInputStore`（runtime）和 `AsyncSegmenterWorker._completed_output`（perception）各写一份 | 提取 `runtime/latest_value_store.py: LatestValueStore[T]`，两边共用，附 `seen_count / drop_count` 统计 |
| transport 生命周期 | `nats_client.py:152-189` 与 `zmq_topic_subscriber.py:72-93` 都有 `start/close + LOGGER.info` | 提取 `transport/_lifecycle.py: BaseTransportClient`（仅做 start/close 状态机和日志前缀），不要为了合并而把 NATS 与 ZMQ 的会话语义强行统一 |
| command handler 三段式 | `command_handlers.py:147-157` 三个 `@registry.request` 函数体一致 | 改为 `for subject, ctype in (CMD_ANCHOR_RESET, RESET), …: registry.request(subject)(partial(_accept, command_type=ctype))`；保留 `_validate` 内的类型分支 |
| diagnostics 图像工具 | `diagnostics/debug_view.py:16-38, 74-80` 与 `diagnostics/stereo_view.py:36-47` 都做缩放 / stereo 拼接 | 提取 `diagnostics/image_utils.py`：`fit_to_width / fit_to_size / stack_stereo` 三个函数，两侧改为只做"画图与 HUD" |

### 2.4 配置层合并（P0）

**事实**：`blue_mouse.toml / pink_mouse.toml / controller.toml / earphone.toml` 体量都在 ~12 行，结构完全一致，仅差 `prompt`、`confidence_threshold`、`mesh_path` 三个字段（earphone 多覆盖 `module.segmenter.type="sam3"`）。

**优化建议**：
- 引入 `objects.toml`，每个目标作为一个 `[objects.<name>]` 子表（含 prompt / threshold / mesh / segmenter type / symmetry_mode），由 `runtime_config.py: load_object_override(name)` 在 defaults 之上叠加。
- 对应入口由 `--config blue_mouse.toml` 改为 `--object blue_mouse`，避免每次新增物体都要复制一份 12 行 toml；旧 `.toml` 文件删除。
- `defaults.toml` 中的 `module.foundationpose.mesh_path` 应保持空或 `data/model/default.glb`，让 override 单一来源；同时审查 `demo.pose` 段在主线（`tracking_server`）是否仍被使用——若仅 `quest_video_stream_demo.py` 使用，则迁到 demo 专属 toml。

### 2.5 routing / handlers 收敛（P0）

- `routing/route_specs.py: iter_nats_request_specs` 当前只有一行过滤，且仅被 `app/tracking_server.py` 用一次——**直接内联，删除 `route_specs.py`**，让 `routing/__init__.py` 只导出 `HandlerRegistry / NatsRouter / HandlerContext`。
- `handlers/status_handlers.py` 是空壳（仅 ~10 行占位）：要么写出第一个真实 handler（与 `AnchorStatusEvent` 闭环挂钩），要么直接删除文件，避免误导后续 agent 以为已有 status 处理面。
- `routing/nats_router.py` 与 `transport/nats_client.py` 之间通过 callback 拼接，可在 `app/tracking_server.py` 启动处把 `router.handle_message` 直接 `add_subscription(subject, router.dispatch)`，三层调用收敛为两层；接口已经够窄，**不需要再抽新基类**。

### 2.6 测试补强（P3）

`tests/` 当前 11 个文件覆盖 command flow / segmenter / pose factory / heartbeat / event log，**transport 失败重连、config 合并、frame-id 单调性、generation 同步** 这些跨层关键路径目前没有用例。

建议新增（保持 unittest 风格，不引入 pytest 依赖）：
- `tests/test_transport_lifecycle.py`：mock NATS 连接掉线 → 是否触发重连日志、是否丢失订阅；ZMQ HWM 满 → 是否仅丢非 latest 数据。
- `tests/test_config_overlay.py`：新对象 toml + defaults 合并，验证 mesh_path / prompt 注入正确，缺省字段保留。
- `tests/test_pipeline_state.py`（取代 generation 散点测试）：reset_tracking_state / _refresh_calibration / 异步 worker 跨代结果应被丢弃。

---

## 3. Unity 侧优化项

### 3.1 三个 Receiver 合并（P0，最有收益的小改）

**事实**：`Client/PoseResultReceiver.cs`（109）、`Client/AnchorStatusReceiver.cs`（119）、`Client/ServerHeartbeatReceiver.cs`（113）三者结构完全一致——`Update()` → `TryDequeue` → `Parser.ParseFrom` → 统计 → 广播给上层。

**优化建议**：抽 `Client/NatsTypedReceiver<TMessage>`（abstract MonoBehaviour）：
- `protected abstract MessageParser<TMessage> Parser { get; }`
- `protected abstract bool TryDequeueRaw(out byte[] payload);`（latest-only / event 由子类传策略枚举）
- `protected abstract void OnParsed(TMessage message);`
- 子类各 ~25 行就能完成。三份同形 60+ 行的 Update 循环代码消失。

`PoseResultReceiver` 可保留独立 `Hub` 广播逻辑（因为它是 raw-vs-smoothed 双路入口），但解析与计数样板下沉到基类。

### 3.2 `PoseToAnchorRuntime.cs` 拆分（P1）

**事实**：749 行单文件，承担：frame alignment（aligner 持有 + RebuildAligner）、processor chain（List<AnchorPoseProcessor> 串行）、reliability policy（policyController 持有 + RebuildPolicyController）、`AnchorStateMachine` 驱动、raw/stable 双路缓存（`rawPose / stablePose / hasRawPose / hasStablePose`）、Inspector 诊断字段（24 个 SerializeField，含 latestPhase / latestPolicyAction / latestServerEvent / latestHeartbeatInputReady…）。

**优化建议**：
- 把 reliability policy 段（ReliabilityGate / PoseInnovationGate / AnchorPredictor / AnchorPolicyController + min/max 阈值 + coast/lost timeout）抽成独立 `Anchor/AnchorPolicyHost.cs` MonoBehaviour，挂同一 GameObject 上；`PoseToAnchorRuntime` 改为只持有 `AnchorPolicyHost` 引用，"启用 policy"由是否引用了该组件决定，去掉 `enableReliabilityPolicy` bool 开关。
- 把 24 个诊断 SerializeField 收纳到 `[Serializable] class RuntimeDiagnostics { public long latestAlignedFrameId; public string latestPhase; … }`，Runtime 暴露 `public RuntimeDiagnostics Diagnostics => diagnostics;`，Inspector 折叠到一个 fold-out。
- `rawPose / stablePose` 双字段保留，但语义由 processor chain 统一处理：当 `processors` 为空 ⇒ stable = raw（不再用 `enableProcessors` bool）。这样 `DynamicObjectAnchor` 只需选 `OutputMode.Raw / Smoothed`，与 AGENTS.md 中"DynamicObjectAnchor 只读取 runtime raw/stable pose"的定位完全一致。
- 把 `RebuildAligner / RebuildPolicyController` 与 frame alignment 阈值参数下沉到 `CameraPoseFrameAligner`（已 365 行，可放）。

### 3.3 `NatsControlClient.cs` 拆层（P1）

**事实**：659 行同时做：NATS 连接管理、订阅循环、三个 ConcurrentQueue（latest pose / event status / latest heartbeat）、request/reply 发起、限流、统计、Inspector 字段（13 个）。

**优化建议**：拆为两层：
- `Transport/NatsBytesClient.cs`：纯 byte[] 层。`Connect / Disconnect / Subscribe(subject, callback) / RequestAsync(subject, payload, timeout)`，**不感知 EgoAnchor subject 与 Protobuf 类型**。
- `Client/NatsControlClient.cs`：上层，持有 `NatsBytesClient`，订阅 EgoAnchor 三个 subject 并写入 `LatestOnlyQueue<byte[]>` / `EventQueue<byte[]>`，提供 `TryDequeueLatestPoseResult / TryDequeueLatestHeartbeat / TryDequeueStatusEvent`。
- 三处 `TryDequeueLatest`（`NatsControlClient.cs:295/321/496`）替换为统一的 `LatestOnlyQueue<T>`（`Util/LatestOnlyQueue.cs`），消除"latest queue + drain old"的重复代码。

### 3.4 `AnchorObservation` 与 `AnchorLifecycleEvent` 合并（P0）

**事实**：`AnchorObservation.cs` 154 行 + `AnchorLifecycleEvent.cs` 72 行，两个 readonly struct/dataclass 各持一套 `Phase / PoseSource / FailureReason / SampleTimeSeconds`，`PoseToAnchorRuntime` 在两个结构间来回拷贝诊断字段。

**优化建议**：保留 `AnchorObservation` 作为"输入侧观测"（frame-aligned pose + 可靠性），`AnchorLifecycleEvent` 作为"输出侧状态变化"（PreviousState / CurrentState / Reason），但消除字段重复——`AnchorLifecycleEvent` 中只引用 `AnchorObservation.SampleTimeSeconds`，不再单独保存 SampleTime/Phase。这是个一次性 30~40 行的小重构。

### 3.5 Processor 基类（P0）

`AnchorKalmanPoseProcessor.cs` 175 + `AnchorLowPassPoseProcessor.cs` 84 都各自维护 `hasState / lastSampleTime / snapOnFirstPose`，并在 `Process` 入口做相同的"首次到来 → snap"判断。

**建议**：在 `Anchor/AnchorPoseProcessor.cs` 基类上加 `protected bool TryHandleFirstSample(in Pose input, double sampleTime, out Pose output)` helper，子类只写各自滤波核心。Kalman 的 3 个独立 1D filter 可抽 `KalmanScalar` 内嵌结构，缩到 ~120 行。

### 3.6 命名收敛（P0）

- `AnchorPoseReference`（枚举 Left/Right/Center/None）+ `FramePoseHistory.FramePoseRecord` + `CameraPoseFrameAligner.alignmentReference`：术语应统一为 `CameraReference`（更短、避免和 Anchor 概念混用），更名一遍。
- `Reliability/AnchorPolicyController` → `Reliability/PolicyController`；`PoseInnovationGate` → `InnovationGate`；包外引用通过 `using EgoAnchor.Reliability;` 拿。这一步配合 asmdef 一起做。

### 3.7 asmdef 分层（P2，编译速度收益最大）

**现状**：`EgoAnchor_Unity\Assets\Scripts\EgoAnchor\` 下没有任何 `*.asmdef`，全部脚本编译进 `Assembly-CSharp.dll`，单脚本改动触发整工程重编。

**建议**：按现有目录建立 6 个 asmdef，依赖图严格单向：

```
EgoAnchor.Protocol.asmdef        → Google.Protobuf
EgoAnchor.Transport.asmdef       → NATS.Net, NetMQ
EgoAnchor.Quest.asmdef           → Meta.XR (Passthrough)
EgoAnchor.Anchor.asmdef          → EgoAnchor.Protocol, EgoAnchor.Quest
EgoAnchor.Reliability.asmdef     → EgoAnchor.Anchor
EgoAnchor.Client.asmdef          → EgoAnchor.Transport, EgoAnchor.Protocol,
                                   EgoAnchor.Anchor, EgoAnchor.Reliability,
                                   EgoAnchor.Quest
EgoAnchor.Diagnostics.asmdef     → EgoAnchor.Anchor (UI 层)
```

`Anchor → Quest`、`Reliability → Anchor` 在当前代码已经天然成立（`PoseToAnchorRuntime` `using EgoAnchor.Quest`），不会引入新的依赖问题。

### 3.8 删除/收紧（P0）

- `PoseToAnchorRuntime.cs:96-99` 的 `keepDiagnostics` 开关：诊断字段在所有路径都被赋值，开关只影响 Inspector 显示而非数据维护，**可以删除**，让 Inspector 始终展示。
- `AnchorCommandClient.cs:46-52` 的 `resetLocalFiltersOnAccepted / clearLocalAnchorPoseOnAccepted` 两个开关：根据 AGENTS.md "CommandAck.accepted=true 只表示 Python 接受命令，不表示重定位完成"，**Unity 不应在 ack 阶段动本地 filter / pose**，建议直接删除，相关清理改由 `AnchorStatusEvent`（已接入 receiver）触发，避免双重清理路径。
- 检查 `Diagnostics/EventLogPanel.cs`（174 行）是否复用 `runtime_event_log` 的字段语义，若不同需对齐。

---

## 4. 协议与跨语言契约（不动主线，仅微调）

- AGENTS.md 已规定"业务代码不手写 subject 字符串"。Unity 端 `SubjectNames.cs` 由协议脚本生成，Python 端 `protocol/__init__.py` 从 `subjects.v1.json` 加载——**保持现状**，不要新增手写映射。
- `EgoAnchor_Protocol/tools/generate_proto.ps1` 是单一生成入口，所有契约改动应继续通过 `.proto + subjects.v1.json` 做，不允许在 Python 或 Unity 侧手工补字段（这一约束已在 AGENTS.md "字段号进入共享 proto 后不得重排"中固化，不需要改）。
- 若 3.4 中 `AnchorLifecycleEvent` 字段调整未涉及跨语言，**不要触碰 proto**；Unity 内部数据结构调整不需要协议变更。

---

## 5. 关键文件优先改动清单

| 文件 | 行 | 动作 | 阶段 |
|---|---:|---|---|
| Python `perception/quest_pose_pipeline.py` | 1153 | 拆 `async_segmenter.py` + `PipelineTrackingState` + 4 个 stage 子方法 | P1 |
| Python `runtime/tracking_runtime.py` | 653 | 把四元数和 header 抽到 `utils/math.py`、`protocol/header_utils.py` | P1 |
| Python `handlers/command_handlers.py` | 160 | 三个 handler 改 partial 注册 | P0 |
| Python `routing/route_specs.py` | 10 | 删除文件，单行函数内联 | P0 |
| Python `handlers/status_handlers.py` | ~10 | 写实或删除 | P0 |
| Python `config/{blue_mouse,pink_mouse,earphone,controller}.toml` | 4×~12 | 合并到 `objects.toml` | P0 |
| Python `transport/_lifecycle.py` | 新增 | `BaseTransportClient` start/close 模板 | P0 |
| Python `runtime/latest_value_store.py` | 新增 | latest-only 缓存基础设施 | P0 |
| Python `diagnostics/image_utils.py` | 新增 | fit / stack / hud 抽取 | P0 |
| Unity `Client/PoseResultReceiver.cs` 等 3 文件 | 109+119+113 | 抽 `NatsTypedReceiver<T>` 基类 | P0 |
| Unity `Anchor/PoseToAnchorRuntime.cs` | 749 | 拆 policy host + 诊断子结构 | P1 |
| Unity `Transport/NatsControlClient.cs` | 659 | 拆 `NatsBytesClient` + `LatestOnlyQueue<T>` | P1 |
| Unity `Anchor/AnchorObservation.cs` + `AnchorLifecycleEvent.cs` | 154+72 | 字段去重 | P0 |
| Unity `Anchor/AnchorPoseProcessor.cs` 等 | 57/84/175 | 抽 `TryHandleFirstSample` helper | P0 |
| Unity 全局 | — | 加 6 个 asmdef | P2 |
| Unity `PoseToAnchorRuntime` 字段 / `AnchorCommandClient` 开关 | — | 删 `keepDiagnostics`、删两个 ack-阶段清理开关 | P0 |

---

## 6. 实施分阶段建议

### 阶段 1 — 同形样板与配置精简（约 1~2 天）

P0 动作集中处理。每改一个不允许跨阶段：先合并再上 PR。

- Python：`route_specs.py` 删除、`status_handlers.py` 处理、`command_handlers.py` partial 化、`object.toml` 合并、`latest_value_store.py` + `image_utils.py` 抽取、四个 override toml 删除。
- Unity：`NatsTypedReceiver<T>` 抽出、`AnchorObservation/LifecycleEvent` 字段去重、`AnchorPoseProcessor` 基类 helper、`keepDiagnostics` / 两个 ack 开关删除。

### 阶段 2 — 巨型文件拆分（约 2~3 天）

需要小步推进、配合 smoke。

- Python：`quest_pose_pipeline.py` 抽 `async_segmenter.py` + `PipelineTrackingState`，再拆 stage 子函数。每步必须跑 `pixi run python -m unittest discover -s src -p "test_*.py"` + `pixi run python ./src/tracking_server.py` 真机/replay 烟雾。
- Python：`tracking_runtime.py` 抽 `utils/math.py` + `protocol/header_utils.py`。
- Unity：`PoseToAnchorRuntime` 拆 `AnchorPolicyHost` 与诊断 sub-struct；`NatsControlClient` 拆 `NatsBytesClient` + `LatestOnlyQueue<T>`。

### 阶段 3 — 结构性优化（约 1 天）

- Unity asmdef 6 包分层、命名收敛（`AnchorPoseReference` → `CameraReference`、`AnchorPolicyController` → `PolicyController` 等）。
- Python tests 三类补强。

### 阶段 4 — 评估与回归

- 对比改动前后 Python 行数（目标：`quest_pose_pipeline.py` < 700，`tracking_runtime.py` < 500）和 Unity 行数（目标：`PoseToAnchorRuntime.cs` < 450，`NatsControlClient.cs` < 350）。
- 运行 AGENTS.md 中"常用入口与验证"全部 4 条命令，确认主线 Python+Unity smoke 不退步。

---

## 7. 不要触碰 / 风险红线

严格遵守 `AGENTS.md` "关键历史约束：不要回退"，本次优化**不**做以下任何动作：

1. 不引入新的传输方案（保持 ZMQ + NATS 双平面）。
2. 不动协议字段号、不改 `subjects.v1.json` channel 列表。
3. 不把 SAM3 设为默认；`module.segmenter.type` 默认仍是 `yoloe26`。
4. 不把 FoundationPose / Cutie 状态搬出 `TrackingRuntime` owner 线程（异步分割只在 worker 内）。
5. 不引入 Unity legacy port 自动迁移逻辑。
6. 不把 `AnchorPolicyController` 写进 `NatsControlClient` / `PoseResultReceiver` / `DynamicObjectAnchor`，仍保留在 anchor runtime / policy 层（即 3.2 中的 `AnchorPolicyHost` 仍属 Anchor 侧）。
7. 不动"用 capture-time frame pose 做 world anchor"的核心机制；`FramePoseHistory` / frame_id 透传不优化掉。

---

## 8. 验证

每阶段都要跑通：

```powershell
# Python 编译 + 单测
cd EgoAnchor_Python
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py"

# Python 主线 smoke（连接 Unity 或 replay）
pixi run python .\src\tracking_server.py

# Unity 编译验证
cd ..
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

阶段 2 拆分巨型文件后，必须额外跑：
- `pixi run python .\src\yoloe_mask_probe.py`（确认分割链路未断）
- 真机 / replay：观察 HUD 中 `mask_src / pose_source / seg_async done/submitted/drop` 计数与改动前一致。
- Unity：raw vs smoothed 两条 `DynamicObjectAnchor` 在静态 + 头动场景下的位置/姿态对比，policy 关闭 / 启用各 1 次。

阶段 3 加 asmdef 后：
- 用 Unity 自带的 `Assets > Open C# Project` 重新生成 csproj，确认 6 个 asmdef 都正确生成 dll 且依赖单向。
- 运行编辑器场景，确认所有 Inspector 引用未丢失（asmdef 改动最常见的回归是 missing reference）。

---

## 9. 预期收益总结

| 维度 | 当前 | 阶段 1+2 后预期 |
|---|---|---|
| `quest_pose_pipeline.py` | 1153 行 / 30+ 方法 | < 700 行 / 单一职责 |
| `tracking_runtime.py` | 653 行 / 含数学逻辑 | < 500 行 / 纯协调层 |
| `PoseToAnchorRuntime.cs` | 749 行 / 24 SerializeField | < 450 行 / 1 子结构折叠 |
| `NatsControlClient.cs` | 659 行 / 3 latest queue | < 350 行 + 独立 NatsBytesClient |
| Override toml 文件 | 4 个 × ~12 行 | 1 个统一 `objects.toml` |
| Unity Receiver 重复 | 3 份 60+ 行 Update 循环 | 1 个基类 + 3 个 ~25 行子类 |
| Unity 编译颗粒度 | 单一 Assembly-CSharp | 6 个 asmdef，单层改动只重编当前层 |

主要可量化收益：**Python 单文件最大行数下降 ~40%、Unity 单文件最大行数下降 ~40%、override toml 数量从 4 → 1、Unity 单脚本改动重编译范围缩小到 1/6**。论文实验阶段（AGENTS.md Phase B/C）继续推进时，更小的单文件 + 单向 asmdef 会让"加 reliability 字段、加新的 anchor policy 行为"这类增量修改都更安全。

---

# 第二轮：重构验收 + 后续优化建议

## 10. Context（本轮目标）

第一轮工程报告提出的 12 项 Python + 9 项 Unity 优化已由用户落地。现在需要：
1. **验收**：逐项核对当前代码状态是否符合阶段 1~3 的要求，标出仍有差距的条目；
2. **后续规划**：基于落地后的目录结构，回答用户两个具体问题——
   - `Anchor/` 下 policy/observation/decision 等脚本是否需要归到子目录；
   - `Anchor/AnchorPolicyHostBase.cs` 是否冗余（用户感觉它和 `Reliability/AnchorPolicyHost.cs` 命名近似）；
3. 输出"必须修"和"可选优化"两档清单，避免一次改太多再次堆积。

**约束**：所有结论必须保留 AGENTS.md "不要回退"红线（双平面、frame-aligned anchor、单 owner runtime），并保留第一轮已确立的 asmdef 单向依赖（`Reliability → Anchor → Quest/Protocol`）。

## 11. 验收记分卡

按第一轮 P0/P1/P2/P3 条目逐项核对（行数为本轮 `wc -l` 实测）。

### 11.1 Python（11/12 ✅）

| 条目 | 目标 | 实测 | 结论 |
|---|---|---|---|
| `quest_pose_pipeline.py` 拆分 | < 700 行 | 553 行 + `pipeline_helpers.py` 377 + `pipeline_types.py` 179 + `async_segmenter.py` 223 | ✅ |
| `tracking_runtime.py` 收缩 | < 500 行 | **576 行** | ⚠ **差距 ~76 行** |
| `command_handlers.py` partial 化 | 三 handler 合并 | 已合并 | ✅ |
| `route_specs.py` 删除 | 删除 | 已删 | ✅ |
| `status_handlers.py` 处理 | 写实或删 | 已删 | ✅ |
| 4 个 override toml 合并 | `objects.toml` + `--object` | 已合并（35 行 / 4 子表） | ✅ |
| `transport/_lifecycle.py` | 抽 base | 已建 | ✅ |
| `runtime/latest_value_store.py` | 抽公共缓存 | 已建 | ✅ |
| `diagnostics/image_utils.py` | 抽 fit/stack/hud | 已建 | ✅ |
| `utils/math.py` 四元数 | 数学外迁 | 已建（仅 43 行，偏薄但合理） | ✅ |
| `protocol/header_utils.py` | header 抽取 | 已建 | ✅ |
| 测试补强（transport/config/pipeline_state） | 三个新测试 | 已加入 `tests/` | ✅ |

### 11.2 Unity（8/9 ✅）

| 条目 | 目标 | 实测 | 结论 |
|---|---|---|---|
| `NatsTypedReceiver<T>` 抽基类 | 3 receiver 同形合并 | 已合并 | ✅ |
| `PoseToAnchorRuntime.cs` 拆分 | < 450 行 | 318 行 主 + `Events.cs` 336 + `Diagnostics.cs` 64 | ✅（主文件）/ ⚠（**`Events.cs` 偏厚**） |
| `NatsControlClient.cs` 拆 `NatsBytesClient` | < 350 行 | **425 行** + `NatsBytesClient.cs` 338 | ⚠ **差距 ~75 行** |
| `LatestOnlyQueue<T>` 统一 | 一份实现 | 已抽到 `Util/`，唯一调用方仅 `NatsControlClient` | ✅（实现统一）/ 备注见 12.1 |
| `AnchorObservation` + `LifecycleEvent` 字段去重 | SampleTime/Phase 不重复 | 已去重 | ✅ |
| `AnchorPoseProcessor` 基类 helper | `TryHandleFirstSample` | 已抽 | ✅ |
| 删除 `keepDiagnostics` 开关 | 删 | 已删 | ✅ |
| 删除 `AnchorCommandClient` 两个 ack 阶段清理开关 | 删 SerializeField + 不在 ack 阶段清理 | SerializeField 已删，但**仍残留 `clearFilters` / `clearAnchorPose` 重载方法**（`AnchorCommandClient.cs:222`） | ❌ **未完成** |
| asmdef 6+ 包分层 | 单向依赖 | 已建 8 个（多了 Util、Diagnostics 单独包） | ✅ |
| 命名收敛 | `CameraReference` / `PolicyController` / `InnovationGate` | 已改名 | ✅ |

### 11.3 总体结论

整体落地度高，**21 项里 19 项达标**，但有 3 个具体问题在阶段 4 必须收尾，2 个目录组织问题适合作为阶段 5 的轻量优化。

## 12. 必须修的 3 个收尾项（阶段 4）

### 12.1 `tracking_runtime.py` 仍 576 行，目标 <500

**事实**：`utils/math.py` 已抽出但只有 43 行，说明四元数迁出没释放预期空间——`tracking_runtime.py` 内还残留 protocol 装配 / command 路由 / heartbeat 装配 / pose log 字段四类样板。

**建议**：
- 把 `_pose_log_fields` 完整迁到独立 `runtime/pose_log_factory.py`（pose_result_factory 旁边），运行时只调用一次。
- 把 `Heartbeat` 装配段（`make_heartbeat / fill_input_ready / publish_heartbeat`）抽到 `runtime/heartbeat_factory.py`，与 PoseResultFactory 一致风格。
- `command` 顺序消费循环（poll → dispatch → ack）抽到 `runtime/command_pump.py`，runtime 只持有 pump 引用。
- 完成后 `tracking_runtime.py` 应只剩"循环 + 阶段调用 + 错误归因"，预计 380~420 行。

### 12.2 `AnchorCommandClient.cs` 残留 ack 阶段清理重载

**事实**：[AnchorCommandClient.cs:222](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Client/AnchorCommandClient.cs#L222) 仍存在 `clearFilters` / `clearAnchorPose` 方法重载。第一轮已删 SerializeField 开关，但调用路径仍在 ack 分支被触发。

**建议**：
- 直接删除这两个方法重载和它们在 `OnAck(...)` 内的调用点；
- 清理改由 `AnchorStatusReceiver` → `PoseToAnchorRuntime.NotifyReset/NotifyReacquire/NotifyClear` 单一路径触发；
- 这与 AGENTS.md "CommandAck.accepted=true 不表示重定位完成" 一致，避免双清理路径冲突。

### 12.3 `PoseToAnchorRuntime.Events.cs` 336 行偏厚

**事实**：主文件 318 行已达标，但 partial `Events.cs` 累积了 8 个 `Notify*` 方法（Reset/Reacquire/Pause/Resume/Clear/MissingPose/AlignFailure/StatusEvent...），逻辑接近 controller 层而非"事件薄壳"。

**建议**：
- 把 `NotifyMissingPose / NotifyAlignFailure` 这两个**纯失败诊断**写入留在主文件（它们与 `SetFailure` 紧耦合）；
- 把 `NotifyReset / NotifyReacquire / NotifyPause / NotifyResume / NotifyClear / NotifyStatusEvent / NotifyHeartbeat` 7 个**对外 policy 通知**抽到独立 `Anchor/Policy/PoseToAnchorRuntime.PolicyNotifications.cs` partial（与 12.4 的目录调整配合），主文件仅保留入口委托；
- 完成后 partial 文件目标 <180 行。

## 13. 用户两个具体问题的答复

### 13.1 `Anchor/` 下脚本是否需要分子目录？✅ 建议分

**事实**：当前 [Anchor/](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Anchor/) 平铺 14 个文件，混合了三类截然不同的职责：
- **runtime 主体**：`PoseToAnchorRuntime.cs` + `PoseToAnchorRuntime.Events.cs` + `PoseToAnchorRuntime.Diagnostics.cs`、`DynamicObjectAnchor.cs`、`FramePoseHistory.cs`、`CameraPoseFrameAligner.cs`、`AnchorPoseTransform.cs`、`CameraReference.cs`；
- **policy 接口/数据**：`AnchorPolicyHostBase.cs`、`AnchorPolicyDecision.cs`、`AnchorObservation.cs`、`AnchorState.cs`、`AnchorLifecycleEvent.cs`；
- **processor 基类**：`AnchorPoseProcessor.cs`（具体 Kalman/LowPass 实现已在 `Anchor/Processors/` 内？需核实）。

**建议拆为 3 个子目录**（仅文件移位 + namespace 不变，**不改 asmdef**——`Anchor.asmdef` 仍覆盖整个 `Anchor/` 树）：

```
Anchor/
├── Runtime/                        ← runtime 主体 + frame alignment
│   ├── PoseToAnchorRuntime.cs
│   ├── PoseToAnchorRuntime.Events.cs   (12.3 拆分后改名)
│   ├── PoseToAnchorRuntime.Diagnostics.cs
│   ├── DynamicObjectAnchor.cs
│   ├── FramePoseHistory.cs
│   ├── CameraPoseFrameAligner.cs
│   ├── AnchorPoseTransform.cs
│   └── CameraReference.cs
├── Policy/                         ← policy 抽象接口 + observation/decision DTO
│   ├── AnchorPolicyHostBase.cs
│   ├── AnchorPolicyDecision.cs
│   ├── AnchorObservation.cs
│   ├── AnchorState.cs
│   ├── AnchorLifecycleEvent.cs
│   └── PoseToAnchorRuntime.PolicyNotifications.cs  (12.3 抽出的 partial)
└── Processor/                      ← processor 基类（具体实现已在 Reliability 或单独子目录）
    └── AnchorPoseProcessor.cs
```

**理由**：
- `Anchor/Policy/` 让 "policy 接口在 Anchor 层、policy 实现在 Reliability 层" 的反向依赖更直观（13.2 即依赖此分组）；
- 不改 namespace（仍为 `EgoAnchor.Anchor`）和 asmdef，**Unity 不会有 missing-reference 风险**；
- `DynamicObjectAnchor` 放 Runtime 子目录避免新读者把它误归 Policy。

**风险**：Unity 移文件会改 `.meta` 路径，需要 git 一并提交；Inspector 引用以 GUID 为准，不会断。

### 13.2 `Anchor/AnchorPolicyHostBase.cs` 是否冗余？❌ **不冗余，必须保留**

用户的疑问是合理的——两个文件都叫 `AnchorPolicyHost*` 且都是 MonoBehaviour，看起来像同一个东西放了两份。但读完代码后**两者承担截然不同的职责**：

| 维度 | `Anchor/AnchorPolicyHostBase.cs`（58 行） | `Reliability/AnchorPolicyHost.cs`（163 行） |
|---|---|---|
| 类型 | `abstract class` | `sealed class : AnchorPolicyHostBase` |
| 内容 | 5 个 abstract 方法（State/AcceptPose/NotifyReset/NotifyReacquire/NotifyPause/Resume/Clear） | Inspector 字段（5 个阈值）+ `PolicyController` 实例 + `Rebuild()` 生命周期 |
| 所在 asmdef | `EgoAnchor.Anchor.asmdef` | `EgoAnchor.Reliability.asmdef`（→ Anchor） |
| 被谁引用 | `PoseToAnchorRuntime.policyHost` 字段类型 | 实际挂在 GameObject 上的具体组件 |

**核心理由（保留 base 的 3 条）**：

1. **asmdef 单向依赖的承重墙**。当前依赖图是 `Reliability → Anchor`（policy 实现依赖 anchor 抽象）。如果删掉 base、`PoseToAnchorRuntime` 直接持有 `Reliability.AnchorPolicyHost`，则 `Anchor.asmdef` 必须依赖 `Reliability.asmdef`——**变成双向依赖，asmdef 编译失败**。
2. **依赖倒置（DIP）**。这是教科书级别的接口在调用方包内、实现在被调方包内的反向依赖范式（类比 Java：`api/` 包定义接口，`impl/` 包提供实现）。第一轮工程报告 3.2 节明确写了"`PoseToAnchorRuntime` 改为只持有 `AnchorPolicyHost` 引用，'启用 policy' 由是否引用了该组件决定"——base 就是这个引用类型。
3. **测试 / 替换灵活性**。未来想加第二个 policy 实现（例如纯 EKF policy 不走 reliability gate），或想在测试里 mock policy，只需新派生一个 `AnchorPolicyHostBase` 即可。如果只有具体类，每次都要改 `PoseToAnchorRuntime`。

**用户感知问题（命名）的处理**：两个文件都叫 `AnchorPolicyHost*` 确实容易让人以为是同一份。建议轻量改名：
- `Anchor/AnchorPolicyHostBase.cs` → `Anchor/Policy/IAnchorPolicyHost.cs`（即使 Unity MonoBehaviour 不允许 interface，命名上加 `I` 前缀或 `Host` 改 `Provider` 仍然能区分）；
- 但这是**命名口味**问题而非架构问题，可与 13.1 的目录拆分一起做，也可以保持现状。

**结论**：`AnchorPolicyHostBase.cs` 是当前依赖架构的承重墙，**绝对不能删**。两个文件并存不是冗余而是分层。

## 14. 可选优化项（阶段 5，低优先级）

下面这些是阶段 4 完工后可以考虑的进一步整理，不属于"不达标"，纯粹是基于现状再迭代的方向。

### 14.1 Python 包内子目录

- `runtime/` 当前 14 个文件平铺，可按职能拆为 `runtime/factories/`（`pose_result_factory.py` / `heartbeat_factory.py` / `pose_log_factory.py`）、`runtime/commands/`（`command_pump.py` 等）、`runtime/input/`（`latest_quest_input_store.py` / `latest_value_store.py`）三组；
- `perception/` 9 个文件可建 `perception/core/`（pipeline 主体）+ `perception/segmenter/`（async_segmenter + 后续 SAM3 worker）；
- `tests/` 17 个文件可镜像源码层级建子目录（`tests/perception/` / `tests/runtime/` / `tests/transport/` / `tests/config/`）。

### 14.2 Unity transport 层 SubjectNames 解耦

[NatsControlClient.cs:207-209](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Transport/NatsControlClient.cs#L207-L209) 直接 `using` 了 `SubjectNames.PoseResult` / `AnchorStatus` / `ServerHeartbeat`，违反"transport 只认 bytes 不认 EgoAnchor 协议"的分层意图（第一轮 3.3 节）。

**建议**：把订阅入口的三行 subject 字符串改为 SerializeField（默认值仍来自 `SubjectNames`，但运行时可注入），或把 `Subscribe(SubjectNames.X, ...)` 三行整体迁到 `Client/NatsSubscriptionInstaller.cs` 一个新组件。这步收益不大，主要是论文里写"transport 是 protocol-agnostic"时口径更干净。

### 14.3 `LatestOnlyQueue<T>` 归位

当前在 `Util/`，但唯一使用方是 `NatsControlClient`。如果未来不打算让其它层（例如 ZMQ Unity 端、本地缓存）复用，可以把它收回 `Transport/`，避免 `Util` 包变成"什么都往里放"。维持 `Util/` 也合理——这是品味问题。

### 14.4 `utils/math.py` 偏薄（43 行）

可以接受。如果未来还要加旋转矩阵相关数学（例如 ZYX Euler / SE3 平均），就让它自然增长；不要为了"凑大小"反向把代码塞进来。

## 15. 阶段 4 实施顺序与验证

按风险从低到高：

1. **删 `clearFilters` / `clearAnchorPose` 方法重载（12.2）**——无破坏性，编译即验证；
2. **拆 `tracking_runtime.py`（12.1）**——纯 Python，跑 `pixi run python -m unittest discover -s src -p "test_*.py"` + `pixi run python ./src/tracking_server.py` 烟雾即可；
3. **拆 `PoseToAnchorRuntime.Events.cs`（12.3）**——partial 拆分，编译验证 + Unity Inspector 引用是否完整；
4. **`Anchor/` 子目录调整（13.1）**——文件移位，必须 `git mv` 保留历史 + Unity Editor 重新生成 csproj。

每步完成后跑 AGENTS.md 中"常用入口与验证"的 4 条命令：

```powershell
cd EgoAnchor_Python
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python .\src\tracking_server.py

cd ..
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

12.3 + 13.1 完成后，加跑：
- Unity Editor 打开场景，确认 `PoseToAnchorRuntime` Inspector 上 `policyHost` 引用未丢失；
- 真机 / replay：raw + smoothed 两条 anchor 在 policy 启用 / 关闭各 1 次，对比静态 + 头动场景。

## 16. 不动的清单（再次重申）

阶段 4/5 同样不允许：
- 改 `subjects.v1.json` channel 列表 / proto 字段号；
- 把 SAM3 设默认；
- 把 FoundationPose 状态搬出 `TrackingRuntime` owner 线程；
- 把 `AnchorPolicyHostBase` 删掉或合并进 `AnchorPolicyHost`（13.2 已论证）；
- 调整 asmdef 依赖方向（必须保持 `Reliability → Anchor`）。

---

## 17. 阶段 4 收尾后的验收指标

| 维度 | 当前 | 阶段 4 后预期 |
|---|---|---|
| `tracking_runtime.py` | 576 行 | < 450 行 |
| `PoseToAnchorRuntime.Events.cs` | 336 行 | < 180 行 + 新 partial `PolicyNotifications.cs` < 180 行 |
| `AnchorCommandClient` ack 清理路径 | 双路径（ack + status） | 单路径（status 唯一） |
| `Anchor/` 平铺文件数 | 14 | Runtime/Policy/Processor 三子目录 |
| `AnchorPolicyHostBase.cs` 名字混淆度 | 高（与 Host 命名相近） | 移到 `Anchor/Policy/` 后通过路径区分 |

主要可量化收益：**Python tracking 路径关键文件全部 <500 行；Unity Anchor 层职责按目录分组、partial 文件不再单文件超 180；ack 阶段不再触发本地状态清理（与 AGENTS.md 一致）**。
