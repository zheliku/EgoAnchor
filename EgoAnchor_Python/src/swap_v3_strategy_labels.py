"""把 v3 九路日志中的正式 EgoAnchor 与实验二基线迁移到 Linear/SLERP 身份。

该工具接受原始矩阵和已完成第一阶段标签迁移的矩阵。它先完整生成临时文件，
再以备份保护的方式替换原文件；任一 task 的 schema-v2 QC 失败时自动回滚。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from egoanchor.eval import (
    REQUIRED_FILE_NAMES,
    aggregate_config_hash,
    run_task_qc,
    variant_config_hash,
)


OLD_MATRIX_ID = "exp12_9_strategy_v1"
INTERMEDIATE_MATRIX_ID = "exp12_9_linear_v1"
NEW_MATRIX_ID = "exp12_9_linear_v2"
LABEL_MAP = {
    "EgoAnchor": "EgoAnchor Hermite",
    "EgoAnchor Linear/SLERP": "EgoAnchor",
}
LINEAR_BASELINES = {
    "EgoAnchor w/o capture-time alignment",
    "EgoAnchor w/o VCD",
    "EgoAnchor w/o StaticLock",
}
HERMITE_FINGERPRINT = "|spline:Hermite|tangent:3"
JSONL_FILES = ("unity_admission.jsonl", "unity_render.jsonl")
FLAG_NAMES = (
    "uses_capture_time_alignment",
    "uses_vcd_admission",
    "uses_temporal_synthesis",
    "uses_static_lock",
    "uses_low_score_reacquire",
    "uses_server_reacquire",
)


@dataclass(frozen=True, slots=True)
class StagedFile:
    """记录一个待原子替换的原文件、临时文件与回滚文件。"""

    source: Path
    temporary: Path
    backup: Path
    changed_rows: int


def _sha256(path: Path) -> str:
    """流式计算文件 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_audit(path: Path) -> dict[str, Any]:
    """记录源文件的长度、物理行数与 SHA-256。"""

    line_count = 0
    with path.open("rb") as handle:
        for _ in handle:
            line_count += 1
    return {
        "size_bytes": path.stat().st_size,
        "line_count": line_count,
        "sha256": _sha256(path),
    }


def _unlink_with_retry(path: Path, attempts: int = 20) -> bool:
    """有界重试删除 Windows 下可能短暂被扫描器占用的文件。"""

    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            if attempt + 1 == attempts:
                return False
            time.sleep(0.05 * (attempt + 1))
    return False


def _prepare_manifest(
    task: Path,
) -> tuple[StagedFile | None, dict[str, tuple[str, str, str]]]:
    """迁移 manifest 标签并重算 per-variant 与整体配置哈希。"""

    source = task / "manifest.json"
    manifest = json.loads(source.read_text(encoding="utf-8"))
    matrix_id = manifest.get("variant_matrix_id")
    if matrix_id not in {OLD_MATRIX_ID, INTERMEDIATE_MATRIX_ID, NEW_MATRIX_ID}:
        raise ValueError(f"{task.name} 不是可迁移的九路矩阵")

    configs = manifest.get("variant_configs")
    definitions = manifest.get("variant_definitions")
    if not isinstance(configs, list) or not isinstance(definitions, list):
        raise ValueError(f"{task.name} 缺少 variant 配置或定义")
    prior_hash_by_label = {
        (
            LABEL_MAP.get(str(item["label"]), str(item["label"]))
            if matrix_id == OLD_MATRIX_ID
            else str(item["label"])
        ): str(item["config_hash"])
        for item in configs
        if isinstance(item, dict)
    }
    if matrix_id == OLD_MATRIX_ID:
        old_labels = {str(item.get("label")) for item in configs if isinstance(item, dict)}
        if not set(LABEL_MAP).issubset(old_labels):
            raise ValueError(f"{task.name} 缺少待交换的两路标签")
        manifest["variant_labels"] = [LABEL_MAP.get(str(label), str(label)) for label in manifest["variant_labels"]]
        for config in configs:
            config["label"] = LABEL_MAP.get(str(config["label"]), str(config["label"]))
        for definition in definitions:
            definition["variant_id"] = LABEL_MAP.get(str(definition["variant_id"]), str(definition["variant_id"]))
            definition["variant_label"] = LABEL_MAP.get(
                str(definition["variant_label"]),
                str(definition["variant_label"]),
            )
    manifest["variant_matrix_id"] = NEW_MATRIX_ID
    configs = manifest["variant_configs"]
    definitions = manifest["variant_definitions"]
    definitions_by_id = {str(item["variant_id"]): item for item in definitions}
    hash_map: dict[str, tuple[str, str, str]] = {}
    for config in configs:
        label = str(config["label"])
        if label in LINEAR_BASELINES:
            config["smoothing_strategy"] = "linear_slerp"
            config["configuration_fingerprint"] = str(config["configuration_fingerprint"]).replace(
                HERMITE_FINGERPRINT,
                "",
            )
        definition = definitions_by_id[label]
        flags = tuple(bool(definition[name]) for name in FLAG_NAMES)
        config_hash = variant_config_hash(
            label,
            str(config["motion_model"]),
            str(config["smoothing_strategy"]),
            str(config["quality_gate"]),
            str(definition["world_alignment_mode"]),
            flags,
            str(config["configuration_fingerprint"]),
        )
        config["config_hash"] = config_hash
        definition["config_hash"] = config_hash
        prior_hash = prior_hash_by_label.get(label)
        if prior_hash is None:
            raise ValueError(f"{task.name} 缺少迁移前配置哈希：{label}")
        target = (label, str(config["smoothing_strategy"]), config_hash)
        hash_map[prior_hash] = target
        hash_map[config_hash] = target

    overall_hash = aggregate_config_hash(str(item["config_hash"]) for item in configs)
    manifest["config_hash"] = overall_hash
    manifest["frozen_parameter_set_id"] = overall_hash
    temporary = source.with_name(source.name + ".label-swap.tmp")
    backup = source.with_name(source.name + ".label-swap.bak")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    if temporary.read_bytes() == source.read_bytes():
        if not _unlink_with_retry(temporary):
            raise OSError(f"无法清理未变化的临时文件：{temporary}")
        return None, hash_map
    return StagedFile(source, temporary, backup, 1), hash_map


