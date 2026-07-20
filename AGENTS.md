# AGENTS.md

后续 AI 接手本仓库任务时，必须先阅读文件顶部的 **用户手动维护要求**。未阅读前不得修改代码。

<!-- USER-MAINTAINED-REQUIREMENTS:BEGIN -->

## 用户手动维护要求

本区由用户手动维护，放在文件顶部，方便查看和修改。后续 AI 只能读取、遵循和引用，不得自行修改、删减、重排、润色、合并或迁移本区内容。只有用户明确要求修改时，才可以改动本区，并且只改用户指定的内容。

1. Python 侧按包级入口导入，不深层导入到具体模块文件。包内可以使用 `from .image_utils import fit_to_size, stack_stereo` 这类显式 re-export；包外使用 `from egoanchor.algorithms import ...`，不要写成 `from egoanchor.algorithms.xxx import ...`。不要使用包级懒导出。
2. 代码需要有充分的中文说明。`.toml` 配置的每个参数都要在同一行末尾写中文注释；类、成员变量和每个方法也要补充中文说明。
3. 命名保持清楚、克制，不要为了"完整"把名字写得过长。
4. 修改代码前先从项目整体判断影响范围，检查模块配合、引用关系和架构边界。不要只做局部补丁，也不要零散修补。
5. 先读懂项目和计划，再严格按计划实现代码。发现计划与项目事实冲突时，及时指出并说明影响。过程中有任何问题请及时和我讨论交流，如果遇到任何不合理的事情立刻和我报告。
6. 重构时不要兼容已废弃的旧代码、旧接口或旧路径。
7. 使用 Code Simplifier 优化项目代码；处理文档和语言表述时使用 humanizer-zh。
8. 处理复杂或大型任务时，请使用子智能体辅助，加快梳理、审查和验证。
9. 改动时直接在我的这个git分支改动，我能看见改动了哪些。我git有备份没有关系，不用担心
10. 每次操作完后记得更新AGENTS.md
11. 注意论文当前主稿路径是 `2026-EgoAnchor/`，使用 LaTeX 编写；当前中文主稿为 `egoanchor_cn_v6.tex`。修改后使用本机 XeLaTeX（推荐 `latexmk -xelatex`）编译检查通过。

<!-- USER-MAINTAINED-REQUIREMENTS:END -->

本文件只记录当前事实、长期约束和已冻结路线。实验过程、旧 session 数字、迁移 hash、调参记录和一次性排障不写入本文件。

## IEEE VR 2027 论文路线

当前中文主稿定位为系统论文。路线以 `2026-EgoAnchor/egoanchor_cn_v6.tex` 和 `2026-EgoAnchor/plan.md` 的系统论文框架为准；旧 `IEEEVR2027_RQ12_REFACTOR_PLAN.md` 文件当前不存在，不再作为权威计划引用。

中心论点：开放视觉后端输出的异步 6DoF pose 不是可直接消费的 MR anchor。EgoAnchor 将低频、异步、质量不均的视觉位姿观测，转换为消费级混合现实应用可持续使用的世界系对象锚点。

论文主叙事固定为 `pose estimate != usable MR anchor`：平台原生支持范围只解释外部感知为何必要，零样本视觉感知只说明给定模型的更多刚体为何可被定位。两者不能被写成核心贡献；核心问题是如何为异步视觉观测恢复时间语义、判断是否接纳，并控制持续 MR 锚点的逐帧输出与生命周期。

三项贡献：

1. 感知后端与锚定运行时解耦的端到端对象锚定系统，以及基于 `frame_id` 的采集时刻世界对齐。
2. 观测到锚点运行时：VCD 观测接纳、Kalman-Hermite 时序合成、显式静止锚定和生命周期管理。
3. 系统实现与分层评估：端到端系统表征、关键组件归因和计划中的跨对象任务层用户研究。

论文外部不再使用 RQ1/RQ2/RQ3 作为顶层结构。当前实验组织为：

- **实验一：端到端系统表征**。在静止目标与主动头动、起停 6DoF、持续平移/旋转、遮挡恢复条件下，比较 *Arrival-Hold*、*Capture-Hold*、*One-Euro Anchor* 与 *EgoAnchor* 的系统行为。
- **实验二：系统设计归因**。在同一日志格式和平台参考下关闭单一设计，归因采集时刻世界对齐、VCD 观测接纳、时序合成和静止锚定的贡献与代价。
- **实验三：跨对象用户研究**。比较 *One-Euro Anchor* 与完整 *EgoAnchor* 在日常刚性物体对象附着任务中的表现与体验收益；当前只冻结设计，实验一/二完成后再启动正式采集。

VCD 的三个语义层次不得混淆：

- 方法输出 `[0,1]` 连续可靠性评分。
- 运行时以冻结阈值执行 admission。
- 离线按分数诱导候选顺序，使用 risk-coverage/AURC 检验评分的风险判别性。VCD 本身不是排序算法，也不是位姿正确概率。

系统配置命名：

