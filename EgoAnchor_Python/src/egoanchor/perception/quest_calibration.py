"""Quest stereo camera_info 到算法内参的映射。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from egoanchor.protocol import quest_pb2


@dataclass(frozen=True, slots=True)
class QuestStereoCalibration:
    """Quest 双目标定在算法处理分辨率下的表示。"""

    left_fx: float
    """左目 fx。"""

    left_fy: float
    """左目 fy。"""

    left_cx: float
    """左目 cx。"""

    left_cy: float
    """左目 cy。"""

    baseline_m: float
    """双目基线，单位米。"""

    calib_width: int
    """内参所在标定坐标系宽度，优先使用 active array。"""

    calib_height: int
    """内参所在标定坐标系高度，优先使用 active array。"""

    assume_center_crop: bool
    """是否按 active array 中心裁剪到当前图像后再缩放 K。"""

    frame_id: int | None = None
    """最近一次 camera_info 对应的 frame_id。"""

    @classmethod
    def from_proto(cls, msg: quest_pb2.QuestCameraInfo, assume_center_crop: bool = True) -> "QuestStereoCalibration":
        """从 QuestCameraInfo 构造双目标定。"""

        header = msg.header if msg.HasField("header") else None
        calib_w = int(msg.active_right) - int(msg.active_left)
        calib_h = int(msg.active_bottom) - int(msg.active_top)
        if calib_w <= 0 or calib_h <= 0:
            calib_w = int(msg.sensor_width) or int(msg.current_width) or int(msg.left_requested_width)
            calib_h = int(msg.sensor_height) or int(msg.current_height) or int(msg.left_requested_height)
        if calib_w <= 0 or calib_h <= 0:
            raise ValueError("QuestCameraInfo 缺少有效的标定图像尺寸。")
        return cls(
            left_fx=float(msg.left_fx),
            left_fy=float(msg.left_fy),
            left_cx=float(msg.left_cx),
            left_cy=float(msg.left_cy),
            baseline_m=float(msg.baseline_m),
            calib_width=calib_w,
            calib_height=calib_h,
            assume_center_crop=bool(assume_center_crop),
            frame_id=int(header.frame_id) if header is not None else None,
        )

    def signature(self) -> tuple[float, ...]:
        """生成轻量签名，用于判断标定是否变化。"""

        return (
            round(self.left_fx, 4),
            round(self.left_fy, 4),
            round(self.left_cx, 4),
            round(self.left_cy, 4),
            round(self.baseline_m, 8),
            float(self.calib_width),
            float(self.calib_height),
            float(int(self.assume_center_crop)),
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

    def scaled_k(self, target_width: int, target_height: int) -> np.ndarray:
        """把左目内参映射到算法处理分辨率。"""

        if target_width <= 0 or target_height <= 0:
            target_width = self.calib_width
            target_height = self.calib_height

        if self.assume_center_crop:
            crop_x, crop_y, sx, sy = self._compute_center_crop_mapping(target_width, target_height)
            cx = (self.left_cx - crop_x) * sx
            cy = (self.left_cy - crop_y) * sy
        else:
            sx = float(target_width) / float(max(self.calib_width, 1))
            sy = float(target_height) / float(max(self.calib_height, 1))
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
