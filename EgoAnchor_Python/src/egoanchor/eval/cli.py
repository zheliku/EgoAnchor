"""EgoAnchor 四阶段离线分析的最小统一命令行骨架。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


EXIT_OK = 0
"""命令完整成功。"""

EXIT_IO_ERROR = 1
"""文件系统或发布源缺失。"""

EXIT_DATA_ERROR = 2
"""schema、QC 或分析契约失败。"""

STAGE_COMMANDS = (
    "qc",
    "preprocess",
    "analyze",
    "publish",
    "materialize-paper",
)
"""四阶段路线及其前置 QC 的统一命令顺序。"""


def build_parser() -> argparse.ArgumentParser:
    """构造只包含新四阶段命令的参数解析器。"""

    parser = argparse.ArgumentParser(
        prog="python -m egoanchor.eval.cli",
        description="EgoAnchor schema-v2 四阶段离线分析",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for command in STAGE_COMMANDS:
        child = subparsers.add_parser(command, help=_command_help(command))
        child.set_defaults(handler=_run_skeleton_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """解析参数；无参数时打印帮助并返回成功码。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    try:
        return int(args.handler(args))
    except OSError as exc:
        print(f"文件系统错误：{exc}", file=sys.stderr)
        return EXIT_IO_ERROR
    except ValueError as exc:
        print(f"数据检查失败：{exc}", file=sys.stderr)
        return EXIT_DATA_ERROR


def _run_skeleton_command(args: argparse.Namespace) -> int:
    """保留阶段入口但暂不产出结果，具体实现由后续 Task 接管。"""

    del args
    return EXIT_OK


def _command_help(command: str) -> str:
    """返回阶段命令的简短中文说明。"""

    descriptions = {
        "qc": "执行 schema-v2 基础质量检查",
        "preprocess": "将原始 task 目录预处理为完整 XLSX",
        "analyze": "只从 XLSX 计算实验指标并发布 CSV",
        "publish": "只从 CSV 发布图表和 TeX",
        "materialize-paper": "只从 TeX 物化主稿数据区块",
    }
    return descriptions[command]


__all__ = [
    "EXIT_DATA_ERROR",
    "EXIT_IO_ERROR",
    "EXIT_OK",
    "STAGE_COMMANDS",
    "build_parser",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
