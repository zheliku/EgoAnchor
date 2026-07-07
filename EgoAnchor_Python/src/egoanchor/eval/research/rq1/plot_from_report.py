"""从已算好的 report CSV 重绘 RQ1 静态锚定 2×2 网格图。

为什么单独一个脚本：完整分析链路 :mod:`egoanchor.eval.research.rq1.analyze`
会 import 整个 metrics 引擎，进而拉起 ``cv2`` 等重依赖；而**画图只需要**
``anchor_error_detail.csv`` 这一张已算好的长表。本脚本只读该 CSV 再调用
:func:`egoanchor.eval.research.rq1.analyze.write_rq1_figure`，因此在只装了
matplotlib/pandas/numpy 的轻环境里也能一键复现论文图，无需重算指标、无需 cv2。

用法（在 EgoAnchor_Python 目录下）::

    KMP_DUPLICATE_LIB_OK=TRUE pixi run python -m egoanchor.eval.research.rq1.plot_from_report \\
        --report-dir data/eval/20260707_141751_controller_right/report

默认画**完整静止序列**（不裁剪最优区间），与 analyze.py 的
``STATIC_STEADY_WINDOW_S = None`` 口径一致；如需仅稳态窗口，传 ``--static-window 50 75``。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pandas as pd

if __package__ in (None, ""):
    # 直接执行本脚本时，把 src/ 加入 sys.path 以解析 egoanchor 包。
    # 本文件位于 src/egoanchor/eval/research/rq1/plot_from_report.py，src = parents[4]。
    _package_root = Path(__file__).resolve().parents[4]
    if str(_package_root) not in sys.path:
        sys.path.insert(0, str(_package_root))

# 只依赖纯绘图层（无 cv2/metrics 重依赖），故轻环境也能一键复现。
from egoanchor.eval.research.rq1.plot import DEFAULT_FIGS_DIR, write_rq1_figure


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数：读 report CSV → 重绘 fig_rq1_static.{png,pdf}。"""

    parser = argparse.ArgumentParser(
        description="从 report/anchor_error_detail.csv 重绘 RQ1 静态锚定图（不重算指标）。"
    )
    parser.add_argument(
        "--report-dir",
        required=True,
        help="含 anchor_error_detail.csv 的 report 目录，如 data/eval/<session>/report。",
    )
    parser.add_argument(
        "--figs-dir",
        default=None,
        help="图输出目录，默认仓库根 2026-EgoAnchor-Typst/figs/rq1。",
    )
    parser.add_argument(
        "--static-window",
        nargs=2,
        type=float,
        metavar=("START_S", "END_S"),
        default=None,
        help="可选 static 列裁剪窗口（相对起点秒）；缺省画完整序列，不取最优区间。",
    )
    args = parser.parse_args(argv)

    detail_path = Path(args.report_dir) / "anchor_error_detail.csv"
    if not detail_path.is_file():
        parser.error(f"找不到 {detail_path}")

    detail = pd.read_csv(detail_path)
    tables = {"anchor_error_detail": detail}

    figs = Path(args.figs_dir) if args.figs_dir else DEFAULT_FIGS_DIR
    window = tuple(args.static_window) if args.static_window else None
    pdf_path = write_rq1_figure(tables, figs / "fig_rq1_static", static_window_s=window)

    print(f"wrote {pdf_path}")
    print(f"wrote {pdf_path.with_suffix('.png')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
