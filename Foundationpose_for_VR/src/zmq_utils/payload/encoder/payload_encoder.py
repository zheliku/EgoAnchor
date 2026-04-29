from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PayloadEncoder(ABC):
    """业务 payload 编码器抽象接口。

    传输层只关心 topic 和 bytes；具体业务对象到 MessagePack payload 的转换
    由子类负责。返回 None 表示当前输入不足或编码失败，发送端应跳过该帧。
    """

    @abstractmethod
    def encode(self, *args: Any, **kwargs: Any) -> bytes | None:
        """编码业务数据为单帧 payload；参数格式由子类定义。"""
        raise NotImplementedError
