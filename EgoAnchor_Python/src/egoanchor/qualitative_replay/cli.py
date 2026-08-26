"""定性 replay 的独立命令行入口。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from egoanchor.config import load_config
from egoanchor.qualitative_replay import (
    COLUMN_LABEL_MODES,
    ROW_KEYS,
    ROW_TITLES,
    TEXTURE_RENDER_BACKENDS,
    TIMELINE_MODES,
    TIMELINE_PLACEMENTS,
    MeshProjector,
    ReplayCapture,
    ReplaySettings,
    describe_samples,
    load_capture,
    load_replay_settings,
    render_comparison_grid,
    render_frame_overlays,
)


def build_parser() -> argparse.ArgumentParser:
    """构造 validate、inspect、frame 和 grid 四个子命令。"""

    parser = argparse.ArgumentParser(
        prog="egoanchor-replay",
        description="校验 Quest Link 定性 replay，并离线生成六行连续轨迹图。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="只校验 capture 契约、统计和全部 JPEG")
    _add_capture_argument(validate)
    validate.add_argument("--allow-incomplete", action="store_true", help="允许非零丢帧统计；仍要求 complete=true")

    inspect = subparsers.add_parser("inspect", help="检查指定帧段的数据完整性和相对平台参考差异")
    _add_capture_argument(inspect)
    inspect.add_argument("--start-sample-id", required=True, help="诊断起始 sample id")
    inspect.add_argument("--count", type=int, default=8, help="诊断样本数，默认 8")
    inspect.add_argument("--frame-step", type=int, default=1, help="相邻诊断样本的已保存帧间隔，默认 1")
    inspect.add_argument("--allow-incomplete", action="store_true", help="允许非零采集丢帧统计")

    frame = subparsers.add_parser("frame", help="输出原图、Quest 参考和四种方法的同步单帧校验图")
    _add_capture_argument(frame)
    frame.add_argument("--sample-id", default=None, help="样本 id；省略时使用首条四方法同时可见样本")
    frame.add_argument("--output", type=Path, default=None, help="输出目录；默认 <capture>/rendered/frame")
    frame.add_argument("--mesh", type=Path, default=None, help="显式 mesh 路径；默认使用 capture provenance")
    frame.add_argument("--config", type=Path, default=None, help="可选局部 TOML 覆盖配置")
    _add_overlay_arguments(frame)
    frame.add_argument("--allow-incomplete", action="store_true", help="允许非零丢帧统计")

    grid = subparsers.add_parser(
        "grid",
        help="按固定已保存帧间隔输出可配置列数、六行的连续轨迹图",
    )
    _add_capture_argument(grid)
    grid.add_argument("--columns", type=int, default=None, help="列数，范围 2--20；默认读取 TOML")
    grid.add_argument("--frame-step", type=int, default=None, help="相邻列间隔的已保存帧数；默认读取 TOML")
    selection = grid.add_mutually_exclusive_group()
    selection.add_argument("--start-sample-id", default=None, help="首列 sample id；省略时找最早完整连续序列")
    selection.add_argument(
        "--sample-ids",
        nargs="+",
        default=None,
        metavar="ID",
        help="显式指定 2--20 个严格递增且等距的 sample id",
    )
    grid.add_argument(
        "--row-keys",
        nargs="+",
        choices=ROW_KEYS,
        default=None,
        help="需要输出的数据行及其排列顺序；默认读取 TOML 的 selection.row_keys",
    )
    grid.add_argument("--cell-width", type=int, default=None, help="每个图像单元宽度；默认读取 TOML")
    crop = grid.add_mutually_exclusive_group()
    crop.add_argument("--crop-padding", type=float, default=None, help="切换为自动裁剪并设置额外留白比例")
    crop.add_argument(
        "--crop",
        dest="crop_xywh",
        nargs=4,
        type=int,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        default=None,
        help="使用固定原图裁剪框；指定后不再使用自动裁剪",
    )
    grid.add_argument("--crop-aspect-ratio", type=float, default=None, help="自动裁剪宽高比；默认读取 TOML")
    grid.add_argument(
        "--column-label",
        choices=COLUMN_LABEL_MODES,
        default=None,
        help="列标题：none、delta-t、sample-id 或 both；默认读取 TOML",
    )
    grid.add_argument("--label-font-size", type=int, default=None, help="左侧行名字号；默认读取 TOML")
    grid.add_argument("--row-label-rotation", type=int, default=None, help="左侧行名逆时针旋转角度；默认读取 TOML")
    grid.add_argument("--column-font-size", type=int, default=None, help="列标题字号；默认读取 TOML")
    grid.add_argument(
        "--timeline-mode",
        choices=TIMELINE_MODES,
        default=None,
        help="时间轴：none、relative-time 或 frame-sequence；默认读取 TOML",
    )
    grid.add_argument(
        "--timeline-placement",
        choices=TIMELINE_PLACEMENTS,
        default=None,
        help="时间轴位置：top 或 bottom；默认读取 TOML",
    )
    grid.add_argument("--label-padding", type=int, default=None, help="行名左右合计留白；默认读取 TOML")
    grid.add_argument("--label-min-width", type=int, default=None, help="行名区域最小宽度；默认读取 TOML")
    grid.add_argument("--row-label-color", default=None, help="左侧行名颜色，格式 #RRGGBB")
    grid.add_argument("--column-label-color", default=None, help="顶部列标题颜色，格式 #RRGGBB")
    grid.add_argument("--header-padding", type=int, default=None, help="顶部标题区域附加高度，单位像素")
    grid.add_argument("--row-label-line-spacing", type=int, default=None, help="多行行标题的行间距，单位像素")
    grid.add_argument("--border-thickness", type=int, default=None, help="图像单元边框线宽，0 表示关闭")
    grid.add_argument("--border-color", default=None, help="图像单元边框颜色，格式 #RRGGBB")
    grid.add_argument("--output", type=Path, default=None, help="输出目录；默认 <capture>/rendered/grid")
    grid.add_argument("--mesh", type=Path, default=None, help="显式 mesh 路径；默认使用 capture provenance")
    grid.add_argument("--config", type=Path, default=None, help="可选局部 TOML 覆盖配置")
    _add_overlay_arguments(grid)
    grid.add_argument("--allow-incomplete", action="store_true", help="允许非零采集丢帧统计")
    return parser


def _add_overlay_arguments(parser: argparse.ArgumentParser) -> None:
    """添加可覆盖 TOML 的半透明模型、轮廓和坐标轴参数。"""

    parser.add_argument("--model-alpha", type=float, default=None, help="半透明模型不透明度，范围 0-1")
    parser.add_argument("--model-color", default=None, help="半透明模型颜色，格式 #RRGGBB")
    parser.add_argument("--reference-alpha", type=float, default=None, help="Quest Reference 填充不透明度")
    parser.add_argument("--fill-mode", choices=("texture", "color"), default=None, help="模型填充模式")
    parser.add_argument("--texture-backend", choices=TEXTURE_RENDER_BACKENDS, default=None, help="纹理后端：auto、nvdiffrast 或 cpu")
    parser.add_argument("--texture-max-size", type=int, default=None, help="纹理预滤波最长边；0 保留原尺寸")
    parser.add_argument("--minimum-component-faces", type=int, default=None, help="保留 mesh 组件所需的最小三角面数")
    parser.add_argument("--texture-brightness", type=float, default=None, help="base-color 纹理亮度倍率")
    parser.add_argument("--method-contour-thickness", type=int, default=None, help="四方法彩色轮廓线宽")
    parser.add_argument("--reference-contour-color", default=None, help="Quest Reference 内轮廓颜色")
    parser.add_argument("--reference-contour-thickness", type=int, default=None, help="Quest Reference 内轮廓线宽")
    parser.add_argument("--reference-halo-color", default=None, help="Quest Reference 外沿颜色")
    parser.add_argument("--reference-halo-thickness", type=int, default=None, help="Quest Reference 外沿总线宽")
    parser.add_argument(
        "--axes",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="显示或隐藏 XYZ 坐标轴；可使用 --no-axes",
    )
    parser.add_argument("--axis-length", type=float, default=None, help="XYZ 轴长度，单位米")
    parser.add_argument("--axis-thickness", type=int, default=None, help="XYZ 轴线宽，单位原图像素")
    parser.add_argument("--axis-label-font-size", type=int, default=None, help="XYZ 端点标签字号，单位像素")
    parser.add_argument("--axis-halo-color", default=None, help="XYZ 轴和文字外沿颜色")
    parser.add_argument("--axis-halo-thickness", type=int, default=None, help="XYZ 轴和文字外沿总线宽")
    parser.add_argument("--axis-tip-length", type=float, default=None, help="箭头尖端长度占轴长比例")
    parser.add_argument("--axis-label-offset", nargs=2, type=int, default=None, metavar=("X", "Y"), help="XYZ 端点文字偏移")
    parser.add_argument("--axis-origin-color", default=None, help="XYZ 原点圆点颜色")
    parser.add_argument("--axis-origin-radius", type=int, default=None, help="XYZ 原点圆点半径")


def main(argv: Sequence[str] | None = None) -> int:
    """执行 replay 子命令；成功返回 0，契约或投影失败由异常明确终止。"""

    args = build_parser().parse_args(argv)
    capture = load_capture(args.capture, strict=not args.allow_incomplete)
    if args.command == "validate":
        print(
            json.dumps(
                {
                    "capture_id": capture.manifest.capture_id,
                    "object_id": capture.manifest.object_id,
                    "samples": len(capture.samples),
                    "status": "valid",
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "inspect":
        rows = describe_samples(
            capture.samples,
            start_sample_id=args.start_sample_id,
            count=args.count,
            frame_step=args.frame_step,
        )
        print(
            json.dumps(
                {
                    "capture_id": capture.manifest.capture_id,
                    "reference_difference_semantics": (
                        "display pose relative to the Quest controller reference; "
                        "diagnostic only, not external ground truth"
                    ),
                    "samples": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    settings = load_replay_settings(args.config)
    model_alpha = settings.overlay.model_alpha if args.model_alpha is None else args.model_alpha
    model_color = settings.overlay.model_color_hex if args.model_color is None else args.model_color
    reference_alpha = (
        settings.overlay.reference_alpha
        if args.reference_alpha is None
        else args.reference_alpha
    )
    method_contour_thickness = (
        settings.overlay.method_contour_thickness_px
        if args.method_contour_thickness is None
        else args.method_contour_thickness
    )
    show_axes = settings.axes.enabled if args.axes is None else args.axes
    axis_length = settings.axes.length_m if args.axis_length is None else args.axis_length
    axis_thickness = (
        settings.axes.thickness_px
        if args.axis_thickness is None
        else args.axis_thickness
    )
    axis_label_font_size = (
        settings.axes.label_font_size_px
        if args.axis_label_font_size is None
        else args.axis_label_font_size
    )
    minimum_component_faces = _value_or(
        args.minimum_component_faces,
        settings.overlay.minimum_component_faces,
    )
    projector, mesh_path = _build_projector(
        capture,
        args.mesh,
        minimum_component_faces=minimum_component_faces,
    )
    configuration_sources = _configuration_sources(
        settings,
        capture_validation_strict=not args.allow_incomplete,
        mesh_path=mesh_path,
        mesh_overridden=args.mesh is not None,
    )
    if args.command == "frame":
        output = args.output or capture.root / "rendered" / "frame"
        paths = render_frame_overlays(
            capture,
            projector,
            output,
            sample_id=args.sample_id,
            model_alpha=model_alpha,
            model_color_hex=model_color,
            method_colors_hex=settings.overlay.method_colors_hex,
            reference_alpha=reference_alpha,
            fill_mode=_value_or(args.fill_mode, settings.overlay.fill_mode),
            texture_backend=_value_or(
                args.texture_backend, settings.overlay.texture_backend
            ),
            texture_max_size_px=_value_or(
                args.texture_max_size, settings.overlay.texture_max_size_px
            ),
            texture_brightness=_value_or(
                args.texture_brightness, settings.overlay.texture_brightness
            ),
            method_contour_thickness=method_contour_thickness,
            reference_contour_color_hex=_value_or(
                args.reference_contour_color,
                settings.overlay.reference_contour_color_hex,
            ),
            reference_contour_thickness=_value_or(
                args.reference_contour_thickness,
                settings.overlay.reference_contour_thickness_px,
            ),
            reference_halo_color_hex=_value_or(
                args.reference_halo_color,
                settings.overlay.reference_halo_color_hex,
            ),
            reference_halo_thickness=_value_or(
                args.reference_halo_thickness,
                settings.overlay.reference_halo_thickness_px,
            ),
            show_axes=show_axes,
            axis_length_m=axis_length,
            axis_thickness=axis_thickness,
            axis_label_font_size=axis_label_font_size,
            axis_colors_hex=settings.axes.colors_hex,
            axis_halo_color_hex=_value_or(
                args.axis_halo_color, settings.axes.halo_color_hex
            ),
            axis_halo_thickness=_value_or(
                args.axis_halo_thickness, settings.axes.halo_thickness_px
            ),
            axis_tip_length=_value_or(args.axis_tip_length, settings.axes.tip_length),
            axis_label_offset_px=tuple(
                _value_or(args.axis_label_offset, settings.axes.label_offset_px)
            ),
            axis_origin_color_hex=_value_or(
                args.axis_origin_color, settings.axes.origin_color_hex
            ),
            axis_origin_radius=_value_or(
                args.axis_origin_radius, settings.axes.origin_radius_px
            ),
        )
        _print_paths(capture, paths, extra={"configuration": configuration_sources})
        return 0

    crop_xywh, crop_padding = _resolve_crop(args, settings)
    explicit_ids = args.sample_ids is not None
    start_sample_id = (
        None
        if explicit_ids
        else _value_or(args.start_sample_id, settings.selection.start_sample_id)
    )
    row_keys = settings.selection.row_keys if args.row_keys is None else tuple(args.row_keys)
    row_titles = settings.selection.rows if args.row_keys is None else tuple(
        ROW_TITLES[row] for row in row_keys
    )
    output = args.output or capture.root / "rendered" / "grid"
    paths = render_comparison_grid(
        capture,
        projector,
        output,
        columns=None if explicit_ids else _value_or(args.columns, settings.selection.columns),
        frame_step=None if explicit_ids else _value_or(args.frame_step, settings.selection.frame_step),
        start_sample_id=start_sample_id,
        sample_ids=args.sample_ids,
        rows=row_keys,
        cell_width=_value_or(args.cell_width, settings.layout.cell_width),
        crop_padding=crop_padding,
        crop_xywh=crop_xywh,
        crop_aspect_ratio=_value_or(
            args.crop_aspect_ratio, settings.crop.aspect_ratio
        ),
        column_label=_value_or(args.column_label, settings.layout.column_label),
        label_font_size=_value_or(args.label_font_size, settings.layout.label_font_size),
        row_label_rotation=_value_or(
            args.row_label_rotation,
            settings.layout.row_label_rotation_deg,
        ),
        column_font_size=_value_or(args.column_font_size, settings.layout.column_font_size),
        timeline=replace(
            settings.timeline,
            mode=_value_or(args.timeline_mode, settings.timeline.mode),
            placement=_value_or(
                args.timeline_placement,
                settings.timeline.placement,
            ),
        ),
        label_padding=_value_or(args.label_padding, settings.layout.label_padding_px),
        label_min_width=_value_or(args.label_min_width, settings.layout.label_min_width_px),
        model_alpha=model_alpha,
        model_color_hex=model_color,
        method_colors_hex=settings.overlay.method_colors_hex,
        reference_alpha=reference_alpha,
        fill_mode=_value_or(args.fill_mode, settings.overlay.fill_mode),
        texture_backend=_value_or(
            args.texture_backend, settings.overlay.texture_backend
        ),
        texture_max_size_px=_value_or(
            args.texture_max_size, settings.overlay.texture_max_size_px
        ),
        texture_brightness=_value_or(
            args.texture_brightness, settings.overlay.texture_brightness
        ),
        method_contour_thickness=method_contour_thickness,
        reference_contour_color_hex=_value_or(
            args.reference_contour_color,
            settings.overlay.reference_contour_color_hex,
        ),
        reference_contour_thickness=_value_or(
            args.reference_contour_thickness,
            settings.overlay.reference_contour_thickness_px,
        ),
        reference_halo_color_hex=_value_or(
            args.reference_halo_color,
            settings.overlay.reference_halo_color_hex,
        ),
        reference_halo_thickness=_value_or(
            args.reference_halo_thickness,
            settings.overlay.reference_halo_thickness_px,
        ),
        show_axes=show_axes,
        axis_length_m=axis_length,
        axis_thickness=axis_thickness,
        axis_label_font_size=axis_label_font_size,
        axis_colors_hex=settings.axes.colors_hex,
        axis_halo_color_hex=_value_or(
            args.axis_halo_color, settings.axes.halo_color_hex
        ),
        axis_halo_thickness=_value_or(
            args.axis_halo_thickness, settings.axes.halo_thickness_px
        ),
        axis_tip_length=_value_or(args.axis_tip_length, settings.axes.tip_length),
        axis_label_offset_px=tuple(
            _value_or(args.axis_label_offset, settings.axes.label_offset_px)
        ),
        axis_origin_color_hex=_value_or(
            args.axis_origin_color, settings.axes.origin_color_hex
        ),
        axis_origin_radius=_value_or(
            args.axis_origin_radius, settings.axes.origin_radius_px
        ),
        gutter=settings.layout.gutter_px,
        border_thickness=_value_or(
            args.border_thickness, settings.layout.border_thickness_px
        ),
        canvas_color_hex=settings.layout.canvas_color_hex,
        border_color_hex=_value_or(args.border_color, settings.layout.border_color_hex),
        row_label_color_hex=_value_or(
            args.row_label_color, settings.layout.row_label_color_hex
        ),
        column_label_color_hex=_value_or(
            args.column_label_color, settings.layout.column_label_color_hex
        ),
        header_padding=_value_or(args.header_padding, settings.layout.header_padding_px),
        row_titles=row_titles,
        row_label_line_spacing=_value_or(
            args.row_label_line_spacing,
            settings.layout.row_label_line_spacing_px,
        ),
        mean_error_font_size=settings.layout.mean_error_font_size_px,
        configuration_provenance=configuration_sources,
    )
    _print_paths(capture, paths)
    return 0


def cli(argv: Sequence[str] | None = None) -> int:
    """把可操作错误压缩成一行，避免普通参数问题输出整段 traceback。"""

    try:
        return main(argv)
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        print(f"replay error: {exc}", file=sys.stderr)
        return 2


def _value_or(value: Any, default: Any) -> Any:
    """只在 CLI 参数未显式出现时使用 TOML 默认值。"""

    return default if value is None else value


def _resolve_crop(
    args: argparse.Namespace,
    settings: ReplaySettings,
) -> tuple[tuple[int, int, int, int] | None, float | None]:
    """按 CLI 优先于 TOML 的规则解析固定或自动裁剪。"""

    if args.crop_xywh is not None:
        x, y, width, height = (int(value) for value in args.crop_xywh)
        return (x, y, width, height), None
    if args.crop_padding is not None:
        return None, float(args.crop_padding)
    if settings.crop.mode == "fixed":
        return settings.crop.fixed_xywh, None
    return None, settings.crop.padding


def _configuration_sources(
    settings: ReplaySettings,
    *,
    capture_validation_strict: bool,
    mesh_path: Path,
    mesh_overridden: bool,
) -> dict[str, object]:
    """记录 TOML、capture 校验模式和实际 mesh 的完整来源。"""

    provenance = settings.provenance
    return {
        "contract_version": settings.contract_version,
        "default_path": str(provenance.default_path),
        "default_sha256": provenance.default_sha256,
        "custom_path": str(provenance.custom_path) if provenance.custom_path is not None else None,
        "custom_sha256": provenance.custom_sha256,
        "capture_validation_strict": bool(capture_validation_strict),
        "mesh_path": str(mesh_path),
        "mesh_sha256": _sha256_file(mesh_path),
        "mesh_overridden": bool(mesh_overridden),
    }


def _add_capture_argument(parser: argparse.ArgumentParser) -> None:
    """给子命令添加统一 capture 目录参数。"""

    parser.add_argument("capture", type=Path, help="Unity 同步后的完整 replay capture 目录")


def _build_projector(
    capture: ReplayCapture,
    mesh_override: Path | None,
    *,
    minimum_component_faces: int,
) -> tuple[MeshProjector, Path]:
    """解析并核对 capture 与当前对象配置的 mesh/scale。"""

    config = load_config(object_name=capture.manifest.object_id)
    configured_mesh = str(config.module.foundationpose.mesh_path)
    configured_scale = float(config.module.foundationpose.apply_scale)
    if configured_mesh != capture.manifest.model_mesh_path:
        raise ValueError(
            "capture 的 model_mesh_path 与当前对象配置不一致: "
            f"capture={capture.manifest.model_mesh_path} config={configured_mesh}"
        )
    if abs(configured_scale - capture.manifest.model_apply_scale) > 1e-9:
        raise ValueError(
            "capture 的 model_apply_scale 与当前对象配置不一致: "
            f"capture={capture.manifest.model_apply_scale} config={configured_scale}"
        )
    mesh_path = mesh_override.expanduser().resolve() if mesh_override is not None else (
        config.paths.python_root / capture.manifest.model_mesh_path
    ).resolve()
    return (
        MeshProjector.from_capture(
            capture,
            mesh_path,
            minimum_component_faces=minimum_component_faces,
        ),
        mesh_path,
    )


def _sha256_file(path: Path) -> str:
    """流式计算实际投影 mesh 的 SHA-256，避免大文件一次读入内存。"""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _print_paths(
    capture: ReplayCapture,
    paths: dict[str, Path],
    *,
    extra: dict[str, object] | None = None,
) -> None:
    """把输出文件以稳定 JSON 打印给调用方。"""

    payload: dict[str, object] = {
        "capture_id": capture.manifest.capture_id,
        "outputs": {name: str(path) for name, path in sorted(paths.items())},
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(cli())