- *Arrival-Hold*：到达时刻复合、接受全部合法候选、零阶保持。
- *Capture-Hold*：采集时刻世界复合、接受全部合法候选、零阶保持，用于隔离 frame alignment。
- *One-Euro Anchor*：采集时刻世界复合、基本有效性检查、OneEuroModel 自适应滤波与基于平滑速度的逐渲染帧外推。
- *EgoAnchor*：采集时刻世界复合、VCD 接纳、Kalman-Hermite 合成、显式静止锚定和生命周期管理。
- 组件消融使用 `EgoAnchor w/o <component>` 风格命名，不再恢复旧 RQ 命名或旧 CLI 兼容层。

IEEE VR 2027 正文、图和表最多 9 页，参考文献最多另占 2 页。Run 2 完成实验一/二后正文不得超过 8.4 页，为实验三用户研究保留空间。实验三是已规划的任务层效用验证，但当前先搁置，待实验一/二完成后再启动正式采集。

两次执行边界：Run 1 完成实验一/二采集前全部工程、论文框架、QC、分析骨架和中文采集手册，并保留实验三设计；用户完成功能自检与实验一/二正式采集；Run 2 完成实验一/二分析、图表和论文回填。本轮按用户明确要求，每个 Task 验证后独立提交并推送。

## 诚实边界

- “纯视觉”只修饰物体位姿估计链路；系统仍依赖外部消费级 GPU、局域网和头显平台追踪。
- 系统需要目标三维模型，不得声称适用于任意对象。
- 控制器 pose 是平台参考位姿，不是外部光学真值；它与头显共享追踪系统，会隐藏共模世界漂移。
- frame alignment 只校正相机采集/到达时刻错配，不补偿采集后的物体运动。
- 单操作员、多 session 的帧只表示时间覆盖，不作为独立样本量。
- Meta、Apple 与专用追踪附件只作为论文中的能力定位对象；相关工作、紧凑能力表和讨论必须以官方或同行评审来源说明其对象绑定语义与前提。跨平台数值实验不是实验一/二的必做证据，只有同一对象、统一参考和相同协议均成立且不影响主实验时才可作为描述性上下文，不能支撑核心贡献。

## 主线目录

| 目录 | 职责 |
|---|---|
| `EgoAnchor_Python/src` | 图像接收、感知、VCD、通信、评估分析 |
| `EgoAnchor_Unity/Assets/Scripts/EgoAnchor` | Quest 采集、时空对齐、公共 admission、四时序策略、显示与录制 |
| `EgoAnchor_Protocol` | Proto 与 subject 唯一来源 |
| `2026-EgoAnchor` | 中文主稿、VGTC 模板、图表与权威重构计划 |

旧 RQ1/RQ2 Unity 脚本、场景和 Python 分析包已删除，不得恢复；`EgoAnchor_Tools3` 仍属于 Run 1 删除范围，不再扩展。正式评估入口只使用实验一/二命名。

## 不可破坏的系统约束

系统使用三条语义平面：

| 平面 | 传输 | 方向 | 内容 |
|---|---|---|---|
| Data | ZMQ PUB/SUB | Unity -> Python | `QuestStereoFrame`、`QuestCameraInfo`，multipart，latest-drain |
| Message | NATS Core pub/sub | Python -> Unity | `PoseResult`、状态、heartbeat |
| Command | NATS request/reply | Unity -> Python | reset、reacquire、control，`request_id` 幂等 |

- Python 只输出 camera-space pose；Unity 用 `frame_id` 回查 image-time proxy camera pose 并合成 world anchor。
- 不得用 PoseResult 到达时的 HMD pose 代替发送帧 pose。
- 业务代码不手写 subject；Python 从 `egoanchor.protocol` 包级入口导入，Unity 使用 `SubjectNames`。
- Proto 字段号不得重排；删除字段时同时 `reserved` 字段号和字段名。
- Unity -> Python ZMQ 端口固定为 `15557`。
- NATS handler 只负责 parse、validate、dedup、enqueue、ack；`TrackingRuntime` 顺序拥有 pipeline/GPU 状态。
- 重获取只有一个中央 owner；四个时序变体不得分别改写共享 Python 感知状态。
- Unity 的正式 session 配对可从 Python `PoseResult`、状态或持续 `ServerHeartbeat` 的 header 获取 `session_id`，不得等待首个 pose；两套采集场景的 NATS 初次连接重试必须开启，使 Python 与 Unity 的启动先后无关。

## Run 1 目标架构

Run 1 目标是完成实验一/二采集前工程与分析骨架。详细工程实现计划见 `2026-EgoAnchor/experiment_1_2_implementation_plan.md`，该计划是当前实验一/二实现的执行入口。正式链路：

```text
PoseResult candidate
  -> frame_id-based capture-time alignment
  -> optional VCD admission
  -> Arrival-Hold / Capture-Hold / One-Euro Anchor / EgoAnchor / component ablations
  -> synchronized display and logs
```

