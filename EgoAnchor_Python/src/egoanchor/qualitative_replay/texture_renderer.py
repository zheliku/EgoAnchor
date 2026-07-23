"""定性 replay 的纹理栅格化后端。"""

from __future__ import annotations

import cv2
import numpy as np


TEXTURE_RENDER_BACKENDS = ("auto", "nvdiffrast", "cpu")
"""TOML 和 CLI 接受的纹理栅格化后端。"""


class NvdiffrastTextureRenderer:
    """复用 VCD 同款 nvdiffrast 语义渲染 unlit base-color 纹理。"""

    def __init__(
        self,
        vertices: np.ndarray,
        faces: np.ndarray,
        uv: np.ndarray,
        texture_rgb: np.ndarray,
        *,
        max_texture_size_px: int,
    ) -> None:
        """在 CUDA 上缓存 mesh、UV、纹理和 raster context。"""

        import nvdiffrast.torch as dr  # type: ignore[import-untyped]
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("nvdiffrast 纹理后端要求可用的 CUDA 设备。")
        device = torch.device("cuda")
        self._device = device
        """纹理、面索引和 clip-space 顶点共用的 CUDA 设备。"""
        raw_vertices = np.asarray(vertices, dtype=np.float64)
        self._model_center = (
            np.min(raw_vertices, axis=0) + np.max(raw_vertices, axis=0)
        ) * 0.5
        """与 FoundationPose `reset_object` 完全一致的轴对齐模型中心。"""
        self._vertices_numpy = raw_vertices - self._model_center
        """VCD renderer 实际使用的中心化 mesh 顶点。"""
        self._torch = torch
        """延迟导入的 torch 模块，避免 CPU 单测加载 CUDA。"""
        self._dr = dr
        """延迟导入的 nvdiffrast.torch 模块。"""
        self._context = dr.RasterizeCudaContext()
        """与 VCD renderer 相同类型的 CUDA raster context。"""
        self._faces = torch.as_tensor(
            np.asarray(faces, dtype=np.int32),
            dtype=torch.int32,
            device=device,
        )
        """三角面索引。"""
        uv_array = np.asarray(uv, dtype=np.float32).copy()
        uv_array[:, 1] = 1.0 - uv_array[:, 1]
        self._uv = torch.as_tensor(uv_array, dtype=torch.float32, device=device)
        """按 FoundationPose `make_mesh_tensors` 规则翻转 V 的纹理坐标。"""
        texture = np.asarray(texture_rgb, dtype=np.uint8)
        longest_edge = max(texture.shape[:2])
        if 0 < int(max_texture_size_px) < longest_edge:
            scale = float(max_texture_size_px) / float(longest_edge)
            target_size = (
                max(1, int(round(texture.shape[1] * scale))),
                max(1, int(round(texture.shape[0] * scale))),
            )
            texture = cv2.resize(texture, target_size, interpolation=cv2.INTER_AREA)
        self.texture_size = (int(texture.shape[1]), int(texture.shape[0]))
        """实际送入 CUDA renderer 的预滤波纹理宽高。"""
        self._texture = torch.as_tensor(
            np.asarray(texture, dtype=np.float32) / 255.0,
            dtype=torch.float32,
            device=device,
        )[None]
        """顶左原点的 RGB base-color 纹理。"""

    def render_crop(
        self,
        pose_cv_camera: np.ndarray,
        camera_matrix: np.ndarray,
        crop_xywh: tuple[int, int, int, int],
    ) -> tuple[np.ndarray, np.ndarray]:
        """按 OpenCV camera pose 在原图裁剪框内输出 RGB 与可见 mask。"""

        torch = self._torch
        x_crop, y_crop, width, height = crop_xywh
        pose = np.asarray(pose_cv_camera, dtype=np.float64).reshape(4, 4)
        camera = np.asarray(camera_matrix, dtype=np.float64).reshape(3, 3)
        centered_pose = pose.copy()
        centered_pose[:3, 3] += pose[:3, :3] @ self._model_center
        points_camera = (
            self._vertices_numpy @ centered_pose[:3, :3].T
            + centered_pose[:3, 3]
        )
        if not np.all(np.isfinite(points_camera)) or np.any(points_camera[:, 2] <= 1e-4):
            raise ValueError("nvdiffrast 纹理投影要求全部 mesh 顶点位于相机近裁剪面之前。")

        crop_camera = camera.copy()
        crop_camera[0, 2] -= float(x_crop)
        crop_camera[1, 2] -= float(y_crop)
        near, far = 1e-3, 100.0
        depth = far - near
        q = -(far + near) / depth
        qn = -2.0 * far * near / depth
        projection = np.array(
            [
                [
                    2.0 * crop_camera[0, 0] / width,
                    -2.0 * crop_camera[0, 1] / width,
                    (-2.0 * crop_camera[0, 2] + width) / width,
                    0.0,
                ],
                [
                    0.0,
                    2.0 * crop_camera[1, 1] / height,
                    (2.0 * crop_camera[1, 2] - height) / height,
                    0.0,
                ],
                [0.0, 0.0, q, qn],
                [0.0, 0.0, -1.0, 0.0],
            ],
            dtype=np.float64,
        )
        gl_camera_from_cv_camera = np.diag([1.0, -1.0, -1.0, 1.0])
        clip_matrix = projection @ gl_camera_from_cv_camera @ centered_pose
        vertices_homogeneous = np.column_stack(
            [self._vertices_numpy, np.ones(len(self._vertices_numpy), dtype=np.float64)]
        ).astype(np.float32)
        clip = (vertices_homogeneous @ clip_matrix.T).astype(np.float32)
        clip_tensor = torch.as_tensor(clip, dtype=torch.float32, device=self._device)[None]
        with torch.no_grad():
            raster, _ = self._dr.rasterize(
                self._context,
                clip_tensor,
                self._faces,
                resolution=(height, width),
            )
            tex_coord, _ = self._dr.interpolate(self._uv, raster, self._faces)
            color = self._dr.texture(self._texture, tex_coord, filter_mode="linear")
            mask = raster[0, ..., 3] > 0.0
        rgb = np.clip(
            np.rint(np.flip(color[0].detach().cpu().numpy(), axis=0) * 255.0),
            0,
            255,
        ).astype(np.uint8)
        visible = np.where(
            np.flip(mask.detach().cpu().numpy(), axis=0), 255, 0
        ).astype(np.uint8)
        return rgb, visible


__all__ = ["NvdiffrastTextureRenderer", "TEXTURE_RENDER_BACKENDS"]
