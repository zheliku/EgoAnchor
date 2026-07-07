"""RQ1 静态锚定图的**纯绘图**层（无重依赖）。

本模块只依赖 matplotlib/numpy/pandas，**不 import** metrics 引擎、io、cv2 等重依赖，
因此既能被完整分析链路 :mod:`egoanchor.eval.research.rq1.analyze` 复用，也能被轻量
复现脚本 :mod:`egoanchor.eval.research.rq1.plot_from_report` 直接调用——后者在只装了
matplotlib/pandas/numpy 的环境里也能一键重绘论文图，无需重算指标、无需 cv2。

绘图口径：默认画**完整静止序列**（``STATIC_STEADY_WINDOW_S = None``，不裁剪最优
稳态区间），如实呈现全程数据。若需回到"仅稳态窗口"的旧口径，传入形如 (50.0, 75.0)
的窗口元组即可。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


# static_observation 展示窗口（相对该场景起点，单位秒）。
# 设为 None 表示**不裁剪、画完整静止序列**——论文如实呈现全程数据，不取最优
# 稳态区间。若需回到"仅稳态窗口"的旧口径，改回形如 (50.0, 75.0) 的元组即可。
STATIC_STEADY_WINDOW_S: tuple[float, float] | None = None

# 论文图导出默认目录（解析到仓库根的绝对路径，避免受 cwd 影响）。
# 本文件位于 EgoAnchor_Python/src/egoanchor/eval/research/rq1/plot.py，
# parents[6] = 仓库根。
_REPO_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_FIGS_DIR = _REPO_ROOT / "2026-EgoAnchor-Typst" / "figs" / "rq1"


def write_rq1_figure(
    tables: dict[str, pd.DataFrame],
    out_path: Path | str,
    *,
    static_window_s: tuple[float, float] | None = STATIC_STEADY_WINDOW_S,
) -> Path:
    """绘制 RQ1 静态锚定质量 2×2 网格图（行=指标，列=场景）。

    本函数不重算指标，只消费共享引擎已算好的 ``anchor_error_detail`` 表。为消除
    双 y 轴同色叠加造成的视觉混乱，把平移与旋转拆到各自的子图，每格只画两条同类
    曲线（颜色区分变体）：

    - 上行：平移误差（mm）；下行：旋转误差（°）。
    - 左列：``static_observation``；右列：``occlusion_recovery``。
    - 每格叠加 *Full*（蓝，突出）与 *No-StaticLock*（橙，半透明），并以 ``y=0``
      点线标注 GT 零误差基线（误差即相对目标参考的偏差，理想真值为 0）。

    同列共享时间轴、同行共享量纲，便于横向对比。图例在图顶统一放置一次。

    默认 ``static_window_s=None`` 画**完整静止序列**（不取最优区间），如实呈现全程；
    遮挡列始终不裁（其尖峰正是要展示的 No-StaticLock 缺陷）。

    Args:
        tables: 至少含 ``anchor_error_detail`` 长表的 dict。
        out_path: 输出文件名主干（不含后缀），同时写 ``.pdf`` 与 ``.png``。
        static_window_s: static 列的裁剪窗 ``(start_s, end_s)``（相对该场景起点）；
            传 ``None``（默认）则画完整 static 段。

    Returns:
        写出的 PDF 路径。
    """

    detail = tables.get("anchor_error_detail", pd.DataFrame())
    colors = {"Full": "#2C7FB8", "No-StaticLock": "#E8853A"}
    scenarios = (("static_observation", "Static observation"),
                 ("occlusion_recovery", "Occlusion recovery"))

    # 行=指标（平移/旋转），列=场景（静止/遮挡）；同列共享 x，同行共享 y。
    fig, axes = plt.subplots(2, 2, figsize=(9, 4.8), sharex="col", sharey="row")

    handles_by_label: dict[str, Any] = {}
    for col, (condition, title) in enumerate(scenarios):
        subset = _select_detail(detail, condition, None)
        if condition == "static_observation" and static_window_s is not None:
            subset = _clip_window(subset, static_window_s)
        ax_t, ax_r = axes[0][col], axes[1][col]
        if subset.empty:
            _placeholder(ax_t, f"{title}: no data")
            _placeholder(ax_r, "")
            continue

        t0 = subset["render_mono_ms"].min()
        for label, group in subset.groupby("label", sort=True):
            group = group.sort_values("render_mono_ms")
            t = (group["render_mono_ms"].to_numpy(dtype=float) - t0) * 0.001
            color = colors.get(str(label), "#666666")
            # Full 突出（实线、不透明），No-StaticLock 半透明衬托，避免噪声压过主线。
            lw, alpha = (1.1, 1.0) if str(label) == "Full" else (0.8, 0.7)
            (ln,) = ax_t.plot(
                t, group["translation_error_m"].to_numpy(dtype=float) * 1000.0,
                linewidth=lw, color=color, alpha=alpha, label=str(label),
            )
            ax_r.plot(
                t, group["rotation_error_deg"].to_numpy(dtype=float),
                linewidth=lw, color=color, alpha=alpha,
            )
            handles_by_label.setdefault(str(label), ln)

        for ax in (ax_t, ax_r):
            gt = ax.axhline(0.0, color="#444444", linewidth=0.8, linestyle=":")
            ax.set_ylim(bottom=0.0)
            ax.grid(True, alpha=0.25)
        handles_by_label.setdefault("GT (0 error)", gt)

        ax_t.set_title(title, fontsize=10)
        ax_r.set_xlabel("time (s)")

    axes[0][0].set_ylabel("translation error (mm)")
    axes[1][0].set_ylabel("rotation error (deg)")

    if handles_by_label:
        fig.legend(handles_by_label.values(), handles_by_label.keys(),
                   loc="upper center", ncol=len(handles_by_label),
                   fontsize=8, frameon=False, bbox_to_anchor=(0.5, 1.005))

    stem = Path(out_path)
    stem.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(stem.with_suffix(".png"), dpi=200)
    pdf_path = stem.with_suffix(".pdf")
    fig.savefig(pdf_path)
    plt.close(fig)
    return pdf_path


def _select_detail(detail: pd.DataFrame, condition: str, label: str | None) -> pd.DataFrame:
    """从 anchor_error_detail 取指定 condition（可选 label）子集。"""

    if detail.empty or "condition" not in detail.columns:
        return pd.DataFrame()
    view = detail[detail["condition"] == condition]
    if label is not None and "label" in view.columns:
        view = view[view["label"] == label]
    return view


def _clip_window(subset: pd.DataFrame, window_s: tuple[float, float]) -> pd.DataFrame:
    """把 subset 裁到相对该场景起点的 ``[start_s, end_s)`` 时间窗。

    起点取 subset 内最小 ``render_mono_ms``（各变体同帧录制，共享同一时间轴）；
    仅用于绘图选段，不影响 summary 表的全段统计。
    """

    if subset.empty or "render_mono_ms" not in subset.columns:
        return subset
    start_s, end_s = window_s
    t0 = float(subset["render_mono_ms"].min())
    rel_s = (subset["render_mono_ms"].astype(float) - t0) * 0.001
    return subset[(rel_s >= start_s) & (rel_s < end_s)]


def _placeholder(ax: "plt.Axes", message: str) -> None:
    """空面板提示。"""

    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)
    ax.set_axis_off()
