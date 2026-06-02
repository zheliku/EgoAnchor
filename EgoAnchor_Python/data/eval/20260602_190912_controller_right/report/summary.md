# EgoAnchor Eval Summary

## GT / Anchor Sanity

- session_id: `20260602_190912_controller_right`
- object_id: `controller_right`
- gt_source: `transform`
- gt_transform: `OVRControllerPrefab`

## anchor_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| static | kalman | 1016 | 0.0903075 | 0.0242141 | 0.179426 | 178.198 | 178.616 | 179.376 |
| unlabeled | kalman | 101 | 0.179426 | 0.179426 | 0.179426 | 178.694 | 178.694 | 178.694 |

## pose_offset_summary

| condition | label | n | position_offset_mean_x_m | position_offset_mean_y_m | position_offset_mean_z_m | position_offset_median_x_m | position_offset_median_y_m | position_offset_median_z_m | position_offset_std_x_m | position_offset_std_y_m | position_offset_std_z_m | position_offset_median_norm_m | position_residual_after_median_p50_m | position_residual_after_median_p95_m | position_residual_after_median_rmse_m | rotation_offset_mean_euler_x_deg | rotation_offset_mean_euler_y_deg | rotation_offset_mean_euler_z_deg | rotation_offset_median_euler_x_deg | rotation_offset_median_euler_y_deg | rotation_offset_median_euler_z_deg | rotation_offset_std_euler_x_deg | rotation_offset_std_euler_y_deg | rotation_offset_std_euler_z_deg | rotation_offset_median_deg | rotation_offset_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| static | kalman | 1016 | 0.0375453 | -0.0187125 | 0.0427068 | 0.00644527 | -0.0133072 | 0.0193353 | 0.0541712 | 0.012034 | 0.0386321 | 0.0243409 | 0.00215705 | 0.160323 | 0.0781948 | 0.434518 | 1.77704 | 179.704 | 2.63383 | 0.968156 | 178.775 | 4.14456 | 6.37494 | 2.55381 | 178.616 | 179.376 |
| unlabeled | kalman | 101 | 0.135578 | -0.0397794 | 0.11059 | 0.135578 | -0.0397794 | 0.11059 | 2.77556e-17 | 0 | 1.38778e-17 | 0.179426 | 0 | 0 | 0 | 354.576 | 10.5058 | 180.814 | 354.576 | 10.5058 | 180.814 | 1.13687e-13 | 1.95399e-14 | 3.41061e-13 | 178.694 | 178.694 |

## latency_summary

| condition | label | n | capture_to_apply_p50_ms | capture_to_apply_p90_ms | capture_to_apply_p95_ms | perception_total_p50_ms | yolo_p50_ms | depth_p50_ms | cutie_p50_ms | pose_p50_ms | publish_to_apply_est_p50_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| static | kalman | 69 | 175.917 | 194.723 | 194.966 | 137.253 | 0 | 36.1824 | 30.2454 | 38.3275 | 40.1825 |
| static | raw | 69 | 175.917 | 194.723 | 194.966 | 137.253 | 0 | 36.1824 | 30.2454 | 38.3275 | 40.1825 |
| unlabeled | kalman | 1 | 2415.83 | 2415.83 | 2415.83 | 142.171 | 0 | 37.3422 | 32.4324 | 40.9034 | 2273.66 |
| unlabeled | raw | 1 | 2415.83 | 2415.83 | 2415.83 | 142.171 | 0 | 37.3422 | 32.4324 | 40.9034 | 2273.66 |

## jitter_summary

| condition | label | n | position_jitter_rms_m | position_jitter_std_m | rotation_jitter_rms_deg | insufficient_data |
| --- | --- | --- | --- | --- | --- | --- |
| static | kalman | 1016 | 0.00987669 | 0.00935582 | 13.356 | False |
| static | raw | 0 | nan | nan | nan | True |
| unlabeled | kalman | 101 | 1.56721e-16 | 1.43883e-16 | 0 | False |
| unlabeled | raw | 0 | nan | nan | nan | True |

## slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| static | kalman | 1016 | 33.7791 | 73.0493 | False |
| unlabeled | kalman | 101 | 69.9349 | 75.7854 | False |

## lag_summary

| condition | label | n | lag_ms | correlation | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| static | kalman | 1016 | nan | nan | True |
| static | raw | 0 | nan | nan | True |
| unlabeled | kalman | 101 | nan | nan | True |
| unlabeled | raw | 0 | nan | nan | True |

## jump_suppression_summary

| condition | label | n | spike_count | spike_threshold_m | max_translation_error_m | policy_reject_count | top_policy_reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| static | kalman | 1016 | 301 | 0.05 | 0.179426 | 19 | score_hold:19 |
| unlabeled | kalman | 101 | 101 | 0.05 | 0.179426 | 0 |  |

## recovery_summary

_insufficient_data_
