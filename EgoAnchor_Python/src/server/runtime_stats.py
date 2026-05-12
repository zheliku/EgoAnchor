"""Runtime statistics for object_tracking_server."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


def ema(prev: float, value: float, alpha: float) -> float:
    """指数滑动平均；首个样本直接作为初始值。"""
    if prev <= 0.0:
        return value
    return prev * (1.0 - alpha) + value * alpha


@dataclass
class TrackingServerStats:
    """聚合 object_tracking_server 主循环统计，避免计数逻辑散在主入口里。"""

    latency_alpha: float
    start_t: float = field(default_factory=time.perf_counter)
    frame_count: int = 0
    sent_count: int = 0
    dropped_count: int = 0
    pose_count: int = 0
    reset_count: int = 0
    run_ms_ema: float = 0.0
    proc_ms_ema: float = 0.0
    wait_ms_ema: float = 0.0
    send_ms_ema: float = 0.0
    e2e_ms_ema: float = 0.0

    def record_output(self, has_pose: bool) -> None:
        self.frame_count += 1
        if has_pose:
            self.pose_count += 1

    def record_payload_drop(self) -> None:
        self.dropped_count += 1

    def record_send(self, sent: bool) -> None:
        if sent:
            self.sent_count += 1
        else:
            self.dropped_count += 1

    def record_reset(self) -> None:
        self.reset_count += 1

    def record_latency(
        self,
        *,
        run_ms: float,
        proc_ms: float,
        wait_ms: float,
        send_ms: float,
        e2e_ms: float,
    ) -> None:
        self.run_ms_ema = ema(self.run_ms_ema, run_ms, self.latency_alpha)
        self.proc_ms_ema = ema(self.proc_ms_ema, proc_ms, self.latency_alpha)
        self.wait_ms_ema = ema(self.wait_ms_ema, wait_ms, self.latency_alpha)
        self.send_ms_ema = ema(self.send_ms_ema, send_ms, self.latency_alpha)
        self.e2e_ms_ema = ema(self.e2e_ms_ema, e2e_ms, self.latency_alpha)

    @property
    def pub_fps(self) -> float:
        elapsed = max(time.perf_counter() - self.start_t, 1e-6)
        return self.sent_count / elapsed

    @property
    def pose_ratio(self) -> float:
        return self.pose_count / max(self.frame_count, 1)

    @property
    def drop_ratio(self) -> float:
        return self.dropped_count / max(self.sent_count + self.dropped_count, 1)

    def debug_overlay_lines(self) -> list[str]:
        return [
            (
                f"e2e={self.e2e_ms_ema:.0f}ms run={self.run_ms_ema:.0f}ms "
                f"proc={self.proc_ms_ema:.0f}ms send={self.send_ms_ema:.1f}ms"
            ),
            f"sent={self.sent_count} drop={self.dropped_count} reset={self.reset_count}",
        ]
