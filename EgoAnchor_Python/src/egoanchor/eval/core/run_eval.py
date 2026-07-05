"""EgoAnchor 离线评估 CLI。

入口只读取 `data/eval/<session_id>` 中的 JSONL/manifest，不导入实时
tracking runtime。当前 GT 语义为 Unity Transform GT，因此不执行 hand-eye
标定。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    # 直接执行本脚本时，把 src/ 加入 sys.path 以解析 egoanchor 包。
    # 本文件位于 src/egoanchor/eval/core/run_eval.py，src = parents[3]。
    package_root = Path(__file__).resolve().parents[3]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

from egoanchor.eval.io import load_session
from egoanchor.eval.metrics import compute_all_metrics
from egoanchor.eval.report import write_figures, write_sanity, write_tables


def run_eval(
    session_dir: Path | str,
    *,
    only: str = "all",
    python_log: Path | str | None = None,
    output_log: Path | str | None = None,
    report_dir: Path | str | None = None,
) -> Path:
    """运行一个 session 的离线评估并返回 report 目录。"""

    session_path = Path(session_dir)
    output_dir = Path(report_dir) if report_dir is not None else session_path / "report"
    logs = load_session(session_path, python_log=python_log, output_log=output_log)
    result = compute_all_metrics(logs)

    if only in ("all", "metrics", "tables"):
        write_tables(result, output_dir)
        write_sanity(result, output_dir)
    elif only == "sanity":
        write_sanity(result, output_dir)

    if only in ("all", "figures"):
        write_figures(result, output_dir)
        if only == "figures":
            write_sanity(result, output_dir)

    return output_dir


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数。"""

    parser = argparse.ArgumentParser(description="Run EgoAnchor offline eval for one session.")
    parser.add_argument("--session-dir", required=True, help="EgoAnchor_Python/data/eval/<session_id> 目录。")
    parser.add_argument("--python-log", default=None, help="可选 Python runtime JSONL，默认从 manifest 自动解析。")
    parser.add_argument("--output-log", default=None, help="可选 Unity output/replay JSONL，默认读取 session 的 unity_output。")
    parser.add_argument("--report-dir", default=None, help="可选 report 输出目录，默认写到 session_dir/report。")
    parser.add_argument(
        "--only",
        choices=("all", "metrics", "tables", "figures", "sanity"),
        default="all",
        help="只运行指定导出阶段；metrics/tables 会写 CSV+Markdown+sanity。",
    )
    args = parser.parse_args(argv)

    report = run_eval(
        Path(args.session_dir),
        only=args.only,
        python_log=Path(args.python_log) if args.python_log else None,
        output_log=Path(args.output_log) if args.output_log else None,
        report_dir=Path(args.report_dir) if args.report_dir else None,
    )
    print(f"report_dir={report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

