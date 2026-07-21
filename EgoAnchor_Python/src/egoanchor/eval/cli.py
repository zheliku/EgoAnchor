"""EgoAnchor Stage 1 预处理与论文重建命令行。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from .paper_analysis.pipeline import build_paper
from .paper_analysis.settings import DEFAULT_SETTINGS_PATH
from .preprocess import (
    REQUIRED_FILE_NAMES,
    TASK_SOURCE_FILE_NAMES,
    finalize_task_events,
    run_task_qc,
    write_task_workbook,
)


EXIT_OK = 0
"""命令完整成功。"""

EXIT_IO_ERROR = 1
"""文件系统或输入源缺失。"""

EXIT_DATA_ERROR = 2
"""schema、QC 或论文输入契约失败。"""

STAGE_COMMANDS = ("qc", "preprocess", "build-paper")
"""保留 Stage 1 桥梁并替换旧 Stage 2/3 的唯一命令集合。"""

_TASK_DIRECTORY_PATTERN = re.compile(r"^task_(?P<task_number>[1-9][0-9]*)_")


def build_parser() -> argparse.ArgumentParser:
    """构造 qc、preprocess 和 build-paper 参数解析器。"""

    parser = argparse.ArgumentParser(prog="python -m egoanchor.eval.cli", description="EgoAnchor 离线论文重建")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    qc = subparsers.add_parser("qc", help="物化跨端事件总表并执行 schema-v2 检查")
    qc.add_argument("task_dirs", nargs="+", type=Path)
    qc.set_defaults(handler=_run_qc)
    preprocess = subparsers.add_parser("preprocess", help="将原始 task 目录预处理为完整 XLSX")
    preprocess.add_argument("task_dirs", nargs="+", type=Path)
    preprocess.add_argument("--out", required=True, type=Path)
    preprocess.add_argument("--code-version", default="unknown")
    preprocess.set_defaults(handler=_run_preprocess)
    build = subparsers.add_parser(
        "build-paper",
        help="从五本 Stage 1 XLSX 重建论文",
        description="只读取 task_1 到 task_5 五本 Stage 1 XLSX，生成图表、表格和中文主稿。",
    )
    build.add_argument("workbooks", nargs="+", type=Path, help="五本初始 XLSX")
    build.add_argument("--out", required=True, type=Path, help="论文指标、绘图数据和 provenance 目录")
    build.add_argument("--paper-root", required=True, type=Path, help="论文根目录")
    build.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS_PATH)
    build.set_defaults(handler=_run_build_paper)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """运行统一 CLI，并把错误映射到冻结退出码。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    try:
        return int(args.handler(args))
    except OSError as error:
        print(f"文件系统错误：{error}", file=sys.stderr)
        return EXIT_IO_ERROR
    except ValueError as error:
        print(f"数据检查失败：{error}", file=sys.stderr)
        return EXIT_DATA_ERROR


def _run_qc(args: argparse.Namespace) -> int:
    """物化缺失事件总表，再只读检查 task。"""

    _require_task_sources(args.task_dirs, TASK_SOURCE_FILE_NAMES)
    for task_dir in args.task_dirs:
        finalize_task_events(task_dir)
    _require_task_sources(args.task_dirs, REQUIRED_FILE_NAMES)
    reports = [run_task_qc(path) for path in args.task_dirs]
    payload: object = reports[0].to_dict() if len(reports) == 1 else {
        "passed": all(report.passed for report in reports),
        "tasks": [report.to_dict() for report in reports],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return EXIT_OK if all(report.passed for report in reports) else EXIT_DATA_ERROR


def _run_preprocess(args: argparse.Namespace) -> int:
    """先整批 QC，再原子发布不变的 Stage 1 完整 XLSX。"""

    _require_task_sources(args.task_dirs, TASK_SOURCE_FILE_NAMES)
    destinations = _preprocess_destinations(args.task_dirs, args.out)
    for task_dir in args.task_dirs:
        finalize_task_events(task_dir)
    _require_task_sources(args.task_dirs, REQUIRED_FILE_NAMES)
    reports = [(task_dir, run_task_qc(task_dir)) for task_dir in args.task_dirs]
    if not all(report.passed for _, report in reports):
        print(json.dumps({"passed": False, "tasks": [report.to_dict() for _, report in reports]}, ensure_ascii=False, sort_keys=True))
        return EXIT_DATA_ERROR
    artifacts = [
        write_task_workbook(task_dir, destination, code_version=args.code_version)
        for task_dir, destination in zip(args.task_dirs, destinations, strict=True)
    ]
    print(
        json.dumps(
            {
                "passed": True,
                "output_root": str(args.out),
                "tasks": [
                    {
                        "task_directory": str(task_dir),
                        "output_workbook": str(artifact.path),
                        "workbook_sha256": artifact.sha256,
                        "input_sha256": artifact.source_set_sha256,
                        "qc": report.to_dict(),
                    }
                    for (task_dir, report), artifact in zip(reports, artifacts, strict=True)
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return EXIT_OK


def _run_build_paper(args: argparse.Namespace) -> int:
    """运行论文分析单入口；失败时不把错误结果标成成功。"""

    payload = build_paper(tuple(args.workbooks), args.out, args.paper_root, args.settings)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


def _require_task_sources(task_dirs: Sequence[Path], file_names: Sequence[str]) -> None:
    """确认原始 task 目录和固定源文件存在。"""

    for task_dir in task_dirs:
        root = task_dir.expanduser()
        if not root.is_dir():
            raise FileNotFoundError(f"schema-v2 task 目录不存在：{root}")
        missing = [name for name in file_names if not (root / name).is_file()]
        if missing:
            raise FileNotFoundError(f"schema-v2 task 缺少固定文件：{', '.join(missing)}")


def _preprocess_destinations(task_dirs: Sequence[Path], output_root: Path) -> tuple[Path, ...]:
    """校验 task 编号、去重和只读边界，返回稳定 XLSX 名称。"""

    destinations: list[Path] = []
    used_names: set[str] = set()
    normalized_output = output_root.expanduser()
    for task_dir in task_dirs:
        match = _TASK_DIRECTORY_PATTERN.match(task_dir.name)
        if match is None:
            raise ValueError(f"task 目录名称必须以 task_N_ 开头：{task_dir}")
        destination = normalized_output / f"task_{match.group('task_number')}_complete.xlsx"
        if destination.name in used_names:
            raise ValueError(f"输入批次包含重复 task 编号：{match.group('task_number')}")
        if destination.resolve().is_relative_to(task_dir.expanduser().resolve()):
            raise ValueError(f"禁止在只读 task 目录内发布工作簿：{destination}")
        used_names.add(destination.name)
        destinations.append(destination)
    return tuple(destinations)


__all__ = ["EXIT_DATA_ERROR", "EXIT_IO_ERROR", "EXIT_OK", "STAGE_COMMANDS", "build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
