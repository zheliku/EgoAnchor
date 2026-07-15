# Experiment 1/2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` when executing this plan task-by-task. If subagents are not available, use `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Run 1 完成实验一和实验二正式采集前的全部工程准备：旧 RQ 代码硬删除、schema-v2 日志链路、Unity 四系统配置与组件消融、Python QC/分析/绘图/LaTeX 骨架、smoke 流程和中文采集手册。

**Architecture:** 本计划采用硬切换架构。Unity 运行时继续复用 `PoseToAnchorRuntime`、`AnchorRuntimeHub`、`AnchorPolicyHost`、`FramePoseHistory` 和现有 policy 模块，但删除 RQ1/RQ2 UI、场景与日志字段；Python 评估侧以 schema-v2 为唯一入口，不读取旧 `session_manifest.json`、旧 `*_unity_capture.jsonl`、旧 `*_unity_output.jsonl` 或旧 RQ 包。实验一比较四个端到端系统配置，实验二在完整 EgoAnchor 上关闭单一组件做配对归因。

**Tech Stack:** Unity C# / NUnit / Input System / Quest + OVR；Python 3 + pandas/numpy/matplotlib；Pixi；NATS + ZMQ；XeLaTeX / latexmk。

## Global Constraints

- 旧代码一律删除，不兼容旧代码，不兼容旧代码。
- 不添加 `FormerlySerializedAs`、旧字段、旧路径、旧标签、旧 CLI 兼容层或旧 schema fallback。
- 论文外部不再使用 RQ1/RQ2/RQ3 作为顶层结构；正式命名只使用实验一、实验二、实验三以及系统配置名。
- 实验一系统配置固定为 `Arrival-Hold`、`Capture-Hold`、`One-Euro Anchor`、`EgoAnchor`。
- 实验二组件归因固定为 `EgoAnchor`、`EgoAnchor w/o capture-time alignment`、`EgoAnchor w/o VCD`、`EgoAnchor w/o temporal synthesis`、`EgoAnchor w/o StaticLock`。
- schema-v2 原始日志固定为 `manifest.json`、`python_candidates.jsonl`、`unity_reference.jsonl`、`unity_admission.jsonl`、`unity_render.jsonl`、`events.jsonl` 和 `audit_samples/`。
- `capture_mono_ms` 是 image-time proxy，不得称曝光真值。
- 平台参考轨迹只称 platform reference，不称外部物理真值。
- `has_output_pose` 表示 runtime 是否有输出；`has_display_pose` 表示用户实际看到的 Transform。显示误差使用 display pose，输出覆盖率使用 output pose。
- `MeasurementTimeSeconds` 属于观测采集/组合语义时间轴；生命周期 freshness 使用到达/生命周期时间轴。不得用 capture time 刷新 stale/lost。
- 重获取只有一个中央 owner：`AnchorRuntimeHub` 汇聚 server reacquire 请求；各变体不得各自持有 command client。
- VCD 三层语义分开：连续可靠性评分、运行时 admission、离线 risk-coverage 诊断。VCD 不是排序算法，也不是位姿正确概率。
- 正式参数只允许使用开发/calibration 数据冻结；formal session 后不得调参。
- 本轮每个 Task 完成并验证后独立提交并推送；提交边界必须与 Task 边界一致。

---

## 0. 当前仓库事实

### 0.1 已经符合新路线的部分

- Unity runtime 主干已经是系统论文需要的组合式架构：
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/AnchorRuntimeHub.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/CameraPoseFrameAligner.cs`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/FramePoseHistory.cs`
- Unity policy 模块可直接组成新系统配置：
  - 零阶保持：`ConstantVelocityModel` + `RawPassthroughStrategy`
  - One Euro：`OneEuroModel` + `RawPassthroughStrategy`
  - EgoAnchor temporal synthesis：`KalmanModel` + `DelayedInterpStrategy`，`DelayedInterpStrategy` 使用 Hermite 样条时对应 Kalman--Hermite
  - StaticLock：`EgoAnchorStaticLockModule`
- Python runtime 主干可复用：
  - `EgoAnchor_Python/src/run_server.py`
  - `EgoAnchor_Python/src/egoanchor/app/tracking_server.py`
  - `EgoAnchor_Python/src/egoanchor/runtime/tracking_runtime.py`
  - `EgoAnchor_Python/src/egoanchor/perception/quest_pose_pipeline.py`
  - `EgoAnchor_Python/src/egoanchor/reliability/pose_quality.py`
  - `EgoAnchor_Python/src/egoanchor/reliability/render_quality.py`
- 协议与 subject 入口保留：
  - `EgoAnchor_Protocol/subjects.v1.json`
  - `EgoAnchor_Protocol/proto/protocol/v1/*.proto`
  - `EgoAnchor_Python/src/egoanchor/protocol/__init__.py`
  - `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/SubjectNames.cs`

### 0.2 必须硬删除或重写的旧路线

Unity 侧旧 RQ 代码和场景：

- 删除 `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/`
- 删除 `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ2/`
- 删除 `EgoAnchor_Unity/Assets/Scene/EgoAnchor-RQ1.unity`
- 删除 `EgoAnchor_Unity/Assets/Scene/EgoAnchor-RQ2.unity`
- 重写 `EgoAnchor_Unity/Assets/Tests/EditMode/EvalUiTests.cs`，不得继续 import `EgoAnchor.Eval.RQ1` 或 `EgoAnchor.Eval.RQ2`
- 重写 `EvalRecorder` 和 `EvalSession` 中的 RQ 字段、旧 manifest 文件名和旧日志文件名

Python 侧旧 RQ 代码和旧 schema：

- 删除 `EgoAnchor_Python/src/egoanchor/eval/research/rq1/`
- 删除 `EgoAnchor_Python/src/egoanchor/eval/research/rq2/`
- 删除 `EgoAnchor_Python/src/egoanchor/eval/research/rq3/`
- 删除或重写 `EgoAnchor_Python/src/egoanchor/eval/research/__init__.py`
- 重写 `EgoAnchor_Python/src/egoanchor/eval/io/schemas.py`
- 重写 `EgoAnchor_Python/src/egoanchor/eval/io/log_loader.py`
- 删除或重写 `EgoAnchor_Python/src/egoanchor/eval/core/batch_eval.py`
- 删除 `EgoAnchor_Python/src/egoanchor/eval/core/cross_scenario_analysis.py`
- 从正式 eval 入口删除 `EgoAnchor_Python/src/egoanchor/eval/core/plot_recorded_strategies.py`
- 重写 `EgoAnchor_Python/src/egoanchor/eval/report/figures.py`
- 重写 `EgoAnchor_Python/src/egoanchor/eval/report/tables.py`
- 删除或重写所有 `test_rq1_*`、`test_rq2_*`、旧 `test_log_loader.py`、旧 `test_run_eval.py`

---

## 1. 文件结构目标

### 1.1 Unity 目标结构

保留并改造：

- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`增加 world alignment mode，使 Arrival-Hold 成为真实 runtime 变体，而不是诊断字段。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`删除 RQ 文案，增加可序列化的实验组件开关摘要。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalRecorder.cs`重写为 schema-v2 recorder，输出 reference/admission/render 三张长表。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalSession.cs`重写为 schema-v2 session 控制器，写 `manifest.json`，不写 `session_manifest.json`。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalJson.cs`重写字段生成器，移除 `unity_capture`、`unity_output`、`rq1_*`、`rq2_*`。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalLog.cs`
  保留有界后台队列，增加每个 schema-v2 文件的 dropped rows 统计。

新增：

- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/WorldAlignmentMode.cs`定义 `CaptureTime` 与 `ArrivalTime`。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/Experiment/ExperimentId.cs`定义 `exp1_system_characterization` 与 `exp2_design_attribution`。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/Experiment/ExperimentScenario.cs`定义 `static_head_motion`、`start_stop_6dof`、`continuous_translation`、`continuous_rotation`、`occlusion_recovery`。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/Experiment/ExperimentTrialSelector.cs`管理 experiment/scenario/trial/event 上下文，替代 RQ1/RQ2 selector。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/Experiment/ExperimentInputHandler.cs`管理键盘输入，替代 RQ1/RQ2 input handler。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/Experiment/ExperimentStatusUI.cs`显示 session、variant、trial、event 状态，替代 RQ1/RQ2 status UI。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalV2Manifest.cs`生成 schema-v2 manifest。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalAdmissionSnapshot.cs`表达一条 candidate × variant admission 记录。
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalRenderSnapshot.cs`表达一条 render tick × variant 记录。
- `EgoAnchor_Unity/Assets/Scene/EgoAnchor-Experiment12.unity`
  正式实验一/二采集场景，配置所有端到端系统变体和组件消融。

删除：

- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/`
- `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ2/`
- `EgoAnchor_Unity/Assets/Scene/EgoAnchor-RQ1.unity`
- `EgoAnchor_Unity/Assets/Scene/EgoAnchor-RQ2.unity`

### 1.2 Python 目标结构

保留并改造：

- `EgoAnchor_Python/src/egoanchor/runtime/eval_session.py`生成 schema-v2 session 元数据和固定文件名。
- `EgoAnchor_Python/src/egoanchor/runtime/runtime_log_writer.py`改为写 `python_candidates.jsonl` 和 `events.jsonl`。
- `EgoAnchor_Python/src/egoanchor/diagnostics/runtime_event_log.py`保留 JSONL writer 能力，但禁止旧 event 字段进入正式 schema。
- `EgoAnchor_Python/src/egoanchor/eval/metrics/*.py`
  迁移 RQ 中性的 error、jitter、latency、recovery、diagnostics 逻辑到 schema-v2 normalized tables。

新增：

- `EgoAnchor_Python/src/egoanchor/eval/schema_v2/__init__.py`
- `EgoAnchor_Python/src/egoanchor/eval/schema_v2/paths.py`
- `EgoAnchor_Python/src/egoanchor/eval/schema_v2/rows.py`
- `EgoAnchor_Python/src/egoanchor/eval/schema_v2/writers.py`
- `EgoAnchor_Python/src/egoanchor/eval/schema_v2/readers.py`
- `EgoAnchor_Python/src/egoanchor/eval/schema_v2/qc.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/__init__.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/contract.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/qc.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/metrics.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/analysis.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/figures.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/latex.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/cli.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/contract.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/qc.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/metrics.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/analysis.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/figures.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/latex.py`
- `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/cli.py`
- `EgoAnchor_Python/src/egoanchor/eval/paper/latex.py`
- `EgoAnchor_Python/src/egoanchor/eval/paper/figures.py`
- `EgoAnchor_Python/src/egoanchor/eval/README.md`

删除：

- `EgoAnchor_Python/src/egoanchor/eval/research/`
- 旧 RQ tests
- 旧 schema reader fallback

### 1.3 论文与手册目标结构

新增：

- `2026-EgoAnchor/experiment_1_2_collection_manual_zh.md`中文采集手册：启动顺序、smoke checklist、实验一/二 trial 操作、停止条件、数据目录检查。
- `2026-EgoAnchor/generated/exp1_numbers.tex`
- `2026-EgoAnchor/generated/exp1_tables.tex`
- `2026-EgoAnchor/generated/exp2_numbers.tex`
- `2026-EgoAnchor/generated/exp2_tables.tex`
- `2026-EgoAnchor/generated/eval_qc_numbers.tex`
- `2026-EgoAnchor/figures/generated/exp1_*.pdf`
- `2026-EgoAnchor/figures/generated/exp2_*.pdf`

---

## 2. 系统配置的工程定义

### 2.1 实验一四个端到端配置

| 配置                | World alignment                                                      | Admission                    | Temporal output                                                  | Lifecycle / loss                                        |
| ------------------- | -------------------------------------------------------------------- | ---------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------- |
| `Arrival-Hold`    | 到达时刻复合，用`FramePoseHistory.TryGetLatest` 的最新 camera pose | 只做有限矩阵和基础合法性检查 | `ConstantVelocityModel` + `RawPassthroughStrategy`，零阶保持 | 保持最后有效位姿，禁用 VCD gate、StaticLock、低分重获取 |
| `Capture-Hold`    | 采集时刻复合，用`frame_id` 回查 image-time proxy camera pose       | 只做有限矩阵和基础合法性检查 | `ConstantVelocityModel` + `RawPassthroughStrategy`，零阶保持 | 保持最后有效位姿，禁用 VCD gate、StaticLock、低分重获取 |
| `One-Euro Anchor` | 采集时刻复合                                                         | 基本有效性检查               | `OneEuroModel` + `RawPassthroughStrategy`，滤波后保持        | 短时保持，超时后重新初始化；禁用 VCD gate 与 StaticLock |
| `EgoAnchor`       | 采集时刻复合                                                         | VCD admission                | `KalmanModel` + `DelayedInterpStrategy(Hermite)`             | 启用 StaticLock、分级退化、重获取 fan-in                |

关键实现点：

- `Arrival-Hold` 必须实际驱动 anchor transform，不能只把 arrival-time raw 写进日志。
- `Arrival-Hold` 的 observation measurement time 使用 PoseResult 到达/处理时刻；`Capture-Hold`、`One-Euro Anchor` 和 `EgoAnchor` 使用 source frame 的 capture time。
- `Capture-Hold` 与 `Arrival-Hold` 除 world composition time 和 measurement time 外，其余配置保持相同。
- `One-Euro Anchor` 是基线，不启用 VCD admission 和 StaticLock。
- `EgoAnchor` 是完整系统，不与 Python 共享 mutable per-variant 状态；Python 感知流只采集一次。

### 2.2 实验二组件归因配置

