"""跨场景汇总分析：将多个sessions的评估结果按场景类型汇总，生成RQ1论文表格。

用法：
    python -m eval.cross_scenario_analysis --sessions-dir data/eval --pattern "rq1_*"
    python -m eval.cross_scenario_analysis --sessions-dir data/eval --output rq1_summary.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    package_root = Path(__file__).resolve().parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))


def collect_session_results(
    sessions_dir: Path,
    pattern: str = "*",
) -> pd.DataFrame:
    """收集所有匹配sessions的评估结果。

    Args:
        sessions_dir: eval 数据根目录
        pattern: session 目录名匹配模式

    Returns:
        包含所有sessions结果的DataFrame
    """
    sessions_dir = Path(sessions_dir)
    sessions = sorted([p for p in sessions_dir.glob(pattern) if p.is_dir()])

    all_results = []

    for session in sessions:
        # 读取 anchor_error_summary.csv
        error_file = session / "report" / "anchor_error_summary.csv"
        if not error_file.exists():
            print(f"WARNING: {session.name} 缺少 anchor_error_summary.csv，跳过")
            continue

        error_df = pd.read_csv(error_file)

        # 读取 jitter_summary.csv
        jitter_file = session / "report" / "jitter_summary.csv"
        jitter_df = pd.read_csv(jitter_file) if jitter_file.exists() else None

        # 读取 lag_summary.csv
        lag_file = session / "report" / "lag_summary.csv"
        lag_df = pd.read_csv(lag_file) if lag_file.exists() else None

        # 读取 latency_summary.csv
        latency_file = session / "report" / "latency_summary.csv"
        latency_df = pd.read_csv(latency_file) if latency_file.exists() else None

        # 读取场景片段（如果存在）
        segments_file = session / "segments.json"
        if segments_file.exists():
            segments_df = pd.read_json(segments_file)
            # 为每个场景类型创建一条记录
            for _, seg in segments_df.iterrows():
                record = {
                    "session_id": session.name,
                    "scenario_type": seg["scenario_type"],
                    "start_time_s": seg["start_time_s"],
                    "end_time_s": seg["end_time_s"],
                    "duration_s": seg["duration_s"],
                }

                # 提取该场景的指标（简化：使用整个session的指标）
                # TODO: 根据时间范围过滤数据
                if not error_df.empty:
                    record.update({
                        "pos_error_mm_mean": error_df["pos_error_mm_mean"].iloc[0],
                        "rot_error_deg_mean": error_df["rot_error_deg_mean"].iloc[0],
                    })

                if jitter_df is not None and not jitter_df.empty:
                    record.update({
                        "jitter_pos_mm": jitter_df["jitter_pos_mm"].iloc[0] if "jitter_pos_mm" in jitter_df.columns else np.nan,
                        "jitter_rot_deg": jitter_df["jitter_rot_deg"].iloc[0] if "jitter_rot_deg" in jitter_df.columns else np.nan,
                    })

                if lag_df is not None and not lag_df.empty:
                    record.update({
                        "lag_ms": lag_df["lag_ms"].iloc[0] if "lag_ms" in lag_df.columns else np.nan,
                    })

                all_results.append(record)
        else:
            # 没有场景片段，使用整个session作为一个记录
            record = {
                "session_id": session.name,
                "scenario_type": "unknown",
                "duration_s": np.nan,
            }

            if not error_df.empty:
                record.update({
                    "pos_error_mm_mean": error_df["pos_error_mm_mean"].iloc[0],
                    "rot_error_deg_mean": error_df["rot_error_deg_mean"].iloc[0],
                })

            if jitter_df is not None and not jitter_df.empty:
                record.update({
                    "jitter_pos_mm": jitter_df["jitter_pos_mm"].iloc[0] if "jitter_pos_mm" in jitter_df.columns else np.nan,
                    "jitter_rot_deg": jitter_df["jitter_rot_deg"].iloc[0] if "jitter_rot_deg" in jitter_df.columns else np.nan,
                })

            if lag_df is not None and not lag_df.empty:
                record.update({
                    "lag_ms": lag_df["lag_ms"].iloc[0] if "lag_ms" in lag_df.columns else np.nan,
                })

            all_results.append(record)

    if not all_results:
        print("WARNING: 没有收集到任何结果")
        return pd.DataFrame()

    return pd.DataFrame(all_results)


def summarize_by_scenario(df: pd.DataFrame) -> pd.DataFrame:
    """按场景类型汇总统计。

    Args:
        df: 包含所有sessions结果的DataFrame

    Returns:
        按场景类型分组的统计DataFrame
    """
    if df.empty:
        return pd.DataFrame()

    # 定义统计函数
    def mean_std(x):
        """计算均值和标准差，格式化为 "mean ± std" """
        if x.isna().all():
            return "N/A"
        mean = x.mean()
        std = x.std()
        if pd.isna(std):
            return f"{mean:.2f}"
        return f"{mean:.2f} ± {std:.2f}"

    # 按场景类型分组
    grouped = df.groupby("scenario_type")

    summary = grouped.agg({
        "pos_error_mm_mean": mean_std,
        "rot_error_deg_mean": mean_std,
        "jitter_pos_mm": mean_std,
        "jitter_rot_deg": mean_std,
        "lag_ms": mean_std,
        "duration_s": "sum",
    })

    # 重命名列
    summary.columns = [
        "位置误差(mm)",
        "旋转误差(度)",
        "位置抖动(mm)",
        "旋转抖动(度)",
        "运动滞后(ms)",
        "总时长(s)",
    ]

    # 添加样本数
    summary["样本数"] = grouped.size()

    # 重新排列列
    summary = summary[["样本数", "总时长(s)", "位置误差(mm)", "旋转误差(度)", "位置抖动(mm)", "旋转抖动(度)", "运动滞后(ms)"]]

    return summary


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数。"""

    parser = argparse.ArgumentParser(
        description="跨场景汇总分析：将多个sessions的结果按场景类型汇总",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 汇总所有RQ1 sessions
  python -m eval.cross_scenario_analysis --sessions-dir data/eval --pattern "rq1_*"

  # 输出到指定文件
  python -m eval.cross_scenario_analysis --sessions-dir data/eval --output rq1_summary.csv

  # 只看controller sessions
  python -m eval.cross_scenario_analysis --pattern "*controller_right*"
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
        "--output",
        type=Path,
        help="输出CSV文件路径（可选）",
    )

    args = parser.parse_args(argv)

    print(f"{'='*70}")
    print(f"跨场景汇总分析")
    print(f"{'='*70}")
    print(f"Sessions dir: {args.sessions_dir}")
    print(f"Pattern:      {args.pattern}")
    print(f"{'='*70}\n")

    # 收集结果
    print("收集sessions结果...")
    df = collect_session_results(args.sessions_dir, args.pattern)

    if df.empty:
        print("ERROR: 没有收集到任何数据")
        return 1

    print(f"收集到 {len(df)} 条记录")
    print(f"场景类型: {df['scenario_type'].unique()}")
    print()

    # 按场景汇总
    print("按场景类型汇总...")
    summary = summarize_by_scenario(df)

    # 打印结果
    print("\n" + "="*70)
    print("RQ1 锚定质量汇总表")
    print("="*70)
    print(summary.to_string())
    print("="*70 + "\n")

    # 保存结果
    if args.output:
        summary.to_csv(args.output)
        print(f"已保存到: {args.output}")

        # 同时保存详细数据
        detail_output = args.output.with_stem(args.output.stem + "_detail")
        df.to_csv(detail_output, index=False)
        print(f"详细数据已保存到: {detail_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
