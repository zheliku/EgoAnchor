from __future__ import annotations

"""
Quest 输入流 handler。

这些 handler 由 `NatsRouter` 在收到 Unity 发布的 protobuf 后调用。
它们只做一件事：把最新输入写入 `LatestInputStore`。

重要边界：这里不解 JPEG、不跑 pipeline、不做耗时 GPU 工作。
"""

import logging

from egoanchor.protocol.v1.quest_pb2 import QuestCameraInfo, QuestStereoFrame
from egoanchor.routing.handler_registry import HandlerContext, HandlerRegistry

LOGGER = logging.getLogger(__name__)


def register_quest_handlers(registry: HandlerRegistry) -> None:
    """向 handler registry 注册 Quest stereo/camera_info 输入处理函数。"""

    @registry.subscribe("egoanchor.v1.quest.stereo")
    def handle_stereo(ctx: HandlerContext, message: QuestStereoFrame) -> None:
        if ctx.latest_inputs is None:
            raise RuntimeError("latest input store is not configured")
        accepted = ctx.latest_inputs.put_stereo(message)
        LOGGER.debug(
            "[v2.quest] stereo frame_id=%s accepted=%s bytes=%d/%d",
            message.header.frame_id,
            accepted,
            len(message.left_image_jpeg),
            len(message.right_image_jpeg),
        )
        return None

    @registry.subscribe("egoanchor.v1.quest.camera_info")
    def handle_camera_info(ctx: HandlerContext, message: QuestCameraInfo) -> None:
        if ctx.latest_inputs is None:
            raise RuntimeError("latest input store is not configured")
        version = ctx.latest_inputs.put_camera_info(message)
        LOGGER.info(
            "[v2.quest] camera_info version=%d supported=%s fx=%.1f baseline=%.4fm",
            version,
            message.is_supported,
            message.left_fx,
            message.baseline_m,
        )
        return None
