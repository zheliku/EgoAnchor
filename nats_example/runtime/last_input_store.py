from __future__ import annotations

"""
v2 latest input store。

Unity 发来的 Quest stereo/camera_info 是实时输入，不需要排队处理旧消息。
本模块按“保留最新”策略缓存输入：
- stereo：按 `header.frame_id` 去重，只接受更大的 frame_id；
- camera_info：低频静态信息，每收到一次 version + 1。

后续 `NatsQuestInput` 或 `TrackingRuntime` 会从这里读取快照，而不是让 NATS
callback 直接操作 pipeline。
"""

import time
from dataclasses import dataclass

from egoanchor.protocol.v1.quest_pb2 import QuestCameraInfo, QuestStereoFrame


@dataclass(frozen=True)
class InputState:
    """输入状态诊断快照，用于日志/heartbeat/测试。"""

    has_stereo: bool
    has_camera_info: bool
    latest_stereo_frame_id: int
    camera_info_version: int
    stereo_updates: int
    dropped_stale_stereo: int


class LatestInputStore:
    """NATS handler 与 runtime 之间的 latest-only 输入缓存。"""

    def __init__(self) -> None:
        self._latest_stereo: QuestStereoFrame | None = None
        self._latest_camera_info: QuestCameraInfo | None = None
        self._camera_info_version = 0
        self._stereo_updates = 0
        self._dropped_stale_stereo = 0
        self._updated_mono_ms = 0.0

    def put_stereo(self, message: QuestStereoFrame) -> bool:
        """写入一帧 stereo。

        返回值表示是否接受该帧；frame_id 不递增的旧帧会被拒绝并计数。
        """
        frame_id = int(message.header.frame_id)
        if self._latest_stereo is not None and frame_id <= int(self._latest_stereo.header.frame_id):
            self._dropped_stale_stereo += 1
            return False
        self._latest_stereo = message
        self._stereo_updates += 1
        self._updated_mono_ms = time.monotonic() * 1000.0
        return True

    def put_camera_info(self, message: QuestCameraInfo) -> int:
        """写入 camera_info，并返回新的版本号。"""
        self._latest_camera_info = message
        self._camera_info_version += 1
        self._updated_mono_ms = time.monotonic() * 1000.0
        return self._camera_info_version

    def get_latest_stereo(self) -> QuestStereoFrame | None:
        """读取最新 stereo protobuf；不复制，调用方不要修改 message。"""
        return self._latest_stereo

    def get_camera_info(self) -> QuestCameraInfo | None:
        """读取最新 camera_info protobuf；不复制，调用方不要修改 message。"""
        return self._latest_camera_info

    def get_camera_info_version(self) -> int:
        """返回 camera_info 更新版本号。"""
        return self._camera_info_version

    def get_input_state(self) -> InputState:
        """返回用于诊断的状态快照。"""
        latest_frame_id = int(self._latest_stereo.header.frame_id) if self._latest_stereo else 0
        return InputState(
            has_stereo=self._latest_stereo is not None,
            has_camera_info=self._latest_camera_info is not None,
            latest_stereo_frame_id=latest_frame_id,
            camera_info_version=self._camera_info_version,
            stereo_updates=self._stereo_updates,
            dropped_stale_stereo=self._dropped_stale_stereo,
        )
