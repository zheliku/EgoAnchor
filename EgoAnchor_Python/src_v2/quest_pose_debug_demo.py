"""可直接运行的 v2 Quest pose debug demo wrapper。

推荐运行方式（在 EgoAnchor_Python 目录）：
    pixi run python ./src_v2/quest_pose_debug_demo.py

该 wrapper 只负责让未安装 package 的源码目录可直接运行；实际逻辑在
`egoanchor.app.quest_pose_debug_demo`。
"""

from __future__ import annotations

from egoanchor.app.quest_pose_debug_demo import main


if __name__ == "__main__":
    main()
