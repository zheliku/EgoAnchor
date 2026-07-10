# RQ2 Dynamic Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留论文原 RQ2 与慢速平移、快速挥动、旋转三个场景，修复评估日志的时间和有效性语义，补齐 RQ2 试次记录与离线分析，并按代码事实改写 Typst 论文。

**Architecture:** Unity 继续拥有 frame history、world pose、GT 与渲染输出，新增明确的图像时间、pose handle 时间和 policy output target 时间；`EvalRecorder` 写真实输出有效性及 RQ2 试次上下文。Python 只消费 JSONL，按 source frame 与 trial 组织指标，不改变运行时感知链路。论文保留研究问题，仅重写错误的因果解释和未实测结论。

**Tech Stack:** C# / Unity / NUnit、Python 3.14 / numpy / pandas / unittest、Typst。

---

## Global Constraints

- 直接在当前分支改动，不创建 worktree，不提交用户未要求的 commit。
- 不修改 proto 或生成代码；Python 不生成 Unity world pose。
- Python 包外导入使用包级入口；新增代码提供充分中文说明。
- RQ1 `rq1_metric` 契约保持有效；RQ2 新字段不借用或恢复 RQ1 旧场景。
- 不把 arrival-time raw 用于物体 `v * tau` 主分析。
- 修改 eval schema 时同步 Unity writer、Python reader、测试、论文与 `AGENTS.md`。

## Task 1: Unity output 时间与有效性契约

**Files:**
- Modify: `EgoAnchor_Unity/Assets/Tests/EditMode/AnchorPolicyHostTests.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Smoothing/SmoothingStrategy.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Smoothing/DelayedInterpStrategy.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Smoothing/RawPassthroughStrategy.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Smoothing/BlendStrategy.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/Contracts/AnchorPolicyOutput.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Policy/AnchorPolicyHost.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/PoseToAnchorRuntime.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Runtime/DynamicObjectAnchor.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalRecorder.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalJson.cs`

- [x] **Step 1: 写失败测试**

新增测试：DelayedInterp 在 `now=10.5`、有效控制点覆盖目标时必须暴露 `OutputTargetTimeSeconds=now-NominalLatencySeconds`；无 policy 输出的 runtime 即使绑定 Transform，EvalRecorder snapshot 也必须 `HasOutputPose=false`。

- [x] **Step 2: 运行测试并确认失败**

Run: `dotnet test "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore`
Expected: 新断言因缺少 output target API / 当前 Transform 判定而失败。

- [x] **Step 3: 实现最小契约**

在 `SmoothingStrategy` 增加只读 `OutputTargetTimeSeconds`，由各策略在 `Output` 时更新。`AnchorPolicyOutput` 增加 `ObservationAgeSeconds`、`OutputTargetTimeSeconds`、`SmoothingDelaySeconds`。`PoseToAnchorRuntime` 暴露毫秒值；Eval snapshot 写：

```text
observation_age_ms
policy_output_target_mono_ms
smoothing_delay_ms
unity_pose_handle_mono_ms
```

`EvalRecorder.BuildSnapshots` 通过 `rt.TryGetOutputPose` 判定有效性，pose 值仍读取应用后的 `anchorTransform`。给 `EvalRecorder` 设置 `DefaultExecutionOrder(50)`，保持 runtime `-50`，DynamicObjectAnchor 明确为 `0`。

- [x] **Step 4: 测试转绿**

Run: `dotnet test "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore`
Expected: PASS。

## Task 2: Unity 图像语义时间

**Files:**
- Modify: `EgoAnchor_Unity/Assets/Tests/EditMode/AnchorPolicyHostTests.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Alignment/FramePoseHistory.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Quest/StereoFrameSource.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalRecorder.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalJson.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ1/RQ1LiveStats.cs`

- [x] **Step 1: 写失败测试**

验证 `FramePoseHistory.Record` 同时保存 `ImageMonoMs/ImageUnityFrame` 与 `SenderMonoMs/SenderUnityFrame`；延迟缓冲选择前一 sample 时，image 时间来自被选 sample，sender 时间是 JPEG 完成后的 payload-ready 时刻，publisher 另记紧邻 `TrySend` 的发布尝试。

