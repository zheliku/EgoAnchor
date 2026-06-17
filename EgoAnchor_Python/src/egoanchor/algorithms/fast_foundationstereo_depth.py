"""Fast-FoundationStereo 深度估计适配器。

保留旧主线验证过的 FFS 调用策略：优先 TensorRT，失败时可按配置回退
PyTorch；但本文件不 import v1/v2 模块，只通过项目内 Fast-FoundationStereo
包级入口导入第三方实现，不在适配器里修改 `sys.path`。
"""

from __future__ import annotations

import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from egoanchor.utils import configure_thirdparty_logging, get_logger

LOGGER = get_logger(__name__, component="FFS")
"""FFS 适配器日志记录器。"""


def _ensure_three_channel(image: np.ndarray) -> np.ndarray:
    """把灰度或多通道图像统一成 HWC 三通道。"""

    if image.ndim == 2:
        return np.repeat(image[..., None], 3, axis=2)
    if image.ndim == 3:
        return image[..., :3]
    raise ValueError("FFS 输入图像维度不正确，应为 (H,W) 或 (H,W,C)。")


class _PyTorchStereoBackend:
    """FFS PyTorch 推理后端。"""

    def __init__(self, host: "FastFoundationStereoDepth") -> None:
        """保存宿主对象，复用宿主中的模型、配置和设备。"""

        self.host = host
        """拥有模型状态和公共配置的深度估计器。"""

    def prepare_optimize_build_volume(self) -> None:
        """当 triton 不可用时，把 cost volume 构建回退到 pytorch1。"""

        if self.host.optimize_build_volume != "triton":
            return
        try:
            import triton  # noqa: F401
        except Exception:
            LOGGER.warning("未检测到 triton，optimize_build_volume 回退为 pytorch1。")
            self.host.optimize_build_volume = "pytorch1"

    def load_model(self) -> None:
        """按需加载 FFS PyTorch 权重。"""

        if self.host.model is not None:
            self.host.runtime_backend = "pytorch"
            return
        if self.host.model_pth_path is None:
            raise FileNotFoundError("未找到可用 pth 文件，无法使用 PyTorch FoundationStereo。")

        self.host.model = self.host.torch.load(str(self.host.model_pth_path), map_location="cpu", weights_only=False)
        self.host.model.args.valid_iters = int(self.host.valid_iters)
        self.host.model.args.max_disp = int(self.host.max_disp)
        self.host.model = self.host.model.to(self.host.device).eval()
        self.host.runtime_backend = "pytorch"

    def predict_disparity(self, left_t: Any, right_t: Any) -> Any:
        """执行 PyTorch 前向并返回视差 tensor。"""

        self.load_model()
        padder = self.host.InputPadder(left_t.shape, divis_by=32, force_square=False)
        left_t, right_t = padder.pad(left_t, right_t)

        if self.host.device.type == "cuda":
            if hasattr(self.host.torch, "autocast"):
                autocast_ctx = self.host.torch.autocast("cuda", enabled=True, dtype=self.host.AMP_DTYPE)
            else:
                autocast_ctx = self.host.torch.cuda.amp.autocast(enabled=True, dtype=self.host.AMP_DTYPE)
        else:
            autocast_ctx = nullcontext()

        with self.host.torch.inference_mode():
            with autocast_ctx:
                disp = self.host.model.forward(
                    left_t,
                    right_t,
                    iters=int(self.host.valid_iters),
                    test_mode=True,
                    optimize_build_volume=str(self.host.optimize_build_volume),
                )
        if self.host.device.type == "cuda":
            self.host.torch.cuda.synchronize()
        return padder.unpad(disp.float())


