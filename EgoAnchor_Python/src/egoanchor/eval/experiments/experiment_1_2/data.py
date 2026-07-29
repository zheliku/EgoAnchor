"""实验一/二的原始任务选择、Stage 1 缓存和活动批次管理。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from tqdm import tqdm

from ..._filesystem import create_inherited_temp_directory, remove_tree_with_retry
from ...preprocess import (
    REQUIRED_FILE_NAMES,
    TASK_SOURCE_FILE_NAMES,
    StageOneQcReport,
    file_sha256,
    finalize_task_events,
    require_task_sources,
    run_task_qc,
    write_task_workbook,
)
from ..common import (
    DEFAULT_BATCH_CONFIG_PATH,
    load_toml,
    project_root as resolve_project_root,
    require_table,
)


_ANALYSIS_TABLE_KEYS = frozenset(
    {
        "exp1_static_table",
        "exp1_dynamic_table",
        "exp2_table",
    }
)
"""实验一/二必须复制到论文目录的三张表格键。"""

_IMAGE_SUFFIXES = frozenset({".png", ".pdf"})
"""论文图片资源允许的文件后缀。"""


EXPECTED_MATRIX_ID = "exp12_9_smoothed_hermite_v4"
"""正式实验一/二必须使用的九路运行时矩阵标识。"""

_BATCH_ID_PATTERN = re.compile(r"^batch_(?:\d{8}_\d{6})(?:_\d{8}_\d{6}){4}$")
"""由任务一至任务五 session 时间按固定顺序组成的批次名格式。"""

_SESSION_TIME_PATTERN = re.compile(r"^(?P<date>\d{8})_(?P<time>\d{6})_")
"""正式 session ID 中用于构造稳定批次名的时间部分。"""

_TASK_DATA_PATTERN = re.compile(
    r"^task_(?P<task>[1-5])_v(?P<version>[1-9]\d*)_"
    r"(?P<date>\d{8})_(?P<time>\d{6})_(?P<object>.+)$"
)
"""任务数据目录名的冻结格式。"""

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

_BATCH_MANIFEST_SCHEMA = "egoanchor_eval_batch_v1"
"""活动批次组合清单的结构版本。"""

_TASK_CACHE_SCHEMA = "egoanchor_task_workbook_v2"
"""单任务 Stage 1 缓存记录的结构版本。"""

BATCH_MANIFEST_NAME = "batch.json"
"""暂存和活动目录中的批次组合清单文件名。"""


@dataclass(frozen=True, slots=True)
class ArtifactDestination:
    """保存一项分析产物键及其论文目标路径。"""

    artifact_key: str
    """``build_result.json`` 中的稳定产物键。"""

    destination: Path
    """论文根目录内由 ``batch.toml`` 明确配置的目标文件。"""


@dataclass(frozen=True, slots=True)
class AssetCopy:
    """保存一项由配置选择的只读资源及其论文目标。"""

    source: Path
    """EgoAnchor_Python 项目内的只读源文件。"""

    destination: Path
    """论文根目录内的目标文件。"""


@dataclass(frozen=True, slots=True)
class BatchPaths:
    """保存实验一/二从共享路径配置解析出的全部绝对路径。"""

    project_root: Path
    """包含 ``pixi.toml`` 的 EgoAnchor_Python 根目录。"""

    task_data_root: Path
    """人工归档并按任务、版本命名的原始日志目录。"""

    task_workbook_root: Path
    """按原始任务目录独立保存的 Stage 1 工作簿缓存。"""

    task_analysis_root: Path
    """按工作簿独立保存的论文指标缓存。"""

    staging_root: Path
    """新批次通过全部检查前的临时父目录。"""

    archive_root: Path
    """退出当前论文活动集的旧批次父目录。"""

    active_root: Path
    """当前论文唯一使用的活动批次目录。"""

    paper_root: Path
    """论文图片和表格所在的仓库内目录。"""

    experiment_asset_destination: Path
    """实验一、二图片复制到论文时使用的目标目录。"""

    table_destinations: tuple[ArtifactDestination, ...]
    """三张分析表格在论文目录中的明确目标路径。"""

    relay_assets: tuple[AssetCopy, ...]
    """由配置明确选择的定性 replay 图片或 PDF。"""

    batch_config_path: Path
    """本次读取的共享路径配置绝对路径。"""


def project_root() -> Path:
    """返回包含 ``pixi.toml`` 的 EgoAnchor_Python 根目录。"""

    return resolve_project_root()


def load_batch_paths(
    root: Path | None = None,
    batch_config_path: Path | None = None,
) -> BatchPaths:
    """读取共享 ``batch.toml`` 中实验一/二拥有的路径。"""

    config_path = (batch_config_path or DEFAULT_BATCH_CONFIG_PATH).expanduser().resolve()
    document = load_toml(config_path)
    base = resolve_project_root(root)
    experiment = require_table(document, "experiment_1_2", config_path.name)
    return _load_paths(document, experiment, base, config_path)


def _load_paths(
    document: dict[str, Any],
    experiment: dict[str, Any],
    base: Path,
    batch_config_path: Path,
) -> BatchPaths:
    """解析实验一/二路径，并限制输入、输出和论文目录边界。"""

    shared = require_table(document, "shared", "batch.toml")
    shared_paths = require_table(shared, "paths", "batch.toml [shared]")
    raw_paths = require_table(experiment, "paths", "batch.toml [experiment_1_2]")
    raw_copy = require_table(
        experiment,
        "copy_assets",
        "batch.toml [experiment_1_2]",
    )

    task_data_root = _resolve_data_path(base, raw_paths, "task_data_root")
    task_workbook_root = _resolve_data_path(base, raw_paths, "task_workbook_root")
    task_analysis_root = _resolve_data_path(base, raw_paths, "task_analysis_root")
    staging_root = _resolve_data_path(base, raw_paths, "staging_root")
    archive_root = _resolve_data_path(base, raw_paths, "archive_root")
    active_root = _resolve_data_path(base, raw_paths, "active_root")
    paper_root = _resolve_paper_path(base, shared_paths)
    experiment_asset_destination = _resolve_asset_destination(
        paper_root,
        raw_copy.get("experiment_destination"),
        "experiment_destination",
        directory=True,
    )
    table_destinations = _resolve_table_destinations(paper_root, raw_copy)
    relay_assets = _resolve_relay_assets(base, paper_root, raw_copy)
    managed = (
        task_data_root,
        task_workbook_root,
        task_analysis_root,
        staging_root,
        archive_root,
        active_root,
    )
    if len(set(managed)) != len(managed):
        raise ValueError("batch.toml 的实验一/二托管路径必须互不相同")
    for index, left in enumerate(managed):
        for right in managed[index + 1 :]:
            if left.is_relative_to(right) or right.is_relative_to(left):
                raise ValueError("batch.toml 的实验一/二托管路径不得互为父子目录")
    if any(
        paper_root.is_relative_to(path) or path.is_relative_to(paper_root)
        for path in managed
    ):
        raise ValueError("paper_root 不得与实验一/二托管数据目录重叠")
    return BatchPaths(
        project_root=base,
        task_data_root=task_data_root,
        task_workbook_root=task_workbook_root,
        task_analysis_root=task_analysis_root,
        staging_root=staging_root,
        archive_root=archive_root,
        active_root=active_root,
        paper_root=paper_root,
        experiment_asset_destination=experiment_asset_destination,
        table_destinations=table_destinations,
        relay_assets=relay_assets,
        batch_config_path=batch_config_path,
    )


def _resolve_data_path(base: Path, raw_paths: dict[str, Any], field_name: str) -> Path:
    """解析必须位于 EgoAnchor_Python/data 内的实验目录。"""

    raw_value = raw_paths.get(field_name)
    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError(f"batch.toml experiment_1_2.paths.{field_name} 必须为非空字符串")
    resolved = (base / raw_value).resolve()
    data_root = (base / "data").resolve()
    if not resolved.is_relative_to(data_root):
        raise ValueError(
            f"batch.toml experiment_1_2.paths.{field_name} 必须位于 {data_root} 内"
        )
    return resolved


def _resolve_paper_path(base: Path, raw_paths: dict[str, Any]) -> Path:
    """解析必须位于当前仓库内的论文目录。"""

    raw_value = raw_paths.get("paper_root")
    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError("batch.toml shared.paths.paper_root 必须为非空字符串")
    resolved = (base / raw_value).resolve()
    repository_root = base.parent.resolve()
    if not resolved.is_relative_to(repository_root):
        raise ValueError(f"batch.toml shared.paths.paper_root 必须位于 {repository_root} 内")
    return resolved


def _resolve_asset_destination(
    paper_root: Path,
    raw_value: Any,
    config_key: str,
    *,
    directory: bool,
    allowed_suffixes: frozenset[str] = _IMAGE_SUFFIXES,
) -> Path:
    """解析论文目录内的资源目标，并拒绝绝对路径和越界路径。"""

    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError(
            f"batch.toml experiment_1_2.copy_assets.{config_key} 必须为非空字符串"
        )
    relative = Path(raw_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(
            f"batch.toml experiment_1_2.copy_assets.{config_key} 必须是 paper_root 内的相对路径"
        )
    resolved = (paper_root / relative).resolve()
    if not resolved.is_relative_to(paper_root):
        raise ValueError(
            f"batch.toml experiment_1_2.copy_assets.{config_key} 超出 paper_root"
        )
    if directory:
        return resolved
    if resolved.suffix.lower() not in allowed_suffixes:
        readable_suffixes = "、".join(
            sorted(suffix.lstrip(".").upper() for suffix in allowed_suffixes)
        )
        raise ValueError(
            f"batch.toml experiment_1_2.copy_assets.{config_key} 只能指向 {readable_suffixes}"
        )
    return resolved


def _resolve_table_destinations(
    paper_root: Path,
    copy_assets: dict[str, Any],
) -> tuple[ArtifactDestination, ...]:
    """读取三张分析表格在论文目录中的明确目标路径。"""

    raw_tables = copy_assets.get("tables")
    if not isinstance(raw_tables, dict) or set(raw_tables) != _ANALYSIS_TABLE_KEYS:
        raise ValueError(
            "batch.toml experiment_1_2.copy_assets.tables 必须恰好配置三张分析表格"
        )
    destinations = tuple(
        ArtifactDestination(
            artifact_key=key,
            destination=_resolve_asset_destination(
                paper_root,
                raw_tables[key],
                f"tables.{key}",
                directory=False,
                allowed_suffixes=frozenset({".tex"}),
            ),
        )
        for key in sorted(_ANALYSIS_TABLE_KEYS)
    )
    if len({item.destination for item in destinations}) != len(destinations):
        raise ValueError("batch.toml experiment_1_2.copy_assets.tables 的目标路径不得重复")
    return destinations


def _resolve_relay_assets(
    project_root_path: Path,
    paper_root: Path,
    copy_assets: dict[str, Any],
) -> tuple[AssetCopy, ...]:
    """读取明确的 replay 来源与论文目标，不按修改时间猜测资源。"""

    raw_assets = copy_assets.get("relay")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise ValueError(
            "batch.toml experiment_1_2.copy_assets.relay 必须包含至少一项明确资源"
        )
    assets: list[AssetCopy] = []
    for index, item in enumerate(raw_assets, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"batch.toml experiment_1_2.copy_assets.relay[{index}] 必须是表"
            )
        raw_source = item.get("source")
        if not isinstance(raw_source, str) or not raw_source:
            raise ValueError(
                f"batch.toml experiment_1_2.copy_assets.relay[{index}].source 必须为非空字符串"
            )
        source_relative = Path(raw_source)
        if source_relative.is_absolute() or ".." in source_relative.parts:
            raise ValueError(
                f"batch.toml experiment_1_2.copy_assets.relay[{index}].source 必须是项目内相对路径"
            )
        source = (project_root_path / source_relative).resolve()
        if (
            not source.is_relative_to(project_root_path)
            or source.suffix.lower() not in _IMAGE_SUFFIXES
        ):
            raise ValueError(
                f"batch.toml experiment_1_2.copy_assets.relay[{index}].source 只能指向项目内 PNG 或 PDF"
            )
        destination = _resolve_asset_destination(
            paper_root,
            item.get("destination"),
            f"relay[{index}].destination",
            directory=False,
        )
        assets.append(AssetCopy(source=source, destination=destination))
    if len({item.destination for item in assets}) != len(assets):
        raise ValueError(
            "batch.toml experiment_1_2.copy_assets.relay 的 destination 不得重复"
        )
    return tuple(assets)


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """一项物理任务的编号和场景标识。"""

    number: int
    """从 1 开始的固定任务编号。"""

    scenario_id: str
    """manifest 和事件行必须使用的场景标识。"""


TASK_SPECS = (
    TaskSpec(1, "static_head_motion"),
    TaskSpec(2, "start_stop_6dof"),
    TaskSpec(3, "continuous_translation"),
    TaskSpec(4, "continuous_rotation"),
    TaskSpec(5, "occlusion_recovery"),
)
"""当前正式流水线要求的五项物理任务。"""


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """一个已映射 task session 的关键批次身份。"""

    task_number: int
    """该 session 唯一完成的任务编号。"""

    source_directory: str
    """`task_data_root` 下的版本化原始目录名。"""

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
class TaskDataEntry:
    """一个从规范目录名识别出的可选任务数据目录。"""

    directory: Path
    """位于 task_data_root 下的完整目录路径。"""

    task_number: int
    """目录名声明的任务编号。"""

    version: int
    """目录名中的数值版本；比较时不按字符串排序。"""

    timestamp: str
    """目录名中的采集时间，格式为 YYYYMMDD_HHMMSS。"""

    object_name: str
    """目录名中的对象标识。"""

    def to_dict(self) -> dict[str, Any]:
        """返回适合 CLI JSON 输出的目录摘要。"""

        return {
            "directory": self.directory.name,
            "task_number": self.task_number,
            "version": self.version,
            "version_label": f"v{self.version}",
            "timestamp": self.timestamp,
            "object": self.object_name,
        }


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

    selected_task_data: tuple[str, ...]
    """本批次自动或显式选择的五个源目录名。"""

    cache_hits: tuple[int, ...]
    """直接复用既有 Stage 1 工作簿的任务编号。"""

    rebuilt_tasks: tuple[int, ...]
    """本次重新执行 QC 并生成工作簿的任务编号。"""

    def to_dict(self) -> dict[str, Any]:
        """返回适合 CLI JSON 输出的普通字典。"""

        return {
            "passed": True,
            "batch_id": self.batch_id,
            "root": str(self.root),
            "sessions": [item.to_dict() for item in self.sessions],
            "selected_task_data": list(self.selected_task_data),
            "workbook_sha256": dict(self.workbook_sha256),
            "cache_hits": list(self.cache_hits),
            "rebuilt_tasks": list(self.rebuilt_tasks),
            "next_command": f"pixi run eval data exp1-2 promote {self.batch_id}",
        }


@dataclass(frozen=True, slots=True)
class TaskCacheRecord:
    """一个原始任务目录及其唯一 Stage 1 工作簿的冻结记录。"""

    task_number: int
    """任务编号。"""

    source_directory: str
    """`task_data_root` 下不可原地修改的原始目录名。"""

    workbook_directory: str
    """`task_workbook_root` 下保存该任务产物的目录名。"""

    workbook_name: str
    """任务工作簿文件名。"""

    workbook_sha256: str
    """已完整验证工作簿的 SHA-256。"""

    source_set_sha256: str
    """工作簿内冻结的原始来源集合 SHA-256。"""

    stage_fingerprint: str
    """生成工作簿所用 Stage 1 实现的内容指纹。"""

    source_snapshot: tuple[tuple[str, str], ...]
    """原始文件相对路径和行尾归一摘要组成的内容快照。"""

    workbook_size: int
    """工作簿字节数，用于发现缓存文件被替换。"""

    session: SessionSummary
    """原始 session 的正式批次身份。"""

    @property
    def workbook_relative_path(self) -> Path:
        """返回相对于工作簿缓存根目录的安全路径。"""

        return Path(self.workbook_directory) / self.workbook_name

    def to_dict(self) -> dict[str, Any]:
        """返回可稳定写入 JSON 的缓存记录。"""

        return {
            "schema": _TASK_CACHE_SCHEMA,
            "task_number": self.task_number,
            "source_directory": self.source_directory,
            "workbook_directory": self.workbook_directory,
            "workbook_name": self.workbook_name,
            "workbook_sha256": self.workbook_sha256,
            "source_set_sha256": self.source_set_sha256,
            "stage_fingerprint": self.stage_fingerprint,
            "source_snapshot": [list(item) for item in self.source_snapshot],
            "workbook_size": self.workbook_size,
            "session": self.session.to_dict(),
        }


class BatchToolError(RuntimeError):
    """Git 等外部工具未成功完成数据准备。"""


def list_task_data(root: Path | None = None) -> list[dict[str, Any]]:
    """列出 task_data_root 的目录名解析结果和 manifest 摘要。"""

    paths = load_batch_paths(root)
    if not paths.task_data_root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for session_dir in sorted(path for path in paths.task_data_root.iterdir() if path.is_dir()):
        try:
            entry = _parse_task_data_entry(session_dir)
        except ValueError as error:
            rows.append({"directory": session_dir.name, "recognized_name": False, "error": str(error)})
            continue
        manifest_path = session_dir / "manifest.json"
        if not manifest_path.is_file():
            rows.append(
                {
                    **entry.to_dict(),
                    "recognized_name": True,
                    "valid_manifest": False,
                    "error": "缺少 manifest.json",
                }
            )
            continue
        try:
            manifest = _read_json(manifest_path)
            python_state = _read_json(session_dir / "python_session.json").get("state")
            completed = manifest.get("completed_tasks")
            completed_numbers = [item.get("task_number") for item in completed] if isinstance(completed, list) else []
            rows.append(
                {
                    **entry.to_dict(),
                    "recognized_name": True,
                    "valid_manifest": True,
                    "session_id": manifest.get("session_id"),
                    "completed_tasks": completed_numbers,
                    "config_hash": manifest.get("config_hash"),
                    "python_state": python_state,
                    "variant_matrix_id": manifest.get("variant_matrix_id"),
                }
            )
        except (OSError, ValueError) as error:
            rows.append(
                {
                    **entry.to_dict(),
                    "recognized_name": True,
                    "valid_manifest": False,
                    "error": str(error),
                }
            )
    return rows


def _stage_fingerprint() -> str:
    """计算真正影响 Stage 1 内容的实现指纹，不绑定无关 Git 提交。"""

    eval_root = Path(__file__).resolve().parents[2]
    source_files = sorted(
        path
        for directory_name in ("contracts", "preprocess", "schema_v2")
        for path in (eval_root / directory_name).rglob("*.py")
    )
    digest = hashlib.sha256()
    for path in source_files:
        digest.update(path.relative_to(eval_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _normalized_file_sha256(path: Path) -> str:
    """流式计算按 LF 归一行尾后的文件摘要，忽略纯 CRLF 差异。"""

    digest = hashlib.sha256()
    pending_cr = False
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if pending_cr:
                # 上一块以 CR 结尾：只有当前块以 LF 开头才构成跨块 CRLF。
                if not chunk.startswith(b"\n"):
                    digest.update(b"\r")
                pending_cr = False
            if chunk.endswith(b"\r"):
                pending_cr = True
                chunk = chunk[:-1]
            digest.update(chunk.replace(b"\r\n", b"\n"))
    if pending_cr:
        digest.update(b"\r")
    return digest.hexdigest()


def _source_snapshot(source: Path) -> tuple[tuple[str, str], ...]:
    """按内容而非文件元数据发现版本目录被原地改写。

    只记录相对路径和行尾归一后的摘要：修改时间和纯 CRLF/LF 行尾变化都不算改写，
    复制、同步或还原原始归档不会误报；任何实质内容变化仍会被摘要捕获。
    """

    rows: list[tuple[str, str]] = []
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        rows.append((path.relative_to(source).as_posix(), _normalized_file_sha256(path)))
    return tuple(rows)


def _cache_directory(paths: BatchPaths, entry: TaskDataEntry) -> Path:
    """返回一个任务目录专属的 Stage 1 缓存目录。"""

    return paths.task_workbook_root / entry.directory.name


def _read_task_cache(
    paths: BatchPaths,
    entry: TaskDataEntry,
    summary: SessionSummary,
    stage_fingerprint: str,
) -> TaskCacheRecord | None:
    """验证轻量缓存记录和工作簿摘要；失效时返回空值并由调用方重建。"""

    cache_root = _cache_directory(paths, entry)
    metadata_path = cache_root / "cache.json"
    try:
        if entry.directory.is_symlink() or cache_root.is_symlink() or metadata_path.is_symlink():
            return None
        document = _read_json(metadata_path)
        record = _task_cache_from_document(document)
        expected_workbook_name = f"task_{entry.task_number}_complete.xlsx"
        if record.workbook_name != expected_workbook_name:
            return None
        workbook = paths.task_workbook_root / record.workbook_relative_path
        if (
            record.task_number != entry.task_number
            or record.source_directory != entry.directory.name
            or record.workbook_directory != entry.directory.name
            or record.session != summary
            or record.stage_fingerprint != stage_fingerprint
            or record.source_snapshot != _source_snapshot(entry.directory)
            or not workbook.is_file()
            or workbook.is_symlink()
            or workbook.stat().st_size != record.workbook_size
        ):
            return None
        return record
    except (KeyError, OSError, TypeError, ValueError):
        return None


def _build_task_cache(
    paths: BatchPaths,
    entry: TaskDataEntry,
    summary: SessionSummary,
    stage_fingerprint: str,
) -> TaskCacheRecord:
    """对单个任务执行一次完整 QC，并原子发布其唯一工作簿缓存。"""

    source = entry.directory
    require_task_sources((source,), TASK_SOURCE_FILE_NAMES)
    finalize_task_events(source)
    require_task_sources((source,), REQUIRED_FILE_NAMES)

    destination = _cache_directory(paths, entry)
    temporary = create_inherited_temp_directory(
        paths.task_workbook_root,
        f".{entry.directory.name}.tmp-",
    )
    workbook_name = f"task_{entry.task_number}_complete.xlsx"
    try:
        artifact = write_task_workbook(
            source,
            temporary / workbook_name,
            code_version=_git_code_version(paths.project_root),
        )
        record = TaskCacheRecord(
            task_number=entry.task_number,
            source_directory=entry.directory.name,
            workbook_directory=entry.directory.name,
            workbook_name=workbook_name,
            workbook_sha256=artifact.sha256,
            source_set_sha256=artifact.source_set_sha256,
            stage_fingerprint=stage_fingerprint,
            source_snapshot=_source_snapshot(source),
            workbook_size=artifact.path.stat().st_size,
            session=summary,
        )
        _write_json_atomic(temporary / "cache.json", record.to_dict())
        _replace_staged_batch(temporary, destination)
    except Exception:
        remove_tree_with_retry(temporary)
        raise
    return record


def _ensure_task_caches(
    paths: BatchPaths,
    entries: Sequence[TaskDataEntry],
    summaries: Sequence[SessionSummary],
    *,
    force: bool,
) -> tuple[tuple[TaskCacheRecord, ...], tuple[int, ...], tuple[int, ...]]:
    """按任务复用或重建工作簿缓存，并返回命中与重建编号。"""

    summary_by_task = {summary.task_number: summary for summary in summaries}
    stage_fingerprint = _stage_fingerprint()
    records: list[TaskCacheRecord] = []
    cache_hits: list[int] = []
    rebuilt_tasks: list[int] = []
    with _task_progress("Stage 1 cache", tuple(entry.directory for entry in entries)) as progress:
        for entry in entries:
            summary = summary_by_task[entry.task_number]
            record = None if force else _read_task_cache(
                paths,
                entry,
                summary,
                stage_fingerprint,
            )
            if record is None:
                progress.set_postfix_str(f"Task {entry.task_number}: rebuild")
                record = _build_task_cache(paths, entry, summary, stage_fingerprint)
                rebuilt_tasks.append(entry.task_number)
            else:
                progress.set_postfix_str(f"Task {entry.task_number}: hit")
                cache_hits.append(entry.task_number)
            records.append(record)
            progress.update()
    return tuple(records), tuple(cache_hits), tuple(rebuilt_tasks)


def _batch_manifest_document(
    batch_id: str,
    records: Sequence[TaskCacheRecord],
) -> dict[str, Any]:
    """构造只引用共享任务缓存的轻量批次组合清单。"""

    return {
        "schema": _BATCH_MANIFEST_SCHEMA,
        "batch_id": batch_id,
        "tasks": [record.to_dict() for record in records],
    }


def _task_cache_from_document(document: Mapping[str, Any]) -> TaskCacheRecord:
    """严格解析一个单任务缓存记录。"""

    if document.get("schema") != _TASK_CACHE_SCHEMA:
        raise ValueError("任务缓存 schema 不受支持")
    snapshot = document.get("source_snapshot")
    if not isinstance(snapshot, list):
        raise ValueError("任务缓存缺少 source_snapshot")
    session_document = document.get("session")
    if not isinstance(session_document, dict):
        raise ValueError("任务缓存缺少 session")
    session = SessionSummary(**session_document)
    if any(not isinstance(item, list) or len(item) != 2 for item in snapshot):
        raise ValueError("任务缓存的 source_snapshot 项格式非法")
    return TaskCacheRecord(
        task_number=int(document["task_number"]),
        source_directory=str(document["source_directory"]),
        workbook_directory=str(document["workbook_directory"]),
        workbook_name=str(document["workbook_name"]),
        workbook_sha256=str(document["workbook_sha256"]),
        source_set_sha256=str(document["source_set_sha256"]),
        stage_fingerprint=str(document["stage_fingerprint"]),
        source_snapshot=tuple(
            (str(item[0]), str(item[1]))
            for item in snapshot
        ),
        workbook_size=int(document["workbook_size"]),
        session=session,
    )


def _write_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    """以同目录临时文件原子发布 UTF-8 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_batch_records(
    batch_root: Path,
    paths: BatchPaths,
) -> tuple[str, tuple[TaskCacheRecord, ...]]:
    """读取轻量批次清单，并快速核对五项共享缓存仍可用。"""

    document = _read_json(batch_root / BATCH_MANIFEST_NAME)
    if document.get("schema") != _BATCH_MANIFEST_SCHEMA:
        raise ValueError("批次清单 schema 不受支持")
    batch_id = str(document.get("batch_id") or "")
    _require_batch_id(batch_id)
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != len(TASK_SPECS):
        raise ValueError("批次清单必须恰好包含 Task 1--5")
    records = tuple(
        _task_cache_from_document(item)
        for item in tasks
        if isinstance(item, dict)
    )
    if len(records) != len(TASK_SPECS):
        raise ValueError("批次清单包含非法任务记录")
    if [record.task_number for record in records] != [spec.number for spec in TASK_SPECS]:
        raise ValueError("批次清单任务必须按 1--5 唯一排序")

    for record in records:
        expected_name = f"task_{record.task_number}_complete.xlsx"
        if (
            Path(record.source_directory).name != record.source_directory
            or Path(record.workbook_directory).name != record.workbook_directory
            or record.workbook_directory != record.source_directory
            or record.workbook_name != expected_name
            or record.session.source_directory != record.source_directory
        ):
            raise ValueError(f"Task {record.task_number} 的缓存路径非法")
        source = paths.task_data_root / record.source_directory
        workbook = paths.task_workbook_root / record.workbook_relative_path
        metadata = paths.task_workbook_root / record.workbook_directory / "cache.json"
        if (
            source.is_symlink()
            or workbook.parent.is_symlink()
            or workbook.is_symlink()
            or metadata.is_symlink()
        ):
            raise ValueError(f"Task {record.task_number} 的缓存路径不得使用符号链接")
        if not source.is_dir():
            raise FileNotFoundError(source)
        if not workbook.is_file() or not metadata.is_file():
            raise FileNotFoundError(f"Task {record.task_number} 的工作簿缓存不完整")
        actual_cache = _task_cache_from_document(_read_json(metadata))
        if actual_cache != record:
            raise ValueError(f"Task {record.task_number} 的 batch.json 与 cache.json 不一致")
        if workbook.stat().st_size != record.workbook_size:
            raise ValueError(f"Task {record.task_number} 的工作簿大小与批次清单不一致")
        if _source_snapshot(source) != record.source_snapshot:
            raise ValueError(
                f"Task {record.task_number} 的版本目录内容已改变；请创建新的 vN 目录"
            )

    summaries = tuple(record.session for record in records)
    _validate_common_summaries(summaries)
    if _batch_id(summaries) != batch_id:
        raise ValueError("batch_id 与五项 session 组合不一致")
    return batch_id, records


