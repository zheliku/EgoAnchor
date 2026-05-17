"""v2 diagnostics 层：统计、日志、debug view。"""

from egoanchor.diagnostics.debug_view import (
	colorize_depth,
	draw_hud,
	make_waiting_image,
	overlay_mask_contour,
	stack_stereo,
	tile_pose_depth_dashboard,
)

__all__ = [
	"colorize_depth",
	"draw_hud",
	"make_waiting_image",
	"overlay_mask_contour",
	"stack_stereo",
	"tile_pose_depth_dashboard",
]
