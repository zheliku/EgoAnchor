"""v3 Python pose debug 应用入口。"""

from __future__ import annotations

import argparse
import logging
import time

import cv2

from egoanchor.config import load_config
from egoanchor.diagnostics import create_fixed_window, make_pose_waiting_image, stack_pose_stereo, tile_pose_depth_dashboard
from egoanchor.protocol import SubjectRegistry
from egoanchor.runtime import TrackingRuntime


def _handle_key(runtime: TrackingRuntime, key: int) -> bool:
    """处理 OpenCV 键盘输入；返回 False 表示退出主循环。"""

    if key in (ord("q"), ord("Q"), 27):
        return False
    if key in (ord("1"), ord("2"), ord("3"), ord("4")):
        stage = key - ord("0")
        runtime.set_stage(stage)
        logging.info("切换 pose debug stage=%d", stage)
    elif key in (ord("r"), ord("R")):
        runtime.reset_tracking_state()
    return True


def run_tracking_server(config_path: str | None = None) -> None:
    """运行 Python-only pose estimation debug server。"""

    cfg = load_config(config_path)
    subjects = SubjectRegistry.load(cfg.paths.subjects_path)
    pose_cfg = cfg.demo.pose
    depth_cfg = cfg.pipeline.depth

    runtime = TrackingRuntime(cfg, subjects)
    debug_window = str(pose_cfg.debug_window_name)
    stereo_window = str(pose_cfg.stereo_window_name)
    waiting = make_pose_waiting_image(int(pose_cfg.debug_window_width), int(pose_cfg.debug_window_height), "EgoAnchor v3 Pose Debug")
    last_wait_log_time = 0.0

    try:
        logging.info("正在启动 v3 pose debug runtime；首次加载模型可能需要较长时间。")
        runtime.start()
        create_fixed_window(debug_window, int(pose_cfg.debug_window_width), int(pose_cfg.debug_window_height))
        create_fixed_window(stereo_window, int(pose_cfg.stereo_window_width), int(pose_cfg.stereo_window_height))
        cv2.imshow(debug_window, waiting)
        logging.info("[TrackingServer:v3] listening on %s. Keys: 1/2/3/4 stage, r reset, q/ESC quit.", runtime.endpoint)

        while True:
            key = cv2.waitKey(1) & 0xFF
            if key != 255 and not _handle_key(runtime, key):
                break

            result = runtime.tick(return_debug=True)
            output = result.pipeline_output
            if output is None or not result.new_frame_processed:
                now = time.perf_counter()
                if now - last_wait_log_time >= float(pose_cfg.wait_log_interval_s):
                    stats = runtime.get_stats()
                    publish_stats = runtime.get_pose_publish_stats()
                    logging.info(
                        "[TrackingServer:v3] waiting/idle received=%d stereo=%d camera_info=%d decode_failed=%d latest_frame=%s pose_pub=%s/%s failed=%s",
                        stats.received,
                        stats.decoded_stereo,
                        stats.decoded_camera_info,
                        stats.decode_failed,
                        stats.latest_stereo_frame_id,
                        publish_stats.get("submitted", 0),
                        publish_stats.get("attempts", 0),
                        publish_stats.get("failed", 0),
                    )
                    last_wait_log_time = now
                cv2.imshow(debug_window, waiting)
                continue

            dashboard = tile_pose_depth_dashboard(
                output.diagnostics,
                output.observation,
                width=int(pose_cfg.debug_window_width),
                height=int(pose_cfg.debug_window_height),
                min_depth=float(depth_cfg.min_depth),
                max_depth=float(depth_cfg.max_depth),
            )
            cv2.imshow(debug_window, dashboard)

            stereo = stack_pose_stereo(output.diagnostics.left_bgr, output.diagnostics.right_bgr)
            cv2.imshow(stereo_window, stereo)
    finally:
        runtime.close()
        cv2.destroyWindow(debug_window)
        cv2.destroyWindow(stereo_window)


def main() -> None:
    """解析命令行并启动 v3 pose debug。"""

    parser = argparse.ArgumentParser(description="EgoAnchor v3 Python-only pose estimation debug server")
    parser.add_argument("--config", default=None, help="可选 v3 TOML 配置路径；默认使用包内 defaults.toml")
    parser.add_argument("--log", default="INFO", help="日志级别，例如 DEBUG/INFO/WARNING")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log).upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    run_tracking_server(args.config)
