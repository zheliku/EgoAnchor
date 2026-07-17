# EgoAnchor 评估采集说明

本目录只保留评估录制基础设施。正式评估入口使用实验一/实验二命名，数据契约为 Python `egoanchor.eval` 的 schema-v2；旧 RQ 场景、selector 和分析入口不再存在。

## 采集前

1. 在 `EgoAnchor_Python` 启动运行时服务：

   ```powershell
   pixi run python .\src\run_server.py
   ```

2. 正式采集打开 `EgoAnchor-Experiment12.unity` 并进入 Play Mode；场景已固定为 Formal。
3. 等待 Python 返回非空 `session_id`，确认任务 1 只是选中而没有进入 `[RUN]`。
4. 移动右手平台参考控制器，确认实时面板显示 `CHECK VERIFIED`。
5. 用右手摇杆或键盘 `1`--`5` 选择任务；一次 A 或 Enter 同时启动 session 和当前 trial，随后用独立动作标记、结束或作废。

`EvalSession` 管理 session 生命周期，`ExperimentTrialSelector` 独立维护五项任务的选择、运行与完成
状态，`EvalRecorder` 写入 Unity 采集和渲染日志。`ExperimentInputHandler` 直接在 Inspector 暴露内联
`InputAction`，不使用 InputActionAsset。完成本次需要的任意任务子集后，在空闲状态再次按结束键即可停止
session；零项完成时不能生成空 session。

操作错误时写入 `trial_rejected` 并只重做对应任务。原始行继续保留，Python 正式分析只投影已经
`trial_ended` 且没有被 rejected 的 trial。manifest 的 `completed_tasks` 记录本次最终保留的任务编号、场景
和 trial。录制停止后不要在同一 Python session 中再次开始；下一批必须重启 Python 取得新 session id。

## schema-v2 输出

每个 session 写入 `EgoAnchor_Python/data/eval/<session_id>/`，固定文件为：

```text
manifest.json
python_session.json
python_candidates.jsonl
python_events.jsonl
unity_reference.jsonl
unity_admission.jsonl
unity_render.jsonl
unity_events.jsonl
events.jsonl
```

writer 会记录 `rows_written` 与 `dropped_rows`。正式分析前必须确认所有必需文件存在、写入丢弃数为零，并通过 reader/QC 的字段、时间线和变体覆盖检查。

## 实验一与实验二

实验一比较四个完整系统配置，覆盖静止观察、主动头动、起停 6DoF、持续运动和遮挡恢复。五项任务可以拆到
多个 session，Python 在分析批次层检查场景并集。

实验二以完整系统为参照，每次只关闭一个归因组件。它不再单独采集四项任务，而是直接复用任务 1--5
同时写出的四个消融 runtime。采集时保持同一输入流和同一参考位姿，分析阶段按
`session x trial/event x variant` 配对汇总，不跨 session 拼接逐帧记录。

具体动作、按键时机和失败重采规则见 `2026-EgoAnchor/experiment_1_2_collection_manual_zh.md`。采集阶段
只记录事实，不在 Unity 端推断统计结果或手工修改日志。