- *Arrival-Hold* 用到达时刻复合和零阶保持，作为直接消费异步视觉位姿的朴素系统基线。
- *Capture-Hold* 用采集时刻复合和零阶保持，作为 Arrival-Hold 与 One-Euro Anchor 之间的时间对齐桥接配置。
- *One-Euro Anchor* 用采集时刻复合、基本有效性检查、OneEuroModel 与 PredictivePassthroughStrategy，作为逐帧预测的标准滤波锚定基线。
- 当前正式场景的 One-Euro 参数按米制位置与约 10 Hz 候选重新标定为位置 `(minCutoff=0.8, beta=6, derivativeCutoff=2)`、旋转 `(1, 1, 2)`；既有 formal 数据若仍来自旧 RawPassthrough 配置，不得与新配置混合分析。
- OneEuroModel Inspector 将平移与旋转参数分为独立 Header；预测透传的候选到达回拉仍属于无残差融合策略的预期行为，不应仅通过提高 cutoff 消除。
- *EgoAnchor* 用采集时刻复合、VCD 接纳、Kalman-Hermite 合成、显式静止锚定和生命周期管理。
- 组件归因通过关闭单一设计实现：w/o capture-time alignment、w/o VCD、w/o temporal synthesis、w/o StaticLock。
- 模型相关 per-variant jump gate 不进入正式比较。

## Run 2 离线分析架构

实验一/二正式数据采集已经完成。当前离线分析以 GPT corrected-newdata-v4 包为呈现基线，执行入口固定为 `egoanchor.eval.cli` 的 `qc`、`preprocess` 和 `build-paper`：

```text
schema-v2 task directory
  -> qc / preprocess -> 五本完整 XLSX
  -> build-paper -> GPT v4 指标、图、表和 egoanchor_cn_v6.tex
```

- 原始 task 目录保留为只读冷归档；Stage 1 成功后，后续阶段不得再读取 JSON/JSONL。
- **Stage 1（`preprocess`）** 只读取原始 task 目录的 JSON/JSONL，执行完整 QC 并逐 task 原子发布 XLSX；不得把 XLSX 之前的任何中间文件作为后续输入。
- Stage 1 的 schema-v2 reader 按固定文件集合流式解析 JSONL，保留来源行号与行 SHA-256；只读硬 QC 检查八 runtime 矩阵、主外键、生命周期、事件合并、warmup reference 和两端 writer 停止态统计，未消费 candidate 仅作为 latest-only 警告。
- `build-paper` 只读取五本 Stage 1 完整 XLSX，计算 GPT v4 指标并直接发布两张 PDF/PNG、两张 TeX 表和中文主稿；它不得回读 raw JSON/JSONL，也不得改写 XLSX。
- 旧 Stage 2/3 分析与发布源码已删除；GPT v4 代码位于 `egoanchor.eval.gpt_v4`，不保留旧入口兼容层。
- 统一分析 CLI 只提供 `qc`、`preprocess`、`build-paper`；QC 或论文输入契约失败时返回退出码 2，禁止生成正式论文产物。
- 统计单位固定为 event/segment，不是 frame；先在 session/trial/event/variant 内计算，再做同 event/segment 配对和 session 汇总。
- 每个场景单独报告，禁止跨场景混池计算全局总分或总排名。
- 实验一发布 `experiment1_corrected_newdata` 三面板图，实验二发布 `experiment2_corrected_newdata` 左三右一归因图；图表样式直接复刻 GPT v4，遮挡只投影 `occlusion_started` episode，图内最小字号固定为 7 pt。
- `egoanchor.eval.contracts` 的 workbook 契约继续作为 Stage 1 Excel 的唯一结构来源，完整保留对齐原始位姿、时间、reference、render 和事件字段；GPT v4 参数唯一入口是 `egoanchor/eval/config/gpt_v4.toml`，每个参数同行保留中文注释。
- Stage 1 workbook writer 先执行全量硬 QC，再在目标目录写临时 XLSX；写出后独立回读检查分片、表头、行数、类型、主外键、来源集合摘要和超长值，并在替换前复算输入来源哈希，全部通过才原子替换正式文件。单 sheet 超限时使用 `_001`、`_002` 分片；未知 JSONL 字段进入 `row_kv`，超长值进入 `large_values`，不得截断或静默丢弃。内部大值 marker 必须精确绑定来源分片；经过转义的同形原始文本仍按字面量回读。每个物理 sheet 冻结首行，并按列语义写入稳定列宽。Windows 下删除临时文件和原子替换遇到短暂共享锁时有界重试，重试耗尽仍保留旧正式文件并返回文件系统错误。
- `preprocess` 在写出前检查整批固定源文件、task 编号和输出边界，再对整批执行只读 QC；任一 task 的 QC 失败时不开始发布。缺目录或缺固定源文件返回 1，schema/QC/命名和输出边界错误返回 2。正式工作簿使用 `task_N_complete.xlsx`，执行时通过 `--code-version` 写入实际分析代码版本；本地可重建的 `data/analysis/` 不进入 Git。
- 主稿由 `build-paper` 从 GPT v4 模板和当前 XLSX 指标完整写出；表格内容内联，PDF 图保持外部依赖。
- 当前中文主稿及自动发布图统一使用 `2026-EgoAnchor/figures/`，不得恢复或新增活动的 `2026-EgoAnchor/figs/` 依赖。
- `build-paper` 的审计产物固定写入 `data/analysis/gpt_v4/`，包括输入 workbook SHA-256、实验一汇总 CSV、capture alignment CSV 和运行性能 JSON；这些派生文件不进入 Git。
- 面向新采集批次的手动复现步骤固定记录在 `2026-EgoAnchor/experiment_1_2_analysis_reproduction_manual_zh.md`；它要求替换五个 raw task 目录后从 `qc`、`preprocess` 执行到 `build-paper` 和 XeLaTeX。
- 正式论文数据不得按场景或指标从不同采集批次择优拼接。替代批次必须以同一代码和 TOML 完整重建五个任务，逐场景报告 event 数、缺失率、median[IQR] 与护栏，并确保 manifest 的配置 hash 和 Git commit 能区分全部生效数值参数；技术 QC 通过不能替代参数 provenance 和关键场景覆盖门槛。
- GPT v4 reader-facing 表格最多保留三位小数，完整精度保存在 `data/analysis/gpt_v4/data/`；实验一按系统报告八项行为属性，实验二按组件报告启用、关闭和配对效应。

