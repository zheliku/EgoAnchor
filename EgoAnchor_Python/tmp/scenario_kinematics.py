"""临时诊断：按场景统计序列时长、目标参考速度与头动速度。

目标速度直接读 Unity 记录的 ``reference_linear_speed_m_s`` / ``reference_angular_speed_deg_s``；
头动速度由 ``head_pos`` / ``head_rot`` 差分得到。只读冻结工作簿。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from egoanchor.eval.experiments.experiment_1_2.analysis import (
    eligible_trials,
    iter_rows,
    workbook_sha256,
)

ROOT = Path("P:/VSCode-Project/EgoAnchor/EgoAnchor_Python")
BATCH = ROOT / "data/experiments/experiment_1_2/batch.json"
WB_ROOT = ROOT / "data/experiments/task_workbooks"

COLUMNS = (
    "session_id", "scenario_id", "trial_id", "event_id", "variant_id",
    "render_mono_ms", "reference_pose_valid",
    "reference_linear_speed_m_s", "reference_angular_speed_deg_s",
    "head_pos_x_m", "head_pos_y_m", "head_pos_z_m",
    "head_rot_x", "head_rot_y", "head_rot_z", "head_rot_w",
)

TRUTHY = {True, 1, "1", "true", "TRUE", "True"}


def resolve_workbooks() -> tuple[Path, ...]:
    batch = json.loads(BATCH.read_text(encoding="utf-8"))
    paths = []
    for task in batch["tasks"]:
        path = WB_ROOT / task["workbook_directory"] / task["workbook_name"]
        if workbook_sha256(path) != task["workbook_sha256"]:
            raise SystemExit(f"workbook SHA 不匹配：{path}")
        paths.append(path)
    return tuple(paths)


def quat_angles_deg(quats: np.ndarray) -> np.ndarray:
    q = quats / np.linalg.norm(quats, axis=1, keepdims=True)
    dots = np.abs(np.sum(q[:-1] * q[1:], axis=1)).clip(-1.0, 1.0)
    return np.degrees(2.0 * np.arccos(dots))


def smooth_median(v: np.ndarray, w: int = 5) -> np.ndarray:
    if v.size < w:
        return v
    return np.array([np.median(v[i : i + w]) for i in range(v.size - w + 1)])


def describe(values: np.ndarray, label: str, unit: str) -> str:
    return (f"  {label:22s} {unit:6s}: median={np.median(values):8.3f}  "
            f"IQR=[{np.quantile(values,0.25):.3f}, {np.quantile(values,0.75):.3f}]  "
            f"range=[{values.min():.3f}, {values.max():.3f}]")


def main() -> None:
    workbooks = resolve_workbooks()
    trials = eligible_trials(workbooks)
    segments: defaultdict[tuple[str, str, str, str], list[tuple]] = defaultdict(list)
    for workbook in workbooks:
        for row in iter_rows(workbook, "unity_render", COLUMNS):
            if str(row.get("variant_id", "")) != "EgoAnchor":
                continue
            key2 = (str(row.get("session_id", "")), str(row.get("trial_id", "")))
            if key2 not in trials:
                continue
            try:
                t = float(row["render_mono_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            head = None
            try:
                hp = [float(row[f"head_pos_{a}"]) for a in ("x_m", "y_m", "z_m")]
                hr = [float(row[f"head_rot_{a}"]) for a in ("x", "y", "z", "w")]
                if all(np.isfinite(hp)) and all(np.isfinite(hr)) and np.linalg.norm(hr) > 1e-6:
                    head = (hp, hr)
            except (KeyError, TypeError, ValueError):
                head = None
            ref_valid = row.get("reference_pose_valid") in TRUTHY
            try:
                lin = float(row.get("reference_linear_speed_m_s") or 0.0)
                ang = float(row.get("reference_angular_speed_deg_s") or 0.0)
            except (TypeError, ValueError):
                lin, ang = 0.0, 0.0
            key = (str(row.get("scenario_id", "")), *key2, str(row.get("event_id", "")))
            segments[key].append((t, lin, ang, ref_valid, head))

    per_scenario: defaultdict[str, defaultdict[str, list]] = defaultdict(lambda: defaultdict(list))
    for (scenario, _s, _t, _e), rows in segments.items():
        rows.sort(key=lambda item: item[0])
        times = np.asarray([r[0] for r in rows], dtype=float)
        times, idx = np.unique(times, return_index=True)
        if times.size < 10:
            continue
        rows = [rows[i] for i in idx]
        bucket = per_scenario[scenario]
        bucket["dur"].append((times[-1] - times[0]) / 1000.0)

        valid = [r for r in rows if r[3]]
        if valid:
            lin = smooth_median(np.asarray([r[1] for r in valid], dtype=float))
            ang = smooth_median(np.asarray([r[2] for r in valid], dtype=float))
            bucket["obj_lin_med"].append(float(np.median(lin)))
            bucket["obj_lin_p95"].append(float(np.quantile(lin, 0.95)))
            bucket["obj_ang_med"].append(float(np.median(ang)))
            bucket["obj_ang_p95"].append(float(np.quantile(ang, 0.95)))

        head_rows = [(r[0], r[4]) for r in rows if r[4] is not None]
        if len(head_rows) >= 10:
            ht = np.asarray([r[0] for r in head_rows], dtype=float)
            hp = np.asarray([r[1][0] for r in head_rows], dtype=float)
            hr = np.asarray([r[1][1] for r in head_rows], dtype=float)
            dt = np.diff(ht) / 1000.0
            ok = dt > 1e-4
            if np.any(ok):
                hlin = smooth_median(np.linalg.norm(np.diff(hp, axis=0), axis=1)[ok] / dt[ok])
                hang = smooth_median(quat_angles_deg(hr)[ok] / dt[ok])
                bucket["head_lin_med"].append(float(np.median(hlin)))
                bucket["head_lin_p95"].append(float(np.quantile(hlin, 0.95)))
                bucket["head_ang_med"].append(float(np.median(hang)))
                bucket["head_ang_p95"].append(float(np.quantile(hang, 0.95)))

    for scenario in sorted(per_scenario):
        b = per_scenario[scenario]
        d = np.asarray(b["dur"], dtype=float)
        print("=" * 78)
        print(f"{scenario}   片段数={d.size}   合计时长={d.sum():.1f} s")
        print("=" * 78)
        print(f"  时长                   s     : median={np.median(d):8.2f}  "
              f"IQR=[{np.quantile(d,0.25):.2f}, {np.quantile(d,0.75):.2f}]  range=[{d.min():.2f}, {d.max():.2f}]")
        for label, key, unit in (
            ("目标线速度 median", "obj_lin_med", "m/s"),
            ("目标线速度 P95", "obj_lin_p95", "m/s"),
            ("目标角速度 median", "obj_ang_med", "deg/s"),
            ("目标角速度 P95", "obj_ang_p95", "deg/s"),
            ("头动线速度 median", "head_lin_med", "m/s"),
            ("头动线速度 P95", "head_lin_p95", "m/s"),
            ("头动角速度 median", "head_ang_med", "deg/s"),
            ("头动角速度 P95", "head_ang_p95", "deg/s"),
        ):
            if b[key]:
                print(describe(np.asarray(b[key], dtype=float), label, unit))
        print()


if __name__ == "__main__":
    main()
