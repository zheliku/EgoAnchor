"""NATS anchor command request/reply 服务。"""

from __future__ import annotations

import logging

from google.protobuf.message import DecodeError, Message as ProtobufMessage

from egoanchor.protocol import CMD_ANCHOR_CONTROL, CMD_ANCHOR_REACQUIRE, CMD_ANCHOR_RESET
from egoanchor.protocol import anchor_pb2, common_pb2
from egoanchor.runtime.command_ack_factory import make_command_ack
from egoanchor.runtime.command_queue import CommandQueue, RuntimeCommand

from .nats_control_client import NatsControlClient


class AnchorCommandService:
    """把 Unity NATS command 转为 runtime command queue。

    本类仍属于 transport/NATS 组合层：它只做 Protobuf parse、基础校验、enqueue 和 ack。
    真正的 reset/reacquire/control 执行必须在 TrackingRuntime tick 中顺序消费。
    """

    def __init__(self, client: NatsControlClient, command_queue: CommandQueue) -> None:
        self.client = client
        self.command_queue = command_queue
        self._seen_request_ids: set[str] = set()
        self._accepted = 0
        self._rejected = 0
        self._duplicates = 0

    @property
    def accepted_count(self) -> int:
        return self._accepted

    @property
    def rejected_count(self) -> int:
        return self._rejected

    @property
    def duplicate_count(self) -> int:
        return self._duplicates

    def register_handlers(self) -> None:
        """向 NatsControlClient 注册三个 anchor command subject。"""

        self.client.subscribe_request_handler(CMD_ANCHOR_RESET, self._handle_reset)
        self.client.subscribe_request_handler(CMD_ANCHOR_REACQUIRE, self._handle_reacquire)
        self.client.subscribe_request_handler(CMD_ANCHOR_CONTROL, self._handle_control)

    def _handle_reset(self, payload: bytes) -> bytes:
        req = anchor_pb2.ResetTrackingRequest()
        return self._parse_enqueue_ack(payload, req, "reset")

    def _handle_reacquire(self, payload: bytes) -> bytes:
        req = anchor_pb2.ReacquireAnchorRequest()
        return self._parse_enqueue_ack(payload, req, "reacquire")

    def _handle_control(self, payload: bytes) -> bytes:
        req = anchor_pb2.AnchorControlRequest()
        return self._parse_enqueue_ack(payload, req, "control")

    def _parse_enqueue_ack(self, payload: bytes, req: ProtobufMessage, command_type: str) -> bytes:
        try:
            req.ParseFromString(payload)
        except DecodeError as exc:
            self._rejected += 1
            logging.warning("[AnchorCommandService] decode failed command=%s bytes=%d: %s", command_type, len(payload), exc)
            return make_command_ack(
                accepted=False,
                status="DECODE_FAILED",
                message="Command protobuf decode failed",
                error_code="DECODE_FAILED",
                error_message=str(exc),
            ).SerializeToString()

        header = req.header if req.HasField("header") else common_pb2.MessageHeader()
        request_id = str(header.request_id or header.message_id or "")
        if not request_id:
            self._rejected += 1
            return make_command_ack(
                request_header=header,
                accepted=False,
                status="MISSING_REQUEST_ID",
                message="Command requires header.request_id or header.message_id",
                error_code="MISSING_REQUEST_ID",
            ).SerializeToString()

        if request_id in self._seen_request_ids:
            self._duplicates += 1
            return make_command_ack(
                request_header=header,
                accepted=True,
                duplicate=True,
                status="DUPLICATE",
                message="Duplicate command request id ignored",
            ).SerializeToString()

        self._seen_request_ids.add(request_id)
        action = ""
        stage: int | None = None
        if isinstance(req, anchor_pb2.AnchorControlRequest):
            action = anchor_pb2.AnchorControlRequest.ControlAction.Name(req.action)
            stage = int(req.stage) if req.stage > 0 else None
        self.command_queue.push(
            RuntimeCommand(
                command_type=command_type,
                request_id=request_id,
                anchor_id=str(header.anchor_id or ""),
                action=action,
                stage=stage,
            )
        )
        self._accepted += 1
        return make_command_ack(
            request_header=header,
            accepted=True,
            status="ENQUEUED",
            message=f"{command_type} command enqueued",
        ).SerializeToString()


__all__ = ["AnchorCommandService"]