## Python 关键约束

入口：`EgoAnchor_Python/src/run_server.py` -> `egoanchor.app.tracking_server`。配置位于 `src/egoanchor/config/defaults.toml` 与 `objects.toml`。

- 默认分割器是 `yoloe26`；SAM3 只能显式启用。
- 评估模式写 `data/eval/<session_id>/` 并通过 header 与 Unity 配对；普通模式写 `data/runtime_logs/`。
- VCD 目标公式为 `R = V * G_CD`，其中 `V = |M_obs intersection M_rnd| / |M_rnd|`。正式采集前必须确保公式、代码和日志一致；当前面积比旧实现不得进入正式结果。
- `color_reprojection < 0` 表示颜色信号不可用，应从几何核排除，而不是视作坏 pose。
- 深度评分保留绝对与结构分量 `D = (1-alpha) D_abs + alpha D_struct`；Run 1 日志必须暴露消融所需分量。
- Python 评估模式的 `RuntimeLogWriter` 已将候选行映射为严格 `PythonCandidateRow`，颜色不可用写入 `null` 并保留解释 flag；runtime 事件与候选行分写固定 schema-v2 文件。
- Python candidate ID 使用 `session_id:frame_id:frame_local_seq`；`RuntimeLogWriter` 关闭时把 candidate/event 的真实 `rows_written`、`dropped_rows` 和 `log_write_failures` 写回 `python_session.json`，供最终 manifest 汇总，Unity 不得伪造 Python 丢行统计。
- `egoanchor.eval` 包级入口只导出 schema-v2、QC 和 Stage 1 workbook 基础设施；GPT v4 论文分析必须从 `egoanchor.eval.gpt_v4` 或离线 CLI 显式进入，运行时服务不得因论文绘图依赖加载失败。
- `CutieMaskTracker` 不直接导入 `torchvision.transforms.functional.to_tensor`，避免 Windows 图像 DLL 冲突。
- 生成代码、`*_pb2.py` 和协议副本不手改。

关键 ownership：`config/` 不导入模型/网络；`transport/` 只管传输；`routing/handlers` 不碰 GPU；`runtime/tracking_runtime.py` 是 pipeline owner；`perception/quest_pose_pipeline.py` 组合视觉模块；`reliability/` 计算 VCD；新 `eval/` 只处理 schema-v2、QC、实验一/二和论文产物。

## Unity 关键约束