def active_batch_id(active_root: Path) -> str | None:
    """只读返回活动批次 ID；缺少或损坏清单时返回空值。"""

    manifest = active_root / BATCH_MANIFEST_NAME
    if not manifest.is_file():
        return None
    try:
        document = _read_json(manifest)
    except (OSError, ValueError):
        return None
    value = document.get("batch_id")
    return str(value) if isinstance(value, str) and value else None


def load_active_batch(
    paths: BatchPaths,
) -> tuple[str, tuple[TaskCacheRecord, ...]]:
    """读取活动组合清单，并核对其五项共享缓存。"""

    return _load_batch_records(paths.active_root, paths)


def validate_active_data(
    paths: BatchPaths,
) -> tuple[tuple[SessionSummary, ...], tuple[StageOneQcReport, ...]]:
    """对活动批次的五个原始任务执行完整身份检查与硬 QC。"""

    _, records = load_active_batch(paths)
    task_dirs = tuple(
        paths.task_data_root / record.source_directory for record in records
    )
    summaries = _validate_task_directories(task_dirs)
    reports = _finalize_and_run_qc(task_dirs)
    return summaries, reports


def stage_batch(
    version: int | None = None,
    task_versions: Mapping[int, int] | None = None,
    object_name: str | None = None,
    *,
    root: Path | None = None,
    batch_id: str | None = None,
) -> BatchArtifact:
    """选择五项任务，并只为缓存缺失或失效的任务生成工作簿。"""

    paths = load_batch_paths(root)
    entries = select_task_data(
        root=root,
        version=version,
        task_versions=task_versions,
        object_name=object_name,
    )

    report_progress("stage: 已选择以下五项任务数据")
    for entry in entries:
        report_progress(f"  Task {entry.task_number}: {entry.directory.name}")
    _, summaries = _map_eval_sessions(tuple(entry.directory for entry in entries))
    _validate_task_data_names(entries, summaries)
    report_progress("stage: 核对五个原始 session 的批次身份")

    resolved_batch_id = batch_id or _batch_id(summaries)
    _require_batch_id(resolved_batch_id)
    records, cache_hits, rebuilt_tasks = _ensure_task_caches(
        paths,
        entries,
        summaries,
        force=False,
    )
    destination = paths.staging_root / resolved_batch_id
    temporary = create_inherited_temp_directory(paths.staging_root, f".{resolved_batch_id}.tmp-")
    try:
        _write_json_atomic(
            temporary / BATCH_MANIFEST_NAME,
            _batch_manifest_document(resolved_batch_id, records),
        )
        _replace_staged_batch(temporary, destination)
    except Exception:
        remove_tree_with_retry(temporary)
        raise

    report_progress(f"stage: 暂存批次已就绪：{resolved_batch_id}")
    return BatchArtifact(
        batch_id=resolved_batch_id,
        root=destination,
        sessions=summaries,
        workbook_sha256={record.workbook_name: record.workbook_sha256 for record in records},
        selected_task_data=tuple(entry.directory.name for entry in entries),
        cache_hits=cache_hits,
        rebuilt_tasks=rebuilt_tasks,
    )


