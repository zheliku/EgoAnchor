"""Unity world pose、OpenCV camera pose 与投影矩阵转换。"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np


UNITY_TO_CV_BASIS = np.diag([1.0, -1.0, 1.0, 1.0]).astype(np.float64)
"""当前 runtime 使用的 x/right、y/up->down、z/forward 基变换。"""


def pose_to_matrix(pose: Mapping[str, Any]) -> np.ndarray:
    """把 JSON position + quaternion xyzw 转成 4x4 齐次矩阵。"""

    position = np.asarray(pose["position"], dtype=np.float64).reshape(3)
    quaternion = np.asarray(pose["rotation_xyzw"], dtype=np.float64).reshape(4)
    norm = float(np.linalg.norm(quaternion))
    if not np.isfinite(norm) or norm <= 1e-12:
        raise ValueError("pose quaternion 必须是非零有限值。")
    x, y, z, w = quaternion / norm
    rotation = np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = position
    return matrix


def display_world_to_cv_camera(
    camera_world_pose: Mapping[str, Any],
    display_world_pose: Mapping[str, Any],
) -> np.ndarray:
    """把最终显示 world pose 重表达为 OpenCV object-in-left-camera pose。

    最终显示 pose 已包含 Unity runtime 的 camera/anchor/world 补偿。这里的目标是重建
    用户实际看到的模型位置，因此不能把这些补偿逆掉；只做 camera-relative 变换和
    ``F @ T @ F`` 坐标基转换。
    """

    camera_to_world = pose_to_matrix(camera_world_pose)
    object_to_world = pose_to_matrix(display_world_pose)
    object_in_unity_camera = np.linalg.inv(camera_to_world) @ object_to_world
    return UNITY_TO_CV_BASIS @ object_in_unity_camera @ UNITY_TO_CV_BASIS


def recorded_projection_matrix(variant: Mapping[str, Any]) -> np.ndarray:
    """读取 Unity 已记录的 row-major OpenCV projection pose。"""

    values = np.asarray(variant["projection_pose_cv_camera"], dtype=np.float64)
    if values.size != 16 or not np.all(np.isfinite(values)):
        raise ValueError("projection_pose_cv_camera 必须包含 16 个有限数。")
    return values.reshape(4, 4)


def verify_projection_matrix(
    camera_world_pose: Mapping[str, Any],
    variant: Mapping[str, Any],
    *,
    tolerance: float = 2e-4,
) -> float:
    """用 world pose 重算矩阵，并返回与 Unity 记录矩阵的最大绝对误差。"""

    if variant.get("has_display_pose") is not True:
        raise ValueError("无 display pose 的 variant 不能验证 projection matrix。")
    expected = display_world_to_cv_camera(camera_world_pose, variant["display_world_pose"])
    recorded = recorded_projection_matrix(variant)
    error = float(np.max(np.abs(expected - recorded)))
    if error > float(tolerance):
        raise ValueError(f"Unity/Python projection matrix 不一致: max_abs_error={error:.6g}")
    return error


__all__ = [
    "UNITY_TO_CV_BASIS",
    "display_world_to_cv_camera",
    "pose_to_matrix",
    "recorded_projection_matrix",
    "verify_projection_matrix",
]
