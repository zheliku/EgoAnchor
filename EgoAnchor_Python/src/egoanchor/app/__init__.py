"""应用入口包。

业务代码应从包级入口导入 app 函数，而不是直接依赖某个具体文件路径。
"""

from __future__ import annotations

from .tracking_server import main as tracking_server_main, run_tracking_server, should_show_waiting_frame


__all__ = ["run_tracking_server", "should_show_waiting_frame", "tracking_server_main"]
