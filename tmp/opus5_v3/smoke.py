"""模型烟测：跑完 24 人，检查效应量、结平率、信度、天花板与顺序诊断是否落在真实区间。"""
from __future__ import annotations

import sys
from collections import Counter

import numpy as np
from scipy import stats

sys.path.insert(0, r"p:\VSCode-Project\EgoAnchor\2026-EgoAnchor\material")

import sim_opus5_v3_personas as PP
import sim_opus5_v3_responses as RS
import sim_opus5_v3_stimulus as ST

SEED = 20260727
PRIMARY = ("Q1", "Q8", "Q2", "Q9", "Q3", "Q6", "Q7")


def run(seed: int = SEED) -> list[RS.ParticipantRun]:
    assignments = PP.build_assignments(seed)
    return [RS.simulate_participant(a, seed + 1000 * (idx + 1))
            for idx, a in enumerate(assignments)]


def object_means(runs: list[RS.ParticipantRun], item: str) -> tuple[np.ndarray, np.ndarray]:
    oe, ea = [], []
    for r in runs:
        oe.append(np.mean([b.ratings[item] for b in r.blocks if b.method == "one_euro"]))
        ea.append(np.mean([b.ratings[item] for b in r.blocks if b.method == "egoanchor"]))
    return np.array(oe), np.array(ea)


