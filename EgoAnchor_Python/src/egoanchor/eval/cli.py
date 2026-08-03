"""通过 ``pixi run eval`` 使用的统一评估工程命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from tqdm.auto import tqdm

from .experiments import (
    BatchToolError,
    analyze_workspace,
    copy_workspace_assets,
    create_raw_template,
    describe_workspace,
    list_task_data,
    preprocess_current,
    promote_batch,
    stage_batch,
    validate_workspace,
)


EXIT_OK = 0
"""命令完整成功。"""

EXIT_IO_ERROR = 1
"""文件系统、Git 或其他外部工具错误。"""

EXIT_DATA_ERROR = 2
"""数据、schema、QC 或论文输入契约错误。"""

_TARGETS = ("all", "exp1-2", "exp3")
"""生命周期命令接受的稳定目标集合。"""


def build_parser() -> argparse.ArgumentParser:
    """构造生命周期统一、正式路径固定的纯 Pixi 命令。"""

    parser = argparse.ArgumentParser(
        prog="pixi run eval",
        description="EgoAnchor 实验一/二与实验三统一离线评估工程",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    status = commands.add_parser("status", help="只读显示配置、输入进度和最近构建状态")
    status.add_argument("target", nargs="?", choices=_TARGETS, default="all", help="默认显示全部实验")
    status.set_defaults(handler=_run_status)

    validate = commands.add_parser("validate", help="检查正式输入能否进入分析")
    validate.add_argument("target", choices=_TARGETS, help="要验证的实验集合")
    validate.set_defaults(handler=_run_validate)

    analyze = commands.add_parser("analyze", help="生成指定实验的全部本地分析产物")
    analyze_targets = analyze.add_subparsers(dest="target", metavar="TARGET", required=True)
    analyze_exp12 = analyze_targets.add_parser("exp1-2", help="分析当前五任务活动批次")
    analyze_exp12.add_argument("--rebuild", action="store_true", help="先强制重建五本 Stage 1 工作簿")
    analyze_exp12.set_defaults(handler=_run_analyze, rebuild_experiment_1_2=False)
    analyze_exp3 = analyze_targets.add_parser("exp3", help="一次生成结果 XLSX、TeX 和全部论文图")
    analyze_exp3.set_defaults(handler=_run_analyze, rebuild_experiment_1_2=False)
    analyze_all = analyze_targets.add_parser("all", help="联合门禁通过后依次分析全部实验")
    analyze_all.add_argument(
        "--rebuild-exp1-2",
        action="store_true",
        help="联合分析前强制重建实验一/二的五本 Stage 1 工作簿",
    )
    analyze_all.set_defaults(handler=_run_analyze, rebuild_experiment_1_2=False)

    copy_assets = commands.add_parser(
        "copy-assets",
        help="联合预检后事务性复制论文图表",
    )
    copy_assets.add_argument(
        "target",
        nargs="?",
        choices=_TARGETS,
        default="exp1-2",
        help="默认复制实验一/二；使用 all 可联合复制全部实验",
    )
    copy_assets.set_defaults(handler=_run_copy_assets)

    data = commands.add_parser("data", help="管理实验专属输入，不执行论文统计")
    data_targets = data.add_subparsers(dest="data_target", metavar="TARGET", required=True)
    _add_experiment_1_2_data_commands(data_targets)
    _add_experiment_3_data_commands(data_targets)
    return parser


def _add_experiment_1_2_data_commands(targets: argparse._SubParsersAction) -> None:
    """注册实验一/二的 session、暂存、提升和预处理命令。"""

    experiment = targets.add_parser("exp1-2", help="管理实验一/二五任务批次")
    commands = experiment.add_subparsers(dest="data_command", metavar="COMMAND", required=True)

    sessions = commands.add_parser("sessions", help="列出任务数据目录中的可选 session")
    sessions.set_defaults(handler=_run_sessions)

    stage = commands.add_parser("stage", help="选择五项任务并准备独立 Stage 1 缓存")
    stage.add_argument(
        "--version",
        type=_parse_version,
        metavar="VERSION",
        help="五项任务统一使用指定版本，例如 2 或 v2",
    )
    stage.add_argument(
        "--task-version",
        action="append",
        default=[],
        metavar="TASK=VERSION",
        help="覆盖单项任务版本，可重复使用",
    )
    stage.add_argument("--object", dest="object_name", metavar="OBJECT", help="限制正式物体目录名")
    stage.add_argument("--promote", action="store_true", help="暂存成功后立即切换为活动批次")
    stage.set_defaults(handler=_run_stage)

    promote = commands.add_parser("promote", help="切换已验证的暂存批次")
    promote.add_argument("batch_id", nargs="?", help="省略时要求暂存区恰好只有一个批次")
    promote.set_defaults(handler=_run_promote)

    preprocess = commands.add_parser("preprocess", help="补建活动批次缺失或失效的 Stage 1 工作簿")
    preprocess.add_argument("--force", action="store_true", help="强制重建全部五本工作簿")
    preprocess.set_defaults(handler=_run_preprocess)


def _add_experiment_3_data_commands(targets: argparse._SubParsersAction) -> None:
    """注册实验三正式空白模板生成命令。"""

    experiment = targets.add_parser("exp3", help="管理实验三正式原始工作簿")
    commands = experiment.add_subparsers(dest="data_command", metavar="COMMAND", required=True)
    template = commands.add_parser("create-template", help="在新路径生成空白正式模板")
    template.add_argument("--output", type=Path, required=True, help="必须是尚不存在的新工作簿路径")
    template.set_defaults(handler=_run_create_template)


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


def _run_status(args: argparse.Namespace) -> dict[str, object]:
    """显示目标工作区状态。"""

    return describe_workspace(args.target)


def _run_validate(args: argparse.Namespace) -> dict[str, object]:
    """运行目标正式分析门禁。"""

    return validate_workspace(args.target)


def _run_analyze(args: argparse.Namespace) -> dict[str, object]:
    """显示实验三阶段进度，并运行指定目标的完整本地分析。"""

    rebuild = bool(
        getattr(args, "rebuild", False) or getattr(args, "rebuild_exp1_2", False)
    )
    if args.target not in {"exp3", "all"}:
        return analyze_workspace(args.target, rebuild_experiment_1_2=rebuild)
    with tqdm(total=18, desc=f"analyze {args.target}", unit="stage", leave=False) as bar:
        def update(message: str) -> None:
            """更新实验三分析阶段，保持 stdout 只有 JSON。"""

            bar.set_postfix_str(message)
            bar.update(1)

        return analyze_workspace(
            args.target,
            rebuild_experiment_1_2=rebuild,
            experiment_3_progress=update,
        )


def _run_copy_assets(args: argparse.Namespace) -> dict[str, object]:
    """通过统一事务复制明确目标集合。"""

    return copy_workspace_assets(args.target)


def _run_sessions(_args: argparse.Namespace) -> dict[str, object]:
    """列出实验一/二候选 session，不修改任何日志。"""

    rows = list_task_data()
    return {"passed": True, "target": "exp1-2", "count": len(rows), "sessions": rows}


def _run_stage(args: argparse.Namespace) -> dict[str, object]:
    """准备五项独立缓存和组合清单，并可立即提升。"""

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
    promoted["next_command"] = "pixi run eval analyze exp1-2"
    return promoted


def _run_promote(args: argparse.Namespace) -> dict[str, object]:
    """切换实验一/二当前活动批次。"""

    return promote_batch(args.batch_id)


def _run_preprocess(args: argparse.Namespace) -> dict[str, object]:
    """增量或强制重建实验一/二 Stage 1 工作簿。"""

    return preprocess_current(force=args.force)


def _run_create_template(args: argparse.Namespace) -> dict[str, object]:
    """从只读工作簿结构来源生成新的实验三空白正式模板。"""

    return create_raw_template(args.output)


def _parse_version(value: str) -> int:
    """把命令行中的 ``2`` 或 ``v2`` 解析为正整数版本。"""

    normalized = value[1:] if value.lower().startswith("v") else value
    if not normalized.isdigit() or normalized.startswith("0"):
        raise argparse.ArgumentTypeError("版本必须是正整数，例如 2 或 v2")
    return int(normalized)


def _parse_task_versions(values: Sequence[str]) -> dict[int, int]:
    """解析可重复的 ``TASK=VERSION``，并拒绝重复任务覆盖。"""

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


__all__ = ["EXIT_DATA_ERROR", "EXIT_IO_ERROR", "EXIT_OK", "build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
