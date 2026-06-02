# EgoAnchor Eval Summary

## GT / Anchor Sanity

- session_id: `20260602_231020_controller_right`
- object_id: `controller_right`
- gt_source: `transform`
- gt_transform: `OVRControllerPrefab`

## anchor_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1553 | 0.0447706 | 0.0452701 | 0.0610461 | 178.691 | 178.642 | 179.749 |
| fast_head | raw | 1553 | 0.0482825 | 0.0448941 | 0.0664662 | 178.475 | 178.685 | 179.736 |
| object_motion | kalman | 3407 | 0.0580571 | 0.0321251 | 0.115615 | 175.922 | 178.764 | 179.757 |
| object_motion | raw | 3407 | 0.0519379 | 0.0296694 | 0.11436 | 176.752 | 178.854 | 179.85 |
| slow_head | kalman | 2009 | 0.0346388 | 0.0359139 | 0.0430274 | 178.521 | 178.474 | 179.521 |
| slow_head | raw | 2009 | 0.0354839 | 0.0355431 | 0.0446788 | 178.505 | 178.551 | 179.75 |
| static | kalman | 3318 | 0.0191025 | 0.018566 | 0.0230277 | 178.569 | 178.581 | 179.116 |
| static | raw | 3318 | 0.0191241 | 0.0185524 | 0.0234078 | 178.565 | 178.604 | 179.288 |
| unlabeled | kalman | 831 | 0.0240074 | 0.0239315 | 0.0251983 | 178.631 | 178.635 | 179.022 |
| unlabeled | raw | 831 | 0.0240925 | 0.0239354 | 0.0253507 | 178.65 | 178.729 | 179.29 |

## pose_offset_summary

