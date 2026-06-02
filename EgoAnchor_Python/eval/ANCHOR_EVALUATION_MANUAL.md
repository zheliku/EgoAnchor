# EgoAnchor Anchor 评测教程手册

本文面向当前 EgoAnchor 评估链路，目标是回答三个问题：

1. 当前 report 里哪些指标能看，哪些是因为没采到数据所以为空。
2. 如何重新录制一份能评估 anchor pose 精度的数据。
3. 最关心 pose 精度对齐时，应该优先看哪些指标。

## 1. 先读懂你当前这两份 session

当前你关心的两份 session 是：

```text
EgoAnchor_Python/data/eval/20260602_190912_controller_right
EgoAnchor_Python/data/eval/20260602_231020_controller_right
```

### 1.1 20260602_190912_controller_right

```text
gt_source = transform
gt_transform = OVRControllerPrefab
capture_rows = 411
output_rows = 2234
pose_rows = 4541
kalman.stable_rows = 1117
raw.stable_rows = 0
kalman.anchor_pose_source_counts = {"legacy_aligned_raw": 1117}
raw.anchor_pose_source_counts = {"none": 1117}
aligned_raw.translation_median_m ~= 0.0245
aligned_raw.translation_p95_m ~= 0.1794
aligned_raw.rotation_median_deg ~= 178.7
```

这说明：

- Python 和 Unity 日志已经能 join，latency 也能算。
- GT 语义是正确的 Transform GT，不需要旧版 hand-eye P2。
- 这份旧数据原始录制时没有正式 `stable_pos/stable_rot`，现在已把主变体 `aligned_raw_pos/aligned_raw_rot` 迁移为 `kalman.stable_pos/stable_rot`，来源标记为 `legacy_aligned_raw`。
- 它可以用于粗略分析静止阶段的 anchor 与 GT 偏移，但不能代表新版 recorder 直接读取最终 `anchorTransform` 的正式实验。
- `raw` 变体仍然没有 stable pose，因此 raw 的正式 anchor error 不会出现。

它的 `report/pose_offset_summary.csv` 中，`static/kalman` 的关键数值是：

```text
position_offset_median_xyz ~= [0.0064, -0.0133, 0.0193] m
position_offset_median_norm ~= 0.0243 m
position_residual_after_median_p50 ~= 0.0022 m
position_residual_after_median_p95 ~= 0.1603 m
rotation_offset_median_euler_xyz ~= [2.63, 0.97, 178.78] deg
rotation_offset_median_deg ~= 178.62 deg
```

这组数据的 median offset 有参考价值，但 p95 residual 很大，说明旧数据尾部并不像一个完全稳定的固定平移偏置。

### 1.2 20260602_231020_controller_right

```text
gt_source = transform
gt_transform = OVRControllerPrefab
capture_rows = 4184
output_rows = 22236
pose_rows = 2379
kalman.stable_rows = 11118
raw.stable_rows = 11118
kalman.anchor_pose_source_counts = {"transform": 11118}
raw.anchor_pose_source_counts = {"transform": 11118}
```

这份数据是更适合正式分析的 session，因为 `kalman` 和 `raw` 都由 Unity recorder 直接读取最终输出 Transform。它的 `static/kalman` 固定偏移诊断是：

```text
position_offset_median_xyz ~= [0.0070, -0.0097, 0.0144] m
position_offset_median_norm ~= 0.0187 m
position_residual_after_median_p50 ~= 0.0022 m
position_residual_after_median_p95 ~= 0.0044 m
rotation_offset_median_euler_xyz ~= [3.87, 1.03, 178.61] deg
rotation_offset_median_deg ~= 178.58 deg
```

这更像固定偏移：减掉 median position offset 后，静止阶段剩余误差 p50 约 2.2 mm，p95 约 4.4 mm。后续如果要手动补偿，优先以这份 `static/kalman` 的 median position offset 作为候选值。

## 2. 为什么有些图没有画出有效曲线

