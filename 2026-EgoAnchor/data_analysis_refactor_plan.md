---
## GPT执行Prompt（完整版）

请将以下内容作为给GPT的初始prompt：

```
你好！我需要你帮我完成EgoAnchor项目的实验一/二离线分析重构工作。

## 背景

我们已经完成了数据采集，现在需要彻底重构数据分析pipeline。旧的分析代码混乱且不满足需求，我们制定了一个四阶段（raw → XLSX → CSV → figures/TeX → 主稿物化）的新架构。

## 你需要阅读的文档（按顺序）

**重要：在开始任何代码修改前，你必须完整阅读以下文档**

1. **仓库根目录 `AGENTS.md`**
   - 先阅读顶部 `USER-MAINTAINED-REQUIREMENTS` 区块（用户手动维护要求）
   - 这是最高优先级的约束，任何情况下都不能违反
   - 关注：Python包导入规范、中文注释要求、架构边界检查

2. **`2026-EgoAnchor/experiment_1_2_analysis_rebuild_plan.md`**
   - 这是用户确认的原始四阶段路线文档
   - 理解为什么要重构、四阶段的理念

3. **`2026-EgoAnchor/experiment_1_2_analysis_rebuild_plan.md`**（本文档）
   - 这是详细实施计划，包含13个Task的完整步骤
   - 这是你的执行蓝图，严格按照它进行

## 核心约束（必须遵守）

### 1. 执行纪律
- **一次只完成一个Task**，从Task 0开始，不要跨Task提前实现
- 每个Task开始前：
  - 运行 `git status` 检查当前状态
  - 用 `rg` 检查影响范围和引用关系
  - 理解这个Task在整体架构中的位置
- 每个Task完成后：
  - 运行验收标准中的所有命令
  - 独立提交：`git commit -m "Task N: <简要描述>"`
  - 推送：`git push`
  - 向我报告：完成了什么、验证结果、下一个Task是什么

### 2. 单向数据契约（严格执行）
这是架构的核心约束，任何违反都会导致整个pipeline失效：

- **Stage 1 (preprocess)**: 只读取原始task目录的JSONL文件
- **Stage 2 (analyze)**: 只读取Stage 1生成的XLSX，**禁止**访问原始JSONL
- **Stage 3 (publish)**: 只读取Stage 2生成的CSV，**禁止**回读XLSX或JSONL
- **Stage 4 (materialize)**: 只读取Stage 3生成的TeX文件，**禁止**直接读CSV

**如果你发现某个阶段需要回读更早的数据源，这说明前面的阶段数据不完整，应该回到前面的阶段补充数据，而不是打破单向契约。**

### 3. 不要做的事情
- ❌ 不要恢复旧的分析接口、旧命令名（如 `analyze-exp1`）或兼容层
- ❌ 不要覆盖我现有的未提交改动（先检查 `git status`）
- ❌ 不要修改 `AGENTS.md` 顶部的 `USER-MAINTAINED-REQUIREMENTS` 区块
- ❌ 不要修改运行时依赖的文件（`schema_v2/{rows,writers,paths}.py`）
- ❌ 不要在Stage 2/3/4中读取比契约允许更早的数据源
- ❌ 不要跨场景混池计算总分（EgoAnchor的优势是场景条件化的）
- ❌ 不要把frame当作统计单位（统计单位是event/segment）

### 4. 必须做的事情
- ✅ 所有类、方法、参数都写中文文档字符串
- ✅ 配置文件（TOML）的每个参数同行写中文注释
- ✅ 先补测试，再改实现
- ✅ 使用包级入口导入，不深层导入（`from egoanchor.eval import X` 而不是 `from egoanchor.eval.xxx.yyy import X`）
- ✅ QC失败必须返回退出码2，不生成任何后续产物
- ✅ 每个阶段输出时记录输入数据的SHA-256，保证lineage可追踪

## 原始数据位置

五个正式task目录（只读）：
```
EgoAnchor_Python/data/eval/task_1_20260717_203329_controller_right/
EgoAnchor_Python/data/eval/task_2_20260717_203749_controller_right/
EgoAnchor_Python/data/eval/task_3_20260717_204156_controller_right/
EgoAnchor_Python/data/eval/task_4_20260717_204943_controller_right/
EgoAnchor_Python/data/eval/task_5_20260717_205539_controller_right/
```

每个目录包含：
- `manifest.json` + `python_session.json`
- `python_candidates.jsonl` (候选位姿)
- `python_events.jsonl` + `unity_events.jsonl` + `events.jsonl`
- `unity_reference.jsonl` (平台参考轨迹)
- `unity_admission.jsonl` (8个variant的接纳决策)
- `unity_render.jsonl` (8个variant的渲染帧)

## 关键技术细节

### Python环境
- 使用 `pixi` 管理环境
- 编译检查：`pixi run python -m compileall src`
- 单元测试：`pixi run python -m unittest discover -s src -p "test_*.py" -t src`
- CLI入口：`pixi run python -m egoanchor.eval.cli <command>`

### 实验配置
**实验一**比较4个系统配置：
1. Arrival-Hold（到达时刻基线）
2. Capture-Hold（采集时刻基线）
3. One-Euro Anchor（标准滤波基线）
4. EgoAnchor（完整系统）

**实验二**比较4个单组件消融：
1. EgoAnchor w/o capture-time alignment（适用场景：static_head_motion）
2. EgoAnchor w/o VCD（适用场景：occlusion_recovery）
3. EgoAnchor w/o temporal synthesis（适用场景：start_stop_6dof）
4. EgoAnchor w/o StaticLock（适用场景：static_head_motion）

### 统计原则
- **统计单位**：event/segment，**不是**frame
- **汇总方式**：先在每个event内计算P95，再对event-level P95做median[IQR]
- **不跨场景混池**：每个场景单独报告，不计算全局总分
- **配对比较**：在相同trial/event内配对，不做frame-level显著性检验

## 开始执行

请先确认你已经阅读了上述三个文档，然后从 **Task 0** 开始执行。

每完成一个Task后，向我报告：
1. 完成了什么（简要说明）
2. 验证结果（运行了哪些命令，结果如何）
3. Git提交hash
4. 下一个Task是什么，你打算如何做

如果在执行过程中遇到任何与计划冲突、不合理的地方，或者发现数据/代码的实际情况与计划假设不符，立即停下来向我报告，不要自行调整计划。

现在请开始 Task 0。
```
---
## 补充说明

