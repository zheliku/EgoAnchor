# EgoAnchor 实验一/二采集手册

正式采集场景：`EgoAnchor_Unity/Assets/Scene/EgoAnchor-Experiment12.unity`。

你不需要填写操作员、运行模式、参数集、模型版本、Git commit 或协议版本。每次 session 可以只采任务 1--9 中的任意几项，不必一次做完，也不必按顺序。最后只要同一冻结配置下的所有 session 合起来覆盖任务 1--9 即可。

每项正式任务必须持续 **90--120 秒**。默认开启最短时长门禁：不足 90 秒时，B 或 `Enter` 不会结束当前任务。超过 120 秒时 UI 计时会变红，请尽快结束。

## 一、先弄清四个动作

采集时只有四类操作，含义不要混用。

| 操作 | 右手手柄 | 键盘 | 实际含义 |
|---|---|---|---|
| 开始任务 | A | 第一次按任务数字 `1`--`9` | 开始当前任务的 trial。从这一刻起，该任务的数据才会进入正式分析范围 |
| 写 marker | 右扳机 | 任务运行中再次按同一个数字 | 只在当前 trial 中记一个时间点，告诉分析程序“动作或遮挡在这里发生” |
| 结束任务 | B | `Enter` | 结束当前任务。满足事件和时长要求后，任务变成 `[OK]` |
| 作废 | 按下右摇杆 | `Backspace` | 当前操作做错时作废该 trial；原始日志保留，但正式分析会排除 |

最容易混淆的是 marker：

- marker **不会开始录制**，A 或第一次按任务数字才会开始任务；
- marker **不会结束录制**，B 或 `Enter` 才会结束任务；
- marker 只是给日志插入一个准确时间点；
- 普通运动任务在动作开始前按 marker；
- 遮挡任务需要在“遮挡开始”和“重新可见”两个时刻各按一次 marker。

## 二、右手手柄和键盘怎么用

### 右手手柄

1. 用右摇杆上下左右，在 3×3 九宫格中选择任务。
2. 按 A 开始选中的任务。
3. 需要标记事件时按右扳机。
4. 采满 90--120 秒后按 B 结束任务。
5. 做错时按下右摇杆作废。

任务正在运行时不能切换任务，防止误操作。

### 键盘

- `1`--`9` 分别对应任务 1--9。
- 任务空闲时按数字：选择并立即开始该任务。
- 任务运行时再按同一个数字：写 marker。
- `Enter`：结束当前任务。
- `Backspace`：作废当前任务或选中的已完成任务。

键盘和手柄完全通用。可以用手柄开始、键盘写 marker、再用手柄结束，日志语义相同。

## 三、UI 怎么看

Canvas 固定在场景世界坐标中，不跟随 `CenterEyeAnchor`。

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
- 黄色 `NEXT`：下一步该做什么；
- 青色 `Phase`：当前采集阶段；
- 橙色 `Marker`：下一次 marker 的作用；
- 黄色计时：尚未达到 90 秒；
- 绿色计时：已经进入 90--120 秒结束窗口；
- 红色计时：已经超过 120 秒；
- 红色 session 提示：Python 未配对、目录已被使用或 session 启动失败。

重要字段：`This session` 是本次最终保留的任务编号；`Trial` 是当前 trial ID；`Trial ... s` 是当前任务总时长；`Phase ... s` 是当前阶段持续时间；`Role` 是最近一个 marker 角色；`NEXT` 是当前最应该执行的操作。

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

如果 UI 显示“当前 Python session 已有 Unity 日志”，这个 `session_id` 已经用过。停止并重新启动 Python，取得新的 `session_id`，不要覆盖旧目录。

## 五、每个任务都按这个节奏

1. 选择任务。
2. 按 A，或按对应数字键，确认任务变成绿色 `[RUN]`。
3. 按任务说明记录 10--15 秒初始基线。
4. 在动作真正开始前按 marker。
5. 执行动作。需要多轮动作时，每轮开始前再次按 marker。
6. 最后留 10--15 秒静止或恢复段。
7. 等计时进入绿色的 90--120 秒窗口。
8. 按 B 或 `Enter`，确认任务变成蓝色 `[OK]`。

按 marker 时应先按键，再开始动作。不要已经移动几秒后才补按。

## 六、任务 1--9 逐项操作

### 任务 1：HEAD，静止目标与主动头动

1. 把右手控制器稳定放在桌面或固定支架上，全程不要移动。
2. 选择任务 1，按 A；键盘直接按 `1`。
3. 正视目标并保持头部静止 10--15 秒。
4. 按一次 marker，然后依次做左右转头、上下点头、左右侧移、靠近和远离。
5. 每种头动做 8--12 秒，中间静止 3--5 秒；切换动作前可以再按 marker。
6. 最后保持目标和头部静止 10--15 秒，90--120 秒内结束。

### 任务 2：6DOF，起停六自由度

