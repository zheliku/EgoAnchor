# EgoAnchor Anchor 效果优化计划（Phase B：算法优化）

## Context（为什么做这件事）

P1 的评估系统已落地，跑出了第一批定量数据。用最新一轮 `20260603_220619_controller_right` 的原始日志交叉验证后，发现**数据重新定义了问题**，不能照直觉优化：

- **静止抖动**：位置 jitter 已被 Kalman 压到 **0.34mm**（很好），但旋转 jitter 仍有 **1.27°**（几乎没压住）。根因在 `AnchorKalmanPoseProcessor` 旋转只用固定速率 Slerp 低通，不是真正的旋转滤波。
- **误差表里 7mm/4.2° 绝大部分是固定标定偏置**：去掉 GT(`OVRControllerPrefab`) 与 mesh 原点之间的常量刚体偏置后，真实跟踪精度是 **0.8mm / 0.5°**。旋转是全场景的薄弱通道。
- **坏 pose 识别是结构性缺失**：FoundationPose 的 `track_one` 只返回 4×4 矩阵，无任何 per-frame 置信度。已核实其 scorer（`FoundationPose/learning/training/predict_score.py:194-209`）是**成对相对排序器**（`model(A,B)→score_logit`，单假设时返回 `logit+100` 哨兵），跨帧不可比，绝对化需多次 GPU 推理。当前唯一拦截是 `_is_track_jump`（阈值 0.6m/100°），缓慢漂移和锁错位姿抓不到。
- **评分坍缩为 1.0**：`pose_quality.py` 在 depth/mask 正常时几乎不降分（实测 542/547 TRACK 帧 = 1.0），无法驱动任何自适应。
- **滤波架构割裂**：开启 policy 时，`PolicyController` 先做 gate/coast 产出 stable pose，这个 pose **又进一次 Kalman**（`PoseToAnchorRuntime.cs:369` 双重滤波）。两级噪声参数互不知情，coast 的线性外推被后级 Kalman 拖拽。

### 用户已决策（严格遵守）

1. **跳过测量基线工作**：本轮不做 hand-eye X 标定、不做 score_calibration 指标，纯算法优化。
2. **坏 pose 识别**：用渲染-重投影一致性（IoU+深度残差）作主信号，复用现有 `nvdiffrast` 光栅化器；scorer 仅在 register 时一次性使用。
3. **滤波统一为单一自适应 6DoF 滤波器**：位置+旋转一体，旋转含角速度（可在 coast 时外推），过程/测量噪声按 reliability_score 自适应，gate/coast 集成进同一模型。
4. **Unity 验证**：用 `EgoAnchorEval` 下的 synthetic pose 流 smoke 驱动器（不引入新测试程序集）。

### 第二轮审阅已采纳的修订（GPT review + 自查）

- **渲染 facade**：reliability 层不直接碰 `estimator.estimator.glctx/mesh_tensors`，由适配器公开 `render_depth_mask(...)`（见 A.1）。
- **shadow mode**：一致性检测加 `mode = "score_only" | "re_register"`，第一轮只降分/写 flag 不重注册，确认误报率后再开重注册（见 A.5）。
- **轻量分布诊断**（窄化采纳，仍不做标定）：补 score/consistency 直方图、policy action/reason 分布、spike 漏检率、一致性开销统计；**不做** score_calibration(ROC/PR-AUC) 与 hand-eye（见新增「E. 轻量诊断」）。
- **一致性数值落 runtime JSONL**：不动 proto，走 observation 旁路记录（见 A.4）。
- **无效即不重注册**（强约束 + warmup + 自激封顶，见 A.2）。
- **滤波上下文显式传参**：用 `Process(input, frameId, sampleTime, in ctx)` 重载替代易误用的状态式 setter（见 C.1）。
- **`AlreadyFiltered`** 决策字段修双滤波（见 C.2）。
- **frame alignment 插值 / recovery 证据闭环**：本轮不做但保留，列入「后续阶段」（见末尾）。

开始执行前，我建议把这些作为硬性检查点：

1. **render_depth_mask** facade 要非常小心
   内部必须 **torch.no_grad()**、输入 pose 转 CUDA float **(1,4,4)**，输出立即 **detach().cpu().numpy()**。还要验证 **nvdiffrast_render** 已经做过 Y flip，观测 mask/depth resize 后方向必须一致，否则一致性会误判。
