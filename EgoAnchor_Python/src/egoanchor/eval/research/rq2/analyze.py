"""RQ2 平移/旋转双任务分析 CLI。"""

from __future__ import annotations

import argparse

from .contract import RQ2Config
from .pipeline import run_rq2_analysis

__all__ = ["main", "run_rq2_analysis"]


def main(argv: list[str] | None = None) -> int:
    """运行描述性统计、质量审计与两张论文时间线。"""

    parser = argparse.ArgumentParser(description="Run EgoAnchor RQ2 dynamic anchoring analysis.")
    parser.add_argument(
        "--session-dir",
        action="append",
        required=True,
        help="data/eval/<session_id> 目录；联合分析时可重复传入。",
    )
    parser.add_argument("--report-dir", default=None, help="统计表与时间线输出目录。")
    parser.add_argument("--figs-dir", default=None, help="可选论文图片目录；复制两张时间线。")
    parser.add_argument(
        "--max-translation-speed-m-s",
        type=float,
        default=0.8,
        help="平移帧纳入分析的最大平台参考速度。",
    )
    parser.add_argument(
        "--max-rotation-speed-deg-s",
        type=float,
        default=180.0,
        help="旋转帧纳入分析的最大平台参考角速度。",
    )
    parser.add_argument(
        "--zoom-frame-count",
        type=int,
        default=120,
        help="XYZ-帧时间线固定放大窗口的渲染帧数。",
    )
    args = parser.parse_args(argv)
    config = RQ2Config(
        max_translation_speed_m_s=args.max_translation_speed_m_s,
        max_rotation_speed_deg_s=args.max_rotation_speed_deg_s,
        zoom_frame_count=args.zoom_frame_count,
    )
    tables = run_rq2_analysis(
        args.session_dir,
        report_dir=args.report_dir,
        figs_dir=args.figs_dir,
        config=config,
    )
    for name in (
        "rq2_session_audit",
        "rq2_trial_audit",
        "rq2_condition_summary",
        "rq2_response_summary",
        "rq2_timeline_windows",
    ):
        table = tables[name]
        print(f"{name}:")
        print(table.to_string(index=False) if not table.empty else "  <no data>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
