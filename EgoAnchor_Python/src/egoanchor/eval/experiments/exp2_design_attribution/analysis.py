"""实验二严格 QC、配对归因和固定产物写出入口。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from egoanchor.eval.schema_v2 import EvalSessionV2, load_session_v2, select_completed_trials

from ..batch import BatchQcReport, run_batch_qc

from .contract import EXPERIMENT_ID, SCENARIO_ABLATION
from .figures import write_exp2_figures
from .latex import write_exp2_latex, write_exp2_tables
from .metrics import aggregate_component_deltas, compute_exp2_paired_deltas
from .qc import Exp2QcReport, run_exp2_qc
from .risk_coverage import VcdRiskCoverageResult, compute_vcd_risk_coverage


@dataclass(frozen=True)
class Exp2Result:
    """一次实验二批量分析的固定产物集合。"""

    output_dir: Path
    """CSV、图和 LaTeX 产物目录。"""

    qc: Exp2QcReport
    """合并后的批量 QC 结果。"""

    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    """稳定表名到内存表的映射。"""

    metrics: dict[str, Any] = field(default_factory=dict)
    """需要进入论文宏的批量标量。"""


def run_exp2_design_attribution(
    session_dirs: Iterable[EvalSessionV2 | str | Path],
    output_dir: str | Path,
    config: Mapping[str, Any] | None = None,
) -> Exp2Result:
    """严格分析实验二 session，并在 QC 失败时只保留审计产物。

    ``config`` 当前只作为冻结接口保留，Run 1 不允许从 formal 数据调参。
    """

    del config
    sessions = [_as_session(item) for item in session_dirs]
    if not sessions:
        raise ValueError("实验二分析至少需要一个 schema-v2 session。")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports = [run_exp2_qc(session) for session in sessions]
    coverage_qc = run_batch_qc(
        sessions,
        experiment_id=EXPERIMENT_ID,
        required_scenarios=SCENARIO_ABLATION,
    )
    session_qc = _session_qc_table(reports, coverage_qc)
    trial_qc = pd.concat([report.trial_qc for report in reports], ignore_index=True)
    session_qc.to_csv(output / "exp2_session_qc.csv", index=False)
    trial_qc.to_csv(output / "exp2_trial_qc.csv", index=False)
    batch_qc = _batch_qc(reports, trial_qc, coverage_qc)
    _write_qc_json(batch_qc, output / "exp2_qc.json")

    if not batch_qc.passed:
        details = " | ".join(batch_qc.errors)
        raise ValueError(f"实验二 QC 失败，已停止指标生成：{details}")

    contributing_ids = set(coverage_qc.contributing_session_ids)
    accepted_sessions = [
        select_completed_trials(session)
        for session in sessions
        if session.session_id in contributing_ids
    ]
    deltas = pd.concat(
        [compute_exp2_paired_deltas(session) for session in accepted_sessions],
        ignore_index=True,
    )
    summary = aggregate_component_deltas(deltas)
    risk = _concat_risk_results(
        [
            compute_vcd_risk_coverage(
                session.python_candidates,
                session.unity_admission,
                session.unity_reference,
            )
            for session in accepted_sessions
        ]
    )
    tables = {
        "exp2_session_qc": session_qc,
        "exp2_trial_qc": trial_qc,
        "exp2_component_deltas": deltas,
        "exp2_component_delta_summary": summary,
        "exp2_vcd_risk_coverage": risk.curve,
        "exp2_vcd_aurc": risk.aurc,
        "exp2_vcd_aurc_summary": risk.summary,
    }
    for name, table in tables.items():
        table.to_csv(output / f"{name}.csv", index=False)

    aurc_median = _aurc_median(risk.aurc)
    write_exp2_figures(summary, risk.curve, output)
    write_exp2_latex(summary, aurc_median, output / "exp2_numbers.tex")
    write_exp2_tables(summary, output / "exp2_tables.tex")
    return Exp2Result(
        output_dir=output,
        qc=batch_qc,
        tables=tables,
        metrics={"vcd_aurc_mm_median": aurc_median},
    )


def _as_session(item: EvalSessionV2 | str | Path) -> EvalSessionV2:
    """统一内存 session 与目录输入。"""

    return item if isinstance(item, EvalSessionV2) else load_session_v2(item)


def _session_qc_table(
    reports: list[Exp2QcReport],
    coverage: BatchQcReport,
) -> pd.DataFrame:
    """把逐 session 与批次覆盖 QC 转成固定审计表。"""

    rows = [
        {
            "session_id": report.session_id,
            "passed": report.passed,
            "errors": " | ".join(report.errors),
            "warnings": " | ".join(report.warnings),
            "contributes": report.contributes,
            **report.metrics,
        }
        for report in reports
    ]
    rows.append(
        {
            "session_id": "batch",
            "passed": coverage.passed,
            "errors": " | ".join(coverage.errors),
            "warnings": "",
            "contributes": True,
            **coverage.metrics,
        }
    )
    return pd.DataFrame.from_records(rows)


def _batch_qc(
    reports: list[Exp2QcReport],
    trial_qc: pd.DataFrame,
    coverage: BatchQcReport,
) -> Exp2QcReport:
    """合并逐 session QC，同时保留每个错误的 session 上下文。"""

    errors = tuple(
        f"{report.session_id}: {message}"
        for report in reports
        for message in report.errors
    ) + tuple(f"batch: {message}" for message in coverage.errors)
    warnings = tuple(
        f"{report.session_id}: {message}"
        for report in reports
        for message in report.warnings
    )
    return Exp2QcReport(
        session_id="batch",
        passed=not errors,
        errors=errors,
        warnings=warnings,
        metrics=dict(coverage.metrics),
        trial_qc=trial_qc,
    )


def _write_qc_json(report: Exp2QcReport, path: Path) -> None:
    """写人可读且可由批处理解析的 QC 审计 JSON。"""

    payload = {
        "passed": report.passed,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
        "metrics": report.metrics,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _concat_risk_results(results: list[VcdRiskCoverageResult]) -> VcdRiskCoverageResult:
    """拼接各 session 的 risk-coverage 三层表。"""

    return VcdRiskCoverageResult(
        curve=pd.concat([result.curve for result in results], ignore_index=True),
        aurc=pd.concat([result.aurc for result in results], ignore_index=True),
        summary=pd.concat([result.summary for result in results], ignore_index=True),
    )


def _aurc_median(aurc: pd.DataFrame) -> float:
    """以 trial/event AURC 为观察单位计算批量中位数。"""

    values = pd.to_numeric(aurc.get("aurc_mm", pd.Series(dtype=float)), errors="coerce")
    finite = values[np.isfinite(values)]
    return float(finite.median()) if not finite.empty else float("nan")


__all__ = ["Exp2Result", "run_exp2_design_attribution"]
