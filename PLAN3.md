# EgoAnchor 最终精简与单程序集化方案

## Summary
- 本方案完整合并 `p-vscode-project-egoanchor-agents-md-un-serialized-rain.md`、`PLAN.md`、`PLAN2.md` 的非冲突内容；只在已确认的冲突点上采用你的选择：`Unity 强归一化`、`同步 namespace`、`删除 AnchorPolicyHostBase`、`Python runtime 强收敛`。
- 当前基线以已验收状态为起点：`tracking_runtime.py` 已收缩到 `351` 行，`PoseToAnchorRuntime.Events.cs` 为 `103` 行，`Anchor` 已拆出 `Runtime/Policy/Processor`；本地验证已通过 `pixi run python -m compileall src`、Python 单测 `51` 通过 `1` 跳过、`dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore` 通过；当前规模约为 Python `7484` 行、Unity `12270` 行（均不含 Generated）。
- 本轮目标是把主线进一步收敛到：Python `runtime` 约 `7` 个文件、Unity `Assets/Scripts/EgoAnchor` 仅 `1` 个 asmdef、`Reliability/` 与 `Util/` 根目录消失、目录职责与命名空间一一对应，同时不触碰协议、不回退架构。

## Implementation Changes
- 实施顺序固定为：`基线锁定` → `Python 入口与 runtime 精简` → `Unity 行为等价瘦身` → `Unity 目录与 namespace 归一化` → `单 asmdef 合并（最后执行）` → `AGENTS/README/任务脚本同步`。
- Python 入口清理按整条链路删除，而不是只删包内模块：删除 `src/egoanchor/app/probes.py`、`src/egoanchor/app/yoloe_mask_probe.py`，同时删除仅做转发的 `src/quest_video_stream_demo.py` 与 `src/yoloe_mask_probe.py`，清理 `egoanchor.app.__init__`、`pixi.toml` 中对应 demo task、`src/README.md` 与 `AGENTS.md` 中的旧入口说明；保留 `tracking_server.py`、`tool-yoloe26-mask`、`tool-sam3-mask` 作为存活入口。
- Python `transport/_lifecycle.py` 内联到 `ZmqTopicSubscriber` 与 `NatsMessageClient`，删除该基类文件，但保留原有 `starting/closing` 日志语义与重连行为。
- Python `perception/pipeline_helpers.py` 整体并回 `quest_pose_pipeline.py`，接受主文件重新变大，不再为了行数指标保留 mixin 壳；`pipeline_types.py` 与 `async_segmenter.py` 保持独立；执行时额外核查 `diagnostics/window.py`，若仍存在则删除，否则记为 no-op。
- Python `egoanchor/runtime` 强收敛为 `tracking_runtime.py`、`quest_stream_receiver.py`、`commands.py`、`message_factories.py`、`runtime_log_writer.py`、`runtime_state.py`、`__init__.py`：把 `latest_quest_input_store.py` 并入 `quest_stream_receiver.py`，把 `command_models.py`/`command_dedup.py`/`command_queue.py`/`command_executor.py`/`command_pump.py` 并为 `commands.py`，把 `pose_result_factory.py`/`status_event_factory.py`/`heartbeat_factory.py` 并为 `message_factories.py`，把 `pose_log_factory.py` 并入 `runtime_log_writer.py`，并将 `latest_value_store.py` 外提到 `egoanchor/utils/latest_value_store.py`。
- Python 保留项固定不删：`runtime_state.py` 继续作为共享状态类型模块，`tracking_runtime.py` 继续作为唯一 owner/coordinator，所有非空 re-export `__init__.py` 保留，不为“少文件数”删除它们。
- Unity 先做行为等价瘦身：把 `PoseToAnchorRuntime` 的 `Events/Diagnostics/ServerNotifications/PolicyNotifications` 全部合回单一 `Runtime/PoseToAnchorRuntime.cs`，允许该文件重新回到约 `600+` 行，并用 `#region` 保持章节；同时清理 `AnchorCommandClient` 的 `lastRequestId/lastSubject/lastAccepted/lastDuplicate/lastStatus/lastMessage` 及相关公开属性，只保留业务计数器。
- Unity 删除 `AnchorPolicyAction.Reset` 枚举值，凡是仍需表达 reset 语义的地方统一改成 `Reject + reason="reset"` 一类文本原因，不保留空转枚举。
- Unity `Diagnostics/EventLogPanel` 改为 TMP-only，删除 `legacyText`、`UnityEngine.UI.Text` 兼容路径与对应 `using`；`Client/README_CommandControl.md` 在其必要接线说明并入 `AGENTS.md` 或 Inspector 注释后删除。
- Unity 目录按顶层功能重新归位为 `Runtime/`、`Alignment/`、`Policy/`、`Processors/`、`Quest/`、`Client/`、`Transport/`、`Protocol/`、`Diagnostics/`：`Anchor` 这层壳整体取消；`CameraPoseFrameAligner`、`FramePoseHistory`、`CameraReference` 移到 `Alignment/`；`AnchorRuntimeHub`、`DynamicObjectAnchor`、合并后的 `PoseToAnchorRuntime` 移到 `Runtime/`；三个 processor 移到 `Processors/`；`StereoFrameSource` 与 `CameraInfoSource` 继续留在 `Quest/`。
- Unity policy 侧做整组迁移而不是单文件挪动：删除 `Policy/AnchorPolicyHostBase.cs`，把 `PoseToAnchorRuntime.policyHost` 改为具体 `AnchorPolicyHost`，并把 `ReliabilityGate`、`ReliabilityScore`、`InnovationGate`、`AnchorPredictor`、`PolicyController`、`AnchorPolicyHost` 连同原 `AnchorObservation`、`AnchorPolicyDecision`、`AnchorLifecycleEvent`、`AnchorStateMachine` 一起统一到顶层 `Policy/`；`AnchorPolicyHost.cs` 不能单独移动，必须随整组 policy 实现一起归位。
- Unity client/transport 重新定界：`NatsControlClient.cs` 从 `Transport/` 移到 `Client/`，因为它已经理解 `SubjectNames`、latest/event queue 与消费语义；`NatsBytesClient.cs`、`ZmqTopicPublisher.cs` 保留在 `Transport/`；`LatestOnlyQueue<T>` 与 `EventQueue<T>` 的类型语义保留，但不再作为根 `Util/` 公共文件存在，而是与 `NatsControlClient` 同域放置；`Util/` 清空后删除。
- Unity namespace 与目录同步：所有手写脚本统一改到新的 `EgoAnchor.Runtime`、`EgoAnchor.Alignment`、`EgoAnchor.Policy`、`EgoAnchor.Processors`、`EgoAnchor.Client`、`EgoAnchor.Transport`、`EgoAnchor.Diagnostics`、`EgoAnchor.Quest`、`EgoAnchor.Protocol`；生成的协议代码保持生成侧 namespace，不为整洁强行改动生成物。
- Unity 单程序集收口必须最后做：删除 `Anchor`、`Client`、`Diagnostics`、`Protocol`、`Quest`、`Reliability`、`Transport`、`Util` 下现有 `8` 个 asmdef，只在 `Assets/Scripts/EgoAnchor` 根下保留一个 `EgoAnchor.asmdef`；根 asmdef 挂接真实依赖，默认包含 `Oculus.VR`、`meta.xr.mrutilitykit`、`Unity.TextMeshPro`，并仅在全局搜索仍有活跃引用时保留 `UnityEngine.UI`；`NATS.Net/NetMQ/Google.Protobuf` 默认沿用 Plugins 自动引用，只有在最终构建证明缺失时才补显式 `precompiledReferences`。
- Unity 还要做一次零引用清扫，但删除标准固定为“四项同时满足”：`无代码引用`、`无场景/Prefab 引用`、`AGENTS.md 未声明`、`不是主线入口或主线对照能力`；同时优先复查 `AnchorCommandClient`、`NatsControlClient`、`CameraPoseFrameAligner`、`QuestStreamPublisher` 这几个热点脚本，只做无行为变化的样板压缩。