| 配置                                     | 与完整 EgoAnchor 的唯一差异                                                                                                                                   |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `EgoAnchor`                            | 完整系统：capture-time alignment + VCD admission + Kalman--Hermite + StaticLock + lifecycle                                                                   |
| `EgoAnchor w/o capture-time alignment` | world alignment mode 改为 arrival-time；其余 VCD、Kalman--Hermite、StaticLock、lifecycle 保持完整                                                             |
| `EgoAnchor w/o VCD`                    | admission mode 改为 basic-validity；禁用 quality gate、trackingScoreFloor、low-score reacquire；其余 capture-time alignment、Kalman--Hermite、StaticLock 保持 |
| `EgoAnchor w/o temporal synthesis`     | temporal output 改为`ConstantVelocityModel` + `RawPassthroughStrategy`；其余 capture-time alignment、VCD admission、StaticLock、lifecycle 保持            |
| `EgoAnchor w/o StaticLock`             | `staticLockModule` 为空或 disabled；其余 capture-time alignment、VCD admission、Kalman--Hermite、lifecycle 保持                                             |

关键实现点：

- 每个 ablation 只能关闭一个机制；manifest 必须记录每个开关，QC 必须验证。
- `w/o VCD` 不等于低分继续触发 lifecycle；禁用 VCD 时不得由低分触发 Lost 或 server reacquire。
- `w/o temporal synthesis` 不是 One Euro；它是完整系统中只移除 Kalman--Hermite，保留 VCD 与 StaticLock 的零阶保持消融。
- `w/o capture-time alignment` 不复用 `Arrival-Hold` 作为 label，因为它仍带 VCD、Kalman--Hermite、StaticLock。

---

## 3. schema-v2 数据契约

### 3.1 目录和文件

每个 session 固定目录：

```text
EgoAnchor_Python/data/eval/<session_id>/
  manifest.json
  python_candidates.jsonl
  unity_reference.jsonl
  unity_admission.jsonl
  unity_render.jsonl
  events.jsonl
  audit_samples/
```

任何正式 reader 遇到下面旧文件作为主输入时必须报错：

- `session_manifest.json`
- `*_unity_capture.jsonl`
- `*_unity_output.jsonl`
- `*_python_runtime.jsonl`

### 3.2 `manifest.json`

必须包含：

- `schema_version: 2`
- `session_id`
- `object_id`
- `run_kind`: `smoke`、`calibration`、`formal`、`debug`
- `experiment_ids`
- `operator_id`
- `created_unix_ms`
- `unity_run_mode`
- `python_host`
- `unity_version`
- `python_version`
- `egoanchor_git_commit`
- `protocol_version`
- `config_hash`
- `frozen_parameter_set_id`
- `object_model_id`
- `variant_definitions`
- `trial_plan`
- `log_files`
- `log_writer_stats`

`log_writer_stats` 必须按文件列出 dropped rows。formal session 中所有 dropped rows 必须为 0。

### 3.3 `python_candidates.jsonl`

每行是一条 Python candidate 或失败 candidate。必须包含：

- `schema_version`
- `event: "python_candidate"`
- `session_id`
- `frame_id`
- `candidate_id`
- `server_receive_mono_ms`
- `server_publish_mono_ms`
- `has_pose`
- camera-space pose：`pose_matrix_cv_camera`、`pose_tx_m`、`pose_ty_m`、`pose_tz_m`、`pose_qx`、`pose_qy`、`pose_qz`、`pose_qw`
- `pose_source`
- `phase`
- `stage`
- `failure_reason`
- VCD：`vcd_score`、`visibility_score`、`geometry_core_score`、`color_projection_score`、`depth_alignment_score`、`depth_abs_score`、`depth_struct_score`、`depth_alpha`
- render diagnostics：`render_quality_*`
- timing diagnostics：`total_ms`、`yolo_ms`、`depth_ms`、`cutie_ms`、`pose_ms`

### 3.4 `unity_reference.jsonl`

每行是一帧 Unity 采集/发送时刻 reference。必须包含：

- `schema_version`
- `event: "unity_reference"`
- `session_id`
- `frame_id`
- `capture_mono_ms`
- `capture_unix_ms`
- `capture_unity_frame`
- `sender_mono_ms`
- `sender_unity_frame`
- `image_time_basis: "camera_pose_history_proxy"`
- `image_time_offset_frames`
- `publish_attempt_mono_ms`
- `publish_succeeded`
- `head_pos`、`head_rot`
- `cam_valid`、`camera_reference`、`cam_pos`、`cam_rot`
- `reference_pose_valid`
- `reference_pose_source`
- `reference_pose_fresh`
- `reference_pose_keep_alive`
- `reference_pose_fresh_age_ms`
- `reference_pos`
- `reference_rot`

字段名使用 `reference_*`，不使用 `gt_*` 作为正式 schema 字段。

### 3.5 `unity_admission.jsonl`

每行是一条 candidate × variant 的 runtime 处理结果。必须包含：

- `schema_version`
- `event: "unity_admission"`
- `session_id`
- `candidate_id`
- `frame_id`
- `variant_id`
- `variant_label`
- `experiment_id`
- `scenario_id`
- `trial_id`
- `event_id`
- `unity_pose_handle_mono_ms`
- `unity_frame`
- `world_alignment_mode`
- `uses_capture_time_alignment`
- `source_capture_mono_ms`
- `source_capture_unity_frame`
- `has_aligned_raw`
- `aligned_raw_pos`
- `aligned_raw_rot`
- `has_arrival_time_raw`
- `arrival_time_raw_pos`
- `arrival_time_raw_rot`
- `arrival_time_raw_mono_ms`
- `uses_vcd_admission`
- `vcd_score`
- `quality_gate`
- `admission_decision`
- `policy_action`
- `policy_reason`
- `anchor_state`
- `motion_model`
- `smoothing_strategy`
- `uses_temporal_synthesis`
- `uses_static_lock`
- `config_hash`

### 3.6 `unity_render.jsonl`

每行是一条 render tick × variant 的长表记录。必须包含：

- `schema_version`
- `event: "unity_render"`
- `session_id`
- `render_tick_id`
- `render_mono_ms`
- `render_unix_ms`
- `render_unity_frame`
- `variant_id`
- `variant_label`
- `experiment_id`
- `scenario_id`
- `trial_id`
- `event_id`
- `condition_id`
- `head_pos`、`head_rot`
- `reference_pose_valid`
- `reference_pose_source`
- `reference_pose_fresh`
- `reference_pose_keep_alive`
- `reference_pose_fresh_age_ms`
- `reference_pos`
- `reference_rot`
- `reference_linear_speed_m_s`
- `reference_angular_speed_deg_s`
- `source_frame_id`
- `has_output_pose`
- `output_pos`
- `output_rot`
- `has_display_pose`
- `display_pos`
- `display_rot`
- `anchor_state`
- `policy_action`
- `policy_reason`
- `observation_age_ms`
- `policy_output_target_mono_ms`
- `smoothing_delay_ms`
- `latest_static_locked`
- `latest_accepted_score`
- `quality_gate`
- `motion_model`
- `smoothing_strategy`
- `config_hash`

