"""v2 本机假 Quest 视频流发送脚本。

用途：
- 在没有 Quest/Unity 的情况下，测试 Python 端 ZMQ/Protobuf 接收与 OpenCV 预览。
- 它发送的 topic、payload 类型和 multipart 格式与 Unity v2 完全一致。

使用方法（打开两个终端，均在 EgoAnchor_Python 目录）：
1. 接收端：pixi run python -m egoanchor.app.quest_video_stream_demo
2. 发送端：pixi run python -m egoanchor.tests.send_fake_quest_stream

注意：
- Python demo 接收端是 SUB bind tcp://*:15557。
- 本脚本是 PUB connect tcp://127.0.0.1:15557。
- 如果接收端窗口能看到左右动态图和递增 frame_id，就说明 v2 数据面基础链路可用。
"""

from __future__ import annotations

import argparse
import math
import time
import uuid

import cv2
import numpy as np
import zmq

from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO
from egoanchor.protocol.v1 import common_pb2, quest_pb2


def _make_image(frame_id: int, side: str, width: int, height: int) -> np.ndarray:
    """生成一张带运动图案的 BGR 测试图。"""

    image = np.zeros((height, width, 3), dtype=np.uint8)
    color = (80, 180, 255) if side == "left" else (255, 180, 80)
    x = int((math.sin(frame_id * 0.08) * 0.5 + 0.5) * (width - 80)) + 40
    y = int((math.cos(frame_id * 0.05) * 0.5 + 0.5) * (height - 80)) + 40
    cv2.circle(image, (x, y), 36, color, -1, cv2.LINE_AA)
    cv2.putText(
        image,
        f"FAKE {side.upper()} frame={frame_id}",
        (24, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return image


def _encode_jpeg(image: np.ndarray, quality: int) -> bytes:
    """把 OpenCV BGR 图编码成 JPEG bytes。"""

    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    return encoded.tobytes()


def _make_header(frame_id: int) -> common_pb2.MessageHeader:
    """构造 v2 MessageHeader。"""

    return common_pb2.MessageHeader(
        message_id=uuid.uuid4().hex,
        frame_id=frame_id,
        unity_frame=frame_id,
        sender_mono_ms=time.perf_counter() * 1000.0,
        created_unix_ms=time.time() * 1000.0,
        schema_version="v1",
    )


def run_sender(endpoint: str, fps: float, width: int, height: int, quality: int) -> None:
    """启动假视频流发送循环。"""

    ctx = zmq.Context.instance()
    socket = ctx.socket(zmq.PUB)
    socket.setsockopt(zmq.SNDHWM, 5)
    socket.connect(endpoint)
    print(f"[FakeQuestStream] connected to {endpoint}")

    frame_id = 0
    interval = 1.0 / max(float(fps), 0.1)
    last_camera_info_time = 0.0
    try:
        # PUB/SUB 有订阅传播延迟；启动后稍等可以减少前几帧丢失造成的误判。
        time.sleep(0.5)
        while True:
            frame_id += 1
            start = time.perf_counter()

            left = _make_image(frame_id, "left", width, height)
            right = _make_image(frame_id, "right", width, height)
            stereo = quest_pb2.QuestStereoFrame(
                header=_make_header(frame_id),
                left_image_jpeg=_encode_jpeg(left, quality),
                right_image_jpeg=_encode_jpeg(right, quality),
                left_width=width,
                left_height=height,
                right_width=width,
                right_height=height,
                jpeg_quality=quality,
            )
            socket.send_multipart([QUEST_STEREO.encode("utf-8"), stereo.SerializeToString()])

            now = time.perf_counter()
            if now - last_camera_info_time >= 1.0:
                camera_info = quest_pb2.QuestCameraInfo(
                    header=_make_header(0),
                    is_supported=True,
                    left_fx=600.0,
                    left_fy=600.0,
                    left_cx=width / 2.0,
                    left_cy=height / 2.0,
                    right_fx=600.0,
                    right_fy=600.0,
                    right_cx=width / 2.0,
                    right_cy=height / 2.0,
                    baseline_m=0.064,
                    sensor_width=width,
                    sensor_height=height,
                    active_left=0,
                    active_top=0,
                    active_right=width,
                    active_bottom=height,
                    left_requested_width=width,
                    left_requested_height=height,
                    right_requested_width=width,
                    right_requested_height=height,
                    current_width=width,
                    current_height=height,
                    max_framerate=int(fps),
                )
                socket.send_multipart([QUEST_CAMERA_INFO.encode("utf-8"), camera_info.SerializeToString()])
                last_camera_info_time = now

            if frame_id % 60 == 0:
                print(f"[FakeQuestStream] sent frame_id={frame_id}")

            elapsed = time.perf_counter() - start
            time.sleep(max(0.0, interval - elapsed))
    except KeyboardInterrupt:
        print("[FakeQuestStream] interrupted")
    finally:
        socket.close(linger=0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send fake v2 Quest stereo stream for local testing")
    parser.add_argument("--endpoint", default="tcp://127.0.0.1:15557", help="Python receiver endpoint")
    parser.add_argument("--fps", type=float, default=30.0, help="发送帧率")
    parser.add_argument("--width", type=int, default=640, help="单目图像宽度")
    parser.add_argument("--height", type=int, default=480, help="单目图像高度")
    parser.add_argument("--quality", type=int, default=85, help="JPEG 质量")
    args = parser.parse_args()
    run_sender(args.endpoint, args.fps, args.width, args.height, args.quality)


if __name__ == "__main__":
    main()
