"""离线分析各阶段共享的原子目录文件系统辅助。"""

from __future__ import annotations

import os
import shutil
import stat
import time
import uuid
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


_TEMP_DIRECTORY_ATTEMPTS = 32
"""随机临时目录发生名称碰撞时的最大尝试次数。"""

_WINDOWS_FILE_RETRY_ATTEMPTS = 12
"""Windows 索引器或防病毒短暂占用目录时的最大重试次数。"""

_WINDOWS_FILE_RETRY_DELAY_SECONDS = 0.25
"""目录清理重试的基础等待秒数。"""

_WINDOWS_REPARSE_POINT_ATTRIBUTE = 0x0400
"""Windows ``FILE_ATTRIBUTE_REPARSE_POINT`` 的稳定数值。"""


@dataclass(frozen=True, slots=True)
class DirectoryReplaceResult:
    """记录目录发布是否替换旧版本，以及旧版本是否清理完成。"""

    destination: Path
    """已成功提交的新活动目录。"""

    replaced_existing: bool
    """本次发布前目标目录是否已存在。"""

    retained_backup: Path | None
    """旧版本清理失败时保留的可审计备份目录。"""

    backup_cleanup_error: str | None
    """旧版本清理失败的错误文本；清理成功时为 ``None``。"""


class DirectoryRollbackError(RuntimeError):
    """新目录提交和旧目录恢复都失败时的可恢复错误。"""

    def __init__(
        self,
        *,
        destination: Path,
        backup: Path,
        publish_error: Exception,
        rollback_error: Exception,
    ) -> None:
        """保留提交与回滚两个异常，并明确给出仍可恢复的备份路径。"""

        self.destination = destination
        """未能完成发布的活动目录路径。"""

        self.backup = backup
        """包含发布前版本、必须人工保留的备份目录。"""

        self.publish_error = publish_error
        """新目录重命名到活动路径时的原始异常。"""

        self.rollback_error = rollback_error
        """把备份恢复到活动路径时的异常。"""

        super().__init__(
            f"目录发布失败且旧版本回滚也失败；请保留备份 {backup} 并人工恢复到 "
            f"{destination}。提交错误：{publish_error!r}；回滚错误：{rollback_error!r}"
        )


def create_inherited_temp_directory(parent: Path, prefix: str) -> Path:
    """在父目录下创建继承其 ACL 的随机临时目录。

    参数：
        parent: 已验证的正式输出父目录。
        prefix: 便于失败审计和清理的临时目录前缀。

    返回：
        已创建且调用方独占的临时目录。
    """

    root = parent.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(_TEMP_DIRECTORY_ATTEMPTS):
        candidate = root / f"{prefix}{uuid.uuid4().hex}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise OSError(f"无法在 {root} 创建唯一临时目录")


def remove_tree_with_retry(path: Path) -> None:
    """删除目录树，并对 Windows 短暂共享锁做有界重试。

    参数：
        path: 只能是调用方已验证的 staging 或 backup 目录。
    """

    for attempt in range(_WINDOWS_FILE_RETRY_ATTEMPTS):
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            return
        except OSError:
            if attempt + 1 == _WINDOWS_FILE_RETRY_ATTEMPTS:
                raise
            time.sleep(_WINDOWS_FILE_RETRY_DELAY_SECONDS * (attempt + 1))


def _entry_exists(path: Path) -> bool:
    """不跟随链接判断目录项是否存在，因而也能识别断开的符号链接。"""

    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    """判断 ``lstat`` 结果是否为符号链接、junction 或其他重解析点。"""

    file_attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        file_attributes & _WINDOWS_REPARSE_POINT_ATTRIBUTE
    )


def _reject_linked_path(path: Path, label: str) -> None:
    """在解析路径前拒绝自身及全部既有父路径中的链接或重解析点。"""

    for component in reversed((path, *path.parents)):
        try:
            metadata = os.lstat(component)
        except FileNotFoundError:
            continue
        if _is_link_or_reparse(metadata):
            raise ValueError(
                f"{label} 自身或父路径包含符号链接、junction 或重解析点，拒绝发布：{component}"
            )


def _validated_publish_path(path: Path, label: str) -> Path:
    """先做无跟随检查，再返回规范化的绝对发布路径。"""

    expanded = path.expanduser()
    absolute = Path(os.path.abspath(expanded))
    _reject_linked_path(absolute, label)
    resolved = absolute.resolve(strict=False)
    # 第一次检查与 resolve 之间仍可能发生外部改写；解析后立即复核，缩小竞态窗口。
    _reject_linked_path(resolved, label)
    return resolved


def _publish_lock_path(destination: Path) -> Path:
    """返回同一目标的协作式发布锁路径。"""

    return destination.parent / f".{destination.name}.publish.lock"


