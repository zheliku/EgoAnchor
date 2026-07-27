"""从摘要 JSON 提取报告所需数字，按报告章节顺序打印。"""
from __future__ import annotations

import json
from pathlib import Path

SRC = Path(r"p:\VSCode-Project\EgoAnchor\2026-EgoAnchor\material\_sim_claude_opus_5_v3_summary.json")
S = json.loads(SRC.read_text(encoding="utf-8"))
PRIMARY = ("Q1", "Q8", "Q2", "Q9", "Q3", "Q6", "Q7")
SCALES = ("AQ_EQ", "AQ_IQ", "TIA_RC", "TIA_UP", "STIAS")


def main() -> None:
    m = S["meta"]
    print("== meta ==")
    for k, v in m.items():
        print(f"  {k}: {v}")
    print(f"\n== session ==\n  {S['session_minutes']}")
    print(f"\n== burden ==\n  {S['burden']}")
    print(f"  ceiling={S['ceiling_rate']:.4f} floor={S['floor_rate']:.4f}")
    print(f"  dist={S['rating_distribution']}")

    print("\n== primary ==")
    for k in PRIMARY:
        p = S["primary"][k]
        r = S["reseed"][k]
        print(f"  {k:<4} OE={p['oe_median']:.2f} EA={p['ea_median']:.2f} "
              f"d={p['diff_mean']:+.3f} sd={p['diff_sd']:.3f} dz={p['dz']:+.3f} "
              f"praw={p['p_raw']:.4f} pholm={p['p_holm']:.4f} "
              f"r={p['r_rb']:+.3f} CI[{p['r_ci'][0]:+.3f},{p['r_ci'][1]:+.3f}] "
              f"+/-/0={p['n_pos']}/{p['n_neg']}/{p['n_tie']} test={p['test_method']} "
              f"| reseed={r['rate']:.3f} dzmed={r['dz_median']:+.3f} "
              f"[{r['dz_lo']:+.3f},{r['dz_hi']:+.3f}]")

    print("\n== published ==")
    for k in SCALES:
        p = S["published"][k]
        r = S["reseed"][k]
        print(f"  {k:<7} OE={p['oe_median']:.2f} EA={p['ea_median']:.2f} "
              f"d={p['diff_mean']:+.3f} dz={p['dz']:+.3f} pholm={p['p_holm']:.4f} "
              f"r={p['r_rb']:+.3f} CI[{p['r_ci'][0]:+.3f},{p['r_ci'][1]:+.3f}] "
              f"a={p['alpha_oe']:.3f}/{p['alpha_ea']:.3f} "
              f"w={p['omega_oe']:.3f}/{p['omega_ea']:.3f} "
              f"+/-/0={p['n_pos']}/{p['n_neg']}/{p['n_tie']} | reseed={r['rate']:.3f}")

    print("\n== AQ items ==")
    for k, v in S["aq_items"].items():
        print(f"  {k:<8} OE={v['oe_median']:.2f} EA={v['ea_median']:.2f} "
              f"d={v['diff_mean']:+.3f} dz={v['dz']:+.3f} praw={v['p_raw']:.4f}")

    print("\n== per object ==")
    for item, objs in S["per_object"].items():
        parts = " | ".join(f"{o}: {v['oe']:.2f}->{v['ea']:.2f} ({v['diff']:+.2f})"
                           for o, v in objs.items())
        print(f"  {item:<7} {parts}")

    print("\n== manipulation ==")
    for e in S["manipulation"]:
        print(f"  {e['name']}: bound={e.get('bound')} p={e.get('tost_p')} "
              f"verdict={e.get('verdict')} oe={e.get('oe_text','')} ea={e.get('ea_text','')} "
              f"diff={e.get('diff_text','')}")

    print("\n== order diagnostics ==")
    for e in S["order_diagnostics"]:
        print(f"  {e}")

    print("\n== events ==")
    for e in S["events"]:
        print(f"  {e[0]}: {e[1]}/{e[2]}")

    print("\n== final ==")
    for k, v in S["final"].items():
        print(f"  {k}: {v}")

    print("\n== themes ==")
    for k, v in sorted(S["themes"].items(), key=lambda kv: -kv[1]):
        if v:
            print(f"  {k}: {v}")

    print("\n== N=18 ==")
    for k, v in S["n18"].items():
        print(f"  {k:<8} pholm={v['p_holm']:.4f} dz={v['dz']:+.3f} sig={v['sig']}")

    print("\n== gain sweep ==")
    print("  GAIN | " + " ".join(f"{i:>6}" for i in PRIMARY) + " | nsig")
    for row in S["gain_sweep"]:
        print(f"  {row[0]:.2f} | " + " ".join(f"{v:>+6.2f}" for v in row[1:8]) + f" | {row[8]}")

    print("\n== channels ==")
    for c in S["channels"]:
        print(f"  {c['channel']:<20} {c['oe']:>9.3f} -> {c['ea']:>9.3f} "
              f"ratio={c['ratio']:>7.2f} adv={c['advantage']:+.3f}")

    print("\n== item advantage ==")
    for k, v in S["item_advantage"].items():
        print(f"  {k:<9} {v:+.4f}")

    print("\n== participants ==")
    for p in S["participants"]:
        print(f"  {p['id']} {p['unit']:<10} acu={p['acuity']:.2f} stab={p['stab_bias']:+.2f} "
              f"lead={p['leading'][:3]} EA={p['ea_label']} "
              f"choice={p['method_choice']:<10} trust={p['trust_choice']:<10} "
              f"str={p['strength']} conf={p['confidence']} min={p['minutes']:.0f} "
              f"cat={p['catastrophe_blocks']} lapse={p['lapse_blocks']} | {p['persona']}")


if __name__ == "__main__":
    main()
