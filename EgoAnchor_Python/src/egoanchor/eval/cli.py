"""通过 ``pixi run eval`` 调用的实验一、二、三统一人工入口。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from tqdm.auto import tqdm

from .batch import (
    BatchToolError,
    analyze_current,
    describe_workflow,
    list_task_data,
    preprocess_current,
    plan_current_assets,
    promote_batch,
    qc_current,
    rebuild_current,
    stage_batch,
)
from .paper_analysis.experiment_3 import (
    analyze_experiment3,
    create_template as create_experiment3_template,
    describe_experiment3,
    plan_experiment3_assets_if_ready,
    plot_experiment3,
    validate_input as validate_experiment3_input,
)
from .paper_analysis.common import publish_artifact_plans


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
        description="EgoAnchor 实验一/二批次分析与实验三问卷分析",
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

    experiment3 = subparsers.add_parser(
        "experiment3",
        help="实验三原始模板、问卷统计、CLMM 与论文图",
    )
    experiment3.set_defaults(handler=_run_experiment3_help, experiment3_parser=experiment3)
    experiment3_commands = experiment3.add_subparsers(dest="experiment3_command", metavar="COMMAND")

    experiment3_config = experiment3_commands.add_parser("config", help="显示实验三配置与当前填表进度")
    experiment3_config.set_defaults(handler=_run_experiment3_config)

    experiment3_template = experiment3_commands.add_parser("build-template", help="在新路径生成空白原始模板")
    experiment3_template.add_argument("--destination", type=Path, required=True, help="必须是尚不存在的新工作簿路径")
    experiment3_template.set_defaults(handler=_run_experiment3_template)

    experiment3_validate = experiment3_commands.add_parser("validate", help="检查实验三原始工作簿结构和填表完整性")
    experiment3_validate.add_argument("--input", type=Path, help="覆盖配置中的默认输入工作簿")
    experiment3_validate.add_argument("--complete", action="store_true", help="进一步要求达到正式分析完整性")
    experiment3_validate.add_argument("--allow-synthetic", action="store_true", help=argparse.SUPPRESS)
    experiment3_validate.set_defaults(handler=_run_experiment3_validate)

    experiment3_analyze = experiment3_commands.add_parser("analyze", help="从原始值生成实验三结果 XLSX 与 TeX")
    experiment3_analyze.add_argument("--input", type=Path, help="覆盖配置中的默认输入工作簿")
    experiment3_analyze.add_argument("--output-root", type=Path, help="覆盖配置中的本地分析输出目录")
    experiment3_analyze.add_argument("--allow-synthetic", action="store_true", help=argparse.SUPPRESS)
    experiment3_analyze.set_defaults(handler=_run_experiment3_analyze)

    experiment3_plot = experiment3_commands.add_parser("plot", help="只读结果 XLSX 生成实验三 PNG/PDF")
    experiment3_plot.add_argument("--output-root", type=Path, help="覆盖配置中的本地分析输出目录")
    experiment3_plot.set_defaults(handler=_run_experiment3_plot)
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
    """联合预检已就绪的实验一/二与实验三，再一次性发布论文资源。"""

    experiment3_plan = plan_experiment3_assets_if_ready()
    experiment12_plan = None
    try:
        experiment12_plan = plan_current_assets()
    except (FileNotFoundError, BatchToolError) as error:
        if experiment3_plan is None:
            raise
        experiment12_status: dict[str, object] = {"status": "skipped", "reason": str(error)}
    else:
        experiment12_status = {"status": "published"}
    plans = tuple(plan for plan in (experiment12_plan, experiment3_plan) if plan is not None)
    published = publish_artifact_plans(plans)
    by_owner = {
        owner: [item for item in published if item["owner"] == owner]
        for owner in ("experiment_1_2", "experiment_3")
    }
    if experiment12_plan is not None:
        experiment12_status["published"] = by_owner["experiment_1_2"]
    experiment3_status: dict[str, object]
    if experiment3_plan is None:
        experiment3_status = {"status": "skipped", "reason": "实验三尚无完整分析构建"}
    else:
        experiment3_status = {
            "status": "published",
            "published": by_owner["experiment_3"],
        }
    return {
        "passed": True,
        "experiment_1_2": experiment12_status,
        "experiment_3": experiment3_status,
        "next_command": "审阅已发布图表，并按论文工作流自行编译主稿",
    }


def _run_rebuild(_args: argparse.Namespace) -> dict[str, object]:
    """从当前 raw 完整重建本地分析产物。"""

    return rebuild_current()


def _run_experiment3_help(args: argparse.Namespace) -> dict[str, object]:
    """缺少实验三子命令时打印局部帮助。"""

    args.experiment3_parser.print_help()
    return {"passed": True}


def _run_experiment3_config(_args: argparse.Namespace) -> dict[str, object]:
    """显示实验三配置与工作簿进度。"""

    return describe_experiment3()


def _run_experiment3_template(args: argparse.Namespace) -> dict[str, object]:
    """从美化来源重建空白正式模板。"""

    return create_experiment3_template(destination=args.destination)


def _run_experiment3_validate(args: argparse.Namespace) -> dict[str, object]:
    """检查实验三输入结构或正式分析完整性。"""

    return validate_experiment3_input(
        input_workbook=args.input,
        require_complete=args.complete,
        allow_synthetic=args.allow_synthetic,
    )


def _run_experiment3_analyze(args: argparse.Namespace) -> dict[str, object]:
    """显示阶段进度并运行完整实验三离线分析。"""

    with tqdm(total=17, desc="experiment3 analyze", unit="stage", leave=False) as bar:
        def update(message: str) -> None:
            """更新分析阶段描述，保持 JSON stdout 干净。"""

            bar.set_postfix_str(message)
            bar.update(1)

        return analyze_experiment3(
            input_workbook=args.input,
            output_root=args.output_root,
            allow_synthetic=args.allow_synthetic,
            progress=update,
        )


def _run_experiment3_plot(args: argparse.Namespace) -> dict[str, object]:
    """从结果工作簿回读并生成论文图。"""

    return plot_experiment3(output_root=args.output_root)


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
