# RQ1 锚定质量评估

本目录存储RQ1分析结果（不存储原始日志）。

---

## 📁 目录结构

```
eval/rq1/
├── controller_summary.csv          # 控制器实验汇总
├── objects_summary.csv             # 真实物体实验汇总  
├── all_summary.csv                 # 完整汇总
├── figures/                        # 图表
│   ├── error_distribution.png
│   ├── jitter_comparison.png
│   └── ...
├── sessions/                       # 每个session的详细报告
│   └── <session_id>/
│       ├── report/
│       └── segments.json
└── report.md                       # 论文级报告
```

---

## 🚀 运行RQ1分析

```bash
cd EgoAnchor_Python

# 分析所有controller sessions
pixi run python -m eval.rq1.run_rq1 \
    --source debug \
    --output eval/rq1 \
    --pattern "*controller_right*"

# 分析所有sessions
pixi run python -m eval.rq1.run_rq1 --source debug --output eval/rq1

# 使用session列表
pixi run python -m eval.rq1.run_rq1 \
    --source debug \
    --output eval/rq1 \
    --session-list rq1_sessions.txt
```

---

## 📋 Session选择

### 方法1：模式匹配

```bash
# 控制器sessions
--pattern "*controller_right*"

# 特定日期
--pattern "20260704_*"

# Gamepad
--pattern "*gamepad*"
```

### 方法2：Session列表

创建 `rq1_sessions.txt`:
```
20260704_143022_controller_right
20260704_150515_controller_right
20260705_092033_gamepad
```

然后：
```bash
pixi run python -m eval.rq1.run_rq1 \
    --session-list rq1_sessions.txt
```

---

## 📊 输出结果

运行完成后，本目录将包含：

1. **汇总表格** (`*.csv`)
   - 按场景类型统计的主要指标
   - 可直接用于论文

2. **详细报告** (`report.md`)
   - 完整结果描述
   - 关键发现
   - 论文撰写建议

3. **图表** (`figures/`)
   - 误差分布
   - 抖动对比
   - 恢复曲线
   - 等

4. **Session详情** (`sessions/<session_id>/`)
   - 每个session的完整指标
   - 场景片段信息

---

## 🔄 重新分析

分析结果可以随时删除重建：

```bash
# 删除旧结果
rm -rf eval/rq1/*

# 重新分析
pixi run python -m eval.rq1.run_rq1 --source debug --output eval/rq1
```

原始日志在 `debug/` 中不变。

---

**注意**：本目录的内容由分析脚本生成，不要手动修改。
