# EgoAnchor 代码精简 + Unity asmdef 合并工程报告（Phase 5）

## Context

Phase 1~4（拆巨型文件 / 抽公共模板 / 配置整合 / asmdef 分层）已全部落地。本轮目标转向**收敛**：
1. **Phase 4 验收闭环**：确认上一轮 4 项收尾任务均已完成；
2. **代码精简**：删除不必要的文件、过度拆分的层、纯诊断字段，让代码量与心智负担继续下降；
3. **Unity asmdef 反向合并**：把 Phase 3 建立的 8 个 asmdef 反向合并为顶层单一 `EgoAnchor.asmdef`。用户明确表态 asmdef 颗粒度过细，子目录不再分别成包；保留单一 asmdef 仍能正确隔离 NATS/NetMQ/Meta.XR 这些第三方依赖。

约束：保留 AGENTS.md "不要回退" 红线（双平面、frame-aligned anchor、单 owner runtime、SAM3 非默认）；Phase 1~4 已沉淀的命名 / 目录 / 工厂分层不动；本轮不改任何 protocol 字段。

---

## 1. Phase 4 验收（全部 ✅）

| 收尾项 | 目标 | 实测 | 结论 |
|---|---|---|---|
| `tracking_runtime.py` 收缩 | < 500 行 | **351 行** | ✅ 远超目标，工厂三件套（`pose_log_factory.py:49` / `heartbeat_factory.py:67` / `command_pump.py:78`）已落地 |
| `AnchorCommandClient` 删 ack 阶段清理重载 | 删双参数 `ResetTrackingAsync` | 已删，仅剩单参数版本 | ✅ |
| `PoseToAnchorRuntime.Events.cs` 收缩 | < 180 行 | **103 行**，新增 `PolicyNotifications.cs:130` / `ServerNotifications.cs:89` | ✅ |
| `Anchor/` 子目录 | Runtime/Policy/Processor 三组 | 已建：Runtime 7 文件 / Policy 6 文件 / Processor 3 文件 | ✅ |

**整体规模**：Python 7484 行（不含 Generated）/ Unity 12270 行（不含 Generated）。本轮目标在此基础上再精简。

---

## 2. Phase 5 工作清单

### 2.1 Python 精简（5 项）

#### 2.1.1 删除 `app/probes.py`（确认）
- 文件位置：[EgoAnchor_Python/src/egoanchor/app/probes.py](EgoAnchor_Python/src/egoanchor/app/probes.py)
- 理由：纯 ZMQ 数据面联通诊断，AGENTS.md 主线入口仅列 `tracking_server.py`；其能力已被真机 / replay smoke 覆盖。
- 动作：删除文件 + grep 全工程消除 import / CLI 引用。

#### 2.1.2 删除 `app/yoloe_mask_probe.py`（确认）
- 文件位置：[EgoAnchor_Python/src/egoanchor/app/yoloe_mask_probe.py](EgoAnchor_Python/src/egoanchor/app/yoloe_mask_probe.py)
- 理由：YOLOE 推理路径已经被 `tracking_server` + 真机回放覆盖，不再需要独立 probe；用户明确同意删除。
- 动作：删除文件 + grep 引用。

#### 2.1.3 内联 `transport/_lifecycle.py: BaseTransportClient`
- 文件位置：[EgoAnchor_Python/src/egoanchor/transport/_lifecycle.py](EgoAnchor_Python/src/egoanchor/transport/_lifecycle.py)
- 理由：当前仅 2 个具体子类（`ZmqTopicSubscriber`、`NatsMessageClient`），且都只用 `begin_start / cancel_start / begin_close` 三个状态机方法。基类只是状态字典，没有共享业务逻辑。
- 动作：把 3 个状态机方法和字段直接内联到两个子类（每个新增 ~15 行），删除 `_lifecycle.py`。两个子类的启动 / 关闭日志保持原样。

