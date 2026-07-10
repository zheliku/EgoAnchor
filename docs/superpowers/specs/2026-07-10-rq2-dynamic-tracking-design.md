# RQ2 动态追踪评估设计

日期：2026-07-10
主题：保留原 RQ2 研究问题与三类动态场景，修正时间语义、评估契约和论文叙述

## 目标

RQ2 保持论文既有定位：评估 EgoAnchor 在慢速平移、快速挥动与旋转运动下的动态追踪能力，并刻画系统在已测试运动范围内的精度、响应性与连续性。此次调整不改变研究问题，只修正原稿中把相机时刻错配与物体运动滞后混为一谈的问题。

完整链路包括三部分：

- Unity 记录 source frame 的图像时间代理、pose 处理时间、策略输出目标时间、runtime 输出有效性和实际显示位姿。
- Python 按 RQ2 试次计算采集时刻 raw 误差、渲染时刻各系统配置的显示误差、物体运动时延项、响应滞后与追踪可用率。
- Typst 论文保留原 RQ2 和三个场景，改写实验方法、图注、结果占位表述与讨论，避免把尚未获得的结果写成事实。

## 不变边界

- Python 始终只输出 camera-space pose；world pose、GT 与 frame alignment 继续由 Unity 拥有。
- `frame_id` 仍是视觉帧与采集时刻相机位姿的唯一对齐主键。
- RQ1 的实时逐帧误差口径与 `rq1_metric` 标注保持不变。
- RQ2 不把 *Frame-aligned* / *Arrival-aligned* 作为主实验变体。现有 arrival-time raw 仅保留为头动诊断，不进入物体速度与时延模型。

## 时间语义

每条有效 source frame 明确区分四个时刻：

1. `image_mono_ms`：与延迟 camera pose 对应的 image-time proxy，供 frame alignment、运动模型和 raw 评估使用。
2. `sender_mono_ms`：JPEG 完成后的 payload-ready/header 时刻，不代表 ZMQ 实际发包。
3. `unity_pose_handle_mono_ms`：Unity 主线程成功处理该 source frame pose 的时刻。
4. `policy_output_target_mono_ms`：平滑策略本渲染帧实际输出所对应的目标时刻。
5. `publish_attempt_mono_ms`：紧邻 ZMQ `TrySend` 前采样的发布尝试时刻；`publish_succeeded` 记录 NetMQ 是否立即接受消息。

Quest Passthrough Camera API 当前没有可直接使用的硬件曝光时间戳。`image_mono_ms` 是 `cameraPoseDelayFrames=1` 下以前一成功采集样本估计的图像时间代理，不得表述为硬件曝光真值。一次样本回退的物理时长取决于成功采集间隔，不能固定解释为一个渲染帧；正式 RQ2 需报告其时间分布，并检查 0/1/2 个成功采集样本回退的敏感性。

由此得到：

- 观测到达时延：`unity_pose_handle_mono_ms - image_mono_ms`。
- 策略有效延迟：`render_mono_ms - policy_output_target_mono_ms`；StaticLock 锁定或解锁接缝覆盖 smoothing pose 时，该字段为 NaN。
- 显示增量滞后：每个系统配置的显示轨迹滞后减 raw 实测轨迹滞后；不把自适应总目标延迟再次与感知时延相加。

## 输出有效性

`has_output_pose` 必须来自 `PoseToAnchorRuntime.TryGetOutputPose`，用于追踪可用率；`has_display_pose/display_pos/display_rot` 记录实际显示 Transform，包括 hold-last。执行顺序固定为：

- `PoseToAnchorRuntime`：`-50`，先推进 policy。
- `DynamicObjectAnchor`：`0`，应用本帧输出。
- `EvalRecorder`：`50`，最后采样显示 Transform 与 GT。

这样既不会把初始 Transform 或 Lost 后残留 Transform误记为当前有效输出，也不会从用户侧实时误差中删除 hold-last。

## RQ2 试次契约

Unity 新增独立的 `Eval/RQ2` 组件，不恢复 RQ1 已删除的 3/4/5 键：

- `rq2_condition`：`none | slow_translation | fast_motion | rotation`
- `rq2_trial_id`：当前 session 内单调递增的正整数；未开始试次时为 `-1`
- `rq2_target_linear_speed_m_s`：可选目标线速度，非平移试次为 NaN
- `rq2_target_angular_speed_deg_s`：可选目标角速度，非旋转试次为 NaN

RQ2 不设阶段状态。按 `1/2/3` 后试次立即生效，按 `0` 结束；`RQ2TrialSelector` 只持有当前试次上下文，不拥有录制状态、不写文件。`EvalRecorder` 每帧读取上下文并写入 output JSONL。Python loader 将这些字段展平到每个 variant 行，并拒绝仍含 `rq2_phase` 的旧日志。

