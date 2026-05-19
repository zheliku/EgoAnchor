"""FoundationPose 6DoF 位姿估计适配器。

本适配器属于 v3 algorithms 层，只封装 object-in-camera pose 的 register、track
和可视化能力，不理解网络、runtime 命令或 Unity world anchor。实现上通过项目内
FoundationPose 子工程动态加载依赖，不引用 v1/v2 代码。
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any, cast

import numpy as np
import trimesh


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

        self.debug_dir = str(debug_dir) if debug_dir else str(self.foundationpose_root / "debug" / "api_v3")
        """FoundationPose 内部 debug 输出目录。"""

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

        self.trimesh_add_pure_colored_texture = resolve_symbol("trimesh_add_pure_colored_texture")
        """给 trimesh 添加纯色纹理的工具函数。"""

        self.draw_posed_3d_box = resolve_symbol("draw_posed_3d_box")
        """绘制目标 3D 包围盒的工具函数。"""

        self.draw_xyz_axis = resolve_symbol("draw_xyz_axis")
        """绘制目标坐标轴的工具函数。"""

        self._load_mesh_and_create_estimator()
        logging.info("FoundationPose v3 estimator initialized: mesh=%s", self.mesh_path)

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

        loaded_mesh = trimesh.load(self.mesh_path)
        if isinstance(loaded_mesh, trimesh.Scene):
            loaded_mesh = loaded_mesh.dump(concatenate=True)
        self.mesh = cast(Any, loaded_mesh)
        """FoundationPose 使用的目标 mesh。"""

        self.mesh.apply_scale(self.apply_scale)
        if self.force_apply_color:
            self.mesh = self.trimesh_add_pure_colored_texture(self.mesh, color=np.array(self.apply_color), resolution=10)

        self.to_origin, extents = trimesh.bounds.oriented_bounds(self.mesh)
        """mesh oriented bounds 到原点的变换与 extents。"""

        self.bbox = np.stack([-extents / 2, extents / 2], axis=0).reshape(2, 3)
        """可视化绘制用的目标包围盒。"""

        scorer = self.ScorePredictor()
        refiner = self.PoseRefinePredictor()
        glctx = self.dr.RasterizeCudaContext()
        self.estimator = self.FoundationPose(
            model_pts=self.mesh.vertices,
            model_normals=self.mesh.vertex_normals,
            symmetry_tfs=self.symmetry_tfs,
            mesh=self.mesh,
            scorer=scorer,
            refiner=refiner,
            glctx=glctx,
            debug_dir=self.debug_dir,
            debug=self.debug,
        )
        """FoundationPose estimator 实例。"""

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
        pose = self.estimator.register(K=self.cam_k, rgb=rgb, depth=np.asarray(depth, dtype=np.float64), ob_mask=mask_u8, iteration=self.est_refine_iter)
        self._initialized = True
        return np.asarray(pose, dtype=np.float64).reshape(4, 4)

    def track(self, rgb: np.ndarray, depth: np.ndarray) -> np.ndarray:
        """后续帧跟踪，要求已经成功 register。"""

        if not self._initialized:
            raise RuntimeError("FoundationPose 尚未 register，不能直接 track。")
        pose = self.estimator.track_one(rgb=rgb, depth=np.asarray(depth, dtype=np.float64), K=self.cam_k, iteration=self.track_refine_iter)
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

    def reset(self) -> None:
        """重置 FoundationPose 时序状态，使下一帧重新 register。"""

        self._initialized = False
        if hasattr(self.estimator, "pose_last"):
            try:
                delattr(self.estimator, "pose_last")
            except Exception:
                self.estimator.pose_last = None
