r"""EgoAnchor Python-only pose debug 入口。

运行示例（在 EgoAnchor_Python 目录）：
    pixi run python .\src\tracking_server.py

当前入口在 Python 侧接收 Quest stereo/camera_info、运行 pose pipeline、显示 OpenCV debug 界面，
并在启用 NATS 时向 Unity 发布 PoseResult，同时接收 reset/reacquire/control 命令。
"""

from __future__ import annotations

from egoanchor.app import tracking_server_main as main


if __name__ == "__main__":
    main()


