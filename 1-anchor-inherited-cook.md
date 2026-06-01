# EgoAnchor 评估系统（Phase P1）落地计划

## Context（为什么做这件事）

你要为 IEEE VR 2027 论文的**指标实验部分**建立定量证据，同时拿到基线数字以指导系统下一步优化（静止抖动、坏 pose 识别、自适应评分）。本轮原则是 **measure-first**：先把采集、对齐、指标和图表打通，不修改 anchor 算法本体。

对比方案已锁定：用 EgoAnchor 追踪 Quest3 左右手柄（`pixi run controller_right` / `pixi run controller_left`，已有 `MetaQuestTouchPlus_Right/Left.glb` mesh），把 **Meta SDK 的 `OVRInput` 手柄 6DoF 当作 ground truth/reference**。Meta SDK 是有 IMU/主动追踪的上界，不宣称超越它；论文的“胜”来自内部消融与系统能力：EgoAnchor 不要求物体内嵌任何传感器，纯视觉即可把异步 6DoF pose stream 转成稳定、世界一致、可恢复的 MR anchor。

本计划以 [`2026-EgoAnchor/paper-plan/EgoAnchor-Evaluation-Plan.md`](2026-EgoAnchor/paper-plan/EgoAnchor-Evaluation-Plan.md) 为草案来源，并补齐三个已决策修订：P1 纳入 `score_calibration`，时间记录改为完整链路，Unity runtime 增加只读 `RuntimeSnapshot`。

### 已核验的代码事实

- Unity 侧已有 `PoseToAnchorRuntime.TryGetRawPose` / `TryGetStablePose` / `AcceptWorldPose(frameId, worldPose)` 与 policy 诊断属性；评估记录器可以单向读取 runtime。
- 采集缝点位于 `StereoFrameSource.TryCapture` 中 `framePoseHistory.Record(...)` 后；只有这里知道 frame_id 与采集时刻相机位姿。
- 评分确实容易坍缩为 1.0：`pose_quality.py` 在 `has_pose` 且 depth/mask 正常时几乎不降分；P1 必须记录 score calibration，但不在本轮改评分算法。
- 原草案的数据仍有遗漏：缺 Unity NATS receive/decode/apply 时间、Python `server_receive_*` 实际填充、Unity encode/send 时间、人类可读时间字段、score calibration 指标。

---

## 指标与对比方式

每个定量指标都用 SDK GT 计算误差。记 anchor 是 mesh 原点世界位姿 `W_T_A`，GT 是手柄世界位姿 `W_T_C`，左右手柄分别标定常量刚体 `X = C_T_A`，误差为：

`E = inv(W_T_C · X) · W_T_A`，`e_t = ||E.t||`（米），`e_r = angle(E.R)`（度）。

| # | 指标 | 测什么 | 怎么测 |
|---|---|---|---|
| 1 | World-space anchor error | 锚定相对 GT 的世界系误差 | 每条件报 `e_t/e_r` 的 RMSE、median、p95 |
| 2 | Head-motion-induced slip | 头动时静止物体是否“滑动” | 用头相机 intrinsics 把 anchor 与 GT 投影到像面，报 `slip_px`，并统计与头部角速度的相关性 |
| 3 | World-space jitter | 静止窗内位姿时间离散度 | GT 速度低于阈值时自动切静止窗，高通去慢漂后报 position/rotation std 与 RMS |
| 4 | Lag | 物体运动到 anchor 响应的延迟 | 速度信号重采样后互相关取 argmax；快速段另报 90% 上升时间 |
| 5 | End-to-end latency | capture 到 first apply 的端到端时延 | Unity 单调钟算 `first_apply - capture_start`；Python timing 负责模块 breakdown |
| 6 | Recovery rate / time | 遮挡/出视野后恢复能力 | manifest marker + anchor_state + 误差回落阈值，报 success rate 与 recovery time |
| 7 | Jump suppression | 坏跳变是否被抑制 | raw 尖峰 vs policy 输出，统计尖峰数量、幅度、reject/hold/coast 比例 |
| 8 | Score calibration / bad-pose detection | reliability score 是否能识别 bad pose | 以 `e_t > 0.05m` 或 `e_r > 15deg` 标 bad pose，另统计 severe jump：`translation > 0.10m` 或 `rotation > 45deg`；输出 ROC-AUC、PR-AUC、precision/recall、score-error scatter、score histogram |
| 9 | Task/主观（可选） | 用户任务体验 | 本轮只留 event marker 钩子，不实现 |

RQ 映射：

- RQ1：arrival-time vs frame-aligned，对比 anchor error 与 slip。
- RQ2：raw / low-pass / Kalman / current policy，对比 jitter、lag、jump suppression、stable error。
- RQ3：always-update vs hold/coast/reacquire，对比 recovery 与 failure taxonomy。
- 通用：latency breakdown、score calibration、日志完整性。