#### 2.1.4 合并 `perception/pipeline_helpers.py` 回主 pipeline
- 文件位置：[EgoAnchor_Python/src/egoanchor/perception/pipeline_helpers.py](EgoAnchor_Python/src/egoanchor/perception/pipeline_helpers.py) （377 行 mixin）
- 理由：单文件 mixin 仅被 `QuestPosePipeline` 一个类继承，拆出来纯粹是为了让 Phase 1 的"主文件 < 700"指标好看。现在主文件 553 行，把 helpers 合回去后预计 ~900 行——比 Phase 1 前 1153 行仍少 22%，且**不再有"helper 是不是基类"的迷惑性**。
- 动作：把 mixin 全部方法平铺回 `quest_pose_pipeline.py`，删 `pipeline_helpers.py`。`pipeline_types.py` 和 `async_segmenter.py` **保留**（它们是真分层）。

#### 2.1.5 `__init__.py` 处理（按用户答复"只清理纯空壳"）
- 实测 `config/handlers/reliability/routing` 4 个 `__init__.py` 都各 re-export 1 个符号（不是纯空壳）；按用户口径"纯空壳才删"——**实际 4 个全部保留**。
- 不做任何动作。

#### 2.1.6 `runtime/` 目录合并（16 → 11 文件）

实测 `runtime/` 共 16 个文件，依赖与外部使用情况清晰，按"是否真耦合"分两组：

**合并组 A：command 流水线 5 文件 → 1 文件**

涉及：
- [command_models.py](EgoAnchor_Python/src/egoanchor/runtime/command_models.py) 31 行（`CommandType` / `RuntimeCommand`）
- [command_dedup.py](EgoAnchor_Python/src/egoanchor/runtime/command_dedup.py) 45 行（`CommandDedupStore`）
- [command_queue.py](EgoAnchor_Python/src/egoanchor/runtime/command_queue.py) 58 行（`CommandQueue`）
- [command_executor.py](EgoAnchor_Python/src/egoanchor/runtime/command_executor.py) 116 行（`CommandExecutor` + `command_handler` 装饰器）
- [command_pump.py](EgoAnchor_Python/src/egoanchor/runtime/command_pump.py) 78 行（`CommandPump`）

合并理由：
1. 这 5 文件形成完整流水线 `models → (dedup, queue) → executor → pump`，内部双向 import；
2. 外部只有 `handlers/command_handlers.py` 引用 `CommandType` 一项；
3. 总行数 328，合并后单文件 ~330 行不算膨胀，避免"5 个 30~120 行小文件互相 import"的导航负担。

动作：合并为 `runtime/command_pipeline.py`，按 `models → dedup → queue → executor → pump` 顺序排列；`__init__.py` 的 re-export 保持不变（外部 import 路径 `from egoanchor.runtime import CommandType` 不受影响）。

**合并组 B：Quest 输入流水线 2 文件 → 1 文件**

涉及：
- [latest_quest_input_store.py](EgoAnchor_Python/src/egoanchor/runtime/latest_quest_input_store.py) 108 行（`LatestQuestInputStore` + `QuestInputStats`）
- [quest_stream_receiver.py](EgoAnchor_Python/src/egoanchor/runtime/quest_stream_receiver.py) 72 行（`QuestStreamReceiver`）

合并理由：
1. `quest_stream_receiver` 直接组装 `LatestQuestInputStore`，两者是"接收 → 写入"流水线；
2. `LatestQuestInputStore` 没有任何 runtime 之外的调用方；`QuestStreamReceiver` 原本被 `app/probes.py` + `app/yoloe_mask_probe.py` 引用，但**这两个文件本轮 2.1.1/2.1.2 已删**——合并后外部唯一调用方就是 `tracking_runtime`；
3. 总行数 180，合并后单文件保持轻量。

动作：合并为 `runtime/quest_input_pipeline.py`。注意必须先做 2.1.1/2.1.2（删 probes / yoloe_mask_probe），再做这个合并，否则会断 demo 引用。

**保留分离的 3 组**（评估后判定不合并）：

