"""临时诊断：统计实验一各评价方面的重复次数、序列时长、运动速度范围与中位数置信区间。

只读 Stage 1 工作簿与活动分析产物，不写任何正式产物。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from egoanchor.eval.experiments.experiment_1_2.analysis import (
    METHODS,
    analyze_workbooks,
    eligible_trials,
    iter_rows,
    load_settings,
)

ROOT = Path("P:/VSCode-Project/EgoAnchor/EgoAnchor_Python")
WORKBOOKS = tuple(sorted((ROOT / "data/experiments/experiment_1_2/workbooks").glob("task_*_complete.xlsx")))
SETTINGS_PATH = ROOT / "src/egoanchor/eval/config/paper.toml"

RENDER_COLUMNS = (
    "session_id",
    "scenario_id",
    "trial_id",
    "event_id",
    "variant_id",
    "render_mono_ms",
    "has_display_pose",
    "reference_pose_valid",
    "reference_pos_x_m",
    "reference_pos_y_m",
    "reference_pos_z_m",
    "reference_rot_x",
    "reference_rot_y",
    "reference_rot_z",
    "reference_rot_w",
)


def bootstrap_median_ci(values, iterations=10000, seed=20260826):
    """中位数的自举 95% 置信区间。"""

    array = np.asarray([float(v) for v in values], dtype=float)
    array = array[np.isfinite(array)]
    if array.size == 0:
        return (float("nan"),) * 3
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, array.size, size=(iterations, array.size))
    medians = np.median(array[draws], axis=1)
    return (
        float(np.median(array)),
        float(np.quantile(medians, 0.025)),
        float(np.quantile(medians, 0.975)),
    )


def quat_angles_deg(quats):
    """相邻四元数之间的最短测地角，单位度。"""

    q = np.asarray(quats, dtype=float)
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    dots = np.abs(np.sum(q[:-1] * q[1:], axis=1)).clip(-1.0, 1.0)
    return np.degrees(2.0 * np.arccos(dots))


def main() -> None:
    settings = load_settings(SETTINGS_PATH)
    trials = eligible_trials(WORKBOOKS)
    results = analyze_workbooks(WORKBOOKS, settings)

    print("=" * 78)
    print("A. 每个评价方面的片段数 n（按方法）")
    print("=" * 78)
    families = {
        "static (静止+主动头动)": results.static_segments,
        "translation (持续平移)": results.translation_segments,
        "rotation (持续旋转)": results.rotation_segments,
        "occlusion (遮挡恢复)": results.occlusion_episodes,
        "transition (起停-起动)": results.transition_segments,
    }
    for name, mapping in families.items():
        counts = {m: len(mapping.get(m, ())) for m in METHODS}
        sessions = {
            m: len({r["session_id"] for r in mapping.get(m, ())}) for m in METHODS
        }
        print(f"{name:28s} n={counts}  sessions={sessions}")

    print()
    print("=" * 78)
    print("B. 序列时长与参考运动速度（由 unity_render 的平台参考轨迹计算）")
    print("=" * 78)
    grouped = defaultdict(list)
    for workbook in WORKBOOKS:
        for row in iter_rows(workbook, "unity_render", RENDER_COLUMNS):
            if str(row.get("variant_id", "")) != "EgoAnchor":
                continue
            key = (str(row.get("session_id", "")), str(row.get("trial_id", "")))
            if key not in trials:
                continue
            if not row.get("reference_pose_valid") in (True, 1, "1", "true", "TRUE", "True"):
                continue
            try:
                t = float(row["render_mono_ms"])
                pos = [float(row[f"reference_pos_{a}_m"]) for a in ("x", "y", "z")]
                rot = [float(row[f"reference_rot_{a}"]) for a in ("x", "y", "z", "w")]
            except (KeyError, TypeError, ValueError):
                continue
            if not all(np.isfinite(pos)) or not all(np.isfinite(rot)):
                continue
            scenario = str(row.get("scenario_id", ""))
            event = str(row.get("event_id", ""))
            grouped[(scenario, *key, event)].append((t, pos, rot))

    per_scenario = defaultdict(lambda: {"dur": [], "lin": [], "ang": [], "lin_p95": [], "ang_p95": []})
    for (scenario, _session, _trial, _event), rows in grouped.items():
        rows.sort(key=lambda item: item[0])
        times = np.asarray([r[0] for r in rows], dtype=float)
        times, idx = np.unique(times, return_index=True)
        if times.size < 10:
            continue
        pos = np.asarray([rows[i][1] for i in idx], dtype=float)
        rot = np.asarray([rows[i][2] for i in idx], dtype=float)
        dt = np.diff(times) / 1000.0
        ok = dt > 1e-4
        if not np.any(ok):
            continue
        duration_s = (times[-1] - times[0]) / 1000.0
        lin = np.linalg.norm(np.diff(pos, axis=0), axis=1)[ok] / dt[ok]
        ang = quat_angles_deg(rot)[ok] / dt[ok]
        # 5 帧滑窗中值抑制单帧参考噪声
        def smooth(v, w=5):
            if v.size < w:
                return v
            return np.array([np.median(v[i : i + w]) for i in range(v.size - w + 1)])

        lin_s, ang_s = smooth(lin), smooth(ang)
        bucket = per_scenario[scenario]
        bucket["dur"].append(duration_s)
        bucket["lin"].append(float(np.median(lin_s)))
        bucket["ang"].append(float(np.median(ang_s)))
        bucket["lin_p95"].append(float(np.quantile(lin_s, 0.95)))
        bucket["ang_p95"].append(float(np.quantile(ang_s, 0.95)))

    for scenario in sorted(per_scenario):
        b = per_scenario[scenario]
        d = np.asarray(b["dur"])
        print(f"\n--- {scenario}  (片段数={d.size}) ---")
        print(f"  时长 s        : median={np.median(d):.2f}  min={d.min():.2f}  max={d.max():.2f}  "
              f"Q1={np.quantile(d,0.25):.2f} Q3={np.quantile(d,0.75):.2f}  合计={d.sum():.1f}")
        for label, key, unit in (
            ("线速度中位", "lin", "m/s"),
            ("线速度P95 ", "lin_p95", "m/s"),
            ("角速度中位", "ang", "deg/s"),
            ("角速度P95 ", "ang_p95", "deg/s"),
        ):
            v = np.asarray(b[key])
            print(f"  {label} {unit:6s}: median={np.median(v):.3f}  Q1={np.quantile(v,0.25):.3f} "
                  f"Q3={np.quantile(v,0.75):.3f}  min={v.min():.3f} max={v.max():.3f}")

    print()
    print("=" * 78)
    print("C. 表 1--3 各单元格的中位数与自举 95% CI")
    print("=" * 78)
    table_specs = (
        ("表1 静态配准", results.static_segments, (
            ("头动耦合 mm", "centered_p95_mm"),
            ("头动耦合 deg", "centered_rotation_p95_deg"),
            ("配准误差 mm", "absolute_p95_mm"),
            ("配准误差 deg", "absolute_rotation_p95_deg"),
            ("静止抖动 mm", "frame_increment_p95_mm"),
            ("静止抖动 deg", "frame_rotation_increment_p95_deg"),
        )),
        ("表2 动态-平移", results.translation_segments, (
            ("有效时延 ms", "effective_lag_ms"),
            ("LA-RMSE mm", "aligned_rmse_mm"),
            ("CT-RMSE mm", "current_time_rmse_mm"),
            ("残余抖动 mm", "aligned_residual_increment_p95_mm"),
        )),
        ("表2 动态-旋转", results.rotation_segments, (
            ("有效时延 ms", "effective_lag_ms"),
            ("LA-RMSE deg", "aligned_rmse_deg"),
            ("CT-RMSE deg", "current_time_rmse_deg"),
            ("残余抖动 deg", "aligned_residual_increment_p95_deg"),
        )),
        ("表3 遮挡", results.occlusion_episodes, (
            ("遮挡误差 mm", "translation_p95_mm"),
            ("遮挡误差 deg", "rotation_p95_deg"),
        )),
        ("表3 起动", results.transition_segments, (
            ("运动响应 ms", "response_ms"),
        )),
    )
    for title, mapping, metrics in table_specs:
        print(f"\n--- {title} ---")
        for label, key in metrics:
            parts = []
            for method in METHODS:
                rows = mapping.get(method, ())
                med, lo, hi = bootstrap_median_ci([r[key] for r in rows])
                parts.append(f"{method}={med:.2f} [{lo:.2f}, {hi:.2f}] (n={len(rows)})")
            print(f"  {label:16s}: " + " | ".join(parts))

    perf_path = ROOT / "data/experiments/experiment_1_2/analysis/metrics/runtime_performance.json"
    print()
    print("=" * 78)
    print("D. runtime_performance.json")
    print("=" * 78)
    print(json.dumps(json.loads(perf_path.read_text(encoding="utf-8")), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
