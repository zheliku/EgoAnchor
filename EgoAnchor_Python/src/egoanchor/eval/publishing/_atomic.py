"""Stage 3 一个或多个目录的联合原子发布工具。"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar

from .._filesystem import create_inherited_temp_directory, remove_tree_with_retry


_Result = TypeVar("_Result")


def paths_overlap(left: Path, right: Path) -> bool:
    """判断两个规范路径是否相同或互为祖先。

    参数：
        left: 第一个待比较路径。
        right: 第二个待比较路径。
    """

    left_resolved = left.expanduser().resolve()
    right_resolved = right.expanduser().resolve()
    return (
        left_resolved == right_resolved
        or left_resolved.is_relative_to(right_resolved)
        or right_resolved.is_relative_to(left_resolved)
    )


def validate_output_boundary(input_root: Path, output_root: Path, label: str) -> Path:
    """拒绝输出与只读 CSV 输入树发生任意方向的覆盖。

    参数：
        input_root: Stage 2 CSV 输入根目录。
        output_root: 待发布目录。
        label: 错误消息使用的产物名称。
    """

    root = input_root.expanduser().resolve()
    destination = output_root.expanduser().resolve()
    if paths_overlap(root, destination):
        raise ValueError(f"{label}输出目录不得与 CSV 输入目录重叠")
    return destination


def _cleanup(path: Path | None) -> None:
    """尽力清理已提交后的临时/备份目录，不反转成功状态。

    参数：
        path: 由本发布调用创建的临时目录；为空时不操作。
    """

    if path is None or not path.exists():
        return
    try:
        remove_tree_with_retry(path)
    except OSError:
        # Windows 索引器短暂占用已废弃 backup 时，正式提交仍视为成功。
        pass


def atomic_publish_directories(
    destinations: Sequence[Path],
    builders: Sequence[Callable[[Path], _Result]],
) -> tuple[_Result, ...]:
    """先构建全部目录，再联合替换正式目录；构建失败不触碰旧产物。

    参数：
        destinations: 一个或多个互不重叠的正式输出目录。
        builders: 与输出目录一一对应、只写给定 staging 目录的构建函数。
    """

    if not destinations or len(destinations) != len(builders):
        raise ValueError("原子发布的输出目录与 builder 必须非空且一一对应")
    normalized = tuple(path.expanduser().resolve() for path in destinations)
    for index, left in enumerate(normalized):
        for right in normalized[index + 1 :]:
            if paths_overlap(left, right):
                raise ValueError("联合发布的输出目录不得相同或互相嵌套")
    for destination in normalized:
        destination.parent.mkdir(parents=True, exist_ok=True)

    stage_parents: list[Path] = []
    stages: list[Path] = []
    results: list[_Result] = []
    try:
        for destination, builder in zip(normalized, builders, strict=True):
            stage_parent = create_inherited_temp_directory(
                destination.parent,
                f".{destination.name}-stage-",
            )
            stage = stage_parent / "payload"
            stage.mkdir()
            stage_parents.append(stage_parent)
            stages.append(stage)
            results.append(builder(stage))
    except Exception:
        for stage_parent in stage_parents:
            _cleanup(stage_parent)
        raise

    backup_parents: list[Path | None] = [None] * len(normalized)
    backups: list[Path | None] = [None] * len(normalized)
    moved_backups: list[int] = []
    try:
        for index, destination in enumerate(normalized):
            if not destination.exists():
                continue
            backup_parent = create_inherited_temp_directory(
                destination.parent,
                f".{destination.name}-backup-",
            )
            backup = backup_parent / "payload"
            backup_parents[index] = backup_parent
            backups[index] = backup
            os.replace(destination, backup)
            moved_backups.append(index)
    except Exception:
        for index in reversed(moved_backups):
            moved_backup = backups[index]
            if (
                moved_backup is not None
                and moved_backup.exists()
                and not normalized[index].exists()
            ):
                os.replace(moved_backup, normalized[index])
        for path in (*stage_parents, *(path for path in backup_parents if path is not None)):
            _cleanup(path)
        raise

    committed: list[int] = []
    try:
        for index, (stage, destination) in enumerate(zip(stages, normalized, strict=True)):
            os.replace(stage, destination)
            committed.append(index)
    except Exception:
        for index in reversed(committed):
            if normalized[index].exists() and not stages[index].exists():
                os.replace(normalized[index], stages[index])
        for index in reversed(moved_backups):
            moved_backup = backups[index]
            if (
                moved_backup is not None
                and moved_backup.exists()
                and not normalized[index].exists()
            ):
                os.replace(moved_backup, normalized[index])
        for path in (*stage_parents, *(path for path in backup_parents if path is not None)):
            _cleanup(path)
        raise

    for path in (*stage_parents, *(path for path in backup_parents if path is not None)):
        _cleanup(path)
    return tuple(results)


__all__ = ["atomic_publish_directories", "paths_overlap", "validate_output_boundary"]
