"""定性 replay 的强类型 TOML 配置入口。"""

from __future__ import annotations

import copy
import hashlib
import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .texture_renderer import TEXTURE_RENDER_BACKENDS


DEFAULT_REPLAY_CONFIG_PATH = (
    Path(__file__).resolve().parent / "config" / "qualitative_replay.toml"
)
"""随包提供的定性 replay 默认配置路径。"""

REPLAY_ROW_KEYS = (
    "passthrough",
    "reference",
    "arrival",
    "capture",
    "one-euro",
    "egoanchor",
)
"""配置和 CLI 使用的稳定小写行标识。"""

COLUMN_LABEL_MODES = ("none", "delta-t", "sample-id", "both")
"""列标题支持的稳定模式。"""

TIMELINE_MODES = ("none", "relative-time", "frame-sequence")
"""时间轴支持的稳定模式。"""

TIMELINE_PLACEMENTS = ("top", "bottom")
"""时间轴支持的稳定放置位置。"""


_TABLE_KEYS = {
    "contract": frozenset({"version"}),
    "selection": frozenset({"columns", "frame_step", "start_sample_id", "row_keys", "rows"}),
    "layout": frozenset(
        {
            "cell_width",
            "column_label",
            "label_font_size",
            "column_font_size",
            "label_padding_px",
            "label_min_width_px",
            "gutter_px",
            "border_thickness_px",
            "canvas_color_hex",
            "border_color_hex",
            "row_label_color_hex",
            "column_label_color_hex",
            "header_padding_px",
            "row_label_line_spacing_px",
        }
    ),
    "timeline": frozenset(
        {
            "mode",
            "placement",
            "font_size_px",
            "color_hex",
            "line_thickness_px",
            "tick_length_px",
            "padding_px",
            "right_extension_px",
        }
    ),
    "crop": frozenset({"mode", "padding", "fixed_xywh", "aspect_ratio"}),
    "overlay": frozenset(
        {
            "model_alpha",
            "reference_alpha",
            "fill_mode",
            "texture_brightness",
            "texture_backend",
            "texture_max_size_px",
            "minimum_component_faces",
            "model_color_hex",
            "method_colors_hex",
            "method_contour_thickness_px",
            "reference_contour_color_hex",
            "reference_contour_thickness_px",
            "reference_halo_color_hex",
            "reference_halo_thickness_px",
        }
    ),
    "axes": frozenset(
        {
            "enabled",
            "length_m",
            "thickness_px",
            "label_font_size_px",
            "colors_hex",
            "halo_color_hex",
            "halo_thickness_px",
            "tip_length",
            "label_offset_px",
            "origin_color_hex",
            "origin_radius_px",
        }
    ),
}
"""配置契约允许出现的表和字段。"""

_HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
"""六位 RGB 十六进制颜色格式。"""


@dataclass(frozen=True, slots=True)
class SelectionSettings:
    """连续轨迹网格的样本选择参数。"""

    columns: int
    """默认输出列数。"""

    frame_step: int
    """相邻列之间的已保存样本间隔。"""

    start_sample_id: str | None
    """默认首列保存帧序号；为空时自动寻找最早完整序列。"""

    row_keys: tuple[str, ...]
    """每个可见行对应的数据源稳定键及其顺序。"""

    rows: tuple[str, ...]
    """与 row_keys 一一对应的可见行标题，按原样显示。"""


@dataclass(frozen=True, slots=True)
class LayoutSettings:
    """连续轨迹网格的版式参数。"""

    cell_width: int
    """每个图像单元的宽度，单位像素。"""

    column_label: str
    """顶部列标题模式。"""

    label_font_size: int
    """左侧行名字号，单位像素。"""

    column_font_size: int
    """顶部列标题字号，单位像素。"""

    label_padding_px: int
    """行名文字左右合计留白，单位像素。"""

    label_min_width_px: int
    """行名区域允许的最小宽度，单位像素。"""

    gutter_px: int
    """相邻图像单元之间的间距，单位像素。"""

    border_thickness_px: int
    """每个图像单元的边框线宽，单位像素。"""

    canvas_color_hex: str
    """网格画布和标签区域的 RGB 十六进制颜色。"""

    border_color_hex: str
    """图像单元边框的 RGB 十六进制颜色。"""

    row_label_color_hex: str
    """左侧行名文字颜色。"""

    column_label_color_hex: str
    """顶部列标题文字颜色。"""

    header_padding_px: int
    """顶部列标题区域在字号之外增加的高度。"""

    row_label_line_spacing_px: int
    """多行行标题的行间距，单位像素。"""


