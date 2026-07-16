# EgoAnchor 实验一/二采集手册

正式采集场景：`EgoAnchor_Unity/Assets/Scene/EgoAnchor-Experiment12.unity`。

你不需要填写操作员、运行模式、参数集、模型版本、Git commit 或协议版本。所有记录下来的 session 都是正式采集。每次 session 可以只采任务 1--9 中的任意几项，不必一次做完，也不必按顺序。最后只要同一冻结配置下的所有 session 合起来覆盖任务 1--9 即可。

任务和 session 都没有持续时间上下限。UI 的 `TIME` 只告诉你已经录了多久，不会阻止结束，也不会因为过短或过长判定失败。完成当前任务要求的动作和 marker 后即可结束；需要中止时也可以直接停止整个 session。

## 一、先弄清五个动作

手柄和键盘走同一套状态机，区别只在物理按键。

| 操作 | 右手手柄 | 键盘 | 实际含义 |
|---|---|---|---|
| 选择任务 | 右摇杆上下左右 | 方向键，或数字行/小键盘 `1`--`9` | 只改变黄色选中项，不开始采集 |
| 开始任务 | A | 主键盘 `Enter` 或小键盘 `Enter` | 开始当前选中任务的 trial |
| 写 marker | 右扳机 | 小键盘 `+` 或 `M` | 在当前 trial 中记录动作、遮挡或重新可见的准确时刻 |
| 结束任务 | 快速短按 B | 小键盘 `0` 或 `E` | 结束当前任务；必需 marker 完整后变成 `[OK]` |
| 作废选中任务 | 按下右摇杆 | `Space` | 只作废当前或选中任务，其他 `[OK]` 任务不变 |
| 停止 session | 长按 B 1.5 秒 | `F` | 随时停止整个 session；活动 trial 会先记为 `trial_rejected` |

最容易混淆的是 marker：

- marker **不会开始录制**，A 或 `Enter` 才会开始任务；
- marker **不会结束录制**，小键盘 `0`、B 或 `E` 才会结束任务；
- marker 只是给日志插入一个准确时间点；
- 普通运动任务在动作开始前按 marker；
- 遮挡任务需要在“遮挡开始”和“重新可见”两个时刻各按一次 marker。

marker 按下后，状态板会保留 2 秒确认信息。绿色 `MARKER SAVED #N` 表示已经写入，并附带 `MOTION START`、`OCCLUSION START` 或 `TARGET VISIBLE`。红色 `MARKER IGNORED` 表示当前没有活动任务，这次按键没有写入日志。看到绿色确认后再开始动作，不要连续快速重复按键。

## 二、右手手柄和键盘怎么用

### 右手手柄

1. 用右摇杆上下左右，在 3×3 九宫格中选择任务。
2. 按 A 开始选中的任务。
3. 需要标记事件时按右扳机。
4. 动作和 marker 完成后短按 B 结束任务。
5. 做错时按下右摇杆作废。
6. 需要停止整个 session 时长按 B 1.5 秒。

任务正在运行时不能切换任务，防止误操作。

### 键盘

- 方向键与右摇杆完全相同，按一次只在九宫格移动一格。
- 主键盘数字行和小键盘 `1`--`9` 可以直接选中对应任务，但不会自动开始。
- 主键盘 `Enter` 和小键盘 `Enter` 都会开始当前选中任务。
- 主流程可以全部在小键盘完成：`1`--`9` 选任务，`Enter` 开始，`+` 写 marker，`0` 结束任务。
- `M` 和 `E` 分别是 marker 与结束任务的兼容键；`Space` 只作废当前或选中任务，`F` 随时停止整个 session。
- 任务运行时会锁定选择；方向键和数字键都不会切换任务，也不会误写 marker。

键盘和手柄完全通用。可以用手柄开始、键盘写 marker、再用手柄结束，日志语义相同。

## 三、UI 怎么看

Canvas 固定在场景世界坐标中，不跟随 `CenterEyeAnchor`。

Canvas 上有两个并排面板。左侧是任务采集状态板，右侧是实时系统诊断板。两块面板都固定在场景根节点。

