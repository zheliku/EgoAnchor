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
- *One-Euro Anchor*：采集时刻世界复合、基本有效性检查、One Euro 自适应滤波与保持。
- *EgoAnchor*：采集时刻世界复合、VCD 接纳、Kalman-Hermite 合成、显式静止锚定和生命周期管理。
- 组件消融使用 `EgoAnchor w/o <component>` 风格命名，不再恢复旧 RQ 命名或旧 CLI 兼容层。

IEEE VR 2027 正文、图和表最多 9 页，参考文献最多另占 2 页。Run 2 完成实验一/二后正文不得超过 8.4 页，为实验三用户研究保留空间。实验三是已规划的任务层效用验证，但当前先搁置，待实验一/二完成后再启动正式采集。

两次执行边界：Run 1 完成实验一/二采集前全部工程、论文框架、QC、分析骨架和中文采集手册，并保留实验三设计；用户完成 smoke 与实验一/二正式采集；Run 2 完成实验一/二分析、图表和论文回填。本轮按用户明确要求，每个 Task 验证后独立提交并推送。

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
- *One-Euro Anchor* 用采集时刻复合、基本有效性检查和 One Euro 自适应滤波，作为标准滤波锚定基线。
- *EgoAnchor* 用采集时刻复合、VCD 接纳、Kalman-Hermite 合成、显式静止锚定和生命周期管理。
- 组件归因通过关闭单一设计实现：w/o capture-time alignment、w/o VCD、w/o temporal synthesis、w/o StaticLock。
- 模型相关 per-variant jump gate 不进入正式比较。

## Python 关键约束

入口：`EgoAnchor_Python/src/run_server.py` -> `egoanchor.app.tracking_server`。配置位于 `src/egoanchor/config/defaults.toml` 与 `objects.toml`。

- 默认分割器是 `yoloe26`；SAM3 只能显式启用。
- 评估模式写 `data/eval/<session_id>/` 并通过 header 与 Unity 配对；普通模式写 `data/runtime_logs/`。
- VCD 目标公式为 `R = V * G_CD`，其中 `V = |M_obs intersection M_rnd| / |M_rnd|`。正式采集前必须确保公式、代码和日志一致；当前面积比旧实现不得进入正式结果。
- `color_reprojection < 0` 表示颜色信号不可用，应从几何核排除，而不是视作坏 pose。
- 深度评分保留绝对与结构分量 `D = (1-alpha) D_abs + alpha D_struct`；Run 1 日志必须暴露消融所需分量。
- Python 评估模式的 `RuntimeLogWriter` 已将候选行映射为严格 `PythonCandidateRow`，颜色不可用写入 `null` 并保留解释 flag；runtime 事件与候选行分写固定 schema-v2 文件。
- Python candidate ID 使用 `session_id:frame_id:frame_local_seq`；`RuntimeLogWriter` 关闭时把 candidate/event 的真实 `rows_written`、`dropped_rows` 和 `log_write_failures` 写回 `python_session.json`，供最终 manifest 汇总，Unity 不得伪造 Python 丢行统计。
- `CutieMaskTracker` 不直接导入 `torchvision.transforms.functional.to_tensor`，避免 Windows 图像 DLL 冲突。
- 生成代码、`*_pb2.py` 和协议副本不手改。

关键 ownership：`config/` 不导入模型/网络；`transport/` 只管传输；`routing/handlers` 不碰 GPU；`runtime/tracking_runtime.py` 是 pipeline owner；`perception/quest_pose_pipeline.py` 组合视觉模块；`reliability/` 计算 VCD；新 `eval/` 只处理 schema-v2、QC、实验一/二和论文产物。

## Unity 关键约束

