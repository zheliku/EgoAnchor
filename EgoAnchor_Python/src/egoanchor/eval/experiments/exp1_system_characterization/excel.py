"""实验一的多 sheet Excel 导出。

把已通过 QC 的分析表和原始 render 长表整理为一个 ``exp1_analysis.xlsx``：
- ``scenario_matrix``：场景×配置的平移中位/P95/抖动透视，一眼比较；
- ``scenario_headline``：每个场景×配置一行的完整展示指标；
- ``trial_metrics``：逐 trial/event×配置的中性指标（论文统计单元）；
- ``static_quality`` / ``occlusion_recovery`` / ``latency``：场景专属指标；
- ``raw_frames``：逐帧×配置的显示误差与状态，供作者自绘时间图。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from egoanchor.eval.excel import write_workbook
from egoanchor.eval.metrics import pose_error

from .contract import VARIANTS
from .metrics import SCENARIO_ORDER, build_scenario_headline


EXCEL_FILENAME = "exp1_analysis.xlsx"
"""实验一 Excel 产物的固定文件名。"""

_RAW_FRAME_MAX = 400_000
"""原始帧 sheet 的最大行数上限，避免超大 session 组合撑爆单表。"""


def write_exp1_excel(
    render: pd.DataFrame,
    tables: Mapping[str, pd.DataFrame],
    output_dir: str | Path,
) -> Path:
    """写出实验一多 sheet 分析 Excel，返回文件路径。"""

    output = Path(output_dir)
    headline = build_scenario_headline(dict(tables))
    sheets = {
        "scenario_matrix": _scenario_matrix(headline),
        "scenario_headline": _rounded(headline),
        "trial_metrics": _rounded(tables.get("exp1_trial_metrics", pd.DataFrame())),
        "static_quality": _rounded(tables.get("exp1_static_quality", pd.DataFrame())),
        "transition_response": _rounded(tables.get("exp1_transition_response", pd.DataFrame())),
        "occlusion_recovery": _rounded(tables.get("exp1_occlusion_recovery", pd.DataFrame())),
        "latency": _rounded(tables.get("exp1_latency_summary", pd.DataFrame())),
        "raw_frames": _raw_frames(render),
    }
    return write_workbook(sheets, output / EXCEL_FILENAME)


def _scenario_matrix(headline: pd.DataFrame) -> pd.DataFrame:
    """构造场景(行)×配置(列)的平移中位/P95/抖动透视，便于横向对比。"""

    metrics = (
        ("translation_median_mm", "Trans median (mm)"),
        ("translation_p95_mm", "Trans P95 (mm)"),
        ("position_hp_rms_mm", "Jitter HP-RMS (mm)"),
    )
    rows: list[dict[str, object]] = []
    for scenario in SCENARIO_ORDER:
        scenario_rows = headline.loc[headline["scenario_id"].astype(str).eq(scenario)]
        for column, metric_label in metrics:
            record: dict[str, object] = {"scenario": scenario, "metric": metric_label}
            for variant in VARIANTS:
                value = pd.to_numeric(
                    scenario_rows.loc[
                        scenario_rows["variant_label"].astype(str).eq(variant), column
                    ],
                    errors="coerce",
                ).dropna()
                record[variant] = round(float(value.iloc[0]), 4) if not value.empty else None
            rows.append(record)
    return pd.DataFrame.from_records(rows)


def _raw_frames(render: pd.DataFrame) -> pd.DataFrame:
    """从 render 长表逐帧计算显示误差，输出可直接绘图的窄表。

    只保留四个实验一配置，并附带时间、场景、事件、观测年龄和锚点状态，使作者
    能够在 Excel 中直接画出“误差-时间”曲线，弥补条形图无法呈现的时间行为。
    """

    columns = [
        "session_id",
        "scenario_id",
        "trial_id",
        "event_id",
        "variant_label",
        "render_mono_ms",
        "render_tick_id",
        "translation_error_mm",
        "rotation_error_deg",
        "has_output_pose",
        "has_display_pose",
        "observation_age_ms",
        "reference_linear_speed_m_s",
        "reference_angular_speed_deg_s",
        "anchor_state",
    ]
    if render.empty:
        return pd.DataFrame(columns=columns)
    scoped = render.loc[render["variant_label"].astype(str).isin(VARIANTS)].copy()
    scoped = scoped.sort_values(
        ["scenario_id", "variant_label", "render_mono_ms"], kind="stable"
    )
    rows: list[dict[str, object]] = []
    for _, row in scoped.iterrows():
        translation_mm = np.nan
        rotation_deg = np.nan
        if (
            bool(row.get("reference_pose_valid"))
            and bool(row.get("has_display_pose"))
            and row.get("reference_pos") is not None
            and row.get("display_pos") is not None
        ):
            translation_m, rotation = pose_error(
                row["reference_pos"], row["reference_rot"], row["display_pos"], row["display_rot"]
            )
            translation_mm = translation_m * 1000.0
            rotation_deg = rotation
        rows.append(
            {
                "session_id": row.get("session_id"),
                "scenario_id": row.get("scenario_id"),
                "trial_id": row.get("trial_id"),
                "event_id": row.get("event_id"),
                "variant_label": row.get("variant_label"),
                "render_mono_ms": _finite(row.get("render_mono_ms")),
                "render_tick_id": row.get("render_tick_id"),
                "translation_error_mm": round(translation_mm, 4) if np.isfinite(translation_mm) else None,
                "rotation_error_deg": round(rotation_deg, 4) if np.isfinite(rotation_deg) else None,
                "has_output_pose": bool(row.get("has_output_pose")),
                "has_display_pose": bool(row.get("has_display_pose")),
                "observation_age_ms": _finite(row.get("observation_age_ms")),
                "reference_linear_speed_m_s": _finite(row.get("reference_linear_speed_m_s")),
                "reference_angular_speed_deg_s": _finite(row.get("reference_angular_speed_deg_s")),
                "anchor_state": row.get("anchor_state"),
            }
        )
        if len(rows) >= _RAW_FRAME_MAX:
            break
    return pd.DataFrame.from_records(rows, columns=columns)


def _rounded(frame: pd.DataFrame, digits: int = 4) -> pd.DataFrame:
    """对数值列四舍五入，减小 Excel 体积并提升可读性。"""

    if frame.empty:
        return frame.copy()
    result = frame.copy()
    for column in result.columns:
        if pd.api.types.is_float_dtype(result[column]):
            result[column] = result[column].round(digits)
    return result


def _finite(value: object) -> float | None:
    """把数值转换为有限 float，缺失返回 None。"""

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return round(number, 4) if np.isfinite(number) else None


__all__ = ["EXCEL_FILENAME", "write_exp1_excel"]