| 候选 | 涉及 | 决定 | 理由 |
|---|---|---|---|
| 4 个 `*_factory.py` | `heartbeat_factory.py:67` / `pose_result_factory.py:84` / `pose_log_factory.py:49` / `status_event_factory.py:78` | **不合并** | 消费者不同（heartbeat 写 NATS / pose_result 写 NATS / pose_log 写 JSONL / status 写 NATS），文件之间**无 import**；共享的 header 构造已经被 Phase 4 抽到 `protocol/header_utils.py`。合并只是把 4 个独立工厂粘在一个 280 行文件里，不消除任何真实重复 |
| `latest_value_store.py` 47 + `latest_quest_input_store.py` 108 | | **不合并** | 前者是通用 latest-only 容器，被 `perception/async_segmenter.py` 复用；后者是 Quest 业务特化。合并会让通用容器粘上 Quest 业务字段 |
| `runtime_state.py` 36 + `status_event_factory.py` 78 | | **不合并** | `RuntimeState` 被 4 个文件 import（heartbeat_factory / runtime_log_writer / command_pump / tracking_runtime），是真正的公共数据类型，不能并到任何单一消费者文件里 |

**目录最终形态**（16 → 11 文件）：

```
runtime/
├── __init__.py
├── command_pipeline.py          ← 新（合并 5 文件）
├── quest_input_pipeline.py      ← 新（合并 2 文件）
├── heartbeat_factory.py         ← 保留
├── latest_value_store.py        ← 保留（通用容器）
├── pose_log_factory.py          ← 保留
├── pose_result_factory.py       ← 保留
├── runtime_log_writer.py        ← 保留
├── runtime_state.py             ← 保留（公共数据类型）
├── status_event_factory.py      ← 保留
└── tracking_runtime.py          ← 保留（主编排）
```

### 2.2 Unity 精简（4 项）

#### 2.2.1 合并 `PoseToAnchorRuntime` 4 个 partial 为 1 个文件（确认）
- 当前文件：
  - `Anchor/Runtime/PoseToAnchorRuntime.cs` 270 行
  - `Anchor/Runtime/PoseToAnchorRuntime.Events.cs` 103 行
  - `Anchor/Runtime/PoseToAnchorRuntime.Diagnostics.cs` 52 行
  - `Anchor/Runtime/PoseToAnchorRuntime.ServerNotifications.cs` 89 行
  - `Anchor/Policy/PoseToAnchorRuntime.PolicyNotifications.cs` 130 行
- 用户决定：合回单一 `Anchor/Runtime/PoseToAnchorRuntime.cs`，**预计合并后 ~614 行**，超出 Phase 4 设的 450 上限。
- 这是一次有意识的回退：用户认为单文件可读性 > 单文件行数指标。Phase 4 的 450 上限作废。
- 动作：
  1. 把 4 个 partial 的方法 / 嵌套类按"主流程 → policy 通知 → server 通知 → events 辅助 → Diagnostics 嵌套类"顺序合到主文件；
  2. 删除 4 个 partial 文件 + 对应 `.meta`；
  3. 新增 `#region` 折叠（`#region Policy Notifications` 等）以保留章节感，**避免 614 行变成长杂揉**。

#### 2.2.2 删除 `AnchorCommandClient` 6 个 lastXxx SerializeField（确认）
- 文件：[EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Client/AnchorCommandClient.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Client/AnchorCommandClient.cs)
- 删除字段：`lastRequestId / lastSubject / lastAccepted / lastDuplicate / lastStatus / lastMessage`
- 同时删除：
  - `LastStatus` / `LastMessage` 两个 public 属性（无业务读取，仅暴露给 Inspector，实测无外部调用）；
  - `ApplyAck` / `RecordFailure` 内部对这 6 字段的赋值；
  - `Debug.Log` 字符串里仍输出 `lastRequestId` / `lastStatus` 等的部分改为读取局部变量。
