"""camera-space pose observation 数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PoseObservation:
    """感知侧输出的单帧 camera-space pose 观测。"""

    has_pose: bool
    """是否存在可用 6DoF pose。"""

    phase: str
    """当前 pipeline phase，例如 WAIT_DETECT、REGISTER、TRACK、REJECT_DEPTH。"""

    frame_id: int | None = None
    """Unity/Quest frame_id，用于未来 Unity frame-aligned anchor 回查。"""

    pose_matrix_cv_camera: tuple[float, ...] | None = None
    """OpenCV camera 坐标系 4x4 object pose，row-major 展平；无 pose 时为 None。"""

    pose_source: str = "NONE"
    """pose 来源：REGISTER、TRACK、RE_REGISTER 或 NONE。"""

    tracking_state_hint: str = "DETECTING"
    """perception 侧状态提示，用于 debug HUD 和未来状态事件。"""

    stage: int = 4
    """当前 debug stage：1=输入，2=mask，3=depth，4=pose。"""

    det_count: int = 0
    """分割器检测数量。"""

    fps: float = 0.0
    """pipeline 处理 FPS 的 EMA。"""

    depth_valid_ratio: float = 0.0
    """全图有效深度比例。"""

    depth_valid_in_mask: float = 0.0
    """mask 内有效深度比例。"""

    depth_median_in_mask: float = 0.0
    """mask 内有效深度中位数，单位米。"""

    depth_iqr_in_mask: float = 0.0
    """mask 内有效深度四分位距，单位米。"""

    depth_quality_score: float = 0.0
    """仅由 depth 有效率估计的子分，范围 0..1，用于 HUD/日志诊断。"""

    mask_area_ratio: float = 0.0
    """mask 前景面积占整图比例。"""

    track_consistency: float = -1.0
    """渲染-重投影一致性分，范围 0..1；-1 表示本帧无有效一致性信号。"""

    consistency_mask_iou: float = 0.0
    """渲染 mask 与观测 mask 的 IoU。"""

    consistency_depth_inlier: float = 0.0
    """渲染深度与观测深度在交集区域的 inlier 比例。"""

    last_translation_delta_m: float = 0.0
    """上一接受 pose 到当前 pose 的平移增量，单位米。"""

    last_rotation_delta_deg: float = 0.0
    """上一接受 pose 到当前 pose 的旋转增量，单位度。"""

    track_reject_count: int = 0
    """连续 track reject 计数。"""

    yolo_ms: float = 0.0
    """YOLOE 分割耗时，单位毫秒。"""

    depth_ms: float = 0.0
    """FFS 深度估计耗时，单位毫秒。"""

    cutie_ms: float = 0.0
    """Cutie mask tracker 耗时，单位毫秒。"""

    pose_ms: float = 0.0
    """FoundationPose register/track 耗时，单位毫秒。"""

    total_ms: float = 0.0
    """pipeline 单帧总耗时，单位毫秒。"""

    reliability_score: float = 0.0
    """感知侧轻量可靠性评分，范围 0..1。"""

    reliability_flags: tuple[str, ...] = field(default_factory=tuple)
    """解释可靠性评分或 reject 原因的诊断 flags。"""

    failure_reason: str = ""
    """结构化失败原因；无失败时为空字符串。"""