如果 report 中这些表是空或 `insufficient_data`，通常不是程序坏了，而是该指标需要的实验条件没有采到：

```text
anchor_error_summary
jitter_summary
slip_summary
lag_summary
jump_suppression_summary
recovery_summary
```

原因分别是：

| 图/表 | 需要什么数据 | 当前缺什么 |
|---|---|---|
| `error_timeline` / `anchor_error_summary` | `gt_pose_valid=true` 且 variant `has_stable=true` | 检查 `stable_rows` |
| `jitter_summary` / `jitter_lag` | 有 stable anchor pose，且有 `static` 窗口 | 检查是否按 1 录了 static |
| `slip_summary` / `slip_timeline` | 有 GT、head pose、stable anchor pose | 检查 `head_pos/head_rot` 与 `stable_rows` |
| `lag_summary` | 有 `object_motion` 段，且至少几帧连续 stable pose | 检查是否按 4 录了 object_motion |
| `jump_suppression_summary` | raw/stable 都有可计算误差 | 检查 raw 与 stable 是否都 `stable_rows>0` |
| `recovery_summary` | 有 event marker，且 marker 后 anchor 重新进入低误差 | 检查是否按 O/V/R 打 marker |

对旧 `20260602_190912_controller_right` 来说，`kalman` 已能出 `anchor_error` 和 `pose_offset`，但 `raw` 没有 stable pose，且只录了少量 static/unlabeled，所以 lag/recovery 等仍然没有足够条件。对新 `20260602_231020_controller_right` 来说，`kalman/raw` 都有正式 Transform 输出，可以优先看 `static/slow_head/fast_head/object_motion` 的误差和固定偏移。

## 3. 重新录制前的 Unity 检查

在 Unity 场景中找到挂了 `AnchorEvalRecorder` 的 `EvalRig`，逐项检查。

### 3.1 GT 绑定

`groundTruthTransform` 应绑定真实控制器的可视 Transform，例如：

```text
OVRControllerPrefab
```

不要绑定：

```text
AnchorObject
AnchorObject Raw
CenterEyeAnchor
任何 runtime 输出物体
```

GT 是答案，anchor 是被评估对象，这两个不能是同一个 Transform。

### 3.2 Variant 绑定

`recordedRuntimes` 至少建议两项：

| label | runtime | anchorTransform | isPrimary |
|---|---|---|---|
| `kalman` 或 `stable` | 稳定版 `PoseToAnchorRuntime` | 实际显示稳定 anchor 的 `AnchorObject` Transform | true |
| `raw` | raw 版 `PoseToAnchorRuntime` | 实际显示 raw anchor 的 `AnchorObject Raw` Transform | false |

重点是 `anchorTransform` 必须拖实际输出物体。否则 report 会继续显示：

```text
stable_rows = 0
anchor_pose_source_counts = {"none": ...}
```

### 3.3 Frame alignment 绑定

确认这些引用和主 runtime 共用同一实例：

```text
stereoSource
framePoseHistory
alignmentReference = Left
headAnchor = OVRCameraRig/CenterEyeAnchor
```

如果 `PoseResultReceiver decoded` 在增加但 aligned 为 0，先查 `FramePoseHistory` 是否共用、`frame_id` 是否透传、`alignmentReference` 是否是 `Left`。

### 3.4 Unity 原始日志旋转字段

Unity 录制时会同时写两套旋转字段：

```text
gt_rot / stable_rot / aligned_raw_rot       # xyzw 四元数，供 Python 离线计算使用
gt_euler_deg / stable_euler_deg / aligned_raw_euler_deg  # xyz 欧拉角，供人工查看
```

`*_euler_deg` 统一在 `[0, 360)` 区间，所以不会出现 `-30` 这种负角度；同一个方向会写成 `330`。正式指标计算仍使用四元数，避免 Euler 万向节和插值问题；报告中给你看的旋转 offset 则写成 0-360 Euler。

## 4. 推荐录制流程