@dataclass(frozen=True, slots=True)
class TimelineSettings:
    """网格相对时间轴的绘制参数。"""

    mode: str
    """时间轴模式，取值为 none、relative-time 或 frame-sequence。"""

    placement: str
    """时间轴位置，取值为 top 或 bottom。"""

    font_size_px: int
    """时间刻度和轴标题字号，单位像素。"""

    color_hex: str
    """轴线、刻度、箭头和文字的 RGB 十六进制颜色。"""

    line_thickness_px: int
    """时间轴主线和刻度线宽，单位像素。"""

    tick_length_px: int
    """每个时间刻度线的长度，单位像素。"""

    padding_px: int
    """图像网格、时间轴文字与画布边缘之间的留白，单位像素。"""

    right_extension_px: int
    """横轴箭头在最后一列右侧额外延伸的长度，单位像素。"""


@dataclass(frozen=True, slots=True)
class CropSettings:
    """原图裁剪参数。"""

    mode: str
    """裁剪模式，取值为 auto 或 fixed。"""

    padding: float
    """自动裁剪相对参考轮廓的额外留白比例。"""

    fixed_xywh: tuple[int, int, int, int] | None
    """固定原图裁剪框；自动模式下为 None。"""

    aspect_ratio: float
    """自动裁剪和网格单元使用的宽高比。"""


@dataclass(frozen=True, slots=True)
class OverlaySettings:
    """半透明手柄模型和轮廓的绘制参数。"""

    model_alpha: float
    """手柄模型填充不透明度。"""

    reference_alpha: float
    """Quest 参考手柄模型的填充不透明度。"""

    fill_mode: str
    """模型填充模式，取值为 texture 或 color。"""

    texture_brightness: float
    """base-color 纹理亮度倍率。"""

    texture_backend: str
    """纹理栅格化后端，取值为 auto、nvdiffrast 或 cpu。"""

    texture_max_size_px: int
    """送入 CUDA renderer 前的纹理最长边；0 表示保留原尺寸。"""

    minimum_component_faces: int
    """保留不连通 mesh 组件所需的最小三角面数量。"""

    model_color_hex: str
    """手柄模型使用的中性 RGB 十六进制颜色。"""

    method_colors_hex: tuple[str, str, str, str]
    """Arrival、Capture、One-Euro、EgoAnchor 的论文轮廓颜色。"""

    method_contour_thickness_px: int
    """四种方法彩色轮廓的线宽，单位像素。"""

    reference_contour_color_hex: str
    """Quest Reference 内轮廓颜色。"""

    reference_contour_thickness_px: int
    """Quest Reference 内轮廓线宽。"""

    reference_halo_color_hex: str
    """Quest Reference 外沿 halo 颜色。"""

    reference_halo_thickness_px: int
    """Quest Reference 外沿 halo 总线宽。"""


@dataclass(frozen=True, slots=True)
class AxesSettings:
    """局部 XYZ 坐标轴的绘制参数。"""

    enabled: bool
    """是否绘制局部 XYZ 坐标轴。"""

    length_m: float
    """每根坐标轴的长度，单位米。"""

    thickness_px: int
    """坐标轴线宽，单位像素。"""

    label_font_size_px: int
    """XYZ 轴端标签字号，单位像素。"""

    colors_hex: tuple[str, str, str]
    """X、Y、Z 三根坐标轴依次使用的 RGB 十六进制颜色。"""

    halo_color_hex: str
    """坐标轴和端点文字的外沿颜色。"""

    halo_thickness_px: int
    """坐标轴和端点文字的外沿总线宽。"""

    tip_length: float
    """箭头尖端长度占整根轴的比例。"""

    label_offset_px: tuple[int, int]
    """XYZ 端点文字相对箭头端点的 x/y 像素偏移。"""

    origin_color_hex: str
    """坐标轴原点圆点颜色。"""

    origin_radius_px: int
    """坐标轴原点圆点半径。"""


