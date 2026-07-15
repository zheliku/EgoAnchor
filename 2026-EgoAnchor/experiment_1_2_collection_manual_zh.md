# EgoAnchor 实验一/二采集手册（简化版）

正式采集使用 `EgoAnchor_Unity/Assets/Scene/EgoAnchor-Experiment12.unity`。这个场景已经固定为
Formal，不需要在 Inspector 填操作员、运行模式、参数集、模型版本、Git commit 或协议版本。

采集时只用一个“推进”动作：

- 戴头显时按右手控制器 A；
- 桌面调试时按键盘 `Space`。

两种输入完全等价。默认 Input System binding 显示在 `ExperimentInputHandler` Inspector 中，可以直接
改成其他按键。状态面板保持在场景中的固定位置，不跟随头部。

平台 reference 来自 Quest 追踪系统，不是外部光学真值。`capture_mono_ms` 是 image-time proxy，
也不是曝光真值。

## 1. 启动

先启动 NATS：

```powershell
nats-server
```

再启动 Python：

```powershell
cd EgoAnchor_Python
pixi run python .\src\run_server.py --object controller_right
```

`--object` 必须与正式场景中的 `EvalSession.objectId` 相同。默认值都是 `controller_right`。

Python 就绪后：

1. 打开 `Assets/Scene/EgoAnchor-Experiment12.unity`。
2. 检查 `ServerEndpointConfig` 的服务器 IP。
3. 进入 Play Mode。
4. 等待 Python 出现 `connected url=...` 和 `listening endpoint=...:15557`。
5. 等 Unity 出现 `复用 Python session_id：...`，状态面板显示 `Recording`。

收到第一个带 Python `session_id` 的 PoseResult 后，Unity 自动开始 session。不要手动创建目录，也不要
在同一个 Python session 内重新开始录制。

## 2. 单键流程

状态面板中的 `NEXT` 是下一次按键的含义，`Progress` 显示当前场景序号。系统按固定顺序执行实验一
5 个场景，再执行实验二 4 个场景。

普通场景只需三次推进：

1. 准备好目标后，按 A（或 `Space`）开始 trial。
2. 完成静止基线，在动作开始的同一时刻按一次，随后执行动作。
3. 动作结束并留足恢复窗口后再按一次。系统结束当前 trial，并选中下一个场景。

遮挡场景需要四次：

1. 按一次开始 trial。
2. 开始遮挡时按一次，写入 `occlusion_started`。
3. 目标刚重新可见时按一次，写入 `target_visible`。
4. 恢复窗口结束后按一次，进入下一场景。

第 9 个场景结束后，Unity 自动停止 session 并写 `manifest.json`，不需要停止快捷键。

## 3. 固定场景顺序

| 进度 | 场景 | 动作与标记时机 |
|---:|---|---|
| 1/9 | 静止目标与主动头动 | 目标保持不动；第二次按键后左右转头、俯仰并前后移动观察 |
| 2/9 | 起停 6DoF | 第二次按键后立即移动并旋转目标，随后明确停止并等待稳定 |
| 3/9 | 持续平移 | 第二次按键后沿冻结方向连续平移，尽量不旋转 |
| 4/9 | 持续旋转 | 第二次按键后绕冻结轴连续旋转，尽量不平移物体中心 |
| 5/9 | 遮挡恢复 | 第二次按键开始遮挡，第三次按键标记目标重新可见 |
| 6/9 | w/o capture-time alignment | 目标固定；第二次按键后执行主动头动 |
| 7/9 | w/o VCD admission | 使用四次按键的遮挡流程 |
| 8/9 | w/o temporal synthesis | 第二次按键后执行起停 6DoF，停止后等待稳定 |
| 9/9 | w/o StaticLock | 第二次按键后移动并旋转目标，停止后等待重新稳定 |

所有 8 个 runtime 在同一候选流、同一 reference 和同一时间线上同步运行。不要为某个基线或消融单独
重启 Python，也不要按配置重复动作。

右手 A 同时用于采集推进和控制器输入。按键时保持握持稳定，按下后再开始目标运动，避免把按键造成的
瞬间晃动当作实验动作。

## 4. Smoke 与 calibration

第一次正式采集前，先在 `EgoAnchor-Develop.unity` 跑 smoke 和 calibration。两者使用相同的 A/`Space`
流程，但不进入论文结果。

Smoke 只检查：

- NATS/ZMQ 双向计数持续增加；
- Unity 与 Python 使用同一个 `session_id`；
- A 和 `Space` 都能推进同一状态机；
- 遮挡场景依次出现 `occlusion_started` 和 `target_visible`；
- 日志没有 dropped row 或 write failure。

Calibration 用于冻结 One Euro、VCD、Kalman--Hermite、StaticLock 和各场景的动作时长。正式场景的
`config_hash` 会自动成为 `frozen_parameter_set_id`，不再人工命名参数集。

一次 Formal session 固定完成 9 个场景各一遍。需要重复时，正常退出 Python并重新启动，采集一套新的
完整 session。不要在同一 session 中临时增加重复次数。

## 5. 结束与检查

状态面板显示 `COLLECTION COMPLETE` 后：

1. 等 Unity 控制台出现 `Manifest 已写入` 和 `Session 结束`。
2. 在 Python OpenCV 窗口按 `q` 或 `Esc`。
3. 等 `python_session.json` 的 `state` 变为 `python_stopped`。
4. 远端采集时，等日志同步完成后再运行 QC。

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

五个 JSONL 文件都不能是空文件。`manifest.json` 和 `python_session.json` 的 `session_id` 必须与
目录名相同，所有 writer 的 `dropped_rows` 和 `log_write_failures` 必须为 0。

运行 QC：

```powershell
cd EgoAnchor_Python
pixi run python -m egoanchor.eval.cli qc .\data\eval\<session_id>
```

返回码为 `0` 且 JSON 中 `"passed": true` 才算通过。

## 6. 失败与重采

以下情况需要放弃当前 session：

- Unity 与 Python 的 session ID 不同；
- NATS/ZMQ 中断，或 pose 流长时间停止；
- 按键时机错误、执行了错误动作，或遮挡事件没有闭合；
- 平台 reference 无效，目标离开可测范围；
- Formal 期间改了代码、模型、参数或场景配置；
- writer 丢行、写入失败，或 QC 不通过。

停止 Play Mode 并正常关闭 Python，保留原目录并标为 rejected。修正问题后新建 Python session，重新
采集完整 9 个场景。不要删行、补行、改 event ID 或覆盖原目录。