### 4.1 录制前准备

在 `EgoAnchor_Python` 目录启动 Python：

```powershell
pixi run controller_right
```

左手柄则：

```powershell
pixi run controller_left
```

Unity 进入 Play 前确认：

```text
[ ] EvalSessionController.objectId 与 Python --object 一致
[ ] AnchorEvalRecorder.groundTruthTransform = OVRControllerPrefab
[ ] recordedRuntimes[*].runtime 已绑定
[ ] recordedRuntimes[*].anchorTransform 已绑定实际输出 AnchorObject
[ ] headAnchor = CenterEyeAnchor
[ ] alignmentReference = Left
```

Unity 进入 Play 后，先确认视觉上 anchor 已经出现并跟着目标大体稳定。然后开始录制。

### 4.2 热键表

当前 `EvalSessionHotkeyDriver` 热键如下：

| 热键 | 动作 |
|---|---|
| F7 | 开始 session |
| F8 | 停止 session，自动关闭当前 condition 并写 manifest |
| 0 | 结束当前 condition |
| 1 | 开始 `static` |
| 2 | 开始 `slow_head` |
| 3 | 开始 `fast_head` |
| 4 | 开始 `object_motion` |
| 5 | 开始 `occlusion` |
| 6 | 开始 `out_of_view` |
| 7 | 开始 `lighting` |
| O | 记录 `occlusion` marker |
| V | 记录 `out_of_view` marker |
| R | 记录 `recovery` marker |

按下新的 condition 键会自动结束上一个 condition；所以通常不必每段之间按 0。只有想手动留一个无标签间隔时才按 0。

### 4.3 完整协议怎么操作

建议按下面顺序录。每段开始时先按对应数字键，再执行动作。

| 顺序 | 热键 | condition | 时长 | 物体怎么动 | 头显怎么动 | 目的 |
|---|---|---|---:|---|---|---|
| 1 | 1 | `static` | 30s | 物体/手柄保持不动，尽量在视野中央 | 头也尽量不动，只做自然微小晃动 | 测静态 pose 对齐和基础误差 |
| 2 | 2 | `slow_head` | 30s | 物体保持不动 | 缓慢左右转头、上下看、轻微前后/左右移动 | 测 frame alignment 和头动下 world consistency |
| 3 | 3 | `fast_head` | 20s | 物体保持不动 | 快速左右/上下转头，但不要把物体甩出视野太久 | 测延迟、frame alignment 和快速头动 slip |
| 4 | 4 | `object_motion` | 30s | 缓慢平移物体，并绕 x/y/z 三轴充分旋转 | 头保持相对稳定，尽量一直看着物体 | 测跟踪精度、旋转精度、lag |
| 5 | 5 | `occlusion` | 20s | 物体基本不动，用手或遮挡物部分挡住；遮挡开始时按 O，恢复清晰时按 R | 头保持能看见物体区域 | 测遮挡下 hold/reject/recovery |
| 6 | 6 | `out_of_view` | 5 次 | 将物体移出视野；移出瞬间按 V，重新回到视野并可见时按 R | 头保持自然观察 | 测丢失后重获 |
| 7 | 7 | `lighting` | 20s | 物体基本不动 | 头正常观察；改变光照、背景或角度 | 测光照/背景变化鲁棒性 |

结束时按 F8。

### 4.4 一次完整录制的按键脚本

可以照这个节奏做：

```text
F7    开始 session
1     static，静止 30s
2     slow_head，慢慢左右/上下看 30s
3     fast_head，快速头动 20s
4     object_motion，移动并旋转手柄 30s
5     occlusion，开始遮挡段
O     遮挡开始
R     遮挡结束/恢复可见
6     out_of_view，开始出视野段
V     第 1 次移出视野
R     第 1 次回到视野
V/R   重复 4 次
7     lighting，改变光照/背景 20s
F8    停止 session
```

如果你只想先排查 pose 精度对齐，最小录制可以是：

