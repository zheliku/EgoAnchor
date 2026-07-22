"""通过 `pixi run eval` 调用的实验一/二批次工作流。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from .batch import (
    BatchToolError,
    analyze_current,
    compile_current_paper,
    list_eval_sessions,
    preprocess_current,
    promote_batch,
    qc_current,
    rebuild_current,
    stage_batch,
)


EXIT_OK = 0
"""命令完整成功。"""

EXIT_IO_ERROR = 1
"""文件系统或外部工具错误。"""

EXIT_DATA_ERROR = 2
"""批次、schema、QC 或论文输入契约错误。"""


def build_parser() -> argparse.ArgumentParser:
    """构造面向人工使用的纯 Pixi 批次命令。"""

    parser = argparse.ArgumentParser(
        prog="pixi run eval",
        description="EgoAnchor 实验一/二批次整理与论文重建",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    sessions = subparsers.add_parser("sessions", help="列出 data/eval 中的 session")
    sessions.set_defaults(handler=_run_sessions)

    stage = subparsers.add_parser("stage", help="按任务 1--5 暂存五个 session 并生成工作簿")
    stage.add_argument(
        "session_ids",
        nargs=5,
        metavar="SESSION_ID",
        help="填写五个 session ID，程序按 completed_tasks 自动映射任务",
    )
    stage.set_defaults(handler=_run_stage)

    promote = subparsers.add_parser("promote", help="将已验证暂存批次切换为当前活动批次")
    promote.add_argument("batch_id", nargs="?", help="省略时要求暂存区恰好只有一个批次")
    promote.set_defaults(handler=_run_promote)

    qc = subparsers.add_parser("qc", help="检查当前活动批次的五项 raw 数据")
    qc.set_defaults(handler=_run_qc)

    preprocess = subparsers.add_parser("preprocess", help="将当前 raw 转为五本完整 XLSX")
    preprocess.set_defaults(handler=_run_preprocess)

    rebuild = subparsers.add_parser("rebuild", help="从当前 raw 重建工作簿、图表、主稿和 PDF")
    rebuild.add_argument("--skip-latex", action="store_true", help="只重建分析和主稿，不编译 PDF")
    rebuild.set_defaults(handler=_run_rebuild)

    analyze = subparsers.add_parser("analyze", help="从当前五本工作簿重建图表、主稿和 PDF")
    analyze.add_argument("--skip-latex", action="store_true", help="只重建分析和主稿，不编译 PDF")
    analyze.set_defaults(handler=_run_analyze)

    latex = subparsers.add_parser("latex", help="只编译当前中文主稿 PDF")
    latex.set_defaults(handler=_run_latex)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """运行批次命令，并使用与正式分析一致的退出码语义。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    try:
        payload = args.handler(args)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_OK
    except (OSError, BatchToolError) as error:
        print(f"文件或工具错误：{error}", file=sys.stderr)
        return EXIT_IO_ERROR
    except ValueError as error:
        print(f"数据检查失败：{error}", file=sys.stderr)
        return EXIT_DATA_ERROR


def _run_sessions(_args: argparse.Namespace) -> dict[str, object]:
    """列出 eval session，不修改任何日志。"""

    rows = list_eval_sessions()
    return {"passed": True, "count": len(rows), "sessions": rows}


def _run_stage(args: argparse.Namespace) -> dict[str, object]:
    """暂存五个 session 并返回下一条 Pixi 命令。"""

    return stage_batch(args.session_ids).to_dict()


def _run_promote(args: argparse.Namespace) -> dict[str, object]:
    """切换当前活动批次。"""

    return promote_batch(args.batch_id)


def _run_qc(_args: argparse.Namespace) -> dict[str, object]:
    """检查当前活动批次的五项 raw 数据。"""

    return qc_current()


def _run_preprocess(_args: argparse.Namespace) -> dict[str, object]:
    """从当前 raw 生成五本 Stage 1 工作簿。"""

    return preprocess_current()


def _run_rebuild(args: argparse.Namespace) -> dict[str, object]:
    """从当前 raw 完整重建论文。"""

    return rebuild_current(
        compile_pdf=not args.skip_latex,
    )


def _run_analyze(args: argparse.Namespace) -> dict[str, object]:
    """从当前工作簿重建图表和论文。"""

    return analyze_current(compile_pdf=not args.skip_latex)


def _run_latex(_args: argparse.Namespace) -> dict[str, object]:
    """只编译当前中文主稿。"""

    return compile_current_paper()


__all__ = [
    "EXIT_DATA_ERROR",
    "EXIT_IO_ERROR",
    "EXIT_OK",
    "build_parser",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
