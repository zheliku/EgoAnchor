# EgoAnchor Eval Summary

## GT / Anchor Sanity

- session_id: `20260614_015450_controller_right`
- object_id: `controller_right`
- gt_source: `transform`
- gt_transform: `OVRControllerPrefab`

## anchor_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 1270 | 0.0423976 | 0.0195642 | 0.089186 | 38.882 | 9.65167 | 94.8121 |
| unlabeled | raw | 1270 | 0.0697926 | 0.0232528 | 0.161931 | 43.756 | 8.46207 | 101.774 |

## pose_offset_summary

| condition | label | n | position_offset_mean_x_m | position_offset_mean_y_m | position_offset_mean_z_m | position_offset_median_x_m | position_offset_median_y_m | position_offset_median_z_m | position_offset_std_x_m | position_offset_std_y_m | position_offset_std_z_m | position_offset_median_norm_m | position_residual_after_median_p50_m | position_residual_after_median_p95_m | position_residual_after_median_rmse_m | rotation_offset_mean_euler_x_deg | rotation_offset_mean_euler_y_deg | rotation_offset_mean_euler_z_deg | rotation_offset_median_euler_x_deg | rotation_offset_median_euler_y_deg | rotation_offset_median_euler_z_deg | rotation_offset_std_euler_x_deg | rotation_offset_std_euler_y_deg | rotation_offset_std_euler_z_deg | rotation_offset_median_deg | rotation_offset_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 1270 | 0.00252882 | 0.00233235 | 0.00255505 | 0.00133136 | -0.00159879 | 0.00725579 | 0.0307491 | 0.021767 | 0.0189705 | 0.00754819 | 0.017715 | 0.0905677 | 0.0426401 | 354.464 | 8.29926 | 358.96 | 358.714 | 359.574 | 359.247 | 25.1329 | 22.275 | 17.6285 | 9.65167 | 94.8121 |
| unlabeled | raw | 1270 | 0.00852548 | -0.00909017 | 0.0288009 | 0.00364153 | -0.00456506 | 0.0103579 | 0.0310706 | 0.0270726 | 0.0467749 | 0.0118906 | 0.0226591 | 0.15039 | 0.0653504 | 5.97171 | 1.36458 | 8.66792 | 359.834 | 358.88 | 0.316581 | 22.4607 | 22.8286 | 28.6688 | 8.46207 | 101.774 |

## latency_summary

| condition | label | n | capture_to_apply_p50_ms | capture_to_apply_p90_ms | capture_to_apply_p95_ms | perception_total_p50_ms | yolo_p50_ms | depth_p50_ms | cutie_p50_ms | pose_p50_ms | publish_to_apply_est_p50_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 95 | 194.112 | 225.291 | 237.509 | 152.926 | 0 | 39.1601 | 34.8362 | 44.4854 | 38.2304 |
| unlabeled | raw | 95 | 194.112 | 225.291 | 237.509 | 152.926 | 0 | 39.1601 | 34.8362 | 44.4854 | 38.2304 |

## jitter_summary

| condition | label | n | position_jitter_rms_m | position_jitter_std_m | rotation_jitter_rms_deg | insufficient_data |
| --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 531 | 0.019843 | 0.0164581 | 59.8914 | False |
| unlabeled | raw | 531 | 0.0191312 | 0.0151997 | 57.7357 | False |

## slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 1270 | 26.246 | 115.241 | False |
| unlabeled | raw | 1270 | 25.9518 | 107.884 | False |

## rq1_raw_mapping_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | arrival_time_raw | 1270 | 0.0687164 | 0.0265937 | 0.162315 | 43.7571 | 7.96488 | 101.806 |
| unlabeled | frame_aligned_raw | 1270 | 0.0697926 | 0.0232528 | 0.161931 | 43.756 | 8.46207 | 101.774 |

## rq1_raw_mapping_slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | arrival_time_raw | 1270 | 23.7585 | 104.326 | False |
| unlabeled | frame_aligned_raw | 1270 | 25.9518 | 107.884 | False |

## lag_summary

| condition | label | n | lag_ms | correlation | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 1270 | 500 | 0.466232 | False |
| unlabeled | raw | 1270 | 400 | 0.451868 | False |

## jump_suppression_summary

| condition | label | n | spike_count | spike_threshold_m | max_translation_error_m | policy_reject_count | top_policy_reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 1270 | 274 | 0.05 | 0.158275 | 253 | score_hold:253 |
| unlabeled | raw | 1270 | 395 | 0.05 | 0.198444 | 0 |  |

## recovery_summary

_insufficient_data_
