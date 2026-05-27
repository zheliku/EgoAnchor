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

