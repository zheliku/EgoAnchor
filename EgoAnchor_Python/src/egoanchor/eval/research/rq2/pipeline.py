"""RQ2 双任务描述性统计与论文时间线编排。"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from egoanchor.eval.io import load_session
from egoanchor.eval.metrics import is_pose_value, pose_error

from .contract import (
    DISPLAY_HOLD_ROTATION_EPS_DEG,
    DISPLAY_HOLD_TRANSLATION_EPS_M,
    RQ2_CONDITIONS,
    RQ2Config,
)
from .plot import TIMELINE_FILENAMES, write_rq2_timelines
from .qc import accepted_trial_keys, compute_session_audit, compute_trial_audit
from .response import compute_response_summary
from .trajectory import (
    active_duration_seconds,
    annotate_active_motion,
    reference_valid_mask,
    unique_trial_frames,
)


SUMMARY_COLUMNS = [
    "session_id",
    "condition",
    "rq2_trial_id",
    "label",
    "n_sessions",
    "n_trials",
    "render_tick_count",
    "analysis_frame_count",
    "analysis_duration_s",
    "source_frame_count",
    "display_error_sample_count",
    "display_pair_count",
    "display_pair_elapsed_s",
    "display_update_rate_hz",
    "display_hold_fraction",
    "tracking_availability",
    "display_translation_median_m",
    "display_translation_p95_m",
    "display_rotation_median_deg",
    "display_rotation_p95_deg",
    "main_error_channel",
    "main_error_median",
    "main_error_p95",
    "main_error_unit",
    "reference_speed_median",
    "reference_speed_p95",
    "reference_speed_unit",
]


def compute_trial_summary(output: pd.DataFrame) -> pd.DataFrame:
    """在每个 ``session × task × trial × variant`` 内计算描述性统计。"""

    if output.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    rows: list[dict[str, object]] = []
    group_columns = ["session_id", "rq2_condition", "rq2_trial_id", "label"]
    for (session_id, condition, trial_id, label), group in _trial_rows(output).groupby(
        group_columns, sort=True
    ):
        identity = {
            "session_id": str(session_id),
            "condition": str(condition),
            "rq2_trial_id": int(trial_id),
            "label": str(label),
            "n_sessions": 1,
            "n_trials": 1,
        }
        rows.append({**identity, **_summarize_group(group, str(condition))})
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def compute_condition_summary(output: pd.DataFrame) -> pd.DataFrame:
    """按运动任务汇总纳入帧；结果为帧层描述，不用于总体推断。"""

    if output.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    rows: list[dict[str, object]] = []
    for (condition, label), group in _trial_rows(output).groupby(
        ["rq2_condition", "label"], sort=True
    ):
        trials = group[["session_id", "rq2_trial_id"]].drop_duplicates()
        identity = {
            "session_id": "pooled",
            "condition": str(condition),
            "rq2_trial_id": -1,
            "label": str(label),
            "n_sessions": int(group["session_id"].astype(str).nunique()),
            "n_trials": int(len(trials)),
        }
        rows.append({**identity, **_summarize_group(group, str(condition))})
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def run_rq2_analysis(
    session_dirs: list[Path | str] | tuple[Path | str, ...] | Path | str,
    *,
    report_dir: Path | str | None = None,
    figs_dir: Path | str | None = None,
    config: RQ2Config | None = None,
) -> dict[str, pd.DataFrame]:
    """加载会话、审计试次、写出最小统计表和两张 XYZ-t 时间线。"""

    settings = config or RQ2Config()
    paths = _normalize_session_dirs(session_dirs)
    outputs: list[pd.DataFrame] = []
    session_audits: list[pd.DataFrame] = []
    trial_audits: list[pd.DataFrame] = []
    seen_session_ids: set[str] = set()
    for path in paths:
        logs = load_session(path)
        session_id = str(logs.manifest.get("session_id", path.name))
        if session_id in seen_session_ids:
            raise ValueError(f"重复 session_id：{session_id}")
        seen_session_ids.add(session_id)
        output = logs.output.copy()
        output["session_id"] = session_id
        output = annotate_active_motion(output, settings)
        session_audit = compute_session_audit(output, logs.manifest)
        trial_audit = compute_trial_audit(output, settings)
        if not bool(session_audit.iloc[0]["accepted"]):
            trial_audit["accepted"] = False
            trial_audit["issues"] = trial_audit["issues"].map(
                lambda value: _append_issue(str(value), "session_rejected")
            )
        outputs.append(output)
        session_audits.append(session_audit)
        trial_audits.append(trial_audit)

    combined = pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()
    session_audit = pd.concat(session_audits, ignore_index=True)
    trial_audit = pd.concat(trial_audits, ignore_index=True)
    accepted_output = _filter_accepted_trials(combined, trial_audit)
    trial_summary = _attach_audit(compute_trial_summary(combined), trial_audit)
    condition_summary = compute_condition_summary(accepted_output)
    response_summary = compute_response_summary(accepted_output, settings)

    destination = _resolve_report_dir(paths, report_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paper_figs = Path(figs_dir) if figs_dir is not None else None
    if paper_figs is not None:
        paper_figs.mkdir(parents=True, exist_ok=True)
        _remove_timeline_files(paper_figs)
    timeline_windows = write_rq2_timelines(
        accepted_output,
        destination,
        config=settings,
    )
    tables = {
        "rq2_session_audit": session_audit,
        "rq2_trial_audit": trial_audit,
        "rq2_trial_summary": trial_summary,
        "rq2_condition_summary": condition_summary,
        "rq2_response_summary": response_summary,
        "rq2_timeline_windows": timeline_windows,
    }
    for name, table in tables.items():
        table.to_csv(destination / f"{name}.csv", index=False, float_format="%.9g")

    if paper_figs is not None:
        for filename in TIMELINE_FILENAMES:
            source = destination / filename
            if source.is_file():
                shutil.copy2(source, paper_figs / filename)
    return tables


def _summarize_group(group: pd.DataFrame, condition: str) -> dict[str, object]:
    """计算一组同步变体帧的连续性、有效率和渲染误差。"""

    work = group.sort_values(
        ["session_id", "rq2_trial_id", "render_mono_ms"], kind="stable"
    ).reset_index(drop=True)
    analysis = work.get("analysis_motion", pd.Series(False, index=work.index)).fillna(False).astype(bool)
    analysis_frames = work[analysis]
    update_rate, hold_fraction, pair_count, pair_elapsed = _display_update_summary(work)
    translation_error, rotation_error = _display_errors(analysis_frames)
    availability = _boolean_mean(analysis_frames.get("has_output_pose"))
    source_count = _source_frame_count(analysis_frames)
    duration = _analysis_duration(work)
    if condition == "rotation":
        main_values = rotation_error
        main_channel = "rotation"
        main_unit = "deg"
        speed_column = "gt_angular_speed_smooth_deg_s"
        speed_unit = "deg/s"
    else:
        main_values = translation_error
        main_channel = "translation"
        main_unit = "m"
        speed_column = "gt_linear_speed_smooth_m_s"
        speed_unit = "m/s"
    speed = _finite_values(analysis_frames.get(speed_column))
    return {
        "render_tick_count": int(len(work)),
        "analysis_frame_count": int(len(analysis_frames)),
        "analysis_duration_s": duration,
        "source_frame_count": source_count,
        "display_error_sample_count": int(len(main_values)),
        "display_pair_count": pair_count,
        "display_pair_elapsed_s": pair_elapsed,
        "display_update_rate_hz": update_rate,
        "display_hold_fraction": hold_fraction,
        "tracking_availability": availability,
        "display_translation_median_m": _percentile(translation_error, 50),
        "display_translation_p95_m": _percentile(translation_error, 95),
        "display_rotation_median_deg": _percentile(rotation_error, 50),
        "display_rotation_p95_deg": _percentile(rotation_error, 95),
        "main_error_channel": main_channel,
        "main_error_median": _percentile(main_values, 50),
        "main_error_p95": _percentile(main_values, 95),
        "main_error_unit": main_unit,
        "reference_speed_median": _percentile(speed, 50),
        "reference_speed_p95": _percentile(speed, 95),
        "reference_speed_unit": speed_unit,
    }


def _display_update_summary(group: pd.DataFrame) -> tuple[float, float, int, float]:
    """仅在同试次、相邻且均纳入的显示帧对上计算更新与保持。"""

    updates = 0
    holds = 0
    elapsed_s = 0.0
    for _, trial in group.groupby(["session_id", "rq2_trial_id"], sort=False):
        frames = trial.sort_values("render_mono_ms", kind="stable").reset_index(drop=True)
        included = frames["analysis_motion"].fillna(False).astype(bool).to_numpy()
        for index in range(1, len(frames)):
            if not included[index - 1] or not included[index]:
                continue
            previous = frames.iloc[index - 1]
            current = frames.iloc[index]
            previous_pose = _display_pose(previous)
            current_pose = _display_pose(current)
            if previous_pose is None or current_pose is None:
                continue
            interval = (float(current["render_mono_ms"]) - float(previous["render_mono_ms"])) / 1000.0
            if not np.isfinite(interval) or interval <= 0.0:
                continue
            translation, rotation = pose_error(*previous_pose, *current_pose)
            changed = (
                translation > DISPLAY_HOLD_TRANSLATION_EPS_M
                or rotation > DISPLAY_HOLD_ROTATION_EPS_DEG
            )
            updates += int(changed)
            holds += int(not changed)
            elapsed_s += interval
    pair_count = updates + holds
    rate = float(updates / elapsed_s) if elapsed_s > 0.0 else np.nan
    hold_fraction = float(holds / pair_count) if pair_count else np.nan
    return rate, hold_fraction, pair_count, elapsed_s


def _display_errors(frames: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """计算显示位姿与同刻新鲜平台参考位姿的逐帧误差。"""

    translation: list[float] = []
    rotation: list[float] = []
    reference_valid = reference_valid_mask(frames)
    for index, frame in frames.iterrows():
        display = _display_pose(frame)
        if (
            display is None
            or not bool(reference_valid.loc[index])
            or not is_pose_value(frame.get("gt_pos"))
            or not is_pose_value(frame.get("gt_rot"))
        ):
            continue
        error = pose_error(frame["gt_pos"], frame["gt_rot"], *display)
        translation.append(error[0])
        rotation.append(error[1])
    return np.asarray(translation, dtype=float), np.asarray(rotation, dtype=float)


def _display_pose(frame: pd.Series) -> tuple[object, object] | None:
    """返回用户实际看到的显示位姿；历史表缺失时回退 runtime 输出。"""

    has_display = bool(frame.get("has_display_pose", frame.get("has_output_pose", False)))
    position = frame.get("display_pos", frame.get("output_pos"))
    rotation = frame.get("display_rot", frame.get("output_rot"))
    if not has_display or not is_pose_value(position) or not is_pose_value(rotation):
        return None
    return position, rotation


def _analysis_duration(group: pd.DataFrame) -> float:
    """跨试次累加有效运动时长，不连接试次或会话边界。"""

    duration = 0.0
    for _, trial in group.groupby(["session_id", "rq2_trial_id"], sort=False):
        duration += active_duration_seconds(unique_trial_frames(trial), "analysis_motion")
    return duration


def _source_frame_count(frames: pd.DataFrame) -> int:
    """按 session 与正 source_frame_id 统计去重观测数。"""

    if frames.empty or "source_frame_id" not in frames.columns:
        return 0
    source = pd.to_numeric(frames["source_frame_id"], errors="coerce")
    positive = np.isfinite(source) & (source > 0)
    valid = frames.loc[positive, ["session_id"]].copy()
    valid["source_frame_id"] = source[positive].astype(int)
    return int(len(valid.drop_duplicates(["session_id", "source_frame_id"])))


def _trial_rows(output: pd.DataFrame) -> pd.DataFrame:
    """过滤到当前双任务契约中的正试次。"""

    trial_id = pd.to_numeric(output.get("rq2_trial_id", -1), errors="coerce")
    return output[
        output.get("rq2_condition", pd.Series("none", index=output.index))
        .astype(str)
        .isin(RQ2_CONDITIONS)
        & (trial_id > 0)
    ].copy()


def _filter_accepted_trials(output: pd.DataFrame, audit: pd.DataFrame) -> pd.DataFrame:
    """仅保留通过会话与试次审计的双变体行。"""

    keys = accepted_trial_keys(audit)
    if not keys or output.empty:
        return output.iloc[0:0].copy()
    mask = [
        (str(session), str(condition), int(trial_id)) in keys
        for session, condition, trial_id in zip(
            output["session_id"], output["rq2_condition"], output["rq2_trial_id"]
        )
    ]
    return output.loc[mask].copy()


def _attach_audit(summary: pd.DataFrame, audit: pd.DataFrame) -> pd.DataFrame:
    """把试次审计结论附到每个系统配置的摘要行。"""

    if summary.empty:
        return summary.assign(audit_accepted=pd.Series(dtype=bool), audit_issues=pd.Series(dtype=str))
    columns = ["session_id", "condition", "rq2_trial_id", "accepted", "issues"]
    attached = summary.merge(
        audit[columns],
        on=["session_id", "condition", "rq2_trial_id"],
        how="left",
        validate="many_to_one",
    )
    return attached.rename(columns={"accepted": "audit_accepted", "issues": "audit_issues"})


def _normalize_session_dirs(
    session_dirs: list[Path | str] | tuple[Path | str, ...] | Path | str,
) -> list[Path]:
    """把单个或多个会话参数规范为非空路径列表。"""

    values = [session_dirs] if isinstance(session_dirs, (str, Path)) else list(session_dirs)
    if not values:
        raise ValueError("session_dirs 不能为空。")
    return [Path(value) for value in values]


def _resolve_report_dir(paths: list[Path], explicit: Path | str | None) -> Path:
    """单会话默认写 session/report；多会话要求显式公共目录。"""

    if explicit is not None:
        return Path(explicit)
    if len(paths) != 1:
        raise ValueError("联合多个 session 时必须显式传入 report_dir。")
    return paths[0] / "report"


def _finite_values(values: object) -> np.ndarray:
    """把表列转换为有限浮点数组。"""

    if values is None:
        return np.empty(0, dtype=float)
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    return numeric[np.isfinite(numeric)]


def _percentile(values: object, percentile: float) -> float:
    """返回有限样本分位数；空样本返回 NaN。"""

    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    return float(np.percentile(finite, percentile)) if len(finite) else np.nan


def _boolean_mean(values: object) -> float:
    """返回布尔列均值；空列返回 NaN。"""

    if not isinstance(values, pd.Series) or values.empty:
        return np.nan
    return float(values.fillna(False).astype(bool).mean())


def _append_issue(existing: str, issue: str) -> str:
    """向竖线分隔的问题码追加一项。"""

    return issue if not existing else f"{existing}|{issue}"


def _remove_timeline_files(directory: Path) -> None:
    """删除该管线拥有的旧时间线，防止拒收复跑沿用陈旧图片。"""

    for filename in TIMELINE_FILENAMES:
        path = directory / filename
        if path.is_file():
            path.unlink()


__all__ = [
    "SUMMARY_COLUMNS",
    "compute_condition_summary",
    "compute_trial_summary",
    "run_rq2_analysis",
]
