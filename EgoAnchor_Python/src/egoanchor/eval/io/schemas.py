"""EgoAnchor 评估 JSONL 行 schema。

本模块只理解离线日志格式，不导入 egoanchor runtime。Unity pose 均为 Unity
世界系，Python pose_result 的矩阵保持 OpenCV camera-space 原始语义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np


class SchemaError(ValueError):
    """评估日志 schema 不满足分析要求时抛出的清晰错误。"""


JsonRow = Mapping[str, Any]
"""单行 JSON object 的只读类型别名。"""


@dataclass(frozen=True)
class CaptureRow:
    """Unity 每个 frame_id 采集瞬间的一行 GT/camera 记录。"""

    frame_id: int
    capture_mono_ms: float
    capture_unix_ms: float
    capture_unity_frame: int
    sender_mono_ms: float
    """JPEG 编码完成并构造协议 header 的 payload-ready 时间；历史日志缺失时为 NaN。"""
    sender_unity_frame: int
    """payload-ready 时的 Unity frameCount；历史日志缺失时为 -1。"""
    gt_sample_mono_ms: float
    """capture 回调实际采样参考位姿的时间；历史日志缺失时为 NaN。"""
    image_time_basis: str
    """图像时刻的来源；当前 Quest 链路为 camera pose 历史代理。"""
    image_time_offset_frames: int
    """图像时间代理相对 payload-ready 帧回退的成功采集样本数。"""
    publish_attempt_mono_ms: float
    """紧邻 ZMQ TrySend 前的 Unity 单调时钟；历史日志缺失时为 NaN。"""
    publish_succeeded: bool
    """NetMQ 是否立即接受该 multipart 消息。"""
    head_pos: np.ndarray
    head_rot: np.ndarray
    cam_valid: bool
    camera_reference: str
    cam_pos: np.ndarray | None
    cam_rot: np.ndarray | None
    gt_pos: np.ndarray | None
    gt_rot: np.ndarray | None
    gt_pose_valid: bool
    gt_pose_source: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        """指标默认可用行：Transform GT 必须有有效 pose。"""

        return bool(self.gt_pose_valid and self.gt_pos is not None and self.gt_rot is not None)

    @classmethod
    def from_dict(cls, row: JsonRow, *, source: str = "unity_capture") -> "CaptureRow":
        """从 unity_capture JSON object 解析一行。"""

        context = _context(source, row)
        gt_pose_valid = _bool(row, "gt_pose_valid", context)
        cam_valid = _bool(row, "cam_valid", context)
        return cls(
            frame_id=_int(row, "frame_id", context),
            capture_mono_ms=_float(row, "capture_mono_ms", context),
            capture_unix_ms=_float(row, "capture_unix_ms", context),
            capture_unity_frame=_int(row, "capture_unity_frame", context),
            sender_mono_ms=_optional_float(row, "sender_mono_ms", np.nan),
            sender_unity_frame=int(_optional_float(row, "sender_unity_frame", -1.0)),
            gt_sample_mono_ms=_optional_float(row, "gt_sample_mono_ms", np.nan),
            image_time_basis=_optional_str(row, "image_time_basis", "legacy_unspecified"),
            image_time_offset_frames=int(
                _optional_float(row, "image_time_offset_frames", -1.0)
            ),
            publish_attempt_mono_ms=_optional_float(row, "publish_attempt_mono_ms", np.nan),
            publish_succeeded=_optional_bool(row, "publish_succeeded", False),
            head_pos=_array(row, "head_pos", 3, context),
            head_rot=_array(row, "head_rot", 4, context),
            cam_valid=cam_valid,
            camera_reference=_str(row, "camera_reference", context),
            cam_pos=_array(row, "cam_pos", 3, context, allow_none=not cam_valid),
            cam_rot=_array(row, "cam_rot", 4, context, allow_none=not cam_valid),
            gt_pos=_array(row, "gt_pos", 3, context, allow_none=not gt_pose_valid),
            gt_rot=_array(row, "gt_rot", 4, context, allow_none=not gt_pose_valid),
            gt_pose_valid=gt_pose_valid,
            gt_pose_source=_str(row, "gt_pose_source", context),
            raw=dict(row),
        )

    def to_record(self) -> dict[str, Any]:
        """转换为 pandas DataFrame 记录。"""

        return {
            "frame_id": self.frame_id,
            "capture_mono_ms": self.capture_mono_ms,
            "capture_unix_ms": self.capture_unix_ms,
            "capture_unity_frame": self.capture_unity_frame,
            "sender_mono_ms": self.sender_mono_ms,
            "sender_unity_frame": self.sender_unity_frame,
            "gt_sample_mono_ms": self.gt_sample_mono_ms,
            "image_time_basis": self.image_time_basis,
            "image_time_offset_frames": self.image_time_offset_frames,
            "publish_attempt_mono_ms": self.publish_attempt_mono_ms,
            "publish_succeeded": self.publish_succeeded,
            "head_pos": self.head_pos,
            "head_rot": self.head_rot,
            "cam_valid": self.cam_valid,
            "camera_reference": self.camera_reference,
            "cam_pos": self.cam_pos,
            "cam_rot": self.cam_rot,
            "gt_pos": self.gt_pos,
            "gt_rot": self.gt_rot,
            "gt_pose_valid": self.gt_pose_valid,
            "gt_pose_source": self.gt_pose_source,
            "valid": self.valid,
        }


@dataclass(frozen=True)
class VariantRow:
    """unity_output variants 数组中的单个 runtime 变体快照。"""

    label: str
    is_primary: bool
    source_frame_id: int
    has_output_pose: bool
    has_display_pose: bool
    """当前渲染 tick 是否实际显示了 anchor pose，包括 hold-last。"""
    output_pos: np.ndarray | None
    output_rot: np.ndarray | None
    display_pos: np.ndarray | None
    display_rot: np.ndarray | None
    anchor_state: str
    policy_action: str
    policy_reason: str
    latest_phase: str
    latest_failure: str
    anchor_pose_source: str
    has_source_capture_timing: bool
    source_capture_mono_ms: float | None
    source_capture_unity_frame: int
    has_aligned_raw: bool
    aligned_raw_pos: np.ndarray | None
    aligned_raw_rot: np.ndarray | None
    has_arrival_time_raw: bool
    arrival_time_raw_pos: np.ndarray | None
    arrival_time_raw_rot: np.ndarray | None
    arrival_time_raw_mono_ms: float
    arrival_time_raw_unity_frame: int
    arrival_time_camera_reference: str
    reliability_score: float
    strategy_label: str
    quality_gate: str
    motion_model: str
    smoothing_strategy: str
    config_hash: str
    latest_residual_meters: float
    latest_residual_degrees: float
    latest_accepted_score: float
    latest_static_locked: bool
    observation_age_ms: float
    """渲染时刻相对当前观测图像时刻的年龄；历史日志缺失时为 NaN。"""
    policy_output_target_mono_ms: float
    """平滑策略当前输出对应的目标时间；历史日志缺失时为 NaN。"""
    smoothing_delay_ms: float
    """渲染时刻相对策略目标时间的有效平滑延迟；历史日志缺失时为 NaN。"""
    unity_pose_handle_mono_ms: float
    """Unity 主线程成功处理 source pose 的时间；历史日志缺失时为 NaN。"""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, row: JsonRow, *, source: str = "unity_output.variant") -> "VariantRow":
        """从 unity_output 的 variants 元素解析变体。"""

        context = _context(source, row)
        has_output_pose = _bool(row, "has_output_pose", context)
        has_display_pose = _optional_bool(row, "has_display_pose", has_output_pose)
        is_primary = _bool(row, "is_primary", context)
        has_source_capture_timing = _bool(row, "has_source_capture_timing", context)
        has_aligned_raw = _optional_bool(row, "has_aligned_raw", False)
        has_arrival_time_raw = _optional_bool(row, "has_arrival_time_raw", False)
        return cls(
            label=_str(row, "label", context),
            is_primary=is_primary,
            source_frame_id=_int(row, "source_frame_id", context),
            has_output_pose=has_output_pose,
            has_display_pose=has_display_pose,
            output_pos=_array(row, "output_pos", 3, context, allow_none=not has_output_pose),
            output_rot=_array(row, "output_rot", 4, context, allow_none=not has_output_pose),
            display_pos=_array(
                {"display_pos": row.get("display_pos", row.get("output_pos"))},
                "display_pos",
                3,
                context,
                allow_none=not has_display_pose,
            ),
            display_rot=_array(
                {"display_rot": row.get("display_rot", row.get("output_rot"))},
                "display_rot",
                4,
                context,
                allow_none=not has_display_pose,
            ),
            anchor_state=_str(row, "anchor_state", context),
            policy_action=_str(row, "policy_action", context),
            policy_reason=_str(row, "policy_reason", context),
            latest_phase=_str(row, "latest_phase", context),
            latest_failure=_str(row, "latest_failure", context),
            anchor_pose_source=_str(row, "anchor_pose_source", context),
            has_source_capture_timing=has_source_capture_timing,
            source_capture_mono_ms=_nullable_float(
                row,
                "source_capture_mono_ms",
                context,
                allow_none=not has_source_capture_timing,
            ),
            source_capture_unity_frame=_int(row, "source_capture_unity_frame", context),
            has_aligned_raw=has_aligned_raw,
            aligned_raw_pos=_optional_array(row, "aligned_raw_pos", 3, context, allow_none=not has_aligned_raw),
            aligned_raw_rot=_optional_array(row, "aligned_raw_rot", 4, context, allow_none=not has_aligned_raw),
            has_arrival_time_raw=has_arrival_time_raw,
            arrival_time_raw_pos=_optional_array(
                row,
                "arrival_time_raw_pos",
                3,
                context,
                allow_missing=True,
                allow_none=not has_arrival_time_raw,
            ),
            arrival_time_raw_rot=_optional_array(
                row,
                "arrival_time_raw_rot",
                4,
                context,
                allow_missing=True,
                allow_none=not has_arrival_time_raw,
            ),
            arrival_time_raw_mono_ms=_optional_float(row, "arrival_time_raw_mono_ms", np.nan),
            arrival_time_raw_unity_frame=int(_optional_float(row, "arrival_time_raw_unity_frame", -1.0)),
            arrival_time_camera_reference=str(row.get("arrival_time_camera_reference", "")),
            reliability_score=_optional_float(row, "reliability_score", np.nan),
            strategy_label=str(row.get("strategy_label", "")),
            quality_gate=_str(row, "quality_gate", context),
            motion_model=str(row.get("motion_model", "")),
            smoothing_strategy=str(row.get("smoothing_strategy", "")),
            config_hash=str(row.get("config_hash", "")),
            latest_residual_meters=_optional_float(row, "latest_residual_meters", np.nan),
            latest_residual_degrees=_optional_float(row, "latest_residual_degrees", np.nan),
            latest_accepted_score=_optional_float(row, "latest_accepted_score", np.nan),
            latest_static_locked=_optional_bool(row, "latest_static_locked", False),
            observation_age_ms=_optional_float(row, "observation_age_ms", np.nan),
            policy_output_target_mono_ms=_optional_float(row, "policy_output_target_mono_ms", np.nan),
            smoothing_delay_ms=_optional_float(row, "smoothing_delay_ms", np.nan),
            unity_pose_handle_mono_ms=_optional_float(row, "unity_pose_handle_mono_ms", np.nan),
            raw=dict(row),
        )

    def to_record(self) -> dict[str, Any]:
        """转换为 pandas DataFrame 记录。"""

        return {
            "label": self.label,
            "is_primary": self.is_primary,
            "source_frame_id": self.source_frame_id,
            "has_output_pose": self.has_output_pose,
            "has_display_pose": self.has_display_pose,
            "output_pos": self.output_pos,
            "output_rot": self.output_rot,
            "display_pos": self.display_pos,
            "display_rot": self.display_rot,
            "anchor_state": self.anchor_state,
            "policy_action": self.policy_action,
            "policy_reason": self.policy_reason,
            "latest_phase": self.latest_phase,
            "latest_failure": self.latest_failure,
            "anchor_pose_source": self.anchor_pose_source,
            "has_source_capture_timing": self.has_source_capture_timing,
            "source_capture_mono_ms": self.source_capture_mono_ms,
            "source_capture_unity_frame": self.source_capture_unity_frame,
            "has_aligned_raw": self.has_aligned_raw,
            "aligned_raw_pos": self.aligned_raw_pos,
            "aligned_raw_rot": self.aligned_raw_rot,
            "has_arrival_time_raw": self.has_arrival_time_raw,
            "arrival_time_raw_pos": self.arrival_time_raw_pos,
            "arrival_time_raw_rot": self.arrival_time_raw_rot,
            "arrival_time_raw_mono_ms": self.arrival_time_raw_mono_ms,
            "arrival_time_raw_unity_frame": self.arrival_time_raw_unity_frame,
            "arrival_time_camera_reference": self.arrival_time_camera_reference,
            "reliability_score": self.reliability_score,
            "strategy_label": self.strategy_label,
            "quality_gate": self.quality_gate,
            "motion_model": self.motion_model,
            "smoothing_strategy": self.smoothing_strategy,
            "config_hash": self.config_hash,
            "latest_residual_meters": self.latest_residual_meters,
            "latest_residual_degrees": self.latest_residual_degrees,
            "latest_accepted_score": self.latest_accepted_score,
            "latest_static_locked": self.latest_static_locked,
            "observation_age_ms": self.observation_age_ms,
            "policy_output_target_mono_ms": self.policy_output_target_mono_ms,
            "smoothing_delay_ms": self.smoothing_delay_ms,
            "unity_pose_handle_mono_ms": self.unity_pose_handle_mono_ms,
        }


@dataclass(frozen=True)
class OutputRow:
    """Unity 每个渲染 tick 的 runtime 输出行。"""

    tick_index: int
    render_mono_ms: float
    render_unix_ms: float
    render_unity_frame: int
    render_source_frame_id: int
    head_pos: np.ndarray
    head_rot: np.ndarray
    gt_pos: np.ndarray | None
    gt_rot: np.ndarray | None
    gt_pose_valid: bool
    gt_pose_source: str
    gt_linear_speed_m_s: float
    """Unity 侧按帧差分计算的 GT 线速度，单位 m/s；首帧为 0。"""
    gt_angular_speed_deg_s: float
    """Unity 侧按帧差分计算的 GT 角速度，单位 deg/s；首帧为 0。"""
    rq1_metric: str
    """RQ1 手动标记的指标类型（对齐论文 RQ1 实验条件）；无标记时为 'none'。"""
    rq1_metric_duration: float
    """当前 RQ1 指标持续时间（秒）。"""
    rq2_condition: str
    """RQ2 运动场景；未开始试次时为 ``none``。"""
    rq2_trial_id: int
    """session 内递增试次编号；未开始试次时为 -1。"""
    rq2_target_linear_speed_m_s: float
    """试次目标线速度；不适用时为 NaN。"""
    rq2_target_angular_speed_deg_s: float
    """试次目标角速度；不适用时为 NaN。"""
    variants: list[VariantRow]
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        """指标默认可用行：Transform GT 必须有有效 pose。"""

        return bool(self.gt_pose_valid and self.gt_pos is not None and self.gt_rot is not None)

    @classmethod
    def from_dict(cls, row: JsonRow, *, tick_index: int, source: str = "unity_output") -> "OutputRow":
        """从 unity_output JSON object 解析一行。"""

        context = _context(source, row)
        if "rq2_phase" in row:
            raise SchemaError(f"{context}: rq2_phase 已删除；请使用当前版本重新采集数据。")
        gt_pose_valid = _bool(row, "gt_pose_valid", context)
        raw_variants = _required(row, "variants", context)
        if not isinstance(raw_variants, list):
            raise SchemaError(f"{context}: variants 应为 list。")
        return cls(
            tick_index=tick_index,
            render_mono_ms=_float(row, "render_mono_ms", context),
            render_unix_ms=_float(row, "render_unix_ms", context),
            render_unity_frame=_int(row, "render_unity_frame", context),
            render_source_frame_id=_int(row, "source_frame_id", context),
            head_pos=_array(row, "head_pos", 3, context),
            head_rot=_array(row, "head_rot", 4, context),
            gt_pos=_array(row, "gt_pos", 3, context, allow_none=not gt_pose_valid),
            gt_rot=_array(row, "gt_rot", 4, context, allow_none=not gt_pose_valid),
            gt_pose_valid=gt_pose_valid,
            gt_pose_source=_str(row, "gt_pose_source", context),
            gt_linear_speed_m_s=_optional_float(row, "gt_linear_speed_m_s", 0.0),
            gt_angular_speed_deg_s=_optional_float(row, "gt_angular_speed_deg_s", 0.0),
            rq1_metric=_optional_str(row, "rq1_metric", "none"),
            rq1_metric_duration=_optional_float(row, "rq1_metric_duration", 0.0),
            rq2_condition=_str(row, "rq2_condition", context),
            rq2_trial_id=_int(row, "rq2_trial_id", context),
            rq2_target_linear_speed_m_s=_required_float_or_nan(
                row,
                "rq2_target_linear_speed_m_s",
                context,
            ),
            rq2_target_angular_speed_deg_s=_required_float_or_nan(
                row,
                "rq2_target_angular_speed_deg_s",
                context,
            ),
            variants=[
                VariantRow.from_dict(item, source=f"{source}:variants[{index}]")
                for index, item in enumerate(raw_variants)
            ],
            raw=dict(row),
        )

    def to_records(self) -> list[dict[str, Any]]:
        """把 variants 展平成长表记录。"""

        records: list[dict[str, Any]] = []
        for variant in self.variants:
            record = {
                "tick_index": self.tick_index,
                "render_mono_ms": self.render_mono_ms,
                "render_unix_ms": self.render_unix_ms,
                "render_unity_frame": self.render_unity_frame,
                "render_source_frame_id": self.render_source_frame_id,
                "head_pos": self.head_pos,
                "head_rot": self.head_rot,
                "gt_pos": self.gt_pos,
                "gt_rot": self.gt_rot,
                "gt_pose_valid": self.gt_pose_valid,
                "gt_pose_source": self.gt_pose_source,
                "gt_linear_speed_m_s": self.gt_linear_speed_m_s,
                "gt_angular_speed_deg_s": self.gt_angular_speed_deg_s,
                "rq1_metric": self.rq1_metric,
                "rq1_metric_duration": self.rq1_metric_duration,
                "rq2_condition": self.rq2_condition,
                "rq2_trial_id": self.rq2_trial_id,
                "rq2_target_linear_speed_m_s": self.rq2_target_linear_speed_m_s,
                "rq2_target_angular_speed_deg_s": self.rq2_target_angular_speed_deg_s,
                "valid": self.valid,
            }
            record.update(variant.to_record())
            records.append(record)
        return records


@dataclass(frozen=True)
class PoseResultRow:
    """Python runtime pose_result 日志行。"""

    frame_id: int
    has_pose: bool
    pose_matrix_cv_camera: np.ndarray | None
    pose_pos_cv_camera: np.ndarray | None
    pose_quat_cv_camera: np.ndarray | None
    pose_score: float
    reliability_flags: list[str]
    phase: str
    stage: int
    pose_source: str
    total_ms: float
    yolo_ms: float
    depth_ms: float
    cutie_ms: float
    pose_ms: float
    server_receive_mono_ms: float
    server_publish_mono_ms: float
    score_reprojection: float
    score_depth: float
    score_mask: float
    color_reprojection: float
    render_quality_evaluated: bool
    render_quality_status: str
    render_quality_mask_iou: float
    render_quality_area_ratio_score: float
    render_quality_render_visible_ratio: float
    render_quality_observed_visible_ratio: float
    render_quality_render_area_px: int
    render_quality_depth_inlier: float
    render_quality_depth_alignment: float
    render_quality_depth_residual_m: float
    render_quality_ms: float
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, row: JsonRow, *, source: str = "pose_result") -> "PoseResultRow":
        """从 Python runtime pose_result JSON object 解析一行。"""

        context = _context(source, row)
        has_pose = _bool(row, "has_pose", context)
        matrix = _optional_matrix4(row, "pose_matrix_cv_camera", context, required=has_pose)
        return cls(
            frame_id=_int(row, "frame_id", context),
            has_pose=has_pose,
            pose_matrix_cv_camera=matrix,
            pose_pos_cv_camera=_optional_pose_pos(row),
            pose_quat_cv_camera=_optional_pose_quat(row),
            pose_score=_optional_float(row, "pose_score", _optional_float(row, "reliability_score", np.nan)),
            reliability_flags=[str(value) for value in row.get("reliability_flags", [])],
            phase=str(row.get("phase", "")),
            stage=int(row.get("stage", -1)),
            pose_source=str(row.get("pose_source", "")),
            total_ms=_optional_float(row, "total_ms", np.nan),
            yolo_ms=_optional_float(row, "yolo_ms", np.nan),
            depth_ms=_optional_float(row, "depth_ms", np.nan),
            cutie_ms=_optional_float(row, "cutie_ms", np.nan),
            pose_ms=_optional_float(row, "pose_ms", np.nan),
            server_receive_mono_ms=_optional_float(row, "server_receive_mono_ms", np.nan),
            server_publish_mono_ms=_optional_float(row, "server_publish_mono_ms", np.nan),
            score_reprojection=_optional_float(row, "score_reprojection", np.nan),
            score_depth=_optional_float(row, "score_depth", np.nan),
            score_mask=_optional_float(row, "score_mask", np.nan),
            color_reprojection=_optional_float(row, "color_reprojection", -1.0),
            render_quality_evaluated=_optional_bool(row, "render_quality_evaluated", False),
            render_quality_status=str(row.get("render_quality_status", "")),
            render_quality_mask_iou=_optional_float(row, "render_quality_mask_iou", 0.0),
            render_quality_area_ratio_score=_optional_float(row, "render_quality_area_ratio_score", 0.0),
            render_quality_render_visible_ratio=_optional_float(row, "render_quality_render_visible_ratio", 0.0),
            render_quality_observed_visible_ratio=_optional_float(row, "render_quality_observed_visible_ratio", 0.0),
            render_quality_render_area_px=int(_optional_float(row, "render_quality_render_area_px", 0.0)),
            render_quality_depth_inlier=_optional_float(row, "render_quality_depth_inlier", 0.0),
            render_quality_depth_alignment=_optional_float(row, "render_quality_depth_alignment", 0.0),
            render_quality_depth_residual_m=_optional_float(row, "render_quality_depth_residual_m", 0.0),
            render_quality_ms=_optional_float(row, "render_quality_ms", 0.0),
            raw=dict(row),
        )

    @property
    def valid(self) -> bool:
        """Python 有 pose 的 frame 才可参与感知输出指标。"""

        return bool(self.has_pose and self.pose_matrix_cv_camera is not None)

    def to_record(self) -> dict[str, Any]:
        """转换为 pandas DataFrame 记录。"""

        return {
            "frame_id": self.frame_id,
            "has_pose": self.has_pose,
            "valid": self.valid,
            "pose_matrix_cv_camera": self.pose_matrix_cv_camera,
            "pose_pos_cv_camera": self.pose_pos_cv_camera,
            "pose_quat_cv_camera": self.pose_quat_cv_camera,
            "pose_score": self.pose_score,
            "reliability_flags": self.reliability_flags,
            "phase": self.phase,
            "stage": self.stage,
            "pose_source": self.pose_source,
            "total_ms": self.total_ms,
            "yolo_ms": self.yolo_ms,
            "depth_ms": self.depth_ms,
            "cutie_ms": self.cutie_ms,
            "pose_ms": self.pose_ms,
            "server_receive_mono_ms": self.server_receive_mono_ms,
            "server_publish_mono_ms": self.server_publish_mono_ms,
            "score_reprojection": self.score_reprojection,
            "score_depth": self.score_depth,
            "score_mask": self.score_mask,
            "color_reprojection": self.color_reprojection,
            "render_quality_evaluated": self.render_quality_evaluated,
            "render_quality_status": self.render_quality_status,
            "render_quality_mask_iou": self.render_quality_mask_iou,
            "render_quality_area_ratio_score": self.render_quality_area_ratio_score,
            "render_quality_render_visible_ratio": self.render_quality_render_visible_ratio,
            "render_quality_observed_visible_ratio": self.render_quality_observed_visible_ratio,
            "render_quality_render_area_px": self.render_quality_render_area_px,
            "render_quality_depth_inlier": self.render_quality_depth_inlier,
            "render_quality_depth_alignment": self.render_quality_depth_alignment,
            "render_quality_depth_residual_m": self.render_quality_depth_residual_m,
            "render_quality_ms": self.render_quality_ms,
        }


@dataclass(frozen=True)
class Manifest:
    """session_manifest.json 的最小结构。"""

    session_id: str
    object_id: str
    condition_spans: list[dict[str, Any]]
    event_markers: list[dict[str, Any]]
    variant_labels: list[str]
    variant_configs: list[dict[str, Any]]
    python_log_filename: str
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, row: JsonRow, *, source: str = "session_manifest.json") -> "Manifest":
        """从 manifest JSON object 解析并做最小字段校验。"""

        context = _context(source, row)
        condition_spans = row.get("condition_spans", [])
        event_markers = row.get("event_markers", [])
        variant_labels = row.get("variant_labels", [])
        variant_configs = row.get("variant_configs", [])
        if not isinstance(condition_spans, list):
            raise SchemaError(f"{context}: condition_spans 应为 list。")
        if not isinstance(event_markers, list):
            raise SchemaError(f"{context}: event_markers 应为 list。")
        if not isinstance(variant_labels, list):
            raise SchemaError(f"{context}: variant_labels 应为 list。")
        if not isinstance(variant_configs, list):
            raise SchemaError(f"{context}: variant_configs 应为 list。")
        return cls(
            session_id=_str(row, "session_id", context),
            object_id=_str(row, "object_id", context),
            condition_spans=[dict(span) if isinstance(span, Mapping) else {"value": span} for span in condition_spans],
            event_markers=[dict(marker) if isinstance(marker, Mapping) else {"value": marker} for marker in event_markers],
            variant_labels=[str(label) for label in variant_labels],
            variant_configs=[dict(config) if isinstance(config, Mapping) else {"value": config} for config in variant_configs],
            python_log_filename=str(row.get("python_log_filename", "")),
            raw=dict(row),
        )


def _context(source: str, row: JsonRow) -> str:
    """构造错误消息前缀。"""

    frame_id = row.get("frame_id")
    if frame_id is None:
        return source
    return f"{source} frame_id={frame_id}"


def _required(row: JsonRow, field_name: str, context: str) -> Any:
    """读取必需字段，缺失时报清晰错误。"""

    if field_name not in row:
        raise SchemaError(f"{context}: 缺少字段 {field_name}。")
    return row[field_name]


def _int(row: JsonRow, field_name: str, context: str) -> int:
    """读取 int 字段。"""

    value = _required(row, field_name, context)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{context}: 字段 {field_name} 不能转换为 int：{value!r}。") from exc


def _float(row: JsonRow, field_name: str, context: str) -> float:
    """读取 float 字段。"""

    value = _required(row, field_name, context)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{context}: 字段 {field_name} 不能转换为 float：{value!r}。") from exc


def _nullable_float(row: JsonRow, field_name: str, context: str, *, allow_none: bool = False) -> float | None:
    """读取允许 null 的 float 字段。"""

    value = _required(row, field_name, context)
    if value is None and allow_none:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{context}: 字段 {field_name} 不能转换为 float：{value!r}。") from exc


def _optional_float(row: JsonRow, field_name: str, default: float) -> float:
    """读取可选 float 字段。"""

    value = row.get(field_name, default)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _required_float_or_nan(row: JsonRow, field_name: str, context: str) -> float:
    """读取必需的可空 float 字段，并把 JSON null 转换为 NaN。"""

    value = _required(row, field_name, context)
    if value is None:
        return np.nan
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{context}: 字段 {field_name} 不能转换为 float：{value!r}。") from exc


def _bool(row: JsonRow, field_name: str, context: str) -> bool:
    """读取 bool 字段。"""

    value = _required(row, field_name, context)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    raise SchemaError(f"{context}: 字段 {field_name} 应为 bool：{value!r}。")


def _optional_bool(row: JsonRow, field_name: str, default: bool) -> bool:
    """读取可选 bool 字段。"""

    value = row.get(field_name, default)
    return bool(value) if isinstance(value, (bool, int, float)) else default


def _str(row: JsonRow, field_name: str, context: str) -> str:
    """读取 string 字段。"""

    return str(_required(row, field_name, context))


def _optional_str(row: JsonRow, field_name: str, default: str) -> str:
    """读取可选 string 字段。"""

    value = row.get(field_name, default)
    return str(value) if value is not None else default


def _array(row: JsonRow, field_name: str, length: int, context: str, *, allow_none: bool = False) -> np.ndarray | None:
    """读取固定长度 float array 字段。"""

    value = _required(row, field_name, context)
    if value is None and allow_none:
        return None
    return _coerce_array(value, field_name, length, context)


def _optional_array(
    row: JsonRow,
    field_name: str,
    length: int,
    context: str,
    *,
    allow_missing: bool = False,
    allow_none: bool = False,
) -> np.ndarray | None:
    """读取可选固定长度 float array 字段。"""

    if field_name not in row:
        if allow_missing or allow_none:
            return None
        raise SchemaError(f"{context}: 缺少字段 {field_name}。")
    value = row[field_name]
    if value is None and allow_none:
        return None
    return _coerce_array(value, field_name, length, context)


def _coerce_array(value: Any, field_name: str, length: int, context: str) -> np.ndarray:
    """把 JSON 数组转换为 numpy float array。"""

    arr = np.asarray(value, dtype=float)
    if arr.shape != (length,):
        raise SchemaError(f"{context}: 字段 {field_name} 期望 shape=({length},)，实际 {arr.shape}。")
    return arr


def _optional_matrix4(row: JsonRow, field_name: str, context: str, *, required: bool) -> np.ndarray | None:
    """读取 row-major 4x4 矩阵。"""

    if field_name not in row:
        if required:
            raise SchemaError(f"{context}: 缺少字段 {field_name}。")
        return None
    value = row[field_name]
    if value is None:
        if required:
            raise SchemaError(f"{context}: 字段 {field_name} 不能为 null。")
        return None
    arr = np.asarray(value, dtype=float)
    if arr.shape == (16,):
        return arr.reshape(4, 4)
    if arr.shape == (4, 4):
        return arr
    raise SchemaError(f"{context}: 字段 {field_name} 期望 16 个数或 4x4，实际 {arr.shape}。")


def _optional_pose_pos(row: JsonRow) -> np.ndarray | None:
    """从 pose_tx_m/pose_ty_m/pose_tz_m 读取可选相机系平移。"""

    keys = ("pose_tx_m", "pose_ty_m", "pose_tz_m")
    if not all(key in row for key in keys):
        return None
    return np.asarray([float(row[key]) for key in keys], dtype=float)


def _optional_pose_quat(row: JsonRow) -> np.ndarray | None:
    """从 pose_qx/pose_qy/pose_qz/pose_qw 读取可选相机系四元数。"""

    keys = ("pose_qx", "pose_qy", "pose_qz", "pose_qw")
    if not all(key in row for key in keys):
        return None
    return np.asarray([float(row[key]) for key in keys], dtype=float)


__all__ = [
    "CaptureRow",
    "JsonRow",
    "Manifest",
    "OutputRow",
    "PoseResultRow",
    "SchemaError",
    "VariantRow",
]
