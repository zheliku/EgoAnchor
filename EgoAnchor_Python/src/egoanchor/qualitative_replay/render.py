"""轻量 CPU mesh 重投影、单帧校验和六行连续轨迹网格。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence, cast

import cv2
import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont

from .contracts import ReplayCapture, ReplaySample, VARIANT_IDS
from .geometry import recorded_projection_matrix, verify_projection_matrix


ROW_IDS = ("rgb", "quest_reference", *VARIANT_IDS)
"""六行固定顺序：原图、Quest 平台参考和四种实验一方法。"""

ROW_LABELS = (
    "Input RGB",
    "Quest Reference",
    "Arrival-Hold",
    "Capture-Hold",
    "One-Euro Interp.",
    "EgoAnchor",
)
"""论文网格左侧显示的稳定英文行名。"""

REFERENCE_COLOR = (45, 45, 45)
"""Quest 官方参考使用的中性深灰，避免与蓝绿橙红四方法混淆。"""


@dataclass(frozen=True, slots=True)
class GridColumn:
    """一列同步样本的图像、五个投影 mask 和统一裁剪框。"""

    sample_index: int
    """样本在 capture 中的零基索引。"""

    sample: ReplaySample
    """该列使用的原子 replay 样本。"""

    background: np.ndarray
    """该列左目 RGB。"""

    masks: tuple[np.ndarray, ...]
    """Quest 参考和四方法 mask，顺序与后五行一致。"""

    crop: tuple[int, int, int, int]
    """同列六行共享的 x、y、width、height。"""


class MeshProjector:
    """把原始对象 mesh 按 OpenCV object-in-camera pose 栅格化成二值轮廓。"""

    def __init__(self, mesh_path: str | Path, *, apply_scale: float = 1.0) -> None:
        """加载 scene-aware mesh，并缓存 vertices/faces 供多帧复用。"""

        path = Path(mesh_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"replay mesh 不存在: {path}")
        loaded = trimesh.load(path, force="scene", process=False)
        if isinstance(loaded, trimesh.Scene):
            scene = loaded
            if not scene.geometry:
                raise ValueError(f"replay mesh scene 不含几何体: {path}")
            try:
                mesh = cast(trimesh.Trimesh, scene.to_geometry())
            except AttributeError:
                mesh = cast(trimesh.Trimesh, cast(Any, scene).dump(concatenate=True))
        elif isinstance(loaded, trimesh.Trimesh):
            mesh = loaded
        else:
            raise ValueError(f"replay mesh 类型不受支持: {type(loaded).__name__}")
        mesh.apply_scale(float(apply_scale))
        self.vertices = np.asarray(mesh.vertices, dtype=np.float64)
        """原始对象坐标系顶点。"""
        self.faces = np.asarray(mesh.faces, dtype=np.int64)
        """三角面索引。"""
        if self.vertices.ndim != 2 or self.vertices.shape[1] != 3:
            raise ValueError(f"replay mesh 顶点格式不合法: {path}")
        if self.faces.ndim != 2 or self.faces.shape[1] != 3:
            raise ValueError(f"replay mesh 必须是三角网格: {path}")

    @classmethod
    def from_arrays(cls, vertices: np.ndarray, faces: np.ndarray) -> "MeshProjector":
        """从数组构造测试用 projector，不经过文件加载。"""

        instance = cls.__new__(cls)
        instance.vertices = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
        instance.faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
        return instance

    def project_mask(
        self,
        pose_cv_camera: np.ndarray,
        camera_matrix: np.ndarray,
        image_width: int,
        image_height: int,
    ) -> np.ndarray:
        """用三角形并集栅格化投影 silhouette，不依赖 CUDA/OpenGL。"""

        pose = np.asarray(pose_cv_camera, dtype=np.float64).reshape(4, 4)
        camera = np.asarray(camera_matrix, dtype=np.float64).reshape(3, 3)
        width = int(image_width)
        height = int(image_height)
        if width <= 0 or height <= 0:
            raise ValueError("投影图像尺寸必须为正数。")

        points_camera = self.vertices @ pose[:3, :3].T + pose[:3, 3]
        z = points_camera[:, 2]
        valid_vertices = np.isfinite(points_camera).all(axis=1) & (z > 1e-4)
        normalized = np.zeros((len(points_camera), 2), dtype=np.float64)
        normalized[valid_vertices] = points_camera[valid_vertices, :2] / z[valid_vertices, None]
        projected = normalized @ camera[:2, :2].T + camera[:2, 2]
        valid_faces = valid_vertices[self.faces].all(axis=1)
        if not np.any(valid_faces):
            return np.zeros((height, width), dtype=np.uint8)

        polygons = projected[self.faces[valid_faces]]
        limit = float(max(width, height) * 16)
        polygons = np.clip(np.rint(polygons), -limit, limit).astype(np.int32)
        mask = np.zeros((height, width), dtype=np.uint8)
        cv2.fillPoly(mask, cast(Any, polygons), 255, lineType=cv2.LINE_8)
        return mask


def render_frame_overlays(
    capture: ReplayCapture,
    projector: MeshProjector,
    output_dir: str | Path,
    *,
    sample_id: str | None = None,
    fill_alpha: float = 0.20,
    contour_thickness: int = 3,
) -> dict[str, Path]:
    """输出原图、Quest 官方参考和四种方法，供首次像素贴合检查。"""

    sample = _resolve_frame_sample(capture.samples, sample_id)
    background = _load_rgb(sample.image_path)
    height, width = background.shape[:2]
    masks = _project_sample_masks(sample, projector, width, height)
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    rgb_path = output / f"{sample.sample_id}_rgb.png"
    _write_rgb_png(rgb_path, background)
    paths["rgb"] = rgb_path

    reference_path = output / f"{sample.sample_id}_quest_reference.png"
    _write_rgb_png(reference_path, _overlay_reference(background, masks[0], contour_thickness))
    paths["quest_reference"] = reference_path

    for variant, mask in zip(sample.variants, masks[1:], strict=True):
        variant_id = str(variant["variant_id"])
        image = _overlay_single(
            background,
            mask,
            _hex_to_rgb(str(variant["color_hex"])),
            fill_alpha=fill_alpha,
            contour_thickness=contour_thickness,
        )
        path = output / f"{sample.sample_id}_{variant_id}.png"
        _write_rgb_png(path, image)
        paths[variant_id] = path
    return paths


def render_comparison_grid(
    capture: ReplayCapture,
    projector: MeshProjector,
    output_dir: str | Path,
    *,
    columns: int = 8,
    frame_step: int = 3,
    start_sample_id: str | None = None,
    cell_width: int = 320,
    crop_padding: float = 0.35,
) -> dict[str, Path]:
    """生成 5-10 列、六行的连续轨迹论文网格。

    列按 capture 样本顺序以固定 ``frame_step`` 取样，不按误差或抖动大小挑帧。
    每列六行共享同一张 RGB、相机内参和 reference-centered crop。
    """

    if not 5 <= int(columns) <= 10:
        raise ValueError("columns 必须位于 5 到 10。")
    if int(frame_step) <= 0:
        raise ValueError("frame_step 必须为正整数。")
    if int(cell_width) < 120:
        raise ValueError("cell_width 不能小于 120。")
    if not 0.0 <= float(crop_padding) <= 2.0:
        raise ValueError("crop_padding 必须位于 0 到 2。")

    selected = select_stride_samples(
        capture.samples,
        columns=int(columns),
        frame_step=int(frame_step),
        start_sample_id=start_sample_id,
    )
    prepared: list[tuple[int, ReplaySample, np.ndarray, tuple[np.ndarray, ...]]] = []
    for sample_index, sample in selected:
        background = _load_rgb(sample.image_path)
        height, width = background.shape[:2]
        masks = _project_sample_masks(sample, projector, width, height)
        prepared.append((sample_index, sample, background, masks))

    crops = _compute_shared_crops(prepared, padding=float(crop_padding))
    grid_columns = tuple(
        GridColumn(index, sample, background, masks, crop)
        for (index, sample, background, masks), crop in zip(prepared, crops, strict=True)
    )
    sheet = _compose_grid(grid_columns, capture, cell_width=int(cell_width))

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    image_path = output / "replay_grid.png"
    metadata_path = output / "replay_grid.json"
    _write_rgb_png(image_path, sheet)
    metadata = {
        "capture_id": capture.manifest.capture_id,
        "selection": "consecutive saved replay samples at a fixed frame_step; no error-based selection",
        "columns": int(columns),
        "frame_step": int(frame_step),
        "row_ids": list(ROW_IDS),
        "row_labels": list(ROW_LABELS),
        "variant_colors_hex": list(capture.manifest.variant_colors_hex),
        "reference_color_hex": "#2D2D2D",
        "crop_semantics": "reference-centered; fixed crop size across columns; one crop shared by all six rows",
        "samples": [
            {
                "sample_index": column.sample_index,
                "sample_id": column.sample.sample_id,
                "image_unity_frame": column.sample.image_unity_frame,
                "image_mono_ms": column.sample.image_mono_ms,
                "relative_time_ms": column.sample.image_mono_ms - capture.samples[0].image_mono_ms,
                "reference_pose_source": column.sample.platform_reference["pose_source"],
                "crop_xywh": list(column.crop),
            }
            for column in grid_columns
        ],
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"grid": image_path, "metadata": metadata_path}


def select_stride_samples(
    samples: Sequence[ReplaySample],
    *,
    columns: int,
    frame_step: int,
    start_sample_id: str | None = None,
) -> tuple[tuple[int, ReplaySample], ...]:
    """按固定已保存帧间隔选择一段六行数据完整的连续序列。"""

    if not 5 <= int(columns) <= 10:
        raise ValueError("columns 必须位于 5 到 10。")
    if int(frame_step) <= 0:
        raise ValueError("frame_step 必须为正整数。")
    span = (int(columns) - 1) * int(frame_step) + 1
    if len(samples) < span:
        raise ValueError(f"capture 样本不足：至少需要 {span} 帧，当前 {len(samples)} 帧。")

    if start_sample_id is not None:
        starts = [index for index, sample in enumerate(samples) if sample.sample_id == start_sample_id]
        if not starts:
            raise KeyError(f"未知 replay sample_id: {start_sample_id}")
    else:
        starts = list(range(0, len(samples) - span + 1))

    for start in starts:
        indices = tuple(start + offset * int(frame_step) for offset in range(int(columns)))
        if indices[-1] >= len(samples):
            break
        chosen = tuple((index, samples[index]) for index in indices)
        if all(_is_complete_grid_sample(sample) for _, sample in chosen):
            return chosen
        if start_sample_id is not None:
            break
    if start_sample_id is not None:
        raise ValueError("指定起点和 frame_step 对应的序列存在无效参考或缺少方法显示 pose。")
    raise ValueError("capture 中找不到满足给定 columns/frame_step 的完整连续序列。")


def _is_complete_grid_sample(sample: ReplaySample) -> bool:
    """判断样本能否生成六行；fresh 和 held 平台参考都视为有效。"""

    return sample.platform_reference.get("valid") is True and all(
        variant.get("has_display_pose") is True for variant in sample.variants
    )


def _project_sample_masks(
    sample: ReplaySample,
    projector: MeshProjector,
    width: int,
    height: int,
) -> tuple[np.ndarray, ...]:
    """投影同一列的 Quest 参考和四方法，并拒绝不可见轮廓。"""

    if not _is_complete_grid_sample(sample):
        raise ValueError(f"sample {sample.sample_id} 六行数据不完整。")
    camera_matrix = _camera_matrix(sample)
    reference = sample.platform_reference
    reference_mask = projector.project_mask(
        recorded_projection_matrix(reference),
        camera_matrix,
        width,
        height,
    )
    masks = [reference_mask]
    for variant in sample.variants:
        verify_projection_matrix(sample.camera["world_pose"], variant)
        masks.append(
            projector.project_mask(
                recorded_projection_matrix(variant),
                camera_matrix,
                width,
                height,
            )
        )
    empty = [ROW_IDS[index + 1] for index, mask in enumerate(masks) if not np.any(mask)]
    if empty:
        raise ValueError(f"sample {sample.sample_id} 的投影不在图像内: {empty}")
    return tuple(masks)


def _compute_shared_crops(
    prepared: Sequence[tuple[int, ReplaySample, np.ndarray, tuple[np.ndarray, ...]]],
    *,
    padding: float,
) -> tuple[tuple[int, int, int, int], ...]:
    """以每列参考质心为中心，求跨列统一大小的 4:3 裁剪框。"""

    centers: list[np.ndarray] = []
    required_half_width = 1.0
    required_half_height = 1.0
    image_height, image_width = prepared[0][2].shape[:2]
    for _, sample, background, masks in prepared:
        if background.shape[:2] != (image_height, image_width):
            raise ValueError(f"sample {sample.sample_id} 图像尺寸与序列其他列不一致。")
        center = _mask_centroid(masks[0])
        centers.append(center)
        union = np.any(np.stack([mask > 0 for mask in masks], axis=0), axis=0)
        y, x = np.nonzero(union)
        required_half_width = max(required_half_width, float(np.max(np.abs(x - center[0]))))
        required_half_height = max(required_half_height, float(np.max(np.abs(y - center[1]))))

    crop_width = int(np.ceil(required_half_width * 2.0 * (1.0 + padding)))
    crop_height = int(np.ceil(required_half_height * 2.0 * (1.0 + padding)))
    aspect = 4.0 / 3.0
    if crop_width / max(crop_height, 1) < aspect:
        crop_width = int(np.ceil(crop_height * aspect))
    else:
        crop_height = int(np.ceil(crop_width / aspect))
    crop_width = min(image_width, max(32, crop_width))
    crop_height = min(image_height, max(24, crop_height))
    return tuple(
        _centered_crop(center, crop_width, crop_height, image_width, image_height)
        for center in centers
    )


def _centered_crop(
    center: np.ndarray,
    width: int,
    height: int,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    """把固定大小裁剪框限制在图像边界内。"""

    x = int(round(float(center[0]) - width * 0.5))
    y = int(round(float(center[1]) - height * 0.5))
    x = min(max(0, x), image_width - width)
    y = min(max(0, y), image_height - height)
    return x, y, width, height


def _compose_grid(
    columns: Sequence[GridColumn],
    capture: ReplayCapture,
    *,
    cell_width: int,
) -> np.ndarray:
    """把六行同步 crop 排成带行名和实际时间的白底论文图。"""

    crop_width = columns[0].crop[2]
    crop_height = columns[0].crop[3]
    cell_height = max(90, int(round(cell_width * crop_height / crop_width)))
    label_width = 190
    header_height = 44
    gutter = 4
    sheet_width = label_width + len(columns) * cell_width + (len(columns) - 1) * gutter
    sheet_height = header_height + len(ROW_IDS) * cell_height + (len(ROW_IDS) - 1) * gutter
    sheet = Image.new("RGB", (sheet_width, sheet_height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    label_font = _load_font(22)
    time_font = _load_font(18)
    status_font = _load_font(12)
    origin_ms = capture.samples[0].image_mono_ms

    for row_index, label in enumerate(ROW_LABELS):
        y = header_height + row_index * (cell_height + gutter)
        _draw_centered_text(draw, (8, y, label_width - 8, y + cell_height), label, label_font)

    for column_index, column in enumerate(columns):
        x = label_width + column_index * (cell_width + gutter)
        relative_seconds = (column.sample.image_mono_ms - origin_ms) / 1000.0
        _draw_centered_text(draw, (x, 0, x + cell_width, header_height), f"t={relative_seconds:.2f}s", time_font)
        crops = _render_column_crops(column, capture)
        for row_index, crop in enumerate(crops):
            y = header_height + row_index * (cell_height + gutter)
            resized = Image.fromarray(crop, mode="RGB").resize(
                (cell_width, cell_height),
                Image.Resampling.LANCZOS,
            )
            sheet.paste(resized, (x, y))
            draw.rectangle((x, y, x + cell_width - 1, y + cell_height - 1), outline=(210, 210, 210), width=1)
            if row_index == 1:
                status = "HELD" if column.sample.platform_reference["keep_alive"] else "LIVE"
                _draw_status_badge(draw, x + 5, y + 5, status, status_font)
    return np.asarray(sheet, dtype=np.uint8)


def _render_column_crops(column: GridColumn, capture: ReplayCapture) -> tuple[np.ndarray, ...]:
    """用一份裁剪框生成该列六行，禁止每个方法独立缩放。"""

    x, y, width, height = column.crop
    background = column.background[y : y + height, x : x + width]
    masks = tuple(mask[y : y + height, x : x + width] for mask in column.masks)
    rows = [background.copy(), _overlay_reference(background, masks[0], 3)]
    for color_hex, mask in zip(capture.manifest.variant_colors_hex, masks[1:], strict=True):
        rows.append(
            _overlay_single(
                background,
                mask,
                _hex_to_rgb(color_hex),
                fill_alpha=0.16,
                contour_thickness=3,
            )
        )
    return tuple(rows)


def _resolve_sample(samples: Sequence[ReplaySample], sample_id: str) -> ReplaySample:
    """按 id 找样本。"""

    for sample in samples:
        if sample.sample_id == sample_id:
            return sample
    raise KeyError(f"未知 replay sample_id: {sample_id}")


def _resolve_frame_sample(samples: Sequence[ReplaySample], sample_id: str | None) -> ReplaySample:
    """显式 id 原样选择；省略时取第一条六行数据完整的样本。"""

    if sample_id is not None:
        return _resolve_sample(samples, sample_id)
    for sample in samples:
        if _is_complete_grid_sample(sample):
            return sample
    raise ValueError("replay capture 中没有平台参考和四种方法同时有效的样本。")


def _camera_matrix(sample: ReplaySample) -> np.ndarray:
    """从样本 camera DTO 构造 K。"""

    camera = sample.camera
    return np.array(
        [
            [float(camera["fx"]), 0.0, float(camera["cx"])],
            [0.0, float(camera["fy"]), float(camera["cy"])],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def _overlay_single(
    background: np.ndarray,
    mask: np.ndarray,
    color: tuple[int, int, int],
    *,
    fill_alpha: float,
    contour_thickness: int,
) -> np.ndarray:
    """叠加单个半透明 silhouette 和实线轮廓。"""

    output = background.copy()
    selected = np.asarray(mask) > 0
    if np.any(selected):
        alpha = float(np.clip(fill_alpha, 0.0, 1.0))
        output[selected] = np.rint(
            output[selected].astype(np.float32) * (1.0 - alpha)
            + np.asarray(color, dtype=np.float32) * alpha
        ).astype(np.uint8)
    return _draw_contours(output, mask, color, max(1, int(contour_thickness)))


def _overlay_reference(background: np.ndarray, mask: np.ndarray, contour_thickness: int) -> np.ndarray:
    """用白色 halo 和深灰内轮廓绘制 Quest 官方参考。"""

    halo = _draw_contours(background, mask, (255, 255, 255), max(3, contour_thickness + 2))
    return _overlay_single(
        halo,
        mask,
        REFERENCE_COLOR,
        fill_alpha=0.10,
        contour_thickness=max(2, contour_thickness),
    )


def _draw_contours(
    image: np.ndarray,
    mask: np.ndarray,
    color: tuple[int, int, int],
    thickness: int,
) -> np.ndarray:
    """只绘制外轮廓，避免填充颜色混浊。"""

    output = image.copy()
    contours, _ = cv2.findContours(
        (np.asarray(mask) > 0).astype(np.uint8),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if contours:
        cv2.drawContours(output, contours, -1, color, int(thickness), cv2.LINE_AA)
    return output


def _mask_centroid(mask: np.ndarray) -> np.ndarray:
    """计算非空 mask 质心。"""

    y, x = np.nonzero(mask)
    if len(x) == 0:
        raise ValueError("空 mask 没有可用质心。")
    return np.array([float(np.mean(x)), float(np.mean(y))], dtype=np.float64)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    """把 #RRGGBB 转为 RGB tuple。"""

    text = value.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"颜色必须是 #RRGGBB: {value}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """优先使用常见无衬线字体，缺失时回退 Pillow 默认字体。"""

    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """在给定矩形内水平和垂直居中文本。"""

    left, top, right, bottom = box
    bounds = draw.textbbox((0, 0), text, font=font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    x = left + (right - left - width) * 0.5
    y = top + (bottom - top - height) * 0.5 - bounds[1]
    draw.text((x, y), text, fill=(25, 25, 25), font=font)


def _draw_status_badge(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """在 Quest Reference 单元内标明当前参考是 LIVE 还是 HELD。"""

    bounds = draw.textbbox((0, 0), text, font=font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    draw.rectangle((x, y, x + width + 8, y + height + 6), fill=(255, 255, 255), outline=(80, 80, 80))
    draw.text((x + 4, y + 3 - bounds[1]), text, fill=(35, 35, 35), font=font)


def _load_rgb(path: Path) -> np.ndarray:
    """无损解码 JPEG 为 RGB uint8。"""

    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8).copy()


def _write_rgb_png(path: Path, image: np.ndarray) -> None:
    """以 PNG 写出 RGB 图，并确保父目录存在。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(image, dtype=np.uint8), mode="RGB").save(
        path,
        format="PNG",
        compress_level=4,
    )


__all__ = [
    "GridColumn",
    "MeshProjector",
    "ROW_IDS",
    "ROW_LABELS",
    "render_comparison_grid",
    "render_frame_overlays",
    "select_stride_samples",
]
