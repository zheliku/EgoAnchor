"""EgoAnchor 四阶段离线分析的最小统一命令行骨架。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from .preprocess import REQUIRED_FILE_NAMES, run_task_qc, write_task_workbook


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

_TASK_DIRECTORY_PATTERN = re.compile(r"^task_(?P<task_number>[1-9][0-9]*)_")
"""正式原始 task 目录提取稳定任务编号的命名规则。"""


def build_parser() -> argparse.ArgumentParser:
    """构造只包含新四阶段命令的参数解析器。"""

    parser = argparse.ArgumentParser(
        prog="python -m egoanchor.eval.cli",
        description="EgoAnchor schema-v2 四阶段离线分析",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for command in STAGE_COMMANDS:
        child = subparsers.add_parser(command, help=_command_help(command))
        if command == "qc":
            child.add_argument(
                "task_dirs",
                nargs="+",
                type=Path,
                help="一个或多个完整 schema-v2 task 目录",
            )
            child.set_defaults(handler=_run_qc)
        elif command == "preprocess":
            child.add_argument(
                "task_dirs",
                nargs="+",
                type=Path,
                help="一个或多个只读 schema-v2 task 目录",
            )
            child.add_argument(
                "--out",
                required=True,
                type=Path,
                help="完整 XLSX 工作簿的发布目录",
            )
            child.add_argument(
                "--code-version",
                default="unknown",
                help="写入 provenance 的代码版本或提交标识",
            )
            child.set_defaults(handler=_run_preprocess)
        else:
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


def _run_qc(args: argparse.Namespace) -> int:
    """只读检查一个或多个 task，打印稳定 JSON 并返回统一退出码。"""

    _require_task_sources(args.task_dirs)
    reports = [run_task_qc(path) for path in args.task_dirs]
    if len(reports) == 1:
        payload: object = reports[0].to_dict()
    else:
        payload = {
            "passed": all(report.passed for report in reports),
            "tasks": [report.to_dict() for report in reports],
        }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return EXIT_OK if all(report.passed for report in reports) else EXIT_DATA_ERROR


def _run_preprocess(args: argparse.Namespace) -> int:
    """先对完整批次执行只读 QC，再逐 task 原子发布 workbook-v2。"""

    _require_task_sources(args.task_dirs)
    destinations = _preprocess_destinations(args.task_dirs, args.out)
    reports = [(task_dir, run_task_qc(task_dir)) for task_dir in args.task_dirs]
    if not all(report.passed for _, report in reports):
        print(
            json.dumps(
                {
                    "passed": False,
                    "tasks": [
                        {
                            "task_directory": str(task_dir),
                            **report.to_dict(),
                        }
                        for task_dir, report in reports
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return EXIT_DATA_ERROR

    artifacts = [
        write_task_workbook(task_dir, destination, code_version=args.code_version)
        for task_dir, destination in zip(args.task_dirs, destinations, strict=True)
    ]
    print(
        json.dumps(
            {
                "passed": True,
                "code_version": args.code_version,
                "output_root": str(args.out),
                "tasks": [
                    {
                        "task_directory": str(task_dir),
                        "session_id": report.session_id,
                        "output_workbook": str(artifact.path),
                        "workbook_sha256": artifact.sha256,
                        "input_sha256": artifact.source_set_sha256,
                        "qc": report.to_dict(),
                        "verification": {
                            "passed": artifact.verification.passed,
                            "logical_row_counts": dict(artifact.verification.logical_row_counts),
                            "large_value_count": artifact.verification.large_value_count,
                        },
                    }
                    for (task_dir, report), artifact in zip(reports, artifacts, strict=True)
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return EXIT_OK


def _require_task_sources(task_dirs: Sequence[Path]) -> None:
    """确认 task 目录和固定源文件存在；缺源统一交给退出码一处理。"""

    for task_dir in task_dirs:
        root = task_dir.expanduser()
        if not root.is_dir():
            raise FileNotFoundError(f"schema-v2 task 目录不存在：{root}")
        missing = [name for name in REQUIRED_FILE_NAMES if not (root / name).is_file()]
        if missing:
            raise FileNotFoundError(f"schema-v2 task 缺少固定文件：{', '.join(missing)}")


def _preprocess_destinations(task_dirs: Sequence[Path], output_root: Path) -> tuple[Path, ...]:
    """验证固定 task 文件名、去重和只读原始目录边界后返回发布路径。"""

    destinations: list[Path] = []
    used_names: set[str] = set()
    normalized_output_root = output_root.expanduser()
    for task_dir in task_dirs:
        match = _TASK_DIRECTORY_PATTERN.match(task_dir.name)
        if match is None:
            raise ValueError(f"task 目录名称必须以 task_N_ 开头：{task_dir}")
        destination = normalized_output_root / f"task_{match.group('task_number')}_complete.xlsx"
        if destination.name in used_names:
            raise ValueError(f"输入批次包含重复 task 编号：{match.group('task_number')}")
        if destination.resolve().is_relative_to(task_dir.expanduser().resolve()):
            raise ValueError(f"禁止在只读 task 目录内发布工作簿：{destination}")
        used_names.add(destination.name)
        destinations.append(destination)
    return tuple(destinations)


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