- `MeasurementTimeSeconds` 属于采集时间轴，用于运动估计与静止锚定；生命周期 freshness 使用到达/生命周期时间轴。不得用 capture time 刷新 stale/lost。
- `has_output_pose` 表示 runtime 是否有输出；`has_display_pose` 表示用户实际看到的 Transform，包括 hold-last。显示误差使用 display pose，输出覆盖率使用 output pose。
- hold-last 显示行从 `DynamicObjectAnchor.LastAppliedFrameId` 保留实际来源帧；只有从未应用或已隐藏的显示才允许 `source_frame_id=-1`。
- StaticLock tether 计算 `obsConsensus -> anchorOrigin`，不得改成单帧观测或 `lockedPose`。
- 头动期间不冻结真实运动证据；`headSettleSeconds` 只覆盖头停后的沉降窗口。
- 距离自适应只放大位置通道；旋转 tether 必须高于旋转噪声地板。
- `EvalLog` 使用有界后台队列；正式 session 的所有日志 `dropped_rows` 必须为 0。
- Unity `EvalSession`/`EvalRecorder` 已固定写入 `manifest.json`、`unity_reference.jsonl`、`unity_admission.jsonl`、`unity_render.jsonl` 和 `events.jsonl`；render 为 tick×variant 长表，admission 由每个 runtime 的实际处理结果产生。`events.jsonl` 由 Python 与 Unity 通过同名 `.lock` 文件逐行互斥追加，Unity 不得因已有 Python 事件拒绝启动或截断文件。
- Unity admission 与 event 行已覆盖 schema-v2 必填时间、策略、上下文和 payload 字段；candidate ID 使用 `session_id:frame_id:frame_local_seq`，同一 `PoseResult` 的多 runtime 回调共用标识。
- Unity manifest 写出 run kind、自动配置哈希、对象、版本、实验/场景计划和真实 Unity writer 统计；`frozen_parameter_set_id` 自动复用整体 `config_hash`，`operator_id` 固定为匿名单操作员，run mode 与 protocol 由代码生成，Git commit 为可选审计字段。Formal 启动不要求现场填写元数据，仍严格要求 Python session 配对和非空变体配置哈希。Python candidate 及跨端 events 总统计在 Unity 停止时明确标为 pending，必须在 Python 停止并同步 `python_session.json` 后完成合并，禁止把 pending 当作 0。
- Unity 采集场景使用固定九场景计划。右手控制器 A 与键盘 `Space` 是两条等价的 Input System 推进入口，binding path 暴露在 `ExperimentInputHandler` Inspector；普通场景按“开始、主事件、结束”推进，遮挡场景增加一次 `target_visible`，最后一个场景完成后自动停止 session。旧数字键、Enter、Shift、0 和 F7/F8 采集接口不得恢复。
- 正式 `EgoAnchor-Experiment12.unity` 场景使用 8 个唯一 runtime：Hub 下以两个空物体分别组织实验一四配置和实验二四个单组件消融，完整 EgoAnchor 只保留一个共享 runtime；场景契约测试冻结组件矩阵与层级；manifest 记录 VCD、时序合成、StaticLock、低分重获取、服务器重获取开关及整体 `config_hash`。
- Inspector 参数、坐标语义和时间语义写 XML summary 或 `[Tooltip]`；不隐藏生效参数。
- Unity 生成协议代码和 `SubjectNames.cs` 不手改。

## Schema-v2 与评估原则

Run 1 将原始日志固定为 `manifest.json`、`python_candidates.jsonl`、`unity_reference.jsonl`、`unity_admission.jsonl`、`unity_render.jsonl`、`events.jsonl` 和审计样本目录。旧 schema 不兼容。