def _replace_staged_batch(temporary: Path, destination: Path) -> None:
    """以已验证的新批次替换同名暂存批次，失败时恢复旧批次。"""

    backup: Path | None = None
    if destination.exists():
        backup = create_inherited_temp_directory(destination.parent, f".{destination.name}.previous-")
        backup.rmdir()
        destination.rename(backup)
    try:
        temporary.rename(destination)
    except Exception:
        if backup is not None and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    if backup is not None:
        remove_tree_with_retry(backup)


def promote_batch(batch_id: str | None = None, *, root: Path | None = None) -> dict[str, Any]:
    """原子切换轻量批次组合清单，并归档上一组合的分析产物。"""

    paths = load_batch_paths(root)
    resolved_batch_id = batch_id or _only_staged_batch(paths.staging_root)
    _require_batch_id(resolved_batch_id)
    staged = paths.staging_root / resolved_batch_id
    if not staged.is_dir():
        raise FileNotFoundError(f"找不到暂存批次：{staged}")
    report_progress("promote: 复核暂存批次清单与任务缓存")
    staged_id, _ = _load_batch_records(staged, paths)
    if staged_id != resolved_batch_id:
        raise ValueError("暂存目录名与 batch.json 的 batch_id 不一致")

    active = paths.active_root
    archive_parent = paths.archive_root
    archived: Path | None = None
    if active.exists() and not active.is_dir():
        raise NotADirectoryError(f"活动批次路径不是目录：{active}")
    active_manifest = active / BATCH_MANIFEST_NAME
    if active.is_dir() and not active_manifest.exists() and any(active.iterdir()):
        raise ValueError(
            "活动批次目录缺少 batch.json；请先迁移或清理旧 raw/workbooks 快照，禁止静默混用"
        )
    active.mkdir(parents=True, exist_ok=True)
    staged_manifest = staged / BATCH_MANIFEST_NAME
    current_batch_id: str | None = None
    if active_manifest.is_file():
        current_batch_id, _ = _load_batch_records(active, paths)
    if current_batch_id == resolved_batch_id:
        staged_manifest.replace(active_manifest)
        remove_tree_with_retry(staged)
        return {
            "passed": True,
            "active_batch": resolved_batch_id,
            "active_root": str(active),
            "archived_root": None,
            "next_command": "pixi run eval analyze exp1-2",
        }
    if current_batch_id is not None:
        archived = archive_parent / current_batch_id
        if archived.exists():
            raise FileExistsError(f"旧活动批次归档目标已存在，拒绝覆盖：{archived}")
        archive_temporary = create_inherited_temp_directory(
            archive_parent,
            f".{current_batch_id}.tmp-",
        )
        try:
            report_progress(f"promote: 归档旧活动清单到 {archived.name}")
            active_manifest.rename(archive_temporary / BATCH_MANIFEST_NAME)
            analysis = active / "analysis"
            if analysis.exists():
                analysis.rename(archive_temporary / "analysis")
            _replace_staged_batch(archive_temporary, archived)
        except Exception:
            if (archive_temporary / BATCH_MANIFEST_NAME).exists() and not active_manifest.exists():
                (archive_temporary / BATCH_MANIFEST_NAME).rename(active_manifest)
            archived_analysis = archive_temporary / "analysis"
            if archived_analysis.exists() and not (active / "analysis").exists():
                archived_analysis.rename(active / "analysis")
            if archive_temporary.exists():
                remove_tree_with_retry(archive_temporary)
            raise
    switched = False
    try:
        report_progress("promote: 切换新的活动组合清单")
        staged_manifest.replace(active_manifest)
        switched = True
    except Exception:
        if archived is not None and (archived / BATCH_MANIFEST_NAME).exists():
            (archived / BATCH_MANIFEST_NAME).rename(active_manifest)
            archived_analysis = archived / "analysis"
            if archived_analysis.exists():
                archived_analysis.rename(active / "analysis")
            if archived.exists() and not any(archived.iterdir()):
                archived.rmdir()
        raise
    if switched:
        # 清理暂存失败不再回滚已成功切换的活动清单，避免破坏可用批次；下次 stage 会覆盖同名暂存目录。
        remove_tree_with_retry(staged)

    report_progress("promote: 活动批次已切换")
    return {
        "passed": True,
        "active_batch": resolved_batch_id,
        "active_root": str(active),
        "archived_root": str(archived) if archived is not None else None,
        "next_command": "pixi run eval analyze exp1-2",
    }


