# EgoAnchor 评估采集说明

本目录只保留评估录制基础设施。正式评估入口使用实验一/实验二命名，数据契约为 Python `egoanchor.eval` 的 schema-v2；旧 RQ 场景、selector 和分析入口不再存在。

## 采集前

1. 在 `EgoAnchor_Python` 启动运行时服务：

   ```powershell
   pixi run python .\src\run_server.py
   ```

2. 在 Unity 打开当前实验配置场景并进入 Play Mode。
3. 等待 Python 返回非空 `session_id`，确认面板显示 `Recording` 后开始动作。
4. 停止 Play Mode 或按场景配置的停止操作，确认 manifest 已写入。

`EvalSession` 管理 session 生命周期，`EvalRecorder` 写入 Unity 采集和渲染日志。录制停止后不要在同一 Python session 中再次开始，以免覆盖同名日志。

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

动作协议、速度上限和统计参数以 `EgoAnchor_Python/src/egoanchor/eval/README.md` 及实验计划为准。采集阶段只记录事实，不在 Unity 端推断统计结果或手工修改日志。