### 3.7 `events.jsonl`

每行是 session/runtime/event marker。必须包含：

- `schema_version`
- `event`
- `event_type`
- `session_id`
- `source`
- `created_unix_ms`
- `mono_ms`
- `unity_frame`
- `severity`
- `experiment_id`
- `scenario_id`
- `trial_id`
- `event_id`
- `variant_id`
- `message`
- `payload`

---

## 4. 任务分解

### Task 1: 删除旧 RQ 入口并建立新命名边界

**Files:**

- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/`
- Delete: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ2/`
- Delete: `EgoAnchor_Unity/Assets/Scene/EgoAnchor-RQ1.unity`
- Delete: `EgoAnchor_Unity/Assets/Scene/EgoAnchor-RQ2.unity`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/research/`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq1_analyze.py`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq1_plot.py`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_analyze.py`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_plot.py`
- Delete: `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_response.py`
- Modify: `EgoAnchor_Unity/Assets/Tests/EditMode/EvalUiTests.cs`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/README.md`

**Interfaces:**

- Consumes: 当前 AGENTS.md 的系统论文路线。
- Produces: 代码层不再存在 RQ namespace/import/scene 作为正式入口。

- [ ] **Step 1: 写删除防回归测试**

  在 Python eval 测试中新增 `test_no_legacy_rq_paths.py`，检查正式包路径不存在。测试内容直接断言旧目录和旧模块不可用。

  Expected assertions:

  ```python
  from pathlib import Path
  import importlib.util

  ROOT = Path(__file__).resolve().parents[3]

  def test_legacy_rq_eval_packages_are_removed():
      eval_root = ROOT / "egoanchor" / "eval"
      assert not (eval_root / "research" / "rq1").exists()
      assert not (eval_root / "research" / "rq2").exists()
      assert not (eval_root / "research" / "rq3").exists()
      assert importlib.util.find_spec("egoanchor.eval.research.rq1") is None
      assert importlib.util.find_spec("egoanchor.eval.research.rq2") is None
  ```
- [ ] **Step 2: 删除 Unity RQ scripts 和 scenes**

  删除 RQ1/RQ2 目录与场景，不创建 alias，不添加 `FormerlySerializedAs`。
- [ ] **Step 3: 删除 Python RQ packages 和 tests**

  删除 `eval/research/` 下旧 RQ 包与旧 RQ tests。
- [ ] **Step 4: 重写 README 顶层说明**

  `EgoAnchor_Python/src/egoanchor/eval/README.md` 只说明 schema-v2、实验一、实验二、Run 1/Run 2 边界，不出现旧命令。
- [ ] **Step 5: 验证没有旧 namespace 编译依赖**

  Run:

  ```powershell
  dotnet build "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore
  pixi run python -m compileall src
  pixi run python -m unittest discover -s src -p "test_*.py" -t src
  ```

  Expected: Unity build 不再报 RQ namespace 缺失；Python 测试中 `test_legacy_rq_eval_packages_are_removed` 通过。

### Task 2: 建立 schema-v2 Python 契约

**Files:**

- Create: `EgoAnchor_Python/src/egoanchor/eval/schema_v2/__init__.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/schema_v2/paths.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/schema_v2/rows.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/schema_v2/writers.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/schema_v2/readers.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/schema_v2/qc.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_schema_v2_paths.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_schema_v2_reader.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_schema_v2_writer.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_schema_v2_qc.py`

**Interfaces:**

- Produces: `EvalV2Paths.for_session(session_dir)`, `load_session_v2(session_dir)`, `JsonlTableWriter`, `run_schema_qc(session)`。
- Later tasks depend on: fixed filenames and old schema rejection.

- [ ] **Step 1: 写 path contract 测试**

  Test must assert exact filenames:

  ```python
  def test_schema_v2_paths_are_fixed(tmp_path):
      paths = EvalV2Paths.for_session(tmp_path / "s01")
      assert paths.manifest.name == "manifest.json"
      assert paths.python_candidates.name == "python_candidates.jsonl"
      assert paths.unity_reference.name == "unity_reference.jsonl"
      assert paths.unity_admission.name == "unity_admission.jsonl"
      assert paths.unity_render.name == "unity_render.jsonl"
      assert paths.events.name == "events.jsonl"
      assert paths.audit_samples.name == "audit_samples"
  ```
- [ ] **Step 2: 写 reader 拒绝旧 schema 测试**

  构造只有 `session_manifest.json` 的 session 目录，`load_session_v2` 必须抛 `SchemaV2Error`，错误信息含 `schema-v2 requires manifest.json`。
- [ ] **Step 3: 写 writer 禁止旧字段测试**

  给 writer 输入包含 `rq1_metric` 或 `rq2_trial_id` 的 dict，必须抛 `SchemaV2Error`。
- [ ] **Step 4: 实现 rows/dataclasses**

  `rows.py` 定义：

  - `SCHEMA_VERSION = 2`
  - `LEGACY_FIELD_PREFIXES = ("rq1_", "rq2_")`
  - `ManifestV2`
  - `PythonCandidateRow`
  - `UnityReferenceRow`
  - `UnityAdmissionRow`
  - `UnityRenderRow`
  - `EventRow`
  - `SchemaV2Error`
- [ ] **Step 5: 实现 writer/reader/QC**

  `readers.py` 只读固定文件；不自动 glob。`qc.py` 检查 session_id 一致、schema_version 为 2、文件齐全、dropped rows 为 0、render tick × variant 完整。
- [ ] **Step 6: 验证**

  Run:

  ```powershell
  cd EgoAnchor_Python
  pixi run python -m unittest egoanchor.eval.tests.test_schema_v2_paths egoanchor.eval.tests.test_schema_v2_reader egoanchor.eval.tests.test_schema_v2_writer egoanchor.eval.tests.test_schema_v2_qc -v
  ```

  Expected: 新 schema-v2 contract tests 全部通过。

### Task 3: Python runtime 写 schema-v2 candidate 和 event

**Files:**

- Modify: `EgoAnchor_Python/src/egoanchor/runtime/eval_session.py`
- Modify: `EgoAnchor_Python/src/egoanchor/runtime/runtime_log_writer.py`
- Modify: `EgoAnchor_Python/src/egoanchor/diagnostics/runtime_event_log.py`
- Modify: `EgoAnchor_Python/src/egoanchor/runtime/tracking_runtime.py`
- Test: `EgoAnchor_Python/src/egoanchor/tests/test_eval_session_coordinator.py`
- Test: `EgoAnchor_Python/src/egoanchor/tests/test_runtime_event_logger.py`
- Test: `EgoAnchor_Python/src/egoanchor/tests/test_pose_log_factory.py`

**Interfaces:**

- Consumes: `EvalV2Paths` and `JsonlTableWriter` from Task 2。
- Produces: Python writes `python_candidates.jsonl` and `events.jsonl` into session directory.