- `MeasurementTimeSeconds` 属于采集时间轴，用于运动估计与静止锚定；生命周期 freshness 使用到达/生命周期时间轴。不得用 capture time 刷新 stale/lost。
- `has_output_pose` 表示 runtime 是否有输出；`has_display_pose` 表示用户实际看到的 Transform，包括 hold-last。显示误差使用 display pose，输出覆盖率使用 output pose。
- hold-last 显示行从 `DynamicObjectAnchor.LastAppliedFrameId` 保留实际来源帧；只有从未应用或已隐藏的显示才允许 `source_frame_id=-1`。
- 平台控制器参考 pose 只从 `EvalRecorder.groundTruth` 绑定的 Transform 读取。`controller_right` 必须绑定 `OVRCameraRig/OVRInteractionComprehensive/OVRControllerVisualRight/OVRControllerPrefab`，对应 `OVRControllerHelper.m_controller=RTouch` 和 `EvalRecorder.gtController=RTouch`；不得绑定名称相似但不会更新的静态节点。参考对象激活且平台报告可追踪时更新 world pose；失活或隐藏时无限期保持最后一次激活 pose，重新激活后继续更新。激活状态只写入 `reference_pose_fresh/reference_pose_keep_alive` 并在实时板显示 `ACTIVE/HELD`，不得把 OVR 状态当作另一套 pose 来源，也不得因失活停止计算实时差异或让正式日志参考失效。正式 session 启动前必须观察到参考对象至少 1 cm 平移或 5 度旋转；manifest 写入参考 Transform 路径、控制器类型和预检结果，未通过时禁止启动。
- StaticLock tether 计算 `obsConsensus -> anchorOrigin`，不得改成单帧观测或 `lockedPose`。
- 头动期间不冻结真实运动证据；`headSettleSeconds` 只覆盖头停后的沉降窗口。
- 距离自适应只放大位置通道；旋转 tether 必须高于旋转噪声地板。
- `EvalLog` 使用有界后台队列；正式 session 的所有日志 `dropped_rows` 必须为 0。
- Unity `EvalSession`/`EvalRecorder` 已固定写入 `manifest.json`、`unity_reference.jsonl`、`unity_admission.jsonl`、`unity_render.jsonl` 和本机独占的 `unity_events.jsonl`；render 为 tick×variant 长表，admission 由每个 runtime 的实际处理结果产生。Python 远端独占写入 `python_events.jsonl`。Mutagen 同步完成后，`qc`/`preprocess` 的 Stage 1 事件物化入口在总表缺失时确定性发布 `events.jsonl`；已有总表只验证，不覆盖。两端不再通过跨机器 `.lock` 共同追加同名文件。
- Unity admission 与 event 行已覆盖 schema-v2 必填时间、策略、上下文和 payload 字段；candidate ID 使用 `session_id:frame_id:frame_local_seq`，同一 `PoseResult` 的多 runtime 回调共用标识。
- Unity manifest 将 `run_kind` 固定写为 `formal`，不再暴露运行类型选择；同时写出自动配置哈希、对象、版本、无时长上下界的实验/场景计划、`completed_tasks` 和真实 Unity writer 统计。`completed_tasks` 按任务编号记录本 session 最终未作废的 trial，schema-v2 QC 必须与 lifecycle events 重新推导的完成集合核对。`frozen_parameter_set_id` 自动复用整体 `config_hash`，`operator_id` 固定为匿名单操作员，run mode 与 protocol 由代码生成，Git commit 为可选审计字段。Formal 启动不要求现场填写元数据，仍严格要求 Python session 配对和非空变体配置哈希。Python candidate 及跨端 events 总统计在 Unity 停止时明确标为 pending，必须在 Python 停止并同步 `python_session.json` 后完成合并，禁止把 pending 当作 0。
- Unity 采集场景维护五项可任意选择的共享物理任务；每项任务同时记录四个实验一系统配置和四个实验二组件消融，不再重复采集任务 6--9。`ExperimentInputHandler` 直接在 Inspector 序列化内联 `InputAction`，不使用 binding 字符串、`InputActionAsset` 或 `InputActionReference`；右手摇杆与键盘方向键共用 3×3 九宫格导航，主键盘数字行与小键盘 `1`--`5` 只负责直接选中任务，A/主键盘 Enter/小键盘 Enter 开始，右扳机/小键盘 `+`/`M` 标记，快速短按 B/小键盘 `0`/`E` 结束任务，摇杆按下/`Space` 只作废当前或选中任务，长按 B 1.5 秒/`F` 可随时停止 session。小键盘主流程固定为 `1`--`5` 选任务、`Enter` 开始、`+` 标记、`0` 结束。进入场景后保持未录制的任务选择状态并默认选中任务 1；方向键、右手摇杆或数字键只改变选中项。正式与开发场景的 `EvalSession.autoStart` 固定关闭；A、主 Enter 或小键盘 Enter 的一次新按下必须在同一回调内启动 session 与当前选中 trial，不得要求第二次确认，启动失败时保留选择且不得写 `trial_started`。右手 B 的结束绑定固定为 `Tap(duration=0.5)`，停止绑定固定为 `Hold(duration=1.5)`，防止长按停止前先误结束 trial。停止 session 时活动 trial 先写 `trial_rejected`，已经完成的任务保持不变。数字行路径必须写 `<Keyboard>/1`--`5`，小键盘路径写 `<Keyboard>/numpad1`--`numpad5`，marker 与结束路径分别写 `<Keyboard>/numpadPlus` 和 `<Keyboard>/numpad0`；不得使用无法解析的 `<Keyboard>/digitN`。运行中禁止切场；任务和 session 均无持续时间门禁，实际 trial 时长只记录不判定成败。已完成任务选中后可按开始动作重录，旧 trial 先写 `trial_rejected`；单独作废仍只影响选中任务。状态板只显示 `NEXT`、九宫格、`CURRENT`、直白 `STATE`、单一实际 trial 计时和固定按键图例，不暴露分析内部的 phase/event role；未录制时任务 1 保持黄色选中，一次显式开始动作后才显示绿色运行并启动 trial 计时；蓝色表示完成、灰色表示待执行，已完成任务被选中时保持蓝色并以箭头和粗体区分；Canvas 保持场景根节点静止。
- 头显状态板运行时文本统一使用英文 ASCII，因为当前 TextMesh Pro 字体资产不保证 CJK 字形；中文只用于代码注释、Inspector Tooltip、控制台日志和采集手册，不得把中文动态状态字符串传给 `ExperimentStatusUI`。
- 正式与开发采集场景的根 Canvas 固定包含两个同级面板：左侧任务状态板和右侧 `EvalLiveStats` 实时诊断板。实时板以 10 Hz 显示 HMD/佩戴/VR focus/输入 focus、output/display/reference、相对平台控制器的位姿差异、观测年龄、同 Unity 时钟 E2E arrival、Python server processing、smoothing delay、pose rate、VCD、残差、frame step 与锚点状态。平台参考差异不是外部真值，实时板不得用于挑选低误差起始时刻；正式指标仍由 schema-v2 离线分析产生。
- marker 成功后状态板显示 2 秒绿色 `MARKER SAVED #N` 和事件角色，非法时显示红色 `MARKER IGNORED`。反馈只属于 UI，不得额外写成实验事件；成功 marker 仍只写既有 `event_marker`。
- `QuestStreamPublisher` 订阅 Meta VR focus：focus 丢失时暂停双目 GPU 读回和 JPEG 编码，恢复后自动继续；录制期间的 `xr_focus_lost/acquired` 写入 Unity events。出现 `HMDUnmounted`、`VrFocusLost` 或 `InputFocusLost` 的活动 trial 应作废重采。
- 正式 `EgoAnchor-Experiment12.unity` 场景使用 8 个唯一 runtime：Hub 下以两个空物体分别组织实验一四配置和实验二四个单组件消融，完整 EgoAnchor 只保留一个共享 runtime；场景契约测试冻结组件矩阵与层级；manifest 记录 VCD、时序合成、StaticLock、低分重获取、服务器重获取开关及整体 `config_hash`。
- Inspector 参数、坐标语义和时间语义写 XML summary 或 `[Tooltip]`；不隐藏生效参数。
- Unity 生成协议代码和 `SubjectNames.cs` 不手改。

