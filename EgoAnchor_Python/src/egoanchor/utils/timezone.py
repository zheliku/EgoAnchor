"""项目统一时区工具。

所有人类可读的时间字符串和 session_id 都使用北京时间（Asia/Shanghai, UTC+8），
不依赖运行机器的系统时区。这样无论 Python 跑在本地还是远程 Linux 服务器，
session 目录名和日志里的可读时间都一致。

注意：本模块只服务于"给人看"的时间。机器对齐基准（单调时钟 mono_ms、
Unix epoch 毫秒 created_unix_ms）与时区无关，不应经过这里。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
"""项目统一的北京时区 (UTC+8)。"""


def beijing_now() -> datetime:
    """返回带北京时区的当前时间，与机器系统时区无关。"""

    return datetime.now(BEIJING_TZ)


__all__ = ["BEIJING_TZ", "beijing_now"]
