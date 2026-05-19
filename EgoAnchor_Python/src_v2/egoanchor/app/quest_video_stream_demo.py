"""Quest -> Python v2 实时视频流通信 demo。

运行方式（在 EgoAnchor_Python 目录）：
    pixi run python -m egoanchor.app.quest_video_stream_demo

本脚本验证范围：
1. Python 绑定 ZMQ SUB 数据面端口 15557。
2. 接收 Unity v2 发布的 Protobuf multipart：[topic_utf8, payload_bytes]。
3. 按 topic latest-drain，分别保留 stereo 与 camera_info 最新消息。
4. 解码 QuestStereoFrame 中的左右 JPEG，并用 OpenCV 实时显示。

本脚本不做的事情：
- 不启动 YOLOE/FFS/FoundationPose。
- 不发布 pose。
- 不接 NATS 控制面。
这些能力后续由 tracking_server.py + TrackingRuntime 逐步接入。
"""

from __future__ import annotations

import argparse
import logging
import time

import cv2
import numpy as np

from egoanchor.config import load_config
from egoanchor.diagnostics import create_fixed_window
from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO
from egoanchor.protocol import quest_pb2
from egoanchor.runtime import QuestStreamReceiver


def _decode_jpeg(data: bytes) -> np.ndarray | None:
    """把 JPEG bytes 解码为 OpenCV BGR 图像。"""

    if not data:
        return None
    encoded = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    return image


