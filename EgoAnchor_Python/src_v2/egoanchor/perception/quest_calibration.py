"""Quest v2 标定数据结构与 K 映射工具。

本文件属于 perception 层：它只描述 Quest camera_info 如何转换成算法需要的
双目标定，不包含网络接收，也不包含模型推理。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from egoanchor.protocol.v1 import quest_pb2


@dataclass(frozen=True, slots=True)
class QuestStereoCalibration:
    """Quest 双目标定的最小算法视图。

    left_fx/left_fy/left_cx/left_cy 来自左目相机内参；baseline_m 是左右目基线。
    calib_width/calib_height 表示内参所在的原始标定坐标系尺寸，优先使用
    active array 尺寸，缺失时回退到 sensor_width/sensor_height 或 current_width/current_height。
    """

    left_fx: float
    left_fy: float
    left_cx: float
    left_cy: float
    baseline_m: float
    calib_width: int
    calib_height: int

    @classmethod
    def from_proto(cls, msg: quest_pb2.QuestCameraInfo) -> "QuestStereoCalibration":
        """从 v2 Protobuf `QuestCameraInfo` 构造标定对象。"""

        width = int(msg.active_right) - int(msg.active_left)
        height = int(msg.active_bottom) - int(msg.active_top)
        if width <= 0 or height <= 0:
            width = int(msg.sensor_width) or int(msg.current_width)
            height = int(msg.sensor_height) or int(msg.current_height)
        if width <= 0 or height <= 0:
            raise ValueError("QuestCameraInfo 缺少有效的标定图像尺寸。")

        return cls(
            left_fx=float(msg.left_fx),
            left_fy=float(msg.left_fy),
            left_cx=float(msg.left_cx),
            left_cy=float(msg.left_cy),
            baseline_m=float(msg.baseline_m),
            calib_width=width,
            calib_height=height,
        )

    def signature(self) -> tuple[float, ...]:
        """生成稳定签名，用于判断网络 camera_info 是否发生变化。"""

        return (
            round(self.left_fx, 4),
            round(self.left_fy, 4),
            round(self.left_cx, 4),
            round(self.left_cy, 4),
            round(self.baseline_m, 8),
            float(self.calib_width),
            float(self.calib_height),
        )

    def _compute_center_crop_mapping(self, width: int, height: int) -> tuple[float, float, float, float]:
        """计算标定坐标系到运行分辨率的中心裁剪 + 缩放映射。"""

        src_w = float(max(self.calib_width, 1))
        src_h = float(max(self.calib_height, 1))
        dst_w = float(max(width, 1))
        dst_h = float(max(height, 1))
        src_aspect = src_w / src_h
        dst_aspect = dst_w / dst_h

        crop_x, crop_y, crop_w, crop_h = 0.0, 0.0, src_w, src_h
        if abs(src_aspect - dst_aspect) > 1e-6:
            if src_aspect > dst_aspect:
                crop_w = src_h * dst_aspect
                crop_x = (src_w - crop_w) * 0.5
            else:
                crop_h = src_w / dst_aspect
                crop_y = (src_h - crop_h) * 0.5

        sx = dst_w / max(crop_w, 1e-6)
        sy = dst_h / max(crop_h, 1e-6)
        return crop_x, crop_y, sx, sy

    def scaled_k(self, width: int, height: int, assume_center_crop: bool = True) -> np.ndarray:
        """把 Quest 标定 K 映射到算法处理分辨率。

        与旧主线保持一致：
        - assume_center_crop=True：先按目标宽高比做中心裁剪，再缩放；
        - False：只做线性缩放。
        """

        if assume_center_crop:
            crop_x, crop_y, sx, sy = self._compute_center_crop_mapping(width, height)
            cx = (self.left_cx - crop_x) * sx
            cy = (self.left_cy - crop_y) * sy
        else:
            sx = float(width) / float(max(self.calib_width, 1))
            sy = float(height) / float(max(self.calib_height, 1))
            cx = self.left_cx * sx
            cy = self.left_cy * sy

        return np.array(
            [
                [self.left_fx * sx, 0.0, cx],
                [0.0, self.left_fy * sy, cy],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
