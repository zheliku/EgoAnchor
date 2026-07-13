"""评估 session 日志加载与 frame_id join。

该模块位于 EgoAnchor_Python/eval，故意不导入 egoanchor 包；它只消费
Unity/Python 已落盘的 JSONL，用于后续标定、指标和报告阶段复用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .schemas import CaptureRow, Manifest, OutputRow, PoseResultRow, SchemaError


@dataclass(frozen=True)
class SessionLogs:
    """一个评估 session 的三张分析表和 manifest。"""

    capture: pd.DataFrame
    """Unity capture 表，index=frame_id。"""

    output: pd.DataFrame
    """Unity output 长表，每个渲染 tick 的每个 variant 一行。"""

    pose: pd.DataFrame
    """Python pose_result 表，index=frame_id。"""

    manifest: dict[str, Any]
    """原始 session_manifest.json 内容。"""


def load_session(
    session_dir: Path | str,
    python_log: Path | str | None = None,
    output_log: Path | str | None = None,
) -> SessionLogs:
    """加载一个 session 目录中的 Unity/Python 评估日志。

    Args:
        session_dir: `EgoAnchor_Python/data/eval/<session_id>` 目录。
        python_log: 可选 Python runtime JSONL；为空时按 manifest 或同目录唯一
            非 Unity JSONL 自动解析。
        output_log: 可选 Unity output/replay JSONL；为空时读取 session 目录中的
            `*_unity_output.jsonl`。

    Returns:
        `SessionLogs`，其中 capture/pose 已按 frame_id 建索引，output 已展平。
    """

    session_path = Path(session_dir)
    if not session_path.is_dir():
        raise SchemaError(f"session_dir 不存在或不是目录：{session_path}")

    manifest_path = session_path / "session_manifest.json"
    manifest = _load_manifest(manifest_path)
    capture_path = _resolve_unique_log(session_path, "*_unity_capture.jsonl", "unity_capture")
    output_path = _resolve_existing_path(session_path, output_log, "output_log") if output_log is not None else _resolve_unique_log(session_path, "*_unity_output.jsonl", "unity_output")
    pose_path = _resolve_python_log(session_path, manifest, python_log)

    return SessionLogs(
        capture=_load_capture(capture_path),
        output=_load_output(output_path),
        pose=_load_pose(pose_path),
        manifest=manifest.raw,
    )


def join_by_frame(logs: SessionLogs) -> pd.DataFrame:
    """按 frame_id 左连接 capture 与 Python pose_result。

    返回表保留每个 capture frame；Python 列统一加 `pose_` 前缀，并新增：
    `capture_valid`、`pose_valid`、`valid`。其中 `valid` 要求 GT live tracked
    且 Python 对该 frame 有 pose。
    """

    capture = logs.capture.reset_index(drop=True).copy()
    pose = logs.pose.reset_index(drop=True).copy()

    if pose.empty:
        pose_prefixed = pd.DataFrame({"frame_id": pd.Series(dtype="int64")})
    else:
        pose_prefixed = pose.add_prefix("pose_")
        pose_prefixed["frame_id"] = pose_prefixed["pose_frame_id"]

    joined = capture.merge(pose_prefixed, on="frame_id", how="left", validate="one_to_one")
    joined["capture_valid"] = joined["valid"].fillna(False).astype(bool)
    if "pose_valid" not in joined:
        joined["pose_valid"] = False
    if "pose_has_pose" not in joined:
        joined["pose_has_pose"] = False
    joined["pose_valid"] = joined["pose_valid"].fillna(False).astype(bool)
    joined["pose_has_pose"] = joined["pose_has_pose"].fillna(False).astype(bool)
    joined["valid"] = joined["capture_valid"] & joined["pose_valid"]
    return joined.set_index("frame_id", drop=False)


def label_conditions(df: pd.DataFrame, manifest: Mapping[str, Any] | Manifest, mono_col: str) -> pd.DataFrame:
    """根据 manifest condition_spans 给 DataFrame 增加 `condition` 列。

    `mono_col` 必须是 Unity 单调毫秒列，例如 capture_mono_ms 或 render_mono_ms。
    优先级：
    1. 有效 RQ2 试次行使用 ``rq2_condition``，避免通用时间段覆盖试次语义。
    2. manifest.condition_spans 非空 → 按时间区间标注，未落入任何 span 标 `unlabeled`。
    3. condition_spans 为空但存在 `rq1_metric` 列 → 直接用 Unity 手动标注的场景标签
       作为 condition（RQ1 每个场景一行），`none`/空标为 `unlabeled`。
    4. 以上标签都没有 → 标为 `unlabeled`。
    """

    if mono_col not in df.columns:
        raise SchemaError(f"DataFrame 缺少时间列 {mono_col}，无法标注 condition。")

    manifest_dict = manifest.raw if isinstance(manifest, Manifest) else dict(manifest)
    spans = list(_iter_condition_spans(manifest_dict.get("condition_spans", [])))
    out = df.copy()
    out["condition"] = "unlabeled"

    if not spans:
        # 回退到 Unity 手动标注的 rq1_metric 场景标签
        if "rq1_metric" in out.columns:
            metric = out["rq1_metric"].fillna("none").astype(str)
            labeled = ~metric.isin(("none", "None", "", "nan"))
            out.loc[labeled, "condition"] = metric[labeled]
    else:
        mono = out[mono_col].astype(float)
        for label, start, end in spans:
            mask = (mono >= start) & (mono < end)
            out.loc[mask, "condition"] = label

    if "rq2_condition" in out.columns:
        rq2 = out["rq2_condition"].fillna("none").astype(str)
        trial_source = out.get("rq2_trial_id", pd.Series(-1, index=out.index))
        trial = pd.to_numeric(trial_source, errors="coerce").fillna(-1)
        active = rq2.isin(("translation", "rotation")) & (trial > 0)
        out.loc[active, "condition"] = rq2[active]
    return out


def _load_manifest(path: Path) -> Manifest:
    """读取 session_manifest.json。"""

    if not path.is_file():
        raise SchemaError(f"缺少 session manifest：{path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaError(f"{path}: JSON 解析失败：{exc}") from exc
    if not isinstance(raw, dict):
        raise SchemaError(f"{path}: manifest 顶层必须是 object。")
    return Manifest.from_dict(raw, source=str(path.name))


def _load_capture(path: Path) -> pd.DataFrame:
    """读取 unity_capture JSONL。"""

    records = []
    for line_no, row in _iter_jsonl(path):
        if row.get("event") not in (None, "unity_capture"):
            raise SchemaError(f"{path.name}:{line_no}: event 应为 unity_capture。")
        records.append(CaptureRow.from_dict(row, source=f"{path.name}:{line_no}").to_record())
    if not records:
        raise SchemaError(f"{path}: 没有 unity_capture 行。")
    frame = pd.DataFrame.from_records(records)
    return frame.set_index("frame_id", drop=False).sort_index()


def _load_output(path: Path) -> pd.DataFrame:
    """读取 unity_output JSONL 并展开 variants。"""

    records: list[dict[str, Any]] = []
    for tick_index, (line_no, row) in enumerate(_iter_jsonl(path)):
        if row.get("event") not in (None, "unity_output"):
            raise SchemaError(f"{path.name}:{line_no}: event 应为 unity_output。")
        output = OutputRow.from_dict(row, tick_index=tick_index, source=f"{path.name}:{line_no}")
        records.extend(output.to_records())
    if not records:
        raise SchemaError(f"{path}: 没有 unity_output variants 行。")
    return pd.DataFrame.from_records(records)


def _load_pose(path: Path) -> pd.DataFrame:
    """读取 Python runtime JSONL 中的 pose_result 行。"""

    records = []
    for line_no, row in _iter_jsonl(path):
        if row.get("event") != "pose_result":
            continue
        records.append(PoseResultRow.from_dict(row, source=f"{path.name}:{line_no}").to_record())
    if not records:
        empty = pd.DataFrame(columns=["frame_id", "has_pose", "valid"])
        return empty.set_index("frame_id", drop=False)
    frame = pd.DataFrame.from_records(records)
    return frame.set_index("frame_id", drop=False).sort_index()


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    """逐行读取 JSONL，并保证每行是 object。"""

    if not path.is_file():
        raise SchemaError(f"日志文件不存在：{path}")
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise SchemaError(f"{path.name}:{line_no}: JSON 解析失败：{exc}") from exc
            if not isinstance(row, dict):
                raise SchemaError(f"{path.name}:{line_no}: JSONL 每行必须是 object。")
            yield line_no, row


def _resolve_unique_log(session_dir: Path, pattern: str, label: str) -> Path:
    """在 session 目录中解析唯一日志文件。"""

    matches = sorted(session_dir.glob(pattern))
    if len(matches) != 1:
        names = ", ".join(path.name for path in matches) or "无"
        raise SchemaError(f"{session_dir}: 期望唯一 {label} 日志 {pattern}，实际：{names}")
    return matches[0]


def _resolve_python_log(session_dir: Path, manifest: Manifest, python_log: Path | str | None) -> Path:
    """按显式参数、manifest、同目录唯一候选的优先级解析 Python runtime log。"""

    if python_log is not None:
        return _resolve_existing_path(session_dir, python_log, "python_log")

    manifest_name = manifest.python_log_filename.strip()
    if manifest_name:
        return _resolve_existing_path(session_dir, manifest_name, "manifest.python_log_filename")

    candidates = [
        path
        for path in sorted(session_dir.glob("*.jsonl"))
        if not path.name.endswith("_unity_capture.jsonl") and not path.name.endswith("_unity_output.jsonl")
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise SchemaError(
            f"{session_dir}: manifest.python_log_filename 为空，且同目录没有 Python runtime JSONL；"
            "请把 runtime log 拷入 session 目录或调用 load_session(..., python_log=...)。"
        )
    names = ", ".join(path.name for path in candidates)
    raise SchemaError(
        f"{session_dir}: manifest.python_log_filename 为空，且同目录有多个候选 Python runtime JSONL：{names}；"
        "请调用 load_session(..., python_log=...) 显式指定。"
    )


def _resolve_existing_path(session_dir: Path, value: Path | str, label: str) -> Path:
    """解析相对/绝对路径并确认存在。"""

    path = Path(value)
    candidates = [path] if path.is_absolute() else [session_dir / path, path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    names = " 或 ".join(str(candidate) for candidate in candidates)
    raise SchemaError(f"{label} 指向的 Python runtime log 不存在：{names}")


def _iter_condition_spans(spans: Iterable[Any]) -> Iterable[tuple[str, float, float]]:
    """解析 manifest condition_spans，兼容 Unity 当前 object 和计划 tuple 风格。"""

    for index, span in enumerate(spans):
        if isinstance(span, Mapping):
            label = str(span.get("label", "unlabeled"))
            start = span.get("start_mono_ms", span.get("start"))
            end = span.get("end_mono_ms", span.get("end"))
        elif isinstance(span, (list, tuple)) and len(span) >= 3:
            label = str(span[0])
            start = span[1]
            end = span[2]
        else:
            raise SchemaError(f"condition_spans[{index}] 格式不支持：{span!r}")
        if start is None or end is None:
            raise SchemaError(f"condition_spans[{index}] 缺少 start/end 时间：{span!r}")
        start_f = float(start)
        end_f = float(end)
        if end_f < start_f:
            raise SchemaError(f"condition_spans[{index}] end 早于 start：{span!r}")
        yield label, start_f, end_f


__all__ = ["SessionLogs", "join_by_frame", "label_conditions", "load_session"]
