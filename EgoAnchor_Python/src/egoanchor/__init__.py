"""EgoAnchor Python 包。

代码从新目录开始实现，只共享跨语言协议源，不导入旧 v1/v2 运行时代码。
当前首个闭环是 Quest/Unity 通过 ZMQ + Protobuf 发送双目图像，Python 实时接收并显示。
"""

from __future__ import annotations

__version__ = "0.3.0"

__all__ = ["__version__"]
