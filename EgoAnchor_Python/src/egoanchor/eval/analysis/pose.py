"""实验一/二位姿归一化、平移误差和旋转误差原语。"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray


FloatArray = NDArray[np.float64]
"""公共位姿原语使用的双精度数组类型。"""


def _vectors(values: ArrayLike, width: int, name: str) -> FloatArray:
    """把输入转换为末维固定且全部有限的双精度向量。

    参数：
        values: 单个向量或一批向量。
        width: 末维要求的元素数量。
        name: 校验失败时使用的字段名。
    """

    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 0 or array.shape[-1] != width:
        raise ValueError(f"{name} 的末维必须是 {width}")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} 包含非有限值")
    return array


def normalize_quaternion(
    quaternion: ArrayLike,
    norm_tolerance: float = 1e-6,
) -> FloatArray:
    """归一化 xyzw 四元数，拒绝零范数和非有限输入。

    参数：
        quaternion: 形状为 ``(4,)`` 或 ``(..., 4)`` 的 xyzw 四元数。
        norm_tolerance: 判定零范数的正容差；正式分析从冻结参数对象传入。
    """

    if not np.isfinite(norm_tolerance) or norm_tolerance <= 0.0:
        raise ValueError("四元数范数容差必须是有限正数")
    values = _vectors(quaternion, 4, "quaternion")
    norms = np.linalg.norm(values, axis=-1, keepdims=True)
    if np.any(norms <= norm_tolerance):
        raise ValueError("四元数范数过小，无法归一化")
    return values / norms


def translation_error_mm(display_position: ArrayLike, reference_position: ArrayLike) -> FloatArray:
    """计算 display 与平台参考之间的三维欧氏平移误差，单位毫米。

    参数：
        display_position: 单个或成批 display 世界坐标位置，单位米。
        reference_position: 与 display 可广播对齐的平台参考位置，单位米。
    """

    display = _vectors(display_position, 3, "display_position")
    reference = _vectors(reference_position, 3, "reference_position")
    try:
        difference = display - reference
    except ValueError as error:
        raise ValueError("display 与 reference 位置形状无法广播") from error
    return np.asarray(1000.0 * np.linalg.norm(difference, axis=-1), dtype=np.float64)


def rotation_error_deg(
    display_rotation: ArrayLike,
    reference_rotation: ArrayLike,
    norm_tolerance: float = 1e-6,
) -> FloatArray:
    """计算两个 xyzw 四元数的最短弧旋转误差，单位度。

    参数：
        display_rotation: 单个或成批 display 四元数。
        reference_rotation: 与 display 可广播对齐的平台参考四元数。
        norm_tolerance: 判定零范数的正容差；正式分析从冻结参数对象传入。
    """

    display = normalize_quaternion(display_rotation, norm_tolerance)
    reference = normalize_quaternion(reference_rotation, norm_tolerance)
    try:
        dot = np.sum(display * reference, axis=-1)
    except ValueError as error:
        raise ValueError("display 与 reference 四元数形状无法广播") from error
    cosine = np.clip(np.abs(dot), 0.0, 1.0)
    return np.asarray(np.degrees(2.0 * np.arccos(cosine)), dtype=np.float64)


__all__ = ["FloatArray", "normalize_quaternion", "rotation_error_deg", "translation_error_mm"]
