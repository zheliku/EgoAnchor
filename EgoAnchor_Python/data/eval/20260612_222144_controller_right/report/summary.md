# EgoAnchor Eval Summary

## GT / Anchor Sanity

- session_id: `20260612_222144_controller_right`
- object_id: `controller_right`
- gt_source: `transform`
- gt_transform: `OVRControllerPrefab`

## anchor_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1790 | 0.0259001 | 0.0215605 | 0.0405961 | 35.6309 | 35.8369 | 38.8193 |
| fast_head | raw | 1790 | 0.0262288 | 0.0220584 | 0.0402487 | 35.7175 | 35.8518 | 38.9931 |
| object_motion | kalman | 3593 | 0.11988 | 0.0721429 | 0.223566 | 83.9202 | 59.1912 | 149.157 |
| object_motion | raw | 3593 | 0.177815 | 0.108467 | 0.35647 | 90.1374 | 58.2462 | 158.963 |
| slow_head | kalman | 1 | 0.0149885 | 0.0149885 | 0.0149885 | 32.6234 | 32.6234 | 32.6234 |
| slow_head | raw | 1 | 0.0153465 | 0.0153465 | 0.0153465 | 32.8904 | 32.8904 | 32.8904 |
| static | kalman | 4617 | 0.0239993 | 0.0192511 | 0.0432394 | 34.9606 | 34.8052 | 37.7486 |
| static | raw | 4617 | 0.0244952 | 0.0196914 | 0.0427782 | 34.9232 | 34.8758 | 37.7983 |
| unlabeled | kalman | 506 | 0.0224499 | 0.022167 | 0.0260161 | 35.8197 | 35.69 | 37.2453 |
| unlabeled | raw | 506 | 0.0230803 | 0.0223318 | 0.0277316 | 35.8988 | 35.3022 | 37.6118 |

## pose_offset_summary