class _TrtStereoBackend:
    """FFS TensorRT 推理后端。"""

    def __init__(self, host: "FastFoundationStereoDepth") -> None:
        """保存宿主对象，TRT runner 生命周期由宿主统一管理。"""

        self.host = host
        """拥有 TRT runner、engine 路径和回退策略的深度估计器。"""

    @staticmethod
    def _platform_tag() -> str:
        """返回当前平台 tag，用于匹配 engine 文件名。"""

        if sys.platform.startswith("win"):
            return "win"
        if sys.platform.startswith("linux"):
            return "linux"
        if sys.platform == "darwin":
            return "mac"
        return "unknown"

    @staticmethod
    def _artifact_tag(height: int, width: int, valid_iters: int, max_disp: int) -> str:
        """按输入尺寸和关键参数生成默认 artifact tag。"""

        return f"h{height}-w{width}-it{valid_iters}-md{max_disp}"

    @staticmethod
    def _first_existing_path(candidates: list[Path]) -> Path | None:
        """从候选路径中返回第一个存在的文件。"""

        for path in candidates:
            if path.is_file():
                return path
        return None

    def ensure_runner(self, infer_h: int, infer_w: int) -> None:
        """根据当前输入尺寸匹配并加载 TRT engine。"""

        if self.host.trt_runner is not None and self.host.trt_input_hw == (infer_h, infer_w):
            return
        if self.host.TrtRunner is None or self.host.OmegaConf is None:
            self.host._fallback_to_pytorch("TRT 依赖未准备完成")
            return
        if self.host.model_root_dir is None:
            self.host._fallback_to_pytorch("模型目录不存在")
            return

        tag = self.host.trt_tag.strip() or self._artifact_tag(infer_h, infer_w, self.host.valid_iters, self.host.max_disp)
        platform_tag = self.host.trt_platform_tag.strip() or self._platform_tag()

        def resolve_engine_path(explicit_path: str, runner_name: str) -> Path | None:
            """解析显式 engine 路径或按约定文件名自动查找。"""

            if explicit_path:
                return Path(explicit_path).expanduser().resolve()
            return self._first_existing_path(
                [
                    self.host.model_root_dir / f"{runner_name}-{tag}.{platform_tag}.{self.host.trt_precision}.engine",
                    self.host.model_root_dir / f"{runner_name}-{tag}.{platform_tag}.engine",
                    self.host.model_root_dir / f"{runner_name}-{tag}.engine",
                ]
            )

        feature_engine_path = resolve_engine_path(self.host.trt_feature_engine_path, "feature_runner")
        post_engine_path = resolve_engine_path(self.host.trt_post_engine_path, "post_runner")
        if feature_engine_path is None or post_engine_path is None:
            self.host._fallback_to_pytorch(f"未找到匹配 engine，tag={tag}, platform={platform_tag}, precision={self.host.trt_precision}")
            return

        try:
            cfg = self.host.OmegaConf.create(
                {
                    "max_disp": int(self.host.max_disp),
                    "valid_iters": int(self.host.valid_iters),
                    "normalize": True,
                    "cv_group": 8,
                }
            )
            self.host.trt_runner = self.host.TrtRunner(cfg, str(feature_engine_path), str(post_engine_path))
            self.host.trt_input_hw = (infer_h, infer_w)
            self.host.runtime_backend = "trt"
            LOGGER.info("FFS TRT runner ready: tag=%s size=%dx%d feature=%s post=%s", tag, infer_h, infer_w, feature_engine_path.name, post_engine_path.name)
        except Exception as exc:
            self.host._fallback_to_pytorch("创建 TRT runner 失败", exc)

    def predict_disparity(self, left_t: Any, right_t: Any) -> Any:
        """执行 TRT 前向；若 TRT 回退则改走 PyTorch。"""

        infer_h = int(left_t.shape[2])
        infer_w = int(left_t.shape[3])
        self.ensure_runner(infer_h, infer_w)
        if self.host.trt_runner is None:
            return self.host._pt_backend.predict_disparity(left_t, right_t)

        with self.host.torch.inference_mode():
            disp = self.host.trt_runner.forward(left_t, right_t)
        if self.host.device.type == "cuda":
            self.host.torch.cuda.synchronize()
        return disp.float()


