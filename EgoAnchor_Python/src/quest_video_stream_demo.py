r"""EgoAnchor Quest 图像通信 demo 启动入口。

运行方式（在 `EgoAnchor_Python` 目录）：
    pixi run python .\src\quest_video_stream_demo.py

本入口只负责把 `src` 作为包根加载，并转交给 `egoanchor.app`。
真正的通信、解码和显示逻辑都放在 `egoanchor` 包内，避免入口脚本堆积业务代码。
"""

from __future__ import annotations

from egoanchor.app import quest_video_probe_main as main


if __name__ == "__main__":
    main()

