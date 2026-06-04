# EgoAnchor Python 可靠性评分进度

## 会话日志

- 已读取用户计划文件，确认本轮只实现 Python 端 A/B/E：渲染一致性检测、可靠性评分重写、轻量诊断与验证文档。
- 已创建 `task_plan.md`、`findings.md`、`progress.md` 作为本轮持久化执行记录。
- 已阅读 `pose_quality.py`、`pose_observation.py`、`pipeline_types.py` 和 `reliability/__init__.py`，确认 A/B 需要新增字段与重写评分逻辑。
- 已阅读 `quest_pose_pipeline.py`、`foundationpose_estimator.py`、`pipeline_factory.py`、`runtime_log_writer.py`、`tracking_runtime.py`、`message_factories.py`、`defaults.toml` 和相关测试，确认本轮接入点。
- 已新增 `test_render_consistency.py` 并完成 RED：`pixi run python -m unittest discover -s src -p "test_render_consistency.py"` 失败于 `RenderConsistencyChecker` 尚未导出，符合预期。
- 已实现 `RenderConsistencyChecker`、`RenderConsistencyResult` 与 `FoundationPoseObjectEstimator.render_depth_mask()` facade；`test_render_consistency.py` 通过 3 个测试。
- 已新增 `test_pose_quality.py` 并完成 RED/GREEN：先失败于 `PoseObservation` 缺少一致性字段，随后新增字段并重写 `score_observation()`，测试 3 项通过。
- 已为 `PipelineTrackingState` 与 runtime JSONL 旁路补 RED/GREEN 测试；新增 diagnostics 字段和 `pose_result(..., diagnostics=...)` 兼容接口。
- 已接入 `_track_deltas()` 与 TRACK 一致性检测入口；修复一次 OpenMP 冲突后，`test_quest_pose_pipeline_segmenter.py` 6 项通过。
- 已新增 `[reliability.consistency]` 默认配置并接入 `build_quest_pose_pipeline()`；默认关闭、模式为 `score_only`。
- 已新增 `eval.metrics.diagnostics.compute_reliability_diagnostics()`，扩展 eval schema 保留一致性字段，并把四张诊断表接入 `compute_all_metrics()` / `run_eval` CSV 导出。
- 中段回归：`test_render_consistency.py`、`test_pose_quality.py`、`test_pipeline_state.py`、`test_runtime_event_logger.py`、`test_segmenter_config.py`、`test_quest_pose_pipeline_segmenter.py`、`eval/test_diagnostics.py`、`eval/test_run_eval.py` 均通过。
- 已新增 `EgoAnchor_Python/POSE_RELIABILITY_VALIDATION.md`。
- 已同步 `AGENTS.md` 中的 reliability consistency 当前事实、配置、代码地图和排查条目。
- 最终验证通过：`pixi run python -m compileall src eval`；`pixi run python -m unittest discover -s src -p "test_*.py"`（62 tests, 1 skipped）；`pixi run python -m unittest discover -s eval -p "test_*.py"`（16 tests）。
- 收到反馈后复核并修正：删除额外 `EgoAnchor_Python/configs/*.toml`，文档/AGENTS/src README 改为 `controller_right` / `controller_left` 对象名，验证配置入口统一回 `src/egoanchor/config/defaults.toml`。
- 已追加 `depth_quality_score`/HUD `depthScore`，让深度质量子分可在 Quest 联机 OpenCV HUD、runtime JSONL 和离线 schema 中直接查看。
- 修正后复扫 `--object controller\b`、`configs\consistency*`、`--prompt`、独立 `` `controller` `` 文案无残留；`EgoAnchor_Python\configs` 不存在。
