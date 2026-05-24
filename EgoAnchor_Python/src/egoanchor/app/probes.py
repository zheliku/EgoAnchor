"""通信探针。

本模块实现首个最小通信 demo：
- Python 绑定 ZMQ SUB 数据面端口；
- 接收 Unity 发送的 multipart `[topic_utf8, protobuf_bytes]`；
- 按 topic 做 latest-only 缓存；
- 解码 `QuestStereoFrame` 中的左右 JPEG，并用 OpenCV 实时显示。

本模块不加载模型、不发布 pose、不接 NATS。这样可以先验证数据面通信质量，
避免被后续 GPU/算法依赖掩盖网络和协议问题。
"""

from __future__ import annotations

import argparse
import logging
import time

import cv2

from egoanchor.config import load_config
from egoanchor.diagnostics import create_fixed_window, decode_jpeg, draw_stereo_hud, make_waiting_image, stack_stereo
from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO, SubjectRegistry, quest_pb2
from egoanchor.runtime import QuestStreamReceiver


def _validate_data_plane_subjects(subjects: SubjectRegistry) -> None:
    """校验本 demo 需要的 ZMQ topic 确实来自共享 subject 契约。"""

    for name in (QUEST_STEREO, QUEST_CAMERA_INFO):
        spec = subjects.require(name)
        if spec.transport != "zmq":
            raise ValueError(f"subject={name} 必须属于 ZMQ 数据面，实际 transport={spec.transport!r}")


def _log_camera_info(info: quest_pb2.QuestCameraInfo, version: int) -> None:
    """打印 camera_info 的关键字段，便于确认标定是否已经到达 Python。"""

    header = info.header if info.HasField("header") else None
    frame_id = int(header.frame_id) if header is not None else -1
    logging.info(
        "[QuestVideoProbe] camera_info version=%d frame_id=%s supported=%s "
        "fx=%.1f fy=%.1f cx=%.1f cy=%.1f baseline=%.6fm sensor=%dx%d current=%dx%d max_fps=%d",
        version,
        frame_id,
        info.is_supported,
        info.left_fx,
        info.left_fy,
        info.left_cx,
        info.left_cy,
        info.baseline_m,
        info.sensor_width,
        info.sensor_height,
        info.current_width,
        info.current_height,
        info.max_framerate,
    )


def run_quest_video_probe(config_path: str | None = None) -> None:
    """运行 Quest -> Python 实时视频流通信 demo。"""

    cfg = load_config(config_path)
    subjects = SubjectRegistry.load(cfg.paths.subjects_path)
    _validate_data_plane_subjects(subjects)

    data_cfg = cfg.network.data_plane
    video_cfg = cfg.demo.video
    receiver = QuestStreamReceiver(
        listen_host=str(data_cfg.listen_host),
        listen_port=int(data_cfg.listen_port),
        hwm=int(data_cfg.receive_hwm),
        topics=[QUEST_STEREO, QUEST_CAMERA_INFO],
    )

    window_name = str(video_cfg.window_name)
    waiting_image = make_waiting_image(
        width=int(video_cfg.stereo_window_width),
        height=int(video_cfg.stereo_window_height),
        title="Waiting for EgoAnchor Quest stereo frames...",
    )
    displayed_frames = 0
    last_stats_frame = 0
    last_stats_time = time.perf_counter()
    last_wait_log_time = 0.0
    last_displayed_frame_id: int | None = None
    last_camera_info_version = 0

    try:
        receiver.start()
        create_fixed_window(window_name, int(video_cfg.stereo_window_width), int(video_cfg.stereo_window_height))
        cv2.imshow(window_name, waiting_image)
        logging.info(
            "[QuestVideoProbe] listening on %s topics=%s. Press q or ESC to exit.",
            receiver.endpoint,
            (QUEST_STEREO, QUEST_CAMERA_INFO),
        )

        while True:
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break

            receiver.poll_latest(timeout_ms=int(data_cfg.poll_timeout_ms))
            stats = receiver.get_stats()

            camera_info = receiver.get_latest_camera_info()
            if camera_info is not None and stats.camera_info_version != last_camera_info_version:
                last_camera_info_version = stats.camera_info_version
                _log_camera_info(camera_info, last_camera_info_version)

            stereo = receiver.get_latest_stereo()
            if stereo is None:
                now = time.perf_counter()
                if now - last_wait_log_time >= float(video_cfg.wait_log_interval_s):
                    logging.info(
                        "[QuestVideoProbe] waiting for stereo... received=%d stereo=%d camera_info=%d "
                        "decode_failed=%d invalid_multipart=%d",
                        stats.received,
                        stats.decoded_stereo,
                        stats.decoded_camera_info,
                        stats.decode_failed,
                        stats.invalid_multipart,
                    )
                    last_wait_log_time = now
                cv2.imshow(window_name, waiting_image)
                continue

            header = stereo.header if stereo.HasField("header") else None
            frame_id = int(header.frame_id) if header is not None else -1
            if frame_id == last_displayed_frame_id:
                continue

            left = decode_jpeg(bytes(stereo.left_image_jpeg))
            right = decode_jpeg(bytes(stereo.right_image_jpeg))
            if left is None or right is None:
                logging.warning(
                    "[QuestVideoProbe] JPEG decode failed frame_id=%s left_bytes=%d right_bytes=%d",
                    frame_id,
                    len(stereo.left_image_jpeg),
                    len(stereo.right_image_jpeg),
                )
                continue

            view = stack_stereo(left, right)
            draw_stereo_hud(
                view,
                frame_id=frame_id,
                left_shape=left.shape,
                right_shape=right.shape,
                camera_info_version=stats.camera_info_version,
                stereo_age_ms=stats.latest_stereo_age_ms,
            )
            cv2.imshow(window_name, view)

            displayed_frames += 1
            last_displayed_frame_id = frame_id
            if displayed_frames - last_stats_frame >= int(video_cfg.stats_interval_frames):
                now = time.perf_counter()
                fps = (displayed_frames - last_stats_frame) / max(now - last_stats_time, 1e-6)
                logging.info(
                    "[QuestVideoProbe] displayed=%d fps=%.1f received=%d stereo=%d camera_info=%d "
                    "stale=%d decode_failed=%d latest_frame_id=%s stereo_age_ms=%.1f",
                    displayed_frames,
                    fps,
                    stats.received,
                    stats.decoded_stereo,
                    stats.decoded_camera_info,
                    stats.stale_stereo_dropped,
                    stats.decode_failed,
                    stats.latest_stereo_frame_id,
                    stats.latest_stereo_age_ms or 0.0,
                )
                last_stats_frame = displayed_frames
                last_stats_time = now
    finally:
        receiver.close()
        cv2.destroyWindow(window_name)


def main() -> None:
    """解析命令行参数并启动通信探针。"""

    parser = argparse.ArgumentParser(description="EgoAnchor Quest -> Python 实时图像通信 demo")
    parser.add_argument("--config", default=None, help="可选 TOML 配置路径；默认使用包内 defaults.toml")
    parser.add_argument("--log", default="INFO", help="日志级别，例如 DEBUG/INFO/WARNING")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    run_quest_video_probe(args.config)
