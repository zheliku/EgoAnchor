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

1. 将目标置于固定起始点，保持头显—目标距离、照明和头部活动范围不变。
2. 按 `1`、`2` 或 `3` 开始粗试次包络，静止约 1.5 s。
3. 连续完成 8–12 s 对应运动：平移沿标记直线在固定端点间往复，旋转围绕同一主轴交替转动。低速平移和旋转至少包含两次方向反转。
4. 动作结束后继续静止约 1.5 s，再按 `0` 结束 trial。

活动 trial 中再次按 `1/2/3` 会被忽略。离线程序根据平台参考轨迹自动提取有效运动区间，前后静止段不会进入动态误差统计；因此无需用按键追逐动作起止时刻。若追踪中断，继续完成当前 trial，不删除失败片段，也不要手动重获取。

RQ2 同步记录 *Full* 与 *Raw-ZOH*。两者接收同一 PoseResult，并使用相同的帧对齐、质量门控、生命周期阈值、渲染时刻和参考位姿；*Raw-ZOH* 仅对最近一次被接受观测作零阶保持，不执行运动估计、时序插值或静止锚定。配对 RQ2 中两个系统配置均不向感知后端发起重获取，避免任一配置改变共享输入。小写 `aligned raw` 仍指图像时间代理处的感知诊断，不是 *Raw-ZOH* 系统配置。

RQ2 场景要求控制器位姿来自当前追踪样本；手柄休眠后的 keep-alive 不会被当作动态参考。参考追踪暂时失效时，对应区间保留在日志中，但不跨无效区间插值。

### 正式采集设计

- 至少完成 3 个独立录制会话；每次重新启动 Python 服务和 Unity Play Mode，并复核模型—控制器外参。
- 每个会话对三类运动各录制 8 个合格 trial，共 24 个；正式数据总计至少 72 个 trial。
- 预先生成分块随机顺序，不要连续录完同一类运动。固定运动端点或角度范围、目标距离、室内照明和允许的头部活动范围。
- 名义目标速度只规范操作。正式统计使用参考轨迹重估的实际速度，不按操作者是否“精确达到”名义值删选 trial。

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
  --session-dir data/eval/<session_id_1> `
  --session-dir data/eval/<session_id_2> `
  --session-dir data/eval/<session_id_3> `
  --report-dir data/eval/rq2_combined_report
```

单会话预检查可以只传一次 `--session-dir`，默认写入该会话的 `report` 目录；联合正式分析应重复传入全部会话，并显式指定公共输出目录。

RQ2 输出 11 张职责分离的 CSV：

| 表 | 用途 |
|---|---|
| `rq2_session_audit.csv` | 日志丢行、manifest 双变体与动态参考新鲜度审计 |
| `rq2_trial_audit.csv` | 每个 trial 的双变体、有效运动、参考覆盖和 raw 产出率审计 |
| `rq2_design_audit.csv` | 3 会话 × 每类 8 次的正式设计完整性审计 |
| `rq2_trial_summary.csv` | 主终点、显示误差、可用率、保持比例和生命周期摘要 |
| `rq2_paired_summary.csv` | *Full* − *Raw-ZOH* 的试次配对差值与层级 bootstrap 区间 |
| `rq2_operating_envelope.csv` | 按实测线速度或角速度分箱的经验运行包络 |
| `rq2_source_error.csv` | 每个感知 source 首次出现时的图像时刻 raw 误差 |
| `rq2_motion_delay.csv` | 图像前运动拟合、时延暴露量与有符号 raw 滞后残差 |
| `rq2_model_summary.csv` | 运动—时延探索性关联及层级 bootstrap 区间 |
| `rq2_latency_summary.csv` | 观测、首次显示、策略目标与可辨识 lag 摘要 |
| `rq2_lag_diagnostics.csv` | 互相关峰值质量、可辨识状态与连续段数量 |

同时生成 `rq2_accuracy_primary`、`rq2_paired_tradeoff`、`rq2_delay_association` 和 `rq2_operating_envelope` 四组 PDF/PNG 图。正式统计只纳入通过会话级和 trial 级审计的数据；设计审计用于判断当前数据集能否支撑论文报告。

## 7. 采集后检查

1. 确认 `session_manifest.json` 存在。
2. 确认 Python 与 Unity 文件名使用同一 `session_id`。
3. 检查 Unity output JSONL 不为空。
4. RQ1 检查每次遮挡各有独立标记段。
5. RQ2 先运行单会话分析，确认 `rq2_session_audit.csv` 和 `rq2_trial_audit.csv` 的 `accepted` 均为 `true`。
6. 确认 manifest 中 capture/output 的 `dropped_rows` 均为 0，每个 trial 同时包含 *Full* 与 *Raw-ZOH*，有效运动不少于 8 s，参考覆盖率不低于 95%。
7. 全部会话完成后运行联合分析，确认 `rq2_design_audit.csv` 的 `study` 行通过。

停止后不要在同一 Python session 中再次按 `F7`。当前实现会检测非空同名日志并拒绝重新开始，以防覆盖；新一轮录制应重启 Python 服务并使用新的 session。