---

## 时间字段标准

每个关键时间点统一记录四类字段：

- `*_mono_ms`：同进程延迟计算主字段。
- `*_unix_ms`：跨进程粗对时和人工排查字段。
- `*_local_iso`：本地时区可读时间，例如 `2026-06-01 21:34:12.345 +08:00`。
- `*_utc_iso`：UTC ISO-8601，例如 `2026-06-01T13:34:12.345Z`。

指标计算不用 ISO 字符串；延迟仍以 `mono_ms` 或 `unix_ms` 数值计算。ISO 只用于人读、日志扫查和论文复核。

---

## 要采集的数据

### `<session>_unity_capture.jsonl`

每个实际发送的 stereo frame 一行，服务于 GT@capture、X 标定、RQ1、latency 起点。字段：

- session/object：`session_id`、`object_id`、`frame_id`、`unity_frame`。
- capture：`capture_start_*`、`encode_done_*`、left/right image size、jpeg bytes。
- send：`send_attempt_*`、`send_done_*`、`send_success`、`send_topic`、`send_endpoint`、payload bytes。
- pose：head world pose、left/right/center camera world pose、GT controller world pose、`gt_position_tracked`、`gt_orientation_tracked`、`gt_valid`。

### `<session>_unity_pose_receive.jsonl`

每条 PoseResult 到 Unity 后一行，服务于 Python→Unity 网络腿、latest-only 丢帧分析、decode/apply 时间链路。字段：

- `frame_id`、`pose_has_pose`、`pose_phase`、`pose_source`、`reliability_score`。
- `unity_receive_*`（NATS 后台回调入队时刻）。
- `unity_decode_*`（主线程 Protobuf decode 时刻）。
- `skipped_older_payloads`、`queue_dropped_count`、`pending_before_decode`。

### `<session>_unity_output.jsonl`

每个 render tick 一行，服务于 jitter、lag、slip、latency 终点、policy 对比。字段：

- `render_*`、head pose、GT pose、`gt_valid`。
- `variants[]`：每个 runtime 一项，含 `label`、`has_raw_pose`、`has_stable_pose`、raw/stable pose、`latest_frame_id`、`anchor_state`、`policy_action`、`policy_reason`、`reliability_score`、`accept_*`、`first_apply_*`、`pose_age_ms`。

### `session_manifest.json`

每 session 一份，服务于条件切分与可复现：

- `session_id`、`object_id`、`unity_run_mode`、`gt_source`、`timezone`、`mono_to_unix_offset_ms`。
- `condition_spans[]`、`event_markers[]`、`variant_labels[]`、`python_runtime_log_path`、`notes`。

### Python runtime log

继续作为 pose/timing/source/reliability 主日志，并补齐：

- `server_receive_*`：Python ZMQ receive time。
- `pipeline_start_*`、`pipeline_done_*`：pipeline processing span。
- `server_publish_*`：PoseResult publish submit time。
- `yolo_ms`、`depth_ms`、`cutie_ms`、`pose_ms`、`total_ms`。

---

## Unity 侧实现

新增 `EgoAnchor_Unity/Assets/Scripts/EgoAnchorEval/`，自带 `EgoAnchorEval.asmdef`，单向依赖 `EgoAnchor`、`Oculus.VR`、`meta.xr.mrutilitykit`。`EgoAnchor.asmdef` 不反向依赖 eval，编译期隔离 GT。

| 文件 | 类型 | 职责 |
|---|---|---|
| `EvalTime.cs` | 纯 C# | 统一生成 mono/unix/local/utc 时间戳 |
| `EvalJson.cs` | 纯 C# | JSON 转义、pose/时间字段写入辅助 |
| `JsonlFileWriter.cs` | 纯 C# | 缓冲 append + 周期 flush |
| `ControllerGroundTruthProvider.cs` | MonoBehaviour | LTouch/RTouch -> Unity world GT pose + tracked 标志 |
| `AnchorEvalRecorder.cs` | MonoBehaviour | 核心记录器：capture、pose receive、output 三类 JSONL |
| `EvalSessionController.cs` | MonoBehaviour | session 开停、condition、marker、manifest |
| `ReplayPoseSource.cs` | MonoBehaviour | P1b：读 raw 流重泵进 runtime |

运行时接口修订：

