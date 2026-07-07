import pandas as pd, numpy as np
csv = r"data/eval/20260707_122900_controller_right/report/anchor_error_detail.csv"
d = pd.read_csv(csv)
d = d[d.condition == "static_observation"].copy()
full = d[d.label == "Full"].sort_values("render_mono_ms")
t = (full.render_mono_ms.to_numpy() - full.render_mono_ms.min()) / 1000.0
mm = full.translation_error_m.to_numpy() * 1000.0
print("total dur", round(t.max(),1), "n", len(t))
# per 2s max
print("--- per 2s ---")
for s in range(0, int(t.max())+1, 2):
    m = (t >= s) & (t < s+2)
    if m.sum():
        print(f"t={s:2d}-{s+2:2d} p50={np.median(mm[m]):.1f} max={mm[m].max():.1f}")
# find spike locations > 6mm
print("--- samples > 6mm ---")
spk = t[mm > 6]
if len(spk):
    print("times:", np.round(spk,1))
