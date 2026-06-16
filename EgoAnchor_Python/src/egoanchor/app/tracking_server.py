"""Python pose debug 应用入口。"""

from __future__ import annotations

import argparse
import time

import cv2

from egoanchor.config import load_config
from egoanchor.diagnostics import make_pose_waiting_image, make_score_debug_view, tile_pose_depth_dashboard
from egoanchor.protocol import SubjectRegistry
from egoanchor.runtime import TrackingRuntime
from egoanchor.utils import configure_logging, get_logger

LOGGER = get_logger(__name__, component="TrackingServer")
"""Python pose debug 应用日志记录器。"""


def _handle_key(runtime: TrackingRuntime, key: int) -> bool:
    """处理 OpenCV 键盘输入；返回 False 表示退出主循环。"""

    if key in (ord("q"), ord("Q"), 27):
        return False
    if key in (ord("1"), ord("2"), ord("3"), ord("4")):
        stage = key - ord("0")
        runtime.set_stage(stage)
        LOGGER.info("切换 pose debug stage=%d", stage)
    elif key in (ord("r"), ord("R")):
        runtime.reset_tracking_state()
    return True


def should_show_waiting_frame(has_debug_frame: bool) -> bool:
    """判断 idle tick 是否应显示等待画面。

    已经显示过真实 dashboard 后，不再用 waiting 图覆盖窗口，避免异步 SAM3 等待
    阶段在 dashboard 与 waiting 之间来回闪烁。
    """

    return not bool(has_debug_frame)


def _create_fixed_window(name: str, width: int, height: int) -> None:
    """创建可调整大小的 OpenCV 窗口，并设置初始尺寸。"""

    cv2.namedWindow(name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(name, max(int(width), 1), max(int(height), 1))


def _destroy_window_if_created(name: str, created: bool) -> None:
    """仅销毁已经创建过的 OpenCV 窗口，避免启动失败时掩盖真实异常。"""

    if not created:
        return
    try:
        cv2.destroyWindow(name)
    except cv2.error as exc:
        LOGGER.debug("OpenCV 窗口销毁失败，忽略清理异常: window=%s error=%s", name, exc)


def run_tracking_server(config_path: str | None = None, object_name: str | None = None) -> None:
    """运行 Python-only pose estimation debug server。"""

    cfg = load_config(config_path, object_name=object_name)
    subjects = SubjectRegistry.load(cfg.paths.subjects_path)
    pose_cfg = cfg.demo.pose
    depth_cfg = cfg.pipeline.depth
    show_tracking_window = bool(getattr(getattr(cfg, "debug", object()), "enable_tracking_window", True))

    runtime = TrackingRuntime(cfg, subjects)
    debug_window = str(pose_cfg.debug_window_name)
    score_window = str(getattr(pose_cfg, "score_window_name", "EgoAnchor Score Debug"))
    waiting = make_pose_waiting_image(int(pose_cfg.debug_window_width), int(pose_cfg.debug_window_height), "EgoAnchor Pose Debug") if show_tracking_window else None
    last_wait_log_time = 0.0
    has_debug_frame = False
    debug_window_created = False
    score_window_created = False

    try:
        LOGGER.info("正在启动 pose debug runtime；首次加载模型可能需要较长时间。")
        runtime.start()
        if show_tracking_window:
            _create_fixed_window(debug_window, int(pose_cfg.debug_window_width), int(pose_cfg.debug_window_height))
            debug_window_created = True
            _create_fixed_window(score_window, int(getattr(pose_cfg, "score_window_width", 960)), int(getattr(pose_cfg, "score_window_height", 800)))
            score_window_created = True
            cv2.imshow(debug_window, waiting)
            LOGGER.info("listening on %s. Keys: 1/2/3/4 stage, r reset, q/ESC quit.", runtime.endpoint)
        else:
            LOGGER.info("listening on %s. OpenCV debug windows are disabled.", runtime.endpoint)

        while True:
            if show_tracking_window:
                key = cv2.waitKey(1) & 0xFF
                if key != 255 and not _handle_key(runtime, key):
                    break

            result = runtime.tick(return_debug=show_tracking_window)
            output = result.pipeline_output
            if output is None or not result.new_frame_processed:
                now = time.perf_counter()
                if now - last_wait_log_time >= float(pose_cfg.wait_log_interval_s):
                    stats = runtime.get_stats()
                    publish_stats = runtime.get_pose_publish_stats()
                    LOGGER.info(
                        "waiting/idle received=%d stereo=%d camera_info=%d decode_failed=%d latest_frame=%s pose_pub=%s/%s failed=%s",
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
                if show_tracking_window and waiting is not None and should_show_waiting_frame(has_debug_frame):
                    cv2.imshow(debug_window, waiting)
                continue

            if not show_tracking_window:
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
            score_debug = make_score_debug_view(
                output.diagnostics,
                output.observation,
                width=int(getattr(pose_cfg, "score_window_width", 960)),
                height=int(getattr(pose_cfg, "score_window_height", 800)),
                min_depth=float(depth_cfg.min_depth),
                max_depth=float(depth_cfg.max_depth),
            )
            cv2.imshow(score_window, score_debug)
            has_debug_frame = True
    finally:
        runtime.close()
        _destroy_window_if_created(debug_window, debug_window_created)
        _destroy_window_if_created(score_window, score_window_created)


def main() -> None:
    """解析命令行并启动 pose debug。"""

    parser = argparse.ArgumentParser(description="EgoAnchor Python-only pose estimation debug server")
    parser.add_argument("--config", default=None, help="可选 TOML 配置路径；默认使用包内 defaults.toml")
    parser.add_argument("--object", dest="object_name", default=None, help="目标物体名；来自 src/egoanchor/config/objects.toml")
    parser.add_argument("--log", default="INFO", help="日志级别，例如 DEBUG/INFO/WARNING")
    parser.add_argument("--log-color", choices=("auto", "always", "never"), default="auto", help="console 日志颜色：auto/always/never")
    args = parser.parse_args()

    configure_logging(args.log, force=True, color=args.log_color)
    run_tracking_server(args.config, args.object_name)
