"""临时工具：由 batch.json 冻结的五本工作簿生成实验一逐单元格中位数与自举 95% CI 的补充材料表。

输出 LaTeX 片段到 stdout；只读工作簿，不触碰正式产物。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from egoanchor.eval.experiments.experiment_1_2.analysis import (
    METHODS,
    analyze_workbooks,
    load_settings,
    workbook_sha256,
)

ROOT = Path("P:/VSCode-Project/EgoAnchor/EgoAnchor_Python")
BATCH = ROOT / "data/experiments/experiment_1_2/batch.json"
WB_ROOT = ROOT / "data/experiments/task_workbooks"
SETTINGS = ROOT / "src/egoanchor/eval/config/paper.toml"

LABELS = {
    "Arrival-Hold": "Arrival",
    "Capture-Hold": "Capture",
    "One-Euro Anchor": "One-Euro",
    "EgoAnchor": "EgoAnchor",
}


def workbooks() -> tuple[Path, ...]:
    batch = json.loads(BATCH.read_text(encoding="utf-8"))
    paths = []
    for task in batch["tasks"]:
        path = WB_ROOT / task["workbook_directory"] / task["workbook_name"]
        if workbook_sha256(path) != task["workbook_sha256"]:
            raise SystemExit(f"SHA 不匹配，拒绝出表：{path}")
        paths.append(path)
    return tuple(paths)


def ci(values, decimals, iterations=20000, seed=20260826) -> str:
    a = np.asarray([float(v) for v in values], dtype=float)
    a = a[np.isfinite(a)]
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, a.size, size=(iterations, a.size))
    med = np.median(a[draws], axis=1)
    lo, hi = np.quantile(med, 0.025), np.quantile(med, 0.975)
    f = f"%.{decimals}f"
    return f"{f % np.median(a)} [{f % lo}, {f % hi}]"


def main() -> None:
    results = analyze_workbooks(workbooks(), load_settings(SETTINGS))
    groups = (
        ("Static registration ($n=12$)", (
            ("Head-motion coupling (mm)", results.static_segments, "centered_p95_mm", 2),
            ("Head-motion coupling ($^\\circ$)", results.static_segments, "centered_rotation_p95_deg", 2),
            ("Registration error (mm)", results.static_segments, "absolute_p95_mm", 2),
            ("Registration error ($^\\circ$)", results.static_segments, "absolute_rotation_p95_deg", 2),
            ("Static jitter (mm)", results.static_segments, "frame_increment_p95_mm", 2),
            ("Static jitter ($^\\circ$)", results.static_segments, "frame_rotation_increment_p95_deg", 2),
        )),
        ("Dynamic following, translation ($n=16$)", (
            ("Effective latency (ms)", results.translation_segments, "effective_lag_ms", 1),
            ("LA-RMSE (mm)", results.translation_segments, "aligned_rmse_mm", 2),
            ("CT-RMSE (mm)", results.translation_segments, "current_time_rmse_mm", 2),
            ("Residual jitter (mm)", results.translation_segments, "aligned_residual_increment_p95_mm", 2),
        )),
        ("Dynamic following, rotation ($n=12$)", (
            ("Effective latency (ms)", results.rotation_segments, "effective_lag_ms", 1),
            ("LA-RMSE ($^\\circ$)", results.rotation_segments, "aligned_rmse_deg", 2),
            ("CT-RMSE ($^\\circ$)", results.rotation_segments, "current_time_rmse_deg", 2),
            ("Residual jitter ($^\\circ$)", results.rotation_segments, "aligned_residual_increment_p95_deg", 2),
        )),
        ("State-transition response ($n=12$)", (
            ("Occlusion recovery (mm)", results.occlusion_episodes, "translation_p95_mm", 2),
            ("Occlusion recovery ($^\\circ$)", results.occlusion_episodes, "rotation_p95_deg", 2),
            ("Motion-response latency (ms)", results.transition_segments, "response_ms", 1),
        )),
    )

    out = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Experiment~1 medians with bootstrap 95\% confidence intervals (20{,}000 resamples of the",
        r"repeated sequences). Each metric is aggregated within a sequence before the median across repetitions",
        r"is taken; values reproduce Tables~1--3 of the main paper. A single operator recorded all sequences.}",
        r"\label{tab:supp-exp1-ci}",
        r"\setlength{\tabcolsep}{4pt}",
        r"\begin{tabular}{@{}lcccc@{}}",
        r"\toprule",
        r"Metric & " + " & ".join(LABELS[m] for m in METHODS) + r" \\",
    ]
    for title, rows in groups:
        out.append(r"\midrule")
        out.append(rf"\multicolumn{{5}}{{@{{}}l}}{{\emph{{{title}}}}} \\")
        for label, mapping, key, decimals in rows:
            cells = [ci([r[key] for r in mapping[m]], decimals) for m in METHODS]
            out.append(f"{label} & " + " & ".join(cells) + r" \\")
    out.extend([r"\bottomrule", r"\end{tabular}", r"\end{table*}"])
    print("\n".join(out))


if __name__ == "__main__":
    main()
