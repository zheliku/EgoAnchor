# EgoAnchor Eval Summary

## GT / Anchor Sanity

- session_id: `20260603_220619_controller_right`
- object_id: `controller_right`
- gt_source: `transform`
- gt_transform: `OVRControllerPrefab`

## anchor_error_summary

| condition | label | n | translation_rmse_m | translation_median_m | translation_p95_m | rotation_rmse_deg | rotation_median_deg | rotation_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1589 | 0.0197801 | 0.0175008 | 0.0313814 | 5.95436 | 5.50504 | 8.34531 |
| fast_head | raw | 1589 | 0.0291055 | 0.0230379 | 0.0538262 | 7.30612 | 5.89482 | 11.9968 |
| slow_head | kalman | 1398 | 0.0141535 | 0.0115686 | 0.0240561 | 4.84333 | 4.85611 | 6.43084 |
| slow_head | raw | 1398 | 0.0166177 | 0.0114378 | 0.0253814 | 5.36546 | 4.94928 | 7.59538 |
| static | kalman | 1652 | 0.00728253 | 0.00702049 | 0.00906073 | 4.29736 | 4.23476 | 5.40862 |
| static | raw | 1652 | 0.00742908 | 0.00702985 | 0.00951531 | 4.33845 | 4.24935 | 5.55928 |
| unlabeled | kalman | 185 | 0.00885377 | 0.0088342 | 0.00936015 | 4.96663 | 4.92769 | 5.36378 |
| unlabeled | raw | 185 | 0.00882794 | 0.00883135 | 0.00943272 | 5.01887 | 4.85259 | 6.11377 |

## pose_offset_summary

| condition | label | n | position_offset_mean_x_m | position_offset_mean_y_m | position_offset_mean_z_m | position_offset_median_x_m | position_offset_median_y_m | position_offset_median_z_m | position_offset_std_x_m | position_offset_std_y_m | position_offset_std_z_m | position_offset_median_norm_m | position_residual_after_median_p50_m | position_residual_after_median_p95_m | position_residual_after_median_rmse_m | rotation_offset_mean_euler_x_deg | rotation_offset_mean_euler_y_deg | rotation_offset_mean_euler_z_deg | rotation_offset_median_euler_x_deg | rotation_offset_median_euler_y_deg | rotation_offset_median_euler_z_deg | rotation_offset_std_euler_x_deg | rotation_offset_std_euler_y_deg | rotation_offset_std_euler_z_deg | rotation_offset_median_deg | rotation_offset_p95_deg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1589 | 0.00839275 | -0.00722136 | 0.0113617 | 0.00759592 | -0.0049251 | 0.0118297 | 0.00823 | 0.00722238 | 0.00443623 | 0.0148962 | 0.0086674 | 0.0220883 | 0.0120707 | 355.364 | 358.282 | 358.094 | 355.394 | 358.211 | 358.175 | 1.60058 | 1.92395 | 0.926928 | 5.50504 | 8.34531 |
| fast_head | raw | 1589 | 0.00850331 | -0.0070871 | 0.0113989 | 0.00723873 | -0.00486195 | 0.0107155 | 0.0177884 | 0.0142351 | 0.00869451 | 0.0138152 | 0.0149882 | 0.0477418 | 0.0245291 | 355.389 | 358.323 | 358.079 | 355.329 | 358.067 | 358.211 | 3.11536 | 3.41318 | 1.99947 | 5.89482 | 11.9968 |
| slow_head | kalman | 1398 | 0.00648228 | -0.00313384 | 0.00863914 | 0.00657456 | -0.0029631 | 0.00729403 | 0.004421 | 0.0043758 | 0.00592893 | 0.0102571 | 0.00514229 | 0.0167543 | 0.00870012 | 356.624 | 357.849 | 358.064 | 356.553 | 357.898 | 357.947 | 1.35935 | 1.08535 | 0.647703 | 4.85611 | 6.43084 |
| slow_head | raw | 1398 | 0.00647357 | -0.00311035 | 0.00857166 | 0.00670192 | -0.0025509 | 0.00740263 | 0.00579075 | 0.00608324 | 0.00897515 | 0.0103064 | 0.0056846 | 0.0338381 | 0.0123622 | 356.596 | 357.894 | 358.082 | 356.377 | 357.937 | 358.079 | 2.15523 | 1.68555 | 1.22304 | 4.94928 | 7.59538 |
| static | kalman | 1652 | 0.00530152 | -0.000659471 | 0.00464389 | 0.00506131 | -0.000643329 | 0.00483346 | 0.00126964 | 0.000832854 | 0.000789259 | 0.00702802 | 0.000785429 | 0.00357718 | 0.00173852 | 357.007 | 357.678 | 358.183 | 357.036 | 357.579 | 358.189 | 0.405059 | 0.541378 | 0.359691 | 4.23476 | 5.40862 |
| static | raw | 1652 | 0.00531202 | -0.000641025 | 0.00463748 | 0.00503725 | -0.000611223 | 0.00476949 | 0.00153104 | 0.00113429 | 0.00119409 | 0.00696387 | 0.00110803 | 0.00559979 | 0.00226944 | 357.023 | 357.671 | 358.178 | 357.06 | 357.591 | 358.193 | 0.54286 | 0.674257 | 0.483339 | 4.24935 | 5.55928 |
| unlabeled | kalman | 185 | 0.00784997 | -0.00132878 | 0.00377543 | 0.0078092 | -0.00123906 | 0.00403358 | 0.000428516 | 0.00050125 | 0.000559351 | 0.0088763 | 0.000700226 | 0.00137874 | 0.000907802 | 356.093 | 357.719 | 358.082 | 356.096 | 357.89 | 358.099 | 0.183969 | 0.386975 | 0.199074 | 4.92769 | 5.36378 |
| unlabeled | raw | 185 | 0.00778557 | -0.00129225 | 0.00367058 | 0.00793676 | -0.00113288 | 0.00389162 | 0.00090002 | 0.000913154 | 0.000728378 | 0.0089118 | 0.00128799 | 0.00321635 | 0.00150716 | 356.091 | 357.681 | 358.112 | 356.078 | 357.683 | 358.368 | 0.342637 | 0.608933 | 0.407839 | 4.85259 | 6.11377 |