@dataclass(frozen=True, slots=True)
class ReplayConfigProvenance:
    """本次解析使用的默认配置和可选覆盖配置来源。"""

    default_path: Path
    """内置默认配置的绝对路径。"""

    default_sha256: str
    """内置默认配置内容的 SHA-256。"""

    custom_path: Path | None
    """显式自定义配置的绝对路径；未指定时为 None。"""

    custom_sha256: str | None
    """显式自定义配置内容的 SHA-256；未指定时为 None。"""


@dataclass(frozen=True, slots=True)
class ReplaySettings:
    """定性 replay 的完整强类型配置。"""

    contract_version: int
    """配置契约版本。"""

    selection: SelectionSettings
    """样本选择参数。"""

    layout: LayoutSettings
    """网格版式参数。"""

    timeline: TimelineSettings
    """网格相对时间轴参数。"""

    crop: CropSettings
    """图像裁剪参数。"""

    overlay: OverlaySettings
    """模型填充和轮廓参数。"""

    axes: AxesSettings
    """局部 XYZ 坐标轴参数。"""

    provenance: ReplayConfigProvenance
    """默认配置和自定义配置的来源记录。"""


def load_replay_settings(config_path: str | Path | None = None) -> ReplaySettings:
    """加载内置配置，并受控合并可选自定义 TOML。

    自定义文档可以只包含需要覆盖的表和字段。加载器会在合并前拒绝
    未知表和未知字段，并在合并后执行完整类型与语义校验。
    """

    default_path = DEFAULT_REPLAY_CONFIG_PATH.resolve()
    default_document, default_sha256 = _read_document(default_path)
    _validate_document_shape(default_document, default_path)

    custom_path: Path | None = None
    custom_sha256: str | None = None
    resolved_document = default_document
    if config_path is not None:
        custom_path = Path(config_path).expanduser().resolve()
        custom_document, custom_sha256 = _read_document(custom_path)
        _validate_document_shape(custom_document, custom_path)
        resolved_document = _merge_documents(default_document, custom_document)

    provenance = ReplayConfigProvenance(
        default_path=default_path,
        default_sha256=default_sha256,
        custom_path=custom_path,
        custom_sha256=custom_sha256,
    )
    return _parse_settings(resolved_document, provenance)


def _read_document(path: Path) -> tuple[dict[str, Any], str]:
    """读取一个 TOML 文档并同时计算原始字节的 SHA-256。"""

    if not path.is_file():
        raise FileNotFoundError(f"定性 replay 配置不存在：{path}")
    content = path.read_bytes()
    document = tomllib.loads(content.decode("utf-8"))
    return document, hashlib.sha256(content).hexdigest()


def _validate_document_shape(document: Mapping[str, Any], source: Path) -> None:
    """拒绝配置契约之外的表、字段和非表根值。"""

    unknown_tables = sorted(set(document) - set(_TABLE_KEYS))
    if unknown_tables:
        raise ValueError(f"{source} 包含未知配置表：{unknown_tables}")
    for table_name, raw_table in document.items():
        if not isinstance(raw_table, dict):
            raise ValueError(f"{source} 的 [{table_name}] 必须是 TOML 表")
        unknown_keys = sorted(set(raw_table) - set(_TABLE_KEYS[table_name]))
        if unknown_keys:
            raise ValueError(
                f"{source} 的 [{table_name}] 包含未知字段：{unknown_keys}"
            )


