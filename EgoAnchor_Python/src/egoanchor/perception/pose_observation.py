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

    server_receive_mono_ms: float = 0.0
    """Python ZMQ 接收该 stereo frame 的本地单调时间戳，单位毫秒；未知时为 0。"""

    pose_matrix_cv_camera: tuple[float, ...] | None = None
    """OpenCV camera 坐标系 4x4 object pose，row-major 展平；无 pose 时为 None。"""

    pose_source: str = "NONE"
    """pose 来源：REGISTER、TRACK 或 NONE。"""

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

    depth_median_m: float = 0.0
    """mask 内有效深度中位数，单位米。"""

    depth_iqr_m: float = 0.0
    """mask 内有效深度四分位距，单位米。"""

    score_reprojection: float = 0.0
    """reliability 最终分中的颜色投影子分（C，Color projection）；协议字段名为 score_reprojection。"""

    score_depth: float = 0.0
    """reliability 最终分中的深度对齐子分（D，Depth alignment）。"""

    score_mask: float = 0.0
    """reliability 最终分中的可见面积子分（V，Visibility）。"""

    mask_area_ratio: float = 0.0
    """mask 前景面积占整图比例。"""

    render_quality_evaluated: bool = False
    """本帧是否已经满足渲染质量检测前置条件并实际跑了检测；为 true 但无信号时应降低可靠性。"""

    render_quality_status: str = "disabled"
    """渲染质量检测状态，用于区分 disabled、warmup、render_exception、valid 等情况。"""

    color_reprojection: float = -1.0
    """颜色投影分（Color projection），范围 0..1；-1 表示本帧无有效颜色信号。"""

    render_quality_mask_iou: float = 0.0
    """渲染 mask 与观测 mask 的 IoU。"""

    render_quality_depth_inlier: float = 0.0
    """渲染深度与观测深度在交集区域的 inlier 比例。"""

    render_quality_depth_alignment: float = 0.0
    """由深度 inlier 和中位残差共同得到的连续深度对齐分。"""

    render_quality_area_ratio_score: float = 0.0
    """观测 Cutie mask 面积 / 渲染投影面积的比例分，低值表示遮挡严重。"""

    render_quality_render_visible_ratio: float = 0.0
    """渲染前景中被观测 mask 覆盖的比例，遮挡时会下降。"""

    render_quality_observed_visible_ratio: float = 0.0
    """观测 mask 中被渲染前景解释的比例，低值表示 pose 未覆盖可见区域。"""

    render_quality_depth_residual_m: float = 0.0
    """渲染深度与观测深度的中位残差，单位米。"""

    render_quality_render_area_px: int = 0
    """渲染质量检测下采样图上的渲染前景像素数。"""

    last_translation_delta_m: float = 0.0
    """上一接受 pose 到当前 pose 的平移增量，单位米。"""

    last_rotation_delta_deg: float = 0.0
    """上一接受 pose 到当前 pose 的旋转增量，单位度。"""

    frame_dt_s: float = 0.0
    """当前 pose 与上一处理 pose 的帧间隔，单位秒，帧间间隔遥测。"""

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
