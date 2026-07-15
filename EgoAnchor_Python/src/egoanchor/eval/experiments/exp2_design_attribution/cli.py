"""实验二独立命令行入口，所有产物写入显式指定的分析目录。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import run_exp2_design_attribution


def main(argv: list[str] | None = None) -> int:
    """解析 session 目录并运行分析。"""

    parser = argparse.ArgumentParser(description="运行 EgoAnchor 实验二系统设计归因分析")
    parser.add_argument(
        "session_dirs",
        nargs="+",
        type=Path,
        help="一个或多个 schema-v2 session 目录",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        required=True,
        type=Path,
        help="CSV、PDF 与 TeX 产物目录；论文默认目录由顶层 eval CLI 统一路由",
    )
    args = parser.parse_args(argv)
    try:
        result = run_exp2_design_attribution(args.session_dirs, args.output_dir, config=None)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for message in result.qc.errors:
        print(f"ERROR: {message}")
    for message in result.qc.warnings:
        print(f"WARNING: {message}")
    return 0 if result.qc.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