def _merge_documents(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    """只在已通过字段检查的配置表内递归合并覆盖值。"""

    merged = copy.deepcopy(dict(base))
    for table_name, raw_table in override.items():
        table = merged.setdefault(table_name, {})
        if not isinstance(table, dict) or not isinstance(raw_table, dict):
            raise ValueError(f"[{table_name}] 必须是 TOML 表")
        table.update(copy.deepcopy(raw_table))
    return merged


def _parse_settings(
    document: Mapping[str, Any],
    provenance: ReplayConfigProvenance,
) -> ReplaySettings:
    """把完整合并文档解析为强类型配置并执行语义校验。"""

    contract = _table(document, "contract")
    selection = _table(document, "selection")
    layout = _table(document, "layout")
    timeline = _table(document, "timeline")
    crop = _table(document, "crop")
    overlay = _table(document, "overlay")
    axes = _table(document, "axes")

    contract_version = _integer(contract, "version")
    if contract_version != 1:
        raise ValueError("定性 replay 只接受配置契约 v1")

    columns = _integer(selection, "columns")
    if not 2 <= columns <= 20:
        raise ValueError("selection.columns 必须位于 2 到 20")
    frame_step = _integer(selection, "frame_step")
    if frame_step <= 0:
        raise ValueError("selection.frame_step 必须为正整数")
    start_sample_id = _optional_text(selection, "start_sample_id")
    if start_sample_id and not start_sample_id.isdecimal():
        raise ValueError("selection.start_sample_id 必须为空或仅包含十进制数字")
    row_keys = _row_keys(selection)
    rows = _rows(selection)
    if len(rows) != len(row_keys):
        raise ValueError("selection.rows 与 selection.row_keys 必须等长")

    cell_width = _integer(layout, "cell_width")
    if cell_width < 120:
        raise ValueError("layout.cell_width 不能小于 120")
    column_label = _text(layout, "column_label")
    if column_label not in COLUMN_LABEL_MODES:
        raise ValueError(f"layout.column_label 必须是 {COLUMN_LABEL_MODES} 之一")
    label_font_size = _font_size(layout, "label_font_size")
    column_font_size = _font_size(layout, "column_font_size")
    label_padding_px = _bounded_integer(
        layout,
        "label_padding_px",
        minimum=0,
        maximum=64,
    )
    label_min_width_px = _bounded_integer(
        layout,
        "label_min_width_px",
        minimum=0,
        maximum=512,
    )
    gutter_px = _bounded_integer(layout, "gutter_px", minimum=0, maximum=64)
    border_thickness_px = _bounded_integer(
        layout,
        "border_thickness_px",
        minimum=0,
        maximum=16,
    )
    canvas_color_hex = _hex_color(layout, "canvas_color_hex")
    border_color_hex = _hex_color(layout, "border_color_hex")
    row_label_color_hex = _hex_color(layout, "row_label_color_hex")
    column_label_color_hex = _hex_color(layout, "column_label_color_hex")
    header_padding_px = _bounded_integer(
        layout, "header_padding_px", minimum=0, maximum=96
    )
    row_label_line_spacing_px = _bounded_integer(
        layout, "row_label_line_spacing_px", minimum=0, maximum=32
    )

    timeline_mode = _text(timeline, "mode")
    if timeline_mode not in TIMELINE_MODES:
        raise ValueError(f"timeline.mode 必须是 {TIMELINE_MODES} 之一")
    timeline_placement = _text(timeline, "placement")
    if timeline_placement not in TIMELINE_PLACEMENTS:
        raise ValueError(
            f"timeline.placement 必须是 {TIMELINE_PLACEMENTS} 之一"
        )
    timeline_font_size_px = _bounded_integer(
        timeline, "font_size_px", minimum=8, maximum=96
    )
    timeline_color_hex = _hex_color(timeline, "color_hex")
    timeline_line_thickness_px = _bounded_integer(
        timeline, "line_thickness_px", minimum=1, maximum=20
    )
    timeline_tick_length_px = _bounded_integer(
        timeline, "tick_length_px", minimum=1, maximum=64
    )
    timeline_padding_px = _bounded_integer(
        timeline, "padding_px", minimum=0, maximum=96
    )
    timeline_right_extension_px = _bounded_integer(
        timeline, "right_extension_px", minimum=0, maximum=256
    )


    crop_mode = _text(crop, "mode")
    if crop_mode not in {"auto", "fixed"}:
        raise ValueError("crop.mode 必须是 auto 或 fixed")
    crop_padding = _number(crop, "padding")
    if not 0.0 <= crop_padding <= 2.0:
        raise ValueError("crop.padding 必须位于 0 到 2")
    fixed_xywh = _fixed_crop(crop, crop_mode)
    crop_aspect_ratio = _number(crop, "aspect_ratio")
    if not 0.25 <= crop_aspect_ratio <= 4.0:
        raise ValueError("crop.aspect_ratio 必须位于 0.25 到 4.0")

    model_alpha = _number(overlay, "model_alpha")
    if not 0.0 <= model_alpha <= 1.0:
        raise ValueError("overlay.model_alpha 必须位于 0 到 1")
    reference_alpha = _number(overlay, "reference_alpha")
    if not 0.0 <= reference_alpha <= 1.0:
        raise ValueError("overlay.reference_alpha 必须位于 0 到 1")
    fill_mode = _text(overlay, "fill_mode")
    if fill_mode not in {"texture", "color"}:
        raise ValueError("overlay.fill_mode 必须是 texture 或 color")
    texture_brightness = _number(overlay, "texture_brightness")
    if not 0.0 <= texture_brightness <= 3.0:
        raise ValueError("overlay.texture_brightness 必须位于 0 到 3")
    texture_backend = _text(overlay, "texture_backend")
    if texture_backend not in TEXTURE_RENDER_BACKENDS:
        raise ValueError(f"overlay.texture_backend 必须是 {TEXTURE_RENDER_BACKENDS} 之一")
    texture_max_size_px = _integer(overlay, "texture_max_size_px")
    if texture_max_size_px != 0 and not 64 <= texture_max_size_px <= 4096:
        raise ValueError("overlay.texture_max_size_px 必须为 0 或位于 64 到 4096")
    minimum_component_faces = _bounded_integer(
        overlay, "minimum_component_faces", minimum=1, maximum=1000
    )
    model_color_hex = _hex_color(overlay, "model_color_hex")
    method_colors = _color_sequence(overlay, "method_colors_hex", count=4)
    method_colors_hex = (
        method_colors[0],
        method_colors[1],
        method_colors[2],
        method_colors[3],
    )
    method_contour_thickness_px = _positive_pixel_value(
        overlay, "method_contour_thickness_px"
    )
    reference_contour_color_hex = _hex_color(overlay, "reference_contour_color_hex")
    reference_contour_thickness_px = _positive_pixel_value(
        overlay, "reference_contour_thickness_px"
    )
    reference_halo_color_hex = _hex_color(overlay, "reference_halo_color_hex")
    reference_halo_thickness_px = _positive_pixel_value(
        overlay, "reference_halo_thickness_px"
    )
    if reference_halo_thickness_px < reference_contour_thickness_px:
        raise ValueError("reference_halo_thickness_px 不能小于 reference_contour_thickness_px")

    axes_enabled = _boolean(axes, "enabled")
    axes_length_m = _number(axes, "length_m")
    if not 0.001 <= axes_length_m <= 1.0:
        raise ValueError("axes.length_m 必须位于 0.001 到 1.0 m")
    axes_thickness_px = _positive_pixel_value(axes, "thickness_px")
    axes_label_font_size_px = _bounded_integer(
        axes,
        "label_font_size_px",
        minimum=8,
        maximum=96,
    )
    axes_colors_hex = _color_triplet(axes, "colors_hex")
    axes_halo_color_hex = _hex_color(axes, "halo_color_hex")
    axes_halo_thickness_px = _positive_pixel_value(axes, "halo_thickness_px")
    if axes_halo_thickness_px < axes_thickness_px:
        raise ValueError("axes.halo_thickness_px 不能小于 axes.thickness_px")
    axes_tip_length = _number(axes, "tip_length")
    if not 0.05 <= axes_tip_length <= 0.5:
        raise ValueError("axes.tip_length 必须位于 0.05 到 0.5")
    axes_label_offset_px = _integer_pair(axes, "label_offset_px", minimum=-64, maximum=64)
    axes_origin_color_hex = _hex_color(axes, "origin_color_hex")
    axes_origin_radius_px = _bounded_integer(
        axes, "origin_radius_px", minimum=1, maximum=32
    )

    return ReplaySettings(
        contract_version=contract_version,
        selection=SelectionSettings(
            columns=columns,
            frame_step=frame_step,
            start_sample_id=start_sample_id or None,
            row_keys=row_keys,
            rows=rows,
        ),
        layout=LayoutSettings(
            cell_width=cell_width,
            column_label=column_label,
            label_font_size=label_font_size,
            column_font_size=column_font_size,
            label_padding_px=label_padding_px,
            label_min_width_px=label_min_width_px,
            gutter_px=gutter_px,
            border_thickness_px=border_thickness_px,
            canvas_color_hex=canvas_color_hex,
            border_color_hex=border_color_hex,
            row_label_color_hex=row_label_color_hex,
            column_label_color_hex=column_label_color_hex,
            header_padding_px=header_padding_px,
            row_label_line_spacing_px=row_label_line_spacing_px,
        ),
        timeline=TimelineSettings(
            mode=timeline_mode,
            placement=timeline_placement,
            font_size_px=timeline_font_size_px,
            color_hex=timeline_color_hex,
            line_thickness_px=timeline_line_thickness_px,
            tick_length_px=timeline_tick_length_px,
            padding_px=timeline_padding_px,
            right_extension_px=timeline_right_extension_px,
        ),
        crop=CropSettings(
            mode=crop_mode,
            padding=crop_padding,
            fixed_xywh=fixed_xywh,
            aspect_ratio=crop_aspect_ratio,
        ),
        overlay=OverlaySettings(
            model_alpha=model_alpha,
            reference_alpha=reference_alpha,
            fill_mode=fill_mode,
            texture_brightness=texture_brightness,
            texture_backend=texture_backend,
            texture_max_size_px=texture_max_size_px,
            minimum_component_faces=minimum_component_faces,
            model_color_hex=model_color_hex,
            method_colors_hex=method_colors_hex,
            method_contour_thickness_px=method_contour_thickness_px,
            reference_contour_color_hex=reference_contour_color_hex,
            reference_contour_thickness_px=reference_contour_thickness_px,
            reference_halo_color_hex=reference_halo_color_hex,
            reference_halo_thickness_px=reference_halo_thickness_px,
        ),
        axes=AxesSettings(
            enabled=axes_enabled,
            length_m=axes_length_m,
            thickness_px=axes_thickness_px,
            label_font_size_px=axes_label_font_size_px,
            colors_hex=axes_colors_hex,
            halo_color_hex=axes_halo_color_hex,
            halo_thickness_px=axes_halo_thickness_px,
            tip_length=axes_tip_length,
            label_offset_px=axes_label_offset_px,
            origin_color_hex=axes_origin_color_hex,
            origin_radius_px=axes_origin_radius_px,
        ),
        provenance=provenance,
    )


def _table(document: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    """读取合并后必须存在的 TOML 表。"""

    value = document.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"定性 replay 配置缺少 [{name}] 表")
    return value


def _integer(table: Mapping[str, Any], key: str) -> int:
    """读取必须为整数且不能是布尔值的字段。"""

    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"配置字段 {key} 必须为整数")
    return value


