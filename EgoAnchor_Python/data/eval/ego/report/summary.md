# EgoAnchor Eval Summary

## GT / Anchor Sanity

- session_id: `20260614_015013_controller_right`
- object_id: `controller_right`
- gt_source: `transform`
- gt_transform: `OVRControllerPrefab`

## anchor_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 3227 | 0.328768 | 0.017916 | 0.185638 | 32.4303 | 8.50862 | 64.9103 |
| unlabeled | raw | 3227 | 0.328296 | 0.0183407 | 0.177586 | 31.5369 | 9.49643 | 63.1539 |

## pose_offset_summary

| condition | label | n | position_offset_mean_x_m | position_offset_mean_y_m | position_offset_mean_z_m | position_offset_median_x_m | position_offset_median_y_m | position_offset_median_z_m | position_offset_std_x_m | position_offset_std_y_m | position_offset_std_z_m | position_offset_median_norm_m | position_residual_after_median_p50_m | position_residual_after_median_p95_m | position_residual_after_median_rmse_m | rotation_offset_mean_euler_x_deg | rotation_offset_mean_euler_y_deg | rotation_offset_mean_euler_z_deg | rotation_offset_median_euler_x_deg | rotation_offset_median_euler_y_deg | rotation_offset_median_euler_z_deg | rotation_offset_std_euler_x_deg | rotation_offset_std_euler_y_deg | rotation_offset_std_euler_z_deg | rotation_offset_median_deg | rotation_offset_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 3227 | 0.000547071 | 0.00327104 | 0.0773725 | 0.00134542 | 0.000388816 | 0.0108111 | 0.0524708 | 0.0614749 | 0.309125 | 0.0109014 | 0.0156745 | 0.186197 | 0.32639 | 359.324 | 3.69289 | 352.063 | 359.312 | 359.291 | 359.375 | 7.86218 | 15.4627 | 26.8109 | 8.50862 | 64.9103 |
| unlabeled | raw | 3227 | 0.000602397 | 0.00324954 | 0.0773874 | 0.00102675 | 0.000498831 | 0.0109895 | 0.0497494 | 0.0611577 | 0.309133 | 0.0110487 | 0.0160071 | 0.177341 | 0.325876 | 359.325 | 3.40182 | 351.992 | 359.273 | 359.434 | 359.214 | 7.75339 | 14.7944 | 26.1159 | 9.49643 | 63.1539 |

## latency_summary

| condition | label | n | capture_to_apply_p50_ms | capture_to_apply_p90_ms | capture_to_apply_p95_ms | perception_total_p50_ms | yolo_p50_ms | depth_p50_ms | cutie_p50_ms | pose_p50_ms | publish_to_apply_est_p50_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 271 | 194.728 | 235.727 | 257.004 | 153.53 | 0 | 38.9252 | 34.1589 | 43.9122 | 41.7265 |
| unlabeled | raw | 271 | 194.728 | 235.727 | 257.004 | 153.53 | 0 | 38.9252 | 34.1589 | 43.9122 | 41.7265 |

## jitter_summary

| condition | label | n | position_jitter_rms_m | position_jitter_std_m | rotation_jitter_rms_deg | insufficient_data |
| --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 2080 | 0.0100962 | 0.0080487 | 60.5293 | False |
| unlabeled | raw | 2080 | 0.00941483 | 0.00745311 | 59.8032 | False |

## slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 3096 | 42.8231 | 139.468 | False |
| unlabeled | raw | 3096 | 40.6996 | 132.53 | False |

## rq1_raw_mapping_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | arrival_time_raw | 3227 | 0.327199 | 0.0187099 | 0.175923 | 31.5082 | 9.41125 | 63.4821 |
| unlabeled | frame_aligned_raw | 3227 | 0.328296 | 0.0183407 | 0.177586 | 31.5369 | 9.49643 | 63.1539 |

## rq1_raw_mapping_slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | arrival_time_raw | 3096 | 40.56 | 131.111 | False |
| unlabeled | frame_aligned_raw | 3096 | 40.6996 | 132.53 | False |

## lag_summary

| condition | label | n | lag_ms | correlation | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 3227 | 166.667 | 0.0581127 | False |
| unlabeled | raw | 3227 | 166.667 | 0.0536685 | False |

## jump_suppression_summary

| condition | label | n | spike_count | spike_threshold_m | max_translation_error_m | policy_reject_count | top_policy_reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 3227 | 937 | 0.05 | 1.60817 | 0 |  |
| unlabeled | raw | 3227 | 957 | 0.05 | 1.60762 | 0 |  |

## recovery_summary

_insufficient_data_
