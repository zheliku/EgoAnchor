"""FoundationPose 6DoF 位姿估计适配器。

本适配器属于 algorithms 层，只封装 object-in-camera pose 的 register、track
和可视化能力，不理解网络、runtime 命令或 Unity world anchor。实现上通过项目内
FoundationPose 子工程动态加载依赖，不引用 v1/v2 代码。
"""

from __future__ import annotations

import importlib
import io
import ctypes
import logging
import os
import sys
import tempfile
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar, cast

import numpy as np
import trimesh
from PIL import Image

T = TypeVar("T")
"""保留被包装函数返回类型的泛型变量。"""


class FoundationPoseObjectEstimator:
    """FoundationPose object-in-camera 6D 位姿估计器。"""

    def __init__(
        self,
        mesh_path: str | Path,
        cam_k: np.ndarray,
        est_refine_iter: int = 5,
        track_refine_iter: int = 2,
        apply_scale: float = 1.0,
        force_apply_color: bool = False,
        apply_color: list[int] | None = None,
        symmetry_tfs: np.ndarray | None = None,
        debug: int = 0,
        debug_dir: str | Path | None = None,
        enable_logging: bool = False,
        project_root: str | Path | None = None,
    ) -> None:
        """加载 mesh 并创建 FoundationPose estimator。"""

        self.project_root = Path(project_root).resolve() if project_root is not None else Path(__file__).resolve().parents[3]
        """EgoAnchor_Python 项目根目录。"""

        self.foundationpose_root = self.project_root / "FoundationPose"
        """FoundationPose 子工程根目录。"""

        raw_mesh_path = Path(mesh_path).expanduser()
        self.mesh_path = raw_mesh_path.resolve() if raw_mesh_path.is_absolute() else (self.project_root / raw_mesh_path).resolve()
        """目标物体 mesh 绝对路径。"""

        self.est_refine_iter = int(est_refine_iter)
        """register 阶段 refine 迭代次数。"""

        self.track_refine_iter = int(track_refine_iter)
        """track 阶段 refine 迭代次数。"""

        self.apply_scale = float(apply_scale)
        """加载 mesh 后应用的尺度缩放。"""

        self.force_apply_color = bool(force_apply_color)
        """是否给 mesh 强制写入纯色纹理。"""

        self.apply_color = apply_color or [0, 159, 237]
        """强制纹理颜色，RGB 顺序。"""

        self.symmetry_tfs = symmetry_tfs
        """目标对称变换集合；无对称约束时为 None。"""

        self.debug = int(debug)
        """FoundationPose 内部 debug 等级。"""

        self.debug_dir = str(debug_dir) if debug_dir else str(self.foundationpose_root / "debug" / "api")
        """FoundationPose 内部 debug 输出目录。"""

        self.enable_logging = bool(enable_logging)
        """是否允许 FoundationPose 内部 stdout/stderr/logging 输出到 console。"""

        self.cam_k = np.asarray(cam_k, dtype=np.float64).reshape(3, 3)
        """算法处理分辨率下的左目相机内参矩阵。"""

        self._initialized = False
        """FoundationPose 是否已经成功 register。"""

        if not self.mesh_path.is_file():
            raise FileNotFoundError(f"FoundationPose mesh 不存在: {self.mesh_path}")
        if str(self.project_root) not in sys.path:
            sys.path.append(str(self.project_root))
        if str(self.foundationpose_root) not in sys.path:
            sys.path.append(str(self.foundationpose_root))

        est_mod, utils_mod = self.load_modules_with_logging_control(self._load_foundationpose_modules, enable_logging=self.enable_logging)

        def resolve_symbol(name: str) -> Any:
            """从 FoundationPose estimater 或 Utils 中解析运行符号。"""

            if hasattr(est_mod, name):
                return getattr(est_mod, name)
            if hasattr(utils_mod, name):
                return getattr(utils_mod, name)
            raise RuntimeError(f"FoundationPose 符号缺失: {name}")

        self.ScorePredictor = resolve_symbol("ScorePredictor")
        """FoundationPose score predictor 类型。"""

        self.PoseRefinePredictor = resolve_symbol("PoseRefinePredictor")
        """FoundationPose pose refine predictor 类型。"""

        self.dr = resolve_symbol("dr")
        """FoundationPose 内部 nvdiffrast 模块引用。"""

        self.FoundationPose = resolve_symbol("FoundationPose")
        """FoundationPose estimator 类型。"""

        self.draw_posed_3d_box = resolve_symbol("draw_posed_3d_box")
        """绘制目标 3D 包围盒的工具函数。"""

        self.draw_xyz_axis = resolve_symbol("draw_xyz_axis")
        """绘制目标坐标轴的工具函数。"""

        self.call_with_logging_control(self._load_mesh_and_create_estimator, enable_logging=self.enable_logging)
        if self.enable_logging:
            logging.info("FoundationPose estimator initialized: mesh=%s", self.mesh_path)

    @staticmethod
    def call_with_logging_control(func: Callable[..., T], *args: Any, enable_logging: bool = False, **kwargs: Any) -> T:
        """按配置调用第三方函数，并可临时抑制 stdout/stderr/logging。

        FoundationPose 内部有若干 print/logging/进度输出。默认把它们收进内存缓冲区，避免高频
        register/track 时盖住 EgoAnchor 自己的系统日志；关闭抑制后保留原始输出，便于
        专门排查 FoundationPose 子工程内部问题。部分 CUDA/渲染依赖会绕过 Python
        `print` 直接写进进程 stdout/stderr 文件描述符，因此这里同时重定向 Python
        stream 和 fd=1/2。
        """

        if enable_logging:
            return func(*args, **kwargs)
        previous_disable_level = logging.root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            with FoundationPoseObjectEstimator._suppress_process_output():
                return func(*args, **kwargs)
        finally:
            logging.disable(previous_disable_level)

    @staticmethod
    @contextmanager
    def _suppress_process_output() -> Iterator[None]:
        """临时吞掉 Python stream 和底层 fd stdout/stderr 输出。"""

        FoundationPoseObjectEstimator._flush_c_stdio()
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        with tempfile.TemporaryFile() as sink_stdout, tempfile.TemporaryFile() as sink_stderr:
            try:
                os.dup2(sink_stdout.fileno(), 1)
                os.dup2(sink_stderr.fileno(), 2)
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    yield
            finally:
                FoundationPoseObjectEstimator._flush_c_stdio()
                os.dup2(saved_stdout_fd, 1)
                os.dup2(saved_stderr_fd, 2)
                os.close(saved_stdout_fd)
                os.close(saved_stderr_fd)

    @staticmethod
    def _flush_c_stdio() -> None:
        """尽量 flush 当前平台 C runtime 的 stdio，避免恢复 fd 后吐出旧缓冲。"""

        candidates: tuple[str | None, ...]
        if os.name == "nt":
            candidates = ("ucrtbase", "msvcrt")
        elif sys.platform == "darwin":
            candidates = (None, "libSystem.B.dylib")
        else:
            candidates = (None, "libc.so.6")

        for name in candidates:
            try:
                libc = ctypes.CDLL(name) if name is not None else ctypes.CDLL(None)
                fflush = libc.fflush
                fflush.argtypes = [ctypes.c_void_p]
                fflush.restype = ctypes.c_int
                fflush(None)
            except Exception:
                continue

    @staticmethod
    def load_modules_with_logging_control(
        loader: Callable[[], tuple[Any, Any]],
        *,
        enable_logging: bool = False,
    ) -> tuple[Any, Any]:
        """按配置加载 FoundationPose 模块，并抑制 import 阶段的第三方输出。"""

        return FoundationPoseObjectEstimator.call_with_logging_control(loader, enable_logging=enable_logging)

    @staticmethod
    def _load_foundationpose_modules() -> tuple[Any, Any]:
        """导入 FoundationPose estimator 与 Utils，并兼容原工程的顶层 Utils import。"""

        try:
            utils_mod = importlib.import_module("FoundationPose.Utils")
        except ModuleNotFoundError:
            utils_mod = importlib.import_module("Utils")

        old_utils_module = sys.modules.get("Utils")
        sys.modules["Utils"] = utils_mod
        try:
            try:
                est_mod = importlib.import_module("FoundationPose.estimater")
            except ModuleNotFoundError:
                est_mod = importlib.import_module("estimater")
        finally:
            if old_utils_module is None:
                sys.modules.pop("Utils", None)
            else:
                sys.modules["Utils"] = old_utils_module
        return est_mod, utils_mod

    def update_camera_matrix(self, cam_k: np.ndarray) -> None:
        """更新运行时相机内参矩阵，不重建 FoundationPose 重模型。

        FoundationPose 的 `register/track_one/visualize` 都在调用时显式传入 K，
        因此收到 QuestCameraInfo 后只需要更新本适配器保存的 `cam_k`。这样可以
        先在 server 启动阶段加载 scorer/refiner/mesh，等真实标定到达后快速开始
        register，避免第一帧数据到达时再做耗时初始化。
        """

        self.cam_k = np.asarray(cam_k, dtype=np.float64).reshape(3, 3)

    def _load_mesh_and_create_estimator(self) -> None:
        """加载 mesh、计算可视化 bbox，并创建 FoundationPose estimator。"""

        loaded_mesh = trimesh.load(self.mesh_path, force="scene", process=False)
        if isinstance(loaded_mesh, trimesh.Scene):
            loaded_mesh = self._scene_to_transformed_mesh(loaded_mesh)
        self.mesh = cast(Any, loaded_mesh)
        """FoundationPose 使用的目标 mesh。"""

        self.mesh.apply_scale(self.apply_scale)
        self._ensure_renderable_visual()

        self.to_origin, extents = self._compute_axis_aligned_bounds_to_origin(self.mesh)
        """mesh 轴对齐 bounds 到原点的变换与 extents。"""

        self.bbox = np.stack([-extents / 2, extents / 2], axis=0).reshape(2, 3)
        """可视化绘制用的目标包围盒。"""

        model_normals = self._get_safe_vertex_normals(self.mesh)
        """传给 FoundationPose 的顶点法线；优先使用 mesh 自带法线，失败时手动估计。"""

        scorer = self.ScorePredictor()
        refiner = self.PoseRefinePredictor()
        glctx = self.dr.RasterizeCudaContext()
        self.estimator = self.FoundationPose(
            model_pts=self.mesh.vertices,
            model_normals=model_normals,
            symmetry_tfs=self.symmetry_tfs,
            mesh=self.mesh,
            scorer=scorer,
            refiner=refiner,
            glctx=glctx,
            debug_dir=self.debug_dir,
            debug=self.debug,
        )
        """FoundationPose estimator 实例。"""

    def _ensure_renderable_visual(self) -> None:
        """确保 mesh visual 可被 FoundationPose rasterizer 使用。

        一些 GLB 会被 trimesh 解析为 `PBRMaterial.baseColorTexture`，而原版
        FoundationPose 的 `make_mesh_tensors()` 只访问 `material.image`。因此这里会
        先把 PBR base color texture 规范化为 FoundationPose 可读的
        `SimpleMaterial.image`；只有在纹理确实缺失或显式强制时才使用纯色纹理。
        """

        visual = getattr(self.mesh, "visual", None)
        material = getattr(visual, "material", None)
        image = self._extract_material_image(material)
        should_apply_color = self.force_apply_color or image is None or not hasattr(image, "convert")
        if not should_apply_color:
            self._set_texture_visual(image)
            logging.info("FoundationPose mesh 使用模型自带纹理: mesh=%s image_size=%s", self.mesh_path, getattr(image, "size", None))
            return

        color = np.asarray(self.apply_color, dtype=np.uint8).reshape(1, 1, 3)
        texture = np.tile(color, (10, 10, 1))
        self._set_texture_visual(Image.fromarray(texture))
        reason = "force_apply_color=true" if self.force_apply_color else "模型纹理不可被 FoundationPose 读取"
        logging.info("FoundationPose mesh 使用纯色纹理 fallback: mesh=%s reason=%s", self.mesh_path, reason)

    @staticmethod
    def _extract_material_image(material: Any) -> Any | None:
        """从 trimesh material 中提取 FoundationPose 可用的 PIL image。"""

        if material is None:
            return None
        image = getattr(material, "image", None)
        if image is not None and hasattr(image, "convert"):
            return image
        base_color_texture = getattr(material, "baseColorTexture", None)
        if base_color_texture is not None and hasattr(base_color_texture, "convert"):
            return base_color_texture
        return None

    def _set_texture_visual(self, image: Any) -> None:
        """把 mesh visual 改写成 FoundationPose `make_mesh_tensors()` 可读取的格式。"""

        visual = getattr(self.mesh, "visual", None)
        vertex_count = int(len(self.mesh.vertices))
        uv = getattr(visual, "uv", None)
        if uv is None or len(uv) != vertex_count:
            uv = np.zeros((vertex_count, 2), dtype=np.float32)
        material = trimesh.visual.texture.SimpleMaterial(image=image)
        self.mesh.visual = trimesh.visual.texture.TextureVisuals(uv=uv, image=image, material=material)

    @staticmethod
    def _compute_axis_aligned_bounds_to_origin(mesh: Any) -> tuple[np.ndarray, np.ndarray]:
        """用轴对齐 bounds 计算 `to_origin`，避免大 GLB 触发 oriented_bounds 崩溃。"""

        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        min_xyz = np.min(vertices, axis=0)
        max_xyz = np.max(vertices, axis=0)
        center = (min_xyz + max_xyz) * 0.5
        extents = np.maximum(max_xyz - min_xyz, 1e-9)
        to_origin = np.eye(4, dtype=np.float64)
        to_origin[:3, 3] = -center
        return to_origin, extents

    @staticmethod
    def _estimate_vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
        """不依赖 trimesh 懒属性，手动按相邻三角面平均估计顶点法线。"""

        triangles = vertices[faces]
        face_normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        face_lengths = np.linalg.norm(face_normals, axis=1)
        valid_faces = face_lengths > 1e-12
        face_normals[valid_faces] /= face_lengths[valid_faces, None]
        face_normals[~valid_faces] = 0.0

        vertex_normals = np.zeros_like(vertices, dtype=np.float64)
        for corner in range(3):
            np.add.at(vertex_normals, faces[:, corner], face_normals)
        vertex_lengths = np.linalg.norm(vertex_normals, axis=1)
        valid_vertices = vertex_lengths > 1e-12
        vertex_normals[valid_vertices] /= vertex_lengths[valid_vertices, None]
        vertex_normals[~valid_vertices] = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        return vertex_normals

    def _get_safe_vertex_normals(self, mesh: Any) -> np.ndarray:
        """获取顶点法线；若 trimesh 懒计算触发底层 DLL 崩溃风险，则使用手动估计。"""

        try:
            normals = np.asarray(mesh.vertex_normals, dtype=np.float64)
            if normals.shape == np.asarray(mesh.vertices).shape and np.all(np.isfinite(normals)):
                return normals
        except Exception as exc:
            logging.warning("读取 mesh.vertex_normals 失败，改用手动法线估计: %s", exc)
        return self._estimate_vertex_normals(np.asarray(mesh.vertices, dtype=np.float64), np.asarray(mesh.faces, dtype=np.int64))

    @staticmethod
    def _scene_to_transformed_mesh(scene: trimesh.Scene) -> Any:
        """把 GLB scene 转为已应用 node transform 的单 mesh。

        有些 GLB 会把真实米单位尺寸写在 scene graph transform 里，而 geometry 顶点仍是
        建模软件内部单位。直接拼接 scene.geometry 会丢掉缩放/旋转/平移，导致
        FoundationPose 把小物体当成巨大物体注册。
        """

        if not scene.geometry:
            raise ValueError("FoundationPose mesh scene 不包含可用几何体。")

        try:
            return scene.to_geometry()
        except AttributeError:
            return scene.dump(concatenate=True)

    @staticmethod
    def _get_pose_xy_from_image_point(ob_in_cam: np.ndarray, cam_k: np.ndarray, x: float, y: float) -> tuple[float, float]:
        """保持 z 不变，由 2D 像素点反推相机坐标系 tx/ty。"""

        t = ob_in_cam[:3, 3]
        fx = float(cam_k[0, 0])
        fy = float(cam_k[1, 1])
        cx = float(cam_k[0, 2])
        cy = float(cam_k[1, 2])
        tz = float(t[2])
        return (float(x) - cx) * tz / fx, (float(y) - cy) * tz / fy

    def adjust_pose_to_image_point(self, x: float, y: float) -> None:
        """用 2D tracker 中心点轻量修正 FoundationPose 上一帧 x/y 平移。"""

        if not hasattr(self.estimator, "pose_last"):
            return
        pose_last = self.estimator.pose_last
        if hasattr(pose_last, "detach"):
            pose_np = pose_last.detach().cpu().numpy()
            is_tensor = True
            device = pose_last.device
            dtype = pose_last.dtype
        else:
            pose_np = np.asarray(pose_last)
            is_tensor = False
            device = None
            dtype = None

        mat = pose_np[0] if pose_np.ndim == 3 else pose_np
        tx, ty = self._get_pose_xy_from_image_point(mat, self.cam_k, x, y)
        mat_new = mat.copy()
        mat_new[0, 3] = tx
        mat_new[1, 3] = ty

        if is_tensor:
            import torch

            self.estimator.pose_last = torch.from_numpy(mat_new).to(device=device, dtype=dtype).unsqueeze(0)
        else:
            self.estimator.pose_last = mat_new

    def register(self, rgb: np.ndarray, depth: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """初始注册：RGB-D + mask -> object-in-camera pose。"""

        mask_u8 = (mask > 0).astype(np.uint8) * 255
        pose = self.call_with_logging_control(
            self.estimator.register,
            K=self.cam_k,
            rgb=rgb,
            depth=np.asarray(depth, dtype=np.float64),
            ob_mask=mask_u8,
            iteration=self.est_refine_iter,
            enable_logging=self.enable_logging,
        )
        self._initialized = True
        return np.asarray(pose, dtype=np.float64).reshape(4, 4)

    def track(self, rgb: np.ndarray, depth: np.ndarray) -> np.ndarray:
        """后续帧跟踪，要求已经成功 register。"""

        if not self._initialized:
            raise RuntimeError("FoundationPose 尚未 register，不能直接 track。")
        pose = self.call_with_logging_control(
            self.estimator.track_one,
            rgb=rgb,
            depth=np.asarray(depth, dtype=np.float64),
            K=self.cam_k,
            iteration=self.track_refine_iter,
            enable_logging=self.enable_logging,
        )
        return np.asarray(pose, dtype=np.float64).reshape(4, 4)

    def visualize_pose(self, rgb: np.ndarray, pose: np.ndarray, axis_scale: float = 0.1, thickness: int = 3) -> np.ndarray:
        """在 RGB 图上绘制目标 3D 包围盒和坐标轴。"""

        center_pose = np.asarray(pose, dtype=np.float64).reshape(4, 4) @ np.linalg.inv(self.to_origin)
        vis = self.draw_posed_3d_box(self.cam_k, img=rgb, ob_in_cam=center_pose, bbox=self.bbox)
        vis = self.draw_xyz_axis(
            vis,
            ob_in_cam=center_pose,
            scale=float(axis_scale),
            K=self.cam_k,
            thickness=int(thickness),
            transparency=0,
            is_input_rgb=True,
        )
        return vis

    def render_depth_mask(
        self,
        pose_cv_camera: np.ndarray,
        output_size: tuple[int, int],
        cam_k: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """按给定 OpenCV camera-space pose 渲染 mesh depth 与二值 mask。

        这是 reliability 层唯一使用的渲染 facade。内部复用 FoundationPose 已创建的
        `glctx` 和 `mesh_tensors`，并把第三方 CUDA/Tensor 输出立即转换为 CPU numpy，
        避免上层模块持有 GPU tensor 或访问 estimator 内部结构。
        """

        def render_once() -> tuple[np.ndarray, np.ndarray]:
            """执行一次 nvdiffrast 渲染并返回 CPU numpy 结果。"""

            import torch

            utils_mod = importlib.import_module("FoundationPose.Utils") if "FoundationPose.Utils" in sys.modules else importlib.import_module("Utils")
            render_fn = getattr(utils_mod, "nvdiffrast_render")
            out_h, out_w = (int(output_size[0]), int(output_size[1]))
            k = np.asarray(cam_k if cam_k is not None else self.cam_k, dtype=np.float64).reshape(3, 3)
            pose = np.asarray(pose_cv_camera, dtype=np.float32).reshape(1, 4, 4)
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            pose_tensor = torch.as_tensor(pose, dtype=torch.float32, device=device)
            with torch.no_grad():
                _color, depth, _normal = render_fn(
                    k,
                    out_h,
                    out_w,
                    pose_tensor,
                    self.estimator.glctx,
                    self.estimator.mesh_tensors,
                    output_size=(out_h, out_w),
                )
            if hasattr(depth, "detach"):
                depth_np = depth.detach().cpu().numpy()
            else:
                depth_np = np.asarray(depth)
            depth_np = np.asarray(depth_np, dtype=np.float32)
            if depth_np.ndim == 3:
                depth_np = depth_np[0]
            if depth_np.ndim == 4:
                depth_np = depth_np[0, ..., 0]
            render_mask = depth_np > 0.0
            return depth_np, render_mask

        return self.call_with_logging_control(render_once, enable_logging=self.enable_logging)

    def reset(self) -> None:
        """重置 FoundationPose 时序状态，使下一帧重新 register。"""

        self._initialized = False
        if hasattr(self.estimator, "pose_last"):
            try:
                delattr(self.estimator, "pose_last")
            except Exception:
                self.estimator.pose_last = None

