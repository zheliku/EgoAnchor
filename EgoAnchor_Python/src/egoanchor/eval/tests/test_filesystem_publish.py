"""共享目录发布 helper 的链接、回滚与并发边界测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from egoanchor.eval import _filesystem as filesystem


class DirectoryPublishTests(unittest.TestCase):
    """验证目录发布不会跟随链接，并保留足够的失败恢复信息。"""

    def test_successful_replace_removes_old_directory(self) -> None:
        """正常替换提交新目录并明确报告旧目录已完成清理。"""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / "staging"
            destination = parent / "active"
            staging.mkdir()
            destination.mkdir()
            (staging / "new.txt").write_text("new", encoding="utf-8")
            (destination / "old.txt").write_text("old", encoding="utf-8")

            result = filesystem.replace_directory_with_rollback(staging, destination)

            self.assertEqual(result.destination, destination.resolve())
            self.assertTrue(result.replaced_existing)
            self.assertIsNone(result.retained_backup)
            self.assertIsNone(result.backup_cleanup_error)
            self.assertEqual((destination / "new.txt").read_text(encoding="utf-8"), "new")
            self.assertFalse((destination / "old.txt").exists())
            self.assertFalse(staging.exists())

    def test_reparse_parent_is_rejected_before_staging_resolve(self) -> None:
        """Windows junction/reparse 父路径在 resolve 跟随它之前即被拒绝。"""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / "staging"
            destination = parent / "active"
            staging.mkdir()
            original_lstat = filesystem.os.lstat
            original_resolve = Path.resolve
            flagged_path = self._path_key(parent)
            staging_key = self._path_key(staging)

            def marked_lstat(path: os.PathLike[str] | str) -> object:
                """只把测试父目录模拟成 Windows 重解析点。"""

                metadata = original_lstat(path)
                if self._path_key(Path(path)) == flagged_path:
                    return SimpleNamespace(
                        st_mode=metadata.st_mode,
                        st_file_attributes=(
                            getattr(metadata, "st_file_attributes", 0) | 0x0400
                        ),
                    )
                return metadata

            def guarded_resolve(path: Path, *, strict: bool = False) -> Path:
                """若实现先 resolve staging，则让测试立即暴露顺序错误。"""

                if self._path_key(path) == staging_key:
                    raise AssertionError("staging resolve 不应早于 reparse 检查")
                return original_resolve(path, strict=strict)

            with (
                mock.patch.object(filesystem.os, "lstat", side_effect=marked_lstat),
                mock.patch.object(Path, "resolve", autospec=True, side_effect=guarded_resolve),
                self.assertRaisesRegex(ValueError, "junction.*重解析点"),
            ):
                filesystem.replace_directory_with_rollback(staging, destination)

            self.assertTrue(staging.is_dir())
            self.assertFalse(destination.exists())

    def test_reparse_destination_is_rejected_before_its_resolve(self) -> None:
        """活动目录自身是 junction/reparse 时不会跟随到真实目标。"""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / "staging"
            destination = parent / "active"
            staging.mkdir()
            destination.mkdir()
            (destination / "protected.txt").write_text("keep", encoding="utf-8")
            original_lstat = filesystem.os.lstat
            original_resolve = Path.resolve
            destination_key = self._path_key(destination)

            def marked_lstat(path: os.PathLike[str] | str) -> object:
                """只把活动目录模拟成 Windows 重解析点。"""

                metadata = original_lstat(path)
                if self._path_key(Path(path)) == destination_key:
                    return SimpleNamespace(
                        st_mode=metadata.st_mode,
                        st_file_attributes=(
                            getattr(metadata, "st_file_attributes", 0) | 0x0400
                        ),
                    )
                return metadata

            def guarded_resolve(path: Path, *, strict: bool = False) -> Path:
                """允许 staging 规范化，但禁止 destination 在检查前被解析。"""

                if self._path_key(path) == destination_key:
                    raise AssertionError("destination resolve 不应早于 reparse 检查")
                return original_resolve(path, strict=strict)

            with (
                mock.patch.object(filesystem.os, "lstat", side_effect=marked_lstat),
                mock.patch.object(Path, "resolve", autospec=True, side_effect=guarded_resolve),
                self.assertRaisesRegex(ValueError, "junction.*重解析点"),
            ):
                filesystem.replace_directory_with_rollback(staging, destination)

            self.assertEqual(
                (destination / "protected.txt").read_text(encoding="utf-8"),
                "keep",
            )
            self.assertTrue(staging.is_dir())

    def test_cleanup_failure_returns_committed_result_and_retains_backup(self) -> None:
        """旧版本清理失败不伪报提交失败，并返回可审计备份位置。"""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / "staging"
            destination = parent / "active"
            staging.mkdir()
            destination.mkdir()
            (staging / "new.txt").write_text("new", encoding="utf-8")
            (destination / "old.txt").write_text("old", encoding="utf-8")

            with (
                mock.patch.object(
                    filesystem,
                    "remove_tree_with_retry",
                    side_effect=OSError("simulated cleanup lock"),
                ),
                self.assertWarnsRegex(RuntimeWarning, "已经提交.*保留备份"),
            ):
                result = filesystem.replace_directory_with_rollback(staging, destination)

            self.assertEqual((destination / "new.txt").read_text(encoding="utf-8"), "new")
            self.assertIsNotNone(result.retained_backup)
            assert result.retained_backup is not None
            self.assertEqual(
                (result.retained_backup / "old.txt").read_text(encoding="utf-8"),
                "old",
            )
            self.assertIn("simulated cleanup lock", result.backup_cleanup_error or "")

    def test_rollback_failure_preserves_original_error_and_backup_path(self) -> None:
        """提交与回滚同时失败时，异常同时暴露原始错误和备份路径。"""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / "staging"
            destination = parent / "active"
            staging.mkdir()
            destination.mkdir()
            (staging / "new.txt").write_text("new", encoding="utf-8")
            (destination / "old.txt").write_text("old", encoding="utf-8")
            original_rename = Path.rename

            def failing_rename(path: Path, target: Path) -> Path:
                """允许旧目录进入 backup，但让提交和恢复两步都失败。"""

                if path == staging:
                    raise OSError("simulated publish failure")
                if path.name.startswith(".active.previous-"):
                    raise OSError("simulated rollback failure")
                return original_rename(path, target)

            with (
                mock.patch.object(Path, "rename", autospec=True, side_effect=failing_rename),
                self.assertRaises(filesystem.DirectoryRollbackError) as raised,
            ):
                filesystem.replace_directory_with_rollback(staging, destination)

            error = raised.exception
            self.assertIn("simulated publish failure", str(error))
            self.assertIn("simulated rollback failure", str(error))
            self.assertIn(str(error.backup), str(error))
            self.assertIs(error.__cause__, error.publish_error)
            self.assertTrue(error.backup.is_dir())
            self.assertEqual((error.backup / "old.txt").read_text(encoding="utf-8"), "old")
            self.assertTrue(staging.is_dir())
            self.assertFalse(destination.exists())

    def test_transient_directory_handle_is_retried_instead_of_failing(self) -> None:
        """短暂占用只让改名重试，不应把整次发布判失败。

        Windows 上任何未带 ``FILE_SHARE_DELETE`` 的目录句柄都会让改名报
        ``ACCESS_DENIED``，索引器、防病毒与编辑器目录监视都会瞬时开出这类句柄；
        发布必须等它松手，而不是把可恢复的占用上抛给使用者。
        """

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / "staging"
            destination = parent / "active"
            staging.mkdir()
            destination.mkdir()
            (staging / "new.txt").write_text("new", encoding="utf-8")
            (destination / "old.txt").write_text("old", encoding="utf-8")
            original_rename = Path.rename
            denials = {"count": 0}

            def briefly_denied(path: Path, target: Path) -> Path:
                """前两次改名活动目录报拒绝访问，第三次放行。"""

                if path == destination and denials["count"] < 2:
                    denials["count"] += 1
                    raise PermissionError(13, "Access is denied")
                return original_rename(path, target)

            with (
                mock.patch.object(Path, "rename", autospec=True, side_effect=briefly_denied),
                mock.patch.object(filesystem, "_WINDOWS_FILE_RETRY_DELAY_SECONDS", 0.0),
            ):
                result = filesystem.replace_directory_with_rollback(staging, destination)

            self.assertEqual(denials["count"], 2)
            self.assertTrue(result.replaced_existing)
            self.assertIsNone(result.retained_backup)
            self.assertEqual(
                (destination / "new.txt").read_text(encoding="utf-8"), "new"
            )
            self.assertFalse(staging.exists())

    def test_managed_file_publish_commits_manifest_last(self) -> None:
        """普通产物全部替换后才允许完整清单变为可见。"""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging, destination, files, commit = self._managed_file_fixture(parent)
            original_replace = Path.replace
            published: list[Path] = []

            def record_replace(path: Path, target: Path) -> Path:
                """只记录从 staging 搬到活动目录的受管文件顺序。"""

                if path.is_relative_to(staging) and target.is_relative_to(destination):
                    published.append(path.relative_to(staging))
                return original_replace(path, target)

            with mock.patch.object(
                Path,
                "replace",
                autospec=True,
                side_effect=record_replace,
            ):
                filesystem.replace_managed_files_with_rollback(
                    staging,
                    destination,
                    files,
                    commit_path=commit,
                )

            self.assertEqual(published, [*files, commit])
            self.assertEqual(
                (destination / commit).read_text(encoding="utf-8"),
                "new manifest",
            )
            self.assertEqual(
                (destination / "unmanaged.txt").read_text(encoding="utf-8"),
                "keep",
            )

    def test_managed_file_publish_rolls_back_error_and_keyboard_interrupt(self) -> None:
        """普通异常与 Ctrl+C 都恢复旧文件、旧清单和未受管文件。"""

        failure_types = (RuntimeError, KeyboardInterrupt)
        for failure_type in failure_types:
            for failed_relative in (
                Path("results/result.txt"),
                Path("figures/figure.pdf"),
                Path("provenance/build_result.json"),
            ):
                with (
                    self.subTest(
                        failure=failure_type.__name__,
                        path=str(failed_relative),
                    ),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    parent = Path(directory)
                    staging, destination, files, commit = self._managed_file_fixture(parent)
                    original_replace = Path.replace
                    failed_source = staging / failed_relative
                    failure = failure_type("simulated failure")

                    def fail_managed_file(path: Path, target: Path) -> Path:
                        """指定产物替换时注入同步异常或用户中断。"""

                        if path == failed_source:
                            raise failure
                        return original_replace(path, target)

                    with (
                        mock.patch.object(
                            Path,
                            "replace",
                            autospec=True,
                            side_effect=fail_managed_file,
                        ),
                        self.assertRaises(failure_type),
                    ):
                        filesystem.replace_managed_files_with_rollback(
                            staging,
                            destination,
                            files,
                            commit_path=commit,
                        )

                    for relative in files:
                        self.assertEqual(
                            (destination / relative).read_text(encoding="utf-8"),
                            f"old {relative.name}",
                        )
                    self.assertEqual(
                        (destination / commit).read_text(encoding="utf-8"),
                        "old manifest",
                    )
                    self.assertEqual(
                        (destination / "unmanaged.txt").read_text(encoding="utf-8"),
                        "keep",
                    )
                    self.assertFalse(tuple(parent.glob(".active.files-backup-*")))
                    self.assertFalse((parent / ".active.publish.lock").exists())

    @unittest.skipUnless(os.name == "nt", "共享模式语义只在 Windows 上成立")
    def test_managed_file_publish_keeps_watched_directory_identity(self) -> None:
        """真实目录句柄持续占用 results 时仍发布成功，且不更换目录节点。"""

        import ctypes
        from ctypes import wintypes

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging, destination, files, commit = self._managed_file_fixture(parent)
            results = destination / "results"
            identity = results.stat().st_ino
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
            handle = create_file(
                str(results), 0x00000001, 0x00000003, None, 3, 0x02000000, None
            )
            self.assertNotEqual(handle, wintypes.HANDLE(-1).value, "无法建立测试句柄")
            try:
                filesystem.replace_managed_files_with_rollback(
                    staging,
                    destination,
                    files,
                    commit_path=commit,
                )
            finally:
                kernel32.CloseHandle(wintypes.HANDLE(handle))

            self.assertEqual(results.stat().st_ino, identity)
            self.assertEqual(
                (destination / commit).read_text(encoding="utf-8"),
                "new manifest",
            )

    def test_persistent_directory_handle_reports_actionable_guidance(self) -> None:
        """持续占用在重试用尽后要给出可操作的排查线索，而非只报「拒绝访问」。"""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = parent / "source"
            target = parent / "target"
            source.mkdir()

            with (
                mock.patch.object(
                    Path,
                    "rename",
                    autospec=True,
                    side_effect=PermissionError(13, "Access is denied"),
                ),
                mock.patch.object(filesystem, "_WINDOWS_FILE_RETRY_DELAY_SECONDS", 0.0),
                self.assertRaises(PermissionError) as raised,
            ):
                filesystem.rename_directory_with_retry(source, target)

            message = str(raised.exception)
            self.assertIn("FILE_SHARE_DELETE", message)
            self.assertIn("不是权限问题", message)
            self.assertIn(str(source), message)

    @unittest.skipUnless(os.name == "nt", "共享模式语义只在 Windows 上成立")
    def test_real_subtree_handle_is_named_in_the_error(self) -> None:
        """真实占用子树深处时，错误必须点名那个对象而不是只报被改名的目录。

        这是实际踩过的坑：``analysis`` 改名被拒，但独占打开 ``analysis`` 自身却成功，
        真正被持有的是 ``analysis/results``。用真句柄而非 mock 才能锁住这个语义。
        """

        import ctypes
        from ctypes import wintypes

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = parent / "active"
            nested = source / "results"
            nested.mkdir(parents=True)

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
            # FILE_LIST_DIRECTORY，共享 READ|WRITE 但**不含 DELETE**，
            # 即 explorer.exe 持有目录时的形态。
            handle = create_file(
                str(nested), 0x00000001, 0x00000003, None, 3, 0x02000000, None
            )
            self.assertNotEqual(handle, wintypes.HANDLE(-1).value, "无法建立测试句柄")
            try:
                with (
                    mock.patch.object(
                        filesystem, "_WINDOWS_RENAME_RETRY_ATTEMPTS", 2
                    ),
                    mock.patch.object(
                        filesystem, "_WINDOWS_FILE_RETRY_DELAY_SECONDS", 0.0
                    ),
                    self.assertRaises(PermissionError) as raised,
                ):
                    filesystem.rename_directory_with_retry(source, parent / "renamed")

                message = str(raised.exception)
                self.assertIn("results", message)
                self.assertIn(str(nested), message)
                self.assertIn("explorer.exe", message)
            finally:
                kernel32.CloseHandle(wintypes.HANDLE(handle))

            # 句柄释放后同一次改名应当成功，确认失败确实由该句柄造成。
            filesystem.rename_directory_with_retry(source, parent / "renamed")
            self.assertTrue((parent / "renamed" / "results").is_dir())

    def test_rename_retry_does_not_mask_existing_target(self) -> None:
        """目标已存在属于调用方逻辑错误，必须立刻上抛而不是重试等待。"""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = parent / "source"
            target = parent / "target"
            source.mkdir()
            attempts = {"count": 0}

            def counting_rename(path: Path, destination: Path) -> Path:
                attempts["count"] += 1
                raise FileExistsError(17, "File exists")

            with (
                mock.patch.object(Path, "rename", autospec=True, side_effect=counting_rename),
                self.assertRaises(FileExistsError),
            ):
                filesystem.rename_directory_with_retry(source, target)

            self.assertEqual(attempts["count"], 1)

    def test_create_only_publish_does_not_overwrite_concurrent_destination(self) -> None:
        """create-only 在最终 rename 前出现同名目标时保留对方目录。"""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / "staging"
            destination = parent / "archive"
            staging.mkdir()
            (staging / "ours.txt").write_text("ours", encoding="utf-8")
            original_rename = Path.rename

            def racing_rename(path: Path, target: Path) -> Path:
                """在最终 rename 瞬间模拟绕过协作锁的外部归档创建者。"""

                if path == staging:
                    target.mkdir()
                    (target / "theirs.txt").write_text("theirs", encoding="utf-8")
                return original_rename(path, target)

            with (
                mock.patch.object(Path, "rename", autospec=True, side_effect=racing_rename),
                self.assertRaises(OSError),
            ):
                filesystem.replace_directory_with_rollback(
                    staging,
                    destination,
                    replace_existing=False,
                )

            self.assertEqual(
                (destination / "theirs.txt").read_text(encoding="utf-8"),
                "theirs",
            )
            self.assertTrue((staging / "ours.txt").is_file())

    def test_existing_publish_lock_blocks_second_create_only_publisher(self) -> None:
        """遵守 helper 的并发发布者由 create-exclusive 锁串行化。"""

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / "staging"
            destination = parent / "archive"
            staging.mkdir()
            lock_path = parent / ".archive.publish.lock"
            lock_path.write_text("another publisher", encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "发布锁"):
                filesystem.replace_directory_with_rollback(
                    staging,
                    destination,
                    replace_existing=False,
                )

            self.assertTrue(staging.is_dir())
            self.assertFalse(destination.exists())
            self.assertEqual(lock_path.read_text(encoding="utf-8"), "another publisher")

    @staticmethod
    def _managed_file_fixture(
        parent: Path,
    ) -> tuple[Path, Path, tuple[Path, ...], Path]:
        """创建带旧构建、新暂存构建和未受管文件的最小发布夹具。"""

        staging = parent / "staging"
        destination = parent / "active"
        files = (
            Path("results/result.txt"),
            Path("figures/figure.pdf"),
        )
        commit = Path("provenance/build_result.json")
        staging.mkdir()
        destination.mkdir()
        for relative in files:
            (staging / relative).parent.mkdir(parents=True, exist_ok=True)
            (destination / relative).parent.mkdir(parents=True, exist_ok=True)
            (staging / relative).write_text(
                f"new {relative.name}",
                encoding="utf-8",
            )
            (destination / relative).write_text(
                f"old {relative.name}",
                encoding="utf-8",
            )
        (staging / commit).parent.mkdir(parents=True, exist_ok=True)
        (destination / commit).parent.mkdir(parents=True, exist_ok=True)
        (staging / commit).write_text("new manifest", encoding="utf-8")
        (destination / commit).write_text("old manifest", encoding="utf-8")
        (destination / "unmanaged.txt").write_text("keep", encoding="utf-8")
        return staging, destination, files, commit

    @staticmethod
    def _path_key(path: Path) -> str:
        """返回适合 Windows 大小写不敏感比较的绝对测试路径。"""

        return os.path.normcase(os.path.abspath(path))


if __name__ == "__main__":
    unittest.main()