def _number(table: Mapping[str, Any], key: str) -> float:
    """读取必须为有限数值且不能是布尔值的字段。"""

    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"配置字段 {key} 必须为数值")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"配置字段 {key} 必须为有限数值")
    return result


def _text(table: Mapping[str, Any], key: str) -> str:
    """读取必须为非空字符串的字段。"""

    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"配置字段 {key} 必须为非空字符串")
    return value


def _optional_text(table: Mapping[str, Any], key: str) -> str:
    """读取允许为空字符串的文本字段。"""

    value = table.get(key)
    if not isinstance(value, str):
        raise ValueError(f"配置字段 {key} 必须为字符串")
    return value


def _boolean(table: Mapping[str, Any], key: str) -> bool:
    """读取必须为布尔值的字段。"""

    value = table.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"配置字段 {key} 必须为布尔值")
    return value


def _row_keys(table: Mapping[str, Any]) -> tuple[str, ...]:
    """读取每个可见行对应的数据源稳定键。"""

    raw_row_keys = table.get("row_keys")
    if not isinstance(raw_row_keys, list) or not raw_row_keys:
        raise ValueError("selection.row_keys 必须是非空字符串数组")
    if any(not isinstance(row, str) for row in raw_row_keys):
        raise ValueError("selection.row_keys 必须只包含字符串")
    row_keys = tuple(raw_row_keys)
    unknown = [row for row in row_keys if row not in REPLAY_ROW_KEYS]
    if unknown:
        raise ValueError(f"selection.row_keys 包含未知行：{unknown}")
    if len(set(row_keys)) != len(row_keys):
        raise ValueError("selection.row_keys 不能包含重复行")
    return row_keys