2. runtime JSONL 旁路是必须项
   现在 tracking_runtime.py (line 311) 只把 protobuf msg 传给 **log_writer.pose_result()**，而 runtime_log_writer.py (line 103) 只从 msg 取字段。所以 **track_consistency / consistency_ms** 不能只改 **PoseLogFactory**，需要让 **pose_result(msg, state, diagnostics=...)** 或类似接口显式接收旁路诊断。
3. Unity 上下文重载不要污染所有 processor
   AnchorPoseProcessor 现在只有普通 **Process(...)**。建议新增 **PoseQualityContext** + 新 processor 自己的重载，或加 **IQualityAwarePoseProcessor**，不要强迫 LowPass/Kalman baseline 改签名。
4. **AnchorPolicyHost.OnValidate()** 会重建 controller
   现在 Inspector 变化会 **Rebuild()** 并清空状态。接入统一滤波器后，Play Mode 下不要因为 Inspector 改值误清滤波器历史；这里要加保护或明确只重建 policy controller，不误 reset processor 状态。
5. Unity smoke 要能命令行自动断言
   MonoBehaviour smoke 可用于场景测试，但真正回归门最好扩展 **EgoAnchor_Tools/anchor_policy_smoke**，或把旋转数学抽成纯 C# core，让 **dotnet run** 能断言静止抖动、coast 旋转、gate、无双滤波。
6. 旋转滤波先测数学，再接 runtime
   必测 **Log/Exp**、短弧符号、接近 180°、静止噪声不放大。常角速度模型对静止抖动有反噬风险，你计划里保留 One-Euro fallback 是对的。
7. **score_only** 必须先跑离线分布
   不要一上来开 **re_register**。先用现有 session 看 consistency 分布、误报率、**consistency_ms** p50/p95，再决定阈值和是否启用重注册。

### 已核验的关键事实

- 渲染器 `nvdiffrast_render(K,H,W,ob_in_cams,glctx,mesh_tensors,output_size)` 在 `FoundationPose/Utils.py:133-219`，返回 `(color, depth, normal)`，camera-space，**可全帧直接渲染**，无需裁剪流水线；复用 estimator 已加载的 `glctx`/`mesh_tensors`，单帧约 5-10ms，下采样后更低。
- `register/track` 在 `foundationpose_estimator.py:429/445` 只返回矩阵，丢弃内部 scorer。
- `PoseResult` 协议已有 `reliability_score`(字段11) + `reliability_flags`(字段12)，**本轮不动 proto**，更丰富的信号塞进这两个字段即可。
- 论文需要 raw / kalman / policy 多个对照 variant —— 统一滤波器**新增**实现，不删除现有处理器。

---

## 实现顺序与依赖

1. **A** 渲染一致性检测器（产出绝对 `track_consistency` 信号），先以 `mode="score_only"` 落地
2. **B** 重写可靠性评分（消费 A 的信号 + 深度 + 跳变幅度）
3. **E** 轻量诊断（score/consistency 直方图、policy 分布、开销），用来判定 A/B 误报率 → 再决定是否把一致性切到 `mode="re_register"`
4. Python 端到端验证（单测 + 离线回放）
5. **C+D** Unity 统一自适应滤波器（D 是 C 的旋转通道），与 A/B 可并行开发，但最终联调在 A/B 落地后（C 的自适应噪声依赖已变得有意义的 `reliability_score`）

---

## A. 渲染-重投影一致性坏 pose 检测器（Python）

### A.1 新建 `EgoAnchor_Python/src/egoanchor/reliability/render_consistency.py`

在 TRACK 输出位姿处渲染 mesh，得到渲染 mask 与渲染深度，与观测 mask（IoU）和观测深度（mask 内深度残差）比较，输出 0..1 绝对一致性分。

```python
class RenderConsistencyChecker:
    """渲染-重投影一致性检测器。FoundationPose scorer 只是成对相对排序器，
    不能跨帧比较，故用几何重投影作为绝对信号。"""
    def __init__(self, iou_weight=0.6, depth_weight=0.4,
                 depth_inlier_thresh_m=0.02, min_render_area_px=50, downscale=2): ...
    def evaluate(self, estimator, pose_cv_camera, observed_mask, observed_depth_m
                 ) -> "RenderConsistencyResult": ...

@dataclass(frozen=True, slots=True)
class RenderConsistencyResult:
    consistency: float; mask_iou: float; depth_inlier_ratio: float
    depth_median_residual_m: float; render_area_px: int; valid: bool
```

