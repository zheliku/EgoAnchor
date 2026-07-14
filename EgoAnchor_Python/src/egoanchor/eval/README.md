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

schema-v2 是唯一受支持的数据契约。reader 会校验文件集合、行级字段、时间语义和跨日志关联；QC 失败的 session 不进入正式汇总。平台参考位姿用于同一 Quest、同一时间线下的配对分析，不作为外部物理真值。

## 实验一：端到端系统表征

实验一比较以下四个系统配置：

- `Arrival-Hold`
- `Capture-Hold`
- `One-Euro Anchor`
- `EgoAnchor`

分析覆盖静止目标与主动头动、起停 6DoF、持续平移或旋转、遮挡恢复。指标先在 `session x trial/event x variant` 内计算，再做配对和 session 汇总，不把逐帧记录当作独立样本。

## 实验二：系统设计归因

实验二以完整 `EgoAnchor` 为参照，每次只关闭一个组件：采集时刻世界对齐、VCD admission、时序合成或 StaticLock。分析输出配对差值，并单独检查 VCD 的 risk-coverage 与 AURC。VCD 分数表示连续可靠性，不解释为位姿正确概率。

## 执行边界

Run 1 完成采集前工程：schema-v2 writer/reader、QC、分析与绘图骨架、合成 smoke 和采集手册。正式参数只用开发或 calibration 数据冻结。

用户完成实验一、实验二的 smoke 和正式采集后，Run 2 读取冻结数据，完成统计、图表、LaTeX 产物和论文回填。正式 session 开始后不再调参，论文数字由评估模块生成，不手工抄写。