### 左侧任务采集状态板

```text
1 HEAD    2 6DOF    3 MOVE
4 ROT     5 OCC     6 ALIGN
7 VCD     8 TEMP    9 LOCK
```

任务状态：

- `[ ]`：未完成；
- `[RUN]`：正在采集；
- `[OK]`：已完成；
- `>`：当前选中；
- 选中一个已经完成的任务时，它仍保持蓝色，只增加箭头和粗体。

颜色：

- 黄色任务：当前选中的未完成任务；
- 绿色任务：正在录制；
- 蓝色任务：本 session 已完成；
- 灰色任务：尚未完成；
- 黄色 `NEXT`：下一步该做什么以及对应按键；
- 青色 `STATE`：当前可确认的操作状态，例如正在记录基线、目标被遮挡或目标已重新可见；
- 橙色 `MARKER`：下一次 marker 应在哪个时刻按；
- 绿色计时：当前任务已经录制的实际时长；空闲时显示灰色 `--:--`；
- 红色 session 提示：Python 未配对、目录已被使用或 session 启动失败。

面板不再显示分析内部的 `Phase`、`Role` 或双计时。`TASKS` 和九宫格用于核对完成范围，`CURRENT` 是当前选中任务，`TIME` 是该任务的总时长，`NEXT` 是当前最应该执行的操作。底部固定列出手柄和键盘按键。

### 右侧实时系统诊断板

右侧面板在 Play Mode 中持续采样，每秒刷新 10 次。它在任务开始前、任务运行中和任务结束后都会更新。

| 面板字段 | 含义 |
|---|---|
| `XR DEVICE / WORN` | 是否检测到头显，以及 Meta runtime 是否判断头显正在佩戴 |
| `XR FOCUS / INPUT` | Unity 是否持有 VR 画面和输入 focus；`LOST` 会显示红色 |
| `OUTPUT / DISPLAY / REF` | 主 runtime 是否有输出、锚点是否实际可见、平台参考 Transform 是否可用；`ACTIVE` 表示正在更新，`HELD` 表示手柄失活后继续使用最后一次激活位姿 |
| `POSITION DELTA` | 显示锚点相对 Quest 平台控制器参考的位置差异，单位 mm |
| `ROTATION DELTA` | 显示锚点相对 Quest 平台控制器参考的旋转差异，单位 deg |
| `OBS AGE` | 当前显示使用的图像观测距现在有多久；它包含等待和运行时保持，不是纯网络时延 |
| `E2E ARRIVAL` | 同一 Unity 单调时钟下，从图像时间代理到 Unity 处理该 PoseResult 的时间 |
| `SERVER` | Python 同一单调时钟下的服务端处理时间，不与 Unity 时钟相减 |
| `SMOOTH` | 时序合成当前引入的实际输出延迟 |
| `POSE RATE` | 新 PoseResult 对应 frame_id 的实时更新率 |
| `VCD LATEST / ACCEPTED` | 最新候选评分，以及最近一次被 policy 接受的评分 |
| `RESIDUAL` | policy 输出阶段的平移和旋转残差 |
| `FRAME STEP` | 相邻 Unity 帧实际显示锚点的位姿变化，包含真实物体运动，不能直接当作抖动指标 |
| `ANCHOR / MOTION / STATIC LOCK` | 锚点生命周期、运动状态和静止锁定状态 |

开始任务前，先确认 `WORN YES`、`VR ACTIVE`、`INPUT ACTIVE`，并且 `OUTPUT`、`DISPLAY`、`REF` 都不是红色。再观察几秒，确认 `POSE RATE` 持续更新，`OBS AGE` 和 `E2E ARRIVAL` 没有不断上升，然后按 A 或 `Enter`。

不要为了得到更好看的结果，等 `POSITION DELTA`、`ROTATION DELTA` 或 VCD 分数特别低时才开始。右侧面板是连接和运行状态诊断，不是正式数据筛选器。控制器 pose 也不是外部光学真值；正式指标以日志完成后的 schema-v2 配对分析为准。

