"""通过 `pixi run eval` 调用的实验一/二唯一人工入口。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from .batch import (
    BatchToolError,
    analyze_current,
    compile_current_paper,
    copy_current_assets,
    describe_workflow,
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
    """构造不需要人工传递路径的纯 Pixi 命令。"""

    parser = argparse.ArgumentParser(
        prog="pixi run eval",
        description="EgoAnchor 实验一/二数据整理、本地分析与图片发布",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    config = subparsers.add_parser("config", help="显示当前生效的输入、输出和论文文件")
    config.set_defaults(handler=_run_config)

    sessions = subparsers.add_parser("sessions", help="列出新采集暂存区中的 session")
    sessions.set_defaults(handler=_run_sessions)

    stage = subparsers.add_parser("stage", help="暂存五个 session，执行 QC 并生成工作簿")
    stage.add_argument(
        "session_directories",
        nargs=5,
        metavar="SESSION_DIR",
        help="填写 data/eval 下的五个 session 目录名，程序按 completed_tasks 自动映射任务",
    )
    stage.set_defaults(handler=_run_stage)

    promote = subparsers.add_parser("promote", help="将已验证暂存批次切换为当前活动批次")
    promote.add_argument("batch_id", nargs="?", help="省略时要求暂存区恰好只有一个批次")
    promote.set_defaults(handler=_run_promote)

    qc = subparsers.add_parser("qc", help="检查当前活动批次的五项 raw 数据")
    qc.set_defaults(handler=_run_qc)

    preprocess = subparsers.add_parser("preprocess", help="将当前 raw 转为五本完整 XLSX")
    preprocess.set_defaults(handler=_run_preprocess)

    analyze = subparsers.add_parser(
        "analyze",
        help="从当前五本 XLSX 重建本地分析图表和 TeX 片段",
        description="只读取当前五本 XLSX，更新活动批次 analysis 目录，不修改论文图表、表格或主稿。",
    )
    analyze.set_defaults(handler=_run_analyze)

    copy_assets = subparsers.add_parser(
        "copy-assets",
        help="将当前实验面板和配置指定 relay PNG/PDF 复制到论文目录",
    )
    copy_assets.set_defaults(handler=_run_copy_assets)

    latex = subparsers.add_parser("latex", help="只编译当前配置的 LaTeX 主稿")
    latex.set_defaults(handler=_run_latex)

    rebuild = subparsers.add_parser("rebuild", help="从当前 raw 开始执行 preprocess 和 analyze")
    rebuild.set_defaults(handler=_run_rebuild)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """运行唯一人工 CLI，并把错误映射到稳定退出码。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    try:
        payload = args.handler(args)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_DATA_ERROR if payload.get("passed") is False else EXIT_OK
    except (OSError, BatchToolError) as error:
        print(f"文件或工具错误：{error}", file=sys.stderr)
        return EXIT_IO_ERROR
    except ValueError as error:
        print(f"数据检查失败：{error}", file=sys.stderr)
        return EXIT_DATA_ERROR


def _run_config(_args: argparse.Namespace) -> dict[str, object]:
    """显示 batch.toml 解析后的绝对输入和输出。"""

    return describe_workflow()


def _run_sessions(_args: argparse.Namespace) -> dict[str, object]:
    """列出 eval session，不修改任何日志。"""

    rows = list_eval_sessions()
    return {"passed": True, "count": len(rows), "sessions": rows}


def _run_stage(args: argparse.Namespace) -> dict[str, object]:
    """暂存五个 session 并返回下一条 Pixi 命令。"""

    return stage_batch(args.session_directories).to_dict()


def _run_promote(args: argparse.Namespace) -> dict[str, object]:
    """切换当前活动批次。"""

    return promote_batch(args.batch_id)


def _run_qc(_args: argparse.Namespace) -> dict[str, object]:
    """检查当前活动批次的五项 raw 数据。"""

    return qc_current()


def _run_preprocess(_args: argparse.Namespace) -> dict[str, object]:
    """从当前 raw 生成五本 Stage 1 工作簿。"""

    return preprocess_current()


def _run_analyze(_args: argparse.Namespace) -> dict[str, object]:
    """从当前工作簿重建本地分析产物。"""

    return analyze_current()


def _run_copy_assets(_args: argparse.Namespace) -> dict[str, object]:
    """显式复制配置允许的论文图片资源。"""

    return copy_current_assets()


def _run_latex(_args: argparse.Namespace) -> dict[str, object]:
    """只编译当前配置的主稿。"""

    return compile_current_paper()


def _run_rebuild(_args: argparse.Namespace) -> dict[str, object]:
    """从当前 raw 完整重建本地分析产物。"""

    return rebuild_current()


__all__ = [
    "EXIT_DATA_ERROR",
    "EXIT_IO_ERROR",
    "EXIT_OK",
    "build_parser",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
