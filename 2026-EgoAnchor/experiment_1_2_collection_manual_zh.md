# EgoAnchor 实验一/二采集手册

本文用于 Run 1 的 smoke、calibration 和 formal 采集。正式场景是
`EgoAnchor_Unity/Assets/Scene/EgoAnchor-Experiment12.unity`。原始数据统一写到
`EgoAnchor_Python/data/eval/<session_id>/`。

平台 reference 来自 Quest 追踪系统，不是外部光学真值。`capture_mono_ms` 是相机位姿历史给出的
image-time proxy，也不是曝光真值。发现问题时保留原目录，不手改 JSONL。

## 1. 采集前检查

### 1.1 机器和对象

- Python 环境已经用 Pixi 安装并完成项目要求的模型构建。
- NATS server 可用，默认监听 `4222`。
- Unity 的 `ServerEndpointConfig` 指向运行 Python 和 NATS 的机器。ZMQ 数据面端口固定为
  `15557`，NATS 端口为 `4222`。
- Python 的 `--object` 与 Unity `EvalSession.objectId` 相同，例如
  `controller_right`。
- 目标三维模型、平台 reference Transform 和相机标定已经绑定。模型版本写入
  `objectModelId`。
- `EvalRecorder` 中有 8 个唯一 runtime：四个实验一配置（其中包含完整 EgoAnchor）和四个消融；
  完整 EgoAnchor 在两个实验中共用同一个 runtime。

### 1.2 Session 用途

在 Unity Inspector 中先设置 `EvalSession.runKind`：

| 用途 | `runKind` | 说明 |
|---|---|---|
| 链路检查 | `Smoke` | 只检查传输、录制、事件和 QC |
| 参数冻结 | `Calibration` | 调 One Euro、VCD、Kalman--Hermite、StaticLock 和事件操作时机 |
| 正式采集 | `Formal` | 使用已经冻结的参数，不再调参 |

Formal 开始前还要填写：

- `operatorId`：匿名操作员编号，不写姓名；
- `runMode`：如 `editor_link` 或实际使用的真机模式；
- `frozenParameterSetId`：calibration 后冻结的参数集编号；
- `objectModelId`：目标 mesh/模型版本；
- `egoanchorGitCommit`：本次采集代码 commit；
- `protocolVersion`：当前为 `v1`。

任一项为空时，Formal session 会拒绝启动。Formal 还要求先收到 Python `session_id`，不会回退到
Unity 本地时钟命名。

## 2. 启动顺序

### 2.1 启动 NATS

在单独的 PowerShell 窗口运行：

```powershell
nats-server
```

如果 NATS 不在本机，Python 配置和 Unity `ServerEndpointConfig` 必须指向同一个服务器地址。

### 2.2 启动 Python

在仓库根目录打开第二个 PowerShell：

```powershell
cd EgoAnchor_Python
pixi run python .\src\run_server.py --object controller_right
```

把 `controller_right` 换成实际对象 ID。默认配置已经开启 eval session 模式，会创建
`data/eval/<session_id>/python_session.json` 和 Python 日志。

先看 Python 控制台：

- NATS 出现 `connected url=...`；
- ZMQ 监听地址使用 `15557`；
- 收到 Quest 数据后，等待统计中的 `stereo` 和 `camera_info` 持续增加；
- OpenCV 窗口从等待画面切换到真实图像和 pose/score 诊断。

模型第一次加载较慢。没有真实图像前不要开始计时。

### 2.3 启动 Unity

1. 打开 `Assets/Scene/EgoAnchor-Experiment12.unity`。
2. 再检查一次服务器 IP、`runKind`、对象 ID 和 session 元数据。
3. 进入 Play Mode。
4. 等 Unity 控制台出现 NATS `connected url=...`。随后核对 ZMQ 周期统计中的
   `stereo=...`、`camera_info=...` 和 `endpoint=...:15557`；两个发送计数应持续增加。
5. `autoStart=true` 时，第一个带 Python `session_id` 的 PoseResult 会自动开始录制。关闭
   `autoStart` 时，确认已经收到 Python pose 后按 `F7`。

### 2.4 检查跨端配对

开始任何 trial 前，核对下面四处：

1. Unity 控制台出现 `复用 Python session_id：<session_id>`，不能出现“回退到本地时钟”。
2. 头显状态面板显示 `Recording`，`Session` 与 Python 新建目录名相同。
3. `EgoAnchor_Python/data/eval/<session_id>/` 已出现 Python 侧文件。
4. Unity 的 pose、status、heartbeat 接收计数继续增加，Python 的 stereo/camera_info 计数也在增加。

Python 在远端机器时，Unity 和 Python 日志最终仍要合并到同名 `<session_id>` 目录。先等同步完成，
再跑 QC。

## 3. 键盘操作

