## 评分系统优化完整计划

### 现状问题

当前 6 个子分中，只有 `consistency_score` 在正常跟踪中提供连续质量信号，其余均为"故障检测门"——正常情况下恒为 1.0，无法区分"好"和"非常好"。

此外，当前 `RenderConsistencyChecker` 将 mask IoU 和 depth 对齐混合为一个 `consistency` 分，而 `pose_quality.py` 的 `depth_score` 只看 mask 内有效深度比例，**职责混乱**。

当前纯乘法公式在多个子分同时有轻微偏差时**惩罚过重**（如 0.8 × 0.85 × 0.97 = 0.66），不能准确反映实际跟踪质量。

---

### 核心架构改动

#### 改动一：职责分离

**渲染接口**：estimator 只渲染一次，返回 color + depth + mask，在调用层拆分给两个独立评分函数（性能不变，逻辑解耦）。

```
estimator.render_color_depth_mask(pose, output_size, cam_k)
  → render_color (H×W×3), render_depth (H×W), render_mask (H×W bool)
```

**评分拆分**：

| 子分              | 重命名                  | 唯一职责                               | 输入数据                                              |
| ----------------- | ----------------------- | -------------------------------------- | ----------------------------------------------------- |
| consistency_score | →**reprojection_score** | 渲染 mask 几何重叠 + 重叠区颜色相似度  | render_color, render_mask, observed_mask, observed_rgb |
| depth_score       | depth_score（不变）     | 渲染深度 vs 观测深度对齐（仅 mask 内） | render_depth, observed_depth, intersection_mask       |

#### 改动二：评分公式从纯乘法改为 Gate × Quality 混合

**原公式**（纯乘法，惩罚过重）：

```
final = phase × consistency × depth × jump × mask × reject
```

**新公式**（门控 × 加权求和）：

```python
# Gate 层：异常时直接压制总分上限
gate = phase_score * mask_score * reject_score

# Quality 层：连续信号加权求和，提供区分度
quality = (
    W_REPROJ * reprojection_score +   # 0.45
    W_DEPTH  * depth_score +           # 0.35
    W_JUMP   * jump_score              # 0.20
)

# 最终分
final_score = clamp01(gate * quality)
```

**设计原则**：
- Gate 子分（phase, mask, reject）：非此即彼的约束，违反时拉低上限；正常时恒为 1.0
- Quality 子分（reprojection, depth, jump）：连续质量信号，线性组合避免乘法过度惩罚

**对比效果**：

| 场景                                    | 纯乘法 | 混合方案 |
| --------------------------------------- | ------ | -------- |
| reproj=0.8, depth=0.85, jump=0.97       | 0.66   | **0.85** |
| reproj=0.6, depth=0.9, jump=1.0         | 0.54   | **0.78** |
| reproj=0.3, depth=0.4, jump=0.5（真差） | 0.06   | **0.38** |
| mask 异常(gate=0.5), quality=0.85       | —      | **0.43** |

---

### 各子分改动计划

#### 1. phase_score — 不变（Gate 层）

- TRACK / REGISTER / RE_REGISTER → 1.0
- 其他 phase → 0.7
- 逻辑清晰，无需调整

---

#### 2. reprojection_score（原 consistency_score）— 几何 + 颜色（Quality 层）

**职责**：物体重投影回相机平面的综合分（mask 重叠 + 颜色相似度），不含 depth

**拆分来源**：原 `RenderConsistencyChecker` 的 mask IoU 部分 + 新增颜色对比

**实现**：新建 `ReprojectionChecker`

- mask_alignment：IoU × observed_visible_ratio 的几何平均
- color_similarity：intersection 区域中心 70%（排除边缘锯齿）的 LAB 颜色相似度
- 综合公式：`score = iou_weight * mask_alignment + color_weight * color_similarity`
- 权重：`iou_weight=0.5, color_weight=0.5`

**颜色相似度计算（LAB 空间，对光照鲁棒）**：

```python
# 在 intersection 区域内，排除边缘 15% 像素（erosion）
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
core_mask = cv2.erode(intersection.astype(np.uint8), kernel) > 0

# 转 LAB 空间：分离亮度和色度，对白平衡/光照变化鲁棒
render_lab = cv2.cvtColor(render_color, cv2.COLOR_RGB2LAB).astype(np.float32)
observed_lab = cv2.cvtColor(observed_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)

# core_mask 内像素的 LAB L2 距离
diff = np.linalg.norm(render_lab[core_mask] - observed_lab[core_mask], axis=1)
color_similarity = clamp01(1.0 - np.mean(diff) / 180.0)  # LAB 实际范围 ~[0,255]，取 180 作为归一化上界
```