- `capture_mono_ms` 是 image-time proxy，不得称曝光真值。
- 平台参考轨迹用于同一 Quest、同一时间线下的配对系统行为分析，不得称外部物理真值。
- 实验一比较 *Arrival-Hold*、*Capture-Hold*、*One-Euro Anchor* 与 *EgoAnchor* 的端到端系统行为。
- 实验二通过单组件关闭归因采集时刻世界对齐、VCD 接纳、时序合成和 StaticLock。
- 静止指标同时报告 HP-RMS、绝对误差和漂移，避免“冻结错误位姿”获得虚假优势。
- 转换指标至少包括 visible response、unlock/relock、peak error 与 settling time。
- 分析先在 `session x trial/event x variant` 内计算，再做 trial/event 配对和 session 汇总；不做 frame-level 推断。
- 正式参数只用开发/calibration 数据冻结；formal session 后不得调参。
- 图表和 LaTeX 数字由 `egoanchor.eval` 自动生成，主稿不手抄结果。
- schema-v2 reader 按 dataclass 契约严格检查固定字段和跨表稳定键，并把 `python_session.json` 的停止态 writer 统计、Python host/version 合并到内存 manifest；pending、错配或非法 fragment 不得进入正式分析。
- schema-v2 QC 对 Formal session 固定要求场景中的 8 个唯一 runtime、按 Unity FNV-1a 规则重算整体 `config_hash`，并检查 writer 行数/丢行/失败、candidate/reference 主键、candidate×variant 与 tick×variant 矩阵及递归旧字段。
- 中性指标统一按 `session_id × experiment_id × scenario_id × trial_id × event_id × condition_id × variant_id` 组内计算；显示误差使用 `reference_*` 与 `display_*`，output availability 只使用 `has_output_pose`。
- candidate arrival 使用 Unity 同一单调时钟的 `source_capture_mono_ms -> unity_pose_handle_mono_ms`；Python processing 使用 `server_receive_mono_ms -> server_publish_mono_ms`，不得跨进程相减单调时钟。
- 人工事件角色写入 `events.payload.event_role`。统一推进动作按状态记录场景主事件，遮挡场景的下一次推进记录新的 `target_visible` 事件；转换与恢复指标按角色切窗，不得根据场景名猜测事件含义。
- 旧 `eval/io`、`eval/core`、`eval/report`、`run_eval` 和旧 schema 测试已删除；正式分析只从 `EvalSessionV2` 和后续 `egoanchor.eval.cli` 进入。
- 旧命名扫描按语义判定：Unity/Python runtime、writer、namespace 和 CLI 不得依赖或输出旧 RQ/schema 名称；`schema_v2/readers.py`、`schema_v2/qc.py` 及其测试可保留旧文件名和字段名，仅用于显式拒绝旧输入，不得把这些 reject-only guard 当作兼容层删除。
- 实验一分析先对完整 8-runtime session 执行 schema-v2 基础 QC，再投影 *Arrival-Hold*、*Capture-Hold*、*One-Euro Anchor* 与 *EgoAnchor*；消融 runtime 不得混入实验一的 VCD、时延、图表或 LaTeX 数字。
- 实验一专属 QC 检查五场景、reference coverage 和 tick×variant 完整性。失败时只写 session/trial QC 审计表并停止，禁止生成正式指标、PDF 和 LaTeX。
- 实验二先验证完整 8-runtime schema-v2 session，再投影完整 *EgoAnchor* 与四个消融。完整系统的四个归因组件必须全开，每个消融名称必须且只能关闭对应组件；字符串布尔值和名称/开关错配均不得进入分析。
- 实验二只在组件对应场景内按 `session_id × scenario_id × trial_id × event_id` 配对完整系统与消融。VCD risk-coverage 仅使用完整 *EgoAnchor* 的 capture-time aligned raw 相对同帧平台 reference 的平移误差，单位为毫米；不得用 VCD 或几何评分分量代替 risk，并列分数按同一阈值整体纳入。
- 统一分析 CLI 只提供 `qc`、`analyze-exp1`、`analyze-exp2`。成功返回 0，文件系统或论文发布缺源返回 1，schema/QC/分析契约失败返回 2；旧 `run_eval`、`batch_eval` 和对应 Pixi 别名均已删除，不得恢复。
- `--out` 保存一次分析的完整 CSV/PDF/TeX；分析成功后，固定 TeX 原子发布到 `2026-EgoAnchor/generated/`，固定 PDF 发布到 `2026-EgoAnchor/figures/generated/`。默认论文根目录从模块位置解析，不依赖当前工作目录，测试和外部调用可用 `--paper-root` 覆盖。
- Run 1 中文采集手册固定为 `2026-EgoAnchor/experiment_1_2_collection_manual_zh.md`；它规定 NATS/Python/Unity 启动、跨端 session 配对、实验一/二事件操作、QC、失败重采和 calibration/formal 冻结边界。
- 中文主稿通过 `\IfFileExists` 加载 `generated/exp{1,2}_numbers.tex`、`generated/exp{1,2}_tables.tex` 和 `figures/generated/` 下的固定 PDF；正式分析产物不存在时不得写占位数字或占用图表版面。

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
- 新行为先补测试或 smoke；最终提供可复现验证命令。
- 不恢复旧端口、旧 MessagePack/JSON pose、旧 NATS 图像流、旧 Python/Unity 入口或旧 eval schema。
- 不添加 `FormerlySerializedAs`、旧字段、旧路径、旧标签或旧 CLI 兼容层。
- 改 schema 时同步 writer、reader、分析、论文接口和本文件。

## AGENTS.md 维护规则

- 不修改顶部 `USER-MAINTAINED-REQUIREMENTS` 区块。
- 只写当前事实、长期约束、已冻结路线和会直接导致失败的历史坑。
- 不记录 session 数字、迁移 hash、调参过程、旧图窗或一次性排障过程。
- 事实变化时直接改原条目，不追加相互矛盾的新说明。