def preprocess_current(
    *,
    root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """只重建活动组合中缺失或失效的任务工作簿；可显式强制全部重建。"""

    report_progress("preprocess: 检查五项独立 Stage 1 缓存")
    paths = load_batch_paths(root)
    batch_id, current_records = _load_batch_records(paths.active_root, paths)
    entries = tuple(
        _parse_task_data_entry(paths.task_data_root / record.source_directory)
        for record in current_records
    )
    summaries = tuple(record.session for record in current_records)
    records, cache_hits, rebuilt_tasks = _ensure_task_caches(
        paths,
        entries,
        summaries,
        force=force,
    )
    _write_json_atomic(
        paths.active_root / BATCH_MANIFEST_NAME,
        _batch_manifest_document(batch_id, records),
    )
    return {
        "passed": True,
        "output_root": str(paths.task_workbook_root),
        "workbook_sha256": {record.workbook_name: record.workbook_sha256 for record in records},
        "cache_hits": list(cache_hits),
        "rebuilt_tasks": list(rebuilt_tasks),
        "next_command": "pixi run eval analyze exp1-2",
    }


def select_task_data(
    *,
    root: Path | None = None,
    version: int | None = None,
    task_versions: Mapping[int, int] | None = None,
    object_name: str | None = None,
) -> tuple[TaskDataEntry, ...]:
    """按任务选择指定版本或最高版本中的最新采集目录。"""

    paths = load_batch_paths(root)
    if not paths.task_data_root.is_dir():
        raise FileNotFoundError(f"任务数据目录不存在：{paths.task_data_root}")
    normalized_version = _require_version(version, "version") if version is not None else None
    normalized_task_versions = _normalize_task_versions(task_versions)
    entries: list[TaskDataEntry] = []
    for path in paths.task_data_root.iterdir():
        if not path.is_dir():
            continue
        try:
            entries.append(_parse_task_data_entry(path))
        except ValueError:
            continue
    if not entries:
        raise ValueError(f"task_data_root 中没有可识别的任务目录：{paths.task_data_root}")

    selected_object = _select_object(
        entries,
        normalized_version,
        normalized_task_versions,
        object_name,
    )
    selected: list[TaskDataEntry] = []
    for spec in TASK_SPECS:
        candidates = [
            entry
            for entry in entries
            if entry.task_number == spec.number and entry.object_name == selected_object
        ]
        requested_version = normalized_task_versions.get(spec.number, normalized_version)
        if requested_version is None and candidates:
            requested_version = max(entry.version for entry in candidates)
        candidates = [entry for entry in candidates if entry.version == requested_version]
        if not candidates:
            label = f"v{requested_version}" if requested_version is not None else "任意版本"
            raise ValueError(f"对象 {selected_object} 的任务 {spec.number} 缺少 {label} 数据")
        selected.append(max(candidates, key=lambda entry: entry.timestamp))
    return tuple(selected)


def _parse_task_data_entry(directory: Path) -> TaskDataEntry:
    """解析并验证一个 task_data 直接子目录的冻结名称。"""

    resolved = directory.resolve()
    if not resolved.is_relative_to(directory.parent.resolve()):
        raise ValueError("任务数据目录不得通过链接指向 task_data_root 外部")
    match = _TASK_DATA_PATTERN.fullmatch(directory.name)
    if match is None:
        raise ValueError(
            "目录名必须为 task_<1-5>_v<正整数>_<YYYYMMDD_HHMMSS>_<物体>"
        )
    timestamp = f"{match.group('date')}_{match.group('time')}"
    try:
        datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
    except ValueError as error:
        raise ValueError(f"目录时间无效：{timestamp}") from error
    return TaskDataEntry(
        directory=resolved,
        task_number=int(match.group("task")),
        version=int(match.group("version")),
        timestamp=timestamp,
        object_name=match.group("object"),
    )


def _select_object(
    entries: Sequence[TaskDataEntry],
    version: int | None,
    task_versions: Mapping[int, int],
    requested_object: str | None,
) -> str:
    """选择唯一能覆盖五项任务的对象，多个对象时要求显式指定。"""

    if requested_object is not None:
        if not requested_object.strip():
            raise ValueError("--object 不能为空")
        return requested_object
    complete_objects: list[str] = []
    for candidate_object in sorted({entry.object_name for entry in entries}):
        covered = set()
        for entry in entries:
            required = task_versions.get(entry.task_number, version)
            if entry.object_name == candidate_object and (required is None or entry.version == required):
                covered.add(entry.task_number)
        if covered == {spec.number for spec in TASK_SPECS}:
            complete_objects.append(candidate_object)
    if len(complete_objects) == 1:
        return complete_objects[0]
    if not complete_objects:
        raise ValueError("没有一个对象在当前版本条件下完整覆盖任务 1--5")
    choices = ", ".join(complete_objects)
    raise ValueError(f"多个对象满足选择条件，请使用 --object 指定：{choices}")


def _normalize_task_versions(task_versions: Mapping[int, int] | None) -> dict[int, int]:
    """验证逐任务版本覆盖，并返回可安全读取的普通字典。"""

    normalized: dict[int, int] = {}
    for task_number, version in (task_versions or {}).items():
        if isinstance(task_number, bool) or not isinstance(task_number, int) or not 1 <= task_number <= 5:
            raise ValueError("task_versions 的任务编号必须在 1--5 内")
        normalized[task_number] = _require_version(version, f"任务 {task_number} 版本")
    return normalized


def _require_version(version: int, label: str) -> int:
    """要求版本为不带前导语义的正整数。"""

    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError(f"{label} 必须为正整数")
    return version


def _validate_task_data_names(
    entries: Sequence[TaskDataEntry],
    summaries: Sequence[SessionSummary],
) -> None:
    """确认目录标签与 manifest 的任务、时间和对象身份一致。"""

    summary_by_source = {summary.source_directory: summary for summary in summaries}
    for entry in entries:
        summary = summary_by_source[entry.directory.name]
        if summary.task_number != entry.task_number:
            raise ValueError(
                f"{entry.directory.name} 的 manifest 未对应任务 {entry.task_number}"
            )
        match = _SESSION_TIME_PATTERN.match(summary.session_id)
        session_timestamp = f"{match.group('date')}_{match.group('time')}" if match else ""
        if entry.timestamp != session_timestamp:
            raise ValueError(f"{entry.directory.name} 的时间与 manifest.session_id 不一致")
        if entry.object_name != summary.object_id:
            raise ValueError(f"{entry.directory.name} 的物体与 manifest.object_id 不一致")


def _map_eval_sessions(task_dirs: Sequence[Path]) -> tuple[tuple[Path, ...], tuple[SessionSummary, ...]]:
    """按 completed_tasks 自动把五个任务数据目录映射到任务 1--5。"""

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
            _session_summary(task_dir, spec),
        )
    if sorted(mapped) != [1, 2, 3, 4, 5]:
        raise ValueError(f"输入 session 必须恰好覆盖任务 1--5，实际为 {sorted(mapped)}")
    ordered_dirs = tuple(mapped[number][0] for number in range(1, 6))
    summaries = tuple(mapped[number][1] for number in range(1, 6))
    _validate_common_summaries(summaries)
    return ordered_dirs, summaries


