# EgoAnchor 结构规范化与瘦身计划

## Summary
- `AnchorPolicyHostBase.cs` 按你当前偏好应删除。理由不是“放错目录”，而是它现在只有一个具体实现，且你已经明确不保留仅有单子类的抽象层。
- `AnchorPolicyHost.cs` 不建议单独从 `Reliability/` 挪到原 `Anchor/Policy/`；正确做法是把整组 reliability-aware policy 实现一起并入新的顶层 `Policy/` 目录。
- Python `egoanchor/runtime` 建议做强收敛：把通用工具移出、把单调用方薄文件合并，目标从当前 `16` 个脚本收敛到 `7` 个左右。

## Unity Structure
- 取消 `Anchor/` 这层壳，把其子域提升到 `Assets/Scripts/EgoAnchor` 根下的顶层功能目录。
- 目标目录结构：
  - `Runtime/`：`PoseToAnchorRuntime*.cs`、`DynamicObjectAnchor.cs`、`AnchorRuntimeHub.cs`
  - `Alignment/`：`CameraPoseFrameAligner.cs`、`FramePoseHistory.cs`、`CameraReference.cs`
  - `Policy/`：`AnchorObservation.cs`、`AnchorPolicyDecision.cs`、`AnchorLifecycleEvent.cs`、`AnchorStateMachine.cs`、`PolicyController.cs`、`ReliabilityGate.cs`、`ReliabilityScore.cs`、`InnovationGate.cs`、`AnchorPredictor.cs`、`AnchorPolicyHost.cs`、`PoseToAnchorRuntime.PolicyNotifications.cs`
  - `Processors/`：`AnchorPoseProcessor.cs`、`AnchorLowPassPoseProcessor.cs`、`AnchorKalmanPoseProcessor.cs`
  - `Quest/`：`StereoFrameSource.cs`、`CameraInfoSource.cs`
  - `Client/`：`NatsControlClient.cs`、`NatsTypedReceiver.cs`、`PoseResultReceiver.cs`、`AnchorStatusReceiver.cs`、`ServerHeartbeatReceiver.cs`、`AnchorCommandClient.cs`、`QuestStreamPublisher.cs`
  - `Transport/`：`NatsBytesClient.cs`、`ZmqTopicPublisher.cs`
  - `Protocol/`、`Diagnostics/` 保持独立
- 具体决策：
  - 删除 `Policy/AnchorPolicyHostBase.cs`
  - `PoseToAnchorRuntime.policyHost` 字段类型改为具体 `AnchorPolicyHost`
  - `LatestOnlyQueue.cs` 不再放 `Util/`；合并进 `Client/NatsControlClient.cs` 作为私有辅助类型
  - `NatsControlClient.cs` 从 `Transport/` 移到 `Client/`，因为它已理解 `SubjectNames`、latest/event queue 和消费语义
  - `FramePoseHistory.cs` 与 `CameraReference.cs` 从 `Quest/` 移到 `Alignment/`，因为它们服务的是 frame-aligned anchoring，而不是采集设备本身
- 程序集配套：
  - 根下保留单个 `EgoAnchor.asmdef`
  - 删除子 asmdef
  - 统一外部依赖到根 asmdef
- 文档配套：
  - 更新 `AGENTS.md` 中所有 `Anchor/Policy`、`Reliability/`、`AnchorPolicyHostBase` 的描述
  - 明确新规则：按功能聚合，不为单一实现保留抽象壳

## Python Runtime
- `EgoAnchor_Python/src/egoanchor/runtime` 目标结构：
  - `tracking_runtime.py`
  - `quest_stream_receiver.py`
  - `commands.py`
  - `message_factories.py`
  - `runtime_log_writer.py`
  - `runtime_state.py`
  - `__init__.py`
- 具体合并方案：
  - `latest_value_store.py` 移到 `egoanchor/utils/latest_value_store.py`
  - `latest_quest_input_store.py` 合并进 `quest_stream_receiver.py`
    - `LatestQuestInputStore` 改为该文件内部实现
    - `QuestInputStats` 保留为该文件公开类型
  - `pose_log_factory.py` 合并进 `runtime_log_writer.py`
  - `pose_result_factory.py`、`status_event_factory.py`、`heartbeat_factory.py` 合并为 `message_factories.py`
  - `command_models.py`、`command_dedup.py`、`command_queue.py`、`command_executor.py`、`command_pump.py` 合并为 `commands.py`
- 明确保留：
  - `runtime_state.py` 保留单文件，不并入大文件
  - `quest_stream_receiver.py` 保留单文件，因为 probe 和 runtime 都会直接用
  - `tracking_runtime.py` 保持 owner/coordinator 角色，不继续塞回 helper 细节
- 配套更新：
  - 更新 `runtime/__init__.py` 包级导出
  - 更新 `async_segmenter.py` 对 `LatestValueStore` 的导入
  - 更新现有单测导入路径，但尽量保留测试语义不变

## Public Interfaces / Type Changes
- Unity：
  - `PoseToAnchorRuntime.policyHost` 从 `AnchorPolicyHostBase` 改为 `AnchorPolicyHost`
  - 场景与 Inspector 需要重序列化该字段
- Python：
  - `egoanchor.runtime` 的导出项改为新的聚合文件来源
  - `LatestValueStore` 不再从 `egoanchor.runtime` 暴露，改从 `egoanchor.utils` 使用
- 不改：
  - Proto 字段
  - `subjects.v1.json`
  - ZMQ/NATS 主线契约
  - reliability-aware policy 的行为语义

## Test Plan
- Python：
  - `pixi run python -m compileall src`
  - `pixi run python -m unittest discover -s src -p "test_*.py"`
  - 重点回归 `test_command_flow.py`、`test_status_heartbeat_factories.py`、`test_pose_log_factory.py`、runtime event logger 相关测试
- Unity：
  - `dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore`
  - 重新生成 Unity C# project，确认只剩根 asmdef
  - 打开 `Assets/Scene/Test-QuestStreamSender.unity`
  - 核对 `PoseToAnchorRuntime.policyHost`、`AnchorPolicyHost`、各 Receiver、`NatsControlClient`、`QuestStreamPublisher` 无 Missing Script
- 结构验证：
  - 检查 `AGENTS.md` 与真实目录一致
  - 检查 `rg` 搜索结果中不再残留旧目录名和旧类型名

## Assumptions
- 当前只需要一个 reliability-aware policy 实现；若未来出现第二个 policy host，再重新引入接口或抽象基类。
- 本轮目标优先是“目录职责清楚 + 文件数减少 + 单程序集”，不是保留最大扩展性。
- `AnchorPolicyHost.cs` 的正确归宿取决于“整组 policy 实现一起迁移”；不做单文件孤立挪动。
