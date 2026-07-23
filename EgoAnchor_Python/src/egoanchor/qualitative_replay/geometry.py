"""Unity world pose、OpenCV camera pose 与投影矩阵转换。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

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


def projection_mesh_local_matrix(variants: Sequence[Mapping[str, Any]]) -> np.ndarray:
    """从 runtime 指纹恢复离线投影 mesh 的局部基变换。

    Unity 最终显示 pose 已包含 ``anchor-pos`` 和 ``anchor-rot``，而离线加载的是
    FoundationPose 使用的 OpenCV mesh。要用最终显示根节点重建 Unity 中真正看到的
    几何，必须先撤销这段对象局部补偿，并在记录的轴翻转基下表达结果。
    """

    transforms = tuple(_projection_mesh_local_matrix(variant) for variant in variants)
    if not transforms:
        raise ValueError("replay 样本不含可解析的 runtime 配置指纹。")
    first = transforms[0]
    if any(not np.allclose(first, item, atol=1e-9, rtol=0.0) for item in transforms[1:]):
        raise ValueError("四种方法的 mesh 局部坐标补偿不一致，不能共用同一投影 mesh。")
    return first


def _projection_mesh_local_matrix(variant: Mapping[str, Any]) -> np.ndarray:
    """解析单个 runtime 指纹并构造 ``F @ B^-1 @ F``。"""

    fingerprint = str(variant.get("runtime_configuration_fingerprint", ""))
    fields = {
        key: value
        for part in fingerprint.split("|")
        if ":" in part
        for key, value in (part.split(":", 1),)
    }
    flip = _parse_fingerprint_bool3(fields.get("flip"), "flip")
    anchor_position = _parse_fingerprint_float3(fields.get("anchor-pos"), "anchor-pos")
    anchor_rotation = _parse_fingerprint_float3(fields.get("anchor-rot"), "anchor-rot")

    signs = np.array([-1.0 if value else 1.0 for value in flip], dtype=np.float64)
    basis = np.eye(4, dtype=np.float64)
    basis[:3, :3] = np.diag(signs)
    compensation = np.eye(4, dtype=np.float64)
    compensation[:3, :3] = _unity_euler_zxy(anchor_rotation)
    compensation[:3, 3] = np.asarray(anchor_position, dtype=np.float64)
    return basis @ np.linalg.inv(compensation) @ basis


def _parse_fingerprint_bool3(value: str | None, name: str) -> tuple[bool, bool, bool]:
    """解析指纹中的三个布尔值。"""

    parts = tuple(part.strip().lower() for part in (value or "").split(","))
    if len(parts) != 3 or any(part not in {"true", "false"} for part in parts):
        raise ValueError(f"runtime_configuration_fingerprint 缺少合法 {name}。")
    return tuple(part == "true" for part in parts)  # type: ignore[return-value]


def _parse_fingerprint_float3(value: str | None, name: str) -> tuple[float, float, float]:
    """解析指纹中的三个有限浮点数。"""

    try:
        parts = tuple(float(part) for part in (value or "").split(","))
    except ValueError as exc:
        raise ValueError(f"runtime_configuration_fingerprint 缺少合法 {name}。") from exc
    if len(parts) != 3 or not np.all(np.isfinite(parts)):
        raise ValueError(f"runtime_configuration_fingerprint 缺少合法 {name}。")
    return parts  # type: ignore[return-value]


def _unity_euler_zxy(euler_deg: tuple[float, float, float]) -> np.ndarray:
    """按 Unity Quaternion.Euler 的 Z-X-Y 顺序构造三维旋转矩阵。"""

    x, y, z = np.radians(np.asarray(euler_deg, dtype=np.float64))
    cx, sx = np.cos(x), np.sin(x)
    cy, sy = np.cos(y), np.sin(y)
    cz, sz = np.cos(z), np.sin(z)
    rotation_x = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    rotation_y = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    rotation_z = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
    return rotation_y @ rotation_x @ rotation_z


__all__ = [
    "UNITY_TO_CV_BASIS",
    "display_world_to_cv_camera",
    "pose_to_matrix",
    "projection_mesh_local_matrix",
    "recorded_projection_matrix",
    "verify_projection_matrix",
]
