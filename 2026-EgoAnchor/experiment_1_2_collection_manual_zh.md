# EgoAnchor 实验一/二采集手册

正式采集使用 `EgoAnchor_Unity/Assets/Scene/EgoAnchor-Experiment12.unity`。场景已经设为
Formal，不需要填写操作员、运行模式、参数集、模型版本、Git commit 或协议版本。

9 项任务可以拆到多个 session 中采集。每个 session 可完成 1--9 中任意数量的任务，也不要求按顺序。
例如，第一次只采任务 1 和 3，第二次再采 2、4、5、6、7、8、9。分析时把这些目录一起传入，批次合计
覆盖 9 项即可。头显面板会显示本次 session 已完成的任务编号。

每项任务持续 90--120 秒。一次只采一项时，完成后可以立即结束 Unity 和 Python；采多项时，任务之间可
停下来准备，但不要退出 Play Mode。9 项纯采集时间合计约为 13.5--18 分钟。

平台 reference 来自 Quest 追踪系统，不是外部光学真值。`capture_mono_ms` 是 image-time proxy，
也不是曝光真值。

## 1. 默认输入

### 右手控制器

| 操作 | 默认输入 | 作用 |
|---|---|---|
| 选择任务 | 右摇杆上下左右 | 在 3×3 九宫格中移动选中项 |
| 开始 | A | 开始当前选中的任务 |
| 事件标记 | 右扳机 | 标记动作开始、遮挡开始或目标重新可见 |
| 结束 | B | 结束当前任务；空闲且至少完成一项时，再按一次结束本次 session |
| 作废 | 按下右摇杆 | 作废当前 trial，或作废选中任务最后一次完成 trial |

任务运行时摇杆选场会被锁定，避免误切到其他任务。按键会轻微扰动控制器，所以应先按下事件键，再开始
移动目标。作废键只用于操作错误，不要把它当暂停键。

### 键盘

键盘采用“一项任务一个键”的方式：

| 按键 | 作用 |
|---|---|
| `1`--`9` | 第一次按下会选择并开始对应任务；任务运行中再次按同一个数字键会写事件标记 |
| `Enter` | 结束当前任务；空闲且至少完成一项时，再按一次结束本次 session |
| `Backspace` | 作废当前 trial，或作废当前选中的已完成 trial |

遮挡任务需要交替记录“遮挡开始”和“目标重新可见”，所以同一个数字键会按多次。UI 的 `NEXT` 和
`Phase` 会说明下一次按键的含义。

## 2. 在 Inspector 中改绑

本项目不使用 InputActionAsset。所有动作都直接序列化在正式场景的 `ExperimentInputHandler` 组件中：

1. 在 Hierarchy 选择 `EvalRecorder`。
2. 找到 `Experiment Input Handler`。
3. 展开 `Navigate Action`、`Start Action`、`Mark Action`、`Stop Action` 和 `Reject Action`。
4. `Task Actions` 固定有 9 项，对应键盘任务 1--9。
5. 在每个 Action 的 Bindings 中直接修改设备和按键。

这些字段是真正的 `InputAction`，不是 binding path 字符串，也不引用外部 InputActionAsset。修改绑定后先跑
smoke，逐个确认 Inspector 中的 Action 与实际操作一致。Formal 开始后不要再改绑定或场景。

## 3. 状态面板

Canvas 固定在场景世界坐标中，不跟随 `CenterEyeAnchor`。面板中的九宫格编号与键盘数字键一致：

```text
1 HEAD    2 6DOF    3 MOVE
4 ROT     5 OCC     6 ALIGN
7 VCD     8 TEMP    9 LOCK
```

状态符号：

- `[ ]`：未完成；
- `[RUN]`：正在采集；
- `[OK]`：已有一个有效完成 trial；
- `>`：摇杆当前选中的任务。

面板还会显示：

- `Completed`：已完成任务数量；
- `This session`：本次日志最终会包含的任务编号；
- `Trial`：当前 trial ID；
- `Phase`：当前处于基线、动作、遮挡或恢复阶段；
- `Trial ... s`：当前任务已录制秒数；
- `Recommended: 90-120 s`：正式时长范围；
- `NEXT`：下一项合法操作。

## 4. 启动

先启动 NATS：

```powershell
nats-server
```

再启动 Python：

```powershell
cd EgoAnchor_Python
pixi run python .\src\run_server.py --object controller_right
```

`--object` 必须与正式场景中的 `EvalSession.objectId` 一致。默认值都是 `controller_right`。

Python 就绪后：

1. 打开 `Assets/Scene/EgoAnchor-Experiment12.unity`。
2. 检查 `ServerEndpointConfig` 的服务器 IP。
3. 进入 Play Mode。
4. 等待 Python 显示 NATS 已连接和 ZMQ 正在监听 `15557`。
5. 等 Unity 显示复用了 Python 的 `session_id`。
6. 确认面板出现 `Recording`，任务 1 被选中，但还没有 `[RUN]`。