## Schema-v2 与评估原则

Run 1 将原始日志固定为 `manifest.json`、`python_candidates.jsonl`、`python_events.jsonl`、`unity_reference.jsonl`、`unity_admission.jsonl`、`unity_render.jsonl`、`unity_events.jsonl`、合并后的 `events.jsonl` 和审计样本目录。旧共享事件文件格式不兼容。

- `capture_mono_ms` 是 image-time proxy，不得称曝光真值。
- 平台参考轨迹用于同一 Quest、同一时间线下的配对系统行为分析，不得称外部物理真值。
- 实验一比较 *Arrival-Hold*、*Capture-Hold*、*One-Euro Anchor* 与 *EgoAnchor* 的端到端系统行为。
- 实验二通过单组件关闭归因采集时刻世界对齐、VCD 接纳、时序合成和 StaticLock。
- 静止指标同时报告 HP-RMS、绝对误差和漂移，避免“冻结错误位姿”获得虚假优势。
- 转换指标至少包括 visible response、unlock/relock、peak error 与 settling time。
- 分析先在 `session x trial/event x variant` 内计算，再做 trial/event 配对和 session 汇总；不做 frame-level 推断。
- 正式参数在系统实现完成时随配置固定；所有记录的实验 session 均为 formal，采集后不得调参。
- 图表和 LaTeX 数字由 `egoanchor.eval` 自动生成，主稿不手抄结果。
- schema-v2 reader 按 dataclass 契约严格检查固定字段和跨表稳定键，并把 `python_session.json` 的停止态 writer 统计、Python host/version 合并到内存 manifest。CLI 事件物化入口只有在 `python_stopped`、两个事件分片 schema 合法、实际行数分别匹配 writer 统计且无丢行/写入失败时，才用冻结全序原子发布可重建的 `events.jsonl`；已有文件交给只读 QC 逐字节验证。半同步、pending、错配或非法 fragment 不得留下部分派生文件，也不得进入正式分析；Mutagen 完成同步后允许对同一目录直接重试。
- schema-v2 QC 对 Formal session 固定要求场景中的 8 个唯一 runtime、按 Unity FNV-1a 规则重算整体 `config_hash`，并检查 writer 行数/丢行/失败、candidate/reference 主键、Unity 已消费 candidate×variant 与 tick×variant 矩阵及递归旧字段。NATS PoseResult 使用 latest-only 消费，Python 已发布但未进入 Unity 的 candidate 只能统计并警告，分析按 admission 投影排除，禁止为未收到的消息伪造 admission；Unity admission 指向未知 Python candidate 仍是硬错误。
- Formal schema-v2 QC 按 `trial_started -> trial_ended` 的 Unity 单调时间核对每个最终完成 trial；开始/结束事件必须唯一且顺序合法。实际持续时间作为描述性审计指标记录，不设上下界，也不决定 QC 成败。
- 中性指标统一按 `session_id × experiment_id × scenario_id × trial_id × event_id × condition_id × variant_id` 组内计算；显示误差使用 `reference_*` 与 `display_*`，output availability 只使用 `has_output_pose`。
- candidate arrival 使用 Unity 同一单调时钟的 `source_capture_mono_ms -> unity_pose_handle_mono_ms`；Python processing 使用 `server_receive_mono_ms -> server_publish_mono_ms`，不得跨进程相减单调时钟。
- 人工事件角色写入 `events.payload.event_role`。五个正式物理任务的完成 trial 都必须至少包含一个 marker；起停 6DoF 必须包含 `transition_started`，遮挡恢复必须从 `occlusion_started` 开始，与 `target_visible` 严格交替并成对闭合。转换与恢复指标按角色切窗，不得根据场景名猜测事件含义；任一实验二消融缺少其冻结关键指标时禁止发布 CSV/PDF/TeX 正式产物。
- schema-v2 基础 QC 始终检查全部原始行；实验一/二正式 QC、指标和 VCD risk-coverage 只投影已有 `trial_ended` 且没有后续 `trial_rejected` 的 trial。被作废和未完成的尝试保留审计记录，但不得进入论文结果。
- 历史离线分析路径和旧 schema 测试已删除；正式分析只从 `EvalSessionV2` 和后续 `egoanchor.eval.cli` 进入。
- 旧命名扫描按语义判定：Unity/Python runtime、writer、namespace 和 CLI 不得依赖或输出旧 RQ/schema 名称；`schema_v2/readers.py`、`schema_v2/qc.py` 及其测试可保留旧文件名和字段名，仅用于显式拒绝旧输入，不得把这些 reject-only guard 当作兼容层删除。
- 实验一分析先对完整 8-runtime session 执行 schema-v2 基础 QC，再投影 *Arrival-Hold*、*Capture-Hold*、*One-Euro Anchor* 与 *EgoAnchor*；消融 runtime 不得混入实验一的 VCD、时延、图表或 LaTeX 数字。
- 实验一单 session QC 只检查实际完成任务的 reference coverage 和 tick×variant 完整性；批次 QC 按已完成 trial 的场景并集要求任务 1--5 全部覆盖。失败时只写 session/trial/批次 QC 审计表并停止，禁止生成正式指标、PDF 和 LaTeX。
- 实验二复用实验一任务 1--5 的同一批 8-runtime schema-v2 session，再按组件适用的物理场景投影完整 *EgoAnchor* 与对应消融：采集时刻对齐和 StaticLock 使用静止头动任务，VCD 使用遮挡恢复任务，时序合成使用起停 6DoF 任务；批次仍要求五项物理任务全部覆盖，使同一组输入目录能够同时生成实验一和实验二产物。完整系统的四个归因组件必须全开，每个消融名称必须且只能关闭对应组件；字符串布尔值和名称/开关错配均不得进入分析。
- 同一分析批次不得包含重复 `session_id`，且固定 formal run kind、对象、对象模型、协议、整体配置哈希、冻结参数集和 runtime 定义必须一致。没有目标实验完成任务的 session 可随同批次输入，但不参与该实验指标。Mutagen `logs-5090` 启用期间原始 `data/eval/<session_id>` 目录名、内部固定文件名和 manifest `session_id` 均不得修改。
- 实验二只在组件对应场景内按 `session_id × scenario_id × trial_id × event_id` 配对完整系统与消融。VCD risk-coverage 仅使用完整 *EgoAnchor* 的 capture-time aligned raw 相对同帧平台 reference 的平移误差，单位为毫米；不得用 VCD 或几何评分分量代替 risk，并列分数按同一阈值整体纳入。
- 统一分析 CLI 只提供 `qc`、`preprocess`、`build-paper`。成功返回 0，文件系统或输入缺源返回 1，schema/QC/论文输入契约失败返回 2；历史入口和对应 Pixi 别名均不保留。
- `preprocess` 将每个 task 原子发布为完整 XLSX；`build-paper` 只从五本 Stage 1 XLSX 计算 GPT v4 指标，并发布固定 TeX 到 `2026-EgoAnchor/tables/`、固定 PDF/PNG 到 `2026-EgoAnchor/figures/generated/`，同时写出 `egoanchor_cn_v6.tex`。默认论文根目录从命令参数指定。
- 自动生成的 LaTeX 控制序列不得含阿拉伯数字；分位数等后缀使用字母拼写（如 `PFifty`、`PNinetyFive`），避免 TeX 在数字处截断命令名。
- 论文发布层的表格和图表必须将内部 `scenario_id`、指标键映射为读者可读的标签；CSV 与 QC 审计文件保留稳定机器字段，二者不得互相替代。
- 分析 reader 对启动阶段的参考时间窗有明确边界：只有 render 内嵌参考有效、`source_capture_mono_ms` 早于首条 `unity_reference` 且 `source_frame_id` 位于首帧之前的 warmup 行可被保留；其余未知 frame-id 仍必须硬失败。指标层同样排除没有右表参考基线的 warmup candidate。
- Run 1 中文采集手册固定为 `2026-EgoAnchor/experiment_1_2_collection_manual_zh.md`；它规定 NATS/Python/Unity 启动、跨端 session 配对、实验一/二事件操作、随时停止、QC、失败重采和 formal 参数固定边界。
- 中文主稿由 `build-paper` 从 GPT v4 模板和当前 XLSX 指标完整写出；图只从 `figures/generated/` 加载固定 PDF，不再使用 `figs/`。正式分析产物不存在时不得写占位数字或占用图表版面。

