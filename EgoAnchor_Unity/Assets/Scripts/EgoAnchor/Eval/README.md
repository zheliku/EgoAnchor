# RQ1 / RQ2 采集操作说明

本文说明 `EgoAnchor-RQ1.unity` 与 `EgoAnchor-RQ2.unity` 的数据采集流程。录制状态只由 `EvalSession` 管理；RQ1 指标标记和 RQ2 试次状态不会自行开启或停止日志。

## 1. 组件职责

| 组件 | 职责 |
|---|---|
| `EvalSession` | 创建 session、开始或停止录制、写 `session_manifest.json` |
| `EvalRecorder` | 写 Unity capture/output JSONL |
| `EvalStatusText` | 统一录制、session、时长和活动行文本格式 |
| `EvalLiveStats` | 显示主变体的实时监控数据，不写文件 |
| `RQ1MetricSelector` | 保存当前 RQ1 指标标记 |
| `RQ2TrialSelector` | 保存当前 RQ2 trial 与目标速度元数据 |

RQ1 与 RQ2 的状态机不同，不共用 selector。两个场景各有一个 `EvalLiveStats`，并挂在右侧 `LiveStatus` 对象上。

## 2. 开始采集

1. 在仓库的 `EgoAnchor_Python` 目录启动服务：

   ```powershell
   pixi run python .\src\run_server.py
   ```

2. 在 Unity 打开对应场景：
   - RQ1：`Assets/Scene/EgoAnchor-RQ1.unity`
   - RQ2：`Assets/Scene/EgoAnchor-RQ2.unity`
3. 进入 Play Mode，等待 Python 完成初始化并发送非空 `session_id`。
4. 看到红色 `● Recording` 后再按实验按键。
5. 全部采集结束后按 `F8`，等待控制台确认 manifest 已写入，再退出 Play Mode。

两个场景的 `EvalSession.autoStart` 均为 `true`。第一条带 Python `session_id` 的 PoseResult 到达后会自动开始录制。`F7` 仅用于手动启动；在 Python session id 到达前使用 F7，会建立无法自动配对的本地 session。

## 3. RQ1：静态锚定质量

### 按键

| 按键 | 操作 |
|---|---|
| `1` | 标记 `static_observation` |
| `2` | 标记一次 `occlusion_recovery` |
| `0` | 清除当前标记 |
| `F7` | 手动开始录制 |
| `F8` | 停止录制并写 manifest |

场景同步记录 *Full* 与 *No-StaticLock*，两者使用同一输入 pose 流和同一渲染时刻。

### 长时静止观察

1. 将目标刚体与参考控制器固定在实验位置。
2. 待锚点进入稳定状态后按 `1`。
3. 按实验协议观察目标并进行正常头部运动。面板建议时长为 80 s。
4. 结束时按 `0`。

不要在目标仍被搬动或系统尚未稳定时按 `1`，否则启动过程会进入静止场景统计。

### 遮挡恢复

每次遮挡必须形成独立的 `2 -> 0` 标记段：

1. 先遮挡目标，使追踪进入遮挡或丢失状态。
2. 揭示目标的同时按 `2`。
3. 保持标记至少 200 ms，并等待锚点恢复稳定。
4. 按 `0` 结束本次事件。
5. 下一次遮挡重新执行上述步骤。

分析程序把每个连续 `occlusion_recovery` 段的起点作为恢复 marker。不要在开始遮挡前按 `2`，也不要在一个长标记段内重复多次遮挡。

## 4. RQ2：动态追踪能力

### 按键与目标元数据

| 按键 | 试次 | 名义目标 |
|---|---|---:|
| `1` | Slow Translation | `0.10 m/s` |
| `2` | Fast Motion | `0.80 m/s` |
| `3` | Rotation | `90 deg/s` |
| `0` | 结束当前 trial | - |
| `F7` / `F8` | 开始 / 停止录制 | - |

目标速度只写入日志作为协议元数据，代码不会约束实际动作速度。离线分析使用控制器参考轨迹估计真实线速度和角速度。

### 单次 trial

