"""通过 `pixi run eval` 调用的实验一/二唯一人工入口。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from .batch import (
    BatchToolError,
    analyze_current,
    copy_current_assets,
    describe_workflow,
    list_task_data,
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
        description="EgoAnchor 实验一/二数据整理、本地分析与图表发布",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    config = subparsers.add_parser("config", help="显示当前生效的数据路径和图表发布位置")
    config.set_defaults(handler=_run_config)

    sessions = subparsers.add_parser("sessions", help="列出任务数据目录中的可选 session")
    sessions.set_defaults(handler=_run_sessions)

    stage = subparsers.add_parser("stage", help="自动选择五项任务，只处理缺失或变化的任务缓存")
    stage.add_argument(
        "--version",
        type=_parse_version,
        metavar="VERSION",
        help="五项任务统一使用指定版本，例如 2 或 v2；省略时各任务使用最高版本",
    )
    stage.add_argument(
        "--task-version",
        action="append",
        default=[],
        metavar="TASK=VERSION",
        help="覆盖单项任务版本，可重复使用，例如 --task-version 3=v2",
    )
    stage.add_argument(
        "--object",
        dest="object_name",
        metavar="OBJECT",
        help="限制目录名中的物体；存在多个完整物体批次时必须指定",
    )
    stage.add_argument(
        "--promote",
        action="store_true",
        help="任务缓存就绪后立刻切换活动组合，无需手工输入 batch_id",
    )
    stage.set_defaults(handler=_run_stage)

    promote = subparsers.add_parser("promote", help="将已验证暂存批次切换为当前活动批次")
    promote.add_argument("batch_id", nargs="?", help="省略时要求暂存区恰好只有一个批次")
    promote.set_defaults(handler=_run_promote)

    qc = subparsers.add_parser("qc", help="显式深查活动组合引用的五项原始数据")
    qc.set_defaults(handler=_run_qc)

    preprocess = subparsers.add_parser("preprocess", help="补建活动组合中缺失或失效的任务 XLSX")
    preprocess.set_defaults(handler=_run_preprocess)

    analyze = subparsers.add_parser(
        "analyze",
        help="复用逐任务指标缓存，生成当前组合的图表和 TeX 片段",
        description="从当前五本 XLSX 复用逐任务缓存，只重算变化任务并更新 analysis；不修改论文目录或主稿。",
    )
    analyze.set_defaults(handler=_run_analyze)

    copy_assets = subparsers.add_parser(
        "copy-assets",
        help="将当前实验面板、表格 TeX 和配置指定 relay 文件复制到论文目录",
    )
    copy_assets.set_defaults(handler=_run_copy_assets)

    rebuild = subparsers.add_parser("rebuild", help="显式强制重建五项 XLSX 和全部分析产物")
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

    rows = list_task_data()
    return {"passed": True, "count": len(rows), "sessions": rows}


def _run_stage(args: argparse.Namespace) -> dict[str, object]:
    """准备五项独立缓存和组合清单，并返回下一条 Pixi 命令。"""

    artifact = stage_batch(
        version=args.version,
        task_versions=_parse_task_versions(args.task_version),
        object_name=args.object_name,
    )
    if not args.promote:
        return artifact.to_dict()
    promoted = promote_batch(artifact.batch_id)
    promoted["staged_batch"] = artifact.batch_id
    promoted["workbook_sha256"] = artifact.workbook_sha256
    promoted["cache_hits"] = list(artifact.cache_hits)
    promoted["rebuilt_tasks"] = list(artifact.rebuilt_tasks)
    promoted["next_command"] = "pixi run eval analyze"
    return promoted


def _run_promote(args: argparse.Namespace) -> dict[str, object]:
    """切换当前活动批次。"""

    return promote_batch(args.batch_id)


def _run_qc(_args: argparse.Namespace) -> dict[str, object]:
    """显式深查当前活动组合的五项原始数据。"""

    return qc_current()


def _run_preprocess(_args: argparse.Namespace) -> dict[str, object]:
    """补建当前活动组合缺失或失效的 Stage 1 工作簿。"""

    return preprocess_current()


def _run_analyze(_args: argparse.Namespace) -> dict[str, object]:
    """从当前工作簿重建本地分析产物。"""

    return analyze_current()


def _run_copy_assets(_args: argparse.Namespace) -> dict[str, object]:
    """显式复制配置允许的论文图片资源。"""

    return copy_current_assets()


def _run_rebuild(_args: argparse.Namespace) -> dict[str, object]:
    """从当前 raw 完整重建本地分析产物。"""

    return rebuild_current()


def _parse_version(value: str) -> int:
    """把命令行中的 `2` 或 `v2` 解析为正整数版本。"""

    normalized = value[1:] if value.lower().startswith("v") else value
    if not normalized.isdigit() or normalized.startswith("0"):
        raise argparse.ArgumentTypeError("版本必须是正整数，例如 2 或 v2")
    return int(normalized)


def _parse_task_versions(values: Sequence[str]) -> dict[int, int]:
    """解析可重复的 TASK=VERSION，并拒绝重复任务覆盖。"""

    parsed: dict[int, int] = {}
    for value in values:
        task_text, separator, version_text = value.partition("=")
        if separator != "=" or task_text not in {"1", "2", "3", "4", "5"}:
            raise ValueError("--task-version 必须写成 TASK=VERSION，TASK 范围为 1--5")
        task_number = int(task_text)
        if task_number in parsed:
            raise ValueError(f"任务 {task_number} 的版本重复指定")
        try:
            parsed[task_number] = _parse_version(version_text)
        except argparse.ArgumentTypeError as error:
            raise ValueError(f"任务 {task_number} 的{error}") from error
    return parsed


__all__ = [
    "EXIT_DATA_ERROR",
    "EXIT_IO_ERROR",
    "EXIT_OK",
    "build_parser",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