## Public Interfaces / Types
- Unity 公开变更：`PoseToAnchorRuntime.policyHost` 从 `AnchorPolicyHostBase` 变为 `AnchorPolicyHost`；`NatsControlClient`、`FramePoseHistory`、`CameraReference`、processor 与 policy 相关类的 namespace 都会变化；`EventLogPanel` 只再接受 `TMP_Text`。
- Unity 编译模型变更：`Assets/Scripts/EgoAnchor` 从多 asmdef 收敛为单一 `EgoAnchor` 程序集，但 `Protocol/SubjectNames`、Protobuf DTO、NATS/ZMQ channel 契约完全不变。
- Python 公开变更：`egoanchor.runtime` 的导出来源改为聚合文件；`LatestValueStore` 改从 `egoanchor.utils` 导入；`quest_video_stream_demo.py` 与 `yoloe_mask_probe.py` 两条旧入口链退役，相关 README / task / AGENTS 说明同步删除。

## Test Plan
- 基线门禁先固定当前绿态：执行 `pixi run python -m compileall src`、`pixi run python -m unittest discover -s src -p "test_*.py"`、`dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore"`，把现在的 `51 pass + 1 skip + Unity build pass` 作为后续每阶段回归参照。
- Python 每个结构阶段后都重复 `compileall + 全量 unittest`；`_lifecycle` 内联后额外做一次 NATS 断开/恢复 smoke，确认日志与重连行为不变；`quest_pose_pipeline` 回并后运行 `tracking_server.py`，确认 `mask_src`、`pose_source`、异步分割计数等 HUD 指标与改动前一致。
- Unity 每个结构阶段后都重复 `dotnet build`，并打开 `Assets/Scene/Test-QuestStreamSender.unity` 检查 `PoseToAnchorRuntime`、`AnchorPolicyHost`、`NatsControlClient`、三个 receiver、`QuestStreamPublisher`、raw/smoothed anchor 路径都无 Missing Script、序列化引用不丢。
- 单 asmdef 合并完成后，关闭 Unity Editor；若出现程序集缓存问题，删除 `Library/ScriptAssemblies` 再重开；确认不存在 `Assembly with name 'EgoAnchor.*' not found`、第三方依赖丢失、或旧程序集名残留错误。
- 端到端 smoke 最终必须覆盖：`ResetTracking`、`ForceReacquire`、`PauseTracking`、`ResumeTracking`、`SetStage` 命令闭环仍正常；raw、low-pass、Kalman、policy runtime 仍共享同一 `PoseResult` 输入；TMP-only 事件面板仍能显示状态/策略事件；全局 `rg` 不再残留 `AnchorPolicyHostBase`、旧 asmdef 名、删除脚本路径和旧 namespace。

## Assumptions
- 三份计划中只要不冲突的内容都已纳入本方案；只出现在某一份计划中的条目默认保留，而不是丢弃。
- 已锁定的默认选择就是最终口径：`Unity 强归一化 + namespace 同步`、`删除 AnchorPolicyHostBase`、`Python runtime 强收敛`、`旧 probe / YOLOE 独立入口链整体退役`。
- 整个重构必须严格保持现有主线语义：不改 proto 字段号、不改 `subjects.v1.json`、不把 SAM3 设为默认、不把 FoundationPose/Cutie owner 从 `TrackingRuntime` 挪走、不删除 raw/low-pass/Kalman 对照能力，并且对 `AGENTS.md` 采用“直接改旧事实”而不是“追加互相矛盾的新说明”。