**选择 LAB 而非 RGB 的原因**：
- RGB L2 对光照/白平衡微小变化非常敏感
- LAB 将亮度（L）和色度（a, b）解耦，即使光照偏移，色度距离仍稳定
- 渲染图和实拍图之间天然存在光照差异，LAB 能显著降低误报

---

#### 3. depth_score — 渲染深度 vs 观测深度对齐（Quality 层）

**职责**：渲染出的物体表面深度与 FFS 估计深度在 mask 内的对齐程度

**拆分来源**：原 `RenderConsistencyChecker` 的 depth_alignment 部分

**实现**：新建 `DepthAlignmentChecker`

**改动 A — 自适应阈值**：

```python
# 根据物体到相机距离自适应
pose_distance = np.linalg.norm(pose_cv_camera[:3, 3])
inlier_thresh = max(0.005, pose_distance * 0.02)
# 例如距离 0.24m → 阈值 5mm
# 距离 1.0m → 阈值 2cm
```

**改动 B — depth 有效覆盖作为前置条件**：

原 `depth_score` 衡量的"mask 内有效深度比例"不是 pose 质量信号，而是**输入质量信号**。将其改为 depth_alignment 的前置条件：

```python
depth_coverage = observation.depth_valid_in_mask

if depth_coverage < 0.10:
    # depth 信号本身不可靠，给中性值（不奖不罚）
    flags.append("depth_coverage_insufficient")
    return 0.5  # 中性值，不拉高也不拉低 quality

# depth 覆盖足够，正常计算深度对齐
depth_alignment_score = _compute_depth_alignment(...)
```

**改动 C — 无渲染时 fallback**：

```python
# 渲染失败时，用 pose 预测距离 vs depth median 做粗略校验
if render_failed and depth_median_in_mask > 0:
    expected_z = pose_cv_camera[2, 3]
    ratio = min(expected_z, depth_median_in_mask) / max(expected_z, depth_median_in_mask)
    return clamp01(ratio)
```

**评分公式**：

```python
depth_inlier = np.mean(residual < inlier_thresh)
median_score = 1.0 - depth_median_residual / (inlier_thresh * 3.0)
depth_alignment_score = clamp01(0.5 * depth_inlier + 0.5 * median_score)
```

---

#### 4. jump_score — 双层阈值 + 帧间隔自适应（Quality 层）

**职责**：相邻帧 pose 跳变惩罚

**问题**：当前硬阈值 0.6m / 100° 太宽，正常帧 ratio ≈ 0.002，完全无区分度。且固定阈值未考虑帧间隔——帧率低时正常运动也可能触发惩罚。

**改动 — 引入软阈值 + 帧间隔自适应**：

```python
BASE_SOFT_TRANSLATION_M = 0.03      # 基准：超过 3cm 开始降分（按 30fps 设定）
HARD_TRANSLATION_M = 0.6            # 完全不可接受（绝对上限，不随帧率缩放）

BASE_SOFT_ROTATION_DEG = 10.0       # 基准：超过 10° 开始降分（按 30fps 设定）
HARD_ROTATION_DEG = 100.0           # 完全不可接受（绝对上限，不随帧率缩放）

EXPECTED_DT = 1.0 / 30.0            # 基准帧间隔（30fps）

def _jump_score(observation, flags):
    t_delta = abs(observation.last_translation_delta_m)
    r_delta = abs(observation.last_rotation_delta_deg)

    # 根据实际帧间隔缩放软阈值
    # Python 服务器 5-6fps → dt ≈ 170-200ms → dt_scale ≈ 5-6
    # 此时 soft_t ≈ 15-18cm, soft_r ≈ 50-60°
    dt = max(observation.frame_dt, 1e-3)  # 实际帧间隔（秒）
    dt_scale = clamp(dt / EXPECTED_DT, 0.5, 8.0)  # 限制缩放范围
    soft_t = BASE_SOFT_TRANSLATION_M * dt_scale
    soft_r = BASE_SOFT_ROTATION_DEG * dt_scale

    if t_delta <= soft_t:
        t_score = 1.0
    else:
        t_score = 1.0 - (t_delta - soft_t) / (HARD_TRANSLATION_M - soft_t)

    if r_delta <= soft_r:
        r_score = 1.0
    else:
        r_score = 1.0 - (r_delta - soft_r) / (HARD_ROTATION_DEG - soft_r)

    score = clamp01(min(t_score, r_score))
    if score < 0.5:
        flags.append("near_jump_limit")
    return score
```