| condition | label | n | position_offset_mean_x_m | position_offset_mean_y_m | position_offset_mean_z_m | position_offset_median_x_m | position_offset_median_y_m | position_offset_median_z_m | position_offset_std_x_m | position_offset_std_y_m | position_offset_std_z_m | position_offset_median_norm_m | position_residual_after_median_p50_m | position_residual_after_median_p95_m | position_residual_after_median_rmse_m | rotation_offset_mean_euler_x_deg | rotation_offset_mean_euler_y_deg | rotation_offset_mean_euler_z_deg | rotation_offset_median_euler_x_deg | rotation_offset_median_euler_y_deg | rotation_offset_median_euler_z_deg | rotation_offset_std_euler_x_deg | rotation_offset_std_euler_y_deg | rotation_offset_std_euler_z_deg | rotation_offset_median_deg | rotation_offset_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1790 | -0.00414562 | -0.00738817 | 0.0217944 | -0.00255236 | -0.00439733 | 0.0197852 | 0.00601115 | 0.00726444 | 0.00592799 | 0.0204281 | 0.00700942 | 0.0224948 | 0.0118139 | 329.336 | 341.397 | 6.78291 | 329.021 | 341.834 | 6.62471 | 2.94769 | 2.28581 | 0.895916 | 35.8369 | 38.8193 |
| fast_head | raw | 1790 | -0.00437953 | -0.00723851 | 0.0221434 | -0.00271847 | -0.00466296 | 0.0202665 | 0.00563296 | 0.00689392 | 0.00684002 | 0.0209729 | 0.0067405 | 0.0227427 | 0.011788 | 329.306 | 341.239 | 6.86548 | 329.217 | 341.491 | 6.6764 | 2.6747 | 2.34958 | 1.08591 | 35.8518 | 38.9931 |
| object_motion | kalman | 3593 | 0.0182183 | -0.00521385 | 0.019765 | 0.00756609 | -0.00685963 | 0.0111264 | 0.0797345 | 0.060636 | 0.0598937 | 0.0151029 | 0.0629562 | 0.237631 | 0.117526 | 311.073 | 16.7893 | 354.031 | 329.584 | 7.22136 | 1.98489 | 55.1854 | 30.1393 | 27.5432 | 59.1912 | 149.157 |
| object_motion | raw | 3593 | 0.0211187 | -0.0387253 | 0.0566139 | 0.00615955 | -0.00714669 | 0.0185802 | 0.0779777 | 0.0918826 | 0.10929 | 0.0208384 | 0.112381 | 0.335712 | 0.170689 | 307.739 | 4.80944 | 353.597 | 330.946 | 0.572659 | 359.634 | 63.2309 | 23.7302 | 30.2007 | 58.2462 | 158.963 |
| slow_head | kalman | 1 | 0.000987009 | -0.000406474 | 0.0149504 | 0.000987009 | -0.000406474 | 0.0149504 | 0 | 0 | 0 | 0.0149885 | 0 | 0 | 0 | 332.959 | 341.085 | 6.17825 | 332.959 | 341.085 | 6.17825 | 0 | 0 | 0 | 32.6234 | 32.6234 |
| slow_head | raw | 1 | 0.000715172 | -0.00063917 | 0.0153165 | 0.000715172 | -0.00063917 | 0.0153165 | 0 | 0 | 0 | 0.0153465 | 0 | 0 | 0 | 332.872 | 340.698 | 6.04655 | 332.872 | 340.698 | 6.04655 | 0 | 0 | 0 | 32.8904 | 32.8904 |
| static | kalman | 4617 | -0.00179386 | -0.00490259 | 0.0201278 | -0.00125553 | -0.00370657 | 0.0183713 | 0.00476283 | 0.00528635 | 0.00964141 | 0.0187835 | 0.00553404 | 0.0246418 | 0.0121816 | 330.045 | 342.257 | 6.75049 | 329.975 | 341.793 | 6.71871 | 2.8178 | 5.21501 | 1.82281 | 34.8052 | 37.7486 |
| static | raw | 4617 | -0.0019219 | -0.00530116 | 0.0204282 | -0.000859773 | -0.00419289 | 0.0188465 | 0.00492867 | 0.0058323 | 0.00962304 | 0.0193264 | 0.00620716 | 0.0235679 | 0.0124807 | 330.052 | 341.85 | 6.77265 | 330.017 | 341.574 | 6.73874 | 2.78393 | 3.55103 | 1.36638 | 34.8758 | 37.7983 |
| unlabeled | kalman | 506 | 0.000939957 | -0.00846111 | 0.0204436 | 0.00108477 | -0.00918156 | 0.0203389 | 0.00179171 | 0.00232445 | 0.00222893 | 0.0223417 | 0.00211578 | 0.00818377 | 0.00375931 | 330.445 | 339.059 | 6.07841 | 330.391 | 338.248 | 5.97067 | 1.29854 | 3.09118 | 0.5286 | 35.69 | 37.2453 |
| unlabeled | raw | 506 | 0.000606628 | -0.00847335 | 0.0210401 | 0.00124323 | -0.00905448 | 0.0205622 | 0.00203996 | 0.00238647 | 0.00282753 | 0.0225019 | 0.00291648 | 0.00764572 | 0.00433854 | 330.331 | 339.111 | 5.91374 | 330.531 | 339.69 | 5.87262 | 1.34674 | 3.25766 | 0.512655 | 35.3022 | 37.6118 |

## latency_summary

| condition | label | n | capture_to_apply_p50_ms | capture_to_apply_p90_ms | capture_to_apply_p95_ms | perception_total_p50_ms | yolo_p50_ms | depth_p50_ms | cutie_p50_ms | pose_p50_ms | publish_to_apply_est_p50_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 138 | 183.25 | 216.221 | 216.459 | 149.48 | 0 | 42.3403 | 30.8946 | 42.5052 | 37.3555 |
| fast_head | raw | 138 | 183.25 | 216.221 | 216.459 | 149.48 | 0 | 42.3403 | 30.8946 | 42.5052 | 37.3555 |
| object_motion | kalman | 256 | 185.825 | 216.464 | 217.287 | 149.835 | 0 | 41.8528 | 31.7758 | 42.2942 | 38.4499 |
| object_motion | raw | 256 | 185.825 | 216.464 | 217.287 | 149.835 | 0 | 41.8528 | 31.7758 | 42.2942 | 38.4499 |
| slow_head | kalman | 1 | 183.036 | 183.036 | 183.036 | 145.973 | 0 | 42.9088 | 28.8267 | 41.4966 | 37.063 |
| slow_head | raw | 1 | 183.036 | 183.036 | 183.036 | 145.973 | 0 | 42.9088 | 28.8267 | 41.4966 | 37.063 |
| static | kalman | 351 | 193.717 | 216.053 | 216.802 | 150.071 | 0 | 41.9084 | 31.0686 | 42.7806 | 38.1924 |
| static | raw | 351 | 193.717 | 216.053 | 216.802 | 150.071 | 0 | 41.9084 | 31.0686 | 42.7806 | 38.1924 |
| unlabeled | kalman | 40 | 194.533 | 216.64 | 218.19 | 151.073 | 0 | 42.3093 | 32.4446 | 42.8435 | 41.3793 |
| unlabeled | raw | 40 | 194.533 | 216.64 | 218.19 | 151.073 | 0 | 42.3093 | 32.4446 | 42.8435 | 41.3793 |

