# EgoAnchor Python 可靠性评分发现记录

## 已知事实

- 用户计划明确本轮先做 Python 端 A/B/E，不做 Unity C/D。
- `PoseResult` 协议已有 `reliability_score` 与 `reliability_flags`，本轮不改 proto。
- 渲染一致性只应通过 FoundationPose 适配器 facade 暴露，不从 reliability 模块触碰第三方 estimator 内部成员。
- 默认行为必须保持现状：一致性检测默认关闭，开启后先 `score_only`，确认误报率后才允许 `re_register`。

## 待核查接入点

- `pose_observation.py` 是否已有可扩展字段。
- `quest_pose_pipeline.py` 的 TRACK 成功、jump reject、diagnostics 与 `_make_observation` 位置。
- FoundationPose 适配器文件名与公开 API。
- `runtime_log_writer.py` 与 `tracking_runtime.py` 当前如何写 PoseResult JSONL。
- 现有 tests 目录和 unittest 发现规则。

## 代码阅读发现

- `PoseObservation` 当前只有 depth/mask/timing/reliability/failure 字段，尚无 `track_consistency`、IoU、depth inlier、上一帧 pose delta。
- `FrameDiagnostics` 当前没有一致性字段；`PipelineStepTiming` 不包含 `consistency_ms`，计划要求不改 proto timing，但 diagnostics 可扩展。
- `PipelineTrackingState` 只有 `track_reject_count` 和 `tracked_mask_lost_count`，需要新增 `low_consistency_count` 与 `frames_since_register`，并在 `bump_generation()` 清零。
- `pose_quality.py` 当前在 has_pose 且 depth/mask 正常时基本维持 1.0，符合计划中“评分坍缩”的问题描述。
- `quest_pose_pipeline.py` 的 `_estimate_pose()` 是 TRACK/jump/re-register 的核心入口；`_finish_frame()` 统一写 `PoseObservation`，适合在 TRACK 成功后、收尾前填 diagnostics。
- FoundationPose 适配器当前只公开 `register()`、`track()`、`visualize_pose()`、`adjust_pose_to_image_point()`、`reset()`，需要新增 `render_depth_mask(...)` facade。
- `tracking_runtime.py` 的 `_publish_observation()` 当前 `self.log_writer.pose_result(msg, state=self.state)` 只传 proto，没有 observation/diagnostics 旁路。
- `runtime_log_writer.py` 的 `pose_result()` 当前只读取 proto msg，适合新增可选 `diagnostics` 参数并保持旧调用兼容。
- `defaults.toml` 目前没有 `[reliability.consistency]`，新增配置段必须默认关闭并逐行中文注释。
- 现有测试使用 `egoanchor/tests/test_*.py` + `unittest`，可新增纯数学单测避免 GPU 依赖。
- Windows pixi 环境中，OpenCV 先加载后再触发 NumPy linalg 可能出现 `libomp.dll`/`libiomp5md.dll` 冲突；pipeline hot path 应避免为简单向量长度/trace 使用 `np.linalg` 或矩阵乘法。
