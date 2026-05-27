"""诊断与可视化包级入口。"""

from __future__ import annotations

from .image_utils import fit_to_size, fit_to_width, stack_stereo
from .debug_view import (
    colorize_depth,
    draw_hud as draw_pose_hud,
    make_waiting_image as make_pose_waiting_image,
    overlay_mask_contour,
    tile_pose_depth_dashboard,
)
from .stereo_view import decode_jpeg, draw_stereo_hud, make_waiting_image
from .runtime_event_log import RuntimeEventLogger
from .window import create_fixed_window

__all__ = [
    "create_fixed_window",
    "decode_jpeg",
    "draw_stereo_hud",
    "fit_to_size",
    "fit_to_width",
    "make_waiting_image",
    "RuntimeEventLogger",
    "stack_stereo",
    "colorize_depth",
    "draw_pose_hud",
    "make_pose_waiting_image",
    "overlay_mask_contour",
    "stack_pose_stereo",
    "tile_pose_depth_dashboard",
]

stack_pose_stereo = stack_stereo
"""pose debug 与视频预览共用的双目拼接函数。"""

