"""RQ2 动态追踪试次分析。

本模块只消费 Unity 已写入的世界系 pose 与时间契约。source-frame 指标按
``source_frame_id`` 首次出现去重；参考轨迹的位置采用线性插值，旋转采用
四元数 Slerp。所有统计以试次为基本单位，不把无输出帧从可用率分母删除。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation
from scipy.stats import pearsonr

from egoanchor.eval.io import SessionLogs, load_session
from egoanchor.eval.metrics import (
    is_pose_value,
    pose_error,
    slerp_lerp_resample,
)


RQ2_CONDITIONS: tuple[str, ...] = ("slow_translation", "fast_motion", "rotation")
"""RQ2 纳入分析的三类动态场景。"""

PRE_IMAGE_FIT_WINDOW_MS = 400.0
"""局部运动拟合只使用图像时刻之前固定 400 ms 的参考轨迹。"""

PRE_IMAGE_MIN_SAMPLES = 4
"""固定窗口内稳健拟合所需的最少参考 pose 数。"""

LAG_GAP_FACTOR = 2.5
"""连续段阈值相对 trial 有效样本中位间隔的倍数。"""

LAG_GAP_MIN_MS = 100.0
"""高帧率流的最小缺口容差，避免少量调度抖动造成过度切段。"""

LAG_GAP_ABSOLUTE_CAP_MS = 500.0
"""缺口阈值绝对上限，禁止跨越明显的 tracking/reacquire 空窗。"""

LAG_MIN_SIGNAL_STD = 1e-5
"""速度信号低于该标准差时视为缺少可辨识动态激励。"""

LAG_MIN_PEAK_CORRELATION = 0.5
"""峰值归一化互相关低于该值时不报告 lag。"""

LAG_MIN_SIGNAL_SAMPLES = 16
"""lag 估计所需的最少速度样本数，避免短序列偶然相关。"""

LAG_SIGNIFICANCE_ALPHA = 0.05
"""候选 lag 多重比较经 Bonferroni 校正后的显著性阈值。"""

DISPLAY_HOLD_TRANSLATION_EPS_M = 1e-6
"""相邻显示位置变化不超过该阈值时视为保持上一 pose。"""

DISPLAY_HOLD_ROTATION_EPS_DEG = 1e-4
"""相邻显示旋转变化不超过该阈值时视为保持上一 pose。"""

MODEL_BOOTSTRAP_SEED = 20260710
"""trial-cluster bootstrap 的固定随机种子。"""

MODEL_BOOTSTRAP_ITERATIONS = 1000
"""trial-cluster bootstrap 重采样次数。"""

MODEL_MIN_TRIALS_FOR_CI = 3
"""回归置信区间所需的最少独立 trial 数。"""

SOURCE_COLUMNS = [
    "condition",
    "rq2_trial_id",
    "label",
    "source_frame_id",
    "image_mono_ms",
    "unity_pose_handle_mono_ms",
    "first_render_mono_ms",
    "policy_output_target_mono_ms",
    "observation_age_ms",
    "smoothing_delay_ms",
    "rq2_target_linear_speed_m_s",
    "rq2_target_angular_speed_deg_s",
    "aligned_raw_pos",
    "aligned_raw_rot",
    "gt_image_pos",
    "gt_image_rot",
    "raw_translation_error_image_m",
    "raw_rotation_error_image_deg",
]
"""每个 source frame 首次出现的诊断表字段。"""

MOTION_COLUMNS = SOURCE_COLUMNS + [
    "handle_delay_ms",
    "render_delay_ms",
    "gt_handle_pos",
    "gt_handle_rot",
    "gt_render_pos",
    "gt_render_rot",
    "raw_translation_error_handle_m",
    "raw_rotation_error_handle_deg",
    "raw_translation_error_render_m",
    "raw_rotation_error_render_deg",
    "pre_image_linear_velocity_m_s",
    "pre_image_rotation_axis_world",
    "pre_image_linear_speed_m_s",
    "pre_image_angular_speed_deg_s",
    "reference_translation_motion_handle_m",
    "reference_translation_motion_render_m",
    "reference_rotation_motion_handle_deg",
    "reference_rotation_motion_render_deg",
    "raw_translation_lag_error_capture_m",
    "raw_translation_lag_error_handle_m",
    "raw_translation_lag_error_render_m",
    "raw_rotation_lag_error_capture_deg",
    "raw_rotation_lag_error_handle_deg",
    "raw_rotation_lag_error_render_deg",
    "expected_translation_handle_m",
    "expected_translation_render_m",
    "expected_rotation_handle_deg",
    "expected_rotation_render_deg",
]
"""同一 raw pose 的有符号滞后残差、预测量与参考运动暴露量字段。

``reference_*_motion_*`` 只描述参考物体在时延区间内实际移动了多少，用于
量化暴露量；它不作为 ``v*tau`` 模型的独立验证量。模型预测速度仅由不与
时延区间重叠的 pre-image 固定窗口估计。
"""

TRIAL_COLUMNS = [
    "condition",
    "rq2_trial_id",
    "label",
    "render_frame_count",
    "output_frame_count",
    "tracking_availability",
    "display_error_sample_count",
    "display_update_rate_hz",
    "display_hold_fraction",
    "raw_error_sample_count",
    "display_translation_median_m",
    "display_translation_p95_m",
    "display_rotation_median_deg",
    "display_rotation_p95_deg",
    "source_frame_count",
    "raw_translation_median_m",
    "raw_translation_p95_m",
    "raw_rotation_median_deg",
    "raw_rotation_p95_deg",
    "observation_delay_p50_ms",
    "observation_delay_p95_ms",
    "effective_policy_delay_p50_ms",
    "smoothing_delay_p50_ms",
    "raw_translation_lag_ms",
    "display_translation_lag_ms",
    "display_minus_raw_translation_lag_ms",
    "raw_rotation_lag_ms",
    "display_rotation_lag_ms",
    "display_minus_raw_rotation_lag_ms",
    "raw_lag_segment_count",
    "display_lag_segment_count",
]
"""RQ2 试次级汇总字段。