## jitter_summary

| condition | label | n | position_jitter_rms_m | position_jitter_std_m | rotation_jitter_rms_deg | insufficient_data |
| --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1790 | 0.00405379 | 0.00270609 | 5.01682 | False |
| fast_head | raw | 1790 | 0.00482125 | 0.0035963 | 5.08315 | False |
| object_motion | kalman | 1979 | 0.0157011 | 0.0132237 | 74.7952 | False |
| object_motion | raw | 1979 | 0.0217316 | 0.0179864 | 82.5171 | False |
| slow_head | kalman | 1 | nan | nan | nan | True |
| slow_head | raw | 1 | nan | nan | nan | True |
| static | kalman | 4617 | 0.00426182 | 0.00383516 | 7.07194 | False |
| static | raw | 4617 | 0.0044869 | 0.00394611 | 5.60967 | False |
| unlabeled | kalman | 506 | 0.00179802 | 0.00140578 | 3.93134 | False |
| unlabeled | raw | 506 | 0.00212263 | 0.00151095 | 4.09095 | False |

## slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1790 | 5.14158 | 11.7483 | False |
| fast_head | raw | 1790 | 5.0452 | 12.7982 | False |
| object_motion | kalman | 3550 | 562.269 | 31067.2 | False |
| object_motion | raw | 3550 | 561.372 | 31020.6 | False |
| slow_head | kalman | 1 | 5.2761 | 5.2761 | False |
| slow_head | raw | 1 | 5.28053 | 5.28053 | False |
| static | kalman | 4617 | 5.00266 | 24.772 | False |
| static | raw | 4617 | 4.87736 | 21.5036 | False |
| unlabeled | kalman | 506 | 4.07834 | 6.80121 | False |
| unlabeled | raw | 506 | 4.11983 | 6.44051 | False |

## lag_summary

| condition | label | n | lag_ms | correlation | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1790 | nan | nan | True |
| fast_head | raw | 1790 | nan | nan | True |
| object_motion | kalman | 3593 | 133.333 | 0.0651622 | False |
| object_motion | raw | 3593 | 433.333 | 0.0373523 | False |
| slow_head | kalman | 1 | nan | nan | True |
| slow_head | raw | 1 | nan | nan | True |
| static | kalman | 4617 | nan | nan | True |
| static | raw | 4617 | nan | nan | True |
| unlabeled | kalman | 506 | nan | nan | True |
| unlabeled | raw | 506 | nan | nan | True |

## jump_suppression_summary

| condition | label | n | spike_count | spike_threshold_m | max_translation_error_m | policy_reject_count | top_policy_reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1790 | 0 | 0.05 | 0.0484431 | 38 | score_reject:26;rotation_innovation_d2_18.1:12 |
| fast_head | raw | 1790 | 14 | 0.05 | 0.06505 | 0 |  |
| object_motion | kalman | 3593 | 2062 | 0.05 | 0.573812 | 1263 | score_reject:1187;rotation_innovation_d2_13.6:14;stale_measurement:13;rotation_innovation_d2_78.2:13;rotation_innovation_d2_157.3:13 |
| object_motion | raw | 3593 | 2446 | 0.05 | 0.786966 | 0 |  |
| slow_head | kalman | 1 | 0 | 0.05 | 0.0149885 | 0 |  |
| slow_head | raw | 1 | 0 | 0.05 | 0.0153465 | 0 |  |
| static | kalman | 4617 | 199 | 0.05 | 0.106037 | 101 | score_reject:36;rotation_innovation_d2_127.6:15;rotation_innovation_d2_99.7:14;rotation_innovation_d2_12.5:13;rotation_innovation_d2_102.6:12 |
| static | raw | 4617 | 185 | 0.05 | 0.0953671 | 0 |  |
| unlabeled | kalman | 506 | 0 | 0.05 | 0.031125 | 0 |  |
| unlabeled | raw | 506 | 0 | 0.05 | 0.0339674 | 0 |  |

## recovery_summary

_insufficient_data_
