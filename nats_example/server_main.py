from __future__ import annotations

"""
EgoAnchor v2 smoke server 入口。

当前用途：验证 NATS + Protobuf 的 request/reply 与 pub/sub 路由是否通畅。
它会启动 NATS router，并注册：
- Quest stereo/camera_info 输入 handler；
- reset/reacquire/control command handler。

当前边界：本入口尚未接真实 QuestObjectTrackingPipeline，不会输出真实 PoseResult。
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from egoanchor.handlers import register_command_handlers, register_quest_handlers
from egoanchor.routing import HandlerContext, HandlerRegistry, ProtobufRegistry, SubjectRegistry
from egoanchor.runtime import CommandDedupStore, CommandQueue, LatestInputStore
from egoanchor.transport import NatsClient, NatsRouter


def build_smoke_router() -> NatsRouter:
    """组装一个不接 pipeline 的 smoke router。"""
    subjects = SubjectRegistry.load()
    protobufs = ProtobufRegistry()
    handlers = HandlerRegistry()
    register_quest_handlers(handlers)
    register_command_handlers(handlers)
    context = HandlerContext(
        latest_inputs=LatestInputStore(),
        commands=CommandQueue(),
        dedup=CommandDedupStore(),
    )
    return NatsRouter(subjects, protobufs, handlers, context)


async def _run(url: str) -> None:
    """连接 NATS、挂载 router，并保持进程运行。"""
    client = NatsClient(url=url)
    await client.connect()
    await build_smoke_router().attach(client)
    logging.info("EgoAnchor v2 smoke server listening on %s", url)
    await asyncio.Event().wait()


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="EgoAnchor v2 NATS/Protobuf smoke server")
    parser.add_argument("--nats", default="nats://127.0.0.1:4222")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="日志级别。调试 stereo 高频输入时可设为 DEBUG。",
    )
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    asyncio.run(_run(args.nats))


if __name__ == "__main__":
    main()