```text
F7 -> 1 static 30s -> 2 slow_head 30s -> 3 fast_head 20s -> F8
```

如果要看旋转和物体运动时的误差，再加：

```text
4 object_motion 30s
```

如果你现在最关心 pose 精度对齐，至少要录前三段：

```text
static + slow_head + fast_head
```

这三段能区分三类问题：

- `static` 已经误差大：GT/anchor 局部坐标、模型原点或基础 pose 有问题。
- `static` 好、`slow_head/fast_head` 变差：frame alignment、latency 或 head-motion-induced slip 有问题。
- raw 好但 stable 差：滤波器、policy 或输出 Transform 绑定有问题。

### 4.5 每个标签能分析什么

| condition | 能看的主指标 | 不能指望它回答什么 |
|---|---|---|
| `static` | `anchor_error`、`jitter`、静态旋转/平移对齐 | lag、recovery |
| `slow_head` | 头动下 `anchor_error`、`slip`、frame alignment 稳定性 | 物体运动 lag |
| `fast_head` | 快速头动下 slip、延迟导致的误差尖峰 | 物体自身运动精度 |
| `object_motion` | 运动 pose 精度、旋转精度、lag | 遮挡恢复 |
| `occlusion` | policy reject/hold、jump suppression、recovery | 纯静态精度基线 |
| `out_of_view` | lost/relocalizing/recovery time | 细粒度静态 jitter |
| `lighting` | 光照变化下的失败率、误差变化 | 几何 lag |

## 5. 运行评估命令

