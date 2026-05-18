"""Quest -> Python v2 pose debug demo。

运行方式（在 EgoAnchor_Python 目录）：
    pixi run python -m egoanchor.app.quest_pose_debug_demo

本 demo 的验证范围：
1. ZMQ/Protobuf 接收 Unity v2 Quest stereo + camera_info。
2. 在 Python 本地执行 YOLOE-26 mask、Fast-FoundationStereo depth、FoundationPose pose。
3. OpenCV 实时显示 stereo、mask/depth/pose debug 界面。
4. 不通过 NATS/ZMQ 向 Unity 发送 PoseResult，避免与后续 Anchor Runtime 设计混淆。

热键：
- 1/2/3/4：切换执行阶段。
- r：重置 FoundationPose/Cutie 跟踪状态。
- q 或 ESC：退出。
"""

from __future__ import annotations

import argparse
import logging
import time

import cv2

from egoanchor.config import load_config
from egoanchor.diagnostics import create_fixed_window, make_waiting_image
from egoanchor.perception import build_quest_pose_pipeline
from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO
from egoanchor.transport import ZmqDataPlaneReceiver


def run_demo(config_path: str | None = None) -> None:
    """启动 Python 本地 pose debug demo。"""

    cfg = load_config(config_path)
    data_cfg = cfg.network.data_plane
    pose_cfg = cfg.demo.pose

    receiver = ZmqDataPlaneReceiver(
        listen_host=data_cfg.listen_host,
        listen_port=data_cfg.listen_port,
        hwm=data_cfg.receive_hwm,
        topics=[QUEST_STEREO, QUEST_CAMERA_INFO],
    )
    pipeline = build_quest_pose_pipeline(cfg)

    debug_window = str(pose_cfg.debug_window_name)
    stereo_window = str(pose_cfg.stereo_window_name)
    waiting = make_waiting_image(message="Waiting for Quest stereo + camera_info for pose debug...")
    last_wait_log_time = 0.0
    last_pose_log_frame_id: int | None = None

    try:
        receiver.start()
        create_fixed_window(debug_window, int(pose_cfg.debug_window_width), int(pose_cfg.debug_window_height))
        create_fixed_window(stereo_window, int(pose_cfg.stereo_window_width), int(pose_cfg.stereo_window_height))
        cv2.imshow(debug_window, waiting)
        cv2.imshow(stereo_window, waiting)
        logging.info(
            "[QuestPoseDebugDemo] Listening on %s. Keys: 1/2/3/4 stage, r reset, q/ESC quit.",
            receiver.endpoint,
        )

        while True:
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key in (ord("1"), ord("2"), ord("3"), ord("4")):
                pipeline.set_stage(int(chr(key)))
                logging.info("[QuestPoseDebugDemo] switch stage -> %d", pipeline.stage)
            elif key == ord("r"):
                pipeline.reset_tracking_state()
                logging.info("[QuestPoseDebugDemo] reset tracking state")

            receiver.poll_latest(timeout_ms=int(data_cfg.poll_timeout_ms))
            output = pipeline.process(
                stereo_msg=receiver.get_latest_stereo(),
                camera_info_msg=receiver.get_latest_camera_info(),
                return_debug=True,
            )

            if output is None:
                now = time.perf_counter()
                if now - last_wait_log_time >= float(pose_cfg.wait_log_interval_s):
                    stats = receiver.get_stats()
                    logging.info(
                        "[QuestPoseDebugDemo] Waiting... received=%d stereo=%d camera_info=%d failed=%d latest_frame_id=%s",
                        stats.received,
                        stats.decoded_stereo,
                        stats.decoded_camera_info,
                        stats.decode_failed,
                        stats.latest_stereo_frame_id,
                    )
                    last_wait_log_time = now
                cv2.imshow(debug_window, waiting)
                cv2.imshow(stereo_window, waiting)
                continue

            if output.debug is not None:
                dashboard_bgr, stereo_bgr = output.debug
                cv2.imshow(debug_window, dashboard_bgr)
                cv2.imshow(stereo_window, stereo_bgr)

            obs = output.observation
            if obs.has_pose and obs.frame_id != last_pose_log_frame_id and obs.pose_matrix_cv_camera is not None:
                t = obs.pose_matrix_cv_camera
                logging.debug(
                    "[QuestPoseDebugDemo] pose frame_id=%s phase=%s xyz=(%.4f, %.4f, %.4f) rel=%.2f",
                    obs.frame_id,
                    obs.phase,
                    t[3],
                    t[7],
                    t[11],
                    obs.reliability_score,
                )
                last_pose_log_frame_id = obs.frame_id
    finally:
        receiver.close()
        cv2.destroyWindow(debug_window)
        cv2.destroyWindow(stereo_window)


def main() -> None:
    parser = argparse.ArgumentParser(description="EgoAnchor v2 Quest pose debug demo（Python local only）")
    parser.add_argument("--config", default=None, help="可选 v2 TOML 配置路径；默认使用 src_v2/egoanchor/config/defaults.toml")
    parser.add_argument("--log", default="INFO", help="日志级别，例如 DEBUG/INFO/WARNING")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log).upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    run_demo(args.config)


if __name__ == "__main__":
    main()
