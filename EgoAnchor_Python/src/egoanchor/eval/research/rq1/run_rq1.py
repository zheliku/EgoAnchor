"""RQ1 锚定质量评估 — 一键批量分析脚本。

从 `data/eval/` 读取所有 session，输出到 `data/research/rq1/`。

用法：
    pixi run python -m egoanchor.eval.research.rq1.run_rq1
    pixi run python -m egoanchor.eval.research.rq1.run_rq1 --source data/eval --output data/research/rq1
    pixi run python -m egoanchor.eval.research.rq1.run_rq1 --pattern "*controller_right*"
    pixi run python -m egoanchor.eval.research.rq1.run_rq1 --check-data
"""

from __future__ import annotations

import argparse
from pathlib import Path

from egoanchor.eval.research.rq1.analyze import analyze_session


def check_integrity(source_dir: Path, pattern: str = "*") -> dict:
    """检查所有 session 的数据完整性（三份 JSONL + manifest）。"""
    sessions = sorted(d for d in source_dir.glob(pattern) if d.is_dir())
    report: dict = {
        "total": len(sessions),
        "complete": 0,
        "missing_python": [],
        "missing_capture": [],
        "missing_output": [],
        "missing_manifest": [],
    }
    for s in sessions:
        missing = []
        if not list(s.glob("*_python_runtime.jsonl")):   missing.append("python_runtime")
        if not list(s.glob("*_unity_capture.jsonl")):    missing.append("unity_capture")
        if not list(s.glob("*_unity_output.jsonl")):     missing.append("unity_output")
        if not (s / "session_manifest.json").exists():   missing.append("manifest")
        if missing:
            for m in missing:
                report[f"missing_{m.split('_')[0]}"].append(s.name)
            print(f"  ERR {s.name}: 缺少 {', '.join(missing)}")
        else:
            report["complete"] += 1
            print(f"  OK {s.name}")
    print(f"\n总计 {report['total']} 个 session，完整 {report['complete']} 个\n")
    return report


def run_rq1(
    source_dir: Path,
    output_dir: Path,
    pattern: str = "*",
    skip_existing: bool = True,
) -> None:
    """批量分析所有 session，每个 session 输出到 output_dir/<session_id>/。"""
    sessions = sorted(d for d in source_dir.glob(pattern) if d.is_dir())
    if not sessions:
        print(f"没有找到任何 session（pattern={pattern}）")
        return

    print(f"找到 {len(sessions)} 个 session，开始分析…\n")
    ok, skip, fail = 0, 0, 0

    for i, session in enumerate(sessions, 1):
        out = output_dir / session.name
        if skip_existing and (out / "summary.md").exists():
            print(f"[{i}/{len(sessions)}] -- 跳过（已存在）: {session.name}")
            skip += 1
            continue
        try:
            analyze_session(session, out)
            print(f"[{i}/{len(sessions)}] OK {session.name} → {out}")
            ok += 1
        except Exception as exc:
            print(f"[{i}/{len(sessions)}] ERR {session.name}: {exc}")
            fail += 1

    print(f"\n完成：OK {ok}  -- 跳过 {skip}  ERR 失败 {fail}\n")
    if ok > 0:
        _write_cross_session_summary(output_dir)


def _write_cross_session_summary(output_dir: Path) -> None:
    """聚合所有 session 的 anchor_error 汇总表，输出 rq1_summary.csv。"""
    import pandas as pd

    dfs: list[pd.DataFrame] = []
    for session_out in sorted(output_dir.iterdir()):
        csv = session_out / "anchor_error_summary.csv"
        if csv.exists():
            df = pd.read_csv(csv)
            df.insert(0, "session", session_out.name)
            dfs.append(df)

    if not dfs:
        print("无 anchor_error 数据可汇总。")
        return

    combined = pd.concat(dfs, ignore_index=True)
    out_csv = output_dir / "rq1_summary.csv"
    combined.to_csv(out_csv, index=False)
    print(f"跨 session 汇总已写到: {out_csv}")

    # 按 condition × label 再聚合（均值）
    num_cols = combined.select_dtypes("number").columns.tolist()
    agg = combined.groupby(["condition", "label"])[num_cols].mean().reset_index()
    agg_csv = output_dir / "rq1_aggregate.csv"
    agg.to_csv(agg_csv, index=False)
    print(f"跨 session 平均汇总: {agg_csv}")


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数。"""
    parser = argparse.ArgumentParser(
        description="RQ1 锚定质量评估 — 批量分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pixi run python -m egoanchor.eval.research.rq1.run_rq1
  pixi run python -m egoanchor.eval.research.rq1.run_rq1 --pattern "*controller_right*"
  pixi run python -m egoanchor.eval.research.rq1.run_rq1 --check-data
""",
    )
    parser.add_argument("--source",  type=Path, default=Path("data/eval"),     help="原始 session 日志目录")
    parser.add_argument("--output",  type=Path, default=Path("data/research/rq1"), help="分析结果输出目录")
    parser.add_argument("--pattern", default="*",     help="Session 目录匹配模式")
    parser.add_argument("--check-data", action="store_true", help="只检查数据完整性，不运行分析")
    parser.add_argument("--no-skip",    action="store_true", help="强制重新分析（不跳过已有结果）")
    args = parser.parse_args(argv)

    source = args.source
    if not source.exists():
        print(f"错误：源目录不存在: {source}")
        return 1

    print(f"源目录:   {source}")
    print(f"输出目录: {args.output}")
    print(f"模式:     {args.pattern}\n")

    print("── 数据完整性检查 ──")
    report = check_integrity(source, args.pattern)

    if args.check_data:
        return 0
    if report["complete"] == 0:
        print("没有完整 session，无法分析。")
        return 1

    args.output.mkdir(parents=True, exist_ok=True)
    print("── 批量分析 ──")
    run_rq1(source, args.output, args.pattern, skip_existing=not args.no_skip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