- 保留：`sentCommands` / `acceptedAcks` / `rejectedAcks` / `failedCommands` 4 个累计计数器（这些是业务统计，不是单帧诊断）。

#### 2.2.3 删除 `AnchorPolicyAction.Reset` 未使用枚举值
- 文件：[EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Anchor/Policy/AnchorPolicyDecision.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Anchor/Policy/AnchorPolicyDecision.cs)
- 实测：`AnchorPolicyAction.Reset` 仅在 `PolicyController.cs` 内被赋值，无任何分支判断或下游消费。
- 动作：删除该枚举成员；如 PolicyController 内还有"Reset" 分支语义，统一改为 `Reject` + Reason 字符串携带 "reset"。

#### 2.2.4 删除 `diagnostics/window.py`（如存在则按 2.1.x，与 Python 一并）
- 已在 2.1 范围内，不重复。

### 2.3 Unity 目录归位 + 删除多余抽象（asmdef 合并的连带收益）

asmdef 合并到单一 dll 后，"为绕过 asmdef 反向依赖而存在的抽象 / 跨目录拆分" 失去依据。本节专门处理这部分。

#### 2.3.1 删除 `AnchorPolicyHostBase.cs`（Phase 4 决策翻转）

- 文件位置：[EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Anchor/Policy/AnchorPolicyHostBase.cs](EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Anchor/Policy/AnchorPolicyHostBase.cs)（53 行 abstract MonoBehaviour，7 个 abstract 成员）
- 全部引用：
  - 自身定义（1 处）
  - `Reliability/AnchorPolicyHost.cs:13` — `sealed class AnchorPolicyHost : AnchorPolicyHostBase`
  - `Anchor/Runtime/PoseToAnchorRuntime.cs:57` — `[SerializeField] private AnchorPolicyHostBase policyHost;`
- **它存在的唯一理由是 asmdef 反向依赖**：当年 `Anchor.asmdef` 不能依赖 `Reliability.asmdef`，所以 Anchor 只能持有本层抽象，由 Reliability 派生 sealed 实现。单 asmdef 后这个约束消失。
- **没有任何其它价值留存**：
  1. 整个工程只有一个具体派生类 `AnchorPolicyHost`，且本身 `sealed`；
  2. 没有任何测试 / mock / 替代实现派生它；
  3. EgoAnchor 是单一 app，不对外发布库，不需要"对外暴露抽象 API"。
- 保留它的代价：7 个 `override` 关键字仪式 + 53 行重复签名 + 读者误以为"另有实现"。
- 动作：
  1. `AnchorPolicyHost.cs` 7 个 `override` 改为普通 `public` 成员（删 `override` 关键字，签名不变）；
  2. `PoseToAnchorRuntime.cs:57` SerializeField 类型从 `AnchorPolicyHostBase` 改为 `AnchorPolicyHost`；
  3. 删除 `Anchor/Policy/AnchorPolicyHostBase.cs` + 对应 `.meta`。
- 风险：极低。Inspector 字段类型从 base 改为 sealed concrete 不影响序列化（Unity 按 GameObject + script GUID 反序列化，concrete 类 GUID 不变）。
- **第 5 节"不动清单"对应翻转**：原"删 `AnchorPolicyHostBase`"=保留 → 现 = 删除。Phase 4 13.2 论证"asmdef 时代承重墙"在 Phase 5 单 asmdef 下不成立。

#### 2.3.2 `Reliability/` 目录整体并入 `Anchor/Policy/`

`Reliability/` 6 个文件全部是 anchor policy 决策机器，"reliability" 是误命名 —— 它们其实是 **policy 决策管线的组件**。当前分目录的唯一原因也是 asmdef 反向依赖（Reliability.asmdef 单向依赖 Anchor.asmdef）。