**算法**：

1. 按 `downscale` 缩放 K（fx,fy,cx,cy / downscale）与 H,W。
2. **不直接访问第三方内部结构**：在 `foundationpose_estimator.py` 适配器上新增公开方法
   `render_depth_mask(pose_cv_camera, output_size, cam_k=None) -> tuple[np.ndarray, np.ndarray]`
   （返回 render_depth、render_mask），内部用 `call_with_logging_control` 包裹 `nvdiffrast_render(K', H', W', ob_in_cams=pose[None], glctx=self.estimator.glctx, mesh_tensors=self.estimator.mesh_tensors, output_size=(H',W'))`。`render_consistency.py` 只调这个 facade，绝不碰 `estimator.estimator.glctx/mesh_tensors`。
3. `render_mask = depth_render > 0`；观测 mask/depth 用 `cv2.INTER_NEAREST` 缩到 (H',W')。
4. **IoU** = inter/union；**深度残差**：inter 内 obs_depth>0 的像素，`inlier_ratio = mean(|d_render - d_obs| < thresh)`。
5. `consistency = clamp01(iou_weight*iou + depth_weight*inlier_ratio)`。
6. `valid = render_area_px >= min_render_area_px and obs_mask.sum()>0`；无效时 caller 视为"本帧无信号"，**绝不触发 RE_REGISTER**。

**关键风险**：渲染喂入的 pose 必须是 FoundationPose 原始输出（与内部 refiner 用的 `ob_in_cams` 一致、基于 `mesh_tensors`），**不是** `visualize_pose` 里 `inv(to_origin)` 后的盒子绘制 pose。喂错会导致 IoU 接近 0、误触发 RE_REGISTER。

将纯数学部分抽成静态方法 `_score_from_maps(render_mask, obs_mask, render_depth, obs_depth, ...)`（不碰 CUDA），便于无 GPU 单测。

`reliability/__init__.py` 导出 `RenderConsistencyChecker`、`RenderConsistencyResult`。

### A.2 接入 `perception/quest_pose_pipeline.py`

- 构造函数新增 `enable_render_consistency=False`、`consistency_mode="score_only"`、`consistency_re_register_threshold=0.35`、`consistency_min_track_frames=2`、`consistency_warmup_frames=3`，按包导入 `from egoanchor.reliability import RenderConsistencyChecker`。
- TRACK 成功且 `_is_track_jump` 通过后，新增 `_check_track_consistency(pose, depth, mask, diagnostics, timing) -> float | None`：调检测器、记 `diagnostics.track_consistency` 等、`None` 表示无效。
- **决策（仅 `consistency_mode=="re_register"` 时生效）**：一致性有效且 `< consistency_re_register_threshold` 连续 `>= consistency_min_track_frames` 帧 → 软 track-loss：`track_reject_count += 1`、reset estimator、有 mask 则 RE_REGISTER（镜像现有 jump 路径 720-733 行），failure_reason=`"low_consistency"`。`score_only` 模式只降分写 flag，**不**重注册。这抓的是 0.6m 跳变门看不见的缓慢漂移/锁错位姿。
- **强约束：以下任一情形只输出 `no_consistency_signal`，绝不触发重注册**：Cutie mask 空、`render_area_px < min_render_area_px`、`depth_valid_in_mask` 过低、刚重注册后 warmup 期内（`frames_since_register < consistency_warmup_frames`）、K 尚未更新。
- **防自激循环**：重注册后用 `consistency_warmup_frames` 跳过一致性判定，且低一致性重注册同样累加 `track_reject_count`、复用现有 `max_consecutive_track_rejects` 封顶，连续触顶则强制回 DETECT 而非无限重注册。
- TRACK 期观测 mask 来自 Cutie；Cutie 关闭或 mask 空 → `valid=False`，仅给中性分（代码注释写明）。

### A.3 `perception/pose_observation.py` 新增字段