**帧间隔自适应的原因**：

delta 是 Python 服务器相邻两次输出之间的 pose 差值，帧间隔由 Python 处理速度决定：
- 当前 Python 5-6fps → 帧间隔 170-200ms → 正常操作 delta 可达 4-8cm/帧
- 若未来优化到 15fps → 帧间隔 67ms → 同样操作 delta 约 2-3cm/帧
- 固定阈值 3cm 在当前 5fps 下几乎每帧都触发惩罚，必须自适应

**当前 5-6fps 下的实际效果**：
- dt ≈ 0.18s, dt_scale ≈ 5.4
- soft_t ≈ 16cm（正常操作不会触发）
- soft_r ≈ 54°（正常旋转不会触发）
- 只有真正的跳变（如 track 丢失后重定位）才会惩罚

**实现注意**：`PoseObservation` 当前没有 `frame_dt` 字段，需要在 `pose_observation.py` 中新增，并在 `quest_pose_pipeline.py` 填充（用当前帧时间戳减去上一帧时间戳）。

---

#### 5. mask_score — 平滑化过渡（Gate 层）

**职责**：cutie mask 面积是否合理

**问题**：当前是硬阶梯（<0.002→0.5，>0.65→0.55，其余→1.0），中间无区分

**改动 — 分段线性平滑**：

```python
def _mask_factor(observation, flags):
    r = observation.mask_area_ratio

    # 太小区域：0 → 0.3, 0.002 → 0.5, 0.01 → 1.0
    if r < 0.002:
        flags.append("mask_too_small")
        return 0.3 + 0.2 * (r / 0.002)  # 0.3 ~ 0.5
    elif r < 0.01:
        return 0.5 + 0.5 * ((r - 0.002) / (0.01 - 0.002))  # 0.5 ~ 1.0

    # 正常区域
    elif r <= 0.4:
        return 1.0

    # 太大区域：0.4 → 1.0, 0.65 → 0.55, >0.8 → 0.3
    elif r <= 0.65:
        flags.append("mask_too_large")
        return 1.0 - 0.45 * ((r - 0.4) / (0.65 - 0.4))  # 1.0 ~ 0.55
    else:
        flags.append("mask_too_large")
        return max(0.3, 0.55 - 0.25 * ((r - 0.65) / (0.8 - 0.65)))  # 0.55 ~ 0.3
```

---

#### 6. reject_score — 不变（Gate 层）

- 有 track reject → 按次数线性降分（最低 0.25）
- 无 reject → 1.0
- 逻辑清晰，无需调整

---

#### 7. 连续高分置信积累（Confidence Warmup）— 新增

**职责**：区分"刚开始跟踪第 1 帧"和"已连续稳定跟踪 60 帧"

**问题**：当前系统无法表达"已经持续一段时间高质量跟踪"的额外可信度。单帧高分不应等同于持续高分。

**实现**：

```python
WARMUP_FRAMES = 10        # 需要连续多少高分帧才到满置信
GOOD_SCORE_THRESH = 0.6   # quality 分高于此视为"好"

class ConfidenceAccumulator:
    def __init__(self):
        self.consecutive_good = 0

    def update(self, quality_score: float) -> float:
        """返回 confidence ramp，范围 0.5~1.0。"""
        if quality_score >= GOOD_SCORE_THRESH:
            self.consecutive_good = min(self.consecutive_good + 1, WARMUP_FRAMES)
        else:
            # 不完全归零，允许偶尔一帧波动
            self.consecutive_good = max(0, self.consecutive_good - 2)

        ramp = self.consecutive_good / WARMUP_FRAMES  # 0.0 ~ 1.0
        return 0.5 + 0.5 * ramp  # 映射到 0.5 ~ 1.0

    def reset(self):
        self.consecutive_good = 0
```

**应用位置**：

```python
confidence = accumulator.update(quality)
final_score = clamp01(gate * quality * confidence)
```

