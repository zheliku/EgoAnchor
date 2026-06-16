"""perception pipeline 构建工厂。

本模块把 TOML 配置转换为 algorithms/perception 组件实例。runtime 只调用本工厂，
不直接关心 YOLOE、FFS、FoundationPose、Cutie 的构造细节。
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from egoanchor.reliability import PoseScoreConfig

from .quest_pose_pipeline import QuestPosePipeline


def _resolve_path(path_value: str | Path, python_root: Path) -> Path:
    """把配置中的相对路径解析到 EgoAnchor_Python 项目根目录。"""

    raw = Path(path_value).expanduser()
    return raw.resolve() if raw.is_absolute() else (python_root / raw).resolve()


def _cfg_get(cfg: SimpleNamespace, name: str, default: Any) -> Any:
    """从 SimpleNamespace 中读取字段，缺失时返回默认值。"""

    return getattr(cfg, name, default)


def _normalize_yolo_device(device: str) -> str | int | None:
    """把配置中的 YOLOE device 字段转为适配器可接受的值。"""

    value = str(device).strip().lower()
    if value in {"", "auto", "none"}:
        return None
    if value.isdigit():
        return int(value)
    return value


def normalize_segmenter_type(segmenter_cfg: SimpleNamespace) -> str:
    """规范化分割后端类型，并尽早拒绝未知值。"""

    value = str(_cfg_get(segmenter_cfg, "type", "yoloe26")).strip().lower()
    aliases = {
        "yolo": "yoloe26",
        "yoloe": "yoloe26",
        "yoloe26": "yoloe26",
        "sam3": "sam3",
    }
    normalized = aliases.get(value)
    if normalized is None:
        raise ValueError(f"未知分割后端 {value!r}，仅支持 yoloe26 或 sam3。")
    return normalized


def should_show_mask_snapshot(configured_snapshot: bool, tracking_window_enabled: bool) -> bool:
    """判断是否允许 register mask snapshot 弹窗。

    `debug.enable_tracking_window=false` 用于 Ubuntu headless/SSH 运行，此时即便
    `debug.show_mask_snapshot=true` 也不能调用 OpenCV GUI API。
    """

    return bool(configured_snapshot) and bool(tracking_window_enabled)


def _generate_cube_symmetry_tfs() -> np.ndarray:
    """生成立方体 24 个正交旋转对称变换。"""

    rotations: list[np.ndarray] = []
    axes = np.eye(3)
    for x_axis in axes.tolist() + (-axes).tolist():
        x = np.asarray(x_axis, dtype=np.float64)
        for y_axis in axes.tolist() + (-axes).tolist():
            y = np.asarray(y_axis, dtype=np.float64)
            if abs(float(np.dot(x, y))) > 1e-6:
                continue
            z = np.cross(x, y)
            r = np.stack([x, y, z], axis=1)
            if np.linalg.det(r) > 0.5:
                rotations.append(r)

    unique: list[np.ndarray] = []
    for r in rotations:
        if not any(np.allclose(r, item) for item in unique):
            unique.append(r)

    transforms = []
    for r in unique:
        tf = np.eye(4, dtype=np.float64)
        tf[:3, :3] = r
        transforms.append(tf)
    return np.stack(transforms, axis=0)


def _generate_axis_symmetry_tfs(axis: str, count: int) -> np.ndarray:
    """围绕指定轴生成离散旋转对称变换。"""

    axis = axis.lower()
    if axis not in {"x", "y", "z"}:
        raise ValueError(f"symmetry_axis 只支持 x/y/z，实际为 {axis!r}")
    count = max(int(count), 1)
    transforms: list[np.ndarray] = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        c = math.cos(angle)
        s = math.sin(angle)
        if axis == "x":
            r = np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)
        elif axis == "y":
            r = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)
        else:
            r = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)
        tf = np.eye(4, dtype=np.float64)
        tf[:3, :3] = r
        transforms.append(tf)
    return np.stack(transforms, axis=0)


def _build_symmetry_tfs(fp_cfg: SimpleNamespace) -> np.ndarray | None:
    """根据 FoundationPose 配置构造对称变换集合。"""

    mode = str(_cfg_get(fp_cfg, "symmetry_mode", "none")).lower()
    if mode in {"", "none", "identity"}:
        return None
    if mode == "cube":
        return _generate_cube_symmetry_tfs()
    if mode == "axis":
        return _generate_axis_symmetry_tfs(str(_cfg_get(fp_cfg, "symmetry_axis", "z")), int(_cfg_get(fp_cfg, "symmetry_count", 36)))
    raise ValueError(f"未知 symmetry_mode={mode!r}")


def build_quest_pose_pipeline(cfg: SimpleNamespace) -> QuestPosePipeline:
    """按 配置构建 QuestPosePipeline。

    这里会在 server 启动阶段预加载 YOLOE、FFS、FoundationPose 和可选 Cutie，
    后续即使 Quest 数据还没到，也不再把模型初始化成本推迟到第一帧。
    FoundationPose 先使用处理分辨率中心点构造一个临时 K；真实 QuestCameraInfo
    到达后，pipeline 会只更新 K 并 reset 时序状态，不重建 scorer/refiner 重模型。
    """

    from egoanchor.algorithms import CutieMaskTracker, FastFoundationStereoDepth, FoundationPoseObjectEstimator, Sam3Segmenter, Yoloe26Segmenter

    python_root = Path(cfg.paths.python_root)
    segmenter_cfg = cfg.module.segmenter
    yolo_cfg = cfg.module.yoloe
    sam3_cfg = cfg.module.sam3
    ffs_cfg = cfg.module.ffs
    fp_cfg = cfg.module.foundationpose
    cutie_cfg = cfg.module.cutie
    calib_cfg = cfg.pipeline.calibration
    depth_cfg = cfg.pipeline.depth
    reliability_cfg = getattr(cfg, "reliability", SimpleNamespace())
    render_quality_cfg = getattr(reliability_cfg, "render_quality", SimpleNamespace())
    pose_score_cfg = getattr(reliability_cfg, "pose_score", SimpleNamespace())
    debug_cfg = cfg.debug
    tracking_window_enabled = bool(_cfg_get(debug_cfg, "enable_tracking_window", True))

    segmenter_type = normalize_segmenter_type(segmenter_cfg)
    confidence_threshold = float(_cfg_get(segmenter_cfg, "confidence_threshold", _cfg_get(yolo_cfg, "conf", _cfg_get(sam3_cfg, "confidence_threshold", 0.1))))
    mask_threshold = float(_cfg_get(segmenter_cfg, "mask_threshold", _cfg_get(sam3_cfg, "mask_threshold", 0.5)))
    if segmenter_type == "yoloe26":
        segmenter = Yoloe26Segmenter(
            model_path=_resolve_path(str(yolo_cfg.model_path), python_root),
            init_prompt=str(segmenter_cfg.prompt),
            conf=confidence_threshold,
            imgsz=int(yolo_cfg.imgsz),
            max_det=int(segmenter_cfg.max_det),
            mask_threshold=mask_threshold,
            use_half=bool(yolo_cfg.use_half),
            device=_normalize_yolo_device(str(yolo_cfg.device)),
            mobileclip2_path=str(_resolve_path(str(yolo_cfg.mobileclip2_path), python_root)),
        )
    else:
        segmenter = Sam3Segmenter(
            repo_path=_resolve_path(str(sam3_cfg.repo_path), python_root),
            checkpoint_path=_resolve_path(str(sam3_cfg.checkpoint_path), python_root),
            init_prompt=str(segmenter_cfg.prompt),
            confidence_threshold=confidence_threshold,
            resolution=int(sam3_cfg.resolution),
            mask_threshold=mask_threshold,
            device=str(sam3_cfg.device),
            load_from_hf=bool(sam3_cfg.load_from_hf),
            disable_position_precompute=bool(_cfg_get(sam3_cfg, "disable_position_precompute", True)),
            enable_logging=bool(_cfg_get(sam3_cfg, "enable_logging", False)),
        )

    depth_estimator = FastFoundationStereoDepth(
        model_dir=_resolve_path(str(ffs_cfg.model_dir), python_root),
        device=str(ffs_cfg.device),
        scale=float(ffs_cfg.scale),
        valid_iters=int(ffs_cfg.valid_iters),
        max_disp=int(ffs_cfg.max_disp),
        optimize_build_volume=str(ffs_cfg.optimize_build_volume),
        seed=int(ffs_cfg.seed),
        cudnn_benchmark=bool(ffs_cfg.cudnn_benchmark),
        use_trt=bool(ffs_cfg.use_trt),
        trt_precision=str(ffs_cfg.trt_precision),
        trt_strict=bool(ffs_cfg.trt_strict),
        trt_tag=str(ffs_cfg.trt_tag),
        trt_platform_tag=str(ffs_cfg.trt_platform_tag),
        trt_feature_engine_path=str(ffs_cfg.trt_feature_engine_path),
        trt_post_engine_path=str(ffs_cfg.trt_post_engine_path),
        enable_logging=bool(_cfg_get(ffs_cfg, "enable_logging", False)),
        project_root=python_root,
    )

    symmetry_tfs = _build_symmetry_tfs(fp_cfg)
    mesh_path = _resolve_path(str(fp_cfg.mesh_path), python_root)
    debug_dir = _resolve_path(str(fp_cfg.debug_dir), python_root)

    process_width = int(calib_cfg.process_width)
    process_height = int(calib_cfg.process_height)
    bootstrap_k = np.array(
        [
            [float(max(process_width, 1)), 0.0, float(max(process_width, 1)) * 0.5],
            [0.0, float(max(process_width, 1)), float(max(process_height, 1)) * 0.5],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )

    def foundationpose_factory(cam_k: np.ndarray) -> FoundationPoseObjectEstimator:
        """按最新相机 K 创建 FoundationPose estimator。"""

        return FoundationPoseObjectEstimator(
            mesh_path=mesh_path,
            cam_k=cam_k,
            est_refine_iter=int(fp_cfg.est_refine_iter),
            track_refine_iter=int(fp_cfg.track_refine_iter),
            apply_scale=float(fp_cfg.apply_scale),
            force_apply_color=bool(fp_cfg.force_apply_color),
            apply_color=[int(v) for v in list(fp_cfg.apply_color)],
            symmetry_tfs=symmetry_tfs,
            debug=int(fp_cfg.debug),
            debug_dir=debug_dir,
            enable_logging=bool(_cfg_get(fp_cfg, "enable_logging", False)),
            project_root=python_root,
        )

    def cutie_factory() -> CutieMaskTracker:
        """创建 Cutie mask tracker。"""

        return CutieMaskTracker(
            seg_threshold=float(cutie_cfg.seg_threshold),
            erosion_size=int(cutie_cfg.erosion_size),
            project_root=python_root,
            enable_logging=bool(_cfg_get(cutie_cfg, "enable_logging", False)),
        )

    foundationpose_estimator = foundationpose_factory(bootstrap_k)
    cutie_tracker = cutie_factory() if bool(cutie_cfg.enabled) else None
    # Pose reliability 合成配置；缺省时保持几何核默认参数。
    pose_score_config = PoseScoreConfig(
        geo_floor=float(_cfg_get(pose_score_cfg, "geo_floor", 0.05)),
        reproj_weight=float(_cfg_get(pose_score_cfg, "reproj_weight", 0.5)),
        depth_weight=float(_cfg_get(pose_score_cfg, "depth_weight", 0.5)),
        mask_floor=float(_cfg_get(pose_score_cfg, "mask_floor", 0.5)),
        jump_floor=float(_cfg_get(pose_score_cfg, "jump_floor", 0.6)),
    )

    return QuestPosePipeline(
        segmenter=segmenter,
        segmenter_name=segmenter_type,
        depth_estimator=depth_estimator,
        foundationpose_estimator=foundationpose_estimator,
        cutie_tracker=cutie_tracker,
        process_width=process_width,
        process_height=process_height,
        assume_center_crop=bool(calib_cfg.assume_center_crop),
        network_calib_update=bool(calib_cfg.network_calib_update),
        min_depth_m=float(depth_cfg.min_depth),
        max_depth_m=float(depth_cfg.max_depth),
        register_min_depth_valid_in_mask=float(fp_cfg.register_min_depth_valid_in_mask),
        re_register_on_track_lost=bool(fp_cfg.re_register_on_track_lost),
        pose_jump_translation_m=float(fp_cfg.pose_jump_translation_m),
        pose_jump_rotation_deg=float(fp_cfg.pose_jump_rotation_deg),
        accept_track_jump_without_mask=bool(_cfg_get(fp_cfg, "accept_track_jump_without_mask", False)),
        max_consecutive_track_rejects=int(_cfg_get(fp_cfg, "max_consecutive_track_rejects", 3)),
        tracked_mask_lost_frames=int(_cfg_get(fp_cfg, "tracked_mask_lost_frames", 3)),
        cutie_enabled=bool(cutie_cfg.enabled),
        cutie_adjust_pose=bool(cutie_cfg.adjust_pose),
        log_stats_interval=int(debug_cfg.pipeline_stats_interval),
        show_mask_snapshot=should_show_mask_snapshot(bool(debug_cfg.show_mask_snapshot), tracking_window_enabled),
        mask_snapshot_window=str(debug_cfg.mask_snapshot_window),
        async_segmentation=bool(_cfg_get(sam3_cfg, "async_segmentation", segmenter_type == "sam3")) if segmenter_type == "sam3" else False,
        enable_render_quality=bool(_cfg_get(render_quality_cfg, "enabled", False)),
        render_quality_mode=str(_cfg_get(render_quality_cfg, "mode", "score_only")),
        render_quality_re_register_threshold=float(_cfg_get(render_quality_cfg, "re_register_threshold", 0.35)),
        render_quality_min_track_frames=int(_cfg_get(render_quality_cfg, "min_track_frames", 2)),
        render_quality_warmup_frames=int(_cfg_get(render_quality_cfg, "warmup_frames", 3)),
        render_quality_depth_distance_ratio=float(_cfg_get(render_quality_cfg, "depth_distance_ratio", 0.02)),
        render_quality_depth_min_inlier_thresh_m=float(_cfg_get(render_quality_cfg, "depth_min_inlier_thresh_m", 0.005)),
        render_quality_depth_min_coverage=float(_cfg_get(render_quality_cfg, "depth_min_coverage", 0.10)),
        render_quality_downscale=int(_cfg_get(render_quality_cfg, "downscale", 2)),
        render_quality_min_render_area_px=int(_cfg_get(render_quality_cfg, "min_render_area_px", 50)),
        render_quality_color_l_weight=float(_cfg_get(render_quality_cfg, "color_l_weight", 0.3)),
        pose_score_config=pose_score_config,
    )