## 协议与生成输出

唯一协议源：

- `EgoAnchor_Protocol/subjects.v1.json`
- `EgoAnchor_Protocol/proto/protocol/v1/{common,quest,anchor}.proto`

生成输出：

- Python：`EgoAnchor_Python/src/egoanchor/protocol/v1/*_pb2.py`
- Unity：`EgoAnchor_Unity/Assets/Scripts/EgoAnchor/Protocol/Generated/*.cs`、`SubjectNames.cs`

## 常用验证

Python（`EgoAnchor_Python`）：

```powershell
pixi run python .\src\run_server.py
pixi run python -m compileall src
pixi run python -m unittest discover -s src -p "test_*.py" -t src
```

Unity（仓库根目录）：

```powershell
dotnet build "EgoAnchor_Unity\EgoAnchor.Tests.csproj" --no-restore
dotnet build "EgoAnchor_Unity\Assembly-CSharp.csproj" --no-restore
```

协议生成（`EgoAnchor_Python`）：

```powershell
pixi run pwsh -File ..\EgoAnchor_Protocol\tools\generate_proto.ps1
```

论文（`2026-EgoAnchor`）：

```powershell
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=pdf egoanchor_cn_v6.tex
```

## 环境与远端关键坑

- `pixi run build` 会构建 nvdiffrast、FoundationPose 扩展和 FFS artifacts，不作为轻量验证。
- FFS 覆盖导出前必须删除旧 `.onnx` 与 `.onnx.data` sidecar，避免 Windows `PermissionError`。
- nvdiffrast 不放 `[pypi-dependencies]`；使用 `_build-nvdiffrast`。Windows 构建任务内部清理并重建 MSVC/CUDA 环境，`CL/INCLUDE/PATH` 不放 Pixi activation；CUDA 13 同时加入 `targets/x64` 与 `cccl` include。
- Windows 数值栈保持 OpenBLAS；SciPy/scikit-learn 使用 PyPI wheel。OpenCV 只保留 `opencv-python`，避免 DLL/OpenMP 冲突。
- 完整 Windows 环境说明在 `EgoAnchor_Python/docs/windows-prerequisites.md`。
- `EgoAnchor_Python/mutagen.yml` 以本机为唯一源码源，source 使用 `one-way-replica`，日志回传使用 `one-way-safe`；远端 `data/eval/` 与 `data/runtime_logs/` 必须先存在。
- Windows 远端 Mutagen 要求 OpenSSH `DefaultShell=cmd.exe` 且系统代码页为 UTF-8；PowerShell DefaultShell 会使相对 agent 命令失败。