```python
track_consistency: float = -1.0       # 渲染一致性分，0..1；-1 表示本帧无信号
consistency_mask_iou: float = 0.0     # 渲染 mask 与观测 mask 的 IoU
consistency_depth_inlier: float = 0.0 # mask 内深度 inlier 比例
last_translation_delta_m: float = 0.0 # 上帧到本帧平移增量（供评分用）
last_rotation_delta_deg: float = 0.0  # 上帧到本帧旋转增量（供评分用）
```

`_make_observation`(827) 的字段重建会自动透传（867-871 行已是除 score/flags 外全字段拷贝）。

### A.4 状态/诊断/timing/日志

- `pipeline_types.py`：`PipelineTrackingState` 加 `low_consistency_count=0`、`frames_since_register=0`（在 `bump_generation()` 清零/重置）；`FrameDiagnostics` 加 `track_consistency/consistency_mask_iou/consistency_depth_inlier/consistency_depth_residual_m/consistency_ms`；一致性耗时也折进 `total_ms`（不动 proto TimingStats）。
- 重构 `_is_track_jump`/新增 `_track_deltas(pose) -> (t_delta, r_delta)`，复用 `_rotation_angle_from_trace_deg`(820)，把测量增量 stash 给 observation。
- **一致性数值落 runtime JSONL（不动 proto）**：`runtime_log_writer.py` 的 `pose_result()` 当前只从 protobuf `msg` 取字段。新增旁路：让 `tracking_runtime` 在写日志时把本帧 `FrameDiagnostics` 的一致性字段一并传入（或 `PoseLogFactory.build` 扩展），记录 `track_consistency / consistency_mask_iou / consistency_depth_inlier / consistency_depth_residual_m / consistency_ms`，供离线分析。Unity 侧仍只收 score/flags。

### A.5 配置 `config/defaults.toml` 新增 `[reliability.consistency]`

```toml
[reliability.consistency]
enabled = false                 # 是否启用渲染一致性检测；真机联调稳定后再设 true。
mode = "score_only"             # score_only=只降分写flag不重注册；re_register=确认误报率后再开连续低一致性重注册。
re_register_threshold = 0.35    # 一致性低于该值且持续若干帧后触发 RE_REGISTER（仅 re_register 模式）。
min_track_frames = 2            # 连续多少帧低一致性才判定锁错/漂移，避免单帧误触发。
warmup_frames = 3               # 重注册后跳过一致性判定的帧数，避免重注册自激循环。
iou_weight = 0.6                # 综合分中 mask IoU 权重。
depth_weight = 0.4              # 综合分中深度 inlier 权重。
depth_inlier_thresh_m = 0.02    # 深度残差 inlier 阈值，单位米。
downscale = 2                   # 一致性渲染下采样倍数，越大越快但越粗。
min_render_area_px = 50         # 渲染前景过少时判无效，不触发重注册。
```

`pipeline_factory.py` 的 `build_quest_pose_pipeline`(~126) 防御式读取该段并传参，默认 `enabled=false` 保持现有行为不变。

### A.6 验证

- 单测 `tests/test_render_consistency.py`：对 `_score_from_maps` 喂合成 mask（完全重叠→≈1、不相交→0、半重叠→中），无需 GPU。
- 离线：录制 session 上开启，逐帧记 `track_consistency`，确认在跳变门漏掉的漂移/锁错帧上掉分。

---

## B. 可区分的可靠性评分：重写 `reliability/pose_quality.py`

把 `score_observation` 从"几乎恒为 1.0"改成三个真正变化量的连续函数：渲染一致性、深度质量、跳变幅度。

保留无 pose 早返回块（16-23）。主体改为各子分（[0,1]）相乘：

1. **一致性子分**（主）：`track_consistency >= 0` 时 `s_consistency = clamp01(track_consistency)`，`<0.5` 标 `consistency_low`；无信号（REGISTER 帧/关闭）时 `=1.0` 但标 `no_consistency_signal`。
2. **深度子分**：平滑斜坡 `s_depth = lerp到[0.3,1.0]`，由 `depth_valid_in_mask` 在 0.05→0.35 映射；保留 `depth_in_mask_low/mid` flag。
3. **跳变子分**：`s_jump = clamp01(1 - max(t_delta/jump_t_thresh, r_delta/jump_r_thresh))`（用 A.3 surfaced 的测量增量），`<0.5` 标 `near_jump_limit`。
4. **mask 面积 / track_reject**：保留现有乘性因子（43-52）。
5. **phase 权重**：TRACK/REGISTER/RE_REGISTER 全权，其余 ×0.7。

