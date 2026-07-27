"""换种子检验先行方法诊断的 p=0.046 是结构性还是抽样波动。

若模型存在结构性顺序效应，重抽中 p<.05 的占比会明显高于名义 5%；
若只是这一次抽样的波动，占比应接近 5%，且效应方向在重抽间随机。
"""
from __future__ import annotations

import sys

import numpy as np
from scipy import stats as sps

sys.path.insert(0, r"p:\VSCode-Project\EgoAnchor\2026-EgoAnchor\material")

import sim_opus5_v3_personas as PS
import sim_opus5_v3_responses as RS
from simulate_exp3_opus5_v3 import PRIMARY_ITEMS, object_mean, run_cohort

ITERS = 400
SEED = 20260727


def composite(run: RS.ParticipantRun) -> float:
    return float(np.mean([object_mean(run, "egoanchor", i) - object_mean(run, "one_euro", i)
                          for i in PRIMARY_ITEMS]))


def main() -> None:
    p_values: list[float] = []
    deltas: list[float] = []
    for idx in range(ITERS):
        seed = SEED + 100_000 + idx * 13
        assignments = PS._build_once(seed)
        runs = run_cohort(seed, assignments=assignments)
        left = [composite(r) for r in runs if r.assignment.leading_method == "egoanchor"]
        right = [composite(r) for r in runs if r.assignment.leading_method == "one_euro"]
        _, p = sps.mannwhitneyu(left, right, alternative="two-sided")
        p_values.append(float(p))
        deltas.append(float(np.mean(left) - np.mean(right)))

    arr = np.asarray(p_values)
    dd = np.asarray(deltas)
    print(f"重抽 {ITERS} 次的先行方法诊断：")
    print(f"  p<.05 占比 = {np.mean(arr < 0.05):.3f}（名义水平 0.05）")
    print(f"  p 中位 = {np.median(arr):.3f}")
    print(f"  组间差 (先EA − 先OE) 均值 = {dd.mean():+.4f}, SD = {dd.std(ddof=1):.4f}")
    print(f"  组间差为正的占比 = {np.mean(dd > 0):.3f}（结构性效应应显著偏离 0.5）")
    t, pt = sps.ttest_1samp(dd, 0.0)
    print(f"  组间差是否系统性偏离零：t={t:+.3f}, p={pt:.4f}")

    # 同时检查区块位置这一结构性共线因子
    pos_p: list[float] = []
    for idx in range(120):
        seed = SEED + 200_000 + idx * 17
        assignments = PS._build_once(seed)
        runs = run_cohort(seed, assignments=assignments)
        by_pos: dict[int, list[float]] = {1: [], 2: [], 3: []}
        for run in runs:
            for block in run.blocks:
                by_pos[block.object_position].append(
                    float(np.mean([block.ratings[i] for i in PRIMARY_ITEMS])))
        _, p = sps.kruskal(*(by_pos[i] for i in (1, 2, 3)))
        pos_p.append(float(p))
    pos = np.asarray(pos_p)
    print(f"\n重抽 120 次的物体区块位置诊断：p<.05 占比 = {np.mean(pos < 0.05):.3f}, "
          f"p 中位 = {np.median(pos):.3f}")


if __name__ == "__main__":
    main()
