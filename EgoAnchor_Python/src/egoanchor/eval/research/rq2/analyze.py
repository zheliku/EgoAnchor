"""RQ2 动态追踪多 session 分析 CLI。"""

import argparse

from . import RQ2Config, run_rq2_analysis

__all__ = [
    "main",
    "run_rq2_analysis",
]


def main(argv: list[str] | None = None) -> int:
    """解析命令行参数，运行 RQ2 分析并打印审计与 trial 汇总。"""

    parser = argparse.ArgumentParser(description="Run EgoAnchor RQ2 dynamic tracking analysis.")
    parser.add_argument(
        "--session-dir",
        action="append",
        required=True,
        help="data/eval/<session_id> 目录；可重复传入以联合分析多个 session。",
    )
    parser.add_argument(
        "--report-dir",
        default=None,
        help="可选输出目录；单 session 默认 <session>/report。",
    )
    parser.add_argument(
        "--translation-tolerance-m",
        type=float,
        default=0.05,
        help="within-tolerance 主终点的平移误差阈值。",
    )
    parser.add_argument(
        "--rotation-tolerance-deg",
        type=float,
        default=10.0,
        help="within-tolerance 主终点的旋转误差阈值。",
    )
    args = parser.parse_args(argv)
    config = RQ2Config(
        translation_tolerance_m=args.translation_tolerance_m,
        rotation_tolerance_deg=args.rotation_tolerance_deg,
    )
    tables = run_rq2_analysis(
        args.session_dir,
        report_dir=args.report_dir,
        config=config,
    )
    session_audit = tables["rq2_session_audit"]
    trial_audit = tables["rq2_trial_audit"]
    design_audit = tables["rq2_design_audit"]
    summary = tables["rq2_trial_summary"]
    print("RQ2 session audit:")
    print(
        session_audit.to_string(index=False)
        if not session_audit.empty
        else "  <no data>"
    )
    print("RQ2 trial audit:")
    print(trial_audit.to_string(index=False) if not trial_audit.empty else "  <no data>")
    print("RQ2 design audit:")
    print(design_audit.to_string(index=False) if not design_audit.empty else "  <no data>")
    print("RQ2 trial summary:")
    print(summary.to_string(index=False) if not summary.empty else "  <no data>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
