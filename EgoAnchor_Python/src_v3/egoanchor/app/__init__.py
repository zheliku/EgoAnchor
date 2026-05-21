"""v3 应用入口包。

这里使用惰性导入，避免仅导入 `egoanchor.app` 时就加载 OpenCV 等较重依赖。
业务代码应从包级入口导入 app 函数，而不是直接依赖某个具体文件路径。
"""

from __future__ import annotations

from typing import Any


def quest_video_probe_main(*args: Any, **kwargs: Any) -> Any:
    """启动 Quest 视频流探针入口。"""

    from .probes import main

    return main(*args, **kwargs)


def tracking_server_main(*args: Any, **kwargs: Any) -> Any:
    """启动 Python-only pose debug 入口。"""

    from .tracking_server import main

    return main(*args, **kwargs)


def yoloe_mask_probe_main(*args: Any, **kwargs: Any) -> Any:
    """启动 YOLOE-26 实时掩码验证入口。"""

    from .yoloe_mask_probe import main

    return main(*args, **kwargs)


__all__ = ["quest_video_probe_main", "tracking_server_main", "yoloe_mask_probe_main"]