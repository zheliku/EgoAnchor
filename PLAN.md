# EgoAnchor 主线精简与 Unity 单程序集化计划

## Summary
- 验收结论：当前主线已达到可继续收敛的稳定状态。实际验证结果是 Python `compileall` 通过、Python 单测 `51` 个通过 `1` 个跳过、Unity `dotnet build` 通过。
- 当前事实：Python 主线已经基本收敛；Unity 代码目录也已按 `Anchor/Runtime`、`Anchor/Policy`、`Anchor/Processor` 分组，但 `Assets/Scripts/EgoAnchor` 现在仍是 `8` 个 asmdef，不是单一程序集。
- 本轮范围只覆盖主线代码：`EgoAnchor_Python/src/egoanchor`、`EgoAnchor_Unity/Assets/Scripts/EgoAnchor` 及其直接关联的 Unity 场景/元数据。
- 精简策略采用“中等精简”：保留论文对照链路与主线能力，优先删除重复边界、兼容分支、单用途薄层和不必要文件，不做协议回退、不删 baseline。

## Key Changes
- Unity 程序集改为单根 asmdef。
  - 在 `EgoAnchor_Unity/Assets/Scripts/EgoAnchor` 根下保留一个 `EgoAnchor.asmdef`。
  - 删除现有子 asmdef：`Anchor`、`Client`、`Diagnostics`、`Protocol`、`Quest`、`Reliability`、`Transport`、`Util`。
  - 保留现有目录分组，不把 `Anchor/Runtime`、`Anchor/Policy`、`Anchor/Processor` 再打散；只改程序集粒度，不改 namespace。
  - 根 asmdef 统一接住当前真实依赖：`Oculus.VR`、`meta.xr.mrutilitykit`、`Unity.TextMeshPro`，以及精简后仍实际使用的 Unity/package 引用。
  - 明确结果：`Assets/Scripts/EgoAnchor` 会编译成一个 `EgoAnchor` 程序集；项目里其他未纳入 asmdef 的脚本仍可继续属于 `Assembly-CSharp`。

- Unity 侧配套瘦身。
  - 保留 `AnchorPolicyHostBase`，不删除、不并入 `AnchorPolicyHost`；它继续作为 `PoseToAnchorRuntime` 依赖的抽象契约。
  - 把 `LatestOnlyQueue.cs` 从 `Util/` 收回到 `Transport/` 或 `Client/Transport` 邻近位置；若 `Util` 只剩这一项，则删掉 `Util/` 目录。
  - 精简 `Diagnostics/EventLogPanel`：移除 `legacyText` 和 `UnityEngine.UI.Text` 兼容路径，统一只保留 `TMP_Text`。
  - 删除 `Client/README_CommandControl.md`，前提是其必要说明已吸收到 `AGENTS.md` 或场景接线已足够直观。
  - 对 `Assets/Scripts/EgoAnchor` 做一次零引用清扫：只删除“无代码引用、无场景引用、AGENTS 未声明、不是主线入口”的文件或成员。

- Python 侧只做保守清扫，不再为了“更少文件”强行重构。
  - 维持当前 `runtime/perception` 结构，不再追求继续拆/并文件。
  - 重点检查并删除无效导出、陈旧注释、无入口引用的文档或残留辅助物。
  - `RuntimeLogWriter`、`PoseLogFactory`、`HeartbeatFactory`、`CommandPump` 当前都有明确引用与职责，默认保留，不做为删减目标。

- 二次审查重点。
  - Unity 后续优先再看这几个手写热点：`Client/AnchorCommandClient.cs`、`Transport/NatsControlClient.cs`、`Anchor/Runtime/CameraPoseFrameAligner.cs`、`Client/QuestStreamPublisher.cs`。
  - 只有在能明确减少重复 Inspector 样板、单用途 helper 或伪分层时才继续瘦身；不为了行数做行为层改写。

## Public Interfaces / Types
- Unity 对外程序集身份从多 asmdef 收敛为单个 `EgoAnchor` asmdef；现有代码 namespace 保持不变。
- `EventLogPanel` Inspector 输出接口改为 TMP-only；若场景里仍绑定旧 `Text`，需要同步迁移。
- 不修改 Protobuf、`subjects.v1.json`、Python 包入口、Quest/ZMQ/NATS 主线契约。

## Test Plan
- Python 验证：
  - `pixi run python -m compileall src`
  - `pixi run python -m unittest discover -s src -p "test_*.py"`
- Unity 构建验证：
  - `dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore`
  - Unity 重新生成 C# project，确认 `Assets/Scripts/EgoAnchor` 只对应单个 `EgoAnchor` 程序集。
- Unity 场景与序列化验证：
  - 打开 `Assets/Scene/Test-QuestStreamSender.unity`，确认 `PoseToAnchorRuntime`、`AnchorCommandClient`、`NatsControlClient`、`QuestStreamPublisher`、`AnchorPolicyHost`、各 Receiver 无 Missing Script。
  - 检查场景/Prefab 重序列化后，旧程序集名引用不再残留为无效绑定。
- 运行时 smoke：
  - 验证 `ResetTracking`、`ForceReacquire`、`PauseTracking`、`ResumeTracking`、`SetStage` 仍走原 command/status 闭环。
  - 验证 raw、low-pass、Kalman、policy runtime 仍共享同一 `PoseResult` 输入，不在 ack 阶段提前清理本地状态。
  - 验证 `EventLogPanel` 在只用 TMP 的情况下仍正常显示状态事件。

## Assumptions
- 本计划基于当前脏工作区继续推进，不能回退你现有未提交改动。
- “尽可能精简”本轮解释为：优先减少程序集和无价值兼容层，不牺牲论文实验对照能力。
- `Anchor/Runtime`、`Anchor/Policy`、`Anchor/Processor` 目录继续保留；你想收敛的是程序集，不是职责分组。
