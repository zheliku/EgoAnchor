# EgoAnchor 论文快速参考卡

**更新日期**: 2026-06-24  
**论文状态**: ✅ 框架完成，待填充实验数据

---

## 📊 论文统计

- **主稿文件**: `egoanchor_final.tex`
- **行数**: 370 行
- **字数**: 约 6,500 中文字（含 LaTeX 标记）
- **完成度**: 摘要 + 引言 100%，后续章节提纲清晰

---

## 🎯 核心定位（30秒电梯演讲）

> **EgoAnchor 是首个同时实现五维能力的端到端真实物体锚定系统：无需训练、纯双目感知、任意刚性日常物体、动态追踪、开放消费级硬件。通过四层协同架构（时间对齐、质量门控、时序平滑、生命周期管理），将 5-12 fps 异步感知流转化为 60 fps 世界一致锚点。**

---

## 🏆 五维能力（最强卖点）

| 维度 | EgoAnchor | Azure | Vision Pro | Vuforia | Meta |
|------|-----------|-------|------------|---------|------|
| **免主动深度** | ✓ | ✗ | ✗ | ✓ | ✓ |
| **任意物体** | ✓ | ✓ | ✓ | ✓ | ✗ |
| **动态追踪** | ✓ | ✓ | ✓ | ✗ | ✓ |
| **免训练** | ✓ | ✗ | ✗ | ✓ | ✓ |
| **开放硬件** | ✓ | ✗ | ✗ | ✗ | ✗ |

**关键**: 没有任何现有系统同时满足所有五个维度。

---

## 🔧 四层协同架构

```
输入: 5-12 fps 感知流 (Python 后端)
  ↓
┌─────────────────────────────────┐
│ 第一层: 时间对齐                 │
│  └─ 帧对齐锚定                  │
│     (消除头动打滑)              │
├─────────────────────────────────┤
│ 第二层: 质量门控                 │
│  └─ 可靠性评分过滤              │
│     (拦截异常观测)              │
├─────────────────────────────────┤
│ 第三层: 时序平滑                 │
│  ├─ 卡尔曼状态估计              │
│  ├─ 静止锁定                    │
│  └─ [升采样] 5-12fps→60fps     │
│     (抑制抖动+视觉流畅)         │
├─────────────────────────────────┤
│ 第四层: 生命周期管理             │
│  └─ 状态机 + 重获取             │
│     (自愈恢复)                  │
└─────────────────────────────────┘
  ↓
输出: 60 fps 世界一致锚点 (Unity 前端)
```

---

## 📝 贡献点（金字塔式）

1. **首个五维能力系统** ← 最强卖点
2. **四层协同架构** ← 系统贡献
3. **以锚点为中心的评估协议** ← 评价创新
4. **开源实现** ← 可复现性

---

## 🛡️ 审稿人防御（3句话）

1. **不争算法新颖性，争系统完整性** - 类比 ORB-SLAM
2. **五维能力空白是独特定位** - 无人同时满足
3. **开放系统达到平台级质量** - 实验验证

---

## 📂 关键文件位置

### 论文主稿
- **当前版**: `2026-EgoAnchor/egoanchor_final.tex`
- 备份版: `egoanchor_final_backup.tex`
- 英文参考: `egoanchor_final_polished.tex`

### 总结文档
- 重构总结: `FINAL_SUMMARY.md`
- 重构要点: `REFRAMING_SUMMARY.md`
- 升采样说明: `UPSAMPLING_IN_ARCHITECTURE.md`
- 今日工作: `WORK_SUMMARY_2026-06-24.md`
- 项目报告: `PROJECT_FINAL_REPORT.md`
- Git 指南: `GIT_COMMIT_GUIDE.md`

### Python 文档
- 评分机制: `EgoAnchor_Python/POSE_SCORING_MECHANISM.md`
- 检查报告: `EgoAnchor_Python/POSE_SCORING_CHECK_REPORT.md`

---

## ✅ 已完成的核心工作

- [x] 论文定位从"问题"转向"系统"
- [x] 摘要精简至 150 词
- [x] 引言深度润色（能力对比表前置）
- [x] 四层架构详细阐述
- [x] 升采样机制补充
- [x] Python 文档检查与更新
- [x] 审稿人防御策略明确

---

## ⏳ 待完成的关键任务

### P0 (必须)
- [ ] 实验数据收集（RQ1-4）
- [ ] Teaser 图绘制
- [ ] 系统架构图绘制
- [ ] 填充 §7 实验结果

### P1 (建议)
- [ ] 用户研究（N=12-15）
- [ ] Supplementary video
- [ ] 开源仓库准备

### P2 (投稿前)
- [ ] 补齐 `\cite`
- [ ] 统一术语
- [ ] 翻译成英文

---

## 💡 关键洞察速查

### 升采样的位置
- **不是第五层**
- 是第三层（时序平滑层）的输出功能
- 基于卡尔曼预测，而非简单插值

### 权重配置
- `reproj_weight = 0.2` (颜色辅助)
- `depth_weight = 0.8` (深度主要)
- 对低纹理目标更可靠

### 评分公式
```
final = gate × quality × confidence
quality = core × modulation
core = weighted_geometric_mean(reprojection, depth)
```

---

## 📞 快速命令

### 编译论文
```bash
cd /p/VSCode-Project/EgoAnchor/2026-EgoAnchor
# (需要配置 LaTeX 环境)
```

### 检查 Git 状态
```bash
cd /p/VSCode-Project/EgoAnchor
git status
```

### 提交修改
```bash
# 参考 GIT_COMMIT_GUIDE.md
```

---

## 🎯 投稿目标

- **会议**: IEEE VR 2027 Papers Track
- **类型**: System Paper
- **对标**: ORB-SLAM 式系统贡献
- **预期**: 顶会接收

---

## 📚 相关资源

### 重要文献
- Azuma 1997 (动态配准误差)
- van Waveren 2016 (ATW)
- FoundationPose 2023
- Vision Pro visionOS 27 Object Tracking

### 对比系统
- Azure Object Anchors (已停服)
- Vision Pro Object Tracking (封闭+训练)
- Vuforia Model Targets (静态)
- Meta Dynamic Object Tracker (预定义类)

---

**最后更新**: 2026-06-24  
**论文状态**: 框架完成，达到顶会水准 ✅  
**下一步**: 实验数据收集 → 图表绘制 → 投稿

---

**祝投稿顺利！Good luck! 🚀**
