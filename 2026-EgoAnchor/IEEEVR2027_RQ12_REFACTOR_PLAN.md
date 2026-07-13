# EgoAnchor IEEE VR 2027 论文与 RQ1/RQ2 工程重构总计划

## 1. 文档地位

本文档是 EgoAnchor 面向 IEEE VR 2027 的论文、运行时、定量采集和分析重构合同。后续实施以本文档为唯一计划来源，不延续旧 RQ1/RQ2 的场景划分、双变体结果、分析入口或兼容层。

实施采用两次 Codex 运行加一次用户采集：

1. **Run 1（采集前）**：一次性完成论文框架重写、RQ1/RQ2 工程重构、统一采集程序、自动 QC、分析与绘图骨架、LaTeX 自动回填接口和中文操作手册。
2. **用户采集**：用户只按手册操作 Quest、控制器和工作站，先完成短 smoke，再完成正式 session；每个 trial 后运行自动 QC。
3. **Run 2（数据返回后）**：完成数据审计、RQ1/RQ2 分析、图表与 LaTeX 数字生成、结果写作、讨论收束和论文编译。

RQ3 在本合同内只冻结问题、协议、页数和结果接口，不实施实验。正式投稿前必须补齐 RQ3 结果，或删除 RQ3 及相关对象覆盖主张。

执行约束：

- 在当前 Git 分支直接修改，不创建提交。
- 允许删除旧代码、旧场景和旧分析入口；不保留兼容适配层。
- 历史原始数据不作为新正式结果；可在 Run 1 中一次性用于开发参数冻结，最终代码不保留旧 schema 兼容。
- 论文论证决定工程边界；没有对应 claim 或 QC 用途的代码不进入新主线。
- 当前中文主稿仍为 `egoanchor_cn_v6.tex`。Run 1 直接重写该文件，不新建 v7。

## 2. 投稿边界与完成状态