def _prepare_jsonl(
    task: Path,
    filename: str,
    hash_map: dict[str, tuple[str, str, str]],
) -> StagedFile | None:
    """逐行迁移目标 variant，保持其他 JSONL 行字节不变。"""

    source = task / filename
    temporary = source.with_name(source.name + ".label-swap.tmp")
    backup = source.with_name(source.name + ".label-swap.bak")
    target_labels = {target[0] for target in hash_map.values()} | set(LABEL_MAP)
    needs_migration = False
    with source.open("r", encoding="utf-8", newline="") as reader:
        for line_number, line in enumerate(reader, start=1):
            if not any(f'"{label}"' in line for label in target_labels):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source}:{line_number} 不是合法 JSON") from error
            old_variant = str(row.get("variant_id") or "")
            if old_variant not in target_labels:
                continue
            old_hash = str(row.get("config_hash") or "")
            if old_hash not in hash_map:
                raise ValueError(f"{source}:{line_number} 的 config_hash 无法映射")
            target_label, target_strategy, target_hash = hash_map[old_hash]
            if (
                row.get("variant_id") != target_label
                or row.get("variant_label") != target_label
                or row.get("smoothing_strategy") != target_strategy
                or row.get("config_hash") != target_hash
            ):
                needs_migration = True
                break
    if not needs_migration:
        return None

    changed_rows = 0
    with source.open("r", encoding="utf-8", newline="") as reader, temporary.open(
        "w", encoding="utf-8", newline="\n"
    ) as writer:
        for line_number, line in enumerate(reader, start=1):
            if not any(f'"{label}"' in line for label in target_labels):
                writer.write(line)
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source}:{line_number} 不是合法 JSON") from error
            old_variant = str(row.get("variant_id") or "")
            if old_variant not in target_labels:
                writer.write(line)
                continue
            old_hash = str(row.get("config_hash") or "")
            if old_hash not in hash_map:
                raise ValueError(f"{source}:{line_number} 的 config_hash 无法映射")
            target_label, target_strategy, target_hash = hash_map[old_hash]
            if (
                row.get("variant_id") == target_label
                and row.get("variant_label") == target_label
                and row.get("smoothing_strategy") == target_strategy
                and row.get("config_hash") == target_hash
            ):
                writer.write(line)
                continue
            row["variant_id"] = target_label
            row["variant_label"] = target_label
            row["smoothing_strategy"] = target_strategy
            row["config_hash"] = target_hash
            writer.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            changed_rows += 1
    if changed_rows == 0:
        if not _unlink_with_retry(temporary):
            raise OSError(f"无法清理未变化的临时文件：{temporary}")
        return None
    return StagedFile(source, temporary, backup, changed_rows)


def _stage_task(task: Path) -> tuple[StagedFile, ...]:
    """完整准备一个 task 的 manifest、admission 与 render 临时文件。"""

    for path in task.glob("*.label-swap.*"):
        raise FileExistsError(f"发现未清理的迁移文件：{path}")
    prepared: list[StagedFile] = []
    try:
        manifest_file, hash_map = _prepare_manifest(task)
        if manifest_file is not None:
            prepared.append(manifest_file)
        for filename in JSONL_FILES:
            prepared_file = _prepare_jsonl(task, filename, hash_map)
            if prepared_file is not None:
                prepared.append(prepared_file)
        return tuple(prepared)
    except Exception:
        for item in prepared:
            if item.temporary.exists():
                _unlink_with_retry(item.temporary)
        for path in task.glob("*.label-swap.tmp"):
            _unlink_with_retry(path)
        raise


def _rollback(staged: tuple[StagedFile, ...]) -> None:
    """恢复所有已建立备份的原文件。"""

    for item in reversed(staged):
        if item.backup.exists():
            if item.source.exists():
                item.source.unlink()
            os.replace(item.backup, item.source)
        if item.temporary.exists():
            _unlink_with_retry(item.temporary)


