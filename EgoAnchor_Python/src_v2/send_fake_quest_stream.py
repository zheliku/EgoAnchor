"""可直接运行的本机假 Quest 视频流发送 wrapper。

推荐运行方式（在 EgoAnchor_Python 目录）：
    pixi run python .\\src_v2\\send_fake_quest_stream.py

配合接收端：
    pixi run python .\\src_v2\\quest_video_stream_demo.py
"""

from __future__ import annotations

from egoanchor.tests import fake_quest_stream_main as main


if __name__ == "__main__":
    main()