def _validate_task_directories(
    task_dirs: Sequence[Path],
) -> tuple[SessionSummary, ...]:
    """检查五个目录的任务映射和当前批次公共身份。"""

    if len(task_dirs) != len(TASK_SPECS):
        raise ValueError("正式批次必须恰好包含任务 1--5 五个目录")
    summaries = tuple(
        _session_summary(path, spec)
        for path, spec in zip(task_dirs, TASK_SPECS, strict=True)
    )
    _validate_common_summaries(summaries)
    return summaries


def _validate_common_summaries(
    summaries: Sequence[SessionSummary],
) -> None:
    """检查 session 唯一性、正式状态和跨 task 公共身份。"""

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
) -> SessionSummary:
    """读取一个 task manifest，并确认它只完成对应任务。"""

    if not task_dir.is_dir():
        raise FileNotFoundError(f"task/session 目录不存在：{task_dir}")
    manifest = _read_json(task_dir / "manifest.json")
    session_id = _nonempty_text(manifest, "session_id")
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
        source_directory=task_dir.name,
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
    with _task_progress("events", task_dirs) as progress:
        for spec, task_dir in zip(TASK_SPECS, task_dirs, strict=True):
            progress.set_postfix_str(f"Task {spec.number}")
            finalize_task_events(task_dir)
            progress.update()
    require_task_sources(tuple(task_dirs), REQUIRED_FILE_NAMES)
    reports: list[StageOneQcReport] = []
    with _task_progress("QC", task_dirs) as progress:
        for spec, task_dir in zip(TASK_SPECS, task_dirs, strict=True):
            progress.set_postfix_str(f"Task {spec.number}")
            reports.append(run_task_qc(task_dir))
            progress.update()
    return tuple(reports)


