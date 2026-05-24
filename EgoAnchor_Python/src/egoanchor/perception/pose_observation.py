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

    mask_area_ratio: float = 0.0
    """mask 前景面积占整图比例。"""

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