按键只在 Unity Game 窗口获得焦点、且 session 正在录制时生效。

| 按键 | 行为 |
|---|---|
| `1` 至 `5` | 选择实验一场景 |
| `Shift+1` 至 `Shift+4` | 选择实验二归因场景 |
| `Enter` | 开始当前场景的新 trial |
| `Space` | 写当前场景的主事件 marker |
| `Shift+Space` | 在遮挡场景写 `target_visible` |
| `0` | 结束当前 trial |
| `F7` | 手动开始 session，仅在关闭自动启动时使用 |
| `F8` | 停止 session 并写 `manifest.json` |

活动 trial 中不能切换场景。场景选择成功后，面板会显示实验名和场景名；按 `Enter` 后
`Trial` 从 `Idle` 变为 `trial_...`。每个正式 trial 只写一次主事件，遮挡场景再写一次
`target_visible`。

一次供实验一/二共同分析的 Formal session 要覆盖实验一的 5 个场景和实验二的 4 个归因场景。
按冻结采集表完成每个场景的规定重复次数，场景之间不重启 Python。全部 trial 完成后再按 `F8`。

## 4. 一分钟 smoke

Smoke 只验证链路，不用于论文结果。下面的时间是现场操作参考，不是 formal 参数。

1. `0-10 s`：等待自动录制。核对 `Recording`、跨端 session ID 和实时计数。
2. `10-25 s`：按 `1`，再按 `Enter`。目标保持静止，按一次 `Space`，缓慢左右转头并前后移动；
   结束后按 `0`。
3. `25-50 s`：按 `Shift+2`，再按 `Enter`。按 `Space` 后完全遮挡目标约 5 秒；目标刚重新可见时
   按 `Shift+Space`，继续保持可见约 5 秒，再按 `0`。
4. `50-60 s`：确认状态面板没有开放的遮挡事件，按 `F8` 停止 Unity 录制。
5. Unity 写出 manifest 后，在 Python OpenCV 窗口按 `q` 或 `Esc`。等待 Python 正常退出。

如果 `0` 在遮挡 trial 中没有反应，通常是漏了 `Shift+Space`。先让目标重新可见并补写该 marker，
再结束 trial；本次 smoke 记为操作异常。

## 5. 实验一：端到端系统表征

实验一的四个配置会在同一个 render tick 上同步运行：Arrival-Hold、Capture-Hold、One-Euro Anchor
和 EgoAnchor。一次动作只做一遍，不按配置分别重采。

正式重复次数、动作时长、移动距离和速度必须在 calibration 结束前写入采集表。本手册只固定按键和
动作顺序。

### 5.1 `1`：静止目标与主动头动

1. 让目标固定在平台 reference 对应位置，不碰目标。
2. 按 `1`，按 `Enter`，先留出冻结表规定的静止基线。
3. 按 `Space` 写 `generic_marker`，随后做冻结表规定的左右转头、前后移动和观察角度变化。
4. 头部回到结束姿态并保持稳定，按 `0`。

目标发生物理位移时，本 trial 作废。

### 5.2 `2`：起停 6DoF

1. 目标先静止，按 `2` 和 `Enter`。
2. 基线结束时按 `Space`。该 marker 的角色是 `transition_started`。
3. 紧接着移动并旋转目标，完成冻结的 6DoF 轨迹，然后明确停止。
4. 停止后继续保持，给 unlock、relock 和 settling 留出完整窗口，再按 `0`。

不要在按 `Space` 前提前移动目标。

### 5.3 `3`：持续平移

1. 按 `3` 和 `Enter`，目标先静止。
2. 按 `Space`，沿冻结的方向和距离连续平移，尽量不旋转。
3. 完成轨迹并保持稳定，按 `0`。

途中明显停顿、回摆或额外旋转时，本 trial 作废。

### 5.4 `4`：持续旋转

1. 按 `4` 和 `Enter`，目标先静止。
2. 按 `Space`，按冻结的轴和角度连续旋转，尽量保持物体中心位置不变。
3. 完成旋转并保持稳定，按 `0`。

大幅平移或旋转方向错误时，本 trial 作废。

### 5.5 `5`：遮挡恢复

1. 按 `5` 和 `Enter`，先记录无遮挡基线。
2. 遮挡动作开始时按 `Space`，写入 `occlusion_started`。
3. 按冻结方式完全遮挡目标，保持规定时长。
4. 移开遮挡物；目标刚重新可见时按 `Shift+Space`，写入新的 `target_visible` 事件。
5. 保持目标可见且静止，完成恢复窗口后按 `0`。

`occlusion_started` 与 `target_visible` 必须按顺序出现，使用两个不同的 event ID。漏掉后一个 marker
时，状态面板会显示 `Occlusion: Waiting for target visible`，trial 也无法结束。