def _batch_id(summaries: Sequence[SessionSummary]) -> str:
    """用五项任务 session 时间构造确定且能区分局部重采的批次名。"""

    timestamps: list[str] = []
    for number in range(1, 6):
        session = next((item for item in summaries if item.task_number == number), None)
        if session is None:
            raise ValueError(f"正式批次缺少任务 {number} session，无法构造 batch_id")
        match = _SESSION_TIME_PATTERN.match(session.session_id)
        if match is None:
            raise ValueError(f"任务 {number} session_id 缺少 YYYYMMDD_HHMMSS 前缀：{session.session_id}")
        timestamps.append(f"{match.group('date')}_{match.group('time')}")
    return "batch_" + "_".join(timestamps)


def _require_batch_id(batch_id: str) -> None:
    """拒绝旧格式和任意路径片段。"""

    if _BATCH_ID_PATTERN.fullmatch(batch_id) is None:
        raise ValueError("batch_id 必须按任务 1--5 写为 batch_YYYYMMDD_HHMMSS_... 格式")


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


def report_progress(message: str) -> None:
    """向终端 stderr 写入不会干扰 JSON 输出的阶段提示。"""

    if sys.stderr.isatty():
        tqdm.write(f"[eval] {message}", file=sys.stderr)


def _task_progress(description: str, task_dirs: Sequence[Path]) -> tqdm:
    """创建五项物理任务的交互式进度条。"""

    return stage_progress(description, len(task_dirs), "task")


def stage_progress(description: str, total: int, unit: str) -> tqdm:
    """创建仅在交互终端显示的 stderr 进度条。"""

    return tqdm(
        total=total,
        desc=f"[eval] {description}",
        unit=unit,
        dynamic_ncols=True,
        file=sys.stderr,
        disable=not sys.stderr.isatty(),
    )


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


__all__ = [
    "ArtifactDestination",
    "AssetCopy",
    "BATCH_MANIFEST_NAME",
    "BatchArtifact",
    "BatchPaths",
    "BatchToolError",
    "EXPECTED_MATRIX_ID",
    "SessionSummary",
    "TASK_SPECS",
    "TaskDataEntry",
    "TaskSpec",
    "active_batch_id",
    "list_task_data",
    "load_batch_paths",
    "load_active_batch",
    "preprocess_current",
    "promote_batch",
    "project_root",
    "report_progress",
    "select_task_data",
    "stage_batch",
    "stage_progress",
    "validate_active_data",
]