`score = phase_w * s_consistency * s_depth * s_jump * mask_factor * reject_factor`，clamp。

**协议**：复用现有 `reliability_score`/`reliability_flags`，**不改 proto**（`message_factories.py:42` 已映射，无需改）。

**验证**：扩展 tests（仿 `test_pose_result_factory.py`）：构造跨度样本断言分数单调且**非恒定**（直接守护"坍缩为 1.0"回归）；离线回放对 `reliability_score` 做直方图确认分布展开。

---

## C. 统一自适应 6DoF 滤波器（Unity）+ D. 旋转通道

用单一可靠性自适应 6DoF 滤波器替代两级（`PolicyController` gate/coast → `AnchorKalmanPoseProcessor` 位置KF+固定Slerp）。

### C.1 核心滤波器：新建 `Assets/Scripts/EgoAnchor/Processors/AnchorAdaptive6DofProcessor.cs`

继承现有 `AnchorPoseProcessor`（namespace `EgoAnchor.Processors`），作为处理器接入现有 list 机制，但吸收原 PolicyController 的 gate/coast 职责。

Inspector 字段（全部 `[Tooltip]` 中文）：

- 位置：`positionMeasurementNoiseHigh/Low`、`positionProcessNoise`
- 旋转：`rotationMeasurementNoiseHigh/Low`、`rotationProcessNoise`、`maxAngularSpeedDegPerSec`
- 自适应：`scoreForFullTrust=0.8`、`scoreForMinTrust=0.2`
- gate：`maxTranslationJumpMeters=0.80`、`maxRotationJumpDegrees=90`
- coast：`maxCoastSeconds=0.45`；`snapOnFirstPose=true`

因 `Process(pose,frameId,sampleTime)` 签名带不了 score/有效性，**用显式上下文重载替代易误用的状态式 setter**（GPT 审阅点 6）：定义 `readonly struct PoseQualityContext { float ReliabilityScore; bool HasMeasurement; string PoseSource; string Reason; }`，新增接口/重载：

```csharp
/// <summary>带可靠性上下文的处理；上下文每帧由调用方显式传入，不残留状态。</summary>
public Pose Process(Pose input, long frameId, double sampleTime, in PoseQualityContext ctx);
```

`PoseToAnchorRuntime` 显式调用该重载，杜绝"忘了设上下文直接 Process"。基类原无参 `Process` 保留给 baseline 处理器。

`ProcessPose` 流程：`dt = ConsumeDeltaTime` → **Predict**（位置常速度，复用 `AnchorKalmanPoseProcessor.cs:143` 的 AxisKalman predict；旋转积分角速度——见 D）→ 若 `!ctx.HasMeasurement` 则 coast（`<= maxCoastSeconds` 返回预测，否则 hold/Lost）→ **Gate**（创新超阈值且 PoseSource 非 register 则拒绝并 coast，register 允许跳变）→ **自适应 update**（测量噪声按 `Lerp(noiseLow, noiseHigh, invLerp(score, min, full))` 缩放：低分→高测量噪声→更信预测=稳；高分→低测量噪声=跟手）→ 返回融合 pose。这是建模"稳 vs 跟手"权衡的唯一位置。

只读属性供 host adapter：`LastMeasurementAccepted`、`IsCoasting`、`IsLost`、`LastReason`、`CurrentFilteredPose`。

### D — 旋转通道数学

用**四元数误差状态滤波 + 角速度**替代固定 Slerp（`AnchorKalmanPoseProcessor.cs:73-74`，1.27° 静止抖动来源）：

状态：朝向四元数 `q` + 体角速度 `ω`(rad/s)。

