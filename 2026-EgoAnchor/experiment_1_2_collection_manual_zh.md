# EgoAnchor 实验一/二采集手册

正式采集场景：`EgoAnchor_Unity/Assets/Scene/EgoAnchor-Experiment12.unity`。

你不需要填写操作员、运行模式、参数集、模型版本、Git commit 或协议版本。所有记录下来的 session 都是正式采集。现在只保留任务 1--5；每个任务会同时记录四个实验一系统配置、四个实验二组件消融和一个 `EgoAnchor Hermite` 插值器对照。因此，同一批任务 1--5 日志会同时进入实验一和实验二，不再重复采集任务 6--9。

当前离线 CLI 不会拆分多任务 session，也不会自动合并多个 session。正式批次固定为任务 1--5 各录一个独立 session，共五个 session；每个 session 只完成一个任务。五次采集必须使用完全相同的冻结配置。完成当前任务后停止 session，重新启动 Python 取得新的 session_id，再采下一项任务。不要把同一个多任务 session 复制成五个 task 目录。

任务和 session 都没有持续时间上下限。UI 的 `TIME` 只告诉你已经录了多久，不会阻止结束，也不会因为过短或过长判定失败。完成当前任务要求的动作和 marker 后即可结束；需要中止时也可以直接停止整个 session。

## 一、先弄清五个动作

手柄和键盘走同一套状态机，区别只在物理按键。

| 操作         | 右手手柄       | 键盘                                | 实际含义                                                    |
| ------------ | -------------- | ----------------------------------- | ----------------------------------------------------------- |
| 选择任务     | 右摇杆上下左右 | 方向键，或数字行/小键盘`1`--`5` | 只改变黄色选中项，不开始采集                                |
| 开始任务     | A              | 主键盘`Enter` 或小键盘 `Enter`  | 开始当前选中任务的 trial                                    |
| 写 marker    | 右扳机         | 小键盘`+` 或 `M`                | 在当前 trial 中记录动作、遮挡或重新可见的准确时刻           |
| 结束任务     | 快速短按 B     | 小键盘`0` 或 `E`                | 结束当前任务；必需 marker 完整后变成`[OK]`                |
| 作废选中任务 | 按下右摇杆     | `Space`                           | 只作废当前或选中任务，其他`[OK]` 任务不变                 |
| 停止 session | 长按 B 1.5 秒  | `F`                               | 随时停止整个 session；活动 trial 会先记为`trial_rejected` |

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
- 主键盘数字行和小键盘 `1`--`5` 可以直接选中对应任务，但不会自动开始。
- 主键盘 `Enter` 和小键盘 `Enter` 都会开始当前选中任务。
- 主流程可以全部在小键盘完成：`1`--`5` 选任务，`Enter` 开始，`+` 写 marker，`0` 结束任务。
- `M` 和 `E` 分别是 marker 与结束任务的兼容键；`Space` 只作废当前或选中任务，`F` 随时停止整个 session。
- 任务运行时会锁定选择；方向键和数字键都不会切换任务，也不会误写 marker。

键盘和手柄完全通用。可以用手柄开始、键盘写 marker、再用手柄结束，日志语义相同。

## 三、UI 怎么看

Canvas 固定在场景世界坐标中，不跟随 `CenterEyeAnchor`。

Canvas 上有两个并排面板。左侧是任务采集状态板，右侧是实时系统诊断板。两块面板都固定在场景根节点。

### 左侧任务采集状态板

