"""YOLOE-26 实时掩码验证应用。"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import cv2

from egoanchor.algorithms import Yoloe26Segmenter
from egoanchor.config import load_config
from egoanchor.diagnostics import make_waiting_image, overlay_mask_contour, stack_stereo
from egoanchor.perception import decode_quest_stereo_frame
from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO, SubjectRegistry
from egoanchor.runtime import QuestStreamReceiver


def _resolve_path(path_value: str | Path, python_root: Path) -> Path:
    """把配置中的相对路径解析到 `EgoAnchor_Python` 根目录。"""

    raw = Path(path_value).expanduser()
    return raw.resolve() if raw.is_absolute() else (python_root / raw).resolve()


def _normalize_device(device: str) -> str | int | None:
    """把配置/命令行中的设备字符串转换成 YOLOE 适配器可接受的值。"""

    value = str(device).strip().lower()
    if value in {"", "auto", "none"}:
        return None
    if value.isdigit():
        return int(value)
    return value


def _parse_args() -> argparse.Namespace:
    """解析 YOLOE 掩码探针命令行参数。"""

    parser = argparse.ArgumentParser(description="EgoAnchor YOLOE-26 实时掩码验证工具")
    parser.add_argument("--config", default=None, help="可选 TOML 配置路径；默认使用包内 defaults.toml")
    parser.add_argument("--object", dest="object_name", default=None, help="目标物体名；来自 src/egoanchor/config/objects.toml")
    parser.add_argument("--log", default="INFO", help="日志级别，例如 DEBUG/INFO/WARNING")
    parser.add_argument("--prompt", default=None, help="覆盖配置中的 YOLOE 文本提示词，例如 'white mouse'")
    parser.add_argument("--conf", type=float, default=None, help="覆盖 YOLOE 置信度阈值")
    parser.add_argument("--max-det", type=int, default=None, help="覆盖最大检测数量")
    parser.add_argument("--mask-threshold", type=float, default=None, help="覆盖 mask 二值化阈值")
    parser.add_argument("--device", default=None, help="覆盖推理设备：auto、cpu、cuda 或 GPU 序号")
    parser.add_argument("--save-dir", default=None, help="可选调试输出目录；按 s 保存当前 overlay/mask/stereo")
    return parser.parse_args()


def _build_segmenter(cfg: object, args: argparse.Namespace) -> Yoloe26Segmenter:
    """按 配置和命令行覆盖项创建 YOLOE-26 分割器。"""

    python_root = Path(cfg.paths.python_root)
    segmenter_cfg = cfg.module.segmenter
    yolo_cfg = cfg.module.yoloe
    prompt = str(args.prompt if args.prompt is not None else segmenter_cfg.prompt)
    conf = float(args.conf if args.conf is not None else segmenter_cfg.confidence_threshold)
    max_det = int(args.max_det if args.max_det is not None else segmenter_cfg.max_det)
    mask_threshold = float(args.mask_threshold if args.mask_threshold is not None else segmenter_cfg.mask_threshold)
    device_value = _normalize_device(str(args.device if args.device is not None else yolo_cfg.device))
    return Yoloe26Segmenter(
        model_path=_resolve_path(str(yolo_cfg.model_path), python_root),
        init_prompt=prompt,
        conf=conf,
        imgsz=int(yolo_cfg.imgsz),
        max_det=max_det,
        mask_threshold=mask_threshold,
        use_half=bool(yolo_cfg.use_half),
        device=device_value,
        mobileclip2_path=_resolve_path(str(yolo_cfg.mobileclip2_path), python_root),
    )


def _make_mask_view(mask_bw: object, width: int, height: int) -> object:
    """把单通道 mask 转成便于横向拼接显示的 BGR 图。"""

    mask_bgr = cv2.cvtColor(mask_bw, cv2.COLOR_GRAY2BGR)
    return cv2.resize(mask_bgr, (max(width, 1), max(height, 1)), interpolation=cv2.INTER_NEAREST)


def _create_keep_ratio_window(name: str, width: int, height: int) -> None:
    """创建初始尺寸固定、缩放时保持图像宽高比的 OpenCV 窗口。"""

    keep_ratio_flag = getattr(cv2, "WINDOW_KEEPRATIO", 0)
    cv2.namedWindow(name, cv2.WINDOW_NORMAL | keep_ratio_flag)
    cv2.resizeWindow(name, max(int(width), 1), max(int(height), 1))


def _fit_to_window(image: object, width: int, height: int) -> object:
    """把图像等比缩放到窗口画布内，剩余区域用黑边填充。"""

    target_width = max(int(width), 1)
    target_height = max(int(height), 1)
    src_height, src_width = image.shape[:2]
    if src_width <= 0 or src_height <= 0:
        return image

    scale = min(target_width / src_width, target_height / src_height)
    view_width = max(1, int(round(src_width * scale)))
    view_height = max(1, int(round(src_height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    fitted = cv2.resize(image, (view_width, view_height), interpolation=interpolation)

    pad_left = max(0, (target_width - view_width) // 2)
    pad_right = max(0, target_width - view_width - pad_left)
    pad_top = max(0, (target_height - view_height) // 2)
    pad_bottom = max(0, target_height - view_height - pad_top)
    return cv2.copyMakeBorder(
        fitted,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )


def _save_snapshot(save_dir: Path, frame_id: int, overlay: object, mask_bw: object, stereo_view: object) -> None:
    """保存当前帧的 overlay、mask 和 stereo 预览，便于离线检查提示词质量。"""

    save_dir.mkdir(parents=True, exist_ok=True)
    prefix = save_dir / f"yoloe_frame_{frame_id}"
    cv2.imwrite(str(prefix.with_name(prefix.name + "_overlay.png")), overlay)
    cv2.imwrite(str(prefix.with_name(prefix.name + "_mask.png")), mask_bw)
    cv2.imwrite(str(prefix.with_name(prefix.name + "_stereo.png")), stereo_view)
    logging.info("已保存 YOLOE 掩码快照: %s_*", prefix)


def run_yoloe_mask_probe(config_path: str | None = None, args: argparse.Namespace | None = None, object_name: str | None = None) -> None:
    """接收 Quest stereo，实时运行 YOLOE-26 并显示 mask/overlay。"""

    cfg = load_config(config_path, object_name=object_name)
    args = args or argparse.Namespace(prompt=None, conf=None, max_det=None, mask_threshold=None, device=None, save_dir=None)
    subjects = SubjectRegistry.load(cfg.paths.subjects_path)
    for name in (QUEST_STEREO, QUEST_CAMERA_INFO):
        spec = subjects.require(name)
        if spec.transport != "zmq":
            raise ValueError(f"subject={name} 必须属于 ZMQ 数据面，实际 transport={spec.transport!r}")

    data_cfg = cfg.network.data_plane
    pose_cfg = cfg.demo.pose
    receiver = QuestStreamReceiver(
        listen_host=str(data_cfg.listen_host),
        listen_port=int(data_cfg.listen_port),
        hwm=int(data_cfg.receive_hwm),
        topics=[QUEST_STEREO, QUEST_CAMERA_INFO],
    )
    logging.info("正在加载 YOLOE-26；首次设置文本 prompt 可能需要较长时间。")
    segmenter = _build_segmenter(cfg, args)

    window_name = "EgoAnchor YOLOE Mask Probe"
    window_width = int(pose_cfg.debug_window_width)
    window_height = int(pose_cfg.debug_window_height)
    waiting_image = make_waiting_image(window_width, window_height, "Waiting for Quest stereo frames...")
    save_dir = Path(args.save_dir).expanduser().resolve() if args.save_dir else None
    displayed_frames = 0
    last_stats_time = time.perf_counter()
    last_wait_log_time = 0.0
    last_frame_id: int | None = None
    latest_overlay = None
    latest_mask = None
    latest_stereo = None
    latest_frame_id = -1

    try:
        receiver.start()
        _create_keep_ratio_window(window_name, window_width, window_height)
        cv2.imshow(window_name, waiting_image)
        logging.info("[YOLOEMaskProbe] listening on %s. Keys: s save, q/ESC quit.", receiver.endpoint)

        while True:
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (ord("s"), ord("S")) and save_dir is not None and latest_overlay is not None:
                _save_snapshot(save_dir, latest_frame_id, latest_overlay, latest_mask, latest_stereo)

            receiver.poll_latest(timeout_ms=int(data_cfg.poll_timeout_ms))
            stats = receiver.get_stats()
            stereo_msg = receiver.get_latest_stereo()
            if stereo_msg is None:
                now = time.perf_counter()
                if now - last_wait_log_time >= float(pose_cfg.wait_log_interval_s):
                    logging.info(
                        "[YOLOEMaskProbe] waiting received=%d stereo=%d camera_info=%d decode_failed=%d",
                        stats.received,
                        stats.decoded_stereo,
                        stats.decoded_camera_info,
                        stats.decode_failed,
                    )
                    last_wait_log_time = now
                cv2.imshow(window_name, waiting_image)
                continue

            decoded = decode_quest_stereo_frame(stereo_msg)
            if decoded is None or decoded.frame_id == last_frame_id:
                continue
            last_frame_id = decoded.frame_id
            result = segmenter.infer(decoded.left_bgr)
            overlay = result.overlay_bgr.copy()
            contour = overlay_mask_contour(overlay, result.mask_bw, color=(0, 255, 255))
            mask_view = _make_mask_view(result.mask_bw, contour.shape[1], contour.shape[0])
            stereo_view = stack_stereo(decoded.left_bgr, decoded.right_bgr)
            dashboard = cv2.vconcat([contour, mask_view])
            if dashboard.shape[1] != stereo_view.shape[1]:
                target_width = dashboard.shape[1]
                target_height = max(1, int(stereo_view.shape[0] * target_width / max(stereo_view.shape[1], 1)))
                stereo_view = cv2.resize(stereo_view, (target_width, target_height), interpolation=cv2.INTER_AREA)
            dashboard = cv2.vconcat([dashboard, stereo_view])
            dashboard = _fit_to_window(dashboard, window_width, window_height)
            cv2.putText(
                dashboard,
                f"frame={decoded.frame_id} det={result.det_count} idx={result.selected_index} mask={result.mask_area_ratio:.3f} infer={result.infer_ms:.1f}ms prompt={','.join(result.prompt)}",
                (16, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(window_name, dashboard)

            latest_overlay = overlay
            latest_mask = result.mask_bw
            latest_stereo = stereo_view
            latest_frame_id = int(decoded.frame_id or -1)
            displayed_frames += 1
            if displayed_frames % 30 == 0:
                now = time.perf_counter()
                fps = 30.0 / max(now - last_stats_time, 1e-6)
                logging.info(
                    "[YOLOEMaskProbe] frame=%s fps=%.1f det=%d selected=%d mask=%.3f infer=%.1fms",
                    decoded.frame_id,
                    fps,
                    result.det_count,
                    result.selected_index,
                    result.mask_area_ratio,
                    result.infer_ms,
                )
                last_stats_time = now
    finally:
        receiver.close()
        cv2.destroyWindow(window_name)


def main() -> None:
    """解析参数并启动 YOLOE 掩码探针。"""

    args = _parse_args()
    logging.basicConfig(level=getattr(logging, str(args.log).upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    run_yoloe_mask_probe(args.config, args, args.object_name)