- **Predict**：`q_pred = q ⊗ Exp(ω·dt)`（`Exp` 用 `Quaternion.AngleAxis(|ω·dt|, ω̂)`），`ω` 不变（常角速度），协方差按旋转过程噪声增长。
- **Update**（测量 `q_meas`）：误差旋转向量 `θ = Log(q_pred⁻¹ ⊗ q_meas)`（轴角→向量，wrap 到 (−π,π]）；自适应旋转测量噪声算增益 `K`；校正 `q = q_pred ⊗ Exp(K_q·θ)`、`ω += K_ω·(θ/dt)`。
- `|ω|` clamp 到 `maxAngularSpeedDegPerSec`。
- **coast 时继续 `Exp(ω·dt)` 外推**（修复 `AnchorPredictor.cs:82` 旋转保持不动的缺陷）。

实现私有静态 `QuaternionLog`/`QuaternionExp`。

**自查风险（关键）：常角速度模型在静止时可能反而放大抖动**——而静止旋转抖动恰是本计划的 PRIMARY 目标。ω 估计本身带噪声，静止时滤波器会"误以为在转"。两条对策同等优先，实现时按 smoke 数据二选一：

1. **误差状态 KF**：用足够大的 ω 过程噪声 / 测量噪声比，让静止时 ω 收敛到 ≈0；并对 ω 加死区（`|ω| < ω_deadband` 时清零）。
2. **One-Euro 四元数滤波**（天生针对静止抖动，速度项随角速度自适应截止频率）：静止低截止=强平滑，快转高截止=跟手。

正式方法二选一由 D 的 smoke 静止抖动断言裁决（必须实测优于 1.27°），不预设赢家；另一个在注释中标注为 fallback。

### C.2 Host 集成：`Policy/AnchorPolicyHost.cs` + `Runtime/PoseToAnchorRuntime.cs`

双重滤波 bug 在 `PoseToAnchorRuntime.cs:369`（对 policy 输出又跑一遍 processor chain）。

- `AnchorPolicyHost` 加序列化 `bool useUnifiedFilter` + 持有一个 `AnchorAdaptive6DofProcessor` 引用。`useUnifiedFilter` 时 `AcceptPose` 走 adapter：①构造 `PoseQualityContext{score, HasAlignedPose, PoseSource, FailureReason}` ②`processor.Process(WorldPose, FrameId, SampleTimeSeconds, in ctx)` ③读回滤波器只读状态（accept/coast/lost/pose），用 6 参构造器打包成 `AnchorPolicyDecision`（`AlreadyFiltered=true`），使 `ApplyPolicyDecision`/诊断/server-status 映射全部不变。
- `ApplyPolicyDecision`(362)：统一滤波模式下**不**对输出再跑 `RunProcessors`。给 `AnchorPolicyDecision`（现为 5 参 readonly struct，`AnchorPolicyDecision.cs:51`）加 `bool AlreadyFiltered` 字段：保留原 5 参构造器（委托新构造器、`AlreadyFiltered=false`，不破坏 legacy/baseline 现有调用），新增 6 参构造器供统一滤波 adapter 使用。`ApplyPolicyDecision` 中 `if (decision.AlreadyFiltered) { stablePose = decision.OutputPose; } else { stablePose = RunProcessors(decision.OutputPose, ...); }`，守护 369 行双滤波。
- missing/align-failed 事件已经过 `policyHost.AcceptPose`（326/346 行），adapter 把 `HasAlignedPose=false → ctx.HasMeasurement=false → coast/hold`，无需新入口。
- 保留 `AnchorStateMachine` 做生命周期标签，host 据滤波器 accept/coast/lost 驱动，HUD/`AnchorStatusEvent` 不动。

### C.3 Baseline 保留（架构风险）

论文对照：raw / low-pass / kalman / 新自适应 policy。**全部保留**：

- **不删** `AnchorKalmanPoseProcessor.cs`、`AnchorLowPassPoseProcessor.cs`。
- raw = `policyHost==null` + 空 processors（现状）
- kalman baseline = `policyHost==null` + `[AnchorKalmanPoseProcessor]`（现状）
- 统一自适应（完整方法）= `policyHost!=null` + `useUnifiedFilter=true` + host 引用 `AnchorAdaptive6DofProcessor`，processors 空
- 旧两级 policy = `policyHost!=null` + `useUnifiedFilter=false`（暂留对照，验证后可退役）

C 是**纯增量**：一个新处理器文件 + 一个模式开关 + 双滤波调用点一个 guard，不动任何 baseline 路径。

### C.4 验证（EgoAnchorEval smoke 驱动器）