## 项目级实现要求

- 日志统一走门面：Python 使用 `egoanchor.utils`，Unity 使用 `EgoAnchorLog`。
- 新行为先补测试或工程功能自检；最终提供可复现验证命令。
- AI 或自动化工具修改 Unity 文件、保存场景、刷新 AssetDatabase 或触发编译前，必须先确认 Editor 不在 Play Mode。正式采集从进入 Play Mode 到退出期间禁止任何代码写入和 Unity MCP 状态变更。
- 不恢复旧端口、旧 MessagePack/JSON pose、旧 NATS 图像流、旧 Python/Unity 入口或旧 eval schema。
- 不添加 `FormerlySerializedAs`、旧字段、旧路径、旧标签或旧 CLI 兼容层。
- 改 schema 时同步 writer、reader、分析、论文接口和本文件。

## 当前离线分析事实

- Stage 1 `preprocess`、workbook-v2 契约、XLSX writer 和回读验证保持不变；`task_1_complete.xlsx` 到 `task_5_complete.xlsx` 是 GPT v4 分析的唯一正式输入。
- GPT v4 只读 XLSX reader 直接解析 ZIP/XML 和逻辑分片 sheet；重建前后五本 XLSX 的 SHA-256 必须不变。
- 实验一图固定为头动中心化泄漏、持续平移 lag--RMSE 和遮挡 episode P95 三面板；实验二固定为 capture-time alignment、StaticLock、VCD 和 temporal synthesis 左三右一图，主稿使用 LaTeX 子图分别排版这些 panel。实验一分类面板使用不透明箱线/须线/误差棒与半透明片段点；持续平移和时序合成面板仅在散点层按每个方法的 1.5x IQR 隐藏视觉异常点，median/IQR、表格和完整审计数据仍包含全部片段；两动态面板纵轴均固定为 0--15 mm。图 2 仅在动态面板放置一套共享方法图例，图 3 仅在时序面板放置 Full/Disabled 图例，图例间距保持可读。
- 实验一表同时报告中心化泄漏、绝对注册、帧间增量、平移/旋转 lag--RMSE、遮挡 P95/40 mm 超限和起停转换；实验二按组件报告启用、关闭和配对效应。
- capture-time alignment 直接比较完整 EgoAnchor 同一 raw candidate 的 capture-time 与 arrival-time 世界复合 P95；StaticLock 使用中心化静止 P95；VCD 只使用 `occlusion_started` episode 的 P95、40 mm 超限数和最大值；时序合成使用持续平移 lag--RMSE。
- GPT 参考包只提供绘图样式、表格布局和论文文字结构，不作为正式数字输入；正式数字必须由当前五本 Stage 1 XLSX 计算。
- 复现命令、退出码和故障排查统一见 `EgoAnchor_Python/docs/analysis_pipeline.md` 与中文复现手册。

## AGENTS.md 维护规则

- 不修改顶部 `USER-MAINTAINED-REQUIREMENTS` 区块。
- 只写当前事实、长期约束、已冻结路线和会直接导致失败的历史坑。
- 不记录 session 数字、迁移 hash、调参过程、旧图窗或一次性排障过程。
- 事实变化时直接改原条目，不追加相互矛盾的新说明。