收到第一个带 Python `session_id` 的 PoseResult 后，Unity 自动开始 session。不要手工创建日志目录，也不要
在同一个 Python session 中重新启动 Unity 录制。每次开始新的模块化 session，都要重新启动 Python，取得
新的 `session_id`。

## 5. 通用采集方法

每项任务都按下面的节奏执行：

1. 用摇杆选任务，或按该任务的数字键。
2. 手柄按 A 开始；键盘首次按数字键时已经自动开始。
3. 保持 10--15 秒基线。此时目标和头部按任务要求保持静止。
4. 在动作真正开始前按右扳机；键盘再次按同一个数字键。
5. 按任务说明执行动作。需要多轮事件时，每轮开始前都重新标记。
6. 总时长达到 90 秒后，留出最后 10--15 秒恢复或静止段。
7. 在 120 秒前按 B 或 `Enter` 结束任务，确认状态变为 `[OK]`。

不要在按下 marker 前就开始动作。转换指标需要 marker 后、平台 reference 开始运动前的短基线；遮挡恢复
指标还要求遮挡开始和目标重新可见两个 marker 严格配对。

## 6. 九项任务怎么做

### 任务 1：HEAD，静止目标与主动头动

目标控制器固定在桌面，全程不移动。

1. 开始任务后静止观察 10--15 秒。
2. 标记一次主事件。
3. 依次做左右偏航、上下俯仰、左右侧移、靠近、远离和组合头动。
4. 每种头动持续约 8--12 秒，相邻动作之间静止 3--5 秒。
5. 最后保持头部和目标静止 10--15 秒，再结束任务。

### 任务 2：6DOF，起停六自由度

1. 先记录 10--15 秒静止基线。
2. 每轮拿起前标记一次 `transition_started`。
3. 平移并旋转控制器 6--8 秒，随后放下并保持静止 8--10 秒。
4. 重复 5--6 轮。平移和旋转方向要有变化，但不要快速甩动。
5. 最后一轮放下后至少静止 10 秒，再结束任务。

### 任务 3：MOVE，持续平移

1. 先记录 10--15 秒静止基线，然后标记主事件。
2. 在桌面上方或预定轨迹内做中低速往复平移，尽量保持控制器朝向不变。
3. 前后、左右和斜向轨迹都要覆盖，每次换向不要突然加速。
4. 连续运动约 65--85 秒，最后静止 10--15 秒后结束。

### 任务 4：ROT，持续旋转

1. 先记录 10--15 秒静止基线，然后标记主事件。
2. 尽量保持控制器中心位置不变，依次绕 yaw、pitch 和 roll 轴旋转。
3. 每个轴正反方向各做若干次，采用连续中低速旋转。
4. 连续运动约 65--85 秒，最后静止 10--15 秒后结束。

### 任务 5：OCC，遮挡与恢复

1. 可见且静止 10--15 秒。
2. 遮挡开始的同一时刻按 marker，UI 进入 `OCCLUDED`。
3. 部分或完全遮挡 8--12 秒。
4. 移开遮挡物。当目标刚重新可见时再次按 marker，UI 进入 `VISIBLE / RECOVERY`。
5. 保持目标静止并等待恢复 8--12 秒。
6. 重复 4--5 轮，覆盖部分遮挡和完全遮挡。
7. 最后一轮必须以 `target_visible` 闭合。总时长达到 90 秒后再结束。

遮挡未闭合时 B 和 `Enter` 不会结束任务，这是为了防止缺失 `target_visible`。

### 任务 6：ALIGN，关闭采集时刻对齐的归因场景

动作与任务 1 相同：目标固定，记录主动头动。重点增加较明显的头部侧移、靠近和远离。目标本身不能动。

### 任务 7：VCD，关闭 VCD 接纳的归因场景

动作与任务 5 相同：执行 4--5 轮遮挡与恢复，每轮都要成对标记 `occlusion_started` 和
`target_visible`。

### 任务 8：TEMP，关闭时序合成的归因场景

动作与任务 2 相同：重复 5--6 轮“静止、标记、起动、六自由度运动、放下、重新静止”。每轮动作前都要
标记 `transition_started`。

### 任务 9：LOCK，关闭 StaticLock 的归因场景

1. 开始后先静止 15 秒，让完整 EgoAnchor 有充分时间进入静止锚定。
2. 每轮动作前标记 `transition_started`。
3. 移动并旋转 6--8 秒，随后放下并静止 10--12 秒。
4. 重复 4--5 轮。
5. 最后一轮结束后静止 15 秒，再结束任务。

## 7. 做错后怎么重做

### 任务还在 `[RUN]`

