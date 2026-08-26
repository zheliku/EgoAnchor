"""mesh 重投影、单帧校验和六行连续轨迹网格。"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

import cv2
import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont

from egoanchor.visuals import METHOD_COLORS_HEX

from .contracts import ReplayCapture, ReplaySample, VARIANT_IDS
from .geometry import (
    projection_mesh_local_matrix,
    recorded_projection_matrix,
    verify_projection_matrix,
)
from .settings import (
    COLUMN_LABEL_MODES,
    REPLAY_ROW_KEYS,
    TIMELINE_MODES,
    TIMELINE_PLACEMENTS,
    TimelineSettings,
)
from .texture_renderer import NvdiffrastTextureRenderer, TEXTURE_RENDER_BACKENDS


ROW_IDS = ("rgb", "quest_reference", *VARIANT_IDS)
"""六行固定顺序：原图、Quest 平台参考和四种实验一方法。"""

ROW_KEYS = REPLAY_ROW_KEYS
"""CLI、TOML 和 sidecar 使用的稳定行键。"""

ROW_TITLES = {
    "passthrough": "Passthrough",
    "reference": "Quest\nReference",
    "arrival": "Arrival",
    "capture": "Capture",
    "one-euro": "One-Euro",
    "egoanchor": "EgoAnchor",
}
"""论文网格左侧显示的正式英文行名。"""

DEFAULT_ROW_TITLES = tuple(ROW_TITLES[row] for row in ROW_KEYS)
"""六个稳定行键对应的默认可见标题。"""

DEFAULT_AXIS_COLORS_HEX = ("#D62728", "#2CA02C", "#1F77B4")
"""X、Y、Z 轴的默认红、绿、蓝颜色。"""

DEFAULT_METHOD_COLORS_HEX = METHOD_COLORS_HEX
"""与论文图 2 一致的 Arrival、Capture、One-Euro、EgoAnchor 颜色。"""


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

    axes: tuple[np.ndarray, ...]
    """Quest 参考和四方法的投影坐标轴点，每项依次为原点、X、Y、Z 端点。"""

    crop: tuple[int, int, int, int]
    """同列六行共享的 x、y、width、height。"""


@dataclass(frozen=True, slots=True)
class PreparedColumn:
    """完成图像、轮廓和坐标轴投影但尚未确定裁剪框的一列。"""

    sample_index: int
    """样本在 capture 中的零基索引。"""

    sample: ReplaySample
    """该列使用的原子 replay 样本。"""

    background: np.ndarray
    """该列左目 RGB。"""

    masks: tuple[np.ndarray, ...]
    """Quest 参考和四方法 mask。"""

    axes: tuple[np.ndarray, ...]
    """Quest 参考和四方法坐标轴的二维投影点。"""


@dataclass(frozen=True, slots=True)
class TextureLayer:
    """裁剪区域内经过深度测试的 unlit base-color 纹理图层。"""

    rgb: np.ndarray
    """与裁剪区域同尺寸的 RGB 图像。"""

    mask: np.ndarray
    """纹理实际覆盖像素的 uint8 mask。"""


@dataclass(frozen=True, slots=True)
class AxisDrawStyle:
    """XYZ 坐标轴所有可见绘制参数。"""

    colors_hex: tuple[str, str, str]
    """X、Y、Z 轴颜色。"""

    thickness_px: int
    """轴线和文字内层线宽。"""

    label_font_size_px: int
    """XYZ 端点文字目标像素高度。"""

    halo_color_hex: str
    """轴线、箭头和文字外沿颜色。"""

    halo_thickness_px: int
    """轴线和文字外沿总线宽。"""

    tip_length: float
    """箭头尖端长度占轴长的比例。"""

    label_offset_px: tuple[int, int]
    """XYZ 文字相对箭头端点的像素偏移。"""

    origin_color_hex: str
    """坐标轴原点内圆颜色。"""

    origin_radius_px: int
    """坐标轴原点内圆半径。"""


class MeshProjector:
    """把带 UV 纹理的对象 mesh 投影为轮廓或裁剪区域内的纹理图层。"""

    def __init__(
        self,
        mesh_path: str | Path,
        *,
        apply_scale: float = 1.0,
        local_matrix: np.ndarray | None = None,
        minimum_component_faces: int = 1,
    ) -> None:
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
        self.uv, self.texture_rgb, self.texture_source = _extract_mesh_texture(mesh)
        """逐顶点 UV、base-color RGB 和纹理来源；不可用时三者按约定回退。"""
        self.vertex_transform = _validate_local_matrix(local_matrix)
        """FoundationPose mesh 到离线投影局部基的齐次变换。"""
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        homogeneous = np.column_stack([vertices, np.ones(len(vertices), dtype=np.float64)])
        self.vertices = (homogeneous @ self.vertex_transform.T)[:, :3]
        """原始对象坐标系顶点。"""
        raw_faces = np.asarray(mesh.faces, dtype=np.int64)
        self.original_face_count = int(len(raw_faces))
        """过滤微小装饰组件前的三角面数量。"""
        self.minimum_component_faces = int(minimum_component_faces)
        """保留不连通 mesh 组件所需的最小三角面数量。"""
        if not 1 <= self.minimum_component_faces <= 1000:
            raise ValueError("minimum_component_faces 必须位于 1 到 1000。")
        self.faces = _filter_small_face_components(
            raw_faces,
            minimum_faces=self.minimum_component_faces,
        )
        """过滤微小装饰组件后的三角面索引。"""
        self._nvdiffrast_renderer: NvdiffrastTextureRenderer | None = None
        """按需创建并跨全部帧复用的 VCD 同款 CUDA 纹理 renderer。"""
        self.texture_backend_resolved: str | None = None
        """本次实际使用的纹理后端；尚未渲染时为 None。"""
        self.texture_backend_fallback_reason: str | None = None
        """auto 后端回退到 CPU 时记录的原因。"""
        self._nvdiffrast_max_texture_size_px: int | None = None
        """当前缓存 CUDA renderer 使用的纹理最长边。"""
        self._auto_backend_failed_max_texture_size_px: int | None = None
        """auto 已确认无法初始化 CUDA 的纹理尺寸，避免每个图层重复尝试。"""
        if self.vertices.ndim != 2 or self.vertices.shape[1] != 3:
            raise ValueError(f"replay mesh 顶点格式不合法: {path}")
        if self.faces.ndim != 2 or self.faces.shape[1] != 3:
            raise ValueError(f"replay mesh 必须是三角网格: {path}")

    @classmethod
    def from_capture(
        cls,
        capture: ReplayCapture,
        mesh_path: str | Path,
        *,
        minimum_component_faces: int = 1,
    ) -> "MeshProjector":
        """按 capture provenance 恢复 Unity 模型局部基并加载投影器。"""

        if not capture.samples:
            raise ValueError("replay capture 不包含可用于恢复局部坐标基的样本。")
        local_matrix = projection_mesh_local_matrix(capture.samples[0].variants)
        for sample in capture.samples[1:]:
            sample_matrix = projection_mesh_local_matrix(sample.variants)
            if not np.allclose(sample_matrix, local_matrix, atol=1e-9, rtol=0.0):
                raise ValueError(
                    "capture 内 runtime 坐标补偿发生变化，无法使用单一局部矩阵投影: "
                    f"sample={sample.sample_id}"
                )
        return cls(
            mesh_path,
            apply_scale=capture.manifest.model_apply_scale,
            local_matrix=local_matrix,
            minimum_component_faces=minimum_component_faces,
        )

    @classmethod
    def from_arrays(
        cls,
        vertices: np.ndarray,
        faces: np.ndarray,
        *,
        local_matrix: np.ndarray | None = None,
        uv: np.ndarray | None = None,
        texture_rgb: np.ndarray | None = None,
        minimum_component_faces: int = 1,
    ) -> "MeshProjector":
        """从数组构造测试用 projector，不经过文件加载。"""

        instance = cls.__new__(cls)
        instance.vertex_transform = _validate_local_matrix(local_matrix)
        raw_vertices = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
        homogeneous = np.column_stack(
            [raw_vertices, np.ones(len(raw_vertices), dtype=np.float64)]
        )
        instance.vertices = (homogeneous @ instance.vertex_transform.T)[:, :3]
        raw_faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
        instance.original_face_count = int(len(raw_faces))
        instance.minimum_component_faces = int(minimum_component_faces)
        instance.faces = _filter_small_face_components(
            raw_faces,
            minimum_faces=instance.minimum_component_faces,
        )
        instance.uv = None if uv is None else np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        instance.texture_rgb = (
            None
            if texture_rgb is None
            else np.asarray(texture_rgb, dtype=np.uint8).reshape(
                int(np.asarray(texture_rgb).shape[0]),
                int(np.asarray(texture_rgb).shape[1]),
                3,
            )
        )
        instance.texture_source = "test_array" if instance.texture_rgb is not None else None
        instance._nvdiffrast_renderer = None
        instance.texture_backend_resolved = None
        instance.texture_backend_fallback_reason = None
        instance._nvdiffrast_max_texture_size_px = None
        instance._auto_backend_failed_max_texture_size_px = None
        if instance.uv is not None and len(instance.uv) != len(instance.vertices):
            raise ValueError("测试 projector 的 UV 数量必须与顶点数一致。")
        return instance

    @property
    def has_texture(self) -> bool:
        """mesh 是否同时具备逐顶点 UV 和 base-color RGB 纹理。"""

        return self.uv is not None and self.texture_rgb is not None

    @property
    def texture_size(self) -> tuple[int, int] | None:
        """返回纹理宽高；无纹理时返回 None。"""

        if self.texture_rgb is None:
            return None
        return int(self.texture_rgb.shape[1]), int(self.texture_rgb.shape[0])

    @property
    def texture_render_size(self) -> tuple[int, int] | None:
        """返回实际送入 CUDA 纹理采样器的宽高；未初始化时退回原始尺寸。"""

        renderer = self._nvdiffrast_renderer
        if renderer is not None:
            return renderer.texture_size
        return self.texture_size

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
        # fillPoly 会对整组重叠多边形应用奇偶规则，使 mesh 三角面互相挖洞。
        # 逐面累积才能得到真实的投影三角形并集。
        for polygon in polygons:
            cv2.fillConvexPoly(mask, polygon, 255, lineType=cv2.LINE_8)
        return mask

    def render_texture_crop(
        self,
        pose_cv_camera: np.ndarray,
        camera_matrix: np.ndarray,
        image_width: int,
        image_height: int,
        crop_xywh: tuple[int, int, int, int],
        *,
        backend: str = "auto",
        max_texture_size_px: int = 0,
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """在给定裁剪框内用 VCD 同款 CUDA 后端或 CPU 回退渲染纹理。"""

        if not self.has_texture:
            return None
        if backend not in TEXTURE_RENDER_BACKENDS:
            raise ValueError(f"texture backend 必须是 {TEXTURE_RENDER_BACKENDS} 之一。")
        if int(max_texture_size_px) != 0 and not 64 <= int(max_texture_size_px) <= 4096:
            raise ValueError("max_texture_size_px 必须为 0 或位于 64 到 4096。")
        x_crop, y_crop, crop_width, crop_height = _validate_crop_box(
            crop_xywh,
            int(image_width),
            int(image_height),
        )
        should_try_cuda = backend == "nvdiffrast" or (
            backend == "auto"
            and self._auto_backend_failed_max_texture_size_px
            != int(max_texture_size_px)
        )
        if should_try_cuda:
            try:
                if (
                    self._nvdiffrast_renderer is None
                    or self._nvdiffrast_max_texture_size_px != int(max_texture_size_px)
                ):
                    self._nvdiffrast_renderer = NvdiffrastTextureRenderer(
                        self.vertices,
                        self.faces,
                        cast(np.ndarray, self.uv),
                        cast(np.ndarray, self.texture_rgb),
                        max_texture_size_px=int(max_texture_size_px),
                    )
                    self._nvdiffrast_max_texture_size_px = int(max_texture_size_px)
                rendered = self._nvdiffrast_renderer.render_crop(
                    pose_cv_camera,
                    camera_matrix,
                    (x_crop, y_crop, crop_width, crop_height),
                )
                self.texture_backend_resolved = "nvdiffrast"
                self.texture_backend_fallback_reason = None
                self._auto_backend_failed_max_texture_size_px = None
                return rendered
            except (ImportError, OSError, RuntimeError) as exc:
                if backend == "nvdiffrast":
                    raise RuntimeError(f"nvdiffrast 纹理渲染失败：{exc}") from exc
                self.texture_backend_fallback_reason = f"{type(exc).__name__}: {exc}"
                self._auto_backend_failed_max_texture_size_px = int(
                    max_texture_size_px
                )

        self.texture_backend_resolved = "cpu"
        if backend == "cpu":
            self.texture_backend_fallback_reason = None
        pose = np.asarray(pose_cv_camera, dtype=np.float64).reshape(4, 4)
        camera = np.asarray(camera_matrix, dtype=np.float64).reshape(3, 3)
        points_camera = self.vertices @ pose[:3, :3].T + pose[:3, 3]
        z = points_camera[:, 2]
        valid_vertices = np.isfinite(points_camera).all(axis=1) & (z > 1e-4)
        normalized = np.zeros((len(points_camera), 2), dtype=np.float64)
        normalized[valid_vertices] = points_camera[valid_vertices, :2] / z[valid_vertices, None]
        projected = normalized @ camera[:2, :2].T + camera[:2, 2]
        projected -= np.array([x_crop, y_crop], dtype=np.float64)

        color = np.zeros((crop_height, crop_width, 3), dtype=np.uint8)
        visible = np.zeros((crop_height, crop_width), dtype=np.uint8)
        depth = np.full((crop_height, crop_width), np.inf, dtype=np.float64)
        uv = cast(np.ndarray, self.uv)
        texture = cast(np.ndarray, self.texture_rgb)
        for face in self.faces:
            if not np.all(valid_vertices[face]):
                continue
            _rasterize_textured_triangle(
                color,
                visible,
                depth,
                projected[face],
                z[face],
                uv[face],
                texture,
            )
        return color, visible

    def project_axes(
        self,
        pose_cv_camera: np.ndarray,
        camera_matrix: np.ndarray,
        image_width: int,
        image_height: int,
        *,
        axis_length_m: float,
        margin_px: int,
    ) -> np.ndarray:
        """按与 mesh 相同的局部补偿链投影模型原点及 X/Y/Z 正轴端点。"""

        length = float(axis_length_m)
        if not np.isfinite(length) or length <= 0.0:
            raise ValueError("axis_length_m 必须是正有限数。")
        local_points = np.array(
            [
                [0.0, 0.0, 0.0, 1.0],
                [length, 0.0, 0.0, 1.0],
                [0.0, length, 0.0, 1.0],
                [0.0, 0.0, length, 1.0],
            ],
            dtype=np.float64,
        )
        compensated = local_points @ self.vertex_transform.T
        pose = np.asarray(pose_cv_camera, dtype=np.float64).reshape(4, 4)
        points_camera = compensated @ pose.T
        if not np.all(np.isfinite(points_camera)) or np.any(points_camera[:, 2] <= 1e-4):
            raise ValueError("坐标轴原点或端点位于相机近裁剪面之后。")
        camera = np.asarray(camera_matrix, dtype=np.float64).reshape(3, 3)
        normalized = points_camera[:, :2] / points_camera[:, 2, None]
        projected = normalized @ camera[:2, :2].T + camera[:2, 2]
        margin = float(max(1, int(margin_px)))
        if (
            np.any(projected[:, 0] < margin)
            or np.any(projected[:, 0] > int(image_width) - 1 - margin)
            or np.any(projected[:, 1] < margin)
            or np.any(projected[:, 1] > int(image_height) - 1 - margin)
        ):
            raise ValueError("坐标轴端点超出原始图像边界；请减小 axis_length_m。")
        return projected


def render_frame_overlays(
    capture: ReplayCapture,
    projector: MeshProjector,
    output_dir: str | Path,
    *,
    sample_id: str | None = None,
    model_alpha: float = 0.98,
    model_color_hex: str = "#D8DCE2",
    method_colors_hex: Sequence[str] = DEFAULT_METHOD_COLORS_HEX,
    reference_alpha: float = 0.50,
    fill_mode: str = "texture",
    texture_backend: str = "auto",
    texture_max_size_px: int = 0,
    texture_brightness: float = 1.0,
    method_contour_thickness: int = 3,
    reference_contour_color_hex: str = "#2D2D2D",
    reference_contour_thickness: int = 3,
    reference_halo_color_hex: str = "#FFFFFF",
    reference_halo_thickness: int = 6,
    show_axes: bool = True,
    axis_length_m: float = 0.06,
    axis_thickness: int = 2,
    axis_label_font_size: int = 16,
    axis_colors_hex: Sequence[str] = DEFAULT_AXIS_COLORS_HEX,
    axis_halo_color_hex: str = "#FFFFFF",
    axis_halo_thickness: int = 5,
    axis_tip_length: float = 0.20,
    axis_label_offset_px: tuple[int, int] = (3, -3),
    axis_origin_color_hex: str = "#232323",
    axis_origin_radius: int = 2,
) -> dict[str, Path]:
    """输出原图、Quest 官方参考和四种方法，供首次像素贴合检查。"""

    sample = _resolve_frame_sample(capture.samples, sample_id)
    background = _load_rgb(sample.image_path)
    height, width = background.shape[:2]
    _validate_overlay_options(
        model_alpha=model_alpha,
        reference_alpha=reference_alpha,
        fill_mode=fill_mode,
        texture_backend=texture_backend,
        texture_max_size_px=texture_max_size_px,
        texture_brightness=texture_brightness,
        method_colors_hex=method_colors_hex,
        method_contour_thickness=method_contour_thickness,
        reference_contour_color_hex=reference_contour_color_hex,
        reference_contour_thickness=reference_contour_thickness,
        reference_halo_color_hex=reference_halo_color_hex,
        reference_halo_thickness=reference_halo_thickness,
        show_axes=show_axes,
        axis_length_m=axis_length_m,
        axis_thickness=axis_thickness,
        axis_label_font_size=axis_label_font_size,
        axis_colors_hex=axis_colors_hex,
        axis_halo_color_hex=axis_halo_color_hex,
        axis_halo_thickness=axis_halo_thickness,
        axis_tip_length=axis_tip_length,
        axis_label_offset_px=axis_label_offset_px,
        axis_origin_color_hex=axis_origin_color_hex,
        axis_origin_radius=axis_origin_radius,
    )
    axis_style = _axis_draw_style(
        axis_colors_hex,
        thickness=axis_thickness,
        label_font_size=axis_label_font_size,
        halo_color_hex=axis_halo_color_hex,
        halo_thickness=axis_halo_thickness,
        tip_length=axis_tip_length,
        label_offset_px=axis_label_offset_px,
        origin_color_hex=axis_origin_color_hex,
        origin_radius=axis_origin_radius,
    )
    masks, axes = _project_sample_geometry(
        sample,
        projector,
        width,
        height,
        axis_length_m=axis_length_m,
        show_axes=show_axes,
        axis_margin_px=_axis_margin_px(axis_style),
    )
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    rgb_path = output / f"{sample.sample_id}_rgb.png"
    _write_rgb_png(rgb_path, background)
    paths["rgb"] = rgb_path

    reference_path = output / f"{sample.sample_id}_quest_reference.png"
    full_crop = (0, 0, width, height)
    camera_matrix = _camera_matrix(sample)
    reference_texture = _texture_layer(
        projector,
        recorded_projection_matrix(sample.platform_reference),
        camera_matrix,
        width,
        height,
        full_crop,
        fill_mode=fill_mode,
        backend=texture_backend,
        max_texture_size_px=texture_max_size_px,
        brightness=texture_brightness,
    )
    reference_image = _overlay_reference(
        background,
        masks[0],
        fill_texture=reference_texture,
        fill_alpha=reference_alpha,
        fill_color=_hex_to_rgb(model_color_hex),
        contour_color=_hex_to_rgb(reference_contour_color_hex),
        contour_thickness=reference_contour_thickness,
        halo_color=_hex_to_rgb(reference_halo_color_hex),
        halo_thickness=reference_halo_thickness,
    )
    if show_axes:
        reference_image = _draw_axes(
            reference_image,
            axes[0],
            axis_style,
        )
    _write_rgb_png(reference_path, reference_image)
    paths["quest_reference"] = reference_path

    for variant, mask, color_hex in zip(
        sample.variants,
        masks[1:],
        method_colors_hex,
        strict=True,
    ):
        variant_id = str(variant["variant_id"])
        variant_texture = _texture_layer(
            projector,
            recorded_projection_matrix(variant),
            camera_matrix,
            width,
            height,
            full_crop,
            fill_mode=fill_mode,
            backend=texture_backend,
            max_texture_size_px=texture_max_size_px,
            brightness=texture_brightness,
        )
        image = _overlay_single(
            background,
            mask,
            _hex_to_rgb(str(color_hex)),
            fill_alpha=model_alpha,
            fill_color=_hex_to_rgb(model_color_hex),
            fill_texture=variant_texture,
            contour_thickness=method_contour_thickness,
        )
        if show_axes:
            variant_index = VARIANT_IDS.index(variant_id) + 1
            image = _draw_axes(
                image,
                axes[variant_index],
                axis_style,
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
    columns: int | None = None,
    frame_step: int | None = None,
    start_sample_id: str | None = None,
    sample_ids: Sequence[str] | None = None,
    rows: Sequence[str] = ROW_KEYS,
    cell_width: int = 320,
    crop_padding: float | None = None,
    crop_xywh: tuple[int, int, int, int] | None = None,
    crop_aspect_ratio: float = 4.0 / 3.0,
    column_label: str = "delta-t",
    label_font_size: int = 30,
    row_label_rotation: int = 0,
    column_font_size: int = 24,
    timeline: TimelineSettings | None = None,
    label_padding: int = 8,
    label_min_width: int = 80,
    model_alpha: float = 0.98,
    model_color_hex: str = "#D8DCE2",
    method_colors_hex: Sequence[str] = DEFAULT_METHOD_COLORS_HEX,
    reference_alpha: float = 0.50,
    fill_mode: str = "texture",
    texture_backend: str = "auto",
    texture_max_size_px: int = 0,
    texture_brightness: float = 1.0,
    method_contour_thickness: int = 3,
    reference_contour_color_hex: str = "#2D2D2D",
    reference_contour_thickness: int = 3,
    reference_halo_color_hex: str = "#FFFFFF",
    reference_halo_thickness: int = 6,
    show_axes: bool = True,
    axis_length_m: float = 0.06,
    axis_thickness: int = 2,
    axis_label_font_size: int = 16,
    axis_colors_hex: Sequence[str] = DEFAULT_AXIS_COLORS_HEX,
    axis_halo_color_hex: str = "#FFFFFF",
    axis_halo_thickness: int = 5,
    axis_tip_length: float = 0.20,
    axis_label_offset_px: tuple[int, int] = (3, -3),
    axis_origin_color_hex: str = "#232323",
    axis_origin_radius: int = 2,
    gutter: int = 4,
    border_thickness: int = 1,
    canvas_color_hex: str = "#FFFFFF",
    border_color_hex: str = "#D2D2D2",
    row_label_color_hex: str = "#202020",
    column_label_color_hex: str = "#202020",
    header_padding: int = 18,
    row_titles: Sequence[str] = DEFAULT_ROW_TITLES,
    row_label_line_spacing: int = 4,
    mean_error_font_size: int = 24,
    export_pdf: bool = True,
    configuration_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    """生成 2--20 列、可选显示行的连续轨迹论文网格。

    列按 capture 样本顺序以固定 ``frame_step`` 取样，不按误差或抖动大小挑帧。
    每列所有显示行共享同一张 RGB、相机内参和裁剪框。
    """

    selected_rows = _validate_rows(rows)
    resolved_row_titles = _resolve_row_titles(row_titles)
    if int(cell_width) < 120:
        raise ValueError("cell_width 不能小于 120。")
    if column_label not in COLUMN_LABEL_MODES:
        raise ValueError(f"column_label 必须是 {COLUMN_LABEL_MODES} 之一。")
    _validate_timeline_settings(timeline)
    if (
        timeline is not None
        and timeline.mode == "relative-time"
        and column_label in {"delta-t", "both"}
    ):
        raise ValueError("启用 relative-time 时间轴时，column_label 不能重复显示 delta-t。")
    if (
        timeline is not None
        and timeline.mode == "frame-sequence"
        and column_label in {"sample-id", "both"}
    ):
        raise ValueError("启用 frame-sequence 时间轴时，column_label 不能重复显示 sample id。")
    for name, size in (
        ("label_font_size", label_font_size),
        ("column_font_size", column_font_size),
    ):
        if not 8 <= int(size) <= 96:
            raise ValueError(f"{name} 必须位于 8 到 96。")
    if not -90 <= int(row_label_rotation) <= 90:
        raise ValueError("row_label_rotation 必须位于 -90 到 90 度。")
    _validate_overlay_options(
        model_alpha=model_alpha,
        reference_alpha=reference_alpha,
        fill_mode=fill_mode,
        texture_backend=texture_backend,
        texture_max_size_px=texture_max_size_px,
        texture_brightness=texture_brightness,
        method_colors_hex=method_colors_hex,
        method_contour_thickness=method_contour_thickness,
        reference_contour_color_hex=reference_contour_color_hex,
        reference_contour_thickness=reference_contour_thickness,
        reference_halo_color_hex=reference_halo_color_hex,
        reference_halo_thickness=reference_halo_thickness,
        show_axes=show_axes,
        axis_length_m=axis_length_m,
        axis_thickness=axis_thickness,
        axis_label_font_size=axis_label_font_size,
        axis_colors_hex=axis_colors_hex,
        axis_halo_color_hex=axis_halo_color_hex,
        axis_halo_thickness=axis_halo_thickness,
        axis_tip_length=axis_tip_length,
        axis_label_offset_px=axis_label_offset_px,
        axis_origin_color_hex=axis_origin_color_hex,
        axis_origin_radius=axis_origin_radius,
    )
    if not 0.25 <= float(crop_aspect_ratio) <= 4.0:
        raise ValueError("crop_aspect_ratio 必须位于 0.25 到 4.0。")
    model_color = _hex_to_rgb(model_color_hex)
    canvas_color = _hex_to_rgb(canvas_color_hex)
    border_color = _hex_to_rgb(border_color_hex)
    row_label_color = _hex_to_rgb(row_label_color_hex)
    column_label_color = _hex_to_rgb(column_label_color_hex)
    if not 0 <= int(gutter) <= 64:
        raise ValueError("gutter 必须位于 0 到 64 px。")
    if not 0 <= int(label_padding) <= 64:
        raise ValueError("label_padding 必须位于 0 到 64 px。")
    if not 0 <= int(label_min_width) <= 512:
        raise ValueError("label_min_width 必须位于 0 到 512 px。")
    if not 0 <= int(border_thickness) <= 16:
        raise ValueError("border_thickness 必须位于 0 到 16 px。")
    if not 0 <= int(header_padding) <= 96:
        raise ValueError("header_padding 必须位于 0 到 96 px。")
    if not 0 <= int(row_label_line_spacing) <= 32:
        raise ValueError("row_label_line_spacing 必须位于 0 到 32 px。")
    if not 8 <= int(mean_error_font_size) <= 96:
        raise ValueError("mean_error_font_size 必须位于 8 到 96 px。")
    axis_style = _axis_draw_style(
        axis_colors_hex,
        thickness=axis_thickness,
        label_font_size=axis_label_font_size,
        halo_color_hex=axis_halo_color_hex,
        halo_thickness=axis_halo_thickness,
        tip_length=axis_tip_length,
        label_offset_px=axis_label_offset_px,
        origin_color_hex=axis_origin_color_hex,
        origin_radius=axis_origin_radius,
    )

    if sample_ids is not None:
        if start_sample_id is not None:
            raise ValueError("sample_ids 与 start_sample_id 不能同时使用。")
        if columns is not None or frame_step is not None:
            raise ValueError("使用 sample_ids 时不能同时指定 columns 或 frame_step。")
        selected = select_samples_by_ids(capture.samples, sample_ids, rows=selected_rows)
        selection_mode = "explicit_sample_ids"
        resolved_columns = len(selected)
        resolved_step = selected[1][0] - selected[0][0]
    else:
        resolved_columns = 6 if columns is None else int(columns)
        resolved_step = 3 if frame_step is None else int(frame_step)
        selected = select_stride_samples(
            capture.samples,
            columns=resolved_columns,
            frame_step=resolved_step,
            start_sample_id=start_sample_id,
            rows=selected_rows,
        )
        selection_mode = "fixed_stride"
    if crop_xywh is not None and crop_padding is not None:
        raise ValueError("crop 与 crop_padding 不能同时使用。")
    resolved_padding = 0.35 if crop_padding is None else float(crop_padding)
    if not 0.0 <= resolved_padding <= 2.0:
        raise ValueError("crop_padding 必须位于 0 到 2。")
    prepared: list[PreparedColumn] = []
    for sample_index, sample in selected:
        background = _load_rgb(sample.image_path)
        height, width = background.shape[:2]
        masks, axes = _project_sample_geometry(
            sample,
            projector,
            width,
            height,
            rows=selected_rows,
            axis_length_m=axis_length_m,
            show_axes=show_axes,
            axis_margin_px=_axis_margin_px(axis_style),
        )
        prepared.append(PreparedColumn(sample_index, sample, background, masks, axes))

    if crop_xywh is None:
        crops = _compute_shared_crops(
            prepared,
            padding=resolved_padding,
            aspect_ratio=float(crop_aspect_ratio),
            row_indices=_row_mask_indices(selected_rows),
            show_axes=show_axes,
            axis_style=axis_style,
        )
        crop_semantics = "reference-centered; fixed crop size across columns; one crop shared by all displayed rows"
    else:
        crops = _validate_fixed_crop(
            prepared,
            crop_xywh,
            row_indices=_row_mask_indices(selected_rows),
            show_axes=show_axes,
            axis_style=axis_style,
        )
        crop_semantics = "fixed image-space crop; identical crop shared by all columns and displayed rows"
    grid_columns = tuple(
        GridColumn(item.sample_index, item.sample, item.background, item.masks, item.axes, crop)
        for item, crop in zip(prepared, crops, strict=True)
    )
    reference_error_summary = _summarize_reference_errors(
        capture.samples,
        start_index=grid_columns[0].sample_index,
        end_index=grid_columns[-1].sample_index,
    )
    sheet, timeline_band_height, coordinate_axes = _compose_grid(
        grid_columns,
        projector,
        rows=selected_rows,
        cell_width=int(cell_width),
        column_label=column_label,
        label_font_size=int(label_font_size),
        row_label_rotation=int(row_label_rotation),
        column_font_size=int(column_font_size),
        timeline=timeline,
        label_padding=int(label_padding),
        label_min_width=int(label_min_width),
        model_alpha=float(model_alpha),
        model_color=model_color,
        method_colors_hex=tuple(str(value) for value in method_colors_hex),
        reference_alpha=float(reference_alpha),
        fill_mode=fill_mode,
        texture_backend=texture_backend,
        texture_max_size_px=int(texture_max_size_px),
        texture_brightness=float(texture_brightness),
        method_contour_thickness=int(method_contour_thickness),
        reference_contour_color=_hex_to_rgb(reference_contour_color_hex),
        reference_contour_thickness=int(reference_contour_thickness),
        reference_halo_color=_hex_to_rgb(reference_halo_color_hex),
        reference_halo_thickness=int(reference_halo_thickness),
        show_axes=bool(show_axes),
        axis_style=axis_style,
        gutter=int(gutter),
        border_thickness=int(border_thickness),
        canvas_color=canvas_color,
        border_color=border_color,
        row_label_color=row_label_color,
        column_label_color=column_label_color,
        header_padding=int(header_padding),
        row_titles=resolved_row_titles,
        row_label_line_spacing=int(row_label_line_spacing),
        mean_error_font_size=int(mean_error_font_size),
        reference_error_summary=reference_error_summary,
    )

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    image_path = output / "replay_grid.png"
    metadata_path = output / "replay_grid.json"
    resolved_fill_mode = "texture" if fill_mode == "texture" and projector.has_texture else "color"
    effective_crop_aspect_ratio = (
        float(crop_aspect_ratio) if crop_xywh is None else None
    )
    texture_fallback_reason = (
        "mesh_missing_uv_or_base_color_texture"
        if fill_mode == "texture" and not projector.has_texture
        else None
    )
    effective_configuration = {
        "selection": {
            "mode": selection_mode,
            "columns": resolved_columns,
            "frame_step": resolved_step,
            "start_sample_id": grid_columns[0].sample.sample_id,
            "sample_ids": [column.sample.sample_id for column in grid_columns],
            "rows": list(selected_rows),
        },
        "layout": {
            "cell_width": int(cell_width),
            "column_label": column_label,
            "label_font_size": int(label_font_size),
            "row_label_rotation_deg": int(row_label_rotation),
            "column_font_size": int(column_font_size),
            "label_padding_px": int(label_padding),
            "label_min_width_px": int(label_min_width),
            "gutter_px": int(gutter),
            "border_thickness_px": int(border_thickness),
            "canvas_color_hex": canvas_color_hex,
            "border_color_hex": border_color_hex,
            "row_label_color_hex": row_label_color_hex,
            "column_label_color_hex": column_label_color_hex,
            "header_padding_px": int(header_padding),
            "row_titles": list(row_titles),
            "row_label_line_spacing_px": int(row_label_line_spacing),
            "mean_error_font_size_px": int(mean_error_font_size),
        },
        "timeline": _effective_timeline_configuration(timeline),
        "crop": {
            "mode": "auto" if crop_xywh is None else "fixed",
            "padding": resolved_padding if crop_xywh is None else None,
            "fixed_xywh": list(crop_xywh) if crop_xywh is not None else None,
            "aspect_ratio": effective_crop_aspect_ratio,
        },
        "overlay": {
            "model_alpha": float(model_alpha),
            "model_color_hex": model_color_hex,
            "method_colors_hex": list(method_colors_hex),
            "reference_alpha": float(reference_alpha),
            "fill_mode": fill_mode,
            "texture_backend": texture_backend,
            "texture_max_size_px": int(texture_max_size_px),
            "minimum_component_faces": projector.minimum_component_faces,
            "texture_brightness": float(texture_brightness),
            "method_contour_thickness_px": int(method_contour_thickness),
            "reference_contour_color_hex": reference_contour_color_hex,
            "reference_contour_thickness_px": int(reference_contour_thickness),
            "reference_halo_color_hex": reference_halo_color_hex,
            "reference_halo_thickness_px": int(reference_halo_thickness),
        },
        "axes": {
            "enabled": bool(show_axes),
            "length_m": float(axis_length_m),
            "thickness_px": int(axis_thickness),
            "label_font_size_px": int(axis_label_font_size),
            "colors_hex": list(axis_colors_hex),
            "halo_color_hex": axis_halo_color_hex,
            "halo_thickness_px": int(axis_halo_thickness),
            "tip_length": float(axis_tip_length),
            "label_offset_px": list(axis_label_offset_px),
            "origin_color_hex": axis_origin_color_hex,
            "origin_radius_px": int(axis_origin_radius),
        },
        "export": {
            "pdf": bool(export_pdf),
            "pdf_dpi": 300 if export_pdf else None,
        },
    }
    effective_json = json.dumps(
        effective_configuration,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    metadata = {
        "capture_id": capture.manifest.capture_id,
        "selection": selection_mode,
        "selection_semantics": "strictly increasing fixed saved-frame stride; no automatic error-based selection",
        "columns": resolved_columns,
        "frame_step": resolved_step,
        "row_ids": [ROW_IDS[ROW_KEYS.index(row)] for row in selected_rows],
        "row_keys": list(selected_rows),
        "row_titles": [resolved_row_titles[row] for row in selected_rows],
        "column_label": column_label,
        "font_sizes": {
            "row_label": int(label_font_size),
            "column_label": int(column_font_size),
            "timeline": (
                int(timeline.font_size_px)
                if timeline is not None and timeline.mode != "none"
                else None
            ),
        },
        "font_identifiers": {
            "row_label": _font_identifier(int(label_font_size)),
            "column_label": _font_identifier(int(column_font_size)),
            "timeline": (
                _font_identifier(int(timeline.font_size_px))
                if timeline is not None and timeline.mode != "none"
                else None
            ),
        },
        "cell_width": int(cell_width),
        "layout": {
            "label_padding_px": int(label_padding),
            "label_min_width_px": int(label_min_width),
            "row_label_rotation_deg": int(row_label_rotation),
            "gutter_px": int(gutter),
            "border_thickness_px": int(border_thickness),
            "canvas_color_hex": canvas_color_hex,
            "border_color_hex": border_color_hex,
            "row_label_color_hex": row_label_color_hex,
            "column_label_color_hex": column_label_color_hex,
            "header_padding_px": int(header_padding),
            "row_label_line_spacing_px": int(row_label_line_spacing),
            "mean_error_font_size_px": int(mean_error_font_size),
        },
        "method_colors_hex": list(method_colors_hex),
        "capture_variant_colors_hex": list(capture.manifest.variant_colors_hex),
        "projection_mesh_local_matrix": projector.vertex_transform.reshape(-1).tolist(),
        "overlay": {
            "model_alpha": float(model_alpha),
            "model_color_hex": model_color_hex,
            "method_colors_hex": list(method_colors_hex),
            "reference_alpha": float(reference_alpha),
            "fill_mode_requested": fill_mode,
            "fill_mode_resolved": resolved_fill_mode,
            "texture_backend_requested": texture_backend,
            "texture_backend_resolved": projector.texture_backend_resolved,
            "texture_backend_fallback_reason": projector.texture_backend_fallback_reason,
            "texture_max_size_px": int(texture_max_size_px),
            "minimum_component_faces": projector.minimum_component_faces,
            "mesh_faces_original": projector.original_face_count,
            "mesh_faces_rendered": int(len(projector.faces)),
            "texture_brightness": float(texture_brightness),
            "texture_source": projector.texture_source,
            "texture_size": list(projector.texture_size) if projector.texture_size else None,
            "texture_render_size": (
                list(projector.texture_render_size)
                if projector.texture_render_size
                else None
            ),
            "texture_fallback_reason": texture_fallback_reason,
            "method_contour_thickness_px": int(method_contour_thickness),
            "reference_contour_color_hex": reference_contour_color_hex,
            "reference_contour_thickness_px": int(reference_contour_thickness),
            "reference_halo_color_hex": reference_halo_color_hex,
            "reference_halo_thickness_px": int(reference_halo_thickness),
        },
        "axes": {
            "enabled": bool(show_axes),
            "coordinate_space": "FoundationPose mesh local coordinates after Unity renderer compensation recovery",
            "length_m": float(axis_length_m),
            "thickness_px": int(axis_thickness),
            "label_font_size_px": int(axis_label_font_size),
            "colors_hex": list(axis_colors_hex),
            "halo_color_hex": axis_halo_color_hex,
            "halo_thickness_px": int(axis_halo_thickness),
            "tip_length": float(axis_tip_length),
            "label_offset_px": list(axis_label_offset_px),
            "origin_color_hex": axis_origin_color_hex,
            "origin_radius_px": int(axis_origin_radius),
            "clipping": False,
        },
        "timeline": _timeline_metadata(
            grid_columns,
            timeline,
            band_height=timeline_band_height,
        ),
        "row_axis": {
            "semantic": "method",
            "direction": "top-to-bottom",
            "row_keys": list(selected_rows),
            "row_titles": [resolved_row_titles[row] for row in selected_rows],
        },
        "reference_error_summary": reference_error_summary,
        "coordinate_axes": coordinate_axes,
        "outputs": {
            "grid": image_path.name,
            "pdf": {
                "enabled": bool(export_pdf),
                "path": "replay_grid.pdf" if export_pdf else None,
                "dpi": 300 if export_pdf else None,
            },
        },
        "configuration": {
            "sources": dict(configuration_provenance or {}),
            "effective": effective_configuration,
            "effective_sha256": hashlib.sha256(effective_json.encode("utf-8")).hexdigest(),
        },
        "crop_mode": "auto_reference_centered" if crop_xywh is None else "fixed_image_space",
        "crop_padding": resolved_padding if crop_xywh is None else None,
        "crop_aspect_ratio": effective_crop_aspect_ratio,
        "requested_crop_xywh": list(crop_xywh) if crop_xywh is not None else None,
        "crop_semantics": crop_semantics,
        "samples": [
            {
                "sample_index": column.sample_index,
                "sample_id": column.sample.sample_id,
                "image_unity_frame": column.sample.image_unity_frame,
                "image_mono_ms": column.sample.image_mono_ms,
                "delta_time_ms": column.sample.image_mono_ms - grid_columns[0].sample.image_mono_ms,
                "capture_relative_time_ms": column.sample.image_mono_ms - capture.samples[0].image_mono_ms,
                "reference_pose_source": column.sample.platform_reference["pose_source"],
                "crop_xywh": list(column.crop),
            }
            for column in grid_columns
        ],
    }
    metadata_text = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    _write_rgb_png(image_path, sheet)
    if export_pdf:
        pdf_path = output / "replay_grid.pdf"
        _write_rgb_pdf(pdf_path, sheet)
    metadata_path.write_text(metadata_text, encoding="utf-8")
    paths = {"grid": image_path, "metadata": metadata_path}
    if export_pdf:
        paths["pdf"] = pdf_path
    return paths


def select_stride_samples(
    samples: Sequence[ReplaySample],
    *,
    columns: int,
    frame_step: int,
    start_sample_id: str | None = None,
    rows: Sequence[str] = ROW_KEYS,
) -> tuple[tuple[int, ReplaySample], ...]:
    """按固定已保存帧间隔选择一段所选行数据完整的连续序列。"""

    selected_rows = _validate_rows(rows)
    if not 2 <= int(columns) <= 20:
        raise ValueError("columns 必须位于 2 到 20。")
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
        if all(_is_complete_grid_sample(sample, selected_rows) for _, sample in chosen):
            return chosen
        if start_sample_id is not None:
            details = _format_sample_issues(chosen, selected_rows)
            raise ValueError(
                "指定起点和 frame_step 对应的序列不能生成所选行网格："
                f"{details}"
            )
    if start_sample_id is not None:
        last_index = starts[0] + (int(columns) - 1) * int(frame_step)
        raise ValueError(
            "指定起点后的样本数不足："
            f"最后一列需要索引 {last_index}，capture 最大索引为 {len(samples) - 1}。"
        )
    raise ValueError("capture 中找不到满足给定 columns/frame_step 的所选行连续序列。")


def select_samples_by_ids(
    samples: Sequence[ReplaySample],
    sample_ids: Sequence[str],
    *,
    rows: Sequence[str] = ROW_KEYS,
) -> tuple[tuple[int, ReplaySample], ...]:
    """按严格递增的等距 sample id 选择 2--20 列，并检查所选行完整性。"""

    selected_rows = _validate_rows(rows)
    requested = tuple(str(sample_id) for sample_id in sample_ids)
    if not 2 <= len(requested) <= 20:
        raise ValueError("sample_ids 必须提供 2 到 20 个样本 id。")
    if len(set(requested)) != len(requested):
        raise ValueError("sample_ids 不能包含重复样本 id。")
    by_id = {sample.sample_id: (index, sample) for index, sample in enumerate(samples)}
    unknown = [sample_id for sample_id in requested if sample_id not in by_id]
    if unknown:
        raise KeyError(f"未知 replay sample_id: {unknown}")
    selected = tuple(by_id[sample_id] for sample_id in requested)
    indices = tuple(index for index, _ in selected)
    steps = tuple(right - left for left, right in zip(indices, indices[1:]))
    if any(step <= 0 for step in steps) or len(set(steps)) != 1:
        raise ValueError("sample_ids 必须按 capture 顺序严格递增，并保持固定样本间隔 N。")
    details = _format_sample_issues(selected, selected_rows)
    if details:
        raise ValueError(f"指定的 sample_ids 不能生成所选行网格：{details}")
    return selected


def describe_samples(
    samples: Sequence[ReplaySample],
    *,
    start_sample_id: str,
    count: int = 8,
    frame_step: int = 1,
) -> tuple[dict[str, Any], ...]:
    """列出一段样本的完整性和相对 Quest 参考误差，供人工判断识别起点。"""

    if int(count) <= 0:
        raise ValueError("count 必须为正整数。")
    if int(frame_step) <= 0:
        raise ValueError("frame_step 必须为正整数。")
    start = next(
        (index for index, sample in enumerate(samples) if sample.sample_id == start_sample_id),
        None,
    )
    if start is None:
        raise KeyError(f"未知 replay sample_id: {start_sample_id}")
    indices = tuple(start + offset * int(frame_step) for offset in range(int(count)))
    if indices[-1] >= len(samples):
        raise ValueError(
            f"诊断范围超出 capture：最后需要索引 {indices[-1]}，最大索引为 {len(samples) - 1}。"
        )
    return tuple(_describe_sample(index, samples[index]) for index in indices)


def _is_complete_grid_sample(
    sample: ReplaySample,
    rows: Sequence[str] = ROW_KEYS,
) -> bool:
    """判断样本能否生成所选行；fresh 和 held 平台参考都视为有效。"""

    required = set(_required_variant_ids(rows))
    return sample.platform_reference.get("valid") is True and all(
        variant.get("has_display_pose") is True
        for variant in sample.variants
        if variant.get("variant_id") in required
    )


def _sample_issues(
    sample: ReplaySample,
    rows: Sequence[str] = ROW_KEYS,
) -> tuple[str, ...]:
    """返回样本不能进入所选行网格的具体原因。"""

    issues: list[str] = []
    if sample.platform_reference.get("valid") is not True:
        issues.append("reference invalid")
    required = set(_required_variant_ids(rows))
    missing = [
        str(variant.get("variant_id"))
        for variant in sample.variants
        if variant.get("variant_id") in required
        if variant.get("has_display_pose") is not True
    ]
    if missing:
        issues.append(f"missing display pose: {','.join(missing)}")
    return tuple(issues)


def _format_sample_issues(
    selected: Sequence[tuple[int, ReplaySample]],
    rows: Sequence[str] = ROW_KEYS,
) -> str:
    """把多列完整性问题压缩成可直接操作的错误信息。"""

    parts = [
        f"{sample.sample_id} ({'; '.join(issues)})"
        for _, sample in selected
        if (issues := _sample_issues(sample, rows))
    ]
    return "; ".join(parts)


def _describe_sample(index: int, sample: ReplaySample) -> dict[str, Any]:
    """生成一条稳定 JSON 诊断记录，不把参考差异解释成外部真值。"""

    reference = sample.platform_reference
    variants = []
    for variant in sample.variants:
        item: dict[str, Any] = {
            "variant_id": variant["variant_id"],
            "has_output_pose": variant["has_output_pose"],
            "has_display_pose": variant["has_display_pose"],
            "pose_source": variant["pose_source"],
        }
        if reference.get("valid") is True and variant.get("has_display_pose") is True:
            position_cm, rotation_deg = _pose_difference(
                reference["world_pose"],
                variant["display_world_pose"],
            )
            item["reference_position_difference_cm"] = round(position_cm, 3)
            item["reference_rotation_difference_deg"] = round(rotation_deg, 3)
        else:
            item["reference_position_difference_cm"] = None
            item["reference_rotation_difference_deg"] = None
        variants.append(item)
    return {
        "sample_index": index,
        "sample_id": sample.sample_id,
        "image_unity_frame": sample.image_unity_frame,
        "reference_valid": reference["valid"],
        "reference_pose_source": reference["pose_source"],
        "grid_complete": not _sample_issues(sample),
        "issues": list(_sample_issues(sample)),
        "variants": variants,
    }


def _summarize_reference_errors(
    samples: Sequence[ReplaySample],
    *,
    start_index: int,
    end_index: int,
) -> dict[str, dict[str, float | int | str]]:
    """汇总当前网格时间窗内各方法相对 Quest 参考的逐帧平均误差。"""

    if not 0 <= int(start_index) <= int(end_index) < len(samples):
        raise ValueError("平均误差时间窗必须落在 replay capture 样本范围内。")
    summary: dict[str, dict[str, float | int | str]] = {}
    for variant_id in VARIANT_IDS:
        position_errors: list[float] = []
        rotation_errors: list[float] = []
        for sample in samples[int(start_index) : int(end_index) + 1]:
            reference = sample.platform_reference
            variant = next(item for item in sample.variants if item["variant_id"] == variant_id)
            display_pose = variant.get("display_world_pose")
            if reference.get("valid") is not True or variant.get("has_display_pose") is not True:
                continue
            if not isinstance(display_pose, dict):
                continue
            position_error, rotation_error = _pose_difference(
                reference["world_pose"],
                display_pose,
            )
            position_errors.append(position_error)
            rotation_errors.append(rotation_error)
        if position_errors:
            summary[variant_id] = {
                "mean_position_error_mm": round(float(np.mean(position_errors)) * 10.0, 6),
                "mean_rotation_error_deg": round(float(np.mean(rotation_errors)), 6),
                "sample_count": len(position_errors),
                "semantics": "shown-window mean over valid display samples vs Quest Reference; translation in mm, rotation in deg",
            }
    return summary


def _pose_difference(reference: dict[str, Any], display: dict[str, Any]) -> tuple[float, float]:
    """计算两条 world pose 的位置厘米差和最短四元数角差。"""

    reference_position = np.asarray(reference["position"], dtype=np.float64)
    display_position = np.asarray(display["position"], dtype=np.float64)
    position_cm = float(np.linalg.norm(display_position - reference_position) * 100.0)
    reference_rotation = np.asarray(reference["rotation_xyzw"], dtype=np.float64)
    display_rotation = np.asarray(display["rotation_xyzw"], dtype=np.float64)
    reference_rotation /= np.linalg.norm(reference_rotation)
    display_rotation /= np.linalg.norm(display_rotation)
    cosine = float(np.clip(abs(np.dot(reference_rotation, display_rotation)), 0.0, 1.0))
    rotation_deg = float(np.degrees(2.0 * np.arccos(cosine)))
    return position_cm, rotation_deg


def _project_sample_geometry(
    sample: ReplaySample,
    projector: MeshProjector,
    width: int,
    height: int,
    *,
    rows: Sequence[str] = ROW_KEYS,
    axis_length_m: float,
    show_axes: bool,
    axis_margin_px: int,
) -> tuple[tuple[np.ndarray, ...], tuple[np.ndarray, ...]]:
    """投影同一列所需的 Quest 参考、方法轮廓和模型局部坐标轴。"""

    selected_rows = _validate_rows(rows)
    if not _is_complete_grid_sample(sample, selected_rows):
        raise ValueError(f"sample {sample.sample_id} 所选行数据不完整。")
    camera_matrix = _camera_matrix(sample)
    reference = sample.platform_reference
    reference_mask = projector.project_mask(
        recorded_projection_matrix(reference),
        camera_matrix,
        width,
        height,
    )
    empty_axes = np.full((4, 2), np.nan, dtype=np.float64)
    reference_axes = (
        projector.project_axes(
            recorded_projection_matrix(reference),
            camera_matrix,
            width,
            height,
            axis_length_m=axis_length_m,
            margin_px=axis_margin_px,
        )
        if show_axes and "reference" in selected_rows
        else empty_axes.copy()
    )
    required_variants = set(_required_variant_ids(selected_rows))
    masks = [reference_mask]
    axes = [reference_axes]
    for variant in sample.variants:
        if variant["variant_id"] in required_variants:
            verify_projection_matrix(sample.camera["world_pose"], variant)
            pose = recorded_projection_matrix(variant)
            masks.append(
                projector.project_mask(
                    pose,
                    camera_matrix,
                    width,
                    height,
                )
            )
            axes.append(
                projector.project_axes(
                    pose,
                    camera_matrix,
                    width,
                    height,
                    axis_length_m=axis_length_m,
                    margin_px=axis_margin_px,
                )
                if show_axes
                else empty_axes.copy()
            )
        else:
            masks.append(np.zeros((height, width), dtype=np.uint8))
            axes.append(empty_axes.copy())
    required_masks = _row_mask_indices(selected_rows)
    empty = [ROW_IDS[index + 1] for index in required_masks if not np.any(masks[index])]
    if empty:
        raise ValueError(f"sample {sample.sample_id} 的投影不在图像内: {empty}")
    return tuple(masks), tuple(axes)


def _compute_shared_crops(
    prepared: Sequence[PreparedColumn],
    *,
    padding: float,
    aspect_ratio: float,
    row_indices: Sequence[int],
    show_axes: bool,
    axis_style: AxisDrawStyle,
) -> tuple[tuple[int, int, int, int], ...]:
    """以每列参考质心为中心，按显示行求跨列统一大小和宽高比的裁剪框。"""

    centers: list[np.ndarray] = []
    required_half_width = 1.0
    required_half_height = 1.0
    image_height, image_width = prepared[0].background.shape[:2]
    for item in prepared:
        if item.background.shape[:2] != (image_height, image_width):
            raise ValueError(f"sample {item.sample.sample_id} 图像尺寸与序列其他列不一致。")
        center = _mask_centroid(item.masks[0])
        centers.append(center)
        selected_masks = [
            _geometry_coverage_mask(
                item.masks[index],
                item.axes[index],
                show_axes=show_axes,
                axis_style=axis_style,
            )
            for index in row_indices
        ]
        union = np.any(np.stack([mask > 0 for mask in selected_masks], axis=0), axis=0)
        y, x = np.nonzero(union)
        required_half_width = max(required_half_width, float(np.max(np.abs(x - center[0]))))
        required_half_height = max(required_half_height, float(np.max(np.abs(y - center[1]))))

    crop_width = int(np.ceil(required_half_width * 2.0 * (1.0 + padding)))
    crop_height = int(np.ceil(required_half_height * 2.0 * (1.0 + padding)))
    aspect = float(aspect_ratio)
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


def _validate_fixed_crop(
    prepared: Sequence[PreparedColumn],
    crop_xywh: tuple[int, int, int, int],
    *,
    row_indices: Sequence[int],
    show_axes: bool,
    axis_style: AxisDrawStyle,
) -> tuple[tuple[int, int, int, int], ...]:
    """校验一份固定图像坐标裁剪框，并应用到全部列。"""

    x, y, width, height = (int(value) for value in crop_xywh)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("crop_xywh 必须是非负 x/y 和正数 width/height。")
    for item in prepared:
        image_height, image_width = item.background.shape[:2]
        if x + width > image_width or y + height > image_height:
            raise ValueError(
                f"crop_xywh 超出 sample {item.sample.sample_id} 的图像边界 "
                f"{image_width}x{image_height}。"
            )
        for index in row_indices:
            coverage = _geometry_coverage_mask(
                item.masks[index],
                item.axes[index],
                show_axes=show_axes,
                axis_style=axis_style,
            )
            outside = coverage.copy()
            outside[y : y + height, x : x + width] = 0
            if np.any(outside):
                raise ValueError(
                    f"crop_xywh 会截断 sample {item.sample.sample_id} 的 "
                    f"{ROW_IDS[index + 1]} 模型或坐标轴。"
                )
    crop = (x, y, width, height)
    return (crop,) * len(prepared)


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
    projector: MeshProjector,
    *,
    rows: Sequence[str],
    cell_width: int,
    column_label: str,
    label_font_size: int,
    row_label_rotation: int,
    column_font_size: int,
    timeline: TimelineSettings | None,
    label_padding: int,
    label_min_width: int,
    model_alpha: float,
    model_color: tuple[int, int, int],
    method_colors_hex: Sequence[str],
    reference_alpha: float,
    fill_mode: str,
    texture_backend: str,
    texture_max_size_px: int,
    texture_brightness: float,
    method_contour_thickness: int,
    reference_contour_color: tuple[int, int, int],
    reference_contour_thickness: int,
    reference_halo_color: tuple[int, int, int],
    reference_halo_thickness: int,
    show_axes: bool,
    axis_style: AxisDrawStyle,
    gutter: int,
    border_thickness: int,
    canvas_color: tuple[int, int, int],
    border_color: tuple[int, int, int],
    row_label_color: tuple[int, int, int],
    column_label_color: tuple[int, int, int],
    header_padding: int,
    row_titles: Mapping[str, str],
    row_label_line_spacing: int,
    mean_error_font_size: int,
    reference_error_summary: Mapping[str, Mapping[str, float | int | str]],
) -> tuple[np.ndarray, int, dict[str, Any]]:
    """把选定同步行排成白底论文图，并按需显示列标题。"""

    crop_width = columns[0].crop[2]
    crop_height = columns[0].crop[3]
    cell_height = max(90, int(round(cell_width * crop_height / crop_width)))
    label_font = _load_font(label_font_size)
    annotation_font = _load_font(mean_error_font_size)
    column_font = _load_font(column_font_size)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    row_label_images = {
        row: _render_rotated_text_image(
            row_titles[row],
            label_font,
            row_label_color,
            spacing=row_label_line_spacing,
            rotation_deg=row_label_rotation,
        )
        for row in rows
    }
    max_label_height = max(image.height for image in row_label_images.values())
    if max_label_height > cell_height - 4:
        raise ValueError(
            "旋转后的行标题高于图像单元；请减小行名字号、降低旋转角度或增大裁剪高度。"
        )
    label_width = int(
        max(
            label_min_width,
            max(image.width for image in row_label_images.values()) + label_padding,
        )
    )
    column_header_height = (
        max(column_font_size, column_font_size + header_padding)
        if column_label != "none"
        else 0
    )
    timeline_band_height = _timeline_band_height(timeline)
    timeline_is_top = (
        timeline is not None
        and timeline.mode != "none"
        and timeline.placement == "top"
    )
    top_timeline_height = timeline_band_height if timeline_is_top else 0
    grid_right = label_width + len(columns) * cell_width + (len(columns) - 1) * gutter
    timeline_extension = (
        timeline.right_extension_px
        if timeline is not None and timeline.mode != "none"
        else 0
    )
    sheet_width = grid_right + timeline_extension
    image_grid_height = len(rows) * cell_height + (len(rows) - 1) * gutter
    grid_top = column_header_height + top_timeline_height
    grid_bottom = grid_top + image_grid_height
    sheet_height = column_header_height + image_grid_height + timeline_band_height
    sheet = Image.new("RGB", (sheet_width, sheet_height), canvas_color)
    draw = ImageDraw.Draw(sheet)
    origin_ms = columns[0].sample.image_mono_ms
    if column_label != "none":
        titles = [_column_title(column.sample, origin_ms, column_label) for column in columns]
        max_title_width = max(
            measure.textbbox((0, 0), title, font=column_font)[2]
            for title in titles
        )
        if max_title_width > cell_width - 8:
            raise ValueError(
                "列标题超出 cell_width；请增大 --cell-width 或减小 --column-font-size。"
            )

    for row_index, row_key in enumerate(rows):
        y = (
            grid_top + row_index * (cell_height + gutter)
        )
        _paste_centered_label_image(
            sheet,
            (2, y, label_width - 2, y + cell_height),
            row_label_images[row_key],
        )
        variant_id = (
            VARIANT_IDS[ROW_KEYS.index(row_key) - 2]
            if row_key not in {"passthrough", "reference"}
            else None
        )
        if variant_id is not None and variant_id in reference_error_summary:
            mean_position = reference_error_summary[variant_id]["mean_position_error_mm"]
            mean_rotation = reference_error_summary[variant_id]["mean_rotation_error_deg"]
            annotation = f"{float(mean_position):.2f} mm\n{float(mean_rotation):.2f}°"
            annotation_bounds = draw.multiline_textbbox(
                (0, 0), annotation, font=annotation_font, spacing=2, align="center"
            )
            annotation_height = annotation_bounds[3] - annotation_bounds[1] + 8
            annotation_box = (
                2,
                y + cell_height - annotation_height - 8,
                label_width - 2,
                y + cell_height - 8,
            )
            draw.rectangle(annotation_box, fill=canvas_color)
            _draw_centered_text(
                draw,
                annotation_box,
                annotation,
                annotation_font,
                _hex_to_rgb(str(method_colors_hex[VARIANT_IDS.index(variant_id)])),
                spacing=2,
            )
    for column_index, column in enumerate(columns):
        x = label_width + column_index * (cell_width + gutter)
        if column_label != "none":
            title = _column_title(column.sample, origin_ms, column_label)
            _draw_centered_text(
                draw,
                (
                    x,
                    0,
                    x + cell_width,
                    column_header_height,
                ),
                title,
                column_font,
                column_label_color,
            )
        crops = _render_column_crops(
            column,
            projector,
            rows,
            model_alpha=model_alpha,
            model_color=model_color,
            method_colors_hex=method_colors_hex,
            reference_alpha=reference_alpha,
            fill_mode=fill_mode,
            texture_backend=texture_backend,
            texture_max_size_px=texture_max_size_px,
            texture_brightness=texture_brightness,
            method_contour_thickness=method_contour_thickness,
            reference_contour_color=reference_contour_color,
            reference_contour_thickness=reference_contour_thickness,
            reference_halo_color=reference_halo_color,
            reference_halo_thickness=reference_halo_thickness,
            show_axes=show_axes,
            axis_style=axis_style,
        )
        for row_index, crop in enumerate(crops):
            y = grid_top + row_index * (cell_height + gutter)
            resized = Image.fromarray(crop, mode="RGB").resize(
                (cell_width, cell_height),
                Image.Resampling.LANCZOS,
            )
            sheet.paste(resized, (x, y))
            if border_thickness > 0:
                draw.rectangle(
                    (x, y, x + cell_width - 1, y + cell_height - 1),
                    outline=border_color,
                    width=border_thickness,
                )
    if timeline is not None and timeline.mode != "none":
        timeline_top = (
            column_header_height
            if timeline.placement == "top"
            else grid_bottom
        )
        _draw_timeline(
            draw,
            columns,
            label_width=label_width,
            cell_width=cell_width,
            gutter=gutter,
            top=timeline_top,
            grid_right=grid_right,
            grid_top=grid_top,
            settings=timeline,
        )
        if timeline.placement == "top":
            _draw_method_axis(
                draw,
                x=label_width,
                grid_top=grid_top,
                grid_bottom=grid_bottom,
                row_count=len(rows),
                cell_height=cell_height,
                gutter=gutter,
                settings=timeline,
            )
    coordinate_axes = {
        "enabled": bool(timeline_is_top),
        "origin": "top-left-of-first-image-cell" if timeline_is_top else None,
        "origin_px": [label_width, grid_top] if timeline_is_top else None,
        "x_direction": "right" if timeline_is_top else None,
        "x_semantic": timeline.mode if timeline_is_top and timeline is not None else None,
        "x_tick_alignment": "selected-column-centers" if timeline_is_top else None,
        "x_tick_centers_px": (
            [
                label_width
                + index * (cell_width + gutter)
                + cell_width // 2
                for index in range(len(columns))
            ]
            if timeline_is_top
            else []
        ),
        "image_grid_right_px": grid_right - 1 if timeline_is_top else None,
        "x_axis_end_px": (
            grid_right - 1 + timeline.right_extension_px
            if timeline_is_top and timeline is not None
            else None
        ),
        "right_extension_px": (
            int(timeline.right_extension_px)
            if timeline_is_top and timeline is not None
            else 0
        ),
        "y_direction": "down" if timeline_is_top else None,
        "y_semantic": "display-row-category" if timeline_is_top else None,
        "y_tick_alignment": "row-cell-centers" if timeline_is_top else None,
        "y_ticks": (
            [
                {
                    "row_key": row,
                    "label": row_titles[row],
                    "center_y_px": (
                        grid_top
                        + index * (cell_height + gutter)
                        + cell_height // 2
                    ),
                }
                for index, row in enumerate(rows)
            ]
            if timeline_is_top
            else []
        ),
    }
    return np.asarray(sheet, dtype=np.uint8), timeline_band_height, coordinate_axes


def _timeline_band_height(settings: TimelineSettings | None) -> int:
    """由时间轴样式推导稳定区域高度；关闭时不占画布空间。"""

    if settings is None or settings.mode == "none":
        return 0
    arrow_height = _timeline_arrow_height(settings)
    text_band = settings.font_size_px + 4
    return (
        settings.padding_px * 4
        + arrow_height
        + settings.tick_length_px
        + text_band * 2
    )


def _draw_timeline(
    draw: ImageDraw.ImageDraw,
    columns: Sequence[GridColumn],
    *,
    label_width: int,
    cell_width: int,
    gutter: int,
    top: int,
    grid_right: int,
    grid_top: int,
    settings: TimelineSettings,
) -> None:
    """绘制与各列中心对齐的相对时间或保存帧序号横轴。"""

    font = _load_font(settings.font_size_px)
    color = _hex_to_rgb(settings.color_hex)
    padding = settings.padding_px
    arrow_height = _timeline_arrow_height(settings)
    text_band = settings.font_size_px + 4
    if settings.placement == "top":
        line_y = grid_top
        tick_label_top = line_y - settings.tick_length_px - padding - text_band
        title_top = top + padding
        tick_start_y = line_y - settings.tick_length_px
    else:
        line_y = top
        tick_label_top = line_y + settings.tick_length_px + padding
        title_top = tick_label_top + text_band + padding
        tick_start_y = line_y + settings.tick_length_px
    tick_centers = tuple(
        label_width + index * (cell_width + gutter) + cell_width // 2
        for index in range(len(columns))
    )
    # 延伸量从最后一列图像的实际右边缘计算，不能再被版式留白抵消。
    line_end = grid_right - 1 + settings.right_extension_px
    _draw_centered_text(
        draw,
        (label_width, title_top, grid_right, title_top + text_band),
        _timeline_title(settings.mode),
        font,
        color,
    )
    draw.line(
        (label_width, line_y, line_end, line_y),
        fill=color,
        width=settings.line_thickness_px,
    )
    draw.polygon(
        (
            (line_end, line_y),
            (
                line_end - arrow_height,
                line_y - arrow_height if settings.placement == "top" else line_y,
            ),
            (
                line_end - arrow_height,
                line_y if settings.placement == "top" else line_y + arrow_height,
            ),
        ),
        fill=color,
    )

    origin_ms = columns[0].sample.image_mono_ms
    tick_labels = tuple(
        _timeline_tick_label(column.sample, origin_ms, settings.mode) for column in columns
    )
    max_tick_width = max(
        draw.textbbox((0, 0), label, font=font)[2] for label in tick_labels
    )
    if max_tick_width > cell_width - 8:
        raise ValueError(
            "时间刻度超出 cell_width；请增大 --cell-width 或减小 timeline.font_size_px。"
        )
    for center, label in zip(tick_centers, tick_labels, strict=True):
        draw.line(
            (center, line_y, center, tick_start_y),
            fill=color,
            width=settings.line_thickness_px,
        )
        _draw_centered_text(
            draw,
            (
                center - cell_width // 2,
                tick_label_top,
                center + cell_width // 2,
                tick_label_top + text_band,
            ),
            label,
            font,
            color,
        )


def _draw_method_axis(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    grid_top: int,
    grid_bottom: int,
    row_count: int,
    cell_height: int,
    gutter: int,
    settings: TimelineSettings,
) -> None:
    """以第一格左上角为原点，绘制向下的方法类别轴。"""

    color = _hex_to_rgb(settings.color_hex)
    arrow_size = _timeline_arrow_height(settings)
    arrow_half = max(3, arrow_size // 2)
    draw.line(
        (x, grid_top, x, grid_bottom - 1),
        fill=color,
        width=settings.line_thickness_px,
    )
    draw.polygon(
        (
            (x, grid_bottom - 1),
            (x - arrow_half, grid_bottom - 1 - arrow_size),
            (x + arrow_half, grid_bottom - 1 - arrow_size),
        ),
        fill=color,
    )
    for row_index in range(row_count):
        center_y = grid_top + row_index * (cell_height + gutter) + cell_height // 2
        draw.line(
            (x - settings.tick_length_px, center_y, x, center_y),
            fill=color,
            width=settings.line_thickness_px,
        )
    radius = max(2, settings.line_thickness_px)
    draw.ellipse(
        (x - radius, grid_top - radius, x + radius, grid_top + radius),
        fill=color,
    )


def _timeline_arrow_height(settings: TimelineSettings) -> int:
    """限制箭头尺寸，避免极端线宽越过最后一列边界。"""

    return max(6, min(16, settings.line_thickness_px * 4))


def _timeline_title(mode: str) -> str:
    """返回时间轴模式对应的可见标题。"""

    return "Frame" if mode == "frame-sequence" else "Δt (s)"


def _timeline_tick_label(sample: ReplaySample, origin_ms: float, mode: str) -> str:
    """按模式格式化相对秒数或可复现的保存帧序号。"""

    if mode == "frame-sequence":
        return str(int(sample.sample_id))

    return f"{(sample.image_mono_ms - origin_ms) / 1000.0:.2f}"


def _effective_timeline_configuration(
    settings: TimelineSettings | None,
) -> dict[str, Any]:
    """生成参与统一配置哈希的时间轴有效参数。"""

    if settings is None or settings.mode == "none":
        return {
            "mode": settings.mode if settings is not None else "none",
            "placement": None,
            "font_size_px": None,
            "color_hex": None,
            "line_thickness_px": None,
            "tick_length_px": None,
            "padding_px": None,
            "right_extension_px": None,
        }
    return {
        "mode": settings.mode,
        "placement": settings.placement,
        "font_size_px": int(settings.font_size_px),
        "color_hex": settings.color_hex,
        "line_thickness_px": int(settings.line_thickness_px),
        "tick_length_px": int(settings.tick_length_px),
        "padding_px": int(settings.padding_px),
        "right_extension_px": int(settings.right_extension_px),
    }


def _timeline_metadata(
    columns: Sequence[GridColumn],
    settings: TimelineSettings | None,
    *,
    band_height: int,
) -> dict[str, Any]:
    """记录时间轴来源、视觉参数和最终可见刻度。"""

    enabled = settings is not None and settings.mode != "none"
    if not enabled:
        return {
            "mode": settings.mode if settings is not None else "none",
            "placement": None,
            "ticks": [],
            "band_height_px": 0,
        }
    assert settings is not None
    origin_ms = columns[0].sample.image_mono_ms
    return {
        "mode": settings.mode,
        "placement": settings.placement,
        "title": _timeline_title(settings.mode),
        "time_source": "sample_id" if settings.mode == "frame-sequence" else "image_mono_ms",
        "origin": "first_selected_sample",
        "origin_sample_id": columns[0].sample.sample_id,
        "coordinate_origin": (
            "top-left-of-first-image-cell"
            if settings.placement == "top"
            else None
        ),
        "horizontal_axis_start": "first-image-left-edge",
        "unit": "saved-sample-index" if settings.mode == "frame-sequence" else "seconds",
        "decimal_places": None if settings.mode == "frame-sequence" else 2,
        "tick_alignment": "selected_column_centers",
        "spacing_semantics": (
            "equal column spacing; labels use saved sample sequence; not a metric time scale"
            if settings.mode == "frame-sequence"
            else "equal column spacing; labels use actual timestamps; not a metric time scale"
        ),
        "font_size_px": int(settings.font_size_px),
        "font_identifier": _font_identifier(int(settings.font_size_px)),
        "color_hex": settings.color_hex,
        "line_thickness_px": int(settings.line_thickness_px),
        "tick_length_px": int(settings.tick_length_px),
        "padding_px": int(settings.padding_px),
        "right_extension_px": int(settings.right_extension_px),
        "band_height_px": int(band_height),
        "ticks": [
            {
                "column_index": index,
                "sample_id": column.sample.sample_id,
                "delta_time_ms": column.sample.image_mono_ms - origin_ms,
                "label": _timeline_tick_label(column.sample, origin_ms, settings.mode),
            }
            for index, column in enumerate(columns)
        ],
    }


def _render_column_crops(
    column: GridColumn,
    projector: MeshProjector,
    selected_rows: Sequence[str],
    *,
    model_alpha: float,
    model_color: tuple[int, int, int],
    method_colors_hex: Sequence[str],
    reference_alpha: float,
    fill_mode: str,
    texture_backend: str,
    texture_max_size_px: int,
    texture_brightness: float,
    method_contour_thickness: int,
    reference_contour_color: tuple[int, int, int],
    reference_contour_thickness: int,
    reference_halo_color: tuple[int, int, int],
    reference_halo_thickness: int,
    show_axes: bool,
    axis_style: AxisDrawStyle,
) -> tuple[np.ndarray, ...]:
    """用一份裁剪框生成该列选定行，禁止每个方法独立缩放。"""

    x, y, width, height = column.crop
    background = column.background[y : y + height, x : x + width]
    masks = tuple(mask[y : y + height, x : x + width] for mask in column.masks)
    axes = tuple(_translate_axes(points, -x, -y) for points in column.axes)
    image_height, image_width = column.background.shape[:2]
    camera_matrix = _camera_matrix(column.sample)
    selected = set(selected_rows)
    reference_texture = (
        _texture_layer(
            projector,
            recorded_projection_matrix(column.sample.platform_reference),
            camera_matrix,
            image_width,
            image_height,
            column.crop,
            fill_mode=fill_mode,
            backend=texture_backend,
            max_texture_size_px=texture_max_size_px,
            brightness=texture_brightness,
        )
        if "reference" in selected
        else None
    )
    reference = _overlay_reference(
        background,
        masks[0],
        fill_texture=reference_texture,
        fill_alpha=reference_alpha,
        fill_color=model_color,
        contour_color=reference_contour_color,
        contour_thickness=reference_contour_thickness,
        halo_color=reference_halo_color,
        halo_thickness=reference_halo_thickness,
    )
    if show_axes and "reference" in selected:
        reference = _draw_axes(
            reference,
            axes[0],
            axis_style,
        )
    rendered_rows = [background.copy(), reference]
    for index, (color_hex, mask) in enumerate(
        zip(method_colors_hex, masks[1:], strict=True),
        start=1,
    ):
        row_key = ROW_KEYS[index + 1]
        variant = column.sample.variants[index - 1]
        texture = (
            _texture_layer(
                projector,
                recorded_projection_matrix(variant),
                camera_matrix,
                image_width,
                image_height,
                column.crop,
                fill_mode=fill_mode,
                backend=texture_backend,
                max_texture_size_px=texture_max_size_px,
                brightness=texture_brightness,
            )
            if row_key in selected
            else None
        )
        rendered = _overlay_single(
            background,
            mask,
            _hex_to_rgb(color_hex),
            fill_alpha=model_alpha,
            fill_color=model_color,
            fill_texture=texture,
            contour_thickness=method_contour_thickness,
        )
        if show_axes and row_key in selected and np.all(np.isfinite(axes[index])):
            rendered = _draw_axes(
                rendered,
                axes[index],
                axis_style,
            )
        rendered_rows.append(rendered)
    return tuple(rendered_rows[ROW_KEYS.index(label)] for label in selected_rows)


def _column_title(sample: ReplaySample, origin_ms: float, mode: str) -> str:
    """按稳定模式生成可选列标题。"""

    delta_seconds = (sample.image_mono_ms - origin_ms) / 1000.0
    delta_text = f"Δt={delta_seconds:.2f} s"
    if mode == "delta-t":
        return delta_text
    if mode == "sample-id":
        return sample.sample_id
    return f"{sample.sample_id}  {delta_text}"


def _validate_rows(rows: Sequence[str]) -> tuple[str, ...]:
    """校验显示行名称并保留用户给出的排列顺序。"""

    selected = tuple(str(row) for row in rows)
    if not selected:
        raise ValueError("rows 至少需要一行。")
    unknown = [row for row in selected if row not in ROW_KEYS]
    if unknown:
        raise ValueError(f"未知 rows: {unknown}；可选值为 {ROW_KEYS}。")
    if len(set(selected)) != len(selected):
        raise ValueError("rows 不能包含重复行。")
    return selected


def _resolve_row_titles(row_titles: Sequence[str]) -> dict[str, str]:
    """把六个可见标题绑定到稳定行键，并拒绝空标题或空白行。"""

    titles = tuple(str(title) for title in row_titles)
    if len(titles) != len(ROW_KEYS):
        raise ValueError("row_titles 必须恰好包含六个标题。")
    if any(not title.strip() for title in titles):
        raise ValueError("row_titles 不能包含空标题。")
    if any(any(not line.strip() for line in title.split("\n")) for title in titles):
        raise ValueError("row_titles 不能包含空白行。")
    return dict(zip(ROW_KEYS, titles, strict=True))


def _row_mask_indices(rows: Sequence[str]) -> tuple[int, ...]:
    """把显示行映射为 mask 索引；passthrough 使用 reference 确定裁剪范围。"""

    indices = {
        0 if row == "passthrough" else ROW_KEYS.index(row) - 1
        for row in rows
    }
    indices.add(0)
    return tuple(sorted(indices))


def _required_variant_ids(rows: Sequence[str]) -> tuple[str, ...]:
    """把显示行映射到需要具备 display pose 的实验一 variant。"""

    return tuple(
        VARIANT_IDS[ROW_KEYS.index(row) - 2]
        for row in rows
        if row not in {"passthrough", "reference"}
    )


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
    fill_color: tuple[int, int, int] | None = None,
    fill_texture: TextureLayer | None = None,
    contour_thickness: int,
) -> np.ndarray:
    """叠加纹理或回退纯色填充，再绘制方法色实线轮廓。"""

    output = background.copy()
    selected = np.asarray(mask) > 0
    if np.any(selected):
        alpha = float(np.clip(fill_alpha, 0.0, 1.0))
        resolved_fill = color if fill_color is None else fill_color
        fill = np.empty_like(output)
        fill[:, :] = np.asarray(resolved_fill, dtype=np.uint8)
        if fill_texture is not None:
            textured = (np.asarray(fill_texture.mask) > 0) & selected
            fill[textured] = fill_texture.rgb[textured]
        output[selected] = np.rint(
            output[selected].astype(np.float32) * (1.0 - alpha)
            + fill[selected].astype(np.float32) * alpha
        ).astype(np.uint8)
    return _draw_contours(output, mask, color, max(1, int(contour_thickness)))


def _overlay_reference(
    background: np.ndarray,
    mask: np.ndarray,
    *,
    fill_texture: TextureLayer | None,
    fill_alpha: float,
    fill_color: tuple[int, int, int],
    contour_color: tuple[int, int, int],
    contour_thickness: int,
    halo_color: tuple[int, int, int],
    halo_thickness: int,
) -> np.ndarray:
    """用可配置 halo、内轮廓和纹理填充绘制 Quest 官方参考。"""

    halo = _draw_contours(background, mask, halo_color, halo_thickness)
    return _overlay_single(
        halo,
        mask,
        contour_color,
        fill_alpha=fill_alpha,
        fill_color=fill_color,
        fill_texture=fill_texture,
        contour_thickness=contour_thickness,
    )


def _texture_layer(
    projector: MeshProjector,
    pose_cv_camera: np.ndarray,
    camera_matrix: np.ndarray,
    image_width: int,
    image_height: int,
    crop_xywh: tuple[int, int, int, int],
    *,
    fill_mode: str,
    backend: str,
    max_texture_size_px: int,
    brightness: float,
) -> TextureLayer | None:
    """按填充模式生成裁剪纹理图层；无纹理时由调用方回退纯色。"""

    if fill_mode != "texture":
        return None
    rendered = projector.render_texture_crop(
        pose_cv_camera,
        camera_matrix,
        image_width,
        image_height,
        crop_xywh,
        backend=backend,
        max_texture_size_px=max_texture_size_px,
    )
    if rendered is None:
        return None
    rgb, mask = rendered
    adjusted = np.clip(
        np.rint(rgb.astype(np.float32) * float(brightness)),
        0,
        255,
    ).astype(np.uint8)
    return TextureLayer(rgb=adjusted, mask=mask)


def _draw_axes(
    image: np.ndarray,
    points: np.ndarray,
    style: AxisDrawStyle,
) -> np.ndarray:
    """在模型层和轮廓上方按统一样式绘制 X/Y/Z 正轴。"""

    projected = np.asarray(points, dtype=np.float64).reshape(4, 2)
    if not np.all(np.isfinite(projected)):
        raise ValueError("坐标轴投影点必须全部为有限值。")
    output = image.copy()
    origin = tuple(np.rint(projected[0]).astype(int))
    font_face = cv2.FONT_HERSHEY_SIMPLEX
    unit_height = cv2.getTextSize("X", font_face, 1.0, style.thickness_px)[0][1]
    font_scale = float(style.label_font_size_px) / max(1, unit_height)
    halo_color = _hex_to_rgb(style.halo_color_hex)
    for endpoint, label, color_hex in zip(
        projected[1:],
        ("X", "Y", "Z"),
        style.colors_hex,
        strict=True,
    ):
        target = tuple(np.rint(endpoint).astype(int))
        color = _hex_to_rgb(str(color_hex))
        cv2.arrowedLine(
            output,
            origin,
            target,
            halo_color,
            style.halo_thickness_px,
            cv2.LINE_AA,
            tipLength=style.tip_length,
        )
        cv2.arrowedLine(
            output,
            origin,
            target,
            color,
            style.thickness_px,
            cv2.LINE_AA,
            tipLength=style.tip_length,
        )
        text_origin = (
            target[0] + style.label_offset_px[0],
            target[1] + style.label_offset_px[1],
        )
        cv2.putText(
            output,
            label,
            text_origin,
            font_face,
            font_scale,
            halo_color,
            style.halo_thickness_px,
            cv2.LINE_AA,
        )
        cv2.putText(
            output,
            label,
            text_origin,
            font_face,
            font_scale,
            color,
            style.thickness_px,
            cv2.LINE_AA,
        )
    cv2.circle(
        output,
        origin,
        style.origin_radius_px + max(1, style.halo_thickness_px - style.thickness_px),
        halo_color,
        -1,
        cv2.LINE_AA,
    )
    cv2.circle(
        output,
        origin,
        style.origin_radius_px,
        _hex_to_rgb(style.origin_color_hex),
        -1,
        cv2.LINE_AA,
    )
    return output


def _geometry_coverage_mask(
    model_mask: np.ndarray,
    axes: np.ndarray,
    *,
    show_axes: bool,
    axis_style: AxisDrawStyle,
) -> np.ndarray:
    """生成模型、轴线、箭头和标签的裁剪覆盖 mask。"""

    coverage = (np.asarray(model_mask) > 0).astype(np.uint8) * 255
    if not show_axes:
        return coverage
    axis_layer = _draw_axes(
        np.zeros((*coverage.shape, 3), dtype=np.uint8),
        axes,
        axis_style,
    )
    coverage[np.any(axis_layer > 0, axis=2)] = 255
    return coverage


def _translate_axes(points: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """把原图坐标轴点平移到裁剪图坐标。"""

    translated = np.asarray(points, dtype=np.float64).copy()
    translated[:, 0] += float(dx)
    translated[:, 1] += float(dy)
    return translated


def _axis_margin_px(style: AxisDrawStyle) -> int:
    """为箭头 halo 和轴端字母预留原图边界距离。"""

    return (
        style.label_font_size_px
        + style.halo_thickness_px
        + max(abs(style.label_offset_px[0]), abs(style.label_offset_px[1]))
        + 4
    )


def _validate_timeline_settings(settings: TimelineSettings | None) -> None:
    """校验包级调用者直接传入的时间轴样式。"""

    if settings is None:
        return
    if settings.mode not in TIMELINE_MODES:
        raise ValueError(f"timeline.mode 必须是 {TIMELINE_MODES} 之一。")
    if settings.placement not in TIMELINE_PLACEMENTS:
        raise ValueError(f"timeline.placement 必须是 {TIMELINE_PLACEMENTS} 之一。")
    if not 8 <= int(settings.font_size_px) <= 96:
        raise ValueError("timeline.font_size_px 必须位于 8 到 96。")
    _hex_to_rgb(settings.color_hex)
    if not 1 <= int(settings.line_thickness_px) <= 20:
        raise ValueError("timeline.line_thickness_px 必须位于 1 到 20。")
    if not 1 <= int(settings.tick_length_px) <= 64:
        raise ValueError("timeline.tick_length_px 必须位于 1 到 64。")
    if not 0 <= int(settings.padding_px) <= 96:
        raise ValueError("timeline.padding_px 必须位于 0 到 96。")
    if not 0 <= int(settings.right_extension_px) <= 256:
        raise ValueError("timeline.right_extension_px 必须位于 0 到 256。")


def _validate_overlay_options(
    *,
    model_alpha: float,
    reference_alpha: float,
    fill_mode: str,
    texture_backend: str,
    texture_max_size_px: int,
    texture_brightness: float,
    method_colors_hex: Sequence[str],
    method_contour_thickness: int,
    reference_contour_color_hex: str,
    reference_contour_thickness: int,
    reference_halo_color_hex: str,
    reference_halo_thickness: int,
    show_axes: bool,
    axis_length_m: float,
    axis_thickness: int,
    axis_label_font_size: int,
    axis_colors_hex: Sequence[str],
    axis_halo_color_hex: str,
    axis_halo_thickness: int,
    axis_tip_length: float,
    axis_label_offset_px: tuple[int, int],
    axis_origin_color_hex: str,
    axis_origin_radius: int,
) -> None:
    """统一校验半透明模型、轮廓和坐标轴的出图参数。"""

    if not 0.0 <= float(model_alpha) <= 1.0:
        raise ValueError("model_alpha 必须位于 0 到 1。")
    if not 0.0 <= float(reference_alpha) <= 1.0:
        raise ValueError("reference_alpha 必须位于 0 到 1。")
    if fill_mode not in {"texture", "color"}:
        raise ValueError("fill_mode 必须是 texture 或 color。")
    if texture_backend not in TEXTURE_RENDER_BACKENDS:
        raise ValueError(f"texture_backend 必须是 {TEXTURE_RENDER_BACKENDS} 之一。")
    if int(texture_max_size_px) != 0 and not 64 <= int(texture_max_size_px) <= 4096:
        raise ValueError("texture_max_size_px 必须为 0 或位于 64 到 4096。")
    if not 0.0 <= float(texture_brightness) <= 3.0:
        raise ValueError("texture_brightness 必须位于 0 到 3。")
    if len(tuple(method_colors_hex)) != 4:
        raise ValueError("method_colors_hex 必须依次提供四种方法颜色。")
    for color_hex in method_colors_hex:
        _hex_to_rgb(str(color_hex))
    if not 1 <= int(method_contour_thickness) <= 20:
        raise ValueError("method_contour_thickness 必须位于 1 到 20 px。")
    _hex_to_rgb(reference_contour_color_hex)
    _hex_to_rgb(reference_halo_color_hex)
    if not 1 <= int(reference_contour_thickness) <= 20:
        raise ValueError("reference_contour_thickness 必须位于 1 到 20 px。")
    if not int(reference_contour_thickness) <= int(reference_halo_thickness) <= 20:
        raise ValueError("reference_halo_thickness 必须位于参考内轮廓线宽到 20 px。")
    if not isinstance(show_axes, bool):
        raise ValueError("show_axes 必须是布尔值。")
    if not np.isfinite(float(axis_length_m)) or not 0.001 <= float(axis_length_m) <= 1.0:
        raise ValueError("axis_length_m 必须位于 0.001 到 1.0 m。")
    if not 1 <= int(axis_thickness) <= 20:
        raise ValueError("axis_thickness 必须位于 1 到 20 px。")
    if not 8 <= int(axis_label_font_size) <= 96:
        raise ValueError("axis_label_font_size 必须位于 8 到 96 px。")
    if len(tuple(axis_colors_hex)) != 3:
        raise ValueError("axis_colors_hex 必须依次提供 X、Y、Z 三种颜色。")
    for color_hex in axis_colors_hex:
        _hex_to_rgb(str(color_hex))
    _hex_to_rgb(axis_halo_color_hex)
    _hex_to_rgb(axis_origin_color_hex)
    if not int(axis_thickness) <= int(axis_halo_thickness) <= 20:
        raise ValueError("axis_halo_thickness 必须位于轴线宽到 20 px。")
    if not 0.05 <= float(axis_tip_length) <= 0.5:
        raise ValueError("axis_tip_length 必须位于 0.05 到 0.5。")
    if len(axis_label_offset_px) != 2 or any(
        not -64 <= int(value) <= 64 for value in axis_label_offset_px
    ):
        raise ValueError("axis_label_offset_px 必须包含两个 -64 到 64 的整数。")
    if not 1 <= int(axis_origin_radius) <= 32:
        raise ValueError("axis_origin_radius 必须位于 1 到 32 px。")


def _axis_draw_style(
    colors_hex: Sequence[str],
    *,
    thickness: int,
    label_font_size: int,
    halo_color_hex: str,
    halo_thickness: int,
    tip_length: float,
    label_offset_px: tuple[int, int],
    origin_color_hex: str,
    origin_radius: int,
) -> AxisDrawStyle:
    """把已校验的坐标轴参数收束为内部绘制样式。"""

    colors = tuple(str(value) for value in colors_hex)
    if len(colors) != 3:
        raise ValueError("坐标轴颜色必须恰好包含三个值。")
    return AxisDrawStyle(
        colors_hex=(colors[0], colors[1], colors[2]),
        thickness_px=int(thickness),
        label_font_size_px=int(label_font_size),
        halo_color_hex=str(halo_color_hex),
        halo_thickness_px=int(halo_thickness),
        tip_length=float(tip_length),
        label_offset_px=(int(label_offset_px[0]), int(label_offset_px[1])),
        origin_color_hex=str(origin_color_hex),
        origin_radius_px=int(origin_radius),
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

    if len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"颜色必须是 #RRGGBB: {value}")
    text = value[1:]
    if any(character not in "0123456789abcdefABCDEF" for character in text):
        raise ValueError(f"颜色必须是 #RRGGBB: {value}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _extract_mesh_texture(
    mesh: trimesh.Trimesh,
) -> tuple[np.ndarray | None, np.ndarray | None, str | None]:
    """从 TextureVisuals 提取逐顶点 UV 和 PBR base-color RGB。"""

    visual = mesh.visual
    raw_uv = getattr(visual, "uv", None)
    material = getattr(visual, "material", None)
    if raw_uv is None or material is None:
        return None, None, None
    texture_image = getattr(material, "baseColorTexture", None)
    texture_source = "pbr_baseColorTexture"
    if texture_image is None:
        texture_image = getattr(material, "image", None)
        texture_source = "material_image"
    if texture_image is None:
        return None, None, None
    uv = np.asarray(raw_uv, dtype=np.float64)
    if uv.shape != (len(mesh.vertices), 2) or not np.all(np.isfinite(uv)):
        raise ValueError("replay mesh 的 UV 必须与顶点一一对应且全部有限。")
    texture = np.asarray(texture_image.convert("RGB"), dtype=np.uint8).copy()
    if texture.ndim != 3 or texture.shape[2] != 3 or min(texture.shape[:2]) <= 0:
        raise ValueError("replay mesh 的 base-color 纹理必须是非空 RGB 图像。")
    return uv, texture, texture_source


def _filter_small_face_components(
    faces: np.ndarray,
    *,
    minimum_faces: int,
) -> np.ndarray:
    """按共享边连通分量剔除小型装饰几何，减少论文图中的握持纹理干扰。"""

    face_array = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    threshold = int(minimum_faces)
    if not 1 <= threshold <= 1000:
        raise ValueError("minimum_faces 必须位于 1 到 1000。")
    if threshold == 1 or len(face_array) == 0:
        return face_array.copy()
    adjacency = trimesh.graph.face_adjacency(face_array)
    components = trimesh.graph.connected_components(
        adjacency,
        nodes=np.arange(len(face_array), dtype=np.int64),
        min_len=1,
    )
    kept = [np.asarray(component, dtype=np.int64) for component in components if len(component) >= threshold]
    if not kept:
        raise ValueError(
            f"minimum_component_faces={threshold} 会移除全部 mesh 组件。"
        )
    indices = np.sort(np.concatenate(kept))
    return face_array[indices]


def _validate_crop_box(
    crop_xywh: tuple[int, int, int, int],
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    """校验原图坐标中的纹理栅格化裁剪框。"""

    x, y, width, height = (int(value) for value in crop_xywh)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("纹理裁剪要求 x/y 非负且 width/height 为正。")
    if x + width > image_width or y + height > image_height:
        raise ValueError("纹理裁剪框超出原图边界。")
    return x, y, width, height


def _rasterize_textured_triangle(
    color: np.ndarray,
    visible: np.ndarray,
    depth: np.ndarray,
    projected: np.ndarray,
    camera_z: np.ndarray,
    uv: np.ndarray,
    texture: np.ndarray,
) -> None:
    """用像素中心重心坐标、1/z 校正和双线性采样写入单个三角形。"""

    height, width = visible.shape
    x_min = max(0, int(np.floor(np.min(projected[:, 0]))))
    x_max = min(width - 1, int(np.ceil(np.max(projected[:, 0]))))
    y_min = max(0, int(np.floor(np.min(projected[:, 1]))))
    y_max = min(height - 1, int(np.ceil(np.max(projected[:, 1]))))
    if x_min > x_max or y_min > y_max:
        return
    x0, y0 = projected[0]
    x1, y1 = projected[1]
    x2, y2 = projected[2]
    denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if not np.isfinite(denominator) or abs(float(denominator)) <= 1e-12:
        return
    yy, xx = np.mgrid[y_min : y_max + 1, x_min : x_max + 1]
    px = xx.astype(np.float64) + 0.5
    py = yy.astype(np.float64) + 0.5
    weight0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denominator
    weight1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denominator
    weight2 = 1.0 - weight0 - weight1
    inside = (weight0 >= -1e-9) & (weight1 >= -1e-9) & (weight2 >= -1e-9)
    inverse_z = (
        weight0 / camera_z[0]
        + weight1 / camera_z[1]
        + weight2 / camera_z[2]
    )
    valid = inside & np.isfinite(inverse_z) & (inverse_z > 0.0)
    candidate_depth = np.full_like(inverse_z, np.inf)
    candidate_depth[valid] = 1.0 / inverse_z[valid]
    target_depth = depth[y_min : y_max + 1, x_min : x_max + 1]
    update = valid & (candidate_depth < target_depth)
    if not np.any(update):
        return

    u_over_z = (
        weight0 * uv[0, 0] / camera_z[0]
        + weight1 * uv[1, 0] / camera_z[1]
        + weight2 * uv[2, 0] / camera_z[2]
    )
    v_over_z = (
        weight0 * uv[0, 1] / camera_z[0]
        + weight1 * uv[1, 1] / camera_z[1]
        + weight2 * uv[2, 1] / camera_z[2]
    )
    u = np.clip(u_over_z[update] / inverse_z[update], 0.0, 1.0)
    v = np.clip(v_over_z[update] / inverse_z[update], 0.0, 1.0)
    sampled = _sample_texture_bilinear(texture, u, v)

    target_color = color[y_min : y_max + 1, x_min : x_max + 1]
    target_visible = visible[y_min : y_max + 1, x_min : x_max + 1]
    target_color[update] = sampled
    target_visible[update] = 255
    target_depth[update] = candidate_depth[update]


def _sample_texture_bilinear(
    texture: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
) -> np.ndarray:
    """按 glTF UV 语义双线性采样顶左原点的 Pillow RGB 纹理。"""

    texture_height, texture_width = texture.shape[:2]
    x = u * float(texture_width - 1)
    y = (1.0 - v) * float(texture_height - 1)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x1 = np.minimum(x0 + 1, texture_width - 1)
    y1 = np.minimum(y0 + 1, texture_height - 1)
    wx = (x - x0)[:, None]
    wy = (y - y0)[:, None]
    top = texture[y0, x0].astype(np.float64) * (1.0 - wx) + texture[y0, x1] * wx
    bottom = texture[y1, x0].astype(np.float64) * (1.0 - wx) + texture[y1, x1] * wx
    return np.clip(np.rint(top * (1.0 - wy) + bottom * wy), 0, 255).astype(np.uint8)


def _validate_local_matrix(value: np.ndarray | None) -> np.ndarray:
    """校验 mesh 局部齐次变换，默认不变换。"""

    matrix = np.eye(4, dtype=np.float64) if value is None else np.asarray(value, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
        raise ValueError("mesh local_matrix 必须是 4x4 有限矩阵。")
    if not np.allclose(matrix[3], np.array([0.0, 0.0, 0.0, 1.0]), atol=1e-12):
        raise ValueError("mesh local_matrix 必须是合法齐次变换。")
    return matrix.copy()


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """优先使用常见无衬线字体，缺失时回退 Pillow 默认字体。"""

    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _font_identifier(size: int) -> str:
    """记录当前机器实际使用的字体文件或 Pillow 回退类型。"""

    font = _load_font(size)
    path = getattr(font, "path", None)
    return str(path) if path else type(font).__name__


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    color: tuple[int, int, int],
    *,
    spacing: int = 4,
) -> None:
    """在给定矩形内水平和垂直居中单行或多行文本。"""

    left, top, right, bottom = box
    bounds = draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        spacing=int(spacing),
        align="center",
    )
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    x = left + (right - left - width) * 0.5
    y = top + (bottom - top - height) * 0.5 - bounds[1]
    draw.multiline_text(
        (x, y),
        text,
        fill=color,
        font=font,
        spacing=int(spacing),
        align="center",
    )


def _render_rotated_text_image(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    color: tuple[int, int, int],
    *,
    spacing: int,
    rotation_deg: int,
) -> Image.Image:
    """把单行或多行标题渲染为可旋转的透明文字图层。"""

    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
    bounds = measure.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        spacing=int(spacing),
        align="center",
    )
    padding = 2
    width = max(1, int(math.ceil(bounds[2] - bounds[0])) + padding * 2)
    height = max(1, int(math.ceil(bounds[3] - bounds[1])) + padding * 2)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(image).multiline_text(
        (padding - bounds[0], padding - bounds[1]),
        text,
        fill=(*color, 255),
        font=font,
        spacing=int(spacing),
        align="center",
    )
    if int(rotation_deg):
        image = image.rotate(
            float(rotation_deg),
            resample=Image.Resampling.BICUBIC,
            expand=True,
        )
    visible = image.getbbox()
    return image.crop(visible) if visible is not None else image


def _paste_centered_label_image(
    sheet: Image.Image,
    box: tuple[int, int, int, int],
    image: Image.Image,
) -> None:
    """把透明文字图层居中贴入标签区域。"""

    left, top, right, bottom = box
    x = int(round(left + (right - left - image.width) * 0.5))
    y = int(round(top + (bottom - top - image.height) * 0.5))
    sheet.paste(image, (x, y), image)


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


def _write_rgb_pdf(path: Path, image: np.ndarray) -> None:
    """把最终 RGB 网格写成单页 PDF，供 LaTeX 直接导入。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(image, dtype=np.uint8), mode="RGB").save(
        path,
        format="PDF",
        resolution=300.0,
        quality=100,
        subsampling=0,
    )


__all__ = [
    "COLUMN_LABEL_MODES",
    "GridColumn",
    "MeshProjector",
    "ROW_IDS",
    "ROW_KEYS",
    "ROW_TITLES",
    "describe_samples",
    "render_comparison_grid",
    "render_frame_overlays",
    "select_samples_by_ids",
    "select_stride_samples",
]
