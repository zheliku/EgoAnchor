"""6D object pose 估计算法接口。"""

from __future__ import annotations

from typing import Protocol

import numpy as np


class ObjectPoseEstimator(Protocol):
    """FoundationPose 等 6D pose 估计器的统一协议。"""

    def register(self, rgb: np.ndarray, depth: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """使用 RGB-D 与目标 mask 完成初始注册，返回 object-in-camera 4x4 pose。"""

    def track(self, rgb: np.ndarray, depth: np.ndarray) -> np.ndarray:
        """使用上一帧状态跟踪当前帧，返回 object-in-camera 4x4 pose。"""

    def visualize_pose(self, rgb: np.ndarray, pose: np.ndarray, axis_scale: float = 0.1, thickness: int = 3) -> np.ndarray:
        """在 RGB 图上绘制 3D 包围盒/坐标轴，返回 RGB 可视化图。"""

    def adjust_pose_to_image_point(self, x: float, y: float) -> None:
        """可选：用 2D 点修正上一帧 pose 的图像平面平移。"""

    def reset(self) -> None:
        """重置内部跟踪状态，使下次输出重新从 register 开始。"""