| 文件 | 当前 | 目标 | 角色 |
|---|---|---|---|
| `ReliabilityScore.cs` | `Reliability/` | `Anchor/Policy/` | `ReliabilityGate.Evaluate()` 的输出数据结构（enum + struct） |
| `ReliabilityGate.cs` | `Reliability/` | `Anchor/Policy/` | policy 管线第一道门（reliability_score 阈值） |
| `InnovationGate.cs` | `Reliability/` | `Anchor/Policy/` | policy 管线第二道门（pose 跳变阈值） |
| `AnchorPredictor.cs` | `Reliability/` | `Anchor/Policy/` | policy 管线 coasting 状态的短时预测 |
| `PolicyController.cs` | `Reliability/` | `Anchor/Policy/` | policy 决策编排器，组合上述 4 个组件 + `AnchorStateMachine` |
| `AnchorPolicyHost.cs` | `Reliability/` | `Anchor/Policy/` | sealed MonoBehaviour，持有 `PolicyController` + Inspector 阈值 |

合并后 `Reliability/` 目录被清空，**整个删除**。"reliability 阈值" 这个语义在 `AnchorPolicyHost` 的 `[Header("Reliability Gate")]` 字段名上保留，足以表达。

动作：
1. 6 个文件物理移到 `Anchor/Policy/`，连同 `.meta`（保留 GUID）；
2. 删除空的 `Reliability/` 目录 + 其 `.meta`；
3. 命名空间保持不变（`namespace EgoAnchor.Reliability` 也可以保留，C# namespace 与目录结构无强绑定）—— 但既然概念归位，建议**同步把 6 个文件的 namespace 由 `EgoAnchor.Reliability` 改为 `EgoAnchor.Anchor`**，并相应在 `PoseToAnchorRuntime.cs` / `AnchorPolicyHost.cs` 调整 `using` 语句；
4. 与 2.3.1 顺序：先做 2.3.1（删 base），再做 2.3.2（移目录），避免半途状态混乱。

#### 2.3.3 `Util/LatestOnlyQueue.cs` 归位到 `Transport/`

- 当前位置：`Util/LatestOnlyQueue.cs`
- Grep 结果：唯一调用方是 `Transport/NatsControlClient.cs`（用于 PoseResult / Heartbeat 的 latest-only 缓冲）。
- 动作：移动到 `Transport/LatestOnlyQueue.cs`，连同 `.meta`；namespace 由 `EgoAnchor.Util` 改为 `EgoAnchor.Transport`；调整 `NatsControlClient.cs` 的 `using`。
- **验证 `Util/` 目录**：移走 `LatestOnlyQueue.cs` 后还剩什么？如果只剩 `EventQueue<T>` 等同样只被 Transport 使用的工具，可以一并并入 Transport 后删 `Util/`。本步骤执行前先 grep 一次 `Util/` 内剩余文件的引用方做最终决定。

#### 2.3.4 `PoseToAnchorRuntime.PolicyNotifications.cs` 归位

- 当前位置：`Anchor/Policy/PoseToAnchorRuntime.PolicyNotifications.cs`
- 这是 partial 文件分错目录的遗留 —— main class 在 `Anchor/Runtime/`，partial 却放在 `Anchor/Policy/`。
- 本计划 2.2.1 已经决定把 4 个 partial 全部合回 `PoseToAnchorRuntime.cs` 单文件，**该 partial 自然消失**，不需要单独"移动"动作。这里只是说明原本的目录错位问题在 2.2.1 一并解决。

### 2.4 Unity asmdef 反向合并（核心结构调整）

#### 现状（Phase 3 留下）
8 个 asmdef，依赖图：

```
Util ← Transport ←—————┐
Protocol ← Transport, Quest, Anchor ← Client
Quest ← Anchor ← Reliability ← Client
Diagnostics ← Anchor
```

外部包依赖：
- `Quest.asmdef` → Oculus.VR、meta.xr.mrutilitykit
- `Diagnostics.asmdef` → Unity.TextMeshPro、UnityEngine.UI

#### 目标
**单一 `Assets/Scripts/EgoAnchor/EgoAnchor.asmdef`**，子目录全部走该顶层 asmdef。

