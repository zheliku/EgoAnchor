"""Quest pose pipeline 的轻量数据结构。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from .pose_observation import PoseObservation


@dataclass(slots=True)
class PipelineStepTiming:
    """单帧 pipeline 各阶段耗时。"""

    yolo_ms: float = 0.0
    """分割后端耗时，单位毫秒；字段名沿用旧 PoseObservation 契约。"""

    depth_ms: float = 0.0
    """FFS 深度估计耗时，单位毫秒。"""

    cutie_ms: float = 0.0
    """Cutie mask tracker 耗时，单位毫秒。"""

    pose_ms: float = 0.0
    """FoundationPose register/track 耗时，单位毫秒。"""

    total_ms: float = 0.0
    """整帧处理耗时，单位毫秒。"""

    def finalize(self, start_time_s: float) -> None:
        """根据单帧起始时间写入 total_ms，避免各阶段重复计算。"""

        self.total_ms = (time.perf_counter() - start_time_s) * 1000.0


class MaskSource(StrEnum):
    """pipeline diagnostics 中的 mask 来源。"""

    NONE = "none"
    """当前帧没有可用 mask。"""

    CUTIE = "cutie"
    """当前 mask 来自 Cutie 时序传播。"""


@dataclass(slots=True)
class FrameDiagnostics:
    """用于 debug 显示的中间图像和诊断数值。"""

    left_bgr: np.ndarray | None = None
    """处理分辨率下的左目 BGR 图。"""

    right_bgr: np.ndarray | None = None
    """处理分辨率下的右目 BGR 图。"""

    mask: np.ndarray | None = None
    """当前使用的二值 mask。"""

    segmentation_overlay_bgr: np.ndarray | None = None
    """分割后端原始 overlay 图。"""

    depth: np.ndarray | None = None
    """FFS 输出深度图，单位米。"""

    pose_vis_bgr: np.ndarray | None = None
    """FoundationPose 可视化图。"""

    stage: int = 4
    """当前 debug stage。"""

    phase: str = "WAIT_STREAM"
    """当前 pipeline phase。"""

    frame_id: int | None = None
    """当前处理帧 frame_id。"""

    det_count: int = 0
    """分割后端返回的检测数量。"""

    mask_area_ratio: float = 0.0
    """mask 面积比例。"""

    mask_source: str = MaskSource.NONE.value
    """当前 mask 来源：none、yoloe、sam3 或 cutie。"""

    cutie_bbox_xywh: tuple[int, int, int, int] = (-1, -1, 0, 0)
    """Cutie 输出 bbox，用于 debug 可视化。"""

    depth_valid_ratio: float = 0.0
    """全图有效深度比例。"""

    depth_valid_in_mask: float = 0.0
    """mask 内有效深度比例。"""

    depth_median_m: float = 0.0
    """mask 内深度中位数，单位米。"""

    depth_iqr_m: float = 0.0
    """mask 内深度 IQR，单位米。"""

    score_phase: float = 0.0
    """reliability 最终分中的 phase 子分。"""

    score_reprojection: float = 0.0
    """reliability 最终分中的颜色重投影子分；协议字段名为 score_reprojection。"""

    score_depth: float = 0.0
    """reliability 最终分中的 depth 子分。"""

    score_jump: float = 0.0
    """reliability 最终分中的相邻 pose 跳变子分。"""

    score_mask: float = 0.0
    """reliability 最终分中的 mask 面积子分。"""

    score_reject: float = 0.0
    """reliability 最终分中的 track reject 子分。"""

    score_confidence: float = 0.0
    """reliability 最终分中的连续高质量跟踪置信子分。"""

    color_reprojection: float = -1.0
    """颜色重投影分，0..1；-1 表示本帧无有效重投影信号。"""

    render_quality_evaluated: bool = False
    """本帧是否已经满足渲染质量检测前置条件；为 true 但无信号时应降低可靠性。"""

    render_quality_status: str = "disabled"
    """渲染质量检测状态，用于解释 score 窗口黑屏或无信号原因。"""

    render_quality_mask_iou: float = 0.0
    """渲染 mask 与观测 mask 的 IoU。"""

    render_quality_depth_inlier: float = 0.0
    """渲染深度与观测深度在交集区域的 inlier 比例。"""

    render_quality_depth_alignment: float = 0.0
    """由深度 inlier 和中位残差共同得到的连续深度对齐分。"""

    render_quality_area_ratio_score: float = 0.0
    """观测 Cutie mask 面积 / 渲染投影面积的比例分，低值表示遮挡或投影面积过大。"""

    render_quality_render_visible_ratio: float = 0.0
    """渲染前景中被观测 mask 覆盖的比例，遮挡时会下降。"""

    render_quality_observed_visible_ratio: float = 0.0
    """观测 mask 中被渲染前景解释的比例，低值表示 pose 未覆盖可见区域。"""

    render_quality_render_area_px: int = 0
    """渲染质量检测下采样图上的渲染前景像素数。"""

    render_quality_depth_residual_m: float = 0.0
    """渲染深度与观测深度的中位残差，单位米。"""

    render_quality_ms: float = 0.0
    """渲染质量检测耗时，单位毫秒。"""

    render_quality_render_mask: np.ndarray | None = None
    """渲染质量检测下采样后的渲染 mask，用于独立 debug 窗口。"""

    render_quality_observed_mask: np.ndarray | None = None
    """渲染质量检测下采样后的观测 mask，用于独立 debug 窗口。"""

    render_quality_render_depth: np.ndarray | None = None
    """渲染质量检测下采样后的渲染 depth，用于独立 debug 窗口。"""

    render_quality_observed_depth: np.ndarray | None = None
    """渲染质量检测下采样后的观测 depth，用于独立 debug 窗口。"""

    render_quality_render_rgb: np.ndarray | None = None
    """渲染质量检测下采样后的渲染 RGB，用于独立 debug 窗口。"""

    render_quality_observed_rgb: np.ndarray | None = None
    """渲染质量检测下采样后的观测 RGB，用于独立 debug 窗口。"""

    last_translation_delta_m: float = 0.0
    """上一接受 pose 到当前 pose 的平移增量，单位米。"""

    last_rotation_delta_deg: float = 0.0
    """上一接受 pose 到当前 pose 的旋转增量，单位度。"""

    frame_dt_s: float = 0.0
    """当前处理 pose 与上一处理 pose 的帧间隔，单位秒。"""

    fps: float = 0.0
    """pipeline FPS EMA。"""

    failure_reason: str = ""
    """当前帧失败原因。"""

    segmenter_async: bool = False
    """当前分割后端是否使用后台异步推理。"""

    segmenter_busy: bool = False
    """后台分割线程是否忙。"""

    segmenter_submitted: int = 0
    """异步分割累计提交帧数。"""

    segmenter_completed: int = 0
    """异步分割累计完成次数。"""

    segmenter_dropped: int = 0
    """异步分割因忙而丢弃的提交次数。"""

    segmenter_error: str = ""
    """异步分割最近一次异常。"""

    timing: PipelineStepTiming = field(default_factory=PipelineStepTiming)
    """当前帧耗时。"""


@dataclass(slots=True)
class QuestPosePipelineOutput:
    """Quest pose pipeline 的单次处理输出。"""

    observation: PoseObservation | None
    """camera-space pose observation；无输入时可为 None。"""

    diagnostics: FrameDiagnostics
    """OpenCV debug 所需中间结果。"""

    timing: PipelineStepTiming
    """单帧耗时统计。"""

    new_frame_processed: bool
    """本次调用是否实际处理了新的 stereo frame。"""


@dataclass(slots=True)
class PipelineTrackingState:
    """FoundationPose/Cutie 时序跟踪状态。"""

    generation: int = 0
    """reset 或 calibration 变化后的代数，用于过滤旧异步分割结果。"""

    has_registered: bool = False
    """FoundationPose 是否已完成首次 register。"""

    cutie_ready: bool = False
    """Cutie 是否已用当前目标 mask 初始化。"""

    last_pose: np.ndarray | None = None
    """上一帧接受的 4x4 pose，用于跳变检测。"""

    track_reject_count: int = 0
    """连续 track reject 次数。"""

    tracked_mask_lost_count: int = 0
    """已注册阶段连续缺失有效 Cutie mask 的帧数。"""

    low_reprojection_count: int = 0
    """连续低颜色重投影分帧数；仅 re_register 模式用于触发软 track-loss。"""

    frames_since_register: int = 0
    """最近一次 register/re-register 后已经处理的 track 帧数，用于 warmup。"""

    last_sender_mono_ms: float | None = None
    """上一条进入 pose 评分的 Unity 发送端时间戳，单位毫秒。"""

    def clear_registration(self, *, reset_reject_count: bool = True) -> None:
        """清空依赖当前 register/track 的状态，保留代数和帧时间历史。"""

        self.has_registered = False
        self.cutie_ready = False
        self.last_pose = None
        if reset_reject_count:
            self.track_reject_count = 0
        self.tracked_mask_lost_count = 0
        self.low_reprojection_count = 0
        self.frames_since_register = 0

    def bump_generation(self) -> None:
        """进入新跟踪代，并清空依赖历史 pose/mask 的状态。"""

        self.generation += 1
        self.clear_registration(reset_reject_count=True)
        self.last_sender_mono_ms = None
