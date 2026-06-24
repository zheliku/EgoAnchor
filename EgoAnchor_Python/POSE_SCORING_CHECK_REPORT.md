# POSE_SCORING_MECHANISM.md 文档检查报告

**检查日期**: 2026-06-24  
**状态**: 已更新，与代码一致

---

## 检查结果总结

### ✅ 文档与代码一致的部分

1. **总体架构** ✅
   - 三层结构：`final = gate * quality * confidence`
   - `quality = core * modulation`
   - 几何核使用加权几何平均

2. **Gate 层** ✅
   - `phase_score`: TRACK/REGISTER/RE_REGISTER = 1.0, 其他 = 0.7
   - `reject_score`: 近期 track reject 按次数降分，最低 0.25

3. **几何核参数** ✅
   - `geo_floor = 0.05` (防止单帧低分变成硬零)
   - 使用 `weighted_geometric_mean` 对 valid 信号

4. **Reprojection 评分逻辑** ✅
   - `track_reprojection < 0` 时返回 `(1.0, False)` 不进入几何核
   - 有效信号低于 0.5 时写 `reprojection_low` flag

5. **Depth 评分逻辑** ✅
   - 覆盖率低于 `MIN_DEPTH_COVERAGE = 0.10` 返回 `(0.5, False)`
   - 使用 `render_quality_depth_alignment`
   - 有渲染深度信号的判定逻辑正确

6. **Mask 调制** ✅
   - `mask_floor = 0.5` (默认值)
   - 优先使用 `render_quality_area_ratio_score`
   - 回退到 `mask_area_ratio` 的逻辑正确

7. **Confidence Warmup** ✅
   - `WARMUP_FRAMES = 10`
   - `GOOD_SCORE_THRESH = 0.6`
   - 初始约 0.5，连续高质量帧逐步上升到 1.0

8. **输出字段** ✅
   - `PoseQualityBreakdown` 所有字段都有文档说明
   - flags 机制正确描述

---

## ⚠️ 已修正的差异

### 配置权重不一致 (已更新)

**原文档** (第 69 行):
```toml
reproj_weight = 0.5
depth_weight = 0.5
```

**实际配置** (`defaults.toml` 第 75-76 行):
```toml
reproj_weight = 0.2  # 颜色作为辅助证据
depth_weight = 0.8   # 深度是主要证据
```

**修正方式**:
- 已更新文档反映实际配置
- 添加注释说明设计意图：对低纹理目标（如手柄）更倾向于相信深度一致性

**设计理由**:
- 手柄、白色立方体等目标纹理少，颜色重投影信号弱
- 深度几何一致性更可靠
- 这个权重分配在实践中表现更好

---

## 📋 文档覆盖的关键点

### 1. 评分目标清晰
文档明确说明评分回答的是："这一帧外部感知返回的 object pose，是否适合作为 Unity real-object anchor 的观测输入？"

### 2. 典型场景分析 (§9)
提供了多种场景的评分示例：
- 双信号高分
- 深度失配拉低分数
- 深度覆盖不足的处理
- 无信号时的中性行为

### 3. Unity 端集成建议 (§11)
明确指出新公式会让"单项几何证据有效低分"的帧明显降分，建议重新复核阈值。

### 4. 验证命令 (§13)
提供了快速验证的单元测试命令。

---

## 🔍 代码实现细节确认

### 关键函数对应关系

| 文档说明 | 代码实现 | 状态 |
|---------|---------|------|
| Gate 层 | `_phase_score()`, `_track_reject_factor()` | ✅ |
| Reprojection | `_reprojection_score()` | ✅ |
| Depth | `_depth_score()`, `_has_render_depth_signal()` | ✅ |
| 几何核 | `_geometry_core()` | ✅ |
| Mask 调制 | `_mask_factor()`, `_bounded_modulator()` | ✅ |
| Confidence | `ConfidenceAccumulator.update()` | ✅ |

### 常量定义确认

| 常量 | 代码值 | 文档说明 | 状态 |
|------|-------|---------|------|
| `MIN_DEPTH_COVERAGE` | 0.10 | 0.10 | ✅ |
| `WARMUP_FRAMES` | 10 | 10 | ✅ |
| `GOOD_SCORE_THRESH` | 0.6 | 0.6 | ✅ |
| `geo_floor` (默认) | 0.05 | 0.05 | ✅ |
| `mask_floor` (默认) | 0.5 | 0.5 | ✅ |

---

## 📝 文档质量评估

### 优点
1. ✅ 结构清晰，分层说明
2. ✅ 提供了典型场景分析
3. ✅ 包含配置透传说明
4. ✅ 有快速验证命令
5. ✅ 解释了设计意图（为什么这样设计）

### 已改进
1. ✅ 配置权重已更新至实际值
2. ✅ 添加了权重选择的设计理由

### 建议（可选）
- 可以添加一个"版本历史"章节记录评分机制的重大变更
- 可以补充一些实际运行的统计数据（如各 flag 出现频率）

---

## 🎯 结论

**文档状态**: ✅ **已是最新版本，与代码完全一致**

**已完成的更新**:
- 修正了 `reproj_weight` 和 `depth_weight` 配置值
- 添加了权重选择的设计理由说明

**文档可用性**: 可直接用于：
- 新开发者理解评分机制
- 调试 pose 质量问题
- 调整配置参数
- Unity 端集成参考

**无需进一步更新**。
