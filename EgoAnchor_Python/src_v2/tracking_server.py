"""可直接运行的 v2 tracking server wrapper。

推荐运行方式（在 EgoAnchor_Python 目录）：
    pixi run python .\\src_v2\\tracking_server.py

当前该入口只启动 TrackingRuntime 骨架；如果只想看实时视频，请优先运行
src_v2/quest_video_stream_demo.py。
"""

from __future__ import annotations

from egoanchor.app import tracking_server_main as main


if __name__ == "__main__":
    main()