场景同步运行 *Full* 与 *Raw-ZOH*。两者共用 PoseResult、`FramePoseHistory`、渲染 tick 与 GT；*Raw-ZOH* 使用 ConstantVelocityModel 与 RawPassthroughStrategy，对最近对齐观测作零阶保持，不启用静止锁。坐标变换、质量门控、生命周期阈值与 hold-last 语义保持一致。*Raw-ZOH* 不发起服务器重获取，只作为被动 shadow baseline。

## 指标口径

### 动态追踪精度

- 用户侧主指标：*Full* 与 *Raw-ZOH* 的 `display(t_render)` 分别同 `GT(t_render)` 计算实时平移和旋转误差，包含 hold-last。
- 感知诊断：只从 `is_primary=true` 的主变体读取 aligned raw pose；每个 `source_frame_id` 保留首次出现的一行，并与 `GT(image_mono_ms)` 比较。所有显示配置共享这份 raw 参照。
- 误差与可用率同时报告；Lost、Reject、reacquire 和无输出不能从样本中静默删除。
- 试次汇总同时报告 `display_update_rate_hz` 与 `display_hold_fraction`。前者是有效相邻渲染帧间 pose 变化事件数除以对应有效时长，后者是保持同一 pose 的样本对比例；`1e-6 m / 1e-4 deg` 以内的数值变化视为保持。

### 时延影响

不能用同一 aligned raw pose 在图像时刻与处理时刻的误差向量之差验证系统时延误差：该作差会代数消去 raw pose，只剩参考轨迹在时延窗口内的运动量。该参考运动量仅作为时延暴露量与插值自检。

系统时延模型使用 raw pose 在 Unity 处理时刻的有符号滞后残差作为观测量。线速度、运动方向、角速度和世界系旋转轴只用图像时刻之前固定 400 ms 的参考轨迹稳健拟合；平移采用 Theil-Sen 斜率，旋转采用相邻四元数的世界系 SO(3) log / dt 中位。参考轨迹保留显式有效 segment，所有插值与拟合均不得跨平台参考位姿失效空窗。观测量与 `v * tau` / `omega * tau` 的关系先按 trial 汇总，再以 trial 为 cluster 做场景级回归与 bootstrap。capture-time 有符号残差单独报告为偏置诊断，不从 handle-time 残差中相减。

轨迹 lag 只在每段至少有 16 个速度样本、观察长度覆盖候选搜索范围、峰值归一化相关不低于 0.5、Bonferroni 校正后 `p <= 0.05` 且峰值不在搜索边界时报告；其余试次记为不可辨识。

### 响应延迟

- 平移与旋转分别估计 lag；旋转信号由相邻四元数的世界系 SO(3) log / dt 构造，不能对相对首帧 rotvec 主值直接求差。
- raw 与每个显示配置分别估计，显示增量为 `lag_display - lag_raw`。
- 统计单位是 trial；帧级记录只用于构造 trial 汇总和 cluster bootstrap。
- GT 插值、pre-image 拟合和 lag 均遵守参考轨迹的显式有效 segment；lag 也不得跨 tracking/reacquire 空窗。输出连续段缺口阈值为 `max(100 ms, 2.5 × median interval)`，并以 500 ms 为绝对上限。样本量、观察长度、峰值相关、校正显著性或动态激励任一不足时返回 NaN。

## 论文结构

RQ2 主图继续采用四面板：

- A：三种运动模式下 *Full* 与 *Raw-ZOH* 的实时误差和可用率。
- B：采集时刻 raw 感知误差与渲染时刻两种系统配置的显示误差。
- C：raw 有符号 handle-time 滞后残差与 pre-image `v * tau` / `omega * tau` 预测量。
- D：观测时延、raw/*Full*/*Raw-ZOH* 实测滞后与显示增量滞后。

在没有正式 RQ2 数据前，结果段只写分析目标、判定口径和待报告量，不预写“显著降低”“高度吻合”或具体性能归因。

## 验证

- Unity EditMode 测试覆盖 output 有效性、平滑目标时间、RQ2 直接试次流程和输入回调生命周期。
- Python 测试覆盖 source-frame 去重、GT 插值、独立 capture bias、正反向运动符号、SO(3) 跨 180°连续性、低激励 lag、7 fps 连续流、reacquire 缺口、trial 聚合与 cluster bootstrap。
- 运行 Python 全量单测、Unity 主线构建与测试程序集构建。
- Typst 编译 `egoanchor_cn_v6.typ` 成功。