手柄静止后可能被平台隐藏。此时 `REF` 显示 `HELD`，位置和旋转差异仍按最后一次激活的 Transform 位姿计算；手柄重新激活后，参考位姿自动继续更新。`HELD` 不是错误，不需要为了让面板变回 `ACTIVE` 而移动手柄。

## 四、启动顺序

### 1. 启动 NATS

```powershell
nats-server
```

### 2. 在 5090 电脑启动 Python

```powershell
cd EgoAnchor_Python
pixi run python .\src\run_server.py --object controller_right
```

Python 服务端日志写到远端 `data/eval/<session_id>/`，再由 Mutagen 回传到本机 `EgoAnchor_Python/data/eval/`。Unity 不应直接覆盖 Python 的日志文件。

### 3. 启动 Unity

1. 打开 `Assets/Scene/EgoAnchor-Experiment12.unity`。
2. 检查 `ServerEndpointConfig` 的服务器 IP。
3. 进入 Play Mode。
4. 等待 Python 显示 NATS 已连接、ZMQ 正在监听 `15557`。
5. 等待 Unity UI 显示 `Recording` 和 Python 的 `session_id`。
6. 确认任务 1 已被选中，但仍是 `[ ]`，不是 `[RUN]`。
7. 查看右侧实时诊断板，确认 `WORN YES`、`VR ACTIVE`、`INPUT ACTIVE`，并等待输出信号和更新率稳定。

如果 UI 显示“当前 Python session 已有 Unity 日志”，这个 `session_id` 已经用过。停止并重新启动 Python，取得新的 `session_id`，不要覆盖旧目录。

## 五、每个任务都按这个节奏

1. 选择任务。
2. 按 A、主键盘 `Enter` 或小键盘 `Enter`，确认任务变成绿色 `[RUN]`。
3. 先保持目标和操作者稳定，记录一段初始基线。
4. 在动作真正开始前按 marker。
5. 执行动作。需要多轮动作时，每轮开始前再次按 marker。
6. 最后保持稳定，确认动作已经结束或目标已经重新可见。
7. 短按 B 或按 `E`，确认任务变成蓝色 `[OK]`。

按 marker 时应先按键，再开始动作。不要已经移动几秒后才补按。

每次按 marker 都要看到绿色 `MARKER SAVED #N`。没有看到确认时先停止动作，检查当前任务是否仍为 `[RUN]`，不要靠重复按键猜测是否写入。

## 六、任务 1--9 逐项操作

### 任务 1：HEAD，静止目标与主动头动

1. 把右手控制器稳定放在桌面或固定支架上，全程不要移动。
2. 选择任务 1，再按 A 或 `Enter` 开始。
3. 正视目标并保持头部静止，建立初始基线。
4. 按一次 marker，然后依次做左右转头、上下点头、左右侧移、靠近和远离。
5. 覆盖每种头动，中间回到稳定状态；切换动作前可以再按 marker。
6. 最后保持目标和头部静止，确认覆盖完整后结束。

### 任务 2：6DOF，起停六自由度

1. 控制器放在桌面，选中任务 2，再按 A 或 `Enter` 开始。
2. 先保持静止，建立初始基线。
3. 准备拿起时先按 marker，然后立即拿起控制器。
4. 同时做平移和旋转，再放回桌面并等待稳定。
5. 重复多轮，每轮拿起前都按 marker；覆盖起动、运动和停止后即可结束。

### 任务 3：MOVE，持续平移

1. 选中任务 3，按 A 或 `Enter` 开始，先保持静止。
2. 按 marker，开始中低速连续平移。
3. 覆盖前后、左右和斜向轨迹，换向不要突然加速；换主要方向前可以再按 marker。
4. 覆盖前后、左右和斜向的连续运动，最后回到静止后结束。

### 任务 4：ROT，持续旋转

1. 选中任务 4，按 A 或 `Enter` 开始，先保持控制器中心位置稳定。
2. 按 marker，依次绕 yaw、pitch、roll 轴做正反方向的中低速旋转。
3. 切换旋转轴前可以再按 marker；覆盖三个旋转轴的正反方向，最后静止后结束。