| condition | label | n | position_offset_mean_x_m | position_offset_mean_y_m | position_offset_mean_z_m | position_offset_median_x_m | position_offset_median_y_m | position_offset_median_z_m | position_offset_std_x_m | position_offset_std_y_m | position_offset_std_z_m | position_offset_median_norm_m | position_residual_after_median_p50_m | position_residual_after_median_p95_m | position_residual_after_median_rmse_m | rotation_offset_mean_euler_x_deg | rotation_offset_mean_euler_y_deg | rotation_offset_mean_euler_z_deg | rotation_offset_median_euler_x_deg | rotation_offset_median_euler_y_deg | rotation_offset_median_euler_z_deg | rotation_offset_std_euler_x_deg | rotation_offset_std_euler_y_deg | rotation_offset_std_euler_z_deg | rotation_offset_median_deg | rotation_offset_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1553 | 0.0152802 | -0.0155153 | 0.0359567 | 0.0150324 | -0.0154718 | 0.0365318 | 0.00998382 | 0.00837202 | 0.00821866 | 0.0424255 | 0.0123413 | 0.0244323 | 0.0154178 | 4.09235 | 0.62775 | 178.891 | 4.49256 | 0.652701 | 178.739 | 3.25497 | 1.50285 | 0.929949 | 178.642 | 179.749 |
| fast_head | raw | 1553 | 0.0154673 | -0.0156228 | 0.0358565 | 0.0150448 | -0.0151773 | 0.0362531 | 0.0157446 | 0.013349 | 0.0116668 | 0.0420831 | 0.0169301 | 0.0402871 | 0.023722 | 4.08054 | 0.616215 | 178.945 | 4.84729 | 0.642154 | 178.811 | 4.85858 | 2.69136 | 1.73549 | 178.685 | 179.736 |
| object_motion | kalman | 3407 | -0.000560101 | -0.0109364 | 0.0192609 | 0.0116497 | -0.0128869 | 0.0201117 | 0.0490157 | 0.0160235 | 0.014847 | 0.0265758 | 0.0116749 | 0.126649 | 0.0550757 | 2.18595 | 1.86809 | 178.604 | 2.7604 | 1.31484 | 179.3 | 7.68314 | 6.15211 | 9.32418 | 178.764 | 179.757 |
| object_motion | raw | 3407 | -0.000612241 | -0.0108721 | 0.0191778 | 0.0118965 | -0.012626 | 0.0204842 | 0.0433655 | 0.0134731 | 0.0122099 | 0.026843 | 0.0103074 | 0.126194 | 0.0487076 | 2.30242 | 1.86753 | 178.604 | 2.51385 | 1.2128 | 179.562 | 5.48276 | 5.41205 | 8.65249 | 178.854 | 179.85 |
| slow_head | kalman | 2009 | 0.0106824 | -0.0125751 | 0.0284715 | 0.00959163 | -0.0121898 | 0.0296917 | 0.00599727 | 0.00493038 | 0.00752981 | 0.0334991 | 0.00890048 | 0.0196728 | 0.0109454 | 4.17467 | 1.13662 | 178.566 | 4.09978 | 1.02757 | 178.498 | 1.05778 | 1.08078 | 0.578984 | 178.474 | 179.521 |
| slow_head | raw | 2009 | 0.0106868 | -0.012599 | 0.0285176 | 0.00965964 | -0.0120592 | 0.0291415 | 0.00784783 | 0.00639924 | 0.00838902 | 0.0329843 | 0.0099729 | 0.0207105 | 0.0132155 | 4.15902 | 1.13435 | 178.568 | 4.05535 | 0.995311 | 178.606 | 1.40535 | 1.37651 | 0.830968 | 178.551 | 179.75 |
| static | kalman | 3318 | 0.00747941 | -0.00995288 | 0.0142454 | 0.00704014 | -0.00973787 | 0.0143539 | 0.00143828 | 0.00129274 | 0.00179829 | 0.0187197 | 0.00223457 | 0.00442598 | 0.00268787 | 3.94692 | 1.04419 | 178.604 | 3.86839 | 1.02983 | 178.606 | 0.495365 | 0.524746 | 0.339873 | 178.581 | 179.116 |
| static | raw | 3318 | 0.00747144 | -0.00995113 | 0.0142178 | 0.00704437 | -0.00977736 | 0.0142487 | 0.00162 | 0.00146882 | 0.00198929 | 0.0186614 | 0.00239911 | 0.005183 | 0.0029921 | 3.94502 | 1.04614 | 178.603 | 3.91433 | 1.01609 | 178.636 | 0.629985 | 0.653224 | 0.465177 | 178.604 | 179.288 |
| unlabeled | kalman | 831 | 0.0106178 | -0.0126161 | 0.017372 | 0.0108538 | -0.0124797 | 0.0173561 | 0.000827219 | 0.000667509 | 0.00123924 | 0.0239746 | 0.000959419 | 0.00305167 | 0.00165535 | 5.14519 | 0.832584 | 178.666 | 5.28133 | 0.863156 | 178.667 | 0.528958 | 0.321035 | 0.235565 | 178.635 | 179.022 |
| unlabeled | raw | 831 | 0.0106173 | -0.0125859 | 0.017339 | 0.010805 | -0.0125434 | 0.01738 | 0.00129597 | 0.00135457 | 0.00227173 | 0.0240031 | 0.00113693 | 0.00412859 | 0.00295193 | 5.15802 | 0.819984 | 178.685 | 5.15451 | 0.83602 | 178.764 | 0.67977 | 0.530178 | 0.448697 | 178.729 | 179.29 |

## latency_summary

| condition | label | n | capture_to_apply_p50_ms | capture_to_apply_p90_ms | capture_to_apply_p95_ms | perception_total_p50_ms | yolo_p50_ms | depth_p50_ms | cutie_p50_ms | pose_p50_ms | publish_to_apply_est_p50_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 137 | 175.177 | 194.536 | 194.98 | 135.487 | 0 | 37.1988 | 32.2169 | 39.394 | 40.9825 |
| fast_head | raw | 137 | 175.177 | 194.536 | 194.98 | 135.487 | 0 | 37.1988 | 32.2169 | 39.394 | 40.9825 |
| object_motion | kalman | 307 | 181.476 | 195.453 | 216.162 | 141.015 | 0 | 38.2052 | 32.5895 | 39.9676 | 40.7464 |
| object_motion | raw | 307 | 181.476 | 195.453 | 216.162 | 141.015 | 0 | 38.2052 | 32.5895 | 39.9676 | 40.7464 |
| slow_head | kalman | 189 | 175.122 | 194.59 | 194.822 | 134.196 | 0 | 37.1278 | 31.9439 | 38.9444 | 42.9898 |
| slow_head | raw | 189 | 175.122 | 194.59 | 194.822 | 134.196 | 0 | 37.1278 | 31.9439 | 38.9444 | 42.9898 |
| static | kalman | 321 | 175.805 | 195.522 | 216.321 | 137.149 | 0 | 37.3304 | 32.9613 | 39.7197 | 40.7579 |
| static | raw | 321 | 175.805 | 195.522 | 216.321 | 137.149 | 0 | 37.3304 | 32.9613 | 39.7197 | 40.7579 |
| unlabeled | kalman | 81 | 180.413 | 194.887 | 195.237 | 133.593 | 0 | 36.2336 | 31.5639 | 38.7488 | 45.1295 |
| unlabeled | raw | 81 | 180.413 | 194.887 | 195.237 | 133.593 | 0 | 36.2336 | 31.5639 | 38.7488 | 45.1295 |

