# Anchor Upsample Baseline Notes

输入观测只来自 primary variant 的 `aligned_raw_pos/aligned_raw_rot`，并按 `source_frame_id` 去重。`stable_pos/stable_rot`、`arrival_time_raw_*`、GT 和 head pose 都不作为算法输入。

模拟时钟优先使用 Unity 日志中逐帧记录的 `render_mono_ms`，因此 render 间隔保留真实的非均匀时间轴；只有合成数据或缺少录制时间时才使用 `--render-hz` 作为回退。每个 render 时刻只使用已经到达的低频观测，调用各 baseline 的 `Predict(renderTime)` 输出最新 pose。

## raw_none

什么都不处理：最近一次观测 pose 的 zero-order hold。

## kalman_prediction

卡尔曼滤波 + 预测：常速度 Kalman 状态在 render tick 前推。

## dead_reckoning_spline

航位推测 + 样条修正：render tick 按观测速度外推，新观测到达后用 smoothstep 三次曲线吸收预测误差。

## residual_blend_prediction

历史残差淡化预测：render 帧持续按运动状态外推；低频观测到达时查历史预测误差，只把残差加入待偿还队列，后续每帧约偿还 10%，避免一次性跳变。

## oneeuro_prediction

One Euro Filter + 预测：自适应低通后用滤波速度短窗口前推。

