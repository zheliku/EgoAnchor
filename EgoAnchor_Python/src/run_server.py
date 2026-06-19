r"""EgoAnchor Python-only pose debug 启动入口。

运行示例（在 EgoAnchor_Python 目录）：
    pixi run python .\src\run_server.py

本文件只是给 pixi 用文件路径启动的薄壳，真正实现在 egoanchor.app 包内；
通过包级入口导入 app 函数，不直接依赖具体模块文件路径。

当前入口在 Python 侧接收 Quest stereo/camera_info、运行 pose pipeline、显示 OpenCV debug 界面，
并在启用 NATS 时向 Unity 发布 PoseResult，同时接收 reset/reacquire/control 命令。
"""

from __future__ import annotations

from egoanchor.app import tracking_server_main as main


if __name__ == "__main__":
    main()
