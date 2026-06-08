"""调试工具共用的 RealSense RGBD 输入封装。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import cv2
import numpy as np


@dataclass(frozen=True)
class RGBDFrame:
    """对齐到彩色图坐标系的 RealSense RGBD 帧。"""

    color_bgr: np.ndarray
    """BGR 彩色图，uint8。"""

    depth: np.ndarray
    """RealSense 原始 z16 深度图，uint16。"""

    timestamp_ms: float
    """彩色帧时间戳，单位毫秒。"""


class RealSenseCamera:
    """RealSense RGBD 彩色流最小封装。"""

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        serial_number: str | None = None,
    ) -> None:
        """保存采集参数，并在实例化阶段检查 pyrealsense2 是否可用。"""

        try:
            import pyrealsense2 as rs_module
        except Exception as exc:
            raise RuntimeError("未检测到 pyrealsense2，请确认 pixi 环境和 RealSense SDK。") from exc

        self.rs = cast(Any, rs_module)
        """pyrealsense2 模块对象。"""

        self.width = int(width)
        """彩色和深度采集宽度。"""

        self.height = int(height)
        """彩色和深度采集高度。"""

        self.fps = int(fps)
        """采集帧率。"""

        self.serial_number = serial_number
        """可选 RealSense 设备序列号。"""

        self.pipeline: Any = None
        """RealSense pipeline 对象。"""

        self.config: Any = None
        """RealSense config 对象。"""

        self._align_to_color: Any = None
        """depth 到 color 的对齐器。"""

        self._started = False
        """相机是否已启动。"""

    def start(self) -> None:
        """启动 color 和 depth 流，并创建 depth->color 对齐器。"""

        if self._started:
            return

        self.pipeline = self.rs.pipeline()
        self.config = self.rs.config()
        if self.serial_number:
            self.config.enable_device(self.serial_number)

        self.config.enable_stream(self.rs.stream.color, self.width, self.height, self.rs.format.bgr8, self.fps)
        self.config.enable_stream(self.rs.stream.depth, self.width, self.height, self.rs.format.z16, self.fps)
        self.pipeline.start(self.config)
        self._align_to_color = self.rs.align(self.rs.stream.color)
        self._started = True

    def stop(self) -> None:
        """停止相机采集；可重复调用。"""

        if not self._started:
            return
        if self.pipeline is not None:
            self.pipeline.stop()
        self.pipeline = None
        self.config = None
        self._align_to_color = None
        self._started = False

    def get_aligned_rgbd_frames(self) -> RGBDFrame:
        """读取一帧 depth 对齐到 color 坐标系的 RGBD 图像。"""

        if not self._started or self.pipeline is None or self._align_to_color is None:
            raise RuntimeError("RealSenseCamera 尚未启动，请先调用 start()。")

        frames = self.pipeline.wait_for_frames()
        aligned_frames = self._align_to_color.process(frames)
        color_frame = aligned_frames.get_color_frame()
        depth_frame = aligned_frames.get_depth_frame()
        if not color_frame or not depth_frame:
            raise RuntimeError("未获取到有效的对齐 RGBD 帧。")

        return RGBDFrame(
            color_bgr=np.asanyarray(color_frame.get_data()),
            depth=np.asanyarray(depth_frame.get_data()),
            timestamp_ms=float(color_frame.get_timestamp()),
        )

    def __enter__(self) -> "RealSenseCamera":
        """进入上下文时启动相机。"""

        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """离开上下文时释放相机。"""

        self.stop()


def show_depth_window(depth: np.ndarray) -> None:
    """把 z16 深度图转为伪彩色窗口，仅用于辅助观察。"""

    depth_u8 = cv2.convertScaleAbs(depth, alpha=0.03)
    depth_color = cv2.applyColorMap(depth_u8, cv2.COLORMAP_JET)
    cv2.imshow("RealSense Depth (Aligned)", depth_color)
