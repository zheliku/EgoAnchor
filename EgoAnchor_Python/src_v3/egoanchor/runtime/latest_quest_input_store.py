"""Quest 输入 latest-only 缓存。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from egoanchor.protocol import quest_pb2


@dataclass(frozen=True)
class QuestInputStats:
    """Quest 输入接收与解码统计。"""

    received: int
    decoded_stereo: int
    decoded_camera_info: int
    decode_failed: int
    invalid_multipart: int
    zmq_errors: int
    stale_stereo_dropped: int
    stream_restarts: int
    camera_info_version: int
    latest_stereo_frame_id: int | None
    latest_camera_info_frame_id: int | None
    latest_session_id: str
    latest_client_id: str
    latest_stereo_age_ms: float | None
    latest_camera_info_age_ms: float | None


class LatestQuestInputStore:
    """按 topic 保存 Quest 输入最新值。"""

    def __init__(self) -> None:
        """初始化 stereo、camera_info 与统计计数器。"""

        self.latest_stereo: quest_pb2.QuestStereoFrame | None = None
        self.latest_camera_info: quest_pb2.QuestCameraInfo | None = None
        self.latest_stereo_rx_mono_ms: float | None = None
        self.latest_camera_info_rx_mono_ms: float | None = None
        self.latest_stereo_frame_id: int | None = None
        self.latest_camera_info_frame_id: int | None = None
        self.latest_session_id = ""
        self.latest_stereo_session_id = ""
        self.latest_camera_info_session_id = ""
        self.latest_client_id = ""
        self.camera_info_version = 0
        self.decoded_stereo = 0
        self.decoded_camera_info = 0
        self.decode_failed = 0
        self.stale_stereo_dropped = 0
        self.stream_restarts = 0

    def update_stereo(self, msg: quest_pb2.QuestStereoFrame) -> bool:
        """更新 stereo 最新帧；同一 Unity 会话内 frame_id 倒退或重复时丢弃。

        Unity 重新进入 Play Mode/重新启动应用后，frame_id 会从 1 重新开始。
        因此不能只看 frame_id 单调性；必须结合 header.session_id 判断是否是新发布会话。
        如果新帧来自新的 session，则清空旧 latest stereo，并允许 frame_id 从小值重新开始。
        """

        frame_id = self._extract_frame_id(msg)
        session_id = self._extract_session_id(msg)
        client_id = self._extract_client_id(msg)
        same_session = not session_id or not self.latest_stereo_session_id or session_id == self.latest_stereo_session_id

        if same_session and frame_id is not None and self.latest_stereo_frame_id is not None and frame_id <= self.latest_stereo_frame_id:
            self.stale_stereo_dropped += 1
            return False

        if not same_session:
            self.stream_restarts += 1
            self.latest_stereo = None
            self.latest_stereo_frame_id = None
            self.latest_stereo_rx_mono_ms = None

        self.latest_stereo = msg
        self.latest_stereo_frame_id = frame_id
        self.latest_stereo_session_id = session_id or self.latest_stereo_session_id
        self.latest_session_id = self.latest_stereo_session_id or self.latest_camera_info_session_id
        self.latest_client_id = client_id or self.latest_client_id
        self.latest_stereo_rx_mono_ms = time.perf_counter() * 1000.0
        self.decoded_stereo += 1
        return True

    def update_camera_info(self, msg: quest_pb2.QuestCameraInfo) -> None:
        """更新 camera_info 最新值，并递增独立版本号。"""

        self.latest_camera_info = msg
        self.latest_camera_info_frame_id = self._extract_frame_id(msg)
        self.latest_camera_info_session_id = self._extract_session_id(msg) or self.latest_camera_info_session_id
        self.latest_session_id = self.latest_stereo_session_id or self.latest_camera_info_session_id
        self.latest_client_id = self._extract_client_id(msg) or self.latest_client_id
        self.latest_camera_info_rx_mono_ms = time.perf_counter() * 1000.0
        self.decoded_camera_info += 1
        self.camera_info_version += 1

    def mark_decode_failed(self) -> None:
        """记录一次 Protobuf 解码失败。"""

        self.decode_failed += 1

    def snapshot_stats(self, *, received: int, invalid_multipart: int, zmq_errors: int) -> QuestInputStats:
        """生成对外展示的输入统计快照。"""

        now_ms = time.perf_counter() * 1000.0
        return QuestInputStats(
            received=received,
            decoded_stereo=self.decoded_stereo,
            decoded_camera_info=self.decoded_camera_info,
            decode_failed=self.decode_failed,
            invalid_multipart=invalid_multipart,
            zmq_errors=zmq_errors,
            stale_stereo_dropped=self.stale_stereo_dropped,
            stream_restarts=self.stream_restarts,
            camera_info_version=self.camera_info_version,
            latest_stereo_frame_id=self.latest_stereo_frame_id,
            latest_camera_info_frame_id=self.latest_camera_info_frame_id,
            latest_session_id=self.latest_session_id,
            latest_client_id=self.latest_client_id,
            latest_stereo_age_ms=(now_ms - self.latest_stereo_rx_mono_ms if self.latest_stereo_rx_mono_ms is not None else None),
            latest_camera_info_age_ms=(
                now_ms - self.latest_camera_info_rx_mono_ms if self.latest_camera_info_rx_mono_ms is not None else None
            ),
        )

    @staticmethod
    def _extract_frame_id(msg: quest_pb2.QuestStereoFrame | quest_pb2.QuestCameraInfo) -> int | None:
        """从 Protobuf header 中提取 frame_id；缺失时返回 None。"""

        if not msg.HasField("header"):
            return None
        return int(msg.header.frame_id)

    @staticmethod
    def _extract_session_id(msg: quest_pb2.QuestStereoFrame | quest_pb2.QuestCameraInfo) -> str:
        """从 Protobuf header 中提取 Unity 发布会话 ID；缺失时返回空字符串。"""

        if not msg.HasField("header"):
            return ""
        return str(getattr(msg.header, "session_id", ""))

    @staticmethod
    def _extract_client_id(msg: quest_pb2.QuestStereoFrame | quest_pb2.QuestCameraInfo) -> str:
        """从 Protobuf header 中提取客户端 ID；缺失时返回空字符串。"""

        if not msg.HasField("header"):
            return ""
        return str(getattr(msg.header, "client_id", ""))