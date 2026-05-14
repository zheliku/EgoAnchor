from __future__ import annotations

"""
Protobuf 类型注册表。

NATS 收到的是 bytes，subject registry 只告诉我们“这个 subject 对应哪个
protobuf full name”。本模块负责把 full name 映射到 Python 生成类，并提供
统一的 parse/serialize 入口。

这样 router 不需要写 `if subject == ...: ResetTrackingRequest.ParseFromString(...)`，
后续新增消息时只要 proto 生成代码和 subjects registry 同步即可。
"""

from google.protobuf.message import Message

from egoanchor.protocol.v1 import anchor_pb2, common_pb2, quest_pb2


class ProtobufRegistry:
    """protobuf full name -> Python generated message class 的映射。"""

    def __init__(self) -> None:
        self._types: dict[str, type[Message]] = {}
        # 这里注册的是生成代码模块；业务逻辑不要直接依赖具体 pb2 文件名。
        self.register_module(common_pb2)
        self.register_module(quest_pb2)
        self.register_module(anchor_pb2)

    def register_module(self, module: object) -> None:
        """扫描一个 pb2 模块，把其中所有 Message 类型加入映射表。"""
        for value in vars(module).values():
            descriptor = getattr(value, "DESCRIPTOR", None)
            full_name = getattr(descriptor, "full_name", None)
            if full_name and isinstance(value, type) and issubclass(value, Message):
                self._types[full_name] = value

    def get_type(self, full_name: str) -> type[Message]:
        """根据 protobuf full name 取生成类。"""
        try:
            return self._types[full_name]
        except KeyError as exc:
            raise KeyError(f"Unknown protobuf type: {full_name}") from exc

    def parse(self, full_name: str, payload: bytes) -> Message:
        """把 bytes 解析成指定 protobuf 类型的 message。"""
        msg_type = self.get_type(full_name)
        msg = msg_type()
        msg.ParseFromString(payload)
        return msg

    @staticmethod
    def serialize(message: Message) -> bytes:
        """把 protobuf message 序列化为 NATS payload bytes。"""
        return message.SerializeToString()

    def has_type(self, full_name: str) -> bool:
        """测试/启动校验用：确认 registry 中能找到指定 protobuf 类型。"""
        return full_name in self._types