- `StereoFrameSource` 新增 `StereoFrameCaptureInfo` 与 capture 事件，包含 frame_id、unity_frame、capture start、encode done、图像尺寸、jpeg bytes、left/right/center camera pose。
- `QuestStreamPublisher` 新增 `StereoFramePublished` 事件，包含 send attempt/done、sent/dropped、topic、payload bytes、endpoint。
- `NatsControlClient` 的 pose queue 从 `byte[]` 改为轻量 envelope：payload + background receive timestamps + queue stats。
- `NatsTypedReceiver` 在主线程 decode 后把 decode context 传给 `PoseResultReceiver`。
- `PoseResultReceiver` 广播 PoseResult 给 runtime，同时把 receive/decode context 传给 eval recorder。
- `PoseToAnchorRuntime` 增加只读 `RuntimeSnapshot`，不改变算法、不修改 Transform 应用逻辑。

---

## Python 侧实现

新增/填充顶层 `EgoAnchor_Python/eval/`（与 `src/` 平级，不 import runtime，只读 JSONL）：

```text
eval/
  io/log_loader.py
  io/schemas.py
  calib/hand_eye.py
  metrics/common.py
  metrics/anchor_error.py
  metrics/latency.py
  metrics/jitter.py
  metrics/slip.py
  metrics/jump_suppression.py
  metrics/score_calibration.py
  report/tables.py
  report/figures.py
  run_eval.py
```

Python runtime 只做日志补齐：

- `utils/time_utils.py`：统一时间戳。
- `quest_stream_receiver.py`：为每个 stereo `frame_id` 保存 Python receive timestamp。
- `message_factories.py`：填充 `PoseResult.server_receive_mono_ms` 与 `server_publish_mono_ms`。
- `runtime_log_writer.py`：补齐 receive/publish ISO 时间与分模块 timing。
- `tracking_runtime.py`：把 receive/pipeline/publish timestamps 串到 PoseResult 与日志。

pixi 任务：

- `eval = "python eval/run_eval.py --session-dir data/eval/{session}"`
- `eval-calib = "python eval/run_eval.py --session-dir data/eval/{session} --only calib"`
- `eval-figures = "python eval/run_eval.py --session-dir data/eval/{session} --only figures"`

---

## 录制协议（左右手柄各跑一轮）

每段用 `BeginCondition/EndCondition` 打标签，瞬时事件用 `Mark`：

| 段 | 时长 | 动作 | 标签 | 服务 |
|---|---|---|---|---|
| 1 | 30s | 物体放定、头不动 | `static` | jitter floor、精度底 |
| 2 | 30s | 物体放定、头自然左右上下 | `slow_head` | 日常 MR、slip 基线 |
| 3 | 20s | 物体放定、猛转头 yaw/平移 | `fast_head` | slip 峰值 |
| 4 | 30s | 手持手柄平移 + 充分三轴旋转 | `object_motion` | X 标定硬约束、lag |
| 5 | 20s | 手挡住一部分 | `occlusion` | 坏/缺观测、jump |
| 6 | ×5 | 移出视野再返回 | `out_of_view` | recovery |
| 7 | 20s | 开关灯/换背景 | `lighting` | 感知鲁棒 |

第 4 段旋转必须覆盖三轴足够范围，否则 `hand_eye` 旋转维不可辨识，脚本必须报警。

---

## 落地顺序

1. 修订计划文件。
2. Python 先写测试：时间戳、PoseResult receive/publish、runtime log timing 字段、eval/io join、score calibration。
3. 实现 Python runtime 时间链路和日志字段。
4. 新增 Unity Eval 程序集、时间/JSONL DTO、capture/send/receive/output 记录器。
5. 实现 Python eval/io 与基础 metrics。
6. 跑编译和单测；用短 session smoke 验证 frame_id join 和时间链路。
7. P1 稳定后再做 P1b replay 和 P2/P3 算法优化。

---

## 验证（本阶段完成定义）

- 10 秒 smoke session 中，每个 Python `pose_result.frame_id` 能 join 到 Unity capture；每个 Unity output variant 有一致的 snapshot。
- 任意一条 pose 能按时间链路还原：capture -> encode -> send -> Python receive -> pipeline -> publish -> Unity receive -> decode -> accept -> first apply。
- 报告中同时出现数值时间差和人类可读时间戳。
- `pixi run eval` 输出基础表图，并包含 score calibration 图表。
- Python 单测、Unity 编译验证通过。

---

## 风险

| 风险 | 缓解 |
|---|---|
| OVRInput 是预测位姿，快速段与真实有偏 | 静态/慢速无影响；快速段 lag 标注，列 limitations |
| Editor+Link 低估真实网络/编码时延 | latency 标注偏乐观；需论文级数据时补 Quest standalone 录制 |
| 手柄旋转激励不足导致 X 不可辨识 | 第 4 段强制三轴充分旋转；`hand_eye` 自动报警 |
| 每渲染帧写盘卡顿 | `JsonlFileWriter` 缓冲 + 周期 flush；必要时 output 降到 30Hz |
| 双盲泄露路径/用户名 | 投稿前清理 session 元数据 |
