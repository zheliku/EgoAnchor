"""v3 诊断与可视化包级入口。"""

from __future__ import annotations

from .debug_view import (
	colorize_depth,
	draw_hud as draw_pose_hud,
	make_waiting_image as make_pose_waiting_image,
	overlay_mask_contour,
	stack_stereo as stack_pose_stereo,
	tile_pose_depth_dashboard,
)
from .stereo_view import decode_jpeg, draw_stereo_hud, make_waiting_image, stack_stereo
from .window import create_fixed_window

__all__ = [
	"create_fixed_window",
	"decode_jpeg",
	"draw_stereo_hud",
	"make_waiting_image",
	"stack_stereo",
	"colorize_depth",
	"draw_pose_hud",
	"make_pose_waiting_image",
	"overlay_mask_contour",
	"stack_pose_stereo",
	"tile_pose_depth_dashboard",
]