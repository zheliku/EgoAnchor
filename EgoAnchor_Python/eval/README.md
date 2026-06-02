# EgoAnchor Python 离线评估使用说明

本文说明当前 Python 端评估功能的完整用法。当前实现覆盖：

- P0：Python runtime JSONL 写出 `pose_result` 分模块耗时和服务端收发时间。
- P1：`eval/io` 加载 Unity capture/output、Python runtime log 和 manifest，并按 `frame_id` join。
- P2：`eval/metrics` 基于 Unity Transform GT 直接计算误差、延迟、jitter、slip、lag、jump suppression、recovery 与 sanity。
- P3：`eval/run_eval.py` 一条命令导出 CSV、Markdown、PNG/PDF 图和 `gt_anchor_sanity.json`。

如果你要按实验流程评测 anchor pose 精度、看懂哪些图为什么为空，先读：
[`ANCHOR_EVALUATION_MANUAL.md`](ANCHOR_EVALUATION_MANUAL.md)。

## 1. P2 hand-eye 为什么不再需要

原计划的 P2 hand-eye 标定用于旧方案：Unity 从 `OVRInput` 读取手柄 SDK 原点，再估计 `X = C_T_A` 把 SDK 原点对齐到 mesh/anchor 原点。

当前 Unity 侧已经改为直接记录场景中绑定的 `groundTruthTransform`，例如 `OVRControllerPrefab`。日志与 manifest 中应看到：

```text
gt_source = "transform"
gt_transform = "OVRControllerPrefab"
gt_pose_source = "transform"
```

因此 GT、anchor、head、camera 都已经是 Unity 世界系 Transform pose。离线指标直接比较 `gt_pos/gt_rot` 与各变体的 `stable_pos/stable_rot`，不再求 `X`。继续做 hand-eye 会把真实 tracking/filter 误差吸收到一个离线标定偏置里，反而削弱评估的客观性。

## 2. 录制一个可分析 session

在 `EgoAnchor_Python` 目录先启动 Python：

```powershell
pixi run controller_right
```

左手柄则运行：

```powershell
pixi run controller_left
```

Python 会创建：

```text
data/eval/<session_id>/
  python_session.json
  <session_id>_python_runtime.jsonl
```

再进入 Unity Editor + Link，使用评估场景：

1. 确认 `AnchorEvalRecorder.groundTruthTransform` 绑定本轮真实 GT Transform，例如 `OVRControllerPrefab`。
2. 确认 `recordedRuntimes` 中每个 variant 同时绑定 `runtime` 和实际输出的 `anchorTransform`。
3. 按 F7 开始录制，按数字键切 condition，按 O/V/R 打事件 marker，按 F8 停止。
4. Unity 会复用 Python session，并在同一目录写入：

```text
<session_id>_unity_capture.jsonl
  <session_id>_unity_output.jsonl
  session_manifest.json
```

Unity capture/output 日志会同时写机器计算用的 `*_rot` 四元数和人类阅读用的 `*_euler_deg` 欧拉角；`*_euler_deg` 统一是 `[0, 360)` 度区间。

建议录制完整协议：

```text
static -> slow_head -> fast_head -> object_motion -> occlusion -> out_of_view -> lighting
```

短 smoke session 可以验证链路，但如果没有 `has_stable=true` 的输出，anchor error/jitter/slip 表会是空表或标记 `insufficient_data`。

## 3. 快速检查 session

在仓库根目录运行 Unity/日志 smoke：

```powershell
dotnet run --project EgoAnchor_Tools\eval_session_check\EvalSessionCheck.csproj -- --session-dir EgoAnchor_Python\data\eval\<session_id> --require-python-join
```

在 `EgoAnchor_Python` 目录快速加载日志：

```powershell
pixi run python -c "from pathlib import Path; from eval.io import load_session, join_by_frame; logs=load_session(Path('data/eval/<session_id>')); joined=join_by_frame(logs); print('capture', logs.capture.shape); print('output', logs.output.shape); print('pose', logs.pose.shape); print('joined', joined.shape); print('pose matched', int(joined['pose_has_pose'].sum())); print('gt_source', logs.manifest.get('gt_source'), logs.manifest.get('gt_transform'))"
```

把 `<session_id>` 换成真实目录名。

## 4. 运行完整离线评估