def _rows(table: Mapping[str, Any]) -> tuple[str, ...]:
    """读取按原样绘制的可见行标题。"""

    raw_rows = table.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("selection.rows 必须是非空字符串数组")
    if any(not isinstance(title, str) or not title.strip() for title in raw_rows):
        raise ValueError("selection.rows 的每项都必须是非空字符串")
    rows = tuple(str(title) for title in raw_rows)
    if any(any(not line.strip() for line in title.split("\n")) for title in rows):
        raise ValueError("selection.rows 不允许空白行")
    return rows


def _font_size(table: Mapping[str, Any], key: str) -> int:
    """读取范围为 8--96 的字体大小。"""

    value = _integer(table, key)
    if not 8 <= value <= 96:
        raise ValueError(f"layout.{key} 必须位于 8 到 96")
    return value


def _bounded_integer(
    table: Mapping[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """读取位于闭区间内的整数配置。"""

    value = _integer(table, key)
    if not minimum <= value <= maximum:
        raise ValueError(f"配置字段 {key} 必须位于 {minimum} 到 {maximum}")
    return value


def _integer_pair(
    table: Mapping[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> tuple[int, int]:
    """读取两个位于同一闭区间内的整数。"""

    raw_value = table.get(key)
    if not isinstance(raw_value, list) or len(raw_value) != 2:
        raise ValueError(f"配置字段 {key} 必须恰好包含两个整数")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in raw_value):
        raise ValueError(f"配置字段 {key} 必须恰好包含两个整数")
    x, y = raw_value
    if not minimum <= x <= maximum or not minimum <= y <= maximum:
        raise ValueError(f"配置字段 {key} 的每项必须位于 {minimum} 到 {maximum}")
    return x, y


def _hex_color(table: Mapping[str, Any], key: str) -> str:
    """读取并规范化一个 #RRGGBB 颜色。"""

    value = _text(table, key)
    if _HEX_COLOR_PATTERN.fullmatch(value) is None:
        raise ValueError(f"配置字段 {key} 必须是 #RRGGBB 格式")
    return value.upper()


def _color_triplet(
    table: Mapping[str, Any],
    key: str,
) -> tuple[str, str, str]:
    """读取固定包含 X、Y、Z 三种颜色的数组。"""

    colors = _color_sequence(table, key, count=3)
    return colors[0], colors[1], colors[2]


def _color_sequence(
    table: Mapping[str, Any],
    key: str,
    *,
    count: int,
) -> tuple[str, ...]:
    """读取固定数量的 RGB 十六进制颜色。"""

    raw_value = table.get(key)
    if not isinstance(raw_value, list) or len(raw_value) != count:
        raise ValueError(f"配置字段 {key} 必须恰好包含 {count} 个颜色")
    colors: list[str] = []
    for value in raw_value:
        if not isinstance(value, str) or _HEX_COLOR_PATTERN.fullmatch(value) is None:
            raise ValueError(f"配置字段 {key} 的每项都必须是 #RRGGBB 格式")
        colors.append(value.upper())
    return tuple(colors)


def _fixed_crop(
    table: Mapping[str, Any],
    mode: str,
) -> tuple[int, int, int, int] | None:
    """读取固定裁剪框，并拒绝与裁剪模式矛盾的配置。"""

    raw_value = table.get("fixed_xywh")
    if not isinstance(raw_value, list):
        raise ValueError("crop.fixed_xywh 必须为整数数组")
    if mode == "auto":
        if raw_value:
            raise ValueError("crop.mode=auto 时 fixed_xywh 必须留空")
        return None
    if len(raw_value) != 4 or any(
        isinstance(value, bool) or not isinstance(value, int) for value in raw_value
    ):
        raise ValueError("crop.mode=fixed 时 fixed_xywh 必须包含四个整数")
    x, y, width, height = raw_value
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("crop.fixed_xywh 要求 x/y 非负且 width/height 为正")
    return x, y, width, height


def _positive_pixel_value(table: Mapping[str, Any], key: str) -> int:
    """读取范围为 1--20 的像素线宽。"""

    value = _integer(table, key)
    if not 1 <= value <= 20:
        raise ValueError(f"配置字段 {key} 必须位于 1 到 20")
    return value


__all__ = [
    "AxesSettings",
    "COLUMN_LABEL_MODES",
    "CropSettings",
    "DEFAULT_REPLAY_CONFIG_PATH",
    "LayoutSettings",
    "OverlaySettings",
    "REPLAY_ROW_KEYS",
    "ReplayConfigProvenance",
    "ReplaySettings",
    "SelectionSettings",
    "TIMELINE_MODES",
    "TIMELINE_PLACEMENTS",
    "TimelineSettings",
    "load_replay_settings",
]
