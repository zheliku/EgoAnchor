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
from typing import Iterable, Iterator


_TEMP_DIRECTORY_ATTEMPTS = 32
"""随机临时目录发生名称碰撞时的最大尝试次数。"""

_WINDOWS_FILE_RETRY_ATTEMPTS = 12
"""Windows 索引器或防病毒短暂占用目录时的最大重试次数。"""

_WINDOWS_FILE_RETRY_DELAY_SECONDS = 0.25
"""目录清理重试的基础等待秒数。"""

_WINDOWS_RENAME_RETRY_ATTEMPTS = 20
"""目录改名遇到短暂句柄占用时的最大重试次数。

实测结论（2026-08-11 逐位验证）：Windows 上**任何未带 ``FILE_SHARE_DELETE`` 的目录
句柄都会让该目录改名失败**——八种共享模式里缺 bit 4 的四种一律失败，带 bit 4 的四种
一律成功；且失败码是 ``ACCESS_DENIED``(5) 而不是 ``SHARING_VIOLATION``(32)，所以看起来
像权限问题，其实不是。

**更关键的一条：占用可以在子树任意深处，报错却落在祖先目录上。** 曾因此排查了很久：
``analysis`` 改名被拒，但以 ``share=0`` 独占打开 ``analysis`` 本身却成功、ACL 与可正常
改名的兄弟目录逐条一致——真正被持有的是 ``analysis/results``。**判定占用必须遍历整个
子树逐项探测，只测被改名的那个目录会得出「无人持有」的错误结论。**

索引器、防病毒、网盘同步、编辑器与文件资源管理器的目录监视都会开出这类句柄，因此
发布期的两次改名必须重试；只对删除重试（``remove_tree_with_retry``）覆盖不到发布路径。
次数比删除多一档：改名只需句柄关闭的那一瞬，等下去通常能成。
"""

_WINDOWS_SHARING_VIOLATION = 32
"""``ERROR_SHARING_VIOLATION``；独占打开失败即证明该对象正被他人持有。"""

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


def _windows_held_entries(root: Path, limit: int = 8) -> list[Path]:
    """列出子树中此刻无法独占打开的对象，用于定位改名被拒的真正占用点。

    参数：
        root: 改名失败的目录；连同其整个子树逐项探测。
        limit: 最多报告多少个被持有的对象，避免错误信息失控。

    返回：
        被他人持有的路径列表；非 Windows、探测不可用或无人持有时返回空列表。

    注意：
        以 ``share=0`` 短暂独占打开是必要手段——占用可能在子树任意深处，而报错只落在
        祖先目录上，只探测 ``root`` 自身会误判成「无人持有」。探测只在改名彻底失败后
        运行一次，且只针对本项目自己的输出目录；本函数永不抛异常，诊断失败就返回空表，
        不能让排查逻辑反过来破坏发布。
    """

    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.restype = wintypes.HANDLE
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]

        invalid_handle = wintypes.HANDLE(-1).value
        open_existing = 3
        backup_semantics = 0x02000000
        open_reparse_point = 0x00200000
        read_access = 0x00000001  # 目录为 FILE_LIST_DIRECTORY，文件为 FILE_READ_DATA

        held: list[Path] = []

        def probe(path: Path, is_directory: bool) -> None:
            flags = open_reparse_point | (backup_semantics if is_directory else 0)
            handle = create_file(
                str(path), read_access, 0, None, open_existing, flags, None
            )
            if handle == invalid_handle:
                if ctypes.get_last_error() == _WINDOWS_SHARING_VIOLATION:
                    held.append(path)
                return
            close_handle(wintypes.HANDLE(handle))

        probe(root, True)
        for current, directories, files in os.walk(root):
            base = Path(current)
            for name in directories:
                if len(held) >= limit:
                    return held
                probe(base / name, True)
            for name in files:
                if len(held) >= limit:
                    return held
                probe(base / name, False)
        return held
    except Exception:  # noqa: BLE001 — 诊断绝不能盖掉真正的发布错误
        return []