## latency_summary

| condition | label | n | capture_to_apply_p50_ms | capture_to_apply_p90_ms | capture_to_apply_p95_ms | perception_total_p50_ms | yolo_p50_ms | depth_p50_ms | cutie_p50_ms | pose_p50_ms | publish_to_apply_est_p50_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 147 | 180.549 | 194.979 | 196.53 | 141.868 | 0 | 37.1124 | 32.5971 | 39.2175 | 38.6531 |
| fast_head | raw | 147 | 180.549 | 194.979 | 196.53 | 141.868 | 0 | 37.1124 | 32.5971 | 39.2175 | 38.6531 |
| slow_head | kalman | 122 | 181.015 | 194.937 | 213.012 | 142.277 | 0 | 37.5847 | 32.3065 | 40.0561 | 38.2702 |
| slow_head | raw | 122 | 181.015 | 194.937 | 213.012 | 142.277 | 0 | 37.5847 | 32.3065 | 40.0561 | 38.2702 |
| static | kalman | 158 | 181.276 | 194.846 | 195.374 | 140.091 | 0 | 36.6874 | 31.9146 | 38.2068 | 41.7066 |
| static | raw | 158 | 181.276 | 194.846 | 195.374 | 140.091 | 0 | 36.6874 | 31.9146 | 38.2068 | 41.7066 |
| unlabeled | kalman | 20 | 181.915 | 195.198 | 195.737 | 138.681 | 0 | 36.8522 | 31.8011 | 38.1087 | 45.8029 |
| unlabeled | raw | 20 | 181.915 | 195.198 | 195.737 | 138.681 | 0 | 36.8522 | 31.8011 | 38.1087 | 45.8029 |

## jitter_summary

| condition | label | n | position_jitter_rms_m | position_jitter_std_m | rotation_jitter_rms_deg | insufficient_data |
| --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1589 | 0.00536777 | 0.00347601 | 2.86887 | False |
| fast_head | raw | 1589 | 0.017177 | 0.0119333 | 5.19562 | False |
| slow_head | kalman | 1398 | 0.00229501 | 0.00180039 | 2.27849 | False |
| slow_head | raw | 1398 | 0.00664831 | 0.00528229 | 3.26057 | False |
| static | kalman | 1652 | 0.000343019 | 0.000262828 | 1.26819 | False |
| static | raw | 1652 | 0.00114547 | 0.000882316 | 1.67819 | False |
| unlabeled | kalman | 185 | 0.00025712 | 0.000130299 | 0.544395 | False |
| unlabeled | raw | 185 | 0.000918189 | 0.00047888 | 0.878302 | False |

## slip_summary

| condition | label | n | slip_rms_px | slip_peak_px | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1589 | 9.09966 | 29.2292 | False |
| fast_head | raw | 1589 | 16.2479 | 59.1916 | False |
| slow_head | kalman | 1398 | 5.97144 | 15.6129 | False |
| slow_head | raw | 1398 | 6.83609 | 20.8396 | False |
| static | kalman | 1652 | 4.20906 | 7.44944 | False |
| static | raw | 1652 | 4.30459 | 8.97832 | False |
| unlabeled | kalman | 185 | 5.91589 | 6.56412 | False |
| unlabeled | raw | 185 | 5.94671 | 7.3956 | False |

## lag_summary

| condition | label | n | lag_ms | correlation | insufficient_data |
| --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1589 | nan | nan | True |
| fast_head | raw | 1589 | nan | nan | True |
| slow_head | kalman | 1398 | nan | nan | True |
| slow_head | raw | 1398 | nan | nan | True |
| static | kalman | 1652 | nan | nan | True |
| static | raw | 1652 | nan | nan | True |
| unlabeled | kalman | 185 | nan | nan | True |
| unlabeled | raw | 185 | nan | nan | True |

## jump_suppression_summary

| condition | label | n | spike_count | spike_threshold_m | max_translation_error_m | policy_reject_count | top_policy_reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fast_head | kalman | 1589 | 0 | 0.05 | 0.041372 | 0 |  |
| fast_head | raw | 1589 | 120 | 0.05 | 0.0785858 | 0 |  |
| slow_head | kalman | 1398 | 0 | 0.05 | 0.0414019 | 0 |  |
| slow_head | raw | 1398 | 31 | 0.05 | 0.066317 | 0 |  |
| static | kalman | 1652 | 0 | 0.05 | 0.0114413 | 0 |  |
| static | raw | 1652 | 0 | 0.05 | 0.0156553 | 0 |  |
| unlabeled | kalman | 185 | 0 | 0.05 | 0.00956026 | 0 |  |
| unlabeled | raw | 185 | 0 | 0.05 | 0.0107742 | 0 |  |

## recovery_summary

_insufficient_data_
