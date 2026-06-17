# EgoAnchor pose 评分机制说明

本文档说明当前 Python 端 pose reliability score 的计算方式。对应代码入口是 `src/egoanchor/reliability/pose_quality.py`，配置入口是 `src/egoanchor/config/defaults.toml` 的 `[reliability.pose_score]`。

## 1. 评分目标

EgoAnchor 的 pose 评分不是模型置信度，也不是 ADD/ADD-S 这类离线 pose accuracy。它回答的是一个运行时问题：

> 这一帧外部感知返回的 object pose，是否适合作为 Unity real-object anchor 的观测输入？

因此评分既要反映几何错误，也要避免把遮挡、快速运动、暂时没有渲染质量信号这些情况误判成 pose 错。当前设计把最终分拆成三层：

```text
final = gate * quality * confidence
```

- `gate`：阶段和近期 reject 的硬约束，决定这帧最高能给多少分。
- `quality`：当前帧 pose 质量，核心由 reprojection/depth 几何证据决定。
- `confidence`：连续高质量 pose 的 warmup，避免刚注册后一帧就满信任。

`PoseResult.reliability_score` 和 runtime JSONL 里的 `pose_score` 都是这里的 `final`。

## 2. 总体公式

当前 `quality` 不再使用四项加权和，而是：

```text
core    = weighted_geometric_mean(valid reprojection, valid depth)
mod     = bounded(mask_score, mask_floor)
quality = clamp01(core * mod)
final   = clamp01(gate * quality * confidence)
```

关键点：

- `reprojection` 和 `depth` 是 pose 几何正确性的证据。两者是合取关系，只要其中一个有效信号很低，几何核就会明显下降。
- `mask` 和 `jump` 不是 pose 几何正确性的直接证据。遮挡会让 mask 小，快速头动会让 jump 变大，但它们不一定说明 pose 算错了，所以只做有下限的调制。
- `score_reprojection`、`score_depth`、`score_mask`、`score_jump` 仍按原始诊断值写入 HUD、JSONL 和 PoseResult。valid 标志只影响 `quality` 合成，不改变这些可见子分。

## 3. Gate 层

`gate = phase_score * reject_score`

`phase_score`：

- `TRACK`、`REGISTER`、`RE_REGISTER`：1.0。
- 其它 phase：0.7，并写入 `phase_<name>` flag。

`reject_score`：

- 没有近期 track reject：1.0。
- `track_reject_count > 0`：写入 `recent_track_reject`，分数按次数下降，最低保留 0.25。

Gate 层不判断渲染质量。它只限制明显不稳定的 pipeline 状态。

## 4. 几何核：reprojection 和 depth

几何核只纳入 valid 的几何信号：

```text
core = exp(sum(weight_i * log(max(score_i, geo_floor))) / sum(weight_i))
```

默认配置：

```toml
geo_floor = 0.05
reproj_weight = 0.5
depth_weight = 0.5
```

`geo_floor` 防止单帧低分直接变成数学上的 0，同时仍保留排序信息。比如 `reprojection=0.81`、`depth=0.0` 时，depth 会按 0.05 进入几何核：

```text
core = sqrt(0.81 * 0.05) ~= 0.20
```

这正是当前机制想要的行为：颜色看起来对，但深度有效低分，说明 pose 几何仍然不可信。

## 5. Reprojection 子分

输入字段：

- `track_reprojection`
- `render_quality_expected`

规则：

| 情况 | `score_reprojection` | valid | flag |
| ---- | -------------------- | ----- | ---- |
| `track_reprojection >= 0` | `clamp01(track_reprojection)` | true | 低于 0.5 写 `reprojection_low` |
| `track_reprojection < 0` 且 `render_quality_expected=false` | 1.0 | false | `no_reprojection_signal` |
| `track_reprojection < 0` 且 `render_quality_expected=true` | 0.30 | true | `reprojection_missing_expected` |

这里的 1.0 不表示 pose 很好，只表示"没有可用重投影信号，不用它惩罚几何核"。如果本来应该有信号却缺失，则按 0.30 作为有效低分进入几何核。

## 6. Depth 子分

输入字段：

- `depth_valid_in_mask`
- `render_quality_depth_alignment`
- `render_quality_depth_inlier`
- `render_quality_depth_residual_m`
- `render_quality_status`
- `render_quality_expected`

规则：

| 情况 | `score_depth` | valid | flag |
| ---- | ------------- | ----- | ---- |
| `depth_valid_in_mask < 0.10` | 0.5 | false | `depth_coverage_insufficient` |
| 有渲染深度信号 | `clamp01(render_quality_depth_alignment)` | true | 低于 0.5 写 `depth_alignment_low` |
| expected 但缺少渲染深度信号 | 0.5 | false | `depth_alignment_missing_expected` |
| 未 expected 且缺少渲染深度信号 | 0.5 | false | `no_depth_alignment_signal` |

有渲染深度信号的判定是：

```text
render_quality_status.startswith("valid")
or render_quality_depth_inlier > 0
or render_quality_depth_residual_m > 0
```

`score_depth=0.5` 在这里主要是 HUD/JSONL 的中性显示值。coverage 不足或缺少渲染深度信号时，depth 不进入几何核。

## 7. Mask 调制

`score_mask` 的来源分两种。

如果有投影面积信号：

```text
score_mask = render_quality_area_ratio_score
```

它表示观测 Cutie mask 面积和渲染投影面积的相对关系。低值通常说明遮挡、mask 丢失，或投影面积明显不匹配。对应 flag：

