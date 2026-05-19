"""可直接运行的 v2 tracking server wrapper。

推荐运行方式（在 EgoAnchor_Python 目录）：
    pixi run python .\\src_v2\\tracking_server.py

该入口启动 `TrackingRuntime`：接收 ZMQ Quest stream，运行本地 pose pipeline，
并在配置启用时通过 NATS 发布 `PoseResult`。
"""

from __future__ import annotations

from egoanchor.app import tracking_server_main as main


if __name__ == "__main__":
    main()
