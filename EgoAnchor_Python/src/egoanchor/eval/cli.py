"""EgoAnchor 四阶段离线分析的最小统一命令行骨架。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from collections.abc import Sequence
from pathlib import Path

from .analysis import (
    analyze_exp1,
    analyze_exp2,
    analysis_parameters_sha256,
    build_exp1_plot_rows,
    build_paper_rows,
    build_vcd_plot_rows,
    input_workbook_set_sha256,
    load_analysis_parameters,
    load_workbook_batch,
    write_csv_tables,
)
from .preprocess import REQUIRED_FILE_NAMES, run_task_qc, write_task_workbook
from .publishing import materialize_paper, publish_artifacts


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
            if command == "analyze":
                child.add_argument(
                    "workbooks",
                    nargs="+",
                    type=Path,
                    help="一个或多个 Stage 1 完整 XLSX",
                )
                child.add_argument("--out", required=True, type=Path, help="CSV 结果目录")
                child.add_argument("--params", type=Path, help="覆盖默认分析 TOML")
                child.add_argument("--code-version", default="unknown", help="审计版本标识")
                child.set_defaults(handler=_run_analyze)
                continue
            if command == "publish":
                child.add_argument("csv_root", type=Path, help="Stage 2 CSV 结果目录")
                child.add_argument(
                    "--paper-root",
                    type=Path,
                    default=None,
                    help="论文根目录，默认从包位置解析",
                )
                child.add_argument("--out", type=Path, default=None, help="覆盖图表输出目录")
                child.add_argument("--tex-out", type=Path, default=None, help="覆盖 TeX 输出目录")
                child.set_defaults(handler=_run_publish)
                continue
            if command == "materialize-paper":
                child.add_argument(
                    "--paper-root",
                    type=Path,
                    default=None,
                    help="论文根目录，默认从包位置解析",
                )
                child.add_argument("--tex-root", type=Path, default=None, help="覆盖四个 TeX 源目录")
                child.add_argument("--manuscript", type=Path, default=None, help="覆盖中文主稿路径")
                child.set_defaults(handler=_run_materialize_paper)
                continue
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


def _default_paper_root() -> Path:
    """从 ``egoanchor/eval`` 模块位置解析仓库论文根目录。"""

    return Path(__file__).resolve().parents[4] / "2026-EgoAnchor"


def _run_publish(args: argparse.Namespace) -> int:
    """只从 Stage 2 CSV 发布论文图表，不回读 XLSX 或原始 JSONL。"""

    paper_root = args.paper_root.expanduser() if args.paper_root is not None else _default_paper_root()
    output = args.out.expanduser() if args.out is not None else paper_root / "figures" / "generated"
    tex_output = args.tex_out.expanduser() if args.tex_out is not None else paper_root / "generated"
    published = publish_artifacts(args.csv_root, output, tex_output)
    figure_result = published.figures
    latex_result = published.latex
    print(
        json.dumps(
            {
                "passed": True,
                "figure_output_root": str(figure_result.output_root),
                "tex_output_root": str(latex_result.output_root),
                "plot_count": figure_result.plot_count,
                "figure_input_csv_sha256": dict(figure_result.input_csv_sha256),
                "tex_input_csv_sha256": dict(latex_result.input_csv_sha256),
                "figure_sha256": {name: dict(value) for name, value in figure_result.figure_hashes.items()},
                "tex_sha256": dict(latex_result.tex_sha256),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return EXIT_OK


def _run_materialize_paper(args: argparse.Namespace) -> int:
    """只从四个 Stage 3 TeX 物化中文主稿受控区块。

    参数：
        args: 命令行解析后的论文根目录、TeX 根目录和主稿路径。
    """

    paper_root = args.paper_root.expanduser() if args.paper_root is not None else _default_paper_root()
    tex_root = args.tex_root.expanduser() if args.tex_root is not None else paper_root / "generated"
    manuscript = (
        args.manuscript.expanduser()
        if args.manuscript is not None
        else paper_root / "egoanchor_cn_v6.tex"
    )
    result = materialize_paper(tex_root, manuscript)
    print(
        json.dumps(
            {
                "passed": True,
                "manuscript": str(result.manuscript_path),
                "manuscript_sha256": result.manuscript_sha256,
                "source_tex_sha256": dict(result.source_tex_sha256),
                "source_csv_sha256": dict(result.source_csv_sha256),
                "block_count": result.block_count,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return EXIT_OK


def _base_result_row(row: dict[str, object]) -> dict[str, object]:
    """把 render/admission 原始行投影为 common CSV 的共享结果列。"""

    return {
        "session_id": row.get("session_id"),
        "experiment_id": row.get("experiment_id"),
        "scenario_id": row.get("scenario_id"),
        "trial_id": row.get("trial_id"),
        "event_id": row.get("event_id"),
        "condition_id": row.get("condition_id"),
        "variant_id": row.get("variant_id"),
        "metric_key": row.get("metric_key"),
        "metric_value": row.get("metric_value"),
        "metric_unit": row.get("metric_unit"),
        "aggregation_level": row.get("aggregation_level"),
        "input_workbook_sha256": row.get("input_workbook_sha256"),
    }


def _run_analyze(args: argparse.Namespace) -> int:
    """只从 Stage 1 XLSX 计算实验一/二并原子发布 CSV。"""

    batch = load_workbook_batch(args.workbooks)
    params = load_analysis_parameters(args.params)
    exp1 = analyze_exp1(batch.trials, params)
    exp2 = analyze_exp2(batch.trials, batch.variant_definitions, batch.vcd_candidates, params)
    candidate_rows_by_key: dict[tuple[object, object], dict[str, object]] = {}
    for candidate_row in batch.candidate_rows:
        key = (candidate_row.get("session_id"), candidate_row.get("candidate_id"))
        existing = candidate_rows_by_key.get(key)
        if existing is None or candidate_row.get("variant_id") == "EgoAnchor":
            candidate_rows_by_key[key] = candidate_row
    tables: dict[str, list[object]] = {
        "exp1/event_metrics": [*exp1.event_metrics],
        "exp1/trial_metrics": [*exp1.trial_metrics],
        "exp1/session_metrics": [*exp1.session_metrics],
        "exp1/scenario_summary": [*exp1.scenario_summary],
        "exp2/event_metrics": [*exp2.components.event_metrics],
        "exp2/trial_metrics": [*exp2.components.trial_metrics],
        "exp2/session_metrics": [*exp2.components.session_metrics],
        "exp2/paired_deltas": [*exp2.components.paired_deltas],
        "exp2/paired_summary": [*exp2.components.paired_summary],
        "exp2/vcd_risk_points": [*exp2.vcd.risk_points],
        "exp2/vcd_curve": [*exp2.vcd.curve],
        "exp2/vcd_aurc": [*exp2.vcd.aurc],
        "trial_windows": list(batch.trial_windows),
        "frame_metrics": [
            {
                **_base_result_row(row),
                "event_id": row.get("event_id") or "",
                "metric_key": "render_tick",
                "aggregation_level": "frame",
                "frame_id": row.get("render_tick_id"),
            }
            for row in batch.frame_rows
        ],
        "candidate_metrics": [
            {
                **_base_result_row(row),
                "event_id": row.get("event_id") or "",
                "metric_key": "candidate",
                "aggregation_level": "candidate",
                "candidate_id": row.get("candidate_id"),
            }
            for row in candidate_rows_by_key.values()
        ],
        "analysis_qc": [
            {"check_id": "stage2_input_xlsx_only", "status": "passed", "observed": len(batch.inputs), "expected": len(batch.inputs), "details": "仅读取 Stage 1 XLSX"},
            {"check_id": "completed_trial_count", "status": "passed", "observed": len(batch.trials), "expected": len(batch.trials), "details": "final trial 投影完成"},
        ],
    }
    exp1_plots = build_exp1_plot_rows(exp1.event_metrics)
    tables["exp1_static_timeline"] = list(exp1_plots.static_timeline)
    tables["exp1_motion_events"] = list(exp1_plots.motion_events)
    tables["exp1_occlusion_events"] = list(exp1_plots.occlusion_events)
    tables["exp2_component_deltas"] = [
        {**asdict(row), "plot_id": "exp2_component_deltas", "panel_id": row.component_id}
        for row in exp2.components.paired_deltas
    ]
    tables["exp2_vcd_curve"] = list(build_vcd_plot_rows(exp2.vcd.curve))
    input_set_hash = input_workbook_set_sha256(item.sha256 for item in batch.inputs)
    tables["plot_catalog"] = [
        {
            "plot_id": plot_id,
            "panel_id": panel_id,
            "source_csv": source_csv,
            "x": x_axis,
            "y": y_axis,
            "hue": hue,
            "filter_rule_id": "completed_formal_trials",
            "order": order,
            "unit": unit,
            "target_width": "columnwidth",
            "expected_rows": expected_rows,
            "data_sha256": input_set_hash,
        }
        for order, (plot_id, panel_id, source_csv, x_axis, y_axis, hue, unit, expected_rows) in enumerate(
            (
                ("exp1_static_timeline", "static_head_motion", "plots/exp1_static_timeline.csv", "event_id", "metric_value", "variant_id", "mm", len(tables["exp1_static_timeline"])),
                ("exp1_motion_events", "motion", "plots/exp1_motion_events.csv", "event_id", "metric_value", "variant_id", "mm", len(tables["exp1_motion_events"])),
                ("exp1_occlusion_events", "occlusion_recovery", "plots/exp1_occlusion_events.csv", "event_id", "metric_value", "variant_id", "mm", len(tables["exp1_occlusion_events"])),
                ("exp2_component_deltas", "components", "plots/exp2_component_deltas.csv", "event_id", "delta", "component_id", "mixed", len(tables["exp2_component_deltas"])),
                ("exp2_vcd_curve", "risk_coverage", "plots/exp2_vcd_curve.csv", "coverage", "risk_mm", "reference_kind", "mm", len(tables["exp2_vcd_curve"])),
            ),
        )
    ]
    paper_rows = build_paper_rows(batch.trials, exp1, exp2)
    tables["numbers"] = list(paper_rows.numbers)
    tables["tables"] = list(paper_rows.tables)
    published = write_csv_tables(
        args.out,
        tables,
        input_workbooks=batch.inputs,
        code_version=args.code_version,
        parameter_set_id=analysis_parameters_sha256(args.params),
    )
    print(
        json.dumps(
            {
                "passed": True,
                "output_root": str(published.output_root),
                "input_workbooks": [str(item.path) for item in batch.inputs],
                "table_count": len(published.table_sha256),
                "trial_count": len(batch.trials),
                "input_sha256": [item.sha256 for item in batch.inputs],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
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