1. 控制器放在桌面，开始任务 2：A 或数字 `2`。
2. 静止 10--15 秒。
3. 准备拿起时先按 marker，然后立即拿起控制器。
4. 同时做平移和旋转 6--8 秒，再放回桌面静止 8--10 秒。
5. 重复 5--6 轮，每轮拿起前都按 marker；最后静止 10--15 秒后结束。

### 任务 3：MOVE，持续平移

1. 开始任务 3：A 或数字 `3`，静止 10--15 秒。
2. 按 marker，开始中低速连续平移。
3. 覆盖前后、左右和斜向轨迹，换向不要突然加速；换主要方向前可以再按 marker。
4. 连续运动约 65--85 秒，最后静止 10--15 秒，90--120 秒内结束。

### 任务 4：ROT，持续旋转

1. 开始任务 4：A 或数字 `4`，保持控制器中心位置稳定 10--15 秒。
2. 按 marker，依次绕 yaw、pitch、roll 轴做正反方向的中低速旋转。
3. 切换旋转轴前可以再按 marker；连续旋转约 65--85 秒，最后静止 10--15 秒后结束。

### 任务 5：OCC，遮挡与恢复

1. 开始任务 5：A 或数字 `5`，保持目标完整可见且静止 10--15 秒。
2. 即将遮挡时按第一次 marker，马上遮挡目标；UI 进入 `OCCLUDED`。
3. 遮挡 8--12 秒，移开遮挡物；目标刚重新可见时按第二次 marker。
4. 可见且静止 8--12 秒，等待恢复；重复 4--5 轮，部分遮挡和完全遮挡都要有。
5. 最后一轮必须以“目标重新可见”marker 闭合，90--120 秒内结束。

如果 UI 仍显示 `OCCLUDED`，B 或 `Enter` 不会结束任务。先让目标重新可见并补按 marker。

### 任务 6：ALIGN，关闭采集时刻对齐

动作与任务 1 相同：目标固定，静止 10--15 秒后按 marker，做左右转头、上下点头、明显侧移、靠近和远离，最后静止 10--15 秒，90--120 秒内结束。

### 任务 7：VCD，关闭 VCD 接纳

动作与任务 5 相同：遮挡开始和重新可见各按一次 marker，重复 4--5 轮，最后一轮必须闭合，90--120 秒内结束。

### 任务 8：TEMP，关闭时序合成

动作与任务 2 相同：静止 10--15 秒，每轮拿起前按 marker，平移加旋转 6--8 秒，放下后静止 8--10 秒，重复 5--6 轮，最后静止 10--15 秒。

### 任务 9：LOCK，关闭 StaticLock

1. 开始任务 9：A 或数字 `9`，控制器放在桌面并静止 15 秒。
2. 每轮拿起前按 marker，平移加旋转 6--8 秒，放下后静止 10--12 秒。
3. 重复 4--5 轮，最后静止 15 秒；90--120 秒内结束。

## 七、做错了怎么处理

当前任务是 `[RUN]` 时，按右摇杆或 `Backspace` 作废，任务回到 `[ ]`，其他 `[OK]` 不受影响。

任务已经是 `[OK]` 时可以直接重采，不需要先删除：手柄选中后按 A，或键盘直接按对应数字。代码会先把旧 trial 写成 `trial_rejected`，再立即开始新 trial。旧日志保留用于审计，正式分析只使用新的未作废完成 trial。

如果只想删除完成状态而暂时不重采，选中任务后按右摇杆或 `Backspace`，任务回到 `[ ]`，不会自动开始。

## 八、结束一个模块化 session

为了避免 Python 停止后的尾帧没有 Unity admission，最后一项任务完成后严格按以下顺序：

1. 确认没有 `[RUN]`，查看 `This session` 核对任务编号。
2. **先停止 5090 上的 Python**，按 `q`、`Esc` 或正常终止服务。
3. 等 `python_session.json` 的 `state` 变为 `python_stopped`，并等待 Mutagen 回传完成。
4. Unity 保持 Play Mode 和空闲状态，此时按 B 或 `Enter` 结束 session。
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

## 十、Inspector 改绑与 smoke

本项目不使用 InputActionAsset。正式场景的 `ExperimentInputHandler` 直接在 Inspector 序列化 `Navigate Action`、`Start Action`、`Mark Action`、`Stop Action`、`Reject Action` 和 9 项 `Task Actions`。需要改绑时展开对应 Action 的 Bindings 直接修改。`ExperimentStatusUI` 的所有颜色也暴露在 Inspector 中。

正式采集前先跑 smoke，确认右手摇杆、A、右扳机、B、摇杆按下、键盘 `1`--`9`、`Enter`、`Backspace` 都有效；运行中不能切换；完成任务选中后仍为蓝色并能直接重采；遮挡 marker 交替；Canvas 不跟随头部；日志无 dropped row 和 write failure。

Smoke 如需快速测试，可以临时关闭 `ExperimentTrialSelector.enforceMinimumDuration`。正式场景开始采集前必须重新开启，Formal 期间不得修改代码、模型、参数、输入绑定或场景配置。