- [ ] **Step 1: 更新 eval session 测试**

  测试 Python session 创建后包含 `python_session.json` 或 manifest fragment，并声明 schema-v2 文件名。旧 `<session_id>_python_runtime.jsonl` 不再出现。
- [ ] **Step 2: 实现 candidate row mapping**

  从 `PoseObservation` 和 render diagnostics 映射到 `PythonCandidateRow`。必须写出：

  - `candidate_id = f"{session_id}:{frame_id}:{candidate_seq}"`
  - camera-space pose
  - `vcd_score`
  - `visibility_score`
  - `geometry_core_score`
  - `color_projection_score`
  - `depth_alignment_score`
  - `depth_abs_score`
  - `depth_struct_score`
  - `depth_alpha`
- [ ] **Step 3: 保留颜色不可用语义**

  当 `color_reprojection < 0` 时，candidate 行写 `color_projection_score = null` 或 `NaN`，同时 `reliability_flags` 包含颜色不可用原因；不得把它算成坏 pose。
- [ ] **Step 4: 拆分 events**

  status、heartbeat、command、runtime_error 写 `events.jsonl`，pose candidate 不再混入 events。
- [ ] **Step 5: 验证**

  Run:

  ```powershell
  cd EgoAnchor_Python
  pixi run python -m unittest egoanchor.tests.test_eval_session_coordinator egoanchor.tests.test_runtime_event_logger egoanchor.tests.test_pose_log_factory -v
  pixi run python -m compileall src
  ```

  Expected: Python runtime tests 通过，compileall 通过。

### Task 4: Unity world alignment mode，让 Arrival-Hold 成为真实变体

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/WorldAlignmentMode.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/CameraPoseFrameAligner.cs`
- Test: `EgoAnchor_Unity/Assets/Tests/EditMode/AnchorPolicyHostTests.cs`
- Test: `EgoAnchor_Unity/Assets/Tests/EditMode/EvalUiTests.cs` or new `RuntimeAlignmentTests.cs`

**Interfaces:**

- Produces: `PoseToAnchorRuntime` serialized field `worldAlignmentMode` with values `CaptureTime` and `ArrivalTime`。
- Later tasks depend on: exact variant semantics for `Arrival-Hold` and `EgoAnchor w/o capture-time alignment`。

- [ ] **Step 1: 写 alignment mode 测试**

  构造两条 camera pose history：source frame camera pose 和 latest camera pose 不同。输入同一个 camera-space pose：

  - `CaptureTime` 输出应使用 source frame camera pose。
  - `ArrivalTime` 输出应使用 latest camera pose。
- [ ] **Step 2: 新增 enum**

  `WorldAlignmentMode.cs`:

  ```csharp
  namespace EgoAnchor.Runtime
  {
      /// <summary>camera-space pose 复合到 Unity world 时使用的参考时刻。</summary>
      public enum WorldAlignmentMode
      {
          /// <summary>用 PoseResult.frame_id 对应的图像采集时刻 camera pose。</summary>
          CaptureTime = 0,
          /// <summary>用 PoseResult 到达 Unity 时最新可用的 camera pose。</summary>
          ArrivalTime = 1,
      }
  }
  ```
- [ ] **Step 3: 修改 `PoseToAnchorRuntime.AcceptPoseResult`**

  - `CaptureTime` 调用 `aligner.TryAlign(result, out worldPose, out usedReference)`。
  - `ArrivalTime` 调用 `aligner.TryAlignWithLatestCameraPose(result, out worldPose, out usedReference, out record)`。
  - `ArrivalTime` 的 observation measurement time 使用 `now`。
  - `CaptureTime` 的 observation measurement time 使用 `ResolveCaptureTimeSeconds(frameId)`。
  - 两种模式都继续记录 arrival raw 诊断，但只有 `ArrivalTime` 把 arrival raw 作为 runtime 输入。
- [ ] **Step 4: 在 runtime public API 暴露配置摘要**

  增加：

  - `public string WorldAlignmentModeName => worldAlignmentMode.ToString();`
  - `public bool UsesCaptureTimeAlignment => worldAlignmentMode == WorldAlignmentMode.CaptureTime;`
- [ ] **Step 5: 验证**

  Run:

  ```powershell
  dotnet build "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore
  dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
  ```

  Expected: runtime alignment tests 通过，Unity C# 编译通过。

### Task 5: Unity schema-v2 session、reference、admission、render 日志

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalSession.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalRecorder.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalJson.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalV2Manifest.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalAdmissionSnapshot.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalRenderSnapshot.cs`
- Test: `EgoAnchor_Unity/Assets/Tests/EditMode/EvalUiTests.cs`

**Interfaces:**

- Consumes: `WorldAlignmentMode` from Task 4。
- Produces: Unity writes `manifest.json`、`unity_reference.jsonl`、`unity_admission.jsonl`、`unity_render.jsonl`、`events.jsonl`。

- [ ] **Step 1: 写 JSON contract tests**

  测试 `EvalJson.BuildReferenceLine`、`BuildAdmissionLine`、`BuildRenderLine`：

  - 含 `schema_version:2`
  - 不含 `rq1_`、`rq2_`、`gt_`
  - `unity_render` 是单 variant 长表行，不内嵌 `variants` 数组
- [ ] **Step 2: 重写 `EvalSession.StartSession`**

  输出文件固定为：

  - `unity_reference.jsonl`
  - `unity_admission.jsonl`
  - `unity_render.jsonl`
  - `events.jsonl`
  - `manifest.json`

  若目标文件已有非空内容，拒绝启动，防止覆盖。
- [ ] **Step 3: 重写 reference logging**

  原 `unity_capture` 改为 `unity_reference`。字段名从 `gt_*` 改为 `reference_*`。
- [ ] **Step 4: 实现 admission logging**

  `PoseToAnchorRuntime` 在处理每条 PoseResult 后产生 `EvalAdmissionSnapshot`。`EvalRecorder` 订阅所有 variants 的 snapshot 并写 `unity_admission.jsonl`。
- [ ] **Step 5: 重写 render logging**

  `LateUpdate` 中对每个 variant 写一行 `unity_render`。`has_output_pose` 来自 runtime，`has_display_pose` 来自 `DynamicObjectAnchor` 或实际显示 Transform 状态。
- [ ] **Step 6: 写 manifest**

  `manifest.json` 包含 schema-v2 文件名、variant definitions、trial plan、config hash 和 dropped rows。停止 session 时写入，不写旧 `session_manifest.json`。
- [ ] **Step 7: 验证**

  Run:

  ```powershell
  dotnet build "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore
  dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
  ```

  Expected: JSON contract tests 通过；构建不出现 RQ namespace 或旧 manifest 字段。

### Task 6: 新实验上下文 UI 和输入处理

**Files:**

- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/Experiment/ExperimentId.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/Experiment/ExperimentScenario.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/Experiment/ExperimentTrialSelector.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/Experiment/ExperimentInputHandler.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/Experiment/ExperimentStatusUI.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalStatusText.cs`
- Test: `EgoAnchor_Unity/Assets/Tests/EditMode/EvalUiTests.cs`

**Interfaces:**

- Produces: `CurrentExperimentId`、`CurrentScenarioId`、`CurrentTrialId`、`CurrentEventId`、`CurrentConditionId`。
- Consumed by: `EvalRecorder` render/admission/event rows。

- [ ] **Step 1: 写输入测试**

  - 不使用 InputActionAsset；手柄选场、开始、事件、结束、作废和键盘任务键均为 Inspector 内联
    `InputAction`。
  - 右手摇杆按 3×3 九宫格选场；A 开始、扳机标记、B 结束、摇杆按下作废。
  - 键盘 `1`--`9` 各自负责一项任务及其 marker，`Enter` 结束，`Backspace` 作废。
  - 运行中不得切场；输入回中前不得重复跨格；未 recording 时不得创建 trial context。
- [ ] **Step 2: 实现 selector**

  Selector 独立维护九项任务的 selected、running 和 completed 状态，不直接写文件。场景可任意顺序完成；
  活动或已完成 trial 可写 `trial_rejected` 后只重做该项。空闲且至少完成一项时，额外确认即可停止当前
  模块化 session，不强制一次跑完九项。
- [ ] **Step 3: 实现 status UI**

  UI 显示九任务状态板、本 session 已完成任务编号、当前选择、phase、trial/phase 计时、90--120 秒范围
  和下一合法动作。使用实验一/实验二命名，不出现 RQ。Canvas 保持场景中的固定 world-space 位置。
- [ ] **Step 4: 验证**

  Run:

  ```powershell
  dotnet build "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore
  ```

  Expected: 内联 Action GUID 唯一，四方向选场与作废重做状态正确，输入回调不累积；未录制时 trial
  context 保持空。

### Task 7: Unity policy 配置摘要与四系统配置/消融场景

**Files:**

- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Smoothing/RawPassthroughStrategy.cs`
- Create/Modify: `EgoAnchor_Unity/Assets/Scene/EgoAnchor-Experiment12.unity`
- Test: `EgoAnchor_Unity/Assets/Tests/EditMode/EvalUiTests.cs`

**Interfaces:**

- Produces: scene-level configured variants and manifest-readable component flags。

- [ ] **Step 1: 移除 RQ tooltip 和 summary 文案**

  `AnchorPolicyHost`、`RawPassthroughStrategy` 等注释和 Tooltip 中的 RQ2 文案改成系统配置文案。
- [ ] **Step 2: 增加 component flags**

  `AnchorPolicyHost` 暴露：

  - `UsesVcdAdmission`
  - `UsesTemporalSynthesis`
  - `UsesStaticLock`
  - `UsesLowScoreReacquire`
  - `UsesServerReacquire`
- [ ] **Step 3: 创建正式实验场景**

  `EgoAnchor-Experiment12.unity` 配置八个唯一 runtime 变体；完整 `EgoAnchor` 由两个实验共享：

  实验一：

  - `Arrival-Hold`
  - `Capture-Hold`
  - `One-Euro Anchor`
  - `EgoAnchor`

  实验二：

  - `EgoAnchor w/o capture-time alignment`
  - `EgoAnchor w/o VCD`
  - `EgoAnchor w/o temporal synthesis`
  - `EgoAnchor w/o StaticLock`

  其中完整 `EgoAnchor` 可被实验一和实验二共享同一个 runtime，manifest 中以 variant_id 区分实验用途。
- [ ] **Step 4: 场景契约测试**

  测试 YAML 中：

  - 不存在 `EgoAnchor-RQ1`、`EgoAnchor-RQ2` 引用。
  - `EvalRecorder` variants 含所有 required labels。
  - `AnchorRuntimeHub` 注册所有 active runtime。
  - 只有完整 EgoAnchor 或需要完整 lifecycle 的消融允许 `emitServerReacquire=1`，shadow baselines 不发 server reacquire。
- [ ] **Step 5: 验证**

  Run:

  ```powershell
  dotnet build "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore
  dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
  ```

  Expected: scene contract tests 通过。

### Task 8: Python schema-v2 reader/QC 接入 Unity logs

**Files:**

- Modify: `EgoAnchor_Python/src/egoanchor/eval/schema_v2/readers.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/schema_v2/qc.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_schema_v2_reader.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_schema_v2_qc.py`

**Interfaces:**

- Consumes: schema-v2 files produced by Tasks 3 and 5。
- Produces: `EvalSessionV2` with normalized DataFrames。

- [ ] **Step 1: 写 fixture session**

  在测试内构造最小 schema-v2 session：2 frames、2 variants、2 render ticks，包含 reference/admission/render/events。
- [ ] **Step 2: 实现 normalized loading**

  `load_session_v2` 返回：

  - `manifest`
  - `python_candidates`
  - `unity_reference`
  - `unity_admission`
  - `unity_render`
  - `events`
- [ ] **Step 3: 实现 joins**

  提供：

  - `join_candidate_admission(session)`
  - `join_render_reference(session)`
  - `select_trials(session, experiment_id)`
- [ ] **Step 4: 实现 QC**

  必查：

  - 文件齐全
  - `schema_version == 2`
  - `session_id` 一致
  - fixed variants 完整
  - render tick × variant 完整
  - dropped rows 为 0
  - 无 `rq1_`、`rq2_` 字段
  - formal session config hash 已冻结
- [ ] **Step 5: 验证**

  Run:

  ```powershell
  cd EgoAnchor_Python
  pixi run python -m unittest egoanchor.eval.tests.test_schema_v2_reader egoanchor.eval.tests.test_schema_v2_qc -v
  ```

  Expected: reader/QC 测试通过。

### Task 9: 迁移 RQ 中性指标到 schema-v2

**Files:**

- Modify: `EgoAnchor_Python/src/egoanchor/eval/metrics/anchor_error.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/metrics/jitter.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/metrics/latency.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/metrics/recovery.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/metrics/diagnostics.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/metrics/pipeline.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_metrics_common.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_jitter.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_diagnostics.py`

**Interfaces:**

- Consumes: `unity_render` long table and `unity_reference`。
- Produces: per trial/event/variant metrics tables。

- [ ] **Step 1: 写 display/output 区分测试**

  构造一行 `has_output_pose=false` 但 `has_display_pose=true` 的 hold-last render row。误差计算使用 display pose；availability 计算 output pose。
- [ ] **Step 2: 实现 display error**

  输出：

  - `translation_error_mm_median`
  - `translation_error_mm_iqr`
  - `translation_error_mm_p95`
  - `rotation_error_deg_median`
  - `rotation_error_deg_iqr`
  - `rotation_error_deg_p95`
