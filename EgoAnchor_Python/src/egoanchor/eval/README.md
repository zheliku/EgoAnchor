# EgoAnchor 评估模块

`egoanchor.eval` 只处理 schema-v2 评估数据。它负责读取和校验原始日志、构造规范化表、计算实验一与实验二的指标，并生成论文图表和 LaTeX 数字。运行时感知、网络传输和 Unity 锚点策略不放在本包中。

## schema-v2 数据

每个 session 位于 `data/eval/<session_id>/`，原始文件固定为：

```text
manifest.json
python_candidates.jsonl
unity_reference.jsonl
unity_admission.jsonl
unity_render.jsonl
events.jsonl
audit_samples/
```

Python 还会写 `python_session.json`，记录停止状态和 writer 统计。运行 QC 前应先正常停止 Python，使其中的 `state` 变为 `python_stopped`。schema-v2 是唯一受支持的数据契约。reader 会校验文件集合、行级字段、时间语义和跨日志关联；QC 失败的 session 不进入正式汇总。平台参考位姿用于同一 Quest、同一时间线下的配对分析，不作为外部物理真值。

基础 QC 检查 session 的全部原始行。实验一/二的正式 QC 和分析随后只选择已有 `trial_ended` 且没有
`trial_rejected` 的 trial。作废尝试不会删除，仍可从原始日志审计，但不会进入指标、配对或 VCD
risk-coverage。manifest 的 `completed_tasks` 是本 session 的任务摘要，QC 会用生命周期事件重新计算并
核对，不能手工修改。

## 启动采集服务

以下命令都从 `EgoAnchor_Python` 目录执行。当前默认配置已启用 eval session，启动时会创建 `data/eval/<session_id>/`：

```powershell
pixi run python .\src\run_server.py --object controller_right
```

`--object` 应换成当前三维模型对应的对象名。需要检查参数时运行：

```powershell
pixi run python .\src\run_server.py --help
```

Python 就绪后再打开 Unity 的 `EgoAnchor-Experiment12.unity` 场景开始采集。场景选择、事件标记和失败重采规则见 `2026-EgoAnchor/experiment_1_2_collection_manual_zh.md`，这里不重复列出快捷键。

## 统一分析 CLI

正式入口只有 `qc`、`analyze-exp1` 和 `analyze-exp2`。旧 `run_eval`、`batch_eval` 及对应别名不再使用。

先检查单个 session：

```powershell
pixi run python -m egoanchor.eval.cli qc .\data\eval\<session_id>
```

QC 会把一行 JSON 写到标准输出，便于脚本直接解析。一个 session 可以只完成任意任务子集。实验分析接收
同一冻结配置的多个目录，在批次层检查任务覆盖：

```powershell
pixi run python -m egoanchor.eval.cli analyze-exp1 .\data\eval\<session_id_1> .\data\eval\<session_id_2> --out .\data\analysis\exp1
pixi run python -m egoanchor.eval.cli analyze-exp2 .\data\eval\<session_id_1> .\data\eval\<session_id_2> --out .\data\analysis\exp2
```

实验一要求所有输入目录合计覆盖任务 1--5，实验二要求合计覆盖任务 6--9。没有当前实验任务的 session 会
被忽略。批次拒绝重复 `session_id`，并要求 run kind、对象、模型、协议、冻结参数和 runtime 定义一致。
Unity 与 Python 均正常停止后，可以给 session 目录增加 `tasks-01-03__` 之类的前缀；内部固定文件名和
manifest 的 `session_id` 不能修改。

`--out` 保存本次分析的完整 CSV、PDF 和 TeX，目录可自行指定。分析成功后，固定 TeX 会发布到 `2026-EgoAnchor/generated/`，固定 PDF 会发布到 `2026-EgoAnchor/figures/generated/`。默认论文路径从模块位置查找，不受当前工作目录影响。若仓库不使用标准目录结构，可显式覆盖：

```powershell
pixi run python -m egoanchor.eval.cli analyze-exp1 .\data\eval\<session_id> --out .\data\analysis\exp1 --paper-root ..\2026-EgoAnchor
```

CLI 返回码固定如下：

| 返回码 | 含义 |
|---:|---|
| `0` | QC 或分析完成，可以进入下一步 |
| `1` | session 文件、输出目录或论文发布产物存在文件系统问题 |
| `2` | schema、QC 或分析数据契约失败 |

命令和参数可直接从帮助页核对：

```powershell
pixi run python -m egoanchor.eval.cli --help
pixi run python -m egoanchor.eval.cli qc --help
pixi run python -m egoanchor.eval.cli analyze-exp1 --help
pixi run python -m egoanchor.eval.cli analyze-exp2 --help
```

## 实验一：端到端系统表征

实验一比较以下四个系统配置：

- `Arrival-Hold`
- `Capture-Hold`
- `One-Euro Anchor`
- `EgoAnchor`

分析覆盖静止目标与主动头动、起停 6DoF、持续平移或旋转、遮挡恢复。指标先在 `session x trial/event x variant` 内计算，再做配对和 session 汇总，不把逐帧记录当作独立样本。

## 实验二：系统设计归因

实验二以完整 `EgoAnchor` 为参照，每次只关闭一个组件：采集时刻世界对齐、VCD admission、时序合成或 StaticLock。分析输出配对差值，并单独检查 VCD 的 risk-coverage 与 AURC。VCD 分数表示连续可靠性，不解释为位姿正确概率。

## Smoke、calibration 和 formal 边界

Smoke 只检查连接、日志和操作流程。它可以运行 QC 和分析来确认产物链，但数据不进入论文统计。Smoke 的 QC 返回 `0` 后再开始 calibration。

Calibration 用于冻结 One Euro、VCD、Kalman--Hermite、StaticLock 和事件判定参数。它与 formal 数据分开保存，也不进入正式结果。

参数冻结后才能开始 formal session，开始后不再调参。所有 writer 的 `dropped_rows` 必须为 `0`；QC 失败时报告需要重采的 trial 或 session，不手工修补日志。

Run 1 负责采集前工程和采集流程准备。用户完成 smoke 与实验一/二正式采集后，Run 2 才读取冻结数据，生成统计、图表和 LaTeX 产物并回填论文。论文数字由评估模块生成，不手工抄写。
