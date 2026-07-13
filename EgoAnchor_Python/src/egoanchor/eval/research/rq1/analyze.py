"""RQ1 静态锚定质量分析 CLI。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .pipeline import run_rq1_analysis


def main(argv: list[str] | None = None) -> int:
    """运行 RQ1 正式分析并打印精度摘要。"""

    parser = argparse.ArgumentParser(description="Run EgoAnchor RQ1 static anchoring analysis.")
    parser.add_argument("--session-dir", required=True, help="data/eval/<session_id> 目录。")
    parser.add_argument("--report-dir", default=None, help="可选 report 输出目录。")
    parser.add_argument("--figs-dir", default=None, help="可选论文图目录。")
    args = parser.parse_args(argv)
    tables = run_rq1_analysis(
        Path(args.session_dir),
        report_dir=Path(args.report_dir) if args.report_dir else None,
        figs_dir=Path(args.figs_dir) if args.figs_dir else None,
    )
    accuracy = tables.get("anchor_error_summary", pd.DataFrame())
    print("RQ1 anchor_error_summary (static scenes, Full vs No-StaticLock):")
    print(accuracy.to_string(index=False) if not accuracy.empty else "  <no data>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
