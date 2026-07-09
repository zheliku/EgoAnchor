"""Windows 运行时 MSVC 环境注入契约测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from egoanchor.algorithms import FastFoundationStereoDepth
from egoanchor.utils import ensure_windows_msvc_runtime_env


class WindowsMsvcRuntimeEnvTest(unittest.TestCase):
    """验证 Windows 运行时按需激活 VS/MSVC 环境。"""

    def test_runtime_env_loader_updates_mapping_when_cl_missing(self) -> None:
        """当 PATH 中没有 cl.exe/link.exe 时，应注入 vcvars64 产生的环境变量。"""

        env = {"PATH": r"C:\dummy"}
        loaded_env = {
            "PATH": r"C:\VS\VC\Tools\MSVC\14.51.36231\bin\Hostx64\x64;C:\dummy",
            "INCLUDE": r"C:\VS\VC\Tools\MSVC\14.51.36231\include",
            "LIB": r"C:\VS\VC\Tools\MSVC\14.51.36231\lib\x64",
        }

        with patch("egoanchor.utils.windows_msvc.load_vs2026_env", return_value=loaded_env) as mocked_loader:
            activated = ensure_windows_msvc_runtime_env(
                env=env,
                os_name="nt",
                which=lambda *_args, **_kwargs: None,
            )

        self.assertTrue(activated)
        self.assertEqual(env["PATH"], loaded_env["PATH"])
        self.assertEqual(env["INCLUDE"], loaded_env["INCLUDE"])
        self.assertEqual(env["LIB"], loaded_env["LIB"])
        mocked_loader.assert_called_once()


class FastFoundationStereoRuntimeBootstrapTest(unittest.TestCase):
    """验证 FFS 在 Windows Triton/TRT 路径下会先准备 MSVC 运行时环境。"""

    def test_prepare_windows_runtime_env_calls_loader_for_trt(self) -> None:
        """TRT 模式会在 Windows 上先尝试注入 MSVC 运行时环境。"""

        with patch("egoanchor.algorithms.fast_foundationstereo_depth.ensure_windows_msvc_runtime_env") as mocked_loader:
            FastFoundationStereoDepth._prepare_windows_runtime_env(
                use_trt=True,
                optimize_build_volume="pytorch1",
                platform_name="win32",
            )

        mocked_loader.assert_called_once_with()

    def test_prepare_windows_runtime_env_skips_plain_pytorch_on_non_windows(self) -> None:
        """非 Windows 或纯 PyTorch 路径不应额外注入 MSVC 环境。"""

        with patch("egoanchor.algorithms.fast_foundationstereo_depth.ensure_windows_msvc_runtime_env") as mocked_loader:
            FastFoundationStereoDepth._prepare_windows_runtime_env(
                use_trt=False,
                optimize_build_volume="pytorch1",
                platform_name="linux",
            )

        mocked_loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