``display_*`` 统计每个 ``label`` 实际显示的 pose，包括 hold-last；可用率仍由
``has_output_pose`` 计算。``display_update_rate_hz`` 是相邻有效渲染帧间实际发生
pose 变化的频率，``display_hold_fraction`` 是保持同一 pose 的样本对比例。
``display_minus_raw_*`` 是同一变体显示 lag 减去 raw lag 的差值。
"""

LATENCY_COLUMNS = [
    "condition",
    "rq2_trial_id",
    "label",
    "source_frame_count",
    "observation_delay_p50_ms",
    "observation_delay_p95_ms",
    "image_to_first_render_p50_ms",
    "effective_policy_delay_p50_ms",
    "smoothing_delay_p50_ms",
    "raw_translation_lag_ms",
    "display_translation_lag_ms",
    "display_minus_raw_translation_lag_ms",
    "raw_rotation_lag_ms",
    "display_rotation_lag_ms",
    "display_minus_raw_rotation_lag_ms",
]
"""RQ2 时延分解表字段；显示 lag 按变体计算，共享 raw 诊断复制到各变体行。"""

MODEL_COLUMNS = [
    "level",
    "condition",
    "rq2_trial_id",
    "label",
    "channel",
    "n",
    "n_trials",
    "observed_mean",
    "predicted_mean",
    "bias",
    "mae",
    "slope",
    "intercept",
    "slope_ci_low",
    "slope_ci_high",
    "intercept_ci_low",
    "intercept_ci_high",
]
"""trial 级模型一致性与场景级 cluster-bootstrap 回归字段。"""


def build_source_observations(logs: SessionLogs | pd.DataFrame) -> pd.DataFrame:
    """从主变体构造按试次和 source frame 去重的采集时刻 raw 表。

    Args:
        logs: ``SessionLogs`` 或已经展平的 unity output 长表。

    Returns:
        每个 ``rq2_trial_id × source_frame_id`` 仅保留主变体首次出现的一行。
        图像时刻参考 pose 从完整 output GT 轨迹插值得到；无法插值时误差为 NaN。
    """

    output = logs.output if isinstance(logs, SessionLogs) else logs
    if output.empty:
        return pd.DataFrame(columns=SOURCE_COLUMNS)

    motion = _trial_rows(output)
    required = (
        "label",
        "is_primary",
        "source_frame_id",
        "source_capture_mono_ms",
        "render_mono_ms",
        "has_aligned_raw",
        "aligned_raw_pos",
        "aligned_raw_rot",
    )
    if motion.empty or any(column not in motion.columns for column in required):
        return pd.DataFrame(columns=SOURCE_COLUMNS)

    motion = motion.loc[motion["is_primary"].fillna(False).astype(bool)].copy()
    if motion.empty:
        return pd.DataFrame(columns=SOURCE_COLUMNS)

    frame_id = pd.to_numeric(motion["source_frame_id"], errors="coerce")
    image_ms = pd.to_numeric(motion["source_capture_mono_ms"], errors="coerce")
    has_raw = motion["has_aligned_raw"].fillna(False).astype(bool)
    candidates = motion.loc[
        has_raw
        & frame_id.notna()
        & (frame_id >= 0)
        & image_ms.notna()
        & motion["aligned_raw_pos"].map(is_pose_value)
        & motion["aligned_raw_rot"].map(is_pose_value)
    ].copy()
    if candidates.empty:
        return pd.DataFrame(columns=SOURCE_COLUMNS)

    candidates["source_frame_id"] = pd.to_numeric(
        candidates["source_frame_id"], errors="raise"
    ).astype(int)
    sort_columns = ["rq2_trial_id", "source_frame_id", "render_mono_ms"]
    if "tick_index" in candidates.columns:
        sort_columns.append("tick_index")
    candidates = candidates.sort_values(sort_columns, kind="stable")
    first = candidates.drop_duplicates(
        ["rq2_trial_id", "source_frame_id"], keep="first"
    )
    trajectory = _gt_trajectory(output)

    records: list[dict[str, Any]] = []
    for _, row in first.iterrows():
        image_time = _finite_float(row.get("source_capture_mono_ms"))
        gt_pos, gt_rot = _interpolate_gt(trajectory, image_time)
        raw_pos = np.asarray(row["aligned_raw_pos"], dtype=float)
        raw_rot = np.asarray(row["aligned_raw_rot"], dtype=float)
        translation_error, rotation_error = _pose_error_or_nan(gt_pos, gt_rot, raw_pos, raw_rot)
        records.append(
            {
                "condition": str(row["rq2_condition"]),
                "rq2_trial_id": int(row["rq2_trial_id"]),
                "label": str(row["label"]),
                "source_frame_id": int(row["source_frame_id"]),
                "image_mono_ms": image_time,
                "unity_pose_handle_mono_ms": _finite_float(row.get("unity_pose_handle_mono_ms")),
                "first_render_mono_ms": _finite_float(row.get("render_mono_ms")),
                "policy_output_target_mono_ms": _finite_float(
                    row.get("policy_output_target_mono_ms")
                ),
                "observation_age_ms": _finite_float(row.get("observation_age_ms")),
                "smoothing_delay_ms": _finite_float(row.get("smoothing_delay_ms")),
                "rq2_target_linear_speed_m_s": _finite_float(
                    row.get("rq2_target_linear_speed_m_s")
                ),
                "rq2_target_angular_speed_deg_s": _finite_float(
                    row.get("rq2_target_angular_speed_deg_s")
                ),
                "aligned_raw_pos": raw_pos,
                "aligned_raw_rot": raw_rot,
                "gt_image_pos": gt_pos,
                "gt_image_rot": gt_rot,
                "raw_translation_error_image_m": translation_error,
                "raw_rotation_error_image_deg": rotation_error,
            }
        )
    return pd.DataFrame.from_records(records, columns=SOURCE_COLUMNS)


def compute_motion_delay(source: pd.DataFrame, output: pd.DataFrame) -> pd.DataFrame:
    """计算 raw 有符号滞后残差、模型预测量与参考运动暴露量。

    方向、世界系旋转轴和速度仅由图像时刻之前固定窗口的参考轨迹稳健
    估计，不读取 image→handle/render 区间。``reference_*`` 列只陈述参考
    物体在该区间的实际运动量；不能把它与同一轨迹导出的预测量当作独立
    模型验证。raw 残差保留 capture 偏置，因此 handle 残差不会把感知误差
    与时延暴露量相减消去。
    """

    if source.empty:
        return pd.DataFrame(columns=MOTION_COLUMNS)
    trajectory = _gt_trajectory(output)
    records: list[dict[str, Any]] = []
    for _, row in source.iterrows():
        record = row.to_dict()
        image_ms = _finite_float(row.get("image_mono_ms"))
        handle_ms = _finite_float(row.get("unity_pose_handle_mono_ms"))
        render_ms = _finite_float(row.get("first_render_mono_ms"))
        raw_pos = np.asarray(row["aligned_raw_pos"], dtype=float)
        raw_rot = np.asarray(row["aligned_raw_rot"], dtype=float)
        gt_image_pos, gt_image_rot = _interpolate_gt(trajectory, image_ms)
        gt_handle_pos, gt_handle_rot = _interpolate_gt(trajectory, handle_ms)
        gt_render_pos, gt_render_rot = _interpolate_gt(trajectory, render_ms)

        handle_delay = _nonnegative_difference(handle_ms, image_ms)
        render_delay = _nonnegative_difference(render_ms, image_ms)
        linear_velocity, angular_velocity = _fit_pre_image_motion(trajectory, image_ms)
        linear_speed = _vector_norm_or_nan(linear_velocity)
        angular_speed_rad = _vector_norm_or_nan(angular_velocity)
        angular_speed_deg = (
            float(np.degrees(angular_speed_rad)) if np.isfinite(angular_speed_rad) else np.nan
        )
        direction = _unit_vector_or_none(linear_velocity)
        rotation_axis = _unit_vector_or_none(angular_velocity)

        handle_error = _pose_error_or_nan(gt_handle_pos, gt_handle_rot, raw_pos, raw_rot)
        render_error = _pose_error_or_nan(gt_render_pos, gt_render_rot, raw_pos, raw_rot)
        record.update(
            {
                "handle_delay_ms": handle_delay,
                "render_delay_ms": render_delay,
                "gt_handle_pos": gt_handle_pos,
                "gt_handle_rot": gt_handle_rot,
                "gt_render_pos": gt_render_pos,
                "gt_render_rot": gt_render_rot,
                "raw_translation_error_handle_m": handle_error[0],
                "raw_rotation_error_handle_deg": handle_error[1],
                "raw_translation_error_render_m": render_error[0],
                "raw_rotation_error_render_deg": render_error[1],
                "pre_image_linear_velocity_m_s": linear_velocity,
                "pre_image_rotation_axis_world": rotation_axis,
                "pre_image_linear_speed_m_s": linear_speed,
                "pre_image_angular_speed_deg_s": angular_speed_deg,
                "reference_translation_motion_handle_m": _signed_motion(
                    gt_image_pos, gt_handle_pos, direction
                ),
                "reference_translation_motion_render_m": _signed_motion(
                    gt_image_pos, gt_render_pos, direction
                ),
                "reference_rotation_motion_handle_deg": _signed_rotation_motion(
                    gt_image_rot, gt_handle_rot, rotation_axis
                ),
                "reference_rotation_motion_render_deg": _signed_rotation_motion(
                    gt_image_rot, gt_render_rot, rotation_axis
                ),
                "raw_translation_lag_error_capture_m": _signed_translation_residual(
                    raw_pos, gt_image_pos, direction
                ),
                "raw_translation_lag_error_handle_m": _signed_translation_residual(
                    raw_pos, gt_handle_pos, direction
                ),
                "raw_translation_lag_error_render_m": _signed_translation_residual(
                    raw_pos, gt_render_pos, direction
                ),
                "raw_rotation_lag_error_capture_deg": _signed_rotation_residual(
                    raw_rot, gt_image_rot, rotation_axis
                ),
                "raw_rotation_lag_error_handle_deg": _signed_rotation_residual(
                    raw_rot, gt_handle_rot, rotation_axis
                ),
                "raw_rotation_lag_error_render_deg": _signed_rotation_residual(
                    raw_rot, gt_render_rot, rotation_axis
                ),
                "expected_translation_handle_m": _speed_displacement(
                    linear_speed, handle_delay
                ),
                "expected_translation_render_m": _speed_displacement(
                    linear_speed, render_delay
                ),
                "expected_rotation_handle_deg": _speed_displacement(
                    angular_speed_deg, handle_delay
                ),
                "expected_rotation_render_deg": _speed_displacement(
                    angular_speed_deg, render_delay
                ),
            }
        )
        records.append(record)
    return pd.DataFrame.from_records(records, columns=MOTION_COLUMNS)


def compute_trial_summary(output: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    """按 ``condition × trial × label`` 汇总动态精度、可用率和响应滞后。"""

    motion = _trial_rows(output)
    if motion.empty:
        return pd.DataFrame(columns=TRIAL_COLUMNS)
    trajectory = _gt_trajectory(output)
    rows: list[dict[str, Any]] = []
    for (condition, trial_id, label), group in motion.groupby(
        ["rq2_condition", "rq2_trial_id", "label"], sort=True
    ):
        trial_frames = _deduplicate_render_frames(group)
        has_output = trial_frames.get("has_output_pose", False)
        if not isinstance(has_output, pd.Series):
            has_output = pd.Series(False, index=trial_frames.index)
        output_mask = has_output.fillna(False).astype(bool)
        has_display = trial_frames.get("has_display_pose", has_output)
        if not isinstance(has_display, pd.Series):
            has_display = has_output
        display_mask = has_display.fillna(False).astype(bool)
        display_update_rate, display_hold_fraction = _display_update_summary(
            trial_frames, display_mask
        )
        display_translation: list[float] = []
        display_rotation: list[float] = []
        for _, frame in trial_frames.loc[display_mask].iterrows():
            if not bool(frame.get("gt_pose_valid", frame.get("valid", False))):
                continue
            display_pos = frame.get("display_pos", frame.get("output_pos"))
            display_rot = frame.get("display_rot", frame.get("output_rot"))
            if not all(
                is_pose_value(value)
                for value in (frame.get("gt_pos"), frame.get("gt_rot"), display_pos, display_rot)
            ):
                continue
            translation, rotation = pose_error(
                frame["gt_pos"], frame["gt_rot"], display_pos, display_rot
            )
            display_translation.append(translation)
            display_rotation.append(rotation)

        source_keys = {"condition", "rq2_trial_id"}
        if source_keys.issubset(source.columns):
            trial_source = source[
                (source["condition"] == condition)
                & (source["rq2_trial_id"] == int(trial_id))
            ].copy()
        else:
            trial_source = pd.DataFrame(columns=SOURCE_COLUMNS)
        raw_translation = _finite_values(trial_source.get("raw_translation_error_image_m"))
        raw_rotation = _finite_values(trial_source.get("raw_rotation_error_image_deg"))
        raw_translation_all = pd.to_numeric(
            trial_source.get("raw_translation_error_image_m", pd.Series(dtype=float)),
            errors="coerce",
        )
        raw_rotation_all = pd.to_numeric(
            trial_source.get("raw_rotation_error_image_deg", pd.Series(dtype=float)),
            errors="coerce",
        )
        raw_error_count = int((raw_translation_all.notna() & raw_rotation_all.notna()).sum())
        observation_delay = (
            pd.to_numeric(trial_source.get("unity_pose_handle_mono_ms"), errors="coerce")
            - pd.to_numeric(trial_source.get("image_mono_ms"), errors="coerce")
            if not trial_source.empty
            else pd.Series(dtype=float)
        )
        smoothing_delay = pd.to_numeric(
            trial_frames.get("smoothing_delay_ms", pd.Series(dtype=float)), errors="coerce"
        )
        effective_policy_delay = pd.to_numeric(
            trial_frames.get("render_mono_ms", pd.Series(dtype=float)), errors="coerce"
        ) - pd.to_numeric(
            trial_frames.get("policy_output_target_mono_ms", pd.Series(dtype=float)),
            errors="coerce",
        )

        raw_lag = _estimate_stream_lag(
            trajectory,
            trial_source.get("unity_pose_handle_mono_ms", pd.Series(dtype=float)),
            trial_source.get("aligned_raw_pos", pd.Series(dtype=object)),
            trial_source.get("aligned_raw_rot", pd.Series(dtype=object)),
        )
        display_lag = _estimate_stream_lag(
            trajectory,
            trial_frames.get("render_mono_ms", pd.Series(dtype=float)),
            trial_frames.get(
                "display_pos", trial_frames.get("output_pos", pd.Series(dtype=object))
            ).where(display_mask),
            trial_frames.get(
                "display_rot", trial_frames.get("output_rot", pd.Series(dtype=object))
            ).where(display_mask),
        )
        rows.append(
            {
                "condition": str(condition),
                "rq2_trial_id": int(trial_id),
                "label": str(label),
                "render_frame_count": int(len(trial_frames)),
                "output_frame_count": int(output_mask.sum()),
                "tracking_availability": (
                    float(output_mask.mean()) if len(trial_frames) else np.nan
                ),
                "display_error_sample_count": int(len(display_translation)),
                "display_update_rate_hz": display_update_rate,
                "display_hold_fraction": display_hold_fraction,
                "raw_error_sample_count": raw_error_count,
                "display_translation_median_m": _percentile(display_translation, 50),
                "display_translation_p95_m": _percentile(display_translation, 95),
                "display_rotation_median_deg": _percentile(display_rotation, 50),
                "display_rotation_p95_deg": _percentile(display_rotation, 95),
                "source_frame_count": int(len(trial_source)),
                "raw_translation_median_m": _percentile(raw_translation, 50),
                "raw_translation_p95_m": _percentile(raw_translation, 95),
                "raw_rotation_median_deg": _percentile(raw_rotation, 50),
                "raw_rotation_p95_deg": _percentile(raw_rotation, 95),
                "observation_delay_p50_ms": _percentile(observation_delay, 50),
                "observation_delay_p95_ms": _percentile(observation_delay, 95),
                "effective_policy_delay_p50_ms": _percentile(effective_policy_delay, 50),
                "smoothing_delay_p50_ms": _percentile(smoothing_delay, 50),
                "raw_translation_lag_ms": raw_lag[0],
                "display_translation_lag_ms": display_lag[0],
                "display_minus_raw_translation_lag_ms": _finite_difference(
                    display_lag[0], raw_lag[0]
                ),
                "raw_rotation_lag_ms": raw_lag[1],
                "display_rotation_lag_ms": display_lag[1],
                "display_minus_raw_rotation_lag_ms": _finite_difference(
                    display_lag[1], raw_lag[1]
                ),
                "raw_lag_segment_count": int(raw_lag[2]),
                "display_lag_segment_count": int(display_lag[2]),
            }
        )
    return pd.DataFrame.from_records(rows, columns=TRIAL_COLUMNS)


def compute_model_summary(motion: pd.DataFrame) -> pd.DataFrame:
    """按 trial 计算时延模型一致性，并在场景级做 trial-cluster bootstrap。

    observed 使用 raw 在 handle 时刻沿预图像运动方向/旋转轴的有符号残差，
    predicted 使用 pre-image 拟合速度与 handle delay 的乘积。每个 trial 先
    汇总为一个统计点，场景回归和 bootstrap 均以 trial 为独立单位，避免把
    同一试次内的 source frame 当作伪重复。试次数少于 3 时 CI 明确为 NaN。
    """

    channel_fields = {
        "translation": (
            "raw_translation_lag_error_handle_m",
            "expected_translation_handle_m",
        ),
        "rotation": (
            "raw_rotation_lag_error_handle_deg",
            "expected_rotation_handle_deg",
        ),
    }
    required_keys = {"condition", "rq2_trial_id", "label"}
    if motion.empty or not required_keys.issubset(motion.columns):
        return pd.DataFrame(columns=MODEL_COLUMNS)

    trial_records: list[dict[str, Any]] = []
    for channel, (observed_column, predicted_column) in channel_fields.items():
        if observed_column not in motion.columns or predicted_column not in motion.columns:
            continue
        work = motion[
            ["condition", "rq2_trial_id", "label", observed_column, predicted_column]
        ].copy()
        work["observed"] = pd.to_numeric(work[observed_column], errors="coerce")
        work["predicted"] = pd.to_numeric(work[predicted_column], errors="coerce")
        work = work[np.isfinite(work["observed"]) & np.isfinite(work["predicted"])]
        for (condition, trial_id, label), group in work.groupby(
            ["condition", "rq2_trial_id", "label"], sort=True
        ):
            residual = group["observed"].to_numpy(dtype=float) - group[
                "predicted"
            ].to_numpy(dtype=float)
            trial_records.append(
                {
                    "level": "trial",
                    "condition": str(condition),
                    "rq2_trial_id": int(trial_id),
                    "label": str(label),
                    "channel": channel,
                    "n": int(len(group)),
                    "n_trials": 1,
                    "observed_mean": float(group["observed"].mean()),
                    "predicted_mean": float(group["predicted"].mean()),
                    "bias": float(np.mean(residual)),
                    "mae": float(np.mean(np.abs(residual))),
                    "slope": np.nan,
                    "intercept": np.nan,
                    "slope_ci_low": np.nan,
                    "slope_ci_high": np.nan,
                    "intercept_ci_low": np.nan,
                    "intercept_ci_high": np.nan,
                }
            )

    if not trial_records:
        return pd.DataFrame(columns=MODEL_COLUMNS)
    trial_table = pd.DataFrame.from_records(trial_records, columns=MODEL_COLUMNS)
    scene_records: list[dict[str, Any]] = []
    for (condition, label, channel), group in trial_table.groupby(
        ["condition", "label", "channel"], sort=True
    ):
        predicted = group["predicted_mean"].to_numpy(dtype=float)
        observed = group["observed_mean"].to_numpy(dtype=float)
        slope, intercept = _linear_fit(predicted, observed)
        ci = _cluster_bootstrap_regression(predicted, observed)
        scene_records.append(
            {
                "level": "scene",
                "condition": str(condition),
                "rq2_trial_id": -1,
                "label": str(label),
                "channel": str(channel),
                "n": int(group["n"].sum()),
                "n_trials": int(len(group)),
                "observed_mean": float(np.mean(observed)),
                "predicted_mean": float(np.mean(predicted)),
                "bias": float(group["bias"].mean()),
                "mae": float(group["mae"].mean()),
                "slope": slope,
                "intercept": intercept,
                "slope_ci_low": ci[0],
                "slope_ci_high": ci[1],
                "intercept_ci_low": ci[2],
                "intercept_ci_high": ci[3],
            }
        )
    return pd.concat(
        [trial_table, pd.DataFrame.from_records(scene_records, columns=MODEL_COLUMNS)],
        ignore_index=True,
    )[MODEL_COLUMNS]


def _linear_fit(predicted: np.ndarray, observed: np.ndarray) -> tuple[float, float]:
    """拟合 ``observed = slope * predicted + intercept``；不可辨识时返回 NaN。"""

    if len(predicted) < 2 or float(np.ptp(predicted)) <= 1e-12:
        return np.nan, np.nan
    slope, intercept = np.polyfit(predicted, observed, deg=1)
    return float(slope), float(intercept)


def _cluster_bootstrap_regression(
    predicted: np.ndarray,
    observed: np.ndarray,
) -> tuple[float, float, float, float]:
    """以 trial 统计点为 cluster 做固定种子的回归 95% bootstrap CI。"""

    if len(predicted) < MODEL_MIN_TRIALS_FOR_CI:
        return np.nan, np.nan, np.nan, np.nan
    rng = np.random.default_rng(MODEL_BOOTSTRAP_SEED)
    slopes: list[float] = []
    intercepts: list[float] = []
    for _ in range(MODEL_BOOTSTRAP_ITERATIONS):
        indices = rng.integers(0, len(predicted), size=len(predicted))
        slope, intercept = _linear_fit(predicted[indices], observed[indices])
        if np.isfinite(slope) and np.isfinite(intercept):
            slopes.append(slope)
            intercepts.append(intercept)
    if not slopes:
        return np.nan, np.nan, np.nan, np.nan
    return (
        float(np.percentile(slopes, 2.5)),
        float(np.percentile(slopes, 97.5)),
        float(np.percentile(intercepts, 2.5)),
        float(np.percentile(intercepts, 97.5)),
    )


def run_rq2_analysis(
    session_dir: Path | str,
    *,
    report_dir: Path | str | None = None,
) -> dict[str, pd.DataFrame]:
    """加载 session，保留四张既有 RQ2 表并新增模型一致性表。"""

    session_path = Path(session_dir)
    logs = load_session(session_path)
    source = build_source_observations(logs)
    motion_delay = compute_motion_delay(source, logs.output)
    trial_summary = compute_trial_summary(logs.output, source)
    latency_summary = _build_latency_summary(source, trial_summary)
    model_summary = compute_model_summary(motion_delay)
    tables = {
        "rq2_source_error": source,
        "rq2_motion_delay": motion_delay,
        "rq2_trial_summary": trial_summary,
        "rq2_latency_summary": latency_summary,
        "rq2_model_summary": model_summary,
    }

    output_dir = Path(report_dir) if report_dir is not None else session_path / "report"
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(output_dir / f"{name}.csv", index=False)
    return tables


def _trial_rows(output: pd.DataFrame) -> pd.DataFrame:
    """筛出有效 RQ2 试次行，保留没有输出 pose 的渲染帧。"""

    required = ("rq2_condition", "rq2_trial_id", "label")
    if output.empty or any(column not in output.columns for column in required):
        return output.iloc[0:0].copy()
    trial = pd.to_numeric(output["rq2_trial_id"], errors="coerce")
    mask = (
        output["rq2_condition"].fillna("none").astype(str).isin(RQ2_CONDITIONS)
        & (trial > 0)
    )
    return output.loc[mask].copy()


def _gt_trajectory(output: pd.DataFrame) -> pd.DataFrame:
    """提取按渲染时间去重的参考轨迹，并保留显式有效连续段。"""

    needed = ("render_mono_ms", "gt_pos", "gt_rot")
    columns = [*needed, "_gt_segment"]
    if output.empty or any(column not in output.columns for column in needed):
        return pd.DataFrame(columns=columns)
    valid = output.get("gt_pose_valid", output.get("valid", False))
    if not isinstance(valid, pd.Series):
        valid = pd.Series(False, index=output.index)
    work = output[list(needed)].copy()
    work["_gt_valid"] = (
        valid.fillna(False).astype(bool)
        & output["gt_pos"].map(is_pose_value)
        & output["gt_rot"].map(is_pose_value)
    )
    work["render_mono_ms"] = pd.to_numeric(work["render_mono_ms"], errors="coerce")
    work = work[work["render_mono_ms"].notna()].sort_values("render_mono_ms", kind="stable")
    work = work.drop_duplicates("render_mono_ms", keep="first").reset_index(drop=True)
    if work.empty:
        return pd.DataFrame(columns=columns)

    times = work["render_mono_ms"].to_numpy(dtype=float)
    valid_values = work["_gt_valid"].to_numpy(dtype=bool)
    segment_ids = np.full(len(work), -1, dtype=int)
    segment_id = -1
    previous_valid = False
    gap_threshold = _gap_threshold(times)
    for index, is_valid in enumerate(valid_values):
        if not is_valid:
            previous_valid = False
            continue
        has_time_gap = index > 0 and times[index] - times[index - 1] > gap_threshold
        if not previous_valid or has_time_gap:
            segment_id += 1
        segment_ids[index] = segment_id
        previous_valid = True

    work["_gt_segment"] = segment_ids
    return work.loc[work["_gt_valid"], columns].reset_index(drop=True)


def _interpolate_gt(
    trajectory: pd.DataFrame,
    mono_ms: float,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """在轨迹覆盖范围内插值参考 pose；不做边界外外推。"""

    if trajectory.empty or not np.isfinite(mono_ms):
        return None, None
    times = trajectory["render_mono_ms"].to_numpy(dtype=float)
    if mono_ms < times[0] or mono_ms > times[-1]:
        return None, None
    right = int(np.searchsorted(times, mono_ms, side="left"))
    if right < len(times) and np.isclose(times[right], mono_ms, atol=1e-9):
        return (
            np.asarray(trajectory.iloc[right]["gt_pos"], dtype=float),
            np.asarray(trajectory.iloc[right]["gt_rot"], dtype=float),
        )
    if right == 0 or right >= len(times):
        return None, None
    if _gt_segment_at(trajectory, mono_ms) is None:
        return None, None
    positions = np.vstack(trajectory["gt_pos"].to_numpy())
    rotations = np.vstack(trajectory["gt_rot"].to_numpy())
    pos, rot = slerp_lerp_resample(times, positions, rotations, np.array([mono_ms]))
    return pos[0], rot[0]


def _gt_segment_at(trajectory: pd.DataFrame, mono_ms: float) -> int | None:
    """返回时刻所在的参考有效连续段；空窗或段间时刻返回 ``None``。"""

    if trajectory.empty or "_gt_segment" not in trajectory.columns:
        return None
    times = trajectory["render_mono_ms"].to_numpy(dtype=float)
    right = int(np.searchsorted(times, mono_ms, side="left"))
    if right < len(times) and np.isclose(times[right], mono_ms, atol=1e-9):
        return int(trajectory.iloc[right]["_gt_segment"])
    if right == 0 or right >= len(times):
        return None
    left_segment = int(trajectory.iloc[right - 1]["_gt_segment"])
    right_segment = int(trajectory.iloc[right]["_gt_segment"])
    return left_segment if left_segment == right_segment else None


def _pose_error_or_nan(
    gt_pos: np.ndarray | None,
    gt_rot: np.ndarray | None,
    pose_pos: np.ndarray,
    pose_rot: np.ndarray,
) -> tuple[float, float]:
    """参考 pose 不可得时返回 NaN，否则计算 SE(3) 误差。"""

    if gt_pos is None or gt_rot is None:
        return np.nan, np.nan
    return pose_error(gt_pos, gt_rot, pose_pos, pose_rot)


def _fit_pre_image_motion(
    trajectory: pd.DataFrame,
    image_ms: float,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """用固定 pre-image 窗口稳健估计世界系线速度与角速度向量。

    位置速度对窗口内所有 pose 对使用 Theil--Sen 分量中位斜率，降低单个
    GT 离群点的影响。角速度由相邻四元数的世界系 SO(3) log / dt 构造，
    再取分量中位数。窗口必须完整落在日志覆盖范围内，且不得读取图像时刻
    之后的参考 pose。
    """

    if trajectory.empty or not np.isfinite(image_ms):
        return None, None
    start_ms = image_ms - PRE_IMAGE_FIT_WINDOW_MS
    times = trajectory["render_mono_ms"].to_numpy(dtype=float)
    if start_ms < float(times[0]) or image_ms > float(times[-1]):
        return None, None

    window = trajectory[
        (trajectory["render_mono_ms"] >= start_ms)
        & (trajectory["render_mono_ms"] <= image_ms)
    ].copy()
    window = _with_interpolated_boundary(window, trajectory, start_ms)
    window = _with_interpolated_boundary(window, trajectory, image_ms)
    window = window.sort_values("render_mono_ms", kind="stable").drop_duplicates(
        "render_mono_ms", keep="first"
    )
    if len(window) < PRE_IMAGE_MIN_SAMPLES:
        return None, None

    segments = pd.to_numeric(window.get("_gt_segment"), errors="coerce")
    if segments.isna().any() or segments.nunique() != 1:
        return None, None

    window_times = window["render_mono_ms"].to_numpy(dtype=float)
    if np.any(np.diff(window_times) > _gap_threshold(times)):
        return None, None
    positions = np.vstack(window["gt_pos"].to_numpy())
    rotations = np.vstack(window["gt_rot"].to_numpy())
    linear_velocity = _theil_sen_velocity(window_times, positions)
    angular_velocity = _median_world_angular_velocity(window_times, rotations)
    return linear_velocity, angular_velocity


def _with_interpolated_boundary(
    window: pd.DataFrame,
    trajectory: pd.DataFrame,
    mono_ms: float,
) -> pd.DataFrame:
    """固定窗口缺少精确边界 sample 时插入一个 GT 插值 pose。"""

    if not window.empty and np.any(
        np.isclose(window["render_mono_ms"].to_numpy(dtype=float), mono_ms, atol=1e-9)
    ):
        return window
    position, rotation = _interpolate_gt(trajectory, mono_ms)
    if position is None or rotation is None:
        return window
    segment_id = _gt_segment_at(trajectory, mono_ms)
    if segment_id is None:
        return window
    boundary = pd.DataFrame.from_records(
        [
            {
                "render_mono_ms": mono_ms,
                "gt_pos": position,
                "gt_rot": rotation,
                "_gt_segment": segment_id,
            }
        ]
    )
    return pd.concat([window, boundary], ignore_index=True)


def _theil_sen_velocity(times_ms: np.ndarray, positions: np.ndarray) -> np.ndarray | None:
    """以所有样本对斜率的分量中位数估计稳健世界系线速度。"""

    slopes: list[np.ndarray] = []
    for first in range(len(times_ms) - 1):
        elapsed_s = (times_ms[first + 1 :] - times_ms[first]) / 1000.0
        valid = elapsed_s > 0.0
        if not np.any(valid):
            continue
        delta = positions[first + 1 :] - positions[first]
        slopes.extend(delta[valid] / elapsed_s[valid, None])
    if not slopes:
        return None
    return np.median(np.vstack(slopes), axis=0)


def _median_world_angular_velocity(
    times_ms: np.ndarray,
    rotations: np.ndarray,
) -> np.ndarray | None:
    """由相邻四元数世界系 SO(3) 增量的分量中位数估计角速度。"""

    velocities: list[np.ndarray] = []
    for index in range(1, len(times_ms)):
        elapsed_s = (times_ms[index] - times_ms[index - 1]) / 1000.0
        if elapsed_s <= 0.0:
            continue
        increment = _world_rotation_vector(rotations[index - 1], rotations[index])
        if increment is not None:
            velocities.append(increment / elapsed_s)
    if not velocities:
        return None
    return np.median(np.vstack(velocities), axis=0)


def _signed_motion(
    start: np.ndarray | None,
    end: np.ndarray | None,
    direction: np.ndarray | None,
) -> float:
    """计算两参考时刻间沿局部运动方向的有符号位移。"""

    if start is None or end is None or direction is None:
        return np.nan
    return float(np.dot(end - start, direction))


def _signed_translation_residual(
    raw: np.ndarray,
    reference: np.ndarray | None,
    direction: np.ndarray | None,
) -> float:
    """计算 ``-u^T(raw-reference)``，使沿运动方向落后的 raw 为正。"""

    if reference is None or direction is None:
        return np.nan
    return float(-np.dot(raw - reference, direction))


def _world_rotation_vector(
    start: np.ndarray | None,
    end: np.ndarray | None,
) -> np.ndarray | None:
    """返回 ``Log(R_end R_start^-1)`` 的世界系旋转向量，单位 rad。"""

    if start is None or end is None:
        return None
    start_rotation = Rotation.from_quat(start)
    end_rotation = Rotation.from_quat(end)
    return np.asarray((end_rotation * start_rotation.inv()).as_rotvec(), dtype=float)


def _signed_rotation_motion(
    start: np.ndarray | None,
    end: np.ndarray | None,
    axis: np.ndarray | None,
) -> float:
    """把参考旋转的世界系 SO(3) log 投影到 pre-image 旋转轴。"""

    increment = _world_rotation_vector(start, end)
    if increment is None or axis is None:
        return np.nan
    return float(np.degrees(np.dot(increment, axis)))


def _signed_rotation_residual(
    raw: np.ndarray,
    reference: np.ndarray | None,
    axis: np.ndarray | None,
) -> float:
    """将 ``Log(R_reference R_raw^-1)`` 投影到 pre-image 世界旋转轴。"""

    increment = _world_rotation_vector(raw, reference)
    if increment is None or axis is None:
        return np.nan
    return float(np.degrees(np.dot(increment, axis)))


def _vector_norm_or_nan(vector: np.ndarray | None) -> float:
    """返回向量模长；向量不可得时返回 NaN。"""

    return float(np.linalg.norm(vector)) if vector is not None else np.nan


def _unit_vector_or_none(vector: np.ndarray | None) -> np.ndarray | None:
    """返回单位向量；输入不可得或接近零时返回 None。"""

    if vector is None:
        return None
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-12 else None


def _speed_displacement(speed: float, delay_ms: float) -> float:
    """把 pre-image 拟合速度与毫秒延迟相乘得到模型预测量。"""

    if not np.isfinite(speed) or not np.isfinite(delay_ms):
        return np.nan
    return float(speed * delay_ms / 1000.0)


def _nonnegative_difference(later: float, earlier: float) -> float:
    """计算非负时间差；缺失或时序倒置时返回 NaN。"""

    if not np.isfinite(later) or not np.isfinite(earlier) or later < earlier:
        return np.nan
    return float(later - earlier)


def _deduplicate_render_frames(group: pd.DataFrame) -> pd.DataFrame:
    """按 tick_index（缺失时按 render 时间）保留每个变体的一条渲染记录。"""

    order = [column for column in ("render_mono_ms", "tick_index") if column in group.columns]
    work = group.sort_values(order, kind="stable") if order else group.copy()
    key = "tick_index" if "tick_index" in work.columns else "render_mono_ms"
    return work.drop_duplicates(key, keep="first")


def _display_update_summary(
    frames: pd.DataFrame,
    display_mask: pd.Series,
) -> tuple[float, float]:
    """汇总显示 pose 的实际更新率与相邻帧保持比例。

    只统计原始相邻渲染帧均有有效显示 pose、时间严格递增且未跨越明显
    日志缺口的样本对。更新率以发生 pose 变化的样本对数除以这些样本对
    覆盖的总时长；保持比例以未变化样本对数除以有效样本对数。
    """

    if len(frames) < 2 or "render_mono_ms" not in frames.columns:
        return np.nan, np.nan

    times = pd.to_numeric(frames["render_mono_ms"], errors="coerce").to_numpy(dtype=float)
    finite_times = times[np.isfinite(times)]
    if len(finite_times) < 2:
        return np.nan, np.nan
    gap_limit = _gap_threshold(np.sort(np.unique(finite_times)))

    pair_count = 0
    held_count = 0
    changed_count = 0
    elapsed_ms = 0.0
    for index in range(1, len(frames)):
        if not bool(display_mask.iloc[index - 1]) or not bool(display_mask.iloc[index]):
            continue
        interval_ms = times[index] - times[index - 1]
        if not np.isfinite(interval_ms) or interval_ms <= 0.0 or interval_ms > gap_limit:
            continue

        previous = frames.iloc[index - 1]
        current = frames.iloc[index]
        previous_pos = previous.get("display_pos", previous.get("output_pos"))
        previous_rot = previous.get("display_rot", previous.get("output_rot"))
        current_pos = current.get("display_pos", current.get("output_pos"))
        current_rot = current.get("display_rot", current.get("output_rot"))
        if not all(
            is_pose_value(value)
            for value in (previous_pos, previous_rot, current_pos, current_rot)
        ):
            continue

        translation, rotation = pose_error(
            previous_pos,
            previous_rot,
            current_pos,
            current_rot,
        )
        changed = (
            translation > DISPLAY_HOLD_TRANSLATION_EPS_M
            or rotation > DISPLAY_HOLD_ROTATION_EPS_DEG
        )
        pair_count += 1
        elapsed_ms += float(interval_ms)
        if changed:
            changed_count += 1
        else:
            held_count += 1

    if pair_count == 0 or elapsed_ms <= 0.0:
        return np.nan, np.nan
    return changed_count * 1000.0 / elapsed_ms, held_count / pair_count


def _estimate_stream_lag(
    trajectory: pd.DataFrame,
    times: pd.Series,
    positions: pd.Series,
    rotations: pd.Series,
    *,
    max_lag_ms: float = 500.0,
) -> tuple[float, float, int]:
    """以速度互相关分别估计平移和旋转响应滞后。

    相邻有效样本间隔超过基于中位采样间隔的相对阈值时先切为独立
    连续段，禁止跨 tracking/reacquire 缺口插值。旋转信号由相邻四元数的
    世界系 SO(3) log / dt 构造，不使用相对首帧 rotvec 主值，因此跨 180°
    不会制造分支跳变。返回平移 lag、旋转 lag 和参与估计的连续段数。
    """

    if trajectory.empty or len(times) < 6:
        return np.nan, np.nan, 0
    time_values = pd.to_numeric(times, errors="coerce").to_numpy(dtype=float)
    usable = np.array(
        [
            np.isfinite(time_values[index])
            and is_pose_value(positions.iloc[index])
            and is_pose_value(rotations.iloc[index])
            for index in range(len(time_values))
        ],
        dtype=bool,
    )
    if int(usable.sum()) < 6:
        return np.nan, np.nan, 0
    sample_times = time_values[usable]
    sample_pos = np.vstack(positions.iloc[np.flatnonzero(usable)].to_numpy())
    sample_rot = np.vstack(rotations.iloc[np.flatnonzero(usable)].to_numpy())
    order = np.argsort(sample_times)
    sample_times = sample_times[order]
    sample_pos = sample_pos[order]
    sample_rot = sample_rot[order]
    unique = np.concatenate(([True], np.diff(sample_times) > 1e-9))
    sample_times = sample_times[unique]
    sample_pos = sample_pos[unique]
    sample_rot = sample_rot[unique]
    if len(sample_times) < 6:
        return np.nan, np.nan, 0

    segments = _continuous_segments(sample_times)
    translation_lags: list[float] = []
    rotation_lags: list[float] = []
    for segment in segments:
        translation_lag, rotation_lag = _estimate_lag_segment(
            trajectory,
            sample_times[segment],
            sample_pos[segment],
            sample_rot[segment],
            max_lag_ms=max_lag_ms,
        )
        translation_lags.append(translation_lag)
        rotation_lags.append(rotation_lag)
    return (
        _median_finite_or_nan(translation_lags),
        _median_finite_or_nan(rotation_lags),
        len(segments),
    )


def _continuous_segments(times_ms: np.ndarray) -> list[slice]:
    """按相对采样间隔阈值切分，并只保留至少 6 个 pose 的连续段。"""

    intervals = np.diff(times_ms)
    if not np.any(np.isfinite(intervals) & (intervals > 0.0)):
        return []
    gap_threshold = _gap_threshold(times_ms)
    breaks = np.flatnonzero(intervals > gap_threshold) + 1
    boundaries = np.concatenate(([0], breaks, [len(times_ms)]))
    return [
        slice(int(start), int(end))
        for start, end in zip(boundaries[:-1], boundaries[1:])
        if end - start >= 6
    ]


def _estimate_lag_segment(
    trajectory: pd.DataFrame,
    sample_times: np.ndarray,
    sample_pos: np.ndarray,
    sample_rot: np.ndarray,
    *,
    max_lag_ms: float,
) -> tuple[float, float]:
    """在单个无缺口连续段内重采样并估计平移/旋转 lag。"""

    translation_lags: list[float] = []
    rotation_lags: list[float] = []
    groups = (
        (group for _, group in trajectory.groupby("_gt_segment", sort=False))
        if "_gt_segment" in trajectory.columns
        else (trajectory,)
    )
    for gt_group in groups:
        translation_lag, rotation_lag = _estimate_lag_overlap(
            gt_group,
            sample_times,
            sample_pos,
            sample_rot,
            max_lag_ms=max_lag_ms,
        )
        translation_lags.append(translation_lag)
        rotation_lags.append(rotation_lag)
    return (
        _median_finite_or_nan(translation_lags),
        _median_finite_or_nan(rotation_lags),
    )


def _estimate_lag_overlap(
    trajectory: pd.DataFrame,
    sample_times: np.ndarray,
    sample_pos: np.ndarray,
    sample_rot: np.ndarray,
    *,
    max_lag_ms: float,
) -> tuple[float, float]:
    """在一个参考轨迹连续段与一个输出连续段的交集内估计 lag。"""

    gt_times = trajectory["render_mono_ms"].to_numpy(dtype=float)
    start = max(float(sample_times[0]), float(gt_times[0]))
    end = min(float(sample_times[-1]), float(gt_times[-1]))
    spacing = np.diff(sample_times)
    finite_spacing = spacing[np.isfinite(spacing) & (spacing > 0.0)]
    if end <= start or len(finite_spacing) == 0:
        return np.nan, np.nan
    step = float(np.median(finite_spacing))
    grid = np.arange(start, end + step * 0.5, step)
    if len(grid) < 6:
        return np.nan, np.nan

    gt_pos, gt_rot = slerp_lerp_resample(
        gt_times,
        np.vstack(trajectory["gt_pos"].to_numpy()),
        np.vstack(trajectory["gt_rot"].to_numpy()),
        grid,
    )
    stream_pos, stream_rot = slerp_lerp_resample(
        sample_times, sample_pos, sample_rot, grid
    )
    translation_lag = _vector_velocity_lag(gt_pos, stream_pos, step, max_lag_ms)
    gt_angular_velocity = _world_angular_velocity_series(gt_rot, step)
    stream_angular_velocity = _world_angular_velocity_series(stream_rot, step)
    rotation_lag = _vector_signal_lag(
        gt_angular_velocity,
        stream_angular_velocity,
        step,
        max_lag_ms,
    )
    return translation_lag, rotation_lag


def _vector_velocity_lag(
    reference: np.ndarray,
    estimate: np.ndarray,
    step_ms: float,
    max_lag_ms: float,
) -> float:
    """把位置轨迹转换成世界系速度后估计互相关滞后。"""

    elapsed_s = step_ms / 1000.0
    if elapsed_s <= 0.0 or len(reference) < 3:
        return np.nan
    reference_velocity = np.diff(reference, axis=0) / elapsed_s
    estimate_velocity = np.diff(estimate, axis=0) / elapsed_s
    return _vector_signal_lag(
        reference_velocity,
        estimate_velocity,
        step_ms,
        max_lag_ms,
    )


def _world_angular_velocity_series(rotations: np.ndarray, step_ms: float) -> np.ndarray:
    """由相邻四元数的世界系 SO(3) log / dt 构造连续角速度向量。"""

    elapsed_s = step_ms / 1000.0
    if elapsed_s <= 0.0 or len(rotations) < 2:
        return np.empty((0, 3), dtype=float)
    rotation = Rotation.from_quat(rotations)
    increments = (rotation[1:] * rotation[:-1].inv()).as_rotvec()
    return np.asarray(increments, dtype=float) / elapsed_s


def _vector_signal_lag(
    reference: np.ndarray,
    estimate: np.ndarray,
    step_ms: float,
    max_lag_ms: float,
) -> float:
    """将三维速度信号投影到参考主轴并估计互相关 lag。"""

    if reference.shape != estimate.shape or len(reference) < LAG_MIN_SIGNAL_SAMPLES:
        return np.nan
    centered = reference - np.mean(reference, axis=0, keepdims=True)
    if float(np.linalg.norm(centered)) <= 1e-9:
        return np.nan
    _, _, axes = np.linalg.svd(centered, full_matrices=False)
    axis = axes[0]
    ref_signal = reference @ axis
    est_signal = estimate @ axis
    ref_signal -= np.mean(ref_signal)
    est_signal -= np.mean(est_signal)
    ref_std = float(np.std(ref_signal))
    est_std = float(np.std(est_signal))
    if ref_std <= LAG_MIN_SIGNAL_STD or est_std <= LAG_MIN_SIGNAL_STD:
        return np.nan
    requested_lag_samples = int(np.floor(max_lag_ms / step_ms))
    required_samples = max(
        LAG_MIN_SIGNAL_SAMPLES,
        2 * requested_lag_samples + LAG_MIN_SIGNAL_SAMPLES,
    )
    if len(ref_signal) < required_samples:
        return np.nan
    max_lag_samples = min(requested_lag_samples, len(ref_signal) - 1)
    min_overlap = max(LAG_MIN_SIGNAL_SAMPLES, int(np.ceil(len(ref_signal) * 0.5)))
    candidates: list[tuple[int, float, float]] = []
    for lag in range(-max_lag_samples, max_lag_samples + 1):
        if lag > 0:
            reference_overlap = ref_signal[:-lag]
            estimate_overlap = est_signal[lag:]
        elif lag < 0:
            reference_overlap = ref_signal[-lag:]
            estimate_overlap = est_signal[:lag]
        else:
            reference_overlap = ref_signal
            estimate_overlap = est_signal
        if len(reference_overlap) < min_overlap:
            continue
        correlation, p_value = pearsonr(reference_overlap, estimate_overlap)
        if np.isfinite(correlation) and np.isfinite(p_value):
            candidates.append((lag, float(correlation), float(p_value)))
    if not candidates:
        return np.nan
    best_lag, best_correlation, best_p_value = max(candidates, key=lambda item: item[1])
    if best_correlation < LAG_MIN_PEAK_CORRELATION:
        return np.nan
    if best_p_value * len(candidates) > LAG_SIGNIFICANCE_ALPHA:
        return np.nan
    if max_lag_samples > 0 and abs(best_lag) == max_lag_samples:
        return np.nan
    return float(best_lag * step_ms)


def _gap_threshold(times_ms: np.ndarray) -> float:
    """根据有效样本间隔计算连续轨迹允许的最大缺口。"""

    intervals = np.diff(times_ms)
    positive = intervals[np.isfinite(intervals) & (intervals > 0.0)]
    if len(positive) == 0:
        return LAG_GAP_MIN_MS
    return min(
        max(LAG_GAP_MIN_MS, LAG_GAP_FACTOR * float(np.median(positive))),
        LAG_GAP_ABSOLUTE_CAP_MS,
    )


def _median_finite_or_nan(values: list[float]) -> float:
    """返回有限值中位数；所有连续段均不可辨识时返回 NaN。"""

    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    return float(np.median(finite)) if len(finite) else np.nan


def _build_latency_summary(
    source: pd.DataFrame,
    trial_summary: pd.DataFrame,
) -> pd.DataFrame:
    """按试次汇总观测、首次显示、策略目标与实测 lag。

    ``source`` 只来自主变体，因此观测时延和 raw lag 是同一试次共享的感知
    诊断；输出时复制到各显示变体行，便于同一行读取对应的 display lag。
    """

    if trial_summary.empty:
        return pd.DataFrame(columns=LATENCY_COLUMNS)
    rows: list[dict[str, Any]] = []
    for _, trial in trial_summary.iterrows():
        subset = source[
            (source["condition"] == trial["condition"])
            & (source["rq2_trial_id"] == trial["rq2_trial_id"])
        ]
        observation = pd.to_numeric(subset.get("unity_pose_handle_mono_ms"), errors="coerce") - pd.to_numeric(
            subset.get("image_mono_ms"), errors="coerce"
        )
        first_render = pd.to_numeric(subset.get("first_render_mono_ms"), errors="coerce") - pd.to_numeric(
            subset.get("image_mono_ms"), errors="coerce"
        )
        rows.append(
            {
                "condition": trial["condition"],
                "rq2_trial_id": int(trial["rq2_trial_id"]),
                "label": trial["label"],
                "source_frame_count": int(len(subset)),
                "observation_delay_p50_ms": _percentile(observation, 50),
                "observation_delay_p95_ms": _percentile(observation, 95),
                "image_to_first_render_p50_ms": _percentile(first_render, 50),
                "effective_policy_delay_p50_ms": trial["effective_policy_delay_p50_ms"],
                "smoothing_delay_p50_ms": trial["smoothing_delay_p50_ms"],
                "raw_translation_lag_ms": trial["raw_translation_lag_ms"],
                "display_translation_lag_ms": trial["display_translation_lag_ms"],
                "display_minus_raw_translation_lag_ms": trial[
                    "display_minus_raw_translation_lag_ms"
                ],
                "raw_rotation_lag_ms": trial["raw_rotation_lag_ms"],
                "display_rotation_lag_ms": trial["display_rotation_lag_ms"],
                "display_minus_raw_rotation_lag_ms": trial[
                    "display_minus_raw_rotation_lag_ms"
                ],
            }
        )
    return pd.DataFrame.from_records(rows, columns=LATENCY_COLUMNS)


def _finite_float(value: object) -> float:
    """宽容读取有限浮点数；非法值统一为 NaN。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


def _finite_values(values: object) -> np.ndarray:
    """把序列转换为只含有限值的一维数组。"""

    if values is None:
        return np.asarray([], dtype=float)
    numeric = np.asarray(pd.to_numeric(values, errors="coerce"), dtype=float)
    return numeric[np.isfinite(numeric)]


def _percentile(values: object, percentile: float) -> float:
    """忽略非有限值计算百分位；无有效样本时返回 NaN。"""

    finite = _finite_values(values)
    return float(np.percentile(finite, percentile)) if len(finite) else np.nan


def _finite_difference(later: float, earlier: float) -> float:
    """两个有限值相减；任一不可得时返回 NaN。"""

    if not np.isfinite(later) or not np.isfinite(earlier):
        return np.nan
    return float(later - earlier)
