"""Fast-FoundationStereo 深度估计 v2 适配器。

本实现按 v2 algorithms 层重新落地，不依赖旧 `src/modules/fast_foundationstereo.py`。
它保留旧主线中验证过的关键策略：
- 支持 PyTorch / TensorRT 两条路径；
- TRT engine 按输入分辨率、valid_iters、max_disp 自动匹配；
- `trt_strict=false` 时 TRT 失败自动回退 PyTorch，保证 debug demo 尽量可运行。
"""

from __future__ import annotations

import importlib
import logging
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _ensure_three_channel(image: np.ndarray) -> np.ndarray:
    """FoundationStereo 输入需要 HWC 三通道；灰度图会复制成三通道。"""

    if image.ndim == 2:
        return np.repeat(image[..., None], 3, axis=2)
    return image[..., :3]


class _PyTorchStereoBackend:
    """PyTorch 推理后端。"""

    def __init__(self, host: "FastFoundationStereoDepth") -> None:
        """保存宿主对象引用，后端共享模型、设备和配置。"""

        self.host = host

    def prepare_optimize_build_volume(self) -> None:
        """Triton 不可用时把 cost volume 构建回退到 pytorch1。"""

        if self.host.optimize_build_volume != "triton":
            return
        try:
            importlib.import_module("triton")
        except Exception:
            logging.warning("未检测到 triton，optimize_build_volume 回退为 pytorch1。")
            self.host.optimize_build_volume = "pytorch1"

    def load_model(self) -> None:
        """按需加载 PyTorch 权重。"""

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
    """TensorRT 推理后端。"""

    def __init__(self, host: "FastFoundationStereoDepth") -> None:
        """保存宿主对象引用，TRT runner 生命周期由宿主统一管理。"""

        self.host = host

    @staticmethod
    def _platform_tag() -> str:
        if sys.platform.startswith("win"):
            return "win"
        if sys.platform.startswith("linux"):
            return "linux"
        if sys.platform == "darwin":
            return "mac"
        return "unknown"

    @staticmethod
    def _artifact_tag(height: int, width: int, valid_iters: int, max_disp: int) -> str:
        return f"h{height}-w{width}-it{valid_iters}-md{max_disp}"

    @staticmethod
    def _first_existing_path(candidates: list[Path]) -> Path | None:
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
            logging.info("TRT runner ready: tag=%s size=%dx%d feature=%s post=%s", tag, infer_h, infer_w, feature_engine_path.name, post_engine_path.name)
        except Exception as exc:
            self.host._fallback_to_pytorch("创建 TRT runner 失败", exc)

    def predict_disparity(self, left_t: Any, right_t: Any) -> Any:
        """执行 TRT 前向；若 ensure_runner 触发回退，则改走 PyTorch。"""

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
        project_root: str | Path | None = None,
    ) -> None:
        # 推理参数：这些值会同时影响 PyTorch 前向和 TRT engine 匹配。
        self.scale = float(scale)
        self.valid_iters = int(valid_iters)
        self.max_disp = int(max_disp)
        self.optimize_build_volume = str(optimize_build_volume)
        self.seed = int(seed)
        self.cudnn_benchmark = bool(cudnn_benchmark)
        self.use_trt = bool(use_trt)
        self.trt_precision = str(trt_precision).lower()
        self.trt_strict = bool(trt_strict)
        self.trt_tag = str(trt_tag)
        self.trt_platform_tag = str(trt_platform_tag)
        self.trt_feature_engine_path = str(trt_feature_engine_path)
        self.trt_post_engine_path = str(trt_post_engine_path)
        # runtime_backend 仅用于日志/诊断；真正分支由 use_trt 和 trt_runner 决定。
        self.runtime_backend = "pytorch"
        self.trt_runner: Any = None
        self.trt_input_hw: tuple[int, int] | None = None
        self.model: Any = None

        # v2 不 import 旧 src/modules，直接定位 Fast-FoundationStereo 工程目录并动态导入。
        self.project_root = Path(project_root).resolve() if project_root is not None else Path(__file__).resolve().parents[3]
        self.ffs_root = self.project_root / "Fast-FoundationStereo"
        if str(self.ffs_root) not in sys.path:
            sys.path.append(str(self.ffs_root))

        core_utils = importlib.import_module("core.utils.utils")
        utils_mod = importlib.import_module("Utils")
        import torch

        self.torch = torch
        self.InputPadder = core_utils.InputPadder
        self.AMP_DTYPE = utils_mod.AMP_DTYPE
        self.set_logging_format = utils_mod.set_logging_format
        self.set_seed = utils_mod.set_seed
        self.model_root_dir, self.model_pth_path = self._resolve_model_paths(model_dir)

        self._pt_backend = _PyTorchStereoBackend(self)
        self._trt_backend = _TrtStereoBackend(self)
        self.set_logging_format(level=logging.INFO)
        self.torch.autograd.set_grad_enabled(False)

        # 用户配置 cuda 但本机不可用时，优先回退 CPU，避免 demo 启动阶段直接崩溃。
        runtime_device = str(device)
        if runtime_device == "cuda" and not self.torch.cuda.is_available():
            logging.warning("CUDA 不可用，FoundationStereo 自动回退 CPU。")
            runtime_device = "cpu"
        self.device = self.torch.device(runtime_device)

        if self.use_trt and self.device.type != "cuda":
            if self.trt_strict:
                raise RuntimeError("TRT 仅支持 CUDA，但当前 device 不是 cuda。")
            logging.warning("当前 device=%s，TRT 不可用，自动回退 PyTorch。", self.device)
            self.use_trt = False

        if self.seed >= 0:
            self.set_seed(self.seed)
            logging.info("FoundationStereo 使用确定性模式 seed=%d", self.seed)
        else:
            self.torch.backends.cudnn.deterministic = False
            if self.device.type == "cuda":
                self.torch.backends.cudnn.benchmark = bool(self.cudnn_benchmark)

        self.TrtRunner: Any = None
        self.OmegaConf: Any = None
        if self.use_trt:
            # TRT 依赖按需加载；失败时根据 trt_strict 决定报错或回退 PyTorch。
            try:
                core_mod = importlib.import_module("core.foundation_stereo")
                omegaconf_mod = importlib.import_module("omegaconf")
                self.TrtRunner = core_mod.TrtRunner
                self.OmegaConf = omegaconf_mod.OmegaConf
            except Exception as exc:
                if self.trt_strict:
                    raise RuntimeError("TRT 依赖导入失败。") from exc
                logging.warning("TRT 依赖导入失败，自动回退 PyTorch。错误: %s", exc)
                self.use_trt = False

        if not self.use_trt:
            self._pt_backend.prepare_optimize_build_volume()
            self._pt_backend.load_model()
        else:
            self.runtime_backend = "trt"
            logging.info("FoundationStereo TRT 模式启用，首次推理将按输入尺寸匹配 engine。")

        if hasattr(self.torch, "set_float32_matmul_precision"):
            self.torch.set_float32_matmul_precision("high")
        if self.device.type == "cuda":
            self.torch.backends.cuda.matmul.allow_tf32 = True
            self.torch.backends.cudnn.allow_tf32 = True

    def _resolve_model_paths(self, model_dir: str | Path) -> tuple[Path, Path | None]:
        """解析 pth 文件或权重目录。"""

        raw = Path(model_dir).expanduser()
        candidates = [raw.resolve()] if raw.is_absolute() else [(self.project_root / raw).resolve(), (self.ffs_root / "weights" / raw).resolve()]
        target = next((cand for cand in candidates if cand.exists()), None)
        if target is None:
            raise FileNotFoundError(f"未找到 FoundationStereo 模型路径: {model_dir}，已检查: {', '.join(str(c) for c in candidates)}")
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
        logging.warning("%s，自动回退 PyTorch。%s", message, f"错误: {exc}" if exc is not None else "")
        self.use_trt = False
        self.trt_runner = None
        self.trt_input_hw = None
        self._pt_backend.prepare_optimize_build_volume()
        self._pt_backend.load_model()

    def _predict_disparity(self, left_t: Any, right_t: Any) -> Any:
        """按当前后端状态预测视差。"""

        if self.use_trt:
            return self._trt_backend.predict_disparity(left_t, right_t)
        return self._pt_backend.predict_disparity(left_t, right_t)

    def predict_depth(
        self,
        left_image: np.ndarray,
        right_image: np.ndarray,
        fx: float,
        baseline: float,
        return_timing: bool = False,
    ) -> np.ndarray | tuple[np.ndarray, dict[str, float]]:
        """预测米制深度图。"""

        t0 = time.perf_counter()
        left = _ensure_three_channel(left_image)
        right = _ensure_three_channel(right_image)

        if self.scale != 1.0:
            left = cv2.resize(left, dsize=None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_LINEAR)
            right = cv2.resize(right, dsize=(left.shape[1], left.shape[0]), interpolation=cv2.INTER_LINEAR)

        left_t = self.torch.as_tensor(left).to(self.device).float()[None].permute(0, 3, 1, 2)
        right_t = self.torch.as_tensor(right).to(self.device).float()[None].permute(0, 3, 1, 2)
        t1 = time.perf_counter()

        t_forward_begin = time.perf_counter()
        disp = self._predict_disparity(left_t, right_t)
        t2 = time.perf_counter()

        disp_np = disp.squeeze(0).squeeze(0).detach().cpu().numpy()
        disp_np = np.clip(disp_np, 1e-6, None)
        depth_meter = (float(fx) * self.scale * float(baseline)) / disp_np

        if self.scale != 1.0:
            depth_meter = cv2.resize(depth_meter, dsize=(left_image.shape[1], left_image.shape[0]), interpolation=cv2.INTER_LINEAR)
        depth_meter[~np.isfinite(depth_meter)] = 0.0
        t3 = time.perf_counter()

        depth_meter = depth_meter.astype(np.float32)
        if not return_timing:
            return depth_meter
        return depth_meter, {
            "prep_ms": (t1 - t0) * 1000.0,
            "forward_ms": (t2 - t_forward_begin) * 1000.0,
            "post_ms": (t3 - t2) * 1000.0,
            "infer_ms": (t3 - t0) * 1000.0,
        }