## jitter_summary

| condition | label | n | position_jitter_rms_m | position_jitter_std_m | rotation_jitter_rms_deg | insufficient_data |
| --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1553 | 0.00445248 | 0.00252151 | 3.79008 | False |
| fast_head | raw | 1553 | 0.0118153 | 0.00722437 | 5.86878 | False |
| object_motion | kalman | 2537 | 0.00937472 | 0.00840599 | 41.5145 | False |
| object_motion | raw | 2537 | 0.0145768 | 0.0128742 | 42.3776 | False |
| slow_head | kalman | 2009 | 0.00167359 | 0.00112614 | 1.75578 | False |
| slow_head | raw | 2009 | 0.0048089 | 0.00355526 | 2.21431 | False |
| static | kalman | 3318 | 0.000278649 | 0.000183251 | 0.982752 | False |
| static | raw | 3318 | 0.00103064 | 0.000701709 | 1.43059 | False |
| unlabeled | kalman | 831 | 0.000572966 | 0.000487584 | 1.49729 | False |
| unlabeled | raw | 831 | 0.00211073 | 0.00183531 | 1.75957 | False |

## slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1553 | 8.68739 | 28.7226 | False |
| fast_head | raw | 1553 | 12.5752 | 53.91 | False |
| object_motion | kalman | 3407 | 34.6756 | 137.568 | False |
| object_motion | raw | 3407 | 30.3163 | 110.877 | False |
| slow_head | kalman | 2009 | 5.233 | 12.7587 | False |
| slow_head | raw | 2009 | 6.21325 | 19.5048 | False |
| static | kalman | 3318 | 1.75497 | 4.07012 | False |
| static | raw | 3318 | 1.8978 | 5.77281 | False |
| unlabeled | kalman | 831 | 2.1893 | 3.91098 | False |
| unlabeled | raw | 831 | 2.35226 | 6.49761 | False |

## lag_summary

| condition | label | n | lag_ms | correlation | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1553 | nan | nan | True |
| fast_head | raw | 1553 | nan | nan | True |
| object_motion | kalman | 3407 | 400 | 0.466565 | False |
| object_motion | raw | 3407 | 366.667 | 0.447281 | False |
| slow_head | kalman | 2009 | nan | nan | True |
| slow_head | raw | 2009 | nan | nan | True |
| static | kalman | 3318 | nan | nan | True |
| static | raw | 3318 | nan | nan | True |
| unlabeled | kalman | 831 | nan | nan | True |
| unlabeled | raw | 831 | nan | nan | True |

## jump_suppression_summary

| condition | label | n | spike_count | spike_threshold_m | max_translation_error_m | policy_reject_count | top_policy_reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1553 | 300 | 0.05 | 0.0782532 | 0 |  |
| fast_head | raw | 1553 | 526 | 0.05 | 0.106786 | 0 |  |
| object_motion | kalman | 3407 | 960 | 0.05 | 0.185627 | 0 |  |
| object_motion | raw | 3407 | 761 | 0.05 | 0.178754 | 0 |  |
| slow_head | kalman | 2009 | 23 | 0.05 | 0.058634 | 0 |  |
| slow_head | raw | 2009 | 24 | 0.05 | 0.0913628 | 0 |  |
| static | kalman | 3318 | 0 | 0.05 | 0.0257561 | 0 |  |
| static | raw | 3318 | 0 | 0.05 | 0.0281845 | 0 |  |
| unlabeled | kalman | 831 | 0 | 0.05 | 0.0294755 | 0 |  |
| unlabeled | raw | 831 | 0 | 0.05 | 0.0430183 | 0 |  |

## recovery_summary

_insufficient_data_
