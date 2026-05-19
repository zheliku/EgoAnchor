r"""EgoAnchor v3 Python-only pose debug 入口。

运行示例（在 EgoAnchor_Python 目录）：
    pixi run python .\src_v3\tracking_server.py

当前入口只在 Python 侧接收 Quest stereo/camera_info、运行 pose pipeline 并显示
OpenCV debug 界面；暂不连接 NATS，也不向 Unity 发布 PoseResult。
"""

from __future__ import annotations

from egoanchor.app import tracking_server_main as main


if __name__ == "__main__":
    main()