1. 先将目标置于本次动作的起始姿态。
2. 动作开始时按 `1`、`2` 或 `3`，trial 立即生效。
3. 连续完成对应运动，期间不要再次按数字键。
4. 动作停止时立即按 `0` 结束 trial。

活动 trial 中再次按 `1/2/3` 会被忽略。按键到动作起点、动作终点到 `0` 键之间的静止时间也属于该 trial，因此应尽量同步操作。每种运动少于 3 个独立 trial 时，场景级 bootstrap 置信区间会是 NaN。

RQ2 同步记录 *Full* 与 *Raw-ZOH*。两者接收同一 PoseResult、使用同一帧对齐、渲染时刻和参考位姿；*Raw-ZOH* 仅对最近一帧对齐观测做零阶保持，不执行预测、插值或静止锚定，并作为不参与服务器重获取的隐藏 shadow runtime。小写 `aligned raw` 仍指图像时间代理处的感知诊断，不是 *Raw-ZOH* 系统配置。

## 5. LiveStatus 字段

| 字段 | 含义 |
|---|---|
| `Latency` | 当前 Unity 单调时刻减去最新对齐帧的图像时间代理，不是纯网络时延 |
| `Pose rate` | `LatestAlignedFrameId` 最近两次变化间隔的倒数，不是渲染帧率 |
| `Trans err` | 主变体显示 pose 与当前实时参考 pose 的欧氏距离 |
| `Rot err` | 主变体显示 pose 与当前实时参考 pose 的四元数最短夹角 |
| `Jitter` | 相邻显示帧的位移和旋转变化；RQ2 中包含真实物体运动 |
| `Score` | 优先显示 policy 接受分，否则显示可靠性分 |
| `State` | 当前锚点生命周期；`[LOCKED]` 表示静止锁定生效 |

颜色阈值：

| 场景 | Latency | 平移误差 | 旋转误差 |
|---|---:|---:|---:|
| RQ1 | 120 / 200 ms | 10 / 20 mm | 5 / 10 deg |
| RQ2 | 120 / 200 ms | 20 / 80 mm | 10 / 40 deg |

低于前一数值显示绿色，高于后一数值显示红色，中间显示黄色。实时面板直接读取参考 Transform，不使用离线日志的 `gt_pose_valid` 门控；面板显示误差不代表该帧一定进入离线统计。

## 6. 输出与分析

数据写入：

```text
EgoAnchor_Python/data/eval/<session_id>/
```

正常停止后应包含：

```text
<session_id>_python_runtime.jsonl
<session_id>_unity_capture.jsonl
<session_id>_unity_output.jsonl
session_manifest.json
```

分析命令：

```powershell
cd EgoAnchor_Python

pixi run python -m egoanchor.eval.research.rq1.analyze `
  --session-dir data/eval/<session_id>

pixi run python -m egoanchor.eval.research.rq2.analyze `
  --session-dir data/eval/<session_id>
```

RQ1 默认分析完整静止序列。RQ2 在 session 的 `report` 目录写入 source error、motion delay、trial summary、latency summary 和 model summary 五张 CSV；带 `label` 的汇总表可直接配对比较 *Full* 与 *Raw-ZOH*。`rq2_trial_summary.csv` 还包含 `display_update_rate_hz` 与 `display_hold_fraction`，分别表示显示 pose 的实际更新频率和相邻有效渲染帧保持同一 pose 的比例。

## 7. 采集后检查

1. 确认 `session_manifest.json` 存在。
2. 确认 Python 与 Unity 文件名使用同一 `session_id`。
3. 检查 Unity output JSONL 不为空。
4. RQ1 检查每次遮挡各有独立标记段。
5. RQ2 检查每个正 `rq2_trial_id` 都有合法 `rq2_condition`，且同时包含 *Full* 与 *Raw-ZOH* 两个标签。
6. 确认正式采集没有持续的 GT 无效区间。

不要在同一 Python session 中停止后再次按 F7。`EvalLog` 会以同名路径重新打开文件，可能覆盖该 session 已有的 Unity 日志。
