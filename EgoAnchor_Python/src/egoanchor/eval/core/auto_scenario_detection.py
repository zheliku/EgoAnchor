"""自动检测评估数据中的场景类型（静止/慢速/快速/旋转/遮挡）。

根据 GT 速度、加速度和 anchor 状态自动识别不同的运动场景，
无需手动按键标记。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


class ScenarioType(Enum):
    """场景类型枚举。"""

    STATIC = "static"              # 静止
    SLOW_MOTION = "slow_motion"    # 慢速运动
    FAST_MOTION = "fast_motion"    # 快速运动
    ROTATION = "rotation"          # 旋转为主
    OCCLUSION = "occlusion"        # 遮挡/追踪丢失
    UNKNOWN = "unknown"            # 未知


@dataclass
class ScenarioSegment:
    """一个连续的场景片段。"""

    scenario_type: ScenarioType
    start_time: float      # 开始时间（秒）
    end_time: float        # 结束时间（秒）
    start_idx: int         # 开始行索引
    end_idx: int          # 结束行索引

    # 统计信息
    duration: float = 0.0
    mean_linear_speed: float = 0.0   # 平均线速度 m/s
    mean_angular_speed: float = 0.0  # 平均角速度 deg/s

    def __post_init__(self):
        self.duration = self.end_time - self.start_time


def compute_velocities(df: pd.DataFrame, time_col: str = "render_mono_ms") -> pd.DataFrame:
    """计算 GT 的线速度和角速度。

    Args:
        df: 包含 gt_pos/gt_rot/render_mono_ms 的 DataFrame
        time_col: 时间列名

    Returns:
        添加了 linear_speed_m_s 和 angular_speed_deg_s 列的 DataFrame
    """
    df = df.copy()

    # 转换为秒
    time_s = df[time_col].values / 1000.0
    dt = np.diff(time_s, prepend=time_s[0])
    dt = np.maximum(dt, 1e-6)  # 避免除零

    # 计算线速度（位置差 / 时间差）
    gt_pos = np.stack(df["gt_pos"].values)  # (N, 3)
    pos_diff = np.diff(gt_pos, axis=0, prepend=gt_pos[0:1])
    linear_speed = np.linalg.norm(pos_diff, axis=1) / dt

    # 计算角速度（四元数差 / 时间差）
    gt_rot = np.stack(df["gt_rot"].values)  # (N, 4) xyzw
    angular_speed = np.zeros(len(gt_rot))

    for i in range(1, len(gt_rot)):
        q1 = gt_rot[i - 1]
        q2 = gt_rot[i]

        # 归一化
        q1 = q1 / (np.linalg.norm(q1) + 1e-9)
        q2 = q2 / (np.linalg.norm(q2) + 1e-9)

        # 计算相对旋转的角度
        # q_rel = q2 * q1^-1
        # 角度 = 2 * arccos(|q_rel.w|)
        dot = abs(np.dot(q1, q2))
        dot = np.clip(dot, -1.0, 1.0)
        angle_rad = 2.0 * np.arccos(dot)
        angular_speed[i] = np.degrees(angle_rad) / dt[i]

    df["linear_speed_m_s"] = linear_speed
    df["angular_speed_deg_s"] = angular_speed

    return df


def detect_scenarios(
    df: pd.DataFrame,
    *,
    static_linear_threshold: float = 0.01,      # 静止线速度阈值 m/s
    static_angular_threshold: float = 5.0,      # 静止角速度阈值 deg/s
    slow_linear_threshold: float = 0.15,        # 慢速线速度阈值 m/s
    fast_linear_threshold: float = 0.5,         # 快速线速度阈值 m/s
    rotation_angular_threshold: float = 30.0,   # 旋转角速度阈值 deg/s
    min_segment_duration: float = 1.0,          # 最小片段时长（秒）
    time_col: str = "render_mono_ms",
) -> list[ScenarioSegment]:
    """自动检测场景片段。

    Args:
        df: 包含 GT pose 和 anchor state 的 DataFrame
        static_linear_threshold: 静止时的线速度上限
        static_angular_threshold: 静止时的角速度上限
        slow_linear_threshold: 慢速运动的线速度上限
        fast_linear_threshold: 快速运动的线速度下限
        rotation_angular_threshold: 旋转为主的角速度下限
        min_segment_duration: 过滤掉短于此时长的片段
        time_col: 时间列名

    Returns:
        场景片段列表
    """
    # 计算速度
    df = compute_velocities(df, time_col)

    # 转换时间到秒
    time_s = df[time_col].values / 1000.0

    # 提取速度
    linear_speed = df["linear_speed_m_s"].values
    angular_speed = df["angular_speed_deg_s"].values

    # 检测 occlusion（anchor state 为 Lost 或 没有 output pose）
    has_output = df["has_output_pose"].values if "has_output_pose" in df.columns else np.ones(len(df), dtype=bool)
    anchor_lost = df["anchor_state"].values == "Lost" if "anchor_state" in df.columns else np.zeros(len(df), dtype=bool)
    is_occluded = (~has_output) | anchor_lost

    # 逐帧分类
    scenario_labels = np.full(len(df), ScenarioType.UNKNOWN)

    for i in range(len(df)):
        if is_occluded[i]:
            scenario_labels[i] = ScenarioType.OCCLUSION
        elif linear_speed[i] < static_linear_threshold and angular_speed[i] < static_angular_threshold:
            scenario_labels[i] = ScenarioType.STATIC
        elif angular_speed[i] > rotation_angular_threshold:
            # 角速度很高，判定为旋转为主
            scenario_labels[i] = ScenarioType.ROTATION
        elif linear_speed[i] > fast_linear_threshold:
            scenario_labels[i] = ScenarioType.FAST_MOTION
        elif linear_speed[i] > static_linear_threshold:
            scenario_labels[i] = ScenarioType.SLOW_MOTION
        else:
            scenario_labels[i] = ScenarioType.STATIC

    # 合并连续的相同标签为片段
    segments = []
    current_type = scenario_labels[0]
    start_idx = 0

    for i in range(1, len(scenario_labels)):
        if scenario_labels[i] != current_type:
            # 创建片段
            segment = ScenarioSegment(
                scenario_type=current_type,
                start_time=time_s[start_idx],
                end_time=time_s[i - 1],
                start_idx=start_idx,
                end_idx=i - 1,
                mean_linear_speed=float(np.mean(linear_speed[start_idx:i])),
                mean_angular_speed=float(np.mean(angular_speed[start_idx:i])),
            )
            segments.append(segment)

            # 开始新片段
            current_type = scenario_labels[i]
            start_idx = i

    # 添加最后一个片段
    segment = ScenarioSegment(
        scenario_type=current_type,
        start_time=time_s[start_idx],
        end_time=time_s[-1],
        start_idx=start_idx,
        end_idx=len(df) - 1,
        mean_linear_speed=float(np.mean(linear_speed[start_idx:])),
        mean_angular_speed=float(np.mean(angular_speed[start_idx:])),
    )
    segments.append(segment)

    # 过滤太短的片段
    segments = [s for s in segments if s.duration >= min_segment_duration]

    return segments


def summarize_segments(segments: list[ScenarioSegment]) -> pd.DataFrame:
    """生成场景片段汇总表。

    Returns:
        包含 scenario_type, start_time, end_time, duration, mean_linear_speed, mean_angular_speed 的 DataFrame
    """
    records = []
    for seg in segments:
        records.append({
            "scenario_type": seg.scenario_type.value,
            "start_time_s": seg.start_time,
            "end_time_s": seg.end_time,
            "duration_s": seg.duration,
            "mean_linear_speed_m_s": seg.mean_linear_speed,
            "mean_angular_speed_deg_s": seg.mean_angular_speed,
        })

    return pd.DataFrame(records)


def print_segment_summary(segments: list[ScenarioSegment]) -> None:
    """打印场景片段摘要。"""
    print("\n" + "="*70)
    print("Scenario Detection Summary")
    print("="*70)

    # 按类型统计
    type_counts = {}
    type_durations = {}

    for seg in segments:
        t = seg.scenario_type.value
        type_counts[t] = type_counts.get(t, 0) + 1
        type_durations[t] = type_durations.get(t, 0.0) + seg.duration

    print(f"{'Type':<20} {'Count':<8} {'Total Duration (s)':<20}")
    print("-"*70)
    for t in sorted(type_counts.keys()):
        print(f"{t:<20} {type_counts[t]:<8} {type_durations[t]:<20.2f}")

    print("\nDetailed Segments:")
    print(f"{'Type':<20} {'Start (s)':<12} {'End (s)':<12} {'Duration (s)':<15} {'Lin Speed (m/s)':<18} {'Ang Speed (deg/s)'}")
    print("-"*120)

    for seg in segments:
        print(
            f"{seg.scenario_type.value:<20} "
            f"{seg.start_time:<12.2f} "
            f"{seg.end_time:<12.2f} "
            f"{seg.duration:<15.2f} "
            f"{seg.mean_linear_speed:<18.3f} "
            f"{seg.mean_angular_speed:<18.2f}"
        )

    print("="*70 + "\n")


if __name__ == "__main__":
    """测试场景检测功能。"""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="自动检测 session 中的场景类型")
    parser.add_argument("--session", type=Path, required=True, help="Session 目录")
    parser.add_argument("--output", type=Path, help="输出 segments.json 的路径")
    args = parser.parse_args()

    # 加载 unity_output
    output_file = list(args.session.glob("*_unity_output.jsonl"))
    if not output_file:
        print(f"ERROR: 未找到 *_unity_output.jsonl")
        raise SystemExit(1)

    # 简单解析（实际应使用 eval.io.load_session）
    rows = []
    with open(output_file[0]) as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    # 提取主变体数据
    records = []
    for row in rows:
        variants = row.get("variants", [])
        primary = next((v for v in variants if v.get("is_primary")), None)
        if primary:
            records.append({
                "render_mono_ms": row.get("render_mono_ms", 0),
                "gt_pos": primary.get("gt_pos"),
                "gt_rot": primary.get("gt_rot"),
                "has_output_pose": primary.get("has_output_pose", False),
                "anchor_state": primary.get("anchor_state", "Unknown"),
            })

    df = pd.DataFrame(records)

    # 检测场景
    segments = detect_scenarios(df)

    # 打印摘要
    print_segment_summary(segments)

    # 输出 JSON
    if args.output:
        summary_df = summarize_segments(segments)
        summary_df.to_json(args.output, orient="records", indent=2)
        print(f"Saved: {args.output}")
