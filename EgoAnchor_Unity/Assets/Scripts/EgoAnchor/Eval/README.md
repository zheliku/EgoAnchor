# EgoAnchor 评估采集说明

本目录只保留评估录制基础设施。正式评估入口使用实验一/实验二命名，数据契约为 Python `egoanchor.eval` 的 schema-v2；旧 RQ 场景、selector 和分析入口不再存在。

## 采集前

1. 在 `EgoAnchor_Python` 启动运行时服务：

   ```powershell
   pixi run python .\src\run_server.py
   ```

2. 正式采集打开 `EgoAnchor-Experiment12.unity` 并进入 Play Mode；场景已固定为 Formal。
3. 等待 Python 返回非空 `session_id`，确认面板显示 `Recording`。
4. 用右手控制器 A 或键盘 `Space` 推进固定九场景计划；最后一个场景完成后自动写 manifest。

`EvalSession` 自动管理 session 生命周期，`ExperimentTrialSelector` 依次选择实验一 5 个场景和实验二
4 个场景，`EvalRecorder` 写入 Unity 采集和渲染日志。手柄与键盘 Input System binding 均暴露在
`ExperimentInputHandler` Inspector 中。录制停止后不要在同一 Python session 中再次开始。

## schema-v2 输出

每个 session 写入 `EgoAnchor_Python/data/eval/<session_id>/`，固定文件为：

```text
manifest.json
python_candidates.jsonl
unity_reference.jsonl
unity_admission.jsonl
unity_render.jsonl
events.jsonl
```

writer 会记录 `rows_written` 与 `dropped_rows`。正式分析前必须确认所有必需文件存在、写入丢弃数为零，并通过 reader/QC 的字段、时间线和变体覆盖检查。

## 实验一与实验二

实验一比较四个完整系统配置，覆盖静止观察、主动头动、起停 6DoF、持续运动和遮挡恢复。

实验二以完整系统为参照，每次只关闭一个归因组件。采集时保持同一输入流和同一参考位姿，分析阶段按 `session x trial/event x variant` 配对汇总，不把逐帧记录当作独立样本。

具体动作、按键时机和失败重采规则见 `2026-EgoAnchor/experiment_1_2_collection_manual_zh.md`。采集阶段
只记录事实，不在 Unity 端推断统计结果或手工修改日志。
