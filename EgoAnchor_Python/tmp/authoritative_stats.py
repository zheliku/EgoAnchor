"""临时诊断：以 batch.json 冻结的五本工作簿为准，核对论文表数值并计算 n、时长、速度与中位数 CI。

先按 SHA256 校验工作簿身份，再复算指标；只读，不写任何正式产物。
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
    workbook_sha256,
)

ROOT = Path("P:/VSCode-Project/EgoAnchor/EgoAnchor_Python")
BATCH = ROOT / "data/experiments/experiment_1_2/batch.json"
WB_ROOT = ROOT / "data/experiments/task_workbooks"
SETTINGS_PATH = ROOT / "src/egoanchor/eval/config/paper.toml"

RENDER_COLUMNS = (
    "session_id", "scenario_id", "trial_id", "event_id", "variant_id",
    "render_mono_ms", "has_display_pose", "reference_pose_valid",
    "reference_pos_x_m", "reference_pos_y_m", "reference_pos_z_m",
    "reference_rot_x", "reference_rot_y", "reference_rot_z", "reference_rot_w",
)


def resolve_workbooks() -> tuple[Path, ...]:
    """按 batch.json 的目录与 SHA256 定位并校验五本冻结工作簿。"""

    batch = json.loads(BATCH.read_text(encoding="utf-8"))
    paths: list[Path] = []
    print("=" * 78)
    print("0. 工作簿身份校验（对照 batch.json）")
    print("=" * 78)
    for task in batch["tasks"]:
        path = WB_ROOT / task["workbook_directory"] / task["workbook_name"]
        actual = workbook_sha256(path)
        expected = task["workbook_sha256"]
        ok = "OK " if actual == expected else "MISMATCH"
        print(f"  [{ok}] task {task['task_number']}  {task['session']['scenario_id']:24s} "
              f"{task['session']['session_id']}")
        if actual != expected:
            print(f"          expected {expected}\n          actual   {actual}")
        paths.append(path)
    return tuple(paths)


def boot_ci(values, iterations=20000, seed=20260826):
    a = np.asarray([float(v) for v in values], dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return float("nan"), float("nan"), float("nan"), 0
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, a.size, size=(iterations, a.size))
    med = np.median(a[draws], axis=1)
    return (
        float(np.median(a)),
        float(np.quantile(med, 0.025)),
        float(np.quantile(med, 0.975)),
        int(a.size),
    )


def quat_angles_deg(quats):
    q = np.asarray(quats, dtype=float)
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    dots = np.abs(np.sum(q[:-1] * q[1:], axis=1)).clip(-1.0, 1.0)
    return np.degrees(2.0 * np.arccos(dots))


def smooth_median(v, w=5):
    if v.size < w:
        return v
    return np.array([np.median(v[i : i + w]) for i in range(v.size - w + 1)])


def main() -> None:
    workbooks = resolve_workbooks()
    settings = load_settings(SETTINGS_PATH)
    trials = eligible_trials(workbooks)
    results = analyze_workbooks(workbooks, settings)

    print()
    print("=" * 78)
    print("1. 表 1--3 逐单元格：中位数、自举 95% CI、n（核对已发表数值）")
    print("=" * 78)
    specs = (
        ("表1 静态配准", results.static_segments, (
            ("头动耦合-平移 mm", "centered_p95_mm", 43.67),
            ("头动耦合-旋转 deg", "centered_rotation_p95_deg", 6.49),
            ("配准误差-平移 mm", "absolute_p95_mm", 44.31),
            ("配准误差-旋转 deg", "absolute_rotation_p95_deg", 9.65),
            ("静止抖动-平移 mm", "frame_increment_p95_mm", 11.70),
            ("静止抖动-旋转 deg", "frame_rotation_increment_p95_deg", 2.98),
        )),
        ("表2 动态-平移", results.translation_segments, (
            ("有效时延 ms", "effective_lag_ms", 202.5),
            ("LA-RMSE mm", "aligned_rmse_mm", 18.57),
            ("CT-RMSE mm", "current_time_rmse_mm", 84.74),
            ("残余抖动 mm", "aligned_residual_increment_p95_mm", 41.08),
        )),
        ("表2 动态-旋转", results.rotation_segments, (
            ("有效时延 ms", "effective_lag_ms", 255.0),
            ("LA-RMSE deg", "aligned_rmse_deg", 6.09),
            ("CT-RMSE deg", "current_time_rmse_deg", 25.44),
            ("残余抖动 deg", "aligned_residual_increment_p95_deg", 10.40),
        )),
        ("表3 遮挡恢复", results.occlusion_episodes, (
            ("遮挡误差-平移 mm", "translation_p95_mm", 18.23),
            ("遮挡误差-旋转 deg", "rotation_p95_deg", 18.39),
        )),
        ("表3 起动响应", results.transition_segments, (
            ("运动响应时延 ms", "response_ms", 157.0),
        )),
    )
    for title, mapping, metrics in specs:
        print(f"\n--- {title} ---")
        for label, key, arrival_published in metrics:
            print(f"  {label}")
            for method in METHODS:
                rows = mapping.get(method, ())
                med, lo, hi, n = boot_ci([r[key] for r in rows])
                flag = ""
                if method == "Arrival-Hold":
                    flag = "  <== 已发表 Arrival = %.2f %s" % (
                        arrival_published,
                        "[一致]" if abs(med - arrival_published) < 0.051 else "[不一致]",
                    )
                print(f"      {method:18s} {med:9.2f} [{lo:8.2f}, {hi:8.2f}]  n={n}{flag}")

    print()
    print("=" * 78)
    print("2. 每场景的序列时长与参考运动速度（平台参考轨迹，EgoAnchor 通道）")
    print("=" * 78)
    grouped = defaultdict(list)
    truthy = {True, 1, "1", "true", "TRUE", "True"}
    for workbook in workbooks:
        for row in iter_rows(workbook, "unity_render", RENDER_COLUMNS):
            if str(row.get("variant_id", "")) != "EgoAnchor":
                continue
            key = (str(row.get("session_id", "")), str(row.get("trial_id", "")))
            if key not in trials or row.get("reference_pose_valid") not in truthy:
                continue
            try:
                t = float(row["render_mono_ms"])
                pos = [float(row[f"reference_pos_{a}_m"]) for a in ("x", "y", "z")]
                rot = [float(row[f"reference_rot_{a}"]) for a in ("x", "y", "z", "w")]
            except (KeyError, TypeError, ValueError):
                continue
            if not all(np.isfinite(pos)) or not all(np.isfinite(rot)):
                continue
            grouped[(str(row.get("scenario_id", "")), *key, str(row.get("event_id", "")))].append((t, pos, rot))

    per_scenario = defaultdict(lambda: defaultdict(list))
    for (scenario, _s, _t, _e), rows in grouped.items():
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
        b = per_scenario[scenario]
        b["dur"].append((times[-1] - times[0]) / 1000.0)
        lin = smooth_median(np.linalg.norm(np.diff(pos, axis=0), axis=1)[ok] / dt[ok])
        ang = smooth_median(quat_angles_deg(rot)[ok] / dt[ok])
        b["lin_med"].append(float(np.median(lin)))
        b["lin_p95"].append(float(np.quantile(lin, 0.95)))
        b["lin_max"].append(float(np.max(lin)))
        b["ang_med"].append(float(np.median(ang)))
        b["ang_p95"].append(float(np.quantile(ang, 0.95)))
        b["ang_max"].append(float(np.max(ang)))

    for scenario in sorted(per_scenario):
        b = per_scenario[scenario]
        d = np.asarray(b["dur"])
        print(f"\n--- {scenario}  (片段数={d.size}) ---")
        print(f"  时长 s : median={np.median(d):.2f}  IQR=[{np.quantile(d,0.25):.2f}, {np.quantile(d,0.75):.2f}]  "
              f"range=[{d.min():.2f}, {d.max():.2f}]  合计={d.sum():.1f}")
        for label, key, unit in (
            ("线速度 median", "lin_med", "m/s"), ("线速度 P95", "lin_p95", "m/s"), ("线速度 max", "lin_max", "m/s"),
            ("角速度 median", "ang_med", "deg/s"), ("角速度 P95", "ang_p95", "deg/s"), ("角速度 max", "ang_max", "deg/s"),
        ):
            v = np.asarray(b[key])
            print(f"  {label:16s} {unit:6s}: median={np.median(v):8.3f}  "
                  f"IQR=[{np.quantile(v,0.25):.3f}, {np.quantile(v,0.75):.3f}]  range=[{v.min():.3f}, {v.max():.3f}]")


if __name__ == "__main__":
    main()
