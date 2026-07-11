"""RQ2 动态追踪分析的纯计算管线与多 session 导出入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from egoanchor.eval.io import SessionLogs, load_session
from egoanchor.eval.metrics import is_pose_value, pose_error

from .contract import (
    ANGULAR_SPEED_BINS_DEG_S,
    DISPLAY_HOLD_ROTATION_EPS_DEG,
    DISPLAY_HOLD_TRANSLATION_EPS_M,
    LINEAR_SPEED_BINS_M_S,
    RQ2_CONDITIONS,
    RQ2Config,
)
from .lag import StreamLag, estimate_stream_lag, runtime_lag_mask
from .model import compute_model_summary
from .paired import compute_paired_summary
from .plot import write_rq2_plots
from .qc import (
    accepted_trial_keys,
    compute_design_audit,
    compute_session_audit,
    compute_trial_audit,
)
from .source import build_source_observations, compute_motion_delay
from .trajectory import (
    active_at_times,
    active_duration_seconds,
    annotate_active_motion,
    build_gt_trajectory,
    reference_valid_mask,
    unique_trial_frames,
)


TRIAL_COLUMNS = [
    "session_id",
    "condition",
    "rq2_trial_id",
    "label",
    "trial_render_frame_count",
    "render_frame_count",
    "active_frame_count",
    "active_duration_s",
    "output_frame_count",
    "tracking_availability",
    "within_tolerance_valid_tracking_rate",
    "within_tolerance_numerator",
    "within_tolerance_denominator",
    "translation_tolerance_m",
    "rotation_tolerance_deg",
    "display_error_sample_count",
    "display_update_rate_hz",
    "display_hold_fraction",
    "raw_error_sample_count",
    "display_translation_median_m",
    "display_translation_p95_m",
    "display_rotation_median_deg",
    "display_rotation_p95_deg",
    "source_frame_count",
    "active_capture_count",
    "raw_source_yield",
    "gt_coverage",
    "raw_translation_median_m",
    "raw_translation_p95_m",
    "raw_rotation_median_deg",
    "raw_rotation_p95_deg",
    "observation_delay_p50_ms",
    "observation_delay_p95_ms",
    "effective_policy_delay_p50_ms",
    "smoothing_delay_p50_ms",
    "raw_translation_lag_ms",
    "raw_translation_lag_peak_correlation",
    "raw_translation_lag_peak_prominence",
    "raw_translation_lag_status",
    "raw_translation_lag_sample_count",
    "display_translation_lag_ms",
    "display_translation_lag_peak_correlation",
    "display_translation_lag_peak_prominence",
    "display_translation_lag_status",
    "display_translation_lag_sample_count",
    "display_minus_raw_translation_lag_ms",
    "raw_rotation_lag_ms",
    "raw_rotation_lag_peak_correlation",
    "raw_rotation_lag_peak_prominence",
    "raw_rotation_lag_status",
    "raw_rotation_lag_sample_count",
    "display_rotation_lag_ms",
    "display_rotation_lag_peak_correlation",
    "display_rotation_lag_peak_prominence",
    "display_rotation_lag_status",
    "display_rotation_lag_sample_count",
    "display_minus_raw_rotation_lag_ms",
    "raw_lag_segment_count",
    "display_lag_segment_count",
    "state_tracking_fraction",
    "state_coasting_fraction",
    "state_frozen_fraction",
    "state_searching_fraction",
    "state_lost_fraction",
    "state_other_fraction",
    "audit_accepted",
    "audit_issues",
]
"""以 active-motion 为主分析窗的 trial × label 汇总字段。"""


LATENCY_COLUMNS = [
    "session_id",
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
"""RQ2 试次级时延分解字段。"""


LAG_DIAGNOSTIC_COLUMNS = [
    "session_id",
    "condition",
    "rq2_trial_id",
    "label",
    "stream",
    "channel",
    "lag_ms",
    "peak_correlation",
    "peak_prominence",
    "status",
    "sample_count",
    "segment_count",
]
"""lag 可辨识状态与峰值质量长表字段。"""


ENVELOPE_COLUMNS = [
    "level",
    "session_id",
    "condition",
    "rq2_trial_id",
    "label",
    "channel",
    "speed_unit",
    "speed_bin_left",
    "speed_bin_right",
    "speed_median",
    "frame_count",
    "n_sessions",
    "n_trials",
    "tracking_availability",
    "within_tolerance_valid_tracking_rate",
    "error_median",
    "error_p95",
    "error_unit",
]
"""按实际速度分箱、等 trial 汇总的经验运行包络字段。"""


def compute_trial_summary(
    output: pd.DataFrame,
    source: pd.DataFrame,
    *,
    capture: pd.DataFrame | None = None,
    session_id: str = "",
    config: RQ2Config | None = None,
) -> pd.DataFrame:
    """按 active-motion 窗汇总动态精度、主终点、连续性与 lag。"""

    settings = config or RQ2Config()
    annotated = annotate_active_motion(output) if "active_motion" not in output else output.copy()
    motion = _trial_rows(annotated)
    if motion.empty:
        return pd.DataFrame(columns=TRIAL_COLUMNS)
    trajectory = build_gt_trajectory(annotated)
    rows: list[dict[str, object]] = []
    for (condition, trial_id, label), group in motion.groupby(
        ["rq2_condition", "rq2_trial_id", "label"], sort=True
    ):
        trial_frames = unique_trial_frames(group)
        active_frames = trial_frames[
            trial_frames["active_motion"].fillna(False).astype(bool)
        ].reset_index(drop=True)
        output_mask = _bool_series(active_frames, "has_output_pose")
        display_mask = _display_mask(active_frames, output_mask)
        display_update_rate, display_hold_fraction = _display_update_summary(
            active_frames, display_mask
        )
        display_translation, display_rotation, tolerance_hits, tolerance_denominator = (
            _display_error_summary(active_frames, display_mask, output_mask, settings)
        )
        trial_source = _trial_source(
            source,
            session_id,
            str(condition),
            int(trial_id),
        )
        active_source = trial_source[
            trial_source.get("active_motion", False).fillna(False).astype(bool)
        ] if not trial_source.empty and "active_motion" in trial_source else trial_source.iloc[0:0]
        raw_translation = _finite_values(
            active_source.get("raw_translation_error_image_m")
        )
        raw_rotation = _finite_values(active_source.get("raw_rotation_error_image_deg"))
        raw_error_count = int(
            (
                pd.to_numeric(
                    active_source.get(
                        "raw_translation_error_image_m", pd.Series(dtype=float)
                    ),
                    errors="coerce",
                ).notna()
                & pd.to_numeric(
                    active_source.get(
                        "raw_rotation_error_image_deg", pd.Series(dtype=float)
                    ),
                    errors="coerce",
                ).notna()
            ).sum()
        )
        observation_delay = (
            pd.to_numeric(active_source.get("unity_pose_handle_mono_ms"), errors="coerce")
            - pd.to_numeric(active_source.get("image_mono_ms"), errors="coerce")
            if not active_source.empty
            else pd.Series(dtype=float)
        )
        smoothing_delay = pd.to_numeric(
            active_frames.get("smoothing_delay_ms", pd.Series(dtype=float)),
            errors="coerce",
        )
        effective_policy_delay = pd.to_numeric(
            active_frames.get("render_mono_ms", pd.Series(dtype=float)), errors="coerce"
        ) - pd.to_numeric(
            active_frames.get(
                "policy_output_target_mono_ms", pd.Series(dtype=float)
            ),
            errors="coerce",
        )
        raw_lag = estimate_stream_lag(
            trajectory,
            trial_source.get("unity_pose_handle_mono_ms", pd.Series(dtype=float)),
            trial_source.get("aligned_raw_pos", pd.Series(dtype=object)),
            trial_source.get("aligned_raw_rot", pd.Series(dtype=object)),
            max_lag_ms=settings.max_lag_ms,
        )
        full_display_mask = _display_mask(
            trial_frames, _bool_series(trial_frames, "has_output_pose")
        )
        lag_mask = runtime_lag_mask(trial_frames, full_display_mask)
        display_lag = estimate_stream_lag(
            trajectory,
            trial_frames.get("render_mono_ms", pd.Series(dtype=float)),
            trial_frames.get(
                "display_pos", trial_frames.get("output_pos", pd.Series(dtype=object))
            ),
            trial_frames.get(
                "display_rot", trial_frames.get("output_rot", pd.Series(dtype=object))
            ),
            valid_mask=lag_mask,
            max_lag_ms=settings.max_lag_ms,
        )
        gt_valid = reference_valid_mask(trial_frames)
        active_capture_count = _count_active_capture(
            capture,
            annotated,
            str(condition),
            int(trial_id),
        )
        source_count = int(active_source["source_frame_id"].nunique()) if not active_source.empty else 0
        state_fraction = _state_fractions(active_frames)
        row = {
            "session_id": str(session_id),
            "condition": str(condition),
            "rq2_trial_id": int(trial_id),
            "label": str(label),
            "trial_render_frame_count": int(len(trial_frames)),
            "render_frame_count": int(len(active_frames)),
            "active_frame_count": int(len(active_frames)),
            "active_duration_s": active_duration_seconds(trial_frames),
            "output_frame_count": int(output_mask.sum()),
            "tracking_availability": (
                float(output_mask.mean()) if len(active_frames) else np.nan
            ),
            "within_tolerance_valid_tracking_rate": (
                float(tolerance_hits / tolerance_denominator)
                if tolerance_denominator > 0
                else np.nan
            ),
            "within_tolerance_numerator": int(tolerance_hits),
            "within_tolerance_denominator": int(tolerance_denominator),
            "translation_tolerance_m": settings.translation_tolerance_m,
            "rotation_tolerance_deg": settings.rotation_tolerance_deg,
            "display_error_sample_count": int(len(display_translation)),
            "display_update_rate_hz": display_update_rate,
            "display_hold_fraction": display_hold_fraction,
            "raw_error_sample_count": raw_error_count,
            "display_translation_median_m": _percentile(display_translation, 50),
            "display_translation_p95_m": _percentile(display_translation, 95),
            "display_rotation_median_deg": _percentile(display_rotation, 50),
            "display_rotation_p95_deg": _percentile(display_rotation, 95),
            "source_frame_count": source_count,
            "active_capture_count": int(active_capture_count),
            "raw_source_yield": (
                float(source_count / active_capture_count)
                if active_capture_count > 0
                else np.nan
            ),
            "gt_coverage": float(gt_valid.mean()) if len(gt_valid) else np.nan,
            "raw_translation_median_m": _percentile(raw_translation, 50),
            "raw_translation_p95_m": _percentile(raw_translation, 95),
            "raw_rotation_median_deg": _percentile(raw_rotation, 50),
            "raw_rotation_p95_deg": _percentile(raw_rotation, 95),
            "observation_delay_p50_ms": _percentile(observation_delay, 50),
            "observation_delay_p95_ms": _percentile(observation_delay, 95),
            "effective_policy_delay_p50_ms": _percentile(
                effective_policy_delay, 50
            ),
            "smoothing_delay_p50_ms": _percentile(smoothing_delay, 50),
            **_lag_fields("raw", raw_lag),
            **_lag_fields("display", display_lag),
            "display_minus_raw_translation_lag_ms": _finite_difference(
                display_lag.translation.lag_ms, raw_lag.translation.lag_ms
            ),
            "display_minus_raw_rotation_lag_ms": _finite_difference(
                display_lag.rotation.lag_ms, raw_lag.rotation.lag_ms
            ),
            "raw_lag_segment_count": int(raw_lag.segment_count),
            "display_lag_segment_count": int(display_lag.segment_count),
            **state_fraction,
            "audit_accepted": False,
            "audit_issues": "not_audited",
        }
        rows.append(row)
    return pd.DataFrame.from_records(rows, columns=TRIAL_COLUMNS)


def compute_operating_envelope(
    output: pd.DataFrame,
    *,
    session_id: str,
    accepted_keys: set[tuple[str, int]],
    config: RQ2Config,
) -> pd.DataFrame:
    """按实测速度分箱，构造不外推单一边界的经验运行包络。"""

    if output.empty or not accepted_keys:
        return pd.DataFrame(columns=ENVELOPE_COLUMNS)
    trial_records: list[dict[str, object]] = []
    motion = _trial_rows(output)
    for (condition, trial_id, label), group in motion.groupby(
        ["rq2_condition", "rq2_trial_id", "label"], sort=True
    ):
        if (str(condition), int(trial_id)) not in accepted_keys:
            continue
        frames = unique_trial_frames(group)
        frames = frames[
            frames["active_motion"].fillna(False).astype(bool)
            & reference_valid_mask(frames)
        ].copy()
        if frames.empty:
            continue
        for definition in _envelope_definitions():
            channel, speed_column, bins, speed_scale, speed_unit, error_unit = definition
            if (str(condition) == "rotation") != (channel == "rotation"):
                continue
            speed = pd.to_numeric(frames.get(speed_column), errors="coerce") * speed_scale
            bin_ids = pd.cut(speed, bins=bins, right=False, labels=False)
            for bin_id, bin_group in frames.groupby(bin_ids, dropna=True, sort=True):
                index = int(bin_id)
                errors, available, within = _channel_envelope_values(
                    bin_group, channel, config
                )
                trial_records.append(
                    {
                        "level": "trial",
                        "session_id": str(session_id),
                        "condition": str(condition),
                        "rq2_trial_id": int(trial_id),
                        "label": str(label),
                        "channel": channel,
                        "speed_unit": speed_unit,
                        "speed_bin_left": float(bins[index]),
                        "speed_bin_right": float(bins[index + 1]),
                        "speed_median": _percentile(
                            speed.loc[bin_group.index], 50
                        ),
                        "frame_count": int(len(bin_group)),
                        "n_sessions": 1,
                        "n_trials": 1,
                        "tracking_availability": available,
                        "within_tolerance_valid_tracking_rate": within,
                        "error_median": _percentile(errors, 50),
                        "error_p95": _percentile(errors, 95),
                        "error_unit": error_unit,
                    }
                )
    trial_table = pd.DataFrame.from_records(trial_records, columns=ENVELOPE_COLUMNS)
    if trial_table.empty:
        return trial_table
    aggregate_records: list[dict[str, object]] = []
    keys = [
        "condition",
        "label",
        "channel",
        "speed_unit",
        "speed_bin_left",
        "speed_bin_right",
        "error_unit",
    ]
    for group_keys, group in trial_table.groupby(keys, sort=True):
        aggregate_records.append(
            {
                "level": "aggregate",
                "session_id": "all",
                "condition": group_keys[0],
                "rq2_trial_id": -1,
                "label": group_keys[1],
                "channel": group_keys[2],
                "speed_unit": group_keys[3],
                "speed_bin_left": group_keys[4],
                "speed_bin_right": group_keys[5],
                "speed_median": float(group["speed_median"].mean()),
                "frame_count": int(group["frame_count"].sum()),
                "n_sessions": int(group["session_id"].nunique()),
                "n_trials": int(len(group)),
                "tracking_availability": float(
                    group["tracking_availability"].mean()
                ),
                "within_tolerance_valid_tracking_rate": float(
                    group["within_tolerance_valid_tracking_rate"].mean()
                ),
                "error_median": float(group["error_median"].mean()),
                "error_p95": float(group["error_p95"].mean()),
                "error_unit": group_keys[6],
            }
        )
    return pd.concat(
        [trial_table, pd.DataFrame.from_records(aggregate_records, columns=ENVELOPE_COLUMNS)],
        ignore_index=True,
    )[ENVELOPE_COLUMNS]


def run_rq2_analysis(
    session_dirs: Path | str | Sequence[Path | str],
    *,
    report_dir: Path | str | None = None,
    config: RQ2Config | None = None,
) -> dict[str, pd.DataFrame]:
    """分析一个或多个 session，写出表格与精简论文图。"""

    settings = config or RQ2Config()
    paths = _normalize_session_dirs(session_dirs)
    session_results: list[dict[str, pd.DataFrame]] = []
    session_ids: set[str] = set()
    for path in paths:
        logs = load_session(path)
        session_id = str(logs.manifest.get("session_id", path.name))
        if session_id in session_ids:
            raise ValueError(f"重复 session_id：{session_id}")
        session_ids.add(session_id)
        session_results.append(_compute_session_tables(logs, session_id, settings))
    combined = _combine_session_tables(session_results)
    combined["rq2_design_audit"] = compute_design_audit(
        combined["rq2_trial_audit"],
        sorted(session_ids),
        settings,
    )
    combined["rq2_operating_envelope"] = _reaggregate_envelope(
        combined["rq2_operating_envelope"]
    )
    accepted_motion = _filter_accepted_motion(
        combined["rq2_motion_delay"], combined["rq2_trial_audit"]
    )
    accepted_trials = _filter_accepted_trials(
        combined["rq2_trial_summary"], combined["rq2_trial_audit"]
    )
    combined["rq2_model_summary"] = compute_model_summary(
        accepted_motion,
        bootstrap_iterations=settings.bootstrap_iterations,
    )
    combined["rq2_paired_summary"] = compute_paired_summary(
        accepted_trials,
        bootstrap_iterations=settings.bootstrap_iterations,
    )
    output_dir = _report_dir(paths, report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, table in combined.items():
        table.to_csv(output_dir / f"{name}.csv", index=False)
    write_rq2_plots(combined, output_dir)
    return combined


def _compute_session_tables(
    logs: SessionLogs,
    session_id: str,
    config: RQ2Config,
) -> dict[str, pd.DataFrame]:
    """计算单个 session 的全部无副作用 RQ2 表。"""

    output = annotate_active_motion(logs.output)
    output["session_id"] = session_id
    source = build_source_observations(output, session_id=session_id)
    motion = compute_motion_delay(source, output)
    trial = compute_trial_summary(
        output,
        source,
        capture=logs.capture,
        session_id=session_id,
        config=config,
    )
    audit = compute_trial_audit(
        output,
        source,
        logs.capture,
        session_id=session_id,
        config=config,
    )
    session_audit = compute_session_audit(
        output,
        logs.manifest,
        session_id=session_id,
    )
    if not bool(session_audit.iloc[0]["accepted"]) and not audit.empty:
        session_issues = str(session_audit.iloc[0]["issues"])
        audit["accepted"] = False
        audit["issues"] = audit["issues"].map(
            lambda value: ";".join(
                part for part in (str(value), session_issues) if part
            )
        )
    trial = _attach_audit(trial, audit)
    accepted = accepted_trial_keys(audit)
    envelope = compute_operating_envelope(
        output,
        session_id=session_id,
        accepted_keys=accepted,
        config=config,
    )
    return {
        "rq2_source_error": source,
        "rq2_motion_delay": motion,
        "rq2_trial_summary": trial,
        "rq2_latency_summary": _build_latency_summary(source, trial),
        "rq2_model_summary": pd.DataFrame(),
        "rq2_trial_audit": audit,
        "rq2_session_audit": session_audit,
        "rq2_design_audit": pd.DataFrame(),
        "rq2_paired_summary": pd.DataFrame(),
        "rq2_operating_envelope": envelope,
        "rq2_lag_diagnostics": _build_lag_diagnostics(trial),
    }


def _trial_rows(output: pd.DataFrame) -> pd.DataFrame:
    """筛出合法 RQ2 试次行，保留无输出帧。"""

    required = ("rq2_condition", "rq2_trial_id", "label")
    if output.empty or any(column not in output.columns for column in required):
        return output.iloc[0:0].copy()
    trial = pd.to_numeric(output["rq2_trial_id"], errors="coerce")
    return output.loc[
        output["rq2_condition"].fillna("none").astype(str).isin(RQ2_CONDITIONS)
        & (trial > 0)
    ].copy()


def _display_error_summary(
    frames: pd.DataFrame,
    display_mask: pd.Series,
    output_mask: pd.Series,
    config: RQ2Config,
) -> tuple[list[float], list[float], int, int]:
    """汇总 display 误差和 within-tolerance 有效追踪主终点。"""

    translation: list[float] = []
    rotation: list[float] = []
    hits = 0
    denominator = 0
    gt_valid = reference_valid_mask(frames)
    for position, (_, frame) in enumerate(frames.iterrows()):
        if not bool(gt_valid.iloc[position]):
            continue
        denominator += 1
        display_pos = frame.get("display_pos", frame.get("output_pos"))
        display_rot = frame.get("display_rot", frame.get("output_rot"))
        if not bool(display_mask.iloc[position]) or not all(
            is_pose_value(value)
            for value in (frame.get("gt_pos"), frame.get("gt_rot"), display_pos, display_rot)
        ):
            continue
        current_translation, current_rotation = pose_error(
            frame["gt_pos"], frame["gt_rot"], display_pos, display_rot
        )
        translation.append(current_translation)
        rotation.append(current_rotation)
        if (
            bool(output_mask.iloc[position])
            and current_translation <= config.translation_tolerance_m
            and current_rotation <= config.rotation_tolerance_deg
        ):
            hits += 1
    return translation, rotation, hits, denominator


def _display_update_summary(
    frames: pd.DataFrame,
    display_mask: pd.Series,
) -> tuple[float, float]:
    """计算 active-motion 显示更新率与保持比例。"""

    if len(frames) < 2 or "render_mono_ms" not in frames.columns:
        return np.nan, np.nan
    times = pd.to_numeric(frames["render_mono_ms"], errors="coerce").to_numpy(dtype=float)
    pair_count = held_count = changed_count = 0
    elapsed_ms = 0.0
    for index in range(1, len(frames)):
        if not bool(display_mask.iloc[index - 1]) or not bool(display_mask.iloc[index]):
            continue
        interval_ms = times[index] - times[index - 1]
        if not np.isfinite(interval_ms) or interval_ms <= 0.0:
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
            previous_pos, previous_rot, current_pos, current_rot
        )
        changed = (
            translation > DISPLAY_HOLD_TRANSLATION_EPS_M
            or rotation > DISPLAY_HOLD_ROTATION_EPS_DEG
        )
        pair_count += 1
        elapsed_ms += float(interval_ms)
        changed_count += int(changed)
        held_count += int(not changed)
    if pair_count == 0 or elapsed_ms <= 0.0:
        return np.nan, np.nan
    return changed_count * 1000.0 / elapsed_ms, held_count / pair_count


def _state_fractions(frames: pd.DataFrame) -> dict[str, float]:
    """汇总 active-motion 生命周期状态占比。"""

    result = {
        "state_tracking_fraction": np.nan,
        "state_coasting_fraction": np.nan,
        "state_frozen_fraction": np.nan,
        "state_searching_fraction": np.nan,
        "state_lost_fraction": np.nan,
        "state_other_fraction": np.nan,
    }
    if frames.empty or "anchor_state" not in frames.columns:
        return result
    states = frames["anchor_state"].fillna("").astype(str).str.lower()
    categories = {
        "tracking": states.str.contains("track"),
        "coasting": states.str.contains("coast"),
        "frozen": states.str.contains("frozen|lock"),
        "searching": states.str.contains("search|reacquir"),
        "lost": states.str.contains("lost"),
    }
    claimed = pd.Series(False, index=states.index)
    for name, mask in categories.items():
        result[f"state_{name}_fraction"] = float(mask.mean())
        claimed |= mask
    result["state_other_fraction"] = float((~claimed).mean())
    return result


def _lag_fields(prefix: str, lag: StreamLag) -> dict[str, object]:
    """把 StreamLag 展平到 trial summary 字段。"""

    return {
        f"{prefix}_translation_lag_ms": lag.translation.lag_ms,
        f"{prefix}_translation_lag_peak_correlation": lag.translation.peak_correlation,
        f"{prefix}_translation_lag_peak_prominence": lag.translation.peak_prominence,
        f"{prefix}_translation_lag_status": lag.translation.status,
        f"{prefix}_translation_lag_sample_count": lag.translation.sample_count,
        f"{prefix}_rotation_lag_ms": lag.rotation.lag_ms,
        f"{prefix}_rotation_lag_peak_correlation": lag.rotation.peak_correlation,
        f"{prefix}_rotation_lag_peak_prominence": lag.rotation.peak_prominence,
        f"{prefix}_rotation_lag_status": lag.rotation.status,
        f"{prefix}_rotation_lag_sample_count": lag.rotation.sample_count,
    }


def _build_lag_diagnostics(trial: pd.DataFrame) -> pd.DataFrame:
    """从 trial summary 构造 lag 质量长表。"""

    rows: list[dict[str, object]] = []
    for _, current in trial.iterrows():
        for stream in ("raw", "display"):
            for channel in ("translation", "rotation"):
                rows.append(
                    {
                        "session_id": current["session_id"],
                        "condition": current["condition"],
                        "rq2_trial_id": int(current["rq2_trial_id"]),
                        "label": current["label"],
                        "stream": stream,
                        "channel": channel,
                        "lag_ms": current[f"{stream}_{channel}_lag_ms"],
                        "peak_correlation": current[
                            f"{stream}_{channel}_lag_peak_correlation"
                        ],
                        "peak_prominence": current[
                            f"{stream}_{channel}_lag_peak_prominence"
                        ],
                        "status": current[f"{stream}_{channel}_lag_status"],
                        "sample_count": int(
                            current[f"{stream}_{channel}_lag_sample_count"]
                        ),
                        "segment_count": int(current[f"{stream}_lag_segment_count"]),
                    }
                )
    return pd.DataFrame.from_records(rows, columns=LAG_DIAGNOSTIC_COLUMNS)


def _build_latency_summary(
    source: pd.DataFrame,
    trial_summary: pd.DataFrame,
) -> pd.DataFrame:
    """按试次汇总观测、首次显示、策略目标与实测 lag。"""

    if trial_summary.empty:
        return pd.DataFrame(columns=LATENCY_COLUMNS)
    rows: list[dict[str, object]] = []
    for _, trial in trial_summary.iterrows():
        subset = _trial_source(
            source,
            str(trial["session_id"]),
            str(trial["condition"]),
            int(trial["rq2_trial_id"]),
        )
        subset = subset[
            subset.get("active_motion", False).fillna(False).astype(bool)
        ] if not subset.empty and "active_motion" in subset else subset.iloc[0:0]
        observation = pd.to_numeric(
            subset.get("unity_pose_handle_mono_ms"), errors="coerce"
        ) - pd.to_numeric(subset.get("image_mono_ms"), errors="coerce")
        first_render = pd.to_numeric(
            subset.get("first_render_mono_ms"), errors="coerce"
        ) - pd.to_numeric(subset.get("image_mono_ms"), errors="coerce")
        rows.append(
            {
                "session_id": trial["session_id"],
                "condition": trial["condition"],
                "rq2_trial_id": int(trial["rq2_trial_id"]),
                "label": trial["label"],
                "source_frame_count": int(len(subset)),
                "observation_delay_p50_ms": _percentile(observation, 50),
                "observation_delay_p95_ms": _percentile(observation, 95),
                "image_to_first_render_p50_ms": _percentile(first_render, 50),
                "effective_policy_delay_p50_ms": trial[
                    "effective_policy_delay_p50_ms"
                ],
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


def _envelope_definitions() -> Iterable[
    tuple[str, str, tuple[float, ...], float, str, str]
]:
    """返回经验运行包络的通道定义。"""

    return (
        (
            "translation",
            "gt_linear_speed_smooth_m_s",
            LINEAR_SPEED_BINS_M_S,
            1.0,
            "m/s",
            "m",
        ),
        (
            "rotation",
            "gt_angular_speed_smooth_rad_s",
            ANGULAR_SPEED_BINS_DEG_S,
            180.0 / np.pi,
            "deg/s",
            "deg",
        ),
    )


def _channel_envelope_values(
    frames: pd.DataFrame,
    channel: str,
    config: RQ2Config,
) -> tuple[list[float], float, float]:
    """计算单个 trial 速度箱的误差和有效率。"""

    errors: list[float] = []
    available_count = 0
    within_count = 0
    for _, frame in frames.iterrows():
        has_output = bool(frame.get("has_output_pose", False))
        available_count += int(has_output)
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
        error = translation if channel == "translation" else rotation
        threshold = (
            config.translation_tolerance_m
            if channel == "translation"
            else config.rotation_tolerance_deg
        )
        errors.append(error)
        within_count += int(has_output and error <= threshold)
    denominator = len(frames)
    return (
        errors,
        float(available_count / denominator) if denominator else np.nan,
        float(within_count / denominator) if denominator else np.nan,
    )


def _attach_audit(trial: pd.DataFrame, audit: pd.DataFrame) -> pd.DataFrame:
    """把 trial 级审计结论附加到每个显示变体行。"""

    if trial.empty or audit.empty:
        return trial
    keys = ["session_id", "condition", "rq2_trial_id"]
    audit_view = audit[keys + ["accepted", "issues", "raw_source_yield"]].rename(
        columns={"accepted": "_accepted", "issues": "_issues", "raw_source_yield": "_audit_yield"}
    )
    merged = trial.merge(audit_view, on=keys, how="left", validate="many_to_one")
    merged["audit_accepted"] = merged.pop("_accepted").fillna(False).astype(bool)
    merged["audit_issues"] = merged.pop("_issues").fillna("missing_audit").astype(str)
    audit_yield = merged.pop("_audit_yield")
    merged["raw_source_yield"] = audit_yield.where(
        np.isfinite(pd.to_numeric(audit_yield, errors="coerce")),
        merged["raw_source_yield"],
    )
    return merged[TRIAL_COLUMNS]


def _filter_accepted_motion(motion: pd.DataFrame, audit: pd.DataFrame) -> pd.DataFrame:
    """仅保留通过 trial audit 的时延关联样本。"""

    if motion.empty or audit.empty:
        return motion.iloc[0:0].copy()
    keys = audit[audit["accepted"].fillna(False).astype(bool)][
        ["session_id", "condition", "rq2_trial_id"]
    ]
    return motion.merge(keys, on=["session_id", "condition", "rq2_trial_id"], how="inner")


def _filter_accepted_trials(trial: pd.DataFrame, audit: pd.DataFrame) -> pd.DataFrame:
    """仅保留通过 trial audit 的配对汇总行。"""

    if trial.empty or audit.empty:
        return trial.iloc[0:0].copy()
    return trial[trial["audit_accepted"].fillna(False).astype(bool)].copy()


def _combine_session_tables(
    results: list[dict[str, pd.DataFrame]],
) -> dict[str, pd.DataFrame]:
    """按表名合并多个 session 的无副作用结果。"""

    names = [
        "rq2_source_error",
        "rq2_motion_delay",
        "rq2_trial_summary",
        "rq2_latency_summary",
        "rq2_model_summary",
        "rq2_trial_audit",
        "rq2_session_audit",
        "rq2_design_audit",
        "rq2_paired_summary",
        "rq2_operating_envelope",
        "rq2_lag_diagnostics",
    ]
    combined: dict[str, pd.DataFrame] = {}
    for name in names:
        all_frames = [result[name] for result in results]
        populated = [frame for frame in all_frames if not frame.empty]
        combined[name] = (
            pd.concat(populated, ignore_index=True)
            if populated
            else all_frames[0].copy()
        )
    return combined


def _reaggregate_envelope(envelope: pd.DataFrame) -> pd.DataFrame:
    """跨 session 重新按 trial 等权汇总经验运行包络。"""

    if envelope.empty:
        return pd.DataFrame(columns=ENVELOPE_COLUMNS)
    trial_table = envelope[envelope["level"].eq("trial")].copy()
    if trial_table.empty:
        return pd.DataFrame(columns=ENVELOPE_COLUMNS)
    aggregate_records: list[dict[str, object]] = []
    keys = [
        "condition",
        "label",
        "channel",
        "speed_unit",
        "speed_bin_left",
        "speed_bin_right",
        "error_unit",
    ]
    for group_keys, group in trial_table.groupby(keys, sort=True):
        aggregate_records.append(
            {
                "level": "aggregate",
                "session_id": "all",
                "condition": group_keys[0],
                "rq2_trial_id": -1,
                "label": group_keys[1],
                "channel": group_keys[2],
                "speed_unit": group_keys[3],
                "speed_bin_left": group_keys[4],
                "speed_bin_right": group_keys[5],
                "speed_median": float(group["speed_median"].mean()),
                "frame_count": int(group["frame_count"].sum()),
                "n_sessions": int(group["session_id"].nunique()),
                "n_trials": int(len(group)),
                "tracking_availability": float(group["tracking_availability"].mean()),
                "within_tolerance_valid_tracking_rate": float(
                    group["within_tolerance_valid_tracking_rate"].mean()
                ),
                "error_median": float(group["error_median"].mean()),
                "error_p95": float(group["error_p95"].mean()),
                "error_unit": group_keys[6],
            }
        )
    return pd.concat(
        [trial_table, pd.DataFrame.from_records(aggregate_records, columns=ENVELOPE_COLUMNS)],
        ignore_index=True,
    )[ENVELOPE_COLUMNS]


def _trial_source(
    source: pd.DataFrame,
    session_id: str,
    condition: str,
    trial_id: int,
) -> pd.DataFrame:
    """筛出单个 session × trial 的共享 raw source。"""

    if source.empty or not {"condition", "rq2_trial_id"}.issubset(source.columns):
        return source.iloc[0:0].copy()
    mask = (
        source["condition"].astype(str).eq(condition)
        & pd.to_numeric(source["rq2_trial_id"], errors="coerce").eq(trial_id)
    )
    if "session_id" in source.columns:
        mask &= source["session_id"].astype(str).eq(session_id)
    return source[mask].copy()


def _count_active_capture(
    capture: pd.DataFrame | None,
    output: pd.DataFrame,
    condition: str,
    trial_id: int,
) -> int:
    """统计 active-motion 时间内成功发布的 capture frame。"""

    if capture is None or capture.empty or "capture_mono_ms" not in capture.columns:
        return 0
    times = pd.to_numeric(capture["capture_mono_ms"], errors="coerce").to_numpy(dtype=float)
    active = active_at_times(output, condition, trial_id, times)
    published = _bool_series(capture, "publish_succeeded", default=True)
    return int(np.sum(active & np.isfinite(times) & published.to_numpy(dtype=bool)))


def _bool_series(
    frame: pd.DataFrame,
    column: str,
    *,
    fallback: str | None = None,
    default: bool = False,
) -> pd.Series:
    """读取与 DataFrame 同索引的 bool 列。"""

    if column in frame.columns:
        return frame[column].fillna(default).astype(bool).reset_index(drop=True)
    if fallback is not None and fallback in frame.columns:
        return frame[fallback].fillna(default).astype(bool).reset_index(drop=True)
    return pd.Series(default, index=range(len(frame)), dtype=bool)


def _display_mask(frames: pd.DataFrame, output_mask: pd.Series) -> pd.Series:
    """读取实际显示 pose 有效性，缺字段时回退 runtime 输出。"""

    if "has_display_pose" in frames.columns:
        return frames["has_display_pose"].fillna(False).astype(bool).reset_index(drop=True)
    return output_mask.reset_index(drop=True)


def _normalize_session_dirs(
    session_dirs: Path | str | Sequence[Path | str],
) -> list[Path]:
    """把单目录或目录序列归一化为非空 Path 列表。"""

    if isinstance(session_dirs, (str, Path)):
        paths = [Path(session_dirs)]
    else:
        paths = [Path(path) for path in session_dirs]
    if not paths:
        raise ValueError("至少需要一个 --session-dir。")
    return paths


def _report_dir(paths: list[Path], explicit: Path | str | None) -> Path:
    """解析单 session 或多 session 默认报告目录。"""

    if explicit is not None:
        return Path(explicit)
    return paths[0] / ("report" if len(paths) == 1 else "rq2_multi_report")


def _finite_values(values: object) -> np.ndarray:
    """把序列转换为只含有限值的一维数组。"""

    if values is None:
        return np.asarray([], dtype=float)
    numeric = np.asarray(pd.to_numeric(values, errors="coerce"), dtype=float)
    return numeric[np.isfinite(numeric)]


def _percentile(values: object, percentile: float) -> float:
    """忽略非有限值计算百分位。"""

    finite = _finite_values(values)
    return float(np.percentile(finite, percentile)) if len(finite) else np.nan


def _finite_difference(later: float, earlier: float) -> float:
    """两个有限值相减。"""

    if not np.isfinite(later) or not np.isfinite(earlier):
        return np.nan
    return float(later - earlier)


__all__ = [
    "ENVELOPE_COLUMNS",
    "LAG_DIAGNOSTIC_COLUMNS",
    "LATENCY_COLUMNS",
    "TRIAL_COLUMNS",
    "compute_operating_envelope",
    "compute_trial_summary",
    "run_rq2_analysis",
]
