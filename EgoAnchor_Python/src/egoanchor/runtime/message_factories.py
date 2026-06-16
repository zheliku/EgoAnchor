"""runtime Protobuf 消息构造器。"""

from __future__ import annotations

from collections.abc import Iterable as IterableABC
import math
import time
import uuid
from typing import Any, Iterable

from egoanchor.perception import PoseObservation
from egoanchor.protocol import anchor_pb2, common_pb2
from .runtime_state import RuntimeState, runtime_state_value

SCHEMA_VERSION = "v1"
"""当前共享协议 schema 版本字符串。"""


def _finite_or_default(value: object, default: float = 0.0) -> float:
    """把任意值转成有限 float；失败、NaN 或 Inf 时使用默认值。"""

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _finite_or_none(value: object) -> float | None:
    """把任意值转成有限 float；失败、NaN 或 Inf 时返回 None。"""

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _int_or_default(value: object, default: int = 0) -> int:
    """把任意值转成 int；失败、NaN 或 Inf 时使用默认值。"""

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _build_message_header(
    *,
    session_id: str,
    client_id: str,
    anchor_id: str,
    frame_id: int,
    request_id: str = "",
) -> common_pb2.MessageHeader:
    """构造带统一时间戳和 schema 版本的共享消息头。"""

    return common_pb2.MessageHeader(
        message_id=uuid.uuid4().hex,
        request_id=str(request_id or ""),
        session_id=str(session_id),
        client_id=str(client_id),
        anchor_id=str(anchor_id),
        frame_id=int(frame_id),
        sender_mono_ms=time.monotonic() * 1000.0,
        created_unix_ms=time.time() * 1000.0,
        schema_version=SCHEMA_VERSION,
    )