### 任务 5：OCC，遮挡与恢复

1. 选中任务 5，按 A 或 `Enter` 开始，保持目标完整可见且静止。
2. 即将遮挡时按第一次 marker，马上遮挡目标；UI 进入 `TARGET OCCLUDED`。
3. 保持遮挡后移开遮挡物；目标刚重新可见时按第二次 marker。
4. 等目标重新稳定；重复多轮，部分遮挡和完全遮挡都要有。
5. 最后一轮必须以“目标重新可见”marker 闭合，然后即可结束。

如果 UI 仍显示 `TARGET OCCLUDED`，小键盘 `0`、B 或 `E` 都不会结束任务。先让目标重新可见并补按 marker。

### 任务 6：ALIGN，关闭采集时刻对齐

动作与任务 1 相同：目标固定，稳定后按 marker，做左右转头、上下点头、明显侧移、靠近和远离，覆盖完整并回到稳定后结束。

### 任务 7：VCD，关闭 VCD 接纳

动作与任务 5 相同：遮挡开始和重新可见各按一次 marker，覆盖部分遮挡和完全遮挡，最后一轮必须闭合。

### 任务 8：TEMP，关闭时序合成

动作与任务 2 相同：先保持静止，每轮拿起前按 marker，完成平移加旋转后放下并等待稳定，重复多轮以覆盖起停变化。

### 任务 9：LOCK，关闭 StaticLock

1. 选中任务 9，按 A 或 `Enter` 开始，控制器放在桌面并保持静止。
2. 每轮拿起前按 marker，完成平移加旋转后放下并等待稳定。
3. 重复多轮，确认静止锚定和重新运动都已覆盖后结束。

## 七、做错了怎么处理

当前任务是 `[RUN]` 时，按下右摇杆或按 `Space` 作废。任务回到 `[ ]`，其他 `[OK]` 不受影响；选中项仍停留在该任务，可以直接重新开始。

任务已经是 `[OK]` 时可以直接重采，不需要先删除：先选中它，再按 A 或 `Enter`。代码会先把旧 trial 写成 `trial_rejected`，再开始新 trial。旧日志保留用于审计，正式分析只使用新的未作废完成 trial。

如果只想删除完成状态而暂时不重采，选中任务后按下右摇杆或按 `Space`。该任务回到 `[ ]`，不会自动开始，也不会影响其他任务。

## 八、结束一个模块化 session

为了避免 Python 停止后的尾帧没有 Unity admission，最后一项任务完成后严格按以下顺序：

1. 确认没有 `[RUN]`，用 `TASKS` 和蓝色 `[OK]` 核对本次完成的任务。
2. **先停止 5090 上的 Python**，按 `q`、`Esc` 或正常终止服务。
3. 等 `python_session.json` 的 `state` 变为 `python_stopped`，并等待 Mutagen 回传完成。
4. Unity 保持 Play Mode，按 `F` 或长按右手 B 1.5 秒停止 session。若有活动 trial，它会自动写入 `trial_rejected`，已经完成的 `[OK]` 任务不受影响。
5. 等 Unity 控制台显示 manifest 已写入，最后退出 Play Mode。

不要在 Python 仍持续发布 PoseResult 时先结束 Unity session。QC 会统计跨端未消费的 Python candidate；实际进入 Unity 的 candidate 仍必须完整覆盖 8 个 runtime。

目录应包含：

```text
manifest.json
python_session.json
python_candidates.jsonl
python_events.jsonl
unity_reference.jsonl
unity_admission.jsonl
unity_render.jsonl
unity_events.jsonl
events.jsonl
audit_samples/
```

`python_events.jsonl` 由 5090 Python 独占写入，`unity_events.jsonl` 由本机 Unity 独占写入。同步完成后，QC 会合并生成 `events.jsonl`。不要手工修改内部固定文件或 manifest 的 `session_id`。两端正常停止后，可以给最外层目录加任务前缀，例如 `tasks-01-03__20260716_153000_controller_right/`。

## 九、运行 QC 和分析