def subscale_means(runs: list[RS.ParticipantRun], items: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    oe, ea = [], []
    for r in runs:
        o = [np.mean([b.ratings[i] for i in items]) for b in r.blocks if b.method == "one_euro"]
        e = [np.mean([b.ratings[i] for i in items]) for b in r.blocks if b.method == "egoanchor"]
        oe.append(np.mean(o)); ea.append(np.mean(e))
    return np.array(oe), np.array(ea)


def tia_sub(runs: list[RS.ParticipantRun], items: tuple[str, ...], hi: int) -> tuple[np.ndarray, np.ndarray]:
    oe, ea = [], []
    for r in runs:
        for m in r.methods:
            vals = []
            for it in items:
                raw = m.ratings[it]
                vals.append((hi + 1) - raw if it in ST.TIA_REVERSED else raw)
            (ea if m.method == "egoanchor" else oe).append(np.mean(vals))
    return np.array(oe), np.array(ea)


def report(label: str, oe: np.ndarray, ea: np.ndarray) -> None:
    d = ea - oe
    n_ties = int(np.sum(d == 0))
    dz = float(np.mean(d) / np.std(d, ddof=1)) if np.std(d, ddof=1) > 0 else float("nan")
    try:
        w, p = stats.wilcoxon(ea, oe, zero_method="wilcox", alternative="two-sided")
    except ValueError:
        w, p = float("nan"), 1.0
    pos = int(np.sum(d > 0)); neg = int(np.sum(d < 0))
    print(f"{label:<10} OE={np.median(oe):.2f} EA={np.median(ea):.2f} "
          f"diff={np.mean(d):+.3f} dz={dz:+.3f} p={p:.4f} +/-/0={pos}/{neg}/{n_ties}")


def alpha(matrix: np.ndarray) -> float:
    k = matrix.shape[1]
    var_items = matrix.var(axis=0, ddof=1).sum()
    var_total = matrix.sum(axis=1).var(ddof=1)
    if var_total <= 0:
        return float("nan")
    return k / (k - 1) * (1 - var_items / var_total)


def main() -> None:
    runs = run()
    print(f"n = {len(runs)}  session minutes: mean={np.mean([r.session_minutes for r in runs]):.1f} "
          f"range={min(r.session_minutes for r in runs):.0f}-{max(r.session_minutes for r in runs):.0f}")
    print()
    print("== 主证实家族 ==")
    for item in PRIMARY:
        report(item, *object_means(runs, item))
    print()
    print("== 已发表量表家族 ==")
    report("AQ-EQ", *subscale_means(runs, ("AQ_EQ1", "AQ_EQ2", "AQ_EQ3")))
    report("AQ-IQ", *subscale_means(runs, ("AQ_IQ1", "AQ_IQ2", "AQ_IQ3")))
    report("TiA-R/C", *tia_sub(runs, ST.TIA_RC_ITEMS, 5))
    report("TiA-U/P", *tia_sub(runs, ST.TIA_UP_ITEMS, 5))
    report("S-TIAS", *tia_sub(runs, ST.STIAS_ITEMS, 7))
    print()
    print("== AQ 单项 ==")
    for item in ("AQ_EQ1", "AQ_EQ2", "AQ_EQ3", "AQ_IQ1", "AQ_IQ2", "AQ_IQ3"):
        report(item, *object_means(runs, item))
    print()
    # 天花板 / 地板
    allr = [b.ratings[i] for r in runs for b in r.blocks for i in RS.ACTIVE_BLOCK_ITEMS]
    c = Counter(allr)
    print("区块评分分布:", {k: c[k] for k in range(1, 8)},
          f"  7 分占比={c[7]/len(allr):.1%}  1 分占比={c[1]/len(allr):.1%}")
    # 问卷负担
    durs = [b.duration_s for r in runs for b in r.blocks]
    runs5 = [b.max_run_length for r in runs for b in r.blocks]
    print(f"区块问卷时长 median={np.median(durs):.0f}s >150s 占比={np.mean(np.array(durs)>150):.1%}  "
          f"最长同分串>=5 占比={np.mean(np.array(runs5)>=5):.1%}")
    # 信度
    for name, items, hi in (("AQ-EQ", ("AQ_EQ1", "AQ_EQ2", "AQ_EQ3"), 7),
                            ("AQ-IQ", ("AQ_IQ1", "AQ_IQ2", "AQ_IQ3"), 7)):
        for method in ("one_euro", "egoanchor"):
            m = np.array([[b.ratings[i] for i in items] for r in runs for b in r.blocks
                          if b.method == method], dtype=float)
            print(f"  alpha {name} {method}: {alpha(m):.3f}")
    for name, items in (("TiA-R/C", ST.TIA_RC_ITEMS), ("TiA-U/P", ST.TIA_UP_ITEMS),
                        ("S-TIAS", ST.STIAS_ITEMS)):
        hi = 7 if name == "S-TIAS" else 5
        for method in ("one_euro", "egoanchor"):
            rows = []
            for r in runs:
                for mo in r.methods:
                    if mo.method != method:
                        continue
                    rows.append([(hi + 1) - mo.ratings[i] if i in ST.TIA_REVERSED else mo.ratings[i]
                                 for i in items])
            print(f"  alpha {name} {method}: {alpha(np.array(rows, dtype=float)):.3f}")
    print()
    # 最终选择
    print("方法选择:", Counter(r.final.method_choice for r in runs))
    print("信任选择:", Counter(r.final.trust_choice for r in runs))
    print("不一致人数:", sum(1 for r in runs if r.final.method_choice != r.final.trust_choice))
    print("区分信心:", Counter(r.final.discrimination_confidence for r in runs))
    print("强度:", Counter(str(r.final.preference_strength) for r in runs))
    print("结束不适:", Counter(r.final.end_discomfort for r in runs))
    # 事件
    cat = sum(1 for r in runs for b in r.blocks if b.catastrophe)
    lock = sum(1 for r in runs for b in r.blocks if b.lock_misplaced)
    lost = sum(1 for r in runs for b in r.blocks if b.audit["occlusion_lifecycle"] == "Lost")
    frozen = sum(1 for r in runs for b in r.blocks if b.audit["occlusion_lifecycle"] == "FrozenUncertain")
    print(f"事件: OE 灾难恢复={cat}/72  EA 锁错位姿={lock}/72  "
          f"FrozenUncertain={frozen}/144  Lost={lost}/144")
    # 顺序诊断
    for name, key in (("先行方法", "leading_method"), ("标签映射", "ea_label")):
        groups: dict[str, list[float]] = {}
        for r in runs:
            oe = np.mean([b.ratings["Q1"] for b in r.blocks if b.method == "one_euro"])
            ea = np.mean([b.ratings["Q1"] for b in r.blocks if b.method == "egoanchor"])
            groups.setdefault(str(getattr(r.assignment, key)), []).append(ea - oe)
        keys = sorted(groups)
        u, p = stats.mannwhitneyu(groups[keys[0]], groups[keys[1]])
        print(f"顺序诊断 {name}: {keys[0]}={np.mean(groups[keys[0]]):+.3f} "
              f"{keys[1]}={np.mean(groups[keys[1]]):+.3f} p={p:.3f}")


if __name__ == "__main__":
    main()
