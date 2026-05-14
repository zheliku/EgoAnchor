from __future__ import annotations

"""
EgoAnchor v2 subject registry 读取器。

设计意图：
- subject 名称、消息类型、通信模式只在 `EgoAnchor_Protocol/subjects.v1.json` 中维护一份；
- Python 运行时启动时读取该 JSON，生成 `SubjectSpec`；
- 业务代码通过 registry 查询 subject，而不是到处硬编码字符串。

注意：这里不是新的协议源头，它只是把共享 registry 文件加载到 Python 进程中。
真正的协议源头仍然是 `EgoAnchor_Protocol/subjects.v1.json` 和 `.proto` 文件。
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SubjectSpec:
    """单个 NATS subject 的静态契约。

    字段说明：
    - subject：NATS 路由名，例如 `egoanchor.v1.cmd.anchor.reset`。
    - direction：消息方向，用来决定 server/client 侧是否需要订阅。
    - protobuf：请求或 pub/sub 消息的 protobuf full name。
    - mode：`pubsub` 或 `request_reply`。
    - latest_only：实时流是否只保留最新帧。
    - reply：request/reply 的响应 protobuf full name。
    - idempotent_by：命令幂等键，目前统一为 `header.request_id`。
    """

    subject: str
    direction: str
    protobuf: str
    mode: str
    latest_only: bool = False
    reply: str | None = None
    idempotent_by: str | None = None

    @property
    def is_request_reply(self) -> bool:
        return self.mode == "request_reply"


class SubjectRegistry:
    """加载并查询 v2 subject 契约。"""

    def __init__(self, specs: dict[str, SubjectSpec]):
        self._specs = dict(specs)

    @classmethod
    def load(cls, path: Path | None = None) -> SubjectRegistry:
        """从 JSON 文件加载 registry。

        单测通常不传 path，直接使用项目默认路径；如果后续需要测试不同版本
        registry，可以传入临时 JSON 文件。
        """
        registry_path = path or cls.default_registry_path()
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        specs: dict[str, SubjectSpec] = {}
        for subject, raw in data.items():
            if not isinstance(raw, dict):
                raise ValueError(f"Invalid subject spec for {subject}")
            specs[subject] = cls._parse_spec(subject, raw)
        return cls(specs)

    @staticmethod
    def default_registry_path() -> Path:
        """返回仓库根目录下共享 subject registry 的默认路径。"""
        return Path(__file__).resolve().parents[4] / "EgoAnchor_Protocol" / "subjects.v1.json"

    @staticmethod
    def _parse_spec(subject: str, raw: dict[str, Any]) -> SubjectSpec:
        """把 JSON dict 转为强类型 `SubjectSpec`，并做基础字段校验。"""
        mode = str(raw.get("mode", ""))
        if mode not in {"pubsub", "request_reply"}:
            raise ValueError(f"Invalid mode for {subject}: {mode}")
        protobuf = str(raw.get("protobuf", ""))
        if not protobuf:
            raise ValueError(f"Missing protobuf type for {subject}")
        return SubjectSpec(
            subject=subject,
            direction=str(raw.get("direction", "")),
            protobuf=protobuf,
            mode=mode,
            latest_only=bool(raw.get("latest_only", False)),
            reply=raw.get("reply"),
            idempotent_by=raw.get("idempotent_by"),
        )

    def get(self, subject: str) -> SubjectSpec:
        """按 subject 名称查契约；未知 subject 直接抛错，避免静默丢消息。"""
        try:
            return self._specs[subject]
        except KeyError as exc:
            raise KeyError(f"Unknown EgoAnchor v2 subject: {subject}") from exc

    def all(self) -> tuple[SubjectSpec, ...]:
        """返回全部 subject spec，供 router 批量订阅。"""
        return tuple(self._specs.values())

    def by_mode(self, mode: str) -> tuple[SubjectSpec, ...]:
        """按通信模式筛选，例如只取 request/reply 命令 subject。"""
        return tuple(spec for spec in self._specs.values() if spec.mode == mode)
