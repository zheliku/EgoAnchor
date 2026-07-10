"""RQ2 动态追踪分析 CLI。"""

import argparse

from .core import (
    RQ2_CONDITIONS,
    build_source_observations,
    compute_model_summary,
    compute_motion_delay,
    compute_trial_summary,
    run_rq2_analysis,
)

__all__ = [
    "RQ2_CONDITIONS",
    "build_source_observations",
    "compute_model_summary",
    "compute_motion_delay",
    "compute_trial_summary",
    "main",
    "run_rq2_analysis",
]


def main(argv: list[str] | None = None) -> int:
    """解析命令行参数，运行 RQ2 分析并打印 trial 汇总。"""

    parser = argparse.ArgumentParser(description="Run EgoAnchor RQ2 dynamic tracking analysis.")
    parser.add_argument("--session-dir", required=True, help="data/eval/<session_id> 目录。")
    parser.add_argument("--report-dir", default=None, help="可选输出目录，默认 <session>/report。")
    args = parser.parse_args(argv)
    tables = run_rq2_analysis(args.session_dir, report_dir=args.report_dir)
    summary = tables["rq2_trial_summary"]
    print("RQ2 trial summary:")
    print(summary.to_string(index=False) if not summary.empty else "  <no data>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