def _make_waiting_image(width: int = 960, height: int = 360) -> np.ndarray:
    """生成等待画面，避免无输入时 OpenCV 窗口看起来像卡死。"""

    image = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(
        image,
        "Waiting for EgoAnchor v2 Quest stereo frames...",
        (24, height // 2 - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (220, 220, 220),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        image,
        "Unity topic: egoanchor.v1.quest.stereo, transport: ZMQ + Protobuf",
        (24, height // 2 + 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (160, 220, 255),
        1,
        cv2.LINE_AA,
    )
    return image


def _stack_stereo(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """把左右图等高拼接，便于肉眼确认双目流是否实时更新。"""

    if left.shape[0] != right.shape[0]:
        target_height = min(left.shape[0], right.shape[0])
        left = cv2.resize(
            left,
            (max(1, int(left.shape[1] * target_height / left.shape[0])), target_height),
            interpolation=cv2.INTER_LINEAR,
        )
        right = cv2.resize(
            right,
            (max(1, int(right.shape[1] * target_height / right.shape[0])), target_height),
            interpolation=cv2.INTER_LINEAR,
        )
    return np.hstack((left, right))


def _print_camera_info_once(msg: quest_pb2.QuestCameraInfo | None) -> bool:
    """首次收到 camera_info 时打印关键标定字段。"""

    if msg is None:
        return False
    header = msg.header if msg.HasField("header") else None
    frame_id = header.frame_id if header is not None else -1
    logging.info(
        "[QuestVideoDemo] CameraInfo frame_id=%s supported=%s fx=%.1f fy=%.1f cx=%.1f cy=%.1f "
        "baseline=%.6fm sensor=%dx%d current=%dx%d max_fps=%d",
        frame_id,
        msg.is_supported,
        msg.left_fx,
        msg.left_fy,
        msg.left_cx,
        msg.left_cy,
        msg.baseline_m,
        msg.sensor_width,
        msg.sensor_height,
        msg.current_width,
        msg.current_height,
        msg.max_framerate,
    )
    return True


def run_demo(config_path: str | None = None) -> None:
    """启动实时视频流 demo 主循环。"""

    cfg = load_config(config_path)
    data_cfg = cfg.network.data_plane
    video_cfg = cfg.demo.video

    receiver = QuestStreamReceiver(
        listen_host=data_cfg.listen_host,
        listen_port=data_cfg.listen_port,
        hwm=data_cfg.receive_hwm,
        topics=[QUEST_STEREO, QUEST_CAMERA_INFO],
    )

    window_name = str(video_cfg.window_name)
    waiting_image = _make_waiting_image()
    frame_count = 0
    last_stats_frame = 0
    last_stats_time = time.perf_counter()
    last_wait_log_time = 0.0
    camera_info_printed = False
    last_displayed_frame_id: int | None = None

    try:
        receiver.start()
        create_fixed_window(
            window_name,
            int(video_cfg.stereo_window_width),
            int(video_cfg.stereo_window_height),
        )
        cv2.imshow(window_name, waiting_image)
        logging.info(
            "[QuestVideoDemo] Listening on %s. Press q or ESC in OpenCV window to exit.",
            receiver.endpoint,
        )

        while True:
            # 先处理窗口事件；没有网络数据时也能响应退出键。
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break

            receiver.poll_latest(timeout_ms=int(data_cfg.poll_timeout_ms))

            if not camera_info_printed:
                camera_info_printed = _print_camera_info_once(receiver.get_latest_camera_info())

            stereo = receiver.get_latest_stereo()
            if stereo is None:
                now = time.perf_counter()
                if now - last_wait_log_time >= float(video_cfg.wait_log_interval_s):
                    stats = receiver.get_stats()
                    logging.info(
                        "[QuestVideoDemo] Waiting for stereo... received=%d decoded_stereo=%d "
                        "decoded_camera_info=%d failed=%d",
                        stats.received,
                        stats.decoded_stereo,
                        stats.decoded_camera_info,
                        stats.decode_failed,
                    )
                    last_wait_log_time = now
                cv2.imshow(window_name, waiting_image)
                continue

            header = stereo.header if stereo.HasField("header") else None
            frame_id = int(header.frame_id) if header is not None else -1
            # latest store 可能在无新帧时返回上一帧；避免重复 JPEG 解码和重复计数。
            if last_displayed_frame_id == frame_id:
                continue

            left = _decode_jpeg(bytes(stereo.left_image_jpeg))
            right = _decode_jpeg(bytes(stereo.right_image_jpeg))
            if left is None or right is None:
                logging.warning(
                    "[QuestVideoDemo] JPEG decode failed frame_id=%s left_bytes=%d right_bytes=%d",
                    frame_id,
                    len(stereo.left_image_jpeg),
                    len(stereo.right_image_jpeg),
                )
                continue

            view = _stack_stereo(left, right)
            cv2.putText(
                view,
                f"frame_id={frame_id} size=L{left.shape[1]}x{left.shape[0]} R{right.shape[1]}x{right.shape[0]}",
                (16, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(window_name, view)
            last_displayed_frame_id = frame_id
            frame_count += 1

            if frame_count - last_stats_frame >= int(video_cfg.stats_interval_frames):
                now = time.perf_counter()
                fps = (frame_count - last_stats_frame) / max(now - last_stats_time, 1e-6)
                stats = receiver.get_stats()
                logging.info(
                    "[QuestVideoDemo] displayed=%d fps=%.1f received=%d decoded_stereo=%d "
                    "decoded_camera_info=%d failed=%d latest_frame_id=%s stereo_age_ms=%.1f",
                    frame_count,
                    fps,
                    stats.received,
                    stats.decoded_stereo,
                    stats.decoded_camera_info,
                    stats.decode_failed,
                    stats.latest_stereo_frame_id,
                    stats.latest_stereo_age_ms or 0.0,
                )
                last_stats_frame = frame_count
                last_stats_time = now
    finally:
        receiver.close()
        cv2.destroyWindow(window_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="EgoAnchor v2 Quest -> Python 实时视频流 demo")
    parser.add_argument("--config", default=None, help="可选 v2 TOML 配置路径；默认使用内置 defaults.toml")
    parser.add_argument("--log", default="INFO", help="日志级别，例如 DEBUG/INFO/WARNING")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log).upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    run_demo(args.config)


if __name__ == "__main__":
    main()