```json
{
  "name": "EgoAnchor",
  "rootNamespace": "EgoAnchor",
  "references": [
    "Oculus.VR",
    "meta.xr.mrutilitykit",
    "Unity.TextMeshPro",
    "UnityEngine.UI"
  ],
  "includePlatforms": [],
  "excludePlatforms": [],
  "allowUnsafeCode": false,
  "overrideReferences": false,
  "autoReferenced": true,
  "defineConstraints": [],
  "versionDefines": [],
  "noEngineReferences": false
}
```

如 NATS.Net / NetMQ / Google.Protobuf 当前是通过 `dll references`（`overrideReferences: true` + `precompiledReferences`）在 Transport.asmdef 内引入，需在合并时**复用同一份引用清单到顶层 asmdef**。本轮 Explore 阶段未找到这些 precompiled 字段（说明它们走的是 Plugins 自动引用 + `autoReferenced: true`）；合并时仅需把 4 个外部 Unity 包 reference 拷过来即可。

#### 删除清单（8 个 asmdef + 8 个 .meta）
- `Anchor/EgoAnchor.Anchor.asmdef`
- `Reliability/EgoAnchor.Reliability.asmdef`
- `Transport/EgoAnchor.Transport.asmdef`
- `Client/EgoAnchor.Client.asmdef`
- `Protocol/EgoAnchor.Protocol.asmdef`
- `Quest/EgoAnchor.Quest.asmdef`
- `Diagnostics/EgoAnchor.Diagnostics.asmdef`
- `Util/EgoAnchor.Util.asmdef`

#### 风险与防护
1. **Inspector 引用丢失**：asmdef 删除会触发 Unity 重新生成 csproj，所有 `MonoScript` 的 GUID 不变（GUID 来自 `.cs.meta`），所以 prefab / 场景里的脚本引用**不会断**。但 Editor 重新打开时如果 Unity 缓存异常，可能短暂报红 → 可以 `Library/ScriptAssemblies/` 删掉重生成。
2. **NATS / NetMQ DLL 自动引用**：当 8 个 asmdef 全部消失后，所有 EgoAnchor 脚本都走顶层 EgoAnchor.asmdef。如果第三方 DLL 是放在 `Plugins/` 目录下且 meta 文件 `validateReferences: true`，`autoReferenced: true` 会让顶层 asmdef 自动获得这些引用——大概率不需要手动加 precompiledReferences。**需要在执行阶段验证**：Unity Editor reimport 后 NATS / NetMQ / Google.Protobuf 是否仍能被发现。如果报错，再补 `precompiledReferences` 数组。
3. **rootNamespace 不动**：保持每个 .cs 的 `namespace EgoAnchor.Anchor` / `EgoAnchor.Transport` 等不变（不是 asmdef 改了 namespace 就要跟着改，C# namespace 是文件内独立声明）。
4. **第三方 asmdef 兼容**：检查 Plugins 下是否有 `*.asmref` 指向被删的 EgoAnchor.X asmdef——本轮 Explore 已确认**无 asmref**，安全。

---

## 3. 实施顺序

按风险从低到高，每步独立验证。**asmdef 合并必须最后做**，因为 2.3 的目录归位 / base 删除在多 asmdef 状态下也能进行（asmdef 跟着脚本走 .meta 移动），但合并后回滚成本高。

