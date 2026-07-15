"""EgoAnchor schema-v2 QC 与实验一/二分析的统一命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .experiments import run_exp1_system_characterization, run_exp2_design_attribution
from .paper import publish_analysis_outputs
from .schema_v2 import SchemaV2Error, load_session_v2, run_schema_qc


EXIT_OK = 0
"""命令完整成功。"""

EXIT_IO_ERROR = 1
"""输出目录或 session 文件发生文件系统错误。"""

EXIT_DATA_ERROR = 2
"""schema、QC、参数或分析数据契约失败。"""


def build_parser() -> argparse.ArgumentParser:
    """构造只包含 schema-v2 正式命令的参数解析器。"""

    parser = argparse.ArgumentParser(
        prog="python -m egoanchor.eval.cli",
        description="EgoAnchor schema-v2 质量检查与实验一/二分析",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    qc_parser = subparsers.add_parser("qc", help="检查一个 schema-v2 session")
    qc_parser.add_argument("session_dir", type=Path, help="schema-v2 session 目录")
    qc_parser.set_defaults(handler=_run_qc)

    exp1_parser = subparsers.add_parser(
        "analyze-exp1",
        help="生成实验一端到端系统表征产物",
    )
    _add_analysis_arguments(exp1_parser)
    exp1_parser.set_defaults(handler=_run_exp1)

    exp2_parser = subparsers.add_parser(
        "analyze-exp2",
        help="生成实验二系统设计归因产物",
    )
    _add_analysis_arguments(exp2_parser)
    exp2_parser.set_defaults(handler=_run_exp2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """解析参数并返回稳定进程码；不在函数内部调用 ``sys.exit``。"""

    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (SchemaV2Error, ValueError) as exc:
        print(f"数据检查失败：{exc}", file=sys.stderr)
        return EXIT_DATA_ERROR
    except OSError as exc:
        print(f"文件系统错误：{exc}", file=sys.stderr)
        return EXIT_IO_ERROR


def _add_analysis_arguments(parser: argparse.ArgumentParser) -> None:
    """给两个分析子命令添加相同的 session 与输出参数。"""

    parser.add_argument(
        "session_dirs",
        nargs="+",
        type=Path,
        help="同一采集批次的一个或多个模块化 schema-v2 session 目录",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="本次分析的 CSV、PDF 和 TeX 输出目录",
    )
    parser.add_argument(
        "--paper-root",
        type=Path,
        default=None,
        help="论文目录；默认自动定位仓库中的 2026-EgoAnchor",
    )


def _run_qc(args: argparse.Namespace) -> int:
    """执行一个 session 的 schema-v2 基础 QC 并打印 JSON 摘要。"""

    session = load_session_v2(args.session_dir)
    report = run_schema_qc(session)
    payload = {
        "session_id": session.session_id,
        "passed": report.passed,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
        "metrics": report.metrics,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return EXIT_OK if report.passed else EXIT_DATA_ERROR


def _run_exp1(args: argparse.Namespace) -> int:
    """调用实验一公开入口并要求其完成严格 QC 与产物写出。"""

    sessions = [load_session_v2(path) for path in args.session_dirs]
    run_exp1_system_characterization(sessions, args.out, config=None)
    publish_analysis_outputs("exp1", args.out, args.paper_root)
    return EXIT_OK


def _run_exp2(args: argparse.Namespace) -> int:
    """调用实验二公开入口并要求其完成严格 QC 与产物写出。"""

    sessions = [load_session_v2(path) for path in args.session_dirs]
    run_exp2_design_attribution(sessions, args.out, config=None)
    publish_analysis_outputs("exp2", args.out, args.paper_root)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXIT_DATA_ERROR",
    "EXIT_IO_ERROR",
    "EXIT_OK",
    "build_parser",
    "main",
]
