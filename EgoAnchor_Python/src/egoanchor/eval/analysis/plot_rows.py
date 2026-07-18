"""Stage 2 实验一 event 指标到三张固定 plot CSV 的投影。"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterable

from .exp1 import EXP1_VARIANTS, MetricRow
from .vcd import VcdCurvePoint


@dataclass(frozen=True, slots=True)
class Exp1PlotRows:
    """保存实验一三张图的 display-ready CSV 行。"""

    static_timeline: tuple[dict[str, object], ...]
    """静止头动 event-P95 四系统行。"""

    motion_events: tuple[dict[str, object], ...]
    """起停 6DoF 运动窗平移 P95 配对行。"""

    occlusion_events: tuple[dict[str, object], ...]
    """遮挡恢复窗平移 P95 配对行。"""


def _plot_row(row: MetricRow, plot_id: str) -> dict[str, object]:
    """将 event 行转换为冻结 plot 主键。

    参数：
        row: Stage 2 已计算的 event 指标行。
        plot_id: 三张实验一图之一的稳定名称。
    """

    values = asdict(row)
    values["event_id"] = f"{row.session_id}:{row.trial_id}:{row.event_id}"
    values["plot_id"] = plot_id
    values["panel_id"] = row.scenario_id
    return values


def _select_rows(
    rows: tuple[MetricRow, ...],
    scenario_id: str,
    metric_key: str,
    plot_id: str,
) -> tuple[dict[str, object], ...]:
    """选择单图指标，并验证每个 event 的四系统精确矩阵。

    参数：
        rows: 实验一全部 event 指标行。
        scenario_id: 当前图冻结的场景标识。
        metric_key: 当前图冻结的指标键。
        plot_id: 当前图的稳定名称。
    """

    selected = tuple(
        row
        for row in rows
        if row.scenario_id == scenario_id and row.metric_key == metric_key
    )
    if not selected:
        raise ValueError(f"实验一正式图缺少 event-level 指标行：{plot_id}")
    groups: dict[tuple[str, str, str], Counter[str]] = {}
    for row in selected:
        key = (row.session_id, row.trial_id, row.event_id)
        groups.setdefault(key, Counter())[row.variant_id] += 1
    expected = Counter(EXP1_VARIANTS)
    invalid = [key for key, variants in groups.items() if variants != expected]
    if invalid:
        raise ValueError(f"实验一正式图四系统矩阵不完整：{plot_id}，event={invalid[0]}")
    return tuple(_plot_row(row, plot_id) for row in selected)


def build_exp1_plot_rows(rows: Iterable[MetricRow]) -> Exp1PlotRows:
    """严格按场景与冻结指标选择实验一三张图的 CSV 行。

    参数：
        rows: 实验一全部 event-level 指标，不含 frame-level 推断。
    """

    materialized = tuple(rows)
    static = _select_rows(
        materialized,
        "static_head_motion",
        "translation_event_pninetyfive_mm",
        "exp1_static_timeline",
    )
    motion = _select_rows(
        materialized,
        "start_stop_6dof",
        "motion_translation_pninetyfive_mm",
        "exp1_motion_events",
    )
    occlusion = _select_rows(
        materialized,
        "occlusion_recovery",
        "occlusion_translation_pninetyfive_mm",
        "exp1_occlusion_events",
    )
    return Exp1PlotRows(static, motion, occlusion)


def build_vcd_plot_rows(rows: Iterable[VcdCurvePoint]) -> tuple[dict[str, object], ...]:
    """只投影冻结 P95 tail-risk 曲线，并验证 VCD/random 成对。

    参数：
        rows: Task 8 同时生成的 mean 与 P95 risk-coverage 点。
    """

    selected = tuple(
        row
        for row in rows
        if row.scenario_id == "occlusion_recovery"
        and row.risk_kind == "tail_pninetyfive"
    )
    if not selected:
        raise ValueError("VCD 正式图缺少 P95 tail-risk 曲线")
    groups: dict[tuple[str, int, float], Counter[str]] = {}
    for row in selected:
        key = (row.scenario_id, row.point_index, row.coverage)
        groups.setdefault(key, Counter())[row.reference_kind] += 1
    expected = Counter(("vcd", "random"))
    invalid = [key for key, references in groups.items() if references != expected]
    if invalid:
        raise ValueError(f"VCD 正式图缺少成对参考曲线：point={invalid[0]}")
    return tuple(
        {
            **asdict(row),
            "plot_id": "exp2_vcd_curve",
            "panel_id": row.reference_kind,
        }
        for row in selected
    )


__all__ = ["Exp1PlotRows", "build_exp1_plot_rows", "build_vcd_plot_rows"]
