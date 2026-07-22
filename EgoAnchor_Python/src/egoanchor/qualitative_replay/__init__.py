"""定性 replay 采集校验、模型重投影和六行连续轨迹图的包级入口。"""

from __future__ import annotations

from .contracts import (
    FORMAT_NAME,
    FORMAT_VERSION,
    VARIANT_COLORS_HEX,
    VARIANT_IDS,
    ReplayCapture,
    ReplayManifest,
    ReplaySample,
    load_capture,
)
from .geometry import (
    UNITY_TO_CV_BASIS,
    display_world_to_cv_camera,
    pose_to_matrix,
    recorded_projection_matrix,
    verify_projection_matrix,
)
from .render import (
    ROW_IDS,
    ROW_LABELS,
    GridColumn,
    MeshProjector,
    render_comparison_grid,
    render_frame_overlays,
    select_stride_samples,
)

__all__ = [
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "VARIANT_COLORS_HEX",
    "VARIANT_IDS",
    "UNITY_TO_CV_BASIS",
    "ROW_IDS",
    "ROW_LABELS",
    "GridColumn",
    "MeshProjector",
    "ReplayCapture",
    "ReplayManifest",
    "ReplaySample",
    "display_world_to_cv_camera",
    "load_capture",
    "pose_to_matrix",
    "recorded_projection_matrix",
    "render_comparison_grid",
    "render_frame_overlays",
    "select_stride_samples",
    "verify_projection_matrix",
]