- [ ] **Step 3: 实现 static metrics**

  静止段同时报告：

  - HP-RMS
  - absolute error
  - drift

  防止“冻结错误位姿”在 jitter 指标上虚假获胜。
- [ ] **Step 4: 实现 transition metrics**

  起停/转换段至少输出：

  - visible response time
  - unlock/relock
  - peak error
  - settling time
- [ ] **Step 5: 实现 occlusion/recovery metrics**

  遮挡恢复段输出：

  - output availability
  - display availability
  - jump P95
  - recovery success
  - recovery time
- [ ] **Step 6: 实现 latency diagnostics**

  输出：

  - `observation_age_ms`
  - `smoothing_delay_ms`
  - candidate arrival/processing latency
  - visual perception frequency
  - render frequency
- [ ] **Step 7: 验证**

  Run:

  ```powershell
  cd EgoAnchor_Python
  pixi run python -m unittest egoanchor.eval.tests.test_metrics_common egoanchor.eval.tests.test_jitter egoanchor.eval.tests.test_diagnostics -v
  ```

  Expected: 指标测试通过，所有输出表名不含 RQ。

### Task 10: 实验一分析包

**Files:**

- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/contract.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/qc.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/metrics.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/analysis.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/figures.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/latex.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp1_system_characterization/cli.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_exp1_system_characterization_analysis.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_exp1_system_characterization_figures.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_exp1_system_characterization_latex.py`

**Interfaces:**

- Produces: `run_exp1_system_characterization(session_dirs, output_dir, config)`。

- [ ] **Step 1: 写 contract**

  `contract.py` 固定：

  ```python
  EXPERIMENT_ID = "exp1_system_characterization"
  VARIANTS = ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", "EgoAnchor")
  SCENARIOS = (
      "static_head_motion",
      "start_stop_6dof",
      "continuous_translation",
      "continuous_rotation",
      "occlusion_recovery",
  )
  ```
- [ ] **Step 2: 写 QC 测试**

  单 session 只检查其实际完成任务的 variant、reference coverage 和 render tick 配对；多个 session 的场景
  并集必须覆盖五类场景。批次缺场景、重复 session id 或冻结配置漂移时必须 fail。
- [ ] **Step 3: 实现 analysis 输出表**

  生成：

  - `exp1_session_qc.csv`
  - `exp1_trial_qc.csv`
  - `exp1_trial_metrics.csv`
  - `exp1_paired_trial_metrics.csv`
  - `exp1_condition_summary.csv`
  - `exp1_static_quality.csv`
  - `exp1_transition_response.csv`
  - `exp1_occlusion_recovery.csv`
  - `exp1_latency_summary.csv`
  - `exp1_vcd_diagnostics.csv`
- [ ] **Step 4: 实现 figures**

  输出 PDF：

  - `exp1_static_timeline.pdf`
  - `exp1_motion_timeline.pdf`
  - `exp1_occlusion_recovery.pdf`
  - `exp1_system_summary.pdf`

  图中 categorical hue 顺序固定为 `Arrival-Hold`、`Capture-Hold`、`One-Euro Anchor`、`EgoAnchor`，不得按排序结果换色。
- [ ] **Step 5: 实现 LaTeX 输出**

  输出：

  - `2026-EgoAnchor/generated/exp1_numbers.tex`
  - `2026-EgoAnchor/generated/exp1_tables.tex`

  macro 前缀使用 `\EAExpOne...`，不含 RQ。
- [ ] **Step 6: 验证**

  Run:

  ```powershell
  cd EgoAnchor_Python
  pixi run python -m unittest egoanchor.eval.tests.test_exp1_system_characterization_analysis egoanchor.eval.tests.test_exp1_system_characterization_figures egoanchor.eval.tests.test_exp1_system_characterization_latex -v
  ```

  Expected: 使用合成 schema-v2 fixture 能生成所有 CSV、PDF 占位图和 LaTeX 宏文件。

### Task 11: 实验二分析包

**Files:**

- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/contract.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/qc.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/metrics.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/analysis.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/figures.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/latex.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/experiments/exp2_design_attribution/cli.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_exp2_design_attribution_analysis.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_exp2_design_attribution_qc.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_exp2_design_attribution_figures.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_exp2_design_attribution_latex.py`

**Interfaces:**

- Produces: `run_exp2_design_attribution(session_dirs, output_dir, config)`。

- [ ] **Step 1: 写 contract**

  `contract.py` 固定：

  ```python
  EXPERIMENT_ID = "exp2_design_attribution"
  BASELINE_VARIANT = "EgoAnchor"
  ABLATION_VARIANTS = (
      "EgoAnchor w/o capture-time alignment",
      "EgoAnchor w/o VCD",
      "EgoAnchor w/o temporal synthesis",
      "EgoAnchor w/o StaticLock",
  )
  REQUIRED_VARIANTS = (BASELINE_VARIANT,) + ABLATION_VARIANTS
  ```
- [ ] **Step 2: 写 single-component QC 测试**

  每个 ablation 的 manifest flags 与 EgoAnchor 比较只能有一个组件差异；多于一个差异必须 fail。单 session
  可只包含部分归因任务，批次并集必须覆盖四个归因场景。
- [ ] **Step 3: 实现 paired delta**

  以 `session_id × scenario_id × trial_id × event_id` 配对完整 EgoAnchor 和每个 ablation，输出：

  - `metric_value_full`
  - `metric_value_ablation`
  - `delta_ablation_minus_full`
  - `paired_n`
- [ ] **Step 4: 实现 VCD risk-coverage 诊断**

  只作为实验二评分风险判别性诊断，输出 `exp2_vcd_risk_coverage.csv` 和 AURC 数字。文案不称 VCD 为排序算法。
- [ ] **Step 5: 实现 figures**

  输出 PDF：

  - `exp2_component_delta.pdf`
  - `exp2_alignment_effect.pdf`
  - `exp2_temporal_synthesis_effect.pdf`
  - `exp2_static_lock_tradeoff.pdf`
  - `exp2_vcd_risk_coverage.pdf`
- [ ] **Step 6: 实现 LaTeX 输出**

  输出：

  - `2026-EgoAnchor/generated/exp2_numbers.tex`
  - `2026-EgoAnchor/generated/exp2_tables.tex`

  macro 前缀使用 `\EAExpTwo...`，不含 RQ。
- [ ] **Step 7: 验证**

  Run:

  ```powershell
  cd EgoAnchor_Python
  pixi run python -m unittest egoanchor.eval.tests.test_exp2_design_attribution_analysis egoanchor.eval.tests.test_exp2_design_attribution_qc egoanchor.eval.tests.test_exp2_design_attribution_figures egoanchor.eval.tests.test_exp2_design_attribution_latex -v
  ```

  Expected: 使用合成 schema-v2 fixture 能生成所有 CSV、PDF 占位图和 LaTeX 宏文件。

### Task 12: 分析 CLI、批处理和论文产物目录

**Files:**