| 顺序 | 项目 | 类别 | 风险 |
|---|---|---|---|
| 1 | 删 `app/probes.py` + `app/yoloe_mask_probe.py` | Python | 低（独立入口） |
| 2 | 删 `AnchorPolicyAction.Reset` 枚举 | Unity | 低（无消费方） |
| 3 | 删 `AnchorCommandClient` 6 个 lastXxx SerializeField | Unity | 低（仅 Inspector） |
| 4 | 内联 `transport/_lifecycle.py` | Python | 中（需测重连） |
| 5 | 合并 `pipeline_helpers.py` 回主 pipeline | Python | 中（需 smoke） |
| 6 | 合并 `runtime/command_*.py` 5 文件为 `command_pipeline.py` | Python | 中（外部仅 1 处引用） |
| 7 | 合并 `runtime/quest_stream_receiver` + `latest_quest_input_store` 为 `quest_input_pipeline.py` | Python | 低（必须在步骤 1 之后） |
| 8 | 合并 `PoseToAnchorRuntime` 4 partial 为 1 文件 | Unity | 中（编辑器引用） |
| 9 | 删 `AnchorPolicyHostBase`，把 `policyHost` 字段改为 `AnchorPolicyHost` | Unity | 低（仅类型替换 + 删 7 个 override） |
| 10 | `Reliability/` 6 文件移到 `Anchor/Policy/`，删空目录 | Unity | 中（GUID 不变，但 Editor 需 reimport） |
| 11 | `Util/LatestOnlyQueue.cs` 移到 `Transport/`（顺带评估剩余 Util/ 文件） | Unity | 低 |
| 12 | asmdef 反向合并为单一 `EgoAnchor.asmdef` | Unity | 高（必须最后做） |

**纪律**：每一步完成后跑下面"验证"小节里对应的命令；不允许把第 7 步和第 1~6 步混在同一次提交里。步骤 9~11 是"目录 / 抽象归位"，必须在步骤 12 之前做完，否则 asmdef 合并后再做目录移动，git 会把"目录归位"和"asmdef 删除"的 diff 揉成一团难以审查。

---

## 4. 验证

