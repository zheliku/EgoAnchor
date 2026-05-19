"""Unity <-> Python v2 anchor 链路 smoke test。

用途：
- 不加载 YOLOE/FFS/FoundationPose；
- Python 通过 ZMQ 接收 Unity `QuestStreamPublisher` 的 stereo/camera_info；
- 每收到新的 stereo frame_id，就通过 NATS 发布一个 identity fake `PoseResult`；
- Unity `PoseResultReceiver + PoseToAnchorRuntime` 若能用同 frame_id 命中 `FramePoseHistory`，即可验证基础 anchor 同步链路。

注意：该入口只验证通信、frame_id 透传和 frame-aligned anchor runtime；正式 tracking 仍使用
`src_v2/tracking_server.py`。
"""

from __future__ import annotations

import argparse
import logging
import math
import time

from egoanchor.config import load_config
from egoanchor.perception import PoseObservation
from egoanchor.runtime import QuestStreamReceiver, pose_result_from_observation
from egoanchor.transport import PoseResultPublisher


def _make_pose_matrix(t: float, z_m: float) -> tuple[float, ...]:
    """生成 OpenCV camera 坐标下的轻微摆动 fake pose。"""

    x_m = 0.06 * math.sin(t)
    y_m = 0.02 * math.cos(t * 0.7)
    return (
        1.0, 0.0, 0.0, x_m,
        0.0, 1.0, 0.0, y_m,
        0.0, 0.0, 1.0, z_m,
        0.0, 0.0, 0.0, 1.0,
    )


def run_smoke(config_path: str | None = None, *, z_m: float = 0.6) -> None:
    """启动基础 anchor 链路 smoke test。"""

    cfg = load_config(config_path)
    data_cfg = cfg.network.data_plane
    receiver = QuestStreamReceiver(
        listen_host=data_cfg.listen_host,
        listen_port=data_cfg.listen_port,
        hwm=data_cfg.receive_hwm,
    )
    publisher = PoseResultPublisher.from_config(cfg)
    last_published_frame_id: int | None = None
    last_log = 0.0
    seq = 0

    try:
        receiver.start()
        publisher.start()
        logging.info(
            "[AnchorLinkSmoke] listening=%s nats_enabled=%s subject=%s",
            receiver.endpoint,
            publisher.enabled,
            publisher.subject,
        )
        while True:
            receiver.poll_latest(timeout_ms=int(data_cfg.poll_timeout_ms))
            stereo = receiver.get_latest_stereo()
            if stereo is not None and stereo.HasField("header"):
                frame_id = int(stereo.header.frame_id)
                if frame_id != last_published_frame_id:
                    seq += 1
                    observation = PoseObservation(
                        has_pose=True,
                        phase="SMOKE_FAKE_POSE",
                        frame_id=frame_id,
                        pose_matrix_cv_camera=_make_pose_matrix(seq * 0.05, z_m),
                        stage=4,
                        det_count=1,
                        depth_valid_ratio=1.0,
                        depth_valid_in_mask=1.0,
                        fps=0.0,
                        reliability_score=1.0,
                    )
                    publisher.publish_pose_result(pose_result_from_observation(observation))
                    last_published_frame_id = frame_id

            now = time.perf_counter()
            if now - last_log >= 2.0:
                stats = receiver.get_stats()
                logging.info(
                    "[AnchorLinkSmoke] received=%d stereo=%d camera_info=%d failed=%d latest_frame_id=%s published=%d publish_failed=%d",
                    stats.received,
                    stats.decoded_stereo,
                    stats.decoded_camera_info,
                    stats.decode_failed,
                    stats.latest_stereo_frame_id,
                    publisher.published_count,
                    publisher.failed_count,
                )
                last_log = now
    except KeyboardInterrupt:
        logging.info("[AnchorLinkSmoke] interrupted")
    finally:
        publisher.close()
        receiver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="EgoAnchor v2 Unity/Python anchor link smoke test")
    parser.add_argument("--config", default=None, help="可选 v2 TOML 配置路径")
    parser.add_argument("--z", type=float, default=0.6, help="fake pose 在 OpenCV camera z 方向的距离，单位米")
    parser.add_argument("--log", default="INFO", help="日志级别，例如 DEBUG/INFO/WARNING")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, str(args.log).upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    run_smoke(args.config, z_m=args.z)


if __name__ == "__main__":
    main()