"""可直接运行的 v2 PoseResult NATS console demo wrapper。

推荐运行方式（在 EgoAnchor_Python 目录）：
	pixi run python ./src_v2/pose_result_console_demo.py --enabled

该 demo 只验证 NATS + Protobuf PoseResult 控制面；正式 frame-aligned anchor
显示仍应运行 tracking_server.py 并接收真实 Quest stereo/camera_info。
"""

from __future__ import annotations

from egoanchor.app import pose_result_console_demo_main as main


if __name__ == "__main__":
	main()