## 6. 实验二：系统设计归因

实验二与实验一共用同一条 Python candidate 流、同一平台 reference 和同一时间线。场景中的 8 个
runtime 同步消费每个候选；不要为某个消融重启 Python，也不要把四个消融拆成四次独立感知采集。

离线分析只在每个场景比较完整 EgoAnchor 与对应消融，其他同步 runtime 用于完整性检查。

| 按键 | 场景 | 动作和事件 |
|---|---|---|
| `Shift+1` | `without_capture_time_alignment` | 目标固定，主动头动；头动开始前按一次 `Space` |
| `Shift+2` | `without_vcd_admission` | 遮挡开始按 `Space`；目标刚重新可见按 `Shift+Space` |
| `Shift+3` | `without_temporal_synthesis` | 目标从静止进入 6DoF 运动；开始前按 `Space`，停止后保持 |
| `Shift+4` | `without_static_lock` | 目标先静止；按 `Space` 后移动并旋转，再停止并等待重新稳定 |

每个场景的完整步骤都是：选场景，按 `Enter`，完成基线，按事件键，执行冻结动作，完成结束窗口，
按 `0`。`Shift+2` 必须在按 `0` 前闭合遮挡事件。

## 7. 停止和文件检查

按下面顺序结束一次 session：

1. 先结束当前 trial。遮挡 trial 要先写 `Shift+Space`。
2. 按 `F8`，等待 Unity 控制台出现 `Manifest 已写入` 和 `Session 结束`。
3. 在 Python OpenCV 窗口按 `q` 或 `Esc`，让 writer 正常关闭。
4. 等 `python_session.json` 的状态变为 `python_stopped`。远端采集还要等同步完成。

同名 session 目录内应有以下 7 项 schema-v2 输出：

1. `manifest.json`
2. `python_candidates.jsonl`
3. `unity_reference.jsonl`
4. `unity_admission.jsonl`
5. `unity_render.jsonl`
6. `events.jsonl`
7. `audit_samples/`

还要保留 `python_session.json`。它是 Python 停止态和 writer 统计 fragment，reader 会把它合并到
内存 manifest。不要把 pending 统计手工改成 0。

检查文件时还要看：

- 五个 JSONL 文件都不是空文件；
- `manifest.json` 和 `python_session.json` 的 `session_id` 与目录名一致；
- `python_session.json.state` 为 `python_stopped`；
- writer 的 `dropped_rows` 和 `log_write_failures` 都为 0；
- Formal manifest 包含 8 个唯一 runtime、非空 `config_hash` 和冻结元数据。

## 8. 运行 QC

回到 Python 目录执行：

```powershell
cd EgoAnchor_Python
pixi run python -m egoanchor.eval.cli qc .\data\eval\<session_id>
```

返回码 `0` 且 JSON 中 `"passed": true` 才算通过。返回码 `2` 表示 schema 或 QC 失败；返回码 `1`
表示文件系统问题。Run 1 先做 QC 和采集审计，正式图表与论文数字留到 Run 2。

## 9. 失败与重采

出现下列任一情况，停止当前 session：

- Unity 与 Python 的 session ID 不同，或 Unity 回退到本地时钟命名；
- NATS/ZMQ 断开、Python 崩溃、pose 流长时间中断；
- 选错场景、漏写事件、事件顺序错误或动作不符合冻结协议；
- 平台 reference 无效、目标离开可测范围或模型/对象 ID 不一致；
- JSONL 为空，writer 有 dropped row/write failure，或 QC 返回失败；
- Formal 期间改了参数、代码、模型、服务器配置或场景 runtime。

当前日志没有“删除某个坏 trial 后继续当作正式 session”的兼容路径。操作失误后，先安全结束并保留原
目录，在采集记录中标为 rejected；然后用相同冻结参数新建 session，重采整套正式流程。不要删行、补行、
改 event ID 或覆盖原目录。

Smoke 和 calibration 可以用新 trial 排查动作，但这些 session 不进入正式结果。

## 10. Calibration 与 Formal 冻结

Calibration 只使用开发数据，至少冻结下面几类内容：

- One Euro 参数；
- VCD admission 阈值和颜色不可用处理；
- Kalman--Hermite 的运动与输出参数；
- StaticLock 的进入、解锁、tether 和头停沉降参数；
- 每个场景的重复次数、动作时长、轨迹、遮挡时长以及事件判定时机。

冻结后记录 `frozenParameterSetId`、代码 commit、对象模型版本和场景配置 hash。随后把 Unity
`runKind` 改为 `Formal`。

看到 formal 数据后不得再调参数。QC 因采集故障失败时，可以在不改冻结参数的前提下重采；如果确实需要
改参数，旧 formal session 全部作废，重新生成参数集 ID，并从头开始正式采集。