class PoseResultFactory:
    """把感知侧 PoseObservation 转成共享协议 PoseResult。"""

    def __init__(self, *, client_id: str = "egoanchor-python", anchor_id: str = "default", session_id: str = "") -> None:
        """保存消息头中的客户端/anchor 标识。"""

        self.client_id = str(client_id)
        self.anchor_id = str(anchor_id)
        self.session_id = str(session_id or uuid.uuid4().hex)

    def build(self, observation: PoseObservation) -> anchor_pb2.PoseResult:
        """从单帧 PoseObservation 构造 PoseResult。"""

        frame_id = int(observation.frame_id if observation.frame_id is not None else -1)
        matrix_values = self._pose_matrix_values(observation.pose_matrix_cv_camera)
        invalid_pose_matrix = bool(observation.has_pose and len(matrix_values) != 16)
        has_pose = bool(observation.has_pose and len(matrix_values) == 16)
        result = anchor_pb2.PoseResult()
        result.header.CopyFrom(self._build_header(frame_id))
        result.has_pose = has_pose
        result.phase = str(observation.phase or "")
        result.stage = _int_or_default(observation.stage, 4)
        result.det_count = _int_or_default(observation.det_count)
        result.depth_valid_ratio = _finite_or_default(observation.depth_valid_ratio)
        result.depth_valid_in_mask = _finite_or_default(observation.depth_valid_in_mask)
        result.mask_area_ratio = _finite_or_default(observation.mask_area_ratio)
        result.reliability_score = _finite_or_default(observation.reliability_score)
        result.reliability_flags.extend(str(flag) for flag in observation.reliability_flags)
        result.score_phase = _finite_or_default(observation.score_phase)
        result.score_reprojection = _finite_or_default(observation.score_reprojection)
        result.score_depth = _finite_or_default(observation.score_depth)
        result.score_jump = _finite_or_default(observation.score_jump)
        result.score_mask = _finite_or_default(observation.score_mask)
        result.score_reject = _finite_or_default(observation.score_reject)
        result.score_confidence = _finite_or_default(observation.score_confidence)
        result.color_reprojection = _finite_or_default(observation.color_reprojection, -1.0)
        result.render_quality_mask_iou = _finite_or_default(observation.render_quality_mask_iou)
        result.render_quality_depth_inlier = _finite_or_default(observation.render_quality_depth_inlier)
        result.render_quality_depth_alignment = _finite_or_default(observation.render_quality_depth_alignment)
        result.render_quality_area_ratio_score = _finite_or_default(observation.render_quality_area_ratio_score)
        result.render_quality_render_visible_ratio = _finite_or_default(observation.render_quality_render_visible_ratio)
        result.render_quality_observed_visible_ratio = _finite_or_default(observation.render_quality_observed_visible_ratio)
        result.render_quality_depth_residual_m = _finite_or_default(observation.render_quality_depth_residual_m)
        result.render_quality_render_area_px = _int_or_default(observation.render_quality_render_area_px)
        result.render_quality_evaluated = bool(observation.render_quality_evaluated)
        result.render_quality_status = str(observation.render_quality_status or "")
        result.pose_source = str(observation.pose_source or "")
        result.fps = _finite_or_default(observation.fps)
        result.server_receive_mono_ms = _finite_or_default(observation.server_receive_mono_ms)
        result.server_publish_mono_ms = time.monotonic() * 1000.0
        result.timing.CopyFrom(
            common_pb2.TimingStats(
                yolo_ms=_finite_or_default(observation.yolo_ms),
                depth_ms=_finite_or_default(observation.depth_ms),
                cutie_ms=_finite_or_default(observation.cutie_ms),
                pose_ms=_finite_or_default(observation.pose_ms),
                total_ms=_finite_or_default(observation.total_ms),
            )
        )

        if has_pose:
            result.pose_matrix_cv_camera.CopyFrom(self._matrix_from_values(matrix_values))
        else:
            error_code = "INVALID_POSE_MATRIX" if invalid_pose_matrix else ""
            result.last_error.CopyFrom(self._build_error(observation, code_override=error_code))
        return result

    def _build_header(self, frame_id: int) -> common_pb2.MessageHeader:
        """构造共享消息头。"""

        return _build_message_header(
            session_id=self.session_id,
            client_id=self.client_id,
            anchor_id=self.anchor_id,
            frame_id=frame_id,
        )

    @staticmethod
    def _matrix_from_values(values: Iterable[float]) -> common_pb2.Matrix4x4:
        """把 row-major 4x4 浮点序列写入 Protobuf Matrix4x4。"""

        matrix_values = [float(value) for value in values]
        if len(matrix_values) != 16:
            matrix_values = []
        matrix = common_pb2.Matrix4x4()
        matrix.values.extend(matrix_values)
        return matrix

    @staticmethod
    def _pose_matrix_values(values: object) -> tuple[float, ...]:
        """读取 pose 矩阵值，只接受 16 个有限浮点数。"""

        if values is None:
            return ()
        if hasattr(values, "reshape"):
            values = values.reshape(-1)
        if not isinstance(values, IterableABC):
            return ()
        flattened: list[float] = []
        for value in values:
            if isinstance(value, IterableABC) and not isinstance(value, (str, bytes)):
                for item in value:
                    parsed = _finite_or_none(item)
                    if parsed is None:
                        return ()
                    flattened.append(parsed)
                continue
            parsed = _finite_or_none(value)
            if parsed is None:
                return ()
            flattened.append(parsed)
        if len(flattened) != 16:
            return ()
        return tuple(flattened)

    @staticmethod
    def _build_error(observation: PoseObservation, *, code_override: str = "") -> common_pb2.ErrorInfo:
        """构造无 pose 时的结构化错误信息。"""

        code = str(code_override or observation.failure_reason or observation.phase or "NO_POSE")
        details = ",".join(str(flag) for flag in observation.reliability_flags)
        return common_pb2.ErrorInfo(code=code, message="当前帧没有可应用的 6DoF pose。", details=details)


