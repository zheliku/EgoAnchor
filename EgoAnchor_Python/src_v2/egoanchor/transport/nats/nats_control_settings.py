"""NATS 控制面配置对象。"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from egoanchor.protocol import POSE_RESULT


@dataclass(frozen=True, slots=True)
class NatsControlSettings:
    """NATS 控制面运行参数。

    文件名和类名都显式使用 `NatsControl*`，对齐 Unity 侧
    `Assets/Scripts_v2/EgoAnchor/Transport/NatsControlClient.cs` 的命名。
    """

    enabled: bool = False
    url: str = "nats://127.0.0.1:4222"
    pose_result_subject: str = POSE_RESULT
    client_name: str = "egoanchor-python-v2"
    connect_timeout_s: float = 2.0
    max_pending_futures: int = 32
    request_timeout_s: float = 1.0

    @classmethod
    def from_config(cls, cfg: SimpleNamespace) -> "NatsControlSettings":
        """从 v2 runtime 配置读取 NATS 控制面参数。"""

        control = cfg.network.control_plane
        return cls(
            enabled=bool(getattr(control, "enabled", False)),
            url=str(getattr(control, "url", "nats://127.0.0.1:4222")),
            pose_result_subject=str(getattr(control, "pose_result_subject", POSE_RESULT)),
            client_name=str(getattr(control, "client_name", "egoanchor-python-v2")),
            connect_timeout_s=float(getattr(control, "connect_timeout_s", 2.0)),
            max_pending_futures=int(getattr(control, "max_pending_futures", 32)),
            request_timeout_s=float(getattr(control, "request_timeout_s", 1.0)),
        )


__all__ = ["NatsControlSettings"]