- Create: `EgoAnchor_Python/src/egoanchor/eval/cli.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/__init__.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/paper/latex.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/paper/figures.py`
- Test: `EgoAnchor_Python/src/egoanchor/eval/tests/test_eval_cli.py`

**Interfaces:**

- Produces CLI:
  - `python -m egoanchor.eval.cli qc <session_dir>`
  - `python -m egoanchor.eval.cli analyze-exp1 <session_dir...> --out <out_dir>`
  - `python -m egoanchor.eval.cli analyze-exp2 <session_dir...> --out <out_dir>`

- [ ] **Step 1: 写 CLI 测试**

  用合成 session 调用 `main([...])`，验证输出文件存在。
- [ ] **Step 2: 实现 CLI**

  不保留旧 `run_eval`、`batch_eval` 命令别名。
- [ ] **Step 3: 固定论文输出路径**

  默认输出到：

  - `2026-EgoAnchor/generated/`
  - `2026-EgoAnchor/figures/generated/`
- [ ] **Step 4: 验证**

  Run:

  ```powershell
  cd EgoAnchor_Python
  pixi run python -m unittest egoanchor.eval.tests.test_eval_cli -v
  ```

  Expected: CLI 测试通过，旧命令不存在。

### Task 13: Run 1 smoke session 与采集手册

**Files:**

- Create: `2026-EgoAnchor/experiment_1_2_collection_manual_zh.md`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/README.md`
- Modify: `2026-EgoAnchor/egoanchor_cn_v6.tex` only if generated file paths need stable include stubs

**Interfaces:**

- Produces: 用户可手动执行 smoke 与 formal 采集的中文流程。

- [ ] **Step 1: 写 smoke checklist**

  手册必须包含：

  - Python 启动命令
  - Unity 场景名
  - NATS/ZMQ 连接检查
  - session 自动配对检查
  - 手柄选场/开始/标记/结束/作废与键盘任务键 smoke 操作
  - 九任务状态、90--120 秒计时和单任务 rejected 重做检查
  - 任意任务子集结束 session、`completed_tasks` 摘要与多 session 批次覆盖检查
  - 停止 session 后文件检查
  - QC 命令
- [ ] **Step 2: 写实验一采集流程**

  包含五类 scenario 的动作说明、事件标记时机、失败重采规则。
- [ ] **Step 3: 写实验二采集流程**

  说明与实验一共用同一候选流和 reference，组件消融通过同场景多 runtime 同步驱动，不单独重跑 Python 感知。
- [ ] **Step 4: 写 formal 参数冻结规则**

  明确 calibration session 用于冻结 One Euro、VCD、Kalman--Hermite、StaticLock 和事件判定；formal
  session 后不得调参。Formal 场景不要求现场填写元数据，参数集标识由整体 config hash 自动生成。
- [ ] **Step 5: 验证手册命令与 CLI 名称一致**

  Run:

  ```powershell
  cd EgoAnchor_Python
  pixi run python -m compileall src
  ```

  Expected: CLI module 可编译，手册中的 module path 与实际代码一致。

### Task 14: 端到端轻量验证门禁

**Files:**

- Modify: `AGENTS.md` only if verification commands change
- No new source files unless previous tasks require small test fixtures

**Interfaces:**

- Produces: Run 1 交付前的最小证据集。

- [ ] **Step 1: Unity 编译验证**

  Run:

  ```powershell
  dotnet build "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore
  dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
  ```

  Expected: exit 0。
- [ ] **Step 2: Python 编译与测试验证**

  Run:

  ```powershell
  cd EgoAnchor_Python
  pixi run python -m compileall src
  pixi run python -m unittest discover -s src -p "test_*.py" -t src
  ```

  Expected: exit 0。
- [ ] **Step 3: 旧命名扫描**

  扫描规则：生产代码中不得出现新的 RQ namespace、schema 字段或 CLI；允许计划文件和删除说明中提到旧名。

  Expected forbidden in source runtime/eval code:

  - `EgoAnchor.Eval.RQ1`
  - `EgoAnchor.Eval.RQ2`
  - `rq1_metric`
  - `rq2_trial_id`
  - `session_manifest.json`
  - `unity_capture`
  - `unity_output`
- [ ] **Step 4: 合成 schema-v2 分析验证**

  Run:

  ```powershell
  cd EgoAnchor_Python
  pixi run python -m egoanchor.eval.cli analyze-exp1 <synthetic_session_dir> --out <tmp_out>
  pixi run python -m egoanchor.eval.cli analyze-exp2 <synthetic_session_dir> --out <tmp_out>
  ```

  Expected: CSV、PDF、LaTeX files 生成，QC 通过。
- [ ] **Step 5: 论文编译验证**

  Run:

  ```powershell
  cd 2026-EgoAnchor
  latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
  ```

  Expected: exit 0。

---

## 5. Run 1 完成标准

Run 1 结束时必须满足：

1. Unity 和 Python 正式代码不再依赖旧 RQ1/RQ2 包、场景、selector、schema 字段或 CLI。
2. Python runtime 能写 `python_candidates.jsonl` 和 `events.jsonl`。
3. Unity runtime 能同步驱动四个实验一配置和四个实验二消融配置。
4. `Arrival-Hold` 是真实 runtime 输出，而不是诊断字段。
5. Unity session 输出 `manifest.json`、`unity_reference.jsonl`、`unity_admission.jsonl`、`unity_render.jsonl`、`events.jsonl`；manifest 的 `completed_tasks` 与最终未作废 trial 一致。
6. Python reader 只接受 schema-v2，遇到旧 schema 报错。
7. 实验一和实验二的 QC、analysis、figures、LaTeX 输出能在合成 fixture 上跑通，并支持多个模块化 session 在批次层补齐九项任务。
8. 中文采集手册清楚写出 smoke、calibration、formal session 的操作顺序和失败重采规则。
9. `AGENTS.md` 指向本计划和 schema-v2 当前事实。

## 6. Run 2 边界

Run 2 只在用户完成 smoke 与实验一/二正式采集后启动。Run 2 不重新设计 schema，不重新命名系统配置，不在 formal 数据后调参。Run 2 只做：

- 读取 formal schema-v2 sessions。
- 跑 QC；若 QC fail，只报告失败原因和需要重采的 trial/session。
- 生成实验一/二正式 CSV、图、LaTeX 数字。
- 回填 `2026-EgoAnchor/egoanchor_cn_v6.tex`。
- 编译论文。

## 7. 自检结果

- Spec coverage: 覆盖旧 RQ 删除、schema-v2、Unity 四配置、实验二组件消融、Python QC/分析/绘图/LaTeX、采集手册和验证命令。
- Placeholder scan: 本计划不使用未定义占位任务；每个任务给出明确文件、接口、步骤和验证命令。
- Type consistency: Unity variant names、Python experiment IDs、schema-v2 filenames 在全文保持一致。
- Scope check: 实验三只保留设计，不进入 Run 1 工程实现；本计划只覆盖实验一和实验二。
