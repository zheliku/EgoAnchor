"""EgoAnchor v2 Python 主入口。

当前阶段 TrackingRuntime 已可接收 Quest ZMQ/Protobuf 数据面并运行 Python 侧
perception pose pipeline；PoseResult/NATS/Unity Anchor Runtime 后续再接入。

建议：
- 只验证通信时运行 quest_video_stream_demo.py。
- 需要本地 OpenCV pose debug 时运行 quest_pose_debug_demo.py。
- 本入口适合后续接 NATS control/pose publisher，模型逻辑仍不写进 transport 层。
"""

from __future__ import annotations

import argparse
import logging
import time

from egoanchor.config import load_config
from egoanchor.runtime.tracking_runtime import TrackingRuntime


def run_server(config_path: str | None = None) -> None:
    """启动 v2 runtime 骨架。"""

    cfg = load_config(config_path)
    runtime = TrackingRuntime(cfg)
    try:
        runtime.start()
        logging.info("[TrackingServer] v2 runtime started. Press Ctrl+C to exit.")
        while True:
            runtime.tick()
            time.sleep(0.001)
    except KeyboardInterrupt:
        logging.info("[TrackingServer] interrupted by user")
    finally:
        runtime.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="EgoAnchor v2 tracking server skeleton")
    parser.add_argument("--config", default=None, help="可选 v2 TOML 配置路径")
    parser.add_argument("--log", default="INFO", help="日志级别，例如 DEBUG/INFO/WARNING")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, str(args.log).upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    run_server(args.config)


if __name__ == "__main__":
    main()
