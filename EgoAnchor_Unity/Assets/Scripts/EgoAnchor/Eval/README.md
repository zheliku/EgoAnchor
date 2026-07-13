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

## 4. RQ2：动态锚定能力

### 按键与目标元数据

| 按键 | 试次 | 名义目标 |
|---|---|---:|
| `1` | Translation | `0.10 m/s` |
| `2` | Rotation | `90 deg/s` |
| `0` | 结束当前 trial | - |
| `F7` / `F8` | 开始 / 停止录制 | - |

目标速度只写入日志作为操作元数据，代码不会约束实际动作速度，也不再按速度拆分平移试次。离线分析使用控制器参考轨迹估计真实线速度和角速度。

### 单次 trial

1. 将目标置于固定起始点，保持头显—目标距离、照明和头部活动范围不变。
2. 按 `1` 或 `2` 开始粗试次包络，静止约 1.5 s。
3. 连续完成 8–12 s 中低速运动：平移沿标记直线在固定端点间往复，旋转围绕同一主轴交替转动，两类运动都至少包含两次方向反转。
4. 动作结束后继续静止约 1.5 s，再按 `0` 结束 trial。

活动 trial 中再次按 `1/2` 会被忽略。离线程序根据平台参考轨迹自动提取有效运动区间，前后静止段不会进入动态误差统计；因此无需用按键追逐动作起止时刻。若追踪中断，继续完成当前 trial，不删除失败片段，也不要手动重获取。

RQ2 同步记录 *Full* 与 *ZOH*。两者接收同一 PoseResult，并使用相同的帧对齐、质量门控、生命周期阈值、渲染时刻和参考位姿；*ZOH*（zero-order hold）仅保持最近一次被接受的帧对齐观测，不执行运动估计、时序插值或静止锚定。配对 RQ2 中两个系统配置均不向感知后端发起重获取，避免任一配置改变共享输入。小写 `aligned raw` 仍指图像时间代理处的感知诊断，不是 *ZOH* 系统配置。

RQ2 场景要求控制器位姿来自当前追踪样本；手柄休眠后的 keep-alive 不会被当作动态参考。参考追踪暂时失效时，对应区间保留在日志中，但不跨无效区间插值。

### 简化采集口径

- RQ2 只区分平移与旋转，不再把平移拆成慢速和快速子类。
- 两类运动均在中低速范围内完成，并固定运动端点或角度范围、目标距离、室内照明和允许的头部活动范围。
- 名义目标速度只规范操作。统计使用参考轨迹重估的实际速度；平移纳入线速度不高于 `0.8 m/s` 的新鲜有效帧，旋转纳入角速度不高于 `180 deg/s` 的新鲜有效帧。

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
  --session-dir data/eval/<session_id> `
  --figs-dir ../2026-EgoAnchor/figs/rq2 `
  --zoom-frame-count 120
```

单会话默认写入该会话的 `report` 目录；联合多个会话时可重复传入 `--session-dir`，并用 `--report-dir` 指定公共输出目录。

RQ2 输出 6 张职责分离的 CSV：

| 表 | 用途 |
|---|---|
| `rq2_session_audit.csv` | 日志丢行、manifest 双变体与动态参考新鲜度审计 |
| `rq2_trial_audit.csv` | 每个 trial 的双变体、运动时长、速度上限与参考覆盖审计 |
| `rq2_trial_summary.csv` | 每个 trial 与系统配置的连续性和渲染时刻误差 |
| `rq2_condition_summary.csv` | 平移/旋转任务的帧层描述性汇总 |
| `rq2_response_summary.csv` | 观测年龄、策略目标延迟覆盖率与可辨识运动 lag |
| `rq2_timeline_windows.csv` | 两张论文时间线的试次与固定选窗元数据 |

同时生成 `fig_rq2_position_timeline` 与 `fig_rq2_rotation_timeline` 两组 PDF/PNG。每组均为世界系 X/Y/Z 三行共享相对 Unity 渲染帧轴的 120 帧放大时间线；旋转使用相对共同起点的世界系 SO(3) 对数向量，不使用 Euler 角，也不累加相邻旋转增量。统计与绘图只纳入通过会话级和 trial 级审计的数据。

## 7. 采集后检查

1. 确认 `session_manifest.json` 存在。
2. 确认 Python 与 Unity 文件名使用同一 `session_id`。
3. 检查 Unity output JSONL 不为空。
4. RQ1 检查每次遮挡各有独立标记段。
5. RQ2 先运行单会话分析，确认 `rq2_session_audit.csv` 和 `rq2_trial_audit.csv` 的 `accepted` 均为 `true`。
6. 确认 manifest 中 capture/output 的 `dropped_rows` 均为 0，每个 trial 同时包含 *Full* 与 *ZOH*，有效运动不少于 8 s，参考覆盖率不低于 95%。
7. 分析完成后确认两张时间线均已生成，`rq2_timeline_windows.csv` 中的 `render_tick_count` 均为 120。

停止后不要在同一 Python session 中再次按 `F7`。当前实现会检测非空同名日志并拒绝重新开始，以防覆盖；新一轮录制应重启 Python 服务并使用新的 session。
