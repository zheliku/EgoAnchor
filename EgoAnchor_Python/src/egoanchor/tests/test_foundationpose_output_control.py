"""FoundationPose 输出抑制辅助逻辑测试。"""

from __future__ import annotations

import io
import ctypes
import logging
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from egoanchor.algorithms import FoundationPoseObjectEstimator


class FoundationPoseOutputControlTest(unittest.TestCase):
    """验证 FoundationPose 内部 stdout/stderr/logging 可按配置抑制。"""

    def _load_c_runtime(self):
        """加载当前平台 C runtime；不可用时跳过依赖 C stdio 的断言。"""

        candidates = ("ucrtbase", "msvcrt") if os.name == "nt" else (None, "libSystem.B.dylib", "libc.so.6")
        for name in candidates:
            try:
                libc = ctypes.CDLL(name) if name is not None else ctypes.CDLL(None)
                libc.fflush.argtypes = [ctypes.c_void_p]
                libc.fflush.restype = ctypes.c_int
                return libc
            except Exception:
                continue
        self.skipTest("当前平台无法通过 ctypes 加载 C runtime。")

    def _load_c_printf_runtime(self):
        """加载带 printf 的 C runtime；没有导出时跳过 C stdio 写入模拟。"""

        candidates = ("ucrtbase", "msvcrt") if os.name == "nt" else (None, "libSystem.B.dylib", "libc.so.6")
        for name in candidates:
            try:
                libc = ctypes.CDLL(name) if name is not None else ctypes.CDLL(None)
                printf = libc.printf
                printf.argtypes = [ctypes.c_char_p]
                printf.restype = ctypes.c_int
                libc.fflush.argtypes = [ctypes.c_void_p]
                libc.fflush.restype = ctypes.c_int
                return libc
            except Exception:
                continue
        self.skipTest("当前平台无法通过 ctypes 找到 printf。")

    def _capture_fd_output(self, callback):
        """捕获直接写入进程 fd=1/2 的输出，用于模拟底层库 console 噪音。"""

        self._load_c_runtime().fflush(None)
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                os.dup2(stdout_file.fileno(), 1)
                os.dup2(stderr_file.fileno(), 2)
                result = callback()
                self._load_c_runtime().fflush(None)
                os.dup2(saved_stdout_fd, 1)
                os.dup2(saved_stderr_fd, 2)
                stdout_file.seek(0)
                stderr_file.seek(0)
                return result, stdout_file.read(), stderr_file.read()
            finally:
                os.dup2(saved_stdout_fd, 1)
                os.dup2(saved_stderr_fd, 2)
                os.close(saved_stdout_fd)
                os.close(saved_stderr_fd)

    def test_logging_disabled_suppresses_stdout_stderr_and_logging(self) -> None:
        """enable_logging=false 时第三方库 print/logging 不应污染系统日志。"""

        stream = io.StringIO()
        logger = logging.getLogger("egoanchor-test-foundationpose-output")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)

        def noisy_call() -> str:
            print("stdout-noise")
            print("stderr-noise", file=__import__("sys").stderr)
            logger.warning("logging-noise")
            return "ok"

        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = FoundationPoseObjectEstimator.call_with_logging_control(noisy_call, enable_logging=False)
        finally:
            logger.removeHandler(handler)

        self.assertEqual(result, "ok")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(stream.getvalue(), "")

    def test_logging_enabled_keeps_stdout(self) -> None:
        """enable_logging=true 时保留第三方库输出，便于排查 FoundationPose 内部问题。"""

        def noisy_call() -> str:
            print("stdout-visible")
            return "ok"

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = FoundationPoseObjectEstimator.call_with_logging_control(noisy_call, enable_logging=True)

        self.assertEqual(result, "ok")
        self.assertIn("stdout-visible", stdout.getvalue())

    def test_logging_disabled_suppresses_fd_stdout_stderr(self) -> None:
        """enable_logging=false 时底层库直接写 fd=1/2 的输出也不应进 console。"""

        def noisy_fd_call() -> str:
            os.write(1, b"fd-stdout-noise")
            os.write(2, b"fd-stderr-noise")
            return "ok"

        result, stdout_bytes, stderr_bytes = self._capture_fd_output(
            lambda: FoundationPoseObjectEstimator.call_with_logging_control(noisy_fd_call, enable_logging=False)
        )

        self.assertEqual(result, "ok")
        self.assertEqual(stdout_bytes, b"")
        self.assertEqual(stderr_bytes, b"")

    @unittest.skipIf(os.name == "nt", "Windows 下不同 C runtime 的 printf 捕获不稳定，使用 controller smoke 覆盖真实扩展输出。")
    def test_logging_disabled_suppresses_c_stdio_buffered_output(self) -> None:
        """enable_logging=false 时 C stdio 缓冲输出不应在恢复 fd 后泄漏。"""

        libc = self._load_c_printf_runtime()
        libc.printf(b"")

        def noisy_c_stdio_call() -> str:
            libc.printf(b"c-stdio-stdout-noise")
            return "ok"

        result, stdout_bytes, stderr_bytes = self._capture_fd_output(
            lambda: FoundationPoseObjectEstimator.call_with_logging_control(noisy_c_stdio_call, enable_logging=False)
        )

        self.assertEqual(result, "ok")
        self.assertEqual(stdout_bytes, b"")
        self.assertEqual(stderr_bytes, b"")

    def test_import_block_can_be_wrapped_by_logging_control(self) -> None:
        """第三方 import 阶段产生的输出也应能被统一抑制。"""

        stream = io.StringIO()
        logger = logging.getLogger("egoanchor-test-foundationpose-import")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)

        def noisy_import_like_block() -> str:
            print("import-stdout-noise")
            print("import-stderr-noise", file=__import__("sys").stderr)
            logger.warning("import-logging-noise")
            return "loaded"

        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = FoundationPoseObjectEstimator.call_with_logging_control(noisy_import_like_block, enable_logging=False)
        finally:
            logger.removeHandler(handler)

        self.assertEqual(result, "loaded")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(stream.getvalue(), "")

    def test_foundationpose_module_load_is_wrapped(self) -> None:
        """FoundationPose 模块加载阶段也使用同一套输出控制。"""

        calls: list[bool] = []

        def fake_loader() -> tuple[object, object]:
            print("module-load-stdout-noise")
            print("module-load-stderr-noise", file=__import__("sys").stderr)
            logging.getLogger("egoanchor-test-foundationpose-module-load").warning("module-load-logging-noise")
            calls.append(True)
            return object(), object()

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            est_mod, utils_mod = FoundationPoseObjectEstimator.load_modules_with_logging_control(fake_loader, enable_logging=False)

        self.assertEqual(calls, [True])
        self.assertIsNotNone(est_mod)
        self.assertIsNotNone(utils_mod)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")


class FoundationPoseMeshLoadTest(unittest.TestCase):
    """验证 FoundationPose mesh 加载保留 GLB scene 节点变换。"""

    def test_scene_geometry_uses_trimesh_transform_aware_conversion(self) -> None:
        """GLB scene 应走 transform-aware conversion，而不是直接拼接原始 geometry。"""

        class FakeScene:
            """只模拟 helper 需要的 scene API，避免单测触发 native 渲染/几何依赖。"""

            geometry = {"mesh": object()}

            def __init__(self) -> None:
                self.to_geometry_called = False

            def to_geometry(self) -> str:
                self.to_geometry_called = True
                return "transformed_mesh"

        scene = FakeScene()

        mesh = FoundationPoseObjectEstimator._scene_to_transformed_mesh(scene)

        self.assertEqual(mesh, "transformed_mesh")
        self.assertTrue(scene.to_geometry_called)


if __name__ == "__main__":
    unittest.main()
