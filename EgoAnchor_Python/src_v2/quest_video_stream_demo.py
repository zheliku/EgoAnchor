"""可直接运行的 v2 Quest 视频流 demo wrapper。

推荐运行方式（在 EgoAnchor_Python 目录）：
    pixi run python .\\src_v2\\quest_video_stream_demo.py

为什么需要 wrapper：
- 当前 v2 还没有打包安装为 Python package。
- 直接运行本文件时，Python 会把 src_v2 放入 sys.path，从而能正常 import egoanchor.*。
"""

from __future__ import annotations

from egoanchor.app.quest_video_stream_demo import main


if __name__ == "__main__":
    main()