@contextmanager
def _exclusive_publish_lock(staging: Path, destination: Path) -> Iterator[None]:
    """用 ``O_EXCL`` 锁串行化遵守本 helper 的同目标发布者。

    进程崩溃时锁文件会保留，其中记录 staging 与 destination，供人工判断备份和
    暂存目录的恢复关系。这里不自动删除陈旧锁，避免把仍在运行的慢发布误判为崩溃。
    """

    lock_path = _publish_lock_path(destination)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    flags |= getattr(os, "O_NOINHERIT", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except FileExistsError as error:
        raise FileExistsError(
            f"活动目录已有发布锁；若确认没有发布进程，请人工检查后删除：{lock_path}"
        ) from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(
                f"pid={os.getpid()}\nstaging={staging}\ndestination={destination}\n"
            )
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            warnings.warn(
                f"目录发布锁清理失败，请人工检查 {lock_path}：{error}",
                RuntimeWarning,
                stacklevel=2,
            )


def _restore_backup_after_publish_failure(
    destination: Path,
    backup: Path,
    publish_error: Exception,
) -> None:
    """尝试恢复旧目录；恢复失败时同时保留两次异常与备份位置。"""

    try:
        _reject_linked_path(destination, "活动输出路径")
        _reject_linked_path(backup, "回滚备份路径")
        if not _entry_exists(backup):
            raise FileNotFoundError(f"回滚备份已不存在：{backup}")
        if _entry_exists(destination):
            raise FileExistsError(f"活动输出路径已被其他进程占用：{destination}")
        backup.rename(destination)
    except Exception as rollback_error:
        raise DirectoryRollbackError(
            destination=destination,
            backup=backup,
            publish_error=publish_error,
            rollback_error=rollback_error,
        ) from publish_error


def _cleanup_backup(backup: Path) -> tuple[Path | None, str | None]:
    """清理已提交发布的旧版本；失败时保留并明确报告可审计路径。"""

    try:
        _reject_linked_path(backup, "提交后备份路径")
        remove_tree_with_retry(backup)
    except Exception as error:
        warnings.warn(
            f"新目录已经提交，但旧版本清理失败；保留备份 {backup}：{error}",
            RuntimeWarning,
            stacklevel=2,
        )
        return backup, str(error)
    return None, None


def replace_directory_with_rollback(
    staging: Path,
    destination: Path,
    *,
    replace_existing: bool = True,
) -> DirectoryReplaceResult:
    """用同级暂存目录发布活动目录，切换失败时恢复旧目录。

    参数：
        staging: 已完整验证、由调用方独占的暂存目录。
        destination: 暂存目录同父级下的活动目录。
        replace_existing: 是否允许替换已有目标；归档等 create-only 发布必须传 ``False``。

    返回：
        明确区分提交成功、旧目录清理成功和保留备份的发布结果。

    注意：
        Windows 上替换已有目录需要先把旧目录改名为唯一备份，再把 staging 改名为
        destination，两次改名之间必然存在短暂空窗，不能宣称为崩溃原子操作。协作式
        锁、带目标名的备份和锁内恢复构成最小可恢复策略；外部进程绕过本 helper 改写
        同一路径仍属于无法完全消除的文件系统竞态。
    """

    staged = _validated_publish_path(staging, "待发布暂存路径")
    target = _validated_publish_path(destination, "活动输出路径")
    if staged == target:
        raise ValueError("暂存目录与活动目录不得是同一路径")
    if not staged.is_dir():
        raise FileNotFoundError(f"待发布暂存目录不存在：{staged}")
    if staged.parent != target.parent:
        raise ValueError("暂存目录与活动目录必须位于同一父目录，禁止跨卷退化为复制")

    with _exclusive_publish_lock(staged, target):
        # 锁只能约束本 helper 的协作发布者，因此在每次改名前再次拒绝链接替换。
        _reject_linked_path(staged, "待发布暂存路径")
        _reject_linked_path(target, "活动输出路径")
        if not staged.is_dir():
            raise FileNotFoundError(f"待发布暂存目录不存在：{staged}")
        target_exists = _entry_exists(target)
        if target_exists and not target.is_dir():
            raise NotADirectoryError(f"活动输出路径不是目录：{target}")
        if target_exists and not replace_existing:
            raise FileExistsError(f"create-only 目标已存在，拒绝覆盖：{target}")

        backup: Path | None = None
        if target_exists:
            backup = create_inherited_temp_directory(
                target.parent,
                f".{target.name}.previous-",
            )
            backup.rmdir()
            _reject_linked_path(target, "活动输出路径")
            target.rename(backup)
        try:
            _reject_linked_path(staged, "待发布暂存路径")
            _reject_linked_path(target, "活动输出路径")
            staged.rename(target)
        except Exception as publish_error:
            if backup is not None:
                _restore_backup_after_publish_failure(target, backup, publish_error)
            raise

        retained_backup: Path | None = None
        cleanup_error: str | None = None
        if backup is not None:
            retained_backup, cleanup_error = _cleanup_backup(backup)
        return DirectoryReplaceResult(
            destination=target,
            replaced_existing=target_exists,
            retained_backup=retained_backup,
            backup_cleanup_error=cleanup_error,
        )


__all__ = [
    "DirectoryReplaceResult",
    "DirectoryRollbackError",
    "create_inherited_temp_directory",
    "remove_tree_with_retry",
    "replace_directory_with_rollback",
]
