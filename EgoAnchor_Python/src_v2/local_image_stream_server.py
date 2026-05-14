from __future__ import annotations

"""v2 本地图片流 smoke server。

用途：先不接 Quest，也不接 tracking pipeline，只验证 Unity 能把本地 Texture2D
编码为 `QuestStereoFrame` protobuf，并通过 NATS 发到 Python。Python 收到后解码
JPEG，并用 OpenCV 显示左右图。

运行：
    python ./src_v2/local_image_stream_server.py --log-level INFO

退出：OpenCV 窗口按 q / ESC，或 Ctrl+C。
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

SRC_V2_DIR = Path(__file__).resolve().parents[1]
if str(SRC_V2_DIR) not in sys.path:
    sys.path.append(str(SRC_V2_DIR))

from egoanchor.protocol.v1.quest_pb2 import QuestStereoFrame  # noqa: E402
from egoanchor.transport import NatsClient  # noqa: E402

LOGGER = logging.getLogger(__name__)


def _decode_jpeg(payload: bytes) -> np.ndarray | None:
    """把 JPEG bytes 解码成 OpenCV BGR 图像。"""
    if not payload:
        return None
    arr = np.frombuffer(payload, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _make_dashboard(left: np.ndarray, right: np.ndarray, frame_id: int, fps: float) -> np.ndarray:
    """拼接左右图并绘制简单 HUD。"""
    if left.shape[:2] != right.shape[:2]:
        right = cv2.resize(right, (left.shape[1], left.shape[0]), interpolation=cv2.INTER_AREA)
    vis = np.hstack((left, right))
    cv2.putText(
        vis,
        f"v2 local image stream frame={frame_id} fps={fps:.1f}",
        (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return vis


async def run_server(nats_url: str, subject: str) -> None:
    """订阅本地图片流并显示。"""
    client = NatsClient(url=nats_url, name="egoanchor-python-v2-local-image")
    await client.connect()

    latest_payload: bytes | None = None
    received_count = 0
    displayed_count = 0
    overwritten_count = 0
    stats_t = time.perf_counter()
    receive_fps = 0.0
    display_fps = 0.0

    async def on_message(_subject: str, payload: bytes, _reply: str | None) -> None:
        nonlocal latest_payload, received_count, overwritten_count
        if latest_payload is not None:
            overwritten_count += 1
        latest_payload = payload
        received_count += 1
        if LOGGER.isEnabledFor(logging.DEBUG):
            msg = QuestStereoFrame()
            msg.ParseFromString(payload)
            LOGGER.debug(
                "[local-image] received frame_id=%s left=%dB right=%dB",
                msg.header.frame_id,
                len(msg.left_image_jpeg),
                len(msg.right_image_jpeg),
            )
        return None

    await client.subscribe(subject, on_message)
    LOGGER.info("[local-image] listening nats=%s subject=%s", nats_url, subject)

    try:
        while True:
            if latest_payload is not None:
                payload = latest_payload
                latest_payload = None
                msg = QuestStereoFrame()
                msg.ParseFromString(payload)
                left = _decode_jpeg(bytes(msg.left_image_jpeg))
                right = _decode_jpeg(bytes(msg.right_image_jpeg))
                if left is not None and right is not None:
                    displayed_count += 1
                    now = time.perf_counter()
                    elapsed = now - stats_t
                    if elapsed >= 1.0:
                        receive_fps = received_count / elapsed
                        display_fps = displayed_count / elapsed
                        received_count = 0
                        displayed_count = 0
                        overwritten = overwritten_count
                        overwritten_count = 0
                        stats_t = now
                        LOGGER.info(
                            "[local-image] frame_id=%s size=%sx%s recv_fps=%.1f display_fps=%.1f overwritten=%d",
                            msg.header.frame_id,
                            left.shape[1],
                            left.shape[0],
                            receive_fps,
                            display_fps,
                            overwritten,
                        )
                    cv2.imshow("EgoAnchor v2 Local Image Stream", _make_dashboard(left, right, msg.header.frame_id, display_fps))

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            await asyncio.sleep(0.001)
    finally:
        await client.close()
        cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description="EgoAnchor v2 local image stream viewer")
    parser.add_argument("--nats", default="nats://127.0.0.1:4222")
    parser.add_argument("--subject", default="egoanchor.v1.quest.stereo")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    )
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    asyncio.run(run_server(args.nats, args.subject))


if __name__ == "__main__":
    main()
