"""实验一严格 QC、分析和固定产物写出入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from egoanchor.eval.schema_v2 import EvalSessionV2, load_session_v2

from .contract import DEFAULT_MIN_REFERENCE_COVERAGE, OUTPUT_TABLES
from .figures import write_exp1_figures
from .latex import write_exp1_latex
from .metrics import build_condition_summary, compute_exp1_tables, concat_exp1_tables
from .qc import Exp1QcReport, run_exp1_qc


@dataclass(frozen=True)
class Exp1Result:
    """一次实验一批量分析的固定产物集合。"""

    output_dir: Path
    """CSV、图和 LaTeX 产物目录。"""

    tables: dict[str, pd.DataFrame]
    """不带 ``.csv`` 后缀的稳定表名到内存表映射。"""

    session_qc: pd.DataFrame
    """逐 session QC 表。"""

    trial_qc: pd.DataFrame
    """逐 trial/event QC 表。"""

    latex_files: tuple[Path, ...] = ()
    """生成的 LaTeX 文件。"""

    figure_files: tuple[Path, ...] = ()
    """生成的 PDF 图文件。"""


def run_exp1_system_characterization(
    session_dirs: Iterable[EvalSessionV2 | str | Path],
    output_dir: str | Path,
    config: dict[str, Any] | None = None,
) -> Exp1Result:
    """严格分析 schema-v2 实验一 session，并写出十张固定 CSV。

    本入口会先写 ``exp1_session_qc.csv`` 与 ``exp1_trial_qc.csv``。任一 session
    未通过时立即抛错，禁止继续生成可能被误用为正式结果的指标、图和 LaTeX。
    """

    sessions = [_load_session(item) for item in session_dirs]
    if not sessions:
        raise ValueError("实验一分析至少需要一个 schema-v2 session。")
    settings = dict(config or {})
    min_reference_coverage = float(
        settings.get("min_reference_coverage", DEFAULT_MIN_REFERENCE_COVERAGE)
    )
    reports = [
        run_exp1_qc(session, min_reference_coverage=min_reference_coverage)
        for session in sessions
    ]

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    session_qc = _session_qc_table(reports)
    trial_qc = pd.concat([report.trial_qc for report in reports], ignore_index=True)
    session_qc.to_csv(output / "exp1_session_qc.csv", index=False)
    trial_qc.to_csv(output / "exp1_trial_qc.csv", index=False)
    failed = [report for report in reports if not report.passed]
    if failed:
        details = "; ".join(
            f"{report.session_id}: {' | '.join(report.errors)}" for report in failed
        )
        raise ValueError(f"实验一 QC 失败，已停止指标生成：{details}")

    metric_tables = concat_exp1_tables([compute_exp1_tables(session) for session in sessions])
    metric_tables["exp1_condition_summary"] = build_condition_summary(
        metric_tables["exp1_trial_metrics"]
    )
    tables = {
        "exp1_session_qc": session_qc,
        "exp1_trial_qc": trial_qc,
        **metric_tables,
    }
    expected_names = {Path(name).stem for name in OUTPUT_TABLES}
    if set(tables) != expected_names:
        raise RuntimeError(
            f"实验一输出表契约不完整：missing={sorted(expected_names - set(tables))}, "
            f"extra={sorted(set(tables) - expected_names)}"
        )
    for name, table in tables.items():
        table.to_csv(output / f"{name}.csv", index=False)

    render = pd.concat([session.unity_render for session in sessions], ignore_index=True)
    figure_files = tuple(write_exp1_figures(render, tables, output))
    latex_files = tuple(write_exp1_latex(tables, output))
    return Exp1Result(
        output_dir=output,
        tables=tables,
        session_qc=session_qc,
        trial_qc=trial_qc,
        latex_files=latex_files,
        figure_files=figure_files,
    )


def _load_session(session: EvalSessionV2 | str | Path) -> EvalSessionV2:
    """统一内存 session 与目录输入。"""

    return session if isinstance(session, EvalSessionV2) else load_session_v2(session)


def _session_qc_table(reports: list[Exp1QcReport]) -> pd.DataFrame:
    """把结构化 QC 报告转换为稳定 CSV 行。"""

    rows = [
        {
            "session_id": report.session_id,
            "passed": report.passed,
            "errors": " | ".join(report.errors),
            "warnings": " | ".join(report.warnings),
            **report.metrics,
        }
        for report in reports
    ]
    return pd.DataFrame.from_records(rows)


__all__ = ["Exp1Result", "run_exp1_system_characterization"]
