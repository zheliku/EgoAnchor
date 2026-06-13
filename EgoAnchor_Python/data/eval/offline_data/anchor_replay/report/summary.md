# EgoAnchor Eval Summary

## GT / Anchor Sanity

- session_id: `20260613_181828_controller_right`
- object_id: `controller_right`
- gt_source: `transform`
- gt_transform: `OVRControllerPrefab`

## anchor_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | egoanchor_full | 3207 | 0.0397093 | 0.0238578 | 0.0861169 | 20.5778 | 6.4032 | 47.5159 |
| unlabeled | egoanchor_no_static | 3207 | 0.0386343 | 0.0240949 | 0.0829729 | 17.6339 | 6.23366 | 40.0147 |
| unlabeled | kalman_cv | 3207 | 0.0385348 | 0.0242811 | 0.0818692 | 17.5308 | 6.69925 | 39.8074 |
| unlabeled | lowpass_predict | 3207 | 0.0334936 | 0.0214658 | 0.0702702 | 15.8214 | 5.7918 | 36.8124 |
| unlabeled | oneeuro_vanilla | 3207 | 0.0421483 | 0.0238467 | 0.093506 | 18.4295 | 6.63161 | 42.0679 |
| unlabeled | raw_zoh | 3207 | 0.0400881 | 0.0226271 | 0.0885835 | 18.5511 | 6.48054 | 42.0046 |

## pose_offset_summary

| condition | label | n | position_offset_mean_x_m | position_offset_mean_y_m | position_offset_mean_z_m | position_offset_median_x_m | position_offset_median_y_m | position_offset_median_z_m | position_offset_std_x_m | position_offset_std_y_m | position_offset_std_z_m | position_offset_median_norm_m | position_residual_after_median_p50_m | position_residual_after_median_p95_m | position_residual_after_median_rmse_m | rotation_offset_mean_euler_x_deg | rotation_offset_mean_euler_y_deg | rotation_offset_mean_euler_z_deg | rotation_offset_median_euler_x_deg | rotation_offset_median_euler_y_deg | rotation_offset_median_euler_z_deg | rotation_offset_std_euler_x_deg | rotation_offset_std_euler_y_deg | rotation_offset_std_euler_z_deg | rotation_offset_median_deg | rotation_offset_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | egoanchor_full | 3207 | 0.00282964 | -0.00475422 | 0.00971748 | 0.00198228 | -0.00396325 | 0.0092561 | 0.0325566 | 0.0127313 | 0.0151582 | 0.0102622 | 0.0175464 | 0.0853439 | 0.0381228 | 358.981 | 359.084 | 359.654 | 357.934 | 357.758 | 359.653 | 8.25075 | 12.3402 | 14.0789 | 6.4032 | 47.5159 |
| unlabeled | egoanchor_no_static | 3207 | 0.00269721 | -0.00476924 | 0.0096895 | 0.00200889 | -0.00392082 | 0.0092405 | 0.0314452 | 0.012529 | 0.0149308 | 0.010237 | 0.0173591 | 0.0822692 | 0.0370148 | 359.021 | 358.712 | 359.589 | 357.96 | 357.963 | 359.706 | 7.37605 | 10.5481 | 11.9265 | 6.23366 | 40.0147 |
| unlabeled | kalman_cv | 3207 | 0.00265281 | -0.00478005 | 0.00966255 | 0.00208867 | -0.00404169 | 0.008915 | 0.031257 | 0.0125954 | 0.0150344 | 0.0100087 | 0.018111 | 0.0815708 | 0.0369202 | 359.023 | 358.724 | 359.502 | 357.983 | 357.97 | 359.743 | 7.35119 | 10.5343 | 11.8002 | 6.69925 | 39.8074 |
| unlabeled | lowpass_predict | 3207 | 0.00271957 | -0.004772 | 0.00967531 | 0.00194616 | -0.00428313 | 0.0087639 | 0.0264001 | 0.0109482 | 0.0134615 | 0.00994679 | 0.0155027 | 0.070125 | 0.0316181 | 358.978 | 358.403 | 359.953 | 358.221 | 357.836 | 359.979 | 6.72475 | 9.21748 | 10.7734 | 5.7918 | 36.8124 |
| unlabeled | oneeuro_vanilla | 3207 | 0.00277322 | -0.00477995 | 0.00957026 | 0.00123169 | -0.00407991 | 0.0102839 | 0.0352709 | 0.0130658 | 0.015479 | 0.011132 | 0.0173314 | 0.0923323 | 0.0407152 | 359.061 | 358.519 | 359.716 | 357.814 | 358.002 | 359.738 | 7.5591 | 10.6767 | 12.8964 | 6.63161 | 42.0679 |
| unlabeled | raw_zoh | 3207 | 0.00277275 | -0.00478279 | 0.00958957 | 0.0018067 | -0.00415994 | 0.0098745 | 0.0332709 | 0.0124821 | 0.014892 | 0.0108662 | 0.0162621 | 0.0873671 | 0.0385478 | 359.021 | 358.587 | 359.773 | 357.816 | 357.985 | 359.729 | 7.57424 | 10.7604 | 12.9747 | 6.48054 | 42.0046 |

