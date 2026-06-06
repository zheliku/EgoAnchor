"""诊断与可视化包级入口。"""

from __future__ import annotations

from .image_utils import fit_to_size, stack_stereo
from .debug_view import (
    colorize_depth,
    draw_hud as draw_pose_hud,
    make_score_debug_view,
    make_waiting_image as make_pose_waiting_image,
    overlay_mask_contour,
    tile_pose_depth_dashboard,
)
from .runtime_event_log import RuntimeEventLogger

__all__ = [
    "fit_to_size",
    "make_score_debug_view",
    "RuntimeEventLogger",
    "stack_stereo",
    "colorize_depth",
    "draw_pose_hud",
    "make_pose_waiting_image",
    "overlay_mask_contour",
    "tile_pose_depth_dashboard",
]

