## 评分系统优化完整计划

### 现状问题

当前 6 个子分中，只有 `consistency_score` 在正常跟踪中提供连续质量信号，其余均为"故障检测门"——正常情况下恒为 1.0，无法区分"好"和"非常好"。

最终分公式不变：

```
final = phase × consistency × depth × jump × mask × reject
```

---

### 各子分改动计划

#### 1. phase_score — 不变

* TRACK / REGISTER / RE_REGISTER → 1.0
* 其他 phase → 0.7
* 逻辑清晰，无需调整

---

#### 2. consistency_score — 加强颜色对比

 **职责** ：物体重投影回相机平面的综合分（mask 重叠 + 颜色相似度）

 **当前实现** ：`iou_weight=0.6, color_weight=0.4`，在 intersection 区域计算颜色差

 **改动** ：

* 颜色对比改为只用 mask 重叠区域的中心 70%（排除边缘锯齿和遮挡不确定区域）
* 确认 `render_color_depth_mask()` 输出的是带纹理的渲染色（非纯色/法线色）
* 权重微调为 `iou_weight=0.5, color_weight=0.5`，提升颜色区分度

---

#### 3. depth_score — 收紧阈值 + 无渲染 fallback

 **职责** ：物体表面渲染深度与 FFS 估计深度在 mask 区域内的对齐分

 **问题** ：当前 `depth_inlier_thresh_m=0.02`（2cm）对小物体太宽松，inlier 永远 ~0.999

 **改动 A — 自适应阈值** ：

```python
# 根据物体到相机距离自适应
inlier_thresh = max(0.005, pose_distance * 0.02)
# 例如距离 0.24m → 阈值 0.005m（5mm）
# 距离 1.0m → 阈值 0.02m（2cm）
```

 **改动 B — 无渲染时 fallback** ：

```python
# 渲染失败时，用 pose 预测距离 vs depth median 做粗略校验
if surface_depth_score < 0 and depth_median_in_mask > 0:
    expected_z = pose_tz  # pose matrix 的 z 分量
    ratio = min(expected_z, depth_median_in_mask) / max(expected_z, depth_median_in_mask)
    return _clamp01(ratio)
```

---

#### 4. jump_score — 双层阈值，增加区分度

 **职责** ：相邻帧 pose 跳变惩罚

 **问题** ：当前硬阈值 0.6m / 100° 太宽，正常帧 ratio ≈ 0.002，完全无区分度

 **改动 — 引入软阈值** ：

```python
SOFT_TRANSLATION_M = 0.03      # 超过 3cm 开始降分
HARD_TRANSLATION_M = 0.6       # 完全不可接受

SOFT_ROTATION_DEG = 10.0       # 超过 10° 开始降分
HARD_ROTATION_DEG = 100.0      # 完全不可接受

def _jump_score(observation, flags):
    t_delta = abs(observation.last_translation_delta_m)
    r_delta = abs(observation.last_rotation_delta_deg)

    if t_delta <= SOFT_TRANSLATION_M:
        t_score = 1.0
    else:
        t_score = 1.0 - (t_delta - SOFT_TRANSLATION_M) / (HARD_TRANSLATION_M - SOFT_TRANSLATION_M)

    if r_delta <= SOFT_ROTATION_DEG:
        r_score = 1.0
    else:
        r_score = 1.0 - (r_delta - SOFT_ROTATION_DEG) / (HARD_ROTATION_DEG - SOFT_ROTATION_DEG)

    score = _clamp01(min(t_score, r_score))
    if score < 0.5:
        flags.append("near_jump_limit")
    return score
```

---

#### 5. mask_score — 平滑化过渡

 **职责** ：cutie mask 面积是否合理

 **问题** ：当前是硬阶梯（<0.002→0.5，>0.65→0.55，其余→1.0），中间无区分

 **改动 — 分段线性平滑** ：

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

#### 6. reject_score — 不变

* 有 track reject → 按次数线性降分（最低 0.25）
* 无 reject → 1.0
* 逻辑清晰，无需调整

---

### 实施优先级

| 阶段 | 改动内容                           | 预期效果                                      |
| ---- | ---------------------------------- | --------------------------------------------- |
| P0   | depth_score 自适应阈值             | 让 depth 在正常跟踪中产出 0.8~0.99 的连续信号 |
| P0   | jump_score 双层阈值                | 让 3cm~60cm 的中等跳变有明确惩罚              |
| P1   | consistency_score 颜色对比区域裁剪 | 减少边缘噪声对颜色分的影响                    |
| P1   | mask_score 平滑化                  | 更细粒度的 mask 质量反馈                      |
| P2   | depth_score 无渲染 fallback        | 减少"无信号=满分"的盲区                       |

---

### 改后预期行为

正常稳定跟踪时，各分数的典型范围：

* phase: 1.0
* consistency: 0.75 ~ 0.95（IoU + 颜色提供连续信号）
* depth: 0.85 ~ 0.98（自适应阈值后有区分度）
* jump: 0.95 ~ 1.0（小范围内仍为 1.0，中等移动开始降分）
* mask: 0.9 ~ 1.0（平滑过渡）
* reject: 1.0

 **final_score 典型范围** ：0.6 ~ 0.93（比现在的 0.88~0.91 有更大动态范围）