在 `Assets/Scripts/EgoAnchorEval/`（已有独立 asmdef）新增一个 MonoBehaviour smoke 驱动器，喂合成 pose 流并记录输出，符合 AGENTS.md 的 smoke 验证习惯。断言：

- **静止抖动(D)（PRIMARY 回归门）**：恒定 pose + 小噪声 → 输出旋转抖动显著低于输入，**且不得高于旧 Slerp baseline 的 1.27°**（常角速度模型若放大静止抖动，此断言会失败，触发切到 One-Euro 或加 ω 死区）；目标亚 0.5°。
- **coast 旋转**：旋转 pose 后断测量 → 输出继续旋转（角速度外推）
- **自适应**：低 score 流 → 输出更稳/滞后；高 score → 紧跟
- **gate**：注入单帧 1m 跳变 → 拒绝、不瞬移
- **无双滤波**：统一模式下断言 `stablePose == decision.OutputPose`（守护 369 行回归）

旋转 Log/Exp、KF predict/update 等核心数学尽量写成纯 C# 静态方法，便于 dotnet 编译检查 + smoke 驱动器读数验证。

---

## E. 轻量诊断（窄化采纳 GPT 审阅点 3，仍不做标定）

目的：算法改完后能证明"坏 pose 被识别了，而非被滤波器磨平"。**只做不需要 GT 标定的分布统计**，明确**不做** score_calibration(ROC/PR-AUC，需要 GT 坏 pose 标签) 和 hand-eye X 标定（属测量基线，已被决策排除）。

落在已有的 `EgoAnchor_Python/eval/` 框架内（只读 JSONL，不 import runtime），新增一个轻量统计脚本/函数（如 `eval/metrics/diagnostics.py`），输出：

- `reliability_score` 直方图 + 是否仍坍缩（unique 值数、众数占比）——直接证明 B 生效。
- `track_consistency` 直方图（来自 A.4 落盘字段）。
- policy `action`/`reason` 分布计数（Accept/Reject/Coast/Hold 各占比）——来自 unity_output variants。
- spike 漏检率：raw 出现 `>spike_threshold` 跳变时，policy 是否 Reject/Hold（复用 `jump_suppression` 已有的 spike 检测）。
- 一致性开销：`consistency_ms` 的 p50/p95，确认延迟预算（目标单帧增量 < 5ms）。

这些是纯计数/直方图，几小时内可加，给论文消融和调参提供"识别 vs 磨平"的判据。

---

## 后续阶段（本轮保留不删，列入路线）

以下不在本轮，但明确保留，避免被误删：

- **frame alignment 插值**（`CameraPoseFrameAligner.cs:121` 仅精确命中 frame_id，淘汰/改 id 即 align 失败）→ 后续做最近邻/线性插值兜底。
- **recovery 证据闭环**：当前录制无 occlusion / out_of_view / no-pose 段，coasting/recovery/Lost→重获取仍无数据证据。后续补录制协议第 4-7 段（物体运动/遮挡/移出视野/变光照）再验证。
- **score_calibration(ROC/PR-AUC) 与 hand-eye X 标定**：需要 GT 坏 pose 标签与刚体标定，留待测量基线阶段。

Python（在 `EgoAnchor_Python`）：

- `pixi run python -m compileall src`
- `pixi run python -m unittest discover -s src -p "test_*.py"`

Unity（仓库根）：

- `dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore`

端到端：开启 `[reliability.consistency].enabled=true`（先 `mode="score_only"`），跑录制/回放 session，用 E 的诊断确认 ①`reliability_score` 分布展开非恒定 ②低一致性帧确实落在坏 pose 上（看 consistency 直方图与 spike 漏检率，确认是识别非磨平）③一致性开销 `consistency_ms` p95 在预算内 ④Unity 静止旋转抖动下降 ⑤raw/kalman/legacy-policy/unified 四 variant 仍可跑（论文矩阵完整）。误报率可接受后再切 `mode="re_register"` 验证重注册。

---

## 实现约束（项目规范）

- Python 按包导入（`from egoanchor.xxx import ...`，不到具体模块文件）。
- 详细中文注释：类的成员变量和每个方法都要注释；`.toml` 每个参数行末不换行中文注释。
- 命名简洁达意，不打补丁式局部修改，全局考虑架构配合。
