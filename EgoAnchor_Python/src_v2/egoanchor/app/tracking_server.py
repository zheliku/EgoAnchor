"""EgoAnchor v2 Python 主入口。

`tracking_server.py` 是后续统一运行入口：它组合 ZMQ 数据面、perception pipeline、
NATS 控制面 PoseResult 发布，以及可选 Python 本地 OpenCV debug 窗口。

热键（启用 debug window 时）：
- 1/2/3/4：切换 perception 执行阶段；
- r：重置 FoundationPose/Cutie 跟踪状态；
- q 或 ESC：退出。

模型逻辑仍保留在 perception/algorithms 层；本入口只负责装配和运行循环。
"""

from __future__ import annotations

import argparse
import logging
import time

import cv2

from egoanchor.config import load_config
from egoanchor.diagnostics import create_fixed_window, make_waiting_image
from egoanchor.runtime import TrackingRuntime


def run_server(config_path: str | None = None, *, debug_window: bool | None = None) -> None:
    """启动 v2 runtime。

    参数：
    - config_path：可选 TOML 覆盖配置。
    - debug_window：是否显示 OpenCV 调试窗口。None 时读取配置 `debug.enable_tracking_window`，
      若配置缺失则默认开启，方便测试阶段直接按键调试。
    """

    cfg = load_config(config_path)
    pose_cfg = cfg.demo.pose
    if debug_window is None:
        debug_window = bool(getattr(cfg.debug, "enable_tracking_window", True))

    runtime = TrackingRuntime(cfg)
    debug_window_name = str(pose_cfg.debug_window_name)
    stereo_window_name = str(pose_cfg.stereo_window_name)
    waiting = make_waiting_image(message="Waiting for Quest stereo + camera_info for tracking_server...")
    last_wait_log_time = 0.0

    try:
        runtime.start()
        if debug_window:
            create_fixed_window(debug_window_name, int(pose_cfg.debug_window_width), int(pose_cfg.debug_window_height))
            create_fixed_window(stereo_window_name, int(pose_cfg.stereo_window_width), int(pose_cfg.stereo_window_height))
            cv2.imshow(debug_window_name, waiting)
            cv2.imshow(stereo_window_name, waiting)
        logging.info(
            "[TrackingServer] v2 runtime started. debug_window=%s. Keys: 1/2/3/4 stage, r reset, q/ESC quit.",
            debug_window,
        )
        while True:
            if debug_window:
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    logging.info("[TrackingServer] exit requested by key")
                    break
                if key in (ord("1"), ord("2"), ord("3"), ord("4")):
                    stage = int(chr(key))
                    runtime.set_stage(stage)
                    logging.info("[TrackingServer] switch stage -> %d", stage)
                elif key == ord("r"):
                    runtime.reset_tracking_state()
                    logging.info("[TrackingServer] reset tracking state")

            tick_result = runtime.tick(return_debug=debug_window)
            if debug_window:
                if tick_result.debug_dashboard_bgr is not None and tick_result.debug_stereo_bgr is not None:
                    cv2.imshow(debug_window_name, tick_result.debug_dashboard_bgr)
                    cv2.imshow(stereo_window_name, tick_result.debug_stereo_bgr)
                elif not tick_result.has_new_output:
                    now = time.perf_counter()
                    if now - last_wait_log_time >= float(pose_cfg.wait_log_interval_s):
                        stats = runtime.receiver.get_stats()
                        logging.info(
                            "[TrackingServer] Waiting... received=%d stereo=%d camera_info=%d failed=%d latest_frame_id=%s",
                            stats.received,
                            stats.decoded_stereo,
                            stats.decoded_camera_info,
                            stats.decode_failed,
                            stats.latest_stereo_frame_id,
                        )
                        last_wait_log_time = now
                    cv2.imshow(debug_window_name, waiting)
                    cv2.imshow(stereo_window_name, waiting)
            else:
                time.sleep(0.001)
    except KeyboardInterrupt:
        logging.info("[TrackingServer] interrupted by user")
    finally:
        runtime.stop()
        if debug_window:
            cv2.destroyWindow(debug_window_name)
            cv2.destroyWindow(stereo_window_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="EgoAnchor v2 tracking server")
    parser.add_argument("--config", default=None, help="可选 v2 TOML 配置路径")
    parser.add_argument("--log", default="INFO", help="日志级别，例如 DEBUG/INFO/WARNING")
    parser.add_argument("--debug-window", dest="debug_window", action="store_true", help="显示 OpenCV 调试窗口并启用键盘控制")
    parser.add_argument("--no-debug-window", dest="debug_window", action="store_false", help="关闭 OpenCV 调试窗口，适合无界面/后台运行")
    parser.set_defaults(debug_window=None)
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, str(args.log).upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    run_server(args.config, debug_window=args.debug_window)


if __name__ == "__main__":
    main()
