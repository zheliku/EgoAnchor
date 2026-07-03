"""批量评估多个 EgoAnchor eval sessions。

用法：
    python -m egoanchor.eval.core.batch_eval --sessions-dir data/eval --pattern "*controller_right*"
    python -m egoanchor.eval.core.batch_eval --sessions-dir data/eval --pattern "rq1_*" --only metrics
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    package_root = Path(__file__).resolve().parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

from egoanchor.eval.core.run_eval import run_eval


def batch_eval(
    sessions_dir: Path,
    pattern: str = "*",
    only: str = "all",
    skip_existing: bool = False,
) -> list[dict]:
    """批量评估多个 sessions。

    Args:
        sessions_dir: eval 数据根目录
        pattern: session 目录名匹配模式
        only: 评估阶段 (all/metrics/tables/figures/sanity)
        skip_existing: 跳过已有 report 的 session

    Returns:
        评估结果列表，每项包含 session/status/report/error
    """
    sessions_dir = Path(sessions_dir)
    if not sessions_dir.exists():
        print(f"ERROR: sessions_dir 不存在: {sessions_dir}")
        return []

    # 查找所有匹配的 session 目录
    sessions = sorted([p for p in sessions_dir.glob(pattern) if p.is_dir()])

    if not sessions:
        print(f"WARNING: 没有找到匹配 '{pattern}' 的 session 目录")
        return []

    print(f"{'='*70}")
    print(f"Batch Evaluation")
    print(f"{'='*70}")
    print(f"Sessions dir: {sessions_dir}")
    print(f"Pattern:      {pattern}")
    print(f"Found:        {len(sessions)} sessions")
    print(f"Mode:         {only}")
    print(f"{'='*70}\n")

    results = []

    for i, session in enumerate(sessions, 1):
        print(f"\n{'='*70}")
        print(f"[{i}/{len(sessions)}] Evaluating: {session.name}")
        print(f"{'='*70}")

        # 检查是否已有 report
        if skip_existing and (session / "report").exists():
            print(f"⊙ SKIP: report 目录已存在")
            results.append({
                "session": session.name,
                "status": "skipped",
                "report": str(session / "report"),
            })
            continue

        try:
            report_dir = run_eval(session, only=only)
            print(f"✓ SUCCESS: {report_dir}")
            results.append({
                "session": session.name,
                "status": "success",
                "report": str(report_dir),
            })
        except Exception as e:
            print(f"✗ FAILED: {e}")
            results.append({
                "session": session.name,
                "status": "failed",
                "error": str(e),
            })

    # 打印汇总
    print(f"\n{'='*70}")
    print(f"Batch Evaluation Summary")
    print(f"{'='*70}")

    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = sum(1 for r in results if r["status"] == "failed")
    skipped_count = sum(1 for r in results if r["status"] == "skipped")

    print(f"Total:    {len(results)}")
    print(f"Success:  {success_count}")
    print(f"Failed:   {failed_count}")
    print(f"Skipped:  {skipped_count}")
    print()

    if failed_count > 0:
        print("Failed sessions:")
        for r in results:
            if r["status"] == "failed":
                print(f"  ✗ {r['session']}: {r.get('error', 'unknown error')}")
        print()

    print("Details:")
    for r in results:
        status_icon = {"success": "✓", "failed": "✗", "skipped": "⊙"}[r["status"]]
        print(f"  {status_icon} {r['session']}: {r['status']}")

    print(f"{'='*70}\n")

    return results


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数。"""

    parser = argparse.ArgumentParser(
        description="Batch evaluate multiple EgoAnchor sessions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 评估所有 controller_right sessions
  python -m eval.batch_eval --sessions-dir data/eval --pattern "*controller_right*"

  # 只生成指标表格，不生成图表
  python -m eval.batch_eval --sessions-dir data/eval --pattern "rq1_*" --only metrics

  # 跳过已有 report 的 sessions
  python -m eval.batch_eval --sessions-dir data/eval --skip-existing
""",
    )

    parser.add_argument(
        "--sessions-dir",
        type=Path,
        default=Path("data/eval"),
        help="评估数据根目录，默认 data/eval",
    )
    parser.add_argument(
        "--pattern",
        default="*",
        help="session 目录名匹配模式，支持 glob 通配符，默认 '*'",
    )
    parser.add_argument(
        "--only",
        choices=("all", "metrics", "tables", "figures", "sanity"),
        default="all",
        help="只运行指定导出阶段，默认 all",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="跳过已有 report 目录的 sessions",
    )

    args = parser.parse_args(argv)

    results = batch_eval(
        sessions_dir=args.sessions_dir,
        pattern=args.pattern,
        only=args.only,
        skip_existing=args.skip_existing,
    )

    # 返回失败数作为退出码
    failed_count = sum(1 for r in results if r["status"] == "failed")
    return min(failed_count, 127)


if __name__ == "__main__":
    raise SystemExit(main())