IEEE VR 2027 正文、图和表合计 4--9 页，参考文献另计但最多 2 页，附录计入正文页数。官方页面：[https://ieeevr.org/2027/contribute/papers/](https://ieeevr.org/2027/contribute/papers/)。

当前两次运行的终点是：

- RQ1/RQ2 证据完整；
- RQ3 协议冻结但结果未完成；
- 中文主稿正文不超过 8.4 页，为 RQ3 结果保留至少 0.55 页；
- 论文不是投稿终稿，直至 RQ3 得到回答或被正式删除。

## 3. 论文中心论点

推荐标题：

> **EgoAnchor: Reliability- and Regime-Aware Dynamic Object Anchoring for Consumer Mixed Reality**

中文工作标题：

> **EgoAnchor：面向消费级混合现实的可靠性与运动区制感知动态物体锚定**

中心论点：

> 开放视觉后端输出的异步 6DoF 位姿并不天然构成可供混合现实应用使用的对象锚点。EgoAnchor 恢复观测的采集时刻世界语义，以 VCD 为候选观测生成连续可靠性评分，并依据固定阈值与静止/运动区制控制锚点更新，从而把低频、延迟且质量不均的相机系位姿流转换为世界系对象锚点。

全文围绕三个运行时问题组织：

1. 观测对应哪个采集时刻和世界坐标关系？
2. 候选观测是否适合更新锚点？
3. 锚点在静止、起停转换和持续运动阶段应如何响应？

时空对齐是系统架构基础；VCD 与显式静止锚定是两项需要独立验证的主要技术贡献。

## 4. 贡献定义

### C1：感知到锚点的分层系统

EgoAnchor 定义异步视觉观测到对象锚点的运行时边界，通过 `frame_id` 恢复图像时间代理处的相机世界变换，并统一管理观测接纳、时序输出和生命周期。

### C2：VCD 观测可靠性评分

VCD 是无需额外学习的可视度门控颜色-深度一致性评分。它为每个 TRACK 候选输出 `[0,1]` 连续分数，供运行时执行阈值接纳；该分数不是位姿正确概率，也不是排序算法。

### C3：显式静止锚定

静止锚定把静止作为独立输出区制，通过锁定、多证据解锁和连续过渡抑制静止期抖动，并显式暴露起动与停止转换代价。

“系统实现与评估”不单列为贡献。评估只承担证据作用。

## 5. 研究问题与可证伪命题

### RQ1：观测可靠性

> **VCD 能否为 TRACK 位姿候选提供有效的观测可靠性评分，使高分候选对应更低的锚点更新风险，并在给定观测接纳覆盖率下降低被接纳观测的尾部误差？**

预先冻结的命题：

- H1a：按评分诱导的候选顺序计算时，完整 VCD 的平移和旋转 AURC 优于 `V` 与 `V·D`。
- H1b：在 calibration 上冻结的目标覆盖率下，VCD 的正式测试 P95 低于 coverage-only 消融。
- H1c：在固定候选流和相同 ZOH consumer 下，VCDGate 减少大误差更新与显示跳变；代价以输出覆盖率报告。

反证条件：完整 VCD 与部分模态消融相当，或 matched-coverage 后收益消失。出现任一条件时，VCD 降级为工程质量信号，不作为独立贡献。

### RQ2：区制感知锚定

> **在相同 VCD 门控观测流上，*ZOH*、*One Euro*、*Ours-NoLock* 与 *Ours-Full* 在静止稳定性、起停响应和持续运动性能上呈现怎样的差异？显式静止区制相对无静止锁变体带来何种收益与代价？**

预先冻结的命题：

- H2a：*Ours-Full* 相对 *Ours-NoLock* 降低静止位置和旋转 HP-RMS，同时不以更大的稳态偏差换取该结果。
- H2b：StaticLock 的 visible response、unlock、relock、peak error 和 settling cost 可以量化；不预设该代价为零。
- H2c：持续运动阶段报告 *Ours-Full - Ours-NoLock* 的配对差，不预先宣称等价或无损。
- H2d：*Ours-Full* 与 *One Euro* 的比较检验完整区制感知运行时相对外部标准滤波器的系统级差异。
- H2e：*Ours-NoLock* 与 *One Euro* 的比较检验 Kalman-Hermite 连续估计相对标准自适应滤波的差异。
- H2f：*ZOH* 是离散保持参照，用于量化不进行时序合成时的连续性代价。

### RQ3：端到端对象覆盖（延期）

> **在给定三维模型且无需逐物体训练的前提下，完整 EgoAnchor 在所测日常刚体上表现出怎样的初始化、持续输出、遮挡恢复和停止后稳定性？**

本轮只冻结如下协议：4--6 个覆盖尺寸、纹理和对称性差异的刚体；报告初始化成功率与时间、输出覆盖率、恢复成功率与时间、停止后稳定性和失败类型。不得使用“任意物体泛化”。

## 6. Claim-Evidence 合同

| Claim                                  | 必需证据                                                       | 证据不足时的处理                         |
| -------------------------------------- | -------------------------------------------------------------- | ---------------------------------------- |
| frame alignment 避免头动造成的坐标错配 | 静止目标、主动头动下的 Frame-aligned/Arrival-aligned 配对诊断  | 仅作为架构实现，不宣称精度收益           |
| VCD 评分具有风险判别性                 | held-out session 中由评分诱导的平移/旋转 risk-coverage 与 AURC | VCD 降为工程信号                         |
| VCD gate 降低有害更新                  | matched-coverage ZOH replay                                    | 不声称下游效用                           |
| StaticLock 降低静止抖动                | Full/NoLock 配对 HP-RMS、绝对误差和锁定漂移                    | 只报告冻结行为                           |
| StaticLock 转换代价可控                | visible response、unlock/relock、peak error、settling          | 明示代价，不使用“打破权衡”             |
| 持续运动性能得到保持                   | 配对 trial/session 差异                                        | 不使用“无损”“等价”或“non-inferior” |
| 输出更连续                             | render-update ratio 与输出覆盖率                               | 只描述输出行为，不称整体性能更优         |
| 系统可恢复                             | visible-again、reacquire 和 stable-anchor 三类时间标记         | 不报告恢复时间                           |
| 覆盖日常物体                           | RQ3 多对象正式试次和失败分析                                   | 限定为控制器与所测对象                   |
| 可部署                                 | 外部 GPU、网络、模型和平台依赖完整披露                         | 不称头显端独立运行                       |

## 7. 论文结构与页数预算

| 内容               | 最终预算 |
| ------------------ | -------: |
| 标题、teaser、摘要 |  0.70 页 |
| 引言               |  0.85 页 |
| 相关工作           |  0.70 页 |
| 系统概览与方法     |  2.10 页 |
| 实现与公共实验设置 |  0.45 页 |
| RQ1--RQ3 实验设计  |  1.20 页 |
| RQ1 结果           |  0.70 页 |
| RQ2 结果           |  0.95 页 |
| RQ3 结果预留       |  0.55 页 |
| 讨论与局限         |  0.55 页 |
| 结论               |  0.20 页 |
| 合计               |  8.95 页 |

Run 1/Run 2 编译时不得使用缩小字号、压缩行距或修改 VGTC 版心规避页限。

### 7.1 章节架构

1. Introduction
2. Related Work
   - Open and zero-shot 6DoF object perception
   - Pose reliability and render-based verification
   - Temporal consistency and object anchoring in XR
3. EgoAnchor
   - Problem formulation and system overview
   - VCD observation reliability
   - Capture-time world alignment
   - Regime-aware temporal anchoring and lifecycle
4. Implementation
5. Evaluation
   - Common apparatus, platform reference and analysis unit
   - RQ1 protocol
   - RQ2 protocol
   - RQ3 protocol
6. Results
   - RQ1
   - RQ2
   - RQ3 reserved
7. Discussion and Limitations
8. Conclusion

### 7.2 摘要和引言合同

摘要固定为六个语义单元：应用问题；`pose estimate != usable anchor`；系统定义；frame alignment、VCD 与 Static Anchoring；真实 RQ1/RQ2 结果；边界。Run 1 使用明确占位符，不写预期趋势。Run 2 只填写数据支持的结论。

引言固定为五段：研究需求；异步位姿作为锚点时的三个缺口；相关路线为何未共同回答；EgoAnchor 的方法与作用范围；三项贡献和已验证结果。

### 7.3 方法压缩

主文最多保留五个展示公式：异步观测定义、frame-aligned transform、VCD、深度融合、StaticLock 核心证据。ZNCC 展开、全部阈值、Kalman 递推、Hermite 细节和完整生命周期参数不进入主文。

### 7.4 图表预算

最终主文最多五个核心浮动体：

1. teaser 与系统总览共用一幅图；
2. RQ1 双面板图：risk-coverage 与 matched-coverage replay；
3. RQ2 完整周期轨迹图，显示平台参考、NoLock、Full 与 lock/unlock 事件；
4. RQ2 主表，指标为行、四配置为列；
5. RQ3 对象覆盖表，后续填入。

RQ1 不再增加独立大表。每 session/trial 结果、扰动网格、参数表、失败案例和 QC 放独立补充材料或 artifact，不放计入正文页数的附录。

## 8. 学术写作规范

- 论文只写研究问题、方法动机、数学定义、实验协议、结果和边界，不记录调试过程、代码迁移、历史 bug 或参数试错。
- 不使用日常口吻、经验总结、开发日志式叙事或“我们发现一个工程问题后修复”的补丁结构。
- 术语固定为：动态真实物体锚定、观测可靠性、时空对齐、运动估计与平滑、静止锚定、生命周期管理。
- 不称平台控制器为 ground truth；统一写“平台参考位姿”或 `platform reference`。
- 不称 VCD 为概率、置信度校准或姿态准确率。
- 不称 One Euro 或 Kalman 为 motion-agnostic；统一写“无显式区制切换的单区制时序策略”。
- 没有 Pareto 参数扫描时不写“打破 jitter-latency trade-off”。
- 不写“实时当前位姿”“任意物体”“普适泛化”“整体最优”。
- 不把帧数作为独立样本量，不用帧级显著性检验。
- 相关工作中的每项事实、算法归属和平台能力必须由真实引用支持；Run 1 完成 DOI/官方来源核验。

## 9. 目标运行时数据流

```text
Quest frame + frame_id
  -> Python perception candidate
  -> VCD components and score
  -> PoseResult candidate
  -> one shared frame alignment
  -> one shared VCD admission decision
  -> immutable AdmittedObservation
  -> ZOH / One Euro / Ours-NoLock / Ours-Full
  -> synchronized render outputs

Python candidate log + Unity reference/admission/render/event logs
  -> schema-v2 strict loader
  -> RQ1/RQ2 derived datasets
  -> QC, CSV, PDF, LaTeX tables and numeric macros
  -> egoanchor_cn_v6.tex
```

候选观测只对齐一次、判定一次。四个时序变体不得各自执行质量门控、模型相关 jump gate 或独立服务器重获取。

## 10. Python 工程重构

### 10.1 保留并修改

- `reliability/reprojection.py`
- `reliability/depth_alignment.py`
- `reliability/render_quality.py`
- `reliability/pose_quality.py`
- `runtime/runtime_log_writer.py`
- `runtime/eval_session.py`
- 现有感知、传输、协议和日志门面中与新数据流一致的部分

### 10.2 VCD 定义

VCD 固定为：

```text
R = V * G_CD
V = |M_obs intersection M_rnd| / |M_rnd|
```

当前 `observed_area/render_area` 不再作为 `V`，仅保留为诊断量。颜色无有效信号时通过显式 `color_enabled=false` 排除 `C`；不得在正式测试对象上逐对象调阈值。

门控前候选日志至少包含：

```text
session_id, trial_id, scenario, object_id, source_frame_id
capture_mono_ms, candidate_status, candidate_pose_camera
tracking_epoch, backend_state
render_support, mask_precision, mask_iou
color_score, color_enabled, valid_color_pixels
depth_abs_score, depth_struct_score, depth_alpha, depth_score
valid_depth_pixels, depth_inlier_ratio, median_normalized_depth_residual
vcd_score, admission_accepted, admission_reason, config_hash
```

REGISTER、warmup、no-pose 和不完整模态必须显式记录状态，但不得混入完整 VCD 消融分母。

### 10.3 新分析包

删除旧 RQ 编排后建立：

```text
egoanchor/eval/
  contract.py
  cli.py
  io/
    schema_v2.py
    load_session.py
  dataset/
    reference_timeline.py
    candidate_dataset.py
    render_dataset.py
  qc/
    session_qc.py
    trial_qc.py
  rq1/
    perturbation.py
    risk_coverage.py
    zoh_replay.py
    report.py
  rq2/
    segmentation.py
    steady_state.py
    transitions.py
    report.py
  paper/
    figures.py
    latex.py
    manifest.py
```

包外只从 `egoanchor.eval` 及其包级 re-export 导入，不深层导入模块文件。

### 10.4 删除清单

Run 1 在新入口测试通过后删除：

- `egoanchor/eval/research/rq1/`
- `egoanchor/eval/research/rq2/`
- `egoanchor/eval/core/`
- `egoanchor/eval/report/`
- 不再服务新 estimand 的 `lag.py`、`slip.py`、`jump_suppression.py` 和旧 recovery 编排
- 旧测试、README 和脚本入口
- `EgoAnchor_Tools3/` 中与 Unity policy 重复且不进入正式分析的仿真实现；新 RQ1 replay 固定使用 Python ZOH consumer，不复制 StaticLock/Hermite

不为旧数据、旧字段、旧配置标签或旧 CLI 提供兼容。

## 11. Unity 工程重构

### 11.1 中央观测边界

新增目标模块：

```text
Policy/Admission/
  VcdAdmissionController.cs
  AdmissionConfig.cs
  AdmissionDecision.cs
Runtime/
  AlignedObservationBuilder.cs
  AnchorObservationHub.cs
```

`AlignedObservationBuilder` 只执行一次 frame alignment。`VcdAdmissionController` 对候选执行结构有效性检查与固定 VCD 阈值判定。`AnchorObservationHub` 把同一个不可变 `AdmittedObservation` 分发给四个 estimator。

删除每个 variant 内的质量门控、预测相关 jump gate、低分重获取计时和服务器请求。服务器重获取由中央 admission/lifecycle 控制器统一决定；四变体只能被动消费同一感知流。

### 11.2 固定四种时序策略

用 `Policy/Temporal/` 替换任意 model × smoothing 自由组合：

```text
IAnchorTemporalEstimator.cs
ZohEstimator.cs
OneEuroEstimator.cs
KalmanHermiteEstimator.cs
TemporalAnchorPolicy.cs
```

定义：

- *ZOH*：保持最新 admitted world observation。
- *One Euro*：每个 admitted observation 按其 measurement timestamp 更新一次；render tick 只读取并保持最近滤波输出，不把 held target 重复伪装成新观测。位置采用三通道滤波，旋转采用最短四元数路径上的增量 SO(3) 滤波；位置和旋转分别配置 `min_cutoff`、`beta` 与 `d_cutoff`。
- *Ours-NoLock*：常速度 Kalman、延迟目标控制和 Hermite 插值，不启用 StaticLock。
- *Ours-Full*：与 NoLock 使用相同 Kalman-Hermite estimator，只增加 StaticLock decorator。

Full 未锁定且不处于解锁过渡时，Full 与 NoLock 的内部 estimator 状态必须逐帧一致。

### 11.3 统一定量场景

删除：

- `Assets/Scripts/EgoAnchor/Eval/RQ1/`
- `Assets/Scripts/EgoAnchor/Eval/RQ2/`
- `Assets/Scene/EgoAnchor-RQ1.unity`
- `Assets/Scene/EgoAnchor-RQ2.unity`

新建：

```text
Assets/Scene/EgoAnchor-Quantitative.unity
Assets/Scripts/EgoAnchor/Eval/Scenario/
Assets/Scripts/EgoAnchor/Eval/Recording/
Assets/Scripts/EgoAnchor/Eval/UI/
```

统一场景键位：

| 按键   | 行为                              |
| ------ | --------------------------------- |
| `F7` | 开始 session                      |
| `1`  | 开始 static_observation trial     |
| `2`  | 开始 partial_occlusion trial      |
| `3`  | 开始 stop_go_translation trial    |
| `4`  | 开始 stop_go_rotation trial       |
| `O`  | 记录 occlusion_start              |
| `V`  | 记录 target_visible_again         |
| `0`  | 结束当前 trial                    |
| `F8` | 停止 session、flush 并写 manifest |

UI 必须显示 session、scenario、trial 编号、时长、四变体配对状态、最新 admitted observation ID、参考新鲜度、缺失事件和 dropped rows。状态文字只服务操作，不进入论文。

### 11.4 录制器拆分

以职责拆分旧 `EvalRecorder`：

```text
EvalCaptureRecorder.cs
EvalAdmissionRecorder.cs
EvalRenderRecorder.cs
EvalEventRecorder.cs
EvalScenarioController.cs
EvalSchemaV2.cs
```

所有 logger 使用有界后台队列；manifest 分别记录各日志 dropped rows 和峰值深度。正式数据要求全部 `dropped_rows=0`。

## 12. Schema v2 数据合同

每个 session 目录固定为：

```text
data/eval/<session_id>/
  manifest.json
  python_candidates.jsonl
  unity_reference.jsonl
  unity_admission.jsonl
  unity_render.jsonl
  events.jsonl
  audit_samples/
```

`unity_reference.jsonl` 以 Unity 渲染/追踪更新频率记录控制器平台参考轨迹和新鲜度。RQ1 使用该轨迹对 `capture_mono_ms` 图像时间代理执行位置插值和 quaternion SLERP，并记录插值跨度、参考年龄和失败原因。不得将 JPEG 完成时刻或 PoseResult 到达时刻称为曝光时刻。

`unity_render.jsonl` 每行对应一个 `render frame × variant`，至少包含：

```text
render_mono_ms, unity_frame, scenario, trial_id, variant
latest_candidate_id, latest_admitted_id
has_output_pose, output_pose
has_display_pose, display_pose
runtime_state, static_lock_state, transition_state
reference_pose_render, reference_fresh
```

`events.jsonl` 至少包含：

```text
session_start, session_stop, trial_start, trial_end
occlusion_start, target_visible_again
reacquire_requested, reacquire_acknowledged
first_candidate_after_reacquire, first_admitted_after_reacquire
first_stable_anchor, static_lock_enter, static_lock_exit
```

reference motion onset/stop 由正式分析按预注册速度迟滞规则推导，不用人工事件替代。

manifest 必须包含：

- schema 版本；
- Git 工作树标识，不要求 commit；
- Unity、Quest、SDK、Python、CUDA、模型与 GPU 版本；
- 相机内参和控制器到模型外参；
- VCD、One Euro、Kalman-Hermite、StaticLock 的完整参数快照；
- 每组参数和总体配置 hash；
- calibration/formal 标记；
- 所有日志写入统计。

## 13. RQ1 正式实验合同

### 13.1 数据来源

RQ1 使用控制器定量轨中自然产生的 TRACK 候选：清晰静止、主动头动、部分遮挡、视野截断、平移和旋转。无 pose 帧只进入 availability 描述，不进入基于评分的风险判别分析。

历史 session 或 Run 1 的固定开发数据只用于冻结阈值、权重和覆盖率；用户新采 session 全部作为 held-out formal data。

### 13.2 评分消融

正式分析计算：

- `V`
- `V·D`
- `V·C`（补充材料）
- `VCD-Full`

深度内部的 `D_abs` 与 `D_struct` 消融进入补充材料。VSD 不作为本轮必做项。

### 13.3 指标

- 平移和旋转分别计算，不合成为无量纲总误差。
- AURC 基于 accepted candidate 的平均损失，积分范围预先固定为 70%--100% coverage。
- 在 70%、80%、90%、100% coverage 报告 P95。
- 正式运行点报告实际 acceptance coverage、accepted P95、严重错误率和低误差误拒率。
- 分数并列采用稳定且与误差无关的 `source_frame_id` 顺序。
- random ranking 和 oracle ranking 只作解释边界。

### 13.4 ZOH replay

固定候选流分别运行 NoGate、V-only、VD 和 VCD gate，统一使用简单 ZOH consumer。比较显示 P95、大幅更新次数和输出覆盖率。不模拟真实 tracking epoch 改写，不声称离线 replay 评价闭环 reacquire。

### 13.5 可控扰动

Run 2 从 `audit_samples` 生成固定随机种子的候选扰动，位置约 10/20/40/80 mm，旋转约 5/10/20/40 degrees。该实验只检查分数对几何错位的单调性，不作为自然失败检测的主证据；同一源帧的多个扰动按簇处理。

### 13.6 RQ1 Go/No-Go

- 若 VCD 在多数 formal session 的 AURC 未优于 `V`/`V·D`，C2 降级。
- 若 replay 收益在 matched coverage 后消失，不写 gate 的下游收益。
- 若 capture-time reference 插值失败率超过预注册阈值，相关 trial 整体补采，不按误差删帧。

## 14. RQ2 正式实验合同

### 14.1 Trial 结构

每个平移和旋转 trial 均包含：前静止 5 s；起动；持续运动 8--12 s；停止；后静止 5 s。按键只标 trial 包络，阶段边界由平台参考速度、迟滞和持续时间离线推导。

Static trial 维持 30--45 s，控制器固定，操作者执行规定范围内的自然头动。Occlusion trial 用于 RQ1 失效候选与恢复诊断，不作为 StaticLock 因果证据。

### 14.2 正式采集量

目标为 5 个独立 formal session，最低不得少于 3 个。每个 session：

- static_observation：2 trials；
- partial_occlusion：2 trials，每 trial 至少 3 次遮挡/重新可见循环；
- stop_go_translation：3 trials；
- stop_go_rotation：3 trials。

独立 session 需重新启动 Python runtime 和 Unity session，并完成一次新 tracking epoch。每个 session 的标定、环境、操作员和时间写入 manifest。

### 14.3 指标

静止：display position/rotation HP-RMS、绝对误差 med/P95、锁定漂移、误锁/误解锁、输出覆盖率。

转换：GT onset 到 visible response、GT onset 到 lock exit、GT stop 到 lock enter、起动后首秒 peak/integrated error、停止后 overshoot 和 settling time。未解锁/未重锁必须计为失败或删失，不得静默排除。

持续运动：平移/旋转 med/P95、render-update ratio、输出覆盖率、运动期仍 locked 的时间占比。

每个 trial 都正式比较四配置。`Ours-Full - Ours-NoLock` 是 StaticLock 的主要因果 estimand；`Ours-Full - One Euro` 是完整系统对外部标准的比较；`Ours-NoLock - One Euro` 比较两种无显式区制切换的时序策略；ZOH 量化离散保持的连续性代价。

### 14.4 统计层级

先在 `session × trial × variant` 内计算指标，再生成 trial 配对差，最后按 session 汇总。主文展示 session 级点、median 和 range；渲染帧只表示时间覆盖。只有 session 数量和预注册条件允许时才报告层级 bootstrap CI，并明确其探索性。

## 15. 自动 QC 与用户采集手册

Run 1 创建中文手册：

`2026-EgoAnchor/RQ12_DATA_COLLECTION_GUIDE.md`

手册必须包括：

1. 硬件摆放、网络、照明、控制器模型和外参检查；
2. Python、NATS、Unity/Quest 的启动顺序；
3. 场景 UI、按键和 trial 动作的逐步说明；
4. smoke session 的固定流程；
5. 五个 formal session 的采集清单；
6. 遮挡、平移、旋转的动作标准；
7. 每 trial/session 结束后的 QC 命令与通过标准；
8. 常见失败、是否重录和如何安全停止；
9. 数据目录、inventory 生成和交回方式。

计划中的 CLI：

```powershell
cd EgoAnchor_Python
pixi run python -m egoanchor.eval.cli qc --session-dir data/eval/<session_id>
pixi run python -m egoanchor.eval.cli inventory --root data/eval --output data/eval/collection_inventory.json
```

QC 必须检查：schema、session ID 配对、四变体完整率、candidate/admitted ID 一致性、事件完整性、参考新鲜度与插值跨度、速度范围、tracking epoch、配置 hash、日志 dropped rows 和 trial 时长。命令以非零退出码表示不可用于正式分析。

用户先完成一个 smoke session。只有自动 QC 全部通过才继续 formal sessions。硬件相关 smoke 失败是“两次运行”目标的唯一例外：不得在未知坏 schema 上继续采集正式数据。

## 16. 自动分析、图表和 LaTeX 回填

Run 1 建立稳定入口：

```powershell
pixi run python -m egoanchor.eval.cli rq1 --manifest data/eval/formal_sessions.toml
pixi run python -m egoanchor.eval.cli rq2 --manifest data/eval/formal_sessions.toml
pixi run python -m egoanchor.eval.cli paper-results --manifest data/eval/formal_sessions.toml
```

输出固定为：

```text
2026-EgoAnchor/generated/results_macros.tex
2026-EgoAnchor/generated/rq1_vcd_summary.tex
2026-EgoAnchor/generated/rq2_temporal_summary.tex
2026-EgoAnchor/figs/rq1/vcd_risk_coverage.pdf
2026-EgoAnchor/figs/rq2/temporal_cycle.pdf
EgoAnchor_Python/data/paper/<analysis_id>/
```

主稿只通过 `\input{generated/...}` 和数字宏引用结果。脚本同时写 analysis manifest、输入 session hash、配置 hash、纳入/排除计数和生成版本。正文不得手工复制数字。

## 17. Run 1 任务清单

Run 1 在无中途人工确认的情况下按以下顺序执行：

1. 更新 AGENTS.md，使本计划成为权威路线。
2. 冻结术语、三项贡献、RQ、estimand、配置标签和论文页数。
3. 用历史数据或预声明默认值冻结 VCD、One Euro、Kalman-Hermite 和 StaticLock 的开发参数；正式数据后不得调参。
4. 修正 VCD 定义与诊断日志，补单元测试。
5. 建立一次 alignment 和一次 admission 的公共观测链，删除 per-variant gate/reacquire。
6. 用固定四 estimator 替换旧自由组合接口；建立 Full/NoLock 状态一致性测试。
7. 重建统一定量场景、事件控制、录制器、UI 和 schema-v2 manifest。
8. 删除旧 RQ1/RQ2 Unity 组件、场景、Python 编排、重复工具和兼容入口。
9. 重建 schema-v2 loader、reference builder、QC、RQ1/RQ2 分析、图表和 LaTeX 导出。
10. 创建合成 fixture 和无 Quest dry-run，确保命令可执行。
11. 重写 `egoanchor_cn_v6.tex` 的标题、摘要占位版、引言、相关工作、方法、实现、RQ1--RQ3 设计、讨论边界和结论占位版；删除旧结果。
12. 核验并补齐真实参考文献；替换 teaser 占位框；结果图使用固定占位接口。
13. 编译主稿并控制在 8.4 页以内。
14. 编写并校对 `RQ12_DATA_COLLECTION_GUIDE.md`。
15. 运行全部验证，输出 Run 1 handoff 清单；不提交 Git。

Run 1 验收：

- Python 与 Unity 编译、测试通过；
- 新 scene 和四 estimator 构建通过；
- synthetic session 的 QC、RQ1、RQ2、paper-results 全链路通过；
- 主稿无旧结果、无虚构数字、无未定义引用，页数不超过 8.4；
- 操作手册包含用户完成采集所需的全部步骤；
- Git 工作树只包含可审查的未提交改动。

## 18. 用户采集阶段

用户严格按手册执行：

1. 运行 smoke session 和 QC；
2. 在 QC 通过后完成目标 5 个 formal session；
3. 每个 trial/session 后立即运行 QC，不通过则当场重录；
4. 生成 `collection_inventory.json`；
5. 将完整 session 目录保留在共享工作区并通知开始 Run 2。

用户不修改分析规则、阈值、配置标签或论文数字。

## 19. Run 2 任务清单

1. 读取 inventory，核对 formal/calibration 标签、配置 hash 和 session 独立性。
2. 运行全量 QC；任何失败先输出精确补采清单，不通过删帧或插值掩盖。
3. 构建 capture-time reference 和候选数据集，生成纳入流程审计。
4. 完成 RQ1 risk-coverage、matched ZOH replay、扰动诊断和失败案例。
5. 完成 RQ2 静止、转换、持续运动指标和 Full/NoLock 配对汇总。
6. 生成 CSV、图、LaTeX 表、数字宏和 analysis manifest。
7. 依据证据执行 claim downgrade，不强迫结果符合 H1/H2。
8. 填写 RQ1/RQ2 结果、摘要、讨论、局限和结论中的真实数字。
9. 执行代码-公式-参数-图表-论文一致性审计和模拟审稿。
10. 编译 XeLaTeX，确认正文不超过 8.4 页并保留 RQ3 空间。
11. 运行最终测试、Code Simplifier 和文档审查；不提交 Git。

Run 2 验收：

- RQ1/RQ2 每个数字可追溯到 formal manifest 与 CSV；
- 图表与 LaTeX 无手工数字；
- 所有主张都有对应证据或已降级；
- 平台参考、单操作员、共享追踪、外部 GPU 和 post-capture lag 边界完整；
- RQ3 仍为明确延期状态，没有虚构结果；
- 主稿和验证命令通过。

## 20. 验证命令

Python：

```powershell
cd EgoAnchor_Python
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src
```

Unity：

```powershell
dotnet build "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

协议变更时：

```powershell
cd EgoAnchor_Python
pixi run pwsh -File ..\EgoAnchor_Protocol\tools\generate_proto.ps1
```

论文：

```powershell
cd 2026-EgoAnchor
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
pdfinfo pdf\egoanchor_cn_v6.pdf
```

## 21. 正式停止条件

出现以下情况时不得继续填充正向结论：

- VCD 定义、代码和日志字段不一致；
- 正式数据使用了测试集调参；
- 四变体 admitted observation ID 不一致；
- capture-time reference 无法可靠重建；
- 任一正式日志 dropped rows 非零；
- lock/unlock 或遮挡事件缺失，导致目标指标不可识别；
- session 数量低于最低要求；
- 结果只在帧池化后成立，在 session 级不稳定；
- 论文超过页限或必须靠版式压缩容纳；
- RQ3 未回答但投稿稿仍保留 RQ3 或多对象泛化结论。

## 22. 最终边界

两次运行完成后，EgoAnchor 应形成一条可审计的论文证据链：候选观测、VCD 证据、公共接纳决定、四种时序输出、平台参考、事件、分析数据、图表和 LaTeX 数字逐层可追溯。工程代码不承担旧实验兼容，也不保存与论文主张无关的并行入口。
