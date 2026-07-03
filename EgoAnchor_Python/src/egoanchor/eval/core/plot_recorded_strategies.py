"""
画出真机录制的各 anchor 策略的渲染轨迹曲线，诊断平滑度问题。

输入：<session>/*_unity_output.jsonl （每渲染帧一行，含每个 variant 的 output_pos/rot + aligned_raw）
输出：<session>/strategy_plots/ 下的 PNG

- 每个 variant 一张 6 子图 (X/Y/Z 位置 + 旋转向量 RotVec X/Y/Z)，叠加观测散点和渲染线
- 一张总对比图（所有 variant 的渲染线叠加）
- 支持 --zoom-start/--zoom-end 放大某时间窗
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def quat_to_rotvec_deg(q):
    """四元数 (x,y,z,w) -> 旋转向量 (轴*角, 度)。与 identity 同半球，连续无 gimbal lock。"""
    q = np.asarray(q, dtype=float)
    n = np.linalg.norm(q)
    if n < 1e-9:
        return np.zeros(3)
    q = q / n
    if q[3] < 0:  # 同半球
        q = -q
    v = q[:3]
    sin_half = np.linalg.norm(v)
    if sin_half < 1e-9:
        return np.zeros(3)
    half = np.arctan2(sin_half, q[3])  # 半角
    return v / sin_half * (2.0 * half) * (180.0 / np.pi)


def load(session_dir):
    matches = glob.glob(os.path.join(session_dir, "*_unity_output.jsonl"))
    if len(matches) != 1:
        sys.exit(f"期望唯一 *_unity_output.jsonl，实际 {len(matches)} 个")
    path = matches[0]

    # variants[label] -> dict of arrays; observations deduped by source_frame_id
    render = {}     # label -> list of (t, pos[3], rotvec[3])
    obs_seen = set()
    obs = []        # (t_capture, pos[3], rotvec[3])
    t0 = None

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            rmono = o.get("render_mono_ms")
            if rmono is None:
                continue
            if t0 is None:
                t0 = rmono
            t = (rmono - t0) / 1000.0
            for v in o.get("variants", []):
                label = v.get("label")
                if label is None:
                    continue
                if v.get("has_output_pose") and v.get("output_pos") and v.get("output_rot"):
                    render.setdefault(label, []).append(
                        (t, np.array(v["output_pos"], float), quat_to_rotvec_deg(v["output_rot"]))
                    )
                # 观测（primary 的 aligned_raw，按 source_frame_id 去重）
                if v.get("is_primary") and v.get("has_aligned_raw"):
                    sfid = v.get("source_frame_id", -1)
                    if sfid not in obs_seen and sfid >= 0:
                        obs_seen.add(sfid)
                        cap = v.get("source_capture_mono_ms")
                        tc = (cap - t0) / 1000.0 if cap is not None else t
                        obs.append((tc, np.array(v["aligned_raw_pos"], float), quat_to_rotvec_deg(v["aligned_raw_rot"])))

    return render, sorted(obs, key=lambda r: r[0]), t0


PANELS = [
    ("X position (m)", lambda pos, rv: pos[0]),
    ("Y position (m)", lambda pos, rv: pos[1]),
    ("Z position (m)", lambda pos, rv: pos[2]),
    ("RotVec X (deg)", lambda pos, rv: rv[0]),
    ("RotVec Y (deg)", lambda pos, rv: rv[1]),
    ("RotVec Z (deg)", lambda pos, rv: rv[2]),
]

COLORS = {
    "raw": "#999999",
    "cv+blend": "#2ca02c",
    "kalman+blend": "#d62728",
    "oneeuro+blend": "#9467bd",
    "kalman+interp": "#ff7f0e",
    "raw_passthrough": "#000000",
}


def arrays(records):
    t = np.array([r[0] for r in records])
    pos = np.array([r[1] for r in records])
    rv = np.array([r[2] for r in records])
    return t, pos, rv


def plot_one(label, render_records, obs, out_path, window=None):
    fig, axes = plt.subplots(6, 1, figsize=(16, 13), sharex=True)
    fig.suptitle(label + (f"  (zoom {window[0]:.1f}-{window[1]:.1f}s)" if window else ""), fontsize=14)
    ot, opos, orv = arrays(obs)
    rt, rpos, rrv = arrays(render_records)
    color = COLORS.get(label, "#1f77b4")
    for i, (title, pick) in enumerate(PANELS):
        ax = axes[i]
        oy = np.array([pick(opos[j], orv[j]) for j in range(len(ot))])
        ry = np.array([pick(rpos[j], rrv[j]) for j in range(len(rt))])
        ax.scatter(ot, oy, s=28, facecolors="none", edgecolors="#202020", label="observation (~5fps)", zorder=3)
        ax.plot(rt, ry, color=color, lw=1.6, label=label, zorder=2)
        ax.set_ylabel(title, fontsize=9)
        if window:
            ax.set_xlim(window)
            m = (rt >= window[0]) & (rt <= window[1])
            mo = (ot >= window[0]) & (ot <= window[1])
            vals = np.concatenate([ry[m], oy[mo]]) if (m.any() or mo.any()) else ry
            if len(vals):
                pad = (vals.max() - vals.min()) * 0.1 + 1e-4
                ax.set_ylim(vals.min() - pad, vals.max() + pad)
        if i == 0:
            ax.legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("time (s)")
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    print("  ", out_path)


def plot_comparison(render, obs, out_path, window=None, labels=None):
    fig, axes = plt.subplots(6, 1, figsize=(18, 14), sharex=True)
    fig.suptitle("comparison (all strategies)" + (f"  (zoom {window[0]:.1f}-{window[1]:.1f}s)" if window else ""), fontsize=14)
    ot, opos, orv = arrays(obs)
    use = labels or list(render.keys())
    for i, (title, pick) in enumerate(PANELS):
        ax = axes[i]
        oy = np.array([pick(opos[j], orv[j]) for j in range(len(ot))])
        ax.scatter(ot, oy, s=24, facecolors="none", edgecolors="#202020", label="observation", zorder=5)
        for label in use:
            if label not in render:
                continue
            rt, rpos, rrv = arrays(render[label])
            ry = np.array([pick(rpos[j], rrv[j]) for j in range(len(rt))])
            ax.plot(rt, ry, color=COLORS.get(label, None), lw=1.3, label=label, alpha=0.85)
        ax.set_ylabel(title, fontsize=9)
        if window:
            ax.set_xlim(window)
        if i == 0:
            ax.legend(loc="upper right", fontsize=8, ncol=2)
    axes[-1].set_xlabel("time (s)")
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    print("  ", out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--zoom-start", type=float, default=None)
    ap.add_argument("--zoom-end", type=float, default=None)
    args = ap.parse_args()

    render, obs, t0 = load(args.session)
    out_dir = os.path.join(args.session, "strategy_plots")
    os.makedirs(out_dir, exist_ok=True)
    window = (args.zoom_start, args.zoom_end) if args.zoom_start is not None and args.zoom_end is not None else None

    print(f"variants: {list(render.keys())}")
    print(f"observations: {len(obs)}, render samples per variant: {len(next(iter(render.values())))}")
    print("plots:")
    for label, recs in render.items():
        safe = label.replace("+", "_")
        plot_one(label, recs, obs, os.path.join(out_dir, f"plot_{safe}.png"))
        if window:
            plot_one(label, recs, obs, os.path.join(out_dir, f"plot_{safe}_zoom.png"), window)
    plot_comparison(render, obs, os.path.join(out_dir, "plot_comparison.png"))
    if window:
        plot_comparison(render, obs, os.path.join(out_dir, "plot_comparison_zoom.png"), window)


if __name__ == "__main__":
    main()