class StatusEventFactory:
    """构造 Python -> Unity 的 AnchorStatusEvent。"""

    def __init__(self, *, client_id: str = "egoanchor-python", anchor_id: str = "default", session_id: str = "") -> None:
        """保存 status event 消息头中的发布端和 anchor 标识。"""

        self.client_id = str(client_id)
        self.anchor_id = str(anchor_id)
        self.session_id = str(session_id or uuid.uuid4().hex)

    def build(
        self,
        state: RuntimeState | str,
        *,
        event: str,
        message: str = "",
        request_id: str = "",
        frame_id: int | None = None,
        anchor_id: str = "",
        error: common_pb2.ErrorInfo | None = None,
    ) -> anchor_pb2.AnchorStatusEvent:
        """构造一条 AnchorStatusEvent。"""

        msg = anchor_pb2.AnchorStatusEvent()
        msg.header.CopyFrom(self._build_header(request_id=request_id, frame_id=frame_id, anchor_id=anchor_id))
        msg.state = runtime_state_value(state)
        msg.event = str(event or "")
        msg.message = str(message or "")
        if error is not None:
            msg.error.CopyFrom(error)
        return msg

    def build_error(
        self,
        state: RuntimeState | str,
        *,
        event: str,
        code: str,
        message: str,
        details: str = "",
        request_id: str = "",
        frame_id: int | None = None,
        anchor_id: str = "",
    ) -> anchor_pb2.AnchorStatusEvent:
        """构造携带结构化 ErrorInfo 的状态事件。"""

        error = common_pb2.ErrorInfo(code=str(code or ""), message=str(message or ""), details=str(details or ""))
        return self.build(
            state,
            event=event,
            message=message,
            request_id=request_id,
            frame_id=frame_id,
            anchor_id=anchor_id,
            error=error,
        )

    def _build_header(self, *, request_id: str = "", frame_id: int | None = None, anchor_id: str = "") -> common_pb2.MessageHeader:
        """构造共享消息头。"""

        return _build_message_header(
            request_id=str(request_id or ""),
            session_id=self.session_id,
            client_id=self.client_id,
            anchor_id=str(anchor_id or self.anchor_id),
            frame_id=int(frame_id if frame_id is not None else -1),
        )


class HeartbeatFactory:
    """构造 Python -> Unity 的 ServerHeartbeat。"""

    def __init__(self, *, client_id: str = "egoanchor-python", anchor_id: str = "default", session_id: str = "") -> None:
        """保存 heartbeat 消息头中的发布端和 anchor 标识。"""

        self.client_id = str(client_id)
        self.anchor_id = str(anchor_id)
        self.session_id = str(session_id or uuid.uuid4().hex)

    def build(
        self,
        state: RuntimeState | str,
        *,
        input_stats: Any | None = None,
        runtime_fps: float = 0.0,
        publish_fps: float = 0.0,
        command_stats: dict[str, Any] | None = None,
        last_error: common_pb2.ErrorInfo | None = None,
    ) -> anchor_pb2.ServerHeartbeat:
        """构造一条 ServerHeartbeat。"""

        heartbeat = anchor_pb2.ServerHeartbeat()
        heartbeat.header.CopyFrom(self._build_header(input_stats))
        heartbeat.state = runtime_state_value(state)
        heartbeat.input_ready = self._is_input_ready(input_stats)
        heartbeat.latest_stereo_frame_id = self._latest_stereo_frame_id(input_stats)
        heartbeat.camera_info_version = int(getattr(input_stats, "camera_info_version", 0) or 0)
        heartbeat.runtime_fps = _finite_or_default(runtime_fps)
        heartbeat.publish_fps = _finite_or_default(publish_fps)
        heartbeat.command_queue_length = _int_or_default((command_stats or {}).get("queue_length", 0))
        if last_error is not None:
            heartbeat.last_error.CopyFrom(last_error)
        return heartbeat

    def _build_header(self, input_stats: Any | None) -> common_pb2.MessageHeader:
        """构造共享消息头。"""

        frame_id = self._latest_stereo_frame_id(input_stats)
        return _build_message_header(
            session_id=self.session_id,
            client_id=self.client_id,
            anchor_id=self.anchor_id,
            frame_id=frame_id,
        )

    @staticmethod
    def _is_input_ready(input_stats: Any | None) -> bool:
        """判断 Quest stereo 和 camera_info 是否都已到达。"""

        if input_stats is None:
            return False
        if hasattr(input_stats, "latest_stereo_frame_id"):
            stereo_ready = getattr(input_stats, "latest_stereo_frame_id", None) is not None
        else:
            stereo_ready = int(getattr(input_stats, "decoded_stereo", 0) or 0) > 0
        if hasattr(input_stats, "latest_camera_info_frame_id"):
            calibration_ready = getattr(input_stats, "latest_camera_info_frame_id", None) is not None
        else:
            calibration_ready = int(getattr(input_stats, "camera_info_version", 0) or 0) > 0
        return stereo_ready and calibration_ready

    @staticmethod
    def _latest_stereo_frame_id(input_stats: Any | None) -> int:
        """读取 latest stereo frame_id，保留合法的 0 号首帧。"""

        value = getattr(input_stats, "latest_stereo_frame_id", None)
        return int(value) if value is not None else -1


__all__ = ["HeartbeatFactory", "PoseResultFactory", "StatusEventFactory"]