### 每步通用
```powershell
# Python 编译 + 单测
cd EgoAnchor_Python
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py"

# Unity 编译
cd ..
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

### 步骤 1（删 probes）
- grep 整工程确认无残留 import：`Grep "from egoanchor.app.probes\|yoloe_mask_probe"`
- 跑 `pixi run python .\src\tracking_server.py`，确认主线不依赖被删模块。

### 步骤 4（内联 _lifecycle）
- 跑 `pixi run python .\src\tracking_server.py`，断开 NATS server 30s 再恢复，观察日志重连提示与原版一致；
- 跑现有 `test_transport_lifecycle.py`（Phase 3 已加入）。

### 步骤 5（合并 pipeline_helpers）
- 真机 / replay：HUD 的 `mask_src / pose_source / seg_async done/submitted/drop` 计数与改动前一致；
- 跑 `pixi run python -m unittest discover -s src -p "test_pipeline_state.py"`。

### 步骤 6（合并 partial）
- Unity Editor 打开场景，确认 `PoseToAnchorRuntime` Inspector 上 `framePoseHistory` / `policyHost` / `processors` 等所有 SerializeField 引用未丢失；
- 真机 / replay：raw + smoothed 两条 `DynamicObjectAnchor` 在 policy 启用 / 关闭各 1 次。

### 步骤 9（删 AnchorPolicyHostBase）
- grep 确认无残留引用：`Grep "AnchorPolicyHostBase"` 应只剩 0 命中；
- Unity Editor 重启后打开 `PoseToAnchorRuntime` Inspector，确认 `policyHost` 字段仍正确指向 `AnchorPolicyHost` 组件（GUID 不变）；
- 编译无 missing reference。

### 步骤 10（Reliability/ → Anchor/Policy/ 目录归位）
- **必须连同 .meta 一起 git mv**，保留 GUID；
- Unity Editor reimport，Console 检查无 "missing script" 警告；
- Inspector 全检：所有 prefab / 场景里挂 `AnchorPolicyHost` 的 GameObject 仍正确显示组件。

### 步骤 11（Util/LatestOnlyQueue → Transport/）
- 同样 `git mv` + .meta；
- 调整 `NatsControlClient.cs` 的 `using` 语句；
- 编译通过即可。

### 步骤 12（asmdef 合并，最关键）
- **删除前**：先 `git status` 确认无未提交改动；
- 删除 8 个 asmdef + 对应 `.meta`，新建顶层 `EgoAnchor.asmdef` + `.meta`；
- 关闭 Unity Editor → 删除 `Library/ScriptAssemblies/` → 重新打开 Editor；
- 检查 Console 是否有 `Assembly with name 'EgoAnchor.X' not found` 或 `The type or namespace name 'NatsClient' could not be found` 类报错；
- 如缺第三方 DLL 引用，按 Console 提示补 `precompiledReferences`；
- 编辑器场景 Inspector 全检：所有 MonoBehaviour 引用未丢失，编译无 missing reference；
- 跑一次 raw + smoothed 双路 anchor smoke。

---

## 5. 不动清单（再次重申）

阶段 5 同样不允许：
- 改 `subjects.v1.json` channel 列表 / proto 字段号；
- 把 SAM3 设默认；
- 把 FoundationPose / Cutie 状态搬出 `TrackingRuntime` owner 线程；
- 删 `LatestOnlyQueue<T>` / `EventQueue<T>` 类型本身（Phase 1 的 latest-only 语义工具，仅做目录归位）；
- 改 `CameraReference` / `PolicyController` / `InnovationGate` 命名（仅做目录归位 / namespace 调整，类名不动）；
- 把 4 个 override TOML 的合并版 `objects.toml` 拆回去。

**Phase 4 决策翻转（本轮显式做掉）**：删除 `AnchorPolicyHostBase`。Phase 4 13.2 把它列为"asmdef 时代的承重墙"故保留，Phase 5 单 asmdef 后该约束消失，论证失效，且无任何其它实现 / 测试需求，故本轮删除。

---

## 6. 预期收益

| 维度 | Phase 4 后 | Phase 5 后预期 |
|---|---|---|
| Python 总行数（不含 Generated） | 7484 | ~6900（删 2 demo + 内联 lifecycle + 合并 helpers + runtime 7→2 文件） |
| `runtime/` 文件数 | 16 | **11**（命令流水线 5→1，Quest 输入 2→1） |
| Unity asmdef 数量 | 8 | **1**（顶层 `EgoAnchor.asmdef`） |
| Unity 顶层目录数 | 8（含 `Reliability/` `Util/`） | **6**（`Reliability/` 并入 `Anchor/Policy/`，`Util/LatestOnlyQueue.cs` 并入 `Transport/`） |
| Unity 编辑器单脚本改动重编范围 | 单层 dll | 单一 EgoAnchor.dll（Phase 3 颗粒度收益作废） |
| `PoseToAnchorRuntime` 文件数 | 4 partial | 1 文件 + region 分章 |
| `AnchorCommandClient` Inspector 字段 | 12 | 6（删 6 个纯诊断） |
| 死枚举值 | 1（`AnchorPolicyAction.Reset`） | 0 |
| 仪式型抽象 | 1（`AnchorPolicyHostBase`，单一派生） | 0（直接持有 sealed concrete） |

主要心智收益：
- **没有"为了拆而拆"的 mixin / partial**：mixin 全部被消化；partial 仅在确实有 Unity 限制时使用；
- **Unity 编译模型回到"一个工程一个 dll"**：用户主观觉得 8 个 asmdef 颗粒度过细，本轮回到单一 dll；副作用是单脚本改动不再缩小重编范围，但用户认可；
- **诊断字段 vs 业务字段边界更清**：删 6 个 lastXxx 后，AnchorCommandClient Inspector 只剩配置项 + 计数器，与 NatsControlClient 的 Inspector 风格统一；
- **目录即语义**：`Reliability/` 这个误命名目录消失，所有 anchor policy 决策机器统一在 `Anchor/Policy/` 下；`Util/` 内部不再放只服务于 Transport 的 latest-only 容器；
- **删除 asmdef 时代的仪式抽象**：`AnchorPolicyHostBase` 这种"为绕反向依赖而存在的 abstract MonoBehaviour"在单 asmdef 后没有任何价值，直接删除让 `PoseToAnchorRuntime` 持有 sealed concrete，少 7 个 override 关键字 + 53 行 base。