在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run eval --session-dir data/eval/<session_id>
```

只导出表格与 sanity：

```powershell
pixi run eval-metrics --session-dir data/eval/<session_id>
```

只导出图表：

```powershell
pixi run eval-figures --session-dir data/eval/<session_id>
```

也可以直接运行脚本：

```powershell
pixi run python eval/run_eval.py --session-dir data/eval/<session_id> --only all
```

可选 `--only`：

```text
all      导出表格、sanity 和图表
metrics  导出 CSV、summary.md 和 sanity
tables   同 metrics
figures  导出图表和 sanity
sanity   只导出 gt_anchor_sanity.json
```

如果旧数据的 manifest 没有 `python_log_filename`，显式指定 Python runtime log：

```powershell
pixi run eval --session-dir data/eval/<session_id> --python-log data/eval/<session_id>/<python_runtime>.jsonl
```

## 5. Report 产物

评估结果写入：

```text
data/eval/<session_id>/report/
```

核心文件：

```text
gt_anchor_sanity.json              # GT/anchor 语义一致性诊断
summary.md                         # 所有 summary 表的 Markdown 版本
anchor_error_summary.csv           # condition × variant 的世界系 anchor error
pose_offset_summary.csv            # 固定偏移诊断，汇总 anchor_pos - gt_pos 与 0-360 Euler 旋转 offset
latency_summary.csv                # capture -> apply + Python 分模块 latency
jitter_summary.csv                 # 静止窗口抖动
slip_summary.csv                   # 屏幕空间 slip
lag_summary.csv                    # 运动滞后估计
jump_suppression_summary.csv       # 尖峰与 reject 统计
recovery_summary.csv               # event marker 后恢复时间
anchor_error_detail.csv            # 逐帧误差，含 position_offset_*_m 与 0-360 rotation_offset_euler_*_deg
*_detail.csv                       # 其它逐行明细，供画图/排查
*.png / *.pdf                      # 可视化图表
```

`gt_anchor_sanity.json` 是第一眼要看的文件。重点字段：

- `gt_source` 应为 `transform`。
- `gt_transform` 应是本轮真实 GT Transform。
- `variants.<label>.stable_rows` 如果是 0，说明该 variant 没有可评估 `anchorTransform` 输出。
- `aligned_raw_error` 只诊断主变体 raw 输入质量，不等于正式 stable 指标。

固定偏移请看 `pose_offset_summary.csv`：

- `position_offset_*_m = anchor_pos - gt_pos`，坐标轴是 Unity world xyz。
- `rotation_offset_euler_*_deg` 是 `inv(gt_rot) * anchor_rot` 的 `xyz` 欧拉角，单位是度，范围为 `[0, 360)`；不写四元数，方便直接判断固定轴向偏差。
- `position_residual_after_median_*_m` 表示减掉 median offset 后还剩多少波动；它越小，越说明可以考虑手动补一个固定 offset。

## 6. 用当前样例验证

当前样例可直接运行：

```powershell
pixi run eval --session-dir data/eval/20260602_190912_controller_right
```

该样例的 sanity 显示：

```text
gt_source = transform
gt_transform = OVRControllerPrefab
aligned_raw translation median ~= 0.0245 m
kalman.stable_rows = 1117
kalman.anchor_pose_source_counts = {"legacy_aligned_raw": 1117}
raw.stable_rows = 0
```

这说明 Transform GT 语义已经对齐，旧 hand-eye P2 不需要。该旧 session 已把主变体原来的 `aligned_raw_pos/aligned_raw_rot` 迁移到 `stable_pos/stable_rot`，所以可以用 `kalman` 行粗略分析静态偏移；但它的来源是 `legacy_aligned_raw`，不是新 recorder 直接读取最终 `anchorTransform`。正式实验仍以 `anchor_pose_source=transform` 的新 session 为准。

## 7. 常见问题

- `ModuleNotFoundError: No module named 'eval'`：使用新版 `eval/run_eval.py`，或从 `EgoAnchor_Python` 目录运行 `pixi run eval --session-dir ...`。
- `anchor_error_summary.csv` 只有表头：检查 `gt_anchor_sanity.json` 的 `stable_rows` 和 `anchor_pose_source_counts`，通常是 Unity `recordedRuntimes[*].anchorTransform` 未绑定或 runtime 未产生 stable 输出。
- `manifest.python_log_filename` 为空：说明 Unity 没复用 Python session。先启动 Python，再 Unity F7；旧数据可用 `--python-log` 指定。
- `latency_summary` 有 `unlabeled`：录制开始前或 condition span 外的帧会落到 `unlabeled`，正式实验应按数字键覆盖完整时间段。
- 图里显示 `insufficient data`：链路正常，但对应指标缺少必要数据，例如 recovery 没 marker、lag 没足够运动帧、jitter 没静止窗口。

## 8. 开发验证命令

在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python -m compileall src eval
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python -m unittest discover -s eval -p "test_*.py"
pixi run eval --session-dir data/eval/20260602_190912_controller_right
```
