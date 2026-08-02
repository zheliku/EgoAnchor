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
    def _path_key(path: Path) -> str:
        """返回适合 Windows 大小写不敏感比较的绝对测试路径。"""

        return os.path.normcase(os.path.abspath(path))


if __name__ == "__main__":
    unittest.main()