```text
1 HEAD    2 6DOF    3 MOVE
4 ROT     5 OCC
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

| 面板字段                          | 含义                                                                                                                                                                                          |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `XR DEVICE / WORN`              | 是否检测到头显，以及 Meta runtime 是否判断头显正在佩戴                                                                                                                                        |
| `XR FOCUS / INPUT`              | Unity 是否持有 VR 画面和输入 focus；`LOST` 会显示红色                                                                                                                                       |
| `OUTPUT / DISPLAY / REF`        | 主 runtime 是否有输出、锚点是否实际可见、平台参考 Transform 是否可用；`ACTIVE` 表示正在更新，`HELD` 表示手柄失活后继续使用最后一次激活位姿；`CHECK VERIFIED` 表示参考绑定已通过运动预检 |
| `POSITION DELTA`                | 显示锚点相对 Quest 平台控制器参考的位置差异，单位 mm                                                                                                                                          |
| `ROTATION DELTA`                | 显示锚点相对 Quest 平台控制器参考的旋转差异，单位 deg                                                                                                                                         |
| `OBS AGE`                       | 当前显示使用的图像观测距现在有多久；它包含等待和运行时保持，不是纯网络时延                                                                                                                    |
| `E2E ARRIVAL`                   | 同一 Unity 单调时钟下，从图像时间代理到 Unity 处理该 PoseResult 的时间                                                                                                                        |
| `SERVER`                        | Python 同一单调时钟下的服务端处理时间，不与 Unity 时钟相减                                                                                                                                    |
| `SMOOTH`                        | 时序合成当前引入的实际输出延迟                                                                                                                                                                |
| `POSE RATE`                     | 新 PoseResult 对应 frame_id 的实时更新率                                                                                                                                                      |
| `VCD LATEST / ACCEPTED`         | 最新候选评分，以及最近一次被 policy 接受的评分                                                                                                                                                |
| `RESIDUAL`                      | policy 输出阶段的平移和旋转残差                                                                                                                                                               |
| `FRAME STEP`                    | 相邻 Unity 帧实际显示锚点的位姿变化，包含真实物体运动，不能直接当作抖动指标                                                                                                                   |
| `ANCHOR / MOTION / STATIC LOCK` | 锚点生命周期、运动状态和静止锁定状态                                                                                                                                                          |

开始任务前，先确认 `WORN YES`、`VR ACTIVE`、`INPUT ACTIVE`，并且 `OUTPUT`、`DISPLAY`、`REF` 都不是红色。再观察几秒，确认 `POSE RATE` 持续更新，`OBS AGE` 和 `E2E ARRIVAL` 没有不断上升，然后按 A 或 `Enter`。

不要为了得到更好看的结果，等 `POSITION DELTA`、`ROTATION DELTA` 或 VCD 分数特别低时才开始。右侧面板是连接和运行状态诊断，不是正式数据筛选器。控制器 pose 也不是外部光学真值；正式指标以日志完成后的 schema-v2 配对分析为准。

手柄静止后可能被平台隐藏。此时 `REF` 显示 `HELD`，位置和旋转差异仍按最后一次激活的 Transform 位姿计算；手柄重新激活后，参考位姿自动继续更新。`HELD` 不是错误，不需要为了让面板变回 `ACTIVE` 而移动手柄。

正式 session 启动前必须看到 `REF ... | CHECK VERIFIED`。进入 Play Mode 后，先拿起右手控制器移动至少约 1 cm，或旋转至少约 5 度，确认提示从 `MOVE TO VERIFY` 变为 `VERIFIED`，再把控制器放到任务要求的位置。这个预检用来证明 Recorder 绑定的是会随平台追踪更新的对象，而不是名称相似但不会更新的静态节点。

## 四、启动顺序

### 1. 启动 NATS

```powershell
nats-server
```

### 2. 在本机启动并检查 Mutagen

```powershell
cd EgoAnchor_Python
mutagen project start
mutagen sync list
```

确认 `logs-5090` 为 `Watching for changes`，且没有 conflict。建议从采集前就保持同步；如果中途未开启，只要远端 Python 日志完整落盘，停止后再开启同步仍可使用，但必须等所有分片完整回传后才能运行 QC。

### 3. 在 5090 电脑启动 Python

```powershell
cd EgoAnchor_Python
pixi run python .\src\run_server.py --object controller_right
```

Python 服务端日志写到远端 `data/eval/<session_id>/`，再由 Mutagen 回传到本机 `EgoAnchor_Python/data/eval/`。Unity 不应直接覆盖 Python 的日志文件。

### 4. 启动 Unity

1. 打开 `Assets/Scene/EgoAnchor-Experiment12.unity`。
2. 检查 `ServerEndpointConfig` 的服务器 IP。
3. 进入 Play Mode。
4. 等待 Python 显示 NATS 已连接、ZMQ 正在监听 `15557`。
5. 等待 Unity 收到 Python 的 `session_id`。此时任务 1 只应呈黄色选中状态，不能显示 `[RUN]`，计时仍为 `--:--`。
6. 拿起右手控制器做一次明显的小幅移动或旋转，确认右侧 `REF` 显示 `CHECK VERIFIED`。
7. 查看右侧实时诊断板，确认 `WORN YES`、`VR ACTIVE`、`INPUT ACTIVE`，并等待输出信号和更新率稳定。
8. 只有按下一次 A、主键盘 `Enter` 或小键盘 `Enter` 后，Unity 才会在同一个输入回调中启动 session 和当前选中的任务。

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

## 六、任务 1--5 逐项操作

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

任务 1--5 运行期间，场景中的 9 个 runtime 始终同时接收同一条 PoseResult 候选流并写入长表。实验一从中选择 `Arrival-Hold`、`Capture-Hold`、`One-Euro Anchor` 和采用 Linear/SLERP 的完整 `EgoAnchor`；实验二从同一批原始行中选择完整 `EgoAnchor` 与四个单组件消融。采集时刻对齐、VCD 和 StaticLock 三个组件对照与完整系统同样使用 Linear/SLERP，确保只关闭目标组件；`EgoAnchor Hermite` 仅替换插值器，用于图 3(d) 的配对策略判断。操作者不需要为实验二或策略对比重复动作。原始 trial/event 上的 `experiment_id` 保留共享物理任务的 `exp1_system_characterization`，实验二由 variant/component 投影得到；分析不得按 `experiment_id == exp2_design_attribution` 排除这些消融行。

## 七、做错了怎么处理

当前任务是 `[RUN]` 时，按下右摇杆或按 `Space` 作废。任务回到 `[ ]`，其他 `[OK]` 不受影响；选中项仍停留在该任务，可以直接重新开始。

任务已经是 `[OK]` 时可以直接重采，不需要先删除：先选中它，再按 A 或 `Enter`。代码会先把旧 trial 写成 `trial_rejected`，再开始新 trial。旧日志保留用于审计，正式分析只使用新的未作废完成 trial。

如果只想删除完成状态而暂时不重采，选中任务后按下右摇杆或按 `Space`。该任务回到 `[ ]`，不会自动开始，也不会影响其他任务。

## 八、结束一个模块化 session

为了避免 Python 停止后的尾帧没有 Unity admission，最后一项任务完成后严格按以下顺序：

1. 确认没有 `[RUN]`，用 `TASKS` 和蓝色 `[OK]` 核对本次完成的任务。
2. **先停止 5090 上的 Python**，按 `q`、`Esc` 或正常终止服务，并在远端确认 `python_session.json` 的 `state` 已变为 `python_stopped`。
3. 立即回到 Unity，保持 Play Mode，按 `F` 或长按右手 B 1.5 秒停止 session。若有活动 trial，它会自动写入 `trial_rejected`，已经完成的 `[OK]` 任务不受影响。
4. 等 Unity 控制台显示 manifest 已写入，再退出 Play Mode。
5. 等 Mutagen 的 `logs-5090` 回到 `Watching for changes`，确认没有 conflict，然后运行 QC。若 `events.jsonl` 尚不存在，QC 会先核对两个事件分片与停止态 writer 统计，再原子生成该文件；已有文件只验证，不会被覆盖。

不要在 Python 仍持续发布 PoseResult 时先结束 Unity session。QC 会统计跨端未消费的 Python candidate；实际进入 Unity 的 candidate 仍必须完整覆盖 9 个 runtime。

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

`python_events.jsonl` 由 5090 Python 独占写入，`unity_events.jsonl` 由本机 Unity 独占写入。同步完成后，QC 会在缺少总表时生成 `events.jsonl`；如果任一分片未停止、行数不符、存在丢行或写入失败，QC 返回 2，且不会留下临时或部分总表。不要手工修改内部固定文件、manifest 的 `session_id`，也不要在仍启用 `logs-5090` 时重命名 `data/eval/<session_id>/`；原始目录保持 Python 生成的 session 名即可。

## 九、运行 QC 并归档

```powershell
cd EgoAnchor_Python
pixi run python -m egoanchor.eval.cli qc .\data\eval\<session_id>
```

返回码为 `0` 且 JSON 中 `"passed": true` 才算当前 session 结构通过。还要确认 writer 的 `dropped_rows`、`log_write_failures` 都为 0，完成任务与 lifecycle 一致，当前任务有 marker，每个被 Unity 消费的 candidate 有 9 个 admission，每个 render tick 有 9 个 runtime。任务 2 至少要有一个 `transition_started`；任务 5 的遮挡/重新可见 marker 必须成对闭合。五个 session 复制到批次暂存目录后还要再运行整批 QC；分析会检查五项任务覆盖和四个消融的关键指标，缺少任一项都不会发布正式 CSV、PDF 或 TeX。

实验一和实验二使用同一组五项任务。每个正式 session 只完成一个任务；五个 session 必须
使用相同配置并分别对应任务 1--5。QC 通过后，先停止 Mutagen，再按分析复现手册复制到
`data/experiments/_staging/experiment_1_2/<batch_id>/raw/` 的固定任务目录。不要直接把裸
session 当作长期归档，也不要删除仍未完成同步的 `data/eval/<session_id>`。

工作簿和论文结果统一通过 `qc`、`preprocess`、`build-paper` 三个命令重建，完整命令见
`experiment_1_2_analysis_reproduction_manual_zh.md`。

## 十、Inspector 改绑与正式采集前自检

本项目不使用 InputActionAsset。正式场景的 `ExperimentInputHandler` 直接在 Inspector 序列化 `Navigate Action`、`Start Action`、`Mark Action`、`Stop Action`、`Finish Action`、`Reject Action` 和 5 项 `Task Actions`。需要改绑时展开对应 Action 的 Bindings 直接修改。`ExperimentStatusUI` 的所有颜色也暴露在 Inspector 中。

开始正式采集前做一次工程功能自检，确认右手摇杆、A、右扳机、B 短按/长按、摇杆按下，以及键盘方向键、数字行/小键盘 `1`--`5`、两个 `Enter`、小键盘 `+`、小键盘 `0`、`M`、`E`、`F`、`Space` 都有效。还要确认数字键只选择、不自动开始，运行中不能切换，`Space` 只作废选中任务，`F` 或长按 B 可以随时停止 session，完成任务选中后仍为蓝色并能直接重采，marker 成功和拒绝都有明显反馈，遮挡 marker 能正确配对，两块 Canvas 面板不跟随头部，实时指标持续更新，`REF` 运动预检能从 `MOVE TO VERIFY` 变为 `VERIFIED`，日志无 dropped row 和 write failure。工程功能自检不是另一类实验 session；真正写入评估目录的数据统一为 formal。

## 十一、Quest 串流黑屏怎么处理

如果头显突然黑屏，先看右侧面板最后显示的 XR 状态。`WORN NO`、`VR LOST` 或 `INPUT LOST` 说明 Meta runtime 已经撤回画面或输入 focus。代码会立即暂停双目 GPU 读回和 JPEG 编码；focus 恢复后自动继续，并把 `xr_focus_lost`、`xr_focus_acquired` 写入 `unity_events.jsonl`。

按以下顺序处理：

1. 确认头显仍然佩戴稳固，近距传感器没有被面罩、胶带或头发遮挡。
2. 唤醒头显并确认 Quest Link 仍连接；需要时回到 Link 界面后再进入 Unity。
3. 等面板恢复为 `WORN YES | VR ACTIVE | INPUT ACTIVE`，并确认 `POSE RATE` 重新更新。
4. 作废黑屏期间正在运行的 trial，再重新采该任务。已经完成的其他任务不用重做。

本次排查过的黑屏日志在故障点依次出现 `HMDUnmounted`、`VrFocusLost` 和 `InputFocusLost`。同一时段的 render、双目发送和日志队列仍正常，没有 OOM、显卡设备丢失、发送失败或 writer 丢行，因此不能把这次故障归因于录制代码卡死。双目同步 `ReadPixels` 和 JPEG 编码仍是长期性能风险；如果以后在 `WORN YES`、`VR ACTIVE` 时再次黑屏，再单独采集 Unity Profiler、Meta Link 日志和 GPU/GC 数据。

正式采集进入 Play Mode 后，不要修改脚本、保存场景、刷新 AssetDatabase，也不要让 Unity MCP 启动或停止 Play Mode。先结束 session 并退出 Play Mode，再进行代码改动。