录制结束后，在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run eval --session-dir data/eval/<session_id>
```

只看表格：

```powershell
pixi run eval-metrics --session-dir data/eval/<session_id>
```

只重画图：

```powershell
pixi run eval-figures --session-dir data/eval/<session_id>
```

结果目录：

```text
data/eval/<session_id>/report/
```

## 6. Pose 精度对齐最该看什么

按这个顺序看，不要一上来盯所有图。

### 第一步：看 `gt_anchor_sanity.json`

先确认评估语义成立：

```text
gt_source == "transform"
gt_transform 是真实控制器 Transform
variants.<label>.stable_rows > 0
variants.<label>.anchor_pose_source_counts 里 transform > 0
```

如果 `stable_rows=0`，先不要看 pose 精度。此时没有正式 anchor pose 被记录，误差表是空的。

`aligned_raw_error` 只用于诊断主变体 raw 输入质量。它不是最终 anchor 精度，因为它不一定是最终显示的 Transform。

### 第二步：看 `anchor_error_summary.csv`

这是 pose 精度对齐的主表。

最重要列：

```text
translation_median_m
translation_p95_m
rotation_median_deg
rotation_p95_deg
```

解释：

- `translation_median_m`：典型位置误差，越小越好。
- `translation_p95_m`：尾部误差，反映偶发跳变或失败。
- `rotation_median_deg`：典型旋转误差。
- `rotation_p95_deg`：旋转尾部错误。

建议先比较：

```text
condition = static, slow_head, fast_head
label = raw vs stable/kalman/controller
```

### 第三步：看 `pose_offset_summary.csv`

这是判断“是不是固定偏移”的主表。它不是额外的旧 aligned_raw 表，而是直接从正式 `anchor_error_detail` 里汇总出来的 `anchor - gt` offset。

最重要列：

```text
position_offset_median_x_m
position_offset_median_y_m
position_offset_median_z_m
position_offset_median_norm_m
position_residual_after_median_p50_m
position_residual_after_median_p95_m
rotation_offset_median_euler_x_deg
rotation_offset_median_euler_y_deg
rotation_offset_median_euler_z_deg
rotation_offset_median_deg
```

定义：

- `position_offset_*_m = anchor_pos - gt_pos`，坐标轴是 Unity world xyz。
- `rotation_offset_euler_*_deg` 是 `inv(gt_rot) * anchor_rot` 的 `xyz` 欧拉角，单位是度，统一在 `[0, 360)` 区间。
- `rotation_offset_median_deg` 是同一个相对旋转的最小夹角大小，适合做总体误差；Euler xyz 适合人眼判断是哪根轴有固定偏差。
- `position_residual_after_median_*_m` 是减掉 median position offset 后还剩多少残差。

怎么判断固定平移偏移：

- `position_offset_median_*_m` 长期稳定，且 `position_residual_after_median_p95_m` 很小：可以考虑手动加一个固定 offset。
- median 看起来固定，但 residual p95 很大：可能有失败帧、错帧、跟踪跳变或 motion 条件混进来了，不能只靠一个固定 offset 解释。
- `static` 很固定，`slow_head/fast_head` residual 变大：基础深度/原点偏移可能存在，但 frame alignment 或 latency 也在贡献误差。

按你这两份数据看：

```text
190912 static/kalman median ~= [0.0064, -0.0133, 0.0193] m，residual p95 ~= 0.1603 m
231020 static/kalman median ~= [0.0070, -0.0097, 0.0144] m，residual p95 ~= 0.0044 m
```

所以 231020 更适合拿来估计固定 position offset；190912 的尾部太大，更像有少量异常或记录条件不完整。

### 第四步：看 `error_timeline.png`

这张图用于定位“误差什么时候变大”。

典型读法：

- 一开始就高：GT Transform、anchorTransform、模型 pivot 或坐标轴语义不一致。
- 头动时尖峰：frame-aligned anchoring 或 latency 问题。
- 遮挡后升高但恢复慢：recovery/policy 问题。
- raw 有尖峰、stable 平滑：滤波/策略起作用。

### 第五步：看 `anchor_error_detail.csv`

如果 summary 不好，进 detail 查每一帧：

```text
render_mono_ms
condition
label
source_frame_id
position_offset_x_m
position_offset_y_m
position_offset_z_m
rotation_offset_euler_x_deg
rotation_offset_euler_y_deg
rotation_offset_euler_z_deg
translation_error_m
rotation_error_deg
anchor_state
policy_action
policy_reason
```

用它回答：

- 是哪个 `source_frame_id` 错了？
- 错误发生时 policy 是 Accept、Hold、Reject 还是 Lost？
- raw 和 stable 在同一帧谁更差？

## 7. 旋转误差接近 180 度怎么判断

当前两份样例的 `rotation_offset_median_deg` 都接近 180 度，而且 0-360 Euler 列里主要表现为：

```text
rotation_offset_median_euler_z_deg ~= 178 deg
```

这通常有三种可能：

1. GT Transform 的局部轴和被评估 mesh/anchor 局部轴差一个固定旋转。
2. OpenCV camera pose 到 Unity world pose 的轴转换或模型前向轴存在固定偏差。
3. 控制器/目标物体存在近似对称，视觉上位置对了，但 orientation metric 用的局部坐标系不一致。

排查方法：

1. 录一段 `static`，保持控制器姿态固定。
2. 确保 `stable_rows>0`。
3. 看 `pose_offset_summary.csv` 的 `rotation_offset_median_euler_x/y/z_deg` 是否长期接近一个常数，例如某一轴接近 90、180、270 或 330。
4. 如果平移误差小、旋转误差恒定大，优先查 GT Transform 轴、mesh 原点、anchor object 的模型旋转 offset，而不是先改滤波器。
5. 如果旋转误差随头动或遮挡剧烈变化，再查 pose tracking 和 frame alignment。

注意：这不是恢复旧 hand-eye P2。旧 P2 是 SDK 原点到 mesh 原点。现在的问题如果存在，更像是 GT Transform 和 anchor mesh 的局部轴定义不一致，需要在 Unity 绑定/模型 offset/评估语义中明确，而不是让 Python 离线估一个自由 `X` 把误差吃掉。

## 8. 其它指标怎么用

### latency_summary.csv

当前这份 session 有 latency 数据：

```text
static capture_to_apply_p50_ms ~= 175.9 ms
perception_total_p50_ms ~= 137.3 ms
publish_to_apply_est_p50_ms ~= 40.2 ms
```

它回答“慢不慢”，不是直接回答“准不准”。但如果 `slow_head/fast_head` 下误差变大，latency 是重要解释变量。

### slip_summary.csv

回答“头动时 anchor 是否在屏幕上滑动”。它需要 stable anchor pose。适合证明 frame-aligned anchoring 的价值。

### jitter_summary.csv

回答“物体静止时 anchor 是否抖”。它不是绝对 pose 精度，而是稳定性。stable 应该比 raw 更低 jitter，但可能带来 lag。

### lag_summary.csv

回答“物体运动时 stable 是否滞后”。需要 `object_motion` 段。

### jump_suppression_summary.csv

回答“policy/filter 是否压住 raw 的尖峰”。需要 raw 和 stable 都有可评估 pose。

### recovery_summary.csv

回答“遮挡或出视野后多久恢复”。需要 event marker，例如 O/V/R。

## 9. 一份合格 pose 精度 session 的检查清单

录完后先打开 `gt_anchor_sanity.json`，确认：

```text
[ ] gt_source = transform
[ ] gt_transform 是真实控制器 Transform
[ ] capture_rows > 0
[ ] pose_rows > 0
[ ] output_rows > 0
[ ] 每个要评估的 variant stable_rows > 0
[ ] anchor_pose_source_counts 里 transform > 0
[ ] condition_spans 覆盖 static/slow_head/fast_head/object_motion
```

然后看 `anchor_error_summary.csv`：

```text
[ ] static translation_median_m
[ ] static rotation_median_deg
[ ] slow_head translation_p95_m
[ ] fast_head translation_p95_m
[ ] raw vs stable/kalman/controller 对比
```

如果怀疑固定偏移，再看 `pose_offset_summary.csv`：

```text
[ ] static position_offset_median_x/y/z_m
[ ] static position_residual_after_median_p95_m
[ ] static rotation_offset_median_euler_x/y/z_deg
```

最后看图：

```text
[ ] error_timeline.png
[ ] latency_breakdown.png
[ ] slip_timeline.png
[ ] jitter_lag.png
```

## 10. 当前你下一步具体该做什么

1. 先以 `20260602_231020_controller_right/report/pose_offset_summary.csv` 的 `static/kalman` 作为固定 position offset 候选：

```text
anchor_pos - gt_pos ~= [0.0070, -0.0097, 0.0144] m
```

如果你的补偿逻辑是“直接给最终 anchor world position 加 correction”，那么 correction 方向应是：

```text
gt_pos - anchor_pos ~= [-0.0070, 0.0097, -0.0144] m
```

如果补偿写在 camera/local/model 坐标里，不要直接照抄这个 world xyz，需要按对应坐标系转换。

2. 暂时不要先用离线 P2 hand-eye 吃掉误差。你现在更需要确认这个 offset 在多次 `static` session 中是否重复出现。
3. 重新录一个短验证 session：`static 30s + slow_head 30s + fast_head 20s`。
4. 跑：

```powershell
cd P:\VSCode-Project\EgoAnchor\EgoAnchor_Python
pixi run eval --session-dir data/eval/<new_session_id>
```

5. 打开：

```text
data/eval/<new_session_id>/report/gt_anchor_sanity.json
```

确认 `stable_rows > 0` 且 `anchor_pose_source_counts` 里是 `transform`。

6. 再看：

```text
anchor_error_summary.csv
pose_offset_summary.csv
error_timeline.png
```

如果补偿后 `static translation_median_m` 明显下降，且 `position_residual_after_median_p95_m` 仍保持几毫米级，说明固定平移 offset 的假设成立。旋转上先查 Unity GT Transform、mesh local axes 和 anchor object 模型旋转，因为当前主要是固定的 Euler z 轴接近 180 度，而不是随机旋转噪声。
