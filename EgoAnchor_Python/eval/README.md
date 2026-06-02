# EgoAnchor Python P0/P1 评估功能使用说明

本文说明当前已实现的 Python 端评估基础能力：

- P0：Python `pose_result` runtime JSONL 会额外写出模块耗时与服务端收发时间。
- P1：`eval/io` 可读取 Unity capture/output、Python runtime log 和 manifest，并按 `frame_id` join。

## 1. 生成共享 eval session

在 `EgoAnchor_Python` 目录启动 Python tracking server：

```powershell
pixi run controller_right
```

左手柄则运行：

```powershell
pixi run controller_left
```

启动后，Python 会先创建共享评估目录：

```text
EgoAnchor_Python/data/eval/<yyyyMMdd_HHmmss_object_id>/
  python_session.json
  <yyyyMMdd_HHmmss_object_id>_python_runtime.jsonl
```

新的 `pose_result` 行包含这些 P0 字段：

```text
total_ms, yolo_ms, depth_ms, cutie_ms, pose_ms,
server_receive_mono_ms, server_publish_mono_ms
```

Python 启动后再到 Unity 按 F7/Start 录制，Unity 会自动复用最新且 `object_id` 匹配、尚未写入 Unity 日志的 Python session 目录。可用下面命令快速检查最新 Python eval session 的第一条 `pose_result`：

```powershell
pixi run python -c "import json,pathlib; sessions=[p for p in pathlib.Path('data/eval').iterdir() if (p/'python_session.json').is_file()]; s=max(sessions, key=lambda p:(p/'python_session.json').stat().st_mtime); meta=json.loads((s/'python_session.json').read_text(encoding='utf-8')); p=s/meta['python_log_filename']; row=next(json.loads(l) for l in p.open(encoding='utf-8') if '\"event\":\"pose_result\"' in l); print(s); print(p); print({k: row.get(k) for k in ['total_ms','yolo_ms','depth_ms','cutie_ms','pose_ms','server_receive_mono_ms','server_publish_mono_ms']})"
```

## 2. 准备一个可分析的 Unity session

推荐流程：

1. 先运行 `pixi run controller_right` 或 `pixi run controller_left`。
2. 等 Python 创建 `data/eval/<session_id>/python_session.json`。
3. Unity 进入 Play 后按 F7/Start，`EvalSessionController` 自动复用该目录。
4. 按 F8/Stop 后，Unity 在同一目录写入 capture/output/manifest。

最终 session 目录应位于：

```text
EgoAnchor_Python/data/eval/<session_id>/
```

目录中至少应有：

```text
<session_id>_unity_capture.jsonl
<session_id>_unity_output.jsonl
session_manifest.json
python_session.json
<session_id>_python_runtime.jsonl
```

`session_manifest.json` 的 `python_log_filename` 会由 Unity 从 `python_session.json` 自动写入，通常不再需要手填 `EvalSessionController.pythonLogFilename`。如果 Unity 没有找到 Python session，仍会创建一个纯 Unity session，此时可用 `load_session(..., python_log=...)` 手动指定。

## 3. 加载日志并按 frame_id join

自动复用成功时不需要传 `python_log`。在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python -c "from pathlib import Path; from eval.io import load_session, join_by_frame, label_conditions; logs=load_session(Path('data/eval/<session_id>')); joined=join_by_frame(logs); capture=label_conditions(logs.capture, logs.manifest, 'capture_mono_ms'); print('capture', logs.capture.shape); print('output', logs.output.shape); print('pose', logs.pose.shape); print('joined', joined.shape); print('matched frames', int(joined['pose_frame_id'].notna().sum())); print('conditions', sorted(capture['condition'].unique().tolist()))"
```

把 `<session_id>` 换成真实目录名即可。若是旧数据或纯 Unity session，再显式传 `python_log=Path("data/runtime_logs/<runtime_log>.jsonl")`。

`load_session()` 返回：

- `logs.capture`：Unity capture 表，`index=frame_id`。
- `logs.output`：Unity output 长表，已经把 `variants` 展开为每个 tick/variant 一行，可直接 `groupby("label")`。
- `logs.pose`：Python `pose_result` 表，`index=frame_id`。
- `logs.manifest`：原始 manifest dict。

`join_by_frame(logs)` 会保留所有 capture frame，并给 Python 列加 `pose_` 前缀。`valid=True` 仅表示 Unity Transform GT 有有效 pose，且 Python 该帧有 pose。

`label_conditions(df, logs.manifest, mono_col)` 会根据 manifest 的 `condition_spans` 写入 `condition` 列；未落入任何区间时为 `unlabeled`。

关键 Unity 评估字段：

- `gt_pos/gt_rot`：绑定的 GT Transform 世界位姿。
- `stable_pos/stable_rot`：该 variant 绑定的实际 Anchor Transform 世界位姿。
- `anchor_pose_source`：`stable_pos/stable_rot` 的来源；正式实验应为 `transform`。
- `source_capture_mono_ms`：该 variant 当前输出对应 source frame 的采集时间，可与 `render_mono_ms` 相减得到 Unity 侧 apply 延迟。
- `capture_unity_frame` / `render_unity_frame`：Unity 帧号，用于排查一帧内采集/应用时序。
- `camera_reference`、`cam_pos/cam_rot`：source frame 的参考相机位姿，用于核对 frame alignment。

## 4. 常见情况

- 如果 Unity 没有复用 Python session，`manifest.python_log_filename` 为空，且没有显式传 `python_log`，loader 会提示你指定 Python runtime log。
- 如果 Unity Start 时没有找到可复用目录，检查 Python 是否先启动、`objectId` 是否与 `--object` 一致、Python session 是否已经被旧 Unity capture/output 占用。
- 如果旧 runtime log 是 P0 之前生成的，`yolo_ms/depth_ms/cutie_ms/pose_ms/server_receive_mono_ms` 会读成 `NaN`；新日志会有实际值。
- 如果 `gt_pose_valid=false`，该行会被标成 `valid=False`；此时 `gt_pos/gt_rot` 应为 `null`，表示本帧没有可用的 Transform GT。
- 如果某行缺少必需字段，loader 会抛 `SchemaError` 并指出具体文件、行号和字段名。

## 5. 验证命令

修改后建议在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python -m compileall src eval
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python -m unittest discover -s eval -p "test_*.py"
```