按下右摇杆，或按 `Backspace`。当前 trial 会写入 `trial_rejected`，任务回到 `[ ]`。修正准备后重新开始
这一项即可。

### 已经按了结束，任务显示 `[OK]`

1. 用摇杆选中该任务；键盘也可以按对应数字键，此时只会选中，不会直接覆盖旧 trial。
2. 按下右摇杆或 `Backspace`，状态回到 `[ ]`。
3. 重新采集这一项。

被作废的原始行会保留在日志中，便于审计。正式 QC、指标和 VCD risk-coverage 只读取正常 `trial_ended`
且没有后续 `trial_rejected` 的 trial，不会把错误尝试混入论文结果。

以下问题需要放弃当前 session，但不会影响其他已经通过 QC 的模块化 session：

- Unity 与 Python 的 session ID 不一致；
- NATS/ZMQ 中断或 pose 流长时间停止；
- writer 丢行或写入失败；
- Formal 过程中改了代码、模型、参数或场景配置；
- 平台 reference 长时间无效，导致多项任务不可用。

## 8. 完成一个模块化 session

本次需要的任务显示 `[OK]` 后，先检查 `This session`。确认没有需要重做的任务，再在空闲状态按一次 B 或
`Enter`。不需要等 9 项全部完成。Unity 会写入 `manifest.json`，其中 `completed_tasks` 按编号记录本次最终
保留的任务和 trial。

随后：

1. 等 Unity 控制台显示 manifest 已写入和 session 已结束。
2. 立即退出 Unity Play Mode，停止继续发送图像帧。
3. 在 Python OpenCV 窗口按 `q` 或 `Esc`。
4. 等 `python_session.json` 的 `state` 变为 `python_stopped`。
5. 远端采集时，等日志同步完成后再运行 QC。

同名 session 目录应包含：

```text
manifest.json
python_session.json
python_candidates.jsonl
unity_reference.jsonl
unity_admission.jsonl
unity_render.jsonl
events.jsonl
audit_samples/
```

五个 JSONL 文件都不能是空文件。所有 writer 的 `dropped_rows` 和 `log_write_failures` 必须为 0。

Unity 和 Python 都正常停止后，可以给最外层目录增加任务前缀，例如：

```text
tasks-01-03__20260716_153000_controller_right/
```

不要修改目录内的固定文件名，也不要修改 `manifest.json` 中的 `session_id`。目录名前缀只用于人工整理；
reader 仍以 manifest 内的稳定 ID 配对数据。重采任务 3 后，保留新旧目录作审计，正式分析时只传入要采用的
新目录即可。

运行 QC：

```powershell
cd EgoAnchor_Python
pixi run python -m egoanchor.eval.cli qc .\data\eval\<session_id>
```

返回码为 `0` 且 JSON 中 `"passed": true` 才算通过。

每个 session 都通过基础 QC 后，将同一冻结配置下的目录一起交给分析。可以把全部模块化目录同时传给两个
命令；没有对应实验任务的 session 会被忽略：

```powershell
pixi run python -m egoanchor.eval.cli analyze-exp1 `
  .\data\eval\tasks-01-03__<session_a> `
  .\data\eval\tasks-02-04-05__<session_b> `
  .\data\eval\tasks-06-07-08-09__<session_c> `
  --out .\data\analysis\exp1

pixi run python -m egoanchor.eval.cli analyze-exp2 `
  .\data\eval\tasks-01-03__<session_a> `
  .\data\eval\tasks-02-04-05__<session_b> `
  .\data\eval\tasks-06-07-08-09__<session_c> `
  --out .\data\analysis\exp2
```

实验一要求批次覆盖任务 1--5，实验二要求覆盖任务 6--9。批次会拒绝重复 `session_id`，也会检查对象、
协议、`config_hash`、`frozen_parameter_set_id` 和八个 runtime 定义是否一致。不能把 calibration、不同参数
或不同对象的目录拼进 Formal 批次。

## 9. Smoke 与 calibration

第一次正式采集前，在 `EgoAnchor-Develop.unity` 跑 smoke 和 calibration。它们不进入论文结果。

Smoke 至少检查：

- 手柄五个动作和键盘 `1`--`9`、`Enter`、`Backspace` 都能被识别；
- 摇杆四方向按九宫格移动，运行中不能误切任务；
- 普通任务、转换任务和遮挡任务产生正确事件角色；
- 作废后只影响当前任务，其他 `[OK]` 状态不变；
- 只完成一项后可以用第二次 B/`Enter` 结束 session，manifest 的 `completed_tasks` 只列这一项；
- Canvas 保持静止，不跟随头部；
- NATS/ZMQ 计数持续增加，日志没有 dropped row 或 write failure。

Calibration 用于冻结 One Euro、VCD、Kalman--Hermite、StaticLock、动作速度和事件判定规则。Formal 每项
仍按 90--120 秒执行，不得用正式数据继续调参。
