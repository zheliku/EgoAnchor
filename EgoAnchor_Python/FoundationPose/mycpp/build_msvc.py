"""使用 VS2026/MSVC 构建 FoundationPose 的 pybind11 扩展。"""

from __future__ import annotations

import locale
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CLEAN_VS_ENV = (
    "VSINSTALLDIR",
    "VCINSTALLDIR",
    "VCToolsInstallDir",
    "VCToolsVersion",
    "VSCMD_ARG_TGT_ARCH",
    "VSCMD_ARG_HOST_ARCH",
    "VSCMD_VER",
    "VisualStudioVersion",
)


def mycpp_dir() -> Path:
    """返回 FoundationPose/mycpp 源码目录，避免依赖调用时的当前目录。"""
    return Path(__file__).resolve().parent


def run_checked(command: list[str], *, env: dict[str, str]) -> None:
    """执行一个构建命令，并在失败时保留原始退出码。"""
    print("[build_msvc]", " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=mycpp_dir(), env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def env_value(env: dict[str, str], name: str) -> str | None:
    """按 Windows 大小写不敏感规则读取环境变量。"""
    if name in env:
        return env[name]
    lowered = name.lower()
    for key, value in env.items():
        if key.lower() == lowered:
            return value
    return None


def candidate_vs_roots(env: dict[str, str]) -> list[Path]:
    """列出 VS2026/18 的常见安装根目录。"""
    roots: list[Path] = []
    for base_name in ("ProgramFiles(x86)", "ProgramFiles"):
        base = env_value(env, base_name)
        if not base:
            continue
        for version in ("18", "2026"):
            for edition in ("BuildTools", "Community", "Enterprise", "Professional"):
                roots.append(Path(base) / "Microsoft Visual Studio" / version / edition)
    return roots


def candidate_vswhere_roots(env: dict[str, str]) -> list[Path]:
    """通过 vswhere 查询 VS2026/18 安装根目录。"""
    vswhere = shutil.which("vswhere.exe", path=env_value(env, "PATH"))
    if not vswhere:
        return []

    commands = [
        [
            vswhere,
            "-nologo",
            "-products",
            "*",
            "-version",
            "[18.0,19.0)",
            "-requires",
            "Microsoft.VisualStudio.ComponentGroup.VC.Tools.145.x86.x64",
            "-property",
            "installationPath",
        ],
        [
            vswhere,
            "-nologo",
            "-products",
            "*",
            "-version",
            "[18.0,19.0)",
            "-requires",
            "Microsoft.VisualStudio.Workload.VCTools",
            "-property",
            "installationPath",
        ],
    ]

    roots: list[Path] = []
    for command in commands:
        completed = subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False),
            errors="replace",
            check=False,
        )
        if completed.returncode == 0:
            roots.extend(Path(line.strip()) for line in completed.stdout.splitlines() if line.strip())
    return roots


def find_vcvars64(env: dict[str, str]) -> Path:
    """定位 VS2026/18 的 vcvars64.bat。"""
    for root in [*candidate_vs_roots(env), *candidate_vswhere_roots(env)]:
        vcvars = root / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        if vcvars.is_file():
            return vcvars
    raise RuntimeError("找不到 VS2026/18 vcvars64.bat，请先安装 Visual Studio Build Tools 2026。")


def load_vs2026_env(env: dict[str, str]) -> dict[str, str]:
    """调用 VS2026/18 的 vcvars64.bat，并把批处理产生的环境变量导入当前进程。"""
    if not env_value(env, "CONDA_PREFIX"):
        raise RuntimeError("缺少 CONDA_PREFIX，请通过 `pixi run _build-fp` 调用。")

    vcvars = find_vcvars64(env)
    print(f"[build_msvc] vcvars={vcvars}", flush=True)

    script_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cmd", delete=False, encoding="ascii") as script:
            script_path = script.name
            script.write("@echo off\n")
            for name in CLEAN_VS_ENV:
                script.write(f'set "{name}="\n')
            script.write(f'call "{vcvars}" >nul\n')
            script.write("if errorlevel 1 exit /b %errorlevel%\n")
            script.write("set\n")

        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", script_path],
            cwd=mycpp_dir(),
            env=env,
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False),
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            sys.stderr.write(completed.stderr)
            raise SystemExit(completed.returncode)
    finally:
        if script_path:
            Path(script_path).unlink(missing_ok=True)

    updated = dict(env)
    for line in completed.stdout.splitlines():
        name, sep, value = line.partition("=")
        if sep:
            updated[name] = value
    return updated


def add_cuda_headers(env: dict[str, str]) -> dict[str, str]:
    """补齐 CUDA 13 targets/CCCL 头路径，避免 cuda_fp16.h 找不到 nv/target。"""
    conda_prefix_value = env_value(env, "CONDA_PREFIX")
    if not conda_prefix_value:
        raise RuntimeError("缺少 CONDA_PREFIX，请通过 `pixi run _build-fp` 调用。")
    conda_prefix = Path(conda_prefix_value)
    cuda_root = conda_prefix / "Library"
    targets = cuda_root / "include" / "targets" / "x64"
    cccl = targets / "cccl"

    updated = dict(env)
    updated["CUDA_HOME"] = str(cuda_root)
    updated["CUDA_PATH"] = str(cuda_root)
    updated["CL"] = f'/I"{targets}" /I"{cccl}"'
    updated["INCLUDE"] = f"{targets};{cccl};{updated.get('INCLUDE', '')}"
    updated["CC"] = "cl.exe"
    updated["CXX"] = "cl.exe"
    return updated


def main() -> int:
    """清理旧 build 目录，并用 Ninja + MSVC 重新编译扩展。"""
    env = add_cuda_headers(load_vs2026_env(dict(os.environ)))
    source_dir = mycpp_dir()
    build_dir = source_dir / "build"

    run_checked(["cmake", "-E", "rm", "-rf", str(build_dir)], env=env)
    run_checked(
        [
            "cmake",
            "-S",
            str(source_dir),
            "-B",
            str(build_dir),
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
        ],
        env=env,
    )
    run_checked(["cmake", "--build", str(build_dir), "--parallel"], env=env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
