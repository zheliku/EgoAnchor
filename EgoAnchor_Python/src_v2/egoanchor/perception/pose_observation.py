"""v2 perception 输出数据结构。"""

from __future__ import annotations

from dataclasses import dataclass



@dataclass(frozen=True)
class PoseObservation:
    """相机坐标系 pose 观测。

    pose_matrix_cv_camera 后续保存 FoundationPose 输出的 OpenCV 相机坐标 4x4 矩阵，
    Unity v2 Anchor Runtime 再通过 frame_id 做 camera pose 回查和 world anchor 对齐。
    """

    has_pose: bool
    phase: str
    frame_id: int | None = None
    pose_matrix_cv_camera: tuple[float, ...] | None = None
    stage: int = 4
    det_count: int = 0
    fps: float = 0.0
    depth_valid_ratio: float = 0.0
    depth_valid_in_mask: float = 0.0
    depth_median_in_mask: float = 0.0
    depth_iqr_in_mask: float = 0.0
    mask_area_ratio: float = 0.0
    track_reject_count: int = 0
    yolo_ms: float = 0.0
    depth_ms: float = 0.0
    cutie_ms: float = 0.0
    pose_ms: float = 0.0
    reliability_score: float = 0.0
