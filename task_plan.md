# EgoAnchor Python 可靠性评分执行计划

## 目标

严格执行 `p-vscode-project-egoanchor-egoanchor-py-calm-newell.md` 中 Python 端本轮计划：实现渲染-重投影一致性坏 pose 检测器、重写可区分的可靠性评分、补轻量诊断，并提供可复现验证文档。本轮只覆盖计划中的 A、B、E 与 Python 验证；C/D Unity 统一滤波器保留为后续阶段。

## 阶段状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| 1 | 阅读计划和现有 Python 架构，定位接入点 | complete |
| 2 | TDD：为渲染一致性纯数学评分写失败测试 | complete |
| 3 | 实现 `RenderConsistencyChecker` 与 FoundationPose render facade | complete |
| 4 | TDD：为可靠性评分非恒定、单调性写失败测试 | complete |
| 5 | 重写 `pose_quality.py` 并把一致性/跳变字段接入 observation | complete |
| 6 | 接入 Quest pose pipeline、配置、诊断与 runtime JSONL 旁路 | complete |
| 7 | 实现轻量诊断脚本/函数 | complete |
| 8 | 运行 Python 编译与单测验证 | complete |
| 9 | 编写详细使用与验证文档 | complete |

## 硬性约束

- 不改共享 proto；只复用 `reliability_score` 和 `reliability_flags`。
- 默认配置保持关闭渲染一致性，`mode` 默认 `score_only`。
- `reliability` 层只调用公开 `render_depth_mask(...)` facade，不直接访问 FoundationPose 第三方内部结构。
- 无效一致性信号只记 `no_consistency_signal`，绝不触发重注册。
- TDD：新增生产代码前先写能失败的测试并运行确认。
- 所有新增 `.toml` 参数同行中文注释。

## 验证命令

在 `EgoAnchor_Python` 目录运行：

```powershell
pixi run python -m compileall src eval
pixi run python -m unittest discover -s src -p "test_*.py"
pixi run python -m unittest discover -s eval -p "test_*.py"
```

## 遇到的错误

| 错误 | 尝试次数 | 解决方案 |
|---|---:|---|
| 直接运行 `python -m unittest egoanchor.tests.test_render_consistency` 找不到 `egoanchor` 包 | 1 | 改用项目既有入口 `python -m unittest discover -s src -p "test_render_consistency.py"` |
| pipeline 测试触发 OpenMP runtime 冲突 | 1 | 定位到 `_track_deltas()` 使用 `np.linalg.norm`/矩阵乘法导致 NumPy linalg 懒加载冲突，改回 `math.sqrt` 与逐元素 trace |
| 文档使用了不存在的 `--object controller` 和额外 `configs/*.toml` | 1 | 改为 `--object controller_right`，删除额外配置文件，统一使用 `src/egoanchor/config/defaults.toml` 的 `[reliability.consistency]` |
| 深度质量子分只影响最终分数但没有直接可视化字段 | 1 | 新增 `depth_quality_score`/HUD `depthScore`，同步 runtime JSONL、eval schema 和测试 |
