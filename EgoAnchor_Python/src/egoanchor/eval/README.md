# EgoAnchor 评估系统说明

本文档说明 RQ1 实验数据的**采集**和**分析**流程。

---

## 一、数据采集（Unity 侧）

### 1. 场景配置

在 Unity 场景中需要挂载以下三个组件（命名空间 `EgoAnchor.Eval`）：

| 组件             | 挂载位置        | 必填绑定                                                                                                                        |
| ---------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `EvalRecorder` | 任意 GameObject | `groundTruth`（手柄 Transform）、`headAnchor`（CenterEyeAnchor）、`stereoSource`、`framePoseHistory`、`variants` 列表 |
| `EvalSession`  | 同上或父节点    | `recorder`、`runtimeHub`，填写 `objectId`（如 `controller_right`）                                                      |
| `EvalHotkeys`  | 同上（可选）    | `session`                                                                                                                     |

**Variants 列表**：在 `EvalRecorder` 的 Inspector 中至少添加一条：

- `label` = `egoanchor`（或你喜欢的名字）
- `runtime` = 场景中的 `PoseToAnchorRuntime`
- `anchorTransform` = 显示 anchor 的 GameObject Transform
- `isPrimary` = ✓

### 2. 采集流程

```
1. 启动 Python 服务：pixi run python src/run_server.py
2. 在 Unity 中按 Play
3. 自动开始录制（autoStart=true，收到第一个 PoseResult 即开始）
4. 做实验动作：静止放置 / 缓慢移动 / 快速挥动 / 遮挡 / 拿出视野
5. 在 Unity 中停止 Play（或按 F8）→ 自动写 session_manifest.json
```

> **无需手动按键标记场景**。Python 分析端会根据 GT 速度自动识别静止/运动/遮挡段。

### 3. 输出文件

每次采集会在 `EgoAnchor_Python/data/eval/<session_id>/` 下生成：

```
20260704_143000_controller_right/
├── 20260704_143000_controller_right_unity_capture.jsonl  ← 每帧采集：GT + 相机位姿
├── 20260704_143000_controller_right_unity_output.jsonl   ← 每渲染帧：anchor 输出 + GT 速度
├── 20260704_143000_controller_right_python_runtime.jsonl ← Python：pose_result + 可靠性分
└── session_manifest.json                                 ← 元数据：session_id、变体配置
```

> Python 日志通过 Mutagen 自动从远端服务器同步到本机，文件名需与 manifest 中 `python_log_filename` 一致。

---

## 二、数据分析（Python 侧）

所有命令在 `EgoAnchor_Python/` 目录下运行。

### 1. 检查数据完整性

```powershell
pixi run python -m egoanchor.eval.research.rq1.run_rq1 --check-data
```

输出每个 session 是否完整（缺哪些文件）。

### 2. 分析单个 session

```powershell
pixi run python -m egoanchor.eval.research.rq1.analyze `
    --session data/eval/20260704_143000_controller_right
```

结果写到 `data/research/rq1/20260704_143000_controller_right/`。

### 3. 批量分析所有 session（推荐）

```powershell
# 分析全部
pixi run python -m egoanchor.eval.research.rq1.run_rq1

# 只分析特定物体
pixi run python -m egoanchor.eval.research.rq1.run_rq1 --pattern "*controller_right*"

# 强制重新分析（不跳过已有结果）
pixi run python -m egoanchor.eval.research.rq1.run_rq1 --no-skip
```

完成后自动生成跨 session 聚合表。

---

## 三、分析输出说明

### 单 session 输出

```
data/research/rq1/<session_id>/
├── segments.csv        ← 自动场景检测结果
├── segments.md
├── anchor_error_detail.csv     ← 逐帧误差（位置 m + 旋转 deg）
├── anchor_error_summary.csv    ← 按场景 × 变体汇总（RMSE / 中位数 / P95）
├── anchor_error_offset_summary.csv  ← 系统性偏移分析
├── jitter_summary.csv          ← 静止期抖动 RMS
├── lag_summary.csv             ← 运动滞后（ms）
├── latency_summary.csv         ← 端到端时延分解
├── recovery_summary.csv        ← 遮挡后恢复时间
└── summary.md                  ← 人类可读摘要 ⭐ 先看这个
```

### 跨 session 输出

```
data/research/rq1/
├── rq1_summary.csv      ← 所有 session 的 anchor_error，已标注 session 列
└── rq1_aggregate.csv    ← 按 condition × label 均值聚合 → 直接用于论文表格
```

---

## 四、场景类型说明

场景标签由 Unity 明确记录，不再用速度阈值自动猜测：

| 研究问题 | 日志标签 | 用途 |
|---|---|---|
| RQ1 | `static_observation` | 长时静止精度与抖动 |
| RQ1 | `occlusion_recovery` | 遮挡期行为与恢复 |
| RQ2 | `translation` | 中低速往复平移 |
| RQ2 | `rotation` | 中低速交替轴向旋转 |

RQ2 另由平台参考轨迹提取有效运动段，并在分析阶段应用平移 `≤0.8 m/s`、旋转 `≤180 deg/s` 的速度上限。

---

## 五、指标定义

| 指标       | 列名                   | 单位 | 说明                                  |
| ---------- | ---------------------- | ---- | ------------------------------------- |
| 位置误差   | `translation_rmse_m` | m    | anchor 与 GT 的欧氏距离 RMS           |
| 旋转误差   | `rotation_rmse_deg`  | deg  | anchor 与 GT 的相对旋转角度 RMS       |
| 静止抖动   | `jitter_pos_rms_m`   | m    | 静止期连续帧 anchor 位移 RMS          |
| 端到端时延 | `e2e_latency_ms`     | ms   | 从采集帧到 anchor 更新的时间          |
| 恢复时间   | `recovery_time_ms`   | ms   | 遮挡结束到误差降回阈值的时间          |

---

## 六、故障排查

**`SchemaError: 缺少 session manifest`**
→ manifest 未写出，检查 Unity 场景中 `EvalSession` 是否正确绑定 `recorder`。

**`anchor_error_summary.csv` 只有表头**
→ GT 或 anchor Transform 未绑定，检查 `EvalRecorder.groundTruth` 和 `variants[].anchorTransform`。

**`python_log_filename` 为空 / Python 日志未找到**
→ 在 session 目录里手动放入 Python runtime JSONL，或运行时加参数：

```powershell
pixi run python -m egoanchor.eval.research.rq1.analyze `
    --session data/eval/<session_id>
```

（`analyze.py` 会自动扫描同目录唯一的 `.jsonl` 文件）

**`detect_scenarios` 没有检测到 `static` 段**
→ GT 速度太高（手柄一直在动），或 `render_mono_ms` 时序混乱。先看 `segments.csv`。

---

## 七、完整工作流一览

```
采集阶段                          分析阶段
─────────                        ─────────
Python 服务启动                  data/eval/ 有完整数据?
    ↓                                ↓  --check-data
Unity Play 自动录制              批量分析 run_rq1.py
    ↓                                ↓
Unity 停止 → manifest 写出       data/research/rq1/
    ↓                                ├── <session>/summary.md  ← 逐session看
Mutagen 同步 Python 日志         ├── rq1_aggregate.csv        ← 论文用
    ↓                                └── rq1_summary.csv       ← 原始数据
data/eval/<session_id>/
```
