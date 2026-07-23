"""实验一/二批次整理、切换和论文重建工作流。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from ._filesystem import create_inherited_temp_directory, remove_tree_with_retry
from .preprocess import (
    REQUIRED_FILE_NAMES,
    TASK_SOURCE_FILE_NAMES,
    StageOneQcReport,
    WorkbookArtifact,
    collect_source_files,
    finalize_task_events,
    require_task_sources,
    run_task_qc,
    source_set_sha256,
    verify_task_workbook,
    write_task_workbook,
)


EXPECTED_MATRIX_ID = "exp12_9_smoothed_hermite_v4"
"""正式实验一/二必须使用的九路运行时矩阵标识。"""

DEFAULT_BATCH_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "batch.toml"
"""批次输入、输出和论文路径的唯一操作配置。"""

_BATCH_ID_PATTERN = re.compile(r"^batch_\d{8}_\d{6}_[0-9a-f]{8,64}$")
"""自动批次名的固定格式。"""

_SESSION_TIME_PATTERN = re.compile(r"^(?P<date>\d{8})_(?P<time>\d{6})_")
"""正式 session ID 中用于构造稳定批次名的时间部分。"""

_PAPER_JOB_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
"""latexmk jobname 允许使用的稳定 ASCII 文件名。"""

_COMMON_MANIFEST_FIELDS = (
    "config_hash",
    "frozen_parameter_set_id",
    "object_id",
    "object_model_id",
    "protocol_version",
    "run_kind",
    "variant_matrix_id",
)
"""同一正式批次必须完全一致的 manifest 字段。"""


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """一项物理任务的编号、归档目录和场景标识。"""

    number: int
    """从 1 开始的固定任务编号。"""

    directory_name: str
    """活动 raw 目录使用的固定名称。"""

    scenario_id: str
    """manifest 和事件行必须使用的场景标识。"""


TASK_SPECS = (
    TaskSpec(1, "task_1_static_head_motion", "static_head_motion"),
    TaskSpec(2, "task_2_start_stop_6dof", "start_stop_6dof"),
    TaskSpec(3, "task_3_continuous_translation", "continuous_translation"),
    TaskSpec(4, "task_4_continuous_rotation", "continuous_rotation"),
    TaskSpec(5, "task_5_occlusion_recovery", "occlusion_recovery"),
)
"""当前正式流水线要求的五项物理任务。"""


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """一个已映射 task session 的关键批次身份。"""

    task_number: int
    """该 session 唯一完成的任务编号。"""

    task_directory: str
    """复制到 raw 后使用的固定目录名。"""

    session_id: str
    """manifest 中不可改写的原始 session ID。"""

    scenario_id: str
    """完成任务对应的场景标识。"""

    config_hash: str
    """九路运行时整体配置哈希。"""

    frozen_parameter_set_id: str
    """正式采集冻结参数集标识。"""

    object_id: str
    """被跟踪对象标识。"""

    object_model_id: str
    """对象三维模型标识。"""

    protocol_version: str
    """跨端协议版本。"""

    run_kind: str
    """采集类型，正式数据必须为 formal。"""

    variant_matrix_id: str
    """九路运行时矩阵标识。"""

    def to_dict(self) -> dict[str, Any]:
        """返回适合 CLI JSON 输出的普通字典。"""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class BatchPaths:
    """从 batch.toml 解析出的绝对批次路径。"""

    project_root: Path
    """包含 pixi.toml 的 EgoAnchor_Python 根目录。"""

    eval_root: Path
    """新采集 session 的同步暂存目录。"""

    staging_root: Path
    """新批次通过全部检查前的临时父目录。"""

    archive_root: Path
    """退出当前论文的旧批次父目录。"""

    active_root: Path
    """当前论文唯一使用的活动批次目录。"""

    paper_root: Path
    """中文 LaTeX 主稿及图表的根目录。"""

    manuscript_path: Path
    """当前需要分析回填和编译的版本化 LaTeX 主稿。"""

    paper_pdf_path: Path
    """不含稿件版本号、面向阅读和交付的稳定 PDF 路径。"""

    config_path: Path
    """本次读取的 batch.toml 绝对路径。"""


@dataclass(frozen=True, slots=True)
class BatchArtifact:
    """一次成功暂存批次的路径、session 和工作簿摘要。"""

    batch_id: str
    """由首个 session 时间和配置哈希构造的稳定批次名。"""

    root: Path
    """位于 `_staging/experiment_1_2/` 下的完整批次目录。"""

    sessions: tuple[SessionSummary, ...]
    """按任务 1--5 排序的 session 身份。"""

    workbook_sha256: dict[str, str]
    """五本 Stage 1 工作簿文件名到 SHA-256 的映射。"""

    def to_dict(self) -> dict[str, Any]:
        """返回适合 CLI JSON 输出的普通字典。"""

        return {
            "passed": True,
            "batch_id": self.batch_id,
            "root": str(self.root),
            "sessions": [item.to_dict() for item in self.sessions],
            "workbook_sha256": dict(self.workbook_sha256),
            "next_command": f"pixi run eval promote {self.batch_id}",
        }


class BatchToolError(RuntimeError):
    """Git 或 XeLaTeX 等外部工具未成功完成工作流。"""


def project_root() -> Path:
    """返回包含 pixi.toml 的 EgoAnchor_Python 根目录。"""

    return Path(__file__).resolve().parents[3]


def load_batch_paths(root: Path | None = None) -> BatchPaths:
    """读取 batch.toml，并把相对路径解析到项目根目录。"""

    base = _normalize_project_root(root)
    with DEFAULT_BATCH_CONFIG_PATH.open("rb") as handle:
        document = tomllib.load(handle)
    raw_paths = document.get("paths")
    if not isinstance(raw_paths, dict):
        raise ValueError("batch.toml 必须包含 [paths]")
    raw_paper = document.get("paper")
    if not isinstance(raw_paper, dict):
        raise ValueError("batch.toml 必须包含 [paper]")

    eval_root = _resolve_data_path(base, raw_paths, "eval_root")
    staging_root = _resolve_data_path(base, raw_paths, "staging_root")
    archive_root = _resolve_data_path(base, raw_paths, "archive_root")
    active_root = _resolve_data_path(base, raw_paths, "active_root")
    paper_root = _resolve_paper_path(base, raw_paths)
    manuscript_path = _resolve_paper_file(paper_root, raw_paper, "manuscript", ".tex")
    paper_pdf_path = _resolve_paper_file(paper_root, raw_paper, "output_pdf", ".pdf")
    managed = (eval_root, staging_root, archive_root, active_root)
    if len(set(managed)) != len(managed):
        raise ValueError("batch.toml 的 eval/staging/archive/active 路径必须互不相同")
    for index, left in enumerate(managed):
        for right in managed[index + 1:]:
            if left.is_relative_to(right) or right.is_relative_to(left):
                raise ValueError("batch.toml 的托管数据路径不得互为父子目录")
    if any(paper_root.is_relative_to(path) or path.is_relative_to(paper_root) for path in managed):
        raise ValueError("paper_root 不得与任何托管数据目录重叠")
    return BatchPaths(
        project_root=base,
        eval_root=eval_root,
        staging_root=staging_root,
        archive_root=archive_root,
        active_root=active_root,
        paper_root=paper_root,
        manuscript_path=manuscript_path,
        paper_pdf_path=paper_pdf_path,
        config_path=DEFAULT_BATCH_CONFIG_PATH,
    )


def describe_workflow(root: Path | None = None) -> dict[str, Any]:
    """返回当前生效配置，以及每个命令的固定输入和输出。"""

    paths = load_batch_paths(root)
    active = paths.active_root
    return {
        "passed": True,
        "configuration_file": str(paths.config_path),
        "paths": {
            "eval_root": str(paths.eval_root),
            "staging_root": str(paths.staging_root),
            "archive_root": str(paths.archive_root),
            "active_root": str(active),
            "paper_root": str(paths.paper_root),
            "manuscript": str(paths.manuscript_path),
            "manuscript_exists": paths.manuscript_path.is_file(),
            "output_pdf": str(paths.paper_pdf_path),
            "output_pdf_exists": paths.paper_pdf_path.is_file(),
        },
        "stages": {
            "config": {
                "input": str(paths.config_path),
                "output": "stdout JSON",
            },
            "sessions": {
                "input": str(paths.eval_root),
                "output": "stdout JSON",
            },
            "stage": {
                "input": str(paths.eval_root / "<session_id>"),
                "output": str(paths.staging_root / "<batch_id>"),
            },
            "promote": {
                "input": str(paths.staging_root / "<batch_id>"),
                "output": str(active),
            },
            "qc": {
                "input": str(active / "raw"),
                "output": "stdout JSON；events.jsonl 缺失时会在对应 raw task 内确定性生成",
            },
            "preprocess": {
                "input": str(active / "raw"),
                "output": str(active / "workbooks"),
            },
            "analyze": {
                "input": str(active / "workbooks"),
                "output": [
                    str(active / "analysis"),
                    str(paths.paper_root / "figures" / "panels"),
                    str(paths.paper_root / "tables"),
                    str(paths.manuscript_path),
                    str(paths.paper_pdf_path),
                ],
                "note": "使用 --skip-latex 时不生成或更新 output_pdf",
            },
            "latex": {
                "input": str(paths.manuscript_path),
                "output": str(paths.paper_pdf_path),
            },
            "rebuild": {
                "input": str(active / "raw"),
                "output": [
                    str(active / "workbooks"),
                    str(active / "analysis"),
                    str(paths.paper_root / "figures" / "panels"),
                    str(paths.paper_root / "tables"),
                    str(paths.manuscript_path),
                    str(paths.paper_pdf_path),
                ],
                "note": "使用 --skip-latex 时不生成或更新 output_pdf",
            },
        },
    }


def list_eval_sessions(root: Path | None = None) -> list[dict[str, Any]]:
    """列出 `data/eval` 下可见 session 的任务和配置摘要。"""

    paths = load_batch_paths(root)
    if not paths.eval_root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for session_dir in sorted(path for path in paths.eval_root.iterdir() if path.is_dir()):
        manifest_path = session_dir / "manifest.json"
        if not manifest_path.is_file():
            rows.append({"directory": session_dir.name, "valid_manifest": False, "error": "缺少 manifest.json"})
            continue
        try:
            manifest = _read_json(manifest_path)
            python_state = _read_json(session_dir / "python_session.json").get("state")
            completed = manifest.get("completed_tasks")
            completed_numbers = [item.get("task_number") for item in completed] if isinstance(completed, list) else []
            rows.append(
                {
                    "directory": session_dir.name,
                    "valid_manifest": True,
                    "session_id": manifest.get("session_id"),
                    "completed_tasks": completed_numbers,
                    "config_hash": manifest.get("config_hash"),
                    "python_state": python_state,
                    "variant_matrix_id": manifest.get("variant_matrix_id"),
                }
            )
        except (OSError, ValueError) as error:
            rows.append({"directory": session_dir.name, "valid_manifest": False, "error": str(error)})
    return rows


def stage_batch(
    session_ids: Sequence[str],
    *,
    root: Path | None = None,
    batch_id: str | None = None,
) -> BatchArtifact:
    """校验五个 eval session，复制到暂存区并生成五本工作簿。"""

    paths = load_batch_paths(root)
    base = paths.project_root
    if len(session_ids) != len(TASK_SPECS):
        raise ValueError("stage 必须接收覆盖任务 1--5 的五个 session ID")
    if len(set(session_ids)) != len(session_ids):
        raise ValueError("五项任务必须来自五个不同 session")

    unordered_dirs = _eval_session_dirs(paths.eval_root, session_ids)
    source_dirs, summaries = _map_eval_sessions(unordered_dirs)
    _finalize_and_require_qc(source_dirs)

    resolved_batch_id = batch_id or _batch_id(summaries)
    _require_batch_id(resolved_batch_id)
    destination = paths.staging_root / resolved_batch_id
    if destination.exists():
        raise FileExistsError(f"批次暂存目录已存在，拒绝合并或覆盖：{destination}")

    temporary = create_inherited_temp_directory(paths.staging_root, f".{resolved_batch_id}.tmp-")
    try:
        staged_dirs = _copy_task_sources(source_dirs, temporary / "raw")
        copied_summaries = _validate_task_directories(staged_dirs, require_session_directory_name=False)
        if copied_summaries != summaries:
            raise ValueError("复制后的 manifest 批次身份与 eval 源不一致")
        _finalize_and_require_qc(staged_dirs)
        artifacts = _write_workbooks(
            staged_dirs,
            temporary / "workbooks",
            _git_code_version(base),
        )
        temporary.rename(destination)
    except Exception:
        remove_tree_with_retry(temporary)
        raise

    return BatchArtifact(
        batch_id=resolved_batch_id,
        root=destination,
        sessions=summaries,
        workbook_sha256={artifact.path.name: artifact.sha256 for artifact in artifacts},
    )


def promote_batch(batch_id: str | None = None, *, root: Path | None = None) -> dict[str, Any]:
    """将一个已验证暂存批次切换为当前活动批次，并冷归档旧批次。"""

    paths = load_batch_paths(root)
    resolved_batch_id = batch_id or _only_staged_batch(paths.staging_root)
    _require_batch_id(resolved_batch_id)
    staged = paths.staging_root / resolved_batch_id
    if not staged.is_dir():
        raise FileNotFoundError(f"找不到暂存批次：{staged}")
    _validate_complete_batch(staged)

    active = paths.active_root
    archive_parent = paths.archive_root
    archived: Path | None = None
    if active.exists():
        current_summaries = _validate_task_directories(_task_dirs(active / "raw"), require_session_directory_name=False)
        archived = archive_parent / _batch_id(current_summaries)
        if archived.exists():
            raise FileExistsError(f"旧批次冷归档已存在，拒绝覆盖：{archived}")
        archive_parent.mkdir(parents=True, exist_ok=True)
        active.rename(archived)

    try:
        staged.rename(active)
    except Exception:
        if archived is not None and archived.exists() and not active.exists():
            archived.rename(active)
        raise

    return {
        "passed": True,
        "active_batch": resolved_batch_id,
        "active_root": str(active),
        "archived_root": str(archived) if archived is not None else None,
        "next_command": "pixi run eval analyze",
    }


def rebuild_current(
    *,
    root: Path | None = None,
    compile_pdf: bool = True,
) -> dict[str, Any]:
    """从当前 raw 重新生成五本工作簿、论文分析产物和最终 PDF。"""

    paths = load_batch_paths(root)
    preprocess_result = preprocess_current(root=paths.project_root)
    result = analyze_current(root=paths.project_root, compile_pdf=compile_pdf)
    result["workbook_sha256"] = preprocess_result["workbook_sha256"]
    return result


def qc_current(*, root: Path | None = None) -> dict[str, Any]:
    """对当前活动批次的五个 raw task 执行完整硬 QC。"""

    paths = load_batch_paths(root)
    task_dirs = _task_dirs(paths.active_root / "raw")
    summaries = _validate_task_directories(task_dirs, require_session_directory_name=False)
    reports = _finalize_and_run_qc(task_dirs)
    return {
        "passed": all(report.passed for report in reports),
        "raw_root": str(paths.active_root / "raw"),
        "sessions": [summary.to_dict() for summary in summaries],
        "tasks": [report.to_dict() for report in reports],
    }


def preprocess_current(
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """把当前活动批次的 raw JSON/JSONL 发布为五本完整工作簿。"""

    paths = load_batch_paths(root)
    task_dirs = _task_dirs(paths.active_root / "raw")
    _validate_task_directories(task_dirs, require_session_directory_name=False)
    _finalize_and_require_qc(task_dirs)
    artifacts = _write_workbooks(
        task_dirs,
        paths.active_root / "workbooks",
        _git_code_version(paths.project_root),
    )
    return {
        "passed": True,
        "output_root": str(paths.active_root / "workbooks"),
        "workbook_sha256": {artifact.path.name: artifact.sha256 for artifact in artifacts},
        "next_command": "pixi run eval analyze --skip-latex",
    }


def analyze_current(*, root: Path | None = None, compile_pdf: bool = True) -> dict[str, Any]:
    """从当前五本工作簿生成指标、绘图数据、图表、主稿和可选 PDF。"""

    from .paper_analysis import build_paper

    paths = load_batch_paths(root)
    active = paths.active_root
    workbooks = tuple(active / "workbooks" / f"task_{number}_complete.xlsx" for number in range(1, 6))
    payload = build_paper(
        workbooks,
        active / "analysis",
        paths.paper_root,
        paths.manuscript_path,
    )
    pdf_path: Path | None = None
    if compile_pdf:
        pdf_path = _compile_paper(paths)
    return {
        "passed": True,
        "analysis": payload,
        "paper_pdf": str(pdf_path) if pdf_path is not None else None,
    }


def compile_current_paper(*, root: Path | None = None) -> dict[str, Any]:
    """只使用 XeLaTeX 编译当前中文主稿，不重新运行数据分析。"""

    paths = load_batch_paths(root)
    pdf_path = _compile_paper(paths)
    return {"passed": True, "paper_pdf": str(pdf_path)}


def _normalize_project_root(root: Path | None) -> Path:
    """规范化项目根目录，并确认 pixi.toml 存在。"""

    base = (root or project_root()).expanduser().resolve()
    if not (base / "pixi.toml").is_file():
        raise FileNotFoundError(f"EgoAnchor_Python 根目录缺少 pixi.toml：{base}")
    return base


def _resolve_data_path(base: Path, raw_paths: dict[str, Any], field_name: str) -> Path:
    """解析必须位于 EgoAnchor_Python/data 内的批次目录。"""

    raw_value = raw_paths.get(field_name)
    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError(f"batch.toml paths.{field_name} 必须为非空字符串")
    resolved = (base / raw_value).resolve()
    data_root = (base / "data").resolve()
    if not resolved.is_relative_to(data_root):
        raise ValueError(f"batch.toml paths.{field_name} 必须位于 {data_root} 内")
    return resolved


def _resolve_paper_path(base: Path, raw_paths: dict[str, Any]) -> Path:
    """解析必须位于当前仓库内的论文目录。"""

    raw_value = raw_paths.get("paper_root")
    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError("batch.toml paths.paper_root 必须为非空字符串")
    resolved = (base / raw_value).resolve()
    repository_root = base.parent.resolve()
    if not resolved.is_relative_to(repository_root):
        raise ValueError(f"batch.toml paths.paper_root 必须位于 {repository_root} 内")
    return resolved


def _resolve_paper_file(
    paper_root: Path,
    raw_paper: dict[str, Any],
    field_name: str,
    suffix: str,
) -> Path:
    """解析 paper_root 内的相对文件路径，并限制预期扩展名。"""

    raw_value = raw_paper.get(field_name)
    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError(f"batch.toml paper.{field_name} 必须为非空字符串")
    relative = Path(raw_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"batch.toml paper.{field_name} 必须是 paper_root 内的相对路径")
    resolved = (paper_root / relative).resolve()
    if not resolved.is_relative_to(paper_root) or resolved.suffix.lower() != suffix:
        raise ValueError(f"batch.toml paper.{field_name} 必须是 paper_root 内的 {suffix} 文件")
    if suffix == ".pdf" and _PAPER_JOB_PATTERN.fullmatch(resolved.stem) is None:
        raise ValueError(
            "batch.toml paper.output_pdf 的文件名只能使用 ASCII 字母、数字、点、下划线和连字符"
        )
    return resolved


def _task_dirs(raw_root: Path) -> tuple[Path, ...]:
    """返回任务 1--5 的固定 raw 目录。"""

    return tuple(raw_root / spec.directory_name for spec in TASK_SPECS)


def _eval_session_dirs(eval_root: Path, session_ids: Sequence[str]) -> tuple[Path, ...]:
    """把 session basename 限制在 data/eval 内，拒绝绝对路径和目录穿越。"""

    normalized_root = eval_root.resolve()
    directories: list[Path] = []
    for session_id in session_ids:
        candidate_name = Path(session_id)
        if candidate_name.is_absolute() or candidate_name.name != session_id or session_id in {".", ".."}:
            raise ValueError(f"session 参数只能是 data/eval 下的目录名：{session_id}")
        candidate = (normalized_root / session_id).resolve()
        if not candidate.is_relative_to(normalized_root):
            raise ValueError(f"session 目录越出 data/eval：{session_id}")
        directories.append(candidate)
    return tuple(directories)


def _map_eval_sessions(task_dirs: Sequence[Path]) -> tuple[tuple[Path, ...], tuple[SessionSummary, ...]]:
    """按 completed_tasks 自动把五个 eval session 映射到任务 1--5。"""

    mapped: dict[int, tuple[Path, SessionSummary]] = {}
    for task_dir in task_dirs:
        manifest = _read_json(task_dir / "manifest.json")
        completed = manifest.get("completed_tasks")
        if not isinstance(completed, list) or len(completed) != 1 or not isinstance(completed[0], dict):
            raise ValueError(f"{task_dir.name} 必须恰好有一个最终完成任务")
        task_number = completed[0].get("task_number")
        if isinstance(task_number, bool) or not isinstance(task_number, int) or not 1 <= task_number <= 5:
            raise ValueError(f"{task_dir.name} 的 task_number 必须在 1--5 内")
        if task_number in mapped:
            raise ValueError(f"输入 session 重复覆盖任务 {task_number}")
        spec = TASK_SPECS[task_number - 1]
        mapped[task_number] = (
            task_dir,
            _session_summary(task_dir, spec, require_session_directory_name=True),
        )
    if sorted(mapped) != [1, 2, 3, 4, 5]:
        raise ValueError(f"输入 session 必须恰好覆盖任务 1--5，实际为 {sorted(mapped)}")
    ordered_dirs = tuple(mapped[number][0] for number in range(1, 6))
    summaries = tuple(mapped[number][1] for number in range(1, 6))
    _validate_common_summaries(summaries)
    return ordered_dirs, summaries


def _validate_task_directories(
    task_dirs: Sequence[Path],
    *,
    require_session_directory_name: bool,
) -> tuple[SessionSummary, ...]:
    """检查五个目录的任务映射和批次公共身份。"""

    if len(task_dirs) != len(TASK_SPECS):
        raise ValueError("正式批次必须恰好包含任务 1--5 五个目录")
    summaries = tuple(
        _session_summary(path, spec, require_session_directory_name=require_session_directory_name)
        for path, spec in zip(task_dirs, TASK_SPECS, strict=True)
    )
    _validate_common_summaries(summaries)
    return summaries


def _validate_common_summaries(summaries: Sequence[SessionSummary]) -> None:
    """检查 session 唯一性、正式状态和跨 task 公共批次身份。"""

    if len({item.session_id for item in summaries}) != len(summaries):
        raise ValueError("同一批次不得包含重复 session_id")
    first = summaries[0]
    for field_name in _COMMON_MANIFEST_FIELDS:
        expected = getattr(first, field_name)
        if any(getattr(item, field_name) != expected for item in summaries[1:]):
            raise ValueError(f"五个 session 的 {field_name} 不一致")
    if first.run_kind != "formal":
        raise ValueError("正式批次的 run_kind 必须为 formal")
    if first.variant_matrix_id != EXPECTED_MATRIX_ID:
        raise ValueError(f"variant_matrix_id 必须为 {EXPECTED_MATRIX_ID}")


def _session_summary(
    task_dir: Path,
    spec: TaskSpec,
    *,
    require_session_directory_name: bool,
) -> SessionSummary:
    """读取一个 task manifest，并确认它只完成对应任务。"""

    if not task_dir.is_dir():
        raise FileNotFoundError(f"task/session 目录不存在：{task_dir}")
    manifest = _read_json(task_dir / "manifest.json")
    session_id = _nonempty_text(manifest, "session_id")
    if require_session_directory_name and task_dir.name != session_id:
        raise ValueError(f"eval 目录名与 manifest.session_id 不一致：{task_dir.name} != {session_id}")
    completed = manifest.get("completed_tasks")
    if not isinstance(completed, list) or len(completed) != 1 or not isinstance(completed[0], dict):
        raise ValueError(f"{session_id} 必须恰好有一个最终完成任务")
    completed_task = completed[0]
    if completed_task.get("task_number") != spec.number:
        raise ValueError(f"{session_id} 未对应任务 {spec.number}")
    if completed_task.get("scenario_id") != spec.scenario_id:
        raise ValueError(f"{session_id} 的 scenario_id 未对应 {spec.scenario_id}")
    return SessionSummary(
        task_number=spec.number,
        task_directory=spec.directory_name,
        session_id=session_id,
        scenario_id=spec.scenario_id,
        config_hash=_nonempty_text(manifest, "config_hash"),
        frozen_parameter_set_id=_nonempty_text(manifest, "frozen_parameter_set_id"),
        object_id=_nonempty_text(manifest, "object_id"),
        object_model_id=_nonempty_text(manifest, "object_model_id"),
        protocol_version=_nonempty_text(manifest, "protocol_version"),
        run_kind=_nonempty_text(manifest, "run_kind"),
        variant_matrix_id=_nonempty_text(manifest, "variant_matrix_id"),
    )


def _read_json(path: Path) -> dict[str, Any]:
    """读取必须为 JSON 对象的 UTF-8 文档。"""

    if not path.is_file():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 文档根必须为对象：{path}")
    return data


def _nonempty_text(document: dict[str, Any], field_name: str) -> str:
    """读取一个必需的非空字符串字段。"""

    value = document.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"manifest.{field_name} 必须为非空字符串")
    return value


def _finalize_and_run_qc(task_dirs: Sequence[Path]) -> tuple[StageOneQcReport, ...]:
    """物化事件总表并返回逐 task 完整硬 QC 报告。"""

    require_task_sources(tuple(task_dirs), TASK_SOURCE_FILE_NAMES)
    for task_dir in task_dirs:
        finalize_task_events(task_dir)
    require_task_sources(tuple(task_dirs), REQUIRED_FILE_NAMES)
    return tuple(run_task_qc(task_dir) for task_dir in task_dirs)


def _finalize_and_require_qc(task_dirs: Sequence[Path]) -> tuple[StageOneQcReport, ...]:
    """物化事件总表，并要求每个 task 的完整硬 QC 通过。"""

    reports = _finalize_and_run_qc(task_dirs)
    failed = [report for report in reports if not report.passed]
    if failed:
        details = "; ".join(
            f"{report.session_id}: {', '.join(issue.code for issue in report.errors)}"
            for report in failed
        )
        raise ValueError(f"批次 QC 失败：{details}")
    return reports


def _copy_task_sources(source_dirs: Sequence[Path], raw_root: Path) -> tuple[Path, ...]:
    """逐 task 复制完整来源，并用来源集合 SHA-256 验证副本。"""

    raw_root.mkdir(parents=True, exist_ok=True)
    destinations: list[Path] = []
    for source, spec in zip(source_dirs, TASK_SPECS, strict=True):
        destination = raw_root / spec.directory_name
        source_digest = source_set_sha256(collect_source_files(source))
        shutil.copytree(source, destination, ignore=_ignore_empty_audit_samples)
        source_digest_after_copy = source_set_sha256(collect_source_files(source))
        copied_digest = source_set_sha256(collect_source_files(destination))
        if source_digest_after_copy != source_digest:
            raise OSError(f"task {spec.number} 在复制期间仍被写入，拒绝暂存半同步数据")
        if copied_digest != source_digest:
            raise OSError(f"task {spec.number} 复制后来源 SHA-256 不一致")
        destinations.append(destination)
    return tuple(destinations)


def _ignore_empty_audit_samples(directory: str, names: list[str]) -> set[str]:
    """暂存时跳过遗留的空 audit_samples 目录，保留真实审计文件。"""

    ignored: set[str] = set()
    source = Path(directory)
    for name in names:
        if name != "audit_samples":
            continue
        candidate = source / name
        if candidate.is_dir() and not any(path.is_file() for path in candidate.rglob("*")):
            ignored.add(name)
    return ignored


def _write_workbooks(
    task_dirs: Sequence[Path],
    output_root: Path,
    code_version: str,
) -> tuple[WorkbookArtifact, ...]:
    """按任务 1--5 发布完整工作簿，并独立回读确认。"""

    output_root.mkdir(parents=True, exist_ok=True)
    artifacts = tuple(
        write_task_workbook(
            task_dir,
            output_root / f"task_{spec.number}_complete.xlsx",
            code_version=code_version,
        )
        for task_dir, spec in zip(task_dirs, TASK_SPECS, strict=True)
    )
    for artifact in artifacts:
        verification = verify_task_workbook(artifact.path)
        if not verification.passed:
            raise ValueError(f"Stage 1 工作簿回读失败：{artifact.path}")
    return artifacts


def _batch_id(summaries: Sequence[SessionSummary]) -> str:
    """用最早 session 时间和配置哈希构造唯一、稳定的批次名。"""

    earliest = min(item.session_id for item in summaries)
    match = _SESSION_TIME_PATTERN.match(earliest)
    if match is None:
        raise ValueError(f"正式 session_id 缺少 YYYYMMDD_HHMMSS 前缀：{earliest}")
    config_token = summaries[0].config_hash[:16]
    if not re.fullmatch(r"[0-9a-f]{8,64}", config_token):
        raise ValueError("config_hash 必须以至少八位小写十六进制字符开头")
    return f"batch_{match.group('date')}_{match.group('time')}_{config_token}"


def _require_batch_id(batch_id: str) -> None:
    """拒绝 v3 等不稳定批次名和任意路径片段。"""

    if _BATCH_ID_PATTERN.fullmatch(batch_id) is None:
        raise ValueError("batch_id 必须为 batch_YYYYMMDD_HHMMSS_<config-hash> 格式")


def _only_staged_batch(staging_parent: Path) -> str:
    """没有显式批次名时，仅在暂存区恰好一个批次时自动选择。"""

    candidates = sorted(
        path.name
        for path in staging_parent.iterdir()
        if path.is_dir() and _BATCH_ID_PATTERN.fullmatch(path.name)
    ) if staging_parent.is_dir() else []
    if len(candidates) != 1:
        raise ValueError("未指定 batch_id 时，暂存区必须恰好包含一个完整批次")
    return candidates[0]


def _validate_complete_batch(batch_root: Path) -> None:
    """在目录切换前重新检查 raw 和五本工作簿。"""

    task_dirs = _task_dirs(batch_root / "raw")
    _validate_task_directories(task_dirs, require_session_directory_name=False)
    _finalize_and_require_qc(task_dirs)
    workbook_root = batch_root / "workbooks"
    for number in range(1, 6):
        workbook = workbook_root / f"task_{number}_complete.xlsx"
        if not workbook.is_file():
            raise FileNotFoundError(workbook)
        verification = verify_task_workbook(workbook)
        if not verification.passed:
            raise ValueError(f"Stage 1 工作簿回读失败：{workbook}")
        raw_digest = source_set_sha256(collect_source_files(task_dirs[number - 1]))
        if verification.source_set_sha256 != raw_digest:
            raise ValueError(f"task {number} 的 raw 与 Stage 1 工作簿来源摘要不一致")


def _git_code_version(base: Path) -> str:
    """读取当前仓库短提交号，禁止把 unknown 写入正式工作簿。"""

    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=base,
        capture_output=True,
        text=True,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value:
        raise BatchToolError("无法读取当前 Git commit，拒绝生成缺少代码版本的正式工作簿")
    return value


def _compile_paper(paths: BatchPaths) -> Path:
    """使用本机 latexmk/XeLaTeX 把版本化主稿编译为稳定 PDF 名称。"""

    executable = shutil.which("latexmk")
    if executable is None:
        raise BatchToolError("找不到 latexmk，请先安装本机 LaTeX 工具链")
    if not paths.manuscript_path.is_file():
        raise FileNotFoundError(paths.manuscript_path)
    paths.paper_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            executable,
            "-xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-jobname={paths.paper_pdf_path.stem}",
            f"-outdir={paths.paper_pdf_path.parent}",
            str(paths.manuscript_path.relative_to(paths.paper_root)),
        ],
        cwd=paths.paper_root,
        check=False,
    )
    if completed.returncode != 0:
        raise BatchToolError(f"XeLaTeX 编译失败，退出码 {completed.returncode}")
    if not paths.paper_pdf_path.is_file():
        raise BatchToolError(f"XeLaTeX 成功返回但未生成 PDF：{paths.paper_pdf_path}")
    return paths.paper_pdf_path


__all__ = [
    "BatchArtifact",
    "BatchPaths",
    "BatchToolError",
    "DEFAULT_BATCH_CONFIG_PATH",
    "EXPECTED_MATRIX_ID",
    "SessionSummary",
    "TASK_SPECS",
    "TaskSpec",
    "analyze_current",
    "compile_current_paper",
    "describe_workflow",
    "list_eval_sessions",
    "load_batch_paths",
    "preprocess_current",
    "project_root",
    "promote_batch",
    "qc_current",
    "rebuild_current",
    "stage_batch",
]