class FastFoundationStereoDepth:
    """Fast-FoundationStereo 米制深度估计器。"""

    def __init__(
        self,
        model_dir: str | Path,
        device: str = "cuda",
        scale: float = 1.0,
        valid_iters: int = 4,
        max_disp: int = 192,
        optimize_build_volume: str = "triton",
        seed: int = -1,
        cudnn_benchmark: bool = True,
        use_trt: bool = True,
        trt_precision: str = "fp16",
        trt_strict: bool = False,
        trt_tag: str = "",
        trt_platform_tag: str = "",
        trt_feature_engine_path: str = "",
        trt_post_engine_path: str = "",
        enable_logging: bool = False,
        allow_tf32: bool = True,
        project_root: str | Path | None = None,
    ) -> None:
        """保存推理参数并初始化 PyTorch/TRT 后端。"""

        self.scale = float(scale)
        """FFS 输入缩放比例；小于 1 可提速但会降低深度精度。"""

        self.valid_iters = int(valid_iters)
        """FFS recurrent refine 迭代次数。"""

        self.max_disp = int(max_disp)
        """最大视差，影响输出范围和 TRT artifact 匹配。"""

        self.optimize_build_volume = str(optimize_build_volume)
        """PyTorch 路径 cost-volume 构建方式。"""

        self.seed = int(seed)
        """随机种子；小于 0 表示速度优先。"""

        self.cudnn_benchmark = bool(cudnn_benchmark)
        """固定输入尺寸时是否启用 cudnn.benchmark。"""

        self.use_trt = bool(use_trt)
        """是否优先使用 TensorRT engine。"""

        self.trt_precision = str(trt_precision).lower()
        """TensorRT engine 精度标签。"""

        self.trt_strict = bool(trt_strict)
        """TRT 失败时是否直接抛错；false 表示自动回退 PyTorch。"""

        self.trt_tag = str(trt_tag)
        """显式 TRT artifact tag；空值按尺寸自动生成。"""

        self.trt_platform_tag = str(trt_platform_tag)
        """显式 TRT 平台标签；空值自动识别。"""

        self.trt_feature_engine_path = str(trt_feature_engine_path)
        """显式 feature runner engine 路径。"""

        self.trt_post_engine_path = str(trt_post_engine_path)
        """显式 post runner engine 路径。"""

        self.enable_logging = bool(enable_logging)
        """是否允许 FFS 内部 stdout/stderr/logging 输出到 console。"""

        self.allow_tf32 = bool(allow_tf32)
        """是否允许 TF32 matmul/cudnn。诊断用：Blackwell(5090) 上 TF32 数值路径可能与 Ampere 差异较大，
        关掉可排查"低精度数值路径导致深度抖动"。默认 True（保持原行为，不影响已稳定的机器）。"""

        self.runtime_backend = "pytorch"
        """当前实际使用的后端名称，仅用于日志和诊断。"""

        self.trt_runner: Any = None
        """当前 TRT runner；没有加载时为 None。"""

        self.trt_input_hw: tuple[int, int] | None = None
        """当前 TRT runner 绑定的输入高宽。"""

        self.model: Any = None
        """PyTorch FFS 模型实例，按需加载。"""

        self.project_root = Path(project_root).resolve() if project_root is not None else Path(__file__).resolve().parents[3]
        """EgoAnchor_Python 项目根目录。"""

        self.ffs_root = self.project_root / "Fast-FoundationStereo"
        """Fast-FoundationStereo 子工程根目录。"""

        import torch

        self._configure_ffs_logging(self.enable_logging)
        InputPadder, amp_dtype, set_seed = self._load_ffs_symbols()

        self.torch = torch
        """运行时 torch 模块引用。"""

        self.InputPadder = InputPadder
        """FFS 输入 padding 工具类。"""

        self.AMP_DTYPE = amp_dtype
        """FFS 项目定义的 autocast dtype。"""

        self.set_seed = set_seed
        """FFS 项目随机种子设置函数。"""

        self.model_root_dir, self.model_pth_path = self._resolve_model_paths(model_dir)
        """FFS 权重目录与 PyTorch 权重文件。"""

        self._pt_backend = _PyTorchStereoBackend(self)
        """PyTorch 后端实例。"""

        self._trt_backend = _TrtStereoBackend(self)
        """TensorRT 后端实例。"""

        self.torch.autograd.set_grad_enabled(False)

        runtime_device = str(device)
        if runtime_device == "cuda" and not self.torch.cuda.is_available():
            LOGGER.warning("CUDA 不可用，FFS 自动回退 CPU。")
            runtime_device = "cpu"
        self.device = self.torch.device(runtime_device)
        """FFS 实际推理设备。"""

        if self.use_trt and self.device.type != "cuda":
            if self.trt_strict:
                raise RuntimeError("TRT 仅支持 CUDA，但当前 device 不是 cuda。")
            LOGGER.warning("当前 device=%s，TRT 不可用，自动回退 PyTorch。", self.device)
            self.use_trt = False

        if self.seed >= 0:
            self.set_seed(self.seed)
            LOGGER.info("FFS 使用确定性模式 seed=%d", self.seed)
        else:
            self.torch.backends.cudnn.deterministic = False
            if self.device.type == "cuda":
                self.torch.backends.cudnn.benchmark = bool(self.cudnn_benchmark)

        self.TrtRunner: Any = None
        """FFS TRT runner 类型；TRT 依赖缺失时为 None。"""

        self.OmegaConf: Any = None
        """OmegaConf 类型引用，用于构造 TRT runner 配置。"""

        if self.use_trt:
            try:
                self.TrtRunner, self.OmegaConf = self._load_trt_symbols()
            except Exception as exc:
                if self.trt_strict:
                    raise RuntimeError("TRT 依赖导入失败。") from exc
                LOGGER.warning("TRT 依赖导入失败，自动回退 PyTorch。错误: %s", exc)
                self.use_trt = False

        if not self.use_trt:
            self._pt_backend.prepare_optimize_build_volume()
            self._pt_backend.load_model()
        else:
            self.runtime_backend = "trt"
            LOGGER.debug("FFS TRT 模式启用，首次推理将按输入尺寸匹配 engine。")

        if hasattr(self.torch, "set_float32_matmul_precision"):
            self.torch.set_float32_matmul_precision("high" if self.allow_tf32 else "highest")
        if self.device.type == "cuda":
            self.torch.backends.cuda.matmul.allow_tf32 = self.allow_tf32
            self.torch.backends.cudnn.allow_tf32 = self.allow_tf32
            if not self.allow_tf32:
                LOGGER.info("FFS TF32 已关闭 (allow_tf32=false)：matmul/cudnn 走 fp32 路径，用于排查数值抖动。")

    @staticmethod
    def _configure_ffs_logging(enabled: bool) -> None:
        """配置 FFS 子工程 logger，默认不向 console 传播。"""

        configure_thirdparty_logging("ffs", enabled)

    @staticmethod
    def _load_ffs_symbols() -> tuple[Any, Any, Any]:
        """导入 FFS 公共工具符号，运行时路径由 Pixi 环境负责。"""

        from core.utils.utils import InputPadder
        import Utils as ffs_utils

        return InputPadder, ffs_utils.AMP_DTYPE, ffs_utils.set_seed

    @staticmethod
    def _load_trt_symbols() -> tuple[Any, Any]:
        """导入 FFS TensorRT runner 和 OmegaConf 类型。"""

        from core.foundation_stereo import TrtRunner
        from omegaconf import OmegaConf

        return TrtRunner, OmegaConf

    def _resolve_model_paths(self, model_dir: str | Path) -> tuple[Path, Path | None]:
        """解析 FFS 权重目录或 pth 文件路径。"""

        raw = Path(model_dir).expanduser()
        candidates = [raw.resolve()] if raw.is_absolute() else [(self.project_root / raw).resolve(), (self.ffs_root / "weights" / raw).resolve()]
        target = next((candidate for candidate in candidates if candidate.exists()), None)
        if target is None:
            raise FileNotFoundError(f"未找到 FFS 模型路径: {model_dir}，已检查: {', '.join(str(c) for c in candidates)}")
        if target.is_file():
            if target.suffix.lower() not in {".pth", ".pt"}:
                raise FileNotFoundError(f"文件存在但不是 pth/pt: {target}")
            return target.parent, target
        pth = target / "model_best_bp2_serialize.pth"
        if pth.is_file():
            return target, pth
        pth_candidates = sorted(target.glob("*.pth"))
        return target, (pth_candidates[0] if pth_candidates else None)

    def _fallback_to_pytorch(self, reason: str, exc: Exception | None = None) -> None:
        """TRT 失败时按 strict 策略回退或抛错。"""

        message = f"TRT 不可用: {reason}"
        if self.trt_strict:
            if exc is not None:
                raise RuntimeError(message) from exc
            raise RuntimeError(message)
        LOGGER.warning("%s，自动回退 PyTorch。%s", message, f"错误: {exc}" if exc is not None else "")
        self.use_trt = False
        self.trt_runner = None
        self.trt_input_hw = None
        self._pt_backend.prepare_optimize_build_volume()
        self._pt_backend.load_model()

    def _predict_disparity(self, left_t: Any, right_t: Any) -> Any:
        """根据当前配置选择 TRT 或 PyTorch 后端预测视差。"""

        if self.use_trt:
            return self._trt_backend.predict_disparity(left_t, right_t)
        return self._pt_backend.predict_disparity(left_t, right_t)

    def predict_depth(self, left_image: np.ndarray, right_image: np.ndarray, fx: float, baseline: float) -> np.ndarray:
        """预测米制深度图，输出 shape 与输入左图一致。"""

        left = _ensure_three_channel(left_image)
        right = _ensure_three_channel(right_image)

        if self.scale != 1.0:
            left = cv2.resize(left, dsize=None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_LINEAR)
            right = cv2.resize(right, dsize=(left.shape[1], left.shape[0]), interpolation=cv2.INTER_LINEAR)

        left_t = self.torch.as_tensor(left).to(self.device).float()[None].permute(0, 3, 1, 2)
        right_t = self.torch.as_tensor(right).to(self.device).float()[None].permute(0, 3, 1, 2)

        t_forward = time.perf_counter()
        disp = self._predict_disparity(left_t, right_t)
        forward_ms = (time.perf_counter() - t_forward) * 1000.0

        disp_np = disp.squeeze(0).squeeze(0).detach().cpu().numpy()
        disp_np = np.clip(disp_np, 1e-6, None)
        depth_meter = (float(fx) * self.scale * float(baseline)) / disp_np

        if self.scale != 1.0:
            depth_meter = cv2.resize(depth_meter, dsize=(left_image.shape[1], left_image.shape[0]), interpolation=cv2.INTER_LINEAR)
        depth_meter[~np.isfinite(depth_meter)] = 0.0
        LOGGER.debug("backend=%s forward_ms=%.1f", self.runtime_backend, forward_ms)
        return depth_meter.astype(np.float32)