### 关于沟通风格

向GPT强调以下沟通方式：

1. **每个Task完成后必须报告**：不要连续执行多个Task
2. **发现问题立即报告**：不要自行调整计划
3. **验证结果要具体**：贴出关键命令的输出，不要只说"通过了"
4. **Git提交要规范**：提交信息格式 `Task N: <简要描述>`

### 可能需要的中途干预

在执行过程中，你可能需要在以下时刻介入：

- **Task 5之后**：检查生成的5个XLSX是否正确（可视化检查）
- **Task 9之后**：检查CSV输出结构是否完整
- **Task 10之后**：检查图表是否符合论文要求
- **Task 12之后**：检查主稿是否可以编译

### 如果GPT偏离了计划

使用以下prompt拉回：

```
请停止当前操作。你违反了单向数据契约/跨Task实现/其他约束。

请重新阅读 experiment_1_2_analysis_rebuild_plan.md 中关于 <具体约束> 的部分，
然后撤销刚才的改动，按照计划重新实现。
```

### 测试GPT是否理解了约束

在开始执行前，可以问GPT：

```
在开始之前，请回答以下问题来确认你理解了约束：

1. Stage 2 可以读取哪些文件？不能读取哪些文件？
2. 统计单位是什么？为什么不能用frame？
3. 如果某个Task的验证失败了，应该怎么办？
4. 实验一比较哪些配置？实验二比较哪些消融？
5. 提交信息的格式是什么？
```