def replace_managed_files_with_rollback(
    staging: Path,
    destination: Path,
    relative_paths: Iterable[Path],
    *,
    commit_path: Path,
) -> None:
    """在稳定目录内事务替换受管文件，并把提交标志最后发布。

    参数：
        staging: 已完整生成并验证的暂存目录。
        destination: 身份必须保持稳定的活动目录。
        relative_paths: 提交标志之外的受管文件相对路径。
        commit_path: 完整清单等提交标志的相对路径；普通文件就位后才替换该文件。

    注意：
        文件级替换无法让多个文件在同一瞬间切换，因此提交标志必须最后替换。发布中的旧
        提交标志与新旧混合文件摘要不符，读取方会关闭失败；新提交标志可见时，其余文件
        已全部就位。任一 ``BaseException`` 都按预先完成的快照恢复整个旧集合；目录本身
        始终不改名，目录监视句柄不参与事务。
    """

    staged = _validated_publish_path(staging, "受管文件暂存路径")
    target = _validated_publish_path(destination, "受管文件活动路径")
    if staged == target:
        raise ValueError("受管文件暂存目录与活动目录不得是同一路径")
    if not staged.is_dir():
        raise FileNotFoundError(f"受管文件暂存目录不存在：{staged}")
    if staged.parent != target.parent:
        raise ValueError("受管文件暂存目录与活动目录必须位于同一父目录")

    files = tuple(_validate_relative_file(path, "受管文件") for path in relative_paths)
    commit = _validate_relative_file(commit_path, "提交标志")
    if not files:
        raise ValueError("受管文件发布至少需要一个非提交文件")
    if len(files) != len(set(files)):
        raise ValueError("受管文件相对路径不得重复")
    if commit in files:
        raise ValueError("提交标志不得同时出现在普通受管文件中")

    with _exclusive_publish_lock(staged, target):
        _reject_linked_path(staged, "受管文件暂存路径")
        _reject_linked_path(target, "受管文件活动路径")
        if not staged.is_dir():
            raise FileNotFoundError(f"受管文件暂存目录不存在：{staged}")
        if _entry_exists(target) and not target.is_dir():
            raise NotADirectoryError(f"受管文件活动路径不是目录：{target}")
        target.mkdir(parents=True, exist_ok=True)

        ordered = (*files, commit)
        for relative in ordered:
            source = staged / relative
            output = target / relative
            _reject_linked_path(source, "受管文件来源")
            _reject_linked_path(output, "受管文件目标")
            if not source.is_file():
                raise FileNotFoundError(f"待发布受管文件不存在：{source}")
            if _entry_exists(output) and not output.is_file():
                raise IsADirectoryError(f"受管文件目标不是普通文件：{output}")
            output.parent.mkdir(parents=True, exist_ok=True)

        backup_root = create_inherited_temp_directory(
            target.parent,
            f".{target.name}.files-backup-",
        )
        try:
            existed = _snapshot_managed_files(target, backup_root, ordered)
        except BaseException:
            _cleanup_managed_backup(backup_root, state="发布尚未开始")
            raise

        try:
            for relative in files:
                (staged / relative).replace(target / relative)
            (staged / commit).replace(target / commit)
        except BaseException as publish_error:
            rollback_errors = _restore_managed_files(
                target,
                backup_root,
                ordered,
                existed,
            )
            if rollback_errors:
                raise RuntimeError(
                    "受管文件发布失败且回滚不完整；"
                    f"请保留备份 {backup_root}。回滚错误：{'；'.join(rollback_errors)}"
                ) from publish_error
            _cleanup_managed_backup(backup_root, state="旧构建已经恢复")
            raise
        else:
            _cleanup_managed_backup(backup_root, state="新构建已经提交")


def _validate_relative_file(path: Path, label: str) -> Path:
    """验证单个文件相对路径不会逃逸发布根目录。"""

    relative = Path(path)
    if (
        relative.is_absolute()
        or bool(relative.drive)
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"{label}必须是不可逃逸的文件相对路径：{path}")
    return relative