## latency_summary

| condition | label | n | capture_to_apply_p50_ms | capture_to_apply_p90_ms | capture_to_apply_p95_ms | perception_total_p50_ms | yolo_p50_ms | depth_p50_ms | cutie_p50_ms | pose_p50_ms | publish_to_apply_est_p50_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | egoanchor_full | 253 | 180.699 | 195.105 | 195.837 | 140.233 | 0 | 37.9634 | 31.0406 | 39.1207 | 40.1181 |
| unlabeled | egoanchor_no_static | 253 | 180.699 | 195.105 | 195.837 | 140.233 | 0 | 37.9634 | 31.0406 | 39.1207 | 40.1181 |
| unlabeled | kalman_cv | 253 | 180.699 | 195.105 | 195.837 | 140.233 | 0 | 37.9634 | 31.0406 | 39.1207 | 40.1181 |
| unlabeled | lowpass_predict | 253 | 180.699 | 195.105 | 195.837 | 140.233 | 0 | 37.9634 | 31.0406 | 39.1207 | 40.1181 |
| unlabeled | oneeuro_vanilla | 253 | 180.699 | 195.105 | 195.837 | 140.233 | 0 | 37.9634 | 31.0406 | 39.1207 | 40.1181 |
| unlabeled | raw_zoh | 253 | 180.699 | 195.105 | 195.837 | 140.233 | 0 | 37.9634 | 31.0406 | 39.1207 | 40.1181 |

## jitter_summary

| condition | label | n | position_jitter_rms_m | position_jitter_std_m | rotation_jitter_rms_deg | insufficient_data |
| --- | --- | --- | --- | --- | --- | --- |
| unlabeled | egoanchor_full | 1297 | 0.0336771 | 0.0298189 | 69.3186 | False |
| unlabeled | egoanchor_no_static | 1297 | 0.0338292 | 0.0299571 | 69.9105 | False |
| unlabeled | kalman_cv | 1297 | 0.0345568 | 0.0305832 | 70.6415 | False |
| unlabeled | lowpass_predict | 1297 | 0.0340271 | 0.0298905 | 69.4554 | False |
| unlabeled | oneeuro_vanilla | 1297 | 0.0297243 | 0.0264134 | 67.6051 | False |
| unlabeled | raw_zoh | 1297 | 0.0306044 | 0.0271288 | 67.5922 | False |

## slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | egoanchor_full | 3207 | 25.1041 | 102.972 | False |
| unlabeled | egoanchor_no_static | 3207 | 24.2401 | 102.972 | False |
| unlabeled | kalman_cv | 3207 | 24.0152 | 102.352 | False |
| unlabeled | lowpass_predict | 3207 | 20.3556 | 95.7953 | False |
| unlabeled | oneeuro_vanilla | 3207 | 27.5546 | 112.6 | False |
| unlabeled | raw_zoh | 3207 | 25.9358 | 106.623 | False |

## rq1_raw_mapping_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | frame_aligned_raw | 3207 | 0.0400881 | 0.0226271 | 0.0885835 | 18.5511 | 6.48054 | 42.0046 |

## rq1_raw_mapping_slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | frame_aligned_raw | 3207 | 25.9358 | 106.623 | False |

## lag_summary

| condition | label | n | lag_ms | correlation | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| unlabeled | egoanchor_full | 3207 | 400 | 0.672249 | False |
| unlabeled | egoanchor_no_static | 3207 | 400 | 0.611792 | False |
| unlabeled | kalman_cv | 3207 | 400 | 0.611227 | False |
| unlabeled | lowpass_predict | 3207 | 233.333 | 0.604671 | False |
| unlabeled | oneeuro_vanilla | 3207 | 400 | 0.617508 | False |
| unlabeled | raw_zoh | 3207 | 400 | 0.614958 | False |

## jump_suppression_summary

| condition | label | n | spike_count | spike_threshold_m | max_translation_error_m | policy_reject_count | top_policy_reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| unlabeled | egoanchor_full | 3207 | 549 | 0.05 | 0.154891 | 0 |  |
| unlabeled | egoanchor_no_static | 3207 | 526 | 0.05 | 0.154891 | 0 |  |
| unlabeled | kalman_cv | 3207 | 523 | 0.05 | 0.155193 | 0 |  |
| unlabeled | lowpass_predict | 3207 | 413 | 0.05 | 0.138354 | 0 |  |
| unlabeled | oneeuro_vanilla | 3207 | 613 | 0.05 | 0.155853 | 0 |  |
| unlabeled | raw_zoh | 3207 | 577 | 0.05 | 0.152621 | 0 |  |

## recovery_summary

_insufficient_data_
