"""Protobuf 类型注册表。

NATS/ZMQ transport 收到的是 bytes，subject 契约只记录 protobuf full name。
本模块负责把 full name 映射到生成代码类，并提供统一 parse/serialize 入口。
"""

from __future__ import annotations

from google.protobuf.message import Message

from . import v1


class ProtobufRegistry:
    """protobuf full name -> generated message class 的映射。"""

    def __init__(self) -> None:
        """注册 当前主线使用的 protocol.v1 生成模块。"""

        self._types: dict[str, type[Message]] = {}
        self.register_module(v1.common_pb2)
        self.register_module(v1.quest_pb2)
        self.register_module(v1.anchor_pb2)

    def register_module(self, module: object) -> None:
        """扫描一个 pb2 模块，把其中所有 Message 类型加入映射。"""

        for value in vars(module).values():
            descriptor = getattr(value, "DESCRIPTOR", None)
            full_name = getattr(descriptor, "full_name", None)
            if full_name and isinstance(value, type) and issubclass(value, Message):
                self._types[str(full_name)] = value

    def get_type(self, full_name: str) -> type[Message]:
        """按 protobuf full name 读取 generated message class。"""

        try:
            return self._types[full_name]
        except KeyError as exc:
            raise KeyError(f"unknown protobuf type: {full_name}") from exc

    def parse(self, full_name: str, payload: bytes) -> Message:
        """把 bytes 解析为指定 protobuf message。"""

        msg_type = self.get_type(full_name)
        msg = msg_type()
        msg.ParseFromString(payload)
        return msg

    @staticmethod
    def serialize(message: Message) -> bytes:
        """把 protobuf message 序列化为 bytes。"""

        return message.SerializeToString()

    def has_type(self, full_name: str) -> bool:
        """启动校验/单测用：确认某个 protobuf full name 已注册。"""

        return full_name in self._types


__all__ = ["ProtobufRegistry"]
