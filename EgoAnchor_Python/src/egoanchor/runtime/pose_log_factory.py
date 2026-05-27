"""PoseResult 结构化日志字段构造器。"""

from __future__ import annotations

import math

from egoanchor.utils import rotation_matrix_to_quaternion


class PoseLogFactory:
    """从 PoseResult 中提取论文实验与诊断需要的 pose 字段。"""

    def __init__(self) -> None:
        """初始化上一帧 pose 缓存，用于计算相邻 jump。"""

        self.last_pose_matrix: tuple[float, ...] | None = None
        """上一条成功写入日志的 camera-space pose matrix。"""

    def build(self, msg: object) -> dict[str, float | list[float]]:
        """提取 pose 平移、旋转和相邻 jump。"""

        if not bool(getattr(msg, "has_pose", False)):
            self.last_pose_matrix = None
            return {}
        matrix = getattr(getattr(msg, "pose_matrix_cv_camera", None), "values", None)
        if matrix is None or len(matrix) != 16:
            self.last_pose_matrix = None
            return {}

        values = tuple(float(v) for v in matrix)
        tx, ty, tz = values[3], values[7], values[11]
        qx, qy, qz, qw = rotation_matrix_to_quaternion(values)
        jump_t = 0.0
        jump_r = 0.0
        if self.last_pose_matrix is not None:
            prev = self.last_pose_matrix
            dx = tx - prev[3]
            dy = ty - prev[7]
            dz = tz - prev[11]
            jump_t = (dx * dx + dy * dy + dz * dz) ** 0.5
            pqx, pqy, pqz, pqw = rotation_matrix_to_quaternion(prev)
            dot = abs(qx * pqx + qy * pqy + qz * pqz + qw * pqw)
            dot = max(-1.0, min(1.0, dot))
            jump_r = math.degrees(2.0 * math.acos(dot))
        self.last_pose_matrix = values
        return {
            "pose_tx_m": tx,
            "pose_ty_m": ty,
            "pose_tz_m": tz,
            "pose_distance_m": (tx * tx + ty * ty + tz * tz) ** 0.5,
            "pose_qx": qx,
            "pose_qy": qy,
            "pose_qz": qz,
            "pose_qw": qw,
            "pose_matrix_cv_camera": list(values),
            "pose_jump_translation_m": jump_t,
            "pose_jump_rotation_deg": jump_r,
        }


__all__ = ["PoseLogFactory"]