```powershell
cd EgoAnchor_Python
pixi run python -m egoanchor.eval.cli qc .\data\eval\<session_id>
```

返回码为 `0` 且 JSON 中 `"passed": true` 才算结构通过。还要确认 writer 的 `dropped_rows`、`log_write_failures` 都为 0，完成任务与 lifecycle 一致，遮挡没有悬空 marker，每个被 Unity 消费的 candidate 有 8 个 admission，每个 render tick 有 8 个 runtime。

实验一批次必须合计覆盖任务 1--5，实验二批次必须合计覆盖任务 6--9：

```powershell
pixi run python -m egoanchor.eval.cli analyze-exp1 `
  .\data\eval\tasks-01-03__<session_a> `
  .\data\eval\tasks-02-04-05__<session_b> `
  --out .\data\analysis\exp1

pixi run python -m egoanchor.eval.cli analyze-exp2 `
  .\data\eval\tasks-06-07__<session_c> `
  .\data\eval\tasks-08-09__<session_d> `
  --out .\data\analysis\exp2
```

## 十、Inspector 改绑与正式采集前自检

本项目不使用 InputActionAsset。正式场景的 `ExperimentInputHandler` 直接在 Inspector 序列化 `Navigate Action`、`Start Action`、`Mark Action`、`Stop Action`、`Finish Action`、`Reject Action` 和 9 项 `Task Actions`。需要改绑时展开对应 Action 的 Bindings 直接修改。`ExperimentStatusUI` 的所有颜色也暴露在 Inspector 中。

开始正式采集前做一次工程功能自检，确认右手摇杆、A、右扳机、B 短按/长按、摇杆按下，以及键盘方向键、数字行/小键盘 `1`--`9`、两个 `Enter`、小键盘 `+`、小键盘 `0`、`M`、`E`、`F`、`Space` 都有效。还要确认数字键只选择、不自动开始，运行中不能切换，`Space` 只作废选中任务，`F` 或长按 B 可以随时停止 session，完成任务选中后仍为蓝色并能直接重采，marker 成功和拒绝都有明显反馈，遮挡 marker 能正确配对，两块 Canvas 面板不跟随头部，实时指标持续更新，日志无 dropped row 和 write failure。工程功能自检不是另一类实验 session；真正写入评估目录的数据统一为 formal。

## 十一、Quest 串流黑屏怎么处理

如果头显突然黑屏，先看右侧面板最后显示的 XR 状态。`WORN NO`、`VR LOST` 或 `INPUT LOST` 说明 Meta runtime 已经撤回画面或输入 focus。代码会立即暂停双目 GPU 读回和 JPEG 编码；focus 恢复后自动继续，并把 `xr_focus_lost`、`xr_focus_acquired` 写入 `unity_events.jsonl`。

按以下顺序处理：

1. 确认头显仍然佩戴稳固，近距传感器没有被面罩、胶带或头发遮挡。
2. 唤醒头显并确认 Quest Link 仍连接；需要时回到 Link 界面后再进入 Unity。
3. 等面板恢复为 `WORN YES | VR ACTIVE | INPUT ACTIVE`，并确认 `POSE RATE` 重新更新。
4. 作废黑屏期间正在运行的 trial，再重新采该任务。已经完成的其他任务不用重做。

本次排查过的黑屏日志在故障点依次出现 `HMDUnmounted`、`VrFocusLost` 和 `InputFocusLost`。同一时段的 render、双目发送和日志队列仍正常，没有 OOM、显卡设备丢失、发送失败或 writer 丢行，因此不能把这次故障归因于录制代码卡死。双目同步 `ReadPixels` 和 JPEG 编码仍是长期性能风险；如果以后在 `WORN YES`、`VR ACTIVE` 时再次黑屏，再单独采集 Unity Profiler、Meta Link 日志和 GPU/GC 数据。

正式采集进入 Play Mode 后，不要修改脚本、保存场景、刷新 AssetDatabase，也不要让 Unity MCP 启动或停止 Play Mode。先结束 session 并退出 Play Mode，再进行代码改动。
