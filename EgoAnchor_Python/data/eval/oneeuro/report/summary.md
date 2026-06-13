# EgoAnchor Eval Summary

## GT / Anchor Sanity

- session_id: `20260614_015559_controller_right`
- object_id: `controller_right`
- gt_source: `transform`
- gt_transform: `OVRControllerPrefab`

## anchor_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 5872 | 0.294536 | 0.018441 | 0.376878 | 20.7998 | 6.26246 | 48.2985 |
| unlabeled | raw | 5872 | 0.295434 | 0.0192137 | 0.38378 | 22.2408 | 6.11302 | 50.2517 |

## pose_offset_summary

| condition | label | n | position_offset_mean_x_m | position_offset_mean_y_m | position_offset_mean_z_m | position_offset_median_x_m | position_offset_median_y_m | position_offset_median_z_m | position_offset_std_x_m | position_offset_std_y_m | position_offset_std_z_m | position_offset_median_norm_m | position_residual_after_median_p50_m | position_residual_after_median_p95_m | position_residual_after_median_rmse_m | rotation_offset_mean_euler_x_deg | rotation_offset_mean_euler_y_deg | rotation_offset_mean_euler_z_deg | rotation_offset_median_euler_x_deg | rotation_offset_median_euler_y_deg | rotation_offset_median_euler_z_deg | rotation_offset_std_euler_x_deg | rotation_offset_std_euler_y_deg | rotation_offset_std_euler_z_deg | rotation_offset_median_deg | rotation_offset_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 5872 | 0.00617272 | -0.0107233 | 0.0710044 | 0.000891596 | -0.0023512 | 0.0102449 | 0.0598673 | 0.0474678 | 0.275171 | 0.010549 | 0.0152438 | 0.367563 | 0.292141 | 359.899 | 356.814 | 1.37722 | 358.556 | 357.209 | 359.76 | 11.1139 | 9.17208 | 16.5494 | 6.26246 | 48.2985 |
| unlabeled | raw | 5872 | 0.00638849 | -0.0103394 | 0.0735111 | 0.0011771 | -0.00256833 | 0.0110049 | 0.0601114 | 0.0476204 | 0.275406 | 0.0113618 | 0.0162541 | 0.373666 | 0.292787 | 0.432157 | 356.025 | 0.319491 | 358.886 | 357.218 | 359.745 | 11.7842 | 9.96271 | 17.8582 | 6.11302 | 50.2517 |

## latency_summary

| condition | label | n | capture_to_apply_p50_ms | capture_to_apply_p90_ms | capture_to_apply_p95_ms | perception_total_p50_ms | yolo_p50_ms | depth_p50_ms | cutie_p50_ms | pose_p50_ms | publish_to_apply_est_p50_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 400 | 195.18 | 223.438 | 226.535 | 158.526 | 0 | 39.5624 | 34.3611 | 44.6929 | 39.4673 |
| unlabeled | raw | 400 | 195.18 | 223.438 | 226.535 | 158.526 | 0 | 39.5624 | 34.3611 | 44.6929 | 39.4673 |

## jitter_summary

| condition | label | n | position_jitter_rms_m | position_jitter_std_m | rotation_jitter_rms_deg | insufficient_data |
| --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 3442 | 0.0212721 | 0.0192805 | 37.1312 | False |
| unlabeled | raw | 3442 | 0.0222683 | 0.0196809 | 39.2522 | False |

## slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 5688 | 3139.08 | 235545 | False |
| unlabeled | raw | 5688 | 3138.31 | 235500 | False |

## rq1_raw_mapping_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | arrival_time_raw | 5652 | 0.28983 | 0.0203756 | 0.142526 | 21.2396 | 5.79238 | 49.7638 |
| unlabeled | frame_aligned_raw | 5872 | 0.294518 | 0.0191934 | 0.38378 | 22.2053 | 6.11302 | 50.2517 |

## rq1_raw_mapping_slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | arrival_time_raw | 5468 | 3200.63 | 235495 | False |
| unlabeled | frame_aligned_raw | 5688 | 3138.3 | 235500 | False |

## lag_summary

| condition | label | n | lag_ms | correlation | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 5872 | -66.6667 | 0.028112 | False |
| unlabeled | raw | 5872 | -433.333 | 0.0150289 | False |

## jump_suppression_summary

| condition | label | n | spike_count | spike_threshold_m | max_translation_error_m | policy_reject_count | top_policy_reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 5872 | 1520 | 0.05 | 1.60568 | 240 | score_hold:228;stale_measurement:12 |
| unlabeled | raw | 5872 | 1636 | 0.05 | 1.60583 | 0 |  |

## recovery_summary

_insufficient_data_