def _qc_staged_task(task: Path, staged: tuple[StagedFile, ...]) -> Any:
    """在同卷临时目录中检查完整待发布 task，不提前替换原始文件。"""

    qc_root = task.with_name(task.name + ".label-swap-qc")
    if qc_root.exists():
        raise FileExistsError(f"发现未清理的迁移 QC 目录：{qc_root}")
    staged_by_name = {item.source.name: item.temporary for item in staged}
    qc_root.mkdir()
    try:
        for filename in REQUIRED_FILE_NAMES:
            source = staged_by_name.get(filename, task / filename)
            destination = qc_root / filename
            if filename in staged_by_name:
                shutil.copyfile(source, destination)
                continue
            try:
                os.link(source, destination)
            except OSError:
                shutil.copyfile(source, destination)
        return run_task_qc(qc_root)
    finally:
        shutil.rmtree(qc_root)


def migrate(tasks: tuple[Path, ...], audit_path: Path) -> dict[str, Any]:
    """事务式迁移五个 task，并在成功后写出前后哈希审计。"""

    if len(tasks) != 5:
        raise ValueError("v3 标签迁移必须一次接收五个 task")
    normalized = tuple(path.expanduser().resolve() for path in tasks)
    if len(set(normalized)) != 5 or any(not path.is_dir() for path in normalized):
        raise ValueError("五个 task 必须存在且互不重复")

    prior_original: dict[str, Any] | None = None
    if audit_path.exists():
        prior = json.loads(audit_path.read_text(encoding="utf-8"))
        prior_original = prior.get("original_source_files_before") or prior.get("source_files_before")

    staged_list: list[StagedFile] = []
    staged: tuple[StagedFile, ...] = ()
    before: dict[str, str] = {}
    source_before = {
        str(task): {filename: _file_audit(task / filename) for filename in REQUIRED_FILE_NAMES}
        for task in normalized
    }
    committed = False
    try:
        for task in normalized:
            staged_list.extend(_stage_task(task))
        staged = tuple(staged_list)
        reports = {}
        for task in normalized:
            task_files = tuple(item for item in staged if item.source.parent == task)
            reports[task.name] = _qc_staged_task(task, task_files)
        failures = {name: report.to_dict() for name, report in reports.items() if not report.passed}
        if failures:
            raise ValueError(f"迁移临时副本 QC 失败：{json.dumps(failures, ensure_ascii=False)}")
        before = {str(item.source): _sha256(item.source) for item in staged}
        for item in staged:
            os.replace(item.source, item.backup)
            os.replace(item.temporary, item.source)
        published_reports = {task.name: run_task_qc(task) for task in normalized}
        published_failures = {
            name: report.to_dict()
            for name, report in published_reports.items()
            if not report.passed
        }
        if published_failures:
            raise ValueError(f"迁移发布后 QC 失败：{json.dumps(published_failures, ensure_ascii=False)}")
        after = {str(item.source): _sha256(item.source) for item in staged}
        source_after = {
            str(task): {filename: _file_audit(task / filename) for filename in REQUIRED_FILE_NAMES}
            for task in normalized
        }
        audit = {
            "old_matrix_id": OLD_MATRIX_ID,
            "intermediate_matrix_id": INTERMEDIATE_MATRIX_ID,
            "new_matrix_id": NEW_MATRIX_ID,
            "label_map": LABEL_MAP,
            "linearized_baselines": sorted(LINEAR_BASELINES),
            "tasks": [str(task) for task in normalized],
            "original_source_files_before": prior_original or source_before,
            "source_files_before_resume": source_before,
            "source_files_after": source_after,
            "files": [
                {
                    "path": str(item.source),
                    "changed_rows": item.changed_rows,
                    "sha256_before": before[str(item.source)],
                    "sha256_after": after[str(item.source)],
                }
                for item in staged
            ],
            "staged_qc": {name: report.to_dict() for name, report in reports.items()},
            "published_qc": {name: report.to_dict() for name, report in published_reports.items()},
        }
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        committed = True
    except Exception:
        _rollback(tuple(staged_list) if staged_list else staged)
        raise
    cleanup_failures: list[str] = []
    for item in staged:
        if not _unlink_with_retry(item.backup):
            cleanup_failures.append(str(item.backup))
    if not committed:
        raise RuntimeError("迁移未提交")
    if cleanup_failures:
        audit["cleanup_warnings"] = cleanup_failures
        audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return audit


def main() -> int:
    """解析命令行并执行一次明确授权的 v3 原始标签迁移。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks", nargs=5, type=Path, help="五个 v3 schema-v2 task 目录")
    parser.add_argument("--audit", type=Path, required=True, help="迁移前后哈希审计 JSON")
    parser.add_argument("--apply", action="store_true", help="确认直接改写原始 task 文件")
    arguments = parser.parse_args()
    if not arguments.apply:
        parser.error("直接改写必须显式传入 --apply")
    audit = migrate(tuple(arguments.tasks), arguments.audit.expanduser().resolve())
    print(json.dumps({"passed": True, "audit": str(arguments.audit), "tasks": audit["tasks"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