- `< 0.35`：`mask_visible_area_low`
- `< 0.65`：`mask_visible_area_mid`

如果没有投影面积信号，则退回全图 mask 面积比例 `mask_area_ratio`：

- 太小：写 `mask_too_small`，分数从 0.3 附近平滑上升。
- 正常范围：1.0。
- 太大：写 `mask_too_large`，分数平滑下降。

mask 不直接进入几何核，而是映射为有下限的调制项：

```text
mask_mod = mask_floor + (1 - mask_floor) * clamp01(score_mask)
```

默认 `mask_floor=0.5`。即使 mask 分很低，也最多把 quality 温和压低，不会单独把 pose 判死。

## 8. Jump 子分（仅诊断，不参与评分）

`score_jump` 来自相邻接受 pose 的平移和旋转增量：

- 平移软阈值基准：`0.03 m`。
- 旋转软阈值基准：`10 deg`。
- 帧间隔按 `frame_dt_s` 自适应，低帧率时软阈值会放宽。
- 平移硬阈值：`0.6 m`。
- 旋转硬阈值：`100 deg`。

当 `score_jump < 0.5` 时写入 `near_jump_limit`。

**`score_jump` 不再参与 quality 合成（2026-06-18 起）。** 离线分析表明：逐帧跳变幅度无法区分坏 pose 和真实快速运动——坏几何帧的跳变幅度并不比正常快动大，让它调制 quality 只会误伤快速运动而几乎抓不到真正的坏 pose。因此 `score_jump` 仅作为 HUD/JSONL 诊断字段保留，坏 pose 的拒绝交给几何核（reprojection/depth）和 Unity anchor 层（几何 flag + CUSUM）。`jump_floor` 配置项保留但当前不生效。

## 9. Confidence warmup

`ConfidenceAccumulator` 用连续高质量帧控制 `confidence`：

- 初始约 0.5。
- 连续 `quality_score >= 0.6` 时逐步上升。
- 默认 10 帧到 1.0。
- 低质量帧会让计数回退。
- 无 pose 时会 reset。

这层的作用是抑制刚 register/re-register 后的瞬时满分，让 Unity 端 policy 不会对第一帧过度信任。

## 10. 典型场景

假设 `gate=1`、`confidence=1`、`mask=1`、`jump=1`。

| 场景 | 结果 |
| ---- | ---- |
| `reprojection=0.81`，`depth=0.90`，两者 valid | `quality ~= sqrt(0.81 * 0.90) = 0.85`，正常高分 |
| `reprojection=0.81`，`depth=0.0`，depth valid | `quality ~= sqrt(0.81 * 0.05) = 0.20`，深度有效失配会拉低几何核 |
| `reprojection=0.81`，depth 覆盖不足 | depth 不进入几何核，`quality ~= 0.81` |
| reprojection disabled，depth 也无信号 | core 回到 1.0，只由 mask/jump/confidence 调制 |
| mask 很低但 reprojection/depth 都好 | 不会被打到 0，只按 `mask_floor` 温和降权 |
| jump 很低但几何证据好 | 不会被打到 0，只按 `jump_floor` 温和降权 |

## 11. 配置透传

配置链路：

```text
defaults.toml [reliability.pose_score]
  -> pipeline_factory.py
  -> QuestPosePipeline.pose_score_config
  -> score_observation_breakdown(..., config=...)
```

`PoseScoreConfig` 会做基本归一化：

- `geo_floor` 限制在 `(0, 1]`。
- `reproj_weight`、`depth_weight` 小于 0 时归零。
- `mask_floor`、`jump_floor` 限制到 `[0, 1]`。
- 如果 reprojection/depth 都没有 valid 信号，或对应权重全为 0，core 返回中性 1.0。

## 12. 输出字段关系

Python `PoseObservation`、Protobuf `PoseResult` 和 runtime JSONL 会保留以下字段：

- `reliability_score` / JSONL `pose_score`：最终分。
- `reliability_flags`：降分和无信号原因。
- `score_phase`：phase 子分。
- `score_reprojection`：颜色重投影子分。
- `score_depth`：深度对齐子分。
- `score_jump`：跳变子分。
- `score_mask`：mask 子分。
- `score_reject`：近期 track reject 子分。
- `score_confidence`：warmup 置信分。
- `track_reprojection`：原始 TRACK 颜色重投影信号，`-1` 表示无有效信号。
- `render_quality_*`：渲染质量细项，用于解释 reprojection、depth 和 mask 子分。

当前没有把 `core` 和 `mod` 作为单独字段写入协议。需要排查时，可以用这些子分和 flags 还原主要原因。

## 13. 对 Unity policy 的影响

新公式会让"单项几何证据有效低分"的帧明显降分。典型例子是颜色重投影还不错，但深度对齐有效低分；旧加权和可能仍给中高分，新几何核会把它拉到低分。

因此 Unity `ReliabilityGate` 的阈值需要用新日志重新复核。当前建议：

1. Python 保持 `reliability.render_quality.mode = "score_only"`。
2. 录制真机 session。
3. 查看 `reliability_score_histogram.csv`、`track_reprojection_histogram.csv` 和 `reliability_flags`。
4. 再决定 Unity 端 accept/reject 阈值，不要沿用旧分布直接定阈。

## 14. 快速验证命令

在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python -m unittest egoanchor.tests.test_pose_quality egoanchor.tests.test_segmenter_config
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python -m unittest discover -s eval -p "test_*.py"
pixi run python -m compileall src eval
```
