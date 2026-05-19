"""EgoAnchor v2 PoseResult NATS 控制面 demo。

运行方式（在 EgoAnchor_Python 目录）：
	pixi run python ./src_v2/pose_result_console_demo.py --enabled

用途：
- 不启动 YOLOE/FFS/FoundationPose，也不依赖 Quest stereo 输入；
- 周期性向 `egoanchor.v1.pose.result` 发布 Protobuf PoseResult；
- 供 Unity 端 NatsControlClient/PoseResultReceiver 的 NATS 解码链路做 smoke test。

重要限制：
- Unity 正式 anchor 对齐必须依赖 FramePoseHistory 中真实采集帧的 camera pose；
- 本 demo 默认发布 frame_id=0，不保证能被 Unity frame-aligned runtime 应用到 Transform；
- 它只用于验证 NATS subject、Protobuf 和 Unity receiver 是否工作。
"""

from __future__ import annotations

import argparse
import logging
import math
import time
import uuid
from types import SimpleNamespace

from egoanchor.protocol import anchor_pb2, common_pb2
from egoanchor.transport import PoseResultPublisher


def _make_cfg(enabled: bool, url: str, connect_timeout_s: float, max_pending_futures: int) -> SimpleNamespace:
	"""构造 PoseResultPublisher.from_config 需要的最小配置对象。"""

	return SimpleNamespace(
		network=SimpleNamespace(
			control_plane=SimpleNamespace(
				enabled=enabled,
				url=url,
				connect_timeout_s=connect_timeout_s,
				max_pending_futures=max_pending_futures,
			)
		)
	)


def _make_pose_matrix(t: float, z_m: float) -> tuple[float, ...]:
	"""生成 row-major OpenCV camera pose 矩阵。

	这里使用单位旋转 + 轻微左右移动，方便 Unity receiver 看到 payload 变化。
	"""

	x_m = 0.08 * math.sin(t)
	y_m = 0.02 * math.cos(t * 0.7)
	return (
		1.0, 0.0, 0.0, x_m,
		0.0, 1.0, 0.0, y_m,
		0.0, 0.0, 1.0, z_m,
		0.0, 0.0, 0.0, 1.0,
	)


def _make_pose_result(frame_id: int, matrix: tuple[float, ...], fps: float) -> anchor_pb2.PoseResult:
	"""直接构造协议层 PoseResult，避免 demo 依赖 perception 数据结构。"""

	msg = anchor_pb2.PoseResult(
		header=common_pb2.MessageHeader(
			message_id=str(uuid.uuid4()),
			client_id="egoanchor-python-v2-console-demo",
			anchor_id="default",
			frame_id=int(frame_id),
			sender_mono_ms=time.perf_counter() * 1000.0,
			created_unix_ms=time.time() * 1000.0,
			schema_version="v1",
		),
		has_pose=True,
		phase="FAKE_POSE",
		stage=4,
		det_count=1,
		depth_valid_ratio=1.0,
		fps=float(fps),
	)
	msg.pose_matrix_cv_camera.values.extend(matrix)
	return msg


def run_demo(url: str, fps: float, enabled: bool, frame_id: int, z_m: float) -> None:
	"""发布假 PoseResult 到 NATS。"""

	cfg = _make_cfg(enabled=enabled, url=url, connect_timeout_s=2.0, max_pending_futures=16)
	publisher = PoseResultPublisher.from_config(cfg)
	interval = 1.0 / max(float(fps), 0.1)
	seq = 0
	try:
		publisher.start()
		logging.info(
			"[PoseResultConsoleDemo] publishing enabled=%s url=%s subject=%s frame_id=%s fps=%.1f",
			enabled,
			url,
			publisher.subject,
			frame_id,
			fps,
		)
		while True:
			start = time.perf_counter()
			seq += 1
			msg = _make_pose_result(frame_id, _make_pose_matrix(seq * 0.05, z_m), fps)
			publisher.publish_pose_result(msg)
			if seq % max(1, int(fps * 2)) == 0:
				logging.info(
					"[PoseResultConsoleDemo] sent=%d published=%d failed=%d",
					seq,
					publisher.published_count,
					publisher.failed_count,
				)
			elapsed = time.perf_counter() - start
			time.sleep(max(0.0, interval - elapsed))
	except KeyboardInterrupt:
		logging.info("[PoseResultConsoleDemo] interrupted")
	finally:
		publisher.close()


def main() -> None:
	parser = argparse.ArgumentParser(description="Publish fake EgoAnchor v2 PoseResult over NATS")
	parser.add_argument("--url", default="nats://127.0.0.1:4222", help="NATS server URL")
	parser.add_argument("--fps", type=float, default=15.0, help="发布频率")
	parser.add_argument("--frame-id", type=int, default=0, help="写入 PoseResult header.frame_id 的值")
	parser.add_argument("--z", type=float, default=0.6, help="假 pose 在 OpenCV camera z 前方的距离，单位米")
	parser.add_argument("--enabled", action="store_true", help="显式启用发布；未传时只验证 disabled no-op 路径")
	parser.add_argument("--log", default="INFO", help="日志级别，例如 DEBUG/INFO/WARNING")
	args = parser.parse_args()
	logging.basicConfig(level=getattr(logging, str(args.log).upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
	run_demo(args.url, args.fps, args.enabled, args.frame_id, args.z)


if __name__ == "__main__":
	main()