def _snapshot_managed_files(
    destination: Path,
    backup_root: Path,
    relative_paths: tuple[Path, ...],
) -> dict[Path, bool]:
    """在修改活动集合前完整复制既有受管文件，并记录各路径是否原先存在。"""

    existed: dict[Path, bool] = {}
    for relative in relative_paths:
        source = destination / relative
        present = _entry_exists(source)
        existed[relative] = present
        if not present:
            continue
        backup = backup_root / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup)
    return existed


def _restore_managed_files(
    destination: Path,
    backup_root: Path,
    relative_paths: tuple[Path, ...],
    existed: dict[Path, bool],
) -> list[str]:
    """按完整快照恢复所有受管路径，最后恢复提交标志。"""

    errors: list[str] = []
    for relative in relative_paths:
        output = destination / relative
        try:
            if existed[relative]:
                (backup_root / relative).replace(output)
            else:
                output.unlink(missing_ok=True)
        except OSError as error:
            errors.append(f"恢复 {output} 失败：{error}")
    return errors


def _cleanup_managed_backup(backup_root: Path, *, state: str) -> None:
    """清理受管文件快照；失败时保留路径并准确说明事务所处状态。"""

    try:
        _reject_linked_path(backup_root, "受管文件备份路径")
        remove_tree_with_retry(backup_root)
    except OSError as error:
        warnings.warn(
            f"{state}，但受管文件备份清理失败；保留 {backup_root}：{error}",
            RuntimeWarning,
            stacklevel=2,
        )


def rename_directory_with_retry(source: Path, destination: Path) -> None:
    """改名目录，并对 Windows 短暂目录句柄占用做有界重试。

    参数：
        source: 调用方已验证的源目录。
        destination: 同一父目录下尚不存在的目标名。

    抛出：
        OSError: 重试用尽后仍被占用；异常信息点名子树里真正被持有的对象，
            避免只留一个「拒绝访问」让人误以为是权限问题。

    注意：
        只重试占用类失败。目标已存在（``FileExistsError``）属于调用方逻辑错误，
        必须立刻上抛，不能靠等待掩盖。
    """

    for attempt in range(_WINDOWS_RENAME_RETRY_ATTEMPTS):
        try:
            source.rename(destination)
            return
        except FileExistsError:
            raise
        except PermissionError as error:
            if attempt + 1 == _WINDOWS_RENAME_RETRY_ATTEMPTS:
                held = _windows_held_entries(source)
                if held:
                    listed = "；".join(str(path) for path in held)
                    culprit = f"子树中仍被占用的对象：{listed}。"
                else:
                    culprit = (
                        "子树逐项探测未发现占用对象（持有者可能在提权盲区内，"
                        "或占用刚好在探测间隙释放）。"
                    )
                raise PermissionError(
                    f"目录改名在 {_WINDOWS_RENAME_RETRY_ATTEMPTS} 次重试后仍被拒绝："
                    f"{source} -> {destination}。"
                    "Windows 上任何未带 FILE_SHARE_DELETE 的句柄都会挡住改名，"
                    "且报错为「拒绝访问」而非「共享冲突」，因此这通常不是权限问题；"
                    "占用还可能在子树任意深处，报错却落在被改名的目录上。"
                    f"{culprit}"
                    "常见持有者：文件资源管理器曾浏览过该目录（即使窗口已不显示它，"
                    "explorer.exe 仍会留着句柄，重启 explorer.exe 即可释放）、"
                    "编辑器/IDE 的目录监视、网盘同步客户端、防病毒实时扫描、"
                    "以及工作目录停在该目录的终端。"
                ) from error
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
        # 回滚同样要重试：挡住第一次改名的句柄往往还在，不重试会把「可恢复的
        # 占用」升级成需要人工处理的 DirectoryRollbackError。
        rename_directory_with_retry(backup, destination)
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
            rename_directory_with_retry(target, backup)
        try:
            _reject_linked_path(staged, "待发布暂存路径")
            _reject_linked_path(target, "活动输出路径")
            rename_directory_with_retry(staged, target)
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
    "rename_directory_with_retry",
    "replace_directory_with_rollback",
    "replace_managed_files_with_rollback",
]