- [x] **Step 2: 运行并确认失败**

Run: `dotnet test "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore`
Expected: `FramePoseRecord` 尚无双时间字段而失败。

- [x] **Step 3: 实现双时间记录**

`FramePoseRecord` 明确保存 image-time proxy 与 payload-ready 两套单调时间/Unity frame。policy measurement、source timing 和 RQ1 live latency 使用 proxy；协议 header 保持 payload-ready 时间。capture JSONL 另写 `image_time_basis`、`image_time_offset_frames`、`publish_attempt_mono_ms`、`publish_succeeded` 与 `gt_sample_mono_ms`，避免把代理时刻、编码完成、发布尝试和参考 pose 采样误称为同刻。

- [x] **Step 4: 测试转绿**

Run: `dotnet test "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore`
Expected: PASS。

## Task 3: Unity RQ2 trial 上下文

**Files:**
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ2/RQ2Condition.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ2/RQ2TrialSelector.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ2/RQ2InputHandler.cs`
- Create: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/RQ2/RQ2StatusUI.cs`
- Create: corresponding `.meta` files
- Create: `EgoAnchor_Unity/Assets/Scene/EgoAnchor-RQ2.unity`
- Create: `EgoAnchor_Unity/Assets/Scene/EgoAnchor-RQ2.unity.meta`
- Modify: `EgoAnchor_Unity/Assets/Tests/EditMode/AnchorPolicyHostTests.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalRecorder.cs`
- Modify: `EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Eval/EvalJson.cs`

- [x] **Step 1: 写失败测试**

测试 selector：按数字键后 trial id 与 condition 立即生效，按 `0` 后回到空闲，活跃试次拒绝重复 Start；阶段 API、空格输入和 `rq2_phase` 字段均不存在；`ToLogString` 输出 `slow_translation/fast_motion/rotation`。

- [x] **Step 2: 运行并确认失败**

Run: `dotnet test "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore`
Expected: RQ2 类型不存在而编译失败。

- [x] **Step 3: 实现 selector 与日志字段**

selector 只持有 `CurrentCondition/CurrentTrialId/TargetLinearSpeedMs/TargetAngularSpeedDegS`；InputHandler 提供三场景直接开始、结束和 F7/F8 会话控制。EvalRecorder 可选绑定 selector，并在每个 output 行写 `rq2_condition/rq2_trial_id/rq2_target_linear_speed_m_s/rq2_target_angular_speed_deg_s`。RQ2 场景接入独立 selector/input/status，并同步记录 *Full* 与被动 *Raw-ZOH* shadow runtime。

- [x] **Step 4: 测试源码通过程序集编译并编译主线**

Run: `dotnet test "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore`

Run: `dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore`

Expected: 两者 PASS。

状态：`EgoAnchor.Tests.csproj` 与 `Assembly-CSharp.csproj` 均构建成功；当前 `dotnet test` 只执行构建且未发现 NUnit 适配器，因此不把它记为 Unity Test Runner 的实际执行证据。RQ2 场景仍需在可用 Unity Editor 会话中打开并保存后运行 EditMode 测试。

## Task 4: Python schema 与 RQ2 指标

**Files:**
- Modify: `EgoAnchor_Python/src/egoanchor/eval/io/schemas.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/io/log_loader.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/metrics/latency.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/research/rq2/analyze.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/research/rq2/__init__.py`
- Modify: `EgoAnchor_Python/src/egoanchor/eval/tests/test_log_loader.py`
- Create: `EgoAnchor_Python/src/egoanchor/eval/tests/test_rq2_analyze.py`

- [x] **Step 1: 写失败 schema 测试**

最小日志含 RQ2 字段、双时间与 policy target；断言 loader 展平后保留这些字段，`condition` 优先使用有效 `rq2_condition`。

- [x] **Step 2: 写失败合成轨迹测试**

构造 1 m/s 平移和 90 deg/s 旋转、100 ms handle delay 的试次。断言：每个 source frame 只保留首次出现；沿运动方向时延位移约 0.1 m；旋转时延约 9 deg；Full 可用率包含无输出帧。

