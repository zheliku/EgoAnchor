"""计算 AQ 缩减规则（停用 AQ_EQ3 与 AQ_IQ1）前后的子量表效应与信度。"""
from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, r"p:\VSCode-Project\EgoAnchor\2026-EgoAnchor\material")

import sim_opus5_v3_stats as SS
from simulate_exp3_opus5_v3 import (
    CANON_OBJECTS,
    SEED,
    reliability_matrix,
    run_cohort,
    subscale_block_value,
)


def sub_mean(runs, method: str, items: tuple[str, ...]) -> np.ndarray:
    return np.asarray([
        float(np.mean([subscale_block_value(r, method, o, items) for o in CANON_OBJECTS]))
        for r in runs
    ], dtype=float)


def alpha_for(runs, method: str, items: tuple[str, ...]) -> float:
    rows = [[subscale_block_value(r, method, o, (i,)) for i in items]
            for r in runs for o in CANON_OBJECTS]
    return SS.cronbach_alpha(np.asarray(rows, dtype=float))


def main() -> None:
    runs = run_cohort(SEED)
    rng = np.random.default_rng(SEED + 31)
    variants = [
        ("AQ-EQ 完整 (EQ1+EQ2+EQ3)", ("AQ_EQ1", "AQ_EQ2", "AQ_EQ3")),
        ("AQ-EQ 缩减 (EQ1+EQ2)", ("AQ_EQ1", "AQ_EQ2")),
        ("AQ-IQ 完整 (IQ1+IQ2+IQ3)", ("AQ_IQ1", "AQ_IQ2", "AQ_IQ3")),
        ("AQ-IQ 缩减 (IQ2+IQ3)", ("AQ_IQ2", "AQ_IQ3")),
        ("AQ-IQ 备选 (IQ1+IQ3, 去反向项 IQ2)", ("AQ_IQ1", "AQ_IQ3")),
    ]
    print(f"{'变体':<36} {'OE Mdn':>7} {'EA Mdn':>7} {'diff':>7} {'dz':>7} "
          f"{'p_raw':>8} {'a(OE)':>7} {'a(EA)':>7}")
    for label, items in variants:
        oe = sub_mean(runs, "one_euro", items)
        ea = sub_mean(runs, "egoanchor", items)
        res = SS.paired_test(label, oe, ea, rng, bootstrap=False)
        a_oe = alpha_for(runs, "one_euro", items)
        a_ea = alpha_for(runs, "egoanchor", items)
        print(f"{label:<36} {res.oe_median:>7.2f} {res.ea_median:>7.2f} "
              f"{res.diff_mean:>+7.3f} {res.dz:>+7.3f} {res.p_raw:>8.4f} "
              f"{a_oe:>7.3f} {a_ea:>7.3f}")

    # 家族内 Holm：用缩减版替换后重算五检验家族
    print("\n缩减版替换后的已发表量表家族（Holm，5 检验）：")
    specs = [
        ("AQ-EQ(缩减)", sub_mean(runs, "one_euro", ("AQ_EQ1", "AQ_EQ2")),
         sub_mean(runs, "egoanchor", ("AQ_EQ1", "AQ_EQ2"))),
        ("AQ-IQ(缩减)", sub_mean(runs, "one_euro", ("AQ_IQ2", "AQ_IQ3")),
         sub_mean(runs, "egoanchor", ("AQ_IQ2", "AQ_IQ3"))),
    ]
    from simulate_exp3_opus5_v3 import paired_arrays
    for key in ("TIA_RC", "TIA_UP", "STIAS"):
        oe, ea = paired_arrays(runs, key)
        specs.append((key, oe, ea))
    results = [SS.paired_test(n, o, e, rng, bootstrap=False) for n, o, e in specs]
    SS.holm(results)
    for r in results:
        print(f"  {r.key:<14} dz={r.dz:+.3f} p_raw={r.p_raw:.4f} p_Holm={r.p_holm:.4f} "
              f"{'*' if r.p_holm < 0.05 else ''}")


if __name__ == "__main__":
    main()