**效果**：
- 刚恢复跟踪的前几帧：confidence = 0.5，final 被压制 50%
- 连续 10 帧高分后：confidence = 1.0，不再限制
- 偶尔 1 帧波动：consecutive_good 减 2，不会立刻崩溃

---

### 完整评分流程（伪代码）

```python
def score_observation(observation: PoseObservation) -> PoseQualityBreakdown:
    flags = []

    # === Gate 层 ===
    phase_score = _phase_score(observation, flags)          # 1.0 or 0.7
    mask_score = _mask_factor(observation, flags)           # 0.3 ~ 1.0
    reject_score = _track_reject_factor(observation, flags) # 0.25 ~ 1.0
    gate = phase_score * mask_score * reject_score

    # === Quality 层 ===
    reprojection_score = _reprojection_score(observation, flags)  # 0.0 ~ 1.0 连续
    depth_score = _depth_alignment_score(observation, flags)      # 0.0 ~ 1.0 连续（覆盖不足时 0.5）
    jump_score = _jump_score(observation, flags)                  # 0.0 ~ 1.0 连续

    quality = (
        W_REPROJ * reprojection_score +   # 0.45
        W_DEPTH  * depth_score +           # 0.35
        W_JUMP   * jump_score              # 0.20
    )

    # === Confidence Warmup ===
    confidence = self.confidence_accumulator.update(quality)

    # === 最终分 ===
    final_score = clamp01(gate * quality * confidence)

    return PoseQualityBreakdown(
        final_score=final_score,
        phase_score=phase_score,
        reprojection_score=reprojection_score,
        depth_score=depth_score,
        jump_score=jump_score,
        mask_score=mask_score,
        reject_score=reject_score,
        confidence=confidence,
        flags=tuple(flags),
    )
```

---

### 实施优先级

| 阶段 | 改动内容                                                                    | 预期效果                                      |
| ---- | --------------------------------------------------------------------------- | --------------------------------------------- |
| P0   | 评分公式改为 gate × quality_weighted_sum                                    | 解决乘法过度惩罚，动态范围合理化              |
| P0   | 拆分 RenderConsistencyChecker → ReprojectionChecker + DepthAlignmentChecker | 职责分离，架构清晰                            |
| P0   | depth_score 改为渲染深度对齐 + 自适应阈值                                   | 让 depth 在正常跟踪中产出连续信号             |
| P0   | depth 有效覆盖降级为前置条件（覆盖不足时给中性值 0.5）                      | 避免"无深度信号 = 满分"的盲区                 |
| P0   | reprojection_score 加入 LAB 颜色相似度                                      | IoU + 颜色双信号，对光照鲁棒                  |
| P1   | jump_score 双层阈值 + 帧间隔自适应                                          | 适应不同帧率，避免低帧率误报                  |
| P1   | mask_score 平滑化                                                           | 更细粒度的 mask 质量反馈                      |
| P1   | Confidence Warmup 积累                                                      | 区分刚开始跟踪和稳定跟踪，抑制初始不确定性    |
| P2   | depth_score 无渲染 fallback                                                 | 减少"无信号=满分"的盲区                       |

---

### 改后预期行为

正常稳定跟踪时，各分数的典型范围：

- phase: 1.0（Gate）
- mask: 0.9 ~ 1.0（Gate，平滑过渡）
- reject: 1.0（Gate）
- reprojection: 0.70 ~ 0.95（Quality，IoU + LAB 颜色提供连续信号）
- depth: 0.75 ~ 0.98（Quality，自适应阈值后有区分度，覆盖不足时 0.5）
- jump: 0.95 ~ 1.0（Quality，小范围内仍为 1.0，中等移动开始降分）
- confidence: 0.5 → 1.0（前 10 帧逐步积累）

**典型 final_score 演变**：
- 刚恢复跟踪第 1 帧：gate=1.0, quality≈0.85, confidence=0.55 → final≈**0.47**
- 稳定跟踪第 10 帧后：gate=1.0, quality≈0.85, confidence=1.0 → final≈**0.85**
- 质量略下降：gate=1.0, quality≈0.70, confidence=0.9 → final≈**0.63**
- mask 异常：gate=0.5, quality≈0.85, confidence=1.0 → final≈**0.43**

**对比现状**：现在 final_score 范围 0.88~0.91（几乎无区分度）→ 改后范围 0.47~0.85（动态范围大，区分有意义）