- [x] **Step 3: 运行并确认失败**

Run: `pixi run python -m unittest egoanchor.eval.tests.test_log_loader egoanchor.eval.tests.test_rq2_analyze`
Expected: 新字段/模块缺失而失败。

- [x] **Step 4: 实现 schema 与分析**

`core.py` 定义 `RQ2_CONDITIONS = ("slow_translation", "fast_motion", "rotation")`，并由包级入口显式导出：`build_source_observations(logs)` 构造 source-frame 表，`compute_motion_delay(source, output)` 计算参考运动暴露量与有符号 raw 滞后残差，`compute_trial_summary(output, source)` 汇总 trial 级误差、可用率、显示更新率、保持比例与 lag，`compute_model_summary(motion)` 生成 trial/场景模型统计，`run_rq2_analysis(session_dir, report_dir=None)` 写出报告表并返回表映射。`analyze.py` 只承担 CLI，避免 `python -m` 的重复导入 warning。

GT 在 image/handle/render 时间上通过 Unity output GT 轨迹插值，显式有效 segment 禁止跨失效空窗。旋转用世界系 SO(3) log，不用 Euler 差。pre-image 速度只用图像时刻前固定 400 ms 窗口稳健拟合。结果写 `rq2_source_error.csv`、`rq2_motion_delay.csv`、`rq2_trial_summary.csv`、`rq2_latency_summary.csv` 与 `rq2_model_summary.csv`。

- [x] **Step 5: 测试转绿**

Run: `pixi run python -m unittest egoanchor.eval.tests.test_log_loader egoanchor.eval.tests.test_rq2_analyze`
Expected: PASS。

## Task 5: Typst 论文与 AGENTS

**Files:**
- Modify: `2026-EgoAnchor-Typst/egoanchor_cn_v6.typ`
- Modify: `AGENTS.md`

- [x] **Step 1: 改写代码事实**

把固定 120 ms 改为按采集至渲染观测年龄自适应的总目标延迟；控制器改称平台参考位姿，并说明固定模型到追踪原点变换需独立标定。

- [x] **Step 2: 改写 RQ2 方法与结果占位**

保留 RQ2 标题和三场景。将“时延补偿前后”改为 capture-time raw、render-time *Full*/*Raw-ZOH* 与沿运动方向时延项；将 Frame/Arrival 对照移出主图；结果段不得预写未实测数值、显著性或机理归因。

- [x] **Step 3: 更新长期项目事实**

在 `AGENTS.md` 现有 RQ2 条目中写明新时间字段、trial 契约、误差口径和分析入口；直接替换被新事实推翻的旧描述，不追加流水账。

- [x] **Step 4: Typst 编译**

Run: `typst compile --root . .\2026-EgoAnchor-Typst\egoanchor_cn_v6.typ .\2026-EgoAnchor-Typst\pdf\egoanchor_cn_v6.pdf`
Expected: exit 0。

## Task 6: 全量验证与审查

- [x] Run: `pixi run python -m compileall src`
- [ ] Run: `pixi run python -m unittest discover -s src -p "test_*.py" -t src`（200 项中 1 项导入失败：既有 `test_windows_msvc_runtime_env` 引用了当前源码不存在的 `ensure_windows_msvc_runtime_env`；eval 56 项全部通过。）
- [ ] Run: `dotnet test "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore`（命令 exit 0，但只构建且未实际发现/执行 NUnit 测试。）
- [x] Run: `dotnet build "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore`
- [x] Run: `dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore`
- [x] Run Typst compile command from Task 5（exit 0；仅有本机缺少 IEEE 模板字体的警告）。
- [x] 使用 Code Simplifier 以 audit 模式复查改动文件；GT 短空窗与短序列 lag 偶然相关两个阻塞问题已补回归测试并修复，未发现其余 51 分以上问题。
- [x] 复核 `git diff`：未改动 proto/生成物；字体资产保留用户原有 staged/unstaged 修改，未触碰或回退。论文、实现、测试、RQ2 场景、设计与计划文档均属于本任务范围。
