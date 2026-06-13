# EgoAnchor Eval Summary

## GT / Anchor Sanity

- session_id: `20260613_181828_controller_right`
- object_id: `controller_right`
- gt_source: `transform`
- gt_transform: `OVRControllerPrefab`

## anchor_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 3207 | 0.0408724 | 0.024365 | 0.0894608 | 19.5336 | 6.50119 | 43.8405 |
| unlabeled | raw | 3207 | 0.0400881 | 0.022627 | 0.0885835 | 18.5511 | 6.48054 | 42.0046 |

## pose_offset_summary

| condition | label | n | position_offset_mean_x_m | position_offset_mean_y_m | position_offset_mean_z_m | position_offset_median_x_m | position_offset_median_y_m | position_offset_median_z_m | position_offset_std_x_m | position_offset_std_y_m | position_offset_std_z_m | position_offset_median_norm_m | position_residual_after_median_p50_m | position_residual_after_median_p95_m | position_residual_after_median_rmse_m | rotation_offset_mean_euler_x_deg | rotation_offset_mean_euler_y_deg | rotation_offset_mean_euler_z_deg | rotation_offset_median_euler_x_deg | rotation_offset_median_euler_y_deg | rotation_offset_median_euler_z_deg | rotation_offset_std_euler_x_deg | rotation_offset_std_euler_y_deg | rotation_offset_std_euler_z_deg | rotation_offset_median_deg | rotation_offset_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 3207 | 0.00260463 | -0.00464669 | 0.00952453 | 0.00164372 | -0.00403066 | 0.0092136 | 0.033649 | 0.013255 | 0.0156049 | 0.0101901 | 0.0177745 | 0.0888005 | 0.0394064 | 359.061 | 358.667 | 359.711 | 357.819 | 358.066 | 359.716 | 7.92818 | 11.2946 | 13.7516 | 6.50119 | 43.8405 |
| unlabeled | raw | 3207 | 0.00277275 | -0.00478279 | 0.00958957 | 0.00180671 | -0.00415994 | 0.00987446 | 0.0332709 | 0.0124821 | 0.014892 | 0.0108662 | 0.0162621 | 0.0873671 | 0.0385478 | 359.021 | 358.587 | 359.773 | 357.816 | 357.985 | 359.729 | 7.57424 | 10.7604 | 12.9747 | 6.48054 | 42.0046 |

## latency_summary

| condition | label | n | capture_to_apply_p50_ms | capture_to_apply_p90_ms | capture_to_apply_p95_ms | perception_total_p50_ms | yolo_p50_ms | depth_p50_ms | cutie_p50_ms | pose_p50_ms | publish_to_apply_est_p50_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 253 | 180.699 | 195.105 | 195.837 | 140.233 | 0 | 37.9634 | 31.0406 | 39.1207 | 40.1181 |
| unlabeled | raw | 253 | 180.699 | 195.105 | 195.837 | 140.233 | 0 | 37.9634 | 31.0406 | 39.1207 | 40.1181 |

## jitter_summary

| condition | label | n | position_jitter_rms_m | position_jitter_std_m | rotation_jitter_rms_deg | insufficient_data |
| --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 1297 | 0.0331378 | 0.0294963 | 67.4867 | False |
| unlabeled | raw | 1297 | 0.0306044 | 0.0271288 | 67.5922 | False |

## slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 3207 | 26.1062 | 102.945 | False |
| unlabeled | raw | 3207 | 25.9358 | 106.623 | False |

## rq1_raw_mapping_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | frame_aligned_raw | 3207 | 0.0400881 | 0.022627 | 0.0885835 | 18.5511 | 6.48054 | 42.0046 |

## rq1_raw_mapping_slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | frame_aligned_raw | 3207 | 25.9358 | 106.623 | False |

## lag_summary

| condition | label | n | lag_ms | correlation | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 3207 | 400 | 0.80253 | False |
| unlabeled | raw | 3207 | 400 | 0.614958 | False |

## jump_suppression_summary

| condition | label | n | spike_count | spike_threshold_m | max_translation_error_m | policy_reject_count | top_policy_reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | kalman | 3207 | 577 | 0.05 | 0.154692 | 0 |  |
| unlabeled | raw | 3207 | 577 | 0.05 | 0.152621 | 0 |  |

## recovery_summary

_insufficient_data_
